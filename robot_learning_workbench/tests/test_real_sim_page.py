from test_ui_restoration import qt


def test_real_sim_has_scene_engine_and_observe_capture_stop_without_authoring_or_teleop(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication,QPushButton,QPlainTextEdit
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');w.tabs.setCurrentIndex(1);w.show();app.processEvents();p=w.sessions['real_sim']
assert set(p.previews)=={'side','wrist','sim_side','sim_wrist'}
assert p.engine.count()==2 and p.scene_combo.isVisible()
assert p.connect_button.text()=='Real/Sim 연결'and p.capture_button.text()=='Capture'and p.stop_button.text()=='중단'
assert not hasattr(p,'candidate_combo')and not hasattr(p,'materials')and not hasattr(p,'settings')and not hasattr(p,'start_teleop_button')
texts=[b.text()for b in p.findChildren(QPushButton)]
assert not any('Teleoperation'in text or 'Input Data'in text or 'Scene 자료'in text for text in texts)
assert not any(m in sys.modules for m in('torch','lerobot','isaaclab','mujoco','serial'))
w.close();app.processEvents()
''',tmp_path)


def test_stop_during_preparation_does_not_start_a_late_session(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.session_client import SessionClient
app=QApplication([]);client=SessionClient('/no/worker','modules');calls=[];terminal=[]
client.job.start=lambda *a,**k:calls.append((a,k));client.terminal.connect(terminal.append)
client.path='pending.yaml';client.busy=True;client.phase='prepare';client.cancel()
client.done({'ok':True,'result':{'runnable':True,'recipe_sha256':'a'*64,'prepared_sha256':'b'*64}})
assert not calls and terminal==['cancelled']and not client.active()
client.timer.stop()
''',tmp_path)


def test_stop_while_start_reply_is_pending_cancels_the_claimed_worker(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.session_client import SessionClient
app=QApplication([]);client=SessionClient('/no/worker','modules');sent=[];client.send=lambda kind,payload=None:sent.append(kind)
client.busy=True;client.phase='start';client.cancel();client.done({'ok':True,'result':{'run_id':'owned'}})
assert sent==['cancel']and client.running
client.running=False;client.timer.stop()
''',tmp_path)
