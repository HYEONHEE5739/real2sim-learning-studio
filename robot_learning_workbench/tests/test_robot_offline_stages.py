from pathlib import Path
from types import SimpleNamespace
import json,yaml
import pytest
from test_precision_calibration import bound
from robot_learning_workbench.recipe import read_recipe,prepare_recipe


def plan(tmp_path,stage,*,mode='offline'):
    profile,_=bound('follower');p=tmp_path/'precision.json';p.write_text(json.dumps(profile))
    device=tmp_path/'device.json';device.write_text(json.dumps({'role':'follower','sdk':{'port':profile['identity']['port'],'id':profile['identity']['id'],'use_degrees':True}}))
    recipe=tmp_path/'recipe.yaml';recipe.write_text(yaml.safe_dump(dict(schema_version=1,stage=stage,inputs={'device_profile':str(device),'calibration_profile':str(p)},execution={'mode':mode},output={'directory':str(tmp_path/'out')})))
    return prepare_recipe(read_recipe(recipe))


def test_precision_offline_runner_rechecks_existing_evidence_not_devices(tmp_path):
    from robot_learning_workbench.robot.offline import run
    p=plan(tmp_path,'precision_calibration');result=run(p,events=lambda _:None,commands=lambda:())
    record=json.loads((p.output_path/'offline-inspection.json').read_text())
    assert result.status=='completed' and record['hardware_connected'] is False
    assert record['physical_verified'] is False and record['joint_reviews']
    assert record['sdk_config_class'].endswith('SO101FollowerConfig')


def test_offline_runner_does_not_activate_live_motion_or_publish_on_cancel(tmp_path):
    from robot_learning_workbench.robot.offline import run
    p=plan(tmp_path,'precision_calibration');events=[]
    result=run(p,events=events.append,commands=lambda:({'kind':'cancel','command_id':'cancel'},))
    assert result.status=='cancelled' and not p.output_path.exists()
    p=SimpleNamespace(effective_settings={'execution':{'mode':'live'}})
    with pytest.raises(ValueError,match='offline inspection'):run(p,events=lambda _:None,commands=lambda:())


def test_actual_policy_to_fake_follower_encoding_uses_safe_mapping(tmp_path):
    import numpy as np
    from test_robot_lifecycle import make
    from robot_learning_workbench.learning.policy import load_policy,predict
    from robot_learning_workbench.robot.control import checked_target
    from robot_learning_workbench.robot.calibration import JOINTS
    import torch
    root=Path(__file__).resolve().parents[2]
    model=root/'docs/evidence/workbench-expansion/integrated-learning/act-resume/checkpoints/000004/pretrained_model'
    policy,pre,post,record=load_policy(model)
    follower,sdk,trace=make(tmp_path);follower.connect()
    try:
        native,_=follower.read();mapper=follower.precision_mapper
        q=mapper.calibrated_to_urdf(native)
        batch={'observation.state':torch.tensor([[q[n]for n in JOINTS]],dtype=torch.float32),**{'observation.images.'+n:torch.zeros(1,3,480,640)for n in ('side','wrist')}}
        requested=predict(policy,pre,post,batch)[0]
        limits=mapper.command_limits({n:e['limits']for n,e in mapper.profile['joints'].items()})
        applied=checked_target(requested,limits=[limits[n]for n in JOINTS],applied_dtype=np.float64)
        encoded,quantized=follower.encode_goal(mapper.urdf_to_calibrated(dict(zip(JOINTS,applied))))
        assert set(encoded)==set(JOINTS)
        follower.activate();follower.send(encoded)
        policy.reset()
    finally:follower.close()
    assert trace.count('send')==1 and not sdk.bus.is_connected


def test_capture_coordinates_require_explicit_model_mapping_and_radians():
    from robot_learning_workbench.robot.offline import capture_binding
    from robot_learning_workbench.robot.calibration import JOINTS
    assert capture_binding({'joint_names':list(JOINTS),'joint_units':['m']*6},None,None)
    assert capture_binding({'joint_names':list(JOINTS),'joint_units':['rad']*6},None,None)


def test_device_profile_identity_mismatch_is_not_approved(tmp_path):
    from robot_learning_workbench.robot.offline import run
    p=plan(tmp_path,'precision_calibration');device=tmp_path/'device.json';data=json.loads(device.read_text());data['sdk']['id']='different';device.write_text(json.dumps(data))
    # Re-prepare actual altered input, rather than merely testing input SHA race.
    p=prepare_recipe(read_recipe(tmp_path/'recipe.yaml'))
    with pytest.raises(ValueError,match='identity'):run(p,events=lambda _:None,commands=lambda:())
    assert not p.output_path.exists()
