"""Single-environment Mimic -> fixed DLS -> actual MuJoCo -> Native C.

Sources: MuJoCo3.3.7 Python API and pinned Isaac Lab2.3 Mimic calculation subset.
https://mujoco.readthedocs.io/en/3.3.7/python.html
"""
from pathlib import Path
import numpy as np
from ...generation import mimic
from ...data.native import load_catalog,open_native,file_sha256
from .source import resolved_model_config
from robot_learning_workbench.data.recording import validate_recording
from .model import JOINTS,_execution_urdf


from ...data.publication import publish_generation

def reset_seeds(seed,count):
    """Original single-worker reset stream: one draw per global attempt."""
    if type(count) is not int or count<0:raise ValueError('Nonnegative attempt count required')
    rng=np.random.default_rng(mimic.attempt_seed(seed,0))
    return [int(rng.integers(2**32)) for _ in range(count)]


def load_inputs(plan):
    if any(b.kind=='placement' and b.name in ('placement.random_xy','placement.contact_random_xy') for b in plan.function_bindings.values()):
        raise ValueError('New DataGen Random uses placement.random_workspace without a Pose Seed')
    catalog=load_catalog(plan.resolved_inputs['dataset']['path'])
    if catalog.execution.get('stage')!='annotation' or catalog.execution.get('engine')!='mujoco':raise ValueError('Verified MuJoCo Annotation input required')
    validate_recording(catalog.execution.get('recording',{}))
    if 'partition' not in catalog.execution or catalog.execution['partition'] is None:raise ValueError('Explicit Annotation partition identity required')
    cfg=resolved_model_config(plan,catalog.execution.get('model_config'))
    if tuple(cfg.active_object_ids)!=tuple(plan.object_order):raise ValueError('Explicit generation creation order must match annotated model')
    acceptance=plan.function_bindings['acceptance']
    if any(b.kind=='metrics' for b in plan.function_bindings.values()):raise ValueError('Standalone DataGen metric declarations are unsupported')
    conf=mimic.configuration(acceptance.params.object,acceptance.params.target,plan.effective_settings['execution']['seed'])
    records=[]
    for row in catalog.episodes:
        if row.start or row.stop not in (None,row.num_frames):raise ValueError('Mimic needs complete annotated Episode boundaries')
        h=open_native(row)
        try:records.append((row.episode_id,h.load_episode(row.key,'cpu')))
        finally:h.close()
    pool=mimic.source_pool(records,conf)
    path=_execution_urdf(plan.scene)
    kin=mimic.bind_kinematics(path,model_sha256=file_sha256(path),joint_order=JOINTS)
    return catalog,pool,cfg,kin


def generate_attempt(plan,model,data,b,pool,kin,segment,claim,*,events,commands,env_index=0):
    """One real attempt. A rejected candidate never changes the applied reference."""
    import mujoco,torch
    from ...data.native import native_api
    from ...data.video import AsyncVideoWriter
    from ...tasks.pick_place import numpy_corners,v8_placement,release_evidence
    from robot_learning_workbench.engines.mujoco.source import initial_arrays
    from robot_learning_workbench.data.recording import add_initial, record_frame
    from robot_learning_workbench.commands import control_commands, step_completed
    from .state import read_sample,snapshot
    from .control import step,command_target
    eid='datagen-'+str(claim['attempt']);ep=native_api()[0]();ep.seed=claim['seed'];add_initial(ep,initial_arrays(model,data,b));initial=snapshot(model,data,b)
    context={'episode_id':eid,'env_index':env_index,'control_dt_s':1/30};signals={};trackers={}
    for role,binding in plan.function_bindings.items():
        if binding.kind=='tracker':trackers[role.split('.',1)[1]]=plan.tasks.functions[binding.name].callable(params=binding.params,episode=context)
    acceptance=plan.function_bindings['acceptance'];params=acceptance.params
    def sample(phase,tick):
        row=read_sample(model,data,b,phase,tick,episode_id=eid,env_index=env_index,object_id=params.object);row['signals']=dict(signals)
        dims=plan.scene.scene['objects'][params.object]['task_geometry']['dimensions_m']
        row['placement_points']={params.object:{'target_id':params.target,'points':numpy_corners(row['object_poses'][params.object],row['object_poses'][params.target],dims)}}
        return row
    controls=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False);videos={};previous_pose=None;previous_command=data.ctrl[list(b.actuator_ids)].copy()
    stream=mimic.RandomStream(claim['seed']);boundaries=mimic.randomize_boundaries(pool,stream=stream);last_plan=None;plans=[];diagnostics=[];tick=0;first=None
    release_reference=None;release_grip=None;released=False;loss_steps=0;drop_step=None
    report={'env_index':env_index,'initial_applied_joint_rad':previous_command.tolist(),'status':'failure','category':'grasp_failure','steps':0,'seed':claim['seed'],'initial_snapshot':initial,'selected_sources':plans,'ik_diagnostics':diagnostics,'boundaries':{k:v.tolist() for k,v in boundaries.items()}}
    try:
        with mujoco.Renderer(model,height=480,width=640) as renderer:
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
                        import time
                        time.sleep(.01)
                    if tick>=plan.effective_settings['execution'].get('max_episode_steps',2000):report.update(category='timeout',steps=tick);return None,{},report
                    before=sample('pre_step',tick);goal=waypoint.pose.numpy().astype(np.float64);grip=float(waypoint.gripper_action.reshape(-1)[0])
                    import time
                    ik_started=time.perf_counter()
                    try:
                        result=mimic.solve_dls(kin,goal,before['joint_positions'],previous_command,grip,model_sha256=b.urdf_sha256,joint_order=JOINTS,frame='robot_base',units='m_rad')
                    except mimic.IKFailure as error:
                        report.update(category='ik_failure',steps=tick,invalid_ik=error.diagnostics);return None,{},report
                    try:target=command_target(result.command,b)
                    except ValueError as error:
                        report.update(category='ik_failure',steps=tick,invalid_ik={**result.diagnostics,'failure_reason':'engine_target_rejected','reason':str(error),'command_applied':False});return None,{},report
                    if np.max(abs(target[:5]-previous_command[:5]))>.5:
                        report.update(category='ik_failure',steps=tick,invalid_ik={**result.diagnostics,'failure_reason':'engine_command_jump','command_applied':False});return None,{},report
                    duration_s=time.perf_counter()-ik_started
                    # Pre-step record first; previous_command only advances after real physics.
                    record_frame(ep,before,goal,target,time_s=tick/30,signals={'grasp':bool(signals.get('grasp') and signals['grasp'].value),'place':v8_placement(before,params=params)},base=b.world_from_robot_base,previous_pose=previous_pose,command_requested=result.command,command_limits=b.limits)
                    for camera,writer in videos.items():renderer.update_scene(data,camera=camera);writer.write(renderer.render())
                    step(model,data,b,target);previous_command=target.copy();previous_pose=goal
                    diag={**result.diagnostics,'duration_s':duration_s,'command_applied':True,'applied_joint_rad':target.tolist(),'tick':tick};diagnostics.append(diag)
                    for key,value in mimic.ik_record(result,duration_s,applied=True).items():ep.add('ik/'+key,torch.from_numpy(np.array(value)))
                    ep.add('ik/applied_joint_rad',torch.from_numpy(target.copy()))
                    post=sample('post_step',tick)
                    for name,tracker in trackers.items():signals[name]=tracker.update(post)
                    ep.add('states/joint_pos',torch.from_numpy(post['joint_positions'].copy()))
                    ep.add('states/finger_contact',torch.tensor([post['contacts']['left'],post['contacts']['right']],dtype=torch.bool))
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
        from robot_learning_workbench.data.recording import command_summary
        try:report['saturation']=command_summary(ep)
        except Exception as error:report['saturation']={'status':'unavailable','reason':str(error)}
        for writer in videos.values():
            if not writer._closed:writer.abort()


def run(plan,*,events,commands):
    import mujoco
    from ...recipe import verify_prepared_inputs,_plain
    from ...data.native import NativeRun,resume_to,history
    from ...run import StageResult
    from ...data.native import collection_settings
    from robot_learning_workbench.engines.mujoco.source import execution_contract, reset_placements
    from robot_learning_workbench.data.publication import publish_event
    from .model import build_model
    from .state import restore_episode
    verify_prepared_inputs(plan);catalog,pool,cfg,kin=load_inputs(plan)
    model,b=build_model(plan.scene,cfg);data=mujoco.MjData(model)
    if catalog.execution.get('model_sha256')!=b.model_sha256:raise ValueError('Annotation model identity differs from generation model')
    from ...tasks.placement import uses_workspace_random
    from ...tasks.registry import TaskError
    random_poses=uses_workspace_random(plan)
    opts=collection_settings(plan.effective_settings['execution'],plan.output_path,stage='datagen')
    execution=execution_contract(plan,b,cfg)
    execution.update(stage='datagen',partition=_plain(catalog.execution['partition']),ik=kin.identity,annotated_input=_plain(catalog.identity),source_pool_order=list(pool.episode_ids),
        target_successes=opts['target_successes'],max_attempts=opts['max_attempts'],max_episode_steps=opts.get('max_episode_steps',2000),
        rng_policy='entropy_workspace_poses_no_rng_resume_v1' if random_poses else 'v8_single_worker_attempt_seed_and_worker_reset_stream',mimic_configuration=_plain(pool.env_cfg.subtask_configs))
    previous=plan.resolved_inputs.get('resume_dataset')
    if previous and len(load_catalog(previous['path']).episodes)>=opts['target_successes']:raise ValueError('Cumulative generation target must exceed previous successes')
    owner=resume_to(previous['path'],plan.output_path,execution) if previous else NativeRun(plan.output_path,execution,append=opts.get('resume',False))
    cancelled=False
    try:
        if opts.get('num_envs',1)>1:return run_parallel(plan,owner,model,b,pool,catalog,kin,opts,events=events,commands=commands)
        count=len(load_catalog(owner.root).episodes);attempt=max((r['attempt'] for r in history(owner.root)),default=0)
        if not random_poses:
            reset_rng=np.random.default_rng(mimic.attempt_seed(opts['seed'],0))
            for _ in range(attempt):reset_rng.integers(2**32)
        while count<opts['target_successes'] and attempt<opts['max_attempts']:
            attempt+=1;segment=owner.segment('datagen-'+str(attempt));claim=owner.claim_attempt(segment)
            restore_episode(model,data,b,None)
            # Placement exhaustion/physics application errors abort this run; never
            # spend an extra RNG draw to turn an invalid placement into a new trial.
            if random_poses:
                try:placements=reset_placements(plan,model,data,b,None)
                except TaskError as error:
                    segment.record_attempt(claim,status='failure',diagnostics={'category':'invalid_placement','code':'INVALID_PLACEMENT',
                        'reason':str(error),'placement':_plain(getattr(error,'diagnostics',{})),'planned_placements':_plain(getattr(error,'placement_records',{})),'steps':0})
                    segment.commit();continue
                except Exception as error:
                    segment.record_attempt(claim,status='failure',diagnostics={'category':'engine_reset_error','reason':str(error),
                        'placements':_plain(getattr(error,'placement_records',{})),'effect':'unknown','steps':0})
                    segment.commit();raise
            else:
                reset_seed=int(reset_rng.integers(2**32))
                reset_placements(plan,model,data,b,reset_seed)
            ep,media,report=generate_attempt(plan,model,data,b,pool,kin,segment,claim,events=events,commands=commands)
            if random_poses:report['placements']=placements
            else:report['reset_seed']=reset_seed
            count+=int(publish_generation(owner,segment,claim,ep,media,report,catalog,kin,events))
            if report['status']=='cancelled':cancelled=True;break
        return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'attempts':attempt,'target_reached':count>=opts['target_successes'],'budget_exhausted':attempt>=opts['max_attempts'],'history':history(owner.root)})
    finally:owner.close()


def run_parallel(plan,owner,model,b,pool,catalog,kin,opts,*,events,commands):
    """Concurrent native MjData/IK/render loops; only this thread publishes files."""
    import mujoco,time,threading
    from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
    from robot_learning_workbench.commands import command_channels
    from robot_learning_workbench.engines.mujoco.source import reset_placements
    from .state import restore_episode
    from ...tasks.placement import uses_workspace_random
    from ...tasks.registry import TaskError
    from ...data.native import history
    from ...run import StageResult
    n=opts['num_envs'];states=[mujoco.MjData(model) for _ in range(n)]
    kinematics=[mimic.bind_kinematics(_execution_urdf(plan.scene),model_sha256=b.urdf_sha256,joint_order=JOINTS) for _ in range(n)]
    polls,send=command_channels(commands,events,n);random=uses_workspace_random(plan);reset_values=reset_seeds(opts['seed'],opts['max_attempts']) if not random else None
    def generate(i,segment,claim):
        started=time.perf_counter();data=states[i];placements=None;reset_seed=None
        try:
            restore_episode(model,data,b,None)
            if not random:reset_seed=reset_values[claim['attempt']-1]
            placements=reset_placements(plan,model,data,b,reset_seed)
            ep,media,report=generate_attempt(plan,model,data,b,pool,kinematics[i],segment,claim,events=send,commands=polls[i],env_index=i)
        except TaskError as error:
            ep,media,report=None,{},dict(status='failure',category='invalid_placement',steps=0,reason=str(error),ik_diagnostics=[],planned_placements=getattr(error,'placement_records',{}))
        except Exception as error:
            ep,media,report=None,{},dict(status='failure',category='execution_error',steps=0,reason=str(error),effect=getattr(error,'effect','unknown'),ik_diagnostics=[],_exception=error)
        report.update(env_index=i,thread_id=threading.get_ident(),elapsed_s=time.perf_counter()-started)
        if random:report['placements']=placements
        else:report['reset_seed']=reset_seed
        return ep,media,report
    count=len(load_catalog(owner.root).episodes);attempt=max((r['attempt'] for r in history(owner.root)),default=0);available=list(range(n));pending={};cancelled=False;fatal=None
    with ThreadPoolExecutor(max_workers=n,thread_name_prefix='mujoco-env') as threads:
        try:
            while pending or (available and count<opts['target_successes'] and attempt<opts['max_attempts'] and not cancelled and fatal is None):
                # Every in-flight attempt reserves at most one remaining success slot.
                while available and count+len(pending)<opts['target_successes'] and attempt<opts['max_attempts'] and not cancelled and fatal is None:
                    i=available.pop(0);attempt+=1;segment=owner.segment('datagen-'+str(attempt));claim=owner.claim_attempt(segment)
                    pending[threads.submit(generate,i,segment,claim)]=(i,segment,claim)
                if not pending:break
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    i,segment,claim=pending.pop(future);ep,media,report=future.result();error=report.pop('_exception',None)
                    count+=int(publish_generation(owner,segment,claim,ep,media,report,catalog,kinematics[i],send));available.append(i)
                    cancelled|=report['status']=='cancelled'
                    if error is not None:fatal=fatal or error;send.stop()
        finally:send.stop()
    if fatal is not None:raise fatal
    return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),count,{'env_num':n,'execution_mode':'concurrent_mjdata_threads','existing_episodes':opts.get('previous_episodes',0),'added_episodes':count-opts.get('previous_episodes',0),'attempts':attempt,'target_reached':count>=opts['target_successes'],'budget_exhausted':attempt>=opts['max_attempts'],'history':history(owner.root)})


