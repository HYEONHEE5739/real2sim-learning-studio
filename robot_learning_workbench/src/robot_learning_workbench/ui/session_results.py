"""Immutable Snapshot and Pair inspection, without SDK or image calculations."""
import json
from pathlib import Path
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QPlainTextEdit
from .view import CameraView


class ResultsDialog(QDialog):
    def __init__(self,row,parent=None):
        super().__init__(parent);self.setWindowTitle('Capture 상세 · 원본 보존');self.resize(1120,800);layout=QVBoxLayout(self);root=Path(row['path'])
        self.files=sorted(p for p in root.rglob('*.png')if p.is_file());self.selection=QComboBox();layout.addWidget(self.selection)
        self.view=CameraView();layout.addWidget(self.view,3)
        for path in self.files:self.selection.addItem(str(path.relative_to(root)),str(path))
        self.selection.currentIndexChanged.connect(lambda _:self.view.show_image(self.selection.currentData())if self.selection.currentData()else None)
        if self.files:self.view.show_image(self.files[0])
        details=dict(row)
        pairs=list(root.glob('shots/*/pair.json'))
        if pairs:details['comparison']=json.loads(pairs[0].read_text())
        text=QPlainTextEdit(json.dumps(details,ensure_ascii=False,indent=2));text.setReadOnly(True);layout.addWidget(text,1)
