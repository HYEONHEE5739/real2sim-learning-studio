"""Dataset Merge explicitly selects multiple official Datasets, independent of Curation edits."""
from pathlib import Path
import json,os,subprocess,sys
import numpy as np
import pytest
from test_workbench_window import UI
from robot_learning_workbench.data import native,lerobot
from robot_learning_workbench.ui.operations import execute


def test_ui_operation_merges_three_official_datasets_with_exact_actions_and_unchanged_inputs(tmp_path):
    from test_lerobot_dataset import source
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    originals=[source(tmp_path,'source'+str(i))for i in range(3)]
    roots=[lerobot.materialize(cat,tmp_path/f'dataset{i}',task='Pick the red cube')for i,cat in enumerate(originals)]
    before={p:native.file_sha256(p)for root in roots for p in root.rglob('*')if p.is_file()}
    result=execute({'operation':'merge','arguments':{'sources':[str(root)for root in roots],'output':str(tmp_path/'merged')}})
    ds=LeRobotDataset('workbench/native',root=result['path'],video_backend='pyav')
    assert ds.num_episodes==6 and len(ds)==18
    expected=np.concatenate([native.read_array(ep,'joint_targets')for cat in originals for ep in cat.episodes])
    np.testing.assert_array_equal(np.asarray(ds.hf_dataset.with_format(None)[:]['action']),expected)
    assert before=={p:native.file_sha256(p)for root in roots for p in root.rglob('*')if p.is_file()}
    with pytest.raises(native.DataError):
        execute({'operation':'merge','arguments':{'sources':[str(roots[0]),str(roots[0])],'output':str(tmp_path/'duplicate')}})
    assert not(tmp_path/'duplicate').exists()


def test_ui_merge_requires_official_folders_before_creating_output(tmp_path):
    from test_lerobot_dataset import source
    one=source(tmp_path,'one');two=source(tmp_path,'two')
    with pytest.raises(native.DataError,match='LeRobot'):
        execute({'operation':'merge','arguments':{'sources':[str(one.root),str(two.root)],'output':str(tmp_path/'bad')}})
    assert not(tmp_path/'bad').exists() and not(tmp_path/'bad.staging').exists()


def test_qt_multi_dataset_picker_and_merge_button_do_not_include_current_native_selection(tmp_path):
    code='''
from pathlib import Path
import sys
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication,QDialog,QFileDialog
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.curation import CurationPage
from robot_learning_workbench.ui.dataset_merge import DatasetMergeDialog
app=QApplication([]);root=Path(sys.argv[1]);rows=[]
for name in('one','two','three'):
 folder=root/name;(folder/'meta').mkdir(parents=True);(folder/'meta/info.json').write_text('{}')
 rows.append(dict(name=name,path=str(folder),category='lerobot',readable=True,episodes=2))
rows.append(dict(name='native',path=str(root/'native'),category='source',readable=True,episodes=20))
d=DatasetMergeDialog('/no/worker',root,rows);assert d.list.count()==3 and not d.merge_button.isEnabled()
d.list.item(0).setCheckState(Qt.CheckState.Checked);assert not d.merge_button.isEnabled()
d.list.item(2).setCheckState(Qt.CheckState.Checked);assert d.merge_button.isEnabled()
d.add_folder(root/'one');assert d.list.count()==3
assert d.paths==[str(root/'one'),str(root/'three')];d.close()
p=CurationPage('/no/worker',root);p.resize(1320,940);p.show();app.processEvents();p.datasets.rows=rows
assert not hasattr(p,'export_scope')
p.source=str(root/'native');p.dirty=True
calls=[];p.perform=lambda op,**args:calls.append((op,args))
def choose(dialog):
 dialog.list.item(0).setCheckState(Qt.CheckState.Checked);dialog.list.item(2).setCheckState(Qt.CheckState.Checked)
 return QDialog.DialogCode.Accepted
DatasetMergeDialog.exec=choose;QFileDialog.getExistingDirectory=lambda *args,**kw:str(root)
QTest.mouseClick(p.buttons['Dataset Merge'],Qt.MouseButton.LeftButton);app.processEvents()
assert calls[-1][0]=='merge' and calls[-1][1]['sources']==[str(root/'one'),str(root/'three')]
assert p.source not in calls[-1][1]['sources']
p.operation='merge';p.finished({'ok':True,'result':{'path':str(root/'merged')}})
assert p.source==str(root/'native') and p.dirty,'Merge discarded unsaved Curation edits'
assert str(root/'merged')in p.state.text()
p.close();app.processEvents()
'''
    result=subprocess.run([UI,'-B','-c',code,str(tmp_path)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr


def test_qt_ten_to_eight_two_exports_and_merge_uses_actual_official_writers(tmp_path):
    from test_native_dataset import execution,episode
    from robot_learning_workbench.robot.calibration import JOINTS
    settings=execution('source');settings.update(single_task='Pick the red cube.',calibration={'records':{}},urdf_sha256='d'*64)
    settings['recording'].update(joint_order=list(JOINTS),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',task_phase='post_step',fps=30)
    workspace=tmp_path/'space';(workspace/'dataset').mkdir(parents=True)
    with native.NativeRun(workspace/'source/demo',settings)as owner:
        segment=owner.segment('one')
        for i in range(10):segment.write_episode(episode(6),episode_id=f'e{i}')
        segment.commit()
    before={p:native.file_sha256(p)for p in owner.root.rglob('*')if p.is_file()}
    code='''
from pathlib import Path
import sys,time
from PyQt6.QtCore import QTimer,Qt
from PyQt6.QtWidgets import QApplication,QFileDialog,QInputDialog
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.curation import CurationPage
from robot_learning_workbench.ui.dataset_merge import DatasetMergeDialog
app=QApplication([]);root=Path(sys.argv[2]);p=CurationPage(sys.argv[1],root);p.resize(1320,940);p.show()
def wait(test):
 end=time.monotonic()+40
 while not test()and time.monotonic()<end:app.processEvents();QTest.qWait(10)
 assert test(),p.state.text()
wait(lambda:len(p.rows)==10 and not p.busy and not p.plot_busy)
p.split();wait(lambda:not p.busy and p.dirty)
QInputDialog.getText=lambda *a,**kw:('split',True);p.save_revision()
train=root/'curation/source/demo/split_r001/train.json';val=train.with_name('val.json')
wait(lambda:p.source==str(train)and not p.busy and not p.plot_busy)
assert len(p.rows)==8 and val.is_file()
QFileDialog.getExistingDirectory=lambda *a,**kw:str(root/'dataset')
p.export();wait(lambda:not p.busy and 'LeRobot 저장 완료'in p.state.text())
p.revisions.choices.setCurrentIndex(p.revisions.choices.findData(str(val)))
wait(lambda:p.source==str(val)and not p.busy and not p.plot_busy)
assert len(p.rows)==2
p.export();wait(lambda:not p.busy and 'LeRobot 저장 완료'in p.state.text())
# The Merge dialog discovers new exports itself; no page reopen/refresh is needed.
def choose():
 dialog=app.activeModalWidget()
 if not isinstance(dialog,DatasetMergeDialog)or dialog.list.count()!=2:
  QTimer.singleShot(20,choose);return
 for i in range(2):dialog.list.item(i).setCheckState(Qt.CheckState.Checked)
 dialog.merge_button.click()
QTimer.singleShot(20,choose);QTest.mouseClick(p.buttons['Dataset Merge'],Qt.MouseButton.LeftButton)
wait(lambda:p.source is not None and Path(p.source).name.startswith('merged_')and not p.busy and not p.plot_busy)
assert len(p.rows)==10
p.close();app.processEvents()
'''
    result=subprocess.run([UI,'-B','-c',code,sys.executable,str(workspace)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=140)
    assert result.returncode==0,result.stdout+result.stderr
    exports=sorted((workspace/'dataset').glob('lerobot_*'))
    assert sorted(len(native.load_catalog(root).episodes)for root in exports)==[2,8]
    merged=next((workspace/'dataset').glob('merged_*'));catalog=native.load_catalog(merged)
    assert len(catalog.episodes)==10 and sorted(len(ids)for ids in catalog.splits.values())==[2,8]
    assert before=={p:native.file_sha256(p)for p in owner.root.rglob('*')if p.is_file()}
