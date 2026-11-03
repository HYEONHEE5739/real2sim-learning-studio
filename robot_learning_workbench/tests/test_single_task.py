"""Source-owned language instruction survives selection and official conversion."""
from dataclasses import asdict
from types import SimpleNamespace
import os,subprocess,sys
import pytest
from test_native_dataset import episode,execution
from test_recipe_preparation import scene,source_doc,registry,annotation_doc
from test_workbench_window import UI
from robot_learning_workbench import recipe
from robot_learning_workbench.data import native,curation,lerobot


TASK='Pick the red cube and place it in cup 1.'


def labelled_source(root,task=TASK):
    from robot_learning_workbench.robot.calibration import JOINTS
    settings=execution('source');settings.update(single_task=task,calibration={'records':{}},urdf_sha256='d'*64)
    settings['recording'].update(joint_order=list(JOINTS),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',task_phase='post_step',fps=30)
    with native.NativeRun(root,settings)as run:
        segment=run.segment('one');segment.write_episode(episode(4),episode_id='demo');segment.commit()
    return native.load_catalog(root)


def test_source_yaml_accepts_task_and_execution_contract_records_it(tmp_path,scene):
    doc=source_doc(tmp_path,execution={'num_episodes': 1, 'single_task': TASK})
    plan=recipe.prepare_recipe(doc,scene=scene,tasks=registry())
    from robot_learning_workbench.engines.mujoco.source import execution_contract
    from robot_learning_workbench.engines.mujoco.model import ModelConfig
    binding=SimpleNamespace(model_sha256='a'*64,urdf_sha256='d'*64,dynamic_objects=('cube_red',))
    result=execution_contract(plan,binding,ModelConfig((0,)*6,('cube_red',),{}))
    assert result['single_task']==TASK and 'seed'not in result
    for value in ('', '   ',123):
        with pytest.raises(recipe.RecipeError):source_doc(tmp_path,execution={'num_episodes': 1, 'single_task': value})


@pytest.mark.parametrize('stage',['annotation','datagen'])
def test_preparation_inherits_source_task_without_another_recipe_field(tmp_path,scene,stage):
    with native.NativeRun(tmp_path/'data',{'stage':'source'if stage=='annotation'else'annotation','scene_identity':asdict(scene.identity),'active_objects':['cube_red'],'single_task':TASK}):pass
    doc=annotation_doc(tmp_path)if stage=='annotation'else source_doc(tmp_path,stage=stage,inputs={'scene':'scene/scene.json','dataset':'data'},functions={'acceptance':{'function':'pick_place.v8_datagen','params':{'object':'cube_red','target':'cup'}}},execution={'seed':42,'num_episodes':20,'max_attempts':40})
    plan=recipe.prepare_recipe(doc,scene=scene,tasks=registry())
    assert plan.effective_settings['execution']['single_task']==TASK
    assert 'single_task'not in doc.spec.execution


def test_revision_export_and_merge_preserve_each_recorded_task(tmp_path):
    left=labelled_source(tmp_path/'left');right=labelled_source(tmp_path/'right',TASK.replace('cup 1','cup 2'))
    before={ep.file:native.file_sha256(ep.file)for cat in(left,right)for ep in cat.episodes}
    view=curation.save_curation(tmp_path/'view.json',left,frame_ranges={'demo':(1,4)})
    output=lerobot.materialize(view,tmp_path/'official')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    ds=LeRobotDataset('workbench/native',root=output,video_backend='pyav')
    assert ds[0]['task']==TASK and len(ds)==3
    merged=lerobot.merge([view,right],tmp_path/'merged')
    again=lerobot.materialize(merged,tmp_path/'again')
    final=LeRobotDataset('workbench/native',root=again,video_backend='pyav')
    assert [final[i]['task']for i in(0,3)]==[TASK,TASK.replace('cup 1','cup 2')]
    with pytest.raises(native.DataError):lerobot.materialize(left,tmp_path/'wrong',task='Different task')
    assert before=={ep.file:native.file_sha256(ep.file)for cat in(left,right)for ep in cat.episodes}


def test_curation_shows_recorded_task_and_exports_without_text_entry(tmp_path):
    labelled_source(tmp_path/'source');(tmp_path/'exports').mkdir()
    code='''
import sys,time,yaml
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QFileDialog,QComboBox
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.curation import CurationPage
from robot_learning_workbench.ui.source_settings import SourceSettings
app=QApplication([]);root=Path(sys.argv[2]);p=CurationPage(sys.argv[1],root);p.show();p.load_source(root/'source')
def wait(test):
 end=time.monotonic()+25
 while not test()and time.monotonic()<end:app.processEvents();QTest.qWait(10)
 assert test(),p.state.text()
wait(lambda:bool(p.rows)and not p.busy)
assert not hasattr(p,'task'), 'Curation still owns an editable task field'
assert 'cup 1'in p.task_label.text()
QFileDialog.getExistingDirectory=lambda *a,**kw:str(root/'exports')
p.export();wait(lambda:not p.busy)
assert list((root/'exports').glob('lerobot-*/meta/tasks.parquet')),p.state.text()
engine=QComboBox();engine.addItem('mujoco');settings=SourceSettings(sys.argv[1],root,engine)
defaults=yaml.safe_load(settings.default_script())['execution']
assert 'single_task'in defaults and 'seed'not in defaults
wait(lambda:settings.catalog.process.state().value==0)
p.close();settings.close();app.processEvents()
'''
    result=subprocess.run([UI,'-B','-c',code,sys.executable,str(tmp_path)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
