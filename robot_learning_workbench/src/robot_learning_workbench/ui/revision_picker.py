"""Revision choices for one original Dataset; Backend owns filesystem discovery."""
from PyQt6.QtCore import pyqtSignal,Qt
from PyQt6.QtWidgets import QWidget,QHBoxLayout,QLabel,QComboBox


class RevisionPicker(QWidget):
    selected=pyqtSignal(str)

    def __init__(self,parent=None):
        super().__init__(parent);layout=QHBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        layout.addWidget(QLabel('Revision'));self.choices=QComboBox();layout.addWidget(self.choices,1)
        self.choices.currentIndexChanged.connect(self.choose);self.reset()

    def reset(self):
        self.choices.blockSignals(True);self.choices.clear();self.choices.addItem('원본 Dataset을 선택하세요',None);self.choices.blockSignals(False);self.setEnabled(False)

    def set_source(self,original,revision,rows):
        self.choices.blockSignals(True)
        try:
            self.choices.clear();self.choices.addItem('원본 전체',original)
            for row in rows:
                title=row['title']+f" · {row['episodes']} Episode"
                if not row['readable']:title+=' · 읽기 오류'
                self.choices.addItem(title,row['path']);i=self.choices.count()-1
                self.choices.setItemData(i,row['error']or row['path'],Qt.ItemDataRole.ToolTipRole)
                self.choices.model().item(i).setEnabled(row['readable'])
            path=revision['path']if revision else original;index=self.choices.findData(path)
            if index<0:self.choices.addItem(revision['name'],path);index=self.choices.count()-1
            self.choices.setCurrentIndex(index)
        finally:self.choices.blockSignals(False)
        self.setEnabled(True)

    def choose(self,*_):
        path=self.choices.currentData()
        if path:self.selected.emit(path)
