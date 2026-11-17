"""Capture filesystem failures must not revoke an otherwise healthy Teleop session.

Only the memory-device backend is used. RenderProcess is not constructed: these
tests isolate the real session/serial-owner boundary after a writer completes.
"""
from concurrent.futures import Future
from contextlib import contextmanager
from pathlib import Path
import time

import numpy as np
import pytest
import yaml

from test_capture_session_protocol import session_recipe
from test_precision_calibration import OLD
from robot_learning_workbench.recipe import prepare_recipe,read_recipe
from robot_learning_workbench.robot.capture import snapshot_state
from robot_learning_workbench.robot.devices import DeviceError
from robot_learning_workbench.robot.session import HardwareSession
from robot_learning_workbench.robot.real_sim import RealSimSession
from robot_learning_workbench.robot.session_devices import construct


class NoRender:
    """The save-result handler does not need to render or touch a GPU."""
    def close(self):pass


@contextmanager
def active_session(tmp_path,kind):
    path,project,spec=session_recipe(tmp_path)
    spec['inputs']['source_robot_model']=str(OLD)
    path.write_text(yaml.safe_dump(spec))
    plan=prepare_recipe(read_recipe(path));plan.output_path.mkdir()
    devices,cameras,bounds=construct(plan);events=[]
    session=(HardwareSession(plan,devices,cameras,bounds,events=events.append)
             if kind=='scene_prepare'else RealSimSession(plan,devices,cameras,events=events.append))
    # Connect the explicit memory devices only. RealSimSession.connect would
    # spawn a renderer; that separate boundary is intentionally not exercised.
    for device in devices.values():device.connect()
    session.state='OBSERVING'
    if kind=='real_sim':session.renderer=NoRender()
    try:
        # Seal an actual measured-observation-format capture before activation;
        # all observations are synthetic, the SnapshotStore/Reader are real.
        follower=devices['follower'];native,interval=follower.read();t=interval['end']['monotonic_ns']
        history=[dict(timestamp_ns=t-(6-i)*100_000_000,native=native,raw=dict(follower.last_raw),feedback_interval=interval)for i in range(7)]
        packets={n:dict(read_start={'monotonic_ns':t-2_000_000},read_end={'monotonic_ns':t-1_000_000},sequence=1)for n in('side','wrist')}
        state=snapshot_state(follower,history,packets,dict(stable=True,window_start_ns=t-600_000_000,window_end_ns=t))
        pending=session.store.prepare('sealed_observation',state,{n:np.full((480,640,3),37,np.uint8)for n in('real_side','real_wrist')},now_ns=t)
        if kind=='scene_prepare':
            from robot_learning_workbench.robot.telemetry import Recorder
            session.recorder=Recorder(plan,follower)
        session.control.start('explicit_start');session.state='TELEOP_ACTIVE'
        yield session,events,pending
    finally:
        # The completed fault Future has already been consumed by the test.
        session.close()


def queued_writer(session,future,phase,pending,command):
    job=dict(id=pending['id'],command=command,phase='QUEUED'if phase=='prepare'else'REGISTERING',
        pending=pending if phase=='finish'else None,future=future,sample=pending['sample'],
        request=dict(requested_ns=time.monotonic_ns(),clock_domain='host_monotonic_ns'),times={})
    session.capture_queue.jobs[job['id']]=job
    return job


def complete_writer(session,kind,future,phase,pending,command):
    """Deliver a real Future through the shared production save-result queue."""
    job=queued_writer(session,future,phase,pending,command)
    (session.poll_capture if kind=='scene_prepare'else session.poll_save)()
    return job


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
@pytest.mark.parametrize('phase',['prepare','finish'])
def test_capture_io_failure_retains_connection_and_existing_teleop_authorization(tmp_path,kind,phase):
    with active_session(tmp_path,kind)as(session,events,pending):
        sealed=Path(pending['staging']);before={str(p.relative_to(sealed)):p.read_bytes()for p in sealed.rglob('*')if p.is_file()}
        activation=session.teleoperation.last_activation.copy();sequence=session.teleoperation.sequence
        future=Future();future.set_exception(OSError('injected capture disk/import error'))
        command=dict(kind='session_snapshot',command_id='save_failed',payload={})
        complete_writer(session,kind,future,phase,pending,command)

        assert session.teleoperation.active,'A Capture disk error unexpectedly stopped the already-authorized Teleop loop'
        assert not session.terminal and all(d.bus.is_connected for d in session.devices.values())
        assert session.state=='TELEOP_ACTIVE'
        assert session.teleoperation.last_activation==activation
        assert before=={str(p.relative_to(sealed)):p.read_bytes()for p in sealed.rglob('*')if p.is_file()}
        assert session.capture_queue.failed[pending['id']]['pending']is(pending if phase=='finish'else None)
        assert any(e['kind']=='command_ack'and e['payload'].get('command_id')=='save_failed'and e['payload']['status']=='rejected'for e in events)
        # Progress uses the same running owner; no fresh teleop_start or implicit
        # reactivation is permitted after an ordinary save failure.
        deadline=time.monotonic()+.5
        while session.teleoperation.sequence<=sequence:
            time.sleep(.005)
            assert time.monotonic()<deadline


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
def test_capture_device_fault_still_revokes_motion_authorization(tmp_path,kind):
    with active_session(tmp_path,kind)as(session,events,pending):
        future=Future();future.set_exception(DeviceError('device_identity','model/feedback identity invalid',effect='not_applied'))
        command=dict(kind='session_snapshot',command_id='device_failed',payload={})
        complete_writer(session,kind,future,'finish',pending,command)
        assert not session.teleoperation.active
        assert session.state=='OBSERVING'
        assert session.capture_queue.failed[pending['id']]['pending']is pending
        assert Path(pending['staging']).is_dir()


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
def test_stop_precedence_is_preserved_while_a_capture_write_is_pending(tmp_path,kind):
    with active_session(tmp_path,kind)as(session,events,pending):
        queued=dict(kind='session_snapshot',command_id='capture_after_stop',payload={})
        stopped=dict(kind='teleop_stop',command_id='explicit_stop',payload={})
        session.dispatch([queued,stopped])
        assert not session.teleoperation.active
        assert any(e['kind']=='command_ack'and e['payload'].get('command_id')=='capture_after_stop'and e['payload']['status']=='rejected'for e in events)
        assert Path(pending['staging']).is_dir()


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
def test_pending_capture_writer_keeps_the_existing_control_owner_progressing(tmp_path,kind):
    with active_session(tmp_path,kind)as(session,events,pending):
        future=Future()
        command=dict(kind='session_snapshot',command_id='slow_capture',payload={})
        job=queued_writer(session,future,'finish',pending,command)
        poll=session.poll_capture if kind=='scene_prepare'else session.poll_save
        drain=session.record_control if kind=='scene_prepare'else session.collect_control
        sequence=session.teleoperation.sequence;activation=session.teleoperation.last_activation.copy()
        try:
            # A writer that remains pending for many control cycles must not
            # wait() on the session thread or require fresh motion permission.
            for _ in range(8):
                session.dispatch([dict(kind='session_heartbeat',command_id='heartbeat',payload={'timestamp_ns':time.monotonic_ns()})])
                poll();drain();time.sleep(.035)
            assert session.teleoperation.active
            assert session.teleoperation.sequence>sequence+2
            assert session.teleoperation.last_activation==activation
            assert not session.terminal and session.capture_queue.jobs[pending['id']]['pending']is pending
        finally:
            # The fake boundary owns no filesystem transaction to complete.
            session.capture_queue.jobs.pop(job['id'])
