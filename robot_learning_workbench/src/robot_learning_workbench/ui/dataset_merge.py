"""Explicit multi-selection of official Dataset folders; merging stays in Backend."""
from pathlib import Path
from PyQt6.QtCore import Qt,QProcess
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QListWidget,QListWidgetItem,QPushButton,QLabel,QFileDialog

from .jobs import BackendJob


class DatasetMergeDialog(QDialog):
    def __init__(self,python,workspace,rows=(),parent=None):
        super().__init__(parent);self.workspace=Path(workspace);self.setWindowTitle('Dataset Merge');self.resize(760,440)
        layout=QVBoxLayout(self);layout.addWidget(QLabel('합칠 LeRobot Dataset을 둘 이상 선택하세요. 현재 편집 중인 데이터는 자동으로 포함하지 않습니다.'))
        self.list=QListWidget();self.list.setWordWrap(True);layout.addWidget(self.list,1)
        self.status=QLabel();self.status.setWordWrap(True);layout.addWidget(self.status)
        buttons=QHBoxLayout();layout.addLayout(buttons)
        add=QPushButton('외부 Dataset 폴더 추가');add.clicked.connect(self.browse);buttons.addWidget(add);buttons.addStretch()
        self.merge_button=QPushButton('선택 Dataset 합치기');self.merge_button.clicked.connect(self.accept);buttons.addWidget(self.merge_button)
        cancel=QPushButton('취소');cancel.clicked.connect(self.reject);buttons.addWidget(cancel)
        for row in rows:
            if row['category']=='lerobot'and row['readable']:self.add_item(Path(row['path']),row['name'],row['episodes'])
        self.list.itemChanged.connect(self.update_count);self.update_count()
        self.job=BackendJob(python,self);self.job.finished.connect(self.loaded);self.catalog_started=False

    def showEvent(self,event):
        super().showEvent(event)
        if not self.catalog_started:
            self.catalog_started=True;self.status.setText('LeRobot Dataset 목록을 읽는 중…');self.job.start('curation_datasets',workspace=str(self.workspace))

    def loaded(self,response):
        if not response.get('ok'):
            self.status.setText(response.get('error',{}).get('message','목록을 읽지 못했습니다. 외부 폴더를 추가할 수 있습니다.'));return
        for row in response['result']['datasets']:
            if row['category']=='lerobot'and row['readable']:self.add_item(Path(row['path']),row['name'],row['episodes'])
        self.update_count()

    def done(self,result):
        if self.job.process.state()!=QProcess.ProcessState.NotRunning:
            self.job.stop()
            if not self.job.process.waitForFinished(1000):self.job.process.kill();self.job.process.waitForFinished(1000)
        super().done(result)

    @property
    def paths(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole)for i in range(self.list.count())if self.list.item(i).checkState()==Qt.CheckState.Checked]

    def add_item(self,path,name,episodes=None):
        path=str(path.resolve())
        if any(self.list.item(i).data(Qt.ItemDataRole.UserRole)==path for i in range(self.list.count())):return
        item=QListWidgetItem(name+(f' · {episodes} Episode'if episodes is not None else'')+'\n'+path)
        item.setData(Qt.ItemDataRole.UserRole,path);item.setFlags(item.flags()|Qt.ItemFlag.ItemIsUserCheckable);item.setCheckState(Qt.CheckState.Unchecked);self.list.addItem(item)

    def add_folder(self,path):
        path=Path(path).resolve()
        if not(path/'meta/info.json').is_file():self.status.setText('meta/info.json이 있는 LeRobot Dataset 최상위 폴더를 선택하세요.');return
        self.add_item(path,path.name);self.update_count()

    def browse(self):
        path=QFileDialog.getExistingDirectory(self,'추가할 LeRobot Dataset',str(self.workspace/'dataset'))
        if path:self.add_folder(path)

    def update_count(self,*_):
        count=len(self.paths);self.merge_button.setEnabled(count>=2);self.status.setText(f'{count}개 선택 · 출력 폴더는 다음 화면에서 선택합니다.')
