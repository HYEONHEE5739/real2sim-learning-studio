"""Only memory buses; no official driver constructor or physical connection."""
from dataclasses import dataclass
from types import SimpleNamespace as NS
import copy
import hashlib
import json
import math
import pytest
from test_precision_calibration import bound
from robot_learning_workbench.robot.calibration import JOINTS,native_from_raw,raw_from_native
from robot_learning_workbench.robot import devices as d

@dataclass
class Cal:
    id:int
    drive_mode:int
    homing_offset:int
    range_min:int
    range_max:int

class Bus:
    def __init__(self,profile,trace):
        self.trace=trace;self.port=profile['identity']['port'];self.is_connected=False;self.is_calibrated=True;self.apply_drive_mode=True
        self.motors={n:NS(id=e['motor']['calibration']['id'],model='sts3215',norm_mode=NS(name=e['motor']['mode'])) for n,e in profile['joints'].items()}
        self.calibration={n:Cal(**e['motor']['calibration']) for n,e in profile['joints'].items()}
        self.specs={n:e['motor'] for n,e in profile['joints'].items()};self.model_resolution_table={'sts3215':4096}
        self.present={n:round(e['anchor_raw']) for n,e in profile['joints'].items()};self.goal=dict(self.present)
        self.port_handler=NS(closePort=self.close_port);self.torque=1;self.fault=None
    def close_port(self):self.trace.append('port_close');self.is_connected=False
    def connect(self):self.trace.append('connect');self.is_connected=True
    def disconnect(self,disable_torque=True):
        self.trace.append(('disconnect',disable_torque))
        if disable_torque:self.disable_torque()
        self.close_port()
    def disable_torque(self,*args):
        self.trace.append('disable')
        if self.fault=='disable':raise TimeoutError('torque response lost')
        self.torque=0
    def sync_read(self,name,**kw):
        self.trace.append('read_'+name)
        if name=='Present_Position':return dict(self.present)
        if name=='Goal_Position':return dict(self.goal) if self.fault!='readback' else dict.fromkeys(JOINTS,-1)
        return dict.fromkeys(JOINTS,0)
    def sync_write(self,name,packet,**kw):self.trace.append('write_'+name);self.goal=dict(packet)
    def _normalize(self,raw):return {m.id:max(0,min(100,native_from_raw(raw[m.id],self.specs[n]))) if n=='gripper' else native_from_raw(raw[m.id],self.specs[n]) for n,m in self.motors.items() if m.id in raw}
    def _unnormalize(self,native):return {m.id:int(raw_from_native(native[m.id],self.specs[n])) for n,m in self.motors.items() if m.id in native}

class SDK:
    def __init__(self,profile,trace):
        self.id=profile['identity']['id'];self.bus=Bus(profile,trace);self.trace=trace;self.action_features={n+'.pos':float for n in JOINTS}
    @property
    def is_calibrated(self):return self.bus.is_calibrated
    def configure(self):
        self.trace.append('configure');self.bus.disable_torque()
        try:
            if self.bus.fault=='configure':raise OSError('configure failed after register writes')
        finally:self.bus.torque=1;self.trace.append('enable')
    def send_action(self,packet):
        self.trace.append('send')
        if self.bus.fault=='send':raise TimeoutError('sent but response lost')
        return packet


def make(tmp_path,role='follower',*,port=None):
    saved,mapper=bound(role);trace=[];sdk=SDK(mapper.profile,trace)
    path=tmp_path/(saved['identity']['id'] if role=='leader' else role+'.json');path.write_text('{}')
    # Distinct, controlled file identity; profile fit evidence remains untouched.
    profile=copy.deepcopy(mapper.profile);identity=copy.deepcopy(profile['identity']);identity['calibration_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    identity['port']=str(port or tmp_path/('memory-'+role));profile['identity']=identity
    for e in profile['joints'].values():
        e['motor']['calibration_hash']=identity['calibration_sha256']
        for ref in e['references']:ref['calibration_hash']=identity['calibration_sha256']
    sdk=SDK(profile,trace)
    cls=d.Follower if role=='follower' else d.Leader
    obj=cls(sdk,profile=profile,calibration_path=path,identity=identity,model_hash=profile['urdf_sha256'])
    return obj,sdk,trace


def test_connect_read_activate_hold_stop_and_duplicate_close(tmp_path):
    f,sdk,t=make(tmp_path);f.connect()
    assert 'configure' not in t and 'send' not in t
    native,interval=f.read();assert list(native)==list(JOINTS) and interval['start']['monotonic_ns']<=interval['end']['monotonic_ns']
    start=len(t);f.activate()
    assert t[start:start+5]==['disable','read_Present_Position','write_Goal_Position','read_Goal_Position','configure']
    assert sdk.bus.torque==1
    before=list(t);f.stop();assert t==before
    with pytest.raises(d.DeviceError) as e:f.send(native)
    assert e.value.effect=='not_applied'
    f.activate();f.send(native)
    f.close();after=list(t);f.close();assert t==after and not sdk.bus.is_connected

@pytest.mark.parametrize('role',['follower','leader'])
def test_connect_identity_mismatch_cleans_partial_port(tmp_path,role):
    f,sdk,t=make(tmp_path,role);sdk.bus.is_calibrated=False
    with pytest.raises(d.DeviceError):f.connect()
    assert not sdk.bus.is_connected and 'configure' not in t


def test_configure_failure_can_enable_torque_then_cleanup_requests_release(tmp_path):
    f,sdk,t=make(tmp_path);f.connect();sdk.bus.fault='configure'
    with pytest.raises(d.DeviceError) as e:f.activate()
    assert e.value.effect=='unknown' and 'enable' in t
    assert t.index('enable')<t.index(('disconnect',True)) and not sdk.bus.is_connected
    assert sdk.bus.torque==0


def test_disconnect_torque_failure_still_closes_port_and_reports_unknown(tmp_path):
    f,sdk,t=make(tmp_path);f.connect();sdk.bus.fault='disable'
    with pytest.raises(d.DeviceError) as e:f.close()
    assert e.value.effect=='unknown' and not sdk.bus.is_connected
    assert e.value.cleanup.port_closed and e.value.cleanup.torque_state=='unknown'
    before=list(t);f.close();assert before==t


def test_all_owned_devices_are_attempted_even_when_first_close_raises():
    trace=[]
    def bad():trace.append('precision');raise OSError('close failed')
    with pytest.raises(d.DeviceError) as e:d.close_devices({'precision':NS(close=bad),'leader':NS(close=lambda:trace.append('leader')),'camera':NS(close=lambda:trace.append('camera'))})
    assert trace==['precision','leader','camera'] and 'precision' in str(e.value)


def test_send_timeout_effect_unknown_is_not_replayed(tmp_path):
    f,sdk,t=make(tmp_path);f.connect();native,_=f.read();f.activate();sdk.bus.fault='send'
    with pytest.raises(d.DeviceError) as e:f.send(native)
    assert e.value.effect=='unknown' and t.count('send')==1
    with pytest.raises(d.DeviceError) as again:f.send(native)
    assert again.value.effect=='not_applied' and t.count('send')==1

@pytest.mark.parametrize('fault',['readback','disable'])
def test_failed_hold_never_calls_configure_and_cleanup_is_explicit(tmp_path,fault):
    f,sdk,t=make(tmp_path);f.connect();sdk.bus.fault=fault
    with pytest.raises(d.DeviceError) as e:f.activate()
    assert e.value.effect=='unknown' and 'configure' not in t and not sdk.bus.is_connected

@pytest.mark.parametrize('fault',['file','mapping','register','motor','nonfinite','bounds'])
def test_pre_send_changes_are_rejected_before_goal(tmp_path,fault):
    f,sdk,t=make(tmp_path);f.connect();native,_=f.read();f.activate()
    if fault=='file':f.calibration_path.write_text('changed')
    elif fault=='mapping':f.precision_mapper.profile['role']='wrong'
    elif fault=='register':sdk.bus.calibration['gripper'].homing_offset+=1
    elif fault=='motor':sdk.bus.motors['gripper'].id=999
    elif fault=='nonfinite':native['gripper']=math.nan
    else:native['gripper']=1e9
    with pytest.raises(d.DeviceError) as e:f.send(native)
    assert e.value.effect=='not_applied' and 'send' not in t


def test_sdk_integer_encoding_and_teleop_model_quantization(tmp_path):
    from robot_learning_workbench.robot.control import command_target
    f,sdk,t=make(tmp_path);f.connect();_,leader=bound('leader')
    limits={n:e['limits'] for n,e in f.profile['joints'].items()}
    leader_native=leader.urdf_to_calibrated({n:sum(pair)/2 for n,pair in leader.command_limits(limits).items()})
    q,command,diagnostics=command_target(leader_native,leader_mapper=leader,follower=f,model_bounds=limits)
    assert q.dtype.name=='float64' and q.shape==(6,) and 'send' not in t
    raw=sdk.bus._unnormalize({sdk.bus.motors[n].id:command[n] for n in JOINTS})
    assert raw==f.last_encoded_goal_raw
    measured=f.precision_mapper.calibrated_to_urdf({n:sdk.bus._normalize(raw)[sdk.bus.motors[n].id] for n in JOINTS})
    assert q.tolist()==[measured[n] for n in JOINTS]
    assert diagnostics['hardware_measured'] is False
    with pytest.raises(ValueError):command_target(leader_native,leader_mapper=leader,follower=f,model_bounds=limits,engine_bounds=[[10,11]]*6)


def test_leader_activation_only_releases_torque_and_has_no_send(tmp_path):
    f,sdk,t=make(tmp_path,'leader');f.connect();start=len(t);f.activate()
    assert t[start:]==['disable'] and 'configure' not in t
    with pytest.raises(d.DeviceError):f.send(dict.fromkeys(JOINTS,0))


def test_readonly_calibration_exclusive_release_and_close_preserve_torque(tmp_path,monkeypatch):
    import fcntl
    f,sdk,t=make(tmp_path);sdk.bus.port_handler.ser=NS(fileno=lambda:999999)
    locks=[];monkeypatch.setattr(fcntl,'ioctl',lambda fd,op:locks.append(op))
    sdk.bus.read=lambda register,joint,normalize=False:(sdk.bus.torque if register=='Torque_Enable' else (native_from_raw(sdk.bus.present[joint],sdk.bus.specs[joint]) if normalize else sdk.bus.present[joint]))
    def release(names):t.append(('release',names));sdk.bus.torque=0
    sdk.bus.disable_torque=release
    calibration=d.CalibrationDevice(sdk,role='follower',identity=f.identity,calibration_path=f.calibration_path)
    calibration.connect();sample=calibration.sample('gripper',live=True)
    assert sample['native_source']=='normalized_same_raw_packet' and sample['torque']==1
    with pytest.raises(d.DeviceError):calibration.release('gripper',approved=False)
    assert sdk.bus.torque==1
    calibration.release('gripper',approved=True);assert sdk.bus.torque==0
    calibration.close();assert ('disconnect',False) in t and len(locks)==2
    assert calibration.cleanup.torque_state=='preserved'


def test_calibration_unlock_failure_still_closes_port_without_torque_write(tmp_path,monkeypatch):
    import fcntl
    f,sdk,t=make(tmp_path);sdk.bus.port_handler.ser=NS(fileno=lambda:999999)
    def ioctl(fd,op):
        if op==__import__('termios').TIOCNXCL:raise OSError('unlock failed')
    monkeypatch.setattr(fcntl,'ioctl',ioctl)
    obj=d.CalibrationDevice(sdk,role='follower',identity=f.identity,calibration_path=f.calibration_path);obj.connect()
    with pytest.raises(d.DeviceError) as e:obj.close()
    assert ('disconnect',False) in t and not sdk.bus.is_connected and 'disable' not in t
    assert e.value.effect=='unknown'

@pytest.mark.parametrize('change',['port','id'])
def test_actual_sdk_endpoint_cannot_be_relabelled_by_profile(tmp_path,change):
    f,sdk,t=make(tmp_path)
    if change=='port':sdk.bus.port='other-port'
    else:sdk.id='other-id'
    with pytest.raises(d.DeviceError):f.connect()
    assert 'configure' not in t and not sdk.bus.is_connected


def test_leader_identity_uses_selected_calibration_filename_like_b03(tmp_path):
    f,sdk,t=make(tmp_path,'leader');sdk.id='official_identifier_without_json_extension'
    f.connect();assert f._connected


def official_functions(file,class_name,names):
    import ast,contextlib,logging
    from enum import Enum
    from pathlib import Path
    root=Path('/home/hyeonhee/miniconda3/envs/lerobot-arena/lib/python3.11/site-packages/lerobot')
    source=(root/file).read_text();tree=ast.parse(source)
    enum=Enum('MotorNormMode',{n:n for n in ('DEGREES','RANGE_0_100','RANGE_M100_100')},type=str)
    ns={'contextmanager':__import__('contextlib').contextmanager,'MotorNormMode':enum,'logger':logging.getLogger('sdk_fixture')}
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==class_name)
    nodes=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in names]
    exec(compile('from __future__ import annotations\n'+ '\n'.join(ast.unparse(n) for n in nodes),str(root/file),'exec'),ns)
    return ns


def test_actual_official_configure_finally_and_disconnect_failure_cleanup(tmp_path):
    f,sdk,t=make(tmp_path);f.connect()
    motors=official_functions('motors/motors_bus.py','MotorsBus',{'torque_disabled','disconnect'})
    follower=official_functions('robots/so101_follower/so101_follower.py','SO101Follower',{'configure'})
    def enable(*args):sdk.bus.torque=1;t.append('official_enable')
    def fail():t.append('official_configure_failed');raise OSError('register failure')
    sdk.bus.enable_torque=enable;sdk.bus.torque_disabled=lambda:motors['torque_disabled'](sdk.bus)
    sdk.bus.configure_motors=fail;sdk.configure=lambda:follower['configure'](sdk)
    with pytest.raises(d.DeviceError):f.activate()
    assert 'official_enable' in t and t.index('official_enable')<t.index(('disconnect',True))
    assert sdk.bus.torque==0 and not sdk.bus.is_connected
    # Second actual SDK path fails before its own closePort; the owner still closes it.
    g,other,trace=make(tmp_path);g.connect()
    other.bus.port_handler.clearPort=lambda:trace.append('clear')
    def timeout(*args,**kwargs):raise TimeoutError('release timeout')
    other.bus.disable_torque=timeout
    other.bus.disconnect=lambda **kwargs:motors['disconnect'](other.bus,**kwargs)
    with pytest.raises(d.DeviceError) as e:g.close()
    assert e.value.cleanup.torque_state=='unknown' and not other.bus.is_connected and 'port_close' in trace


def test_actual_official_integer_encoder_over_sixty_b03_targets(tmp_path):
    from types import MethodType
    functions=official_functions('motors/motors_bus.py','MotorsBus',{'_normalize','_unnormalize'})
    f,sdk,t=make(tmp_path);bus=sdk.bus
    for n,motor in bus.motors.items():motor.norm_mode=functions['MotorNormMode'][motor.norm_mode.name]
    bus._id_to_name=lambda id_:next(n for n,m in bus.motors.items() if m.id==id_)
    bus._id_to_model=lambda id_:bus.motors[bus._id_to_name(id_)].model
    bus._normalize=MethodType(functions['_normalize'],bus);bus._unnormalize=MethodType(functions['_unnormalize'],bus)
    f.connect();mapper=f.precision_mapper;bounds=mapper.command_limits({n:e['limits'] for n,e in mapper.profile['joints'].items()})
    for fraction in (.05,.25,.5,.75,.95):
        q={n:v[0]+fraction*(v[1]-v[0]) for n,v in bounds.items()};native=mapper.urdf_to_calibrated(q)
        command,encoded=f.encode_goal(native);actual=bus._unnormalize({bus.motors[n].id:command[n] for n in JOINTS})
        assert actual==f.last_encoded_goal_raw
        assert [encoded[n] for n in JOINTS]==[bus._normalize(actual)[bus.motors[n].id] for n in JOINTS]


def test_homed_raw_packet_is_not_cast_before_hold_write_or_saved_feedback(tmp_path):
    f,sdk,t=make(tmp_path);f.connect();f.read()
    assert all(isinstance(v,int) for v in f.last_raw.values())
    original=sdk.bus.sync_write
    def write(name,packet,**kw):
        assert all(isinstance(v,int) for v in packet.values())
        original(name,packet,**kw)
    sdk.bus.sync_write=write;f.activate()


def test_interrupted_partial_connect_and_cleanup_still_visit_remaining_resources(tmp_path):
    f,sdk,t=make(tmp_path)
    def interrupt():sdk.bus.is_connected=True;raise KeyboardInterrupt('interrupted handshake')
    sdk.bus.connect=interrupt
    with pytest.raises(d.DeviceError):f.connect()
    assert not sdk.bus.is_connected
    trace=[]
    def interrupted_close():trace.append('first');raise KeyboardInterrupt('interrupted close')
    with pytest.raises(d.DeviceError):d.close_devices({'first':NS(close=interrupted_close),'second':NS(close=lambda:trace.append('second'))})
    assert trace==['first','second']


def test_feedback_and_sdk_encoding_do_not_add_hardware_calibration_reads(tmp_path,monkeypatch):
    f,sdk,t=make(tmp_path);f.connect()
    def unexpected_check(_):raise AssertionError('Unexpected extra hardware calibration read')
    monkeypatch.setattr(type(sdk),'is_calibrated',property(unexpected_check))
    native,_=f.read();f.encode_goal(native)
