"""Frame eligibility remains strict; accepting a request does not mean publishing it."""
from types import SimpleNamespace
from collections import deque
from robot_learning_workbench.robot.session import HardwareSession


def session(clock,monkeypatch):
    import robot_learning_workbench.robot.session as module
    s=HardwareSession.__new__(HardwareSession);s.events=[];s.events=s.events.append
    from robot_learning_workbench.robot.supervised import Teleoperation
    s.state='OBSERVING';s.teleoperation=Teleoperation.__new__(Teleoperation);s.teleoperation.active=False;s.teleoperation.hardware=False;s.snapshots=[];s.terminal=False;s.closing=False
    s.pending=s.saving=s.acquiring=None;s.capture_error='';s.history=deque([{'timestamp_ns':clock-30000000},{'timestamp_ns':clock}])
    s.stability=SimpleNamespace(assess=lambda:{'stable':True,'window_start_ns':clock-600000000})
    s.packets={n:{'sequence':1,'read_end':{'monotonic_ns':clock-119000000}}for n in('side','wrist')};s.store=SimpleNamespace(last_sequences={})
    monkeypatch.setattr(module.time,'monotonic_ns',lambda:clock)
    return s


def test_slow_frame_still_rejected_but_request_can_wait_for_next_frame(monkeypatch):
    s=session(1000000000,monkeypatch);s.packets['side']['read_end']['monotonic_ns']=980000000
    assert not s.capture_ready()
    assert '119'in s.capture_error and '100'in s.capture_error and 'Wrist'in s.capture_error
    emitted=[];s.events=emitted.append;s.emit(capture_ready=False,capture_reason=s.capture_error)
    p=emitted[-1]['payload']['progress'];assert p['capture_request_allowed']and not p['capture_pending']
    assert p['teleoperation_available']and not p['teleoperation_reason']
    s.acquiring=object();s.state='CAPTURING';s.emit()
    assert not emitted[-1]['payload']['progress']['capture_request_allowed']
    s.acquiring=None;s.state='OBSERVING';s.packets['wrist']['read_end']['monotonic_ns']=990000000
    assert s.capture_ready()


def test_stale_and_unstable_data_remain_ineligible(monkeypatch):
    s=session(1000000000,monkeypatch);s.packets['side']['read_end']['monotonic_ns']=790000000
    assert not s.capture_ready()and '210'in s.capture_error and '200'in s.capture_error
    s.stability=SimpleNamespace(assess=lambda:{'stable':False,'reason':'warming_up'})
    assert not s.capture_ready()and '0.6'in s.capture_error


def test_unstable_gripper_reports_the_actual_sdk_percentage_point_limit(monkeypatch):
    from robot_learning_workbench.robot.capture import Stability
    from robot_learning_workbench.robot.calibration import JOINTS
    s=session(1000000000,monkeypatch);s.stability=Stability()
    for index in range(31):
        native=dict.fromkeys(JOINTS,0.);native['gripper']=3. if index%2 else 0.
        s.stability.add(100000000+index*30000000,native)
    assert not s.capture_ready()
    assert '그리퍼'in s.capture_error and '3.00'in s.capture_error and '2.00%p'in s.capture_error
