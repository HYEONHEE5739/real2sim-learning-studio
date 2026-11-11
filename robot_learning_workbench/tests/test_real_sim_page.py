from test_ui_restoration import qt


def test_real_sim_has_scene_engine_and_combined_teleop_capture_stop_without_authoring(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication,QPushButton,QPlainTextEdit
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');w.tabs.setCurrentIndex(1);w.show();app.processEvents();p=w.sessions['real_sim']
assert set(p.previews)=={'side','wrist','sim_side','sim_wrist'}
assert p.engine.count()==2 and p.scene_combo.isVisible()
assert p.connect_button.text()=='Real/Sim 연결 · Teleop'and p.capture_button.text()=='Capture'and p.stop_button.text()=='중단'
assert not hasattr(p,'candidate_combo')and not hasattr(p,'materials')and not hasattr(p,'settings')and not hasattr(p,'start_teleop_button')
texts=[b.text()for b in p.findChildren(QPushButton)]
assert not any('Teleoperation'in text or 'Input Data'in text or 'Scene 자료'in text for text in texts)
assert not any(m in sys.modules for m in('torch','lerobot','isaaclab','mujoco','serial'))
w.close();app.processEvents()
''',tmp_path)


def test_existing_refit_button_sends_source_bound_memo_without_another_reconstruction_button(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication,QPushButton
from robot_learning_workbench.ui.real_sim_page import RealSimPage
from real2sim_builder.project import Project
from real2sim_builder import evidence,ui_reconstruction
app=QApplication([]);root=Path(sys.argv[1]);project=Project.create(root/'scenes','memo')
page=RealSimPage('/no/worker',[],root);page.catalog_timer.stop();page.client.timer.stop()
row={'project':str(project.root),'scene':str(project.root/'exports/source/scene.json'),'engines':['mujoco']}
page.scene_combo.blockSignals(True);page.scene_combo.addItem('selected',row);page.scene_combo.blockSignals(False)
page.project={'project':str(project.root),'name':'memo'}
seen=[]
evidence.save_reconstruction_memo=lambda p,text,source:seen.append((p.root,text,source))
class Dialog:
 def __init__(self,*args,**kwargs):assert kwargs['refit']is True
 def exec(self):seen.append('opened existing refit dialog')
ui_reconstruction.ReconstructionDialog=Dialog
page.refinement_memo.setPlainText('The wrist gripper looks too small.')
page.open_refinement()
assert seen==[(project.root,'The wrist gripper looks too small.',row['scene']),'opened existing refit dialog']
assert len([b for b in page.findChildren(QPushButton)if b.text()=='촬영 자료로 Scene 재정합'])==1
assert not(project.root/'input/scene_memo.txt').exists()
page.close();app.processEvents()
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


def test_authored_comparison_is_visible_as_no_physics_and_native_stays_distinct(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.real_sim_page import RealSimPage
app=QApplication([]);p=RealSimPage('/no/worker',[],Path(sys.argv[1]));p.catalog_timer.stop();p.client.timer.stop()
simulation={'applied_sim_joint_rad':[0.]*6,'sim_joint_delta_rad':[0.]*6,'physics_steps':0,'state_application':'authored_measured_fk'}
p.update_progress({'session_state':'OBSERVING','simulation':simulation})
assert 'FK 시각 비교'in p.simulated.text()and '물리 실행 없음'in p.simulated.text()
simulation={**simulation,'physics_steps':10,'state_application':'native_physics_joint_target'}
p.update_progress({'session_state':'OBSERVING','simulation':simulation})
assert 'Sim 관절값'in p.simulated.text()and '물리 실행 없음'not in p.simulated.text()
p.close();app.processEvents()
''',tmp_path)
