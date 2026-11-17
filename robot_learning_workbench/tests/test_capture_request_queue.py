"""Session request-time observations must not wait for the previous disk job."""
from concurrent.futures import Future
import time
import pytest
from test_capture_save_continuity import active_session


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
def test_two_capture_clicks_are_observed_before_the_first_save_finishes(tmp_path,kind,monkeypatch):
    with active_session(tmp_path,kind)as(session,events,_):
        for camera in session.cameras.values():camera.start()
        deadline=time.monotonic()+2
        while any(camera.nearest()is None for camera in session.cameras.values()):
            assert time.monotonic()<deadline
            time.sleep(.002)
        original=session.writer.submit;held=[]
        def slow_save(*args,**kwargs):
            future=Future();held.append(future);return future
        monkeypatch.setattr(session.writer,'submit',slow_save)
        try:
            for index in range(2):
                time.sleep(.04)
                session.dispatch([{'kind':'session_snapshot','command_id':'click_'+str(index),'payload':{'requested_ns':time.monotonic_ns()}}])
            accepted=[e['payload']['command_id']for e in events if e['kind']=='command_ack'and e['payload']['status']=='accepted']
            assert accepted==['click_0','click_1'],'The next click was blocked by saving or the stable-pose wait'
            assert len(held)==2 and not any(f.done()for f in held)
            assert session.teleoperation.active
        finally:
            for future in held:future.set_exception(OSError('Controlled test writer shutdown'))
            monkeypatch.setattr(session.writer,'submit',original)


def test_moving_observation_can_be_archived_but_is_never_calibration_eligible(tmp_path):
    import json
    from pathlib import Path
    import numpy as np
    from robot_learning_workbench.robot.capture import snapshot_state,prepare_snapshot
    from real2sim_builder.capture import load_session
    with active_session(tmp_path,'scene_prepare')as(session,events,pending):
        session.control.stop();follower=session.devices['follower'];native,interval=follower.read();t=interval['end']['monotonic_ns']
        history=[dict(timestamp_ns=t-30_000_000,native=native,raw=dict(follower.last_raw),feedback_interval=interval),
                 dict(timestamp_ns=t,native=native,raw=dict(follower.last_raw),feedback_interval=interval)]
        packets={n:dict(read_start={'monotonic_ns':t-2_000_000},read_end={'monotonic_ns':t-1_000_000},sequence=2)for n in('side','wrist')}
        state=snapshot_state(follower,history,packets,{'stable':False,'reason':'motion_or_sampling_gap'})
        state.update(capture_policy='observation',captured_host_ns=t)
        raw={n:np.full((480,640,3),37,np.uint8)for n in('real_side','real_wrist')}
        archived=session.store.prepare('moving',state,raw,now_ns=t)
        manifest,samples,_=load_session(archived['staging'])
        assert manifest['capture_policy']=='observation'
        assert samples[0]['quality']['eligible_for_calibration']is False
        assert all(not i['eligible']for i in samples[0]['images'])
        measured=json.loads((Path(archived['staging'])/'state.json').read_text())
        assert measured['real_stability']['stable']is False


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
def test_capture_queue_is_bounded_and_full_is_explicit_without_stopping_teleop(tmp_path,kind,monkeypatch):
    with active_session(tmp_path,kind)as(session,events,_):
        for camera in session.cameras.values():camera.start()
        time.sleep(.06);held=[];original=session.writer.submit
        def slow(*args,**kwargs):
            future=Future();held.append(future);return future
        monkeypatch.setattr(session.writer,'submit',slow)
        sequence=session.teleoperation.sequence
        try:
            for index in range(5):
                time.sleep(.04)
                session.dispatch([dict(kind='session_snapshot',command_id='burst_'+str(index),payload={'requested_ns':time.monotonic_ns()})])
            receipts=[e['payload']for e in events if e['kind']=='command_ack']
            assert [r['command_id']for r in receipts if r['status']=='accepted']==['burst_'+str(i)for i in range(4)]
            assert any(r['command_id']=='burst_4'and r['status']=='rejected'and 'queue full'in r['reason']for r in receipts)
            assert len(held)==len(session.capture_queue.jobs)==4
            assert session.teleoperation.active and session.teleoperation.sequence>sequence+2
            assert session.state=='TELEOP_ACTIVE'
        finally:
            for future in held:future.set_exception(OSError('Test queue disposal'))
            monkeypatch.setattr(session.writer,'submit',original)


def test_request_uses_the_recorded_instant_and_never_a_later_frame(tmp_path,monkeypatch):
    from robot_learning_workbench.robot.capture import freeze_capture
    import numpy as np
    with active_session(tmp_path,'scene_prepare')as(session,events,_):
        session.control.stop();follower=session.devices['follower'];native,interval=follower.read();t=interval['end']['monotonic_ns']
        session.history.clear()
        session.history.extend(dict(timestamp_ns=t-offset,native=native,raw=dict(follower.last_raw),feedback_interval=interval)for offset in(30_000_000,0))
        for camera in session.cameras.values():
            for number,stamp,color in[(1,t-2_000_000,30),(2,t+20_000_000,200)]:
                camera.frames.append(dict(sequence=number,read_start={'monotonic_ns':stamp-1_000_000},read_end={'monotonic_ns':stamp},rgb=np.full((480,640,3),color,np.uint8)))
        monkeypatch.setattr(session,'read_observation',lambda:None);time.sleep(.03)
        command=dict(command_id='instant',payload={'requested_ns':t})
        state,images,sequences=freeze_capture(session,command,{})
        assert state['captured_host_ns']==state['capture_request']['requested_ns']==t
        assert sequences==dict(side=1,wrist=1)
        assert all(np.all(rgb==30)for rgb in images.values())
        assert all(row['read_end']['monotonic_ns']<=t for row in state['timestamps']['real_cameras'].values())
        with pytest.raises(ValueError,match='request window'):freeze_capture(session,dict(command_id='late',payload={'requested_ns':t-2_000_000_000}),{})


def test_request_timestamp_and_nonterminal_receipt_travel_through_actual_r03(tmp_path):
    import json
    from robot_learning_workbench.run import RunHandle,send_command,_poll_commands,_stage_event,_command
    root=tmp_path/'run';root.mkdir()
    for name in('commands','acks'):(root/name).mkdir()
    (root/'run.json').write_text(json.dumps(dict(request_id='req',stage='capture_session',status='running',phase='running')))
    handle=RunHandle('run','req',root);state=dict(seq=0,seen_commands=set(),command_seq=0,context={})
    command=dict(command_id='click',kind='session_snapshot',payload={'requested_ns':time.monotonic_ns(),'policy':'observation'})
    assert send_command(handle,command).status=='queued'
    assert _poll_commands(root,state,'capture_session')==(command,)
    _stage_event(root,state,dict(kind='command_ack',payload=dict(command_id='click',status='accepted')))
    assert json.loads((root/'acks/click.json').read_text())['status']=='accepted'
    _stage_event(root,state,dict(kind='command_ack',payload=dict(command_id='click',status='completed')))
    assert json.loads((root/'acks/click.json').read_text())['status']=='completed'
    for bad in[{'requested_ns':True},{'requested_ns':-1},{'policy':'made_up'}]:
        with pytest.raises(Exception):_command(dict(command_id='bad',kind='session_snapshot',payload=bad))


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
def test_actual_freshness_failure_during_queued_capture_stays_stopped(tmp_path,kind,monkeypatch):
    with active_session(tmp_path,kind)as(session,events,pending):
        from test_capture_save_continuity import queued_writer
        held=Future();command=dict(kind='session_snapshot',command_id='slow',payload={})
        job=queued_writer(session,held,'finish',pending,command)
        control=session.teleoperation;target=control._target
        def slow_target():time.sleep(.12);return target()
        monkeypatch.setattr(control,'_target',slow_target)
        deadline=time.monotonic()+2
        while control.active:
            assert time.monotonic()<deadline
            time.sleep(.01)
        (session.record_control if kind=='scene_prepare'else session.collect_control)()
        assert session.state=='OBSERVING'
        assert 'Stale feedback'in control.last_attempt['error']
        assert control.last_attempt['timing_ms']['feedback_age']>100
        held.set_exception(OSError('Capture test failed after safety stop'))
        (session.poll_capture if kind=='scene_prepare'else session.poll_save)()
        assert not control.active and session.state=='OBSERVING'
        assert session.capture_queue.failed[job['id']]['pending']is pending


def test_unbound_registration_keeps_each_camera_aligned_q_for_moving_capture(tmp_path):
    import numpy as np
    from robot_learning_workbench.robot.capture import snapshot_state
    from robot_learning_workbench.robot.calibration import native_from_raw
    from real2sim_builder.capture import load_session
    with active_session(tmp_path,'scene_prepare')as(session,events,_):
        session.control.stop();f=session.devices['follower'];_,interval=f.read();t=interval['end']['monotonic_ns'];history=[]
        for offset,delta in[(80_000_000,0),(0,20)]:
            raw=dict(f.last_raw);raw['shoulder_pan']+=delta
            native={n:native_from_raw(value,f.motor_specs[n])for n,value in raw.items()}
            history.append(dict(timestamp_ns=t-offset,native=native,raw=raw,feedback_interval=interval))
        packets={n:dict(sequence=2,read_start={'monotonic_ns':t-41_000_000},read_end={'monotonic_ns':t-40_000_000})for n in('side','wrist')}
        state=snapshot_state(f,history,packets,{'stable':False,'reason':'motion_or_sampling_gap'})
        state.update(captured_host_ns=t,capture_policy='observation')
        pending=session.store.prepare('moving_interpolation',state,{n:np.full((480,640,3),37,np.uint8)for n in('real_side','real_wrist')},now_ns=t)
        result=session.store.finish(pending);_,samples,_=load_session(result['path'])
        expected=samples[0]['images'][0]['q_measured']
        assert expected!=samples[0]['q_measured']
        assert all(row['q_measured']==expected and row['eligible']is False for row in session.project.evidence['images'])


def test_writer_submission_failure_after_sim_result_releases_queue_and_keeps_raw(tmp_path,monkeypatch):
    from pathlib import Path
    from test_capture_save_continuity import queued_writer
    with active_session(tmp_path,'real_sim')as(session,events,pending):
        job=queued_writer(session,None,'finish',pending,dict(kind='session_snapshot',command_id='submitted',payload={}))
        job['phase']='SIM_PAIR';session.capture_queue.rendering=job['id']
        def refused(*a,**k):raise OSError('Writer refused a postprocess job')
        monkeypatch.setattr(session.writer,'submit',refused)
        session.capture_queue.rendered({'id':job['id']})
        assert not session.capture_queue.jobs and session.capture_queue.rendering is None
        assert session.capture_queue.failed[job['id']]['pending']is pending
        assert Path(pending['staging'],'COMPLETE').is_file()
        assert session.teleoperation.active
