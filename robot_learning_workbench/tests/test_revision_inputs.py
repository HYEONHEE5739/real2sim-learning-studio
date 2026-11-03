"""Selected Dataset inputs cross UI/Recipe boundaries without running an engine."""
from dataclasses import asdict
from pathlib import Path
import os,subprocess,sys
import pytest
from test_native_dataset import episode,execution
from test_recipe_preparation import scene,source_doc,registry,annotation_doc
from test_curation_revisions import dataset
from test_workbench_window import UI
from robot_learning_workbench import recipe
from robot_learning_workbench.data import native
from robot_learning_workbench.data.revisions import save_revision


@pytest.mark.parametrize('stage',['annotation','datagen'])
@pytest.mark.parametrize('role',['all','train','val'])
def test_prepared_pipeline_consumes_only_selected_whole_episodes(tmp_path,scene,stage,role):
    kind='source'if stage=='annotation'else'annotation';workspace=tmp_path/'space'
    settings=execution(kind);settings.update(scene_identity=asdict(scene.identity),single_task='Put red cube in cup 1.')
    with native.NativeRun(workspace/kind/'demo',settings)as owner:
        segment=owner.segment('one')
        for i in range(3):segment.write_episode(episode(6),episode_id=f'e{i}')
        segment.commit()
    if role=='all':selected=save_revision(workspace,owner.root,'selected',exclude=['e1'])['all']
    else:selected=save_revision(workspace,owner.root,'selected',splits={'train':['e0','e1'],'val':['e2']})[role]
    import yaml
    if stage=='annotation':
        original_doc=annotation_doc(tmp_path);data=yaml.safe_load(original_doc.path.read_text());data['inputs']['dataset']=str(selected.root)
        original_doc.path.write_text(yaml.safe_dump(data));doc=recipe.read_recipe(original_doc.path)
    else:
        doc=source_doc(tmp_path,stage=stage,inputs={'scene':'scene/scene.json','dataset':str(selected.root)},
            functions={'acceptance':{'function':'pick_place.v8_datagen','params':{'object':'cube_red','target':'cup'}}},
            execution={'seed':42,'num_episodes':20,'max_attempts':40})
    plan=recipe.prepare_recipe(doc,scene=scene,tasks=registry())
    path=plan.resolved_inputs['dataset']['path']
    assert path==str(selected.root)
    assert [e.episode_id for e in native.load_catalog(path).episodes]==({'all':['e0','e2'],'train':['e0','e1'],'val':['e2']}[role])
    assert plan.effective_settings['execution']['single_task']=='Put red cube in cup 1.'
    recipe.verify_prepared_inputs(plan)
    trimmed=save_revision(workspace,selected.root,'trim',frame_ranges={selected.episodes[0].episode_id:(1,6)})[role]
    import yaml
    data=yaml.safe_load(doc.path.read_text());data['inputs']['dataset']=str(trimmed.root);doc.path.write_text(yaml.safe_dump(data))
    with pytest.raises(recipe.RecipeError)as error:recipe.prepare_recipe(recipe.read_recipe(doc.path),scene=scene,tasks=registry())
    assert error.value.code=='REPLAY_INITIAL_UNAVAILABLE'


def test_pipeline_dataset_dialog_selects_original_or_revision_and_updates_recipe(tmp_path):
    workspace=tmp_path/'space'
    for kind in('source','annotation'):
        original=dataset(workspace/kind/'demo',kind)
        save_revision(workspace,original.root,'selected',splits={'train':['e0','e1'],'val':['e2']})
    code='''
import sys,time,yaml
from pathlib import Path
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QWidget
from robot_learning_workbench.ui.dataset_input import DatasetInputDialog
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[2])
def wait(condition):
 end=time.monotonic()+30
 while not condition()and time.monotonic()<end:app.processEvents();QTest.qWait(10)
 assert condition()
for stage,kind in(('annotation','source'),('datagen','annotation')):
 parent=QWidget();parent.workspace=root
 page=WorkflowPage(stage,sys.argv[1],root/'modules.yaml',parent)
 script=root/(stage+'.yaml')
 script.write_text(yaml.safe_dump(dict(schema_version=1,stage=stage,engine='mujoco',inputs=dict(dataset=str(root/kind/'demo')),execution={},output=dict(directory=str(root/stage/'output')))))
 page.job.start=lambda *a,**k:None;page.settings.load_script(script);page.busy=False;page.buttons()
 revision=str(root/'curation'/kind/'demo/selected_r001/val.json')
 def choose():
  dialog=app.activeModalWidget()
  if not isinstance(dialog,DatasetInputDialog)or dialog.open_button.isEnabled()is False or dialog.revisions.choices.findData(revision)<0:
   QTimer.singleShot(20,choose);return
  assert dialog.datasets.kind.currentData()==kind
  assert dialog.path==str(root/kind/'demo')
  dialog.revisions.choices.setCurrentIndex(dialog.revisions.choices.findData(revision))
  assert dialog.path==revision
  dialog.open_button.click()
 QTimer.singleShot(20,choose);page.settings.choose_input('dataset')
 assert page.settings.selectors['dataset'].toolTip()==revision
 assert page.editor.data()['inputs']['dataset']==revision
 wait(lambda:page.settings.query.process.state().value==0);page.close();parent.close()
dialog=DatasetInputDialog(sys.argv[1],root,'annotation');dialog.show()
wait(lambda:bool(dialog.path)and dialog.open_button.isEnabled())
dialog.load(str(root/'missing.json'))
assert not dialog.path and not dialog.open_button.isEnabled()
wait(lambda:dialog.job.process.state().value==0)
assert not dialog.path and not dialog.open_button.isEnabled()
dialog.load(str(root/'source/demo'));dialog.clear()
wait(lambda:dialog.job.process.state().value==0)
assert not dialog.path and not dialog.open_button.isEnabled()
dialog.reject()
assert not any(name in sys.modules for name in('torch','mujoco','isaaclab','lerobot'))
'''
    result=subprocess.run([UI,'-B','-c',code,sys.executable,str(workspace)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=100)
    assert result.returncode==0,result.stdout+result.stderr


def test_curated_datagen_materializes_only_selected_episodes_and_frames(tmp_path):
    from robot_learning_workbench.data.lerobot import materialize
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    workspace=tmp_path/'space';original=dataset(workspace/'datagen/demo','datagen')
    selected=save_revision(workspace,original.root,'train',exclude=['e1'],frame_ranges={'e0':(1,4)})['all']
    output=materialize(selected,tmp_path/'official')
    final=LeRobotDataset('workbench/native',root=output,video_backend='pyav')
    assert final.num_episodes==2 and len(final)==9
    assert [e.episode_id for e in native.load_catalog(selected.root).episodes]==['e0','e2']
