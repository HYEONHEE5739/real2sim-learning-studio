"""Camera allocation follows metadata, independent of names and engine choice."""
import copy
import numpy as np
import pytest
from PIL import Image
from real2sim_builder.scene import value
from test_builder_export import legacy_scene


def scene_with_roles():
    scene=legacy_scene();base=scene['cameras'][0];scene['cameras']=[]
    for name in ('optical_a','optical_b','side','wrist_photo','appearance'):
        cam=copy.deepcopy(base);cam['id']=name;scene['cameras'].append(cam)
    images=[{'id':'capture_a','camera':'optical_a','role':'capture','camera_type':'side'},
        {'id':'capture_b','camera':'optical_b','role':'capture','camera_type':'wrist'},
        {'id':'photo_1','camera':'side','role':'scene_photo','camera_type':'external'},
        {'id':'photo_2','camera':'wrist_photo','role':'scene_photo','camera_type':'external'},
        {'id':'ref','camera':'appearance','role':'model_reference','camera_type':'external'}]
    scene['view_registrations']={r['id']:{'camera':r['camera'],'camera_type':r['camera_type']}for r in images if r['role']!='model_reference'}
    return scene,images


def test_sensor_selection_uses_metadata_not_side_wrist_names_and_is_read_only():
    from real2sim_builder.cameras import select_render_cameras,camera_roles
    scene,images=scene_with_roles();before=copy.deepcopy(scene)
    assert camera_roles(scene,images)=={'optical_a':'side','optical_b':'wrist','side':'reference','wrist_photo':'reference','appearance':'context'}
    selected=select_render_cameras(scene,image_records=images)
    assert [c['id']for c in selected['cameras']]==['optical_a','optical_b']
    assert scene==before
    selected['cameras'][0]['pose']['value'][0][3]=123
    assert scene==before


def test_explicit_virtual_camera_keeps_original_k_pose_image_binding_and_all_source_views():
    from real2sim_builder.cameras import select_render_cameras
    scene,images=scene_with_roles();before=copy.deepcopy(scene)
    selected=select_render_cameras(scene,image_records=images,camera_ids=['side'])
    assert selected['cameras']==[scene['cameras'][2]]
    assert selected['view_registrations']=={'photo_1':scene['view_registrations']['photo_1']}
    assert scene==before and len(scene['cameras'])==5
    with pytest.raises(ValueError,match='context|reference'):select_render_cameras(scene,image_records=images,camera_ids=['appearance'])
    with pytest.raises(ValueError,match='Unknown'):select_render_cameras(scene,image_records=images,camera_ids=['invented'])


def test_conflicting_or_absent_role_metadata_cannot_allocate_arbitrary_sensors():
    from real2sim_builder.cameras import select_render_cameras,camera_roles
    scene,images=scene_with_roles();images[0]['camera_type']='external'
    with pytest.raises(ValueError,match='Conflicting'):camera_roles(scene,images)
    plain=legacy_scene()
    with pytest.raises(ValueError,match='metadata'):select_render_cameras(plain)
    plain['cameras'][0]['purpose']='inspection'
    assert camera_roles(plain)['side']=='reference'
    assert len(select_render_cameras(plain,camera_ids=['side'])['cameras'])==1


@pytest.mark.parametrize('engine',['mujoco','isaac'])
def test_photo_comparison_opens_one_virtual_camera_at_a_time_and_closes_on_failure(tmp_path,monkeypatch,engine):
    from real2sim_builder.project import Project
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.observations import register_image
    from real2sim_builder.authoring import apply_scene_plan
    from real2sim_builder.calibration.hybrid import alignment_metrics
    p=Project.create(tmp_path,'reference lifetime');scene=legacy_scene();cam=scene['cameras'][0];cam['id']='photo_0';p.save_scene(scene);c=Candidate.create(p,'auto')
    plan={'object_poses':[],'cameras':[],'needs':[]}
    for index in range(8):
        path=tmp_path/(str(index)+'.png');Image.new('RGB',(160,120),(index,20,30)).save(path)
        name='photo_'+str(index);image=register_image(p,path,camera=name,camera_type='external',scene_state='layout')
        plan['cameras'].append({'id':name,'frame':'world','pose':cam['pose']['value'],'K':cam['K']['value'],'distortion':[0]*5,'resolution':[160,120],'image_ids':[image['id']],'evidence':['estimated photo camera']})
    apply_scene_plan(c,plan,scene_state='layout');before=copy.deepcopy(c.scene);active=[];opened=[];closed=[]
    class Native:
        def __init__(self,scene,*a,**kw):
            names=[x['id']for x in scene['cameras']];assert len(names)==1 and not active
            self.name=names[0];active.append(self.name);opened.append(self.name)
        def __enter__(self):return self
        def __exit__(self,*a):closed.append(self.name);active.remove(self.name)
        def update_scene(self,scene):assert [x['id']for x in scene['cameras']]==[self.name]
        def rgb(self,name):assert name==self.name;return np.zeros((120,160,3),np.uint8)
    result=alignment_metrics(p,c.scene,c.root/'fitting/test',{'engine':engine,'renderer_factory':Native})
    assert len(result['images'])==8 and len(opened)==8 and opened==closed and not active
    assert c.scene==before
    class Failure(Native):
        def rgb(self,name):raise RuntimeError('native image failed')
    with pytest.raises(RuntimeError,match='native image failed'):
        alignment_metrics(p,c.scene,c.root/'fitting/failure',{'engine':engine,'renderer_factory':Failure})
    assert not active and opened==closed and c.scene==before


def test_isaac_close_releases_owned_render_products_and_stage_even_when_repeated():
    from real2sim_builder.isaac_render import IsaacRenderer
    events=[]
    class Annotator:
        def detach(self,paths):assert paths==['/owned'];events.append('detach')
    class Product:
        path='/owned'
        def destroy(self):events.append('product')
    class Stage:
        def RemovePrim(self,path):assert path=='/World/Authored';events.append('stage')
    class Sim:
        def clear_all_callbacks(self):events.append('callbacks')
        def clear_instance(self):events.append('instance')
        def stop(self):events.append('stop')
    renderer=IsaacRenderer.__new__(IsaacRenderer)
    renderer.frames={'buffer':object()};renderer.cameras={'a':{'rgb':Annotator()}};renderer.products=[Product(),Product()];renderer.camera_product_paths={'a':'/owned'};renderer.stage=Stage();renderer.sim=Sim()
    renderer.close();renderer.close()
    assert events==['detach','product','product','stage','callbacks','instance','stop']
    assert renderer.products==[]and not renderer.frames and renderer.stage is None and renderer.sim is None


def test_sensor_context_is_reused_and_closed_before_opening_a_photo_or_after_failure(tmp_path):
    from real2sim_builder.rendering import render_views
    scene,images=scene_with_roles();active=[];created=[];closed=[]
    class Native:
        def __init__(self,scene,*args):
            assert not active
            self.names=[c['id']for c in scene['cameras']];active.append(self);created.append(self.names)
        def __enter__(self):return self
        def __exit__(self,*args):active.remove(self);closed.append(self.names)
        def update_scene(self,scene):assert [c['id']for c in scene['cameras']]==self.names
    with pytest.raises(RuntimeError,match='stop'):
        with render_views(Native,tmp_path,tmp_path,images)as view:
            with view(scene,'optical_a')as first:pass
            with view(scene,'optical_b')as second:assert first is second
            with view(scene,'side')as photo:assert photo.names==['side']
            assert not active
            with view(scene,'optical_a'):raise RuntimeError('stop')
    assert created==closed==[['optical_a','optical_b'],['side'],['optical_a','optical_b']]


@pytest.mark.parametrize('engine',['mujoco','isaac'])
def test_authored_realsim_uses_role_to_camera_binding_in_both_engines(tmp_path,monkeypatch,engine):
    from types import SimpleNamespace
    from robot_learning_workbench.robot import authored_render
    from real2sim_builder import rendering,isaac_render,capture
    scene,images=scene_with_roles();scene['robot_model']={'path':'unused.urdf'}
    before=copy.deepcopy(scene);allocated=[]
    class Native:
        def __init__(self,scene,*args,**kwargs):
            self.names=[c['id']for c in scene['cameras']];allocated.append(self.names)
        def update_scene(self,scene):assert [c['id']for c in scene['cameras']]==self.names
        def rgb(self,name):assert name in self.names;return np.zeros((480,640,3),np.uint8)
        def close(self):pass
    monkeypatch.setattr(rendering,'Renderer',Native);monkeypatch.setattr(isaac_render,'IsaacRenderer',Native)
    monkeypatch.setattr(authored_render,'joint_specs',lambda path:{n:{'limits':[-1.,1.]}for n in authored_render.JOINTS})
    monkeypatch.setattr(capture,'observation_scene',lambda scene,*args,**kwargs:copy.deepcopy(scene))
    view=SimpleNamespace(authored_scene=scene,package=SimpleNamespace(root=tmp_path),engine=engine,verify=lambda:None,scene_identity={},source_scene={},mapping={})
    with authored_render.AuthoredRenderer(view,tmp_path)as renderer:result=renderer.render([0.]*6)
    assert allocated==[['optical_a','optical_b']]
    assert set(result['images'])==set(result['sim_cameras'])=={'side','wrist'}
    assert result['sim_cameras']['side']['camera_id']=='optical_a'
    assert result['sim_cameras']['wrist']['camera_id']=='optical_b'
    assert scene==before and result['physics_steps']==0


def test_isaac_close_still_destroys_products_and_stops_context_when_detach_fails():
    from real2sim_builder.isaac_render import IsaacRenderer
    events=[]
    class BrokenAnnotator:
        def detach(self,*args):raise RuntimeError('native graph gone')
    class Product:
        def destroy(self):events.append('destroy')
    class Sim:
        def clear_all_callbacks(self):events.append('callbacks')
        def clear_instance(self):events.append('instance')
        def stop(self):events.append('stop')
    renderer=IsaacRenderer.__new__(IsaacRenderer);renderer.frames={};renderer.cameras={'a':{'rgb':BrokenAnnotator()}}
    renderer.products=[Product()];renderer.camera_product_paths={'a':'/owned'};renderer.stage=None;renderer.sim=Sim()
    with pytest.raises(RuntimeError,match='native graph gone'):renderer.close()
    assert events==['destroy','callbacks','instance','stop']
    renderer.close()
    assert not renderer.cameras and not renderer.products and renderer.sim is None


@pytest.mark.parametrize('object_observations',[False,True])
def test_isaac_compare_worker_requests_rgb_and_only_needed_mask_output(tmp_path,monkeypatch,object_observations):
    import sys
    from types import SimpleNamespace
    from real2sim_builder import isaac_render,project
    from real2sim_builder.calibration import hybrid
    from real2sim_builder.files import write,read
    outputs=[];closed=[]
    launcher=lambda **kw:SimpleNamespace(app=SimpleNamespace(close=lambda **kw:closed.append(True)))
    monkeypatch.setitem(sys.modules,'isaaclab.app',SimpleNamespace(AppLauncher=launcher))
    monkeypatch.setattr(project,'Project',lambda path:SimpleNamespace(root=tmp_path))
    def native(*args,**kw):outputs.append(kw['data_types'])
    monkeypatch.setattr(isaac_render,'IsaacRenderer',native)
    monkeypatch.setattr(hybrid,'cloud_inputs',lambda *args:[{'object_id':'block'}]if object_observations else [])
    def compare(p,scene,folder,options):
        options['renderer_factory'](scene,p.root,folder)
        return {'images':[],'physics_steps':0}
    monkeypatch.setattr(hybrid,'alignment_metrics',compare)
    write(tmp_path/'request.json',{'project':str(tmp_path),'scene':legacy_scene(),'options':{},'operation':'compare'})
    isaac_render.worker(tmp_path)
    assert outputs==[('rgb','semantic_segmentation')if object_observations else('rgb',)]
    assert closed==[True]and read(tmp_path/'report.json')['physics_steps']==0


def test_reference_views_release_products_without_recreating_switchable_scene_context(tmp_path):
    from real2sim_builder.rendering import render_views
    scene,images=scene_with_roles();created=[];closed=[];released=[]
    class Native:
        def __init__(self,scene,*args):created.append(self);self.update_scene(scene)
        def update_scene(self,scene):self.products=[c['id']for c in scene['cameras']]
        def release_cameras(self):released.append(list(self.products));self.products=[]
        def __enter__(self):return self
        def __exit__(self,*args):self.release_cameras();closed.append(self)
    with render_views(Native,tmp_path,tmp_path,images)as view:
        for n in range(8):
            with view(scene,'side')as renderer:assert renderer.products==['side']
            assert not renderer.products and not closed
        with view(scene,'optical_a')as renderer:assert renderer.products==['optical_a','optical_b']
        with view(scene,'optical_b')as other:assert renderer is other
    assert len(created)==len(closed)==1 and len(released)==9


def test_isaac_camera_switch_uses_real_usd_schema_without_rebuilding_geometry(tmp_path,monkeypatch):
    import sys,types
    from pxr import Usd,UsdGeom
    from real2sim_builder.isaac_render import IsaacRenderer
    from real2sim_builder.exporters.usd import export
    scene=legacy_scene();scene['cameras'][0]['id']='photo_a';before=copy.deepcopy(scene)
    path=tmp_path/'scene.usda';export(scene,tmp_path,path)
    stage=Usd.Stage.CreateInMemory();stage.DefinePrim('/World/Authored','Xform').GetReferences().AddReference(str(path),'/Scene')
    attached=[];detached=[];destroyed=[]
    class Annotator:
        def attach(self,paths):attached.extend(paths)
        def detach(self,paths):detached.extend(paths)
    class Product:
        def __init__(self):self.path='/products/'+str(len(attached))
        def destroy(self):destroyed.append(self.path)
    core=types.ModuleType('omni.replicator.core');core.create=types.SimpleNamespace(render_product=lambda *a,**kw:Product());core.AnnotatorRegistry=types.SimpleNamespace(get_annotator=lambda *a,**kw:Annotator())
    omni=types.ModuleType('omni');replicator=types.ModuleType('omni.replicator');omni.replicator=replicator;replicator.core=core
    for name,module in(('omni',omni),('omni.replicator',replicator),('omni.replicator.core',core)):monkeypatch.setitem(sys.modules,name,module)
    renders=[];sim=types.SimpleNamespace(render=lambda:renders.append(True),clear_all_callbacks=lambda:None,clear_instance=lambda:None,stop=lambda:None)
    renderer=IsaacRenderer.__new__(IsaacRenderer);renderer.scene=copy.deepcopy(scene);renderer.stage=stage;renderer.sim=sim
    renderer.frames={};renderer.cameras={};renderer.products=[];renderer.camera_product_paths={};renderer.resolutions={};renderer.data_types=('rgb',)
    renderer.update_scene(scene);first_product=renderer.products[0].path
    renderer.release_cameras();assert not renderer.products
    second=copy.deepcopy(scene);camera=second['cameras'][0];camera['id']='photo_b';camera['K']['value'][0][0]=510.;camera['K']['value'][0][2]=70.
    renderer.update_scene(second)
    native=UsdGeom.Camera.Get(stage,'/World/Authored/photo_b');w=camera['resolution'][0]
    assert native and native.GetPrim().IsActive()and not stage.GetPrimAtPath('/World/Authored/photo_a').IsActive()
    assert np.isclose(native.GetHorizontalApertureAttr().Get(),w/510.*10)
    assert np.isclose(native.GetHorizontalApertureOffsetAttr().Get(),(w/2-70)/510.*10)
    assert renderer.sim is sim and set(renderer.cameras)=={'photo_b'}and len(renders)==6
    renderer.close();assert attached==detached==destroyed and first_product in destroyed
    assert scene==before
