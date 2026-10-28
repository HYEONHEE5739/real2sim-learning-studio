import json
import pytest
from robot_learning_workbench.learning.validate import evaluate
from robot_learning_workbench.data.native import load_catalog
from robot_learning_workbench.data.lerobot import control_contract
from test_policy_paths import validation,official,VAL,MODEL


@pytest.mark.parametrize('declared',[False,True])
def test_external_validation_separates_numerical_metrics_from_control_approval(tmp_path,declared):
    meaning=control_contract(load_catalog(VAL)) if declared else None
    p=validation(tmp_path,official(tmp_path),meaning)
    assert evaluate(p,events=lambda _:None,commands=lambda:()).status=='completed'
    report=json.loads((p.output_path/'validation.json').read_text())
    assert report['robot_control_approved'] is False and report['lineage_status']=='unverified_external_provenance'
    assert ('mae_rad' in report)==declared
    assert report['units']==('rad' if declared else 'unspecified_dataset_units')


@pytest.mark.parametrize('bad',['unit','order','feature'])
def test_inconsistent_declared_meaning_or_feature_is_rejected(tmp_path,monkeypatch,bad):
    meaning=control_contract(load_catalog(VAL))
    if bad=='unit':meaning['action']['units']=['degree']*6
    if bad=='order':meaning['joint_order'].reverse()
    if bad=='feature':
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies import factory
        from types import SimpleNamespace
        from robot_learning_workbench.learning import validate
        cfg=PreTrainedConfig.from_pretrained(MODEL/'pretrained_model',local_files_only=True)
        cfg.input_features['observation.state'].shape=(7,)
        monkeypatch.setattr(validate,'load_policy',lambda *a:(SimpleNamespace(config=cfg),None,None,{'external_official':True,'control_contract':None,'step':None}))
    p=validation(tmp_path,official(tmp_path),meaning)
    with pytest.raises(ValueError):evaluate(p,events=lambda _:None,commands=lambda:())
    assert not p.output_path.exists()


@pytest.mark.parametrize('case',['verified','absent','degree','order','delta'])
def test_simulation_binding_stays_stricter_than_offline_comparison(tmp_path,monkeypatch,case):
    from types import SimpleNamespace as NS
    from scene_contract.package import load_scene
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies import factory
    from robot_learning_workbench.learning import policy
    from test_policy_paths import ROOT
    cfg=PreTrainedConfig.from_pretrained(MODEL/'pretrained_model',local_files_only=True)
    if case=='delta':cfg.use_delta_joint_actions_aloha=True
    monkeypatch.setattr(policy,'load_policy',lambda *a,**kw:(NS(config=cfg),None,None,{'external_official':True,'control_contract':None}))
    meaning=control_contract(load_catalog(VAL));model=meaning['robot_model_sha256']
    scene=load_scene(ROOT/'docs/evidence/e01-v8-collision/runspace/relocated/scene-v8-native/scene.json')
    if case=='degree':meaning['action']['units']=['degree']*6
    if case=='order':meaning['joint_order'].reverse()
    p=NS(resolved_inputs={'policy':{'path':'controlled official fixture'}},input_documents={} if case=='absent' else {'policy_contract':meaning},scene=scene,scene_identity=meaning['scene_identity'],effective_settings={'execution':{}})
    if case=='verified':assert policy.policy_inputs(p,model)[-1]==meaning
    else:
        with pytest.raises(ValueError):policy.policy_inputs(p,model)
