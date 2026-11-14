"""Optional Scene materials and one free-form note buffer."""
from pathlib import Path
from PyQt6.QtCore import pyqtSignal,Qt
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QPushButton,QLabel,QListWidget,QPlainTextEdit,QFileDialog


DEFAULT_NOTES = """Codex에게 Scene 제작을 요청하듯 자유롭게 적어주세요.
장면과 작업 목적, 물체 특징, 알고 있는 실측 크기와 단위,
같은 제품인 물체, 위치 관계, 원하는 형상·색·재질 등을 함께 설명하면 됩니다.
예: 두 컵은 같은 제품이고 높이는 100mm야. 빨간 블록을 왼쪽 컵에 넣고 싶어.
정해진 형식이나 별도 필수 치수 입력은 없습니다."""


class SceneInputs(QWidget):
    saveRequested=pyqtSignal(list,str)
    def __init__(self,workspace,parent=None):
        super().__init__(parent);self._loaded_notes='';self._displayed_notes='';self.workspace=str(workspace);self.pending=[];box=QVBoxLayout(self);box.setContentsMargins(0,0,0,0)
        box.addWidget(QLabel('Input Data · 모두 선택 사항'))
        self.scene_add=QPushButton('＋ Scene 이미지 추가');box.addWidget(self.scene_add);self.scene_add.clicked.connect(lambda:self.choose('scene_photo'))
        self.model_add=QPushButton('＋ Model 이미지 추가');box.addWidget(self.model_add);self.model_add.clicked.connect(lambda:self.choose('model_reference'))
        self.add=QPushButton('기타 자료 추가');box.addWidget(self.add);self.add.clicked.connect(lambda:self.choose('attachment'))
        self.files=QListWidget();self.files.setTextElideMode(Qt.TextElideMode.ElideMiddle);self.files.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff);self.files.setMaximumHeight(170);box.addWidget(self.files)
        box.addWidget(QLabel('Scene 메모'));self.notes=QPlainTextEdit();self.notes.setPlaceholderText(DEFAULT_NOTES);self.notes.setMinimumHeight(140);self.notes.setStyleSheet('QPlainTextEdit { background: #f4f5f7; color: #18212d; border: 1px solid #abb9c8; border-radius: 6px; padding: 8px; }');box.addWidget(self.notes,1)
        self.save=QPushButton('Scene 자료 저장');self.save.clicked.connect(lambda:self.saveRequested.emit(self.pending,self.note_text()));box.addWidget(self.save)
        self.reconstruct=QPushButton('Auto Reconstruction');box.addWidget(self.reconstruct);self.reconstruct.setEnabled(False)
        self.reconstruct.clicked.connect(self.open_reconstruction);self.project_path=None;self.backend_python=None
        self.library=QPushButton('Object Library · 3D 보기');box.addWidget(self.library);self.library.setEnabled(False);self.library.clicked.connect(self.open_library)

    def open_library(self):
        if self.project_path and self.backend_python:
            from .object_library import ObjectLibraryDialog
            ObjectLibraryDialog(self.project_path,self.backend_python,self).exec()

    def note_text(self):
        text=self.notes.toPlainText()
        # Qt normalizes display line endings; an untouched prompt retains bytes.
        return self._loaded_notes if text==self._displayed_notes else text

    def open_reconstruction(self):
        if not self.project_path or not self.backend_python:return
        from real2sim_builder.ui_reconstruction import ReconstructionDialog
        dialog=ReconstructionDialog(self.project_path,self.backend_python,self);dialog.exec()
    def choose(self,role='scene_photo'):
        image_filter='Images (*.png *.jpg *.jpeg *.webp *.tif *.tiff)'if role!='attachment'else'Builder inputs (*.urdf *.stl *.obj *.usd *.usda *.usdc *.mp4 *.mov *.avi *.json *.yaml *.csv *.txt *.pdf);;All files (*)'
        files,_=QFileDialog.getOpenFileNames(self,'Scene 자료 선택',self.workspace,image_filter)
        for file in files:
            row={'path':file,'role':role}
            if row not in self.pending:self.pending.append(row);self.files.addItem('추가 예정 · '+role+' · '+Path(file).name)
    def load(self,data):
        self.project_path=data.get('project');self.reconstruct.setEnabled(bool(self.project_path and self.backend_python))
        self.library.setEnabled(bool(self.project_path and self.backend_python))
        self.pending=[];self.files.clear();self._loaded_notes=data.get('notes','');self.notes.setPlainText(self._loaded_notes);self._displayed_notes=self.notes.toPlainText()
        for role,title in [('scene_photo','Scene Photos'),('model_reference','Model References'),(None,'기타 자료')]:
            rows=[r for r in data.get('inputs',[])if (r.get('role')if r.get('role')in('scene_photo','model_reference')else None)==role]
            if rows:self.files.addItem(title)
            for row in rows:self.files.addItem(row.get('status','등록')+' · '+(row.get('name')or Path(row['path']).name))
