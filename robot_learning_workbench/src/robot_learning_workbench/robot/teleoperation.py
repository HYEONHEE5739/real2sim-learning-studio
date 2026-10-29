"""Full-axis Fake teleoperation; physical Follower arm commands are never enabled."""
import time
from typing import TYPE_CHECKING
from collections.abc import Callable,Iterable
import numpy as np
from .calibration import JOINTS
from .devices import DeviceError,close_devices
from .capture import observed_positions
from .control import command_target
if TYPE_CHECKING:
    from .devices import Follower,Leader
    from ..recipe import PreparedRun
    from ..run import StageResult


def collect(leader: 'Leader', follower: 'Follower', *, model_bounds: dict, frames: int, commands: Callable[[],Iterable[dict]]) -> tuple[list,bool]:
    """Exercise the existing six-axis contract only with explicit memory devices."""
    if follower.read_only or any(c.__module__.startswith('lerobot.')for c in type(follower.bus).__mro__):
        raise DeviceError('teleoperation','ARM_MOTION_NOT_APPROVED: full-axis loop accepts memory devices only',effect='not_applied')
    if type(frames)is not int or not 1<=frames<=300:raise ValueError('Bounded frame count required')
    rows=[];cancelled=False
    try:
        leader.connect();follower.connect();leader.activate();follower.activate()
        for _ in range(frames):
            if any(c['kind']=='cancel'for c in commands()):cancelled=True;break
            native,interval=follower.read()
            measured=observed_positions(follower.precision_mapper,native,raw=follower.last_raw,motor_specs=follower.motor_specs)
            source,source_interval=leader.read()
            target,command,details=command_target(source,leader_mapper=leader.precision_mapper,follower=follower,model_bounds=model_bounds,leader_raw=leader.last_raw)
            returned,sent=follower.send(command);after,after_interval=follower.read()
            observed=observed_positions(follower.precision_mapper,after,raw=follower.last_raw,motor_specs=follower.motor_specs)
            rows.append(dict(timestamp_ns=interval['end']['monotonic_ns'],pre_measured_model_rad=[measured[n]for n in JOINTS],
                requested_model_rad=details['requested_model_rad'],applied_model_rad=target.tolist(),post_measured_model_rad=[observed[n]for n in JOINTS],
                saturation=details['saturation'],native_sent=returned,send_timing=sent,leader_timing=source_interval,feedback_timing=after_interval,hardware_verified=False))
        return rows,cancelled
    finally:close_devices({'leader':leader,'follower':follower})


def collect_policy(policy: object, pre: Callable, post: Callable, *, follower: 'Follower', contract: dict, model_bounds: dict, images: dict, frames: int, commands: Callable[[],Iterable[dict]], task: str|None=None) -> tuple[list,bool]:
    """Official queue/processor loop with an explicitly memory-only full-axis device."""
    from ..learning.policy import observation_batch,infer,action_queue_depth
    from .control import encode_model_target
    if follower.read_only or any(c.__module__.startswith('lerobot.')for c in type(follower.bus).__mro__):raise DeviceError('policy','ARM_MOTION_NOT_APPROVED: full-axis Policy requires a memory device',effect='not_applied')
    if type(frames)is not int or not 1<=frames<=300:raise ValueError('Bounded Fake Policy frame count required')
    rows=[];cancelled=False;policy.reset()
    try:
        follower.connect();follower.activate()
        for _ in range(frames):
            if any(c['kind']=='cancel'for c in commands()):cancelled=True;break
            native,interval=follower.read()
            measured=observed_positions(follower.precision_mapper,native,raw=follower.last_raw,motor_specs=follower.motor_specs)
            batch=observation_batch([measured[n]for n in JOINTS],images,joint_order=JOINTS,task=task)
            begin=time.perf_counter();requested=infer(policy,pre,post,batch,contract=contract)[0]
            target,command,details=encode_model_target(requested,follower=follower,model_bounds=model_bounds)
            returned,sent=follower.send(command);after,after_interval=follower.read()
            actual=observed_positions(follower.precision_mapper,after,raw=follower.last_raw,motor_specs=follower.motor_specs)
            rows.append(dict(timestamp_ns=interval['end']['monotonic_ns'],pre_measured_model_rad=[measured[n]for n in JOINTS],requested_model_rad=details['requested_model_rad'],
                applied_model_rad=target.tolist(),post_measured_model_rad=[actual[n]for n in JOINTS],saturation=details['saturation'],native_sent=returned,
                send_timing=sent,feedback_timing=after_interval,inference_s=time.perf_counter()-begin,policy_queue_depth=action_queue_depth(policy),hardware_verified=False))
        return rows,cancelled
    finally:
        try:policy.reset()
        finally:close_devices({'follower':follower})


def fake_device(spec: dict, profile: dict) -> 'Follower':
    """Memory-only SDK API, with official normalization math; no serial constructor."""
    import json,hashlib
    from pathlib import Path
    from types import SimpleNamespace as NS
    from lerobot.motors import Motor,MotorCalibration,MotorNormMode
    from lerobot.motors.motors_bus import MotorsBus
    from lerobot.motors.feetech.feetech import FeetechMotorsBus
    from .devices import Follower,Leader
    raw=Path(spec['calibration_path']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=profile['identity']['calibration_sha256']:raise ValueError('Fake calibration fixture identity differs')
    calibration={n:MotorCalibration(**c)for n,c in json.loads(raw).items()}
    motors={n:Motor(i+1,'sts3215',MotorNormMode.RANGE_0_100 if n=='gripper'else MotorNormMode.DEGREES)for i,n in enumerate(JOINTS)}
    arithmetic=object.__new__(FeetechMotorsBus);MotorsBus.__init__(arithmetic,spec['sdk']['port'],motors,calibration)
    present={n:int(e['anchor_raw'])for n,e in profile['joints'].items()};goal=dict(present)
    bus=NS(port=spec['sdk']['port'],is_connected=False,motors=motors,calibration=calibration,model_resolution_table=arithmetic.model_resolution_table,
        apply_drive_mode=arithmetic.apply_drive_mode,_normalize=arithmetic._normalize,_unnormalize=arithmetic._unnormalize)
    def connect():bus.is_connected=True
    def disconnect(disable_torque=True):bus.is_connected=False
    def read(name,normalize=False):return dict(present if name=='Present_Position'else goal)
    def write(name,packet,normalize=False):goal.update(packet)
    def send(packet):
        normalized={motors[n].id:packet[n+'.pos']for n in JOINTS};encoded=bus._unnormalize(normalized)
        present.update({n:encoded[m.id]for n,m in motors.items()});goal.update(present);return packet
    bus.connect=connect;bus.disconnect=disconnect;bus.sync_read=read;bus.sync_write=write;bus.disable_torque=lambda:None;bus.port_handler=NS(closePort=disconnect)
    sdk=NS(id=spec['sdk']['id'],bus=bus,is_calibrated=True,action_features={n+'.pos':float for n in JOINTS},configure=lambda:None,send_action=send)
    cls=Leader if spec['role']=='leader'else Follower
    return cls(sdk,profile=profile,calibration_path=spec['calibration_path'],identity=profile['identity'],model_hash=profile['urdf_sha256'])


def run(plan: 'PreparedRun', *, events: Callable[[dict],None], commands: Callable[[],Iterable[dict]]) -> 'StageResult':
    """Persist an explicitly Fake full-axis Episode in the existing Native format."""
    from ..recipe import verify_prepared_inputs,_plain
    from ..data.native import NativeRun,native_api
    from ..run import StageResult
    from .calibration import load_profile
    verify_prepared_inputs(plan);opts=plan.effective_settings['execution']
    if opts.get('mode')!='fake_all':
        from .live import run as live_run
        return live_run(plan,events=events,commands=commands)
    spec=_plain(plan.input_documents['device_profile'])
    profile=load_profile(plan.resolved_inputs['calibration_profile']['path'],role='follower')
    if plan.scene is not None and spec.get('calibration_id'):
        from .calibration import mapper_from_scene
        bound=mapper_from_scene(plan.scene,spec['calibration_id'],role='follower',phase='device_observation').profile
        if bound['identity']!=profile['identity']:raise ValueError('Selected Fake profile differs from Scene observation identity')
        profile=bound
    f=fake_device(spec,profile)
    if plan.stage=='real_evaluation':
        from .live import policy_bundle
        policy,pre,post,record,contract=policy_bundle(plan)
        rows,cancelled=collect_policy(policy,pre,post,follower=f,contract=contract,model_bounds={n:e['limits']for n,e in profile['joints'].items()},
            images={n:np.zeros((480,640,3),np.uint8)for n in ('side','wrist')},frames=opts['max_frames'],commands=commands,task=opts.get('task_instruction'))
    else:
        leader_spec=_plain(plan.input_documents['leader_device_profile']);leader_profile=load_profile(plan.resolved_inputs['leader_calibration_profile']['path'],role='leader')
        l=fake_device(leader_spec,leader_profile)
        rows,cancelled=collect(l,f,model_bounds={n:e['limits']for n,e in profile['joints'].items()},frames=opts['max_frames'],commands=commands)
    execution={'stage':plan.stage,'engine':'fake','seed':0,'hardware_connected':False,'recording_only':True,'action_encoding':'absolute_model_joint_position_target_rad6','joint_order':list(JOINTS),'synthetic_rgb_input':plan.stage=='real_evaluation','model_sha256':profile['urdf_sha256']}
    if plan.stage=='real_evaluation':
        from ..data.native import digest
        execution['policy']={'identity':digest(record),'step':record.get('step'),'control_contract':contract}
    import torch
    with NativeRun(plan.output_path,execution)as owner:
        segment=owner.segment('fake-teleoperation');claim=owner.claim_attempt(segment);ep=native_api()[0]();ep.seed=0;ep.success=True
        for i,row in enumerate(rows):
            for name,value in {'actions':row['applied_model_rad'],'joint_targets':row['applied_model_rad'],'obs/policy/joint_pos':row['pre_measured_model_rad'],
                'states/joint_pos':row['post_measured_model_rad'],'commands/requested_joint_rad':[row['requested_model_rad'][n]for n in JOINTS],
                'commands/applied_joint_rad':row['applied_model_rad'],'commands/saturation_delta_rad':row['saturation']['delta_rad'],'obs/timestamp':[i/30],
                'timing/send_duration_s':[(row['send_timing']['end']['monotonic_ns']-row['send_timing']['start']['monotonic_ns'])/1e9]}.items():ep.add(name,torch.from_numpy(np.asarray(value,dtype=np.float64)))
            ep.add('commands/saturation_mask',torch.tensor(row['saturation']['saturation_mask'],dtype=torch.bool))
            if 'inference_s'in row:
                ep.add('policy/inference_s',torch.tensor([row['inference_s']],dtype=torch.float64))
                if row['policy_queue_depth'] is not None:ep.add('policy/action_queue_depth',torch.tensor([row['policy_queue_depth']],dtype=torch.int64))
        if rows and not cancelled:
            segment.write_episode(ep,episode_id='fake-teleoperation',metadata={'hardware_verified':False,'recording_only':True});segment.record_attempt(claim,status='success',episode_id='fake-teleoperation')
        else:segment.record_attempt(claim,status='cancelled')
        segment.commit()
    return StageResult('cancelled'if cancelled or not rows else 'completed',(str(plan.output_path),),int(bool(rows) and not cancelled),{'status':'CANCELLED'if cancelled else'FAKE_VERIFIED','hardware_connected':False,'frames':len(rows)})
