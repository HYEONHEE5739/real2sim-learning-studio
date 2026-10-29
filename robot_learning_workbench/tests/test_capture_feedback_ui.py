"""Actual Qt state updates must not repaint disabled actions or erase command errors."""
from test_ui_restoration import qt


def test_repeated_unready_updates_do_not_toggle_capture_button(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtCore import QObject,QEvent
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');p=w.sessions['capture']
p.settings.recipe=lambda:{'execution':{'device_source':'hardware'}}
p.client.running=True;p.client.stage='capture_session'
class Changes(QObject):
 def __init__(self):super().__init__();self.states=[]
 def eventFilter(self,obj,event):
  if event.type()==QEvent.Type.EnabledChange:self.states.append(obj.isEnabled())
  return False
progress={'session_state':'OBSERVING','teleop_active':False,'capture_ready':False,'capture_reason':'wrist: stale/skew, 재촬영 필요','device_source':'hardware'}
p.update_progress(progress);watch=Changes();p.capture_button.installEventFilter(watch)
for _ in range(8):p.update_progress(progress)
assert watch.states==[],watch.states
p.client.running=False;w.close()
''',tmp_path)


def test_teleop_rejection_remains_visible_across_live_camera_updates(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');p=w.sessions['capture']
p.settings.recipe=lambda:{'execution':{'device_source':'hardware'}}
p.client.running=True;p.client.stage='capture_session'
p.event_received({'kind':'command_ack','payload':{'status':'rejected','reason':'Explicit reviewed command/follow budget required before motion; observation needs none'}})
for _ in range(5):p.update_progress({'session_state':'OBSERVING','capture_ready':False,'capture_reason':'안정된 Follower 관측을 기다립니다','device_source':'hardware'})
assert 'budget'in p.capture_hint.text()or any('budget'in label.text()and label.isVisibleTo(p)for label in p.findChildren(__import__('PyQt6.QtWidgets',fromlist=['QLabel']).QLabel))
p.client.running=False;w.close()
''',tmp_path)


def test_capture_requests_stay_available_between_slow_camera_frames_and_busy_locks(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');p=w.sessions['capture']
p.settings.recipe=lambda:{'execution':{'device_source':'hardware'}};p.client.running=True;p.client.stage='capture_session'
for ready in(False,True,False,True):
 p.update_progress({'session_state':'OBSERVING','capture_ready':ready,'capture_request_allowed':True,'capture_pending':False,'device_source':'hardware'})
 assert p.capture_button.isEnabled()
p.update_progress({'session_state':'CAPTURING','capture_request_allowed':False,'capture_pending':True})
assert not p.capture_button.isEnabled()and '처리'in p.capture_button.text()
p.update_progress({'session_state':'DISCONNECTING','capture_request_allowed':False,'capture_pending':False})
assert not p.capture_button.isEnabled()
p.client.running=False;w.close()
''',tmp_path)


def test_teleop_configuration_reason_is_independent_of_capture_stability(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');p=w.sessions['capture']
p.settings.recipe=lambda:{'execution':{'device_source':'hardware'}};p.client.running=True;p.client.stage='capture_session'
p.update_progress({'session_state':'OBSERVING','teleoperation_available':False,'teleoperation_reason':'Teleoperation: 명령 변화·추종 오차 제한 검토 필요','capture_ready':True,'capture_request_allowed':True,'device_source':'hardware'})
assert not p.start_teleop_button.isEnabled()and p.capture_button.isEnabled()
assert '제한'in p.start_teleop_button.toolTip()
p.client.running=False;w.close()
''',tmp_path)
