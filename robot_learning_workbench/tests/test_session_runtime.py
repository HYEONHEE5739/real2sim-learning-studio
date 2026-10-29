import json,time
from pathlib import Path
import pytest
from test_capture_session_protocol import session_recipe
from robot_learning_workbench.recipe import read_recipe,prepare_recipe
from robot_learning_workbench.robot.devices import close_devices


def test_persistent_session_connects_once_and_capture_commands_leave_it_observing(tmp_path):
    from robot_learning_workbench.robot.session import HardwareSession
    from robot_learning_workbench.robot.session_devices import construct
    from test_precision_calibration import OLD
    path,project,spec=session_recipe(tmp_path);spec['inputs']['source_robot_model']=str(OLD)
    import yaml
    path.write_text(yaml.safe_dump(spec));plan=prepare_recipe(read_recipe(path));devices,cameras,bounds=construct(plan)
    events=[];s=HardwareSession(plan,devices,cameras,bounds,events=events.append)
    try:
        s.connect();assert s.state=='OBSERVING'and not s.teleoperation.active
        deadline=time.monotonic()+5
        while not s.capture_ready():
            s.observe();time.sleep(.035)
            assert time.monotonic()<deadline
        for name in('one','two'):
            requested=time.monotonic_ns();s.command({'kind':'session_snapshot','command_id':name,'payload':{}})
            assert s.state=='CAPTURING'
            while s.state=='CAPTURING':
                s.observe();s.poll_capture();time.sleep(.035)
            assert s.state=='OBSERVING'
            assert s.snapshots[-1]['timestamp_ns']>=requested
            if name=='one':time.sleep(.05);s.observe()
        assert len(project.evidence['capture_sessions'])==2 and all(e['status']=='SAVED'for e in s.snapshots)
        assert all(not row['calibration_approved']for row in s.snapshots)
        s.command({'kind':'session_disconnect','command_id':'bye','payload':{}})
        assert s.state=='DISCONNECTED'and s.terminal and not s.teleoperation.active
        assert all(not d.bus.is_connected for d in devices.values())
    finally:s.close()


def test_session_cancel_in_same_batch_precedes_snapshot_or_motion(tmp_path):
    from robot_learning_workbench.robot.session import HardwareSession
    from robot_learning_workbench.robot.session_devices import construct
    from test_precision_calibration import OLD
    path,project,spec=session_recipe(tmp_path);spec['inputs']['source_robot_model']=str(OLD)
    import yaml
    path.write_text(yaml.safe_dump(spec));plan=prepare_recipe(read_recipe(path));devices,cameras,bounds=construct(plan)
    events=[];s=HardwareSession(plan,devices,cameras,bounds,events=events.append)
    try:
        s.connect();s.dispatch([{'kind':'session_snapshot','command_id':'bad','payload':{}},{'kind':'cancel','command_id':'stop','payload':{}}])
        assert s.terminal and not s.snapshots and s.cancelled
        assert any(e['kind']=='command_ack'and e['payload']['command_id']=='bad'and e['payload']['status']=='rejected'for e in events)
    finally:s.close()


def test_disconnect_drains_one_started_snapshot_after_stopping_devices(tmp_path):
    from robot_learning_workbench.robot.session import HardwareSession
    from robot_learning_workbench.robot.session_devices import construct
    from test_precision_calibration import OLD
    import yaml
    path,project,spec=session_recipe(tmp_path);spec['inputs']['source_robot_model']=str(OLD);path.write_text(yaml.safe_dump(spec))
    plan=prepare_recipe(read_recipe(path));devices,cameras,bounds=construct(plan);events=[];s=HardwareSession(plan,devices,cameras,bounds,events=events.append)
    try:
        s.connect();deadline=time.monotonic()+5
        while not s.capture_ready():
            s.observe();time.sleep(.035);assert time.monotonic()<deadline
        s.command({'kind':'session_snapshot','command_id':'one','payload':{}});s.close()
        assert s.state=='DISCONNECTED'and len(project.evidence['capture_sessions'])==1
        assert all(not d.bus.is_connected for d in devices.values())
    finally:s.close()


def test_fake_supervised_cycle_records_native_targets_and_next_feedback(tmp_path):
    from robot_learning_workbench.robot.session import HardwareSession
    from robot_learning_workbench.robot.session_devices import construct
    from robot_learning_workbench.data.native import load_catalog,read_array
    from test_precision_calibration import OLD
    from test_supervised_session import approval
    import yaml
    path,project,spec=session_recipe(tmp_path);spec['inputs']['source_robot_model']=str(OLD);path.write_text(yaml.safe_dump(spec));plan=prepare_recipe(read_recipe(path))
    devices,cameras,bounds=construct(plan);events=[];s=HardwareSession(plan,devices,cameras,bounds,events=events.append)
    try:
        s.connect();s.command({'kind':'teleop_prepare','command_id':'proposal','payload':{}})
        assert s.teleoperation.proposal is not None
        s.command({'kind':'teleop_start','command_id':'start','payload':approval(s.teleoperation.proposal)})
        assert s.teleoperation.active
        for _ in range(4):s.observe();time.sleep(.035)
        s.command({'kind':'teleop_stop','command_id':'stop','payload':{}});assert not s.teleoperation.active
    finally:s.close()
    catalog=load_catalog(plan.output_path/'teleoperation');assert len(catalog.episodes)==1
    assert read_array(catalog.episodes[0],'joint_targets').shape==(3,6)
    assert read_array(catalog.episodes[0],'states/joint_pos').shape==(3,6)
    assert catalog.execution['hardware_connected']is False and catalog.execution['training_ready']is False


def test_disconnect_cleanup_failure_is_not_normal_worker_completion(tmp_path,monkeypatch):
    from robot_learning_workbench.robot.session import HardwareSession
    from robot_learning_workbench.robot.session_devices import construct
    from test_precision_calibration import OLD
    import yaml
    path,project,spec=session_recipe(tmp_path);spec['inputs']['source_robot_model']=str(OLD);path.write_text(yaml.safe_dump(spec))
    plan=prepare_recipe(read_recipe(path));devices,cameras,bounds=construct(plan);s=HardwareSession(plan,devices,cameras,bounds,events=lambda e:None)
    s.connect();real=devices['leader'].close
    def fail():real();raise RuntimeError('cleanup failed')
    monkeypatch.setattr(devices['leader'],'close',fail)
    with pytest.raises(Exception,match='cleanup failed'):s.command({'kind':'session_disconnect','command_id':'badclose','payload':{}})
    assert s.state=='FAILED'and s.terminal


def test_retry_cannot_replace_pending_snapshot_command_during_save(tmp_path):
    from concurrent.futures import Future
    from robot_learning_workbench.robot.session import HardwareSession
    from robot_learning_workbench.robot.session_devices import construct
    from test_precision_calibration import OLD
    import yaml
    path,project,spec=session_recipe(tmp_path);spec['inputs']['source_robot_model']=str(OLD);path.write_text(yaml.safe_dump(spec))
    plan=prepare_recipe(read_recipe(path));devices,cameras,bounds=construct(plan);events=[];s=HardwareSession(plan,devices,cameras,bounds,events=events.append)
    future=Future();s.pending={'id':'shot'};s.pending_command={'command_id':'original'};s.saving=future;s.save_phase='finish'
    s.command({'kind':'session_import','command_id':'retry','payload':{'snapshot_id':'shot'}})
    assert s.saving is future and s.pending_command['command_id']=='original'
    assert events[-2]['payload']['status']=='rejected'
    s.saving=None;s.close()


def test_pair_render_in_flight_cannot_be_recovered_as_unpaired_capture(tmp_path):
    from robot_learning_workbench.robot.session import HardwareSession
    from robot_learning_workbench.robot.session_devices import construct
    from test_precision_calibration import OLD
    import yaml
    path,project,spec=session_recipe(tmp_path);spec['inputs']['source_robot_model']=str(OLD);path.write_text(yaml.safe_dump(spec))
    plan=prepare_recipe(read_recipe(path));d,c,b=construct(plan);events=[];s=HardwareSession(plan,d,c,b,events=events.append)
    try:
        s.pending={'id':'pair_pending'};s.pending_command={'command_id':'original'};s.renderer=object()
        s.command({'kind':'session_import','command_id':'retry','payload':{'snapshot_id':'pair_pending'}})
        assert s.saving is None and s.pending_command['command_id']=='original'
        assert any(e['kind']=='command_ack'and e['payload']['status']=='rejected'for e in events)
    finally:s.renderer=None;s.pending_command=None;s.close()
