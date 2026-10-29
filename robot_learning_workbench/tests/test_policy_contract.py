"""L02 pure safety/closed checkpoint identity; no engines or physical device."""
import numpy as np
import pytest

def test_policy_output_uses_absolute_radians_and_position_saturation():
    from robot_learning_workbench.learning.policy import validate_action
    from robot_learning_workbench.robot.calibration import JOINTS
    bounds=np.tile([-1.,1.],(6,1));q=np.array([0,.1,.2,.3,.4,.5],dtype=np.float32)
    np.testing.assert_array_equal(validate_action(q,joint_order=JOINTS,units='model_rad',limits=bounds),q)
    for bad in (np.full(6,np.nan),np.full(6,np.inf),np.zeros(7)):
        with pytest.raises(ValueError):validate_action(bad,joint_order=JOINTS,units='model_rad',limits=bounds)
    with pytest.raises(ValueError):validate_action(q,joint_order=JOINTS,units='degree',limits=bounds)
    with pytest.raises(ValueError):validate_action(q,joint_order=tuple(reversed(JOINTS)),units='model_rad',limits=bounds)


def test_float32_limit_saturation_preserves_exact_input():
    from robot_learning_workbench.learning.policy import validate_action
    from robot_learning_workbench.robot.calibration import JOINTS
    upper=1.7453264625997165;q=np.zeros(6);q[3]=upper
    bounds=np.tile([-2.,2.],(6,1));bounds[3,1]=upper
    np.testing.assert_array_equal(validate_action(q,joint_order=JOINTS,units='model_rad',limits=bounds),q)
    assert validate_action(q.astype(np.float32),joint_order=JOINTS,units='model_rad',limits=bounds)[3]==1.7453263998031616


def test_inference_returns_postprocessed_saturated_position_target():
    import torch
    from robot_learning_workbench.learning.policy import infer
    from robot_learning_workbench.robot.calibration import JOINTS
    from types import SimpleNamespace
    policy=SimpleNamespace(select_action=lambda batch:torch.zeros((1,6)))
    actual=infer(policy,lambda b:b,lambda x:x+.25,{},contract={'joint_order':JOINTS},limits=np.tile([-1,1],(6,1)))
    np.testing.assert_array_equal(actual,np.full((1,6),.25))
    np.testing.assert_array_equal(infer(policy,lambda b:b,lambda x:x+2,{},contract={'joint_order':JOINTS},limits=np.tile([-1,1],(6,1))),np.ones((1,6)))


def test_checkpoint_missing_and_tampered_manifest_are_not_loaded(tmp_path):
    from robot_learning_workbench.learning.policy import checkpoint_record
    import json
    with pytest.raises(ValueError):checkpoint_record(tmp_path)
    (tmp_path/'workbench-checkpoint.json').write_text(json.dumps({'schema_version':1,'complete':True,'files':{'pretrained_model/model.safetensors':'0'*64}}))
    with pytest.raises(ValueError):checkpoint_record(tmp_path)


def test_checkpoint_seal_requires_valid_finite_safetensors(tmp_path):
    # Synthetic incomplete official-file fixture, not a trained Policy.
    from robot_learning_workbench.learning.policy import seal_checkpoint
    import json
    p=tmp_path/'pretrained_model';p.mkdir();s=tmp_path/'training_state';s.mkdir()
    for name in ('config.json','train_config.json','policy_preprocessor.json','policy_postprocessor.json'):(p/name).write_text('{}')
    for name in ('optimizer_param_groups.json',):(s/name).write_text('{}')
    (s/'training_step.json').write_text('{"step":1}')
    for path in (p/'model.safetensors',s/'optimizer_state.safetensors',s/'rng_state.safetensors'):path.write_bytes(b'broken')
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    with pytest.raises(ValueError):seal_checkpoint(tmp_path,dataset=root/'docs/evidence/l03-lerobot/outputs-final/train',config={},recipe_sha256='0'*64)
    assert not (tmp_path/'workbench-checkpoint.json').exists()


def test_external_official_act_checkpoint_does_not_require_project_manifest(tmp_path):
    from pathlib import Path
    from robot_learning_workbench.learning.policy import load_policy
    root=Path(__file__).resolve().parents[2]/'docs/evidence/learning-bundle/runs/act-second/checkpoints/000002/pretrained_model'
    for p in root.iterdir():
        if p.is_file():(tmp_path/p.name).symlink_to(p)
    policy,pre,post,record=load_policy(tmp_path)
    assert record['external_official'] is True and record['control_contract'] is None
    assert policy.config.type=='act'


def test_queue_diagnostics_do_not_report_missing_queues_as_zero():
    from collections import deque
    from types import SimpleNamespace as NS
    from robot_learning_workbench.learning.policy import action_queue_depth
    assert action_queue_depth(NS(_action_queue=deque([1])))==1
    assert action_queue_depth(NS(_queues={'action':deque([1,2])}))==2
    assert action_queue_depth(NS()) is None
