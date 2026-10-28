"""Native Isaac Source replay and post-step Task acceptance; no IK execution."""
from pathlib import Path
import time
import numpy as np
from .source import record_frame,settings_for,model_identity
from .state import initial_state,restore_episode,read_sample
from .mdp import apply_joint_targets,validate_targets
from ..mujoco.source import add_initial,control_commands,step_completed,publish_event
from ..mujoco.annotation import accept_annotation,validate_recording,validate_source_ranges
from ...data.native import native_api,open_native,load_catalog,NativeRun
from ...data.video import AsyncVideoWriter


def task_sample(env,plan,phase,tick,episode_id,signals,*,params=None,env_index=0):
    """Preserve original GPU float32 target-local corners and speed comparison."""
    import torch
    from isaaclab.utils.math import subtract_frame_transforms,quat_apply
    params=plan.function_bindings['acceptance'].params if params is None else params
    row=read_sample(env,env_index,phase,tick,episode_id=episode_id,object_id=params.object);row['signals']=dict(signals)
    cube=env.scene[params.object];target=env.scene[params.target]
    pos,quat=subtract_frame_transforms(target.data.root_pos_w,target.data.root_quat_w,cube.data.root_pos_w,cube.data.root_quat_w)
    size=plan.scene.scene['objects'][params.object]['task_geometry']['dimensions_m']
    corners=torch.tensor([[a*size[0]/2,b*size[1]/2,c*size[2]/2] for a in (-1,1) for b in (-1,1) for c in (-1,1)],device=env.device)
    points=quat_apply(quat[:,None,:].expand(-1,8,-1).reshape(-1,4),corners[None].expand(env.num_envs,-1,-1).reshape(-1,3)).reshape(env.num_envs,8,3)+pos[:,None,:]
    row['placement_points']={params.object:{'target_id':params.target,'points':points[env_index]}}
    row['linear_velocities'][params.object]=cube.data.root_lin_vel_w[env_index].clone()
    return row


def replay_episode(plan,env,source,segment,*,events,commands):
    from .mdp import complete_episode
    return complete_episode(env,replay_steps(plan,env,source,segment,events=events,commands=commands))


def replay_steps(plan,env,source,segment,*,events,commands,env_index=0):
    import torch
    from ...tasks.pick_place import v8_placement
    handler=open_native(source)
    try:recorded=handler.load_episode(source.key,'cpu')
    finally:handler.close()
    def arrays(value):return {k:arrays(v) if isinstance(v,dict) else v.numpy().copy() for k,v in value.items()}
    original=arrays(recorded.data['initial_state']);restore_episode(env,[env_index],original,is_relative=True)
    targets=recorded.data['joint_targets'].numpy();goals=recorded.data['obs']['datagen_info']['target_eef_pose']['tool0'].numpy()
    bounds=np.broadcast_to(env.cfg.workbench_joint_limits_rad,(len(targets),6,2));applied_targets=validate_targets(targets,bounds)
    ep=native_api()[0]();ep.seed=recorded.seed;add_initial(ep,initial_state(env,env_index,relative=True))
    base=np.asarray(env.cfg.workbench_inputs['profile']['robot_base']['T_world']);signals={};trackers={};eid=source.episode_id
    for role,binding in plan.function_bindings.items():
        if binding.kind=='tracker':trackers[role.split('.',1)[1]]=plan.tasks.functions[binding.name].callable(params=binding.params,episode={'episode_id':eid,'env_index':env_index,'control_dt_s':env.step_dt})
    controls=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False);videos={};previous=None;first=None;trace=[];tick=0
    acceptance=plan.function_bindings['acceptance']
    try:
        for name in ('side','wrist'):videos[name]=AsyncVideoWriter(segment.folder/(name+'.mp4'),env_index=env_index)
        while tick<len(targets):
            events({'kind':'status','payload':{'episode_id':eid,'env_index':env_index,'tick':tick,'progress':{'frames':tick,'total':len(targets)}}})
            control_commands(commands(),controls,events,tick=tick,episode_id=eid,env_index=env_index)
            if controls['cancelled'] or controls['skipped']:return None,{},dict(status='cancelled' if controls['cancelled'] else 'skipped',frames=tick)
            if controls['paused'] and not controls['steps']:yield None;continue
            before=task_sample(env,plan,'pre_step',tick,eid,signals,env_index=env_index);pregrasp=bool(signals.get('grasp') and signals['grasp'].value)
            target=applied_targets[tick]
            record_frame(ep,before,goals[tick],target,time_s=tick/30,base=base,signals={'grasp':pregrasp,'place':v8_placement(before,params=acceptance.params)},previous_pose=previous,command_requested=targets[tick],command_limits=bounds[tick])
            for name,writer in videos.items():writer.write(before['cameras'][name]['rgb'])
            yield target
            post=task_sample(env,plan,'post_step',tick,eid,signals,env_index=env_index)
            for name,tracker in trackers.items():signals[name]=tracker.update(post)
            if signals.get('grasp') and signals['grasp'].value and first is None:first=tick
            trace.append({'tick':tick,'pre_grasp':pregrasp,'post_grasp':bool(signals.get('grasp') and signals['grasp'].value),'q':post['joint_positions'].tolist(),'qd':post['joint_velocities'].tolist(),'object_pose':post['object_poses'][acceptance.params.object].tolist(),'forces':post['contacts']['force_w'].tolist()})
            previous=goals[tick];step_completed(controls,events,tick);tick+=1
        final=task_sample(env,plan,'episode_end',tick-1,eid,signals,env_index=env_index);passed=plan.tasks.functions[acceptance.name].callable(final,params=acceptance.params)
        if type(passed) is not bool:raise ValueError('Task acceptance must return bool')
        accepted,mark=accept_annotation(passed,tick,plan.effective_settings['execution']['mode'],controls['marks'])
        report=dict(env_index=env_index,initial_frame='scene_world',engine_env_origin=env.scene.env_origins[env_index].cpu().numpy().tolist(),status='success' if accepted else 'failure',physical_replay_passed=passed,frames=tick,first_grasp_post_tick=first,trace=trace,initial_state_owner='annotation_replay_start',source_initial_state=original)
        from ..mujoco.source import command_summary
        report['saturation']=command_summary(ep)
        if not accepted:return None,{},report
        ep.pre_export();ep.success=True;ep.data['obs']['events']['place'][-1]=1
        if mark is not None:
            signal=torch.from_numpy((np.arange(tick)>=mark).astype(np.uint8)[:,None]);ep.data['obs']['events']['grasp']=signal;ep.data['obs']['datagen_info']['subtask_term_signals']['grasp']=signal
        report['annotation']={'grasp':int(torch.nonzero(ep.data['obs']['events']['grasp'][:,0])[0]),'method':'manual' if mark is not None else 'auto'}
        for writer in videos.values():writer.close()
        return ep,{k:v.video_path for k,v in videos.items()},report
    finally:
        for writer in videos.values():
            if not writer._closed:writer.abort()


def validate_source(catalog):
    validate_source_ranges(catalog)
    if catalog.execution.get('stage')!='source' or catalog.execution.get('engine')!='isaac':raise ValueError('Original Isaac Source required')
    validate_recording(catalog.execution.get('recording',{}))
    if not catalog.episodes:raise ValueError('Nonempty complete Source episodes required')


def run(plan,*,events,commands):
    import tempfile
    from isaaclab.envs import ManagerBasedEnv
    from .env_cfg import build_env_cfg
    from ...recipe import verify_prepared_inputs,_plain
    from ...run import StageResult
    verify_prepared_inputs(plan);catalog=load_catalog(plan.resolved_inputs['dataset']['path'])
    validate_source(catalog);settings=settings_for(plan,catalog.execution.get('model_config'))
    if catalog.execution.get('model_sha256')!=model_identity(plan.scene,settings):raise ValueError('Source physics/model identity differs')
    if any(b.kind=='metrics' for b in plan.function_bindings.values()):raise ValueError('Standalone metrics execution is unsupported')
    execution={**catalog.execution,'stage':'annotation','source_dataset':_plain(catalog.identity),'annotation_mode':plan.effective_settings['execution']['mode'],'task_code':_plain(plan.effective_settings['task_modules_sha256']),'workflow_code':_plain(plan.effective_settings['code_files'])}
    execution['recording']={**execution['recording'],'position_target_policy':'saturation_inward_v1','joint_targets_role':'applied'}
    env=None;saved=0;cancelled=False;reports=[]
    plan.output_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='isaac-annotation-',dir=plan.output_path.parent) as temporary:
        try:
            env=ManagerBasedEnv(cfg=build_env_cfg(plan.scene,settings,num_envs=plan.effective_settings['execution'].get('num_envs',1),runtime_directory=Path(temporary)/'runtime'));env.reset()
            with NativeRun(plan.output_path,execution) as owner:
                if env.num_envs>1:return replay_vector(plan,owner,env,catalog,events=events,commands=commands)
                for index,source in enumerate(catalog.episodes):
                    seg=owner.segment('annotation-'+str(index),request={'source_dataset':_plain(catalog.identity),'episode':source.episode_id});claim=owner.claim_attempt(seg)
                    try:ep,media,report=replay_episode(plan,env,source,seg,events=events,commands=commands)
                    except Exception as error:
                        from ...robot.control import TargetRejected
                        if isinstance(error,TargetRejected):
                            seg.record_attempt(claim,status='failure',diagnostics={'category':'action_safety_rejection',**error.diagnostics});seg.commit()
                        raise
                    summary={k:v for k,v in report.items() if k not in ('trace','source_initial_state')};reports.append(summary)
                    if ep is not None:
                        eid='annotation-'+str(index);seg.write_episode(ep,episode_id=eid,metadata={**{k:v for k,v in report.items() if k!='trace'},'restore_policy':'fixed robot base from Scene; observed root telemetry preserved; joints and object state restored','source_lineage':{'dataset':_plain(catalog.identity),'episode_id':source.episode_id,'key':source.key}},media=media)
                        for p in media.values():Path(p).unlink()
                        seg.record_attempt(claim,status='success',episode_id=eid,diagnostics=summary);seg.commit();saved+=1;publish_event(owner.root,eid,events)
                    else:
                        for p in seg.folder.glob('*.mp4'):p.unlink()
                        seg.record_attempt(claim,status='cancelled' if report['status']=='cancelled' else 'failure',diagnostics=summary);seg.commit()
                    if report['status']=='cancelled':cancelled=True;break
            return StageResult('cancelled' if cancelled else 'completed',(str(plan.output_path),),saved,{'attempts':len(reports),'reports':reports})
        finally:
            if env is not None:env.close()


def replay_vector(plan,owner,env,catalog,*,events,commands):
    from .mdp import advance_streams
    from .source import abort_streams
    from ..mujoco.source import command_channels
    from ...recipe import _plain
    from ...run import StageResult
    n=env.num_envs;polls,send=command_channels(commands,events,n,vector=True);sources=iter(enumerate(catalog.episodes));streams={};pending={};ready={};saved=0;reports=[];cancelled=False
    def schedule(i):
        item=next(sources,None)
        if item is None:return
        ordinal,source=item;seg=owner.segment('annotation-'+str(ordinal),request={'source_dataset':_plain(catalog.identity),'episode':source.episode_id});claim=owner.claim_attempt(seg)
        streams[i]=replay_steps(plan,env,source,seg,events=send,commands=polls[i],env_index=i);pending[i]=(seg,claim,source)
    try:
        for i in range(n):schedule(i)
        while streams:
            send.refresh()
            if send.cancelled():cancelled=True;send.ack_cancel();break
            done,_=advance_streams(env,streams,ready,pause_check=send.paused)
            for i,result in done.items():
                seg,claim,source=pending.pop(i);streams.pop(i);ready.pop(i,None)
                if isinstance(result,Exception):
                    seg.record_attempt(claim,status='failure',diagnostics={'env_index':i,'reason':str(result),'effect':getattr(result,'effect','unknown')});seg.commit();raise result
                ep,media,report=result;summary={k:v for k,v in report.items() if k not in ('trace','source_initial_state')};reports.append(summary)
                if ep is not None:
                    eid='annotation-'+str(claim['attempt']-1);seg.write_episode(ep,episode_id=eid,metadata={**{k:v for k,v in report.items() if k!='trace'},'source_lineage':{'dataset':_plain(catalog.identity),'episode_id':source.episode_id,'key':source.key}},media=media)
                    for p in media.values():Path(p).unlink()
                    seg.record_attempt(claim,status='success',episode_id=eid,diagnostics=summary);saved+=1
                else:seg.record_attempt(claim,status='cancelled' if report['status']=='cancelled' else 'failure',diagnostics=summary)
                seg.commit()
                if ep is not None:publish_event(owner.root,eid,send)
                cancelled|=report['status']=='cancelled'
                if not cancelled:schedule(i)
            if cancelled:break
    finally:abort_streams(streams,pending,cancelled=cancelled)
    return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),saved,{'env_num':n,'attempts':len(reports),'reports':reports})
