"""Geometry-derived feature/contour selection and actual GL display settings."""
from test_asset_view import viewport_check


def test_feature_topology_boundaries_angles_nonmanifold_and_degenerate_faces(tmp_path):
    viewport_check(tmp_path,'''
import numpy as np
from robot_learning_workbench.ui.collision_wireframe import collision_topology,feature_mask
def mesh(v,f):return {'kind':'collision','vertices':v,'faces':f}
plane=mesh([[0,0,0],[1,0,0],[1,1,0],[0,1,0]],[[0,1,2],[0,2,3],[0,1,2],[0,0,1]])
t=collision_topology([plane])
assert len(t['parts'][0]['segments'])==5
assert feature_mask(t,25,[0,0,1]).sum()==4
assert t['ignored_degenerate']==1 and t['ignored_duplicate']==1
# Boundary edges survive even at angle180; a real20 degree crease varies.
angle=np.radians(20.)
fold=mesh([[0,0,0],[1,0,0],[0,1,0],[0,-np.cos(angle),np.sin(angle)]],[[0,1,2],[1,0,3]])
t=collision_topology([fold])
assert feature_mask(t,25,[0,0,1]).sum()==4
assert feature_mask(t,15,[0,0,1]).sum()==5
nonmanifold=mesh([[0,0,0],[1,0,0],[0,1,0],[0,-1,0],[0,0,1]],[[0,1,2],[1,0,3],[0,1,4]])
t=collision_topology([nonmanifold]);assert t['nonmanifold_edges']==1
assert feature_mask(t,180,[0,0,1]).all()
# Empty/zero-area data is safe and does not invent a normal or a feature.
t=collision_topology([mesh([[0,0,0],[1,0,0],[2,0,0]],[[0,1,2]])])
assert not feature_mask(t,25,[0,0,1]).any() and t['ignored_degenerate']==1
''')


def test_contacting_parts_use_geometry_not_part_identity_for_feature_seams(tmp_path):
    viewport_check(tmp_path,'''
import numpy as np
from robot_learning_workbench.ui.collision_wireframe import collision_topology,feature_mask
def box(lo,hi):
 v=np.array([[x,y,z]for x in[lo[0],hi[0]]for y in[lo[1],hi[1]]for z in[lo[2],hi[2]]])
 faces=[[0,1,3],[0,3,2],[4,6,7],[4,7,5],[0,4,5],[0,5,1],
        [2,3,7],[2,7,6],[0,2,6],[0,6,4],[1,5,7],[1,7,3]]
 return {'kind':'collision','vertices':v.tolist(),'faces':faces}
a=box([-1,-1,-1],[0,1,1]);b=box([0,-1,-1],[1,1,1])
# Matching interface with deliberately different triangle diagonals.
b['faces'][:2]=[[0,1,2],[1,3,2]]
t=collision_topology([a,b]);assert t['contact_patch_pairs']==1
mask=feature_mask(t,25,[1,1,1]);segments=t['segments'][mask]
# No internal seam in the middle of a straight combined box face.
assert not any(np.all(e[:,0]==0) for e in segments)
assert sum(len(p['segments'])for p in t['parts'])==36
actual={tuple(sorted(map(tuple,e)))for p in t['parts']for e in p['segments']}
assert all(tuple(sorted(map(tuple,e)))in actual for e in segments)
# Separated parts are never bridged or classified as a shared interface.
b['vertices']=(np.array(b['vertices'])+[.1,0,0]).tolist()
t=collision_topology([a,b]);assert t['contact_patch_pairs']==0
assert sum(feature_mask(t,25,[1,1,1]))==24
# Identical solids with reversed winding are overlapping geometry, not a set
# of internal contact patches. Their whole outline must never disappear.
reverse=box([-1,-1,-1],[0,1,1]);reverse['faces']=[list(reversed(f))for f in reverse['faces']]
t=collision_topology([a,reverse]);assert t['contact_patch_pairs']==0
assert feature_mask(t,25,[1,1,1]).sum()==24
''')


def test_curved_surface_silhouette_survives_large_feature_angle_and_orbit(tmp_path):
    viewport_check(tmp_path,'''
import numpy as np
from robot_learning_workbench.ui.collision_wireframe import collision_topology,feature_mask
v=[]
for z in[-1.,1.]:
 for a in np.arange(64)*2*np.pi/64:v.append([np.cos(a),np.sin(a),z])
f=[]
for i in range(64):
 j=(i+1)%64;f.extend([[i,j,64+j],[i,64+j,64+i]])
t=collision_topology([{'kind':'collision','vertices':v,'faces':f}])
a=feature_mask(t,89,[1.,.13,0]);b=feature_mask(t,89,[.13,1.,0])
# 128 rim edges plus two view-dependent longitudinal silhouette segments.
assert a.sum()==130 and b.sum()==130
assert not np.array_equal(a,b)
assert feature_mask(t,1,[1.,.13,0]).sum()>a.sum()
assert np.isfinite(t['normals']).all()
''')


def test_feature_gl_cache_silhouette_opacity_and_state_restoration(tmp_path):
    viewport_check(tmp_path,'''
import numpy as np
from robot_learning_workbench.ui.asset_viewport import AssetViewport
v=AssetViewport();v.resize(500,400);v.show()
vertices=[[np.cos(a),np.sin(a),z]for z in[-1.,1.]for a in np.arange(64)*2*np.pi/64]
faces=[]
for i in range(64):
 j=(i+1)%64;faces.extend([[i,j,64+j],[i,64+j,64+i]])
mesh={'kind':'collision','vertices':vertices,'faces':faces,'uv':[],'texture_png':None}
v.load({'meshes':[dict(mesh,kind='visual',color=[.4]*3),mesh]})
def wait():
 deadline=time.monotonic()+5
 while v.running:
  app.processEvents();time.sleep(.005);assert time.monotonic()<deadline,v.gl_error
v.state.update(show_collision=True,edge_mode='feature',feature_angle=25.,pitch=0.,yaw=7.);v.request_render();wait()
assert v.feature['count']==260
topology=v.topology;ids=[p['buffer'].bufferId()for p in v.parts+v.edges];feature_id=v.feature['buffer'].bufferId()
def forbidden():raise AssertionError('Display setting reloaded geometry')
v.upload=forbidden
key=v.feature_key
v.state['yaw']=17.;v.request_render();wait();assert v.feature_key!=key and v.feature['count']==260
v.state['feature_angle']=1.;v.request_render();wait();assert v.feature['count']>260
key=v.feature_key
for alpha in[0.,.2,.5,1.]:
 v.state.update(hidden_opacity=alpha,visible_opacity=1.-alpha/2);v.request_render();wait()
 assert v.topology is topology and v.feature_key==key
 assert feature_id==v.feature['buffer'].bufferId()
assert ids==[p['buffer'].bufferId()for p in v.parts+v.edges]
v.state['edge_mode']='all';v.request_render();wait();assert v.edges[0]['count']==512
v.state['show_collision']=False;v.request_render();wait()
v.makeCurrent();assert v.functions.glGetError()==0
assert v.functions.glGetBooleanv(0x0B72)  # GL_DEPTH_WRITEMASK restored.
assert not v.functions.glIsEnabled(0x0BE2)  # GL_BLEND disabled after drawing.
v.doneCurrent();v.close();app.processEvents();assert v.feature is None and v.topology is None
''')


def test_edge_opacity_zero_twenty_fifty_hundred_is_actual_alpha_blending(tmp_path):
    viewport_check(tmp_path,'''
import numpy as np
from robot_learning_workbench.ui.asset_viewport import AssetViewport
v=AssetViewport();v.resize(500,400);v.show()
visual={'kind':'visual','vertices':[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]],
 'faces':[[0,1,2],[0,2,3]],'uv':[],'texture_png':None,'color':[.4]*3}
collision={'kind':'collision','vertices':[[-.8,.3,0],[.8,.3,0],[0,.3,.7]],'faces':[[0,1,2]],'uv':[],'texture_png':None}
v.load({'meshes':[visual,collision]})
def render(alpha,yaw=0.,mode='xray'):
 v.state.update(yaw=yaw,pitch=0.,grid=False,lighting=False,show_collision=True,collision_mode=mode,
  hidden_opacity=alpha,visible_opacity=alpha,edge_mode='feature',feature_angle=25.)
 v.request_render();deadline=time.monotonic()+5
 while v.running:
  app.processEvents();time.sleep(.005);assert time.monotonic()<deadline,v.gl_error
 image=v.image.convertToFormat(v.image.Format.Format_RGBA8888);ptr=image.bits();ptr.setsize(image.sizeInBytes())
 return np.frombuffer(ptr,np.uint8).reshape(image.height(),image.bytesPerLine()//4,4)[:,:image.width(),:3].astype(float)
for yaw in[0.,180.]:
 frames={a:render(a,yaw)for a in[0.,.2,.5,1.]}
 # Sample an interior section of a single horizontal segment, away from line
 # junctions and footer glyphs. MSAA coverage is part of the measured alpha.
 roi=(slice(195,205),slice(200,300));difference=np.max(abs(frames[1.][roi]-frames[0.][roi]),axis=-1)
 y,x=np.unravel_index(difference.argmax(),difference.shape);y+=195;x+=200
 base=frames[0.][y,x];full=frames[1.][y,x];assert np.max(abs(full-base))>30,(yaw,base,full)
 for a in[.2,.5]:assert np.max(abs(frames[a][y,x]-(base+a*(full-base))))<=2.,(yaw,a,frames[a][y,x])
 if yaw==0.:
  assert np.array_equal(frames[0.],render(1.,yaw,'visible'))
  assert full[0]>full[1]>full[2]  # Orange hidden layer.
 else:assert full[2]>full[0]and full[1]>full[0]  # Cyan visible layer.
v.close();app.processEvents()
''')


def test_zero_area_collision_has_no_invented_edges_or_gl_error(tmp_path):
    viewport_check(tmp_path,'''
from robot_learning_workbench.ui.asset_viewport import AssetViewport
v=AssetViewport();v.resize(500,400);v.show()
mesh={'kind':'collision','vertices':[[0,0,0],[1,0,0],[2,0,0]],'faces':[[0,1,2]],'uv':[],'texture_png':None}
v.load({'meshes':[mesh]});v.state['show_collision']=True;v.request_render()
deadline=time.monotonic()+5
while v.running:
 app.processEvents();time.sleep(.005);assert time.monotonic()<deadline,v.gl_error
assert v.topology['ignored_degenerate']==1 and v.feature['count']==0
assert v.edges[0]['count']==0
v.makeCurrent();assert v.functions.glGetError()==0;v.doneCurrent()
v.close();app.processEvents()
''')
