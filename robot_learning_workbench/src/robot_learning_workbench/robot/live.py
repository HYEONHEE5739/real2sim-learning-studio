"""Concrete observation loops for R03. Real arm Goal/Torque writes are prohibited."""
from pathlib import Path
import time
import numpy as np
from ..data.native import DataError,atomic_json
from .calibration import JOINTS,load_profile,mapper_from_scene
from .devices import CameraReader,close_devices
from .configuration import create_observer
from .capture import observed_positions,Stability


def open_inputs(plan):
    """Construct explicit pinned devices; SDK constructors do not connect."""
    from ..recipe import _plain
    from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
    spec=_plain(plan.input_documents['device_profile'])
    profile=load_profile(plan.resolved_inputs['calibration_profile']['path'],role=spec['role'])
    if plan.scene is not None:
        if not spec.get('calibration_id'):raise ValueError('Explicit observation Calibration ID required')
        mapper=mapper_from_scene(plan.scene,spec['calibration_id'],role=spec['role'],phase='device_observation')
        if mapper.profile['identity']!=profile['identity']:raise ValueError('Selected profile and Scene observation identity differ')
        profile=mapper.profile
    device=create_observer(spec,profile);cameras={}
    if 'camera_config' in plan.input_documents:
        config=_plain(plan.input_documents['camera_config'])['cameras']
        if set(config)!={'side','wrist'}:raise ValueError('Explicit Side/Wrist cameras required')
        paths=[]
        for name,settings in config.items():
            cfg=OpenCVCameraConfig(**settings)
            if (cfg.width,cfg.height)!=(640,480) or cfg.fps!=30:raise ValueError('Original RGB640x480/30FPS required')
            path=Path('/dev/video'+str(cfg.index_or_path)) if isinstance(cfg.index_or_path,int) else Path(cfg.index_or_path)
            paths.append(path.resolve());cameras[name]=CameraReader.from_config(cfg)
        if len(set(paths))!=2:raise ValueError('Side/Wrist cannot be the same camera')
    return device,cameras


def run(plan, *, events, commands):
    from ..recipe import verify_prepared_inputs,_plain
    from ..run import StageResult
    opts=plan.effective_settings['execution'];mode=opts.get('mode')
    if opts.get('enable_motion') or mode not in ('observe_only','live_capture'):
        raise DataError('ARM_MOTION_NOT_APPROVED','execution','ARM_MOTION_NOT_APPROVED: live workers collect observations only')
    verify_prepared_inputs(plan)
    frames=opts.get('max_frames',1)
    if type(frames)is not int or not 1<=frames<=300:raise ValueError('Explicit bounded max_frames in 1..300 required')
    policy=None
    if plan.stage=='real_evaluation':
        from ..learning.policy import policy_inputs,observation_batch,infer
        if plan.scene is None:raise ValueError('Explicit Scene and Policy control binding required before live inference')
        urdf=plan.scene.scene['robot'].get('model_sha256')
        if not urdf:
            hashes={r['execution_model_sha256']for r in plan.scene.calibration['records'].values()if r.get('kind')=='robot_residual' and r['application']['mode']=='baked'}
            if len(hashes)!=1:raise ValueError('Explicit execution model identity required')
            urdf=next(iter(hashes))
        policy,pre,post,record,contract=policy_inputs(plan,urdf)
        policy.reset()
    device,cameras=open_inputs(plan);owned={'device':device,**cameras};rows=[];images=[];cancelled=False
    report=dict(mode=mode,hardware_connected=False,physical_verified=False,arm_commands=0,torque_commands=0,command_sent=False,frames=0)
    try:
        device.connect();report['hardware_connected']=True
        for camera in cameras.values():camera.start()
        stability=Stability();started=time.monotonic();deadline=started+3
        while cameras and any(camera.nearest() is None for camera in cameras.values()):
            if time.monotonic()>deadline:raise ValueError('Camera startup timeout')
            time.sleep(.01)
        for index in range(frames):
            begin=time.monotonic()
            for command in commands():
                kind=command['kind']
                if kind=='cancel':
                    cancelled=True;events({'kind':'command_ack','payload':{'command_id':command['command_id'],'status':'completed'}})
                else:events({'kind':'command_ack','payload':{'command_id':command['command_id'],'status':'rejected','reason':'Observation-only stage accepts cancel; no physical Step/Home/Reset'}})
            if cancelled:break
            native,interval=device.read();t=interval['end']['monotonic_ns']
            q=observed_positions(device.precision_mapper,native,raw=device.last_raw,motor_specs=device.motor_specs)
            stability.add(t,native);rgb={};timing={}
            for name,camera in cameras.items():
                packet=camera.nearest(t)
                if packet is None:raise ValueError(name+': no frame')
                stamp=packet['read_end']['monotonic_ns']
                eligible=abs(stamp-t)<=100_000_000 and time.monotonic_ns()-stamp<=200_000_000
                if not eligible and plan.stage=='real_evaluation':raise ValueError(name+': stale/skewed Camera/Joint observations; no inference')
                rgb[name]=packet['rgb'];timing[name]={'timestamp_ns':stamp,'read_start_ns':packet['read_start']['monotonic_ns'],'sequence':packet['sequence'],'joint_skew_ns':stamp-t,'eligible':eligible}
            rows.append(dict(id='sample_'+str(index),timestamp_ns=t,q_measured=[q[n]for n in JOINTS],native=native,raw=dict(device.last_raw),
                camera_timing=timing,feedback_interval=interval,command_sent=False,command_applied=False,stability=stability.assess()))
            if policy is not None:
                batch=observation_batch([q[n]for n in JOINTS],rgb,joint_order=JOINTS,task=opts.get('task_instruction'))
                inference_start=time.perf_counter();action=infer(policy,pre,post,batch,contract=contract)[0]
                rows[-1].update(policy_action_model_rad=action.tolist(),inference_s=time.perf_counter()-inference_start,
                    observation_latency_s=(time.monotonic_ns()-t)/1e9,policy_queue_depth=len(getattr(policy,'_action_queue',[])))
            if rgb:images.append(rgb)
            events({'kind':'status','payload':{'progress':{'measured_frames':len(rows),'arm_commands':0}}})
            time.sleep(max(0,1/30-(time.monotonic()-begin)))
        report.update(frames=len(rows),observations=rows,identity=device.identity,mapping=device.precision_mapper.metadata(),
            camera_metadata={n:c.metadata for n,c in cameras.items()},elapsed_s=time.monotonic()-started,
            measured_hz=len(rows)/(time.monotonic()-started),status='cancelled'if cancelled else 'HARDWARE_READ_VERIFIED')
        if mode=='live_capture' and not cancelled:
            from .capture import save_session
            if set(cameras)!={'side','wrist'}:raise ValueError('Live Capture requires both cameras')
            if 'robot_model'not in plan.resolved_inputs:raise ValueError('Explicit portable robot_model required')
            model=Path(plan.resolved_inputs['robot_model']['path'])
            from ..data.native import file_sha256
            if file_sha256(model)!=device.profile['urdf_sha256']:raise ValueError('Capture model differs from Precision mapping')
            metadata={'hardware_identity':device.identity,'hardware_synchronized':False,'command_source':'observation_only_no_training_action',
                      'camera_metadata':report['camera_metadata']}
            if plan.scene is not None:
                from ..data.native import digest
                metadata.update(scene_identity=_plain(plan.scene_identity),calibration_sha256=digest(_plain(plan.scene.calibration)))
            save_session(plan.output_path,model=model,mapping=device.precision_mapper.metadata(),samples=rows,images=images,metadata=metadata)
        else:plan.output_path.mkdir()
        atomic_json(plan.output_path/'hardware-report.json',report)
        return StageResult('cancelled'if cancelled else 'completed',(str(plan.output_path),),0,{'frames':len(rows),'arm_commands':0,'command_sent':False})
    finally:
        try:
            if policy is not None:policy.reset()
        finally:close_devices(owned)
