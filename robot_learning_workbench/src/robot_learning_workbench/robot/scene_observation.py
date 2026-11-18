"""Unbound camera/SDK observations for Scene preparation; no model or command authority."""
from pathlib import Path
import time,hashlib,copy,uuid
from .devices import stamp,close_devices,serial_lease
from .calibration import JOINTS,values
from ..data.native import atomic_json,file_sha256


class SDKObservation:
    """Official SDK read boundary before a user Precision/model binding exists."""
    def __init__(self,device,spec,calibration):
        self.device=device;self.bus=device.bus;self.spec=spec;self.calibration=Path(calibration);self.connected=False;self.lease=None;self.last_raw=None
        self.calibration_sha256=file_sha256(self.calibration)if self.calibration.is_file()else None
    def connect(self):
        from .registration import resolve_serial
        if not self.calibration_sha256:raise ValueError('SDK Calibration required: use the supervised calibration procedure first')
        if file_sha256(self.calibration)!=self.calibration_sha256:raise ValueError('SDK Calibration changed')
        if resolve_serial(self.spec['usb_identity'])!=self.bus.port:raise ValueError('USB identity changed')
        self.lease=serial_lease(self.bus.port)
        try:
            self.bus.connect()  # Never official device.connect/configure: they may enable torque.
            if not self.device.is_calibrated:raise ValueError('SDK calibration/register mismatch; no automatic writes')
            if set(self.bus.motors)!=set(JOINTS):raise ValueError('SO101 joint mapping mismatch')
            self.connected=True
        except BaseException:self.close();raise
    def read(self):
        if not self.connected:raise ValueError('Observation device disconnected')
        begin=stamp();raw=self.bus.sync_read('Present_Position',normalize=False);values(raw)
        native=self.bus._normalize({self.bus.motors[n].id:v for n,v in raw.items()});self.last_raw=dict(raw)
        return values({n:native[self.bus.motors[n].id]for n in JOINTS}),{'start':begin,'end':stamp()}
    def close(self):
        try:
            if self.device.is_connected:self.bus.disconnect(disable_torque=False)
        finally:
            self.connected=False
            if self.lease:self.lease.close();self.lease=None


def construct(plan):
    from ..recipe import _plain
    from .devices import CameraReader
    from .offline import sdk_configuration
    devices={}
    for key in('device_profile','leader_device_profile'):
        if key not in plan.input_documents:continue
        spec=_plain(plan.input_documents[key]);calibration=Path(spec['calibration_path'])
        from .registration import resolve_serial
        spec['sdk']['port']=resolve_serial(spec['usb_identity']);cfg=sdk_configuration(spec)
        if Path(cfg.calibration_dir).resolve()!=calibration.parent or calibration.name!=cfg.id+'.json':raise ValueError('SDK calibration ownership mismatch')
        if spec['role']=='follower':
            from lerobot.robots.so101_follower.so101_follower import SO101Follower
            device=SO101Follower(cfg)
        else:
            from lerobot.teleoperators.so101_leader.so101_leader import SO101Leader
            device=SO101Leader(cfg)
        devices[spec['role']]=SDKObservation(device,spec,calibration)
    cameras={};configs=_plain(plan.input_documents['camera_config'])['cameras']
    if set(configs)!={'side','wrist'}:raise ValueError('Select Side/Wrist cameras')
    paths=[]
    for name,settings in configs.items():
        from lerobot.cameras.opencv.configuration_opencv import OpenCVCameraConfig
        cfg=OpenCVCameraConfig(**settings)
        if(cfg.width,cfg.height,cfg.fps)!=(640,480,30):raise ValueError('Original640x480 requested30FPS required')
        paths.append(str(Path(str(cfg.index_or_path)).resolve()));cameras[name]=CameraReader.from_config(cfg)
    if len(set(paths))!=2:raise ValueError('Select distinct cameras')
    return devices,cameras


def save_materials(project,session_id,key,packets,feedback,*,now_ns=None,request=None):
    """Existing Builder images/documents; no new Dataset or model Snapshot schema."""
    import os
    from PIL import Image
    from real2sim_builder.evidence import register_observation_images
    from real2sim_builder.files import write,sha,read
    from real2sim_builder.scene import identifier
    identifier(session_id);identifier(key)
    started=time.monotonic_ns()
    now=time.monotonic_ns()if now_ns is None else now_ns
    if set(packets)!={'side','wrist'}or any(p is None for p in packets.values()):raise ValueError('Both camera observations required')
    times=[]
    for p in packets.values():
        t=p['read_end']['monotonic_ns'];times.append(t)
        if not p['read_start']['monotonic_ns']<=t<=now or now-t>200000000:raise ValueError('Camera stale; retry Capture')
        if p['rgb'].shape!=(480,640,3)or str(p['rgb'].dtype)!='uint8':raise ValueError('Original640x480 RGB required')
    if feedback:
        t=feedback['interval']['end']['monotonic_ns'];times.append(t)
        if t>now or now-t>200000000:raise ValueError('SDK feedback stale')
    if max(times)-min(times)>100000000:raise ValueError('Observation skew exceeds100ms')
    if request:
        if not 0<request['requested_ns']<=request['received_ns']<=request['observed_ns'] or request['observed_ns']!=now:
            raise ValueError('Invalid observation request timestamp order')
        if any(p['read_end']['monotonic_ns']>request['requested_ns']for p in packets.values()):
            raise ValueError('Camera observation is after the requested time')
        if feedback and feedback['interval']['end']['monotonic_ns']>request['requested_ns']:
            raise ValueError('SDK observation is after the requested time')
    root=project.root/'input/observations'/session_id/key
    images={name:str(root/(name+'.png'))for name in packets}
    record={'session_id':session_id,'timestamp_kind':'host_receipt_not_exposure','hardware_synchronized':False,'model_state':None,'action':None,'sdk_feedback':feedback,'camera_timing':{n:{k:p[k]for k in('read_start','read_end','sequence')}for n,p in packets.items()},'eligible_for_calibration':False,'reason':'Unbound reference observations; model/Precision/camera calibration unverified'}
    record['capture_request']=request
    record['pixel_sha256']={n:hashlib.sha256(p['rgb'].tobytes()).hexdigest()for n,p in packets.items()}
    if root.exists():
        if not(root/'COMPLETE').is_file():raise ValueError('Partial original observation retained; inspect before retrying')
        seal=read(root/'COMPLETE')
        if seal.get('observation_sha256')!=sha(root/'observation.json'):raise ValueError('Sealed observation metadata changed')
        previous=read(root/'observation.json')
        expected={k:v for k,v in previous.items()if k!='image_sha256'}
        if expected!=record:raise ValueError('Observation key reused with different original inputs')
        record=previous
        for name in packets:
            if sha(root/(name+'.png'))!=record['image_sha256'][name]:raise ValueError('Original observation image changed')
    else:
        root.mkdir(parents=True)
        for name,p in packets.items():
            path=root/(name+'.png');Image.fromarray(p['rgb']).save(path,compress_level=1)
            with path.open('rb')as stream:os.fsync(stream.fileno())
        record['image_sha256']={n:sha(root/(n+'.png'))for n in packets}
        write(root/'observation.json',record)
        atomic_json(root/'COMPLETE',{'sealed':True,'observation_sha256':sha(root/'observation.json')})
    raw_saved=time.monotonic_ns()
    register_observation_images(project,root)
    registered=time.monotonic_ns()
    return {'id':key,'session_id':session_id,'path':str(root),'unix_ns':packets['side']['read_end']['unix_ns'],'q_measured':[],'images':images,'quality':[record['reason']],'paired':False,'kind':'scene_materials',
        'status':'SAVED','phase':'REGISTERED','request':request,
        'processing_times_ns':{'raw_saved_ns':raw_saved,'registration_completed_ns':registered},
        'save_timing_ms':{'raw_save':(raw_saved-started)/1e6,'registration':(registered-raw_saved)/1e6,'total':(registered-started)/1e6}}


def recover_materials(project,folder):
    """Explicit registration retry of the same sealed originals, never recapture."""
    from PIL import Image
    from real2sim_builder.files import read
    import numpy as np
    folder=Path(folder).resolve()
    if not folder.is_relative_to((project.root/'input/observations').resolve())or not(folder/'COMPLETE').is_file():
        raise ValueError('Choose a sealed observation owned by this Project')
    record=read(folder/'observation.json')
    if read(folder/'COMPLETE').get('observation_sha256')!=__import__('hashlib').sha256((folder/'observation.json').read_bytes()).hexdigest():
        raise ValueError('Sealed observation metadata changed')
    packets={n:{**row,'rgb':np.asarray(Image.open(folder/(n+'.png')).convert('RGB')).copy()}for n,row in record['camera_timing'].items()}
    request=record.get('capture_request')
    now=request['observed_ns']if request else max(p['read_end']['monotonic_ns']for p in packets.values())
    return save_materials(project,record['session_id'],folder.name,packets,record.get('sdk_feedback'),now_ns=now,request=request)


def freeze_material_observation(cameras,feedback_history,requested_ns,sequences):
    now=time.monotonic_ns()
    if type(requested_ns)is not int or not 0<requested_ns<=now or now-requested_ns>1_000_000_000:
        raise ValueError('Capture request is outside the observation buffer window')
    packets={n:camera.nearest(requested_ns,not_after=True)for n,camera in cameras.items()}
    if any(p is None or p['sequence']<=sequences.get(n,-1)or now-p['read_end']['monotonic_ns']>200_000_000 for n,p in packets.items()):
        raise ValueError('No new camera frame at the requested time; retry Capture')
    feedback=None
    if feedback_history:
        feedback=next((copy.deepcopy(row)for row in reversed(feedback_history)if row['interval']['end']['monotonic_ns']<=requested_ns),None)
        if feedback is None:raise ValueError('No SDK feedback at the requested time')
    return packets,feedback,dict(requested_ns=requested_ns,received_ns=now,observed_ns=time.monotonic_ns(),
        clock_domain='host_monotonic_ns',timestamp_kind='host_receipt_not_exposure')


def run(plan,*,events,commands):
    from real2sim_builder.project import Project
    from ..recipe import verify_prepared_inputs
    from ..run import StageResult
    from ..data import video
    verify_prepared_inputs(plan);devices,cameras=construct(plan);project=Project(plan.resolved_inputs['project']['root']);plan.output_path.mkdir()
    from collections import deque
    from .snapshots import snapshot_writer,writer_ready,save_snapshot
    session_id=plan.output_path.name.replace('-','_')
    writer=snapshot_writer(project=project,session_id=session_id)
    last_heartbeat=time.monotonic_ns();rows=[];sequences={};jobs={};failures=[];cancelled=False;error=None;finished=False;feedback_history=deque(maxlen=90)
    def emit(**p):events({'kind':'status','payload':{'progress':{'session_state':'OBSERVING','teleop_active':False,'device_source':'hardware','teleoperation_available':False,
        'teleoperation_reason':'관측 전용 구성 · Teleoperation에는 검증된 Model/Precision 결합과 명령 제한이 필요합니다.','capture_request_allowed':not finished and len(jobs)<2,
        'capture_queue_size':len(jobs),'capture_queue_capacity':2,'capture_pending':bool(jobs),**p}}})
    def ack(c,status='completed',reason=None):events({'kind':'command_ack','payload':{'command_id':c['command_id'],'status':status,**({'reason':reason}if reason else{})}})
    def poll_saved():
        for key,job in list(jobs.items()):
            if not job['future'].done():continue
            jobs.pop(key)
            try:
                row=job['future'].result();rows.append(row);ack(job['command']);emit(snapshot={**row,'command_id':job['command']['command_id']})
            except Exception as exc:
                retained=dict(id=key,command_id=job['command']['command_id'],path=str(project.root/'input/observations'/session_id/key),
                    phase='FAILED',error=str(exc),q_measured=[])
                failures.append(retained);ack(job['command'],'rejected',str(exc));emit(capture_update=retained)
    try:
        writer.submit(writer_ready).result(timeout=30)
        for d in devices.values():d.connect()
        for c in cameras.values():c.start()
        emit(capture_reason='SDK native units only; model rad unavailable'if devices else'Camera reference capture; robot/model not required')
        while not finished:
            batch=list(commands());stops=[c for c in batch if c['kind']in('cancel','session_disconnect','session_finish')]
            for c in batch:
                k=c['kind']
                if stops and c not in stops and k!='session_heartbeat':ack(c,'rejected','Stop/cancel takes precedence');continue
                if k=='session_heartbeat':
                    t=c['payload']['timestamp_ns']
                    if 0<=time.monotonic_ns()-t<=1000000000:last_heartbeat=t
                elif k in('cancel','session_disconnect','session_finish'):cancelled|=k=='cancel';finished=True;ack(c)
                elif k=='session_snapshot':
                    if len(jobs)>=2:ack(c,'rejected','Original save queue full (2)');continue
                    try:
                        requested=c['payload'].get('requested_ns',time.monotonic_ns())
                        packets,frozen_feedback,request=freeze_material_observation(cameras,feedback_history,requested,sequences)
                        if 'follower'in devices and frozen_feedback is None:raise ValueError('No SDK feedback at the requested time')
                        key='observation_'+c['command_id']
                        future=writer.submit(save_snapshot,'materials',key,packets,frozen_feedback,now_ns=request['observed_ns'],request=request)
                        jobs[key]=dict(command=c,future=future)
                        sequences.update({n:p['sequence']for n,p in packets.items()})
                        ack(c,'accepted');emit(capture_update=dict(id=key,command_id=c['command_id'],phase='QUEUED',request=request,q_measured=[]))
                    except ValueError as exc:ack(c,'rejected',str(exc))
                elif k=='session_import':
                    key=c['payload']['snapshot_id'];folder=project.root/'input/observations'/session_id/key
                    if len(jobs)>=2 or key in jobs:ack(c,'rejected','Original save queue full or retry already pending');continue
                    jobs[key]=dict(command=c,future=writer.submit(save_snapshot,'materials_retry',str(folder)));ack(c,'accepted')
                else:ack(c,'rejected','This observation path has no model mapping or motion authority')
            if finished:break
            if time.monotonic_ns()-last_heartbeat>3000000000:raise ValueError('UI heartbeat lost; closing observations')
            feedback=None
            if 'follower'in devices:
                d=devices['follower'];native,interval=d.read();feedback={'native':native,'raw':d.last_raw,'interval':interval,'units':{n:'percent_0_100'if n=='gripper'else'calibration_relative_degree'for n in JOINTS}}
                feedback_history.append(copy.deepcopy(feedback))
            now=time.monotonic_ns();packets={n:c.nearest(now,not_after=True)for n,c in cameras.items()}
            if video._preview_sink:
                for n,p in packets.items():
                    if p is not None:video._preview_sink(n,p['rgb'],p['sequence'],0.,0)
            ready=all(p is not None and now-p['read_end']['monotonic_ns']<=200000000 and p['sequence']>sequences.get(n,-1)for n,p in packets.items())
            emit(capture_ready=ready,sdk_feedback=feedback,camera_timing={n:None if packet is None else {**cameras[n].statistics(),'age_ms':(now-packet['read_end']['monotonic_ns'])/1e6,'joint_skew_ms':(packet['read_end']['monotonic_ns']-feedback['interval']['end']['monotonic_ns'])/1e6 if feedback else None}for n,packet in packets.items()})
            poll_saved()
            time.sleep(1/30)
    except Exception as exc:error=str(exc);raise
    finally:
        try:close_devices({**devices,**cameras})
        finally:
            writer.shutdown(wait=True);poll_saved()
            atomic_json(plan.output_path/'session-report.json',{'snapshots':rows,'failed_captures':failures,'error':error,'model_state':None,'action':None,'command_sent':False,'hardware_connected':bool(devices),'physical_verified':False})
    return StageResult('cancelled'if cancelled else'completed',(str(plan.output_path),),0,{'snapshots':len(rows),'command_sent':False})
