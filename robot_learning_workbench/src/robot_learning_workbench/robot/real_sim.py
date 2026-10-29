"""Follower feedback → native Scene rendering and four-image Paired Capture.

This connection has no Leader, Teleoperation capability, Goal or Torque command.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from .capture import Stability,observed_positions,snapshot_state,capture_reason
from .calibration import JOINTS
from .devices import close_devices,DeviceError
from .snapshots import SnapshotStore
from .render_transport import RenderProcess
from ..data.native import atomic_json


class RealSimSession:
    def __init__(self,plan,devices,cameras,*,events):
        from real2sim_builder.project import Project
        if set(devices)!={'follower'}:raise ValueError('Real/Sim observes only the Follower')
        self.plan=plan;self.devices=devices;self.cameras=cameras;self.events=events;self.follower=devices['follower']
        self.project=Project(plan.resolved_inputs['project']['root']);self.history=deque(maxlen=180);self.stability=Stability();self.packets={}
        self.store=SnapshotStore(self.project,session_id=plan.output_path.name.replace('-','_'),model=plan.resolved_inputs['robot_model']['path'],mapping=self.follower.precision_mapper.metadata())
        self.state='DISCONNECTED';self.terminal=False;self.closing=False;self.cancelled=False;self.renderer=None;self.snapshots=[];self.seen=set();self.last_heartbeat=time.monotonic_ns()
        self.writer=ThreadPoolExecutor(max_workers=1,thread_name_prefix='paired-capture');self.future=None;self.phase=None;self.acquiring=None;self.pending=None;self.command_pending=None
    def emit(self,**progress):
        busy=self.acquiring is not None or self.pending is not None or self.future is not None
        self.events({'kind':'status','payload':{'progress':{'session_state':self.state,'device_source':self.plan.effective_settings['execution']['device_source'],
            'capture_request_allowed':self.state=='OBSERVING'and not busy and not self.closing,'capture_pending':busy,'snapshots':len(self.snapshots),**progress}}})
    def ack(self,c,status='completed',reason=None):
        self.events({'kind':'command_ack','payload':{'command_id':c['command_id'],'status':status,**({'reason':reason}if reason else{})}})
    def connect(self):
        self.state='CONNECTING';self.emit(capture_reason='Follower/Camera 연결과 선택 Scene 초기화 중')
        try:
            self.follower.connect()
            for camera in self.cameras.values():camera.start()
            from ..recipe import verify_prepared_inputs
            verify_prepared_inputs(self.plan)
            self.renderer=RenderProcess(self.plan,self.follower.precision_mapper.metadata());self.render_deadline=time.monotonic()+180
        except BaseException:self.close();raise
    def dispatch(self,commands):
        rows=list(commands);stops=[c for c in rows if c['kind']in('cancel','session_disconnect','session_finish')]
        for c in rows:
            if c['kind']=='session_heartbeat':
                t=c['payload']['timestamp_ns']
                if 0<=time.monotonic_ns()-t<=1000000000:self.last_heartbeat=t
                continue
            if c['command_id']in self.seen:continue
            self.seen.add(c['command_id'])
            if stops and c not in stops:self.ack(c,'rejected','Stop/cancel takes precedence');continue
            if c in stops:
                self.cancelled|=c['kind']=='cancel';self.close();self.ack(c);continue
            if c['kind']!='session_snapshot':self.ack(c,'rejected','Real/Sim is a read-only observation connection');continue
            if self.state!='OBSERVING'or self.acquiring is not None or self.pending is not None or self.future is not None:
                self.ack(c,'rejected','Wait for Real/Sim connection or current Capture to finish');continue
            self.acquiring=c;self.acquire_deadline=time.monotonic()+5;self.state='CAPTURING';self.emit(capture_reason='최신 영상·관절 정합 확인 중')
    def observe(self):
        native,interval=self.follower.read();t=interval['end']['monotonic_ns'];q=observed_positions(self.follower.precision_mapper,native,raw=self.follower.last_raw,motor_specs=self.follower.motor_specs)
        self.history.append({'timestamp_ns':t,'native':native,'raw':dict(self.follower.last_raw),'q_measured':[q[n]for n in JOINTS],'feedback_interval':interval})
        self.stability.add(t,native);self.packets={n:c.nearest(t,not_after=True)for n,c in self.cameras.items()};self.observed_at=time.monotonic_ns()
        self.renderer.observe(self.history[-1]['q_measured']);result=self.renderer.poll()
        if self.renderer.last_live is not None and self.state=='CONNECTING':self.state='OBSERVING'
        if self.state=='CONNECTING'and time.monotonic()>self.render_deadline:raise TimeoutError('Selected Scene did not initialize within180s')
        if self.pending is not None and result is not None:
            self.future=self.writer.submit(self.store.finish,self.pending,rendered=result);self.phase='finish'
        from ..data import video
        if video._preview_sink:
            for name,packet in self.packets.items():
                if packet is not None:video._preview_sink(name,packet['rgb'],packet['sequence'],t/1e9,0)
        reason=capture_reason(self.history,self.stability,self.packets,self.store.last_sequences,busy=self.pending is not None or self.future is not None)
        self.emit(q_measured=self.history[-1]['q_measured'],capture_ready=not reason,capture_reason=reason or'최신 측정 관절값으로 Real/Sim Capture할 수 있습니다',
            camera_timing={n:None if p is None else {**self.cameras[n].statistics(),'age_ms':(time.monotonic_ns()-p['read_end']['monotonic_ns'])/1e6,'joint_skew_ms':(p['read_end']['monotonic_ns']-t)/1e6}for n,p in self.packets.items()},
            render_timing=None if self.renderer.last_live is None else {'render_ms':self.renderer.last_live['render_ms'],'age_ms':(time.monotonic_ns()-self.renderer.last_live['sim_timestamp']['monotonic_ns'])/1e6})
        if self.acquiring:
            if not reason:
                state=snapshot_state(self.follower,list(self.history),self.packets,self.stability.assess());state.update(captured_host_ns=self.observed_at,camera_metadata={n:c.metadata for n,c in self.cameras.items()},device_source=self.plan.effective_settings['execution']['device_source'])
                self.command_pending=self.acquiring;self.acquiring=None;images={'real_'+n:p['rgb']for n,p in self.packets.items()}
                self.future=self.writer.submit(self.store.prepare,'pair_'+self.command_pending['command_id'],state,images);self.phase='prepare'
            elif time.monotonic()>self.acquire_deadline:
                self.ack(self.acquiring,'rejected','5초 안에 정합된 관측을 얻지 못했습니다: '+reason);self.acquiring=None;self.state='OBSERVING'
        self.poll_save()
    def poll_save(self):
        if self.future is None or not self.future.done():return
        future=self.future;self.future=None
        try:
            result=future.result()
            if self.phase=='prepare':
                self.pending=result
                if self.closing:
                    self.ack(self.command_pending,'rejected','Stopped before Sim render; sealed observation retained');self.command_pending=None
                else:self.renderer.capture(self.pending);self.render_deadline=time.monotonic()+180
            else:
                self.snapshots.append(result);warnings=self.renderer.release_capture(self.pending['id'])
                if warnings:self.events({'kind':'log','payload':{'level':'warning','message':'Render cleanup: '+str(warnings)}})
                self.pending=None;self.ack(self.command_pending);self.command_pending=None;self.state='DISCONNECTING'if self.closing else'OBSERVING';self.emit(snapshot=result)
        except Exception as error:
            if self.command_pending:self.ack(self.command_pending,'rejected',str(error));self.command_pending=None
            self.state='OBSERVING';self.emit(error=str(error),pending_snapshot=self.pending)
    def close(self):
        if self.terminal:return
        self.closing=True;self.state='DISCONNECTING';self.emit();errors=[]
        if self.acquiring:self.ack(self.acquiring,'rejected','Stopped before Capture');self.acquiring=None
        try:close_devices({**self.devices,**self.cameras})
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
    from .session_devices import construct_observation
    verify_prepared_inputs(plan);devices,cameras=construct_observation(plan);plan.output_path.mkdir();session=None;error=None
    try:
        session=RealSimSession(plan,devices,cameras,events=events);session.connect()
        while not session.terminal:
            begin=time.monotonic();session.dispatch(commands())
            if session.terminal:break
            if time.monotonic_ns()-session.last_heartbeat>3000000000:raise DeviceError('real_sim','UI heartbeat lost; closing observation',effect='not_applied')
            if session.pending is not None and time.monotonic()>session.render_deadline:raise TimeoutError('Frozen Pair render timed out; observation retained')
            session.observe();time.sleep(max(0,1/30-(time.monotonic()-begin)))
    except Exception as exc:error=str(exc);raise
    finally:
        try:
            if session:session.close()
            else:close_devices({**devices,**cameras})
        finally:atomic_json(plan.output_path/'session-report.json',{'state':session.state if session else'FAILED','error':error,'scene_identity':dict(plan.scene_identity),'snapshots':session.snapshots if session else[],
            'pending_snapshot':session.pending if session else None,'hardware_connected':plan.effective_settings['execution']['device_source']=='hardware','command_sent':False,'goal_torque_writes':0})
    return StageResult('cancelled'if session.cancelled else'completed',(str(plan.output_path),),0,{'snapshots':len(session.snapshots),'command_sent':False})
