"""Real MuJoCo3.3.7 dynamics and state boundaries, no hardware/IK/workflow."""
from pathlib import Path
import copy,json
import numpy as np
import pytest
from scene_contract.package import load_scene

ROOT=Path(__file__).resolve().parents[2]
PACKAGE=ROOT/'docs/evidence/simulation-engine/runspace/scene'


def test_robot_compiler_keeps_calibrated_model_and_installs_finger_parts():
    from robot_learning_workbench.engines.mujoco.model import robot_xml,JOINTS
    from scipy.spatial.transform import Rotation
    import mujoco
    from xml.etree import ElementTree as ET
    old=Path('/home/hyeonhee/soarm_isaaclab/soarm101_lab')
    urdf=old/'outputs/real2sim/environments/scene2_builder/v8/assets/SO101/urdf/so101_sim.urdf'
    convex=json.loads((old/'assets/SO101/mujoco/finger_convex_parts.json').read_text())
    pads=json.loads((old/'assets/SO101/mujoco/usd_contact_pads.json').read_text())
    node,limits,hashes=robot_xml(urdf,np.eye(4),convex,pads)
    model=mujoco.MjModel.from_xml_string(ET.tostring(node,encoding='unicode'))
    assert model.njnt==6 and model.nu==6
    assert [model.joint(n).name for n in JOINTS]==list(JOINTS)
    assert len([i for i in range(model.ngeom) if '_collision_' in (model.geom(i).name or '') and '_part_' in model.geom(i).name])==sum(len(m['parts']) for m in convex['meshes'])
    assert model.geom('gripper_contact_pad').contype==2
    assert model.geom('jaw_contact_pad').contype==2
    assert not any('snapshot' in (model.body(i).name or '') for i in range(model.nbody))
    assert len(limits)==6 and len(hashes)>6


def config_from_evidence():
    from robot_learning_workbench.engines.mujoco.model import ModelConfig,JOINTS
    settings=json.loads((ROOT/'docs/evidence/simulation-engine/runtime-inputs.json').read_text())
    physics=json.loads((PACKAGE/settings['baseline_metadata']['compiled_physics']['asset_path']).read_text())['objects']
    return ModelConfig(initial_joint_rad=tuple(settings['initial_joint_rad'][n] for n in JOINTS),active_object_ids=tuple(settings['active_object_ids']),object_physics=physics)


def test_dynamic_scene_binds_articulation_objects_and_live_wrist_camera():
    import mujoco
    from robot_learning_workbench.engines.mujoco.model import build_model,JOINTS
    package=load_scene(PACKAGE/'scene.json');model,bindings=build_model(package,config_from_evidence());data=mujoco.MjData(model)
    assert model.nu==6 and len(bindings.joint_ids)==6 and bindings.dynamic_objects==('cube_red',)
    assert mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'robot_base_0')==-1
    assert mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'cube_blue')==-1
    assert mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'cube_green')==-1
    assert len(bindings.finger_geom_ids)>3 and model.camera('wrist').bodyid==model.body('robot_gripper').id
    assert model.opt.timestep==1/300 and bindings.decimation==10
    assert all(model.actuator_trnid[aid,0]==jid for jid,aid in zip(bindings.joint_ids,bindings.actuator_ids))
    assert bindings.urdf_sha256==package.calibration['records']['residual']['execution_model_sha256']
    assert bindings.scene_identity==package.identity


@pytest.fixture
def engine():
    import mujoco
    from robot_learning_workbench.engines.mujoco.model import build_model
    from robot_learning_workbench.engines.mujoco.state import restore_episode
    model,bindings=build_model(load_scene(PACKAGE/'scene.json'),config_from_evidence());data=mujoco.MjData(model)
    restore_episode(model,data,bindings,None)
    return model,data,bindings


def test_real_step_changes_state_and_full_snapshot_restores_exact_replay(engine):
    from robot_learning_workbench.engines.mujoco.state import snapshot,restore_episode,read_sample
    from robot_learning_workbench.engines.mujoco.control import step
    model,data,b=engine;initial=snapshot(model,data,b);before=data.qpos.copy()
    target=b.initial_joint_rad.copy();target[0]+=.1
    for _ in range(5):step(model,data,b,target)
    assert data.time==pytest.approx(5/30) and not np.array_equal(before,data.qpos)
    after=snapshot(model,data,b)
    restore_episode(model,data,b,initial)
    assert snapshot(model,data,b)['integration_state']==initial['integration_state']
    for _ in range(5):step(model,data,b,target)
    np.testing.assert_array_equal(snapshot(model,data,b)['integration_state'],after['integration_state'])
    sample=read_sample(model,data,b,phase='post_step',tick=4)
    assert sample['phase']=='post_step' and sample['tick']==4 and sample['joint_order']==tuple(b.initial_joint_rad.shape[0] and __import__('robot_learning_workbench.robot.calibration',fromlist=['JOINTS']).JOINTS)
    assert not np.shares_memory(sample['joint_positions'],data.qpos)


@pytest.mark.parametrize('field,value',[('model_sha256','0'*64),('mujoco_version','0'),('state_spec',0),('integration_state',[float('nan')])])
def test_incompatible_snapshot_rejected_without_changing_state(engine,field,value):
    from robot_learning_workbench.engines.mujoco.state import snapshot,restore_episode
    model,data,b=engine;before=snapshot(model,data,b);invalid=copy.deepcopy(before);invalid[field]=value
    with pytest.raises(ValueError):restore_episode(model,data,b,invalid)
    assert snapshot(model,data,b)==before


def test_actual_finger_and_table_contacts_and_invalid_reset_rollback(engine):
    import mujoco
    from robot_learning_workbench.engines.mujoco.state import snapshot,reset_object_poses,finger_contacts
    model,data,b=engine;before=snapshot(model,data,b)
    pose=np.eye(4);pose[:3,3]=data.geom_xpos[model.geom('gripper_contact_pad').id]
    with pytest.raises(ValueError,match='penetrat'):reset_object_poses(model,data,b,[('cube_red',pose)])
    assert snapshot(model,data,b)==before
    q,v=b.object_indices['cube_red'];data.qpos[q:q+3]=pose[:3,3];mujoco.mj_forward(model,data)
    assert finger_contacts(model,data,b,'cube_red')[0]
    assert any(c.dist<0 for c in data.contact)
    force=np.empty(6)
    for _ in range(2):mujoco.mj_step(model,data)
    for i,c in enumerate(data.contact):
        mujoco.mj_contactForce(model,data,i,force)
        assert np.isfinite(force).all()


def test_camera_pose_is_live_and_rgb_uses_real_renderer(engine):
    import mujoco
    from robot_learning_workbench.engines.mujoco.state import camera_pose
    from robot_learning_workbench.engines.mujoco.control import step
    model,data,b=engine;first=camera_pose(model,data,b,'wrist');target=b.initial_joint_rad.copy();target[0]+=.1
    for _ in range(3):step(model,data,b,target)
    assert not np.array_equal(first,camera_pose(model,data,b,'wrist'))
    with mujoco.Renderer(model,height=120,width=160) as renderer:
        renderer.update_scene(data,camera='side');image=renderer.render()
        assert image.shape==(120,160,3) and image.dtype==np.uint8 and image.std()>0


def test_canonical_b01_initial_pose_velocities_and_static_identity_restore(engine):
    import h5py
    from robot_learning_workbench.engines.mujoco.state import snapshot,restore_episode,read_sample
    def arrays(group):return {key:arrays(value) if hasattr(value,'keys') else value[()] for key,value in group.items()}
    with h5py.File(ROOT/'docs/evidence/b01/runs/source_mujoco_A/data/dataset.hdf5') as f:initial=arrays(f['data/demo_0/initial_state'])
    model,data,b=engine;restore_episode(model,data,b,initial)
    sample=read_sample(model,data,b,phase='pre_step',tick=0,object_id='cube_red')
    np.testing.assert_array_equal(sample['joint_positions'],initial['articulation']['robot']['joint_position'][0])
    np.testing.assert_allclose(sample['object_poses']['cube_red'][:3,3],initial['rigid_object']['cube_red']['root_pose'][0,:3],rtol=0,atol=1e-12)
    before=snapshot(model,data,b);invalid=copy.deepcopy(initial);invalid['rigid_object']['cup_a']['root_pose'][0,0]+=1.
    with pytest.raises(ValueError,match='static'):restore_episode(model,data,b,invalid)
    assert snapshot(model,data,b)==before


@pytest.mark.parametrize('target',[[True]*6,[0]*5,[float('nan')]*6,[complex(1,2)]*6,{'shoulder_pan':0.}])
def test_invalid_command_never_changes_controller_or_physics(engine,target):
    from robot_learning_workbench.engines.mujoco.state import snapshot
    from robot_learning_workbench.engines.mujoco.control import step
    model,data,b=engine;before=snapshot(model,data,b)
    with pytest.raises(ValueError):step(model,data,b,target)
    assert snapshot(model,data,b)==before


@pytest.mark.parametrize('changes',[{'initial_joint_rad':(True,)*6},{'decimation':True},{'physics_timestep_s':float('nan')},{'active_object_ids':('no_such_object',)},{'active_object_ids':('cube_red','cube_red')}])
def test_bad_model_config_is_rejected_before_compilation(changes):
    from dataclasses import replace
    from robot_learning_workbench.engines.mujoco.model import build_model
    with pytest.raises(ValueError):build_model(load_scene(PACKAGE/'scene.json'),replace(config_from_evidence(),**changes))


def test_moved_package_preserves_model_snapshot_and_replay(tmp_path):
    import shutil,mujoco
    from robot_learning_workbench.engines.mujoco.model import build_model
    from robot_learning_workbench.engines.mujoco.state import snapshot,restore_episode
    from robot_learning_workbench.engines.mujoco.control import step
    original=tmp_path/'original';shutil.copytree(PACKAGE,original)
    p=load_scene(original/'scene.json');cfg=config_from_evidence();model,b=build_model(p,cfg);data=mujoco.MjData(model);restore_episode(model,data,b,None)
    step(model,data,b,b.initial_joint_rad);saved=snapshot(model,data,b)
    moved=tmp_path/'moved';original.rename(moved);new_model,new_b=build_model(load_scene(moved/'scene.json'),cfg);new_data=mujoco.MjData(new_model)
    assert new_b.model_sha256==b.model_sha256
    restore_episode(new_model,new_data,new_b,saved)
    for _ in range(3):step(model,data,b,b.initial_joint_rad);step(new_model,new_data,new_b,new_b.initial_joint_rad)
    np.testing.assert_array_equal(data.qpos,new_data.qpos)
    np.testing.assert_array_equal(data.qvel,new_data.qvel)


def test_task_sample_phase_and_target_are_not_invented(engine):
    from robot_learning_workbench.engines.mujoco.state import read_sample
    m,d,b=engine
    for kwargs in ({'phase':'now','tick':0},{'phase':'post_step','tick':True},{'phase':'pre_step','tick':0,'object_id':'cube_blue'}):
        with pytest.raises(ValueError):read_sample(m,d,b,**kwargs)
    plain=read_sample(m,d,b,'pre_step',0)
    assert 'contacts' not in plain and 'grasp_inputs' not in plain


def test_explicit_source_object_selection_preserves_fixed_target_semantics():
    import mujoco
    from dataclasses import replace
    from robot_learning_workbench.engines.mujoco.model import build_model
    cfg=replace(config_from_evidence(),object_ids=('cube_red','cup_a'))
    model,b=build_model(load_scene(PACKAGE/'scene.json'),cfg)
    assert 'cup_a' in b.object_body_ids and 'cup_b' not in b.object_body_ids
    assert mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,'builder_cup_b_red_print_visual_0')==-1
    assert model.body('cup_a').jntnum==0
    with pytest.raises(ValueError):build_model(load_scene(PACKAGE/'scene.json'),replace(cfg,object_ids=('cup_a',)))


def test_canonical_restore_validates_static_pose_before_first_forward(engine):
    import h5py,mujoco
    from robot_learning_workbench.engines.mujoco.state import restore_episode
    def arrays(group):return {key:arrays(value) if hasattr(value,'keys') else value[()] for key,value in group.items()}
    with h5py.File(ROOT/'docs/evidence/b01/runs/source_mujoco_A/data/dataset.hdf5') as f:initial=arrays(f['data/demo_0/initial_state'])
    model,_,b=engine;fresh=mujoco.MjData(model)
    restore_episode(model,fresh,b,initial)
    assert np.linalg.norm(fresh.xpos[b.object_body_ids['cup_a']])>0
