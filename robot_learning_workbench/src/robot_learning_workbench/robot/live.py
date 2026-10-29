"""Concrete observation loops for R03. Real arm Goal/Torque writes are prohibited."""
from pathlib import Path
from typing import TYPE_CHECKING
from collections.abc import Callable,Iterable
import time
import numpy as np
from ..data.native import DataError,atomic_json
from .calibration import JOINTS,load_profile,mapper_from_scene
from .devices import CameraReader,close_devices,DeviceError
from .configuration import create_observer
from .capture import observed_positions,Stability
if TYPE_CHECKING:
    from ..recipe import PreparedRun
    from ..run import StageResult
    from .devices import Follower


def policy_bundle(plan: 'PreparedRun') -> tuple:
    """Reuse official Policy loading with the selected execution model contract."""
    from ..learning.policy import policy_inputs
    if plan.scene is None:raise ValueError('Explicit Scene and Policy control binding required before live inference')
    urdf=plan.scene.scene['robot'].get('model_sha256')
    if not urdf:
        hashes={r['execution_model_sha256']for r in plan.scene.calibration['records'].values()if r.get('kind')=='robot_residual' and r['application']['mode']=='baked'}
        if len(hashes)!=1:raise ValueError('Explicit execution model identity required')
        urdf=next(iter(hashes))
    return policy_inputs(plan,urdf)


def open_inputs(plan: 'PreparedRun') -> tuple['Follower',dict[str,CameraReader]]:
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


def run(plan: 'PreparedRun', *, events: Callable[[dict],None], commands: Callable[[],Iterable[dict]]) -> 'StageResult':
    from ..recipe import verify_prepared_inputs,_plain
    from ..run import StageResult
    opts=plan.effective_settings['execution'];mode=opts.get('mode')
    if mode=='gripper_once' and not opts.get('enable_motion'):
        return gripper_trial(plan,events=events,commands=commands)
    if opts.get('enable_motion') or mode not in ('observe_only','live_capture'):
        raise DataError('ARM_MOTION_NOT_APPROVED','execution','ARM_MOTION_NOT_APPROVED: live workers collect observations only')
    verify_prepared_inputs(plan)
    frames=opts.get('max_frames',1)
    if type(frames)is not int or not 1<=frames<=300:raise ValueError('Explicit bounded max_frames in 1..300 required')
    policy=None
    if plan.stage=='real_evaluation':
        from ..learning.policy import observation_batch,infer,action_queue_depth
        policy,pre,post,record,contract=policy_bundle(plan)
        policy.reset()
    device,cameras=open_inputs(plan);owned={'device':device,**cameras};rows=[];images=[];cancelled=False
    report=dict(mode=mode,hardware_connected=False,physical_verified=False,arm_commands=0,torque_commands=0,command_sent=False,frames=0)
    if policy is not None:
        from ..data.native import digest
        report['policy']={'identity':digest(record),'step':record.get('step'),'control_contract':contract}
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
                    observation_latency_s=(time.monotonic_ns()-t)/1e9,policy_queue_depth=action_queue_depth(policy))
            if rgb:
                images.append(rgb)
                from ..data import video
                if video._preview_sink is not None:
                    for name,image in rgb.items():video._preview_sink(name,image,index,(t-rows[0]['timestamp_ns'])/1e9,0)
            events({'kind':'status','payload':{'progress':{'measured_frames':len(rows),'arm_commands':0}}})
            time.sleep(max(0,1/30-(time.monotonic()-begin)))
        report.update(frames=len(rows),observations=rows,identity=device.identity,mapping=device.precision_mapper.metadata(),
            camera_metadata={n:c.metadata for n,c in cameras.items()},elapsed_s=time.monotonic()-started,
            measured_hz=len(rows)/(time.monotonic()-started),status='cancelled'if cancelled else 'HARDWARE_READ_VERIFIED')
        if mode=='live_capture' and not cancelled:
            from .capture import save_session,prepare_snapshot
            if set(cameras)!={'side','wrist'}:raise ValueError('Live Capture requires both cameras')
            if 'robot_model'not in plan.resolved_inputs:raise ValueError('Explicit portable robot_model required')
            model=Path(plan.resolved_inputs['robot_model']['path'])
            from ..data.native import file_sha256
            if file_sha256(model)!=device.profile['urdf_sha256']:raise ValueError('Capture model differs from Precision mapping')
            last=rows[-1]
            state={'joint_names':list(JOINTS),'sim_joint_mapping':device.precision_mapper.metadata(),
                'precision_observation_only':True,'sent_target':None,'physical_follower_measured_joint_state':last['native'],
                'precision_raw_feedback':{'follower':last['raw']},'hardware':{'follower':{'motor_specs':device.motor_specs}},
                'measured_samples':[{'timestamp_ns':r['timestamp_ns'],'native':r['native'],'raw':r['raw']}for r in rows],
                'real_stability':last['stability'],'timestamps':{'follower':last['feedback_interval'],'real_cameras':{
                    'real_'+n:{'read_start':{'monotonic_ns':p['read_start_ns']},'read_end':{'monotonic_ns':p['timestamp_ns']},'sequence':p['sequence']}for n,p in last['camera_timing'].items()}}}
            try:
                _,_,warnings=prepare_snapshot(state,{'real_'+n:rgb for n,rgb in images[-1].items()},{'cameras':{n:{'resolution':[640,480]}for n in cameras}})
                report['snapshot_quality']={'eligible':not warnings,'warnings':warnings,'physical_calibration_verified':False}
            except ValueError as error:report['snapshot_quality']={'eligible':False,'reason':str(error),'physical_calibration_verified':False}
            metadata={'hardware_identity':device.identity,'hardware_synchronized':False,'command_source':'observation_only_no_training_action',
                      'camera_metadata':report['camera_metadata']}
            if plan.scene is not None:
                from ..data.native import digest
                metadata.update(scene_identity=_plain(plan.scene_identity),calibration_sha256=digest(_plain(plan.scene.calibration)))
            save_session(plan.output_path,model=model,mapping=device.precision_mapper.metadata(),samples=rows,images=images,metadata=metadata,scene=plan.scene)
        else:plan.output_path.mkdir()
        if plan.stage=='real_sim' and rows and not cancelled:
            from PIL import Image
            if set(cameras)!={'side','wrist'}:raise ValueError('Real/Sim needs measured Side/Wrist RGB')
            simulated,applied=render_comparison(plan,np.array(rows[-1]['q_measured']),plan.output_path)
            comparison={}
            for name,rgb in simulated.items():
                Image.fromarray(rgb).save(plan.output_path/('sim-'+name+'.png'))
                Image.fromarray(images[-1][name]).save(plan.output_path/('real-'+name+'.png'))
                comparison[name]={'photometric_mae_rgb_0_255':float(np.abs(rgb.astype(float)-images[-1][name].astype(float)).mean()),
                    'landmark_error':'unmeasured: no corresponding observed landmarks supplied',
                    'calibration_approved':False,'camera_host_skew_ns':rows[-1]['camera_timing'][name]['joint_skew_ns']}
            report['real_sim']={'engine':plan.engine,'measured_q_rad':rows[-1]['q_measured'],'simulation_state_q_rad':applied.tolist(),
                'state_dtype':str(applied.dtype),'cameras':comparison,'physics_steps':0,'physical_robot_commands':0,
                'scope':'measured state rendering and photometric comparison; not geometric Calibration approval'}
        if plan.stage=='precision_calibration':
            from .calibration import review_joint
            report['precision']={'joint_reviews':{n:review_joint(e)['review']for n,e in device.profile['joints'].items()},
                'status':'PARTIAL','reason':'Existing reference fit reviewed; current static feedback is not a new independent angle reference',
                'new_calibration_saved':False,'motor_specs':device.motor_specs}
        atomic_json(plan.output_path/'hardware-report.json',report)
        return StageResult('cancelled'if cancelled else 'completed',(str(plan.output_path),),0,{'frames':len(rows),'arm_commands':0,'command_sent':False})
    finally:
        try:
            if policy is not None:policy.reset()
        finally:close_devices(owned)


def render_comparison(plan: 'PreparedRun', measured_q: np.ndarray, directory: Path) -> tuple[dict[str,np.ndarray],np.ndarray]:
    """Render measured simulation state, not a motor target or a physics rollout."""
    from ..recipe import _plain
    settings=_plain(plan.input_documents.get('engine_config'))
    q=np.asarray(measured_q,dtype=np.float64)
    if q.shape!=(6,) or not np.isfinite(q).all():raise ValueError('Finite measured model-radian q required')
    if settings is None:raise ValueError('Explicit existing engine_config required for Real/Sim render')
    if plan.engine=='mujoco':
        import mujoco
        from ..engines.mujoco.model import ModelConfig,build_model
        model,binding=build_model(plan.scene,ModelConfig(**settings));data=mujoco.MjData(model)
        data.qpos[list(binding.q_indices)]=q;mujoco.mj_forward(model,data)
        with mujoco.Renderer(model,height=480,width=640)as renderer:
            images={}
            for name in ('side','wrist'):
                renderer.update_scene(data,camera=binding.camera_ids[name]);images[name]=renderer.render().copy()
        return images,data.qpos[list(binding.q_indices)].copy()
    if plan.engine=='isaac':
        import torch,tempfile
        from isaaclab.envs import ManagerBasedEnv
        from ..engines.isaac.env_cfg import build_env_cfg
        env=None
        with tempfile.TemporaryDirectory(dir=directory,prefix='real-sim-')as temporary:
            try:
                env=ManagerBasedEnv(cfg=build_env_cfg(plan.scene,settings,runtime_directory=Path(temporary)/'runtime'));env.reset()
                robot=env.scene['robot'];ids=[robot.joint_names.index(n)for n in JOINTS]
                pose=robot.data.joint_pos.clone();pose[:,ids]=torch.tensor(q,dtype=pose.dtype,device=env.device)
                robot.write_joint_state_to_sim(pose,torch.zeros_like(pose));env.scene.write_data_to_sim();env.sim.forward()
                for _ in range(3):env.sim.render()
                for name in ('side','wrist'):env.scene['camera_'+name].update(env.physics_dt,force_recompute=True)
                images={n:env.scene['camera_'+n].data.output['rgb'][0,:,:,:3].detach().cpu().numpy().copy()for n in ('side','wrist')}
                return images,robot.data.joint_pos[0,ids].detach().cpu().numpy().copy()
            finally:
                if env is not None:env.close()
    raise ValueError('Supported actual engine required')


def gripper_trial(plan: 'PreparedRun', *, events: Callable[[dict],None], commands: Callable[[],Iterable[dict]]) -> 'StageResult':
    """R03 one-shot preflight, supervised approval, exactly one motor6 goal."""
    from ..recipe import verify_prepared_inputs,_plain
    from ..run import StageResult
    from .configuration import bind_gripper_command
    from .devices import gripper_proposal,send_gripper_once
    from .calibration import joint_specs,fingerprint
    verify_prepared_inputs(plan);opts=plan.effective_settings['execution']
    if plan.stage not in ('teleoperation','real_evaluation'):raise DataError('ARM_MOTION_NOT_APPROVED','stage','Gripper-only Teleoperation/Policy stage required')
    if (plan.stage=='teleoperation' and 'gripper_target_rad'not in opts) or 'max_gripper_delta_raw'not in opts:raise ValueError('Explicit direction/target and small displacement budget required; no default motion')
    device,cameras=open_inputs(plan);report={'command_sent':False,'arm_commands':0,'torque_commands':0,'status':'BLOCKED'}
    policy=None
    try:
        spec=_plain(plan.input_documents['device_profile'])
        if plan.scene is None or not spec.get('command_calibration_id'):raise ValueError('Explicit Scene command Calibration required; no observation binding fallback')
        bind_gripper_command(device,plan.scene,spec['command_calibration_id'])
        if not device._connected:device.connect()
        models=[plan.scene.root/f.path for f in plan.scene.files if f.sha256==device.profile['urdf_sha256'] and f.path.endswith('.urdf')]
        if len(models)!=1:raise ValueError('Exact command mapping URDF required')
        requested=opts.get('gripper_target_rad')
        if plan.stage=='real_evaluation':
            from ..learning.policy import observation_batch,infer,action_queue_depth
            policy,pre,post,record,contract=policy_bundle(plan);policy.reset()
            if set(cameras)!={'side','wrist'}:raise ValueError('Real Policy needs both physical cameras')
            for c in cameras.values():c.start()
            deadline=time.monotonic()+3
            while any(c.nearest() is None for c in cameras.values()):
                if time.monotonic()>deadline:raise ValueError('Camera startup timeout')
                time.sleep(.01)
            native,interval=device.read();q=observed_positions(device.precision_mapper,native,raw=device.last_raw,motor_specs=device.motor_specs)
            packets={n:c.nearest()for n,c in cameras.items()}
            if any(abs(p['read_end']['monotonic_ns']-interval['end']['monotonic_ns'])>100_000_000 for p in packets.values()):raise ValueError('Camera/Joint skew; no Policy command')
            batch=observation_batch([q[n]for n in JOINTS],{n:p['rgb']for n,p in packets.items()},joint_order=JOINTS,task=opts.get('task_instruction'))
            action=infer(policy,pre,post,batch,contract=contract)[0]
            report['policy_action_model_rad']=action.tolist();requested=float(action[5])
        proposal=gripper_proposal(device,requested,model_bounds={n:s['limits']for n,s in joint_specs(models[0]).items()},max_delta_raw=opts['max_gripper_delta_raw'])
        report['proposal']=proposal
        events({'kind':'status','payload':{'progress':{'gripper_proposal':proposal},'episode_id':'gripper-once'}})
        deadline=time.monotonic()+30;approved=False;cancelled=False
        while time.monotonic()<deadline and not approved and not cancelled:
            pending=list(commands())
            if any(command['kind']=='cancel'for command in pending):
                cancelled=True;device.stop()
                for command in pending:
                    ack={'command_id':command['command_id'],'status':'completed'if command['kind']=='cancel'else'rejected'}
                    if command['kind']!='cancel':ack['reason']='Cancel takes priority over approval in the same command batch'
                    events({'kind':'command_ack','payload':ack})
                break
            for command in pending:
                payload=command.get('payload',{});kind=command['kind']
                if approved:
                    events({'kind':'command_ack','payload':{'command_id':command['command_id'],'status':'rejected','reason':'One-shot approval already consumed; no second send'}})
                    continue
                if kind=='cancel':cancelled=True;ok=True
                else:
                    ok=kind=='gripper_approve' and payload.get('proposal_sha256')==fingerprint(proposal) and payload.get('target_raw')==proposal['target_raw'] and all(payload.get(k)is True for k in ('supervised','clear','stop_ready'))
                    if ok:
                        report['motion']=send_gripper_once(device,proposal,approved=True);report['command_sent']=True;approved=True
                ack={'command_id':command['command_id'],'status':'completed'if ok else'rejected'}
                if not ok:ack['reason']='Exact current proposal and explicit supervised/clear/stop-ready approval required'
                events({'kind':'command_ack','payload':ack})
            if not approved and not cancelled:time.sleep(.05)
        report['status']='SINGLE_COMMAND_VERIFIED'if approved else 'CANCELLED'if cancelled else'APPROVAL_TIMEOUT'
        plan.output_path.mkdir();atomic_json(plan.output_path/'gripper-report.json',report)
        return StageResult('completed'if approved else'cancelled',(str(plan.output_path),),0,report)
    except DeviceError as error:
        report.update(status='FAILED',effect=error.effect,command_sent='unknown'if error.effect=='unknown'else report['command_sent'],error=str(error))
        plan.output_path.mkdir(exist_ok=True);atomic_json(plan.output_path/'gripper-report.json',report)
        raise
    finally:
        try:
            if policy is not None:policy.reset()
        finally:close_devices({'device':device,**cameras})
