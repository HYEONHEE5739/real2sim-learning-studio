"""Explicit official Hub operations; auth remains in the existing HF credential store.

https://huggingface.co/docs/huggingface_hub/v0.35.3/guides/download
https://huggingface.co/docs/huggingface_hub/v0.35.3/guides/upload
"""
from pathlib import Path
from huggingface_hub import HfApi,snapshot_download
from huggingface_hub.utils import validate_repo_id
from ..data.native import DataError,atomic_json


def api():return HfApi()


def validate(repo_id,repo_type,revision):
    validate_repo_id(repo_id)
    if repo_type not in ('model','dataset') or not isinstance(revision,str) or not revision.strip():
        raise DataError('HUB_INPUT_INVALID','hub','Explicit model/dataset type and revision required')


def resolve(repo_id: str,repo_type: str,revision: str) -> dict:
    validate(repo_id,repo_type,revision)
    info=api().repo_info(repo_id,repo_type=repo_type,revision=revision)
    if len(info.sha)!=40 or any(c not in '0123456789abcdef' for c in info.sha):raise ValueError('Hub did not return a pinned commit')
    return dict(repo_id=repo_id,repo_type=repo_type,revision=revision,commit=info.sha,private=info.private)


def download(resolved: dict) -> str:
    commit=resolved['commit'];validate(resolved['repo_id'],resolved['repo_type'],commit)
    if len(commit)!=40 or any(c not in '0123456789abcdef' for c in commit):raise ValueError('Resolve revision before download')
    # Official cache owns immutable blobs. No second full copy into Workspace.
    return snapshot_download(repo_id=resolved['repo_id'],repo_type=resolved['repo_type'],revision=commit)


def upload(folder: Path,repo_id: str,repo_type: str,*,parent: str,private: bool,confirm: bool,revision: str='main') -> dict:
    validate(repo_id,repo_type,revision)
    if confirm is not True or type(private) is not bool or len(parent)!=40:raise ValueError('Explicit upload confirmation, visibility and existing parent commit required')
    root=Path(folder).resolve()
    if not root.is_dir():raise ValueError('Explicit local artifact directory required')
    # Never upload workstation credentials/caches or a complete Workspace by accident.
    blob_root=root.parent.parent/'blobs' if root.parent.name=='snapshots' and len(root.name)==40 and root.parent.parent.name.startswith(('models--','datasets--')) else None
    for path in root.rglob('*'):
        if path.is_symlink() and (not path.is_file() or not (path.resolve().is_relative_to(root) or blob_root is not None and path.resolve().is_relative_to(blob_root))):raise ValueError('Artifact symlink escapes approved files/cache blobs')
    forbidden={'.git','.env','.netrc','.git-credentials','.cache','.ssh','token','stored_tokens'}
    if any(p.name in forbidden or p.suffix.lower() in ('.pem','.key') for p in root.rglob('*')):raise ValueError('Credential/cache files are not publishable artifacts')
    if repo_type=='dataset' and not (root/'meta/info.json').is_file():raise ValueError('Official LeRobot Dataset artifact required')
    if repo_type=='model' and not all((root/n).is_file() for n in ('config.json','model.safetensors','policy_preprocessor.json','policy_postprocessor.json')):raise ValueError('Official Policy and processors required')
    current=resolve(repo_id,repo_type,revision)
    if current['commit']!=parent or current['private']!=private:raise DataError('HUB_CONFLICT','revision','Remote parent/visibility changed; resolve and review again')
    result=api().upload_folder(repo_id=repo_id,repo_type=repo_type,folder_path=root,revision=revision,parent_commit=parent,commit_message='Workbench explicit artifact publication')
    return dict(repo_id=repo_id,repo_type=repo_type,commit=result.oid,url=result.commit_url,private=private)


def run(plan,*,events,commands):
    """R03 owns the attempt; a bounded child owns the explicit network operation."""
    import os,sys,json,time,subprocess
    from ..recipe import verify_prepared_inputs,_plain
    from ..run import StageResult
    from .train import stop_child
    verify_prepared_inputs(plan)
    if plan.output_path.exists():raise ValueError('New Hub receipt output required')
    opts=_plain(plan.effective_settings['execution']);inputs=plan.resolved_inputs
    payload=dict(operation=plan.stage,repo_id=inputs['repo_id']['value'],repo_type=opts['repo_type'],revision=inputs.get('revision',{}).get('value','main'))
    if plan.stage=='hub_upload':
        if opts.get('confirm_upload') is not True:raise ValueError('Explicit upload confirmation required')
        payload.update(folder=inputs['artifact']['path'],parent=opts['parent_commit'],private=opts['private'],confirm=True)
    else:
        revision=payload['revision']
        if len(revision)!=40 or any(c not in '0123456789abcdef' for c in revision):raise ValueError('Resolve and save a commit before downloading')
    env=os.environ.copy();env.update(HF_HUB_OFFLINE='0',HF_DATASETS_OFFLINE='0')
    log=plan.output_path.with_name(plan.output_path.name+'.hub.log');result_file=plan.output_path.with_name(plan.output_path.name+'.hub-result.json')
    payload['result_file']=str(result_file);cancelled=False
    with log.open('xb') as stream:
        child=subprocess.Popen([sys.executable,'-B','-m',__name__],stdin=subprocess.PIPE,stdout=stream,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        try:
            child.stdin.write(json.dumps(payload).encode());child.stdin.close()
            while child.poll() is None:
                for cmd in commands():
                    if cmd['kind']=='cancel':
                        cancelled=True;events({'kind':'command_ack','payload':{'command_id':cmd['command_id'],'status':'completed'}})
                if cancelled:break
                time.sleep(.1)
            code=stop_child(child) if cancelled else child.wait()
        finally:
            if child.poll() is None:stop_child(child)
    if cancelled:return StageResult('cancelled',(),0,{'remote_effect':'unknown' if plan.stage=='hub_upload' else 'not_uploaded','cache_may_be_partial':True})
    if code:raise DataError('HUB_OPERATION_FAILED','hub',f'Official Hub child exit {code}; see {log}',effect='unknown' if plan.stage=='hub_upload' else 'not_applied')
    from ..data.native import read_json
    result=read_json(result_file);plan.output_path.mkdir();atomic_json(plan.output_path/'hub-result.json',result)
    result_file.unlink()
    return StageResult('completed',(str(plan.output_path/'hub-result.json'),),0,result)


def main():
    import json,sys
    request=json.load(sys.stdin);output=Path(request.pop('result_file'));operation=request.pop('operation')
    if operation=='hub_upload':result=upload(**request)
    else:
        result=resolve(**request);result['path']=download(result)
    atomic_json(output,result,exclusive=True)


if __name__=='__main__':main()
