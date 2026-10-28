"""E01 input binding tests run without starting Isaac; runtime evidence is separate."""
from pathlib import Path
import copy,json,sys
import pytest

ROOT=Path(__file__).resolve().parents[2]
INPUT=ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json'


def package_and_inputs():
    from scene_contract.package import load_scene
    data=json.loads(INPUT.read_text())
    return load_scene(Path(data['package_root'])/'scene.json'),data


def test_isaac_module_import_is_inert_and_fixed_execution_metadata_is_bound():
    before=set(sys.modules)
    from robot_learning_workbench.engines.isaac.env_cfg import execution_inputs
    package,inputs=package_and_inputs();bound=execution_inputs(package,inputs)
    assert bound['dt']==1/240 and bound['decimation']==8
    assert bound['joint_order']==tuple(package.scene['robot']['joint_order'])
    assert bound['robot_urdf'].is_relative_to(package.root)
    assert bound['profile']['cameras']['wrist']['parent']=='gripper'
    assert not any(n.split('.')[0] in ('isaaclab','omni','pxr') for n in set(sys.modules)-before)


@pytest.mark.parametrize('field',['profile','task','physics'])
def test_engine_metadata_cannot_escape_scene_manifest(field):
    from robot_learning_workbench.engines.isaac.env_cfg import execution_inputs
    package,inputs=package_and_inputs();bad=copy.deepcopy(inputs)
    bad['baseline_metadata'][field]['asset_path']='../../outside.json'
    with pytest.raises(ValueError):execution_inputs(package,bad)


def test_same_revision_different_bytes_and_baked_model_mismatch_are_rejected():
    from robot_learning_workbench.engines.isaac.env_cfg import execution_inputs
    package,inputs=package_and_inputs();bad=copy.deepcopy(inputs);bad['scene_identity']['manifest_sha256']='0'*64
    with pytest.raises(ValueError):execution_inputs(package,bad)
    bad=copy.deepcopy(inputs);bad['active_object_ids']=['robot_gripper_0']
    with pytest.raises(ValueError):execution_inputs(package,bad)


def test_unknown_device_or_nonpositive_physics_dt_is_not_a_fallback():
    from robot_learning_workbench.engines.isaac.env_cfg import execution_inputs
    package,inputs=package_and_inputs();bad=copy.deepcopy(inputs);bad['isaac']['physics_timestep_s']=0
    with pytest.raises(ValueError):execution_inputs(package,bad)


def test_derived_assets_exclude_reference_robot_and_unselected_dynamic_objects(tmp_path):
    from robot_learning_workbench.engines.isaac.env_cfg import execution_inputs,write_scene_assets
    package,inputs=package_and_inputs();bound=execution_inputs(package,inputs)
    files=write_scene_assets(package,bound,tmp_path/'native')
    from pxr import Usd
    stage=Usd.Stage.Open(str(files['static']))
    assert not stage.GetPrimAtPath('/Static/robot_gripper_0').IsActive()
    assert not stage.GetPrimAtPath('/Static/cube_blue').IsActive()
    assert not stage.GetPrimAtPath('/Static/cube_red').IsActive()
    assert stage.GetPrimAtPath('/Static/table').IsActive()
    dynamic=Usd.Stage.Open(str(files['objects']['cube_red']))
    assert dynamic.GetDefaultPrim().GetPath().pathString=='/Object'
    assert len(files['mounted'])>0


def test_configuration_rejects_missing_engine_context_before_importing_isaac(tmp_path):
    from robot_learning_workbench.engines.isaac.env_cfg import build_env_cfg
    package,inputs=package_and_inputs()
    with pytest.raises(ValueError):build_env_cfg(package,None,runtime_directory=tmp_path/'runtime')


def test_restore_preflight_preserves_dtype_and_rejects_partial_or_nonfinite_state():
    import numpy as np
    from robot_learning_workbench.engines.isaac.state import validate_initial
    initial={'articulation':{'robot':{'root_pose':np.array([[0,0,0,1,0,0,0]],np.float32),'root_velocity':np.zeros((1,6),np.float32),'joint_position':np.zeros((1,6),np.float32),'joint_velocity':np.zeros((1,6),np.float32)}},'rigid_object':{'cube_red':{'root_pose':np.array([[0,0,.03,1,0,0,0]],np.float64),'root_velocity':np.zeros((1,6),np.float64)}}}
    result=validate_initial(initial,1,('cube_red',))
    assert result['rigid_object']['cube_red']['root_pose'].dtype==np.float64
    assert result['articulation']['robot']['joint_position'].dtype==np.float32
    result['articulation']['robot']['joint_position'][0,0]=1
    assert initial['articulation']['robot']['joint_position'][0,0]==0
    for kind in ('missing','nan','shape'):
        bad=copy.deepcopy(initial)
        if kind=='missing':bad['rigid_object']={}
        elif kind=='nan':bad['articulation']['robot']['joint_position'][0,0]=np.nan
        else:bad['articulation']['robot']['root_velocity']=np.zeros((1,5))
        with pytest.raises(ValueError):validate_initial(bad,1,('cube_red',))


def test_model_radian_target_preserves_endpoint_without_usd_degree_roundtrip():
    import numpy as np
    from robot_learning_workbench.engines.isaac.mdp import validate_targets
    limits=np.array([[-1.7453265190124512,1.7453265190124512]]*6,np.float32)
    q=limits[:,1][None].copy()
    np.testing.assert_array_equal(validate_targets(q,limits[None]),q)
    np.testing.assert_array_equal(validate_targets(np.nextafter(q,np.float32(np.inf)),limits[None]),q)
    for bad in (q.astype(bool),np.full((1,6),np.nan)):
        with pytest.raises(ValueError):validate_targets(bad,limits[None])


def test_execution_requires_packaged_isaac_usd_without_importer_fallback():
    from robot_learning_workbench.engines.isaac.env_cfg import execution_inputs
    package,inputs=package_and_inputs()
    from dataclasses import replace
    scene=dict(package.scene);robot=dict(scene['robot']);robot.pop('bindings',None);scene['robot']=robot
    with pytest.raises(ValueError,match='execution USD'):
        execution_inputs(replace(package,scene=scene),inputs)
