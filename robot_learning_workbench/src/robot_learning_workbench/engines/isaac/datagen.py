"""Concrete Isaac Mimic/DLS workflow, after AppLauncher; no execution adapter.

https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html
"""
from pathlib import Path
import numpy as np
from ...generation import mimic
from ...data.native import load_catalog,open_native,file_sha256
from .source import settings_for,model_identity
from ..mujoco.annotation import validate_recording
from ...robot.calibration import JOINTS


def load_inputs(plan):
    from .env_cfg import execution_inputs
    validate_placements(plan)
    catalog=load_catalog(plan.resolved_inputs['dataset']['path'])
    if catalog.execution.get('stage')!='annotation' or catalog.execution.get('engine')!='isaac':raise ValueError('Verified Isaac Annotation input required')
    validate_recording(catalog.execution.get('recording',{}))
    if 'partition' not in catalog.execution or catalog.execution['partition'] is None:raise ValueError('Explicit input partition identity required')
    settings=settings_for(plan,catalog.execution.get('model_config'))
    if catalog.execution.get('model_sha256')!=model_identity(plan.scene,settings):raise ValueError('Annotation model/physics identity differs')
    if any(b.kind=='metrics' for b in plan.function_bindings.values()):raise ValueError('Standalone metrics execution unsupported')
    params=plan.function_bindings['acceptance'].params;conf=mimic.configuration(params.object,params.target,plan.effective_settings['execution']['seed']);records=[]
    for row in catalog.episodes:
        if row.start or row.stop not in (None,row.num_frames):raise ValueError('Complete Annotation Episode boundaries required')
        h=open_native(row)
        try:records.append((row.episode_id,h.load_episode(row.key,'cpu')))
        finally:h.close()
    pool=mimic.source_pool(records,conf);inputs=execution_inputs(plan.scene,settings)
    kin=mimic.bind_kinematics(inputs['robot_urdf'],model_sha256=file_sha256(inputs['robot_urdf']),joint_order=JOINTS)
    return catalog,pool,settings,kin


def generate_attempt(plan,env,pool,kin,segment,claim,*,events,commands):
    from .mdp import complete_episode
    return complete_episode(env,generation_steps(plan,env,pool,kin,segment,claim,events=events,commands=commands))


def generation_steps(plan,env,pool,kin,segment,claim,*,events,commands,env_index=0):
    """One real attempt. A rejected candidate never changes the applied reference."""
    import torch
    from ...data.native import native_api
    from ...data.video import AsyncVideoWriter
    from ...tasks.pick_place import v8_placement,release_evidence
    from .source import record_frame
    from .annotation import task_sample
    from ..mujoco.source import add_initial,control_commands,step_completed
    from .state import initial_state
    from .mdp import apply_joint_targets,validate_targets
    eid='datagen-'+str(claim['attempt']);ep=native_api()[0]();ep.seed=claim['seed'];initial=initial_state(env,env_index,relative=True);add_initial(ep,initial)
    context={'episode_id':eid,'env_index':env_index,'control_dt_s':env.step_dt};signals={};trackers={}
    for role,binding in plan.function_bindings.items():
        if binding.kind=='tracker':trackers[role.split('.',1)[1]]=plan.tasks.functions[binding.name].callable(params=binding.params,episode=context)
    acceptance=plan.function_bindings['acceptance'];params=acceptance.params
    def sample(phase,tick):return task_sample(env,plan,phase,tick,eid,signals,env_index=env_index)
    controls=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False);videos={};previous_pose=None;robot=env.scene['robot'];ids=[robot.joint_names.index(n) for n in JOINTS];previous_command=robot.data.joint_pos_target[env_index,ids].detach().cpu().numpy().copy()
    stream=mimic.RandomStream(claim['seed']);boundaries=mimic.randomize_boundaries(pool,stream=stream);last_plan=None;plans=[];diagnostics=[];tick=0;first=None
    release_reference=None;release_grip=None;released=False;loss_steps=0;drop_step=None
    report={'env_index':env_index,'initial_frame':'scene_world','engine_env_origin':env.scene.env_origins[env_index].cpu().numpy().tolist(),'initial_applied_joint_rad':previous_command.tolist(),'status':'failure','category':'grasp_failure','steps':0,'seed':claim['seed'],'initial_snapshot':initial,'selected_sources':plans,'ik_diagnostics':diagnostics,'boundaries':{k:v.tolist() for k,v in boundaries.items()}}
    try:
        for camera in ('side','wrist'):videos[camera]=AsyncVideoWriter(segment.folder/(camera+'.mp4'),env_index=env_index)
        for index in range(len(pool.env_cfg.subtask_configs['tool0'])):
            before=sample('pre_step',tick)
            trajectory=mimic.plan_subtask(pool,index,boundaries,eef_pose=before['eef_pose'],object_poses=before['object_poses'],stream=stream,previous=last_plan)
            last_plan=trajectory;plans.append({'subtask':index,'source_index':trajectory.source_index,'episode_id':trajectory.source_episode,'boundary':list(trajectory.boundary)})
            ep.data.setdefault('mimic_plan',{})[str(index)]={'target_eef_pose':torch.stack([w.pose for w in trajectory.waypoints]),'gripper_action':torch.stack([w.gripper_action for w in trajectory.waypoints]),'action_noise':torch.tensor([float(w.noise) for w in trajectory.waypoints],dtype=torch.float64)}
            for waypoint in trajectory.waypoints:
                while True:
                    events({'kind':'status','payload':{'episode_id':eid,'env_index':env_index,'tick':tick,'progress':{'attempt':claim['attempt'],'frames':tick}}})
                    control_commands(commands(),controls,events,tick=tick,episode_id=eid,env_index=env_index)
                    if controls['cancelled']:report.update(status='cancelled',category='interrupted',steps=tick);return None,{},report
                    if not controls['paused'] or controls['steps']:break
                    yield None
                if tick>=plan.effective_settings['execution'].get('max_episode_steps',2000):report.update(category='timeout',steps=tick);return None,{},report
                before=sample('pre_step',tick);goal=waypoint.pose.numpy().astype(np.float64);grip=float(waypoint.gripper_action.reshape(-1)[0])
                import time
                ik_started=time.perf_counter()
                try:
                    result=mimic.solve_dls(kin,goal,before['joint_positions'],previous_command,grip,model_sha256=kin.model_sha256,joint_order=JOINTS,frame='robot_base',units='m_rad')
                except mimic.IKFailure as error:
                    report.update(category='ik_failure',steps=tick,invalid_ik=error.diagnostics);return None,{},report
                try:
                    target=validate_targets(result.command[None],np.array(env.cfg.workbench_joint_limits_rad)[None])[0]
                except ValueError as error:
                    report.update(category='ik_failure',steps=tick,invalid_ik={**result.diagnostics,'failure_reason':'engine_target_rejected','reason':str(error),'command_rejection':getattr(error,'diagnostics',{}),'command_applied':False});return None,{},report
                
                # The float32 engine payload must satisfy the same guard as the candidate.
                if np.max(abs(target[:5].astype(np.float64)-previous_command[:5].astype(np.float64)))>.5:
                    report.update(category='ik_failure',steps=tick,invalid_ik={**result.diagnostics,'failure_reason':'engine_command_jump','command_applied':False});return None,{},report
                duration_s=time.perf_counter()-ik_started
                # Pre-step record first; previous_command only advances after real physics.
                # Training target is actual payload; commands/requested retains solver float64.
                record_frame(ep,before,goal,target,time_s=tick/30,signals={'grasp':bool(signals.get('grasp') and signals['grasp'].value),'place':v8_placement(before,params=params)},base=np.asarray(env.cfg.workbench_inputs['profile']['robot_base']['T_world']),previous_pose=previous_pose,command_requested=result.command,command_limits=np.array(env.cfg.workbench_joint_limits_rad))
                for camera,writer in videos.items():writer.write(before['cameras'][camera]['rgb'])
                yield target
                previous_command=target.copy();previous_pose=goal
                diag={**result.diagnostics,'duration_s':duration_s,'command_applied':True,'applied_joint_rad':target.tolist(),'tick':tick};diagnostics.append(diag)
                for key,value in mimic.ik_record(result,duration_s,applied=True).items():ep.add('ik/'+key,torch.from_numpy(np.array(value)))
                ep.add('ik/applied_joint_rad',torch.from_numpy(target.copy()))
                post=sample('post_step',tick)
                for name,tracker in trackers.items():signals[name]=tracker.update(post)
                ep.add('states/joint_pos',torch.from_numpy(post['joint_positions'].copy()))
                ep.add('states/contact_force_w',torch.from_numpy(post['contacts']['force_w'].copy()))
                ep.add('states/grasp_latched',torch.tensor([bool(signals.get('grasp') and signals['grasp'].value)],dtype=torch.uint8))
                release_reference,release_grip,released,loss_steps,drop_step=release_evidence(trackers['grasp'],post['grasp_inputs']['relative'],(post['contacts']['left'],post['contacts']['right']),target,tick,30,release_reference,release_grip,released,loss_steps,drop_step)
                if signals.get('grasp') and signals['grasp'].value and first is None:first=tick
                step_completed(controls,events,tick);tick+=1
        final=sample('episode_end',tick-1);passed=plan.tasks.functions[acceptance.name].callable(final,params=params)
        if type(passed) is not bool:raise ValueError('Task acceptance must return bool')
        report.update(steps=tick,first_grasp_post_tick=first,drop_step=drop_step,release_commanded=released,final_placement=v8_placement(final,params=params),grasp_latched=bool(signals.get('grasp') and signals['grasp'].value))
        if not passed:report['category']='grasp_failure' if first is None else 'drop_failure' if drop_step is not None else 'place_failure';return None,{},report
        ep.pre_export();ep.success=True;ep.data['obs']['events']['place'][-1]=1
        for writer in videos.values():writer.close()
        report.update(status='success',category='success')
        return ep,{k:v.video_path for k,v in videos.items()},report
    finally:
        from ..mujoco.source import command_summary
        try:report['saturation']=command_summary(ep)
        except Exception as error:report['saturation']={'status':'unavailable','reason':str(error)}
        for writer in videos.values():
            if not writer._closed:writer.abort()



def validate_placements(plan):
    # New DataGen Random has an explicit entropy-only rule. Historical seeded
    # samplers remain pure Baseline functions, not a new DataGen Pose policy.
    if any(b.kind=='placement' and b.name not in ('placement.fixed_xy','placement.random_workspace') for b in plan.function_bindings.values()):
        raise ValueError('New DataGen Random uses placement.random_workspace; legacy Random is not supported')


def run(plan,*,events,commands):
    import tempfile
    from isaaclab.envs import ManagerBasedEnv
    from .env_cfg import build_env_cfg
    from .source import execution_contract,reset_placements,publish_event
    from ...recipe import verify_prepared_inputs,_plain
    from ...data.native import NativeRun,resume_to,history
    from ...run import StageResult
    from ...data.native import collection_settings
    from ...tasks.placement import uses_workspace_random
    from ...tasks.registry import TaskError
    random_poses=uses_workspace_random(plan)
    verify_prepared_inputs(plan);catalog,pool,settings,kin=load_inputs(plan);opts=collection_settings(plan.effective_settings['execution'],plan.output_path,stage='datagen')
    execution=execution_contract(plan,settings)
    execution.update(stage='datagen',partition=_plain(catalog.execution['partition']),ik=kin.identity,annotated_input=_plain(catalog.identity),source_pool_order=list(pool.episode_ids),
        target_successes=opts['target_successes'],max_attempts=opts['max_attempts'],max_episode_steps=opts.get('max_episode_steps',2000),
        rng_policy=('entropy_workspace_poses_episode_reset_v1' if 'num_episodes' in opts else 'entropy_workspace_poses_one_attempt_per_worker_v1') if random_poses else 'attempt_seed_sequence_fixed_placement_no_reset_draws',mimic_configuration=_plain(pool.env_cfg.subtask_configs))
    previous=plan.resolved_inputs.get('resume_dataset')
    if previous and len(load_catalog(previous['path']).episodes)>=opts['target_successes']:raise ValueError('Cumulative generation target must exceed previous successes')
    owner=env=None;cancelled=False;plan.output_path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='isaac-datagen-',dir=plan.output_path.parent) as temporary:
        try:
            owner=resume_to(previous['path'],plan.output_path,execution) if previous else NativeRun(plan.output_path,execution,append=opts.get('resume',False))
            count=len(load_catalog(owner.root).episodes);attempt=max((r['attempt'] for r in history(owner.root)),default=0)
            env=ManagerBasedEnv(cfg=build_env_cfg(plan.scene,settings,num_envs=opts.get('num_envs',1),runtime_directory=Path(temporary)/'runtime'));env.reset()
            if env.num_envs>1:return run_vector(plan,owner,env,pool,catalog,kin,opts,events=events,commands=commands)
            while count<opts['target_successes'] and attempt<opts['max_attempts']:
                attempt+=1;segment=owner.segment('datagen-'+str(attempt));claim=owner.claim_attempt(segment)
                env.reset()
                if random_poses:
                    try:placements=reset_placements(plan,env,None)
                    except TaskError as error:
                        segment.record_attempt(claim,status='failure',diagnostics={'category':'invalid_placement','code':'INVALID_PLACEMENT',
                            'reason':str(error),'placement':_plain(getattr(error,'diagnostics',{})),'planned_placements':_plain(getattr(error,'placement_records',{})),'steps':0})
                        segment.commit();break
                    except Exception as error:
                        segment.record_attempt(claim,status='failure',diagnostics={'category':'engine_reset_error','reason':str(error),
                            'placements':_plain(getattr(error,'placement_records',{})),'effect':'unknown','steps':0})
                        segment.commit();raise
                else:reset_placements(plan,env,opts['seed'])
                ep,media,report=generate_attempt(plan,env,pool,kin,segment,claim,events=events,commands=commands)
                if random_poses:report['placements']=placements
                summary={k:v for k,v in report.items() if k!='ik_diagnostics'};rows=report['ik_diagnostics']
                summary['ik_summary']={'applied_steps':len(rows),'native_nonconverged_steps':sum(not r['converged'] for r in rows),'pose_diagnostic_failed_steps':sum(not r['common_pose_passed'] for r in rows)}
                summary['last_applied_ik']=rows[-1] if rows else None
                if ep is not None:
                    eid='datagen-'+str(attempt)
                    lineage=[{'dataset':_plain(catalog.identity),**selection,'source_lineage':catalog.episodes[selection['source_index']].metadata.get('source_lineage')} for selection in report['selected_sources']]
                    segment.write_episode(ep,episode_id=eid,metadata={**summary,'non_tensor_arrays':{'ik/failure_reason':np.asarray([r['failure_reason'].encode() for r in rows],dtype='S64')},'ik_identity':kin.identity,'source_lineage':lineage,'success_source':'stable_grasp_and_placement'},media=media)
                    for p in media.values():Path(p).unlink()
                    segment.record_attempt(claim,status='success',episode_id=eid,diagnostics=summary);segment.commit();count+=1;publish_event(owner.root,eid,events)
                else:
                    for p in segment.folder.glob('*.mp4'):p.unlink()
                    status='cancelled' if report['status']=='cancelled' else 'ik_failure' if report['category']=='ik_failure' else 'failure'
                    segment.record_attempt(claim,status=status,diagnostics=summary);segment.commit()
                if report['status']=='cancelled':cancelled=True;break
                if random_poses and 'num_episodes' not in opts:break  # Historical one-attempt contract.
            return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'attempts':attempt,'target_reached':count>=opts['target_successes'],'budget_exhausted':attempt>=opts['max_attempts'],'fresh_worker_required':random_poses and 'num_episodes' not in opts and count<opts['target_successes'] and attempt<opts['max_attempts'],'history':history(owner.root)})
        finally:
            try:
                if env is not None:env.close()
            finally:
                if owner is not None:owner.close()


def run_vector(plan,owner,env,pool,catalog,kin,opts,*,events,commands):
    """Official vector step with per-env pre/post generators and partial resets."""
    import torch
    from .source import reset_placements
    from .mdp import advance_streams
    from ..mujoco.source import command_channels
    from ..mujoco.datagen import publish_generation
    from ...data.native import history
    from ...run import StageResult
    from ...tasks.placement import uses_workspace_random
    from ...tasks.registry import TaskError
    n=env.num_envs;polls,send=command_channels(commands,events,n,vector=True)
    from .env_cfg import execution_inputs
    urdf=execution_inputs(plan.scene,catalog.execution['model_config'])['robot_urdf']
    kinematics=[mimic.bind_kinematics(urdf,model_sha256=kin.model_sha256,joint_order=JOINTS) for _ in range(n)]
    count=len(load_catalog(owner.root).episodes);attempt=max((r['attempt'] for r in history(owner.root)),default=0);available=list(range(n));streams={};pending={};ready={};cancelled=False
    random=uses_workspace_random(plan)
    try:
        while streams or (available and count<opts['target_successes'] and attempt<opts['max_attempts'] and not cancelled):
            while available and count+len(streams)<opts['target_successes'] and attempt<opts['max_attempts'] and not cancelled:
                i=available.pop(0);attempt+=1;segment=owner.segment('datagen-'+str(attempt));claim=owner.claim_attempt(segment)
                try:
                    env.reset(env_ids=torch.tensor([i],dtype=torch.long,device=env.device));placements=reset_placements(plan,env,None if random else opts['seed'],env_index=i)
                except TaskError as error:
                    segment.record_attempt(claim,status='failure',diagnostics={'env_index':i,'category':'invalid_placement','code':error.code,'reason':str(error),'placements':getattr(error,'placement_records',{}),'steps':0});segment.commit();available.append(i);continue
                except Exception as error:
                    segment.record_attempt(claim,status='failure',diagnostics={'env_index':i,'category':'engine_reset_error','reason':str(error),'effect':'unknown'});segment.commit();raise
                streams[i]=generation_steps(plan,env,pool,kinematics[i],segment,claim,events=send,commands=polls[i],env_index=i);pending[i]=(segment,claim,placements)
            if not streams:break
            send.refresh()
            if send.cancelled():cancelled=True;send.ack_cancel();break
            finished,_=advance_streams(env,streams,ready,pause_check=send.paused)
            for i,result in finished.items():
                segment,claim,placements=pending.pop(i);streams.pop(i);ready.pop(i,None);available.append(i)
                if isinstance(result,Exception):
                    segment.record_attempt(claim,status='failure',diagnostics={'env_index':i,'category':'execution_error','reason':str(result),'effect':getattr(result,'effect','unknown')});segment.commit();continue
                ep,media,report=result
                if random:report['placements']=placements
                count+=int(publish_generation(owner,segment,claim,ep,media,report,catalog,kinematics[i],send));cancelled|=report['status']=='cancelled'
            if cancelled:break
    finally:
        from .source import abort_streams
        abort_streams(streams,pending,cancelled=cancelled)
    return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'env_num':n,'execution_mode':'official_vector_scene','existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'attempts':attempt,'target_reached':count>=opts['target_successes'],'budget_exhausted':attempt>=opts['max_attempts'],'history':history(owner.root)})
