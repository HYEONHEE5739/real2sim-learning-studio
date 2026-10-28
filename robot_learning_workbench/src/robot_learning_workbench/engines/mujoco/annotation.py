"""Recorded-source MuJoCo replay, post-step Tasks and Native Annotation publish."""
from pathlib import Path
import time
import numpy as np
from .model import build_model
from .state import restore_episode,read_sample,snapshot
from .control import step,command_target
from .source import (resolved_model_config,initial_arrays,add_initial,record_frame,control_commands,publish_event,step_completed)
from ...data.native import NativeRun,native_api,load_catalog,open_native
from ...data.video import AsyncVideoWriter


def accept_annotation(physical_passed,frames,mode,marks):
    if mode not in ('auto','manual'):raise ValueError('Unknown Annotation mode')
    if not physical_passed:return False,None
    if mode=='auto':return True,None
    if len(marks)!=1 or not 0<marks[0]<frames-1:return False,None
    return True,marks[0]


def replay_episode(plan,model,data,b,source,segment,*,events,commands,env_index=0):
    import mujoco
    from ...tasks.pick_place import numpy_corners,v8_placement
    handler=open_native(source)
    try:recorded=handler.load_episode(source.key,'cpu')
    finally:handler.close()
    if recorded is None:raise ValueError('Missing official Source Episode')
    values=recorded.data
    def array_tree(value):return {k:array_tree(v) if isinstance(v,dict) else v.numpy().copy() for k,v in value.items()}
    initial=array_tree(values['initial_state']);original_snapshot=source.metadata.get('initial_snapshot')
    # New Source's exact opaque state is authoritative. Legacy Source retains
    # explicitly recorded canonical initial; never use an Annotation's new initial.
    restore_episode(model,data,b,original_snapshot if original_snapshot is not None else initial)
    replay_initial=snapshot(model,data,b)
    targets=values['joint_targets'].numpy();goals=values['obs']['datagen_info']['target_eef_pose']['tool0'].numpy()
    applied_targets=np.stack([command_target(target,b) for target in targets])
    eid=source.episode_id;controls=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False)
    trackers={};signals={};videos={};previous=None;first_grasp=None;trace=[]
    episode=native_api()[0]();episode.seed=recorded.seed;add_initial(episode,initial_arrays(model,data,b))
    context={'episode_id':eid,'env_index':env_index,'control_dt_s':1/30}
    for role,binding in plan.function_bindings.items():
        if binding.kind=='tracker':trackers[role.split('.',1)[1]]=plan.tasks.functions[binding.name].callable(params=binding.params,episode=context)
    acceptance=plan.function_bindings['acceptance']
    def sample(phase,tick):
        object_id=getattr(acceptance.params,'object',None)
        row=read_sample(model,data,b,phase,tick,episode_id=eid,env_index=env_index,object_id=object_id);row['signals']=dict(signals);row['placement_points']={}
        for binding in plan.function_bindings.values():
            params=binding.params
            if hasattr(params,'target') and hasattr(params,'object'):
                dims=plan.scene.scene['objects'][params.object]['task_geometry']['dimensions_m']
                row['placement_points'][params.object]={'target_id':params.target,'points':numpy_corners(row['object_poses'][params.object],row['object_poses'][params.target],dims)}
        return row
    try:
        with mujoco.Renderer(model,height=480,width=640) as renderer:
            for camera in ('side','wrist'):videos[camera]=AsyncVideoWriter(segment.folder/(camera+'.mp4'),env_index=env_index)
            tick=0
            while tick<len(targets):
                events({'kind':'status','payload':{'episode_id':eid,'env_index':env_index,'tick':tick,'progress':{'frames':tick,'total':len(targets)}}})
                control_commands(commands(),controls,events,tick=tick,episode_id=eid,env_index=env_index)
                if controls['cancelled'] or controls['skipped']:return None,{},dict(status='cancelled' if controls['cancelled'] else 'skipped',frames=tick)
                if controls['paused'] and not controls['steps']:time.sleep(.01);continue
                before=sample('pre_step',tick)
                pregrasp=bool(signals.get('grasp') and signals['grasp'].value)
                placed=v8_placement(before,params=acceptance.params)
                target=applied_targets[tick]
                record_frame(episode,before,goals[tick],target,time_s=tick/30,signals={'grasp':pregrasp,'place':placed},base=b.world_from_robot_base,previous_pose=previous,command_requested=targets[tick],command_limits=b.limits)
                previous=goals[tick]
                for camera,writer in videos.items():renderer.update_scene(data,camera=camera);writer.write(renderer.render())
                step(model,data,b,target);post=sample('post_step',tick)
                for name,tracker in trackers.items():signals[name]=tracker.update(post)
                if signals.get('grasp') and signals['grasp'].value and first_grasp is None:first_grasp=tick
                trace.append({'tick':tick,'pre_grasp':pregrasp,'post_grasp':bool(signals.get('grasp') and signals['grasp'].value),'contacts':post.get('contacts'),
                              'joint_max_abs_rad':float(np.max(abs(before['joint_positions']-values['obs']['policy']['joint_pos'][tick].numpy())))})
                tick+=1
                step_completed(controls,events,tick-1)
        final=sample('episode_end',len(targets)-1)
        passed=plan.tasks.functions[acceptance.name].callable(final,params=acceptance.params)
        if type(passed) is not bool:raise ValueError('Acceptance must return bool')
        accepted,mark=accept_annotation(passed,len(targets),plan.effective_settings['execution']['mode'],controls['marks'])
        report=dict(status='success' if accepted else 'failure',physical_replay_passed=passed,first_grasp_post_tick=first_grasp,frames=len(targets),trace=trace)
        from ..mujoco.source import command_summary
        report['saturation']=command_summary(episode)
        if not accepted:return None,{},report
        episode.pre_export();episode.success=True
        episode.data['obs']['events']['place'][-1]=1
        if mark is not None:
            import torch
            signal=torch.from_numpy((np.arange(len(targets))>=mark).astype(np.uint8)[:,None])
            episode.data['obs']['events']['grasp']=signal;episode.data['obs']['datagen_info']['subtask_term_signals']['grasp']=signal
        report.update(annotation={'grasp':int(np.flatnonzero(episode.data['obs']['events']['grasp'].numpy())[0]),'place':int(np.flatnonzero(episode.data['obs']['events']['place'].numpy())[0]),
            'method':'manual_grasp_and_measured_place' if mark is not None else 'stable_contact_replay'},
            source_initial_snapshot=original_snapshot,replay_initial_snapshot=replay_initial,initial_state_owner='annotation_replay_start')
        for writer in videos.values():writer.close()
        return episode,{name:w.video_path for name,w in videos.items()},report
    finally:
        for writer in videos.values():
            if not writer._closed:writer.abort()


def run(plan,*,events,commands):
    import mujoco
    from ...recipe import verify_prepared_inputs,_plain
    from ...run import StageResult
    verify_prepared_inputs(plan)
    catalog=load_catalog(plan.resolved_inputs['dataset']['path'])
    if catalog.execution.get('stage')!='source':raise ValueError('Annotation requires original Source, not re-saved Annotation initial state')
    validate_recording(catalog.execution.get('recording',{}));validate_source_ranges(catalog)
    if any(v.kind=='metrics' for v in plan.function_bindings.values()):raise ValueError('Annotation optional metrics are not supported by this runner')
    cfg=resolved_model_config(plan,catalog.execution.get('model_config'))
    if tuple(cfg.active_object_ids)!=tuple(catalog.execution['active_objects']):raise ValueError('Recorded active object ordering differs')
    model,b=build_model(plan.scene,cfg);data=mujoco.MjData(model)
    if catalog.execution.get('engine')!='mujoco' or catalog.execution.get('model_sha256')!=b.model_sha256:raise ValueError('Source engine/model identity mismatch; explicit migration required')
    execution={**catalog.execution,'stage':'annotation','source_dataset':_plain(catalog.identity),
               'task_code':_plain(plan.effective_settings['task_modules_sha256']),'annotation_mode':plan.effective_settings['execution']['mode'],
               'workflow_code':{Path(k).name:v for k,v in plan.effective_settings['code_files'].items()}}
    execution['recording']={**execution['recording'],'position_target_policy':'saturation_inward_v1','joint_targets_role':'applied'}
    saved=0;cancelled=False;reports=[]
    with NativeRun(plan.output_path,execution) as owner:
        if plan.effective_settings['execution'].get('num_envs',1)>1:return replay_parallel(plan,owner,model,b,catalog,events=events,commands=commands)
        for ordinal,original in enumerate(catalog.episodes):
            seg=owner.segment('annotation-'+str(ordinal),request={'source':original.episode_id,'dataset':_plain(catalog.identity)})
            claim=owner.claim_attempt(seg)
            ep,media,report=replay_episode(plan,model,data,b,original,seg,events=events,commands=commands)
            accepted,summary=publish_annotation(owner,seg,claim,ep,media,report,catalog,original,events);saved+=int(accepted);reports.append(summary)
            if report['status']=='cancelled':cancelled=True;break
    return StageResult('cancelled' if cancelled else 'completed',(str(plan.output_path),),saved,{'attempts':len(reports),'reports':reports})


def validate_recording(recording):
    from .model import JOINTS
    required=dict(joint_order=list(JOINTS),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',task_phase='post_step',fps=30,resolution=[640,480])
    if any(recording.get(k)!=v for k,v in required.items()):
        raise ValueError('Source joint order/unit/frame/phase/camera contract missing or incompatible')


def publish_annotation(owner,seg,claim,ep,media,report,catalog,original,events):
    from ...recipe import _plain
    summary={k:v for k,v in report.items() if k not in ('trace','source_initial_snapshot','replay_initial_snapshot')}
    if ep is not None:
        eid='annotation-'+str(claim['attempt']-1)
        seg.write_episode(ep,episode_id=eid,metadata={**report,'source_lineage':{'dataset':_plain(catalog.identity),'episode_id':original.episode_id,'key':original.key},'source_metadata':original.metadata},media=media)
        for path in media.values():Path(path).unlink()
        seg.record_attempt(claim,status='success',episode_id=eid,diagnostics=summary);seg.commit();publish_event(owner.root,eid,events)
    else:
        seg.record_attempt(claim,status='cancelled' if report['status']=='cancelled' else 'failure',diagnostics=summary);seg.commit()
    return ep is not None,{k:v for k,v in report.items() if k not in ('trace','source_initial_snapshot','replay_initial_snapshot')}


def replay_parallel(plan,owner,model,b,catalog,*,events,commands):
    """Distinct Source initial/action streams; each native state owns its tracker."""
    import mujoco
    from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
    from .source import command_channels
    from ...recipe import _plain
    from ...run import StageResult
    n=plan.effective_settings['execution']['num_envs'];states=[mujoco.MjData(model) for _ in range(n)]
    polls,send=command_channels(commands,events,n);sources=iter(enumerate(catalog.episodes));pending={};saved=0;reports=[];cancelled=False;fatal=None
    def schedule(threads,i):
        item=next(sources,None)
        if item is None:return
        ordinal,source=item;seg=owner.segment('annotation-'+str(ordinal),request={'source':source.episode_id,'dataset':_plain(catalog.identity)});claim=owner.claim_attempt(seg)
        pending[threads.submit(replay_episode,plan,model,states[i],b,source,seg,events=send,commands=polls[i],env_index=i)]=(i,source,seg,claim)
    with ThreadPoolExecutor(max_workers=n,thread_name_prefix='mujoco-annotation') as threads:
        try:
            for i in range(n):schedule(threads,i)
            while pending:
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    i,source,seg,claim=pending.pop(future)
                    try:ep,media,report=future.result()
                    except Exception as error:
                        seg.record_attempt(claim,status='failure',diagnostics={'env_index':i,'reason':str(error),'effect':getattr(error,'effect','unknown')});seg.commit();fatal=fatal or error;send.stop();continue
                    report['env_index']=i;accepted,summary=publish_annotation(owner,seg,claim,ep,media,report,catalog,source,send);saved+=int(accepted);reports.append(summary)
                    cancelled|=report['status']=='cancelled'
                    if not cancelled and fatal is None:schedule(threads,i)
        finally:send.stop()
    if fatal is not None:raise fatal
    return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),saved,{'env_num':n,'attempts':len(reports),'reports':reports})


def validate_source_ranges(catalog):
    if any(ep.start!=0 or ep.stop not in (None,ep.num_frames) for ep in catalog.episodes):
        raise ValueError('Annotation requires complete Source episodes and original initial state; use a numerical Source stream to collect a new episode from a trim')
