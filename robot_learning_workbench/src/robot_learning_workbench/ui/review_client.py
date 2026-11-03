"""One Curation decoder process; one in-flight request and one latest target."""
import json,shutil
from pathlib import Path
from PyQt6.QtCore import QObject,QProcess,pyqtSignal


class ReviewClient(QObject):
    opened=pyqtSignal(object)
    frame=pyqtSignal(object)
    error=pyqtSignal(str)

    def __init__(self,python,workspace,directory,parent=None):
        super().__init__(parent);self.python=python;self.workspace=str(workspace);self.directory=Path(directory);self.process=QProcess(self);self.closing=False;self.diagnostics=''
        self.process.readyReadStandardOutput.connect(self.read);self.process.started.connect(self.send)
        self.process.errorOccurred.connect(self.failed);self.process.finished.connect(self.ended)
        self.process.readyReadStandardError.connect(self.read_error)
        self.buffer=bytearray();self.latest=None;self.inflight=None;self.number=0;self.epoch=0;self.seek=0;self.context=None

    def failed(self,error):
        if not self.closing and error==QProcess.ProcessError.FailedToStart:self.error.emit(self.process.errorString())

    def read_error(self):self.diagnostics=(self.diagnostics+bytes(self.process.readAllStandardError()).decode(errors='replace'))[-2000:]

    def ended(self,code,*_):
        self.inflight=None
        if code and not self.closing:self.error.emit('Review worker 종료: '+self.diagnostics)

    def select(self,source,selection_id):
        self.epoch+=1;self.context=(source,selection_id)

    def request(self,frame,*,manual=False):
        if self.context is None:return
        if manual:self.seek+=1
        self.number+=1;self.latest=dict(id=self.number,epoch=self.epoch,seek=self.seek,
            source=self.context[0],selection_id=self.context[1],frame=frame)
        if self.process.state()==QProcess.ProcessState.NotRunning:
            self.closing=False;self.process.start(self.python,['-B','-m','robot_learning_workbench.ui.review_worker','--output',str(self.directory),'--workspace',self.workspace])
        else:self.send()

    def send(self):
        if self.inflight is not None or self.latest is None or self.process.state()!=QProcess.ProcessState.Running:return
        self.inflight=self.latest;self.latest=None;self.process.write(json.dumps(self.inflight).encode()+b'\n')

    def read(self):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        while b'\n'in self.buffer:
            line,_,tail=self.buffer.partition(b'\n');self.buffer=bytearray(tail)
            try:response=json.loads(line)
            except ValueError:self.error.emit('Review worker 응답 오류');continue
            self.inflight=None
            if response['epoch']==self.epoch and response.get('ok')and 'info'in response:self.opened.emit(response['info'])
            if response['epoch']==self.epoch and response['seek']==self.seek:
                if not response['ok']:self.error.emit(response['error'])
                else:
                    from ..run import read_preview_frame
                    result=response['result'];result['images']={}
                    for camera in result['video_pts_s']:
                        item=read_preview_frame(self.directory,camera)
                        if item is not None and item[0]['frame_index']==result['selection_frame']:result['images'][camera]=item[1]
                    self.frame.emit(result)
            self.send()

    def close(self):
        self.latest=None;self.epoch+=1;self.closing=True
        if self.process.state()!=QProcess.ProcessState.NotRunning:
            self.process.write(b'{"operation":"close"}\n');self.process.closeWriteChannel()
            if not self.process.waitForFinished(1000):
                self.process.terminate()
                if not self.process.waitForFinished(1000):self.process.kill();self.process.waitForFinished(1000)
        self.inflight=None;self.buffer.clear();shutil.rmtree(self.directory,ignore_errors=True)
