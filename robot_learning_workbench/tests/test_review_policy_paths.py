"""Public policy input paths, with the actual immutable closed checkpoint."""
from pathlib import Path
import os,subprocess,json,yaml
import pytest
from robot_learning_workbench.recipe import read_recipe,prepare_recipe,verify_prepared_inputs
ROOT=Path(__file__).resolve().parents[2]
CHECKPOINT=ROOT/'docs/evidence/architecture-completion/final-workspace/policy/act-resume/checkpoints/000004'
DATASET=ROOT/'docs/evidence/architecture-completion/final-workspace/dataset/val'


@pytest.mark.parametrize('leaf',[False,True])
def test_recipe_supports_both_policy_paths_and_pins_owned_record(tmp_path,leaf):
    path=CHECKPOINT/'pretrained_model'if leaf else CHECKPOINT
    p=tmp_path/'r.yaml';p.write_text(yaml.safe_dump(dict(schema_version=1,stage='offline_validation',inputs={'dataset':str(DATASET),'policy':str(path)},execution={'max_batches':1},output={'directory':str(tmp_path/'out')})))
    plan=prepare_recipe(read_recipe(p));assert plan.input_documents['policy_config']['type']=='act'
    assert Path(plan.resolved_inputs['policy']['path'])==CHECKPOINT
    assert 'workbench-checkpoint.json'in plan.resolved_inputs['policy']['files']
    verify_prepared_inputs(plan)


def test_qt_policy_label_resolves_checkpoint_root_without_heavy_imports(tmp_path):
    code='''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);page=WorkflowPage('offline_validation',sys.executable,'modules');page.editor.path=Path(sys.argv[1])/'r.yaml'
for path in (Path(sys.argv[2]),Path(sys.argv[2])/'pretrained_model'):
 page.show_policy_model(str(path));assert 'act' in page.policy_model.text(),page.policy_model.text()
assert not any(n in sys.modules for n in ('torch','lerobot','isaaclab','mujoco'))
page.timer.stop();page.close()
'''
    from test_workbench_window import UI
    result=subprocess.run([UI,'-B','-c',code,str(tmp_path),str(CHECKPOINT)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_leaf_path_does_not_bypass_owned_metadata_or_processor_changes(tmp_path):
    import shutil
    from robot_learning_workbench.learning.policy import load_policy
    root=tmp_path/'owned';shutil.copytree(CHECKPOINT,root,copy_function=os.link)
    # Break hardlinks before changing controlled copies of preserved inputs.
    manifest=root/'workbench-checkpoint.json';raw=manifest.read_bytes();manifest.unlink();manifest.write_bytes(raw)
    p=tmp_path/'r.yaml';p.write_text(yaml.safe_dump(dict(schema_version=1,stage='offline_validation',inputs={'dataset':str(DATASET),'policy':str(root/'pretrained_model')},execution={},output={'directory':str(tmp_path/'out')})))
    plan=prepare_recipe(read_recipe(p));doc=json.loads(raw);doc['note']='changed after prepare';manifest.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='changed'):verify_prepared_inputs(plan)
    processor=root/'pretrained_model/policy_preprocessor.json';processor.unlink();processor.write_text('{}')
    for path in (root,root/'pretrained_model'):
        with pytest.raises(ValueError,match='changed/missing'):load_policy(path)
