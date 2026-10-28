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


def test_observer_factory_checks_calibration_before_sdk_construction(tmp_path,monkeypatch):
    from robot_learning_workbench.robot.configuration import create_observer
    from test_precision_calibration import bound
    saved,_=bound('follower');p=tmp_path/'wrong.json';p.write_text('{}')
    with pytest.raises(ValueError,match='calibration'):
        create_observer({'role':'follower','calibration_path':str(p),'sdk':{'port':saved['identity']['port'],'id':saved['identity']['id'],'use_degrees':True}},saved)


def test_direct_official_device_cannot_enable_full_arm_motion(tmp_path):
    device,sdk,_=make(tmp_path)
    class OfficialBus(type(sdk.bus)):
        __module__='lerobot.motors.feetech.feetech'
    sdk.bus.__class__=OfficialBus
    from robot_learning_workbench.robot.devices import Follower
    same=Follower(sdk,profile=device.profile,calibration_path=device.calibration_path,identity=device.identity,model_hash=device.profile['urdf_sha256'])
    assert same.read_only is True
    with pytest.raises(DeviceError,match='ARM_MOTION_NOT_APPROVED'):same.activate()


def test_reference_collection_cannot_release_any_arm_joint(tmp_path):
    from robot_learning_workbench.robot.devices import CalibrationDevice
    f,sdk,trace=make(tmp_path);cal=CalibrationDevice(sdk,role='follower',identity=f.identity,calibration_path=f.calibration_path)
    cal.exclusive=True
    for n in ('shoulder_pan','shoulder_lift','elbow_flex','wrist_flex','wrist_roll'):
        with pytest.raises(DeviceError):cal.release(n,approved=True)
    assert 'disable'not in trace
