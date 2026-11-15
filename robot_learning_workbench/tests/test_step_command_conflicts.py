"""Real command routing/ACK boundaries with no engine, inference or hardware."""
import pytest

from robot_learning_workbench.commands import command_channels,control_commands,step_completed


def _state():return {'steps':0,'paused':False,'cancelled':False,'marks':[]}


def _step(identifier,count=2):
    return {'command_id':identifier,'kind':'step','payload':{'count':count},'env_index':0,'episode_id':'episode-a'}


def _apply(rows,state,events):
    control_commands(rows,state,events,tick=7,episode_id='episode-a',env_index=0)


def _acks(events,identifier):
    return[event['payload']for event in events if event['kind']=='command_ack'and event['payload']['command_id']==identifier]


@pytest.mark.parametrize('same_poll',[True,False])
def test_second_distinct_step_is_rejected_without_losing_first_or_failing_worker(same_poll):
    state=_state();events=[];first=_step('first');second=_step('second',1)
    if same_poll:_apply([first,second],state,events.append)
    else:
        _apply([first],state,events.append);_apply([second],state,events.append)
    assert state['steps']==2 and state['step_command']=='first'and state['paused']
    assert not _acks(events,'first')
    rejection=_acks(events,'second')
    assert len(rejection)==1 and rejection[0]['status']=='rejected'and rejection[0].get('reason')
    step_completed(state,events.append,8)
    assert state['steps']==1 and not _acks(events,'first')
    step_completed(state,events.append,9)
    assert _acks(events,'first')==[{'command_id':'first','status':'completed','applied_tick':9}]
    assert state['steps']==0 and 'step_command'not in state


def test_same_pending_step_replay_does_not_send_premature_terminal_ack():
    state=_state();events=[];row=_step('same')
    _apply([row],state,events.append);_apply([dict(row)],state,events.append)
    assert state['steps']==2 and state['step_command']=='same'
    assert not _acks(events,'same')
    step_completed(state,events.append,8);step_completed(state,events.append,9)
    assert _acks(events,'same')==[{'command_id':'same','status':'completed','applied_tick':9}]


@pytest.mark.parametrize('cancel_first',[False,True])
def test_busy_step_plus_cancel_never_raises_and_cancel_wins(cancel_first):
    state=_state();events=[];_apply([_step('first')],state,events.append)
    cancel={'command_id':'cancel','kind':'cancel','payload':{'reason':'stop'}}
    rows=[cancel,_step('second',1)]if cancel_first else[_step('second',1),cancel]
    _apply(rows,state,events.append)
    assert state['cancelled']is True
    assert not _acks(events,'first'),'Cancellation must not invent completed physics steps'
    assert _acks(events,'cancel')[0]['status']=='completed'


def test_channel_ack_dedup_cannot_hide_original_step_completion():
    queue=[_step('first'),_step('first'),_step('second',1)];events=[]
    def commands():
        rows=queue.copy();queue.clear();return rows
    polls,send=command_channels(commands,events.append,1)
    state=_state();_apply(polls[0](),state,send)
    assert not _acks(events,'first')
    assert len(_acks(events,'second'))==1 and _acks(events,'second')[0]['status']=='rejected'
    step_completed(state,send,8);step_completed(state,send,9)
    assert _acks(events,'first')==[{'command_id':'first','status':'completed','applied_tick':9}]
    assert polls[0]()==[]


def test_vector_step_remains_rejected_without_per_env_physics_permission():
    queue=[_step('vector-step',1)];events=[]
    def commands():
        rows=queue.copy();queue.clear();return rows
    polls,send=command_channels(commands,events.append,2,vector=True)
    assert polls[0]()==[]and polls[1]()==[]
    assert len(_acks(events,'vector-step'))==1
    assert _acks(events,'vector-step')[0]['status']=='rejected'


def test_real_r03_claims_distinct_steps_once_and_records_conflict_as_rejected(tmp_path,monkeypatch):
    from robot_learning_workbench import run as worker
    from test_worker_protocol import claim_without_spawn
    handle,_=claim_without_spawn(tmp_path,monkeypatch)
    state={'seq':0,'context':{'episode_id':'episode-a','env_index':0},'seen_commands':set(),'command_seq':0}
    first=_step('first');second=_step('second',1)
    worker.send_command(handle,first);worker.send_command(handle,first);worker.send_command(handle,second)
    pending=worker._poll_commands(handle.run_dir,state,'annotation')
    assert[command['command_id']for command in pending]==['first','second']
    assert worker._poll_commands(handle.run_dir,state,'annotation')==()
    events=[]
    def send(event):
        events.append(event);worker._stage_event(handle.run_dir,state,event)
    control=_state();_apply(pending,control,send)
    assert worker.send_command(handle,first).status=='accepted'
    assert worker.send_command(handle,second).status=='rejected'
    step_completed(control,send,8);step_completed(control,send,9)
    assert worker.send_command(handle,first).status=='completed'
    assert worker.send_command(handle,first).applied_tick==9
    assert len(_acks(events,'first'))==1 and len(_acks(events,'second'))==1


def test_qt_step_pending_waits_for_matching_terminal_ack(tmp_path):
    from test_pipeline_scripts import qt
    qt('''
import sys,json
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench import run
app=QApplication([]);root=Path(sys.argv[1]);folder=root/'run';folder.mkdir();(folder/'commands').mkdir()
(folder/'run.json').write_text(json.dumps(dict(run_id='run',request_id='request',status='running',phase='running',stage='annotation')))
p=WorkflowPage('annotation','/no/worker','modules');p.timer.stop()
p.handle=dict(run_id='run',request_id='request',run_dir=str(folder),output_path=str(root/'out'))
p.context={'episode_id':'one','env_index':0,'tick':1};sent=[]
def send(h,c):sent.append(c);return NS(status='accepted')
with patch.object(run,'send_command',side_effect=send):
 p.poll();p.command('step');p.command('step')
 assert len(sent)==1 and not p.commands['step'].isEnabled()
 cid=sent[0]['command_id']
 def ack(id_,status):
  with patch.object(run,'read_events',return_value=NS(items=[{'kind':'command_ack','payload':dict(command_id=id_,status=status)}],next_seq=1)):p.poll()
 ack('unrelated','completed');assert not p.commands['step'].isEnabled()
 ack(cid,'accepted');assert not p.commands['step'].isEnabled()
 ack(cid,'rejected');assert p.commands['step'].isEnabled()
 p.command('step');assert len(sent)==2
 ack(sent[-1]['command_id'],'completed');assert p.commands['step'].isEnabled()
 p.cancel_run();assert not p.commands['step'].isEnabled()or p.stop_requested
p.close()
''',tmp_path)
