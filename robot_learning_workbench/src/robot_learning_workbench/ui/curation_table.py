"""Editors for an Episode's bounded frame range and optional train/val split."""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox,QSpinBox,QStyledItemDelegate


class FrameRangeDelegate(QStyledItemDelegate):
    def createEditor(self,parent,option,index):
        low,high=index.siblingAtColumn(2).data(Qt.ItemDataRole.UserRole)
        editor=QSpinBox(parent)
        if index.column()==2:
            editor.setRange(low,int(index.siblingAtColumn(3).data())-1)
        else:
            editor.setRange(int(index.siblingAtColumn(2).data())+1,high)
        return editor

    def setEditorData(self,editor,index):
        editor.setValue(int(index.data()))

    def setModelData(self,editor,model,index):
        editor.interpretText();model.setData(index,editor.value(),Qt.ItemDataRole.EditRole)


class SplitDelegate(QStyledItemDelegate):
    def createEditor(self,parent,option,index):
        editor=QComboBox(parent);editor.addItems(['','train','val'])
        editor.activated.connect(lambda _:self.commit(editor))
        return editor

    def commit(self,editor):
        self.commitData.emit(editor);self.closeEditor.emit(editor)

    def setEditorData(self,editor,index):
        editor.setCurrentIndex(max(0,editor.findText(index.data())))

    def setModelData(self,editor,model,index):
        model.setData(index,editor.currentText(),Qt.ItemDataRole.EditRole)
