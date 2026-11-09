"""Workspace revision names/versions and selected Dataset editing context.

The existing Curation reader/writer owns selection semantics and identity checks.
Managed revisions reference the original Dataset; prior JSONs are provenance only.
"""
from dataclasses import asdict
from datetime import datetime,timezone
from pathlib import Path
import re,os,fcntl,shutil,tempfile
from . import curation
from .native import DatasetIdentity,DataError,load_catalog,read_json,digest,task_object_ids


def _metadata(document):
    if not isinstance(document,dict):raise DataError('CURATION_INVALID','revision','Revision JSON 객체가 필요합니다.')
    meta=document.get('revision',{})
    if not isinstance(meta,dict):raise DataError('CURATION_INVALID','revision','잘못된 Revision 편집 정보입니다.')
    if 'name'in meta:_label(meta['name'])
    if meta.get('split')not in(None,'train','val'):raise DataError('CURATION_INVALID','revision','잘못된 Split 역할입니다.')
    if 'number'in meta and(type(meta['number'])is not int or meta['number']<1):raise DataError('CURATION_INVALID','revision','잘못된 Revision 번호입니다.')
    return meta


def editor_state(source):
    selection=curation._catalog(source);original=selection
    while original.kind=='curated':original=curation._parent(original)
    meta=_metadata(read_json(selection.root))if selection.kind=='curated'else{}
    return dict(original=original,selection=selection,name=meta.get('name',selection.root.stem if selection.kind=='curated'else None),number=meta.get('number'))


def category(original):return 'lerobot'if original.kind=='lerobot'else original.execution.get('stage','other')


def _label(name):
    if not isinstance(name,str)or not name.strip()or name in('.','..')or any(c in name for c in('/','\\'))or any(ord(c)<32 for c in name):
        raise DataError('CURATION_INVALID','name','폴더 경로 대신 Revision 이름을 입력하세요.')
    return name.strip()


def _directory(workspace,original):
    workspace=Path(workspace).resolve();kind=_label(category(original));name=original.root.name
    expected=workspace/('dataset'if kind=='lerobot'else kind)
    # Resolve ownership from saved revision metadata, not a hash in its label.
    if original.root.parent!=expected:
        base=workspace/'curation'/kind
        for path in base.glob('*/*.json'):
            try:record=read_json(path)
            except (OSError,ValueError):continue
            if record.get('source',{}).get('identity',{}).get('dataset_id')==original.identity.dataset_id:return path.parent
        from scene_contract.naming import available_path
        name=available_path(base,name).name
    folder=workspace/'curation'/kind/name
    if not folder.resolve().is_relative_to(workspace/'curation')or folder.resolve().is_relative_to(original.root):
        raise DataError('OUTPUT_CONFLICT','curation','Revision은 원본 밖의 Workspace curation 경로에 저장해야 합니다.')
    return folder


def list_revisions(workspace,source):
    original=editor_state(source)['original'];root=Path(workspace).resolve()/'curation';rows=[];expected=_directory(workspace,original)
    for path in (root/_label(category(original))).rglob('*.json'):
        if any(part.startswith('.')for part in path.relative_to(root).parts):continue
        if not path.resolve().is_relative_to(root):continue
        belongs=False
        try:
            document=read_json(path);meta=_metadata(document);reference=document.get('source',{})
            if not isinstance(reference,dict)or not isinstance(reference.get('identity'),dict):raise DataError('CURATION_INVALID','source','원본 참조가 없습니다.')
            if reference['identity'].get('dataset_id')!=original.identity.dataset_id:continue
            belongs=True;selection=load_catalog(path)
            rows.append(dict(path=str(path.resolve()),name=meta.get('name',path.stem),number=meta.get('number'),title=(f"{meta['name']}_{meta['split']}_r{meta['number']:03d}"if meta.get('split')else path.stem),
                             episodes=len(selection.episodes),total=len(original.episodes),readable=True,error=''))
        except (OSError,ValueError,TypeError,KeyError)as error:
            if belongs or path.parent==expected or path.parent.parent==expected:rows.append(dict(path=str(path.resolve()),name=path.stem,number=None,title=path.stem,episodes=0,total=len(original.episodes),readable=False,error=str(error)))
    return sorted(rows,key=lambda row:(-int(row['number']or 0),row['title']),reverse=False)


def save_revision(workspace,source,name,*,parent=None,expected_original=None,**selection):
    """Publish one unsplit Dataset or a group of independent train/val Datasets."""
    state=editor_state(source);original=state['original'];selected=state['selection'];name=_label(name)
    if expected_original is not None:original=load_catalog(original.root,expected=DatasetIdentity(**expected_original))
    parent_id=selected.identity.dataset_id if selected.kind=='curated'else None
    if parent is not None:
        previous=editor_state(parent)
        if previous['original'].identity!=original.identity:raise DataError('CURATION_INCOMPATIBLE','parent','다른 원본의 Revision을 이어 저장할 수 없습니다.')
        parent_id=previous['selection'].identity.dataset_id
    folder=_directory(workspace,original);folder.mkdir(parents=True,exist_ok=True)
    pattern=re.compile(re.escape(name)+r'_r(\d+)(?:\.json)?$')
    with (folder/'.revision.lock').open('a+b')as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        number=max((int(match[1])for path in folder.iterdir()if(match:=pattern.fullmatch(path.name))),default=0)+1
        meta=dict(name=name,number=number,created_at=datetime.now(timezone.utc).isoformat(),parent_id=parent_id)
        staging=Path(tempfile.mkdtemp(prefix='.pending-',dir=folder));published=None
        try:
            whole=curation.save_curation(staging/'selection.json',selected,revision=meta,flatten=True,**selection)
            groups={role:ids for role,ids in(whole.splits or{}).items()if ids}
            if not groups:
                path=folder/f'{name}_r{number:03d}.json'
                return {'all':curation.save_curation(path,selected,revision=meta,flatten=True,**selection)}
            ids={ep.selection_id or ep.episode_id for ep in whole.episodes}
            if set(groups)-{'train','val'}or set(id_ for values in groups.values()for id_ in values)!=ids:
                raise DataError('CURATION_INVALID','Split','포함 Episode의 Split을 모두 train 또는 val로 지정하세요. 모두 빈칸이면 일반 Revision으로 저장합니다.')
            for role in('train','val'):
                if role in groups:
                    curation.save_curation(staging/f'{role}.json',whole,order=groups[role],splits={role:groups[role]},revision={**meta,'split':role},flatten=True)
            (staging/'selection.json').unlink()
            target=folder/f'{name}_r{number:03d}'
            if target.exists():raise DataError('OUTPUT_EXISTS',str(target),'new Revision version required')
            os.rename(staging,target);published=target
            return {role:load_catalog(published/f'{role}.json')for role in('train','val')if role in groups}
        except BaseException:
            if published is not None and published.exists():shutil.rmtree(published)
            raise
        finally:
            if staging.exists():shutil.rmtree(staging)


def revision_choices(workspace,path):
    state=editor_state(path);original=state['original'];selected=state['selection']
    descriptor=dict(path=str(original.root),name=original.root.name,category=category(original),readable=True,error='',episodes=len(original.episodes),
                    frames=sum((ep.num_frames if ep.stop is None else ep.stop)-ep.start for ep in original.episodes))
    return dict(path=str(selected.root),original_path=str(original.root),original_identity=asdict(original.identity),original=descriptor,
                revision=dict(name=state['name'],number=state['number'],path=str(selected.root))if selected.kind=='curated'else None,
                revisions=list_revisions(workspace,original))


def editor_catalog(workspace,path):
    """The active Revision is a Dataset containing only its selected Episodes."""
    from .quality import motion_quality
    from .lerobot import recorded_task
    selected=curation._catalog(path)
    inspection=curation.inspect_dataset(selected);quality=motion_quality(selected)
    for row in inspection['episodes']:
        row.update(included=True,edit_range=row['selection_range'],edit_split=row['split']or'',quality=quality[row['selection_id']])
    descriptions=list(dict.fromkeys(recorded_task(selected,ep)for ep in selected.episodes))
    return dict(**revision_choices(workspace,selected),kind=selected.kind,inspection=inspection,task_descriptions=descriptions,
                active_objects=selected.execution.get('active_objects',[]),task_objects=list(task_object_ids(selected.execution)))
