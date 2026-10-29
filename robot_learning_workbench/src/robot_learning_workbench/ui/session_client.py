"""Qt presentation of the existing R03 lifecycle and explicit session commands."""
import time,uuid
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
        super().__init__(parent);self.modules=str(modules);self.handle=None;self.busy=False;self.running=False;self.phase=None;self.cursor=0;self.generations={};self.heartbeat=0
        self.job=BackendJob(python,self);self.job.finished.connect(self.done);self.job.log.connect(self.error)
        self.timer=QTimer(self);self.timer.setInterval(80);self.timer.timeout.connect(self.poll);self.timer.start()
    def active(self):return self.busy or self.running
    def connect_session(self,path):
        if self.active():raise ValueError('기존 연결 종료를 기다리세요')
        import yaml
        self.stage=yaml.safe_load(Path(path).read_text())['stage']
        self.path=str(path);self.busy=True;self.phase='prepare';self.job.start('prepare',path=self.path,modules=self.modules)
    def done(self,response):
        self.busy=False
        if not response.get('ok'):self.error.emit(response.get('error',{}).get('message','Backend error'));self.terminal.emit('failed');return
        result=response['result']
        if self.phase=='prepare':
            if not result.get('runnable'):self.error.emit(result['reason']);return
            self.busy=True;self.phase='start';self.job.start('start',path=self.path,modules=self.modules,request_id=uuid.uuid4().hex,expected_recipe_sha256=result['recipe_sha256'],expected_prepared_sha256=result['prepared_sha256'])
        elif self.phase=='start':self.handle=result;self.running=True;self.cursor=0;self.generations.clear();self.heartbeat=0
    def send(self,kind,payload=None):
        if not self.running:raise ValueError('연결된 Session이 없습니다')
        from ..run import RunHandle,send_command
        h=self.handle;key=uuid.uuid4().hex
        send_command(RunHandle(h['run_id'],h['request_id'],Path(h['run_dir'])),{'command_id':key,'kind':kind,'payload':payload or {}})
        return key
    def poll(self):
        if not self.running:return
        from ..run import read_status,read_events,read_preview_frame
        try:
            status=read_status(self.handle['run_dir']).status
            if status in('completed','failed','cancelled','unknown'):
                # Drain final saved-snapshot/ACK events before publishing terminal.
                while self.read_events():pass
                if status=='unknown':
                    import shutil
                    shutil.rmtree(Path(self.handle['run_dir'])/'preview',ignore_errors=True)
                self.running=False;self.terminal.emit(status);return
            now=time.monotonic_ns()
            if self.stage in('scene_capture','capture_session','paired_session')and now-self.heartbeat>400_000_000:
                from ..run import RunHandle,touch_session
                h=self.handle;touch_session(RunHandle(h['run_id'],h['request_id'],Path(h['run_dir'])),now);self.heartbeat=now
            self.read_events()
            for camera in('side','wrist','sim_side','sim_wrist'):
                frame=read_preview_frame(self.handle['run_dir'],camera)
                if frame is not None:
                    meta,raw=frame
                    if self.generations.get(camera)!=meta['generation']:
                        self.generations[camera]=meta['generation'];self.preview.emit(camera,raw)
        except Exception as error:self.error.emit(str(error))
    def read_events(self):
        from ..run import read_events
        page=read_events(self.handle['run_dir'],self.cursor,200);self.cursor=page.next_seq
        for event in page.items:
            self.received.emit(event)
            if event['kind']=='status':self.progress.emit(event['payload'].get('progress',{}))
        return len(page.items)
    def cancel(self):
        if self.running:self.send('cancel')
