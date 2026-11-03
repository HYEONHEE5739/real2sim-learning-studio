"""Pipeline scripts are the single editable execution configuration."""
import os,subprocess
from pathlib import Path
import pytest,yaml
from test_workbench_window import UI


def qt(code,tmp_path):
    result=subprocess.run([UI,'-B','-c',code,str(tmp_path)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=40)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('stage',['annotation','datagen','train','simulation_evaluation','offline_validation','hub_download','hub_upload','real_evaluation'])
def test_default_scripts_follow_existing_recipe_schema(tmp_path,stage):
    from robot_learning_workbench.ui.pipeline_scripts import default_script
    from robot_learning_workbench.recipe import read_recipe
    text=default_script(stage,tmp_path,'mujoco');data=yaml.safe_load(text)
    for key,value in data['inputs'].items():
        if not value:data['inputs'][key]='owner/repo'if key=='repo_id'else'/explicit/'+key
    if stage=='hub_upload':data['execution']['parent_commit']='0'*40
    if stage in('simulation_evaluation','real_evaluation'):data['execution']['task_instruction']='Put the selected block in the cup.'
    path=tmp_path/(stage+'.yaml');path.write_text(yaml.safe_dump(data))
    assert read_recipe(path).spec.stage==stage
    assert data['output']['directory'].startswith(str(tmp_path))
    if stage=='real_evaluation':assert data['execution']['mode']=='observe_only'and data['execution']['enable_motion']is False


def test_every_page_uses_visible_yaml_and_keeps_drafts_when_switching(tmp_path):
    qt('''
import sys,yaml
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QPushButton
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([])
for stage in ('annotation','datagen','train','simulation_evaluation','offline_validation','hub_download','hub_upload','real_evaluation'):
 p=WorkflowPage(stage,'/no/worker','modules');p.resize(1320,900);p.show();app.processEvents()
 assert p.editor.isVisible()and yaml.safe_load(p.editor.text.toPlainText())['stage']==stage
 assert not any(hasattr(p,name)for name in ('counts','placement','object_table','dataset_resume','training_settings','hub_settings','mode','output'))
 assert p.settings.load_button.text()=='Recipe 불러오기'and p.settings.save_button.text()=='저장 및 적용'
 p.editor.text.appendPlainText('# keep my draft');text=p.editor.text.toPlainText()
 p.hide();p.show();assert p.editor.text.toPlainText()==text
 assert not p.start_button.isEnabled()
 p.timer.stop();p.close()
assert not any(name in sys.modules for name in ('torch','mujoco','isaaclab','lerobot','serial'))
''',tmp_path)


def test_load_apply_and_prepare_identity_do_not_start_or_overwrite_input(tmp_path):
    qt('''
import sys,hashlib,yaml
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QFileDialog
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);r=root/'r.yaml'
r.write_text('schema_version: 1\\nstage: annotation\\nengine: mujoco\\ninputs: {dataset: ./source, scene: ./scene/scene.json}\\nexecution: {mode: auto}\\noutput: {directory: ./annotation}\\nfunctions: {acceptance: {function: pick_place.annotation, params: {object: red, target: cup}}}\\n')
original=r.read_bytes();p=WorkflowPage('annotation','/no/worker','modules');requests=[]
p.job.start=lambda operation,**kw:requests.append((operation,kw))
p.settings.load_script(r)
assert r.read_bytes()==original and p.busy and requests[-1][0]=='prepare'
sha=hashlib.sha256(original).hexdigest()
p.job_finished({'ok':True,'result':{'runnable':True,'state':'runtime_ready','reason':'ready','recipe_sha256':sha,'prepared_sha256':'plan'}})
assert p.start_button.isEnabled()and all(op=='prepare'for op,_ in requests)
p.editor.text.appendPlainText('# edit');assert p.ready is None and not p.start_button.isEnabled()
target=root/'scripts'/'annotation'/'new.yaml';QFileDialog.getSaveFileName=lambda *a,**k:(str(target),'')
p.settings.save_and_apply();saved=yaml.safe_load(target.read_text())
assert Path(saved['inputs']['dataset'])==root/'source'and Path(saved['output']['directory'])==root/'annotation'
assert r.read_bytes()==original and not p.editor.dirty and p.busy
p.cancel_run();p.job_finished({'ok':True,'result':{'runnable':True,'state':'runtime_ready','reason':'late','recipe_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'prepared_sha256':'late'}})
assert p.ready is None and not p.busy and all(op=='prepare'for op,_ in requests)
p.timer.stop();p.close()
''',tmp_path)


def test_recorded_dataset_uses_exact_scene_not_latest(tmp_path,monkeypatch):
    from robot_learning_workbench.ui import pipeline_inputs
    from robot_learning_workbench.data.native import NativeRun
    from test_native_dataset import execution
    config=execution('source');config.update(scene_identity={'scene_id':'scene','revision':'old','manifest_sha256':'a'*64},engine='mujoco')
    with NativeRun(tmp_path/'data',config)as run:pass
    old=dict(scene_id='scene',revision='old',manifest_sha256='a'*64,scene='/old/scene.json',engine_config={'mujoco':'/old/model.json'})
    latest={**old,'revision':'new','scene':'/new/scene.json'}
    monkeypatch.setattr(pipeline_inputs,'scenes',lambda workspace:{'scenes':[old,latest]})
    result=pipeline_inputs.dataset_inputs(tmp_path,run.root,'annotation')
    assert result['inputs']=={'dataset':str(run.root),'scene':'/old/scene.json'}
    assert pipeline_inputs.dataset_inputs(tmp_path,run.root,'datagen')['inputs']['engine_config']=='/old/model.json'
    monkeypatch.setattr(pipeline_inputs,'scenes',lambda workspace:{'scenes':[latest]})
    with pytest.raises(ValueError,match='정확히 일치'):pipeline_inputs.dataset_inputs(tmp_path,run.root,'annotation')


def test_hub_actions_discard_stale_resolve_and_upload_requires_click_confirmation(tmp_path):
    qt('''
import sys,hashlib,yaml
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QMessageBox
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('hub_upload','/no/worker','modules')
requests=[];p.job.start=lambda op,**kw:requests.append((op,kw))
data=p.editor.data();data['inputs'].update(artifact=str(root/'dataset'),repo_id='owner/repo');data['execution'].update(parent_commit='a'*40,confirm_upload=True)
r=root/'upload.yaml';r.write_text(yaml.safe_dump(data));p.settings.load_script(r)
sha=hashlib.sha256(r.read_bytes()).hexdigest()
p.job_finished({'ok':True,'result':{'runnable':True,'state':'runtime_ready','reason':'ready','recipe_sha256':sha,'prepared_sha256':'plan'}})
p.hub_actions.operation='resolve';p.hub_actions.version=p.settings.version
p.editor.text.appendPlainText('# edit');before=p.editor.text.toPlainText()
p.hub_actions.received({'ok':True,'result':{'commit':'b'*40,'private':False}})
assert p.editor.text.toPlainText()==before
p.settings.load_script(r);p.job_finished({'ok':True,'result':{'runnable':True,'state':'runtime_ready','reason':'ready','recipe_sha256':sha,'prepared_sha256':'plan'}})
QMessageBox.question=lambda *a,**kw:QMessageBox.StandardButton.No
p.start_run();assert all(op=='prepare'for op,_ in requests)
QMessageBox.question=lambda *a,**kw:QMessageBox.StandardButton.Yes
p.start_run();assert requests[-1][0]=='start'and requests[-1][1]['expected_prepared_sha256']=='plan'
p.busy=False;p.timer.stop();p.close()
''',tmp_path)


def test_training_json_save_preserves_official_fields_and_source_config(tmp_path):
    qt('''
import sys,json
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QFileDialog
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench.ui.training_json import TrainingJsonDialog
from robot_learning_workbench.ui.jobs import BackendJob
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('train','/no/worker','modules')
BackendJob.start=lambda *args,**kwargs:None
p.settings.set_inputs({'dataset':str(root/'dataset')})
old=root/'original.json';cfg={'policy':{'type':'act','device':'cpu','chunk_size':20},'steps':123,'custom_official_field':{'preserve':True}}
old.write_text(json.dumps(cfg));dialog=TrainingJsonDialog(p);dialog.load(old)
new=root/'saved.json';QFileDialog.getSaveFileName=lambda *args,**kw:(str(new),'')
dialog.save();saved=json.loads(new.read_text())
assert all(saved[k]==v for k,v in cfg.items())and json.loads(old.read_text())==cfg
assert saved['dataset']['root']==str(root/'dataset')and saved['output_dir']==p.editor.data()['output']['directory']and saved['resume']is False
assert p.editor.data()['inputs']['training_config']==str(new)and p.editor.dirty
dialog.reject();p.timer.stop();p.close()
''',tmp_path)


def test_bad_script_selection_cannot_run_the_previous_script(tmp_path):
    qt('''
import sys,yaml
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('offline_validation','/no/worker','modules')
p.job.start=lambda *args,**kw:None
r=root/'good.yaml';r.write_text(yaml.safe_dump(p.editor.data()));p.settings.load_script(r)
p.job_finished({'ok':False,'error':{'message':'missing dataset'}})
wrong=root/'wrong.yaml';wrong.write_text('stage: train\\n')
try:p.settings.load_script(wrong)
except ValueError:pass
else:raise AssertionError('wrong stage accepted')
assert p.ready is None and not p.start_button.isEnabled()
p.editor.text.setPlainText('inputs: [broken');assert p.editor.dirty and not p.start_button.isEnabled()
p.timer.stop();p.close()
''',tmp_path)
