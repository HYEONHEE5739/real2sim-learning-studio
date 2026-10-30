"""Reference-angle workflow; observation only, immutable profiles and explicit activation."""
from pathlib import Path
import copy,math,time,uuid
import yaml
from .calibration import JOINTS,SCHEMA,LEGACY_MAPPER,joint_specs,joint_angle,fit_joint,review_joint,validate_joint,load_profile,profile_for_model,PrecisionMapper,fingerprint
from .devices import serial_lease
from ..data.native import atomic_json,file_sha256


class PrecisionSession:
    def __init__(self,workspace,configuration,role,robot_model,device,*,events):
        self.workspace=Path(workspace).resolve();self.configuration=Path(configuration).resolve();self.model=Path(robot_model).resolve();self.device=device;self.events=events
        if role not in('leader','follower')or not self.configuration.is_relative_to(self.workspace/'devices')or not self.model.is_relative_to(self.workspace):raise ValueError('Owned device configuration/model and explicit robot role required')
        self.role=role;self.config_hash=file_sha256(self.configuration);self.model_hash=file_sha256(self.model);self.config=yaml.safe_load(self.configuration.read_text());self.specs=joint_specs(self.model)
        self.identity=copy.deepcopy(device.identity);self.references={n:[]for n in JOINTS};self.candidates={};self.saved={};self.connected=False;self.lease=None
        key='calibration_profile'if role=='follower'else'leader_calibration_profile';self.source_profile=None;self.profile={}
        if key in self.config['inputs']:
            self.source_profile=(self.configuration.parent/self.config['inputs'][key]).resolve()
            if not self.source_profile.is_relative_to(self.workspace):raise ValueError('Existing Precision profile must be workspace-owned')
            self.profile=load_profile(self.source_profile,role=role)
            expected={k:v for k,v in self.identity.items()if k!='port'};saved={k:v for k,v in self.profile['identity'].items()if k!='port'}
            if expected!=saved:raise ValueError('Source Precision device identity differs')
            self.profile['identity']=copy.deepcopy(self.identity)
            if self.profile['urdf_sha256']!=self.model_hash:
                source=(self.configuration.parent/self.config['inputs']['source_robot_model']).resolve()
                if not source.is_relative_to(self.workspace):raise ValueError('Source model evidence must be workspace-owned')
                self.profile=profile_for_model(self.profile,self.model_hash,source_model=source.read_bytes(),execution_model=self.model.read_bytes())
        self.source_hash=file_sha256(self.source_profile)if self.source_profile else None
    def unchanged(self):
        if self.device.identity!=self.identity or not self.device.unchanged():raise ValueError('Device/calibration identity changed')
        if file_sha256(self.configuration)!=self.config_hash or file_sha256(self.model)!=self.model_hash:raise ValueError('Configuration/model changed')
        if self.source_profile and file_sha256(self.source_profile)!=self.source_hash:raise ValueError('Source Precision profile changed')
    def connect(self):
        if self.connected:raise ValueError('Precision session already connected')
        try:
            self.lease=serial_lease(self.identity['port']);self.device.connect();self.unchanged();self.connected=True
        except BaseException:self.close();raise
    def close(self):
        try:self.device.close()
        finally:
            self.connected=False
            if self.lease:self.lease.close();self.lease=None
    def measure(self,joint):
        self.unchanged();sample=self.device.sample(joint,live=True);entry=self.profile.get('joints',{}).get(joint)
        errors={};candidate=self.candidates.get(joint)
        def mapped(e,label):
            try:return joint_angle(e,sample['raw'])if e else None
            except ValueError as error:errors[label]=str(error);return None
        before=mapped(entry,'before')if entry else LEGACY_MAPPER.calibrated_to_urdf({**dict.fromkeys(JOINTS,0.),joint:sample['legacy_position']})[joint]
        return {**sample,'before_model_rad':before,'after_model_rad':mapped(candidate,'after'),'mapping_errors':errors,'physical_verified':False}
    def command(self,kind,payload):
        if not self.connected:raise ValueError('Connect the selected Calibration device first')
        self.unchanged();joint=payload.get('joint')
        if kind in('precision_record','precision_fit','precision_review')and joint not in JOINTS:raise ValueError('Select a named robot joint')
        if kind=='precision_record':
            angle=payload['angle_rad'];split=payload['split']
            if type(angle)not in(int,float)or not math.isfinite(angle)or not self.specs[joint]['limits'][0]<=angle<=self.specs[joint]['limits'][1]:raise ValueError('Finite reference angle inside URDF limits required')
            if split not in('train','validation'):raise ValueError('Explicit train/validation reference split required')
            sample=self.measure(joint)
            if sample['torque']!=0:raise ValueError('Torque must already be off; support the arm and move it manually')
            row={**sample,'reference_id':uuid.uuid4().hex,'angle_rad':float(angle),'split':split,'reference_kind':'angle','opening_m':None,'evidence':'estimated/manual'}
            self.references[joint].append(row);self.candidates.pop(joint,None);return row
        if kind=='precision_fit':
            candidate=fit_joint(self.references[joint],self.device.motor_spec(joint),joint,self.specs[joint]['limits'],reference_mode='angle');self.candidates[joint]=candidate;return candidate
        if kind=='precision_review':
            candidate=self.candidates[joint];fn=validate_joint if payload['independent']else review_joint
            candidate=fn(candidate,payload['tolerance_deg']);self.candidates[joint]=candidate;return candidate
        if kind=='precision_save':return self.save()
        if kind=='precision_activate':return self.activate(payload['path'],payload['approved'])
        if kind=='precision_remove':
            for n,rows in self.references.items():
                if any(r['reference_id']==payload['reference_id']for r in rows):self.references[n]=[r for r in rows if r['reference_id']!=payload['reference_id']];self.candidates.pop(n,None);return {'removed':payload['reference_id']}
            raise ValueError('Unknown session reference')
        raise ValueError('Unsupported Precision command')

    def save(self):
        if any(rows and n not in self.candidates for n,rows in self.references.items()):raise ValueError('Fit and review every newly recorded joint before saving')
        if not self.candidates or any(e['status']not in('REVIEWED_MANUAL','VALIDATED_MANUAL')for e in self.candidates.values()):raise ValueError('Review/validation is required before saving a Precision revision')
        profile=copy.deepcopy(self.profile);joints=profile.get('joints',{});joints.update(copy.deepcopy(self.candidates))
        profile.update(schema=SCHEMA,id='profile_'+uuid.uuid4().hex,role=self.role,identity=copy.deepcopy(self.identity),urdf_sha256=self.model_hash,joints=joints,created_ns=time.time_ns(),physical_verified=False)
        profile.pop('runtime_model_binding',None)
        if self.source_profile:profile.update(parent_sha256=self.source_hash,parent_path=str(self.source_profile))
        PrecisionMapper(profile);path=self.workspace/'calibration'/self.role/(profile['id']+'.json');path.parent.mkdir(parents=True,exist_ok=True);atomic_json(path,profile,exclusive=True);self.saved[str(path)]={'sha256':file_sha256(path),'draft_sha256':self.draft_identity()}
        return {'path':str(path),'sha256':self.saved[str(path)]['sha256'],'physical_verified':False}

    def draft_identity(self):return fingerprint({'references':self.references,'candidates':self.candidates})

    def activate(self,path,approved):
        if approved is not True:raise ValueError('Explicit user approval required before applying a Precision profile')
        path=Path(path).resolve()
        saved=self.saved.get(str(path))
        if not saved or file_sha256(path)!=saved['sha256']:raise ValueError('Choose an unchanged profile saved by this session')
        if self.draft_identity()!=saved['draft_sha256']:raise ValueError('Stale saved profile: reference/fit/review draft changed; save the current reviewed revision')
        load_profile(path,expected_sha256=saved['sha256'],role=self.role,identity=self.identity)
        from .registration import save_configuration
        configuration=copy.deepcopy(self.config);configuration['inputs']={k:str((self.configuration.parent/v).resolve())for k,v in configuration['inputs'].items()}
        key='calibration_profile'if self.role=='follower'else'leader_calibration_profile';configuration['inputs'][key]=str(path)
        configuration['inputs']['robot_model']=str(self.model)
        if {'calibration_profile','leader_calibration_profile','device_profile','leader_device_profile','camera_config'}<=configuration['inputs'].keys():configuration['stage']='capture_session'
        target=save_configuration(self.workspace,'precision-'+self.role,configuration)
        return {'configuration_path':str(target),'source_configuration_path':str(self.configuration),'profile_path':str(path),'physical_verified':False,'registers_written':False}


def construct(plan,*,events):
    from ..recipe import _plain
    from .devices import CalibrationDevice
    configuration=Path(plan.resolved_inputs['configuration']['path']);workspace=configuration.parent.parent.parent
    if configuration.parent.parent.name!='devices':raise ValueError('Select a saved workspace/devices configuration')
    role=plan.effective_settings['execution']['role'];spec=_plain(plan.input_documents['device_profile']);data=yaml.safe_load(configuration.read_text())
    key='device_profile'if role=='follower'else'leader_device_profile'
    if spec['role']!=role or(configuration.parent/data['inputs'][key]).resolve()!=Path(plan.resolved_inputs['device_profile']['path']):raise ValueError('Selected device is not the configured robot role')
    calibration=Path(spec['calibration_path']).resolve()
    if not calibration.is_relative_to(workspace)or not calibration.is_file():raise ValueError('Existing workspace-owned SDK Calibration required before reference-angle calibration')
    memory=plan.effective_settings['execution']['device_source']=='memory'
    if not memory:
        from .registration import resolve_serial
        spec['sdk']['port']=resolve_serial(spec['usb_identity'])
    from .configuration import observation_configuration
    cfg=observation_configuration(spec)
    if memory:
        from .teleoperation import fake_device
        if 'calibration_profile'not in plan.resolved_inputs:raise ValueError('Memory SDK arithmetic needs an explicit reference Profile fixture')
        profile=load_profile(plan.resolved_inputs['calibration_profile']['path'],role=role);spec['sdk']['port']=str(plan.output_path/('memory-'+role));profile['identity']['port']=spec['sdk']['port']
        observer=fake_device(spec,profile);sdk=observer.device;identity=observer.identity
    else:
        if role=='follower':
            from lerobot.robots.so101_follower.so101_follower import SO101Follower
            sdk=SO101Follower(cfg)
        else:
            from lerobot.teleoperators.so101_leader.so101_leader import SO101Leader
            sdk=SO101Leader(cfg)
        identity={'role':role,'port':str(Path(cfg.port).resolve()),'id':calibration.name if role=='leader'else cfg.id,'calibration_sha256':file_sha256(calibration),'motors':{n:{'id':m.id,'model':m.model}for n,m in sdk.bus.motors.items()}}
    device=CalibrationDevice(sdk,role=role,identity=identity,calibration_path=calibration,kernel_exclusive=not memory)
    return PrecisionSession(workspace,configuration,role,plan.resolved_inputs['robot_model']['path'],device,events=events)


def run(plan,*,events,commands):
    from ..recipe import verify_prepared_inputs
    from ..run import StageResult
    verify_prepared_inputs(plan);session=construct(plan,events=events);plan.output_path.mkdir();joint=JOINTS[0];seen=set();cancelled=False;error=None;heartbeat=time.monotonic_ns()
    def emit(**payload):events({'kind':'status','payload':{'progress':{'precision_state':'CONNECTED','role':session.role,**payload}}})
    def ack(c,status='completed',reason=None):events({'kind':'command_ack','payload':{'command_id':c['command_id'],'status':status,**({'reason':reason}if reason else{})}})
    try:
        session.connect();running=True
        while running:
            begin=time.monotonic();batch=list(commands());stops=[c for c in batch if c['kind']in('cancel','session_disconnect','session_finish')]
            for c in batch:
                if c['kind']=='session_heartbeat':
                    stamp=c['payload']['timestamp_ns']
                    if 0<=time.monotonic_ns()-stamp<=1_000_000_000:heartbeat=stamp
                    continue
                if c['command_id']in seen:continue
                seen.add(c['command_id'])
                if stops:
                    ack(c,'completed'if c in stops else'rejected','Stop/cancel takes precedence');running=False;cancelled|=any(s['kind']=='cancel'for s in stops);continue
                try:
                    verify_prepared_inputs(plan)
                    if c['kind']=='precision_select':joint=c['payload']['joint'];result={'joint':joint}
                    else:result=session.command(c['kind'],c['payload'])
                    emit(precision_result={'kind':c['kind'],'result':result,'joint':joint,'references':session.references[joint],'candidate':session.candidates.get(joint)});ack(c)
                except Exception as failure:ack(c,'rejected',str(failure));emit(error=str(failure))
            if not running:break
            if time.monotonic_ns()-heartbeat>3_000_000_000:raise TimeoutError('Precision UI heartbeat lost; closing read-only device')
            emit(current_measurement=session.measure(joint));time.sleep(max(0,.1-(time.monotonic()-begin)))
    except Exception as failure:error=str(failure);raise
    finally:
        try:session.close()
        finally:atomic_json(plan.output_path/'precision-report.json',{'state':'FAILED'if error else'DISCONNECTED','error':error,'role':session.role,'references':session.references,'saved_profiles':session.saved,'goal_commands':0,'torque_commands':0,'physical_verified':False})
    return StageResult('cancelled'if cancelled else'completed',(str(plan.output_path),),0,{'saved_profiles':len(session.saved),'physical_verified':False})
