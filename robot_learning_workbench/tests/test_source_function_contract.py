"""One Task binding contract across live/recorded and single/vector Source."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace as NS
import copy
import json
import numpy as np
import pytest
from test_recipe_preparation import scene,source_doc
from robot_learning_workbench import recipe
from robot_learning_workbench.data import native as n


@pytest.fixture
def plans(tmp_path,monkeypatch,scene):
    import uuid,sys
    from robot_learning_workbench.tasks.registry import load_registry
    name='source_contract_'+uuid.uuid4().hex;path=tmp_path/(name+'.py')
    path.write_text('''from dataclasses import dataclass
from robot_learning_workbench.tasks.registry import FunctionSpec
from robot_learning_workbench.tasks.pick_place import SignalValue
@dataclass(frozen=True)
class Params:
 threshold:float=.2
def metric(sample,*,params):return {'threshold':params.threshold,'tick':sample['tick']}
class Tracker:
 def __init__(self,p):self.p=p
 def update(self,sample):return SignalValue(sample['tick']>=self.p.threshold,sample['tick'],sample['phase'],{})
def tracker(*,params,episode):return Tracker(params)
FUNCTIONS={'contract.metric':FunctionSpec(kind='metrics',stages={'source'},engines={'independent'},params_type=Params,callable=metric),
 'contract.tracker':FunctionSpec(kind='tracker',stages={'source'},engines={'independent'},params_type=Params,callable=tracker,bindings={'source':{'phase':'pre_step'}})}
''')
    monkeypatch.syspath_prepend(str(tmp_path));tasks=load_registry(('robot_learning_workbench.tasks.placement',name))
    def build(threshold):
        functions={'metrics':{'function':'contract.metric','params':{'threshold':threshold}},
                   'signals':{'seen':{'function':'contract.tracker','params':{'threshold':threshold}}}}
        return recipe.prepare_recipe(source_doc(tmp_path,functions=functions),scene=scene,tasks=tasks,inputs={})
    yield build
    sys.modules.pop(name,None)


def _contract(plan,engine,tmp_path,monkeypatch):
    if engine=='mujoco':
        from robot_learning_workbench.engines.mujoco.source import execution_contract
        from robot_learning_workbench.engines.mujoco.model import ModelConfig
        return execution_contract(plan,NS(model_sha256='a'*64,urdf_sha256='b'*64,dynamic_objects=('cube_red',)),ModelConfig((0.,)*6,('cube_red',),{}))
    from robot_learning_workbench.engines.isaac import source,env_cfg
    urdf=tmp_path/'model.urdf';urdf.write_text('<robot name="synthetic"><link name="base"/></robot>')
    monkeypatch.setattr(env_cfg,'execution_inputs',lambda *a:{'robot_urdf':urdf})
    monkeypatch.setattr(source,'model_identity',lambda *a:'a'*64)
    from robot_learning_workbench.robot.calibration import JOINTS
    package=NS(scene={**plan.scene.scene,'robot':{**plan.scene.scene['robot'],'joint_order':list(JOINTS)}},calibration=plan.scene.calibration)
    return source.execution_contract(replace(plan,engine='isaac',scene=package),{'active_object_ids':['cube_red']})


@pytest.mark.parametrize('engine',['mujoco','isaac'])
def test_source_execution_binds_actual_function_parameters_for_every_input_kind(tmp_path,monkeypatch,plans,engine):
    plan=plans(.2);other=plans(.9);one=_contract(plan,engine,tmp_path,monkeypatch);two=_contract(other,engine,tmp_path,monkeypatch)
    assert one['source_functions']['metrics']['params']['threshold']==.2
    assert one['source_functions']['signals.seen']['params']['threshold']==.2
    assert n.semantic_identity(one)!=n.semantic_identity(two)
    # Real Source append accepts the identical producer, but never parameter drift.
    from test_native_dataset import episode
    root=tmp_path/'native'
    with n.NativeRun(root,one)as run:
        seg=run.segment('first');claim=run.claim_attempt(seg);seg.write_episode(episode(),episode_id='one');seg.record_attempt(claim,status='success',episode_id='one');seg.commit()
    before={p:n.file_sha256(p)for p in root.rglob('*')if p.is_file()}
    with pytest.raises(n.DataError,match='source_functions'):n.NativeRun(root,two,append=True)
    assert before=={p:n.file_sha256(p)for p in root.rglob('*')if p.is_file()}
    with n.NativeRun(root,one,append=True)as run:assert len(n.load_catalog(run.root).episodes)==1


def test_recorded_isaac_vector_keeps_plan_and_records_actual_declared_metrics_and_signal(tmp_path,monkeypatch,plans):
    import torch
    from robot_learning_workbench.engines.isaac import source,mdp,state,env_cfg
    from robot_learning_workbench.generation import mimic
    from robot_learning_workbench.robot.calibration import JOINTS
    from test_native_dataset import execution,episode
    plan=replace(plans(.2),engine='isaac');original=source.collection_steps
    monkeypatch.setattr(env_cfg,'execution_inputs',lambda *a:{'robot_urdf':tmp_path/'unused.urdf'})
    monkeypatch.setattr(mimic,'bind_kinematics',lambda *a,**k:NS(forward_kinematics=lambda q:np.eye(4)))
    monkeypatch.setattr(source,'initial_state',lambda *a,**k:{'articulation':{},'rigid_object':{}})
    monkeypatch.setattr(state,'restore_episode',lambda *a,**k:None);monkeypatch.setattr(source,'reset_placements',lambda *a,**k:None)
    monkeypatch.setattr(source,'pose_delta_action',lambda *a:torch.zeros(7))
    def sample(env,index,phase,tick,**kwargs):
        return dict(episode_id=kwargs['episode_id'],env_index=index,phase=phase,tick=tick,joint_positions=np.ones(6,np.float32),
            joint_velocities=np.zeros(6,np.float32),eef_pose=np.eye(4),object_poses={},
            cameras={key:{'rgb':np.zeros((8,8,3),np.uint8)}for key in('side','wrist')})
    monkeypatch.setattr(source,'read_sample',sample)
    class Video:
        def __init__(self,path,**kwargs):self.video_path=path;self._closed=False
        def write(self,rgb):pass
        def close(self):self._closed=True
        def abort(self):self._closed=True
    monkeypatch.setattr(source,'AsyncVideoWriter',Video)
    def collect(*args,**kwargs):
        gen=original(*args,**kwargs)
        try:
            while True:yield next(gen)
        except StopIteration as result:
            ep,media,initial,status=result.value
            return ep,{},initial,status  # Codec-only boundary: the real arrays are published.
    monkeypatch.setattr(source,'collection_steps',collect)
    env=NS(num_envs=2,device='cpu',sim=NS(current_time=0.),cfg=NS(workbench_joint_order=JOINTS,
        workbench_inputs={'profile':{'robot_base':{'T_world':np.eye(4)}}},workbench_joint_limits_rad=[[-2,2]]*6),
        obs_buf={'policy':{key:torch.zeros(2,width)for key,width in [('ee_state',7),('joint_pos',6),('joint_vel',6)]}})
    class Scene(dict):pass
    env.scene=Scene(robot=NS(joint_names=JOINTS,data=NS(joint_pos_target=torch.ones(2,6))));env.scene.env_origins=torch.zeros(2,3)
    monkeypatch.setattr(mdp,'apply_joint_targets',lambda e,t:setattr(e.sim,'current_time',e.sim.current_time+1/30))
    settings=execution('source');settings.update(engine='isaac',rng_policy='entropy_placement_per_call_v1',model_config={});settings.pop('seed')
    with n.NativeRun(tmp_path/'streams',settings)as run:
        seg=run.segment('streams')
        for i in range(2):seg.write_episode(episode(3),episode_id='e'+str(i))
        seg.commit()
    catalog=n.load_catalog(run.root);before={p:n.file_sha256(p)for p in run.root.rglob('*')if p.is_file()}
    with n.NativeRun(tmp_path/'recorded-vector',settings)as owner:
        result=source.collect_vector(plan,owner,env,NS(model_sha256='b'*64),catalog,{'episodes':2},events=lambda _:None,commands=lambda:())
    assert result.status=='completed'and result.completed_episodes==2
    for ep in n.load_catalog(owner.root).episodes:
        np.testing.assert_array_equal(n.read_array(ep,'metrics/pre_step/metrics/threshold'),[.2]*3)
        np.testing.assert_array_equal(n.read_array(ep,'obs/events/seen').reshape(-1),[0,1,1])
    assert before=={p:n.file_sha256(p)for p in run.root.rglob('*')if p.is_file()}


def test_single_mujoco_source_records_the_same_task_metrics_and_signals(tmp_path,plans):
    import mujoco
    from scene_contract.package import load_scene
    from robot_learning_workbench.engines.mujoco import source
    from robot_learning_workbench.engines.mujoco.model import ModelConfig,build_model,JOINTS
    from robot_learning_workbench.engines.mujoco.state import restore_episode
    root=Path(__file__).resolve().parents[2]
    settings=json.loads((root/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text());package=Path(settings['package_root'])
    physics=json.loads((package/settings['baseline_metadata']['compiled_physics']['asset_path']).read_text())['objects']
    cfg=ModelConfig(tuple(settings['initial_joint_rad'][name]for name in JOINTS),('cube_red',),physics)
    model,b=build_model(load_scene(package/'scene.json'),cfg);data=mujoco.MjData(model);restore_episode(model,data,b,None)
    target=data.qpos[list(b.q_indices)].copy();plan=plans(.2)
    with n.NativeRun(tmp_path/'single',{'stage':'source','seed':4})as owner:
        segment=owner.segment('one')
        ep,media,initial,status=source.collect_episode(model,data,b,segment,plan=plan,episode_id='single',frames=3,
            read_target=lambda:target,events=lambda _:None,commands=lambda:())
        assert status=='completed';segment.write_episode(ep,episode_id='one',media=media);segment.commit()
    ep=n.load_catalog(owner.root).episodes[0]
    np.testing.assert_array_equal(n.read_array(ep,'metrics/pre_step/metrics/threshold'),[.2]*3)
    np.testing.assert_array_equal(n.read_array(ep,'obs/events/seen').reshape(-1),[0,1,1])
