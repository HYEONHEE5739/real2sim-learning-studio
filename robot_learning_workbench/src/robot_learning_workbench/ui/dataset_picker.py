"""Workspace Dataset selection; canonical reading stays in the Backend."""
from PyQt6.QtCore import QProcess,pyqtSignal
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QComboBox,QLabel
from .jobs import BackendJob


class DatasetPicker(QWidget):
    selected=pyqtSignal(str)
    cleared=pyqtSignal()

    def __init__(self,python,workspace,parent=None):
        super().__init__(parent);self.workspace=str(workspace);self.rows=[];self.last_path=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0);row=QHBoxLayout();layout.addLayout(row)
        self.kind=QComboBox();row.addWidget(self.kind)
        for label,key in [('전체',''),('Source','source'),('Annotation','annotation'),('DataGen','datagen'),('LeRobot Dataset','lerobot')]:self.kind.addItem(label,key)
        self.choices=QComboBox();self.choices.setMinimumContentsLength(15);row.addWidget(self.choices,1)
        self.status=QLabel('저장된 Dataset을 찾습니다.');self.status.setWordWrap(True);layout.addWidget(self.status)
        self.job=BackendJob(python,self);self.job.finished.connect(self.finished)
        self.kind.currentIndexChanged.connect(self.filter_rows);self.choices.currentIndexChanged.connect(self.selection_changed);self.choices.activated.connect(self.activate)
        self.selection_changed()

    def showEvent(self,event):
        super().showEvent(event);self.refresh()

    def refresh(self):
        if self.job.process.state()!=QProcess.ProcessState.NotRunning:return
        self.status.show();self.status.setText('저장된 Dataset 목록을 읽는 중…')
        self.job.start('curation_datasets',workspace=self.workspace)

    def finished(self,response):
        if not response.get('ok'):
            self.status.setText(response.get('error',{}).get('message','Dataset 목록을 읽지 못했습니다.'));return
        self.rows=response['result']['datasets'];self.filter_rows()

    def filter_rows(self,*_):
        previous=self.choices.currentData();path=previous['path']if previous else None
        rows=[r for r in self.rows if not self.kind.currentData()or r['category']==self.kind.currentData()]
        self.choices.blockSignals(True);self.choices.clear()
        for row in rows:
            label=f"{row['name']} · {row['episodes']} Episode / {row['frames']} frame"
            if not row['readable']:label+=' · 읽기 오류'
            self.choices.addItem(label,row)
        index=next((i for i,r in enumerate(rows)if r['path']==path),next((i for i,r in enumerate(rows)if r['readable']and r['episodes']),0))
        self.choices.setCurrentIndex(index if rows else-1);self.choices.blockSignals(False);self.selection_changed()

    def selection_changed(self,*_):
        row=self.choices.currentData()
        self.status.setVisible(not row or not row['readable']or not row['episodes']);self.choices.setToolTip(row['path']if row else'')
        if row:self.status.setText(row['error']if not row['readable']else row['path']+(' · 저장 완료된 Episode가 없습니다.'if not row['episodes']else''))
        else:self.status.setText('이 종류의 저장된 Dataset이 없습니다. 외부 결과는 데이터 열기로 선택하세요.')

        if row and row['path']!=self.last_path:
            self.last_path=row['path'];self.selected.emit(row['path'])
        elif row is None:
            self.last_path=None;self.cleared.emit()

    def activate(self,*_):
        row=self.choices.currentData()
        if row:self.selected.emit(row['path'])

    def show_original(self,row):
        self.blockSignals(True)
        try:
            self.rows=[item for item in self.rows if item['path']!=row['path']]+[row]
            if self.kind.currentData()and self.kind.currentData()!=row['category']:self.kind.setCurrentIndex(0)
            self.filter_rows()
            index=next(i for i in range(self.choices.count())if self.choices.itemData(i)['path']==row['path'])
            self.last_path=row['path'];self.choices.setCurrentIndex(index);self.selection_changed()
        finally:self.blockSignals(False)
