"""Original Dataset selection and managed revision selection are separate UI flows."""
import os,subprocess,sys
from test_curation_revisions import dataset
from test_workbench_window import UI


def test_qt_managed_revisions_open_selected_dataset_and_original_dropdown(tmp_path):
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo1');dataset(workspace/'datagen/generated','datagen')
    code='''
import sys,time,json
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QInputDialog,QFileDialog,QComboBox,QSpinBox
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.curation import CurationPage
app=QApplication([]);root=Path(sys.argv[2]);p=CurationPage(sys.argv[1],root);p.show()
def wait(test):
 end=time.monotonic()+30
 while not test()and time.monotonic()<end:app.processEvents();QTest.qWait(10)
 assert test(),p.state.text()
wait(lambda:bool(p.rows)and not p.busy and not p.plot_busy)
assert hasattr(p,'revisions'),'No separate Revision selector'
assert not any(hasattr(p,name)for name in('histogram','review_button','frame','trim_start','trim_stop','assign','result','export_scope'))
assert p.table.columnCount()==7
def original(path):
 i=next(i for i in range(p.datasets.choices.count())if p.datasets.choices.itemData(i)['path']==str(path))
 p.datasets.choices.setCurrentIndex(i)
 wait(lambda:p.source==str(path)and not p.busy and not p.plot_busy)
original(root/'source/demo1')
QInputDialog.getText=lambda *a,**kw:('clean',True)
p.advanced_toggle.setChecked(True);app.processEvents()
p.table.item(0,2).setText('1');p.table.item(0,3).setText('4')
assert p.table.item(0,4).text()=='6'
def set_split(row,value):
 p.table.setCurrentCell(row,6);p.table.editItem(p.table.item(row,6));app.processEvents()
 combo=p.table.findChild(QComboBox)
 assert combo is not None and [combo.itemText(i)for i in range(combo.count())]==['','train','val']
 combo.setCurrentText(value);QTest.keyClick(combo,Qt.Key.Key_Return);app.processEvents()
 assert p.table.item(row,6).text()==value
epoch=p.reader.epoch
set_split(0,'val');assert p.reader.epoch==epoch,'Editing a Split reopened the same Episode'
set_split(0,'');set_split(0,'train');set_split(1,'train');set_split(2,'val')
p.save_revision()
first=root/'curation/source/demo1/clean_r001/train.json'
validation=first.with_name('val.json')
wait(lambda:p.source==str(first)and not p.busy and not p.plot_busy)
assert p.original_source==str(root/'source/demo1')
assert p.datasets.choices.currentData()['path']==p.original_source
assert [row['episode_id']for row in p.rows]==['e0','e1']
assert '전체 2개 중 2개 포함'in p.selection_count.text()
assert p.frame_range()==(1,4) and p.table.item(0,4).text()=='6'
assert p.table.item(0,6).text()=='train' and p.table.item(1,6).text()=='train'
assert validation.is_file() and 'train: 2'in p.state.text() and 'val: 1'in p.state.text()
# A nested Revision preserves the original length while bounding editable ranges.
p.table.editItem(p.table.item(0,3));app.processEvents();editor=p.table.findChild(QSpinBox)
assert editor.maximum()==4 and editor.minimum()==2
QTest.keyClick(editor,Qt.Key.Key_Escape);app.processEvents()
p.train_ratio.setValue(50);p.split()
wait(lambda:not p.busy and p.analysis_panel.isVisible())
app.processEvents()
rect=p.overview.scatter.rect();point=p.overview.scatter.mapTo(p.page_scroll.viewport(),rect.center())
assert p.page_scroll.viewport().rect().contains(point),'Preview did not scroll to the distribution'
assert p.revisions.choices.currentData()==str(first)
assert p.revisions.choices.currentText()=='clean_train_r001 · 2 Episode'
assert sum(row['selection_range'][1]-row['selection_range'][0]for row in p.rows)==9
p.episode_list.item(1).setCheckState(Qt.CheckState.Unchecked)
set_split(0,'train');p.table.item(0,2).setText('2');p.save_revision()
second=first.parent.with_name('clean_r002')/'train.json'
wait(lambda:p.source==str(second)and not p.busy and not p.plot_busy)
assert '전체 1개 중 1개 포함'in p.selection_count.text()
assert p.rows[0]['selection_range']==[2,4]
doc=json.loads(second.read_text());assert(second.parent/doc['source']['path']).resolve()==root/'source/demo1'
p.revisions.choices.setCurrentIndex(p.revisions.choices.findData(str(first)))
wait(lambda:p.source==str(first)and not p.busy and not p.plot_busy)
assert len(p.rows)==2 and all(row['included']for row in p.rows)
p.revisions.choices.setCurrentIndex(0)
wait(lambda:p.source==str(root/'source/demo1')and not p.busy and not p.plot_busy)
assert '전체 3개 중 3개 포함'in p.selection_count.text()
original(root/'datagen/generated');assert p.revisions.choices.count()==1
dialogs=[]
def choose(*args,**kwargs):dialogs.append(args[2]);return str(first),'JSON'
QFileDialog.getOpenFileName=choose;p.choose_revision()
wait(lambda:p.source==str(first)and not p.busy and not p.plot_busy)
assert dialogs==[str(root/'curation')]
assert p.datasets.choices.currentData()['path']==str(root/'source/demo1')
calls=[]
p.perform=lambda op,**args:calls.append((op,args))
QFileDialog.getExistingDirectory=lambda *args:str(root/'exports')
p.export()
assert calls[-1][0]=='materialize' and 'split'not in calls[-1][1]
assert calls[-1][1]['source']==str(first)
p.close();app.processEvents();assert not p.preview_directory.exists()
'''
    result=subprocess.run([UI,'-B','-c',code,sys.executable,str(workspace)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=110)
    assert result.returncode==0,result.stdout+result.stderr
