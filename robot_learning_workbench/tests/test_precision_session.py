"""Reference-angle calibration through one read-only session; no physical driver."""
import copy,hashlib,json,math,time
from pathlib import Path

import pytest,yaml

from robot_learning_workbench.robot.calibration import JOINTS,load_profile,native_from_raw

R=Path(__file__).resolve().parents[2]


class MemoryCalibrationDevice:
    """The existing CalibrationDevice sample/identity boundary, without a serial bus."""
    def __init__(self,spec,profile):
        self.role=spec['role'];self.identity=copy.deepcopy(profile['identity']);self.calibration_path=Path(spec['calibration_path'])
        self.profile=profile;self.raw=dict.fromkeys(JOINTS,1500);self.torque=0;self.connected=False;self.exclusive=False;self.trace=[]
        self.original_identity=copy.deepcopy(self.identity)
    def connect(self):self.trace.append('connect');self.connected=True;self.exclusive=True
    def close(self):self.trace.append('close');self.connected=False;self.exclusive=False
    def unchanged(self):
        return self.identity==self.original_identity and hashlib.sha256(self.calibration_path.read_bytes()).hexdigest()==self.identity['calibration_sha256']
    def motor_spec(self,joint):return copy.deepcopy(self.profile['joints'][joint]['motor'])
    def sample(self,joint,live=False):
        assert self.connected and self.unchanged(),'Selected device/calibration changed'
        self.trace.append('sample');now=time.monotonic_ns();spec=self.motor_spec(joint)
        return {'joint':joint,'raw':self.raw[joint],'legacy_position':native_from_raw(self.raw[joint],spec),'torque':self.torque,
                'timestamp_ns':now,'read_start_ns':now,'raw_timestamp_ns':now,'native_timestamp_ns':now,
                'native_source':'normalized_same_raw_packet','clock':'host_monotonic_ns; not hardware synchronized',
                'device_identity':copy.deepcopy(self.identity),'calibration_hash':self.identity['calibration_sha256'],'motor':spec}


def precision_fixture(tmp_path):
    """Own the small SDK/Profile/URDF inputs; don't depend on deleted USD/weights."""
    from robot_learning_workbench.robot.precision import PrecisionSession
    source=R/'workbench_runs/devices/so101-pickplace-0b794e7c/capture.yaml';source_data=yaml.safe_load(source.read_text())
    workspace=tmp_path/'workspace';directory=workspace/'devices/original';directory.mkdir(parents=True)
    data=copy.deepcopy(source_data);data['inputs']={};data['execution']={'device_source':'memory'};data['output']={'directory':'unused'}
    model=directory/'source-model.urdf';model.write_bytes(Path(source_data['inputs']['source_robot_model']).read_bytes());data['inputs']['robot_model']=str(model)
    specs={};profiles={}
    for role,dk,pk in(('follower','device_profile','calibration_profile'),('leader','leader_device_profile','leader_calibration_profile')):
        spec=json.loads(Path(source_data['inputs'][dk]).read_text());profile=json.loads(Path(source_data['inputs'][pk]).read_text())
        sdk_path=directory/'sdk'/role/Path(spec['calibration_path']).name;sdk_path.parent.mkdir(parents=True);sdk_path.write_bytes(Path(spec['calibration_path']).read_bytes())
        spec['calibration_path']=str(sdk_path);spec['sdk']['calibration_dir']=str(sdk_path.parent);spec['sdk']['port']=str(directory/('memory-'+role));profile['identity']['port']=spec['sdk']['port']
        assert hashlib.sha256(model.read_bytes()).hexdigest()==profile['urdf_sha256']
        device_path=directory/(role+'-device.json');device_path.write_text(json.dumps(spec));profile_path=directory/(role+'-profile.json');profile_path.write_text(json.dumps(profile))
        data['inputs'].update({dk:str(device_path),pk:str(profile_path)});specs[role]=spec;profiles[role]=profile
    camera=directory/'cameras.json';camera.write_bytes(Path(source_data['inputs']['camera_config']).read_bytes());data['inputs']['camera_config']=str(camera)
    configuration=directory/'capture.yaml';configuration.write_text(yaml.safe_dump(data));device=MemoryCalibrationDevice(specs['follower'],profiles['follower']);events=[]
    session=PrecisionSession(workspace,configuration,'follower',model,device,events=events.append)
    return session,device,workspace,configuration,Path(data['inputs']['calibration_profile']),events


def recorded_candidate(session,device):
    for raw,angle,split in((1500,0.,'train'),(2500,math.pi/2,'train'),(2000,math.pi/4,'validation')):
        device.raw['shoulder_pan']=raw
        session.command('precision_record',{'joint':'shoulder_pan','angle_rad':angle,'split':split})
    return session.command('precision_fit',{'joint':'shoulder_pan'})


def test_zero_reference_fit_independent_review_save_and_explicit_activation(tmp_path):
    session,device,workspace,configuration,old_profile,_=precision_fixture(tmp_path);original_config=configuration.read_bytes();original_profile=old_profile.read_bytes()
    try:
        session.connect();candidate=recorded_candidate(session,device)
        assert candidate['status']=='CANDIDATE_NEEDS_VALIDATION'
        with pytest.raises(ValueError,match='review|Review|validat|VALIDAT'):session.command('precision_save',{})
        reviewed=session.command('precision_review',{'joint':'shoulder_pan','tolerance_deg':.5,'independent':True})
        assert reviewed['status']=='VALIDATED_MANUAL'and reviewed['physical_verified']is False
        saved=session.command('precision_save',{});path=Path(saved['path']);assert path.is_relative_to(workspace/'calibration')
        profile=load_profile(path);assert profile['identity']==device.identity and profile['urdf_sha256']==hashlib.sha256((configuration.parent/'source-model.urdf').read_bytes()).hexdigest()
        assert profile['physical_verified']is False and abs(profile['joints']['shoulder_pan']['reference_angle_rad'])<1e-12
        with pytest.raises(ValueError,match='approv|승인'):session.command('precision_activate',{'path':str(path),'approved':False})
        result=session.command('precision_activate',{'path':str(path),'approved':True});new_config=Path(result['configuration_path'])
        assert new_config!=configuration and new_config.is_relative_to(workspace/'devices')
        updated=yaml.safe_load(new_config.read_text());assert Path(updated['inputs']['calibration_profile']).resolve()==path.resolve()
        assert result['source_configuration_path']==str(configuration)
        assert configuration.read_bytes()==original_config and old_profile.read_bytes()==original_profile
        assert session.command('precision_save',{})['path']!=str(old_profile)
        assert set(device.trace)<={'connect','sample'}
    finally:session.close()
    assert not device.connected and device.torque==0


def test_reference_capture_requires_supported_unpowered_pose_and_model_range(tmp_path):
    session,device,_,configuration,old_profile,_=precision_fixture(tmp_path);before=(configuration.read_bytes(),old_profile.read_bytes())
    try:
        session.connect();device.torque=1
        with pytest.raises((ValueError,RuntimeError),match='[Tt]orque|토크'):session.command('precision_record',{'joint':'shoulder_pan','angle_rad':0.,'split':'train'})
        device.torque=0
        with pytest.raises(ValueError,match='limit|range|범위'):session.command('precision_record',{'joint':'shoulder_pan','angle_rad':100.,'split':'train'})
        with pytest.raises(ValueError):session.command('precision_record',{'joint':'shoulder_pan','angle_rad':float('nan'),'split':'train'})
        assert (configuration.read_bytes(),old_profile.read_bytes())==before
        assert set(device.trace)<={'connect','sample'}
    finally:session.close()


def test_changed_sdk_identity_cannot_activate_a_saved_profile(tmp_path):
    session,device,_,configuration,old_profile,_=precision_fixture(tmp_path);before=(configuration.read_bytes(),old_profile.read_bytes())
    try:
        session.connect();recorded_candidate(session,device);session.command('precision_review',{'joint':'shoulder_pan','tolerance_deg':.5,'independent':True});saved=session.command('precision_save',{})
        device.identity['id']='different-follower'
        with pytest.raises((ValueError,AssertionError,RuntimeError),match='identity|Identity|changed|calibration|device'):session.command('precision_activate',{'path':saved['path'],'approved':True})
        assert (configuration.read_bytes(),old_profile.read_bytes())==before
        assert set(device.trace)<={'connect','sample'}
    finally:session.close()


def test_precision_recipe_and_worker_commands_pin_owned_inputs_without_connecting(tmp_path):
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.run import _command
    from robot_learning_workbench.robot.precision import construct
    session,_,workspace,configuration,_,_=precision_fixture(tmp_path);data=yaml.safe_load(configuration.read_text())
    path=workspace/'precision.yaml';path.write_text(yaml.safe_dump({'schema_version':1,'stage':'precision_session','inputs':{'configuration':str(configuration),'device_profile':data['inputs']['device_profile'],'calibration_profile':data['inputs']['calibration_profile'],'robot_model':data['inputs']['robot_model']},'execution':{'device_source':'memory','role':'follower'},'output':{'directory':str(workspace/'precision-output')}}))
    plan=prepare_recipe(read_recipe(path));prepared=construct(plan,events=lambda e:None)
    assert not prepared.connected
    assert _command({'command_id':'zero','kind':'precision_record','payload':{'joint':'shoulder_pan','angle_rad':0.,'split':'train'}})['kind']=='precision_record'
    with pytest.raises(Exception):_command({'command_id':'bad','kind':'precision_record','payload':{'joint':'shoulder_pan','angle_rad':float('nan'),'split':'train'}})


def test_production_precision_runner_reads_memory_sdk_and_closes_without_motion(tmp_path):
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.robot.precision import run
    _,_,workspace,configuration,_,_=precision_fixture(tmp_path);data=yaml.safe_load(configuration.read_text())
    path=workspace/'precision-run.yaml';path.write_text(yaml.safe_dump({'schema_version':1,'stage':'precision_session','inputs':{'configuration':str(configuration),'device_profile':data['inputs']['device_profile'],'calibration_profile':data['inputs']['calibration_profile'],'robot_model':data['inputs']['robot_model']},'execution':{'device_source':'memory','role':'follower'},'output':{'directory':str(workspace/'run-output')}}))
    from robot_learning_workbench import run as worker
    doc=read_recipe(path);plan=prepare_recipe(doc)
    handle=worker.start(worker.StartRequest('precision-smoke',path,doc.sha256,'precision_session',plan.output_path,expected_prepared_sha256=plan.sha256))
    deadline=time.monotonic()+12;recorded=False;finished=False
    try:
        while time.monotonic()<deadline:
            status=worker.read_status(handle.run_dir).status
            if status in('completed','failed','cancelled','unknown'):break
            worker.touch_session(handle,time.monotonic_ns())
            events=worker.read_events(handle.run_dir,limit=200).items
            if not recorded and any(e['kind']=='status'and e['payload'].get('progress',{}).get('current_measurement')for e in events):
                worker.send_command(handle,{'command_id':'zero','kind':'precision_record','payload':{'joint':'shoulder_pan','angle_rad':0.,'split':'train'}});recorded=True
            if recorded and (handle.run_dir/'acks/zero.json').exists()and json.loads((handle.run_dir/'acks/zero.json').read_text())['status']=='completed'and not finished:
                worker.send_command(handle,{'command_id':'end','kind':'session_finish','payload':{}});finished=True
            time.sleep(.03)
        assert worker.read_status(handle.run_dir).status=='completed',json.loads((handle.run_dir/'run.json').read_text())
        report=json.loads((plan.output_path/'precision-report.json').read_text());assert report['goal_commands']==report['torque_commands']==0 and len(report['references']['shoulder_pan'])==1
    finally:
        if worker.read_status(handle.run_dir).status not in('completed','failed','cancelled','unknown'):
            worker.send_command(handle,{'command_id':'cancel-test','kind':'cancel','payload':{}})
            end=time.monotonic()+5
            while time.monotonic()<end and worker.read_status(handle.run_dir).status not in('completed','failed','cancelled','unknown'):time.sleep(.05)
