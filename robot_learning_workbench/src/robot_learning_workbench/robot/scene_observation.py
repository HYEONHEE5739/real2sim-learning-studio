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


def save_materials(project,key,packets,feedback,*,now_ns=None):
    """Existing Builder images/documents; no new Dataset or model Snapshot schema."""
    import os
    from PIL import Image
    from real2sim_builder.evidence import add_image
    from real2sim_builder.files import write,sha
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
    root=project.root/'input/observations'/key
    if root.exists():raise ValueError('Observation already exists')
    root.mkdir(parents=True);images={}
    record={'timestamp_kind':'host_receipt_not_exposure','hardware_synchronized':False,'model_state':None,'action':None,'sdk_feedback':feedback,'camera_timing':{n:{k:p[k]for k in('read_start','read_end','sequence')}for n,p in packets.items()},'eligible_for_calibration':False,'reason':'Unbound reference observations; model/Precision/camera calibration unverified'}
    write(root/'observation.json',record)
    for name,p in packets.items():Image.fromarray(p['rgb']).save(root/(name+'.png'))
    from real2sim_builder.candidate import exclusive
    with exclusive(project):
        before=copy.deepcopy(project.evidence)
        try:
            for name in packets:
                source=root/(name+'.png');owned=project.root/add_image(project,source,camera=name,context_only=True)['path'];images[name]=str(owned)
                if owned!=source:source.unlink();os.link(owned,source)
            evidence=project.evidence;evidence.setdefault('documents',[]).append({'path':str((root/'observation.json').relative_to(project.root)),'sha256':sha(root/'observation.json'),'role':'unbound_sdk_camera_observation','status':'UNVERIFIED'})
            write(project.root/'input/evidence.yaml',evidence);project.invalidate();(root/'COMPLETE').write_text('complete\n')
        except BaseException:write(project.root/'input/evidence.yaml',before);raise
    return {'id':key,'path':str(root),'unix_ns':packets['side']['read_end']['unix_ns'],'q_measured':[],'images':images,'quality':[record['reason']],'paired':False,'kind':'scene_materials'}


def run(plan,*,events,commands):
    from real2sim_builder.project import Project
    from ..recipe import verify_prepared_inputs
    from ..run import StageResult
    from ..data import video
    verify_prepared_inputs(plan);devices,cameras=construct(plan);project=Project(plan.resolved_inputs['project']['root']);plan.output_path.mkdir()
    last_heartbeat=time.monotonic_ns();rows=[];sequences={};pending=None;cancelled=False;error=None
    def emit(**p):events({'kind':'status','payload':{'progress':{'session_state':'OBSERVING','teleop_active':False,'device_source':'hardware','teleoperation_available':False,**p}}})
    def ack(c,status='completed',reason=None):events({'kind':'command_ack','payload':{'command_id':c['command_id'],'status':status,**({'reason':reason}if reason else{})}})
    try:
        for d in devices.values():d.connect()
        for c in cameras.values():c.start()
        emit(capture_reason='SDK native units only; model rad unavailable'if devices else'Camera reference capture; robot/model not required')
        finished=False
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
                    if pending:ack(c,'rejected','Capture already pending')
                    else:pending=(c,time.monotonic()+5)
                else:ack(c,'rejected','This observation path has no model mapping or motion authority')
            if finished:break
            if time.monotonic_ns()-last_heartbeat>3000000000:raise ValueError('UI heartbeat lost; closing observations')
            feedback=None
            if 'follower'in devices:
                d=devices['follower'];native,interval=d.read();feedback={'native':native,'raw':d.last_raw,'interval':interval,'units':{n:'percent_0_100'if n=='gripper'else'calibration_relative_degree'for n in JOINTS}}
            now=time.monotonic_ns();packets={n:c.nearest(now,not_after=True)for n,c in cameras.items()}
            if video._preview_sink:
                for n,p in packets.items():
                    if p is not None:video._preview_sink(n,p['rgb'],p['sequence'],0.,0)
            ready=all(p is not None and now-p['read_end']['monotonic_ns']<=200000000 and p['sequence']>sequences.get(n,-1)for n,p in packets.items())
            emit(capture_ready=ready,sdk_feedback=feedback,camera_timing={n:None if packet is None else {**cameras[n].statistics(),'age_ms':(now-packet['read_end']['monotonic_ns'])/1e6,'joint_skew_ms':(packet['read_end']['monotonic_ns']-feedback['interval']['end']['monotonic_ns'])/1e6 if feedback else None}for n,packet in packets.items()})
            if pending:
                c,deadline=pending
                try:
                    if not ready:raise ValueError('Waiting for fresh camera frames')
                    row=save_materials(project,'observation_'+c['command_id'],packets,feedback);rows.append(row);sequences={n:p['sequence']for n,p in packets.items()};pending=None;ack(c);emit(snapshot=row)
                except ValueError as exc:
                    if time.monotonic()>deadline:ack(c,'rejected',str(exc));pending=None
            time.sleep(1/30)
    except Exception as exc:error=str(exc);raise
    finally:
        try:close_devices({**devices,**cameras})
        finally:
            if pending:ack(pending[0],'rejected','Disconnected before Capture')
            atomic_json(plan.output_path/'session-report.json',{'snapshots':rows,'error':error,'model_state':None,'action':None,'command_sent':False,'hardware_connected':bool(devices),'physical_verified':False})
    return StageResult('cancelled'if cancelled else'completed',(str(plan.output_path),),0,{'snapshots':len(rows),'command_sent':False})
