"""ACT simulation evaluation: Placement termination, no gripper/grasp success gate."""


def evaluation_result(*,placed,grasp,steps,limit):
    return dict(success=bool(placed),category='placement_success' if placed else 'max_steps' if steps>=limit else 'task_failure',
                steps=steps,grasp_latched=bool(grasp),placement=bool(placed))

from pathlib import Path
import time,resource
import numpy as np
from ...learning.policy import load_policy,infer,observation_batch,preflight_action,ActionRejected
from ...data.native import NativeRun,load_catalog,history,resume_to,digest,atomic_json,native_api,DataError
from .source import add_initial,record_frame,control_commands,step_completed,publish_event


def execution_failure(error,*,phase,steps,applying=False):
    import traceback
    from ...run import _error
    traceback.print_exception(type(error),error,error.__traceback__)
    effect='unknown' if applying or phase in ('task','reset') else getattr(error,'effect','not_applied')
    error.effect=effect  # Propagate the observed execution effect with the same error/cause.
    return dict(success=False,category='engine_error' if phase in ('physics','reset') else 'camera_error' if phase=='camera' else 'policy_error' if phase=='policy' else 'execution_error',
                error={'phase':phase,**_error(error,effect=effect)},steps=steps,_exception=error)


def abort_videos(videos,report):
    errors=[]
    for writer in videos.values():
        if writer._closed:continue
        try:writer.abort()
        except Exception as error:errors.append(error)
    if errors:report.update(execution_failure(ExceptionGroup('Video cleanup failed',errors),phase='recording_cleanup',steps=report.get('steps',0),applying=True))


def policy_inputs(plan,urdf_sha256):
    """Explicit live IO binding; external official Policies need no owned manifest."""
    from ...recipe import _plain
    from ...robot.calibration import JOINTS
    policy,pre,post,record=load_policy(plan.resolved_inputs['policy']['path'],device='cpu')
    if policy.config.type=='smolvla' and not plan.effective_settings['execution'].get('task_instruction'):raise DataError('POLICY_INCOMPATIBLE','task_instruction','SmolVLA needs explicit language instruction')
    contract=record.get('control_contract') or _plain(plan.input_documents.get('policy_contract'))
    expected=dict(schema_version=1,scene_identity=_plain(plan.scene_identity),calibration_sha256=digest(_plain(plan.scene.calibration)),robot_model_sha256=urdf_sha256,
        joint_order=list(JOINTS),pose_frame='robot_base',control_hz=30,policy_tensor_dtype='float32',
        observation=dict(source='obs/policy/joint_pos',phase='pre_step',meaning='measured_model_joint_position',units=['rad']*6),
        action=dict(source='joint_targets',phase='command_for_step_t',meaning='absolute_model_joint_position_target',units=['rad']*6),
        cameras={n:dict(color='rgb',fps=30.,shape=[480,640,3]) for n in ('side','wrist')})
    if contract and 'command_processing' in contract:expected['command_processing']={'position_target_policy':'saturation_inward_v1','training_target':'applied'}
    if contract!=expected:raise DataError('POLICY_INCOMPATIBLE','policy','Explicit Scene/model/Calibration/joint/unit/phase/camera contract mismatch')
    features={'observation.state':(6,),**{'observation.images.'+n:(3,480,640) for n in ('side','wrist')}}
    if {k:tuple(v.shape) for k,v in policy.config.input_features.items()}!=features or tuple(policy.config.output_features['action'].shape)!=(6,):raise DataError('POLICY_INCOMPATIBLE','features','Policy features differ from actual live inputs')
    return policy,pre,post,record,contract


def evaluation_execution(plan,execution,record):
    from ...recipe import _plain
    if any(b.kind=='placement' and b.name not in ('placement.fixed_xy','placement.random_workspace') for b in plan.function_bindings.values()):raise ValueError('Evaluation supports Fixed or Workspace Random placement')
    params=plan.function_bindings['success'].params
    if plan.function_bindings['success'].name!='pick_place.v8_evaluation':raise ValueError('P01 preserves explicit v8 Placement evaluation')
    for binding in plan.function_bindings.values():
        if binding.kind=='tracker' and getattr(binding.params,'object',None)!=params.object:raise ValueError('P01 tracker must observe the evaluated object')
        if binding.kind=='metrics' and (getattr(binding.params,'object',None)!=params.object or getattr(binding.params,'target',None)!=params.target):raise ValueError('P01 metric object/target mismatch')
    steps=max(1,int(np.ceil(plan.effective_settings['execution'].get('timeout_s',10)*30)))
    execution.update(policy_identity=digest(record),policy_checkpoint_step=record['step'],policy_files=record['files'],policy_training_dataset=record.get('dataset_identity'),
        evaluation_contract=digest({'bindings':_plain(plan.function_bindings),'max_steps':steps,'control_policy':'position_saturation_inward_v1','policy_device':'cpu','task_instruction':plan.effective_settings['execution'].get('task_instruction')}),
        episodes=plan.effective_settings['execution']['episodes'],max_steps=steps,rng_policy='entropy_workspace_poses_no_rng_resume_v1' if any(b.name=='placement.random_workspace' for b in plan.function_bindings.values()) else 'fixed_initial_base_seed_plus_attempt_minus_one')
    execution['recording'].update(timestamp_clock='episode_control_relative',engine_clock='physics_simulation_seconds',applied_command='commands/applied_joint_rad')
    return execution


def trackers_for(plan,eid,*,env_index=0):
    return {role.split('.',1)[1]:plan.tasks.functions[b.name].callable(params=b.params,episode={'episode_id':eid,'env_index':env_index,'control_dt_s':1/30}) for role,b in plan.function_bindings.items() if b.kind=='tracker'}


def post_evaluation(plan,row,trackers,signals,state,initial_positions,report):
    from ...tasks.pick_place import object_metrics
    for name,tracker in trackers.items():signals[name]=tracker.update(row)
    row['signals']=dict(signals);binding=plan.function_bindings['success'];placed=plan.tasks.functions[binding.name].callable(row,params=binding.params)
    if type(placed) is not bool:raise ValueError('Evaluation predicate must return bool')
    grasp=bool(signals.get('grasp') and signals['grasp'].value)
    for key,value in (('first_grasp_post_tick',grasp),('first_placement_post_tick',placed)):
        if value and report.get(key) is None:report[key]=row['tick']
    report['metrics']=object_metrics(plan.object_order,binding.params.object,{n:p[:3,3] for n,p in row['object_poses'].items()},row['eef_pose'][:3,3],state,grasp,placed,initial_positions)
    for role,b in plan.function_bindings.items():
        if b.kind=='metrics':report.setdefault('declared_metrics',{})[role]=plan.tasks.functions[b.name].callable(row,params=b.params)
    return placed,grasp


def publish_attempt(owner,segment,claim,ep,media,report,events):
    eid='evaluation-'+str(claim['attempt']);saved=None
    if ep is not None:
        ep.success=report['success'];segment.write_episode(ep,episode_id=eid,metadata={**report,'success_source':'simulation_place_condition'},media=media)
        for path in media.values():Path(path).unlink()
        saved=eid
    status='cancelled' if report['category']=='cancelled' else 'success' if report['success'] else 'failure'
    summary_report={k:v for k,v in report.items() if k!='initial_snapshot'}
    segment.record_attempt(claim,status=status,episode_id=saved,diagnostics=summary_report);segment.commit()
    if saved:publish_event(owner.root,eid,events)
    rows=history(owner.root);successes=sum(row['status']=='success' for row in rows)
    summary=dict(attempts=len(rows),successes=successes,failures=sum(row['status']=='failure' for row in rows),cancelled=sum(row['status']=='cancelled' for row in rows),
        safety_rejections=sum(row.get('diagnostics',{}).get('category')=='action_safety_rejection' for row in rows),success_rate=successes/len(rows) if rows else None,
        denominator='all recorded attempts, including rejection/errors/cancellation',completed_episodes=len(load_catalog(owner.root).episodes),latest=summary_report)
    atomic_json(owner.root/'evaluation-summary.json',summary)
    return summary


def rollout(plan,model,data,b,kin,policy_bundle,segment,claim,*,events,commands,env_index=0):
    """Each recorded pre-step row has one real, accepted physics command."""
    import mujoco,torch
    from .state import read_sample,snapshot
    from .source import initial_arrays
    from .control import command_target,step
    from ...data.video import AsyncVideoWriter
    from ...tasks.pick_place import numpy_corners,v8_placement
    policy,pre,post,record,contract=policy_bundle;policy.reset()
    eid='evaluation-'+str(claim['attempt']);ep=native_api()[0]();ep.seed=claim['seed'];add_initial(ep,initial_arrays(model,data,b))
    initial=snapshot(model,data,b);params=plan.function_bindings['success'].params
    signals={};trackers=trackers_for(plan,eid,env_index=env_index);state={};videos={};previous=None;latencies=[];tick=0;placed=False;grasp=False
    report=dict(env_index=env_index,success=False,category='max_steps',steps=0,first_grasp_post_tick=None,first_placement_post_tick=None,initial_snapshot=initial,policy_reset=True,physics_effect='not_started',recipe_sha256=plan.recipe_sha256)
    controls=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False)
    def sample(phase,t):
        row=read_sample(model,data,b,phase,t,episode_id=eid,env_index=env_index,object_id=params.object);row['signals']=dict(signals)
        dims=plan.scene.scene['objects'][params.object]['task_geometry']['dimensions_m']
        row['placement_points']={params.object:{'target_id':params.target,'points':numpy_corners(row['object_poses'][params.object],row['object_poses'][params.target],dims)}}
        return row
    initial_positions={n:p[:3,3].copy() for n,p in sample('pre_step',0)['object_poses'].items()};phase='camera';applying=False
    try:
        with mujoco.Renderer(model,height=480,width=640) as renderer:
            for name in ('side','wrist'):videos[name]=AsyncVideoWriter(segment.folder/(name+'.mp4'),env_index=env_index)
            while tick<report_limit(plan):
                events({'kind':'status','payload':{'episode_id':eid,'env_index':env_index,'tick':tick,'progress':{'applied_steps':tick}}})
                control_commands(commands(),controls,events,tick=tick,episode_id=eid,env_index=env_index)
                if controls['cancelled'] or controls['skipped']:
                    report.update(category='cancelled',steps=tick);return None,{},report
                if controls['paused'] and not controls['steps']:time.sleep(.01);continue
                phase='observation';before=sample('pre_step',tick);rgb={}
                phase='camera'
                for name in ('side','wrist'):renderer.update_scene(data,camera=name);rgb[name]=renderer.render().copy()
                phase='policy';batch=observation_batch(before['joint_positions'],rgb,joint_order=before['joint_order'],task=plan.effective_settings['execution'].get('task_instruction'));started=time.perf_counter()
                try:
                    original=infer(policy,pre,post,batch,contract=contract)[0]
                    target=preflight_action(original,limits=b.limits,applied_dtype=np.float64)
                    target=command_target(target,b)  # Keep the actual engine's final preflight.
                except ActionRejected as error:
                    error.diagnostics['applied_dtype']='float64';report.update(category='action_safety_rejection',rejection={'tick':tick,**error.diagnostics});break
                latencies.append(time.perf_counter()-started);goal=kin.forward_kinematics(target[:5]);phase='recording'
                record_frame(ep,before,goal,target,time_s=tick/30,base=b.world_from_robot_base,signals={'grasp':grasp,'place':v8_placement(before,params=params)},previous_pose=previous,command_requested=original,command_limits=b.limits)
                ep.add('obs/physics_timestamp',torch.tensor(float(data.time),dtype=torch.float64))
                for name,writer in videos.items():writer.write(rgb[name])
                phase='physics';applying=True;step(model,data,b,target);applying=False
                phase='task';after=sample('post_step',tick);placed,grasp=post_evaluation(plan,after,trackers,signals,state,initial_positions,report)
                ep.add('states/joint_pos',torch.from_numpy(after['joint_positions'].copy()))
                ep.add('states/joint_vel',torch.from_numpy(data.qvel[list(b.v_indices)].copy()))
                ep.add('states/finger_contact',torch.tensor([after['contacts']['left'],after['contacts']['right']],dtype=torch.bool))
                ep.add('states/grasp_latched',torch.tensor([grasp],dtype=torch.uint8));ep.add('states/placement',torch.tensor([placed],dtype=torch.uint8))
                ep.add('states/physics_timestamp',torch.tensor(float(data.time),dtype=torch.float64))
                ep.add('policy/action_queue_remaining',torch.tensor(len(policy._action_queue) if hasattr(policy,'_action_queue') else len(policy._queues['action']) if hasattr(policy,'_queues') else -1,dtype=torch.int64))
                previous=goal;step_completed(controls,events,tick);tick+=1;report['physics_effect']='applied'
                if placed:report.update(success=True,category='placement_success');break
        if placed or tick>=report_limit(plan):report.update(evaluation_result(placed=placed,grasp=grasp,steps=tick,limit=report_limit(plan)))
        report.update(steps=tick,inference_mean_s=float(np.mean(latencies)) if latencies else None,inference_calls=len(latencies),policy_chunk_steps=policy.config.n_action_steps,peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
        if not tick:return None,{},report
        ep.pre_export()
        if placed:ep.data['obs']['events']['place'][-1]=1
        for writer in videos.values():writer.close()
        return ep,{name:writer.video_path for name,writer in videos.items()},report
    except Exception as error:
        report.update(execution_failure(error,phase=phase,steps=tick,applying=applying))
        return None,{},report
    finally:
        from ..mujoco.source import command_summary
        try:report['saturation']=command_summary(ep)
        except Exception as error:report['saturation']={'status':'unavailable','reason':str(error)}
        abort_videos(videos,report)


def report_limit(plan):return max(1,int(np.ceil(plan.effective_settings['execution'].get('timeout_s',10)*30)))


def run(plan,*,events,commands):
    import mujoco
    from ...recipe import verify_prepared_inputs
    from ...run import StageResult
    from ...generation.mimic import bind_kinematics
    from .source import resolved_model_config,execution_contract,reset_placements
    from .model import build_model,JOINTS,_execution_urdf
    from .state import restore_episode
    verify_prepared_inputs(plan);cfg=resolved_model_config(plan)
    if tuple(cfg.active_object_ids)!=tuple(plan.object_order):raise ValueError('Evaluation creation order differs from explicit engine configuration')
    model,b=build_model(plan.scene,cfg);data=mujoco.MjData(model);bundle=policy_inputs(plan,b.urdf_sha256)
    kin=bind_kinematics(_execution_urdf(plan.scene),model_sha256=b.urdf_sha256,joint_order=JOINTS)
    execution=evaluation_execution(plan,execution_contract(plan,b,cfg),bundle[3]);previous=plan.resolved_inputs.get('resume_dataset')
    owner=resume_to(previous['path'],plan.output_path,execution) if previous else NativeRun(plan.output_path,execution)
    summary={};cancelled=False
    try:
        if plan.effective_settings['execution'].get('num_envs',1)>1:return rollout_parallel(plan,owner,model,b,kin,bundle,execution,events=events,commands=commands)
        attempts=history(owner.root)
        if len(attempts)>=execution['episodes']:raise ValueError('Cumulative evaluation attempts must exceed prior attempts')
        while len(history(owner.root))<execution['episodes']:
            number=max((a['attempt'] for a in history(owner.root)),default=0)+1;segment=owner.segment('evaluation-'+str(number));claim=owner.claim_attempt(segment)
            started=time.perf_counter()
            try:
                restore_episode(model,data,b,None);reset_placements(plan,model,data,b,claim['seed'])
            except Exception as error:ep,media,report=None,{},execution_failure(error,phase='reset',steps=0)
            else:ep,media,report=rollout(plan,model,data,b,kin,bundle,segment,claim,events=events,commands=commands)
            fatal=report.pop('_exception',None)
            report.update(elapsed_s=time.perf_counter()-started,actual_fps=report['steps']/(time.perf_counter()-started))
            summary=publish_attempt(owner,segment,claim,ep,media,report,events)
            if fatal is not None:raise fatal
            if report['category']=='cancelled':cancelled=True;break
        return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),len(load_catalog(owner.root).episodes),summary)
    finally:owner.close()


def rollout_parallel(plan,owner,model,b,kin,bundle,execution,*,events,commands):
    """Independent policy queues and MjData, one immutable Native publisher."""
    import copy,mujoco
    from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
    from .source import command_channels,reset_placements
    from .state import restore_episode
    from ...generation.mimic import bind_kinematics
    from .model import _execution_urdf,JOINTS
    from ...run import StageResult
    n=plan.effective_settings['execution']['num_envs'];states=[mujoco.MjData(model) for _ in range(n)]
    bundles=[copy.deepcopy(bundle) for _ in range(n)];kinematics=[bind_kinematics(_execution_urdf(plan.scene),model_sha256=b.urdf_sha256,joint_order=JOINTS) for _ in range(n)]
    polls,send=command_channels(commands,events,n);number=max((a['attempt'] for a in history(owner.root)),default=0);available=list(range(n));pending={};cancelled=False;fatal=None;summary={}
    def evaluate(i,segment,claim):
        started=time.perf_counter()
        try:restore_episode(model,states[i],b,None);placements=reset_placements(plan,model,states[i],b,claim['seed'])
        except Exception as error:ep,media,report=None,{},execution_failure(error,phase='reset',steps=0);placements=None
        else:ep,media,report=rollout(plan,model,states[i],b,kinematics[i],bundles[i],segment,claim,events=send,commands=polls[i],env_index=i)
        duration=time.perf_counter()-started;report.update(env_index=i,placements=placements,elapsed_s=duration,actual_fps=report['steps']/duration)
        return ep,media,report
    with ThreadPoolExecutor(max_workers=n,thread_name_prefix='mujoco-evaluation') as threads:
        try:
            while pending or (available and number<execution['episodes'] and not cancelled and fatal is None):
                while available and number<execution['episodes'] and not cancelled and fatal is None:
                    i=available.pop(0);number+=1;segment=owner.segment('evaluation-'+str(number));claim=owner.claim_attempt(segment)
                    pending[threads.submit(evaluate,i,segment,claim)]=(i,segment,claim)
                if not pending:break
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                for future in done:
                    i,segment,claim=pending.pop(future);ep,media,report=future.result();error=report.pop('_exception',None)
                    summary=publish_attempt(owner,segment,claim,ep,media,report,send);available.append(i);cancelled|=report['category']=='cancelled'
                    if error is not None:fatal=fatal or error;send.stop()
        finally:send.stop()
    if fatal is not None:raise fatal
    return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),len(load_catalog(owner.root).episodes),{**summary,'env_num':n})
