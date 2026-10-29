from test_ui_restoration import qt


def test_new_device_ui_has_basic_choices_and_one_advanced_recipe_buffer(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.device_setup import DeviceSetup
app=QApplication([]);p=DeviceSetup(Path(sys.argv[1]),'/no/worker','modules');p.show();app.processEvents()
p.discovered({'serial':[{'path':'/dev/ttyACM7','serial':'new','vid':1,'pid':2}],'cameras':[{'path':'/dev/v4l/by-id/one'},{'path':'/dev/v4l/by-id/two'}]})
assert p.robot.currentData()=='so101'and p.leader.count()==2 and p.side.count()==3
assert not p.advanced.isVisible()and not hasattr(p,'step')and not hasattr(p,'ports')
assert not any(m in sys.modules for m in('serial','lerobot','torch','mujoco'))
p.close()
''',tmp_path)


def test_scene_capture_right_panel_is_optional_inputs_and_bright_free_notes(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');w.show();app.processEvents();p=w.sessions['capture']
assert p.input_button.isVisible()and p.notes.isVisible()and p.save_materials.isVisible()
assert p.notes.palette().base().color().lightness()>150
assert p.settings.configuration.parent()is p.settings and not p.settings.configuration.isVisible()
assert 'Recipe'not in p.notes.placeholderText()
w.close();app.processEvents()
''',tmp_path)


def test_busy_device_request_and_missing_saved_file_are_reported_without_ui_exception(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.device_setup import DeviceSetup
app=QApplication([]);root=Path(sys.argv[1]);p=DeviceSetup(root,'/no/worker','modules')
p.operation='session_devices';p.job.process.state=lambda:QProcess.ProcessState.Running
p.save_selected();assert p.operation=='session_devices'and '기다리' in p.status.text()
p.configuration.addItem('Missing',str(root/'missing.yaml'));p.configuration.setCurrentIndex(p.configuration.count()-1)
assert p.saved_recipe is None and 'missing.yaml'in p.status.text()
p.close()
''',tmp_path)


def test_failed_scene_selection_cannot_capture_into_previous_scene(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');p=w.sessions['capture']
p.project={'project':str(root/'A'),'name':'A'};p.project_combo.addItem('A',str(root/'A'));p.settings.saved_recipe=root/'A-config.yaml';p.buttons(False)
p.job.start=lambda *args,**kwargs:None
p.load_project(root/'B');assert not p.connect_button.isEnabled()and p.project is None
p.project_result({'ok':False,'error':{'message':'Bound B configuration changed'}})
assert p.project is None and p.settings.saved_recipe is None and not p.connect_button.isEnabled()
assert 'changed'in p.operation_message.text()
w.close();app.processEvents()
''',tmp_path)


def test_snapshot_rows_in_one_historical_dataset_keep_distinct_observation_identity(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');p=w.sessions['capture']
for key in('one','two','one'):p.snapshot_table.append({'id':key,'path':str(root/'shared-dataset'),'q_measured':[]})
assert len(p.rows)==2 and p.snapshot_table.rowCount()==2
w.close()
''',tmp_path)


def test_snapshot_details_select_only_chosen_observation_images_and_pair(tmp_path):
    qt('''
from pathlib import Path
import sys,json,yaml
from PyQt6.QtWidgets import QApplication,QPlainTextEdit
from PyQt6.QtGui import QImage,QColor
from robot_learning_workbench.ui.session_results import ResultsDialog
app=QApplication([]);root=Path(sys.argv[1]);dataset=root/'dataset';rows=[]
for name,color in(('one','red'),('two','blue')):
 shot=dataset/'shots'/name;shot.mkdir(parents=True)
 image=QImage(32,24,QImage.Format.Format_RGB32);image.fill(QColor(color));image.save(str(shot/'side.png'));image.save(str(shot/'sim_side.png'))
 (shot/'pair.json').write_text(json.dumps({'selected_snapshot':name}))
 rows.append({'id':name,'path':'shots/'+name})
(dataset/'capture_manifest.yaml').write_text(yaml.safe_dump({'schema':'real2sim.snapshot/1','snapshots':rows}))
row={'id':'two','path':str(dataset),'q_measured':[.2]*6,'images':{'side':str(dataset/'shots/two/side.png')}}
dialog=ResultsDialog(row)
assert len(dialog.files)==2 and all(path.parent.name=='two'for path in dialog.files)
assert json.loads(dialog.findChild(QPlainTextEdit).toPlainText())['comparison']['selected_snapshot']=='two'
assert Path(dialog.selection.currentData()).parent.name=='two'
dialog.close()
''',tmp_path)
