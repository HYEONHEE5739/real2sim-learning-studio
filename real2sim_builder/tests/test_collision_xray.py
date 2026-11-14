"""Actual Qt/GL checks for collision geometry, depth classification and controls."""
from test_asset_view import viewport_check


def test_triangle_edges_weld_soup_within_each_part_only(tmp_path):
    viewport_check(tmp_path,'''
import numpy as np
from robot_learning_workbench.ui.asset_viewport import triangle_edges,AssetViewport
# Two triangle soup faces share coordinates but not vertex/UV indices.
points=np.array([[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,-1],[1,0,1],[-1,0,1]])
faces=np.array([[0,1,2],[3,4,5],[0,1,2]])
edges=triangle_edges(points,faces)
assert edges.shape==(5,2,3),edges
assert len({tuple(sorted(map(tuple,e)))for e in edges})==5
v=AssetViewport();v.resize(500,400);v.show()
mesh={'kind':'collision','vertices':points.tolist(),'faces':faces.tolist(),'uv':[],'texture_png':None}
v.load({'meshes':[mesh,dict(mesh)]})
deadline=time.monotonic()+5
while v.running:
 app.processEvents();time.sleep(.005);assert time.monotonic()<deadline,v.gl_error
assert len(v.edges)==2 and sum(e['count']for e in v.edges)==20
v.makeCurrent();ids=[e['buffer'].bufferId()for e in v.edges];v.doneCurrent()
v.load(None);v.repaint();app.processEvents();v.makeCurrent()
assert all(not v.functions.glIsBuffer(i)for i in ids);v.doneCurrent()
v.close();app.processEvents();assert not v.edges
''')


def test_xray_hidden_edges_and_visible_depth_swap_on_orbit(tmp_path):
    viewport_check(tmp_path,'''
import numpy as np
from robot_learning_workbench.ui.asset_viewport import AssetViewport
v=AssetViewport();v.resize(500,400);v.show()
visual={'kind':'visual','vertices':[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]],
 'faces':[[0,1,2],[0,2,3]],'uv':[],'texture_png':None,'color':[.4,.4,.4]}
collision={'kind':'collision','vertices':[[-.8,.3,0],[.8,.3,0],[0,.3,.7]],
 'faces':[[0,1,2]],'uv':[],'texture_png':None}
v.load({'meshes':[visual,collision]})
def render(mode,yaw=0.,opacity=1.,enabled=True):
 v.state.update(yaw=yaw,pitch=0.,grid=False,lighting=False,show_visual=True,
     show_collision=enabled,collision_mode=mode,visual_opacity=opacity,edge_mode='all',hidden_opacity=.65)
 v.request_render();deadline=time.monotonic()+5
 while v.running:
  app.processEvents();time.sleep(.005);assert time.monotonic()<deadline,v.gl_error
 image=v.image.convertToFormat(v.image.Format.Format_RGBA8888)
 ptr=image.bits();ptr.setsize(image.sizeInBytes())
 rgb=np.frombuffer(ptr,np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)[:,:image.width(),:3].astype(float)
 rgb=rgb[20:-30,20:-20]
 cyan=(rgb[:,:,1]>150)&(rgb[:,:,2]>180)&(rgb[:,:,0]<100)
 orange=(rgb[:,:,0]>140)&(rgb[:,:,0]>1.4*rgb[:,:,1])&(rgb[:,:,1]>1.4*rgb[:,:,2])
 return int(cyan.sum()),int(orange.sum()),v.image.copy()
visible=render('visible');xray=render('xray');rotated=render('xray',180.)
assert visible[:2]==(0,0),visible[:2]
assert xray[1]>40 and xray[0]==0,xray[:2]
assert rotated[0]>80 and rotated[1]==0,rotated[:2]
faded=render('xray',opacity=0.)
assert faded[1]==xray[1]and faded[0]==xray[0],(faded[:2],xray[:2])
disabled=render('xray',enabled=False)
assert disabled[:2]==(0,0),disabled[:2]
xray[2].save(str(Path(sys.argv[1])/'hidden-orange.png'))
rotated[2].save(str(Path(sys.argv[1])/'rotated-cyan.png'))
# Visible layer draws no collision surfaces over the Visual interior.
assert xray[2].pixelColor(250,245)==visible[2].pixelColor(250,245)
v.close();app.processEvents()
''')


def test_coplanar_edges_are_visible_without_repeated_face_stacking(tmp_path):
    viewport_check(tmp_path,'''
import copy,numpy as np
from robot_learning_workbench.ui.asset_viewport import AssetViewport
v=AssetViewport();v.resize(500,400);v.show()
mesh={'vertices':[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]],'faces':[[0,1,2],[0,2,3]],
 'kind':'visual','uv':[],'color':[.4]*3,'texture_png':None}
collision=dict(mesh,kind='collision')
def render(faces):
 collision['faces']=faces;v.load({'meshes':[mesh,collision]})
 v.state.update(yaw=0.,pitch=0.,show_collision=True,collision_mode='xray',grid=False,lighting=False,edge_mode='all',hidden_opacity=.65)
 v.request_render();deadline=time.monotonic()+5
 while v.running:
  app.processEvents();time.sleep(.005);assert time.monotonic()<deadline,v.gl_error
 image=v.image.convertToFormat(v.image.Format.Format_RGBA8888);ptr=image.bits();ptr.setsize(image.sizeInBytes())
 a=np.frombuffer(ptr,np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)[:,:image.width(),:3].copy()
 # Exclude QPainter's LCD-antialiased footer text from edge color counts.
 rgb=a[20:-30,20:-20]
 cyan=(rgb[:,:,1]>150)&(rgb[:,:,2]>180)&(rgb[:,:,0]<100)
 orange=(rgb[:,:,0]>140)&(rgb[:,:,0]>rgb[:,:,1]*1.4)&(rgb[:,:,1]>rgb[:,:,2]*1.4)
 assert cyan.sum()>150 and orange.sum()==0,(cyan.sum(),orange.sum())
 return a
one=render([[0,1,2],[0,2,3]]);repeated=render([[0,1,2],[0,2,3]]*3)
assert np.array_equal(one,repeated)
v.close();app.processEvents()
''')


def test_visual_opacity_preserves_geometry_and_depth_classification(tmp_path):
    viewport_check(tmp_path,'''
import copy,numpy as np
from robot_learning_workbench.ui.asset_viewport import AssetViewport
v=AssetViewport();v.resize(500,400);v.show()
mesh={'kind':'visual','vertices':[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]],
 'faces':[[0,1,2],[0,2,3]],'uv':[],'color':[1.,0.,0.],'texture_png':None}
payload={'meshes':[mesh]};before=copy.deepcopy(payload);v.load(payload)
def render(opacity,visible=True):
 v.state.update(yaw=0.,pitch=0.,grid=False,lighting=False,show_visual=visible,
     show_collision=False,visual_opacity=opacity);v.request_render()
 deadline=time.monotonic()+5
 while v.running:
  app.processEvents();time.sleep(.005);assert time.monotonic()<deadline,v.gl_error
 return np.array(v.image.pixelColor(250,220).getRgb()[:3])
full=render(1.);half=render(.5);zero=render(0.);off=render(1.,False)
assert np.max(abs(half-(full+zero)/2))<3,(full,half,zero)
assert np.array_equal(zero,off)and np.array_equal(zero,[32,39,51])
assert payload==before
center=v.center.copy();extent=v.extent
v.reset_view();assert v.state['visual_opacity']==1. and v.state['show_visual']is False
assert np.array_equal(center,v.center)and extent==v.extent
v.close();app.processEvents()
''')
