"""Immutable Snapshot and Pair inspection, without SDK or image calculations."""
import json
import yaml
from pathlib import Path
from PyQt6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QComboBox,QPlainTextEdit,QPushButton,QMessageBox
from PyQt6.QtCore import QTemporaryDir
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
        from real2sim_builder.capture import snapshot_metadata
        from real2sim_builder.scene import local_path
        sealed=snapshot_metadata(root)['files'] if (root/'metadata.json').is_file() else None
        self.files=(sorted(local_path(root,p) for p in sealed if p.endswith('.png')) if sealed is not None
                    else sorted(p for p in root.rglob('*.png') if p.is_file()))
        self.selection=QComboBox();layout.addWidget(self.selection)
        self.view=CameraView();layout.addWidget(self.view,3)
        for path in self.files:self.selection.addItem(str(path.relative_to(root)),str(path))
        self.selection.currentIndexChanged.connect(lambda _:self.view.show_image(self.selection.currentData())if self.selection.currentData()else None)
        if self.files:self.view.show_image(self.files[0])
        details=dict(row)
        if sealed is not None and 'pair.json' in sealed:details['comparison']=json.loads((root/'pair.json').read_text())
        if details.get('comparison',{}).get('comparison_images',{}).get('status')=='DEFERRED':
            button=QPushButton('비교 이미지 생성 · 원본 보존');layout.addWidget(button)
            self.comparison_temporary=QTemporaryDir()
            self.finished.connect(lambda _:self.comparison_temporary.remove())
            def comparisons():
                try:
                    from ..robot.pairs import render_comparisons
                    folder=Path(self.comparison_temporary.path())
                    for path in render_comparisons(root,folder):
                        self.selection.addItem('comparison/'+str(Path(path).relative_to(folder)),path)
                    button.setEnabled(False)
                except Exception as error:QMessageBox.warning(self,'비교 이미지',str(error))
            button.clicked.connect(comparisons)
        text=QPlainTextEdit(json.dumps(details,ensure_ascii=False,indent=2));text.setReadOnly(True);layout.addWidget(text,1)
