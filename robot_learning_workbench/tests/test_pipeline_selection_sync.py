"""YAML edits and the compact Scene/engine selectors describe the same draft."""
import pytest
from test_pipeline_scripts import qt


@pytest.mark.parametrize('stage',['annotation','datagen','simulation_evaluation'])
def test_yaml_engine_edit_then_scene_selection_uses_the_edited_engine(tmp_path,stage):
    qt('''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1])
p=WorkflowPage(STAGE,'/no/worker','modules');s=p.settings
row={'name':'Scene','revision':'r1','project':str(root/'project'),'scene':str(root/'project/export/scene.json'),
     'engines':['isaac','mujoco'],'engine_config':{'isaac':str(root/'isaac.json'),'mujoco':str(root/'mujoco.json')}}
s.query_operation='scenes';s.received({'ok':True,'result':{'scenes':[row]}})
for engine,key in (('isaaclab','isaac'),('mujoco','mujoco')):
 text=p.editor.text.toPlainText().replace('engine: '+p.engine.currentText(),'engine: '+engine)
 text+='\\n# Preserve typed comments and formatting\\n'
 version=s.version;p.ready={'old':'plan'};p.editor.text.setPlainText(text)
 assert p.engine.currentText()==engine,(engine,p.engine.currentText())
 assert p.editor.text.toPlainText()==text and s.version==version+1
 assert p.ready is None and p.editor.dirty and not p.start_button.isEnabled()
 s.scene.setCurrentIndex(0);s.scene.setCurrentIndex(1)
 assert p.editor.data()['inputs']['engine_config']==row['engine_config'][key]
 assert p.editor.data()['engine']==engine
assert not any(n in sys.modules for n in ('mujoco','isaaclab','torch','serial'))
p.timer.stop();p.close()
'''.replace('STAGE',repr(stage)),tmp_path)


def test_yaml_scene_changes_show_exact_revision_or_external_path_without_rewriting(tmp_path):
    qt('''
import sys,yaml
from pathlib import Path
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('datagen','/no/worker','modules');s=p.settings
script=root/'script.yaml';script.write_text(yaml.safe_dump(p.editor.data()));p.editor.load(script)
rows=[{'name':'Scene','revision':rev,'project':str(root/'project'),'scene':str(root/rev/'scene.json'),'engines':['mujoco'],'engine_config':{}}for rev in ('old','new')]
s.query_operation='scenes';s.received({'ok':True,'result':{'scenes':rows}})
for value,index in (('./old/scene.json',1),('./new/scene.json',2),('./outside/scene.json',0),('',0)):
 data=p.editor.data();data['inputs']['scene']=value
 text=yaml.safe_dump(data,sort_keys=False)+'# retain this comment\\n';p.editor.text.setPlainText(text)
 assert s.scene.currentIndex()==index
 if value and index==0:
  assert str(root/'outside/scene.json')==s.scene.itemData(0,Qt.ItemDataRole.ToolTipRole)
  assert 'outside' in s.scene.currentText()
 if not value:assert s.scene.currentText()=='Scene 선택'
 assert p.editor.text.toPlainText()==text
assert script.read_text()!=p.editor.text.toPlainText()
p.timer.stop();p.close()
''',tmp_path)


def test_invalid_yaml_clears_stale_choices_and_recovers_without_overwriting(tmp_path):
    qt('''
import sys,yaml
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('annotation','/no/worker','modules');s=p.settings
row={'name':'Scene','revision':'r','project':str(root),'scene':str(root/'scene.json'),'engines':['mujoco'],'engine_config':{}}
s.query_operation='scenes';s.received({'ok':True,'result':{'scenes':[row]}})
good=p.editor.data();good['inputs']['scene']=row['scene'];original=yaml.safe_dump(good)
for broken in ('inputs: [','engine: {bad: value}\\n','engine: unsupported\\n','inputs: {}\\n'):
 p.editor.text.setPlainText(original);assert s.scene.currentIndex()==1
 p.editor.text.setPlainText(broken)
 assert p.engine.currentIndex()==-1 and s.scene.currentIndex()==0
 assert p.editor.text.toPlainText()==broken and not p.start_button.isEnabled()
 if 'unsupported' in broken:
  s.scene.setCurrentIndex(1)
  assert p.editor.text.toPlainText()==broken,'Scene selection assumed MuJoCo for invalid YAML engine'
 p.editor.text.setPlainText(original)
 assert p.engine.currentText()=='mujoco' and s.scene.currentIndex()==1
 assert p.editor.text.toPlainText()==original
p.timer.stop();p.close()
''',tmp_path)


def test_engine_dropdown_still_updates_yaml_and_registered_scene_config(tmp_path):
    qt('''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
app=QApplication([]);root=Path(sys.argv[1]);p=WorkflowPage('datagen','/no/worker','modules');s=p.settings
row={'name':'Scene','revision':'r','project':str(root),'scene':str(root/'scene.json'),'engines':['mujoco','isaac'],
     'engine_config':{'mujoco':str(root/'mj.json'),'isaac':str(root/'is.json')}}
s.query_operation='scenes';s.received({'ok':True,'result':{'scenes':[row]}});s.scene.setCurrentIndex(1)
for engine,key in (('isaaclab','isaac'),('mujoco','mujoco')):
 p.engine.setCurrentText(engine)
 assert p.editor.data()['engine']==engine
 assert p.editor.data()['inputs']['engine_config']==row['engine_config'][key]
 assert s.scene.currentIndex()==1
p.timer.stop();p.close()
''',tmp_path)
