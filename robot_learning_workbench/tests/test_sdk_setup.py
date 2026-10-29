import pytest


def test_official_calibration_requires_onsite_confirmation_and_preserves_existing_file(tmp_path):
    from robot_learning_workbench.robot.sdk_calibration import validate_spec
    config=tmp_path/'devices/new';config.mkdir(parents=True);cal=config/'calibration/follower/new.json';cal.parent.mkdir(parents=True)
    spec={'role':'follower','usb_identity':{'serial':'new'},'calibration_path':str(cal),'sdk':{'id':'new','port':'/fixture','use_degrees':True,'calibration_dir':str(cal.parent)}}
    with pytest.raises(ValueError,match='approval'):validate_spec(spec,config,False)
    validate_spec(spec,config,True)
    cal.write_text('{}')
    with pytest.raises(ValueError,match='existing'):validate_spec(spec,config,True)


def test_sdk_calibration_calls_official_procedure_only_after_gate_and_never_configures(monkeypatch,tmp_path):
    from robot_learning_workbench.robot.sdk_calibration import calibrate
    calls=[]
    class Bus:
        def connect(self):calls.append('connect')
        def disconnect(self,disable_torque):assert disable_torque is False;calls.append('close')
    class SDK:
        bus=Bus()
        def calibrate(self):
            calls.append('calibrate');assert input('Move manually then continue')==''
        def configure(self):raise AssertionError('No automatic configure/torque')
    calibrate(SDK(),lambda text:'',lambda:True)
    assert calls==['connect','calibrate','close']
    calls.clear()
    with pytest.raises(InterruptedError):calibrate(SDK(),lambda text:(_ for _ in()).throw(InterruptedError('cancel')),lambda:True)
    assert calls==['connect','calibrate','close']


def test_official_range_loop_is_driven_by_r03_enter_and_can_cancel():
    from robot_learning_workbench.robot.sdk_calibration import calibrate
    from lerobot.motors.motors_bus import MotorsBus
    calls=[]
    class Bus:
        motors={'joint':None};count=0
        def connect(self):calls.append('open')
        def disconnect(self,disable_torque):assert disable_torque is False;calls.append('close')
        def sync_read(self,*args,**kwargs):self.count+=1;return {'joint':self.count}
        def record_ranges_of_motion(self):return MotorsBus.record_ranges_of_motion(self,display_values=False)
    class SDK:
        bus=Bus()
        def calibrate(self):self.result=self.bus.record_ranges_of_motion()
    device=SDK();polls=[]
    def enter():polls.append(1);return len(polls)>2
    calibrate(device,lambda text:'',enter)
    assert len(polls)==3 and device.result==({'joint':1},{'joint':4})and calls==['open','close']
    calls.clear()
    with pytest.raises(InterruptedError):calibrate(SDK(),lambda text:'',lambda:(_ for _ in()).throw(InterruptedError('cancel')))
    assert calls==['open','close']
