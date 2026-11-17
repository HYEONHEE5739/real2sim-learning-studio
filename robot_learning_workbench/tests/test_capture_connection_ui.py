"""One user Connect click authorizes one start after readiness, never a retry."""
from test_ui_restoration import qt


SCRIPT=r'''
from pathlib import Path
import sys
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication,QPushButton
from robot_learning_workbench.ui.app import Window
from robot_learning_workbench.ui.jobs import BackendJob
app=QApplication([]);root=Path(sys.argv[1]);BackendJob.start=lambda *a,**k:None
w=Window('/no/worker',root/'modules',root/'workspace');w.show()
for p in w.sessions.values():p.stop_timers()
p=w.sessions['capture'];p.project={'project':str(root/'project'),'name':'test'}
p.settings.saved_recipe=root/'saved.yaml'
data={'stage':'capture_session','inputs':{'leader_device_profile':'leader'},'execution':{'device_source':'memory'}}
p.settings.recipe=lambda:dict(data,inputs=data['inputs'].copy())
sent=[];connections=[];p.client.send=lambda kind,payload=None:sent.append(kind)
def connected(path):
 connections.append(path);p.client.stage=data['stage'];p.client.running=True
p.client.connect_session=connected;p.buttons(False)
def settle():
 for _ in range(5):app.processEvents()
settle()
'''


def test_connect_click_starts_teleop_once_after_ready_and_never_rearms_after_fault(tmp_path):
    qt(SCRIPT+r'''
assert not hasattr(p,'start_teleop_button'),'Scene Prepare must expose only three session actions'
p.connect_button.click();assert len(connections)==1 and sent==[]
p.update_progress({'session_state':'CONNECTING','teleoperation_available':True});assert not sent
p.update_progress({'session_state':'OBSERVING','teleoperation_available':True,'teleop_active':False});assert sent==['teleop_start']
for _ in range(4):p.update_progress({'session_state':'OBSERVING','teleoperation_available':True,'teleop_active':False})
assert sent==['teleop_start']
p.update_progress({'session_state':'TELEOP_ACTIVE','teleop_active':True});assert not p.connect_button.isEnabled()
p.update_progress({'session_state':'OBSERVING','teleop_active':False,'error':'Stale feedback/Leader command'})
assert sent==['teleop_start'] and p.connect_button.isEnabled()
p.connect_button.click();assert sent==['teleop_start','teleop_start']and len(connections)==1
p.client.running=False;w.close();settle()
''',tmp_path)


def test_connect_start_intent_is_cancelled_on_finish_tab_change_rejection_and_camera_only(tmp_path):
    qt(SCRIPT+r'''
for cancelled_by in ['finish','tab','rejected','client_error','camera_only']:
 p.client.running=False;p.finishing=False;p.last_progress={};w.tabs.setCurrentIndex(0);settle()
 data['stage']='scene_capture'if cancelled_by=='camera_only'else'capture_session'
 p.buttons(False);p.connect_button.click();sent.clear()
 if cancelled_by=='finish':p.client.finish=lambda:None;p.finish()
 elif cancelled_by=='tab':w.tabs.setCurrentIndex(1);settle()
 elif cancelled_by=='rejected':p.event_received({'kind':'command_ack','payload':{'status':'rejected','reason':'Device identity mismatch'}})
 elif cancelled_by=='client_error':p.client.error.emit('Connection response could not be read')
 p.update_progress({'session_state':'OBSERVING','teleoperation_available':cancelled_by!='camera_only','teleop_active':False,'capture_request_allowed':True})
 assert 'teleop_start'not in sent,(cancelled_by,sent)
 p.client.running=False
w.close();settle()
''',tmp_path)


def test_three_actions_fit_left_camera_column_and_right_sidebar_keeps_its_width(tmp_path):
    qt(SCRIPT+r'''
for size in[(1280,720),(1650,920),(1920,1080)]:
 w.resize(*size);settle()
 controls=[p.connect_button,p.capture_button,p.finish_button]
 assert not hasattr(p,'start_teleop_button')
 left=p.camera_area.mapTo(p,QPoint());right=left.x()+p.camera_area.width()
 assert abs(controls[0].mapTo(p,QPoint()).x()-left.x())<=2
 assert abs(controls[-1].mapTo(p,QPoint()).x()+controls[-1].width()-right)<=2
 assert max(b.width()for b in controls)-min(b.width()for b in controls)<=2
 assert all(b.visibleRegion().boundingRect().height()==b.height()for b in controls)
 assert p.materials.width()>=240
w.close();settle()
''',tmp_path)
