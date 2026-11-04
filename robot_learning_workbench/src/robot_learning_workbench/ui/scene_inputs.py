"""Optional Scene materials and one free-form note buffer."""
from PyQt6.QtCore import pyqtSignal,Qt
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QPushButton,QLabel,QListWidget,QPlainTextEdit,QFileDialog


DEFAULT_NOTES = """[장면과 작업 설명]

[실측 크기·위치]
물체 이름, 가로×세로×높이, 측정 단위를 적어주세요.

[항상 배치할 구성요소]

[선택형 작업 물체]
실행 Script에서 선택해서 사용할 물체를 적어주세요.

[물리·접촉 조건]
충돌, 미끄러짐, 질량, 그리퍼 접촉 요구 등을 적어주세요.

[카메라·기타 참고사항]
"""


class SceneInputs(QWidget):
    saveRequested=pyqtSignal(list,str)
    def __init__(self,workspace,parent=None):
        super().__init__(parent);self._loaded_notes='';self._displayed_notes='';self.workspace=str(workspace);self.pending=[];box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0)
        box.addWidget(QLabel('Input Data · 모두 선택 사항'));self.add=QPushButton('＋ Input Data 추가');box.addWidget(self.add);self.add.clicked.connect(self.choose)
        self.files=QListWidget();self.files.setTextElideMode(Qt.TextElideMode.ElideMiddle);self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.files.setMaximumHeight(170);box.addWidget(self.files)
        box.addWidget(QLabel('Scene 메모'));self.notes=QPlainTextEdit();self.notes.setPlaceholderText(DEFAULT_NOTES);self.notes.setMinimumHeight(140);self.notes.setStyleSheet('QPlainTextEdit { background: #f4f5f7; color: #18212d; border: 1px solid #abb9c8; border-radius: 6px; padding: 8px; }');box.addWidget(self.notes,1)
        self.save=QPushButton('Scene 자료 저장');self.save.clicked.connect(lambda:self.saveRequested.emit(self.pending,self.note_text()));box.addWidget(self.save)
        self.reconstruct=QPushButton('Auto Reconstruction');box.addWidget(self.reconstruct);self.reconstruct.setEnabled(False)
        self.reconstruct.clicked.connect(self.open_reconstruction);self.project_path=None;self.backend_python=None

    def note_text(self):
        text=self.notes.toPlainText()
        # Qt normalizes display line endings; an untouched prompt retains bytes.
        return self._loaded_notes if text==self._displayed_notes else text

    def open_reconstruction(self):
        if not self.project_path or not self.backend_python:return
        from real2sim_builder.ui_reconstruction import ReconstructionDialog
        dialog=ReconstructionDialog(self.project_path,self.backend_python,self);dialog.exec()
    def choose(self):
        files,_=QFileDialog.getOpenFileNames(self,'Scene Input Data 선택',self.workspace,'Builder inputs (*.urdf *.stl *.obj *.png *.jpg *.jpeg *.mp4 *.mov *.avi *.json *.yaml *.csv *.txt *.pdf);;All files (*)')
        for file in files:
            if file not in self.pending:self.pending.append(file);self.files.addItem('추가 예정 · '+file)
    def load(self,data):
        self.project_path=data.get('project');self.reconstruct.setEnabled(bool(self.project_path and self.backend_python))
        self.pending=[];self.files.clear();self._loaded_notes=data.get('notes','');self.notes.setPlainText(self._loaded_notes);self._displayed_notes=self.notes.toPlainText()
        for row in data.get('inputs',[]):self.files.addItem(row.get('status','등록')+' · '+row.get('path',''))
