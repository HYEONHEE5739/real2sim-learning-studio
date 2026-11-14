import numpy as np
import pytest
from real2sim_builder.files import sha


def viewport_check(tmp_path,code):
    """Actual native-window Qt/GL test; offscreen QPA has no GL widget support."""
    import os,subprocess
    from pathlib import Path
    env=dict(os.environ,QT_QPA_PLATFORM='xcb',XDG_CONFIG_HOME=str(tmp_path/'qt-settings'))
    env.pop('PYTHONHOME',None)
    env.pop('LIBGL_ALWAYS_SOFTWARE',None)
    setup='''
import sys,time
from pathlib import Path
from PyQt6.QtWidgets import QApplication
app=QApplication([])
'''
    qt=Path('workbench_runs/runtime/qt/bin/python3.11').absolute()
    run=subprocess.run([str(qt),'-B','-c',setup+code,str(tmp_path)],env=env,text=True,capture_output=True,timeout=30)
    assert run.returncode==0,run.stdout+run.stderr


def test_viewport_per_pixel_occlusion_for_intersecting_triangles(tmp_path):
    viewport_check(tmp_path,'''
from robot_learning_workbench.ui.asset_viewport import AssetViewport
v=AssetViewport();v.resize(500,400);v.show()
payload={'meshes':[{'kind':'visual','vertices':[[-1,-d,-1],[1,d,-1],[0,0,1]],
 'faces':[[0,1,2]],'uv':[],'color':color,'texture_png':None}
 for d,color in[(.8,[1.,0.,0.]),(-.8,[0.,0.,1.])]]}
v.load(payload);v.state.update(yaw=0.,pitch=0.,pan=[0.,0.]);v.request_render()
deadline=time.monotonic()+5
while v.running or v.pending or v.image is None:
 app.processEvents();time.sleep(.005);assert time.monotonic()<deadline
image=v.image;image.save(str(Path(sys.argv[1])/'crossing.png'))
left=image.pixelColor(220,220);right=image.pixelColor(280,220)
assert left.red()>left.blue()*2 and right.blue()>right.red()*2,(left.getRgb(),right.getRgb())
# Submission order must not change per-pixel visibility.
v.load({'meshes':list(reversed(payload['meshes']))});v.state.update(yaw=0.,pitch=0.);v.request_render()
while v.running:
 app.processEvents();time.sleep(.005);assert time.monotonic()<deadline
assert v.image.pixelColor(220,220)==left and v.image.pixelColor(280,220)==right
v.close();app.processEvents()
''')


def test_texture_triangle_seams_version_reload_and_gl_resource_release(tmp_path):
    viewport_check(tmp_path,'''
import base64,numpy as np
from PyQt6.QtCore import QBuffer,QByteArray,QIODevice
from PyQt6.QtGui import QImage,QColor
from robot_learning_workbench.ui.asset_viewport import AssetViewport,view_rotation
assert np.allclose(np.linalg.det(view_rotation(35,30)),1.)
image=QImage(8,8,QImage.Format.Format_RGB32);image.fill(QColor('red'))
raw=QByteArray();stream=QBuffer(raw);stream.open(QIODevice.OpenModeFlag.WriteOnly);image.save(stream,'PNG')
texture=base64.b64encode(bytes(raw)).decode();meshes=[]
# Thin adjacent triangles reproduce integer clipping cracks in the old painter.
for a,b in zip(np.linspace(-1,1,101)[:-1],np.linspace(-1,1,101)[1:]):
 meshes.append({'kind':'visual','vertices':[[a,0,-1],[b,0,-1],[b,0,1],[a,0,1]],
  'faces':[[0,1,2],[0,2,3]],'uv':[[0,0],[1,0],[1,1],[0,1]],
  'color':[0.,1.,0.],'texture_png':texture})
v=AssetViewport();v.resize(500,400);v.show();v.load({'meshes':meshes})
def wait():
 deadline=time.monotonic()+8
 while v.running or v.image is None:
  app.processEvents();time.sleep(.005);assert time.monotonic()<deadline,v.gl_error
v.state.update(yaw=0.,pitch=0.,lighting=False,grid=False);v.request_render();wait()
for x in range(180,320):
 for y in range(140,260):
  c=v.image.pixelColor(x,y);assert c.red()>250 and c.green()<3 and c.blue()<3,(x,y,c.getRgb())
v.makeCurrent();buffers=[p['buffer'].bufferId()for p in v.parts];textures=[p['texture'].textureId()for p in v.parts];v.doneCurrent()
v.load(None);v.repaint();app.processEvents();assert not v.parts and v.image is None
v.makeCurrent();assert all(not v.functions.glIsBuffer(i)for i in buffers)
assert all(not v.functions.glIsTexture(i)for i in textures);v.doneCurrent()
# A second version has a genuinely different color; old buffers cannot survive.
for m in meshes:m['texture_png']=None;m['color']=[0.,0.,1.]
v.load({'meshes':meshes});v.state.update(yaw=0.,pitch=0.,lighting=False,grid=False);v.request_render();wait()
assert v.image.pixelColor(250,200).blue()>250
v.close();app.processEvents();assert not v.parts and v.program is None
''')


def test_collision_visible_only_wireframe_uses_nearest_layer(tmp_path):
    viewport_check(tmp_path,'''
from robot_learning_workbench.ui.asset_viewport import AssetViewport
def triangle(kind,y):
 return {'kind':kind,'vertices':[[-1,y,-1],[1,y,-1],[0,y,1]],'faces':[[0,1,2]],
  'uv':[],'color':[1.,0.,0.],'texture_png':None}
v=AssetViewport();v.resize(500,400);v.show()
meshes=[triangle('visual',.5),triangle('collision',-.3),triangle('collision',.1)]
def sample(rows,mode):
 v.load({'meshes':rows});v.state.update(yaw=0.,pitch=0.,lighting=False,grid=False,
   show_visual=mode!='collision',show_collision=True,collision_mode='visible');v.request_render()
 deadline=time.monotonic()+5
 while v.running or v.image is None:
  app.processEvents();time.sleep(.005);assert time.monotonic()<deadline
 return v.image.pixelColor(250,220).getRgb()
front=sample(meshes[:2],'overlay');both=sample(meshes,'overlay');reverse=sample(list(reversed(meshes)),'overlay')
assert front==both==reverse,(front,both,reverse)
# Overlay is now wireframe: it must not paint the triangle's interior cyan.
assert front[:3]==(255,0,0),front
opaque=sample(meshes,'collision');assert opaque[1]>180 and opaque[2]>200
v.close();app.processEvents()
''')


def test_preview_reads_usda_visual_collision_and_preserves_version(tmp_path):
    from test_object_assets import asset_fixture
    from test_stage_pipeline import synthetic_project
    from real2sim_builder.object_assets import register_object_asset
    from real2sim_builder.asset_view import load_asset_view
    p=synthetic_project(tmp_path);asset=register_object_asset(p,asset_fixture(tmp_path/'source'),asset_id='cup')
    before={f:sha(p.root/asset['manifest'].rsplit('/',1)[0]/f)for f in asset['files']}
    view=load_asset_view(p,asset['manifest'])
    assert view['meshes'] and {'visual','collision'}=={m['kind']for m in view['meshes']}
    assert all(len(m['faces'])>0 and np.asarray(m['vertices']).shape[1]==3 for m in view['meshes'])
    assert view['asset_id']=='cup'and view['version']=='v001'
    assert all(sha(p.root/asset['manifest'].rsplit('/',1)[0]/f)==digest for f,digest in before.items())


def test_preview_rejects_damaged_asset_instead_of_placeholder(tmp_path):
    from test_object_assets import asset_fixture
    from test_stage_pipeline import synthetic_project
    from real2sim_builder.object_assets import register_object_asset
    from real2sim_builder.asset_view import load_asset_view
    p=synthetic_project(tmp_path);a=register_object_asset(p,asset_fixture(tmp_path/'source'),asset_id='cup')
    path=p.root/a['manifest'];path.parent.joinpath(a['entry']).write_text('damaged')
    with pytest.raises(ValueError):load_asset_view(p,a['manifest'])


def test_library_assign_keeps_instance_pose_and_other_scene(tmp_path):
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.object_assets import register_object_asset
    from real2sim_builder.asset_view import library_action
    from test_object_assets import asset_fixture
    a=Project.create(tmp_path/'scenes','one');b=Project.create(tmp_path/'scenes','two')
    asset=register_object_asset(a,asset_fixture(tmp_path/'source'),asset_id='block')
    for p in [a,b]:
        Candidate.create(p,'draft')
        library_action(p,'instantiate',manifest=asset['manifest'],candidate='draft',object_id='block')
    c=Candidate(a,'draft');old=c.scene;other=Candidate(b,'draft').scene
    library_action(a,'assign',manifest=asset['manifest'],candidate='draft',object_id='block')
    assert c.scene['objects'][0]['pose']==old['objects'][0]['pose']
    assert Candidate(b,'draft').scene==other
    assert library_action(a,'preview',manifest=asset['manifest'])['meshes'][0]['texture_png']


def test_qt_viewport_real_triangles_mouse_modes_and_release(tmp_path):
    viewport_check(tmp_path,'''
import time,gc,weakref
from PyQt6.QtCore import QPoint,QPointF,Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtTest import QTest
from robot_learning_workbench.ui.asset_viewport import AssetViewport
v=AssetViewport();v.resize(500,400);v.show()
class Payload(dict):pass
payload=Payload(meshes=[{'kind':kind,'vertices':[[-1,-1,0],[1,-1,0],[0,1,1]],'faces':[[0,1,2]],'uv':[], 'color':[.8,.1,.2],'texture_png':None}for kind in ['visual','collision']])
reference=weakref.ref(payload)
images=[];v.rendered.connect(images.append);v.load(payload)
def wait_image():
 until=time.monotonic()+5
 while v.running or v.pending:
  app.processEvents();time.sleep(.005)
  assert time.monotonic()<until
 app.processEvents()
wait_image();assert images and not images[-1].isNull()
assert v.isValid() and v.gl_info['depth_bits']>=24,v.gl_info
old=v.state['yaw'];QTest.mousePress(v,Qt.MouseButton.RightButton,pos=QPoint(200,200));QTest.mouseMove(v,QPoint(240,220));QTest.mouseRelease(v,Qt.MouseButton.RightButton,pos=QPoint(240,220));assert v.state['yaw']!=old
wheel=QWheelEvent(QPointF(200,200),QPointF(200,200),QPoint(),QPoint(0,120),Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
app.sendEvent(v,wheel);assert v.state['zoom']>1
QTest.mousePress(v,Qt.MouseButton.MiddleButton,pos=QPoint(200,200));QTest.mouseMove(v,QPoint(230,210));QTest.mouseRelease(v,Qt.MouseButton.MiddleButton,pos=QPoint(230,210));assert v.state['pan']!=[0.,0.]
v.state['show_collision']=True;v.request_render();wait_image();v.reset_view();wait_image();assert v.state['zoom']==1 and v.state['show_collision']
images[-1].save(str(Path(sys.argv[1])/'viewport.png'));del payload
v.close();app.processEvents();gc.collect();assert v.closed and v.payload is None
assert reference() is None, 'Closed Viewer retained Mesh data through a completed render task'
assert not v.parts and not v.lines and not v.edges and v.program is None and v.vao is None
''')


def test_library_dialog_actual_backend_loads_usda_without_main_thread_import(tmp_path):
    import sys,json
    from test_object_assets import asset_fixture
    from real2sim_builder.project import Project
    from real2sim_builder.object_assets import register_object_asset
    from PIL import Image
    p=Project.create(tmp_path/'scenes','library UI');red=register_object_asset(p,asset_fixture(tmp_path/'source'),asset_id='cube')
    source=asset_fixture(tmp_path/'blue-source');Image.new('RGB',(4,4),'blue').save(source.parent/'texture.png')
    blue=register_object_asset(p,source,asset_id='cube')
    before={f:sha((p.root/red['manifest']).parent/f)for f in red['files']}
    viewport_check(tmp_path,'''\nimport time
from robot_learning_workbench.ui.object_library import ObjectLibraryDialog
from PyQt6.QtCore import QProcess
root=Path('''+repr(str(p.root))+''')
d=ObjectLibraryDialog(root,'''+repr(sys.executable)+''');d.show()
deadline=time.monotonic()+15
while d.job.process.state()!=QProcess.ProcessState.NotRunning:
 app.processEvents();time.sleep(.01);assert time.monotonic()<deadline
app.processEvents();assert d.items.count()==1,d.status.text()
d.items.setCurrentRow(0)
while d.job.process.state()!=QProcess.ProcessState.NotRunning or d.view.running:
 app.processEvents();time.sleep(.01);assert time.monotonic()<deadline
app.processEvents();assert d.view.payload['asset_id']=='cube',d.status.text()
assert d.view.state['show_visual']and not d.view.state['show_collision']
assert d.collision_mode.currentData()=='xray'and d.opacity.value()==100
assert d.edge_mode.currentData()=='feature'and d.feature_angle.value()==25
assert d.visible_opacity.value()==0 and d.hidden_opacity.value()==0
assert not d.advanced.isChecked()and not d.advanced_panel.isVisible()
assert 'pxr'not in sys.modules
assert d.view.image is not None
colors=[d.view.image.pixelColor(x,y)for x in range(0,d.view.image.width(),10)for y in range(0,d.view.image.height(),10)]
assert any(c.red()>150 and c.green()<60 and c.blue()<60 for c in colors), 'USD red Texture was not rendered'
assert d.view.image.save(str(Path(sys.argv[1])/'actual_asset_view.png'))
# UI switches modify the displayed buffers, not the Asset or Camera transform.
d.visible_opacity.setValue(100);d.collision_mode.setCurrentIndex(d.collision_mode.findData('visible'));d.opacity.setValue(45)
assert d.view.state['show_collision']and d.view.state['collision_mode']=='visible'
assert d.view.state['visual_opacity']==.45
d.edge_mode.setCurrentIndex(d.edge_mode.findData('all'));d.hidden_opacity.setValue(50);d.visible_opacity.setValue(60)
assert d.view.state['edge_mode']=='all'and d.view.state['hidden_opacity']==.5
assert d.view.state['visible_opacity']==.6 and not d.feature_angle.isEnabled()
d.edge_mode.setCurrentIndex(d.edge_mode.findData('feature'));d.feature_angle.setValue(40)
assert d.feature_angle.isEnabled()and d.view.state['feature_angle']==40
# Real version selector reloads actual GPU geometry/Texture and clears stale
# preview data while the second version is loading.
assert d.version.count()==2
d.version.setCurrentIndex(1);assert d.view.payload is None
while d.job.process.state()!=QProcess.ProcessState.NotRunning or d.view.running or d.view.image is None:
 app.processEvents();time.sleep(.01);assert time.monotonic()<deadline
assert d.view.payload['version']=='v002'
assert d.visible_opacity.value()==60 and d.opacity.value()==45
assert d.view.state['visual_opacity']==.45 and d.view.state['show_collision']
assert d.view.state['feature_angle']==40 and d.view.state['hidden_opacity']==.5
d.visible_opacity.setValue(0);d.hidden_opacity.setValue(0);d.opacity.setValue(100)
while d.view.running:
 app.processEvents();time.sleep(.005);assert time.monotonic()<deadline
colors=[d.view.image.pixelColor(x,y)for x in range(0,d.view.image.width(),10)for y in range(0,d.view.image.height(),10)]
assert any(c.blue()>150 and c.green()<60 and c.red()<60 for c in colors),'Version Texture remained stale'
d.version.setCurrentIndex(0)
while d.job.process.state()!=QProcess.ProcessState.NotRunning or d.view.running or d.view.image is None:
 app.processEvents();time.sleep(.01);assert time.monotonic()<deadline
assert d.view.payload['version']=='v001'
d.collision_only.click()
assert d.collision_only.isChecked()and not d.view.state['show_visual']and d.view.state['show_collision']
d.reset.click();assert not d.view.state['show_visual']and d.view.state['show_collision']
d.collision_only.click();assert d.view.state['show_visual']and not d.view.state['show_collision']
d.close();app.processEvents()
''')
    assert all(sha((p.root/red['manifest']).parent/f)==h for f,h in before.items())
