"""MuJoCo Source: caller-owned input, direct stepping, official Native recording.

MuJoCo 3.3.7 https://mujoco.readthedocs.io/en/3.3.7/python.html
Isaac Lab EpisodeData is a CPU data API, never an Isaac environment here.
"""
from dataclasses import asdict
from pathlib import Path
import time
import numpy as np
from scipy.spatial.transform import Rotation
from .model import JOINTS,ModelConfig,build_model
from .state import read_sample,restore_episode,snapshot
from .control import step,command_target
from ...data.native import NativeRun,native_api,load_catalog,digest,history,resume_to
from ...data.video import AsyncVideoWriter


from ...data.recording import pose7, record_frame, add_initial, collection_coordinates, command_summary, recorded_initial
from ...commands import control_commands, step_completed, command_channels
from ...data.publication import publish_event
from ...robot.configuration import create_leader

def initial_arrays(model,data,b):
    """Measured world state; opaque integration snapshot is recorded separately."""
    import mujoco
    robot={'root_pose':pose7(b.world_from_robot_base)[None],'root_velocity':np.zeros((1,6)),
           'joint_position':data.qpos[list(b.q_indices)][None].copy(),'joint_velocity':data.qvel[list(b.v_indices)][None].copy()}
    objects={}
    for name,index in b.object_body_ids.items():
        pose=np.eye(4);pose[:3,3]=data.xpos[index];pose[:3,:3]=data.xmat[index].reshape(3,3)
        twist=np.empty(6);mujoco.mj_objectVelocity(model,data,mujoco.mjtObj.mjOBJ_BODY,index,twist,0)
        objects[name]={'root_pose':pose7(pose)[None],'root_velocity':np.r_[twist[3:],twist[:3]][None]}
    return {'articulation':{'robot':robot},'rigid_object':objects}


def collect_episode(model,data,b,segment,*,episode_id,seed,frames,read_target,events,commands,realtime=False,duration_s=None,env_index=0):
    """Actual MuJoCo collection. read_target returns measured Leader model radians.

    Recorded input fixtures may supply the same boundary without opening a device;
    that tests simulation collection, not physical Teleoperation.
    """
    import mujoco
    episode=native_api()[0]();episode.seed=seed;episode.success=True
    initial=initial_arrays(model,data,b);opaque=snapshot(model,data,b);add_initial(episode,initial)
    controls=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False)
    videos={};previous=None;fk=mujoco.MjData(model);count=0
    try:
        with mujoco.Renderer(model,height=480,width=640) as renderer:
            for camera in ('side','wrist'):
                videos[camera]=AsyncVideoWriter(segment.folder/(camera+'.mp4'),fps=30,width=640,height=480,env_index=env_index)
            deadline=None if duration_s is None else time.monotonic()+duration_s
            while count<frames and (deadline is None or time.monotonic()<deadline):
                started=time.monotonic()
                events({'kind':'status','payload':{'episode_id':episode_id,'env_index':env_index,'tick':count,'progress':{'frames':count}}})
                control_commands(commands(),controls,events,tick=count,episode_id=episode_id,env_index=env_index)
                if controls['cancelled']:return episode,{},opaque,'cancelled'
                if controls.get('discard'):return episode,{},opaque,'discarded'
                if controls.get('save'):
                    if not count:return episode,{},opaque,'discarded'
                    break
                if controls['paused'] and not controls['steps']:
                    time.sleep(.01)
                    if deadline is not None:deadline+=time.monotonic()-started
                    continue
                requested=np.asarray(read_target())
                target=source_target(requested,b)
                requested=requested.astype(np.float64)
                sample=read_sample(model,data,b,'pre_step',count,episode_id=episode_id,env_index=env_index)
                fk.qpos[:]=data.qpos;fk.qpos[list(b.q_indices)]=target;mujoco.mj_forward(model,fk)
                target_pose=np.eye(4);target_pose[:3,3]=fk.site_xpos[b.eef_id];target_pose[:3,:3]=fk.site_xmat[b.eef_id].reshape(3,3)
                target_pose=np.linalg.inv(b.world_from_robot_base)@target_pose
                record_frame(episode,sample,target_pose,target,time_s=float(data.time),requested=requested,base=b.world_from_robot_base,previous_pose=previous,command_requested=requested,command_limits=source_limits(b))
                previous=target_pose
                for camera,writer in videos.items():
                    renderer.update_scene(data,camera=camera);writer.write(renderer.render())
                step(model,data,b,target);count+=1
                step_completed(controls,events,count-1)
                if realtime:time.sleep(max(0,1/30-(time.monotonic()-started)))
        if not count:return episode,{},opaque,'discarded'
        for writer in videos.values():writer.close()
        return episode,{name:writer.video_path for name,writer in videos.items()},opaque,'completed'
    except Exception as error:
        from ...robot.control import TargetRejected
        if isinstance(error,TargetRejected):error.diagnostics['applied_steps']=count
        raise
    finally:
        for writer in videos.values():
            if not writer._closed:writer.abort()


def execution_contract(plan,b,cfg):
    from ...recipe import _plain
    from ...data.native import file_sha256
    return dict(stage=plan.stage,engine='mujoco',scene_identity=_plain(plan.scene_identity),calibration=_plain(plan.scene.calibration),
        model_sha256=b.model_sha256,urdf_sha256=b.urdf_sha256,active_objects=list(b.dynamic_objects),partition='unpartitioned',
        task_code=_plain(plan.effective_settings['task_modules_sha256']),workflow_code={Path(k).name:v for k,v in plan.effective_settings['code_files'].items()},
        recording=dict(position_target_policy='saturation_inward_v1',joint_targets_role='applied',joint_order=list(JOINTS),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',
                       task_phase='post_step',collection_units=['rad']*5+['fraction'],collection_gripper_endpoints_rad=[0.,float(np.deg2rad(100))],fps=30,resolution=[640,480],codec='libx264',crf=18),
        seed=plan.effective_settings['execution'].get('seed',0),rng_policy='source_base_seed_plus_attempt_minus_one',
        model_config=_plain(asdict(cfg)),placements={k:_plain(v) for k,v in plan.function_bindings.items() if v.kind=='placement'})


def resolved_model_config(plan,recorded=None):
    from ...recipe import _plain
    settings=plan.effective_settings['execution']
    if plan.engine!='mujoco':raise ValueError('MuJoCo configuration required')
    raw=recorded if recorded is not None else plan.input_documents.get('engine_config')
    if raw is None:raise ValueError('Explicit engine_config ModelConfig required')
    cfg=ModelConfig(**_plain(raw))
    if cfg.width!=640 or cfg.height!=480 or cfg.physics_timestep_s*cfg.decimation!=1/30:raise ValueError('Side/Wrist 640x480 at 30Hz required')
    if plan.stage=='source' and plan.object_order and tuple(cfg.active_object_ids)!=tuple(plan.object_order):raise ValueError('Model object order differs from Recipe')
    return cfg


def reset_placements(plan,model,data,b,seed):
    from .state import reset_object_poses
    from ...tasks.placement import PlacementRequest
    from scene_contract.transforms import resolve_transform
    from ...tasks.placement import uses_workspace_random,workspace_reset_poses,validate_workspace_payload
    if uses_workspace_random(plan):
        occupied={}
        for name,body in b.object_body_ids.items():
            if any(model.geom_contype[g] and model.geom_bodyid[g]==body for g in range(model.ngeom)):
                pose=np.eye(4);pose[:3,:3]=data.xmat[body].reshape(3,3);pose[:3,3]=data.xpos[body];occupied[name]=pose
        poses,records=workspace_reset_poses(plan,occupied)
        from scipy.spatial.transform import Rotation
        payloads=[]
        for name,pose in poses:
            # Match reset_object_poses' exact matrix -> quaternion -> matrix path.
            payload=pose.copy();quat=Rotation.from_matrix(pose[:3,:3]).as_quat();payload[:3,:3]=Rotation.from_quat(quat).as_matrix()
            payloads.append((name,payload));records[name]['payload_world_pose']=payload.tolist()
        try:validate_workspace_payload(plan,payloads,occupied)
        except Exception as error:
            error.placement_records=records;raise
        try:reset_object_poses(model,data,b,poses)
        except Exception as error:
            if isinstance(error,ValueError) and str(error)=='Reset pose penetrates Collision geometry':
                from ...tasks.placement import _fail
                _fail('INVALID_PLACEMENT',plan.object_order[0],'Native collision query rejected batch; integration state rolled back',
                      placements=records,physical_collision_checked=True,effect='rolled_back')
            for record in records.values():record['applied']='unknown'
            error.placement_records=records;raise
        for name,_ in poses:
            body=b.object_body_ids[name];observed=np.eye(4);observed[:3,:3]=data.xmat[body].reshape(3,3);observed[:3,3]=data.xpos[body]
            records[name].update(applied=True,applied_world_pose=observed.tolist(),observed_world_pose=observed.tolist(),physical_collision_checked=True)
        return records
    rng=np.random.default_rng(seed)
    sample=read_sample(model,data,b,'pre_step',0)
    occupied={name:b.world_from_robot_base@sample['object_poses'][name] for name in b.dynamic_objects}
    for name in plan.object_order:
        binding=plan.function_bindings['objects.'+name+'.placement'];params=binding.params
        frame=params.frame;world_from_frame=resolve_transform(plan.scene.scene['frames'],source=frame,target='world')
        poses={key:np.linalg.inv(world_from_frame)@value for key,value in occupied.items() if key!=name}
        request=PlacementRequest(name,frame,params.support,occupied_poses=poses,rng=rng,rules_id=params.rules,**dict(binding.request_fields))
        result=plan.tasks.functions[binding.name].callable(request,params=params)
        if params.rules=='v8_preserved':
            from ...tasks.placement import validate_v8_pose
            context=params._context
            validate_v8_pose(result.pose,context['object_dimensions'],context['support_pose'],context['support_dimensions'],object_id=name)
        pose=world_from_frame@result.pose
        reset_object_poses(model,data,b,[(name,pose)]);occupied[name]=pose


def run(plan,*,events,commands,leader=None):
    """Saved Recipe -> real MuJoCo -> sealed Native segments. No Follower commands."""
    import mujoco
    from ...recipe import verify_prepared_inputs
    from ...run import StageResult
    from ...data.native import collection_settings
    from ...robot.calibration import JOINTS,values
    verify_prepared_inputs(plan)
    if 'source_dataset' in plan.resolved_inputs:return run_recorded(plan,events=events,commands=commands)
    if plan.effective_settings['execution'].get('num_envs',1)>1:raise ValueError('Multi-env Source requires explicit independent recorded streams; no Leader broadcast')
    cfg=resolved_model_config(plan)
    if any(v.kind!='placement' for v in plan.function_bindings.values()):raise ValueError('Source optional signal/metric execution is not supported by this runner')
    opts=collection_settings(plan.effective_settings['execution'],plan.output_path,stage='source')
    if 'episode_time_s' not in opts or 'reset_time_s' not in opts:raise ValueError('Explicit Source episode_time_s/reset_time_s required')
    frames=max(1,int(np.ceil(opts['episode_time_s']*30)))
    model,b=build_model(plan.scene,cfg);data=mujoco.MjData(model);restore_episode(model,data,b,None)
    execution=execution_contract(plan,b,cfg);execution.update(episodes=opts['episodes'],episode_time_s=opts['episode_time_s'],reset_time_s=opts['reset_time_s'],device_identity=dict(plan.resolved_inputs['device_profile']))
    previous=plan.resolved_inputs.get('resume_dataset');owner=None;device=leader;cancelled=False
    try:
        # Model/sensor construction and Resume validation precede motor activation.
        with mujoco.Renderer(model,height=480,width=640) as renderer:
            for camera in ('side','wrist'):renderer.update_scene(data,camera=camera);renderer.render()
        owner=resume_to(previous['path'],plan.output_path,execution) if previous else NativeRun(plan.output_path,execution,append=opts.get('resume',False))
        count=len(load_catalog(owner.root).episodes)
        if count>=opts['episodes']:raise ValueError('Source cumulative Episode target must exceed completed count')
        device=device if device is not None else create_leader(plan)
        device.connect()
        from ...robot.calibration import mapper_from_scene
        spec=plan.input_documents['device_profile']
        expected_mapper=mapper_from_scene(plan.scene,spec['calibration_id'],role='leader',phase='device_observation')
        if device.precision_mapper.metadata()['sha256']!=expected_mapper.metadata()['sha256']:raise ValueError('Connected Leader mapping identity changed')
        device.activate()
        def read_target():
            native,_=device.read()
            measured=values(device.precision_mapper.calibrated_to_observation(native,raw=device.last_raw))
            return np.array([measured[n] for n in JOINTS])
        while count<opts['episodes']:
            number=max((r['attempt'] for r in history(owner.root)),default=0)+1
            seg=owner.segment('source-'+str(number));claim=owner.claim_attempt(seg);eid='source-'+str(number)
            restore_episode(model,data,b,None);reset_placements(plan,model,data,b,claim['seed'])
            from ...robot.control import TargetRejected
            try:
                ep,media,opaque,status=collect_episode(model,data,b,seg,episode_id=eid,seed=claim['seed'],frames=frames,read_target=read_target,events=events,commands=commands,realtime=True,duration_s=opts['episode_time_s'])
            except TargetRejected as error:
                seg.record_attempt(claim,status='failure',diagnostics={'category':'action_safety_rejection',**error.diagnostics})
                seg.commit();raise
            if status in ('cancelled','discarded'):
                for path in seg.folder.glob('*.mp4'):path.unlink()
                seg.record_attempt(claim,status='cancelled' if status=='cancelled' else 'failure',diagnostics={'reason':status});seg.commit()
                if status=='cancelled':cancelled=True;break
            else:
                seg.write_episode(ep,episode_id=eid,metadata={'success_source':'recording_only','saturation':command_summary(ep),'initial_snapshot':opaque,'initial_state_owner':'this_source_episode','seed':claim['seed']},media=media)
                for path in media.values():Path(path).unlink()
                seg.record_attempt(claim,status='success',episode_id=eid);seg.commit();count+=1;publish_event(owner.root,eid,events)
            until=time.monotonic()+opts['reset_time_s'];control=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False,inactive=True)
            while count<opts['episodes'] and time.monotonic()<until:
                control_commands(commands(),control,events,tick=frames,episode_id=eid)
                if control['cancelled']:cancelled=True;break
                time.sleep(.01)
            if cancelled:break
        return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'attempts':len(history(owner.root)),'existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'target_reached':count>=opts['episodes']})
    finally:
        try:
            if device is not None:device.close()
        finally:
            if owner is not None:owner.close()


def source_limits(b):
    """Approved model/canonical Source gripper intersection; no physical approval."""
    lower=b.limits[:,0].copy();upper=b.limits[:,1].copy()
    lower[5]=max(lower[5],0.);upper[5]=min(upper[5],float(np.deg2rad(100)))
    if lower[5]>upper[5]:raise ValueError('Model has no canonical gripper command range')
    return np.column_stack((lower,upper))


def source_target(requested,b):
    from ...robot.control import checked_target
    return command_target(checked_target(requested,limits=source_limits(b),applied_dtype=np.float64),b)


def run_recorded(plan,*,events,commands):
    """Collect actual simulation from explicit recorded target streams, no device."""
    import mujoco
    from ...data.native import collection_settings,open_native
    from ...run import StageResult
    from robot_learning_workbench.data.recording import validate_recording
    from ...recipe import _plain
    catalog=load_catalog(plan.resolved_inputs['source_dataset']['path']);validate_recording(catalog.execution.get('recording',{}))
    if catalog.execution.get('stage')!='source' or catalog.execution.get('engine')!='mujoco' or not catalog.episodes:raise ValueError('Matching nonempty Source target streams required')
    cfg=resolved_model_config(plan,catalog.execution.get('model_config'));model,b=build_model(plan.scene,cfg);data=mujoco.MjData(model)
    if catalog.execution.get('model_sha256')!=b.model_sha256:raise ValueError('Source stream model binding differs')
    opts=collection_settings(plan.effective_settings['execution'],plan.output_path,stage='source')
    execution=execution_contract(plan,b,cfg);execution.update(episodes=opts['episodes'],source_stream_identity=_plain(catalog.identity),source_input_kind='recorded_target_stream')
    with NativeRun(plan.output_path,execution,append=opts.get('resume',False)) as owner:
        if opts.get('num_envs',1)>1:return collect_streams(plan,owner,model,b,catalog,opts,events=events,commands=commands)
        count=len(load_catalog(owner.root).episodes);cancelled=False
        while count<opts['episodes']:
            attempt=max((r['attempt'] for r in history(owner.root)),default=0)+1;source=catalog.episodes[(attempt-1)%len(catalog.episodes)]
            reader=open_native(source)
            try:recorded=reader.load_episode(source.key,'cpu')
            finally:reader.close()
            targets=recorded.data['joint_targets'].numpy()[source.start:source.stop if source.stop is not None else source.num_frames].copy();stream=iter(targets)
            restore_episode(model,data,b,None if plan.object_order else source.metadata.get('initial_snapshot',recorded_initial(recorded)))
            if plan.object_order:reset_placements(plan,model,data,b,opts.get('seed',0)+attempt-1)
            segment=owner.segment('source-'+str(attempt));claim=owner.claim_attempt(segment);eid='source-'+str(attempt)
            try:ep,media,initial,status=collect_episode(model,data,b,segment,episode_id=eid,seed=claim['seed'],frames=len(targets),read_target=lambda:next(stream),events=events,commands=commands)
            except Exception as error:
                segment.record_attempt(claim,status='failure',diagnostics={'code':getattr(error,'code','COLLECTION_ERROR'),'reason':str(error),'effect':getattr(error,'effect','unknown')});segment.commit();raise
            if status=='completed':
                segment.write_episode(ep,episode_id=eid,metadata={'success_source':'recording_only','input_kind':'recorded_target_stream','source_initial_state_reused':not bool(plan.object_order),'env_index':0,'source_lineage':{'dataset':_plain(catalog.identity),'episode_id':source.episode_id},'initial_snapshot':initial,'saturation':command_summary(ep)},media=media)
                for path in media.values():Path(path).unlink()
                segment.record_attempt(claim,status='success',episode_id=eid);segment.commit();count+=1;publish_event(owner.root,eid,events)
            else:
                segment.record_attempt(claim,status='cancelled' if status=='cancelled' else 'failure',diagnostics={'reason':status});segment.commit()
            if status=='cancelled':cancelled=True;break
        return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'target_reached':count>=opts['episodes'],'attempts':len(history(owner.root))})


def collect_streams(plan,owner,model,b,catalog,opts,*,events,commands):
    """Explicit Source streams on independent native MjData, no device fan-out."""
    import mujoco
    from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
    from ...data.native import open_native
    from ...run import StageResult
    from ...recipe import _plain
    n=opts['num_envs']
    if len(catalog.episodes)<n:raise ValueError('Multi-env Source needs at least env_num explicit Source streams')
    states=[mujoco.MjData(model) for _ in range(n)];polls,send=command_channels(commands,events,n)
    def collect(i,source,segment,claim):
        reader=open_native(source)
        try:recorded=reader.load_episode(source.key,'cpu')
        finally:reader.close()
        targets=recorded.data['joint_targets'].numpy()[source.start:source.stop if source.stop is not None else source.num_frames].copy();stream=iter(targets);data=states[i]
        restore_episode(model,data,b,None if plan.object_order else source.metadata.get('initial_snapshot',recorded_initial(recorded)))
        if plan.object_order:reset_placements(plan,model,data,b,claim['seed'])
        return collect_episode(model,data,b,segment,episode_id='source-'+str(claim['attempt']),seed=claim['seed'],frames=len(targets),read_target=lambda:next(stream),events=send,commands=polls[i],env_index=i)
    count=len(load_catalog(owner.root).episodes);attempt=max((r['attempt'] for r in history(owner.root)),default=0);available=list(range(n));pending={};cancelled=False;fatal=None
    with ThreadPoolExecutor(max_workers=n,thread_name_prefix='mujoco-source') as threads:
        try:
            while pending or (available and count<opts['episodes'] and not cancelled and fatal is None):
                while available and count+len(pending)<opts['episodes'] and not cancelled and fatal is None:
                    i=available.pop(0);attempt+=1;source=catalog.episodes[(attempt-1)%len(catalog.episodes)];segment=owner.segment('source-'+str(attempt));claim=owner.claim_attempt(segment)
                    pending[threads.submit(collect,i,source,segment,claim)]=(i,source,segment,claim)
                if not pending:break
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    i,source,segment,claim=pending.pop(future);eid='source-'+str(claim['attempt'])
                    try:ep,media,initial,status=future.result()
                    except Exception as error:
                        segment.record_attempt(claim,status='failure',diagnostics={'env_index':i,'reason':str(error),'effect':getattr(error,'effect','unknown')});segment.commit();fatal=fatal or error;send.stop();continue
                    if status=='completed':
                        segment.write_episode(ep,episode_id=eid,metadata={'env_index':i,'success_source':'recording_only','input_kind':'recorded_target_stream','source_initial_state_reused':not bool(plan.object_order),'initial_snapshot':initial,'saturation':command_summary(ep),'source_lineage':{'dataset':_plain(catalog.identity),'episode_id':source.episode_id,'frame_range':[source.start,source.stop or source.num_frames]}},media=media)
                        for path in media.values():Path(path).unlink()
                        segment.record_attempt(claim,status='success',episode_id=eid);count+=1
                    else:segment.record_attempt(claim,status='cancelled' if status=='cancelled' else 'failure',diagnostics={'env_index':i,'reason':status})
                    segment.commit()
                    if status=='completed':publish_event(owner.root,eid,send)
                    cancelled|=status=='cancelled';available.append(i)
        finally:send.stop()
    if fatal is not None:raise fatal
    return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'env_num':n,'existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'target_reached':count>=opts['episodes'],'attempts':len(history(owner.root))})


