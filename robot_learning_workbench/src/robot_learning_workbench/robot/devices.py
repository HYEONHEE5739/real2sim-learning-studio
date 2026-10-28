"""Concrete SO101 device boundaries. Construction/import never opens a port.

The supplied SDK object is an official device or a fake of that same concrete API.
No automatic calibration, scanning, command retry or implicit active profile lookup.
"""
from dataclasses import dataclass, asdict, is_dataclass
from pathlib import Path
from collections import deque
from threading import Event,Lock,Thread
import copy
import hashlib
import math
import time
from .calibration import (JOINTS, PrecisionMapper, profile_for_model, values,
                          raw_from_native, native_from_raw, fingerprint)


@dataclass(frozen=True)
class DeviceIssue:
    field: str
    reason: str


class DeviceError(RuntimeError):
    def __init__(self, phase, message, *, effect='unknown', cleanup=None):
        self.code='DEVICE_ERROR'; self.phase=phase; self.message=str(message)
        self.effect=effect; self.cleanup=cleanup; self.issues=(DeviceIssue(phase,str(message)),)
        super().__init__(phase + ': ' + str(message))


@dataclass(frozen=True)
class CleanupResult:
    port_closed: bool
    torque_release_requested: bool
    torque_state: str
    errors: tuple[str,...]=()


def stamp(): return {'monotonic_ns':time.monotonic_ns(), 'unix_ns':time.time_ns()}
def _record(value): return asdict(value) if is_dataclass(value) else dict(value)


def close_devices(devices):
    """Attempt every owned resource once; retain all errors instead of masking them."""
    results={}; errors=[]
    for name, device in devices.items():
        if device is None: continue
        try: results[name]=device.close()
        except BaseException as exc: errors.append((name,exc));results[name]=getattr(exc,'cleanup',None)
    if errors:
        error=DeviceError('close_devices','; '.join(name+': '+str(exc) for name,exc in errors))
        error.results=results
        raise error from errors[0][1]
    return results


class Follower:
    """Read-only connect, explicit hold/configure activation and native commands."""
    role='follower'
    @classmethod
    def from_config(cls, config, **binding):
        """Construct the installed official SDK device; connection remains explicit."""
        from importlib.metadata import version
        if version('lerobot') != '0.4.1': raise ValueError('LeRobot 0.4.1 required')
        if cls.role=='leader':
            from lerobot.teleoperators.so101_leader.so101_leader import SO101Leader
            device=SO101Leader(config)
        else:
            from lerobot.robots.so101_follower.so101_follower import SO101Follower
            if config.cameras or config.max_relative_target is not None or not config.use_degrees or not config.disable_torque_on_disconnect:
                raise ValueError('Expected degree-mode SO101 without cameras/relative target rewrite')
            device=SO101Follower(config)
        # Production SDK devices are observation-only. Full-axis activation/send
        # remains available only to explicit in-memory devices in tests.
        binding['read_only']=True
        return cls(device,**binding)
    def __init__(self, device, *, profile, calibration_path, identity, model_hash,
                 source_model=None, execution_model=None, read_only=False):
        self.device=device; self.bus=device.bus; self.identity=copy.deepcopy(identity)
        self.calibration_path=Path(calibration_path)
        self.profile=profile_for_model(profile,model_hash,source_model=source_model,execution_model=execution_model)
        self.precision_mapper=PrecisionMapper(self.profile)
        self._mapping_hash=self.precision_mapper.metadata()['sha256']
        self._closed=False; self._connected=False; self._activated=False; self._sending=False
        self.last_raw=None; self.last_encoded_goal_raw=None; self._last_goal_ns=None
        self.cleanup=None; self.metadata={'native_units':{n:'percent_0_100' if n=='gripper' else 'calibration_relative_degree' for n in JOINTS}}
        self.read_only=bool(read_only or any(c.__module__.startswith('lerobot.') for c in type(self.bus).__mro__))
        self._port_lock=None

    def _check_identity(self, *, hardware=False):
        if self.identity != self.profile['identity'] or self.identity.get('role') != self.role or self.profile.get('role') != self.role:
            raise ValueError('Precision device/role identity mismatch')
        identifier=self.calibration_path.name if self.role=='leader' else self.device.id
        if str(Path(self.bus.port).resolve()) != self.identity['port'] or identifier != self.identity['id']:
            raise ValueError('SDK port/device id mismatch')
        if hashlib.sha256(self.calibration_path.read_bytes()).hexdigest() != self.identity['calibration_sha256']:
            raise ValueError('Motor calibration file identity changed')
        if hardware and not self.device.is_calibrated: raise ValueError('Motor calibration registers mismatch')
        motors={n:{'id':m.id,'model':m.model} for n,m in self.bus.motors.items()}
        if motors != self.identity['motors']: raise ValueError('Motor identity mismatch')
        if self.precision_mapper.metadata()['sha256'] != self._mapping_hash: raise ValueError('Precision mapping changed')
        self.motor_specs={}
        for n in JOINTS:
            motor=self.bus.motors[n]
            spec={'calibration_hash':self.identity['calibration_sha256'],'calibration':_record(self.bus.calibration[n]),
                  'resolution':self.bus.model_resolution_table[motor.model], 'mode':motor.norm_mode.name,'apply_drive_mode':bool(self.bus.apply_drive_mode)}
            if spec['mode'] != ('RANGE_0_100' if n=='gripper' else 'DEGREES'): raise ValueError('Motor normalization mismatch')
            if n in self.profile['joints'] and spec != self.profile['joints'][n]['motor']: raise ValueError('Profile motor spec mismatch')
            self.motor_specs[n]=spec

    def connect(self):
        if self._connected or self._closed: raise DeviceError('connect','Already connected or closed',effect='not_applied')
        try:
            if self.read_only:
                import os,fcntl
                key=hashlib.sha256(str(Path(self.bus.port).resolve()).encode()).hexdigest()
                fd=os.open('/tmp/rlw-'+str(os.getuid())+'-serial-'+key+'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
                self._port_lock=os.fdopen(fd,'r+b');fcntl.flock(self._port_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.bus.connect()  # Official device.connect would configure/calibrate.
            self._check_identity(hardware=True)
            if self.role=='follower' and set(self.device.action_features) != {n+'.pos' for n in JOINTS}: raise ValueError('Unexpected action schema')
            lo=self.bus._normalize({cal.id:cal.range_min for cal in self.bus.calibration.values()})
            hi=self.bus._normalize({cal.id:cal.range_max for cal in self.bus.calibration.values()})
            self.limits={n:sorted((lo[self.bus.motors[n].id],hi[self.bus.motors[n].id])) for n in JOINTS}
            self._connected=True
        except BaseException as exc:
            try: self.close()
            except DeviceError: pass
            raise DeviceError('connect',str(exc),effect='unknown',cleanup=self.cleanup) from exc

    def read(self):
        if not self._connected: raise DeviceError('read','Not connected',effect='not_applied')
        try:
            start=stamp()
            raw=self.bus.sync_read('Present_Position',normalize=False)
            values(raw)  # Validate without changing raw integer register values.
            normalized=self.bus._normalize({self.bus.motors[n].id:v for n,v in raw.items()})
            native=values({n:normalized[self.bus.motors[n].id] for n in JOINTS})
            self.last_raw=dict(raw)
            return native, {'start':start,'end':stamp()}
        except BaseException as exc: raise DeviceError('read',str(exc),effect='not_applied') from exc

    def activate(self):
        if self.read_only:raise DeviceError('activate','ARM_MOTION_NOT_APPROVED: real device is observation-only',effect='not_applied')
        if not self._connected: raise DeviceError('activate','Not connected',effect='not_applied')
        try: self._check_identity(hardware=True)
        except BaseException as exc: raise DeviceError('activate',str(exc),effect='not_applied') from exc
        if self._activated:
            self._sending=True
            return
        try:
            self.bus.disable_torque()
            present=self.bus.sync_read('Present_Position',normalize=False)
            values(present)
            self.bus.sync_write('Goal_Position',present,normalize=False)
            if values(self.bus.sync_read('Goal_Position',normalize=False)) != present:
                raise ValueError('Hold target readback mismatch; configure not called')
            self.device.configure()  # SDK may enable torque even when configure raises.
            self._activated=True; self._sending=True
        except BaseException as exc:
            try: self.close()
            except DeviceError: pass
            raise DeviceError('activate',str(exc),effect='unknown',cleanup=self.cleanup) from exc

    def stop(self):
        """No bus write: prohibit new goals, hold the last hardware target."""
        self._sending=False; self._last_goal_ns=None
        self._gripper_proposal=None

    def encode_goal(self,target):
        from .control import encode_goal
        try:
            self._check_identity()
            return encode_goal(self,target)
        except BaseException as exc: raise DeviceError('encode_goal',str(exc),effect='not_applied') from exc

    def send(self,target):
        if self.read_only:raise DeviceError('send','ARM_MOTION_NOT_APPROVED: full-axis hardware send is prohibited',effect='not_applied')
        if not self._connected or not self._sending: raise DeviceError('send','Not activated or stopped',effect='not_applied')
        try:
            self._check_identity();target=values(target)
            if any(target[n]<self.limits[n][0]-1e-6 or target[n]>self.limits[n][1]+1e-6 for n in JOINTS):
                raise ValueError('Native goal outside calibrated motor range')
        except BaseException as exc: raise DeviceError('send',str(exc),effect='not_applied') from exc
        try:
            start=stamp(); sent=self.device.send_action({n+'.pos':v for n,v in target.items()});end=stamp()
            returned=values({n:sent[n+'.pos'] for n in JOINTS})
            self.metadata['command_timing']={'send_ms':(end['monotonic_ns']-start['monotonic_ns'])/1e6,
                'interval_ms':None if self._last_goal_ns is None else (end['monotonic_ns']-self._last_goal_ns)/1e6}
            self._last_goal_ns=end['monotonic_ns']
            return returned,{'start':start,'end':end}
        except BaseException as exc:
            self.stop()  # No replay of a command whose physical effect is unknown.
            raise DeviceError('send',str(exc),effect='unknown') from exc

    def close(self):
        if self._closed: return self.cleanup
        errors=[]; self._sending=False; self._activated=False
        release=self.role!='calibration' and not self.read_only
        try:
            if self.bus.is_connected: self.bus.disconnect(disable_torque=release)
        except BaseException as exc: errors.append(str(exc))
        finally:
            # Official disconnect may fail before closePort after torque timeout.
            try:
                if self.bus.is_connected: self.bus.port_handler.closePort()
            except BaseException as exc: errors.append(str(exc))
            self._closed=True; self._connected=False
            if self._port_lock is not None:self._port_lock.close();self._port_lock=None
        closed=not self.bus.is_connected
        self.cleanup=CleanupResult(closed,release,'unknown' if errors else ('unmeasured' if release else 'preserved'),tuple(errors))
        if errors or not closed: raise DeviceError('disconnect','; '.join(errors) or 'Port state unknown',cleanup=self.cleanup)
        return self.cleanup


class Leader(Follower):
    """Same concrete bus/read ownership, with torque-release-only activation."""
    role='leader'

    def activate(self):
        if not self._connected: raise DeviceError('activate','Not connected',effect='not_applied')
        if self.read_only:
            self._check_identity(hardware=True)
            return  # Preserve Leader torque; no automatic release.
        try:
            self._check_identity(hardware=True); self.bus.disable_torque(); self._activated=True
        except BaseException as exc:
            try: self.close()
            except DeviceError: pass
            raise DeviceError('activate',str(exc),cleanup=self.cleanup) from exc

    def send(self,target): raise DeviceError('send','Leader has no follower goal API',effect='not_applied')


def gripper_proposal(follower: Follower, requested_rad: float, *, model_bounds: dict, max_delta_raw: int) -> dict:
    """Calculate a single-motor command; explicit displacement budget has no default."""
    from .control import checked_target,encode_goal
    import numpy as np
    if any(c.__module__.startswith('lerobot.')for c in type(follower.bus).__mro__) and not getattr(follower,'_command_binding_verified',False):
        raise DeviceError('gripper_preflight','Explicit command Calibration binding required; observation mapping alone cannot authorize motion',effect='not_applied')
    if not follower.read_only or follower.role!='follower' or not follower._connected or getattr(follower,'_gripper_consumed',False):
        raise DeviceError('gripper_preflight','Connected observation-only Follower required; one shot per connection',effect='not_applied')
    if type(max_delta_raw)is not int or max_delta_raw<=0 or isinstance(requested_rad,bool) or not math.isfinite(requested_rad):
        raise DeviceError('gripper_preflight','Explicit finite target and positive integer displacement budget required',effect='not_applied')
    follower._check_identity(hardware=True)
    native,interval=follower.read();bus=follower.bus;current=int(follower.last_raw['gripper'])
    if time.monotonic_ns()-interval['end']['monotonic_ns']>200_000_000 or interval['end']['monotonic_ns']-interval['start']['monotonic_ns']>200_000_000:raise DeviceError('gripper_preflight','Stale or slow feedback',effect='not_applied')
    if bus.motors['gripper'].id!=6 or bus.read('Operating_Mode','gripper',normalize=False)!=0 or bus.read('Torque_Enable','gripper',normalize=False)!=1:
        raise DeviceError('gripper_preflight','Expected motor6 in existing position mode with torque already on; no automatic torque change',effect='not_applied')
    if bus.read('Goal_Position','gripper',normalize=False)!=current:
        raise DeviceError('gripper_preflight','Existing gripper goal differs from feedback; motion state unclear',effect='not_applied')
    # Only the gripper inverse is needed: arm feedback is never an arm goal.
    profile=copy.deepcopy(follower.profile)
    if 'gripper'not in profile['joints']:raise DeviceError('gripper_preflight','Approved gripper Precision mapping missing',effect='not_applied')
    profile['joints']={'gripper':profile['joints']['gripper']};mapper=PrecisionMapper(profile)
    bounds=mapper.command_limits(model_bounds);request=np.zeros(6);request[-1]=requested_rad
    diagnostic={};target=checked_target(request,limits=[bounds[n] for n in JOINTS],applied_dtype=np.float64,diagnostics=diagnostic)
    native_goal=mapper.urdf_to_calibrated(dict(zip(JOINTS,target.tolist())))['gripper']
    command,encoded=encode_goal(follower,{'gripper':native_goal},joints=('gripper',))
    raw=int(follower.last_encoded_goal_raw[6]);delta=raw-current
    actual=mapper.calibrated_to_urdf({**dict.fromkeys(JOINTS,0.),**encoded})['gripper']
    if not bounds['gripper'][0]<=actual<=bounds['gripper'][1] or not 0<abs(delta)<=max_delta_raw:
        raise DeviceError('gripper_preflight','Target exceeds the explicitly approved single-step displacement or has no displacement',effect='not_applied')
    proposal=dict(identity=copy.deepcopy(follower.identity),mapping_sha256=follower._mapping_hash,motor_id=6,joint='gripper',
        current_raw=current,target_raw=raw,raw_delta=delta,max_delta_raw=max_delta_raw,requested_model_rad=requested_rad,
        applied_model_rad=actual,native_command=command['gripper'],saturation=diagnostic,created_ns=time.monotonic_ns(),command_sent=False)
    follower._gripper_proposal=fingerprint(proposal)
    return proposal


def send_gripper_once(follower: Follower, proposal: dict, *, approved: bool=False) -> dict:
    """One explicit Goal_Position write to motor6; no arm/torque/configuration writes.

    Approval must be supplied by a supervised user after reviewing this proposal.
    A timeout/unknown send consumes the authorization; it is never retried.
    """
    if approved is not True or not follower.read_only or not follower._connected or getattr(follower,'_gripper_consumed',False):
        raise DeviceError('gripper_send','Explicit one-shot approval and unchanged connection required',effect='not_applied')
    if fingerprint(proposal)!=getattr(follower,'_gripper_proposal',None) or proposal['identity']!=follower.identity or proposal['mapping_sha256']!=follower._mapping_hash or proposal['motor_id']!=6 or proposal['joint']!='gripper':
        raise DeviceError('gripper_send','Proposal/Device identity changed',effect='not_applied')
    if not 0<=time.monotonic_ns()-proposal['created_ns']<=30_000_000_000:
        raise DeviceError('gripper_send','Proposal expired; new read and approval required',effect='not_applied')
    follower._gripper_consumed=True
    check_start=time.monotonic_ns();follower._check_identity(hardware=True);bus=follower.bus
    if bus.read('Present_Position','gripper',normalize=False)!=proposal['current_raw'] or bus.read('Goal_Position','gripper',normalize=False)!=proposal['current_raw'] or bus.read('Torque_Enable','gripper',normalize=False)!=1 or bus.read('Operating_Mode','gripper',normalize=False)!=0:
        raise DeviceError('gripper_send','Feedback/torque/mode changed; authorization invalid',effect='not_applied')
    if time.monotonic_ns()-check_start>200_000_000:raise DeviceError('gripper_send','Pre-send reads exceeded 200ms; authorization consumed without sending',effect='not_applied')
    try:
        start=stamp();bus.write('Goal_Position','gripper',proposal['target_raw'],normalize=False);end=stamp()
        feedback=bus.read('Present_Position','gripper',normalize=False)
        return dict(sent_joint='gripper',motor_id=6,command_count=1,start=start,end=end,feedback_raw=feedback,
                    target_raw=proposal['target_raw'],reached=feedback==proposal['target_raw'],arm_commands=0,torque_commands=0)
    except BaseException as error:raise DeviceError('gripper_send',str(error),effect='unknown')from error


class CalibrationDevice:
    """Exclusive read-only reference collection; approved joint release is explicit."""
    def __init__(self, device, *, role, identity, calibration_path):
        if role not in ('leader','follower'): raise ValueError('Unknown calibration role')
        self.device=device; self.bus=device.bus; self.role=role
        self.identity=copy.deepcopy(identity);self.calibration_path=Path(calibration_path)
        self.exclusive=False;self._closed=False;self.cleanup=None

    def unchanged(self):
        motors={n:{'id':m.id,'model':m.model} for n,m in self.bus.motors.items()}
        identifier=self.calibration_path.name if self.role=='leader' else self.device.id
        return (self.device.is_calibrated and self.identity['role']==self.role and self.identity['motors']==motors
                and str(Path(self.bus.port).resolve())==self.identity['port'] and identifier==self.identity['id']
                and hashlib.sha256(self.calibration_path.read_bytes()).hexdigest()==self.identity['calibration_sha256'])

    def connect(self):
        if self._closed or self.bus.is_connected: raise DeviceError('calibration_connect','Already open or closed',effect='not_applied')
        try:
            import fcntl,termios
            self.bus.connect()
            fcntl.ioctl(self.bus.port_handler.ser.fileno(),termios.TIOCEXCL);self.exclusive=True
            if not self.unchanged(): raise ValueError('Device/calibration identity mismatch')
        except BaseException as exc:
            try:self.close()
            except DeviceError:pass
            raise DeviceError('calibration_connect',str(exc),cleanup=self.cleanup) from exc

    def motor_spec(self,joint):
        motor=self.bus.motors[joint]
        return {'calibration_hash':self.identity['calibration_sha256'],'calibration':_record(self.bus.calibration[joint]),
                'resolution':self.bus.model_resolution_table[motor.model],'mode':motor.norm_mode.name,'apply_drive_mode':bool(self.bus.apply_drive_mode)}

    def sample(self,joint,live=False):
        try:
            if joint not in JOINTS or not self.exclusive or not self.unchanged(): raise ValueError('Invalid joint or calibration changed')
            start=time.monotonic_ns();raw=self.bus.read('Present_Position',joint,normalize=False);raw_time=time.monotonic_ns()
            identifier=self.bus.motors[joint].id
            native=self.bus._normalize({identifier:raw})[identifier] if live else self.bus.read('Present_Position',joint,normalize=True)
            native_time=raw_time if live else time.monotonic_ns()
            if not math.isfinite(raw) or not math.isfinite(native):raise ValueError('Nonfinite reference')
            if abs(self.bus._unnormalize({identifier:native})[identifier]-raw)>3:raise ValueError('Raw/normalized reads moved or clipped')
            torque=self.bus.read('Torque_Enable',joint,normalize=False)
            return {'raw':raw,'legacy_position':native,'torque':int(torque),'timestamp_ns':time.monotonic_ns(),
                'read_start_ns':start,'raw_timestamp_ns':raw_time,'native_timestamp_ns':native_time,
                'clock':'host_monotonic_ns; not hardware synchronized','native_source':'normalized_same_raw_packet' if live else 'separate_normalized_read',
                'joint':joint,'device_identity':copy.deepcopy(self.identity),'calibration_hash':self.identity['calibration_sha256'],'motor':self.motor_spec(joint)}
        except BaseException as exc:raise DeviceError('calibration_sample',str(exc),effect='not_applied') from exc

    def release(self,joint,*,approved=False):
        if joint!='gripper' or approved is not True or not self.exclusive or not self.unchanged():
            raise DeviceError('calibration_release','Explicit approval and unchanged connected device required',effect='not_applied')
        try:
            self.bus.disable_torque([joint])
            if self.bus.read('Torque_Enable',joint,normalize=False)!=0:raise ValueError('Torque release not confirmed')
        except BaseException as exc:raise DeviceError('calibration_release',str(exc),effect='unknown') from exc

    def close(self):
        if self._closed:return self.cleanup
        errors=[]
        try:
            if self.exclusive:
                import fcntl,termios
                fcntl.ioctl(self.bus.port_handler.ser.fileno(),termios.TIOCNXCL)
        except BaseException as exc:errors.append(str(exc))
        finally:
            self.exclusive=False
            try:
                if self.bus.is_connected:self.bus.disconnect(disable_torque=False)
            except BaseException as exc:errors.append(str(exc))
            finally:
                try:
                    if self.bus.is_connected:self.bus.port_handler.closePort()
                except BaseException as exc:errors.append(str(exc))
                self._closed=True
        self.cleanup=CleanupResult(not self.bus.is_connected,False,'unknown' if errors else 'preserved',tuple(errors))
        if errors:raise DeviceError('calibration_close','; '.join(errors),cleanup=self.cleanup)
        return self.cleanup


class CameraReader:
    """Official camera.read in an owned thread; frames have host receipt times."""
    def __init__(self,camera,*,device,resolution=(640,480)):
        self.camera=camera;self.resolution=tuple(resolution)
        self.frames=deque(maxlen=90);self.lock=Lock();self.stop=Event()
        self.thread=None;self.error=None;self._closed=False;self._close_error=None
        self.metadata={'device':str(device),'requested_size':list(resolution),'color':'RGB',
            'timestamp_kind':'host_read_interval','hardware_exposure_timestamp_available':False}

    @classmethod
    def from_config(cls,config):
        from lerobot.cameras.opencv.camera_opencv import OpenCVCamera
        from lerobot.cameras.opencv.configuration_opencv import ColorMode,Cv2Rotation
        if config.color_mode!=ColorMode.RGB or config.rotation!=Cv2Rotation.NO_ROTATION:raise ValueError('Original unrotated RGB camera required')
        return cls(OpenCVCamera(config),device=config.index_or_path,resolution=(config.width,config.height))

    def start(self):
        if self.thread is not None or self._closed:raise DeviceError('camera_start','Already started or closed',effect='not_applied')
        try:
            self.camera.connect()
            cap=getattr(self.camera,'videocapture',None)
            if cap is not None:
                import cv2
                self.metadata['buffer_size_request_accepted']=bool(cap.set(cv2.CAP_PROP_BUFFERSIZE,1))
                self.metadata['reported']={name:float(cap.get(key)) for name,key in (
                    ('width',cv2.CAP_PROP_FRAME_WIDTH),('height',cv2.CAP_PROP_FRAME_HEIGHT),('fps',cv2.CAP_PROP_FPS),
                    ('exposure',cv2.CAP_PROP_EXPOSURE),('auto_exposure',cv2.CAP_PROP_AUTO_EXPOSURE))}
                self.metadata['reported']={k:v if math.isfinite(v) else None for k,v in self.metadata['reported'].items()}
            self.thread=Thread(target=self._run,daemon=True,name='capture-camera-'+self.metadata['device'])
            self.thread.start()
        except BaseException as exc:
            try:self.close()
            except DeviceError:pass
            raise DeviceError('camera_start',str(exc),effect='unknown') from exc

    def _run(self):
        import numpy as np
        seq=0
        try:
            while not self.stop.is_set():
                begin=stamp();rgb=self.camera.read();end=stamp()
                if not isinstance(rgb,np.ndarray) or rgb.dtype!=np.uint8 or rgb.shape!=(self.resolution[1],self.resolution[0],3):
                    raise ValueError('Original RGB uint8 camera resolution mismatch')
                seq+=1;packet={'rgb':rgb.copy(),'sequence':seq,'read_start':begin,'read_end':end}
                with self.lock:self.frames.append(packet)
        except BaseException as exc:
            if not self.stop.is_set():self.error=repr(exc)

    def nearest(self,target_ns=None):
        if self.error:raise DeviceError('camera_read',self.error,effect='not_applied')
        with self.lock:
            if not self.frames:return None
            frame=self.frames[-1] if target_ns is None else min(self.frames,key=lambda f:abs(f['read_end']['monotonic_ns']-target_ns))
            return {**copy.deepcopy({k:v for k,v in frame.items() if k!='rgb'}),'rgb':frame['rgb'].copy()}

    def close(self):
        if self._closed:
            if self._close_error:raise self._close_error
            return
        self.stop.set();errors=[]
        try:
            if self.thread:self.thread.join(timeout=.5)
        except BaseException as exc:errors.append(str(exc))
        try:
            if self.camera.is_connected:self.camera.disconnect()
        except BaseException as exc:errors.append(str(exc))
        finally:
            if self.thread:
                try:
                    self.thread.join(timeout=1.)
                    if self.thread.is_alive():errors.append('Camera thread is still alive')
                except BaseException as exc:errors.append(str(exc))
            self._closed=True
        if errors:
            self._close_error=DeviceError('camera_close','; '.join(errors),effect='unknown')
            raise self._close_error
