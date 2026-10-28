import os,subprocess
from pathlib import Path
UI=Path('/home/hyeonhee/soarm_isaaclab/soarm101_lab/.venv-real2sim-ui/bin/python3.11')


def test_real_qt_recipe_edit_save_reload_and_inert_import(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.recipe_editor import RecipeEditor
from pathlib import Path
import sys
app=QApplication([]);path=Path(sys.argv[1])/'r.yaml';path.write_text('stage: datagen\\n')
w=RecipeEditor();w.load(path);assert not w.dirty and w.state=='저장됨'
w.text.insertPlainText('# change\\n');assert w.dirty
w.save();assert not w.dirty;w.load(path);assert '# change' in w.text.toPlainText()
assert not any(x in sys.modules for x in ['torch','mujoco','isaaclab','lerobot'])
w.close()
'''
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen');p=subprocess.run([str(UI),'-B','-c',code,str(tmp_path)],env=env,capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr


def test_recipe_save_never_writes_installed_sdk(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.recipe_editor import RecipeEditor
from pathlib import Path
from unittest.mock import patch
app=QApplication([]);w=RecipeEditor();w.text.setPlainText('stage: train')
with patch.object(Path,'write_text') as write:
 try:w.save('/home/hyeonhee/miniconda3/forbidden-ui.yaml')
 except ValueError:pass
 else:raise AssertionError('SDK path accepted')
 assert not write.called
'''
    p=subprocess.run([str(UI),'-B','-c',code],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert p.returncode==0,p.stdout+p.stderr
