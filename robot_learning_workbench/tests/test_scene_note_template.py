import os,subprocess
from test_workbench_window import UI


def test_scene_notes_start_with_editable_template_and_preserve_saved_text(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.scene_inputs import SceneInputs
app=QApplication([]);panel=SceneInputs('.')
assert '[선택형 작업 물체]'in panel.notes.toPlainText()
panel.load(dict(notes='',notes_saved=False))
assert '[물리·접촉 조건]'in panel.notes.toPlainText()
panel.load(dict(notes='My measured scene',notes_saved=True))
assert panel.notes.toPlainText()=='My measured scene'
panel.load(dict(notes='',notes_saved=True))
assert not panel.notes.toPlainText()
'''
    result=subprocess.run([UI,'-B','-c',code],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
