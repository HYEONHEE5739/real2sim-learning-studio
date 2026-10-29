"""Original Qt presentation with saved Recipe/R03 semantics, without hardware IO."""
import os,subprocess
from pathlib import Path
from test_workbench_window import UI


def qt(script,tmp_path):
    result=subprocess.run([UI,'-B','-c',script,str(tmp_path)],env=dict(os.environ,QT_QPA_PLATFORM='offscreen'),capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr


def test_workflow_has_original_viewer_settings_and_advanced_recipe_boundary(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.workflow import WorkflowPage
from robot_learning_workbench.ui.view import CameraView
app=QApplication([]);page=WorkflowPage('datagen',sys.executable,'modules')
page.resize(1320,900);page.show();app.processEvents()
assert page.width()==1320 and page.height()==900
assert page.splitter.widget(0) is page.viewer and page.splitter.widget(1) is page.settings_scroll
assert 320<=page.settings_scroll.width()<=430
assert page.previews.keys()=={'side','wrist'} and all(isinstance(p,CameraView)for p in page.previews.values())
assert page.start_button.objectName()=='primaryAction' and page.cancel_button.objectName()=='stopAction'
assert not page.details.isChecked() and not page.editor.isVisible()
assert not page.input_rows['resume_dataset'].isVisible()
assert page.object_table.isVisible() and page.counts['num_episodes'].isVisible()
assert not page.gripper_button.isVisible() and page.loss_chart is None
page.timer.stop();page.close()
assert not any(n in sys.modules for n in ('torch','lerobot','isaaclab','mujoco','serial'))
''',tmp_path)


def test_theme_and_camera_widget_preserve_original_code(tmp_path):
    qt('''
import ast
from pathlib import Path
from robot_learning_workbench.ui import theme,view
old=Path('/home/hyeonhee/soarm_isaaclab/soarm101_lab/source/soarm101_lab/soarm101_lab/workflow')
namespace={};exec(compile((old/'theme.py').read_text(),'original-theme','exec'),namespace)
assert theme.STYLE==namespace['STYLE']
def camera(path):
    tree=ast.parse(path.read_text());return ast.dump(next(n for n in tree.body if isinstance(n,ast.ClassDef)and n.name=='CameraView'),include_attributes=False)
assert camera(old/'view.py')==camera(Path(view.__file__))
''',tmp_path)


def test_original_main_tabs_navigation_and_saved_stage_state_fit_both_sizes(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);window=Window('/no/worker',root/'modules.yaml',root/'workspace')
assert [window.tabs.tabText(i)for i in range(window.tabs.count())]==['1 · Real2Sim Capture','2 · Real / Sim','3 · Workspace Pipeline','4 · Precision Calibration']
assert window.navigation_panel.width()==200 and window.navigation.objectName()=='stageNavigation'
p=window.workflows['source'];recipe=root/'source.yaml'
recipe.write_text('schema_version: 1\\nstage: source\\nengine: mujoco\\ninputs: {}\\nexecution: {num_episodes: 1}\\noutput: {directory: source}\\n')
p.load_recipe(recipe);p.counts['num_episodes'].setValue(3)
for size in ((1320,900),(1920,1080)):
    window.resize(*size);window.show();app.processEvents()
    assert (window.width(),window.height())==size
    window.tabs.setCurrentIndex(2)
    window.navigation.setCurrentRow(4);app.processEvents()
    assert window.stack.currentWidget() is window.workflows['datagen']
    window.navigation.setCurrentRow(1);app.processEvents()
    assert p.editor.dirty and p.counts['num_episodes'].value()==3 and not p.start_button.isEnabled()
window.close();app.processEvents();assert not window.isVisible()
assert not any(n in sys.modules for n in ('torch','lerobot','isaaclab','mujoco','serial'))
''',tmp_path)
