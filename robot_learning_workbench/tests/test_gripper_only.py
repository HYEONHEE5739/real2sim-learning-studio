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


def test_actual_sdk_needs_explicit_command_phase_binding(tmp_path):
    f,sdk,t,raw=follower(tmp_path)
    class OfficialBus(type(sdk.bus)):
        __module__='lerobot.motors.feetech.feetech'
    sdk.bus.__class__=OfficialBus
    with pytest.raises(devices.DeviceError,match='command Calibration'):
        devices.gripper_proposal(f,0.,model_bounds={n:e['limits']for n,e in f.profile['joints'].items()},max_delta_raw=1)
    f.close()


def test_worker_waits_for_exact_proposal_and_supervised_one_shot_approval(tmp_path,monkeypatch):
    from types import SimpleNamespace as NS
    from robot_learning_workbench.robot import live,configuration
    from robot_learning_workbench import recipe
    f,sdk,trace,raw=follower(tmp_path)
    entry=f.profile['joints']['gripper'];target=(raw+1-entry['anchor_raw'])*entry['rad_per_count']+entry['reference_angle_rad']
    proposal=[]
    monkeypatch.setattr(live,'open_inputs',lambda _: (f,{}))
    monkeypatch.setattr(configuration,'bind_gripper_command',lambda *a: {'motion_approved':False})
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda _:None)
    model=tmp_path/'model.urdf'
    # Joint limits used from exact model bytes in this fixture.
    model.write_text('<robot>'+''.join('<joint name="'+n+'" type="revolute"><origin xyz="0 0 0"/><parent link="p"/><child link="c"/><axis xyz="0 0 1"/><limit lower="'+str(e['limits'][0])+'" upper="'+str(e['limits'][1])+'"/></joint>'for n,e in f.profile['joints'].items())+'</robot>')
    p=NS(stage='teleoperation',scene=NS(files=[NS(path=model.name,sha256=f.profile['urdf_sha256'])],root=tmp_path),
        input_documents={'device_profile':{'command_calibration_id':'explicit_command'}},output_path=tmp_path/'result',effective_settings={'execution':{'mode':'gripper_once','gripper_target_rad':target,'max_gripper_delta_raw':1}})
    def events(event):
        if 'gripper_proposal'in event.get('payload',{}).get('progress',{}):proposal.append(event['payload']['progress']['gripper_proposal'])
    def commands():
        if not proposal:return ()
        from robot_learning_workbench.robot.calibration import fingerprint
        return ({'kind':'gripper_approve','command_id':'approved','payload':{'proposal_sha256':fingerprint(proposal[0]),'target_raw':proposal[0]['target_raw'],'supervised':True,'clear':True,'stop_ready':True}},)
    result=live.run(p,events=events,commands=commands)
    assert result.status=='completed' and len(proposal)==1
    assert len([r for r in trace if isinstance(r,tuple)and r[0]=='write_one'])==1


@pytest.mark.parametrize('hazard',['goal_changed','stopped','expired','packet_changed'])
def test_approval_is_invalidated_before_any_goal_write(tmp_path,hazard):
    f,sdk,trace,raw=follower(tmp_path);e=f.profile['joints']['gripper']
    target=(raw+1-e['anchor_raw'])*e['rad_per_count']+e['reference_angle_rad']
    p=devices.gripper_proposal(f,target,model_bounds={n:e['limits']for n,e in f.profile['joints'].items()},max_delta_raw=1)
    if hazard=='goal_changed':sdk.bus.goal['gripper']=raw+10
    if hazard=='stopped':f.stop()
    if hazard=='expired':p['created_ns']-=60_000_000_000
    if hazard=='packet_changed':p['target_raw']+=2
    with pytest.raises(devices.DeviceError):devices.send_gripper_once(f,p,approved=True)
    f.close()
    assert not any(isinstance(x,tuple)and x[0]=='write_one'for x in trace)


def test_policy_gripper_path_uses_only_the_official_gripper_output(tmp_path,monkeypatch):
    from types import SimpleNamespace as NS
    from robot_learning_workbench.robot import live,configuration
    from robot_learning_workbench import recipe
    from robot_learning_workbench.learning import policy
    import numpy as np
    f,sdk,trace,raw=follower(tmp_path);entry=f.profile['joints']['gripper']
    target=(raw+1-entry['anchor_raw'])*entry['rad_per_count']+entry['reference_angle_rad']
    import time
    class Camera:
        def start(self):pass
        def nearest(self,*a):return {'rgb':np.zeros((480,640,3),np.uint8),'read_end':{'monotonic_ns':time.monotonic_ns()}}
        def close(self):pass
    monkeypatch.setattr(live,'open_inputs',lambda _: (f,{'side':Camera(),'wrist':Camera()}))
    monkeypatch.setattr(configuration,'bind_gripper_command',lambda *a: {})
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda _:None)
    monkeypatch.setattr(policy,'policy_inputs',lambda *a:(NS(reset=lambda:None),None,None,{'step':4},{'joint_order':list(JOINTS)}))
    monkeypatch.setattr(policy,'observation_batch',lambda *a,**kw:{})
    monkeypatch.setattr(policy,'infer',lambda *a,**kw:np.array([[100.,100.,100.,100.,100.,target]]))
    from test_precision_calibration import CURRENT
    p=NS(stage='real_evaluation',scene=NS(scene={'robot':{'model_sha256':f.profile['urdf_sha256']}},files=[NS(path=CURRENT.name,sha256=f.profile['urdf_sha256'])],root=CURRENT.parent),input_documents={'device_profile':{'command_calibration_id':'explicit'}},output_path=tmp_path/'policy',effective_settings={'execution':{'mode':'gripper_once','max_gripper_delta_raw':1}})
    from robot_learning_workbench.robot.calibration import fingerprint
    proposals=[]
    def events(e):
        if 'gripper_proposal'in e.get('payload',{}).get('progress',{}):proposals.append(e['payload']['progress']['gripper_proposal'])
    def commands():return ({'kind':'gripper_approve','command_id':'one','payload':{'proposal_sha256':fingerprint(proposals[0]),'target_raw':proposals[0]['target_raw'],'supervised':True,'clear':True,'stop_ready':True}},)if proposals else ()
    result=live.run(p,events=events,commands=commands)
    assert result.status=='completed' and len([x for x in trace if isinstance(x,tuple)and x[0]=='write_one'])==1
