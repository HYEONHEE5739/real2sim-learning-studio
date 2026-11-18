"""Real Qt rendering of live camera panels, isolated from devices and workers."""
from test_ui_restoration import qt


def test_opening_ui_does_not_create_unused_pipeline_output_folders(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);workspace=root/'workspace';w=Window('/no/worker',root/'modules',workspace)
assert workspace.is_dir()
assert not any((workspace/name).exists()for name in ('annotation','datagen','dataset','policy','evaluation'))
w.close();app.processEvents()
''',tmp_path)


def test_both_live_pages_show_all_four_corners_without_cropping_or_stretching(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtGui import QColor,QPainter,QPixmap
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
from robot_learning_workbench.ui.jobs import BackendJob
BackendJob.start=lambda *a,**k:None
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace')
frame=QPixmap(640,480);frame.fill(QColor(31,189,123));painter=QPainter(frame)
corners=[(0,0,QColor('red')),(608,0,QColor('yellow')),
         (0,448,QColor('blue')),(608,448,QColor('magenta'))]
for x,y,color in corners:painter.fillRect(x,y,32,32,color)
painter.end();original=frame.toImage()
for page in w.sessions.values():page.stop_timers()
for width,height in[(1650,920),(1920,1080),(1280,720)]:
 for index,name in[(0,'capture'),(1,'real_sim')]:
  w.tabs.setCurrentIndex(index);w.resize(width,height);w.show();app.processEvents();page=w.sessions[name]
  for view in page.previews.values():view.setPixmap(frame)
  modes=[None]if name=='capture'else[2,0,1]
  for mode in modes:
   if mode is not None:page.view_mode.setCurrentIndex(mode)
   app.processEvents()
   for camera,view in page.previews.items():
    if not view.isVisible():continue
    image=view.grab().toImage();scale=min(view.width()/640,view.height()/480)
    left=(view.width()-640*scale)/2;top=(view.height()-480*scale)/2
    for x,y,color in corners:
     px=round(left+(x+16)*scale);py=round(top+(y+16)*scale)
     assert image.pixelColor(px,py)==color,('Cropped live corner',name,camera,width,height,mode,x,y,view.size())
    assert view.pixmap().toImage()==original, 'Display must preserve the complete 640x480 source'
w.close();app.processEvents()
assert not any(n in sys.modules for n in['torch','mujoco','isaaclab','lerobot','serial'])
''',tmp_path)


def test_scene_prepare_keeps_capture_history_accessible_without_shrinking_live_images(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');w.resize(1320,900);w.show();app.processEvents();p=w.sessions['capture']
assert all(v.height()>=300 for v in p.previews.values())
assert not p.snapshot_table.isVisible()
p.history_toggle.click();app.processEvents();assert p.snapshot_table.isVisible()
p.history_toggle.click();app.processEvents();assert all(v.height()>=300 for v in p.previews.values())
w.close();app.processEvents()
''',tmp_path)


def test_real_sim_can_compare_either_sensor_large_or_all_four_without_reconnecting(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');w.tabs.setCurrentIndex(1);w.resize(1320,900);w.show();app.processEvents()
p=w.sessions['real_sim'];calls=[];p.client.send=lambda *a,**k:calls.append((a,k));identities={k:id(v)for k,v in p.previews.items()}
for index,expected in [(0,{'side','sim_side'}),(1,{'wrist','sim_wrist'}),(2,set(p.previews))]:
 p.view_mode.setCurrentIndex(index);app.processEvents()
 assert {k for k,v in p.previews.items()if v.isVisible()}==expected
 assert {k:id(v)for k,v in p.previews.items()}==identities
 assert w.width()==1320 and w.height()==900
 if index!=2:assert all(p.previews[k].height()>=300 for k in expected)
assert not calls
w.close();app.processEvents()
''',tmp_path)


def test_live_image_expands_without_changing_recorded_frame_or_session(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtCore import QPoint,Qt,QTimer
from PyQt6.QtGui import QColor,QPixmap
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication,QDialog
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace');w.show();app.processEvents()
page=w.sessions['capture'];view=page.previews['side'];frame=QPixmap(640,480);frame.fill(QColor('green'));view.setPixmap(frame);calls=[]
page.client.send=lambda *a,**k:calls.append((a,k));observed=[]
def inspect():
 dialogs=[d for d in QApplication.topLevelWidgets()if isinstance(d,QDialog)and d.isVisible()]
 assert len(dialogs)==1, 'Double click must open an enlarged camera view'
 dialog=dialogs[0];assert dialog.width()>=800 and dialog.height()>=600
 observed.append(dialog.size())
 dialog.accept()
QTimer.singleShot(50,inspect)
QTest.mouseDClick(view,Qt.MouseButton.LeftButton,pos=QPoint(view.width()//2,view.height()//2))
app.processEvents();assert observed, 'Double click did not open an enlarged camera view'
assert not calls, 'Enlarging an image must not stop or reconnect Teleop'
assert view.pixmap().size()==frame.size()
w.close();app.processEvents()
''',tmp_path)


def test_capture_ui_shows_save_phase_and_distinguishes_stopped_teleop(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);root=Path(sys.argv[1]);w=Window('/no/worker',root/'modules',root/'workspace')
for name in ('capture','real_sim'):
 page=w.sessions[name];page.client.running=True;page.client.timer.stop();page.client.send=lambda *a,**k:None
 page.update_progress({'session_state':'CAPTURING','capture_pending':True,'capture_phase':'finish','capture_elapsed_s':1.25,'teleop_active':True})
 assert '등록' in page.capture_hint.text() and '1.2' in page.capture_hint.text(),page.capture_hint.text()
 page.update_progress({'teleop_active':False})
 assert 'Teleop 중지' in page.capture_hint.text(),page.capture_hint.text()
 page.update_progress({'session_state':'TELEOP_ACTIVE','capture_pending':False,'capture_phase':None,'teleop_active':True})
 assert '등록' not in page.capture_hint.text() and 'Teleop 중지' not in page.capture_hint.text()
 page.client.running=False
w.close();app.processEvents()
''',tmp_path)
