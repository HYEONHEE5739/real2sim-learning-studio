"""Durable R03 approval dispatch -> existing one-shot memory-device guard."""
from pathlib import Path
from types import SimpleNamespace as NS
import inspect
import pytest
from robot_learning_workbench import run as worker


def _ipc(tmp_path,stage):
    root=tmp_path/'ipc';root.mkdir();(root/'commands').mkdir();(root/'acks').mkdir()
    worker._status(root,'running','running',run_id='ipc',request_id='request',stage=stage,worker_identity=worker._worker_identity())
    return worker.RunHandle('ipc','request',root),{'seq':0,'context':{},'seen_commands':set(),'command_seq':0}


def _poll(handle,state,stage,plan):
    # The baseline has no prepared-plan input; reproduce its actual allowlist
    # rejection rather than failing only on a newly proposed keyword.
    kwargs={'plan':plan}if 'plan'in inspect.signature(worker._poll_commands).parameters else{}
    return worker._poll_commands(handle.run_dir,state,stage,**kwargs)


@pytest.mark.parametrize('case',['approve','wrong_proposal','cancel_first','cancel_last','timeout'])
def test_one_shot_memory_gripper_consumes_r03_approval_without_expanding_arm_authority(tmp_path,monkeypatch,case):
    from test_gripper_only import follower
    from robot_learning_workbench.robot import live,configuration
    from robot_learning_workbench import recipe
    from robot_learning_workbench.robot.calibration import fingerprint
    device,sdk,trace,raw=follower(tmp_path);entry=device.profile['joints']['gripper']
    target=(raw+1-entry['anchor_raw'])*entry['rad_per_count']+entry['reference_angle_rad']
    model=tmp_path/'model.urdf';model.write_text('<robot>'+''.join('<joint name="'+n+'" type="revolute"><origin xyz="0 0 0"/><parent link="p"/><child link="c"/><axis xyz="0 0 1"/><limit lower="'+str(v['limits'][0])+'" upper="'+str(v['limits'][1])+'"/></joint>'for n,v in device.profile['joints'].items())+'</robot>')
    plan=NS(stage='teleoperation',scene=NS(files=[NS(path=model.name,sha256=device.profile['urdf_sha256'])],root=tmp_path),
        input_documents={'device_profile':{'command_calibration_id':'explicit'}},output_path=tmp_path/'output',
        effective_settings={'execution':{'mode':'gripper_once','gripper_target_rad':target,'max_gripper_delta_raw':1}})
    monkeypatch.setattr(live,'open_inputs',lambda _:(device,{}))
    monkeypatch.setattr(configuration,'bind_gripper_command',lambda *a:{'scope':'explicit fake command binding'})
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda _:None)
    handle,state=_ipc(tmp_path,'teleoperation');queued=False;polled=0
    if case=='timeout':
        ticks=iter(range(0,1000,31))
        monkeypatch.setattr(live.time,'monotonic',lambda:next(ticks))
    def events(event):
        nonlocal queued
        worker._stage_event(handle.run_dir,state,event)
        proposal=event.get('payload',{}).get('progress',{}).get('gripper_proposal')
        if proposal is not None and not queued and case!='timeout':
            queued=True
            approval={'command_id':'approve','kind':'gripper_approve','payload':{'proposal_sha256':'0'*64 if case=='wrong_proposal'else fingerprint(proposal),
                'target_raw':proposal['target_raw'],'supervised':True,'clear':True,'stop_ready':True}}
            cancel={'command_id':'cancel','kind':'cancel','payload':{}}
            commands=[cancel,approval]if case=='cancel_first'else[approval,cancel]if case=='cancel_last'else[approval]
            for command in commands:worker.send_command(handle,command)
    def commands():
        nonlocal polled
        polled+=1
        if polled==2:worker.send_command(handle,{'command_id':'cancel','kind':'cancel','payload':{}})
        assert polled<4,'Fake approval test did not terminate'
        return _poll(handle,state,'teleoperation',plan)
    result=live.run(plan,events=events,commands=commands)
    writes=[row for row in trace if isinstance(row,tuple)and row[0]=='write_one']
    assert len(writes)==int(case=='approve')
    assert result.status==('completed'if case=='approve'else'cancelled')
    if case=='timeout':
        assert result.attempt_summary['status']=='APPROVAL_TIMEOUT'and not queued and not polled
        return
    ack=worker.send_command(handle,{'command_id':'approve','kind':'gripper_approve','payload':worker._read(handle.run_dir/'commands/approve.json')['payload']['payload']})
    assert ack.status==('completed'if case=='approve'else'rejected')
    assert result.attempt_summary['arm_commands']==0


@pytest.mark.parametrize('mode,enabled,capability',[('observe_only',False,True),('fake_all',False,True),('gripper_once',True,True),('gripper_once',False,False)])
def test_other_prepared_modes_and_missing_command_capability_keep_approval_blocked(tmp_path,mode,enabled,capability):
    handle,state=_ipc(tmp_path,'real_evaluation')
    plan=NS(stage='real_evaluation',scene=NS(),input_documents={'device_profile':{'command_calibration_id':'explicit'}if capability else{}},
        effective_settings={'execution':{'mode':mode,'enable_motion':enabled,'max_gripper_delta_raw':1}})
    command={'command_id':'approve','kind':'gripper_approve','payload':{'proposal_sha256':'0'*64,'target_raw':1,'supervised':True,'clear':True,'stop_ready':True}}
    worker.send_command(handle,command)
    assert not _poll(handle,state,'real_evaluation',plan)
    assert worker.send_command(handle,command).status=='rejected'
