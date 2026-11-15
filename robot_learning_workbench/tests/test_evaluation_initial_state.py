"""Real rollout/Native publication contracts with explicit fake physics/Policy IO."""
from types import SimpleNamespace as NS
import numpy as np
import pytest
from robot_learning_workbench.data import native as n


@pytest.mark.parametrize('engine',['mujoco','isaac'])
@pytest.mark.parametrize('success_phase',['episode_start','pre_step','post_step'])
def test_initial_success_is_not_policy_success_and_never_creates_fake_action_rows(tmp_path,monkeypatch,engine,success_phase):
    import torch
    from robot_learning_workbench.tasks.registry import FunctionSpec
    from robot_learning_workbench.tasks import execution as tasks
    from robot_learning_workbench.recipe import FunctionBinding
    from robot_learning_workbench.robot.calibration import JOINTS
    from robot_learning_workbench.data.publication import publish_attempt
    from robot_learning_workbench.engines.mujoco import evaluation as mj_eval,source as mj_source,state as mj_state,control
    from robot_learning_workbench.engines.isaac import evaluation as isaac_eval
    binding=FunctionBinding('success','fixture.success','predicate',None,success_phase,{},())
    spec=NS(callable=lambda row,params:True)
    plan=NS(recipe_sha256='a'*64,function_bindings={'success':binding},tasks=NS(functions={'fixture.success':spec}),
        effective_settings={'execution':{'timeout_s':.1}})
    def sample(phase,tick):
        return dict(phase=phase,tick=tick,object_poses={},joint_positions=np.zeros(6),joint_velocities=np.zeros(6),
            contacts={'left':False,'right':False,'force_w':np.zeros((2,3))},
            joint_order=JOINTS,eef_pose=np.eye(4),cameras={key:{'rgb':np.zeros((8,8,3),np.uint8)}for key in('side','wrist')})
    policy=NS(reset=lambda:None,config=NS(n_action_steps=1));calls=[]
    bundle=(policy,None,None,{}, {'joint_order':JOINTS})
    evaluation=mj_eval if engine=='mujoco'else isaac_eval
    monkeypatch.setattr(evaluation,'infer',lambda *a,**k:(calls.append('infer')or np.zeros((1,6))))
    monkeypatch.setattr(evaluation,'observation_batch',lambda *a,**k:{})
    class Video:
        def __init__(self,path,**kwargs):self.video_path=path;self._closed=False
        def write(self,rgb):pass
        def close(self):self._closed=True
        def abort(self):self._closed=True
    from robot_learning_workbench.data import video
    monkeypatch.setattr(video,'AsyncVideoWriter',Video)
    if engine=='isaac':monkeypatch.setattr(evaluation,'AsyncVideoWriter',Video)
    config=dict(stage='simulation_evaluation',scene_identity={'revision':'fixture'},calibration={},task_code={},seed=7,engine=engine,
        recording={},model_sha256='model',active_objects=[],partition='unpartitioned',rng_policy='fixture',policy_identity='policy',evaluation_contract='fixture',episodes=1)
    with n.NativeRun(tmp_path/'attempts',config)as owner:
        segment=owner.segment('first');claim=owner.claim_attempt(segment)
        if engine=='mujoco':
            import mujoco
            class Renderer:
                def __init__(self,*a,**k):pass
                def __enter__(self):return self
                def __exit__(self,*a):pass
            monkeypatch.setattr(mujoco,'Renderer',Renderer)
            monkeypatch.setattr(mj_source,'initial_arrays',lambda *a:{'articulation':{},'rigid_object':{}})
            monkeypatch.setattr(mj_state,'snapshot',lambda *a:{})
            monkeypatch.setattr(mj_state,'read_sample',lambda model,data,b,phase,tick,**k:sample(phase,tick))
            monkeypatch.setattr(evaluation,'camera_rgb',lambda *a:np.zeros((8,8,3),np.uint8))
            monkeypatch.setattr(control,'command_target',lambda q,b:q)
            monkeypatch.setattr(control,'step',lambda *a:None)
            data=NS(time=0.,qvel=np.zeros(6));binding_model=NS(world_from_robot_base=np.eye(4),limits=np.tile([-2.,2.],(6,1)),v_indices=range(6))
            ep,media,report=evaluation.rollout(plan,None,data,binding_model,NS(forward_kinematics=lambda q:np.eye(4)),bundle,segment,claim,events=lambda _:None,commands=lambda:())
        else:
            monkeypatch.setattr(evaluation,'initial_state',lambda *a,**k:{'articulation':{},'rigid_object':{}})
            monkeypatch.setattr(evaluation,'task_sample',lambda env,p,phase,tick,eid,signals,**k:sample(phase,tick))
            env=NS(device='cpu',sim=NS(current_time=0.),scene=NS(env_origins=torch.zeros(1,3)),
                cfg=NS(workbench_inputs={'profile':{'robot_base':{'T_world':np.eye(4)}}},workbench_joint_limits_rad=[[-2,2]]*6),
                obs_buf={'policy':{'joint_pos':torch.zeros(1,6),'joint_vel':torch.zeros(1,6)}})
            generator=evaluation.rollout_steps(plan,env,NS(forward_kinematics=lambda q:np.eye(4)),bundle,segment,claim,events=lambda _:None,commands=lambda:())
            try:
                while True:next(generator)
            except StopIteration as result:ep,media,report=result.value
        if success_phase!='post_step':
            assert report['success']is False and report['category']=='initial_state_satisfied'
            assert report['initial_state_success']is True and report['policy_executed']is False
            assert report['steps']==0 and report['inference_calls']==0 and not calls and ep is None
        else:
            assert report['success']is True and report['steps']==1 and len(calls)==1 and ep is not None
            assert len(ep.data['actions'])==1
        summary=publish_attempt(owner,segment,claim,ep,{},report,lambda _:None)
        assert summary['attempts']==1 and summary['successes']==int(success_phase=='post_step')
        assert summary['success_rate']==float(success_phase=='post_step')
        assert summary['completed_episodes']==int(success_phase=='post_step')
        assert summary['initial_state_satisfied']==int(success_phase!='post_step')
    before={p:n.file_sha256(p)for p in owner.root.rglob('*')if p.is_file()}
    with n.resume_to(owner.root,tmp_path/'resumed',{**config,'episodes':2})as resumed:
        new=resumed.claim_attempt(resumed.segment('next'))
        assert new['attempt']==2
        assert len(n.load_catalog(resumed.root).episodes)==int(success_phase=='post_step')
    assert before=={p:n.file_sha256(p)for p in owner.root.rglob('*')if p.is_file()}
