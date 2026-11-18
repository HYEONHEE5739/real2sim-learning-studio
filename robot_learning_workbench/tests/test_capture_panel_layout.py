"""Real Qt geometry/scrolling checks; no camera, renderer or motor connection."""
from test_ui_restoration import qt


PROBE=r'''
from pathlib import Path
import json,os,sys
from PyQt6.QtCore import QPoint
from PyQt6.QtGui import QColor,QPixmap
from PyQt6.QtWidgets import QApplication,QScrollArea
from robot_learning_workbench.ui.app import Window
from robot_learning_workbench.ui.jobs import BackendJob

app=QApplication([]);root=Path(sys.argv[1]);root.mkdir(exist_ok=True,parents=True)
BackendJob.start=lambda *a,**k:None
w=Window('/no/worker',root/'modules',root/'workspace');failures=[];records=[]
source=Path.cwd()/'workbench_runs/scenes/pickplace-colorblock/input/captures/real_sim_20261117_03/capture_001'
replay=os.environ.get('R2S_LAYOUT_SCREENSHOTS')=='1'
frame=QPixmap(640,480);frame.fill(QColor(30,160,130))
def settle():
 for _ in range(5):app.processEvents()
def check(ok,reason):
 if not ok:failures.append(reason)
def fully_visible(widget):
 region=widget.visibleRegion().boundingRect()
 return widget.isVisible() and region.width()>=widget.width()-1 and region.height()>=widget.height()-1
for page in w.sessions.values():page.stop_timers()
for size in [(1650,920),(1920,1080),(1280,720)]:
 for index,name in [(0,'capture'),(1,'real_sim')]:
  w.tabs.setCurrentIndex(index);w.resize(*size);w.show();settle();p=w.sessions[name]
  if name=='real_sim':
   check(p.view_mode.currentIndex()==2,(name,size,'default must be four views'))
   p.view_mode.setCurrentIndex(2);settle()
  for camera,view in p.previews.items():
   image=QPixmap(str(source/(camera+'.png')))if replay else frame
   view.setPixmap(image)
   p.camera_labels[camera].setText(camera.upper()+' · 저장 영상 재생'if replay else camera.upper()+' · 합성 UI 시험')
  controls=([p.connect_button,p.capture_button,p.finish_button]if name=='capture'else[p.connect_button,p.capture_button,p.stop_button])
  p.client.timer.stop();p.client.stage='capture_session'if name=='capture'else'paired_session';p.client.running=True;p.client.send=lambda *a,**k:None
  p.update_progress({'session_state':'OBSERVING','teleop_active':False,'teleoperation_available':True,'capture_request_allowed':True,'device_source':'memory'})
  p.state.setText('저장 영상 재생 · 합성 기록 행 / 실물 연결 없음'if replay else'Qt geometry test')
  for count in [0,20,100]:
   p.snapshot_table.reset()
   for row in range(count):p.snapshot_table.append({'id':'ui_'+str(row),'path':str(root/('synthetic_'+str(row))),'unix_ns':1_700_000_000_000_000_000+row*1_000_000_000,'q_measured':[0.]*6,'images':{},'paired':name=='real_sim'})
   assert not p.history_toggle.isCheckable(),'History must open a popup instead of expanding the main page'
   dialog=p.session_layout.history_dialog;dialog.close();settle()
   check(not p.snapshot_table.isVisible(),(name,size,count,'history popup must start closed'))
   collapsed=[v.height()for v in p.previews.values()]
   check(p.history_toggle.mapTo(p,QPoint()).x()>p.width()/2,(name,size,'history button must be on the right'))
   for opened in [True,False,True,False,True]:
    if opened:p.history_toggle.click()
    else:dialog.close()
    settle()
    check(dialog.isVisible()==opened and not dialog.isModal(),(name,size,count,'popup state'))
    check([v.height()for v in p.previews.values()]==collapsed,(name,size,count,'popup changed camera allocation'))
    check((w.width(),w.height())==size,(name,size,count,'window forced larger',w.width(),w.height()))
    check(all(fully_visible(b)for b in controls),(name,size,count,opened,'action clipped'))
    check(all(fully_visible(v)for v in p.previews.values()),(name,size,count,opened,'camera clipped'))
    check(all(v.height()>=90 for v in p.previews.values()),(name,size,count,opened,'camera too short'))
    if size[1]>=920:
     check(fully_visible(p.project_combo if name=='capture'else p.scene_combo),(name,size,count,opened,'selector unnecessarily scrolled out'))
   if hasattr(p,'session_layout'):
    layout=p.session_layout
    check(isinstance(layout.page_scroll,QScrollArea),(name,'page fallback missing'))
    check(p.camera_area.height()<=layout.page_scroll.viewport().height()+2,(name,size,count,'camera exceeds live viewport'))
    check(p.snapshot_table.height()<=dialog.height(),(name,size,count,'table expands with rows'))
   else:check(False,(name,'bounded shared layout missing'))
   if count>=20:check(p.snapshot_table.verticalScrollBar().maximum()>0,(name,size,count,'table internal scroll missing'))
   if replay:
    path=root/(os.environ.get('R2S_LAYOUT_PHASE','after')+'-'+name+'-'+str(size[0])+'x'+str(size[1])+'-n'+str(count)+'.png');w.grab().save(str(path))
    dialog.grab().save(str(path.with_stem(path.stem+'-popup')))
   records.append({'page':name,'requested_window':list(size),'actual_window':[w.width(),w.height()],'rows':count,'camera_heights':[v.height()for v in p.previews.values()],
     'collapsed_camera_heights':collapsed,'camera_visible':[fully_visible(v)for v in p.previews.values()],'buttons_visible':[fully_visible(b)for b in controls],
     'table_height':p.snapshot_table.height(),'table_scroll_max':p.snapshot_table.verticalScrollBar().maximum(),
     'popup_size':[dialog.width(),dialog.height()]})
  p.client.running=False;dialog.close()
w.close();settle()
(root/(os.environ.get('R2S_LAYOUT_PHASE','after')+'-geometry.json')).write_text(json.dumps({'records':records,'failures':failures},ensure_ascii=False,indent=2))
assert not any(m in sys.modules for m in ['torch','lerobot','mujoco','isaaclab','serial'])
if os.environ.get('R2S_LAYOUT_RECORD_ONLY')!='1':assert not failures,failures[:12]
print(json.dumps({'cases':len(records),'failures':len(failures)}))
'''


def test_capture_history_respects_window_and_camera_geometry_for_all_sizes_and_row_counts(tmp_path):
    qt(PROBE,tmp_path)


def test_history_zoom_keeps_same_table_selection_and_controls_and_scroll_fallback(tmp_path):
    qt(r'''
from pathlib import Path
import sys
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication,QScrollArea
from robot_learning_workbench.ui.app import Window
from robot_learning_workbench.ui.jobs import BackendJob
app=QApplication([]);root=Path(sys.argv[1]);BackendJob.start=lambda *a,**k:None
w=Window('/no/worker',root/'modules',root/'workspace');w.resize(1280,720);w.show();app.processEvents()
for index,name in [(0,'capture'),(1,'real_sim')]:
 w.tabs.setCurrentIndex(index);app.processEvents();p=w.sessions[name];p.client.timer.stop();layout=p.session_layout
 sent=[];p.client.stage='capture_session'if name=='capture'else'paired_session';p.client.send=lambda kind,payload=None,**kw:sent.append(kind);p.client.running=True
 p.update_progress({'session_state':'OBSERVING','teleop_active':False,'teleoperation_available':True,'capture_request_allowed':True})
 for i in range(20):p.snapshot_table.append({'id':str(i),'path':str(root/str(i)),'q_measured':[0.]*6})
 p.history_toggle.click();app.processEvents();p.snapshot_table.selectRow(5)
 table=p.snapshot_table;before=[r.copy()for r in table.rows]
 popup=layout.history_dialog;p.history_toggle.click();app.processEvents()
 assert popup is not None,'History button must open a popup directly'
 assert layout.history_dialog is popup
 assert layout.history_dialog.isVisible() and not layout.history_dialog.isModal()
 assert p.snapshot_table is table and table.isVisible() and table.currentRow()==5
 assert all(b.isVisible()for b in [p.connect_button,p.capture_button])
 raw=b'P6\n4 3\n255\n'+bytes([30,80,190])*12
 QTimer.singleShot(0,lambda:p.show_preview('side',raw));app.processEvents()
 assert p.previews['side'].pixmap().width()==4 and p.previews['side'].pixmap().height()==3
 assert not sent,'Opening history changed live control state'
 p.capture_button.click();assert sent==['session_snapshot'];sent.clear()
 p.connect_button.click()
 assert sent==['teleop_start'];sent.clear()
 p.snapshot_table.append({'id':'live','path':str(root/'live'),'q_measured':[0.]*6})
 layout.history_dialog.close();app.processEvents()
 assert not popup.isVisible() and not table.isVisible()
 p.history_toggle.click();app.processEvents()
 assert layout.history_dialog is popup and table.isVisible()
 assert table.rows[:20]==before and table.currentRow()==5 and table.rowCount()==21
 # Existing selected-snapshot details keep their original signal target.
 import robot_learning_workbench.ui.snapshot_table as module
 seen=[]
 class Details:
  def __init__(self,row,parent):seen.append(row['id'])
  def exec(self):pass
 original=module.ResultsDialog;module.ResultsDialog=Details
 try:table.cellDoubleClicked.emit(5,0)
 finally:module.ResultsDialog=original
 assert seen==['5']
 p.show_error('Long guidance\n'*50);app.processEvents()
 bar=layout.page_scroll.verticalScrollBar();assert bar.maximum()>0
 bar.setValue(bar.maximum());app.processEvents()
 assert p.operation_message.visibleRegion().boundingRect().bottom()>=p.operation_message.height()-2
 assert p.capture_button.visibleRegion().boundingRect().height()==p.capture_button.height()
 if name=='real_sim':
  p.run_folder.setText('Saved capture folder / long guidance '*30);p.run_folder.show();app.processEvents()
  inner=layout.history_dialog.findChild(QScrollArea).verticalScrollBar();inner.setValue(inner.maximum());app.processEvents()
  assert p.refit_button.visibleRegion().boundingRect().height()==p.refit_button.height()
  p.client.cancel=lambda:sent.append('cancel');p.stop_button.click();assert sent==['cancel']
 else:
  p.client.finish=lambda:sent.append('session_finish');p.finish_button.click();assert sent==['session_finish']
  p.finishing=False
 p.client.running=False
 p.operation_message.hide();bar.setValue(0);popup.close()
w.close();app.processEvents()
''',tmp_path)


def test_scene_prepare_diagnostic_log_opens_on_the_right_and_keeps_live_messages(tmp_path):
    qt(r'''
from pathlib import Path
import sys
from PyQt6.QtCore import QPoint
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
from robot_learning_workbench.ui.jobs import BackendJob
app=QApplication([]);root=Path(sys.argv[1]);BackendJob.start=lambda *a,**k:None
w=Window('/no/worker',root/'modules',root/'workspace');w.resize(1280,720);w.show()
for page in w.sessions.values():page.stop_timers()
for _ in range(5):app.processEvents()
p=w.sessions['capture'];sent=[];p.client.send=lambda *a,**k:sent.append(a)
assert hasattr(p,'diagnostics_button'),'Diagnostic log needs a right-hand popup button'
assert p.diagnostics_button.mapTo(p,QPoint()).x()>p.width()/2
assert not p.log.isVisible()
p.show_error('before opening')
for _ in range(5):app.processEvents()
heights=[v.height()for v in p.previews.values()]
p.diagnostics_button.click();app.processEvents()
popup=p.log.window()
assert popup is not w and popup.isVisible() and not popup.isModal()
assert [v.height()for v in p.previews.values()]==heights
p.show_error('arrived while open');assert 'arrived while open'in p.log.toPlainText()
p.history_toggle.click();app.processEvents()
assert popup.isVisible()and p.session_layout.history_dialog.isVisible()
popup.close();p.show_error('arrived while closed');p.diagnostics_button.click();app.processEvents()
assert p.log.window()is popup and 'before opening'in p.log.toPlainText()and 'arrived while closed'in p.log.toPlainText()
assert p.log.isReadOnly()and not sent
w.close();app.processEvents()
assert not popup.isVisible()and not p.session_layout.history_dialog.isVisible()
''',tmp_path)
