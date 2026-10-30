"""Camera/render/storage waits must not suspend the motor control cadence."""
import time,yaml
from test_capture_session_protocol import session_recipe
from test_precision_calibration import OLD
from test_supervised_session import approval
from robot_learning_workbench.recipe import read_recipe,prepare_recipe
from robot_learning_workbench.robot.session_devices import construct
from robot_learning_workbench.robot.session import HardwareSession
from robot_learning_workbench.robot.calibration import JOINTS,raw_from_native


def test_capture_observation_delay_does_not_suspend_approved_leader_control(tmp_path):
    path,_,data=session_recipe(tmp_path);data['inputs']['source_robot_model']=str(OLD);path.write_text(yaml.safe_dump(data));plan=prepare_recipe(read_recipe(path));devices,cameras,bounds=construct(plan);s=HardwareSession(plan,devices,cameras,bounds,events=lambda e:None)
    try:
        s.connect();s.command({'kind':'teleop_prepare','command_id':'proposal','payload':{}});s.command({'kind':'teleop_start','command_id':'start','payload':approval(s.teleoperation.proposal)});assert s.teleoperation.active
        follower=devices['follower'];native,_=follower.read();before=follower.precision_mapper.calibrated_to_urdf(native);target=before.copy();target['shoulder_pan']+=.03
        leader=devices['leader'];native=leader.precision_mapper.urdf_to_calibrated(target);raw={n:round(raw_from_native(native[n],leader.motor_specs[n]))for n in JOINTS};read=leader.bus.sync_read
        leader.bus.sync_read=lambda name,**kw:raw.copy()if name=='Present_Position'else read(name,**kw)
        # No Session.observe calls while Camera/Pair/preview publication is busy.
        time.sleep(.28)
        measured,_=follower.read();after=follower.precision_mapper.calibrated_to_urdf(measured)
        assert after['shoulder_pan']-before['shoulder_pan']>.02,'Leader control stalled behind the observation loop'
        assert s.teleoperation.active and s.teleoperation.sequence>=3
        s.command({'kind':'teleop_stop','command_id':'stop','payload':{}});count=s.teleoperation.sequence;time.sleep(.08);assert s.teleoperation.sequence==count
    finally:s.close()


def test_stop_during_leader_read_blocks_goal_before_transmission(tmp_path):
    import threading
    from test_supervised_session import controller
    from robot_learning_workbench.robot.teleop_loop import TeleoperationLoop
    c,l,f,_,trace,_=controller(tmp_path);loop=TeleoperationLoop(c);entered=threading.Event();release=threading.Event();read=l.read
    def blocked():
        if threading.current_thread().name=='leader-follower-control':entered.set();assert release.wait(1)
        return read()
    l.read=blocked
    try:
        proposal=loop.prepare({});loop.start(approval(proposal));assert entered.wait(1)
        loop.stopped.set();release.set();loop.stop()
        assert not c.active and 'send'not in trace
    finally:release.set();loop.stop();l.close();f.close()


def test_undrained_command_record_queue_stops_without_silent_loss(tmp_path):
    from test_supervised_session import controller
    from robot_learning_workbench.robot.teleop_loop import TeleoperationLoop
    c,l,f,_,trace,_=controller(tmp_path);loop=TeleoperationLoop(c)
    try:
        proposal=loop.prepare({});loop.rows.extend([{'preserved':True}for _ in range(300)]);loop.start(approval(proposal))
        deadline=time.monotonic()+1
        while loop.thread.is_alive():time.sleep(.01);assert time.monotonic()<deadline
        from types import SimpleNamespace
        rows=[];error=loop.record_to(SimpleNamespace(append=rows.append));assert len(rows)==300 and 'queue full'in error and not c.active and 'send'not in trace
    finally:loop.stop();l.close();f.close()


import pytest
@pytest.mark.parametrize('kind',['capture','real_sim'])
def test_control_record_failure_during_close_still_closes_all_owned_resources(tmp_path,kind):
    from types import SimpleNamespace
    if kind=='capture':
        path,_,data=session_recipe(tmp_path);data['inputs']['source_robot_model']=str(OLD);path.write_text(yaml.safe_dump(data));plan=prepare_recipe(read_recipe(path));devices,cameras,bounds=construct(plan);s=HardwareSession(plan,devices,cameras,bounds,events=lambda e:None)
    else:
        from test_leader_teleop_workflow import configured_scene
        from robot_learning_workbench.robot.real_sim import RealSimSession
        path,_,data,config=configured_scene(tmp_path);data['inputs'].update({k:config['inputs'][k]for k in('leader_device_profile','leader_calibration_profile')});data['execution']=config['execution'];path.write_text(yaml.safe_dump(data));plan=prepare_recipe(read_recipe(path));devices,cameras,_=construct(plan);s=RealSimSession(plan,devices,cameras,events=lambda e:None)
    trace=[]
    for d in devices.values():d.connect()
    for c in cameras.values():c.start()
    if kind=='real_sim':s.renderer=SimpleNamespace(close=lambda:trace.append('renderer_closed'))
    def fail(row):raise RuntimeError('injected control recorder write failure')
    s.recorder=SimpleNamespace(append=fail,close=lambda:trace.append('recorder_closed'));s.control.rows.append({'recorded':False})
    try:
        with pytest.raises(Exception,match='recorder write failure'):s.record_control()
        with pytest.raises(Exception,match='recorder write failure'):s.close()
        assert s.terminal and s.state=='FAILED'
        assert len(s.control.rows)==1,'Unwritten control record must remain visible after failure'
        assert all(not d._connected for d in devices.values())
        assert 'recorder_closed'in trace
        if kind=='real_sim':assert 'renderer_closed'in trace
    finally:
        s.control.rows.clear();s.close()


@pytest.mark.parametrize('kind',['capture','real_sim'])
def test_failed_worker_report_preserves_unwritten_control_payloads(tmp_path,monkeypatch,kind):
    import json
    from types import SimpleNamespace
    if kind=='capture':
        import robot_learning_workbench.robot.session as runner
        name='HardwareSession';path,_,data=session_recipe(tmp_path);data['inputs']['source_robot_model']=str(OLD)
    else:
        import robot_learning_workbench.robot.real_sim as runner
        from test_leader_teleop_workflow import configured_scene
        name='RealSimSession';path,_,data,config=configured_scene(tmp_path);data['inputs'].update({k:config['inputs'][k]for k in('leader_device_profile','leader_calibration_profile')});data['execution']=config['execution']
        monkeypatch.setattr(runner,'RenderProcess',lambda *a:SimpleNamespace(close=lambda:None))
    path.write_text(yaml.safe_dump(data));plan=prepare_recipe(read_recipe(path));original=getattr(runner,name)
    row={'requested_model_rad':dict.fromkeys(JOINTS,.1),'applied_model_rad':[.1]*6,'sdk_goal_raw':dict.fromkeys(JOINTS,2048),'timestamp_ns':12345}
    class RecordingFault(original):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            def fail(_):raise RuntimeError('injected terminal recording failure')
            self.recorder=SimpleNamespace(append=fail,close=lambda:None);self.control.rows.append(row)
    monkeypatch.setattr(runner,name,RecordingFault)
    with pytest.raises(Exception,match='terminal recording failure'):runner.run(plan,events=lambda e:None,commands=lambda:[{'command_id':'stop','kind':'cancel','payload':{}}])
    report=json.loads((plan.output_path/'session-report.json').read_text())
    assert report['state']=='FAILED'and report['pending_control_rows']==1
    assert report['unwritten_control_records']==[row],'Worker exit must retain attempted target/SDK/timing diagnostics'
