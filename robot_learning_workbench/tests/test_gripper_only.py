import time
import pytest
from test_robot_lifecycle import make
from robot_learning_workbench.robot import devices
from robot_learning_workbench.robot.calibration import JOINTS,native_from_raw


def follower(tmp_path):
    f,sdk,trace=make(tmp_path);f.read_only=True;f.connect()
    e=f.profile['joints']['gripper'];raw=round(e['anchor_raw'])
    sdk.bus.present['gripper']=raw;sdk.bus.goal['gripper']=raw
    def read(register,joint,normalize=False):
        assert joint=='gripper'
        return {'Torque_Enable':1,'Operating_Mode':0,'Present_Position':sdk.bus.present[joint],'Goal_Position':sdk.bus.goal[joint]}[register]
    def write(register,joint,value,normalize=False):
        assert joint=='gripper' and register=='Goal_Position' and not normalize
        trace.append(('write_one',register,joint,value));sdk.bus.goal[joint]=value;sdk.bus.present[joint]=value
    sdk.bus.read=read;sdk.bus.write=write
    return f,sdk,trace,raw


def test_only_single_approved_gripper_register_is_written(tmp_path):
    f,sdk,t,raw=follower(tmp_path)
    limits={n:e['limits']for n,e in f.profile['joints'].items()};e=f.profile['joints']['gripper']
    target=f.precision_mapper.calibrated_to_urdf({n:native_from_raw(raw+1 if n=='gripper' else sdk.bus.present[n],spec['motor'])for n,spec in f.profile['joints'].items()})['gripper']
    p=devices.gripper_proposal(f,target,model_bounds=limits,max_delta_raw=1)
    assert p['motor_id']==6 and p['raw_delta']==1
    with pytest.raises(devices.DeviceError):devices.send_gripper_once(f,p,approved=False)
    out=devices.send_gripper_once(f,p,approved=True)
    assert out['sent_joint']=='gripper' and out['command_count']==1
    with pytest.raises(devices.DeviceError):devices.send_gripper_once(f,p,approved=True)
    f.close()
    assert [x for x in t if isinstance(x,tuple) and x[0]=='write_one']==[('write_one','Goal_Position','gripper',raw+1)]
    assert 'disable'not in t and 'configure'not in t and 'send'not in t


def test_unapproved_large_or_stale_motion_is_blocked(tmp_path):
    f,_,t,_=follower(tmp_path);limits={n:e['limits']for n,e in f.profile['joints'].items()}
    with pytest.raises(devices.DeviceError):devices.gripper_proposal(f,100.,model_bounds=limits,max_delta_raw=1)
    assert not any(isinstance(x,tuple)and x[0]=='write_one'for x in t)
    f.close()
