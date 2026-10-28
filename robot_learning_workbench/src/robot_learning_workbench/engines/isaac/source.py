"""Isaac Lab2.3 native Source recording, after AppLauncher, without device auto-start.

https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html
"""
from pathlib import Path
import time
import numpy as np
from .state import initial_state,read_sample
from .mdp import apply_joint_targets,validate_targets
from robot_learning_workbench.data.recording import record_frame as _record_frame, add_initial, collection_coordinates, command_summary
from robot_learning_workbench.commands import control_commands, step_completed
from robot_learning_workbench.data.publication import publish_event
from robot_learning_workbench.robot.configuration import create_leader
from ...data.native import native_api,digest
from ...data.video import AsyncVideoWriter


def validate_settings(settings):
    if settings['isaac']['physics_timestep_s']*settings['isaac']['decimation']!=1/30:raise ValueError('Isaac collection needs explicit 30Hz control settings')


def record_frame(episode,sample,target_pose,target,*,time_s,base,requested=None,signals=None,previous_pose=None,command_requested=None,command_limits=None):
    import torch
    _record_frame(episode,sample,target_pose,target,time_s=time_s,base=base,requested=requested,signals=signals,previous_pose=previous_pose,command_requested=command_requested,command_limits=command_limits)
    episode.add('obs/policy/joint_vel',torch.from_numpy(sample['joint_velocities'].copy()))


def pose_delta_action(previous,current,gripper):
    """Original native Source post-step EEF delta, separate from target actions."""
    import torch
    from isaaclab.utils.math import matrix_from_quat,quat_from_matrix,axis_angle_from_quat
    before=matrix_from_quat(previous[3:7].unsqueeze(0))[0];after=matrix_from_quat(current[3:7].unsqueeze(0))[0]
    rotation=quat_from_matrix((after@before.T).unsqueeze(0))[0]
    return torch.cat([current[:3]-previous[:3],axis_angle_from_quat(rotation.unsqueeze(0))[0],gripper.reshape(1)])


def collect_episode(env,segment,kin,*,episode_id,seed,frames,read_target,events,commands,duration_s=None,realtime=False):
    from .mdp import complete_episode
    return complete_episode(env,collection_steps(env,segment,kin,episode_id=episode_id,seed=seed,frames=frames,read_target=read_target,events=events,commands=commands,duration_s=duration_s,realtime=realtime))


def collection_steps(env,segment,kin,*,episode_id,seed,frames,read_target,events,commands,duration_s=None,realtime=False,env_index=0):
    import torch
    ep=native_api()[0]();ep.seed=seed;ep.success=True;initial=initial_state(env,env_index,relative=True);add_initial(ep,initial)
    base=np.asarray(env.cfg.workbench_inputs['profile']['robot_base']['T_world'])
    limits=np.array(env.cfg.workbench_joint_limits_rad);limits[5]=[max(limits[5,0],0.),min(limits[5,1],np.deg2rad(100))]
    controls=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False);videos={};previous=None;tick=0
    try:
        for camera in ('side','wrist'):videos[camera]=AsyncVideoWriter(segment.folder/(camera+'.mp4'),env_index=env_index)
        deadline=None if duration_s is None else time.monotonic()+duration_s
        while tick<frames and (deadline is None or time.monotonic()<deadline):
            started=time.monotonic();events({'kind':'status','payload':{'episode_id':episode_id,'env_index':env_index,'tick':tick,'progress':{'frames':tick}}})
            control_commands(commands(),controls,events,tick=tick,episode_id=episode_id,env_index=env_index)
            if controls['cancelled'] or controls.get('discard'):return None,{},initial,'cancelled' if controls['cancelled'] else 'discarded'
            if controls.get('save'):break
            if controls['paused'] and not controls['steps']:
                yield None
                if deadline is not None:deadline+=time.monotonic()-started
                continue
            requested=np.asarray(read_target())
            from ...robot.control import checked_target
            target=validate_targets(checked_target(requested,limits=limits,applied_dtype=np.float32)[None],limits[None])[0]
            before=read_sample(env,env_index,'pre_step',tick,episode_id=episode_id)
            target_pose=kin.forward_kinematics(target[:5])
            record_frame(ep,before,target_pose,target,time_s=float(env.sim.current_time),base=base,requested=requested.astype(np.float64),previous_pose=previous,command_requested=requested,command_limits=limits)
            for name,writer in videos.items():writer.write(before['cameras'][name]['rgb'])
            native_before=env.obs_buf['policy']['ee_state'][env_index].clone()
            yield target
            raw=pose_delta_action(native_before,env.obs_buf['policy']['ee_state'][env_index],torch.as_tensor(target[-1],device=env.device))
            if not torch.isfinite(raw).all():raise RuntimeError('Nonfinite post-step EEF delta after command; effect unknown')
            ep.add('collection/recorded_mimic_actions',raw.cpu().clone())
            for name in ('joint_pos','joint_vel'):ep.add('states/'+name,env.obs_buf['policy'][name][env_index].detach().cpu().clone())
            previous=target_pose;step_completed(controls,events,tick);tick+=1
            if realtime:time.sleep(max(0,1/30-(time.monotonic()-started)))
        if not tick:return None,{},initial,'discarded'
        for writer in videos.values():writer.close()
        return ep,{k:v.video_path for k,v in videos.items()},initial,'completed'
    except Exception as error:
        from ...robot.control import TargetRejected
        if isinstance(error,TargetRejected):error.diagnostics['applied_steps']=tick
        raise
    finally:
        for writer in videos.values():
            if not writer._closed:writer.abort()


def settings_for(plan,recorded=None):
    from ...recipe import _plain
    raw=recorded if recorded is not None else plan.input_documents.get('engine_config')
    if raw is None:raise ValueError('Explicit Isaac engine_config required')
    settings=_plain(raw);settings.pop('package_root',None);validate_settings(settings)
    if (plan.stage=='datagen' or (plan.stage=='source' and plan.object_order)) and tuple(settings['active_object_ids'])!=tuple(plan.object_order):raise ValueError('Recipe object order differs from explicit engine configuration')
    return settings


def model_identity(package,settings):
    from .env_cfg import execution_inputs
    from ...data.native import file_sha256
    inputs=execution_inputs(package,settings)
    return digest({'scene':inputs['scene_identity'],'settings':{k:v for k,v in settings.items() if k not in ('package_root','seed')},'usd_sha256':file_sha256(inputs['robot_usd']),'urdf_sha256':file_sha256(inputs['robot_urdf'])})


def execution_contract(plan,settings):
    from ...recipe import _plain
    return dict(stage=plan.stage,engine='isaac',scene_identity=_plain(plan.scene_identity),calibration=_plain(plan.scene.calibration),model_sha256=model_identity(plan.scene,settings),
        model_config={k:v for k,v in settings.items() if k!='package_root'},active_objects=list(settings['active_object_ids']),partition='unpartitioned',seed=plan.effective_settings['execution'].get('seed',0),
        task_code=_plain(plan.effective_settings['task_modules_sha256']),workflow_code={k:v for k,v in plan.effective_settings['code_files'].items()},
        rng_policy='source_base_seed_plus_attempt_minus_one',recording=dict(position_target_policy='saturation_inward_v1',joint_targets_role='applied',joint_order=list(plan.scene.scene['robot']['joint_order']),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',task_phase='post_step',fps=30,resolution=[640,480],codec='libx264',crf=18))


def reset_placements(plan,env,seed,*,env_index=0):
    import torch
    from ...tasks.placement import PlacementRequest,validate_v8_pose
    from scene_contract.transforms import resolve_transform
    from scipy.spatial.transform import Rotation
    from ...tasks.placement import uses_workspace_random,workspace_reset_poses,validate_workspace_payload
    from .state import _matrix,restore_episode
    initial=initial_state(env,env_index)
    origin=env.scene.env_origins[env_index].detach().cpu().numpy().astype(np.float64)
    def canonical(pose):
        result=_matrix(pose);result[:3,3]-=origin;return result
    if uses_workspace_random(plan):
        occupied={}
        for name,spec in env.cfg.workbench_inputs['compiled_physics']['objects'].items():
            if not spec.get('collision'):continue
            if name in initial['rigid_object']:occupied[name]=canonical(initial['rigid_object'][name]['root_pose'][0])
            elif name in plan.scene.scene['objects']:
                occupied[name]=resolve_transform(plan.scene.scene['frames'],source=plan.scene.scene['objects'][name]['frame_id'],target='world')
        poses,records=workspace_reset_poses(plan,occupied)
        for name,pose in poses:
            quat=Rotation.from_matrix(pose[:3,:3]).as_quat()[[3,0,1,2]]
            initial['rigid_object'][name]['root_pose']=np.r_[pose[:3,3]+origin,quat][None];initial['rigid_object'][name]['root_velocity'][:]=0
        payloads=[]
        for name,_ in poses:
            # Native write_root_pose uses float32; validate that payload, not only
            # the ideal float64 sampled pose. No numeric adjustment is allowed.
            payload=initial['rigid_object'][name]['root_pose'][0].astype(np.float32)
            actual=canonical(payload);payloads.append((name,actual));records[name]['payload_world_pose']=actual.tolist()
        try:validate_workspace_payload(plan,payloads,occupied)
        except Exception as error:
            error.placement_records=records;raise
        try:
            restore_episode(env,[env_index],initial)
            observed=initial_state(env,env_index)
        except Exception as error:
            for record in records.values():record['applied']='unknown'
            error.placement_records=records;raise
        for name,_ in poses:
            actual=canonical(observed['rigid_object'][name]['root_pose'][0])
            records[name].update(applied=True,applied_world_pose=actual.tolist(),observed_world_pose=actual.tolist(),physical_collision_checked=False)
        return records
    rng=np.random.default_rng(seed)
    from .state import _matrix,restore_episode
    occupied={n:canonical(initial['rigid_object'][n]['root_pose'][0]) for n in plan.object_order}
    for name in plan.object_order:
        binding=plan.function_bindings['objects.'+name+'.placement'];params=binding.params
        world=resolve_transform(plan.scene.scene['frames'],source=params.frame,target='world');inverse=np.linalg.inv(world)
        request=PlacementRequest(name,params.frame,params.support,occupied_poses={n:inverse@p for n,p in occupied.items() if n!=name},rng=rng,rules_id=params.rules,**dict(binding.request_fields))
        result=plan.tasks.functions[binding.name].callable(request,params=params)
        if params.rules=='v8_preserved':
            context=params._context;validate_v8_pose(result.pose,context['object_dimensions'],context['support_pose'],context['support_dimensions'],object_id=name)
        pose=world@result.pose;quat=Rotation.from_matrix(pose[:3,:3]).as_quat()[[3,0,1,2]]
        initial['rigid_object'][name]['root_pose']=np.r_[pose[:3,3]+origin,quat][None];initial['rigid_object'][name]['root_velocity'][:]=0;occupied[name]=pose
    restore_episode(env,[env_index],initial)


def run(plan,*,events,commands,leader=None):
    import tempfile
    from isaaclab.envs import ManagerBasedEnv
    from .env_cfg import build_env_cfg,execution_inputs
    from ...generation.mimic import bind_kinematics
    from ...recipe import verify_prepared_inputs
    from ...data.native import NativeRun,resume_to,load_catalog,history,file_sha256
    from ...robot.calibration import mapper_from_scene,JOINTS,values
    from ...run import StageResult
    from ...data.native import collection_settings
    verify_prepared_inputs(plan)
    if 'source_dataset' in plan.resolved_inputs:return run_recorded(plan,events=events,commands=commands)
    if plan.effective_settings['execution'].get('num_envs',1)>1:raise ValueError('Multi-env Source requires independent recorded streams; no Leader broadcast')
    settings=settings_for(plan);opts=collection_settings(plan.effective_settings['execution'],plan.output_path,stage='source')
    if any(b.kind!='placement' for b in plan.function_bindings.values()):raise ValueError('Optional Source signal/metrics execution unsupported')
    if not {'episode_time_s','reset_time_s'}<=opts.keys():raise ValueError('Source timing must be explicit')
    inputs=execution_inputs(plan.scene,settings);kin=bind_kinematics(inputs['robot_urdf'],model_sha256=file_sha256(inputs['robot_urdf']),joint_order=JOINTS)
    env=owner=None;device=leader;cancelled=False
    plan.output_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='isaac-source-',dir=plan.output_path.parent) as temporary:
        try:
            env=ManagerBasedEnv(cfg=build_env_cfg(plan.scene,settings,runtime_directory=Path(temporary)/'runtime'));env.reset()
            execution=execution_contract(plan,settings);execution.update(episodes=opts['episodes'],episode_time_s=opts['episode_time_s'],reset_time_s=opts['reset_time_s'],device_identity=dict(plan.resolved_inputs['device_profile']))
            previous=plan.resolved_inputs.get('resume_dataset');owner=resume_to(previous['path'],plan.output_path,execution) if previous else NativeRun(plan.output_path,execution,append=opts.get('resume',False))
            count=len(load_catalog(owner.root).episodes)
            if count>=opts['episodes']:raise ValueError('Cumulative target must exceed previous completed count')
            device=device if device is not None else create_leader(plan);device.connect()
            mapper=mapper_from_scene(plan.scene,plan.input_documents['device_profile']['calibration_id'],role='leader',phase='device_observation')
            if device.precision_mapper.metadata()['sha256']!=mapper.metadata()['sha256']:raise ValueError('Leader mapping changed')
            device.activate()
            def read_target():
                native,_=device.read();measured=values(device.precision_mapper.calibrated_to_observation(native,raw=device.last_raw))
                return np.array([measured[n] for n in JOINTS])
            while count<opts['episodes']:
                number=max((r['attempt'] for r in history(owner.root)),default=0)+1;segment=owner.segment('source-'+str(number));claim=owner.claim_attempt(segment);eid='source-'+str(number)
                env.reset();reset_placements(plan,env,claim['seed'])
                from ...robot.control import TargetRejected
                try:
                    ep,media,initial,status=collect_episode(env,segment,kin,episode_id=eid,seed=claim['seed'],frames=int(np.ceil(opts['episode_time_s']*30)),read_target=read_target,events=events,commands=commands,duration_s=opts['episode_time_s'],realtime=True)
                except TargetRejected as error:
                    segment.record_attempt(claim,status='failure',diagnostics={'category':'action_safety_rejection',**error.diagnostics})
                    segment.commit();raise
                if ep is not None:
                    segment.write_episode(ep,episode_id=eid,metadata={'success_source':'recording_only','saturation':command_summary(ep),'initial_state_owner':'this_source_episode','seed':claim['seed']},media=media)
                    for path in media.values():Path(path).unlink()
                    segment.record_attempt(claim,status='success',episode_id=eid);segment.commit();count+=1;publish_event(owner.root,eid,events)
                else:
                    for path in segment.folder.glob('*.mp4'):path.unlink()
                    segment.record_attempt(claim,status='cancelled' if status=='cancelled' else 'failure',diagnostics={'reason':status});segment.commit()
                if status=='cancelled':cancelled=True;break
                until=time.monotonic()+opts['reset_time_s'];state=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False,inactive=True)
                while count<opts['episodes'] and time.monotonic()<until:
                    control_commands(commands(),state,events,tick=0,episode_id=eid)
                    if state['cancelled']:cancelled=True;break
                    time.sleep(.01)
                if cancelled:break
            return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'attempts':len(history(owner.root)),'existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'target_reached':count>=opts['episodes']})
        finally:
            try:
                if device is not None:device.close()
            finally:
                try:
                    if owner is not None:owner.close()
                finally:
                    if env is not None:env.close()


def run_recorded(plan,*,events,commands):
    """Actual Isaac collection from an explicit numerical target stream, no bus."""
    import tempfile
    from isaaclab.envs import ManagerBasedEnv
    from .env_cfg import build_env_cfg,execution_inputs
    from .state import restore_episode
    from robot_learning_workbench.data.recording import validate_recording
    from ...data.native import NativeRun,load_catalog,open_native,history,collection_settings,file_sha256
    from ...generation.mimic import bind_kinematics
    from ...recipe import _plain
    from ...run import StageResult
    from ...robot.calibration import JOINTS
    catalog=load_catalog(plan.resolved_inputs['source_dataset']['path']);validate_recording(catalog.execution.get('recording',{}))
    if catalog.execution.get('stage')!='source' or catalog.execution.get('engine')!='isaac' or not catalog.episodes:raise ValueError('Matching nonempty Isaac Source streams required')
    settings=settings_for(plan,catalog.execution['model_config']);opts=collection_settings(plan.effective_settings['execution'],plan.output_path,stage='source')
    if catalog.execution.get('model_sha256')!=model_identity(plan.scene,settings):raise ValueError('Source stream model identity differs')
    execution=execution_contract(plan,settings);execution.update(episodes=opts['episodes'],source_stream_identity=_plain(catalog.identity),source_input_kind='recorded_target_stream')
    inputs=execution_inputs(plan.scene,settings);kin=bind_kinematics(inputs['robot_urdf'],model_sha256=file_sha256(inputs['robot_urdf']),joint_order=JOINTS)
    env=None;owner=None;cancelled=False;plan.output_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='isaac-source-recorded-',dir=plan.output_path.parent) as temp:
        try:
            owner=NativeRun(plan.output_path,execution,append=opts.get('resume',False));count=len(load_catalog(owner.root).episodes)
            env=ManagerBasedEnv(cfg=build_env_cfg(plan.scene,settings,num_envs=opts.get('num_envs',1),runtime_directory=Path(temp)/'runtime'));env.reset()
            if env.num_envs>1:return collect_vector(plan,owner,env,kin,catalog,opts,events=events,commands=commands)
            baseline=initial_state(env)
            while count<opts['episodes']:
                attempt=max((r['attempt'] for r in history(owner.root)),default=0)+1;source=catalog.episodes[(attempt-1)%len(catalog.episodes)]
                reader=open_native(source)
                try:recorded=reader.load_episode(source.key,'cpu')
                finally:reader.close()
                targets=recorded.data['joint_targets'].numpy()[source.start:source.stop if source.stop is not None else source.num_frames].copy();stream=iter(targets)
                if plan.object_order:
                    restore_episode(env,[0],baseline);reset_placements(plan,env,opts.get('seed',0)+attempt-1)
                else:
                    from robot_learning_workbench.data.recording import recorded_initial
                    restore_episode(env,[0],recorded_initial(recorded),is_relative=True)
                segment=owner.segment('source-'+str(attempt));claim=owner.claim_attempt(segment);eid='source-'+str(attempt)
                try:ep,media,initial,status=collect_episode(env,segment,kin,episode_id=eid,seed=claim['seed'],frames=len(targets),read_target=lambda:next(stream),events=events,commands=commands)
                except Exception as error:
                    segment.record_attempt(claim,status='failure',diagnostics={'code':getattr(error,'code','COLLECTION_ERROR'),'reason':str(error),'effect':getattr(error,'effect','unknown')});segment.commit();raise
                if ep is not None:
                    segment.write_episode(ep,episode_id=eid,metadata={'success_source':'recording_only','input_kind':'recorded_target_stream','source_initial_state_reused':not bool(plan.object_order),'env_index':0,'source_lineage':{'dataset':_plain(catalog.identity),'episode_id':source.episode_id},'initial_state_owner':'this_source_episode','saturation':command_summary(ep)},media=media)
                    for path in media.values():Path(path).unlink()
                    segment.record_attempt(claim,status='success',episode_id=eid);segment.commit();count+=1;publish_event(owner.root,eid,events)
                else:segment.record_attempt(claim,status='cancelled' if status=='cancelled' else 'failure',diagnostics={'reason':status});segment.commit()
                if status=='cancelled':cancelled=True;break
            return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'target_reached':count>=opts['episodes'],'attempts':len(history(owner.root))})
        finally:
            try:
                if env is not None:env.close()
            finally:
                if owner is not None:owner.close()


def abort_streams(streams,pending,*,cancelled):
    """Close every generator/video and seal only empty failed/cancelled attempts."""
    errors=[]
    for i,stream in tuple(streams.items()):
        try:stream.close()
        except Exception as error:errors.append(error)
        segment,claim,*_=pending[i]
        try:
            segment.record_attempt(claim,status='cancelled' if cancelled else 'failure',diagnostics={'env_index':i,'category':'cancelled' if cancelled else 'vector_execution_error','effect':'unknown'});segment.commit()
        except Exception as error:errors.append(error)
    if errors:raise ExceptionGroup('Vector stream cleanup failed',errors)


def collect_vector(plan,owner,env,kin,catalog,opts,*,events,commands):
    """Independent numerical Source streams, one official vector physics step."""
    from .mdp import advance_streams
    from .state import restore_episode
    from .env_cfg import execution_inputs
    from robot_learning_workbench.commands import command_channels
    from robot_learning_workbench.data.recording import recorded_initial
    from ...generation.mimic import bind_kinematics
    from ...data.native import load_catalog,history,open_native
    from ...recipe import _plain
    from ...run import StageResult
    from ...robot.calibration import JOINTS
    n=env.num_envs
    if len(catalog.episodes)<n:raise ValueError('Multi-env Source needs at least env_num explicit Source streams')
    urdf=execution_inputs(plan.scene,catalog.execution['model_config'])['robot_urdf']
    kinematics=[bind_kinematics(urdf,model_sha256=kin.model_sha256,joint_order=JOINTS) for _ in range(n)]
    baseline=[initial_state(env,i) for i in range(n)];polls,send=command_channels(commands,events,n,vector=True)
    count=len(load_catalog(owner.root).episodes);attempt=max((r['attempt'] for r in history(owner.root)),default=0);available=list(range(n));streams={};pending={};ready={};cancelled=False
    try:
        while streams or (available and count<opts['episodes'] and not cancelled):
            while available and count+len(streams)<opts['episodes'] and not cancelled:
                i=available.pop(0);attempt+=1;source=catalog.episodes[(attempt-1)%len(catalog.episodes)];reader=open_native(source)
                try:recorded=reader.load_episode(source.key,'cpu')
                finally:reader.close()
                targets=recorded.data['joint_targets'].numpy()[source.start:source.stop if source.stop is not None else source.num_frames].copy()
                if plan.object_order:restore_episode(env,[i],baseline[i]);reset_placements(plan,env,opts.get('seed',0)+attempt-1,env_index=i)
                else:restore_episode(env,[i],recorded_initial(recorded),is_relative=True)
                segment=owner.segment('source-'+str(attempt));claim=owner.claim_attempt(segment)
                streams[i]=collection_steps(env,segment,kinematics[i],episode_id='source-'+str(attempt),seed=claim['seed'],frames=len(targets),read_target=lambda stream=iter(targets):next(stream),events=send,commands=polls[i],env_index=i)
                pending[i]=(segment,claim,source)
            if not streams:break
            send.refresh()
            if send.cancelled():cancelled=True;send.ack_cancel();break
            finished,_=advance_streams(env,streams,ready,pause_check=send.paused)
            for i,result in finished.items():
                segment,claim,source=pending.pop(i);streams.pop(i);ready.pop(i,None);available.append(i);eid='source-'+str(claim['attempt'])
                if isinstance(result,Exception):
                    segment.record_attempt(claim,status='failure',diagnostics={'env_index':i,'reason':str(result),'effect':getattr(result,'effect','unknown')});segment.commit();raise result
                ep,media,initial,status=result
                if status=='completed':
                    segment.write_episode(ep,episode_id=eid,metadata={'success_source':'recording_only','input_kind':'recorded_target_stream','source_initial_state_reused':not bool(plan.object_order),'env_index':i,'initial_frame':'scene_world','engine_env_origin':env.scene.env_origins[i].cpu().numpy().tolist(),'source_lineage':{'dataset':_plain(catalog.identity),'episode_id':source.episode_id,'frame_range':[source.start,source.stop or source.num_frames]},'initial_state_owner':'this_source_episode','saturation':command_summary(ep)},media=media)
                    for path in media.values():Path(path).unlink()
                    segment.record_attempt(claim,status='success',episode_id=eid);count+=1
                else:segment.record_attempt(claim,status='cancelled' if status=='cancelled' else 'failure',diagnostics={'env_index':i,'reason':status})
                segment.commit()
                if status=='completed':publish_event(owner.root,eid,send)
                cancelled|=status=='cancelled'
            if cancelled:break
    finally:abort_streams(streams,pending,cancelled=cancelled)
    return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'env_num':n,'existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'target_reached':count>=opts['episodes'],'attempts':attempt})
