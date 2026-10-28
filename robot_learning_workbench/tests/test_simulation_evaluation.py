"""P01 strict output boundary and completed-failure Native semantics."""
from pathlib import Path
import numpy as np
import pytest
from robot_learning_workbench.robot.calibration import JOINTS


def test_policy_payload_saturates_inside_exact_model_bounds():
    from robot_learning_workbench.learning.policy import preflight_action
    bounds=np.array([[-2.,2.]]*6);bounds[3,1]=1.7453264625997165
    target=np.zeros(6);target[3]=bounds[3,1];diagnostics={}
    np.testing.assert_array_equal(preflight_action(target,limits=bounds,applied_dtype=np.float64),target)
    payload=preflight_action(target,limits=bounds,applied_dtype=np.float32,diagnostics=diagnostics)
    assert payload[3]==1.7453263998031616 and diagnostics['saturated_joints']==['wrist_flex']
    assert target[3]==bounds[3,1]


@pytest.mark.parametrize('kind',['large','tiny','nan','shape'])
def test_policy_distinguishes_finite_saturation_from_invalid_input(kind):
    from robot_learning_workbench.learning.policy import preflight_action,ActionRejected
    value=np.zeros(6);bounds=np.array([[-1.,1.]]*6)
    if kind=='large':value[0]=5
    elif kind=='tiny':value[0]=np.nextafter(1.,2.)
    elif kind=='nan':value[0]=np.nan
    else:value=np.zeros(7)
    if kind in ('nan','shape'):
        with pytest.raises(ActionRejected) as error:preflight_action(value,limits=bounds,applied_dtype=np.float64)
        assert error.value.diagnostics['command_applied'] is False
    else:
        q=preflight_action(value,limits=bounds,applied_dtype=np.float64)
        assert q[0]==1. and value[0]>1.


def test_live_policy_batch_preserves_rgb_order_and_pre_state():
    from robot_learning_workbench.learning.policy import observation_batch
    rgb=np.arange(480*640*3,dtype=np.uint8).reshape(480,640,3);q=np.arange(6,dtype=np.float64)
    b=observation_batch(q,{'side':rgb,'wrist':rgb},joint_order=JOINTS)
    assert b['observation.state'].shape==(1,6)
    assert b['observation.images.side'].shape==(1,3,480,640)
    np.testing.assert_array_equal(b['observation.state'].numpy()[0],q.astype(np.float32))
    np.testing.assert_array_equal((b['observation.images.side'].numpy()[0].transpose(1,2,0)*255).round().astype(np.uint8),rgb)


def test_evaluation_success_is_placement_independent_of_grasp():
    from robot_learning_workbench.engines.mujoco.evaluation import evaluation_result
    assert evaluation_result(placed=True,grasp=False,steps=1,limit=10)['category']=='placement_success'
    assert evaluation_result(placed=False,grasp=True,steps=10,limit=10)['category']=='max_steps'


def test_completed_failure_episode_resumes_but_unknown_and_changed_policy_do_not(tmp_path):
    import torch
    from robot_learning_workbench.data.native import NativeRun,native_api,resume_to,load_catalog,history
    execution=dict(stage='simulation_evaluation',scene_identity={'revision':'one'},calibration={},task_code={},seed=7,engine='mujoco',recording={},model_sha256='model',active_objects=['cube'],partition='unpartitioned',rng_policy='fixed',policy_identity='policy-a',evaluation_contract='recipe-a',episodes=1)
    ep=native_api()[0]();ep.data={'actions':torch.zeros((2,7)),'obs':{'policy':{'joint_pos':torch.zeros((2,6))}}};ep.success=False
    with NativeRun(tmp_path/'old',execution) as run:
        segment=run.segment('evaluation-1');claim=run.claim_attempt(segment)
        segment.write_episode(ep,episode_id='evaluation-1');segment.record_attempt(claim,status='failure',episode_id='evaluation-1',diagnostics={'category':'max_steps'});segment.commit()
    for key in ('policy_identity','model_sha256','scene_identity','evaluation_contract'):
        wrong={**execution,key:'different','episodes':2}
        with pytest.raises(ValueError):resume_to(tmp_path/'old',tmp_path/key,wrong)
        assert not (tmp_path/key).exists()
    with resume_to(tmp_path/'old',tmp_path/'new',{**execution,'episodes':2}) as run:
        assert len(load_catalog(run.root).episodes)==1 and history(run.root)[0]['status']=='failure'
    with NativeRun(tmp_path/'unknown',execution) as run:
        run.claim_attempt(run.segment('evaluation-1'))
    with pytest.raises(ValueError):resume_to(tmp_path/'unknown',tmp_path/'no-auto',execution)
    assert not (tmp_path/'no-auto').exists()


def test_execution_error_preserves_structured_identity_and_trace(capsys):
    from robot_learning_workbench.engines.mujoco.evaluation import execution_failure
    from robot_learning_workbench.data.native import DataError
    try:raise DataError('CALIBRATION_INVALID','robot','wrong model',effect='not_started')
    except DataError as error:report=execution_failure(error,phase='reset',steps=0)
    assert report['error']['code']=='CALIBRATION_INVALID'
    assert report['error']['issues'][0]['field']=='robot'
    assert report['_exception'].code=='CALIBRATION_INVALID'
    assert report['error']['effect']=='unknown'
    assert 'wrong model' in capsys.readouterr().err


def prepared_evaluation(tmp_path):
    import json,yaml
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    root=Path(__file__).resolve().parents[2]
    spec=yaml.safe_load((root/'docs/evidence/p01-rollout/mujoco-first.yaml').read_text());spec['output']['directory']=str(tmp_path/'out')
    spec['execution']['timeout_s']=.1
    p=tmp_path/'evaluation.yaml';p.write_text(yaml.safe_dump(spec,sort_keys=False))
    return prepare_recipe(read_recipe(p),tasks=load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement')))


def test_observed_reset_error_is_committed_failure_and_owner_closed(tmp_path,monkeypatch):
    from robot_learning_workbench.engines.mujoco import evaluation,source
    from robot_learning_workbench.data.native import history,recover,read_json
    from robot_learning_workbench.tasks.registry import TaskError
    plan=prepared_evaluation(tmp_path)
    def reject(*args):raise TaskError('PLACEMENT_INVALID','objects.cube_red','injected reset failure')
    monkeypatch.setattr(source,'reset_placements',reject)
    with pytest.raises(TaskError):evaluation.run(plan,events=lambda row:None,commands=lambda:())
    rows=history(plan.output_path);assert len(rows)==1 and rows[0]['status']=='failure'
    assert rows[0]['diagnostics']['error']['code']=='PLACEMENT_INVALID'
    assert read_json(plan.output_path/'run.json')['closed']
    assert not recover(plan.output_path)['unresolved_intents']


def test_injected_large_second_action_is_saturated_and_recorded_before_real_engine(tmp_path,monkeypatch):
    """Controlled fault test, not evidence the learned checkpoint emitted this target."""
    from robot_learning_workbench.engines.mujoco import evaluation,control
    from robot_learning_workbench.data.native import load_catalog,read_array
    plan=prepared_evaluation(tmp_path);original=evaluation.infer;calls=[];steps=[];engine_step=control.step
    def unsafe(*args,**kwargs):
        action=original(*args,**kwargs);calls.append(action.copy())
        if len(calls)==2:action[0,0]=100.
        return action
    def apply(*args):steps.append(np.array(args[-1],copy=True));return engine_step(*args)
    monkeypatch.setattr(evaluation,'infer',unsafe);monkeypatch.setattr(control,'step',apply)
    result=evaluation.run(plan,events=lambda row:None,commands=lambda:())
    assert result.status=='completed' and len(steps)==3
    episode=load_catalog(plan.output_path).episodes[0]
    assert episode.num_frames==3 and episode.metadata['category']=='max_steps'
    assert read_array(episode,'commands/requested_joint_rad')[1,0]==100.
    assert read_array(episode,'commands/saturation_mask')[1,0]
    assert read_array(episode,'joint_targets')[1,0]==steps[1][0]<100.
    assert episode.metadata['saturation']['saturated_steps']==1
    np.testing.assert_array_equal(read_array(episode,'commands/applied_joint_rad'),np.stack(steps))


def test_isaac_close_error_still_closes_native_owner(tmp_path,monkeypatch):
    """Lifecycle unit only: no fake engine success or rollout acceptance."""
    import sys,types
    from robot_learning_workbench.engines.isaac import evaluation,env_cfg
    from robot_learning_workbench.data import native
    from robot_learning_workbench.generation import mimic
    from robot_learning_workbench import recipe
    plan=prepared_evaluation(tmp_path);plan=__import__('dataclasses').replace(plan,engine='isaac')
    monkeypatch.setattr(evaluation,'settings_for',lambda plan:{'active_object_ids':list(plan.object_order)})
    monkeypatch.setattr(env_cfg,'execution_inputs',lambda *args:{'robot_urdf':Path(__file__)})
    monkeypatch.setattr(env_cfg,'build_env_cfg',lambda *args,**kwargs:None)
    monkeypatch.setattr(evaluation,'policy_inputs',lambda *args:(None,None,None,{},None))
    monkeypatch.setattr(evaluation,'evaluation_execution',lambda *args:{'episodes':1})
    monkeypatch.setattr(evaluation,'execution_contract',lambda *args:{})
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda plan:None)
    monkeypatch.setattr(mimic,'bind_kinematics',lambda *args,**kwargs:None)
    closed=[]
    class Owner:
        root=tmp_path/'unused'
        def __init__(self,*args):pass
        def close(self):closed.append('owner')
    class Env:
        def __init__(self,**kwargs):pass
        def reset(self):raise RuntimeError('injected setup failure')
        def close(self):closed.append('env');raise RuntimeError('injected close failure')
    monkeypatch.setattr(evaluation,'NativeRun',Owner);monkeypatch.setattr(evaluation,'history',lambda *args:[])
    monkeypatch.setitem(sys.modules,'isaaclab.envs',types.SimpleNamespace(ManagerBasedEnv=Env))
    with pytest.raises(RuntimeError,match='close failure'):evaluation.run(plan,events=lambda row:None,commands=lambda:())
    assert closed==['env','owner']


def test_abort_failure_still_attempts_remaining_video_cleanup():
    from robot_learning_workbench.engines.mujoco.evaluation import abort_videos
    closed=[];report={'success':False,'category':'cancelled','steps':2}
    class Video:
        _closed=False
        def __init__(self,name):self.name=name
        def abort(self):
            closed.append(self.name)
            if self.name=='side':raise OSError('injected unlink error')
    abort_videos({'side':Video('side'),'wrist':Video('wrist')},report)
    assert closed==['side','wrist'] and report['category']=='execution_error'
    assert isinstance(report['_exception'],ExceptionGroup)


def test_native_evaluation_identity_includes_training_dataset_and_processors(tmp_path):
    from robot_learning_workbench.engines.mujoco.evaluation import evaluation_execution
    from robot_learning_workbench.data.native import digest
    plan=prepared_evaluation(tmp_path)
    record={'files':{'policy_preprocessor.json':'a','model.safetensors':'b'},'step':4,'control_contract':None,'dataset_identity':{'dataset_id':'train','metadata_sha256':'identity'}}
    result=evaluation_execution(plan,{'recording':{}},record)
    assert result['policy_identity']==digest(record)
    assert result['policy_training_dataset']==record['dataset_identity']
    assert result['policy_files']==record['files'] and result['policy_checkpoint_step']==4
