from dataclasses import replace
import json,sys,threading,time,os
from pathlib import Path
import pytest
from robot_learning_workbench import run as w
from test_run_claims import request


def claim_without_spawn(tmp_path,monkeypatch):
    class Process:pid=os.getpid()
    with monkeypatch.context() as patch:
        patch.setattr(w.subprocess,'Popen',lambda *a,**kw:Process())
        handle=w.start(request(tmp_path))
    return handle,w.load_worker_request(handle.run_dir)


def test_execute_fixture_and_second_worker_claim_is_rejected(tmp_path,monkeypatch):
    handle,req=claim_without_spawn(tmp_path,monkeypatch);calls=[]
    def runner(plan,*,events,commands):
        calls.append(plan.recipe_sha256);events({'kind':'log','payload':{'level':'info','message':'fixture log'}})
        return w.StageResult('completed')
    result=w.execute(req,_runner=runner)
    assert result.status=='completed' and len(calls)==1
    assert w.read_status(handle.run_dir).status=='completed'
    assert w._read(handle.run_dir/'run.json')['fixture_runner'] is True
    with pytest.raises(w.RunError):w.execute(req,_runner=runner)
    events=w.read_events(handle.run_dir,after_seq=0,limit=2)
    assert len(events.items)==2 and events.next_seq==2
    assert w.read_events(handle.run_dir,after_seq=2).items[-1]['payload']['status']=='completed'


def test_changed_saved_yaml_is_blocked_before_runner(tmp_path,monkeypatch):
    handle,req=claim_without_spawn(tmp_path,monkeypatch);req.request.recipe_path.write_text('changed')
    calls=[];result=w.execute(req,_runner=lambda *a,**kw:calls.append(1))
    assert result.status=='failed' and result.error['code'] in ('INPUT_CHANGED','RECIPE_INVALID') and not calls


def test_command_dedup_unsupported_and_cooperative_cancel(tmp_path,monkeypatch):
    handle,req=claim_without_spawn(tmp_path,monkeypatch);applied=[]
    bad={'command_id':'step1','kind':'step','payload':{'count':1}}
    assert w.send_command(handle,bad).status=='queued'
    cancel={'command_id':'cancel1','kind':'cancel','payload':{'reason':'test'}}
    w.send_command(handle,cancel)
    assert w.send_command(handle,cancel).command_id=='cancel1'
    with pytest.raises(w.RunError):w.send_command(handle,{**cancel,'payload':{'reason':'different'}})
    def runner(plan,*,events,commands):
        rows=commands();applied.extend(c['command_id'] for c in rows)
        assert commands()==()
        events({'kind':'command_ack','payload':{'command_id':'cancel1','status':'completed'}})
        return w.StageResult('cancelled')
    assert w.execute(req,_runner=runner).status=='cancelled'
    assert applied==['cancel1']
    assert w.send_command(handle,bad).status=='rejected'
    assert w.send_command(handle,cancel).status=='completed'


def test_recipe_edit_after_one_read_does_not_override_current_plan(tmp_path,monkeypatch):
    handle,req=claim_without_spawn(tmp_path,monkeypatch)
    def runner(plan,*,events,commands):
        req.request.recipe_path.write_text('new edit for next run')
        assert plan.stage=='train' and plan.recipe_sha256==req.request.expected_recipe_sha256
        return w.StageResult('completed')
    assert w.execute(req,_runner=runner).status=='completed'


def test_preview_is_bounded_snapshot_and_stdout_not_control(tmp_path,monkeypatch):
    handle,req=claim_without_spawn(tmp_path,monkeypatch)
    def runner(plan,*,events,commands):
        for i in range(200):events({'kind':'preview','payload':{'camera':'side','slot':0,'generation':i,'frame_index':i,'time_s':i/30}})
        events({'kind':'status','payload':{'progress':{'frames':200}}})
        return w.StageResult('completed')
    w.execute(req,_runner=runner)
    assert w.read_preview(handle.run_dir)['payload']['generation']==199
    assert len(w.read_events(handle.run_dir,after_seq=0,limit=1000).items)<10

from test_recipe_preparation import scene,dataset,annotation_doc


def wait_for(fn,timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        value=fn()
        if value:return value
        time.sleep(.01)
    pytest.fail('worker did not reach expected state')


def test_real_process_commands_ack_targets_stdout_and_cancel(tmp_path,scene,monkeypatch):
    dataset(tmp_path,scene);doc=annotation_doc(tmp_path)
    modules=Path(__file__).resolve().parents[1]/'task_modules.yaml'
    script=tmp_path/'fixture_worker.py';script.write_text('''import json,sys,time
from pathlib import Path
from robot_learning_workbench.run import execute,load_worker_request,StageResult
request=load_worker_request(Path(sys.argv[1]))
def runner(plan,*,events,commands):
 print('{"kind":"status","payload":{"status":"completed"}}',flush=True)
 plan.output_path.mkdir();applied=[]
 events({'kind':'status','payload':{'progress':{'fixture_ready':True},'episode_id':'episode_a','env_index':0,'tick':7}})
 end=time.monotonic()+6
 while time.monotonic()<end:
  for command in commands():
   applied.append(command['command_id'])
   events({'kind':'command_ack','payload':{'command_id':command['command_id'],'status':'completed','applied_tick':7+len(applied)}})
   if command['kind']=='cancel':
    path=plan.output_path/'fixture-applied.json';path.write_text(json.dumps(applied))
    return StageResult('cancelled',(str(path),))
  time.sleep(.005)
 raise RuntimeError('fixture timeout')
result=execute(request,_runner=runner)
raise SystemExit(0 if result.status=='cancelled' else 1)
''')
    popen=w.subprocess.Popen
    def launch(argv,**kw):
        return popen([argv[0],'-B',str(script),argv[-1]],**kw)
    with monkeypatch.context() as patch:
        patch.setattr(w.subprocess,'Popen',launch)
        handle=w.start(w.StartRequest('real-ipc',doc.path,doc.sha256,'annotation',tmp_path/'annotation',modules,w._sha(modules.read_bytes())))
    wait_for(lambda:w.read_status(handle.run_dir).progress.get('fixture_ready'))
    stale={'command_id':'old','kind':'mark','episode_id':'old_episode','env_index':0,'payload':{'event':'grasp','frame':203}}
    w.send_command(handle,stale)
    step={'command_id':'step','kind':'step','episode_id':'episode_a','env_index':0,'payload':{'count':1}}
    w.send_command(handle,step);w.send_command(handle,step)
    wait_for(lambda:w.send_command(handle,step).status=='completed')
    mark={'command_id':'mark','kind':'mark','episode_id':'episode_a','env_index':0,'payload':{'event':'grasp','frame':203}}
    w.send_command(handle,mark);wait_for(lambda:w.send_command(handle,mark).status=='completed')
    w.send_command(handle,{'command_id':'stop','kind':'cancel','payload':{'reason':'done'}})
    wait_for(lambda:w.read_status(handle.run_dir).status=='cancelled')
    assert json.loads((tmp_path/'annotation/fixture-applied.json').read_text())==['step','mark','stop']
    assert w.send_command(handle,stale).status=='rejected'
    assert w.send_command(handle,step).applied_tick==8
    assert '"status":"completed"' in (handle.run_dir/'stdout.log').read_text()
    events=w.read_events(handle.run_dir,after_seq=0,limit=1000)
    assert not any(e['kind']=='status' and e['payload'].get('status')=='completed' for e in events.items)


def test_invalid_handle_cannot_inject_other_run_command(tmp_path,monkeypatch):
    handle,req=claim_without_spawn(tmp_path,monkeypatch)
    with pytest.raises(w.RunError):w.send_command(replace(handle,run_id='other'),{'command_id':'bad','kind':'cancel','payload':{}})
    assert not list((handle.run_dir/'commands').iterdir())


@pytest.mark.parametrize('event',[
 {'kind':'log','payload':{'level':'info','message':42}},
 {'kind':'status','payload':{'progress':[1,2]}},
 {'kind':'status','payload':{'status':'completed'}},
 {'kind':'preview','payload':{'camera':False,'slot':0,'generation':1,'frame_index':1,'time_s':0.}},
])
def test_invalid_producer_messages_fail_explicitly(tmp_path,monkeypatch,event):
    handle,req=claim_without_spawn(tmp_path,monkeypatch)
    def runner(plan,*,events,commands):events(event);return w.StageResult('completed')
    result=w.execute(req,_runner=runner)
    assert result.status=='failed' and result.error['code']=='PROTOCOL_INVALID'


def test_actual_worker_kill_preserves_episode_and_unresolved_ack(tmp_path,monkeypatch):
    req=request(tmp_path,'kill-probe');script=tmp_path/'kill_fixture.py'
    script.write_text('''import sys,time
from pathlib import Path
import numpy as np
from robot_learning_workbench.run import execute,load_worker_request
from robot_learning_workbench.data.native import NativeRun,load_catalog
from isaaclab.utils.datasets import EpisodeData
import torch
request=load_worker_request(Path(sys.argv[1]))
def runner(plan,*,events,commands):
 with NativeRun(plan.output_path,{'stage':'source'}) as owner:
  segment=owner.segment('saved')
  ep=EpisodeData();ep.data={'actions':torch.zeros((1,7)),'obs':{'q':torch.zeros((1,6))}}
  segment.write_episode(ep,episode_id='saved');segment.commit()
 dataset=load_catalog(plan.output_path)
 events({'kind':'episode_committed','payload':{'dataset_path':str(dataset.root),'dataset_identity':{'dataset_id':dataset.identity.dataset_id,'metadata_sha256':dataset.identity.metadata_sha256},'episode_id':'saved'}})
 events({'kind':'status','payload':{'progress':{'fixture_ready':True}}})
 while True:
  if commands():
   events({'kind':'status','payload':{'progress':{'accepted_no_ack':True}}})
   time.sleep(10)
  time.sleep(.005)
execute(request,_runner=runner)
''')
    original=w.subprocess.Popen;children=[]
    def launch(argv,**kw):
        process=original([argv[0],'-B',str(script),argv[-1]],**kw);children.append(process);return process
    with monkeypatch.context() as patch:
        patch.setattr(w.subprocess,'Popen',launch);handle=w.start(req)
    wait_for(lambda:w.read_status(handle.run_dir).progress.get('fixture_ready'))
    command={'command_id':'pending-cancel','kind':'cancel','payload':{}}
    w.send_command(handle,command);wait_for(lambda:w.read_status(handle.run_dir).progress.get('accepted_no_ack'))
    import os,signal
    identity=w._read(handle.run_dir/'run.json')['worker_identity'];assert identity['pid']==children[0].pid
    os.kill(children[0].pid,signal.SIGKILL)
    wait_for(lambda:w.read_status(handle.run_dir).status=='failed')
    assert w.read_status(handle.run_dir).error['code']=='WORKER_EXITED'
    assert w.send_command(handle,command).status=='accepted'  # not completed, never replayed
    assert w.start(req).run_id==handle.run_id and len(children)==1
    from robot_learning_workbench.data.native import load_catalog
    assert load_catalog(tmp_path/'output').episodes[0].num_frames==1


def test_worker_never_reads_a_command_before_sender_finishes(tmp_path,monkeypatch):
    handle,req=claim_without_spawn(tmp_path,monkeypatch);started=threading.Event();finish=threading.Event();original=w._exclusive;result=[];errors=[]
    def slow(path,value):
        if path.parent.name!='commands':return original(path,value)
        with path.open('xb') as stream:
            started.set();assert finish.wait(2);stream.write(w._bytes(value));stream.flush()
    def send():
        try:w.send_command(handle,{'command_id':'one','kind':'cancel','payload':{}})
        except Exception as ex:errors.append(ex)
    def poll():
        try:result.extend(w._poll_commands(handle.run_dir,{'seq':0,'context':{},'seen_commands':set(),'command_seq':0},'train'))
        except Exception as ex:errors.append(ex)
    monkeypatch.setattr(w,'_exclusive',slow);sender=threading.Thread(target=send);sender.start();assert started.wait(2)
    reader=threading.Thread(target=poll);reader.start();time.sleep(.02);assert not result and not errors
    finish.set();sender.join(2);reader.join(2)
    assert not errors and [row['command_id'] for row in result]==['one']


def test_full_prepared_identity_change_is_rejected_before_runner(tmp_path,monkeypatch):
    handle,req=claim_without_spawn(tmp_path,monkeypatch)
    from robot_learning_workbench.cli import prepare
    plan=prepare(req.request.recipe_path)
    # A newly persisted request may pin the preceding validation result.
    changed=replace(req,request=replace(req.request,expected_prepared_sha256=plan.sha256))
    w._atomic(handle.run_dir/'worker_request.json',w._plain(changed))
    claim=w._read(Path(w._read(handle.run_dir/'run.json')['claim_path']));claim['payload_sha256']=w._sha(w._bytes(changed.request));claim['worker_request_sha256']=w._sha((handle.run_dir/'worker_request.json').read_bytes());w._atomic(Path(w._read(handle.run_dir/'run.json')['claim_path']),claim)
    (tmp_path/'train.json').write_text('{"policy":{"type":"smolvla"}}')
    called=[];result=w.execute(changed,_runner=lambda *a,**kw:called.append(1))
    assert result.status=='failed' and result.error['code']=='INPUT_CHANGED' and not called


def test_control_payload_bounds_and_duplicate_json_keys(tmp_path,monkeypatch):
    handle,req=claim_without_spawn(tmp_path,monkeypatch)
    with pytest.raises(w.RunError):w.send_command(handle,{'command_id':'large','kind':'cancel','payload':{'reason':'x'*70000}})
    assert not list((handle.run_dir/'commands').iterdir())
    with pytest.raises(ValueError):w._decode('{"count":1,"count":2}')


@pytest.mark.parametrize('result',[None,w.StageResult('completed',output_refs=''),w.StageResult('completed',completed_episodes=True)])
def test_invalid_stage_return_is_not_success(tmp_path,monkeypatch,result):
    handle,req=claim_without_spawn(tmp_path,monkeypatch)
    value=w.execute(req,_runner=lambda *a,**kw:result)
    assert value.status=='failed' and value.error['code']=='STAGE_RESULT_INVALID'


def test_preview_accepts_full_resolution_env_timing_metadata(tmp_path):
    from robot_learning_workbench.run import _stage_event
    state={'preview_seq':0};value={'camera':'side','slot':1,'generation':1,'frame_index':0,'time_s':0.,'env_index':3,'shape':[480,640,3],'published_monotonic_ns':4}
    _stage_event(tmp_path,state,{'kind':'preview','payload':value})
    assert state['preview']['payload']['env_index']==3
