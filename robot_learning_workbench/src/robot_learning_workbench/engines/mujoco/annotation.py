"""Recorded-source MuJoCo replay, post-step Tasks and Native Annotation publish."""
from pathlib import Path
from dataclasses import asdict
import time
import numpy as np
from .model import build_model
from .state import restore_episode,read_sample,snapshot
from .control import step,command_target
from robot_learning_workbench.engines.mujoco.source import resolved_model_config, initial_arrays
from robot_learning_workbench.data.recording import add_initial, record_frame
from robot_learning_workbench.commands import control_commands, step_completed
from robot_learning_workbench.data.publication import publish_event
from ...data.native import NativeRun,native_api,load_catalog,open_native
from ...data.video import AsyncVideoWriter
from ...data.recording import record_metrics


from ...data.recording import validate_recording, validate_source_ranges
from ...data.publication import publish_annotation
from ...tasks.evaluation import accept_annotation

def replay_episode(plan,model,data,b,source,segment,*,events,commands,env_index=0):
    import mujoco
    from ...tasks.execution import contact_object,add_placement_points,placement_signal,recorded_signals,update_signals,metrics,annotation_events,predicate
    handler=open_native(source)
    try:recorded=handler.load_episode(source.key,'cpu')
    finally:handler.close()
    if recorded is None:raise ValueError('Missing official Source Episode')
    values=recorded.data
    def array_tree(value):return {k:array_tree(v) if isinstance(v,dict) else v.numpy().copy() for k,v in value.items()}
    initial=array_tree(values['initial_state']);original_snapshot=source.metadata.get('initial_snapshot')
    # New Source's exact opaque state is authoritative. Legacy Source retains
    # explicitly recorded canonical initial; never use an Annotation's new initial.
    restore_episode(model,data,b,original_snapshot if original_snapshot is not None and original_snapshot.get('backend')=='mujoco'else initial)
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
        row=read_sample(model,data,b,phase,tick,episode_id=eid,env_index=env_index,object_id=contact_object(plan));row['signals']=dict(signals)
        return add_placement_points(plan,row)
    start=sample('episode_start',0);update_signals(plan,start,trackers,signals);record_metrics(episode,metrics(plan,start),'episode_start')
    try:
        with mujoco.Renderer(model,height=480,width=640) as renderer:
            for camera in ('side','wrist'):videos[camera]=AsyncVideoWriter(segment.folder/(camera+'.mp4'),env_index=env_index)
            tick=0
            while tick<len(targets):
                events({'kind':'status','payload':{'episode_id':eid,'env_index':env_index,'tick':tick,'progress':{'frames':tick,'total':len(targets)}}})
                control_commands(commands(),controls,events,tick=tick,episode_id=eid,env_index=env_index)
                if controls['cancelled'] or controls['skipped']:return None,{},dict(status='cancelled' if controls['cancelled'] else 'skipped',frames=tick)
                if controls['paused'] and not controls['steps']:time.sleep(.01);continue
                before=sample('pre_step',tick);update_signals(plan,before,trackers,signals);pre_metrics=metrics(plan,before);record_metrics(episode,pre_metrics,'pre_step')
                pregrasp=bool(signals.get('grasp') and signals['grasp'].value)
                placed=placement_signal(plan,before)
                target=applied_targets[tick]
                record_frame(episode,before,goals[tick],target,time_s=tick/30,signals={**recorded_signals(signals),'grasp':pregrasp,'place':placed},base=b.world_from_robot_base,previous_pose=previous,command_requested=targets[tick],command_limits=b.limits)
                previous=goals[tick]
                for camera,writer in videos.items():renderer.update_scene(data,camera=camera);writer.write(renderer.render())
                step(model,data,b,target);post=sample('post_step',tick)
                update_signals(plan,post,trackers,signals)
                post_metrics=metrics(plan,post);record_metrics(episode,post_metrics,'post_step')
                if signals.get('grasp') and signals['grasp'].value and first_grasp is None:first_grasp=tick
                declared_metrics={**pre_metrics,**post_metrics}
                trace.append({'metrics':declared_metrics,'tick':tick,'pre_grasp':pregrasp,'post_grasp':bool(signals.get('grasp') and signals['grasp'].value),'contacts':post.get('contacts'),
                              'joint_max_abs_rad':float(np.max(abs(before['joint_positions']-values['obs']['policy']['joint_pos'][tick].numpy())))})
                tick+=1
                step_completed(controls,events,tick-1)
        final=sample('episode_end',len(targets)-1);update_signals(plan,final,trackers,signals)
        record_metrics(episode,metrics(plan,final),'episode_end');passed=predicate(plan,'acceptance',final)
        if type(passed) is not bool:raise ValueError('Acceptance must return bool')
        accepted,mark=accept_annotation(passed,len(targets),plan.effective_settings['execution']['mode'],controls['marks'])
        if plan.effective_settings['execution']['mode']=='manual'and acceptance.name!='pick_place.v8_annotation':
            accepted=passed and bool(controls.get('event_marks'))and all(0<v<len(targets)-1 for v in controls['event_marks'].values());mark=None
        report=dict(status='success' if accepted else 'failure',physical_replay_passed=passed,first_grasp_post_tick=first_grasp,frames=len(targets),trace=trace)
        from robot_learning_workbench.data.recording import command_summary
        report['saturation']=command_summary(episode)
        if not accepted:return None,{},report
        episode.pre_export();episode.success=True
        episode.data['obs']['events']['place'][-1]=1 if acceptance.name=='pick_place.v8_annotation'else episode.data['obs']['events']['place'][-1]
        if mark is not None:
            import torch
            signal=torch.from_numpy((np.arange(len(targets))>=mark).astype(np.uint8)[:,None])
            episode.data['obs']['events']['grasp']=signal;episode.data['obs']['datagen_info']['subtask_term_signals']['grasp']=signal
        report.update(annotation={**annotation_events(episode,manual_frame=mark,manual_events=controls.get('event_marks')),'method':plan.effective_settings['execution']['mode'],'acceptance_function':acceptance.name},source_initial_snapshot=original_snapshot,replay_initial_snapshot=replay_initial,initial_state_owner='annotation_replay_start')
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
    from ...data.recording import replay_settings
    cfg=resolved_model_config(plan,replay_settings(plan,catalog))
    if tuple(cfg.active_object_ids)!=tuple(catalog.execution['active_objects']):raise ValueError('Recorded active object ordering differs')
    model,b=build_model(plan.scene,cfg);data=mujoco.MjData(model)
    if catalog.execution.get('engine')=='mujoco'and catalog.execution.get('model_sha256')!=b.model_sha256:raise ValueError('Source MuJoCo physical model differs from selected configuration')
    if catalog.execution.get('urdf_sha256',b.urdf_sha256)!=b.urdf_sha256:raise ValueError('Source robot model coordinates differ from replay URDF')
    execution={**catalog.execution,'engine':'mujoco','model_sha256':b.model_sha256,'urdf_sha256':b.urdf_sha256,'model_config':_plain(asdict(cfg)),'replay_source_engine':catalog.execution.get('engine'),'physics_equivalence_verified':False,'stage':'annotation','source_dataset':_plain(catalog.identity),
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


def replay_parallel(plan,owner,model,b,catalog,*,events,commands):
    """Distinct Source initial/action streams; each native state owns its tracker."""
    import mujoco
    from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
    from robot_learning_workbench.commands import command_channels
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


