"""Saved Recipe editor state. A buffer is never a runnable configuration."""
from pathlib import Path
import yaml
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QWidget,QVBoxLayout,QPlainTextEdit,QLabel


class RecipeEditor(QWidget):
    changed=pyqtSignal()
    def __init__(self,parent=None):
        super().__init__(parent);self.path=None;self.dirty=False;self.state='편집 중'
        layout=QVBoxLayout(self);self.label=QLabel('저장 Recipe를 선택하세요');self.text=QPlainTextEdit();layout.addWidget(self.label);layout.addWidget(self.text)
        self.text.textChanged.connect(self.edited)
    def edited(self):
        self.dirty=True;self.state='편집 중';self.label.setText('편집 중 — 저장한 뒤 검사하세요');self.changed.emit()
    def load(self,path):
        self.path=Path(path).resolve();self.text.setPlainText(self.path.read_text());self.dirty=False;self.state='저장됨';self.label.setText('저장됨 · '+self.path.name)
    def data(self):
        result=yaml.safe_load(self.text.toPlainText())
        if not isinstance(result,dict):raise ValueError('Recipe는 YAML mapping이어야 합니다')
        return result
    def update(self,fn):
        data=self.data();fn(data);self.text.setPlainText(yaml.safe_dump(data,sort_keys=False,allow_unicode=True))
    def save(self,path=None):
        target=Path(path).resolve() if path else self.path
        if target is None:raise ValueError('저장 위치를 선택하세요')
        # Never overwrite historical evidence or original project Recipes.
        protected=('/home/hyeonhee/soarm_isaaclab/','/home/hyeonhee/miniconda3/','/home/hyeonhee/IsaacLab/')
        if str(target).startswith(protected) or ('docs' in target.parts and 'evidence' in target.parts and target.exists()):
            raise ValueError('보존 자료입니다. 다른 이름으로 저장하세요')
        target.parent.mkdir(parents=True,exist_ok=True);target.write_text(self.text.toPlainText())
        self.path=target;self.dirty=False;self.state='저장됨';self.label.setText('저장됨 · '+target.name);self.changed.emit()
