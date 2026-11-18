"""Qt presentation of the existing R03 lifecycle and explicit session commands."""
import json,time,uuid
from pathlib import Path
from PyQt6.QtCore import QObject,QTimer,pyqtSignal
from .jobs import BackendJob


class SessionClient(QObject):
    progress=pyqtSignal(object)
    received=pyqtSignal(object)
    preview=pyqtSignal(str,bytes)
    terminal=pyqtSignal(str)
    error=pyqtSignal(str)
    def __init__(self,python,modules,parent=None):
        super().__init__(parent);self.modules=str(modules);self.handle=None;self.busy=False;self.running=False;self.phase=None;self.cursor=0;self.generations={};self.heartbeat=0;self.cancel_requested=False
        self.exit_pending=None
        self.startup_times_ns={}
        self.job=BackendJob(python,self);self.job.finished.connect(self.done);self.job.log.connect(self.error)
        self.timer=QTimer(self);self.timer.setInterval(80);self.timer.timeout.connect(self.poll);self.timer.start()
    def active(self):return self.busy or self.running
    def connect_session(self,path):
        if self.active():raise ValueError('기존 연결 종료를 기다리세요')
        import yaml
        self.stage=yaml.safe_load(Path(path).read_text())['stage']
        self.startup_times_ns={'prepare_started':time.monotonic_ns()};self.progress.emit({'connection_phase':'scene_check','session_state':'CONNECTING'})
        self.path=str(path);self.busy=True;self.phase='prepare';self.cancel_requested=False;self.job.start('prepare',path=self.path,modules=self.modules)
    def done(self,response):
        self.busy=False
        if not response.get('ok'):self.error.emit(response.get('error',{}).get('message','Backend error'));self.terminal.emit('failed');return
        result=response['result']
        if self.phase=='prepare':
            self.startup_times_ns['prepared']=time.monotonic_ns()
            if self.cancel_requested:self.terminal.emit('cancelled');return
            if not result.get('runnable'):self.error.emit(result['reason']);self.terminal.emit('failed');return
            self.start_prepared(self.path,result)
        elif self.phase=='start':
            self.startup_times_ns['worker_spawn_received']=time.monotonic_ns()
            self.progress.emit({'client_startup_times_ns':dict(self.startup_times_ns)})
            self.handle=result;self.running=True;self.cursor=0;self.generations.clear();self.heartbeat=0;self.exit_pending=None
            if self.cancel_requested:self.send('cancel')
    def start_prepared(self,path,prepared):
        if self.active():raise ValueError('기존 실행 종료를 기다리세요')
        import yaml
        self.path=str(path);self.stage=yaml.safe_load(Path(path).read_text())['stage']
        if not hasattr(self,'startup_times_ns'):self.startup_times_ns={}
        self.startup_times_ns['worker_spawn_requested']=time.monotonic_ns()
        self.busy=True;self.phase='start';self.cancel_requested=False
        self.job.start('start',path=self.path,modules=self.modules,request_id=uuid.uuid4().hex,expected_recipe_sha256=prepared['recipe_sha256'],expected_prepared_sha256=prepared['prepared_sha256'])

    def send(self,kind,payload=None,*,context=None):
        if not self.running:raise ValueError('연결된 Session이 없습니다')
        from ..run import RunHandle,send_command
        h=self.handle;key=uuid.uuid4().hex
        payload=dict(payload or{})
        if kind=='session_snapshot'and self.stage in('scene_capture','capture_session','paired_session'):
            payload.setdefault('requested_ns',time.monotonic_ns());payload.setdefault('policy','observation')
        command={'command_id':key,'kind':kind,'payload':payload}
        if context:
            for field in('episode_id','env_index'):
                if field in context:command[field]=context[field]
        receipt=send_command(RunHandle(h['run_id'],h['request_id'],Path(h['run_dir'])),command)
        if receipt.status=='rejected':raise ValueError(receipt.reason)
        if kind=='session_snapshot':
            self.progress.emit({'capture_update':dict(id=('pair_'if self.stage=='paired_session'else'observation_'if self.stage=='scene_capture'else'snapshot_')+key,
                command_id=key,phase='REQUESTED',requested_ns=payload.get('requested_ns'),path=None,q_measured=[])})
        return key
    def poll(self):
        if not self.running and self.exit_pending is None:return
        from ..run import read_status,read_events,read_preview_frame
        try:
            observed=read_status(self.handle['run_dir']if self.running else self.exit_pending)
            if not self.running:
                if observed.exit_code is not None or observed.process_error:
                    self.exit_pending=None
                    if observed.process_error:self.error.emit('작업 '+observed.status+' · '+observed.process_error['message'])
                return
            status=observed.status
            if status in('completed','failed','cancelled','unknown'):
                # Drain final saved-snapshot/ACK events before publishing terminal.
                while self.read_events():pass
                if status=='unknown':
                    import shutil
                    shutil.rmtree(Path(self.handle['run_dir'])/'preview',ignore_errors=True)
                self.running=False;self.terminal.emit(status)
                if observed.process_error:self.error.emit('작업 '+status+' · '+observed.process_error['message'])
                elif observed.exit_code is None and status!='unknown':
                    spawn=Path(self.handle['run_dir'])/'spawn.json'
                    if spawn.is_file() and json.loads(spawn.read_text()).get('exit_monitored'):self.exit_pending=self.handle['run_dir']
                return
            now=time.monotonic_ns()
            if self.stage in('scene_capture','capture_session','paired_session','precision_session')and now-self.heartbeat>400_000_000:
                from ..run import RunHandle,touch_session
                h=self.handle;touch_session(RunHandle(h['run_id'],h['request_id'],Path(h['run_dir'])),now);self.heartbeat=now
            self.read_events()
            for camera in('side','wrist','sim_side','sim_wrist'):
                frame=read_preview_frame(self.handle['run_dir'],camera)
                if frame is not None:
                    meta,raw=frame
                    if self.generations.get(camera)!=meta['generation']:
                        self.generations[camera]=meta['generation'];self.preview.emit(camera,raw)
        except Exception as error:
            if not self.running:self.exit_pending=None
            self.error.emit(str(error))
    def read_events(self):
        from ..run import read_events
        page=read_events(self.handle['run_dir'],self.cursor,200);self.cursor=page.next_seq
        for event in page.items:
            self.received.emit(event)
            if event['kind']=='status':self.progress.emit(event['payload'].get('progress',{}))
        return len(page.items)
    def cancel(self):
        self.cancel_requested=True
        if self.running:self.send('cancel')

    def finish(self):
        self.cancel_requested=True
        if self.running:self.send('session_finish')
