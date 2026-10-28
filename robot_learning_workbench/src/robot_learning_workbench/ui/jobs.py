"""A Qt-owned subprocess for one explicit backend call; no engine in the GUI.

https://doc.qt.io/qt-6.11/qprocess.html
"""
import json
from PyQt6.QtCore import QObject,QProcess,pyqtSignal


class BackendJob(QObject):
    finished=pyqtSignal(object)
    log=pyqtSignal(str)
    def __init__(self,python,parent=None):
        super().__init__(parent);self.python=python;self.process=QProcess(self);self.buffer=bytearray()
        self.process.readyReadStandardOutput.connect(lambda:self.buffer.extend(bytes(self.process.readAllStandardOutput())))
        self.process.readyReadStandardError.connect(lambda:self.log.emit(bytes(self.process.readAllStandardError()).decode(errors='replace')))
        self.process.finished.connect(self.done)
        self.process.errorOccurred.connect(self.failed)
    def failed(self,error):
        message=self.process.errorString();self.log.emit(message)
        if error==QProcess.ProcessError.FailedToStart:self.finished.emit({'ok':False,'error':{'message':message}})
    def start(self,operation,**arguments):
        if self.process.state()!=QProcess.ProcessState.NotRunning:raise RuntimeError('이 작업이 끝난 뒤 다시 실행하세요')
        from PyQt6.QtCore import QProcessEnvironment
        env=QProcessEnvironment.systemEnvironment()
        if operation=='hub_resolve':env.insert('HF_HUB_OFFLINE','0')
        self.process.setProcessEnvironment(env)
        self.buffer.clear();self.process.start(self.python,['-B','-m','robot_learning_workbench.ui.operations'])
        self.process.write(json.dumps({'operation':operation,'arguments':arguments}).encode());self.process.closeWriteChannel()
    def done(self,*_):
        self.buffer.extend(bytes(self.process.readAllStandardOutput()))
        try:result=json.loads(self.buffer)
        except ValueError:result={'ok':False,'error':{'message':'Backend 응답을 읽을 수 없습니다 (exit '+str(self.process.exitCode())+'). '+self.buffer.decode(errors='replace')[-2000:]}}
        self.finished.emit(result)
    def stop(self):
        if self.process.state()!=QProcess.ProcessState.NotRunning:self.process.terminate()
