"""Optional Scene materials and one free-form note buffer."""
from PyQt6.QtCore import pyqtSignal,Qt
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QPushButton,QLabel,QListWidget,QPlainTextEdit,QFileDialog


class SceneInputs(QWidget):
    saveRequested=pyqtSignal(list,str)
    def __init__(self,workspace,parent=None):
        super().__init__(parent);self.workspace=str(workspace);self.pending=[];box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0)
        box.addWidget(QLabel('Input Data · 모두 선택 사항'));self.add=QPushButton('＋ Input Data 추가');box.addWidget(self.add);self.add.clicked.connect(self.choose)
        self.files=QListWidget();self.files.setTextElideMode(Qt.TextElideMode.ElideMiddle);self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.files.setMaximumHeight(170);box.addWidget(self.files)
        box.addWidget(QLabel('Scene 메모'));self.notes=QPlainTextEdit();self.notes.setPlaceholderText('물체 크기, 설치 위치, 작업 목표, 실측 정보 등을 자유롭게 기록하세요. 빈 상태로도 저장할 수 있습니다.');self.notes.setMinimumHeight(140);self.notes.setStyleSheet('QPlainTextEdit { background: #f4f5f7; color: #18212d; border: 1px solid #abb9c8; border-radius: 6px; padding: 8px; }');box.addWidget(self.notes,1)
        self.save=QPushButton('Scene 자료 저장');self.save.clicked.connect(lambda:self.saveRequested.emit(self.pending,self.notes.toPlainText()));box.addWidget(self.save)
        hint=QLabel('자료 저장과 Reconstruction 준비 상태는 별개입니다. 누락된 Model/Camera/실측 근거는 검증 단계에서 안내합니다.');hint.setWordWrap(True);box.addWidget(hint)
    def choose(self):
        files,_=QFileDialog.getOpenFileNames(self,'Scene Input Data 선택',self.workspace,'Builder inputs (*.urdf *.stl *.obj *.glb *.png *.jpg *.jpeg *.json *.yaml *.csv *.txt *.pdf);;All files (*)')
        for file in files:
            if file not in self.pending:self.pending.append(file);self.files.addItem('추가 예정 · '+file)
    def load(self,data):
        self.pending=[];self.files.clear();self.notes.setPlainText(data.get('notes',''))
        for row in data.get('inputs',[]):self.files.addItem(row.get('status','등록')+' · '+row.get('path',''))
