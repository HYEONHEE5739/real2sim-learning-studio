"""Host-time/Geometry fixtures and fake cameras, without camera acquisition."""
from collections import deque
import copy
import json
from pathlib import Path
from threading import Event,Lock
from types import SimpleNamespace as NS
import numpy as np
import pytest
from robot_learning_workbench.robot import capture as c
from robot_learning_workbench.robot.devices import CameraReader,DeviceError
from robot_learning_workbench.robot.calibration import JOINTS
from test_precision_calibration import bound,B03

@pytest.mark.parametrize('times,stable',[( [0,200000000,400000000,600000000],True),([0,200000001,400000001,600000001],False)])
def test_b03_stability_time_boundaries(times,stable):
    s=c.Stability()
    for t in times:s.add(t,dict.fromkeys(JOINTS,0.))
    assert s.assess()['stable'] is stable
    with pytest.raises(ValueError):s.add(times[-1],dict.fromkeys(JOINTS,0.))


def test_b03_arm_interpolation_and_gripper_left_hold():
    samples=[{'timestamp_ns':0,'native':dict.fromkeys(JOINTS,0.)},{'timestamp_ns':100000000,'native':{**dict.fromkeys(JOINTS,0.),'shoulder_pan':20.,'gripper':80.}}]
    q=c.align_measured(samples,50000000)
    assert abs(q[0]-np.deg2rad(10))<1e-12 and q[-1]==0
    assert len(c.align_measured(samples,200000000))==6
    with pytest.raises(ValueError):c.align_measured(samples,200000001)


def pair(now=200000000,arm=.035,gripper=2.,camera_time=0):
    stability={'stable':True,'window_start_ns':-1000000000,'window_end_ns':1000000000}
    frame={'read_start':{'monotonic_ns':camera_time},'read_end':{'monotonic_ns':camera_time}}
    return c.assess_pair({'real_side':frame,'real_wrist':frame},{'monotonic_ns':0},
      {'start':{'monotonic_ns':0},'end':{'monotonic_ns':0}},stability,stability,
      {'max_arm_error_rad':arm,'gripper_error_percentage_points':gripper},now)


def test_b03_pair_boundaries_are_heuristics_not_hardware_sync():
    assert pair()['eligible_for_calibration'] and pair()['hardware_synchronized'] is False
    assert not pair(now=200000001)['eligible_for_calibration']
    assert not pair(arm=np.nextafter(.035,np.inf))['eligible_for_calibration']
    assert pair(camera_time=100000000)['eligible_for_calibration']
    assert not pair(camera_time=100000001)['eligible_for_calibration']


def test_b03_camera_geometry_and_raw_k_are_separate():
    geometry=json.loads((B03/'camera-probes.json').read_text())['geometry']
    for name,row in geometry.items():
        np.testing.assert_array_equal(c.render_k({'K':row['K_raw'],'resolution':row['resolution']}),row['K_render'])
        np.testing.assert_array_equal(np.asarray(row['T_parent_optical'])@np.diag([1,-1,-1,1]),row['T_parent_engine_camera'])
    np.testing.assert_array_equal(c.render_k({'K':[[800,0,301],[0,820,211],[0,0,1]],'resolution':[640,480]}),[[810,0,320],[0,810,240],[0,0,1]])


def test_camera_nearest_copies_and_does_not_claim_freshness():
    reader=CameraReader(NS(),device='fake',resolution=(3,2))
    assert reader.nearest() is None
    reader.frames.append({'rgb':np.ones((2,3,3),np.uint8),'read_end':{'monotonic_ns':0}})
    packet=reader.nearest(10**12);packet['rgb'][:]=0
    assert reader.frames[0]['rgb'].all()
    reader.error='fake error'
    with pytest.raises(DeviceError):reader.nearest()


def test_camera_close_reports_live_thread_even_if_disconnect_returns():
    trace=[];camera=NS(is_connected=True,disconnect=lambda:trace.append('disconnect'))
    reader=CameraReader(camera,device='fake',resolution=(3,2))
    reader.thread=NS(join=lambda timeout:trace.append(timeout),is_alive=lambda:True)
    with pytest.raises(DeviceError) as e:reader.close()
    assert trace==[.5,'disconnect',1.] and e.value.effect=='unknown'

@pytest.fixture
def snapshot():
    _,m=bound('follower')
    bounds=m.command_limits({n:e['limits'] for n,e in m.profile['joints'].items()})
    native=m.urdf_to_calibrated({n:sum(v)/2 for n,v in bounds.items()})
    history=[];s=c.Stability();end=1000000000
    for i in range(8):
        t=end-(7-i)*100000000;history.append({'timestamp_ns':t,'native':dict(native)});s.add(t,native)
    packet=lambda t:{'monotonic_ns':t,'unix_ns':t+1000000000}
    state={'joint_names':list(JOINTS),'sim_joint_mapping':m.metadata(),'physical_follower_measured_joint_state':native,
      'measured_samples':history,'real_stability':s.assess(),'precision_observation_only':True,'sent_target':None,
      'timestamps':{'follower':{'start':packet(end-1000000),'end':packet(end)},'real_cameras':{
        'real_'+n:{'read_start':packet(end-25000000-2000000),'read_end':packet(end-25000000),'sequence':1} for n in ('side','wrist')}}}
    profile={'cameras':{n:{'resolution':[64,48],'K':[[500,0,32],[0,500,24],[0,0,1]],'distortion':[0]*5,'T_parent_camera':np.eye(4).tolist(),'parent':'world'} for n in ('side','wrist')}}
    image=np.repeat((np.indices((48,64)).sum(0)%2*255).astype(np.uint8)[:,:,None],3,axis=2)
    return state,{'real_side':image,'real_wrist':image.copy()},profile


def test_snapshot_measured_commands_identity_and_owned_metadata(snapshot):
    state,images,profile=snapshot
    measured,observed,warnings=c.prepare_snapshot(state,images,profile,now_ns=1010000000)
    assert not warnings and measured['q_command'] is None and measured['hardware_synchronized'] is False
    assert [r['camera'] for r in observed]==['side','wrist'] and all(r['eligible'] for r in observed)
    assert measured['mapping_sha256']==state['sim_joint_mapping']['sha256']
    before=copy.deepcopy(measured);state['timestamps']['follower']['end']['monotonic_ns']=0
    assert measured==before

@pytest.mark.parametrize('bad',['moving','stale','future','skew','resolution','float_image','missing_history','passive_command','unknown_mapping','order','nonfinite','nan_pair'])
def test_snapshot_rejects_false_sensor_evidence(snapshot,bad):
    state,images,profile=snapshot
    if bad=='moving':state['real_stability']['stable']=False
    elif bad=='stale':state['timestamps']['real_cameras']['real_side']['read_end']['monotonic_ns']=700000000
    elif bad=='future':state['timestamps']['real_cameras']['real_side']['read_end']['monotonic_ns']=1100000000
    elif bad=='skew':state['timestamps']['real_cameras']['real_side']['read_end']['monotonic_ns']=850000000
    elif bad=='resolution':images['real_side']=images['real_side'][:20]
    elif bad=='float_image':images['real_side']=images['real_side'].astype(float)
    elif bad=='missing_history':state['measured_samples']=[]
    elif bad=='passive_command':state['sent_target']=state['physical_follower_measured_joint_state']
    elif bad=='unknown_mapping':state['sim_joint_mapping']={'schema':'UNKNOWN'}
    elif bad=='order':state['joint_names'].reverse()
    elif bad=='nonfinite':state['physical_follower_measured_joint_state']['gripper']=np.nan
    else:
        with pytest.raises(ValueError):pair(arm=np.nan)
        return
    with pytest.raises(ValueError):c.prepare_snapshot(state,images,profile,now_ns=1010000000)


def test_blur_warns_and_excludes_calibration_without_fabricating_image(snapshot):
    state,images,profile=snapshot;images['real_side'][:]=0
    measured,observed,warnings=c.prepare_snapshot(state,images,profile,now_ns=1010000000)
    assert warnings and observed[0]['eligible'] is False and observed[1]['eligible'] is True


def test_real_fake_camera_thread_bounded_and_released():
    calls=[];gate=Event()
    def read():gate.wait(.002);return np.zeros((2,3,3),np.uint8)
    camera=NS(is_connected=False,read=read)
    def connect():camera.is_connected=True;calls.append('connect')
    def disconnect():camera.is_connected=False;calls.append('disconnect');gate.set()
    camera.connect=connect;camera.disconnect=disconnect
    reader=CameraReader(camera,device='fake',resolution=(3,2));reader.start()
    import time
    until=time.monotonic()+2
    while reader.nearest() is None and time.monotonic()<until:gate.wait(.002)
    assert reader.nearest() is not None
    reader.close();reader.close();assert calls==['connect','disconnect'] and not reader.thread.is_alive()


def test_partial_profile_uses_raw_gripper_evidence_beyond_sdk_saturation():
    from robot_learning_workbench.robot.calibration import PrecisionMapper,native_from_raw,raw_from_native
    _,full=bound('follower');p=copy.deepcopy(full.profile);p['joints']={'shoulder_pan':p['joints']['shoulder_pan']};mapper=PrecisionMapper(p)
    native=dict.fromkeys(JOINTS,0.);specs={n:e['motor'] for n,e in full.profile['joints'].items()}
    raw={n:raw_from_native(native[n],specs[n]) for n in JOINTS};raw['gripper']=specs['gripper']['calibration']['range_max']+10;native['gripper']=100
    q=c.observed_positions(mapper,native,raw=raw,motor_specs=specs)
    assert q['gripper']>np.deg2rad(100)


def test_stability_owns_tip_samples_and_rejects_nonfinite():
    s=c.Stability();tip=np.ones(3);s.add(0,dict.fromkeys(JOINTS,0.),tip);tip[:]=0
    assert s.history[-1][2].all()
    with pytest.raises(ValueError):s.add(1,dict.fromkeys(JOINTS,np.nan))
