"""Qt is a separate interpreter; no SDK or robot IO from the frontend."""
from test_ui_restoration import qt


def test_dedicated_capture_and_pair_tabs_follow_mockup_and_keep_sdk_out_of_qt(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace')
for size in ((1320,900),(1920,1080)):
 w.resize(*size);w.show();app.processEvents()
 for name,tab in [('capture',0),('real_sim',1)]:
  w.tabs.setCurrentIndex(tab);app.processEvents();p=w.sessions[name]
  assert p.project_combo.isVisible() and p.settings_button.isVisible()
  assert set(p.previews)==({'side','wrist'}if name=='capture'else{'side','wrist','sim_side','sim_wrist'})
  assert p.snapshot_table.isVisible() and len(p.joint_labels)==6
  assert not p.start_teleop_button.isEnabled()and not p.capture_button.isEnabled()
  assert not p.disconnect_button.isEnabled()and not p.finish_button.isEnabled()
  assert p.width()<=size[0] and p.height()<size[1]
w.close();app.processEvents();assert not w.isVisible()
assert not any(m in sys.modules for m in ('torch','lerobot','isaaclab','mujoco','serial'))
''',tmp_path)


def test_device_configuration_forms_and_json_share_existing_profile_buffers(tmp_path):
    qt('''
from pathlib import Path
import sys,json
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.session_settings import DeviceSettings
app=QApplication([]);root=Path(sys.argv[1]);p=DeviceSettings(root)
p.set_document('device_profile',{'role':'follower','calibration_path':'calibration.json','sdk':{'port':'/dev/first','id':'follower','use_degrees':True}})
p.ports['device_profile'].setText('/dev/second');p.ports['device_profile'].editingFinished.emit()
assert p.documents['device_profile'].data()['sdk']['port']=='/dev/second'
p.documents['device_profile'].text.setPlainText(json.dumps({'role':'follower','calibration_path':'other.json','sdk':{'port':'/dev/third','id':'follower','use_degrees':True}}))
p.sync_forms('device_profile');assert p.ports['device_profile'].text()=='/dev/third'
assert p.dirty and not p.validated
p.close()
''',tmp_path)


def test_saved_device_configuration_reloads_as_saved_json_without_second_save(tmp_path):
    qt('''
from pathlib import Path
import sys,json
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.session_settings import DeviceSettings
app=QApplication([]);root=Path(sys.argv[1]);p=DeviceSettings(root)
p.set_document('device_profile',{'role':'follower','calibration_path':'/fixture/calibration.json','sdk':{'port':'/fixture/port','id':'follower','use_degrees':True}})
path=p.save(root/'config.yaml');other=DeviceSettings(root);other.load_recipe(path)
data=other.recipe();assert data['inputs']['device_profile'].endswith('.json')
assert json.loads(Path(data['inputs']['device_profile']).read_text())['sdk']['port']=='/fixture/port'
''',tmp_path)
