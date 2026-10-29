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


def test_session_identity_controls_and_hidden_pending_activation_are_locked(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication,QInputDialog
from robot_learning_workbench.ui.app import Window
app=QApplication([]);w=Window('/no/worker',Path(sys.argv[1])/'modules',Path(sys.argv[1])/'workspace');w.show();app.processEvents();p=w.sessions['capture']
p.client.running=True;p.client.stage='capture_session';p.last_progress={'teleop_active':False};sent=[];p.send=lambda kind,payload=None:sent.append(kind);p.buttons(True)
assert not p.settings.configuration.isEnabled()and all(not b.isEnabled()for b in p.project_buttons)
QInputDialog.getText=lambda *a:(_ for _ in()).throw(AssertionError('Must not open Project editor while connected'))
p.new_project();assert p.project is None
w.tabs.setCurrentIndex(1);app.processEvents();assert 'teleop_stop'in sent
p.client.running=False;w.close();app.processEvents()
''',tmp_path)
