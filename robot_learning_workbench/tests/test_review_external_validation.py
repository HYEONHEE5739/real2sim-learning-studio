from pathlib import Path
import json,yaml
import pytest
from robot_learning_workbench.recipe import read_recipe,prepare_recipe
from robot_learning_workbench.learning.validate import evaluate
from robot_learning_workbench.data.native import load_catalog
from robot_learning_workbench.data.lerobot import control_contract
from test_review_policy_paths import CHECKPOINT,DATASET


def external(tmp_path):
    path=tmp_path/'official-policy';path.mkdir()
    for p in (CHECKPOINT/'pretrained_model').iterdir():
        if p.is_file():(path/p.name).symlink_to(p)
    return path


def plan(tmp_path,policy,contract):
    inputs={'dataset':str(DATASET),'policy':str(policy)}
    if contract is not None:
        p=tmp_path/'meaning.json';p.write_text(json.dumps(contract));inputs['policy_contract']=str(p)
    p=tmp_path/'validation.yaml';p.write_text(yaml.safe_dump(dict(schema_version=1,stage='offline_validation',inputs=inputs,execution={'max_batches':1},output={'directory':str(tmp_path/'out')})))
    return prepare_recipe(read_recipe(p))


def test_external_official_policy_validates_with_explicit_matching_meaning(tmp_path):
    meaning=control_contract(load_catalog(DATASET));p=plan(tmp_path,external(tmp_path),meaning)
    assert evaluate(p,events=lambda _:None,commands=lambda:()).status=='completed'
    result=json.loads((p.output_path/'validation.json').read_text())
    assert result['batches']==1 and result['units']=='rad'
    assert result['robot_control_approved'] is False
    assert result['contract_source']=='explicit_policy_contract'
    assert result['lineage_status']=='unverified_external_provenance'


def test_missing_external_robot_meaning_never_becomes_control_approval(tmp_path):
    p=plan(tmp_path,external(tmp_path),None)
    with pytest.raises(ValueError):evaluate(p,events=lambda _:None,commands=lambda:())
    assert not p.output_path.exists()


def test_external_inconsistent_action_units_rejected_before_output(tmp_path):
    meaning=control_contract(load_catalog(DATASET));meaning['action']['units']=['degree']*6
    p=plan(tmp_path,external(tmp_path),meaning)
    with pytest.raises(ValueError):evaluate(p,events=lambda _:None,commands=lambda:())
    assert not p.output_path.exists()


def test_external_validation_checks_official_dataset_features(tmp_path,monkeypatch):
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies import factory
    from robot_learning_workbench.learning import validate
    cfg=PreTrainedConfig.from_pretrained(CHECKPOINT/'pretrained_model',local_files_only=True)
    cfg.input_features['observation.images.side'].shape=(3,64,64)
    from types import SimpleNamespace
    monkeypatch.setattr(validate,'load_policy',lambda *a:(SimpleNamespace(config=cfg),None,None,{'control_contract':None,'step':None}))
    p=plan(tmp_path,external(tmp_path),control_contract(load_catalog(DATASET)))
    with pytest.raises(ValueError,match='features'):evaluate(p,events=lambda _:None,commands=lambda:())
    assert not p.output_path.exists()
