"""Independent evaluation entry; real Policy inference verified in evidence child."""
from pathlib import Path
import json,yaml
import pytest
ROOT=Path(__file__).resolve().parents[2]


def test_validation_rejects_training_dataset_overlap_before_output(tmp_path):
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.learning.validate import evaluate
    source=ROOT/'docs/evidence/learning-bundle';p=tmp_path/'v.yaml'
    p.write_text(yaml.safe_dump(dict(schema_version=1,stage='offline_validation',inputs={'dataset':str(ROOT/'docs/evidence/l03-lerobot/outputs-final/train'),'policy':str(source/'runs/act-second/checkpoints/000002/pretrained_model')},execution={'batch_size':1,'max_batches':1},output={'directory':str(tmp_path/'out')})))
    with pytest.raises(ValueError):evaluate(prepare_recipe(read_recipe(p)),events=lambda row:None,commands=lambda:())
    assert not (tmp_path/'out').exists()


def test_changed_training_metadata_is_rejected_before_leakage_claim(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from test_lerobot_dataset import source
    from robot_learning_workbench.data import lerobot,native
    from robot_learning_workbench.learning import validate
    import json
    src=source(tmp_path);train=lerobot.materialize(src,tmp_path/'train',task='pick red cube');val=lerobot.materialize(src,tmp_path/'val',task='pick red cube')
    original=native.load_catalog(train);record={'dataset_path':str(train),'dataset_identity':vars(original.identity),'control_contract':lerobot.control_contract(native.load_catalog(val))}
    p=train/'workbench.json';doc=json.loads(p.read_text());doc['note']='changed after checkpoint';p.write_text(json.dumps(doc))
    monkeypatch.setattr(validate,'load_policy',lambda *args:(None,None,None,record));monkeypatch.setattr(__import__('robot_learning_workbench.recipe',fromlist=['verify_prepared_inputs']),'verify_prepared_inputs',lambda plan:None)
    plan=SimpleNamespace(resolved_inputs={'dataset':{'path':str(val)},'policy':{'path':'unused'}},output_path=tmp_path/'out')
    with pytest.raises(ValueError):validate.evaluate(plan,events=lambda row:None,commands=lambda:())
    assert not plan.output_path.exists()
