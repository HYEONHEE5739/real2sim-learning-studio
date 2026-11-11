"""Use the existing owned-child boundary for configured stage runtimes."""
from pathlib import Path
import os
import subprocess
import sys
from contextlib import contextmanager, nullcontext
from .files import read, sha
from .stage_artifacts import StageNeeds


RUNTIME_KEYS = {'blender':'blender', 'video': 'preparation', 'da3': 'da3', 'support': 'sam3', 'segments': 'sam3', 'vlm': 'vlm',
                'support_masks':'sam3', 'support_planes':'pose', 'segments_raw':'sam3', 'segments_post':'decomposition',
                'image_edit_removal':'image_edit_removal','image_edit_objects':'image_edit_objects',
                'image_edit': 'image_edit', 'background_remove':'rembg', 'removal': 'decomposition',
                'depth_inpaint': 'prior_depth', 'cpd': 'pose',
                'canonicalize':'pose', 'front_views':'pose', 'foundationpose': 'foundationpose', 'articulation': 'articulation',
                'physics': 'physics', 'simulator': 'simulator'}


def validate_configuration(configuration):
    """Reject credentials before any Candidate/request/identity is persisted."""
    runtimes=configuration.get('runtimes',{})
    if not isinstance(runtimes,dict):raise ValueError('Runtime settings mapping required')
    def contains_secret(node):
        if isinstance(node,dict):return bool({str(k).lower()for k in node}&{'token','api_key','password','authorization','credentials'})or any(contains_secret(v)for v in node.values())
        if isinstance(node,list):return any(contains_secret(v)for v in node)
        return False
    if contains_secret(runtimes):raise ValueError('Runtime credentials must use the provider environment')
    import math
    for spec in runtimes.values():
        if not isinstance(spec,dict):raise ValueError('Runtime settings mapping required')
        timeout=spec.get('timeout_s',900)
        if type(timeout)not in(int,float)or not math.isfinite(timeout)or not 1<=timeout<=3600:
            raise ValueError('Finite bounded Runtime deadline 1..3600 seconds required')
        minimum=spec.get('minimum_free_mib',1)
        if type(minimum)not in(int,float)or not math.isfinite(minimum)or minimum<=0:
            raise ValueError('Finite positive minimum_free_mib required')


def workspace_configuration(project, configuration):
    """Fill missing installation keys from Workspace; never import another Scene.

    The Workspace file holds runtimes only. Project/explicit settings win, including
    explicit None/disabled values; nested model_options are merged by key.
    """
    import copy
    result=copy.deepcopy(configuration)
    path=project.root.parent.parent/'runtime/reconstruction.yaml'
    if not path.is_file():return result
    saved=read(path)
    if not isinstance(saved,dict)or set(saved)!={'runtimes'}:
        raise ValueError('Workspace reconstruction settings must contain runtimes only')
    validate_configuration(saved)
    def merge(defaults, selected):
        merged=copy.deepcopy(defaults)
        for key,value in selected.items():
            merged[key]=merge(merged[key],value)if isinstance(merged.get(key),dict)and isinstance(value,dict)else copy.deepcopy(value)
        return merged
    result['runtimes']=merge(saved['runtimes'],result.get('runtimes',{}))
    validate_configuration(result)
    return result


@contextmanager
def runtime_environment(configuration):
    """Scope the existing Blender selector to an explicit installation setting."""
    executable=configuration.get('runtimes',{}).get('blender',{}).get('executable')
    if not executable:
        yield;return
    path=Path(executable).expanduser()
    if not path.is_file()or not os.access(path,os.X_OK):raise StageNeeds('NEEDS_RUNTIME','Configured Blender executable is unavailable')
    previous=os.environ.get('REAL2SIM_BLENDER')
    os.environ['REAL2SIM_BLENDER']=str(path.resolve())
    try:yield
    finally:
        if previous is None:os.environ.pop('REAL2SIM_BLENDER',None)
        else:os.environ['REAL2SIM_BLENDER']=previous


def runtime_key(configuration, operation, request=None):
    """Optional Stage5/6 backend overrides; existing image_edit remains fallback."""
    if operation=='image_edit'and request and request.get('image_edit_role'):
        role=request['image_edit_role']
        if role not in ('removal','objects'):raise ValueError('Unknown image edit stage role')
        operation='image_edit_'+role
    if operation in ('image_edit_removal','image_edit_objects'):
        return operation if operation in configuration.get('runtimes',{})else'image_edit'
    return RUNTIME_KEYS[operation]


def identity(configuration, operation):
    validate_configuration(configuration)
    if operation=='vlm':
        from . import codex_cli,authoring
        model=os.environ.get('REAL2SIM_CODEX_MODEL');effort=os.environ.get('REAL2SIM_CODEX_EFFORT')or None
        return {'kind':'real','operation':'vlm','provider':'codex','model':model,'reasoning_effort':effort,
            'capability':codex_cli.model_metadata(model),'contract':codex_cli.VISUAL_POLICY_VERSION,'disabled_features':list(codex_cli.VISUAL_DISABLED_FEATURES),
            'visual_policy_sha256':__import__('hashlib').sha256(authoring.visual_policy(authoring._codex_guidance()[0]).encode()).hexdigest(),
            'guide_sha256':authoring._codex_guidance()[1]['sha256']}
    spec = configuration.get('runtimes', {}).get(runtime_key(configuration,operation), {})
    if operation == 'video' and not spec:spec = {'python': sys.executable}
    result = {'kind': 'real', 'operation': operation, 'settings': spec,
              'worker_sha256': sha(Path(__file__).with_name('stage_workers.py'))}
    files = {}
    for key in ('python', 'executable', 'model', 'source', 'simfoundry_source', 'workflow', 'models'):
        if not spec.get(key):continue
        path = Path(spec[key]).expanduser()
        if path.is_dir():
            paths = sorted(p for p in path.rglob('*') if p.suffix in ('.safetensors', '.json', '.pt', '.pth', '.py', '.yaml', '.yml', '.gguf'))
        else:
            paths = [path] if path.is_file() else []
        for file in paths:
            files[str(file.resolve())] = sha(file)
    if operation in ('support','segments'):
        post='support_planes'if operation=='support'else'segments_post'
        result['postprocessing']=identity(configuration,post)
    result['adapter_sha256']={name:sha(Path(__file__).with_name(name)) for name in ('sam31_adapter.py','comfy_edit.py')}
    result['files'] = files
    if operation=='canonicalize':result['visual_runtime']=identity(configuration,'vlm')
    return result


@contextmanager
def _gpu_slot(project, timeout):
    """Serialize Builder model children across projects; no resident model service."""
    import fcntl
    import tempfile
    import time
    path=Path(tempfile.gettempdir())/('real2sim-gpu-'+str(os.getuid())+'.lock')
    deadline=time.monotonic()+timeout
    with path.open('a')as stream:
        while True:
            project.checkpoint()
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>deadline:raise StageNeeds('NEEDS_RUNTIME','Another Builder GPU child owns the device')
                time.sleep(.1)
        try:yield
        finally:fcntl.flock(stream,fcntl.LOCK_UN)


def invoke(candidate, configuration, operation, request, folder, *, provider=None):
    from .inference import _run_worker
    validate_configuration(configuration)
    if operation=='vlm':
        from .authoring import run_codex_vlm
        legacy=configuration.get('runtimes',{}).get('vlm',{})
        if legacy and legacy.get('provider')!='codex':
            raise StageNeeds('NEEDS_RUNTIME','LEGACY_VLM_CONFIG: replace runtimes.vlm with {provider: codex}; existing paths/records are preserved',code='LEGACY_VLM_CONFIG')
        if set(legacy)-{'provider','timeout_s'}:
            raise StageNeeds('NEEDS_RUNTIME','LEGACY_VLM_CONFIG: remove Gemini-only VLM settings explicitly; use the shared Codex UI selection',code='LEGACY_VLM_CONFIG')
        try:return run_codex_vlm(candidate,request,folder,timeout_s=legacy.get('timeout_s',900))
        except Exception as error:
            if isinstance(error,InterruptedError):raise
            if isinstance(error,StageNeeds):raise
            if getattr(error,'code',None):raise StageNeeds('NEEDS_RUNTIME','Codex '+error.code+'; switch account or resume in the existing UI',code=error.code)from None
            if isinstance(error,(OSError,RuntimeError)):
                raise StageNeeds('NEEDS_RUNTIME','Codex CLI unavailable or timed out; completed stage artifacts retained')from None
            raise
    if operation=='canonicalize':
        import numpy as np
        from .calibration.canonicalization import yaw_to_target_rotation
        from .reconstruction_stages import typed_record
        run=provider or(lambda op,req,out:invoke(candidate,configuration,op,req,out))
        out=Path(folder);azimuth=None;judgments=[]
        for phase in ('coarse','fine')if request.get('refine')else('coarse',):
            views=run('front_views',{**request,'coarse_azimuth':azimuth},out/phase/'renders')
            labels=[v['label']for v in views['views']]
            schema=typed_record({'choice':{'type':'string','enum':labels+['NONE']},'uncertain':{'type':'boolean'},
                'reason':{'type':'string'},'evidence':{'type':'array','items':{'type':'string'},'minItems':1}})
            answer=run('vlm',{'images':[v['path']for v in views['views']]+([request['photo']]if request.get('photo')else[]),
                'task':'semantic_front','response_schema':schema,'context':request,
                'prompt':'Choose the semantic front view of '+str(request.get('category'))+'. Labels in image order: '+str(labels)+
                '. NONE means no meaningful front. Report uncertainty; do not infer a metric pose.'},out/phase/'judgment')['answer']
            judgments.append(answer)
            if answer['uncertain']or answer['choice']=='NONE':
                return {'rotation':np.eye(3).tolist(),'front':{'status':'ambiguous','judgments':judgments},'semantic_front_verified':False}
            azimuth=next(v['azimuth_deg']for v in views['views']if v['label']==answer['choice'])
        C=np.array([[1.,0,0],[0,0,1],[0,-1,0]])
        return {'rotation':(C.T@yaw_to_target_rotation(azimuth)@C).tolist(),
            'front':{'status':'rotated','front_azimuth_deg':azimuth,'judgments':judgments},'semantic_front_verified':False}
    if operation in ('support','segments'):
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        raw_kind='support_masks'if operation=='support'else'segments_raw'
        post_kind='support_planes'if operation=='support'else'segments_post'
        # The existing provider caches each completed child independently, so a
        # missing CPU dependency on Resume cannot force another SAM Forward.
        run=provider or (lambda op,req,out:invoke(candidate,configuration,op,req,out))
        sam=run(raw_kind,request,folder/'sam31')
        return run(post_kind,{**request,'sam_result':sam},folder/'cpu')
    key = runtime_key(configuration,operation,request)
    spec = configuration.get('runtimes', {}).get(key, {})
    if operation=='image_edit'and spec.get('provider')=='gemini':
        raise StageNeeds('NEEDS_RUNTIME','LEGACY_IMAGE_PROVIDER: configure local FLUX explicitly; Codex performs visual judgment, not RGB generation',code='LEGACY_IMAGE_PROVIDER')
    if operation == 'video' and not spec:spec = {'python': sys.executable}
    python = Path(spec.get('python', '')).expanduser()
    if not python.is_file() or not os.access(python, os.X_OK):
        raise StageNeeds('NEEDS_RUNTIME', key+': configure an existing Python runtime')
    if operation in ('support_masks','segments_raw','depth_inpaint') or (operation=='image_edit'and spec.get('provider','comfy_gguf')in('comfy_gguf','flux')and request.get('task')!='describe'):
        floor=5120 if operation=='depth_inpaint'else 6144 if operation=='image_edit'else 4096
        minimum=max(floor,float(spec.get('minimum_free_mib',floor)))
        try:free=float(subprocess.check_output(['nvidia-smi','--query-gpu=memory.free','--format=csv,noheader,nounits'],text=True).splitlines()[0])
        except (OSError,subprocess.CalledProcessError,ValueError):raise StageNeeds('NEEDS_RUNTIME','Cannot verify available CUDA VRAM')from None
        if free<minimum:raise StageNeeds('NEEDS_RUNTIME',key+': insufficient free VRAM; no worker launched')
    if operation == 'da3':
        n, res = len(request['images']), request['process_res']
        if n > 8 or res not in (336, 448) or (res == 448 and n > 4):
            raise StageNeeds('NEEDS_MORE_DATA', 'Unmeasured DA3 frame/resolution budget; use overlap chunks')
        try:
            free = float(subprocess.check_output(['nvidia-smi', '--query-gpu=memory.free',
                                                   '--format=csv,noheader,nounits'], text=True).splitlines()[0])
        except (OSError, subprocess.CalledProcessError, ValueError):
            raise StageNeeds('NEEDS_RUNTIME', 'Cannot verify available CUDA VRAM') from None
        minimum = 6656 if n > 4 else 6400 if res == 448 else 5120
        if free < max(minimum, float(spec.get('minimum_free_mib', minimum))):
            raise StageNeeds('NEEDS_RUNTIME', 'Insufficient free VRAM for the configured DA3 trial')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    payload = {**request, 'output': str(folder.resolve()),
               **{k: spec[k] for k in ('source', 'model', 'simfoundry_source', 'model_options', 'provider', 'workflow', 'models') if k in spec}}
    uses_gpu=operation in ('da3','support_masks','segments_raw','depth_inpaint','foundationpose','physics','simulator')or(operation=='image_edit'and spec.get('provider','comfy_gguf')in('comfy_gguf','flux')and request.get('task')!='describe')
    try:
        with _gpu_slot(candidate.project,float(spec.get('timeout_s',900)))if uses_gpu else nullcontext():
            _run_worker(candidate.project, python, operation, payload, folder,
                        float(spec.get('timeout_s', 900)), entrypoint=Path(__file__).with_name('stage_workers.py'))
    except InterruptedError:
        raise
    except RuntimeError:
        path = folder/'result.json'
        if path.is_file():
            result=read(path);error=result.get('error',{});code=error.get('code')
            if result.get('status')=='NEEDS_RUNTIME':
                raise StageNeeds('NEEDS_RUNTIME',key+': configured local dependency/service is unavailable',code=code)from None
            if code=='VRAM_OUT_OF_MEMORY':raise StageNeeds('NEEDS_RUNTIME',key+': CUDA OOM; child exited; reduce the configured batch budget',code=code)from None
        raise
    result = read(folder/'result.json')
    if result.get('execution') != 'real' or result.get('status') != 'COMPLETE':
        raise ValueError('Invalid actual stage worker result')
    return result['data']
