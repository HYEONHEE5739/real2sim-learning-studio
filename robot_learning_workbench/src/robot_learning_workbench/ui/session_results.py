"""Immutable Snapshot and Pair inspection, without SDK or image calculations."""
import json
import yaml
from pathlib import Path
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QPlainTextEdit
from .view import CameraView


class ResultsDialog(QDialog):
    def __init__(self,row,parent=None):
        super().__init__(parent);self.setWindowTitle('Capture 상세 · 원본 보존');self.resize(1120,800);layout=QVBoxLayout(self);root=Path(row['path']).resolve()
        if (root/'capture_manifest.yaml').is_file():
            manifest=yaml.safe_load((root/'capture_manifest.yaml').read_text())
            selected=[shot for shot in manifest['snapshots']if shot['id']==row['id']]
            if len(selected)!=1:raise ValueError('Choose one recorded Snapshot identity')
            shot=(root/selected[0]['path']).resolve()
            if not shot.is_relative_to(root)or not shot.is_dir():raise ValueError('Selected Snapshot path is missing or outside its Dataset')
            root=shot
        self.files=sorted(p for p in root.rglob('*.png')if p.is_file());self.selection=QComboBox();layout.addWidget(self.selection)
        self.view=CameraView();layout.addWidget(self.view,3)
        for path in self.files:self.selection.addItem(str(path.relative_to(root)),str(path))
        self.selection.currentIndexChanged.connect(lambda _:self.view.show_image(self.selection.currentData())if self.selection.currentData()else None)
        if self.files:self.view.show_image(self.files[0])
        details=dict(row)
        if (root/'pair.json').is_file():details['comparison']=json.loads((root/'pair.json').read_text())
        text=QPlainTextEdit(json.dumps(details,ensure_ascii=False,indent=2));text.setReadOnly(True);layout.addWidget(text,1)
