from test_ui_restoration import qt


def test_capture_can_configure_missing_limits_from_start_without_reconnecting(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
import robot_learning_workbench.ui.teleop_controls as controls
app=QApplication([]);w=Window('/no/worker',Path(sys.argv[1])/'modules',Path(sys.argv[1])/'workspace');w.show();app.processEvents();p=w.sessions['capture']
p.client.running=True;p.client.stage='capture_session';sent=[];p.client.send=lambda kind,payload=None:sent.append((kind,payload))
controls.request_limits=lambda parent,current:{'max_command_step_rad':.05,'max_follow_error_rad':.2}
p.update_progress({'session_state':'OBSERVING','teleoperation_available':True,'teleoperation_reason':'이동 제한 설정 필요','capture_request_allowed':True})
assert p.start_teleop_button.isEnabled();p.start_teleop_button.click()
assert sent==[('teleop_prepare',{'max_command_step_rad':.05,'max_follow_error_rad':.2})]
p.client.running=False;w.close();app.processEvents()
''',tmp_path)


def test_real_sim_connection_requests_supervised_leader_control_after_scene_ready(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);w=Window('/no/worker',Path(sys.argv[1])/'modules',Path(sys.argv[1])/'workspace');w.tabs.setCurrentIndex(1);w.show();app.processEvents();p=w.sessions['real_sim']
p.client.running=True;p.client.stage='paired_session';sent=[];p.client.send=lambda kind,payload=None:sent.append((kind,payload));p.request_control=True
p.update_progress({'session_state':'CONNECTING','teleoperation_available':True});app.processEvents();assert sent==[]
p.update_progress({'session_state':'OBSERVING','teleoperation_available':True});app.processEvents()
assert [row[0]for row in sent]==['teleop_prepare']
p.update_progress({'session_state':'OBSERVING','teleoperation_available':True});app.processEvents();assert len(sent)==1
p.update_progress({'session_state':'TELEOP_ACTIVE','teleop_active':True,'teleoperation_available':True});w.tabs.setCurrentIndex(0);app.processEvents()
assert sent[-1][0]=='teleop_stop'
p.client.running=False;w.close();app.processEvents()
''',tmp_path)


def test_device_setup_exposes_reviewed_limits_without_advanced_yaml(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.device_setup import DeviceSetup
app=QApplication([]);d=DeviceSetup(Path(sys.argv[1]),'/no/worker','modules');d.show();app.processEvents()
assert d.motion_limits.isVisible()and not d.advanced.isVisible()
assert d.motion_limits.values()=={},'Do not invent approved hardware limits'
d.motion_limits.load({'max_command_step_rad':.05,'max_follow_error_rad':.2});assert d.motion_limits.values()['max_command_step_rad']==.05
d.calibration_client.timer.stop();d.close()
''',tmp_path)


def test_motion_form_and_yaml_edit_the_same_device_configuration_buffer(tmp_path):
    qt('''
from pathlib import Path
import sys,yaml
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.device_setup import DeviceSetup
app=QApplication([]);d=DeviceSetup(Path(sys.argv[1]),'/no/worker','modules')
d.load_recipe(Path.cwd()/'workbench_runs/devices/so101-pickplace-0b794e7c/capture.yaml')
d.motion_limits.fields['max_command_step_rad'].setValue(.05);d.motion_limits.fields['max_follow_error_rad'].setValue(.2)
assert d.advanced.data()['execution']['max_command_step_rad']==.05
buffer=d.advanced.data();buffer['execution']['max_command_step_rad']=.03;d.advanced.text.setPlainText(yaml.safe_dump(buffer))
assert d.motion_limits.values()['max_command_step_rad']==.03
d.calibration_client.timer.stop();d.close()
''',tmp_path)


def test_capture_terminal_closes_a_pending_on_site_approval(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication,QDialog
from robot_learning_workbench.ui.app import Window
app=QApplication([]);w=Window('/no/worker',Path(sys.argv[1])/'modules',Path(sys.argv[1])/'workspace');w.show();app.processEvents();p=w.sessions['capture']
d=QDialog(p);p.approval_dialog=d;d.show();app.processEvents();assert d.isVisible()
p.ended('failed');app.processEvents();assert not d.isVisible()
w.close();app.processEvents()
''',tmp_path)


def test_partial_yaml_edit_does_not_crash_the_device_form(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.device_setup import DeviceSetup
app=QApplication([]);d=DeviceSetup(Path(sys.argv[1]),'/no/worker','modules')
for text in ('execution: [','execution: wrong-type','execution: {max_command_step_rad: wrong-type}'):
 d.advanced.text.setPlainText(text);app.processEvents();d.motion_limits.fields['max_follow_error_rad'].setValue(.2);app.processEvents()
assert d.dirty
d.motion_limits.fields['max_command_step_rad'].setValue(.05);app.processEvents()
assert d.advanced.data()['execution']['max_command_step_rad']==.05
d.calibration_client.timer.stop();d.close()
''',tmp_path)
