"""Choose a recorded Dataset or saved selection for Annotation/DataGen."""
from pathlib import Path
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,QFileDialog
from .dataset_picker import DatasetPicker
from .revision_picker import RevisionPicker
from .jobs import BackendJob


class DatasetInputDialog(QDialog):
    def __init__(self,python,workspace,stage,parent=None):
        super().__init__(parent);self.workspace=Path(workspace);self.path='';self.pending=None;self.target=None;self.closed=False
        self.setWindowTitle('입력 Dataset · 원본 또는 선별본');self.resize(720,240)
        layout=QVBoxLayout(self);self.datasets=DatasetPicker(python,workspace,self);layout.addWidget(self.datasets)
        kind='source'if stage=='annotation'else'annotation';self.datasets.kind.setCurrentIndex(self.datasets.kind.findData(kind))
        self.revisions=RevisionPicker(self);layout.addWidget(self.revisions)
        self.status=QLabel('Dataset을 선택하세요.');self.status.setWordWrap(True);layout.addWidget(self.status)
        files=QHBoxLayout();layout.addLayout(files)
        folder=QPushButton('외부 Dataset 폴더');revision=QPushButton('Revision 파일');files.addWidget(folder);files.addWidget(revision)
        folder.clicked.connect(lambda:self.browse(False,kind));revision.clicked.connect(lambda:self.browse(True,kind))
        buttons=QHBoxLayout();layout.addLayout(buttons);buttons.addStretch()
        self.open_button=QPushButton('선택');self.open_button.setEnabled(False);cancel=QPushButton('취소');buttons.addWidget(self.open_button);buttons.addWidget(cancel)
        self.open_button.clicked.connect(self.accept);cancel.clicked.connect(self.reject)
        self.job=BackendJob(python,self);self.job.finished.connect(self.loaded)
        self.datasets.selected.connect(self.load);self.datasets.cleared.connect(self.clear);self.revisions.selected.connect(self.select)

    def clear(self):
        self.path='';self.pending=None;self.target=None;self.revisions.reset();self.open_button.setEnabled(False)

    def load(self,path):
        if self.closed:return
        self.path='';self.target=str(path);self.pending=self.target;self.open_button.setEnabled(False);self.revisions.setEnabled(False)
        if self.job.process.state()!=QProcess.ProcessState.NotRunning:return
        path=self.pending;self.pending=None;self.datasets.setEnabled(False);self.status.setText('저장된 Dataset과 Revision을 읽는 중…')
        self.job.start('curation_revisions',workspace=str(self.workspace),path=path)

    def loaded(self,response):
        if self.closed:return
        if self.pending:self.load(self.pending);return
        self.datasets.setEnabled(True)
        if self.target is None:return
        if not response.get('ok'):
            self.clear();self.status.setText(response.get('error',{}).get('message','Dataset을 읽지 못했습니다.'));return
        data=response['result'];self.datasets.show_original(data['original'])
        self.revisions.set_source(data['original_path'],data['revision'],data['revisions']);self.select(data['path'])

    def select(self,path):
        self.path=path;self.status.setText(path);self.open_button.setEnabled(bool(path))

    def browse(self,revision,kind):
        if revision:path,_=QFileDialog.getOpenFileName(self,'Revision 파일',str(self.workspace/'curation'/kind),'JSON (*.json)')
        else:path=QFileDialog.getExistingDirectory(self,'Dataset 폴더',str(self.workspace/kind))
        if path:self.load(path)

    def done(self,result):
        self.closed=True
        for job in(self.job,self.datasets.job):
            if job.process.state()!=QProcess.ProcessState.NotRunning:
                job.stop()
                if not job.process.waitForFinished(1000):job.process.kill();job.process.waitForFinished(1000)
        super().done(result)
