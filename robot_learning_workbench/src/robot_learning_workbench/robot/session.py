"""Persistent R03 hardware sessions. UI commands never carry motor targets."""
import time,copy
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .capture import Stability,observed_positions,snapshot_state
from .devices import close_devices,DeviceError
from .supervised import Teleoperation
from .snapshots import SnapshotStore
from .calibration import JOINTS
from ..data.native import atomic_json


class HardwareSession:
    def __init__(self,plan,devices,cameras,bounds,*,events,renderer=None):
        from real2sim_builder.project import Project
        self.plan=plan;self.devices=devices;self.cameras=cameras;self.events=events;self.renderer=renderer
        self.state='DISCONNECTED';self.terminal=False;self.closing=False;self.cancelled=False;self.finished=False;self.snapshots=[];self.pending=None;self.pending_command=None
        self.history=deque(maxlen=180);self.packets={};self.stability=Stability();self.last_heartbeat=time.monotonic_ns();self.capture_error='연결 후 안정된 관측을 기다립니다';self.seen=set()
        self.writer=ThreadPoolExecutor(max_workers=1,thread_name_prefix='snapshot-save');self.saving=None;self.save_phase=None;self.pending_render=None;self.acquiring=None;self.acquire_deadline=0
        self.project=Project(plan.resolved_inputs['project']['root']);self.session_id=plan.output_path.name.replace('-','_')
        self.store=SnapshotStore(self.project,session_id=self.session_id,model=plan.resolved_inputs['robot_model']['path'],mapping=devices['follower'].precision_mapper.metadata())
        settings=plan.effective_settings['execution'];self.teleoperation=Teleoperation(devices['leader'],devices['follower'],model_bounds=bounds,session_id=self.session_id,max_step_rad=settings['max_command_step_rad'],max_follow_error_rad=settings['max_follow_error_rad'])

    def emit(self,**progress):
        self.events({'kind':'status','payload':{'progress':{'session_state':self.state,'teleop_active':self.teleoperation.active,'snapshots':len(self.snapshots),**progress}}})

    def ack(self,command,status='completed',reason=None):
        self.events({'kind':'command_ack','payload':{'command_id':command['command_id'],'status':status,**({'reason':reason}if reason else{})}})

    def connect(self):
        self.state='CONNECTING';self.emit()
        try:
            for device in self.devices.values():device.connect()
            for camera in self.cameras.values():camera.start()
            self.state='OBSERVING';self.emit(device_source=self.plan.effective_settings['execution']['device_source'],identities={n:d.identity for n,d in self.devices.items()})
        except Exception:self.state='FAILED';self.close();raise

    def read_observation(self):
        device=self.devices['follower'];native,interval=device.read();t=interval['end']['monotonic_ns']
        q=observed_positions(device.precision_mapper,native,raw=device.last_raw,motor_specs=device.motor_specs)
        self.history.append(dict(timestamp_ns=t,native=native,raw=dict(device.last_raw),q_measured=[q[n]for n in JOINTS],feedback_interval=interval))
        self.stability.add(t,native);self.packets={n:c.nearest(t,not_after=True)for n,c in self.cameras.items()};self.observed_at_ns=time.monotonic_ns()
    def observe(self):
        self.read_observation();device=self.devices['follower'];t=self.history[-1]['timestamp_ns']
        if self.teleoperation.active:
            row=self.teleoperation.tick()
            from .telemetry import Recorder
            if not hasattr(self,'recorder'):self.recorder=Recorder(self.plan,self.devices['follower'])
            self.recorder.append(row)
        if self.renderer is not None:self.renderer.observe(self.history[-1]['q_measured'])
        from ..data import video
        if video._preview_sink is not None:
            for name,packet in self.packets.items():
                if packet is not None:video._preview_sink(name,packet['rgb'],packet['sequence'],(t-self.history[0]['timestamp_ns'])/1e9,0)
        self.emit(feedback_gap_ms=(self.history[-1]['timestamp_ns']-self.history[-2]['timestamp_ns'])/1e6 if len(self.history)>1 else None,q_measured=self.history[-1]['q_measured'],raw=dict(device.last_raw),capture_ready=self.acquiring is None and self.capture_ready(),capture_reason='관측 정합 대기 중…'if self.acquiring else self.capture_error,
                  camera_timing={n:None if p is None else {**self.cameras[n].statistics(),'sequence':p['sequence'],'age_ms':(time.monotonic_ns()-p['read_end']['monotonic_ns'])/1e6,'joint_skew_ms':(p['read_end']['monotonic_ns']-t)/1e6}for n,p in self.packets.items()})

    def capture_ready(self):
        self.capture_error=''
        if self.pending is not None or self.saving is not None:self.capture_error='Pair 렌더/저장 중';return False
        if not self.history or not self.stability.assess().get('stable'):self.capture_error='안정된 Follower 관측을 기다립니다';return False
        t=self.history[-1]['timestamp_ns'];now=time.monotonic_ns()
        window=[r['timestamp_ns']for r in self.history if r['timestamp_ns']>=self.stability.assess()['window_start_ns']]
        if any(b-a>100_000_000 for a,b in zip(window,window[1:])):self.capture_error='측정 간격100ms 초과 · 연속 feedback 대기';return False
        for name,p in self.packets.items():
            if p is None or now-p['read_end']['monotonic_ns']>200_000_000 or abs(t-p['read_end']['monotonic_ns'])>100_000_000:self.capture_error=name+': stale/skew, 재촬영 필요';return False
            if p['sequence']<=self.store.last_sequences.get(name,-1):self.capture_error=name+': 새 frame 대기';return False
        return True

    def dispatch(self,commands):
        commands=list(commands)
        for command in commands:
            if command['kind']=='session_heartbeat':
                t=command['payload']['timestamp_ns']
                if 0<=time.monotonic_ns()-t<=1_000_000_000:self.last_heartbeat=t;self.teleoperation.last_heartbeat_ns=t
        commands=[c for c in commands if c['kind']!='session_heartbeat'];stops=[c for c in commands if c['kind']in('cancel','session_disconnect','session_finish','teleop_stop')]
        if stops:
            for c in commands:
                if c not in stops:self.ack(c,'rejected','Stop/cancel takes precedence')
            for c in stops:self.command(c)
        else:
            for c in commands:self.command(c)

    def command(self,command):
        key=command['command_id']
        if key in self.seen:return
        self.seen.add(key);kind=command['kind'];payload=command['payload']
        try:
            if self.terminal:self.ack(command,'rejected','Session is disconnected');return
            if kind in('cancel','session_disconnect','session_finish'):
                self.cancelled=kind=='cancel';self.finished=kind=='session_finish';self.close()
            elif kind=='teleop_prepare':
                from .telemetry import Recorder
                if not hasattr(self,'recorder'):self.recorder=Recorder(self.plan,self.devices['follower'])
                proposal=self.teleoperation.propose();self.state='TELEOP_READY';self.emit(teleop_proposal=proposal)
            elif kind=='teleop_start':self.teleoperation.start(payload);self.state='TELEOP_ACTIVE';self.emit()
            elif kind=='teleop_stop':self.teleoperation.stop();self.state='OBSERVING';self.emit()
            elif kind=='session_snapshot':
                if self.acquiring is not None or self.pending is not None or self.saving is not None:raise ValueError('Capture already in progress')
                self.read_observation();self.acquiring=command;self.acquire_deadline=time.monotonic()+5;self.state='CAPTURING'
                self.try_capture();self.emit();return
            elif kind=='session_import':
                if self.saving is not None or self.pending_command is not None:raise ValueError('Capture/render/save is still running; retry after failure')
                if self.pending is None or self.pending['id']!=payload['snapshot_id']:raise ValueError('No recoverable pending capture')
                self.pending_command=command;self.complete_capture(self.pending_render);return
            else:raise ValueError('Command is not supported by this Session')
            self.ack(command)
        except Exception as error:
            if self.terminal:
                self.ack(command,'rejected',str(error));raise
            if isinstance(error,DeviceError):self.teleoperation.stop()
            self.state='TELEOP_ACTIVE'if self.teleoperation.active else'OBSERVING';self.ack(command,'rejected',str(error));self.emit(error=str(error),pending_snapshot=self.pending['id']if self.pending else None)

    def try_capture(self):
        if self.acquiring is None:return
        if self.capture_ready():
            command=self.acquiring;self.acquiring=None
            state=snapshot_state(self.devices['follower'],list(self.history),self.packets,self.stability.assess())
            state.update(captured_host_ns=self.observed_at_ns,camera_metadata={n:c.metadata for n,c in self.cameras.items()},device_source=self.plan.effective_settings['execution']['device_source'])
            self.pending_command=command
            self.saving=self.writer.submit(self.store.prepare,'snapshot_'+command['command_id'],state,{'real_'+n:p['rgb']for n,p in self.packets.items()});self.save_phase='prepare'
        elif time.monotonic()>self.acquire_deadline:
            command=self.acquiring;self.acquiring=None;self.state='TELEOP_ACTIVE'if self.teleoperation.active else'OBSERVING';self.ack(command,'rejected','정합된 관측을5초 안에 얻지 못했습니다: '+self.capture_error)

    def complete_capture(self,rendered=None):
        if rendered is not None:self.pending_render=rendered
        self.saving=self.writer.submit(self.store.finish,self.pending,rendered=rendered);self.save_phase='finish'

    def poll_capture(self):
        self.try_capture()
        if self.saving is None or not self.saving.done():return
        future=self.saving;self.saving=None
        try:
            result=future.result()
            if self.save_phase=='prepare':
                self.pending=result
                if self.closing and self.renderer is not None:
                    self.ack(self.pending_command,'rejected','Disconnected before Pair render; sealed observation retained');self.pending_command=None;return
                if self.renderer is None:self.complete_capture()
                else:self.renderer.capture(self.pending)
            else:
                self.snapshots.append(result)
                if self.renderer is not None:
                    warnings=self.renderer.release_capture(self.pending['id'])
                    if warnings:self.events({'kind':'log','payload':{'level':'warning','message':'Render IPC cleanup: '+str(warnings)}})
                self.pending=None;self.pending_render=None;self.ack(self.pending_command);self.pending_command=None
                self.state='DISCONNECTING'if self.closing else'TELEOP_ACTIVE'if self.teleoperation.active else'OBSERVING';self.emit(snapshot=result)
        except Exception as error:
            self.ack(self.pending_command,'rejected',str(error));self.pending_command=None;self.state='OBSERVING';self.teleoperation.stop();self.emit(error=str(error),pending_snapshot=self.pending['id']if self.pending else None)

    def close(self):
        if self.terminal:return
        self.closing=True;self.teleoperation.stop();self.state='DISCONNECTING';self.emit();errors=[]
        if self.acquiring is not None:
            self.ack(self.acquiring,'rejected','Disconnected before synchronized capture; no observation published');self.acquiring=None
        if self.renderer is not None:
            try:self.renderer.close()
            except Exception as error:errors.append(str(error))
        try:close_devices({**self.devices,**self.cameras})
        except Exception as error:errors.append(str(error))
        if hasattr(self,'recorder'):
            try:self.recorder.close()
            except Exception as error:errors.append(str(error))
        # Close devices first, then finish the one owned filesystem transaction.
        try:
            while self.saving is not None:
                try:self.saving.result()
                except Exception:pass  # poll_capture preserves the failed transaction and ACK.
                self.poll_capture()
            self.writer.shutdown(wait=True)
        except Exception as error:errors.append(str(error))
        self.terminal=True;self.state='FAILED'if errors else'DISCONNECTED';self.emit(cleanup_errors=errors)
        if errors:raise DeviceError('session_close','; '.join(errors),effect='unknown')


def run(plan,*,events,commands):
    from ..recipe import verify_prepared_inputs
    from ..run import StageResult
    from .session_devices import construct
    verify_prepared_inputs(plan);devices,cameras,bounds=construct(plan);plan.output_path.mkdir();renderer=None
    if plan.stage=='paired_session':
        from .real_sim import RenderProcess
        renderer=RenderProcess(plan,devices['follower'].precision_mapper.metadata())
    try:session=HardwareSession(plan,devices,cameras,bounds,events=events,renderer=renderer)
    except Exception:
        if renderer is not None:renderer.close()
        close_devices({**devices,**cameras});raise
    error=None
    try:
        session.connect()
        while not session.terminal:
            begin=time.monotonic();session.dispatch(commands())
            if session.terminal:break
            if time.monotonic_ns()-session.last_heartbeat>3_000_000_000:raise DeviceError('session','UI heartbeat lost; no further goals',effect='not_applied')
            session.observe()
            session.poll_capture()
            if renderer is not None:
                result=renderer.poll()
                if renderer.last_live is not None:session.emit(render_timing={'render_ms':renderer.last_live['render_ms'],'age_ms':(time.monotonic_ns()-renderer.last_live['sim_timestamp']['monotonic_ns'])/1e6})
                if result is not None and session.pending is not None:session.complete_capture(result)
            time.sleep(max(0,1/30-(time.monotonic()-begin)))
    except Exception as exc:error=str(exc);raise
    finally:
        try:session.close()
        finally:atomic_json(plan.output_path/'session-report.json',dict(state=session.state,error=error,project_id=session.project.info['id'],snapshots=session.snapshots,
            pending_snapshot=session.pending,teleoperation_last_attempt=session.teleoperation.last_attempt,device_source=plan.effective_settings['execution']['device_source'],motion_verified=False,stop_policy='preserve_torque_no_new_goal'))
    return StageResult('cancelled'if session.cancelled else'completed',(str(plan.output_path),),0,{'snapshots':len(session.snapshots),'disconnected':True,'task_finished':session.finished})
