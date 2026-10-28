"""Offline Isaac workflow input boundaries; actual app is a separate evidence run."""
import json
from pathlib import Path
import numpy as np
import pytest
ROOT=Path(__file__).resolve().parents[2]


def test_isaac_recording_preserves_native_dtype_and_phase():
    from robot_learning_workbench.engines.isaac.source import record_frame
    from robot_learning_workbench.data.native import native_api
    q=np.zeros(6,dtype=np.float32);pose=np.eye(4)
    row=dict(joint_positions=q,joint_velocities=q.copy(),eef_pose=pose,object_poses={'cube_red':pose})
    ep=native_api()[0]();record_frame(ep,row,pose,q,time_s=0.,base=pose)
    ep.pre_export()
    assert ep.data['joint_targets'].numpy().dtype==np.float32
    assert ep.data['obs']['policy']['joint_vel'].numpy().dtype==np.float32
    assert ep.data['obs']['datagen_info']['eef_pose']['tool0'].numpy().dtype==np.float32


def test_isaac_engine_settings_are_scene_bound():
    from robot_learning_workbench.engines.isaac.source import validate_settings
    settings=json.loads((ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text())
    validate_settings(settings)
    with pytest.raises(ValueError):validate_settings({**settings,'isaac':{'physics_timestep_s':1/240,'decimation':7}})


def test_post_physics_nonfinite_state_is_unknown_failure():
    import torch
    from types import SimpleNamespace as NS
    from robot_learning_workbench.engines.isaac.mdp import validate_post_state
    robot=NS(data=NS(root_state_w=torch.zeros(1,13),joint_pos=torch.zeros(1,6),joint_vel=torch.zeros(1,6)))
    env=NS(scene=NS(articulations={'robot':robot},rigid_objects={}))
    validate_post_state(env)
    robot.data.joint_vel[0,-1]=float('nan')
    with pytest.raises(RuntimeError,match='after command'):validate_post_state(env)


def test_fixed_robot_root_is_not_reapplied_as_a_measurement_command():
    import torch
    from types import SimpleNamespace as NS
    from robot_learning_workbench.engines.isaac.state import restore_episode
    from robot_learning_workbench.robot.calibration import JOINTS
    calls=[]
    def forbidden(*a,**k):raise AssertionError('Fixed root must remain authored by Scene reset')
    robot=NS(joint_names=list(JOINTS),data=NS(soft_joint_pos_limits=torch.tensor([[[-3.,3.]]*6])),write_root_pose_to_sim=forbidden,write_root_velocity_to_sim=forbidden,write_joint_state_to_sim=lambda *a,**k:calls.append('joints'),set_joint_position_target=lambda *a,**k:calls.append('target'))
    class Scene(dict):
        def write_data_to_sim(self):pass
        def update(self,dt):pass
    scene=Scene(robot=robot);scene.rigid_objects={};scene.env_origins=torch.zeros((1,3))
    env=NS(device='cpu',num_envs=1,cfg=NS(workbench_joint_order=JOINTS,workbench_inputs={'profile':{'robot_base':{'T_world':np.eye(4)}}}),scene=scene,reset=lambda **kw:None,sim=NS(forward=lambda:None),physics_dt=1/240,observation_manager=NS(compute=lambda:{}))
    values={'articulation':{'robot':{'root_pose':np.array([[0.,0,0,1,0,0,0]],dtype=np.float32),'root_velocity':np.zeros((1,6),np.float32),'joint_position':np.zeros((1,6),np.float32),'joint_velocity':np.zeros((1,6),np.float32)}},'rigid_object':{}}
    restore_episode(env,[0],values)
    assert calls==['joints','target']


def test_annotation_uses_recorded_creation_order_not_empty_recipe_objects():
    from types import SimpleNamespace as NS
    from robot_learning_workbench.engines.isaac.source import settings_for
    settings=json.loads((ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text())
    plan=NS(stage='annotation',object_order=(),effective_settings={'execution':{}},input_documents={})
    assert settings_for(plan,settings)['active_object_ids']==settings['active_object_ids']


def test_incompatible_fixed_root_is_rejected_before_reset():
    from types import SimpleNamespace as NS
    from robot_learning_workbench.engines.isaac.state import validate_fixed_base
    import torch
    env=NS(cfg=NS(workbench_inputs={'profile':{'robot_base':{'T_world':np.eye(4)}}}),scene=NS(env_origins=torch.zeros((1,3))))
    root={'root_pose':np.array([[0.,0,0,1.00000024,0,0,0]]),'root_velocity':np.zeros((1,6))}
    validate_fixed_base(env,[0],root)
    root['root_pose'][0,0]=.01
    with pytest.raises(ValueError):validate_fixed_base(env,[0],root)
    root['root_pose'][0,0]=0;root['root_velocity'][0,0]=.01
    with pytest.raises(ValueError):validate_fixed_base(env,[0],root)


def test_multi_episode_isaac_annotation_keeps_original_initial_contract():
    from types import SimpleNamespace
    from robot_learning_workbench.robot.calibration import JOINTS
    from robot_learning_workbench.engines.isaac.annotation import validate_source
    contract={'stage':'source','engine':'isaac','recording':{'joint_order':list(JOINTS),'units':'m_rad_s','pose_frame':'robot_base','observation_phase':'pre_step','task_phase':'post_step','fps':30,'resolution':[640,480]}}
    validate_source(SimpleNamespace(execution=contract,episodes=[SimpleNamespace(start=0,stop=None,num_frames=388)]))
    validate_source(SimpleNamespace(execution=contract,episodes=[SimpleNamespace(start=0,stop=None,num_frames=388),SimpleNamespace(start=0,stop=None,num_frames=388)]))
    with pytest.raises(ValueError,match='Nonempty'):validate_source(SimpleNamespace(execution=contract,episodes=[]))


def test_isaac_worker_shutdown_returns_before_terminal_publication(monkeypatch):
    import sys,types
    from types import SimpleNamespace
    from robot_learning_workbench import run
    closed=[]
    class Launcher:
        def __init__(self,**settings):
            self.fast=settings.get('fast_shutdown',True);self.app=self
        def close(self):
            if self.fast:raise SystemExit('SDK fast shutdown exits before execute writes terminal result')
            closed.append(True)
    monkeypatch.setitem(sys.modules,'isaaclab.app',types.SimpleNamespace(AppLauncher=Launcher))
    result=run.StageResult('completed',(),0,{})
    monkeypatch.setattr(run.importlib,'import_module',lambda *a,**kw:SimpleNamespace(run=lambda *a,**kw:result))
    plan=SimpleNamespace(stage='annotation',engine='isaac',effective_settings={'execution':{'headless':True}})
    assert run._run_stage(plan,events=lambda e:None,commands=lambda:()) is result
    assert closed==[True]
