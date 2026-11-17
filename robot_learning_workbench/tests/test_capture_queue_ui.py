"""Offscreen UI receipts/history only; no Object Library, engine or hardware."""
from test_ui_restoration import qt


def test_both_pages_accept_another_click_and_update_the_same_capture_row(tmp_path):
    qt(r'''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
from robot_learning_workbench.ui.jobs import BackendJob
app=QApplication([]);root=Path(sys.argv[1]);BackendJob.start=lambda *a,**k:None
w=Window('/no/worker',root/'modules',root/'workspace');w.show()
for p in w.sessions.values():p.stop_timers()
for index,name in[(0,'capture'),(1,'real_sim')]:
 w.tabs.setCurrentIndex(index);app.processEvents();p=w.sessions[name];p.client.running=True;p.client.cancel_requested=False
 p.client.stage='capture_session'if name=='capture'else'paired_session';sent=[];p.client.send=lambda kind,payload=None:sent.append(kind)
 p.update_progress(dict(session_state='TELEOP_ACTIVE',teleop_active=True,teleoperation_available=True,
  capture_pending=True,capture_queue_size=1,capture_queue_capacity=4,capture_request_allowed=True,capture_phase='registering'))
 assert p.capture_button.isEnabled()and '중'in p.capture_hint.text()and '추가 촬영 가능'in p.capture_hint.text()
 p.capture_button.click();assert sent==['session_snapshot']
 for phase in['REQUESTED','OBSERVED','QUEUED','RAW_SAVED','SIM_PAIR','REGISTERING','REGISTERED']:
  p.update_progress({'capture_update':dict(id='shot',command_id='command',phase=phase,path=str(root/'shot'),q_measured=[0.]*6)})
 assert p.snapshot_table.rowCount()==1 and p.rows[0]['phase']=='REGISTERED'
 p.update_progress({'capture_update':dict(id='full',command_id='rejected',phase='REQUESTED',path=None)})
 p.event_received(dict(kind='command_ack',payload=dict(command_id='rejected',status='rejected',reason='Capture queue full')))
 assert p.rows[1]['phase']=='FAILED'and 'queue full'in p.rows[1]['error']
 p.update_progress(dict(capture_queue_size=4,capture_request_allowed=False));assert not p.capture_button.isEnabled()
 p.update_progress({'capture_update':dict(id='unfinished',command_id='unfinished',phase='RAW_SAVED',path=str(root/'pending'))})
 p.client.running=False;p.ended('failed')
 assert p.rows[0]['phase']=='REGISTERED'and p.rows[2]['phase']=='FAILED'
w.close();app.processEvents()
assert not any(n in sys.modules for n in['torch','mujoco','isaaclab','lerobot','serial'])
''',tmp_path)


def test_qt_capture_click_carries_its_clock_to_actual_r03_command_storage(tmp_path):
    qt(r'''
from pathlib import Path
import json,sys,time
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.session_client import SessionClient
from robot_learning_workbench.run import _poll_commands
app=QApplication([]);root=Path(sys.argv[1])/'run';root.mkdir()
for name in['commands','acks']:(root/name).mkdir()
(root/'run.json').write_text(json.dumps(dict(request_id='request',stage='capture_session',status='running',phase='running')))
client=SessionClient('/no/worker','unused');client.timer.stop();client.running=True;client.stage='capture_session'
client.handle=dict(run_id='run',request_id='request',run_dir=str(root));updates=[];client.progress.connect(updates.append)
before=time.monotonic_ns();key=client.send('session_snapshot');after=time.monotonic_ns()
state=dict(seq=0,seen_commands=set(),command_seq=0,context={})
command,=_poll_commands(root,state,'capture_session')
assert command['command_id']==key and before<=command['payload']['requested_ns']<=after
assert command['payload']['policy']=='observation'
assert updates[0]['capture_update']['phase']=='REQUESTED'
assert not any(u.get('snapshot')for u in updates),'A click was misreported as a saved capture'
client.running=False;client.deleteLater();app.processEvents()
assert not any(n in sys.modules for n in['torch','mujoco','isaaclab','lerobot','serial'])
''',tmp_path)
