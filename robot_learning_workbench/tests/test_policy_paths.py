"""Policy input paths, ownership and UI labels; preserved checkpoints are read-only."""
import json,os,subprocess,shutil
from pathlib import Path
import pytest,yaml
from robot_learning_workbench.recipe import read_recipe,prepare_recipe,verify_prepared_inputs
ROOT=Path(__file__).resolve().parents[2]
MODEL=ROOT/'docs/evidence/architecture-completion/final-workspace/policy/act-resume/checkpoints/000004'
VAL=ROOT/'docs/evidence/architecture-completion/final-workspace/dataset/val'


def validation(tmp_path,policy,meaning=None):
    inputs={'policy':str(policy),'dataset':str(VAL)}
    if meaning is not None:
        p=tmp_path/'meaning.json';p.write_text(json.dumps(meaning));inputs['policy_contract']=str(p)
    path=tmp_path/'recipe.yaml';path.write_text(yaml.safe_dump(dict(schema_version=1,stage='offline_validation',inputs=inputs,execution={'max_batches':1},output={'directory':str(tmp_path/'out')})))
    return prepare_recipe(read_recipe(path))


def official(tmp_path):
    p=tmp_path/'external';p.mkdir()
    for source in (MODEL/'pretrained_model').iterdir():
        if source.is_file():(p/source.name).symlink_to(source)
    return p


@pytest.mark.parametrize('kind',['root','leaf','official'])
def test_policy_paths_preserve_owner_and_official_structure(tmp_path,kind):
    policy=official(tmp_path) if kind=='official' else MODEL/ 'pretrained_model' if kind=='leaf' else MODEL
    plan=validation(tmp_path,policy)
    assert plan.input_documents['policy_config']['type']=='act'
    if kind!='official':
        assert Path(plan.resolved_inputs['policy']['path'])==MODEL
        assert 'workbench-checkpoint.json' in plan.resolved_inputs['policy']['files']
    verify_prepared_inputs(plan)


def test_qt_label_accepts_root_and_leaf_without_backend_imports(tmp_path):
    from test_workbench_window import UI
    code='''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);p=WorkflowPage('offline_validation',sys.executable,'modules');p.editor.path=Path(sys.argv[1])/'r.yaml'
for path in (Path(sys.argv[2]),Path(sys.argv[2])/'pretrained_model'):
 p.show_policy_model(str(path));assert 'act' in p.policy_model.text(),p.policy_model.text()
assert not any(n in sys.modules for n in ('torch','lerobot','mujoco','isaaclab'))
p.timer.stop();p.close()
'''
    result=subprocess.run([UI,'-B','-c',code,str(tmp_path),str(MODEL)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('leaf',[False,True])
def test_finetune_cannot_bypass_owned_processor_integrity(tmp_path,leaf):
    from robot_learning_workbench.learning.train import training_command
    root=tmp_path/'owned';shutil.copytree(MODEL,root,copy_function=os.link)
    (root/'pretrained_model/policy_preprocessor.json').unlink()
    config=json.loads((root/'workbench-checkpoint.json').read_text())['config']
    config.update(resume=False,output_dir=str(tmp_path/'out'),steps=1);config['policy']['pretrained_path']=str(root/'pretrained_model')
    cfg=tmp_path/'train.json';cfg.write_text(json.dumps(config))
    p=tmp_path/'fine.yaml';p.write_text(yaml.safe_dump(dict(schema_version=1,stage='train',inputs={'policy':str(root/'pretrained_model' if leaf else root),'dataset':config['dataset']['root'],'training_config':str(cfg)},execution={'mode':'finetune'},output={'directory':str(tmp_path/'out')})))
    with pytest.raises(ValueError)as error:training_command(prepare_recipe(read_recipe(p)))
    assert error.value.code=='CHECKPOINT_INTEGRITY_MISMATCH'


def test_invalid_path_and_missing_official_processor_are_clear(tmp_path):
    from robot_learning_workbench.recipe import policy_model_path
    from robot_learning_workbench.learning.policy import load_policy
    with pytest.raises(ValueError,match='pretrained_model'):policy_model_path(tmp_path/'not-a-model')
    path=official(tmp_path);(path/'policy_postprocessor.json').unlink()
    with pytest.raises(ValueError)as error:load_policy(path)
    assert error.value.code=='CHECKPOINT_INCOMPLETE'


@pytest.mark.parametrize('leaf',[False,True])
def test_owned_metadata_and_processor_tampering_are_pinned(tmp_path,leaf):
    from robot_learning_workbench.learning.policy import load_policy
    root=tmp_path/'owned';shutil.copytree(MODEL,root,copy_function=os.link)
    policy=root/'pretrained_model'if leaf else root;plan=validation(tmp_path,policy)
    processor=root/'pretrained_model/policy_preprocessor.json';processor.unlink();processor.write_text('{}')
    with pytest.raises(ValueError):verify_prepared_inputs(plan)
    with pytest.raises(ValueError)as error:load_policy(policy)
    assert error.value.code=='CHECKPOINT_INTEGRITY_MISMATCH'


def test_external_model_inside_checkpoint_does_not_select_parent_policy(tmp_path):
    from robot_learning_workbench.learning.policy import load_policy
    root=tmp_path/'owned';shutil.copytree(MODEL,root,copy_function=os.link)
    source=ROOT/'docs/evidence/architecture-completion/phase3-learning/diffusion-resume/checkpoints/000002/pretrained_model'
    external=root/'downloaded_diffusion';external.mkdir()
    for p in source.iterdir():
        if p.is_file():(external/p.name).symlink_to(p)
    p=validation(tmp_path,external)
    assert p.input_documents['policy_config']['type']=='diffusion'
    assert Path(p.resolved_inputs['policy']['path'])==external
    model,_,_,record=load_policy(external)
    assert model.config.type=='diffusion' and record['external_official'] is True
