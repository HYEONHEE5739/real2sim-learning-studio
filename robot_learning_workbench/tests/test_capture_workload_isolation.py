"""Capture CPU work must not hold the interpreter serving live motor control.

Only memory SDK devices are used. The bounded C workload deliberately holds
its interpreter's GIL for 160ms, representing a non-yielding native/JSON task.
It is not a claim that one particular real image codec holds the GIL.
"""
import os
from pathlib import Path
import time

import pytest
import numpy as np

from test_capture_save_continuity import active_session
from robot_learning_workbench.robot.supervised import Teleoperation


def cpu_workload(marker):
    """No hardware: a process-local C wait that deliberately retains the GIL."""
    import ctypes
    library=ctypes.PyDLL(None)
    sleep=library.usleep;sleep.argtypes=[ctypes.c_uint];sleep.restype=ctypes.c_int
    Path(marker).write_text(str(os.getpid()))
    sleep(160_000)
    return os.getpid()


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
def test_capture_cpu_work_cannot_expire_fresh_control_feedback(tmp_path,kind):
    with active_session(tmp_path,kind)as(session,events,pending):
        # Release the running memory serial owner before the one-cycle probe;
        # there is never concurrent SDK access. Starting this new controller is
        # explicit test authorization, never production automatic reactivation.
        session.control.stop()
        session.writer.submit(os.getpid).result(timeout=10)
        leader=session.devices['leader'];follower=session.devices['follower']
        control=Teleoperation(leader,follower,model_bounds={n:e['limits']for n,e in follower.profile['joints'].items()},session_id='isolation_probe')
        control.start(command_id='explicit_isolation_probe')
        target=control._target;future=None;marker=tmp_path/'capture-cpu-started'
        def target_during_capture():
            nonlocal future
            # Teleoperation.tick already read fresh Follower feedback here.
            future=session.writer.submit(cpu_workload,str(marker))
            deadline=time.monotonic()+5
            while not marker.exists():
                if future.done():future.result()
                assert time.monotonic()<deadline,'Capture workload did not start'
                time.sleep(.001)
            return target()
        control._target=target_during_capture
        try:
            row=control.tick()
            assert control.active and row['sequence']==1
            assert control.last_attempt['send_begin_ns']-row['feedback_interval']['end']['monotonic_ns']<=100_000_000
        finally:
            control.stop()
            if future is not None:future.result(timeout=10)


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
def test_two_actual_capture_transactions_keep_authorized_control_and_join_writer(tmp_path,kind,monkeypatch):
    """Real writer/Reader/Project, memory serial/cameras; only render is synthetic."""
    import yaml
    from test_capture_session_protocol import session_recipe
    from test_precision_calibration import OLD
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    from robot_learning_workbench.robot.session_devices import construct
    from robot_learning_workbench.robot.session import HardwareSession
    from robot_learning_workbench.robot.real_sim import RealSimSession
    from real2sim_builder.project import Project
    from real2sim_builder.capture import load_session

    class FrozenRender:
        def __init__(self,*_):
            self.last_live={'applied_sim_joint_rad':[0.]*6,'sim_target_joint_rad':[0.]*6,'sim_joint_delta_rad':[0.]*6,
                'physics_steps':0,'simulation_time_s':0.,'state_application':'authored_measured_fk',
                'render_ms':0.,'sim_timestamp':{'monotonic_ns':time.monotonic_ns()}}
            self.capture_id=None;self.closed=False
        def observe(self,q):pass
        def capture(self,pending):self.capture_id=pending['id'];self.q=pending['sample']['q_measured']
        def poll(self):
            if self.capture_id is None:return None
            identifier=self.capture_id;self.capture_id=None
            return dict(id=identifier,images={n:np.full((480,640,3),90,np.uint8)for n in('side','wrist')},
                measured_q_rad=self.q,applied_sim_joint_rad=self.q,scene_identity={'manifest_sha256':'a'*64},
                engine='synthetic',sim_timestamp={'monotonic_ns':time.monotonic_ns()},sim_cameras={},joint_mapping={})
        def release_capture(self,_):return []
        def close(self):self.closed=True

    monkeypatch.setattr('robot_learning_workbench.robot.real_sim.RenderProcess',FrozenRender)
    path,project,spec=session_recipe(tmp_path);spec['inputs']['source_robot_model']=str(OLD);path.write_text(yaml.safe_dump(spec))
    plan=prepare_recipe(read_recipe(path));plan.output_path.mkdir();devices,cameras,bounds=construct(plan);events=[]
    session=(HardwareSession(plan,devices,cameras,bounds,events=events.append)if kind=='scene_prepare'
             else RealSimSession(plan,devices,cameras,events=events.append))
    writer_pid=None
    def cycle():
        session.dispatch([dict(kind='session_heartbeat',command_id='heartbeat',payload={'timestamp_ns':time.monotonic_ns()})])
        session.observe()
        if kind=='scene_prepare':session.poll_capture()
        time.sleep(1/30)
    try:
        session.connect();writer_pid=session.writer.submit(os.getpid).result(timeout=10)
        assert writer_pid!=os.getpid(),'Save work still shares the motor owner interpreter'
        cycle();session.dispatch([dict(kind='teleop_start',command_id='explicit_start',payload={})])
        activation=session.teleoperation.last_activation.copy()
        for index in range(2):
            deadline=time.monotonic()+15
            while not session.snapshots or len(session.snapshots)<=index:
                cycle()
                assert time.monotonic()<deadline,events[-3:]
                assert session.teleoperation.active,events[-3:]
                if (session.state=='TELEOP_ACTIVE'and session.stability.assess().get('stable')
                    and not session.capture_queue.jobs):
                    session.dispatch([dict(kind='session_snapshot',command_id='shot_'+str(index),payload={})])
            assert session.state=='TELEOP_ACTIVE'
            assert session.teleoperation.last_activation==activation
            result=session.snapshots[index];manifest,rows,_=load_session(result['path'])
            assert rows[0]['q_measured']==result['q_measured']
            assert result['paired']==(kind=='real_sim')
            assert manifest['device_source']=='memory'
        evidence=Project(project.root).evidence
        assert len(evidence['capture_sessions'])==2 and len(evidence['images'])==4
        assert not any(e['payload'].get('error')for e in events if e['kind']=='status')
        phases={e['payload'].get('progress',{}).get('capture_update',{}).get('phase')for e in events if e['kind']=='status'}
        assert {'QUEUED','RAW_SAVED','REGISTERING','REGISTERED'}<=phases,'Per-Capture publication phases are not observable'
        assert all(r['capture_elapsed_s']>0 and r['save_timing_ms']['total']>0 for r in session.snapshots)
    finally:session.close()
    assert writer_pid is not None and not Path('/proc',str(writer_pid)).exists(),'Owned save process leaked after Session close'


def test_alignment_decodes_each_feedback_packet_once(monkeypatch):
    """Six joint reads must not repeat all Precision validation six times."""
    from robot_learning_workbench.robot import capture
    from robot_learning_workbench.robot.calibration import JOINTS
    calls=[]
    def observed(mapper,native,**_):calls.append(native);return dict(native)
    monkeypatch.setattr(capture,'observed_positions',observed)
    rows=[dict(timestamp_ns=100+i*10,native=dict.fromkeys(JOINTS,float(i)))for i in range(3)]
    assert capture.align_measured(rows,115,mapper=object())==[1.5]*5+[1.0]
    assert len(calls)==len(rows),'Each feedback packet was redundantly decoded for every joint'


def test_genuine_feedback_deadline_still_stops_and_records_the_failing_cycle(tmp_path):
    from robot_learning_workbench.robot.devices import DeviceError
    with active_session(tmp_path,'real_sim')as(session,events,pending):
        session.control.stop();leader=session.devices['leader'];follower=session.devices['follower']
        control=Teleoperation(leader,follower,model_bounds={n:e['limits']for n,e in follower.profile['joints'].items()},session_id='deadline_probe')
        control.start(command_id='explicit_deadline_probe');target=control._target
        def slow_target():time.sleep(.12);return target()
        control._target=slow_target
        with pytest.raises(DeviceError,match='Stale feedback/Leader command'):control.tick()
        assert not control.active
        assert control.last_attempt is not None,'The actual failed cycle disappeared from the session report'
        assert control.last_attempt['command_sent']is False and control.last_attempt['effect']=='not_applied'
        assert control.last_attempt['timing_ms']['feedback_age']>100
        assert 'Stale feedback'in control.last_attempt['error']


def fail_import_in_save_child(pending):
    """Inject one filesystem failure after rename, inside the real save owner."""
    from real2sim_builder import capture
    from robot_learning_workbench.robot.snapshots import save_snapshot
    original=capture.import_snapshots
    def fail(*args,**kwargs):raise OSError('injected registration failure after rename')
    capture.import_snapshots=fail
    try:return save_snapshot('finish',pending)
    finally:capture.import_snapshots=original


@pytest.mark.parametrize('kind',['scene_prepare','real_sim'])
def test_save_child_failure_reports_renamed_capture_and_preserves_explicit_retry(tmp_path,kind):
    from test_capture_save_continuity import complete_writer
    from real2sim_builder.capture import load_session
    with active_session(tmp_path,kind)as(session,events,pending):
        original=(Path(pending['staging'])/'capture_manifest.yaml').read_bytes()
        future=session.writer.submit(fail_import_in_save_child,pending)
        with pytest.raises(OSError,match='after rename'):future.result(timeout=10)
        command=dict(kind='session_snapshot',command_id='failed_save',payload={})
        complete_writer(session,kind,future,'finish',pending,command)
        assert session.teleoperation.active
        recovered=session.capture_queue.failed[pending['id']]['pending']
        assert recovered and recovered.get('path'),'Renamed capture path was lost across the process boundary'
        sealed=Path(recovered['path'])
        assert not Path(recovered['staging']).exists() and sealed.is_dir()
        assert(sealed/'capture_manifest.yaml').read_bytes()==original
        assert load_session(sealed)[1][0]['q_measured']==pending['sample']['q_measured']
        if kind=='scene_prepare':
            session.dispatch([dict(kind='session_import',command_id='explicit_retry',payload={'snapshot_id':pending['id']})])
            deadline=time.monotonic()+10
            while session.capture_queue.jobs:
                session.dispatch([dict(kind='session_heartbeat',command_id='heartbeat',payload={'timestamp_ns':time.monotonic_ns()})])
                session.poll_capture();session.record_control();time.sleep(.02)
                assert time.monotonic()<deadline
            assert not session.capture_queue.jobs and session.snapshots[-1]['path']==str(sealed)
            assert session.teleoperation.active
