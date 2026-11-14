"""Native Qt display state and zero-opacity depth/color separation."""
from test_asset_view import viewport_check


def test_three_opacity_controls_and_advanced_diagnostic_restore(tmp_path):
    viewport_check(tmp_path,'''
import copy
from PyQt6.QtWidgets import QCheckBox
from robot_learning_workbench.ui.object_library import ObjectLibraryDialog
from robot_learning_workbench.ui.theme import STYLE
app.setStyleSheet(STYLE)
ObjectLibraryDialog.call=lambda *args,**kwargs:None  # External backend boundary.
d=ObjectLibraryDialog(Path(sys.argv[1]),sys.executable);d.show()
mesh={'kind':'visual','vertices':[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]],
 'faces':[[0,1,2],[0,2,3]],'uv':[],'texture_png':None,'color':[.4]*3}
payload={'asset_id':'long_object_'*40,'version':'v001','dimensions':{'value':[.024,None,.024],
 'provenance':'measured','evidence':['reference '*200]},'collision_status':'AUTHORED_UNVALIDATED',
 'physical_verified':False,'material_scope':'diffuse/UV preview','meshes':[mesh,dict(mesh,kind='collision')]}
d.operation='preview';d.received({'ok':True,'result':payload})
def wait():
 end=time.monotonic()+5
 while d.view.running:
  app.processEvents();time.sleep(.005);assert time.monotonic()<end,d.view.gl_error
 app.processEvents()
wait()
assert (d.opacity.value(),d.visible_opacity.value(),d.hidden_opacity.value())==(100,0,0)
assert not d.advanced.isChecked()and not d.advanced_panel.isVisible()
assert not any(w.isVisible()for w in d.findChildren(QCheckBox))
assert d.view.state['collision_mode']=='xray'and d.view.state['edge_mode']=='feature'
assert not d.view.state['show_collision']and d.view.state['show_visual']
assert '24 × ? × 24 mm'in d.details.text()and 'reference'not in d.details.text()
assert payload['asset_id']in d.advanced_details.text()and 'reference'in d.advanced_details.toolTip()
topology=d.view.topology;ids=[p['buffer'].bufferId()for p in d.view.parts+d.view.edges]
d.opacity.setValue(0);d.visible_opacity.setValue(100);d.hidden_opacity.setValue(20);wait()
assert d.view.state['show_visual']and d.view.state['visual_opacity']==0  # Depth remains.
assert d.view.state['show_collision']and d.view.state['hidden_opacity']==.2
assert d.view.topology is topology and ids==[p['buffer'].bufferId()for p in d.view.parts+d.view.edges]
d.advanced.click();wait();assert d.advanced_panel.isVisible()
d.edge_mode.setCurrentIndex(d.edge_mode.findData('all'));assert not d.feature_angle.isEnabled()
d.edge_mode.setCurrentIndex(d.edge_mode.findData('feature'));assert d.feature_angle.isEnabled()
d.feature_angle.setValue(40)
d.collision_mode.setCurrentIndex(d.collision_mode.findData('visible'));assert not d.hidden_opacity.isEnabled()
d.visible_opacity.setValue(0);wait();assert not d.view.state['show_collision']
d.collision_mode.setCurrentIndex(d.collision_mode.findData('xray'));d.visible_opacity.setValue(80)
saved=copy.deepcopy(d.view.state);values=(d.opacity.value(),d.visible_opacity.value(),d.hidden_opacity.value())
d.collision_only.click();wait();assert d.collision_only.isChecked()
assert not d.view.state['show_visual']and d.view.state['show_collision']
assert not d.opacity.isEnabled()and not d.visible_opacity.isEnabled()
d.collision_only.click();wait()
assert d.view.state==saved and values==(d.opacity.value(),d.visible_opacity.value(),d.hidden_opacity.value())
d.advanced.click();wait();assert not d.advanced_panel.isVisible()and d.view.state==saved
d.visible_opacity.setValue(0);d.hidden_opacity.setValue(0);wait();assert not d.view.state['show_collision']
d.advanced.click();d.resize(900,720);wait();assert (d.width(),d.height())==(900,720)
assert d.view.geometry().bottom()<d.details.geometry().top()
d.close();app.processEvents();assert not d.view.parts and d.view.payload is None
''')


def test_zero_visual_alpha_skips_color_pass_but_keeps_hidden_edge_depth(tmp_path):
    viewport_check(tmp_path,'''
import numpy as np
from robot_learning_workbench.ui.asset_viewport import AssetViewport
v=AssetViewport();v.resize(500,400);v.show()
visual={'kind':'visual','vertices':[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]],
 'faces':[[0,1,2],[0,2,3]],'uv':[],'texture_png':None,'color':[.4]*3}
collision={'kind':'collision','vertices':[[-.8,.3,0],[.8,.3,0],[0,.3,.7]],
 'faces':[[0,1,2]],'uv':[],'texture_png':None}
v.load({'meshes':[visual,collision]});calls=[];draw=v.draw
def observed(part,color,**kwargs):
 calls.append((part.get('kind'),color[3]));return draw(part,color,**kwargs)
v.draw=observed
def render(alpha):
 v.state.update(yaw=0.,pitch=0.,grid=False,show_visual=True,visual_opacity=alpha,
  show_collision=True,collision_mode='xray',visible_opacity=1.,hidden_opacity=1.)
 calls.clear();v.request_render();end=time.monotonic()+5
 while v.running:
  app.processEvents();time.sleep(.005);assert time.monotonic()<end,v.gl_error
 image=v.image.convertToFormat(v.image.Format.Format_RGBA8888);ptr=image.bits();ptr.setsize(image.sizeInBytes())
 rgb=np.frombuffer(ptr,np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)[:,:image.width(),:3]
 orange=(rgb[:,:,0]>200)&(rgb[:,:,1]>80)&(rgb[:,:,1]<180)&(rgb[:,:,2]<80)
 return orange
full=render(1.);zero=render(0.)
assert full.sum()>40 and np.array_equal(full,zero)
assert any(kind=='visual'for kind,alpha in calls)  # Depth-only raster still exists.
assert not any(kind=='visual'and alpha==0 for kind,alpha in calls),calls
v.makeCurrent();assert v.functions.glGetError()==0
assert v.functions.glGetBooleanv(0x0B72)and not v.functions.glIsEnabled(0x0BE2);v.doneCurrent()
v.close();app.processEvents()
''')
