"""Use the already-installed isolated Qt interpreter; never borrow its NumPy."""
import os,subprocess
from pathlib import Path

UI_PYTHON=Path('/home/hyeonhee/soarm_isaaclab/soarm101_lab/.venv-real2sim-ui/bin/python3.11')


def test_offscreen_project_reload_inventory_and_no_engine_imports(tmp_path):
    assert UI_PYTHON.is_file(),'Existing UI interpreter required; absence is not a passing skip'
    code='''
from PyQt6.QtWidgets import QApplication,QPushButton
from PyQt6.QtCore import QProcess
from real2sim_builder.project import Project
from real2sim_builder.ui import Window
from pathlib import Path
import sys,json
app=QApplication([]);project=Project.create(Path(sys.argv[1]),'Builder UI review')
window=Window(sys.argv[1]);window.timer.stop();window.list.setCurrentRow(0);app.processEvents()
assert window.project.root==project.root and window.tabs.count()==4
assert 'DRAFT' in window.status.text() and 'software-egl'==window.renderer.currentText()
buttons={b.text() for b in window.findChildren(QPushButton)}
assert {'Reload project','Export new revision','Create candidate','Reject candidate','Promote candidate'}<=buttons
window.worker_state(QProcess.ProcessState.Starting);assert not window.list.isEnabled()
window.worker_state(QProcess.ProcessState.NotRunning);assert window.list.isEnabled()
window.reload_project();assert window.project.root==project.root
assert not any(n.split('.')[0] in ('mujoco','pxr','isaaclab','omni','torch') for n in sys.modules)
window.close();print(json.dumps({'tabs':4,'buttons':sorted(buttons),'no_engine_import':True}))
'''
    env=os.environ.copy();env['QT_QPA_PLATFORM']='offscreen';env.pop('PYTHONHOME',None)
    result=subprocess.run([str(UI_PYTHON),'-B','-c',code,str(tmp_path)],capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stdout+result.stderr


def test_actual_input_worker_uses_own_python_and_preserves_foreign_gui_environment(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication,QFileDialog
from real2sim_builder.project import Project
from real2sim_builder.ui import Window
from PIL import Image
from pathlib import Path
import os,sys,json
root=Path(sys.argv[1]);project=Project.create(root/'projects','Actual input import');image=root/'input.png';Image.new('RGB',(64,48)).save(image)
foreign=root/'foreign';foreign.mkdir();(foreign/'numpy.py').write_text('raise RuntimeError("GUI NumPy leaked")')
os.environ['PYTHONPATH']=str(foreign);os.environ['PYTHONHOME']=str(root/'invalid-python-home')
app=QApplication([]);window=Window(project.root.parent);window.timer.stop();window.list.setCurrentRow(0)
window.python.setText('/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python')
QFileDialog.getOpenFileNames=lambda *a:([str(image)],'')
window.add('image');assert window.process.waitForFinished(10000),window.log.toPlainText()
assert window.process.exitCode()==0,window.log.toPlainText()
assert len(project.evidence['images'])==1
assert os.environ['PYTHONHOME'].endswith('invalid-python-home')
window.close();print('actual worker import success; no device connection')
'''
    env=os.environ.copy();env['QT_QPA_PLATFORM']='offscreen';env.pop('PYTHONHOME',None)
    result=subprocess.run([str(UI_PYTHON),'-B','-c',code,str(tmp_path)],capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stdout+result.stderr


def test_ui_does_not_hide_corrupt_reload_or_overwrite_existing_export(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from real2sim_builder.project import Project
from real2sim_builder.ui import Window
from pathlib import Path
import sys
root=Path(sys.argv[1]);project=Project.create(root,'Error visibility');app=QApplication([]);window=Window(root);window.timer.stop();window.list.setCurrentRow(0)
(project.root/'working/state.json').write_text('{broken')
window.poll();assert 'READ_ERROR' in window.status.text() and 'state' in window.log.toPlainText()
try:window.export_selected(root)
except ValueError:pass
else:raise AssertionError('existing export destination accepted')
window.close()
'''
    env=os.environ.copy();env['QT_QPA_PLATFORM']='offscreen';env.pop('PYTHONHOME',None)
    result=subprocess.run([str(UI_PYTHON),'-B','-c',code,str(tmp_path)],capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stdout+result.stderr


def test_changing_project_clears_previous_render_instead_of_displaying_stale_evidence(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QImage
from real2sim_builder.project import Project
from real2sim_builder.ui import Window
from pathlib import Path
import sys
root=Path(sys.argv[1]);old=Project.create(root,'A old preview');new=Project.create(root,'B no render')
folder=old.root/'working/validation/previews/000_side';folder.mkdir(parents=True)
image=QImage(64,48,QImage.Format.Format_RGB32);image.fill(0x102030)
for name in ('side_by_side','overlay','difference'):assert image.save(str(folder/(name+'.png')))
app=QApplication([]);window=Window(root);window.timer.stop();window.list.setCurrentRow(window.paths.index(old.root));app.processEvents();window.poll()
assert all(label.pixmap() is not None and not label.pixmap().isNull() for label in window.pictures.values())
window.list.setCurrentRow(window.paths.index(new.root));app.processEvents();window.poll()
assert all(label.pixmap() is None or label.pixmap().isNull() for label in window.pictures.values())
window.close()
'''
    env=os.environ.copy();env['QT_QPA_PLATFORM']='offscreen';env.pop('PYTHONHOME',None)
    result=subprocess.run([str(UI_PYTHON),'-B','-c',code,str(tmp_path)],capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stdout+result.stderr


def test_corrupt_project_is_visible_as_read_error_without_crashing_project_list(tmp_path):
    code='''
from PyQt6.QtWidgets import QApplication
from real2sim_builder.project import Project
from real2sim_builder.ui import Window
from pathlib import Path
import sys
root=Path(sys.argv[1]);project=Project.create(root,'Broken metadata');(project.root/'working/state.json').write_text('{broken')
app=QApplication([]);window=Window(root);window.timer.stop()
assert window.list.count()==1 and 'READ_ERROR' in window.list.item(0).text()
window.list.setCurrentRow(0);app.processEvents();assert 'READ_ERROR' in window.status.text()
window.close()
'''
    env=os.environ.copy();env['QT_QPA_PLATFORM']='offscreen';env.pop('PYTHONHOME',None)
    result=subprocess.run([str(UI_PYTHON),'-B','-c',code,str(tmp_path)],capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stdout+result.stderr
