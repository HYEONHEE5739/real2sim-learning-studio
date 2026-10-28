"""Full-axis Fake teleoperation; physical Follower arm commands are never enabled."""
import time
import numpy as np
from .calibration import JOINTS
from .devices import DeviceError,close_devices
from .capture import observed_positions
from .control import command_target


def collect(leader, follower, *, model_bounds: dict, frames: int, commands) -> list:
    """Exercise the existing six-axis contract only with explicit memory devices."""
    if follower.read_only or any(c.__module__.startswith('lerobot.')for c in type(follower.bus).__mro__):
        raise DeviceError('teleoperation','ARM_MOTION_NOT_APPROVED: full-axis loop accepts memory devices only',effect='not_applied')
    if type(frames)is not int or not 1<=frames<=300:raise ValueError('Bounded frame count required')
    rows=[]
    try:
        leader.connect();follower.connect();leader.activate();follower.activate()
        for _ in range(frames):
            if any(c['kind']=='cancel'for c in commands()):break
            native,interval=follower.read()
            measured=observed_positions(follower.precision_mapper,native,raw=follower.last_raw,motor_specs=follower.motor_specs)
            source,source_interval=leader.read()
            target,command,details=command_target(source,leader_mapper=leader.precision_mapper,follower=follower,model_bounds=model_bounds,leader_raw=leader.last_raw)
            returned,sent=follower.send(command);after,after_interval=follower.read()
            observed=observed_positions(follower.precision_mapper,after,raw=follower.last_raw,motor_specs=follower.motor_specs)
            rows.append(dict(timestamp_ns=interval['end']['monotonic_ns'],pre_measured_model_rad=[measured[n]for n in JOINTS],
                requested_model_rad=details['requested_model_rad'],applied_model_rad=target.tolist(),post_measured_model_rad=[observed[n]for n in JOINTS],
                saturation=details['saturation'],native_sent=returned,send_timing=sent,leader_timing=source_interval,feedback_timing=after_interval,hardware_verified=False))
        return rows
    finally:close_devices({'leader':leader,'follower':follower})


def fake_device(spec: dict, profile: dict):
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


def run(plan, *, events, commands):
    """Persist an explicitly Fake full-axis Episode in the existing Native format."""
    from ..recipe import verify_prepared_inputs,_plain
    from ..data.native import NativeRun,native_api
    from ..run import StageResult
    from .calibration import load_profile
    verify_prepared_inputs(plan);opts=plan.effective_settings['execution']
    if opts.get('mode')!='fake_all':
        from .live import run as live_run
        return live_run(plan,events=events,commands=commands)
    spec=_plain(plan.input_documents['device_profile']);leader_spec=_plain(plan.input_documents['leader_device_profile'])
    profile=load_profile(plan.resolved_inputs['calibration_profile']['path'],role='follower')
    leader_profile=load_profile(plan.resolved_inputs['leader_calibration_profile']['path'],role='leader')
    f=fake_device(spec,profile);l=fake_device(leader_spec,leader_profile)
    rows=collect(l,f,model_bounds={n:e['limits']for n,e in profile['joints'].items()},frames=opts['max_frames'],commands=commands)
    execution={'stage':'teleoperation','engine':'fake','seed':0,'hardware_connected':False,'recording_only':True,'model_sha256':profile['urdf_sha256']}
    import torch
    with NativeRun(plan.output_path,execution)as owner:
        segment=owner.segment('fake-teleoperation');claim=owner.claim_attempt(segment);ep=native_api()[0]();ep.seed=0;ep.success=True
        for i,row in enumerate(rows):
            for name,value in {'actions':row['applied_model_rad'],'joint_targets':row['applied_model_rad'],'obs/policy/joint_pos':row['pre_measured_model_rad'],
                'states/joint_pos':row['post_measured_model_rad'],'commands/requested_joint_rad':[row['requested_model_rad'][n]for n in JOINTS],
                'commands/applied_joint_rad':row['applied_model_rad'],'obs/timestamp':[i/30]}.items():ep.add(name,torch.from_numpy(np.asarray(value,dtype=np.float64)))
        if rows:
            segment.write_episode(ep,episode_id='fake-teleoperation',metadata={'hardware_verified':False,'recording_only':True});segment.record_attempt(claim,status='success',episode_id='fake-teleoperation')
        else:segment.record_attempt(claim,status='cancelled')
        segment.commit()
    return StageResult('completed'if rows else 'cancelled',(str(plan.output_path),),int(bool(rows)),{'status':'FAKE_VERIFIED','hardware_connected':False,'frames':len(rows)})
