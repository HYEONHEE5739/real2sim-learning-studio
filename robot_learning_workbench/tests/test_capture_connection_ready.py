"""A saved Project must be selectable before a user can connect its devices."""
from test_ui_restoration import qt


def test_capture_lists_saved_projects_and_selection_restores_connect_readiness(tmp_path):
    qt('''
from pathlib import Path
import sys,yaml
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QApplication
from real2sim_builder.project import Project
from robot_learning_workbench.robot.registration import bind_configuration
from robot_learning_workbench.ui.session_page import CapturePage
root=Path(sys.argv[1]);workspace=root/'workspace'
project=Project.create(workspace/'scenes','My first scene')
device=workspace/'devices'/'saved';device.mkdir(parents=True)
camera=device/'cameras.json';camera.write_text('{"cameras":{"side":{"index_or_path":"/missing/side"},"wrist":{"index_or_path":"/missing/wrist"}}}')
configuration=device/'capture.yaml';configuration.write_text(yaml.safe_dump({'schema_version':1,'stage':'scene_capture',
    'inputs':{'camera_config':'cameras.json'},'execution':{'device_source':'hardware'},'output':{'directory':'unused'}}))
bind_configuration(project.root,configuration,workspace)
app=QApplication([]);page=CapturePage('/home/hyeonhee/miniconda3/envs/lerobot-arena/bin/python','unused',workspace)
page.show();app.processEvents()
for job in page.findChildren(__import__('robot_learning_workbench.ui.jobs',fromlist=['BackendJob']).BackendJob):
    if job.process.state()!=QProcess.ProcessState.NotRunning:assert job.process.waitForFinished(10000)
app.processEvents()
index=page.project_combo.findData(str(project.root))
assert index>0,'Saved Project absent; connection stays grey with no selectable destination'
assert page.project is None and not page.connect_button.isEnabled()
assert 'Project'in page.connection_hint.text()and page.connection_hint.isVisible()
page.project_combo.setCurrentIndex(index)
assert page.job.process.waitForFinished(10000)
app.processEvents()
assert page.project['project']==str(project.root)
assert page.settings.saved_recipe==configuration.resolve()
assert page.connect_button.isEnabled() and not page.connection_hint.isVisible()
assert not page.client.active() and not list((workspace/'capture').glob('*.yaml'))
page.project_combo.setCurrentIndex(0);app.processEvents()
assert page.project is None and page.settings.saved_recipe is None and not page.connect_button.isEnabled()
assert not any(name in sys.modules for name in('serial','lerobot','torch','mujoco'))
page.stop_timers();page.close()
''',tmp_path)


def test_capture_explains_missing_configuration_after_project_selection(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.session_page import CapturePage
app=QApplication([]);root=Path(sys.argv[1]);page=CapturePage('/no/worker','unused',root)
page.project_result({'ok':True,'result':{'project':str(root/'empty'),'name':'Empty','configuration_path':None}})
page.show();app.processEvents();page.buttons(False)
assert not page.connect_button.isEnabled()
assert '장치 설정'in page.connection_hint.text()and page.connection_hint.isVisible()
assert '장치 설정'in page.connect_button.toolTip()
page.stop_timers();page.close()
''',tmp_path)
