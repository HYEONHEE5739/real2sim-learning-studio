"""Supervised Leader→Follower control and measured Follower→native Scene rendering."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from .capture import Stability,observed_positions,snapshot_state,capture_reason
from .calibration import JOINTS
from .devices import close_devices,DeviceError
from .snapshots import SnapshotStore
from .render_transport import RenderProcess
from .supervised import Teleoperation
from .teleop_loop import TeleoperationLoop
from ..data.native import atomic_json


class RealSimSession:
    def __init__(self,plan,devices,cameras,*,events):
        from real2sim_builder.project import Project
        if 'follower'not in devices or set(devices)-{'follower','leader'}:raise ValueError('Real/Sim requires a Follower and optional Leader')
        self.plan=plan;self.devices=devices;self.cameras=cameras;self.events=events;self.follower=devices['follower']
        self.project=Project(plan.resolved_inputs['project']['root']);self.history=deque(maxlen=180);self.stability=Stability();self.packets={}
        self.store=SnapshotStore(self.project,session_id=plan.output_path.name.replace('-','_'),model=plan.resolved_inputs['robot_model']['path'],mapping=self.follower.precision_mapper.metadata())
        self.state='DISCONNECTED';self.terminal=False;self.closing=False;self.cancelled=False;self.renderer=None;self.snapshots=[];self.seen=set();self.last_heartbeat=time.monotonic_ns()
        self.writer=ThreadPoolExecutor(max_workers=1,thread_name_prefix='paired-capture');self.future=None;self.phase=None;self.acquiring=None;self.pending=None;self.command_pending=None;self.rendered=None
        self.teleoperation=None;self.control=None;self.control_history=deque(maxlen=300);self.last_error=None
        if 'leader'in devices:
            from .calibration import joint_specs
            bounds={n:e['limits']for n,e in joint_specs(plan.resolved_inputs['robot_model']['path']).items()}
            self.teleoperation=Teleoperation(devices['leader'],self.follower,model_bounds=bounds,session_id=plan.output_path.name)
            self.control=TeleoperationLoop(self.teleoperation)
    def emit(self,**progress):
        busy=self.acquiring is not None or self.pending is not None or self.future is not None or self.rendered is not None
        self.events({'kind':'status','payload':{'progress':{'session_state':self.state,'device_source':self.plan.effective_settings['execution']['device_source'],
            'teleop_active':bool(self.teleoperation and self.teleoperation.active),'teleoperation_available':self.teleoperation is not None,
            'teleoperation_reason':''if self.teleoperation else'Leader/Precision 구성이 없어 관측만 가능합니다. Capture의 장치 설정에서 Leader를 선택하세요.',
            'capture_request_allowed':self.state in('OBSERVING','TELEOP_ACTIVE')and not busy and not self.closing,'capture_pending':busy,'snapshots':len(self.snapshots),**progress}}})
    def ack(self,c,status='completed',reason=None):
        self.events({'kind':'command_ack','payload':{'command_id':c['command_id'],'status':status,**({'reason':reason}if reason else{})}})
    def connect(self):
        self.state='CONNECTING';self.emit(capture_reason='Follower/Camera 연결과 선택 Scene 초기화 중')
        try:
            for device in self.devices.values():device.connect()
            for camera in self.cameras.values():camera.start()
            from ..recipe import verify_prepared_inputs
            verify_prepared_inputs(self.plan)
            self.renderer=RenderProcess(self.plan,self.follower.precision_mapper.metadata());self.render_deadline=time.monotonic()+180
        except BaseException:self.close();raise
    def dispatch(self,commands):
        rows=list(commands);stops=[c for c in rows if c['kind']in('cancel','session_disconnect','session_finish','teleop_stop')]
        for c in rows:
            if c['kind']=='session_heartbeat':
                t=c['payload']['timestamp_ns']
                if 0<=time.monotonic_ns()-t<=1000000000:
                    self.last_heartbeat=t
                    if self.teleoperation:self.teleoperation.last_heartbeat_ns=t
                continue
            if c['command_id']in self.seen:continue
            self.seen.add(c['command_id'])
            if stops and c not in stops:self.ack(c,'rejected','Stop/cancel takes precedence');continue
            if c in stops:
                if self.control:self.control.stop();self.collect_control()
                if c['kind']=='teleop_stop':
                    if self.state=='TELEOP_ACTIVE':self.state='OBSERVING'
                    self.ack(c);self.emit();continue
                self.cancelled|=c['kind']=='cancel';self.close();self.ack(c);continue
            if c['kind']=='teleop_start':
                try:
                    if self.teleoperation is None:raise ValueError('Leader and its Precision profile are required for Teleoperation')
                    if self.state not in('OBSERVING','TELEOP_ACTIVE'):raise ValueError('Wait for Scene connection or Capture completion')
                    self.control.start(c['command_id']);self.state='TELEOP_ACTIVE';self.emit();self.ack(c)
                except Exception as error:self.last_error=str(error);self.ack(c,'rejected',str(error));self.emit(error=str(error))
                continue
            if c['kind']!='session_snapshot':self.ack(c,'rejected','Unsupported Real/Sim session command');continue
            if self.state not in('OBSERVING','TELEOP_ACTIVE')or self.acquiring is not None or self.pending is not None or self.future is not None or self.rendered is not None:
                self.ack(c,'rejected','Wait for Real/Sim connection or current Capture to finish');continue
            self.acquiring=c;self.acquire_deadline=time.monotonic()+5;self.state='CAPTURING';self.emit(capture_reason='최신 영상·관절 정합 확인 중')
    def observe(self):
        if self.control:samples=self.control.samples(self.history[-1]['timestamp_ns']if self.history else 0)
        else:
            native,interval=self.follower.read();q=observed_positions(self.follower.precision_mapper,native,raw=self.follower.last_raw,motor_specs=self.follower.motor_specs)
            samples=[{'native':native,'interval':interval,'raw':dict(self.follower.last_raw),'q_measured':[q[n]for n in JOINTS]}]
        for sample in samples:
            native=sample['native'];interval=sample['interval'];t=interval['end']['monotonic_ns']
            if not self.history or t>self.history[-1]['timestamp_ns']:
                self.history.append({'timestamp_ns':t,'native':native,'raw':sample['raw'],'q_measured':sample['q_measured'],'feedback_interval':interval});self.stability.add(t,native)
        t=self.history[-1]['timestamp_ns']
        self.packets={n:c.nearest(t,not_after=True)for n,c in self.cameras.items()};self.observed_at=time.monotonic_ns();self.collect_control()
        self.renderer.observe(self.history[-1]['q_measured']);result=self.renderer.poll()
        if self.renderer.last_live is not None and self.state=='CONNECTING':self.state='OBSERVING'
        if self.state=='CONNECTING'and time.monotonic()>self.render_deadline:raise TimeoutError('Selected Scene did not initialize within180s')
        if result is not None:self.rendered=result
        from ..data import video
        if video._preview_sink:
            for name,packet in self.packets.items():
                if packet is not None:video._preview_sink(name,packet['rgb'],packet['sequence'],t/1e9,0)
        reason=capture_reason(self.history,self.stability,self.packets,self.store.last_sequences,busy=self.pending is not None or self.future is not None or self.rendered is not None)
        self.emit(q_measured=self.history[-1]['q_measured'],capture_ready=not reason,capture_reason=reason or'최신 측정 관절값으로 Real/Sim Capture할 수 있습니다',
            simulation=None if self.renderer.last_live is None else {key:self.renderer.last_live[key] for key in ('applied_sim_joint_rad','sim_target_joint_rad','sim_joint_delta_rad','physics_steps','simulation_time_s')},
            camera_timing={n:None if p is None else {**self.cameras[n].statistics(),'age_ms':(time.monotonic_ns()-p['read_end']['monotonic_ns'])/1e6,'joint_skew_ms':(p['read_end']['monotonic_ns']-t)/1e6}for n,p in self.packets.items()},
            render_timing=None if self.renderer.last_live is None else {'render_ms':self.renderer.last_live['render_ms'],'age_ms':(time.monotonic_ns()-self.renderer.last_live['sim_timestamp']['monotonic_ns'])/1e6})
        if self.acquiring:
            if not reason:
                state=snapshot_state(self.follower,list(self.history),self.packets,self.stability.assess());state.update(captured_host_ns=self.observed_at,camera_metadata={n:c.metadata for n,c in self.cameras.items()},device_source=self.plan.effective_settings['execution']['device_source'])
                self.command_pending=self.acquiring;self.acquiring=None;images={'real_'+n:p['rgb']for n,p in self.packets.items()}
                identifier='pair_'+self.command_pending['command_id']
                self.renderer.capture({'id':identifier,'sample':{'q_measured':state['physical_q_measured']}});self.render_deadline=time.monotonic()+180
                self.future=self.writer.submit(self.store.prepare,identifier,state,images);self.phase='prepare'
            elif time.monotonic()>self.acquire_deadline:
                self.ack(self.acquiring,'rejected','5초 안에 정합된 관측을 얻지 못했습니다: '+reason);self.acquiring=None;self.state=self.observation_state()
        self.poll_save()
        if self.pending is not None and self.rendered is not None and self.future is None and not self.closing:
            self.future=self.writer.submit(self.store.finish,self.pending,rendered=self.rendered);self.phase='finish';self.rendered=None
    def poll_save(self):
        if self.future is None or not self.future.done():return
        future=self.future;self.future=None
        try:
            result=future.result()
            if self.phase=='prepare':
                self.pending=result
                if self.closing:
                    self.ack(self.command_pending,'rejected','Stopped before Pair completion; sealed observation retained');self.command_pending=None
            else:
                self.snapshots.append(result);warnings=self.renderer.release_capture(self.pending['id'])
                if warnings:self.events({'kind':'log','payload':{'level':'warning','message':'Render cleanup: '+str(warnings)}})
                self.pending=None;self.ack(self.command_pending);self.command_pending=None;self.state='DISCONNECTING'if self.closing else self.observation_state();self.emit(snapshot=result)
        except Exception as error:
            self.last_error=str(error)
            if self.command_pending:self.ack(self.command_pending,'rejected',str(error));self.command_pending=None
            if self.control:self.control.stop()
            self.state='OBSERVING';self.emit(error=str(error),pending_snapshot=self.pending)
    def collect_control(self):
        if not self.control:return
        rows,error=self.control.drain();self.control_history.extend(rows)
        if error:
            self.last_error=error
            if self.state=='TELEOP_ACTIVE':self.state='OBSERVING'
            self.emit(error=error)
    def observation_state(self):return 'TELEOP_ACTIVE'if self.teleoperation and self.teleoperation.active else'OBSERVING'
    def close(self):
        if self.terminal:return
        self.closing=True;self.state='DISCONNECTING';self.emit();errors=[]
        stopped=True
        if self.control:
            try:self.control.stop()
            except Exception as error:errors.append(str(error))
            stopped=not(self.control.thread and self.control.thread.is_alive())
            if stopped:
                try:self.collect_control()
                except Exception as error:errors.append(str(error))
            if self.control.recording_error and self.control.recording_error not in errors:errors.append(self.control.recording_error)
        if self.acquiring:self.ack(self.acquiring,'rejected','Stopped before Capture');self.acquiring=None
        try:close_devices({**(self.devices if stopped else{}),**self.cameras})
        except Exception as error:errors.append(str(error))
        if self.renderer:
            try:self.renderer.close()
            except Exception as error:errors.append(str(error))
        try:
            if self.future is not None:
                try:self.future.result()
                except Exception:pass
                self.poll_save()
            if self.command_pending:self.ack(self.command_pending,'rejected','Stopped before Pair completion; pending observation retained');self.command_pending=None
            self.writer.shutdown(wait=True)
        except Exception as error:errors.append(str(error))
        self.terminal=True;self.state='FAILED'if errors else'DISCONNECTED';self.emit(cleanup_errors=errors)
        if errors:raise DeviceError('real_sim_close','; '.join(errors),effect='not_applied')


def run(plan,*,events,commands):
    from ..recipe import verify_prepared_inputs
    from ..run import StageResult
    from .session_devices import construct
    verify_prepared_inputs(plan);devices,cameras,_=construct(plan);plan.output_path.mkdir();session=None;error=None
    try:
        session=RealSimSession(plan,devices,cameras,events=events);session.connect()
        while not session.terminal:
            begin=time.monotonic();session.dispatch(commands())
            if session.terminal:break
            if time.monotonic_ns()-session.last_heartbeat>3000000000:raise DeviceError('real_sim','UI heartbeat lost; closing observation',effect='not_applied')
            if session.renderer.capture_id is not None and time.monotonic()>session.render_deadline:raise TimeoutError('Frozen Pair render timed out; observation retained')
            session.observe();time.sleep(max(0,1/30-(time.monotonic()-begin)))
    except Exception as exc:error=str(exc);raise
    finally:
        try:
            if session:session.close()
            else:close_devices({**devices,**cameras})
        finally:
            report={'state':session.state if session else'FAILED','error':error or(session.last_error if session else None),'scene_identity':dict(plan.scene_identity),'snapshots':session.snapshots if session else[],
            'pending_snapshot':session.pending if session else None,'hardware_connected':plan.effective_settings['execution']['device_source']=='hardware',
            'pending_control_rows':len(session.control.rows)if session and session.control else 0,'control_record_error':session.control.recording_error if session and session.control else None,
            'unwritten_control_records':list(session.control.rows)if session and session.control else[],
            'recent_control_records':list(session.control_history)if session else[],
            'teleoperation_activation':session.teleoperation.last_activation if session and session.teleoperation else None,'teleoperation_last_attempt':session.teleoperation.last_attempt if session and session.teleoperation else None,'motion_verified':False,'stop_policy':'preserve_torque_no_new_goal'}
            if report['error']or report['snapshots']or report['pending_snapshot']or report['pending_control_rows']or report['state']=='FAILED':
                atomic_json(plan.output_path/'session-report.json',report)
            else:
                import shutil
                shutil.rmtree(plan.output_path)
    refs=(str(plan.output_path),)if plan.output_path.exists()else()
    return StageResult('cancelled'if session.cancelled else'completed',refs,0,{'snapshots':len(session.snapshots),'saved':bool(refs),'motion_verified':False})
