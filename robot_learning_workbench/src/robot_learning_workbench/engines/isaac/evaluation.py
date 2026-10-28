"""Official Isaac Lab ACT rollout, after AppLauncher, safe bounded position targets.

https://isaac-sim.github.io/IsaacLab/v2.3.0/source/api/lab/isaaclab.envs.html
"""
from pathlib import Path
import time,resource,tempfile
import numpy as np
from .annotation import task_sample
from .state import initial_state,restore_episode
from .mdp import apply_joint_targets,validate_targets
from .source import settings_for,execution_contract,reset_placements,record_frame
from robot_learning_workbench.learning.policy import policy_inputs
from robot_learning_workbench.tasks.evaluation import evaluation_execution, trackers_for, post_evaluation, report_limit, evaluation_result
from robot_learning_workbench.data.publication import publish_attempt
from robot_learning_workbench.run import execution_failure
from robot_learning_workbench.run import abort_videos
from robot_learning_workbench.data.recording import add_initial
from robot_learning_workbench.commands import control_commands, step_completed
from ...learning.policy import infer,observation_batch,preflight_action,ActionRejected
from ...data.native import NativeRun,resume_to,history,load_catalog,native_api,DataError,file_sha256
from ...data.video import AsyncVideoWriter


def rollout(plan,env,kin,bundle,segment,claim,*,events,commands):
    from .mdp import complete_episode
    return complete_episode(env,rollout_steps(plan,env,kin,bundle,segment,claim,events=events,commands=commands))


def rollout_steps(plan,env,kin,bundle,segment,claim,*,events,commands,env_index=0):
    import torch
    from ...tasks.pick_place import v8_placement
    policy,pre,post,record,contract=bundle;policy.reset();eid='evaluation-'+str(claim['attempt'])
    ep=native_api()[0]();ep.seed=claim['seed'];add_initial(ep,initial_state(env,env_index,relative=True));params=plan.function_bindings['success'].params
    base=np.asarray(env.cfg.workbench_inputs['profile']['robot_base']['T_world']);bounds=np.array(env.cfg.workbench_joint_limits_rad)
    signals={};trackers=trackers_for(plan,eid,env_index=env_index);state={};videos={};previous=None;latencies=[];tick=0;placed=False;grasp=False
    report=dict(env_index=env_index,initial_frame='scene_world',engine_env_origin=env.scene.env_origins[env_index].cpu().numpy().tolist(),success=False,category='max_steps',steps=0,first_grasp_post_tick=None,first_placement_post_tick=None,policy_reset=True,physics_effect='not_started',recipe_sha256=plan.recipe_sha256)
    controls=dict(paused=False,steps=0,cancelled=False,marks=[],skipped=False)
    def sample(phase,t):return task_sample(env,plan,phase,t,eid,signals,params=params,env_index=env_index)
    initial_positions={n:p[:3,3].copy() for n,p in sample('pre_step',0)['object_poses'].items()};phase='camera';applying=False
    try:
        for name in ('side','wrist'):videos[name]=AsyncVideoWriter(segment.folder/(name+'.mp4'),env_index=env_index)
        while tick<report_limit(plan):
            events({'kind':'status','payload':{'episode_id':eid,'env_index':env_index,'tick':tick,'progress':{'applied_steps':tick}}})
            control_commands(commands(),controls,events,tick=tick,episode_id=eid,env_index=env_index)
            if controls['cancelled'] or controls['skipped']:report.update(category='cancelled',steps=tick);return None,{},report
            if controls['paused'] and not controls['steps']:yield None;continue
            phase='camera';before=sample('pre_step',tick);rgb={name:row['rgb'] for name,row in before['cameras'].items()}
            phase='policy';batch=observation_batch(before['joint_positions'],rgb,joint_order=before['joint_order'],task=plan.effective_settings['execution'].get('task_instruction'));started=time.perf_counter()
            try:
                original=infer(policy,pre,post,batch,contract=contract)[0]
                target=preflight_action(original,limits=bounds,applied_dtype=np.float32)
                target=validate_targets(target[None],bounds[None])[0]  # Actual engine preflight also required.
            except ActionRejected as error:
                error.diagnostics['applied_dtype']='float32';report.update(category='action_safety_rejection',rejection={'tick':tick,**error.diagnostics});break
            latencies.append(time.perf_counter()-started);goal=kin.forward_kinematics(target[:5]);phase='recording'
            record_frame(ep,before,goal,target,time_s=tick/30,base=base,signals={'grasp':grasp,'place':v8_placement(before,params=params)},previous_pose=previous,command_requested=original,command_limits=bounds)
            ep.add('obs/physics_timestamp',torch.tensor(float(env.sim.current_time),dtype=torch.float64))
            for name,writer in videos.items():writer.write(rgb[name])
            phase='physics';applying=True
            yield target
            applying=False
            phase='task';after=sample('post_step',tick);placed,grasp=post_evaluation(plan,after,trackers,signals,state,initial_positions,report)
            ep.add('states/joint_pos',torch.from_numpy(after['joint_positions'].copy()));ep.add('states/joint_vel',torch.from_numpy(after['joint_velocities'].copy()))
            ep.add('states/finger_contact',torch.tensor([after['contacts']['left'],after['contacts']['right']],dtype=torch.bool));ep.add('states/contact_force_w',torch.from_numpy(after['contacts']['force_w'].copy()))
            ep.add('states/grasp_latched',torch.tensor([grasp],dtype=torch.uint8));ep.add('states/placement',torch.tensor([placed],dtype=torch.uint8))
            ep.add('states/physics_timestamp',torch.tensor(float(env.sim.current_time),dtype=torch.float64))
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
        from robot_learning_workbench.data.recording import command_summary
        try:report['saturation']=command_summary(ep)
        except Exception as error:report['saturation']={'status':'unavailable','reason':str(error)}
        abort_videos(videos,report)


def run(plan,*,events,commands):
    from isaaclab.envs import ManagerBasedEnv
    from .env_cfg import execution_inputs,build_env_cfg
    from ...recipe import verify_prepared_inputs
    from ...run import StageResult
    from ...generation.mimic import bind_kinematics
    from ...robot.calibration import JOINTS
    verify_prepared_inputs(plan);settings=settings_for(plan)
    if tuple(settings['active_object_ids'])!=tuple(plan.object_order):raise ValueError('Evaluation object order differs from bound Scene')
    inputs=execution_inputs(plan.scene,settings);urdf=inputs['robot_urdf'];sha=file_sha256(urdf)
    bundle=policy_inputs(plan,sha);kin=bind_kinematics(urdf,model_sha256=sha,joint_order=JOINTS)
    execution=evaluation_execution(plan,execution_contract(plan,settings),bundle[3]);previous=plan.resolved_inputs.get('resume_dataset')
    owner=resume_to(previous['path'],plan.output_path,execution) if previous else NativeRun(plan.output_path,execution)
    env=None;summary={};cancelled=False
    try:
        if len(history(owner.root))>=execution['episodes']:raise ValueError('Cumulative evaluation attempts must exceed prior attempts')
        with tempfile.TemporaryDirectory(prefix='isaac-evaluation-',dir=plan.output_path.parent) as temporary:
            env=ManagerBasedEnv(cfg=build_env_cfg(plan.scene,settings,num_envs=plan.effective_settings['execution'].get('num_envs',1),runtime_directory=Path(temporary)/'runtime'));env.reset()
            if env.num_envs>1:return rollout_vector(plan,owner,env,kin,bundle,execution,events=events,commands=commands)
            reference=initial_state(env)
            while len(history(owner.root))<execution['episodes']:
                number=max((a['attempt'] for a in history(owner.root)),default=0)+1;segment=owner.segment('evaluation-'+str(number));claim=owner.claim_attempt(segment)
                started=time.perf_counter()
                try:
                    restore_episode(env,[0],reference);reset_placements(plan,env,claim['seed'])
                except Exception as error:ep,media,report=None,{},execution_failure(error,phase='reset',steps=0)
                else:ep,media,report=rollout(plan,env,kin,bundle,segment,claim,events=events,commands=commands)
                fatal=report.pop('_exception',None)
                report.update(elapsed_s=time.perf_counter()-started,actual_fps=report['steps']/(time.perf_counter()-started))
                summary=publish_attempt(owner,segment,claim,ep,media,report,events)
                if fatal is not None:raise fatal
                if report['category']=='cancelled':cancelled=True;break
            return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),len(load_catalog(owner.root).episodes),summary)
    finally:
        try:
            if env is not None:env.close()
        finally:owner.close()


def rollout_vector(plan,owner,env,kin,bundle,execution,*,events,commands):
    import copy
    from .mdp import advance_streams
    from .source import abort_streams
    from .env_cfg import execution_inputs
    from robot_learning_workbench.commands import command_channels
    from ...generation.mimic import bind_kinematics
    from ...robot.calibration import JOINTS
    from ...run import StageResult
    n=env.num_envs;polls,send=command_channels(commands,events,n,vector=True);bundles=[copy.deepcopy(bundle) for _ in range(n)]
    urdf=execution_inputs(plan.scene,env.cfg.workbench_settings if hasattr(env.cfg,'workbench_settings') else plan.input_documents['engine_config'])['robot_urdf']
    kinematics=[bind_kinematics(urdf,model_sha256=kin.model_sha256,joint_order=JOINTS) for _ in range(n)];references=[initial_state(env,i) for i in range(n)]
    number=max((r['attempt'] for r in history(owner.root)),default=0);streams={};pending={};ready={};available=list(range(n));cancelled=False;summary={}
    try:
        while streams or (available and number<execution['episodes'] and not cancelled):
            while available and number<execution['episodes'] and not cancelled:
                i=available.pop(0);number+=1;segment=owner.segment('evaluation-'+str(number));claim=owner.claim_attempt(segment);started=time.perf_counter()
                try:restore_episode(env,[i],references[i]);placements=reset_placements(plan,env,claim['seed'],env_index=i)
                except Exception as error:
                    report=execution_failure(error,phase='reset',steps=0);report.pop('_exception',None);publish_attempt(owner,segment,claim,None,{},report,send);raise
                streams[i]=rollout_steps(plan,env,kinematics[i],bundles[i],segment,claim,events=send,commands=polls[i],env_index=i);pending[i]=(segment,claim,started,placements)
            if not streams:break
            send.refresh()
            if send.cancelled():cancelled=True;send.ack_cancel();break
            done,_=advance_streams(env,streams,ready,pause_check=send.paused)
            for i,result in done.items():
                segment,claim,started,placements=pending.pop(i);streams.pop(i);ready.pop(i,None);available.append(i)
                if isinstance(result,Exception):report=execution_failure(result,phase='physics',steps=0,applying=True);ep=None;media={}
                else:ep,media,report=result
                fatal=report.pop('_exception',None);elapsed=time.perf_counter()-started;report.update(placements=placements,elapsed_s=elapsed,actual_fps=report['steps']/elapsed)
                summary=publish_attempt(owner,segment,claim,ep,media,report,send);cancelled|=report['category']=='cancelled'
                if fatal is not None:raise fatal
            if cancelled:break
    finally:abort_streams(streams,pending,cancelled=cancelled)
    return StageResult('cancelled' if cancelled else 'completed',(str(owner.root),),len(load_catalog(owner.root).episodes),{**summary,'env_num':n})
