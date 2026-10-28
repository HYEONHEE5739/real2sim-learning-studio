"""Controlled Capture/Policy fixture; real Precision and official SDK arithmetic, no IO."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pytest
from test_precision_calibration import bound,CURRENT
from robot_learning_workbench.robot import offline,control
from robot_learning_workbench.robot.devices import DeviceError
from robot_learning_workbench.robot.calibration import JOINTS,PrecisionMapper


def fixture(tmp_path,monkeypatch,requested):
    from lerobot.motors.feetech.feetech import FeetechMotorsBus
    def forbidden(*args,**kwargs):raise AssertionError('Hardware/serial constructor or IO attempted')
    monkeypatch.setattr(FeetechMotorsBus,'__init__',forbidden)
    for method in ('connect','disconnect','sync_read','sync_write'):
        monkeypatch.setattr(FeetechMotorsBus,method,forbidden)
    _,mapper=bound('follower');profile=copy.deepcopy(mapper.profile)
    calibration={n:e['motor']['calibration'] for n,e in profile['joints'].items()}
    motor=tmp_path/'motors.json';motor.write_text(json.dumps(calibration))
    sha=hashlib.sha256(motor.read_bytes()).hexdigest();profile['identity']['calibration_sha256']=sha
    for entry in profile['joints'].values():
        entry['motor']['calibration_hash']=sha
        for ref in entry['references']:ref['calibration_hash']=sha
    mapper=PrecisionMapper(profile)
    path=tmp_path/'precision.json';path.write_text(json.dumps(profile))
    model=tmp_path/'model.urdf';model.write_bytes(CURRENT.read_bytes())
    scene=NS(root=tmp_path,scene={'robot':{'joint_order':list(JOINTS),'model_sha256':profile['urdf_sha256']}},
             files=[NS(path='model.urdf',sha256=profile['urdf_sha256'])])
    device={'role':'follower','sdk':{'id':profile['identity']['id'],'port':profile['identity']['port'],'use_degrees':True},'calibration_id':'obs','command_calibration_id':'command'}
    p=NS(stage='real_evaluation',effective_settings={'execution':{'mode':'offline'}},scene=scene,scene_identity={},
         output_path=tmp_path/'out',input_documents={'device_profile':device},resolved_inputs={
             'calibration_profile':{'path':str(path)},'capture_session':{'path':str(tmp_path)},'motor_calibration':{'path':str(motor)}})
    from robot_learning_workbench import recipe
    from robot_learning_workbench.learning import policy
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda _:None)
    monkeypatch.setattr(offline,'capture_binding',lambda *args:[])
    monkeypatch.setattr(offline,'mapper_from_scene',lambda *args,**kwargs:mapper)
    capture=offline.capture_module()
    monkeypatch.setattr(capture,'load_session',lambda _:({'joint_names':list(JOINTS),'clock':{},'schema':'controlled'},[{'q_measured':[0.]*6,'images':[]}],[]))
    monkeypatch.setattr(policy,'policy_inputs',lambda *args:(None,None,None,{'step':4},{}))
    monkeypatch.setattr(policy,'observation_batch',lambda *args,**kwargs:{})
    monkeypatch.setattr(policy,'infer',lambda *args,**kwargs:np.asarray([requested]))
    return p,mapper


@pytest.mark.parametrize('requested_value',[100.,-100.])
def test_real_offline_policy_uses_shared_saturation_and_sdk_encoding(tmp_path,monkeypatch,requested_value):
    requested=[requested_value]*6;p,mapper=fixture(tmp_path,monkeypatch,requested)
    result=offline.run(p,events=lambda _:None,commands=lambda:())
    report=json.loads((p.output_path/'offline-inspection.json').read_text());data=report['policy']
    assert result.status=='completed' and data['command_sent'] is False
    assert data['action_model_rad']==requested
    assert all(data['command_preflight']['saturation']['saturation_mask'])
    assert len(data['sdk_goal_raw'])==6
    actual=data['command_preflight']['encoded_model_rad'];bounds=data['command_preflight']['bounds_rad']
    assert all(bounds[i][0]<=actual[n]<=bounds[i][1]for i,n in enumerate(JOINTS))
    assert report['hardware_connected'] is False and report['physical_verified'] is False


def test_offline_command_requires_original_sdk_calibration(tmp_path,monkeypatch):
    p,_=fixture(tmp_path,monkeypatch,[0.]*6);del p.resolved_inputs['motor_calibration']
    offline.run(p,events=lambda _:None,commands=lambda:())
    report=json.loads((p.output_path/'offline-inspection.json').read_text())
    assert report['status']=='PARTIAL' and 'sdk_goal_raw' not in report['policy']
    assert 'motor_calibration' in report['command_binding']


def test_offline_command_rejects_calibration_identity_change(tmp_path,monkeypatch):
    p,_=fixture(tmp_path,monkeypatch,[0.]*6)
    Path(p.resolved_inputs['motor_calibration']['path']).write_text('{}')
    with pytest.raises(ValueError,match='calibration file identity'):
        offline.run(p,events=lambda _:None,commands=lambda:())
    assert not p.output_path.exists()


@pytest.mark.parametrize('case',['nan','shape','unit','order','sdk'])
def test_shared_position_preflight_keeps_invalid_input_and_encoder_guards(tmp_path,monkeypatch,case):
    from test_robot_lifecycle import make
    from robot_learning_workbench.robot.calibration import joint_specs
    follower,_,trace=make(tmp_path);follower._check_identity()
    bus=follower.device.bus
    low=bus._normalize({c.id:c.range_min for c in bus.calibration.values()})
    high=bus._normalize({c.id:c.range_max for c in bus.calibration.values()})
    follower.limits={n:sorted((low[m.id],high[m.id]))for n,m in bus.motors.items()}
    bounds={n:s['limits']for n,s in joint_specs(CURRENT).items()}
    common=follower.precision_mapper.command_limits(bounds);target=np.array([sum(common[n])/2 for n in JOINTS]);kw={}
    if case=='nan':target[0]=np.nan
    if case=='shape':target=target[:5]
    if case=='unit':kw['units']='degree'
    if case=='order':kw['joint_order']=JOINTS[::-1]
    if case=='sdk':
        original=bus._unnormalize
        monkeypatch.setattr(bus,'_unnormalize',lambda q:{i:r+2 for i,r in original(q).items()})
    with pytest.raises(DeviceError if case=='sdk' else control.TargetRejected):control.position_target(target,follower=follower,model_bounds=bounds,**kw)
    assert trace==[]
