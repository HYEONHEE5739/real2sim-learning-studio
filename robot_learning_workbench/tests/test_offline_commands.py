"""Controlled observations/Policy; actual Precision/SDK math, never a serial device."""
import copy,hashlib,json
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pytest
from test_precision_calibration import bound,CURRENT
from robot_learning_workbench.robot import offline,control
from robot_learning_workbench.robot.calibration import JOINTS,PrecisionMapper,joint_specs


def setup(tmp_path,monkeypatch,action):
    from lerobot.motors.feetech.feetech import FeetechMotorsBus
    def forbidden(*a,**kw):raise AssertionError('Hardware constructor or IO called')
    for method in ('__init__','connect','disconnect','sync_read','sync_write'):
        monkeypatch.setattr(FeetechMotorsBus,method,forbidden)
    _,mapper=bound('follower');profile=copy.deepcopy(mapper.profile)
    cal=tmp_path/'motors.json';cal.write_text(json.dumps({n:e['motor']['calibration']for n,e in profile['joints'].items()}))
    sha=hashlib.sha256(cal.read_bytes()).hexdigest();profile['identity']['calibration_sha256']=sha
    for e in profile['joints'].values():
        e['motor']['calibration_hash']=sha
        for ref in e['references']:ref['calibration_hash']=sha
    mapper=PrecisionMapper(profile);p=tmp_path/'precision.json';p.write_text(json.dumps(profile))
    model=tmp_path/'model.urdf';model.write_bytes(CURRENT.read_bytes())
    device={'role':'follower','sdk':{'port':profile['identity']['port'],'id':profile['identity']['id'],'use_degrees':True},'calibration_id':'observation','command_calibration_id':'command','calibration_path':str(cal)}
    plan=NS(stage='real_evaluation',effective_settings={'execution':{'mode':'offline'}},scene=NS(root=tmp_path,scene={'robot':{'joint_order':list(JOINTS),'model_sha256':profile['urdf_sha256']}},files=[NS(path='model.urdf',sha256=profile['urdf_sha256'])]),scene_identity={},input_documents={'device_profile':device},resolved_inputs={'calibration_profile':{'path':str(p)},'capture_session':{'path':str(tmp_path)},'motor_calibration':{'path':str(cal)}},output_path=tmp_path/'output')
    from robot_learning_workbench import recipe
    from robot_learning_workbench.learning import policy
    from real2sim_builder import capture
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda _:None)
    monkeypatch.setattr(capture,'load_session',lambda _:({'joint_names':list(JOINTS),'clock':{},'schema':'fixture'},[{'q_measured':[0.]*6,'images':[]}],[]))
    monkeypatch.setattr(offline,'capture_binding',lambda *a:[])
    monkeypatch.setattr(offline,'mapper_from_scene',lambda *a,**kw:mapper)
    monkeypatch.setattr(policy,'policy_inputs',lambda *a:(None,None,None,{'step':4},{}))
    monkeypatch.setattr(policy,'observation_batch',lambda *a,**kw:{})
    monkeypatch.setattr(policy,'infer',lambda *a,**kw:np.array([action]))
    return plan,mapper


@pytest.mark.parametrize('value',[100.,-100.])
def test_offline_policy_saturates_and_checks_official_integer_encoding(tmp_path,monkeypatch,value):
    p,_=setup(tmp_path,monkeypatch,[value]*6)
    assert offline.run(p,events=lambda _:None,commands=lambda:()).status=='completed'
    report=json.loads((p.output_path/'offline-inspection.json').read_text());command=report['policy']['command_preflight']
    assert command['encoding_possible'] is True and all(command['saturation']['saturation_mask'])
    assert report['policy']['action_model_rad']==[value]*6 and report['policy']['command_sent'] is False
    assert all(command['bounds_rad'][i][0]<=command['encoded_model_rad'][n]<=command['bounds_rad'][i][1]for i,n in enumerate(JOINTS))
    assert report['hardware_connected'] is False and report['physical_verified'] is False


def test_missing_sdk_calibration_is_partial_not_approved(tmp_path,monkeypatch):
    p,_=setup(tmp_path,monkeypatch,[0.]*6);del p.resolved_inputs['motor_calibration']
    offline.run(p,events=lambda _:None,commands=lambda:())
    report=json.loads((p.output_path/'offline-inspection.json').read_text())
    assert report['status']=='PARTIAL' and report['policy']['command_sent'] is False
    assert 'encoding' in report['command_binding'].lower()


def test_changed_calibration_is_rejected_and_explained(tmp_path,monkeypatch):
    p,_=setup(tmp_path,monkeypatch,[0.]*6);Path(p.resolved_inputs['motor_calibration']['path']).write_text('{}')
    with pytest.raises(ValueError,match='calibration file identity'):offline.run(p,events=lambda _:None,commands=lambda:())
    report=json.loads((p.output_path/'offline-inspection.json').read_text())
    assert report['status']=='REJECTED' and report['policy']['command_sent'] is False
    assert report['policy']['command_preflight']['encoding_possible'] is False
    assert 'identity' in report['policy']['command_preflight']['reason']


@pytest.mark.parametrize('case',['safe','motor','quantization','nan','inf','shape','unit','order','no_intersection','branch','sdk'])
def test_shared_command_guards_without_connect_or_send(tmp_path,monkeypatch,case):
    from test_robot_lifecycle import make
    from robot_learning_workbench.robot.devices import DeviceError
    follower,_,trace=make(tmp_path);follower._check_identity()
    bus=follower.device.bus
    low=bus._normalize({c.id:c.range_min for c in bus.calibration.values()});high=bus._normalize({c.id:c.range_max for c in bus.calibration.values()})
    follower.limits={n:sorted((low[m.id],high[m.id])) for n,m in bus.motors.items()}
    bounds={n:s['limits']for n,s in joint_specs(CURRENT).items()};common=follower.precision_mapper.command_limits(bounds)
    q=np.array([sum(common[n])/2 for n in JOINTS]);kwargs={}
    if case=='motor':
        n=next(n for n in JOINTS if common[n][1]<bounds[n][1]-1e-6);q[JOINTS.index(n)]=bounds[n][1]
    if case=='quantization':q=np.array([common[n][1]for n in JOINTS])
    if case=='nan':q[0]=np.nan
    if case=='inf':q[0]=np.inf
    if case=='shape':q=q[:5]
    if case=='unit':kwargs['units']='degree'
    if case=='order':kwargs['joint_order']=JOINTS[::-1]
    if case=='no_intersection':bounds[JOINTS[0]]=[100.,101.]
    if case=='branch':
        c=follower.precision_mapper.profile['joints'][JOINTS[0]]['motor']['calibration'];c['range_max']=c['range_min']+4096
    if case=='sdk':
        original=bus._unnormalize;monkeypatch.setattr(bus,'_unnormalize',lambda target:{i:r+2 for i,r in original(target).items()})
    if case in ('safe','motor','quantization'):
        actual,_,report=control.encode_model_target(q,follower=follower,model_bounds=bounds,**kwargs)
        assert report['encoding_possible'] and all(common[n][0]<=actual[i]<=common[n][1]for i,n in enumerate(JOINTS))
        assert any(report['saturation']['saturation_mask'])==(case=='motor')
    else:
        with pytest.raises(DeviceError if case=='sdk' else ValueError)as error:control.encode_model_target(q,follower=follower,model_bounds=bounds,**kwargs)
        if case=='sdk':assert error.value.command_preflight['encoding_possible'] is False
    assert trace==[]
