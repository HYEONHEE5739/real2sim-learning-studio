"""Hardware paths must preserve arm Goal/Torque registers, including cleanup."""
import pytest
from test_robot_lifecycle import make
from robot_learning_workbench.robot.devices import DeviceError


@pytest.mark.parametrize('role',['leader','follower'])
def test_read_only_device_connect_feedback_cancel_close_never_writes(tmp_path,role):
    device,sdk,trace=make(tmp_path,role);device.read_only=True
    device.connect();device.read();device.stop()
    if role=='leader':device.activate()  # Source's existing activation must remain passive.
    else:
        with pytest.raises(DeviceError,match='ARM_MOTION_NOT_APPROVED'):device.activate()
    with pytest.raises(DeviceError):device.send(dict.fromkeys(sdk.bus.motors,0.))
    device.close()
    assert not any(t in ('disable','configure','enable','send','write_Goal_Position')for t in trace)
    assert ('disconnect',False) in trace and sdk.bus.torque==1


def test_read_only_connect_failure_preserves_torque(tmp_path):
    device,sdk,trace=make(tmp_path);device.read_only=True;sdk.bus.is_calibrated=False
    with pytest.raises(DeviceError):device.connect()
    assert ('disconnect',False) in trace and 'disable' not in trace
