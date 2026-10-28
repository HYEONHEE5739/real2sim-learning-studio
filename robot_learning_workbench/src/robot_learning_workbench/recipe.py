"""Saved declarative Recipe validation/preparation. No engine, device or training loop."""
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from pathlib import Path
from types import MappingProxyType
import hashlib
import json
import math
import yaml


@dataclass(frozen=True)
class Issue:
    field:str
    reason:str
    source:str|None=None
    line:int|None=None


class RecipeError(ValueError):
    def __init__(self,code,field,reason,source=None,line=None):
        self.code=code;self.message=f'{field}: {reason}';self.effect='not_started'
        self.issues=(Issue(field,reason,str(source) if source else None,line),)
        super().__init__(self.message)


def _fail(field,reason,source=None,code='RECIPE_INVALID',line=None):raise RecipeError(code,field,reason,source,line)
def _freeze(v):
    if isinstance(v,Mapping):return MappingProxyType({k:_freeze(x) for k,x in v.items()})
    if isinstance(v,(list,tuple)):return tuple(_freeze(x) for x in v)
    return v

def _plain(v):
    if isinstance(v,Mapping):return {k:_plain(x) for k,x in v.items()}
    if is_dataclass(v):return {f.name:_plain(getattr(v,f.name)) for f in fields(v)}
    if isinstance(v,(list,tuple)):return [_plain(x) for x in v]
    if isinstance(v,Path):return str(v)
    return v

def _bytes(v):return json.dumps(_plain(v),sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def _sha(raw):return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class RecipeSpec:
    schema_version:int
    stage:str
    inputs:Mapping
    execution:Mapping
    output:Mapping
    engine:str|None=None
    objects:Mapping=None
    functions:Mapping=None


@dataclass(frozen=True)
class RecipeDocument:
    path:Path
    raw:bytes
    sha256:str
    base_dir:Path
    spec:RecipeSpec


_SIM={'source','annotation','datagen','simulation_evaluation','real_sim'}
_INPUTS={
 'source':({'scene'},{'device_profile','engine_config','resume_dataset','source_dataset'}),'annotation':({'dataset'},{'scene'}),'datagen':({'scene','dataset'},{'resume_dataset'}),
 'simulation_evaluation':({'scene','policy'},{'engine_config','resume_dataset','policy_contract'}),'real_evaluation':({'policy','device_profile'},{'scene','camera_config','calibration_profile','capture_session','policy_contract'}),
 'train':({'dataset','training_config'},{'policy','checkpoint'}),'offline_validation':({'dataset','policy'},{'policy_contract'}),
 'convert':({'dataset'},{'feature_mapping'}),'merge':({'datasets'},set()),'hub_upload':({'artifact','repo_id'},{'revision'}),
 'hub_download':({'repo_id'},{'revision'}),'capture':({'device_profile','camera_config'},{'calibration_profile','capture_session'}),
 'precision_calibration':({'device_profile'},{'calibration_profile'}),'real_sim':({'scene','device_profile'},{'camera_config','calibration_profile','capture_session'})}
_EXEC={
 'source':({'seed'},{'episodes','num_episodes','resume','env_num','num_envs','headless','episode_time_s','reset_time_s'}),'annotation':({'mode'},{'env_num','num_envs','headless'}),
 'datagen':({'max_attempts','seed'},{'target_successes','num_episodes','resume','env_num','num_envs','headless','max_episode_steps'}),
 'simulation_evaluation':({'episodes','seed'},{'timeout_s','env_num','num_envs','headless','task_instruction'}),
 'real_evaluation':({'episodes'},{'timeout_s','enable_motion','mode','task_instruction'}),'train':({'mode'},set()),
 'offline_validation':(set(),{'batch_size','max_batches'}),'convert':(set(),set()),'merge':(set(),set()),
 'hub_upload':({'repo_type','parent_commit','private','confirm_upload'},set()),'hub_download':({'repo_type'},set()),'capture':(set(),{'episodes','mode'}),
 'precision_calibration':(set(),{'mode'}),'real_sim':(set(),{'headless','mode'})}
_ROLES={'source':{'signals','metrics'},'annotation':{'signals','acceptance','metrics'},
 'datagen':{'signals','acceptance','metrics'},'simulation_evaluation':{'signals','success','metrics'},'real_sim':{'signals','metrics'}}


def _mapping(value,allowed,required,field,path):
    if not isinstance(value,dict):_fail(field,'expected mapping',path)
    for key in value:
        if not isinstance(key,str) or key not in allowed:_fail(field+'.'+str(key),'unknown field',path)
    for key in required:
        if key not in value:_fail(field+'.'+key,'required field',path)


def _declaration(value,field,path):
    _mapping(value,{'function','params'},{'function'},field,path)
    if not isinstance(value['function'],str) or not value['function']:_fail(field+'.function','nonempty registered name required',path)
    if not isinstance(value.get('params',{}),dict):_fail(field+'.params','expected parameter mapping',path)


def _validate(data,path):
    required={'schema_version','stage','inputs','execution','output'}
    _mapping(data,required|{'engine','objects','functions'},required,'recipe',path)
    if type(data['schema_version']) is not int or data['schema_version']!=1:_fail('schema_version','unsupported Schema',path,code='SCHEMA_UNSUPPORTED')
    stage=data['stage']
    if not isinstance(stage,str) or stage not in _INPUTS:_fail('stage','unknown stage',path)
    if stage in _SIM:
        if data.get('engine') not in ('isaaclab','mujoco'):_fail('engine','isaaclab or mujoco required',path)
    elif 'engine' in data:_fail('engine','not used by this stage',path)
    req,opt=_INPUTS[stage];_mapping(data['inputs'],req|opt,req,'inputs',path)
    for key,value in data['inputs'].items():
        values=value if key=='datasets' else [value]
        if not isinstance(values,list) or not values or any(not isinstance(v,str) or not v.strip() for v in values):_fail('inputs.'+key,'nonempty explicit path/ID required',path)
    req,opt=_EXEC[stage];_mapping(data['execution'],req|opt,req,'execution',path)
    for key,value in data['execution'].items():
        where='execution.'+key
        if key in ('episodes','target_successes','max_attempts','env_num','num_envs','num_episodes','batch_size','max_batches','max_episode_steps'):
            if type(value) is not int or value<1:_fail(where,'positive integer required',path)
        elif key=='repo_type':
            if value not in ('dataset','model'):_fail(where,'dataset or model required',path)
        elif key=='parent_commit':
            if not isinstance(value,str) or len(value)!=40 or any(c not in '0123456789abcdef' for c in value):_fail(where,'resolved parent commit required',path)
        elif key=='seed':
            if type(value) is not int or not 0<=value<2**32:_fail(where,'uint32 integer required',path)
        elif key in ('headless','enable_motion','resume','private','confirm_upload'):
            if type(value) is not bool:_fail(where,'boolean required',path)
        elif key in ('timeout_s','episode_time_s','reset_time_s'):
            if type(value) not in (int,float) or not math.isfinite(value) or (value<0 if key=='reset_time_s' else value<=0):_fail(where,'finite valid seconds required',path)
        elif key=='task_instruction':
            if not isinstance(value,str) or not value.strip():_fail(where,'explicit language instruction required',path)
        elif key=='mode':
            if value not in (('manual','auto') if stage=='annotation' else ('offline',) if stage in ('capture','precision_calibration','real_evaluation','real_sim') else ('scratch','finetune','resume')):_fail(where,'unsupported stage mode',path)
    if stage in ('source','datagen'):
        opts=data['execution'];count='episodes' if stage=='source' else 'target_successes'
        if ('num_episodes' in opts)==(count in opts):_fail('execution','Specify exactly one of num_episodes (additional) or '+count+' (legacy cumulative)',path)
        if opts.get('resume') and ('num_episodes' not in opts or 'resume_dataset' in data['inputs']):_fail('execution.resume','Same-path append needs additional num_episodes, without legacy resume_dataset',path)
    if stage=='source' and ('device_profile' in data['inputs'])==('source_dataset' in data['inputs']):_fail('inputs','Choose one approved device_profile or explicit recorded simulation source_dataset',path)
    if 'env_num' in data['execution'] and 'num_envs' in data['execution']:_fail('execution','Use env_num only, not two environment-count names',path)
    _mapping(data['output'],{'directory'}|({'repo_id'} if stage in ('convert','merge') else set()),{'directory'},'output',path)
    if any(not isinstance(v,str) or not v.strip() for v in data['output'].values()):_fail('output','nonempty paths/IDs required',path)
    objects=data.get('objects',{})
    if stage in ('source','datagen','simulation_evaluation'):
        if not isinstance(objects,dict) or (not objects and not (stage=='source' and 'source_dataset' in data['inputs'])):_fail('objects','explicit creation list required',path)
        for name,value in objects.items():
            if not isinstance(name,str) or not name:_fail('objects','nonempty Object ID required',path)
            _mapping(value,{'placement'},{'placement'},'objects.'+name,path);_declaration(value['placement'],'objects.'+name+'.placement',path)
    elif 'objects' in data:_fail('objects','not used; Annotation restores recorded initial state',path)
    if 'functions' in data and stage not in _ROLES:_fail('functions','not used by this stage',path)
    functions=data.get('functions',{})
    _mapping(functions,_ROLES.get(stage,set()),set(),'functions',path)
    for role,value in functions.items():
        if role=='signals':
            if not isinstance(value,dict):_fail('functions.signals','named declarations required',path)
            for signal,decl in value.items():
                if not isinstance(signal,str) or not signal.isidentifier():_fail('functions.signals','signal identifier required',path)
                _declaration(decl,'functions.signals.'+signal,path)
        else:_declaration(value,'functions.'+role,path)
    needed='acceptance' if stage in ('annotation','datagen') else 'success' if stage=='simulation_evaluation' else None
    if needed and needed not in functions:_fail('functions.'+needed,'explicit stage decision required',path)
    return RecipeSpec(1,stage,_freeze(data['inputs']),_freeze(data['execution']),_freeze(data['output']),data.get('engine'),_freeze(objects),_freeze(functions))


def read_recipe(path,*,expected_stage=None):
    path=Path(path).resolve()
    try:raw=path.read_bytes()
    except OSError as exc:raise RecipeError('RECIPE_INVALID','path',str(exc),path) from exc
    return _parse_recipe(path,raw,expected_stage)


def _parse_recipe(path,raw,expected_stage=None):
    class Loader(yaml.SafeLoader):pass
    def mapping(loader,node):
        result={}
        for key_node,value_node in node.value:
            key=loader.construct_object(key_node,deep=True)
            if not isinstance(key,str) or key in result:_fail(str(key),'duplicate/non-string YAML key',path,line=key_node.start_mark.line+1)
            result[key]=loader.construct_object(value_node,deep=True)
        return result
    Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,mapping)
    try:
        if any(isinstance(t,(yaml.tokens.AliasToken,yaml.tokens.AnchorToken)) for t in yaml.scan(raw)):_fail('yaml','anchors/aliases are unsupported',path)
        data=yaml.load(raw,Loader=Loader)
        def check(value,field='recipe'):
            if isinstance(value,dict):
                for key,v in value.items():
                    if isinstance(data,dict) and data.get('stage')=='datagen' and key in ('ik_solver','ik_failure_policy','ik_parameters','ik_identity','ik_configuration','ik_policy_configuration'):_fail(field+'.'+key,'IK is fixed by the system',path)
                    check(v,field+'.'+key)
            elif isinstance(value,list):
                for i,v in enumerate(value):check(v,f'{field}[{i}]')
            elif value is not None and type(value) not in (str,int,float,bool):_fail(field,'only JSON scalar/list/mapping values allowed',path)
            elif type(value) is float and not math.isfinite(value):_fail(field,'nonfinite value',path)
        check(data);spec=_validate(data,path)
        if expected_stage is not None and spec.stage!=expected_stage:_fail('stage','different UI/CLI stage',path)
        return RecipeDocument(path,raw,_sha(raw),path.parent,spec)
    except yaml.YAMLError as exc:
        mark=getattr(exc,'problem_mark',None)
        raise RecipeError('RECIPE_INVALID','yaml',str(exc),path,mark.line+1 if mark else None) from exc


@dataclass(frozen=True)
class FunctionBinding:
    role:str
    name:str
    kind:str
    params:object
    phase:str|None
    request_fields:Mapping
    requires:tuple


@dataclass(frozen=True)
class PreparedRun:
    recipe_sha256:str
    stage:str
    engine:str|None
    resolved_inputs:Mapping
    scene_identity:Mapping|None
    object_order:tuple
    function_bindings:Mapping
    effective_settings:Mapping
    code_identity:str
    output_path:Path
    pending_checks:tuple
    input_documents:Mapping
    scene:object=None
    tasks:object=None

    @property
    def sha256(self):return _sha(_bytes(self.summary()))

    def summary(self):
        return {k:_plain(getattr(self,k)) for k in ('recipe_sha256','stage','engine','resolved_inputs','scene_identity','object_order','function_bindings','effective_settings','code_identity','output_path','pending_checks')}


def _resolve(doc,value):
    path=Path(value)
    return (doc.base_dir/path).resolve() if not path.is_absolute() else path.resolve()


def policy_model_path(path: Path|str) -> Path:
    """Resolve input layout only; official loading and integrity belong to policy.py."""
    root=Path(path).resolve()
    if (root/'workbench-checkpoint.json').is_file():return root/'pretrained_model'
    if (root/'config.json').is_file():return root
    if (root/'pretrained_model/config.json').is_file():return root/'pretrained_model'
    raise RecipeError('INPUT_INVALID','inputs.policy','Select an official Model folder with config.json, model.safetensors and processors, a Workbench checkpoint root with workbench-checkpoint.json/pretrained_model/, or its pretrained_model/ folder. Training Resume also requires training_state/.')


def _artifact(path):
    from .data.native import file_sha256
    if not path.exists():_fail('inputs',f'missing {path}',code='INPUT_MISSING')
    entries={}
    paths=[path] if path.is_file() else sorted(path.rglob('*'))
    for file in paths:
        if file.is_symlink() and not file.is_file():_fail('inputs',f'directory/broken symlink requires explicit resolution: {file}',code='INPUT_INVALID')
        if file.is_file():entries[file.name if path.is_file() else file.relative_to(path).as_posix()]=file_sha256(file)
    return {'path':str(path),'kind':'file' if path.is_file() else 'directory','identity':_sha(_bytes(entries)),'files':entries}


def _official_dataset(path):
    """Pin small official metadata and file sizes, sharing immutable bulk bytes."""
    from .data.native import file_sha256,load_catalog
    load_catalog(path)
    files={p.relative_to(path).as_posix():file_sha256(p) for p in (path/'meta').rglob('*') if p.is_file()}
    if (path/'workbench.json').is_file():files['workbench.json']=file_sha256(path/'workbench.json')
    sizes={p.relative_to(path).as_posix():p.stat().st_size for name in ('data','videos') for p in (path/name).rglob('*') if p.is_file()}
    return {'path':str(path),'kind':'lerobot_dataset','identity':_sha(_bytes({'metadata':files,'sizes':sizes})),'files':files,'bulk_sizes':sizes}


def _json_input(path):
    from .data.native import decode_json
    raw=path.read_bytes();data=decode_json(raw)
    if not isinstance(data,dict):_fail('inputs',f'{path} must contain a JSON object')
    return data,_sha(raw)


def _bind(tasks,scene,stage,engine,selected,role,decl,*,params_extra=None,request_fields=None):
    from .tasks.registry import resolve,validate_params
    kind='tracker' if role.startswith('signals.') else 'placement' if role.startswith('objects.') else 'predicate' if role=='success' else role
    spec=resolve(tasks,decl['function'],kind=kind,stage=stage,engine=engine)
    names={f.name for f in fields(spec.params_type)}
    values={**{k:v for k,v in (params_extra or {}).items() if k in names},**_plain(decl.get('params',{}))}
    params=validate_params(tasks,decl['function'],values,kind=kind,stage=stage,engine=engine,scene=scene,selected_objects=selected)
    default_phase='episode_start' if kind=='placement' else 'episode_end' if kind=='acceptance' else 'pre_step' if kind=='metrics' and stage!='simulation_evaluation' else 'post_step'
    return FunctionBinding(role,decl['function'],kind,params,spec.bindings.get(stage,{}).get('phase',default_phase),_freeze(request_fields or {}),spec.requires)


def _function_bindings(doc,scene,tasks,selected,engine):
    result={};spec=doc.spec
    if (spec.objects or spec.functions) and tasks is None:_fail('functions','explicit Task registry required',doc.path)
    for name,obj in spec.objects.items():
        decl=_plain(obj['placement']);values=decl.setdefault('params',{});request={}
        if values.get('object',name)!=name:_fail('objects.'+name,'parameter object differs from creation ID',doc.path)
        for key,length in (('xy_m',2),('orientation',3)):
            if key not in values:continue
            value=values.pop(key)
            if not isinstance(value,list) or len(value)!=length:_fail('objects.'+name+'.'+key,'invalid request shape',doc.path)
            if key=='xy_m' and any(type(v) not in (int,float) or not math.isfinite(v) for v in value):_fail('objects.'+name+'.xy_m','finite XY metres required',doc.path)
            if key=='orientation':
                import numpy as np
                from scene_contract.transforms import validate_transform
                raw=np.asarray(value)
                if raw.shape!=(3,3) or raw.dtype.kind not in 'fiu':_fail('objects.'+name+'.orientation','numeric rotation matrix required; bool is not an angle/rotation value',doc.path)
                matrix=np.eye(4)
                try:matrix[:3,:3]=raw;validate_transform(matrix)
                except (ValueError,TypeError) as exc:raise RecipeError('RECIPE_INVALID','objects.'+name+'.orientation',str(exc),doc.path) from exc
            request[key]=value
        if decl['function'] in ('placement.fixed_xy','placement.contact_fixed_xy') and 'xy_m' not in request:_fail('objects.'+name+'.xy_m','Fixed XY requires explicit position',doc.path)
        role='objects.'+name+'.placement';result[role]=_bind(tasks,scene,spec.stage,engine,selected,role,decl,params_extra={'object':name},request_fields=request)
    for role,decl in spec.functions.items():
        if role=='signals':
            for name,provider in decl.items():
                key='signals.'+name;result[key]=_bind(tasks,scene,spec.stage,engine,selected,key,provider)
        else:result[role]=_bind(tasks,scene,spec.stage,engine,selected,role,decl)
    # Resolve declared signal providers only. No generic DAG scheduler or phase execution.
    queue=list(result.values())
    while queue:
        binding=queue.pop(0);declaration=tasks.functions[binding.name].bindings.get(spec.stage,{})
        for signal,provider in declaration.get('signals',{}).items():
            key='signals.'+signal;provider_spec=tasks.functions[provider['function']]
            available=_plain(binding.params);names={f.name for f in fields(provider_spec.params_type)}
            values={k:v for k,v in available.items() if k in names};values.update(_plain(provider.get('params',{})))
            candidate=_bind(tasks,scene,spec.stage,engine,selected,key,{'function':provider['function'],'params':values})
            if key in result:
                if result[key].name!=candidate.name or _bytes(result[key].params)!=_bytes(candidate.params):_fail('functions.'+key,'conflicting tracker parameters',doc.path)
            else:result[key]=candidate;queue.append(candidate)
        for required in binding.requires:
            if required.startswith('signals.') and required not in result and required.split('.',1)[1] not in declaration.get('signals',{}):
                _fail('functions.'+binding.role,'missing explicit signal provider '+required,doc.path)
    return _freeze(result)


def prepare_recipe(doc,*,scene=None,tasks=None,inputs=None):
    from scene_contract.package import load_scene
    from .data.native import load_catalog
    spec=doc.spec;resolved={};documents={};dataset=None;catalog=inputs or {}
    for key,value in spec.inputs.items():
        if key in ('repo_id','revision'):
            resolved[key]=_freeze({'kind':'identifier','value':value});continue
        values=value if key=='datasets' else (value,);items=[]
        for item in values:
            pinned=None
            if item.startswith('hf://'):
                pinned=catalog.get(key)
                if (not isinstance(pinned,Mapping) or pinned.get('source_uri')!=item or not isinstance(pinned.get('revision'),str)
                        or len(pinned['revision'])!=40 or any(c not in '0123456789abcdef' for c in pinned['revision'])
                        or not isinstance(pinned.get('path'),str) or not Path(pinned['path']).is_absolute()):
                    _fail('inputs.'+key,'official resolver must supply a pinned local snapshot; no implicit network/cache write',doc.path,code='INPUT_UNRESOLVED')
            path=Path(pinned['path']).resolve() if pinned is not None else _resolve(doc,item)
            if key=='policy':
                folder=policy_model_path(path)
                if folder.name=='pretrained_model' and (folder.parent/'workbench-checkpoint.json').is_file():path=folder.parent
            if key=='scene':
                actual=load_scene(path,expected=scene.identity if scene is not None else None);scene=actual
                identity=_plain(actual.identity);entry={'kind':'scene','path':str(path),'identity':identity}
            elif key in ('dataset','datasets','resume_dataset','source_dataset') and ((path/'run.json').is_file() or (path.is_file() and path.suffix=='.json' and _json_input(path)[0].get('kind')=='curated_native')):
                data=load_catalog(path)
                if spec.stage in ('train','offline_validation'):_fail('inputs.'+key,'explicit exact Native LeRobot materialization required; no episodes= selection fallback',doc.path,code='MATERIALIZATION_REQUIRED')
                if key=='dataset':dataset=data
                entry={'kind':'native_dataset','path':str(data.root),'identity':_plain(data.identity)}
            else:
                if key in ('dataset','datasets'):
                    if spec.stage in ('annotation','datagen') or not path.is_dir() or not (path/'meta/info.json').is_file():
                        _fail('inputs.'+key,'Native recording required for replay; policy inputs require official LeRobot Metadata, with explicit conversion and no retired-format fallback',doc.path,code='INPUT_FORMAT_UNSUPPORTED')
                entry=_official_dataset(path) if (key=='dataset' and spec.stage in ('train','offline_validation') or key=='artifact' and spec.stage=='hub_upload' and spec.execution['repo_type']=='dataset') and (path/'meta/tasks.parquet').is_file() else _artifact(path)
                if path.is_file() and path.suffix=='.json':
                    data,digest=_json_input(path)
                    if entry['files'][path.name]!=digest:_fail('inputs.'+key,'changed during read',doc.path,code='INPUT_CHANGED')
                    if key=='training_config' and isinstance(data.get('policy'),dict) and str(data['policy'].get('type','')).lower() in ('minivla','legacy_minivla'):_fail('inputs.training_config','MiniVLA is excluded',doc.path,code='POLICY_UNSUPPORTED')
                    documents[key]=_freeze(data)
                if key=='policy':
                    folder=policy_model_path(path);config_path=folder/'config.json'
                    config,digest=_json_input(config_path)
                    if entry['files'][config_path.relative_to(path).as_posix()]!=digest:_fail('inputs.policy','changed config',doc.path,code='INPUT_CHANGED')
                    if str(config.get('type','')).lower() in ('minivla','legacy_minivla'):_fail('inputs.policy','MiniVLA is excluded',doc.path,code='POLICY_UNSUPPORTED')
                    documents['policy_config']=_freeze(config)
                if key=='dataset' and spec.stage in ('train','offline_validation') and (not path.is_dir() or not (path/'meta/info.json').is_file()):
                    _fail('inputs.dataset','official Dataset metadata required; legacy inputs need explicit conversion',doc.path)
            if pinned is not None:entry.update(source_uri=item,revision=pinned['revision'],resolution='caller_pinned_snapshot')
            provided=catalog.get(key)
            if provided is not None:
                identity=_plain(getattr(provided,'identity',provided.get('identity',provided) if isinstance(provided,Mapping) else provided))
                if identity!=entry['identity']:_fail('inputs.'+key,'catalog identity differs from saved input',doc.path,code='INPUT_CHANGED')
            items.append(_freeze(entry))
        resolved[key]=tuple(items) if key=='datasets' else items[0]
    if spec.stage=='real_evaluation' and (calibration:=documents.get('device_profile',{}).get('calibration_path')):
        path=Path(calibration)
        if not path.is_absolute():_fail('inputs.device_profile.calibration_path','explicit absolute SDK calibration path required',doc.path)
        resolved['motor_calibration']=_freeze(_artifact(path.resolve()))
    if scene is not None and 'scene' not in resolved:
        scene=load_scene(scene.root/'scene.json',expected=scene.identity)
        resolved['scene']=_freeze({'kind':'scene','path':str(scene.root/'scene.json'),'identity':_plain(scene.identity)})
    expected=None
    if dataset is not None and spec.stage in ('annotation','datagen'):
        if any(e.start!=0 or (e.stop is not None and e.stop!=e.num_frames) for e in dataset.episodes):_fail('inputs.dataset','trimmed training view has no measured initial state at its new first frame',doc.path,code='REPLAY_INITIAL_UNAVAILABLE')
        expected=dataset.execution.get('scene_identity')
        if not expected:_fail('inputs.dataset','recorded Scene identity missing; validated migration required',doc.path,code='SCENE_REVISION_MISSING')
        if scene is None:_fail('inputs.scene','exact recorded Scene package location required',doc.path,code='SCENE_REVISION_MISSING')
        if _plain(scene.identity)!=_plain(expected):_fail('inputs.scene','recorded Revision/hash mismatch',doc.path,code='SCENE_INTEGRITY_MISMATCH')
    engine='isaac' if spec.engine=='isaaclab' else spec.engine
    if spec.stage in _SIM:
        if scene is None:_fail('inputs.scene','Scene package required',doc.path)
        if engine not in scene.scene['engines']:_fail('engine','Scene has no declared engine entry',doc.path,code='SCENE_ENGINE_UNSUPPORTED')
    order=tuple(spec.objects)
    if scene is not None:
        for name in order:
            if name not in scene.scene['objects'] or scene.scene['objects'][name].get('role')!='task_object':_fail('objects.'+name,'unknown/non-task object',doc.path)
    selected=order if order else tuple(dataset.execution.get('active_objects',())) if dataset else ()
    if dataset is not None and spec.stage in ('annotation','datagen') and not selected:_fail('inputs.dataset','recorded object selection missing',doc.path)
    bindings=_function_bindings(doc,scene,tasks,selected,engine)
    output=_resolve(doc,spec.output['directory'])
    if spec.stage=='train':
        config=documents['training_config']
        if bool(config.get('resume',False))!=(spec.execution['mode']=='resume'):_fail('inputs.training_config.resume','differs from saved mode',doc.path,code='INPUT_CONFLICT')
        if spec.execution['mode']=='resume' and 'checkpoint' not in resolved:_fail('inputs.checkpoint','explicit closed local checkpoint required',doc.path,code='RESUME_INCOMPATIBLE')
        if config.get('output_dir') is not None:
            declared=config['output_dir']
            if not isinstance(declared,str) or not Path(declared).is_absolute() or Path(declared).resolve()!=output:_fail('inputs.training_config.output_dir','explicit absolute official output must match Recipe; no silent override',doc.path,code='INPUT_CONFLICT')
        declared_dataset=config.get('dataset',{})
        if isinstance(declared_dataset,Mapping) and declared_dataset.get('root') is not None:
            root=declared_dataset['root']
            if not isinstance(root,str) or not Path(root).is_absolute() or Path(root).resolve()!=Path(resolved['dataset']['path']):_fail('inputs.training_config.dataset.root','official Dataset root differs from Recipe',doc.path,code='INPUT_CONFLICT')
    appending=spec.stage in ('source','datagen') and spec.execution.get('resume',False)
    if appending:
        previous=load_catalog(output)
        if previous.kind!='native' or previous.execution.get('stage')!=spec.stage or previous.execution.get('engine')!=engine:_fail('output.directory','Matching native stage/engine required for append',doc.path,code='RESUME_INCOMPATIBLE')
        resolved['append_dataset']=_freeze({'kind':'native_dataset','path':str(output),'identity':_plain(previous.identity)})
    elif output.exists():_fail('output.directory','new output required; official Trainer resume needs its own validated output policy',doc.path,code='OUTPUT_EXISTS')
    source_files={}
    for entry in resolved.values():
        rows=entry if isinstance(entry,tuple) else (entry,)
        for row in rows:
            if row.get('path'):
                p=Path(row['path'])
                if appending and row is resolved.get('append_dataset'):continue
                if appending and p==output and row.get('kind')=='native_dataset':continue
                if row['kind']=='scene' and output.is_relative_to(p.parent):_fail('output.directory','must not write inside immutable Scene package',doc.path)
                if output==p or output in p.parents or (p.is_dir() and output.is_relative_to(p)):_fail('output.directory','must be separate from all immutable inputs',doc.path)
    if tasks is not None:
        for name,digest in tasks.source_sha256.items():source_files[name]=digest
    code_names=['recipe.py','run.py','cli.py']
    if engine in ('mujoco','isaac') and spec.stage in ('source','annotation','datagen','simulation_evaluation'):
        code_names += ['engines/'+engine+'/'+name+'.py' for name in ('source','annotation','datagen','model','state','control')]
        if spec.stage=='simulation_evaluation':code_names += ['engines/'+engine+'/evaluation.py']
        if engine=='isaac':code_names += ['engines/isaac/env_cfg.py','engines/isaac/mdp.py']
        code_names += ['generation/mimic.py','data/native.py','data/video.py','data/recording.py','data/publication.py','commands.py','tasks/evaluation.py','robot/calibration.py','robot/devices.py','robot/configuration.py','robot/control.py']
        if spec.stage=='simulation_evaluation':code_names += ['learning/policy.py','learning/smol_compat.py']
    if spec.stage in ('train','offline_validation'):code_names += ['learning/train.py','learning/policy.py','learning/validate.py','learning/smol_compat.py','data/lerobot.py']
    if spec.stage in ('hub_download','hub_upload'):code_names += ['learning/hub.py','learning/train.py']
    if spec.stage in ('capture','precision_calibration','real_evaluation','real_sim'):code_names += ['robot/offline.py','robot/control.py','robot/calibration.py','robot/capture.py','robot/devices.py','learning/policy.py','learning/smol_compat.py']
    code_files={str(p):_sha(p.read_bytes()) for name in code_names if (p:=Path(__file__).parent/name).is_file()}
    if spec.stage in ('capture','real_sim','real_evaluation'):
        from .robot.offline import capture_reader
        capture=capture_reader()
        for name in ('capture.py','files.py','scene.py'):
            p=Path(capture.__file__).parent/name;code_files[str(p)]=_sha(p.read_bytes())
    runtime_execution=_plain(spec.execution)
    if 'env_num' in runtime_execution:runtime_execution['num_envs']=runtime_execution['env_num']
    effective={'execution':runtime_execution,'task_modules_sha256':source_files,'code_files':code_files}
    if spec.stage=='datagen':effective['ik_policy_contract']=dict(algorithm='pinocchio_dls',failure_policy='best_effort',parameters=dict(position_weight=1.,orientation_weight=.01,max_iterations=200,tolerance=1e-3,damping=1e-3,step_size=.3),safety=dict(finite=True,joint_limits=True,max_arm_command_jump_rad=.5,jump_reference='previous_applied_command_arm'),runtime_identity_state='requires E06 binding; no solver/model/code identity fabricated')
    pending=[]
    if spec.stage in _SIM:pending.append('engine_binding_and_initial_state_restore')
    if spec.stage=='datagen':pending.append('datagen_ik_runtime_identity')
    if spec.stage=='train':pending.append('official_training_validation')
    if 'policy' in spec.inputs:pending.append('official_policy_processor_validation')
    if any(k in spec.inputs for k in ('device_profile','camera_config','calibration_profile')):pending.append('device_calibration_validation')
    code=_sha(_bytes({'task_sources':sorted(set(source_files.values())),'core_sources':{Path(p).name:h for p,h in code_files.items()}}))
    return PreparedRun(doc.sha256,spec.stage,engine,_freeze(resolved),_freeze(_plain(scene.identity)) if scene else None,order,bindings,_freeze(effective),code,output,tuple(pending),_freeze(documents),scene,tasks)


def verify_prepared_inputs(prepared):
    from scene_contract.package import load_scene,SceneIdentity
    from .data.native import load_catalog,DatasetIdentity
    for value in prepared.resolved_inputs.values():
        for entry in (value if isinstance(value,tuple) else (value,)):
            if entry['kind']=='identifier':continue
            try:
                if entry['kind']=='scene':load_scene(Path(entry['path']),expected=SceneIdentity(**entry['identity']))
                elif entry['kind']=='native_dataset':
                    load_catalog(entry['path'],expected=DatasetIdentity(**entry['identity']))
                elif entry['kind']=='lerobot_dataset':
                    if _official_dataset(Path(entry['path']))['identity']!=entry['identity']:raise ValueError('official metadata or bulk sizes changed')
                elif _artifact(Path(entry['path']))['identity']!=entry['identity']:raise ValueError('file bytes changed')
            except (ValueError,OSError) as exc:raise RecipeError('INPUT_CHANGED','inputs',str(exc)) from exc
    for path,digest in {**prepared.effective_settings['task_modules_sha256'],**prepared.effective_settings['code_files']}.items():
        if _sha(Path(path).read_bytes())!=digest:_fail('functions','Task code changed',code='INPUT_CHANGED')
