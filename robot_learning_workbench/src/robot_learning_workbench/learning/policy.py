"""Official local checkpoint/processor loading and explicit model-radian output.

https://github.com/huggingface/lerobot/blob/v0.4.1/src/lerobot/policies/pretrained.py
"""
from pathlib import Path
import numpy as np
from ..data.native import DataError,DatasetIdentity,atomic_json,read_json,file_sha256,digest,load_catalog
from ..data.lerobot import control_contract,_pinned
from ..robot.calibration import JOINTS


class ActionRejected(ValueError):
    def __init__(self,message,diagnostics):
        super().__init__(message);self.diagnostics=diagnostics


def action_diagnostics(action,*,applied_dtype=None):
    value=np.asarray(action)
    original=[float(x) if np.isfinite(x) else str(x) for x in value.reshape(-1)] if value.dtype.kind in 'fiu' else repr(action)
    return dict(original_action=original,original_shape=list(value.shape),original_dtype=str(value.dtype),
                applied_dtype=str(np.dtype(applied_dtype)) if applied_dtype is not None else None,
                joint_order=list(JOINTS),units='model_rad',command_applied=False,violations=[])


def preflight_action(action,*,limits,applied_dtype,diagnostics=None):
    """Position saturation inside exact limits; invalid Policy output still fails."""
    diagnostic=action_diagnostics(action,applied_dtype=applied_dtype)
    try:
        original=validate_action(action,joint_order=JOINTS,units='model_rad')
        from ..robot.control import checked_target
        payload=checked_target(original,limits=limits,applied_dtype=applied_dtype,diagnostics=diagnostic)
        if diagnostics is not None:diagnostics.update(diagnostic)
        return payload
    except ValueError as error:raise ActionRejected('POLICY_ACTION_UNSAFE: '+str(error),diagnostic) from error


def observation_batch(joints,cameras,*,joint_order,task=None):
    """Official Dataset-equivalent live RGB [0,1] BCHW and pre-step state."""
    import torch
    q=validate_action(joints,joint_order=joint_order,units='model_rad')
    if q.shape!=(6,) or set(cameras)!= {'side','wrist'}:raise ValueError('One measured state and Side/Wrist RGB required')
    batch={'observation.state':torch.from_numpy(q.astype(np.float32)[None])}
    for name,rgb in cameras.items():
        image=np.asarray(rgb)
        if image.shape!=(480,640,3) or image.dtype!=np.uint8:raise ValueError('Live camera requires finite RGB uint8 640x480')
        batch['observation.images.'+name]=torch.from_numpy(image.copy()).permute(2,0,1).unsqueeze(0).float()/255
    if task is not None:
        if not isinstance(task,str) or not task.strip():raise ValueError('Explicit task instruction required')
        batch['task']=[task]
    return batch


def validate_action(action,*,joint_order,units,limits=None):
    if tuple(joint_order)!=JOINTS or units!='model_rad':raise ValueError('Policy output must be absolute SO101 model radians in declared joint order')
    value=np.asarray(action)
    if value.shape[-1:]!=(6,) or value.dtype.kind not in 'fiu' or not np.isfinite(value).all():raise ValueError('Finite six-joint Policy output required')
    if limits is not None:
        bounds=np.asarray(limits)
        if bounds.shape!=(6,2) or not np.isfinite(bounds).all() or np.any(bounds[:,0]>bounds[:,1]):raise ValueError('Finite model limits required')
        from ..robot.control import checked_target
        shape=value.shape;rows=value.reshape(-1,6);dtype=value.dtype if value.dtype.kind=='f' else np.float64
        return np.stack([checked_target(row,limits=bounds,applied_dtype=dtype) for row in rows]).reshape(shape)
    return value.copy()


def checkpoint_record(path: Path|str,*,expected: str|None=None) -> dict:
    root=Path(path).resolve();root=root.parent if root.name=='pretrained_model' else root
    record=read_json(root/'workbench-checkpoint.json')
    if record.get('schema_version')!=1 or record.get('complete') is not True:raise DataError('CHECKPOINT_INCOMPLETE','checkpoint','Closed checkpoint record required')
    if expected is not None and digest(record)!=expected:raise DataError('INPUT_CHANGED','checkpoint','Checkpoint identity differs')
    required={'pretrained_model/model.safetensors','pretrained_model/config.json','pretrained_model/train_config.json','pretrained_model/policy_preprocessor.json','pretrained_model/policy_postprocessor.json','training_state/training_step.json','training_state/optimizer_state.safetensors','training_state/optimizer_param_groups.json','training_state/rng_state.safetensors'}
    if not required<=record.get('files',{}).keys():raise DataError('CHECKPOINT_INCOMPLETE','checkpoint','Essential official files missing from identity')
    for name,sha in record['files'].items():
        p=root/name
        if not p.resolve().is_relative_to(root) or not p.is_file() or file_sha256(p)!=sha:raise DataError('CHECKPOINT_INTEGRITY_MISMATCH',name,'Saved checkpoint bytes changed/missing')
    return record


def seal_checkpoint(path: Path|str,*,dataset,config: dict,recipe_sha256: str,expected_dataset: dict|None=None) -> dict:
    """Called only after official child closes; never append to source checkpoints."""
    root=Path(path);policy=root/'pretrained_model';state=root/'training_state'
    required=[policy/'model.safetensors',policy/'config.json',policy/'train_config.json',policy/'policy_preprocessor.json',policy/'policy_postprocessor.json',state/'training_step.json',state/'optimizer_state.safetensors',state/'optimizer_param_groups.json',state/'rng_state.safetensors']
    if config.get('scheduler') is not None:required.append(state/'scheduler_state.json')
    if any(not p.is_file() for p in required):raise DataError('CHECKPOINT_INCOMPLETE','checkpoint','Official Policy/processor/optimizer/RNG/state files incomplete')
    from safetensors import safe_open
    import torch
    for p in root.rglob('*.safetensors'):
        try:
            with safe_open(p,framework='pt',device='cpu') as tensors:
                if any(not torch.isfinite(tensors.get_tensor(key)).all() for key in tensors.keys()):raise ValueError('Nonfinite checkpoint tensors')
        except Exception as error:raise DataError('CHECKPOINT_INCOMPLETE',str(p),'Invalid/nonfinite official tensor file') from error
    step=read_json(state/'training_step.json')['step']
    saved=read_json(policy/'train_config.json')
    def compare(wanted,actual):
        if isinstance(wanted,dict):return isinstance(actual,dict) and all(key in actual and compare(value,actual[key]) for key,value in wanted.items())
        return wanted==actual
    if not compare(config,saved):raise DataError('CHECKPOINT_INCOMPLETE','config','Official saved configuration differs from declared training request')
    files={p.relative_to(root).as_posix():file_sha256(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink() and p.name!='workbench-checkpoint.json'}
    catalog=load_catalog(dataset,expected=DatasetIdentity(**expected_dataset) if expected_dataset else None)
    record={'schema_version':1,'complete':True,'step':step,'files':files,'dataset_identity':vars(catalog.identity),'dataset_path':str(catalog.root),'control_contract':control_contract(catalog),'config':config,'recipe_sha256':recipe_sha256}
    if config.get('policy',{}).get('type')=='smolvla':
        from .smol_compat import identity
        record['smol_compatibility']=identity()
    atomic_json(root/'workbench-checkpoint.json',record,exclusive=True);return record


def policy_catalog() -> list[dict]:
    """Installed official config registry, without importing optional model weights."""
    from dataclasses import fields
    import draccus
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.factory import make_policy_config
    rows=[]
    for name in sorted(PreTrainedConfig.get_known_choices()):
        try:
            config=make_policy_config(name)
            rows.append({'type':name,'config':draccus.encode(config),
                         'fields':{f.name:str(f.type) for f in fields(config)},'error':None})
        except Exception as error:
            rows.append({'type':name,'config':None,'fields':{},'error':str(error)})
    return rows


def load_policy(path: Path|str,*,expected: str|None=None,device: str='cpu'):
    from ..recipe import policy_directory
    _pinned();folder=policy_directory(path);root=folder.parent if (folder.parent/'workbench-checkpoint.json').is_file() else folder
    if (root/'workbench-checkpoint.json').is_file():
        record=checkpoint_record(root,expected=expected);folder=root/'pretrained_model'
    else:
        required=['config.json','model.safetensors','policy_preprocessor.json','policy_postprocessor.json']
        if any(not (folder/name).is_file() for name in required):raise DataError('CHECKPOINT_INCOMPLETE','policy','Official local model/config/processors required')
        files={p.name:file_sha256(p) for p in folder.iterdir() if p.is_file()}
        if expected is not None and digest(files)!=expected:raise DataError('INPUT_CHANGED','policy','Official artifact identity differs')
        record={'external_official':True,'control_contract':None,'files':files,'step':None}
    config=read_json(folder/'config.json')
    if config.get('type')=='smolvla' and not record.get('external_official'):
        from .smol_compat import identity
        if record.get('smol_compatibility')!=identity():raise DataError('POLICY_INCOMPATIBLE','smol_compatibility','Pinned loss patch identity differs or missing')
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.factory import make_pre_post_processors,get_policy_class
    cfg=PreTrainedConfig.from_pretrained(folder,local_files_only=True)
    # Official config argument avoids redundant backbone downloads; all trained
    # parameters are then restored from the local model.safetensors.
    if config['type']=='smolvla':
        from .smol_compat import enable
        enable()
        cfg.load_vlm_weights=False
    if hasattr(cfg,'pretrained_backbone_weights'):cfg.pretrained_backbone_weights=None
    policy_class=get_policy_class(config['type'])
    policy=policy_class.from_pretrained(folder,config=cfg,local_files_only=True);policy.to(device).eval();policy.reset()
    contract=record.get('control_contract')
    if contract:
        expected_features={'observation.state':(6,)}
        expected_features.update({'observation.images.'+name:(shape['shape'][2],shape['shape'][0],shape['shape'][1]) for name,shape in contract['cameras'].items()})
        if {k:tuple(v.shape) for k,v in policy.config.input_features.items()}!=expected_features or tuple(policy.config.output_features['action'].shape)!=(6,):raise DataError('POLICY_INCOMPATIBLE','features','Checkpoint model and recorded Dataset features differ')
    pre,post=make_pre_post_processors(policy_cfg=policy.config,pretrained_path=folder,preprocessor_overrides={'device_processor':{'device':device}})
    return policy,pre,post,record


def predict(policy,pre,post,batch: dict):
    """Official inference without granting any robot command binding."""
    import torch
    with torch.inference_mode():action=post(policy.select_action(pre(batch)))
    result=action.detach().cpu().numpy()
    if result.ndim!=2 or result.dtype.kind not in 'fiu' or not np.isfinite(result).all():raise ValueError('Finite batched official Policy output required')
    return result


def infer(policy,pre,post,batch: dict,*,contract: dict,limits=None):
    if contract is None:raise ValueError('Explicit Policy control contract required')
    result=predict(policy,pre,post,batch)
    try:return validate_action(result,joint_order=contract['joint_order'],units='model_rad',limits=limits)
    except ValueError as error:raise ActionRejected(str(error),action_diagnostics(result)) from error


def policy_inputs(plan,urdf_sha256):
    """Explicit live IO binding; external official Policies need no owned manifest."""
    from ..recipe import _plain
    policy,pre,post,record=load_policy(plan.resolved_inputs['policy']['path'],device='cpu')
    if (hasattr(policy.config,'tokenizer_max_length') or hasattr(policy.config,'vlm_model_name') or hasattr(policy.config,'tokenizer_assets_repo')) and not plan.effective_settings['execution'].get('task_instruction'):raise DataError('POLICY_INCOMPATIBLE','task_instruction','Language-conditioned Policy needs explicit instruction')
    contract=record.get('control_contract') or _plain(plan.input_documents.get('policy_contract'))
    expected=dict(schema_version=1,scene_identity=_plain(plan.scene_identity),calibration_sha256=digest(_plain(plan.scene.calibration)),robot_model_sha256=urdf_sha256,
        joint_order=list(JOINTS),pose_frame='robot_base',control_hz=30,policy_tensor_dtype='float32',
        observation=dict(source='obs/policy/joint_pos',phase='pre_step',meaning='measured_model_joint_position',units=['rad']*6),
        action=dict(source='joint_targets',phase='command_for_step_t',meaning='absolute_model_joint_position_target',units=['rad']*6),
        cameras={n:dict(color='rgb',fps=30.,shape=[480,640,3]) for n in ('side','wrist')})
    if contract and 'command_processing' in contract:expected['command_processing']={'position_target_policy':'saturation_inward_v1','training_target':'applied'}
    if contract!=expected:raise DataError('POLICY_INCOMPATIBLE','policy','Explicit Scene/model/Calibration/joint/unit/phase/camera contract mismatch')
    features={'observation.state':(6,),**{'observation.images.'+n:(3,480,640) for n in ('side','wrist')}}
    if {k:tuple(v.shape) for k,v in policy.config.input_features.items()}!=features or tuple(policy.config.output_features['action'].shape)!=(6,):raise DataError('POLICY_INCOMPATIBLE','features','Policy features differ from actual live inputs')
    return policy,pre,post,record,contract

