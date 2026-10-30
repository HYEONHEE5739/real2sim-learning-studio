from test_ui_restoration import qt


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
