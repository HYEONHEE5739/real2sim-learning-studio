"""Render the existing pages with one coherent palette; no engine or robot."""
from test_ui_restoration import qt


def test_studio_theme_reaches_every_page_editor_and_popup_without_white_overrides(tmp_path):
    qt(r'''
from pathlib import Path
import sys
from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication,QDialog,QVBoxLayout,QComboBox,QPlainTextEdit
from robot_learning_workbench.ui.app import Window
from robot_learning_workbench.ui.jobs import BackendJob
from robot_learning_workbench.ui.theme import COLORS
app=QApplication([]);root=Path(sys.argv[1]);BackendJob.start=lambda *a,**k:None
w=Window('/no/worker',root/'modules',root/'workspace');w.show()
for page in w.sessions.values():page.stop_timers()
assert COLORS['accent']=='#00d9c0'
editors=[w.sessions['capture'].notes,*[p.editor.text for p in w.workflows.values()]]
for editor in editors:
 editor.ensurePolished()
 assert editor.palette().color(QPalette.ColorRole.Base).lightness()<65
 assert editor.palette().color(QPalette.ColorRole.Text).lightness()>170
assert w.sessions['capture'].connect_button.icon().isNull()is False
assert w.sessions['real_sim'].capture_button.icon().isNull()is False
assert w.safety.wordWrap()and '연결'in w.safety.text()and 'Teleop'in w.safety.text()
# Child dialogs inherit the same chrome, including native combo popup lists.
d=QDialog(w);layout=QVBoxLayout(d);combo=QComboBox();combo.addItems(['one','two']);layout.addWidget(combo)
d.show();app.processEvents();combo.ensurePolished();combo.view().ensurePolished()
assert combo.palette().color(QPalette.ColorRole.Base).lightness()<65
assert combo.view().palette().color(QPalette.ColorRole.Text).lightness()>170
d.close();w.close();app.processEvents()
assert not any(m in sys.modules for m in['torch','lerobot','mujoco','isaaclab','serial'])
''',tmp_path)
