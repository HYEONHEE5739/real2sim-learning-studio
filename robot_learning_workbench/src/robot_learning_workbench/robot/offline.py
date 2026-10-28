"""Inspect preserved device/Capture/Policy inputs through R03; never open devices.

Live collection, measured Calibration and real rollout are separate hardware gates.
Reports contain diagnostics/references, not another Capture or Dataset format.
"""
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING
import numpy as np
from ..data.native import DataError,atomic_json
from .calibration import JOINTS,PrecisionMapper,load_profile,review_joint,mapper_from_scene
if TYPE_CHECKING:
    from lerobot.robots.so101_follower.config_so101_follower import SO101FollowerConfig


def capture_module() -> ModuleType:
    """Builder owns Capture schemas; report the optional dependency explicitly."""
    from importlib import import_module
    try:return import_module('real2sim_builder.capture')
    except ImportError as exc:
        raise DataError('STAGE_DEPENDENCY_MISSING','offline','Install the offline extra in the backend environment; Builder Capture dependency unavailable: '+str(exc)) from exc


def sdk_configuration(spec):
    """Validate official constructor config, without constructing a serial SDK bus."""
    role=spec.get('role')
    if role=='leader':
        from lerobot.teleoperators.so101_leader.config_so101_leader import SO101LeaderConfig
        cls=SO101LeaderConfig
    elif role=='follower':
        from lerobot.robots.so101_follower.config_so101_follower import SO101FollowerConfig
        cls=SO101FollowerConfig
    else:raise ValueError('Explicit leader/follower role required')
    cfg=cls(**dict(spec['sdk']))
    if not cfg.use_degrees:raise ValueError('Precision mapping requires degree-native SDK config')
    if role=='follower' and (cfg.cameras or cfg.max_relative_target is not None or not cfg.disable_torque_on_disconnect):raise ValueError('Explicit camera ownership, no SDK target limiter, release-on-disconnect required')
    return cfg


def capture_binding(manifest,scene,calibration_id):
    """Return explicit unbound reasons; historical model changes need evidence."""
    reasons=[]
    if manifest.get('joint_names')!=list(JOINTS) or manifest.get('joint_units')!=['rad']*6:reasons.append('Capture requires declared six-joint model-radian coordinates')
    if scene is None or not calibration_id:return reasons+['Explicit Scene/device_observation calibration binding missing']
    from ..recipe import _plain
    from ..data.native import digest
    if manifest.get('scene_identity')!=_plain(scene.identity) or manifest.get('calibration_sha256')!=digest(_plain(scene.calibration)):
        reasons.append('Capture camera/Scene Calibration identity is not explicitly bound')
    mapper=mapper_from_scene(scene,calibration_id,role='follower',phase='device_observation')
    if manifest.get('source_robot_sha256')!=mapper.profile['urdf_sha256'] or manifest.get('joint_mapping',{}).get('sha256')!=mapper.metadata()['sha256']:
        reasons.append('Historical Capture model/mapping differs; approved rebinding/equivalence evidence required')
    return reasons


def encoder_preflight(action: np.ndarray, *, mapper: PrecisionMapper, model_path: Path|str, calibration_path: Path|str, cfg: 'SO101FollowerConfig') -> dict:
    """Use official CPU-only normalization and existing Follower checks; never IO.

    Feetech's serial constructor is deliberately NOT called. The official base
    initializer supplies only motor/calibration tables for its pure math methods.
    """
    import hashlib,json
    from types import SimpleNamespace
    from lerobot.motors import Motor,MotorCalibration,MotorNormMode
    from lerobot.motors.motors_bus import MotorsBus
    from lerobot.motors.feetech.feetech import FeetechMotorsBus
    from .calibration import joint_specs
    from .devices import Follower
    from .control import position_target
    profile=mapper.profile;identity=profile['identity']
    if hashlib.sha256(Path(model_path).read_bytes()).hexdigest()!=profile['urdf_sha256']:raise ValueError('Command mapping execution model identity differs')
    raw=Path(calibration_path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=identity['calibration_sha256']:raise ValueError('Motor calibration file identity changed')
    expected={n:{'id':i+1,'model':'sts3215'} for i,n in enumerate(JOINTS)}
    if identity['motors']!=expected:raise ValueError('Expected official SO101 Follower motor identity')
    calibration=json.loads(raw)
    if set(calibration)!=set(JOINTS):raise ValueError('Expected six SDK motor calibration records')
    for n,c in calibration.items():
        if set(c)!={'id','drive_mode','homing_offset','range_min','range_max'} or any(type(v)is not int for v in c.values()):raise ValueError('Invalid SDK integer motor calibration')
        if c['id']!=expected[n]['id'] or c['drive_mode'] not in (0,1) or not 0<=c['range_min']<c['range_max']<4096:raise ValueError('Invalid SDK motor ID/range')
    motors={n:Motor(i+1,'sts3215',MotorNormMode.RANGE_0_100 if n=='gripper' else MotorNormMode.DEGREES) for i,n in enumerate(JOINTS)}
    bus=object.__new__(FeetechMotorsBus)
    MotorsBus.__init__(bus,cfg.port,motors,{n:MotorCalibration(**c) for n,c in calibration.items()})
    follower=Follower(SimpleNamespace(id=cfg.id,bus=bus),profile=profile,identity=identity,calibration_path=calibration_path,model_hash=profile['urdf_sha256'])
    follower._check_identity()  # Pure identity/motor-spec checks, no register reads.
    low=bus._normalize({c.id:c.range_min for c in bus.calibration.values()})
    high=bus._normalize({c.id:c.range_max for c in bus.calibration.values()})
    follower.limits={n:sorted((low[m.id],high[m.id])) for n,m in motors.items()}
    bounds={n:s['limits'] for n,s in joint_specs(model_path).items()}
    _,native,diagnostics=position_target(action,follower=follower,model_bounds=bounds)
    return {'native_target':native,'sdk_goal_raw':follower.last_encoded_goal_raw,'command_preflight':diagnostics}


def run(plan,*,events,commands):
    opts=plan.effective_settings['execution']
    if opts.get('mode')!='offline' or opts.get('enable_motion'):raise DataError('HARDWARE_NOT_APPROVED','execution','Only explicit offline inspection is enabled; no port, torque or camera access')
    capture=capture_module() if plan.stage in ('capture','real_sim','real_evaluation') else None
    from ..recipe import verify_prepared_inputs,_plain
    from ..run import StageResult
    verify_prepared_inputs(plan)
    for cmd in commands():
        if cmd['kind']=='cancel':
            events({'kind':'command_ack','payload':{'command_id':cmd['command_id'],'status':'completed'}})
            return StageResult('cancelled',(),0,{'hardware_connected':False})
    device=_plain(plan.input_documents['device_profile']);cfg=sdk_configuration(device)
    report=dict(stage=plan.stage,mode='offline',hardware_connected=False,physical_verified=False,
                status='CODE_READY',sdk_config_class=type(cfg).__module__+'.'+type(cfg).__name__,
                scope='preserved-input inspection; not hardware operation',inputs=_plain(plan.resolved_inputs))
    profile=None
    if 'calibration_profile' in plan.resolved_inputs:
        profile=load_profile(plan.resolved_inputs['calibration_profile']['path'],role=device['role'])
        if any(profile['identity'].get(k)!=getattr(cfg,k) for k in ('id','port')):raise ValueError('Selected device/config and Calibration identity differ')
        report['joint_reviews']={n:{k:v for k,v in review_joint(e).items() if k in ('status','review','reason')} for n,e in profile['joints'].items()}
        report['profile_physical_verified']=profile.get('physical_verified',False)
    if plan.stage in ('capture','real_sim','real_evaluation'):
        if 'capture_session' not in plan.resolved_inputs:raise DataError('CAPTURE_INPUT_REQUIRED','capture_session','Explicit preserved Capture/Snapshot session required for offline mode')
        # Builder owns portable Capture schemas and measured-time validation.
        root=Path(plan.resolved_inputs['capture_session']['path']);manifest,samples,_=capture.load_session(root)
        report['capture']={'samples':len(samples),'clock':manifest['clock'],'joint_names':manifest['joint_names'],
                           'images':sum(len(s['images']) for s in samples),'schema':manifest['schema']}
        if not samples:raise ValueError('No committed measured observations')
        if 'camera_config' in plan.input_documents:
            cameras=_plain(plan.input_documents['camera_config']).get('cameras',{})
            actual={c['id']:c['resolution'] for c in manifest['cameras']}
            if {n:c['resolution'] for n,c in cameras.items()}!=actual:raise ValueError('Selected camera config differs from recorded Capture')
        if plan.scene is not None:
            if tuple(manifest['joint_names'])!=JOINTS or tuple(plan.scene.scene['robot']['joint_order'])!=JOINTS:raise ValueError('Scene and measured Capture joint order differ')
            report['scene_identity']=_plain(plan.scene_identity)
            reasons=capture_binding(manifest,plan.scene,device.get('calibration_id'))
            report['capture_binding']={'compatible':not reasons,'reasons':reasons}
            if reasons:report['status']='PARTIAL'
            report['real_sim_comparison']='measured inputs validated; new engine rendering/residual fitting not performed'
        if plan.stage=='real_evaluation' and report.get('capture_binding',{}).get('compatible') is not True:
            report.update(status='PARTIAL',policy={'inference_performed':False,'command_sent':False},command_binding='Capture coordinates not bound to selected Scene; no inference or command conversion')
        elif plan.stage=='real_evaluation':
            if plan.scene is None:raise ValueError('Explicit Scene required for offline Policy binding')
            from ..learning.policy import policy_inputs,observation_batch,infer
            from PIL import Image
            robot=plan.scene.scene['robot'];urdf=robot.get('model_sha256')
            if not urdf:
                records=plan.scene.calibration['records'].values()
                hashes={r['execution_model_sha256'] for r in records if r.get('kind')=='robot_residual' and r['application']['mode']=='baked'}
                if len(hashes)!=1:raise ValueError('Explicit execution model identity required')
                urdf=next(iter(hashes))
            policy,pre,post,record,contract=policy_inputs(plan,urdf)
            sample=samples[0];images={}
            from real2sim_builder.scene import local_path
            for image in sample['images']:
                name=image['camera'].removeprefix('real_')
                if name not in ('side','wrist'):raise ValueError('Explicit Side/Wrist camera mapping required')
                images[name]=np.asarray(Image.open(local_path(root,image['path'])).convert('RGB'))
            batch=observation_batch(np.asarray(sample['q_measured']),images,joint_order=manifest['joint_names'],task=opts.get('task_instruction'))
            action=infer(policy,pre,post,batch,contract=contract)[0]
            report['policy']={'step':record['step'],'action_model_rad':action.tolist(),'command_sent':False}
            command_id=device.get('command_calibration_id')
            if not command_id:report.update(status='PARTIAL',command_binding='missing explicit device_command calibration ID')
            else:
                # Even an offline encoder preflight requires the command-phase record.
                mapper=mapper_from_scene(plan.scene,command_id,role='follower',phase='device_command')
                if profile is None or mapper.profile!=profile:raise ValueError('Selected Calibration and Scene command binding identity/model differ')
                if 'motor_calibration' not in plan.resolved_inputs:
                    report.update(status='PARTIAL',command_binding='missing explicit motor_calibration; SDK encoding not validated')
                else:
                    models=[plan.scene.root/f.path for f in plan.scene.files if f.sha256==urdf and f.path.endswith('.urdf')]
                    if len(models)!=1:raise ValueError('Explicit execution URDF required for model/motor command intersection')
                    data=encoder_preflight(action,mapper=mapper,model_path=models[0],calibration_path=plan.resolved_inputs['motor_calibration']['path'],cfg=cfg)
                    report['policy'].update(data);report['command_binding']='validated offline; no motor activation/SDK send; hardware safety unverified'
    if plan.stage=='precision_calibration' and 'joint_reviews' not in report:raise ValueError('Explicit preserved calibration_profile required')
    plan.output_path.mkdir();path=plan.output_path/'offline-inspection.json';atomic_json(path,report)
    return StageResult('completed',(str(path),),0,{'status':report['status'],'hardware_connected':False,'physical_verified':False})
