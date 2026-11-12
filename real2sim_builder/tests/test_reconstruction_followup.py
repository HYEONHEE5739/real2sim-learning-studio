"""Follow-up contracts: synthetic inputs only; no model or simulator Forward."""
import copy
import numpy as np
import pytest
from real2sim_builder.stage_artifacts import StageNeeds


def validity(**changes):
    return {'validity':'yes','identity_preserved':True,'other_objects_present':False,
        'uncertain':True,'reason':'Hidden back surface cannot be observed',
        'assessment':{'observed_shape_preserved':True,'foreground_valid':True,'measurement_consistent':True,
                      'uncertainties':['HIDDEN_GEOMETRY','UNMEASURED_DIMENSIONS']},**changes}


def test_stage6_hidden_uncertainty_retains_original_answer():
    from real2sim_builder.reconstruction_stages import object_validity_gate
    answer=validity();original=copy.deepcopy(answer)
    result=object_validity_gate(answer,'cup','abc')
    assert result['classification']=='ESTIMATED_CONTINUE'
    assert answer==original and answer['uncertain']is True


@pytest.mark.parametrize('fault',['identity','alpha','shape','measurement','contamination','texture','untyped'])
def test_stage6_bad_or_unclassified_generation_is_object_review(fault):
    from real2sim_builder.reconstruction_stages import object_validity_gate
    answer=validity()
    if fault=='identity':answer['identity_preserved']=False
    elif fault=='contamination':answer['other_objects_present']=True
    elif fault=='texture':answer['assessment']['uncertainties']=['TEXTURE_APPEARANCE']
    elif fault=='untyped':answer.pop('assessment')
    else:answer['assessment'][{'alpha':'foreground_valid','shape':'observed_shape_preserved','measurement':'measurement_consistent'}[fault]]=False
    with pytest.raises(StageNeeds)as error:object_validity_gate(answer,'cup','abc')
    assert error.value.gate['object_ids']==['cup']
    assert error.value.gate['input_sha256']=='abc'


def relation(kind,statement,bindings,measurements,reference=None,quote=None):
    import re
    return {'relation':kind,'statement_quote':statement,'relation_quote':quote or {'cube':'정육면체','cylinder':'지름','axes':'치수','equal_dimensions':'같은 치수','same_product':'같은 제품'}[kind],
        'bindings':[{'object_id':name,'subject_quote':subject}for name,subject in bindings],
        'measurements':[{'field':field,'axis_quote':axis,'value_quote':number+unit,'value':number,'unit':unit,
            'clause_quote':re.search(re.escape(axis)+r'[^0-9]*'+re.escape(number+unit),statement).group()}for field,axis,number,unit in measurements],
        'reference_object_id':reference}


def parse_relations(rows,text):
    import hashlib
    from test_modeling_handoff import semantic_reply
    from real2sim_builder.authoring import parse_scene_analysis
    answer=semantic_reply(rows,text)
    return parse_scene_analysis(answer,{'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()})


def geometry(kind,dims,text,relations):
    return {'kind':kind,'dimensions_m':dims,'source':'user_memo','evidence_quote':text,
        'evidence':[],'wall_m':None,'support':None,'measurement_claims':[],'dimension_relations':relations}


def test_three_colored_cubes_share_explicit_edge_with_each_id_bound():
    text='빨간색, 파란색, 초록색 블록은 각각 한 변이 24mm인 정육면체다.'
    bindings=[('red_block','빨간색'),('blue_block','파란색'),('green_block','초록색')]
    r=relation('cube',text,bindings,[('edge','한 변','24','mm')])
    rows=[{'id':name,'prompt':subject+' 블록','role':'manipulable_object','geometry':geometry('box',[.024]*3,text,[r])}for name,subject in bindings]
    parsed=parse_relations(rows,text)
    assert set(parsed)=={n for n,_ in bindings}
    for obj in parsed.values():
        assert obj['geometry']['dimensions_m']==[.024]*3
        assert obj['geometry']['numeric_evidence_verified']is True
        assert obj['geometry']['dimension_relations']==[r]
        assert obj['geometry']['semantics_verified']is False


def test_cylinder_diameter_height_are_separate_not_copied_to_z():
    text='컵의 지름은 8cm이고 높이는 10cm다.'
    r=relation('cylinder',text,[('cup','컵')],[('diameter','지름','8','cm'),('z','높이','10','cm')])
    rows=[{'id':'cup','prompt':'컵','role':'receptacle','geometry':geometry('container',[.08,.08,.1],text,[r])}]
    parsed=parse_relations(rows,text)['cup']['geometry']
    assert parsed['numeric_evidence_verified']is True and parsed['dimensions_m'][2]==.1
    rows[0]['geometry']['dimensions_m'][2]=.08
    with pytest.raises(ValueError,match='relation|dimension'):parse_relations(rows,text)


@pytest.mark.parametrize('fault',['unit','axis','object','ambiguous','equal_estimate'])
def test_invalid_relation_evidence_never_becomes_measured(fault):
    text='red cube edge 24mm.'
    r=relation('cube',text,[('red','red')],[('edge','edge','24','mm')],quote='cube')
    rows=[{'id':'red','prompt':'red cube','role':'manipulable_object','geometry':geometry('box',[.024]*3,text,[r])}]
    if fault=='unit':r['measurements'][0]['unit']='cm'
    elif fault=='axis':r['measurements'][0]['field']='z'
    elif fault=='object':r['bindings'][0]['object_id']='other'
    elif fault=='ambiguous':rows.append({'id':'red2','prompt':'red cube','role':'manipulable_object','geometry':None})
    else:
        text='red and blue have same dimensions.'
        rows[0]['geometry']=geometry('box',[.024]*3,text,[])
        eq=relation('equal_dimensions',text,[('red','red'),('blue','blue')],[],reference='red',quote='same dimensions')
        rows.append({'id':'blue','prompt':'blue cube','role':'manipulable_object','geometry':geometry('box',[.024]*3,text,[eq])})
    with pytest.raises(ValueError):parse_relations(rows,text)


def world_anchors(scale=2.):
    from scipy.spatial.transform import Rotation
    x=np.array([[0,0,0],[.1,0,0],[0,.1,0],[0,0,.1],[.07,.08,.04]])
    R=Rotation.from_euler('xyz',[.1,.2,.3]).as_matrix();t=np.array([.2,-.3,.04])
    return [{'id':str(i),'group_id':str(i),'split':'validation'if i==4 else'train',
        'support_point':p.tolist(),'robot_world_point_m':(scale*R@p+t).tolist(),
        'source':'measured','evidence':['independent surveyed point correspondence']}for i,p in enumerate(x)]


def test_world_registration_solves_scale_and_rigid_pose_with_independent_holdout(tmp_path):
    from real2sim_builder.reconstruction_stages import resolve_stage_world
    cfg={'sensor_registration':{'world_anchors':world_anchors()}}
    original=copy.deepcopy(cfg)
    registration,report=resolve_stage_world(cfg,True,tmp_path)
    assert registration['provenance']=='estimated'and abs(registration['scale']-2)<1e-10
    assert report['train_rmse_m']<1e-12 and report['holdout_rmse_m']<1e-12
    assert report['independent_accuracy_verified']is False
    assert cfg==original
    assert np.isclose(np.linalg.det(np.asarray(registration['support_to_world'])[:3,:3]),1)


def test_board_size_preserves_scale_but_cannot_determine_robot_base(tmp_path):
    from real2sim_builder.reconstruction_stages import resolve_stage_world
    from real2sim_builder.files import read
    cfg={'metric_anchors':[{'source':'measured','evidence':['caliper and explicit full four corners'],
        'observed_corners_camera_m':[[0,0,1],[.0735,0,1],[.0735,.0755,1],[0,.0755,1]],'dimensions_xy_m':[.147,.151]}]}
    with pytest.raises(StageNeeds)as error:resolve_stage_world(cfg,True,tmp_path)
    assert error.value.code=='ROBOT_WORLD_REQUIRED'
    report=read(tmp_path/'world_resolution.json')
    assert report['robot_world']=='UNRESOLVED'and abs(report['metric_scale_estimate']-2)<1e-12
    assert 'support_to_world'not in report


@pytest.mark.parametrize('fault',['group_leak','point_leak','collinear'])
def test_world_alignment_rejects_leakage_or_unobservable_motion(tmp_path,fault):
    from real2sim_builder.reconstruction_stages import resolve_stage_world
    a=world_anchors()
    if fault=='group_leak':a[-1]['group_id']=a[0]['group_id']
    elif fault=='point_leak':a[-1]['support_point']=a[0]['support_point']
    else:
        for i,r in enumerate(a):r['support_point']=[i*.1,0,0];r['robot_world_point_m']=[i*.2,0,0]
    with pytest.raises((ValueError,StageNeeds)):resolve_stage_world({'sensor_registration':{'world_anchors':a}},True,tmp_path)


def test_joint_sensor_role_uses_metadata_and_reports_holdout_without_render(tmp_path):
    from PIL import Image
    from real2sim_builder.project import Project
    from real2sim_builder.files import write
    from real2sim_builder.observations import register_image,register_views
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.calibration.joint import fit_joint_scene
    from real2sim_builder.calibration.camera import project_point
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'projects','sensor role');truth=legacy_scene()
    truth['cameras'][0]['id']='wrist'  # Deliberately misleading name: fixed Side metadata.
    truth['cameras'][0]['camera_type']='side'
    p.save_scene(truth)
    images=[]
    for i,split in enumerate(['train','validation']):
        f=tmp_path/f'{i}.png';Image.new('RGB',tuple(truth['cameras'][0]['resolution']),(20+i,20,20)).save(f)
        images.append(register_image(p,f,camera='wrist',camera_type='side',scene_state='layout',split=split))
    e=p.evidence;e['landmarks']=[]
    for image in images:
        for x in(-.01,.01):
            for y in(-.01,.01):
                for z in(-.01,.01):
                    row={'observation':image['id'],'object':'block','point_m':[x,y,z]}
                    row['uv']=project_point(truth,truth['cameras'][0],row)[0].tolist();e['landmarks'].append(row)
    write(p.root/'input/evidence.yaml',e)
    c=Candidate.create(p,'joint')
    truth=register_views(c,scene=truth,persist=False)['scene']
    scene=copy.deepcopy(truth);scene['objects'][1]['pose']['provenance']='estimated';scene['objects'][1]['pose']['value'][0][3]+=.01
    fitted,report=fit_joint_scene(p,scene,{'objects':['block'],'cameras':[],'max_nfev':30})
    assert report['status']=='IMPROVED'
    assert report['holdout_after']['count']==8 and report['holdout_after']['rmse_px']<report['holdout_before']['rmse_px']
    assert fitted['cameras']==truth['cameras'] and report['independent_verification']is False


def test_similarity_scales_translation_and_mesh_without_scaling_camera_rotation(tmp_path,monkeypatch):
    from real2sim_builder import reconstruction_stages as stages
    from real2sim_builder.files import read
    from real2sim_builder.candidate import Candidate
    from test_stage_pipeline import synthetic_project
    from test_stage_compilation import FullModels,full_config
    from test_stage_pose import fake_codex_mesh
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);cfg=full_config();cfg['sensor_registration']={'world_anchors':world_anchors()}
    monkeypatch.setattr('real2sim_builder.authoring.run_codex_modeling',fake_codex_mesh)
    r=_run_stage_pipeline(p,candidate='auto',config=cfg,worker=FullModels(),through_stage=10)
    assert r['status']=='STAGES_COMPLETE',r
    data=read(r['stages']['10']['artifact'])['output_manifest']['data'];assert abs(data['world_scale']-2)<1e-10
    scene=Candidate(p,'auto').scene
    assert all(np.isclose(np.linalg.det(np.array(c['pose']['value'])[:3,:3]),1)for c in scene['cameras'])
    ref=np.eye(4);ref[:3,3]=[1,2,3]
    reg,report=stages.resolve_stage_world(cfg,True,tmp_path)
    pose=stages.registered_world_pose(reg,ref);W=np.array(reg['support_to_world'])
    np.testing.assert_allclose(pose[:3,3],W[:3,:3]@[2,4,6]+W[:3,3])


def test_radius_and_length_width_thickness_have_explicit_axes():
    text='cylinder radius 4cm height 10cm.'
    r=relation('cylinder',text,[('cyl','cylinder')],[('radius','radius','4','cm'),('z','height','10','cm')],quote='cylinder')
    parsed=parse_relations([{'id':'cyl','prompt':'cylinder','role':'manipulable_object','geometry':geometry('cylinder',[.08,.08,.1],text,[r])}],text)
    assert parsed['cyl']['geometry']['numeric_evidence_verified']
    text='plate dimensions length 20cm width 10cm thickness 5mm.'
    r=relation('axes',text,[('plate','plate')],[('x','length','20','cm'),('y','width','10','cm'),('z','thickness','5','mm')],quote='dimensions')
    parsed=parse_relations([{'id':'plate','prompt':'plate','role':'manipulable_object','geometry':geometry('box',[.2,.1,.005],text,[r])}],text)
    assert parsed['plate']['geometry']['numeric_evidence_verified']


def test_explicit_same_product_can_derive_only_grounded_dimensions():
    text='red cube edge 24mm. red and blue are same product.'
    r=relation('cube','red cube edge 24mm.',[('red','red')],[('edge','edge','24','mm')],quote='cube')
    eq=relation('same_product','red and blue are same product.',[('red','red'),('blue','blue')],[],reference='red',quote='same product')
    rows=[{'id':name,'prompt':name+' cube','role':'manipulable_object','geometry':geometry('box',[.024]*3,text,relations)}for name,relations in [('blue',[eq]),('red',[r])]]
    parsed=parse_relations(rows,text)
    assert parsed['blue']['geometry']['numeric_evidence_verified']
    assert parsed['blue']['geometry']['derivation']['verified_dimensions']==dict(x=.024,y=.024,z=.024)


def test_stage6_real_prepare_path_keeps_point_provenance_and_uncertainty(tmp_path):
    from test_stage_decomposition import DecompositionModels
    from test_stage_pipeline import synthetic_project
    from real2sim_builder.automation import _run_stage_pipeline
    from real2sim_builder.files import read
    class Models(DecompositionModels):
        def __call__(self,op,req,folder):
            if op=='vlm'and req.get('task')=='object_validity':return {'answer':validity()}
            return super().__call__(op,req,folder)
    cfg={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}},
         'image_preparation':{'size':32,'check_valid':True}}
    result=_run_stage_pipeline(synthetic_project(tmp_path),candidate='prepare',config=cfg,worker=Models(),through_stage=6)
    assert result['status']=='STAGES_COMPLETE',result
    obj=read(result['stages']['6']['artifact'])['output_manifest']['data']['objects'][0]
    assert obj['validity']['uncertain']is True and obj['validity_gate']['classification']=='ESTIMATED_CONTINUE'
    assert obj['enhanced']['depth_frame']=='observed_original_only'
    assert obj['point_provenance']['policy']=='original_only'
    with np.load(obj['original_points'])as a:assert a['camera_points'].shape[0]==a['uv_processed'].shape[0]


def test_metric_support_and_wrist_motion_resolve_base_without_manual_world_pose(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from real2sim_builder import reconstruction_stages as stages,observations
    from real2sim_builder.scene import empty,value
    scene=empty('support gauge');scene['robot_model']={'existing':'identity validated in existing sensor registration'}
    scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated')}
    cfg={'metric_anchors':[{'source':'measured','evidence':['full corners'],
        'observed_corners_camera_m':[[0,0,1],[.1,0,1],[.1,.1,1],[0,.1,1]],'dimensions_xy_m':[.1,.1]}]}
    base=np.eye(4);base[:3,3]=[.2,.3,.4]
    project=SimpleNamespace(root=tmp_path,evidence={'images':[{'id':'wrist1','camera_type':'wrist','capture_manifest':'synthetic.json'}]},checkpoint=lambda:None)
    c=SimpleNamespace(project=project)
    def register(candidate,config,*,scene=None,persist=True,initialize_base=False):
        assert persist is False and initialize_base is True
        assert 'reconstruction_observations'in scene
        return {'scene':scene,'views':[],'needs':[],'status':'REGISTERED_ESTIMATED',
            'diagnostics':[{'camera':'tool_camera','motion':{'status':'OPTIMIZED','rank':13,'scale':1.,'rmse':0.,'T_relative_base':base.tolist(),'T_link_camera':np.eye(4).tolist()}}]}
    monkeypatch.setattr(observations,'register_sensor_views',register)
    registration,draft,report=stages.resolve_sensor_world(c,cfg,scene,{6:{'objects':[]}},tmp_path,{'metric_scale_estimate':1.})
    np.testing.assert_allclose(registration['support_to_world'],np.linalg.inv(base))
    assert registration['provenance']=='estimated'and report['robot_world']=='ESTIMATED'
    assert draft['frames']['robot_base']['transform']['provenance']=='estimated'
    assert scene['frames']['robot_base']['transform']['value']==np.eye(4).tolist()


def test_relative_sensor_initialization_uses_actual_fk_shared_mount_and_train_only(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    from real2sim_builder.project import Project
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.scene import empty,value
    from real2sim_builder.files import sha,write
    from real2sim_builder.observations import register_image,register_sensor_views
    from real2sim_builder.calibration import registration
    from real2sim_builder.calibration.geometry import link_transforms
    p=Project.create(tmp_path/'projects','relative sensor');model=p.root/'input/robot.urdf'
    xml=['<robot name="fixture"><link name="base"/>'];names=[];parent='base'
    for n,axis in enumerate(['0 0 1','0 1 0','1 0 0','0 1 0','1 0 0','0 0 1']):
        link=f'l{n}';name=f'j{n}';names.append(name)
        xml.append(f'<link name="{link}"/><joint name="{name}" type="revolute"><parent link="{parent}"/><child link="{link}"/><origin xyz=".04 .01 .03"/><axis xyz="{axis}"/><limit lower="-2" upper="2" effort="1" velocity="1"/></joint>');parent=link
    model.write_text(''.join(xml)+'</robot>')
    scene=empty('motion');scene['robot_model']={'path':'input/robot.urdf','format':'urdf','model_sha256':sha(model),'joint_names':names,'mapping':{'sha256':'a'*64}}
    scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'calibrated',['protected original World'])}
    scene['frames']['robot_link_l5']={'parent':'robot_base','transform':value(np.eye(4).tolist(),'derived')}
    mount=np.eye(4);mount[:3,3]=[.02,0,.04];base=np.eye(4);base[:3,3]=[.3,.1,.4]
    K=[[30,0,20],[0,30,20],[0,0,1.]]
    scene['cameras']=[{'id':'tool_optics','frame':'robot_link_l5','pose':value(mount.tolist(),'calibrated',['fixture mount']),
        'K':value(K,'calibrated',['fixture K']),'distortion':value([0.]*5,'calibrated'),'resolution':[40,40]}]
    from test_builder_export import legacy_scene
    scene['objects']=legacy_scene()['objects'];p.save_scene(scene)
    rng=np.random.default_rng(8);poses=[];captures=[]
    for n in range(9):
        q=rng.uniform(-.8,.8,6).tolist();fk=link_transforms(model,dict(zip(names,q)))['l5'];poses.append(base@fk@mount)
        f=tmp_path/f'pose{n}.png';Image.new('RGB',(40,40),(n,10,0)).save(f)
        captures.append(register_image(p,f,camera='tool_optics',camera_type='wrist',scene_state='layout',split='validation'if n==8 else'train',joint_record={
            'q_measured':q,'joint_names':names,'joint_units':['rad']*6,'mapping_sha256':'a'*64,'robot_model_sha256':sha(model),'image_timestamp_ns':n*1000,'joint_timestamp_ns':n*1000}))
    f=tmp_path/'photo.png';Image.new('RGB',(40,40),(120,10,0)).save(f)
    photo=register_image(p,f,camera='photo',camera_type='external',scene_state='photo_layout')
    e=p.evidence
    for i in e['images']:
        if i['camera_type']=='wrist':i['capture_manifest']='synthetic-capture.json'
    write(p.root/'input/evidence.yaml',e)
    uv=np.array([[x,y]for x in(5,15,25,35)for y in(5,15,25)],float)
    cloud=p.root/'original_points.npz';np.savez(cloud,uv_original=uv,points_world_m=rng.normal(size=(12,3)))
    scene['reconstruction_observations']={'clouds':[{'image_id':photo['id'],'object_id':'table','path':cloud.name,'sha256':sha(cloud)}]}
    class Features:
        def detectAndCompute(self,*_):return [SimpleNamespace(pt=tuple(x))for x in uv],np.ones((12,128),np.float32)
    class Matcher:
        def knnMatch(self,*a,**kw):return [[SimpleNamespace(queryIdx=n,trainIdx=n,distance=1),SimpleNamespace(distance=10)]for n in range(12)]
    monkeypatch.setattr('real2sim_builder.observations.cv2.SIFT_create',lambda **kw:Features())
    monkeypatch.setattr('real2sim_builder.observations.cv2.BFMatcher',Matcher)
    calls=[]
    def pnp(*a,**kw):
        index=len(calls)%8;calls.append(index)
        return {'status':'ESTIMATED','T_world_camera':poses[index].tolist(),'K':K,'distortion':[0.]*5,'rmse_px':0}
    monkeypatch.setattr(registration,'camera_from_correspondences',pnp)
    original=copy.deepcopy(p.evidence);c=Candidate.create(p,'draft')
    result=register_sensor_views(c,{'capture_layouts':[{'scene_state_id':'layout','status':'SAME_LAYOUT'}]},scene=scene,persist=False,initialize_base=True)
    motion=result['diagnostics'][0]['motion']
    assert motion['rank']==13 and len(calls)==16  # 8 seeds + 8 train poses; holdout excluded.
    np.testing.assert_allclose(motion['T_relative_base'],base,atol=1e-6)
    np.testing.assert_allclose(motion['T_link_camera'],mount,atol=1e-6)
    assert result['scene']['cameras']==scene['cameras']
    assert result['scene']['frames']['robot_base']==scene['frames']['robot_base']
    assert len(result['views'])==9 and p.evidence==original


def test_korean_subject_fragment_and_unbound_second_size_are_not_measurements():
    text='컵받침의 지름은 8cm다.'
    r=relation('cylinder',text,[('cup','컵')],[('diameter','지름','8','cm')])
    rows=[{'id':'cup','prompt':'컵','role':'receptacle','geometry':geometry('container',[.08,.08,None],text,[r])}]
    with pytest.raises(ValueError,match='subject'):parse_relations(rows,text)
    text='red cube edge 24mm and blue cube edge 30mm.'
    r=relation('cube',text,[('red','red'),('blue','blue')],[('edge','edge','24','mm')],quote='cube')
    rows=[{'id':name,'prompt':name+' cube','role':'manipulable_object','geometry':geometry('box',[.024]*3,text,[r])}for name in('red','blue')]
    with pytest.raises(ValueError,match='numeric'):parse_relations(rows,text)


def test_derived_memo_size_cannot_override_existing_measured_asset(tmp_path):
    from real2sim_builder.authoring import geometry_specs
    from real2sim_builder.scene import empty
    from real2sim_builder.initialization import measured_geometry
    text='red cube edge 24mm.'
    r=relation('cube',text,[('red','red')],[('edge','edge','24','mm')],quote='cube')
    parsed=parse_relations([{'id':'red','prompt':'red cube','role':'manipulable_object','geometry':geometry('box',[.024]*3,text,[r])}],text)
    original=measured_geometry(empty('protected'),[{'id':'red','kind':'box','dimensions_m':[.03]*3,'evidence':['existing caliper measurement']}])
    before=copy.deepcopy(original)
    with pytest.raises(ValueError,match='conflict|locked'):geometry_specs({'objects':parsed},original)
    assert original==before
