"""Gate policy regressions: synthetic arrays and fake workers only, no models."""
from pathlib import Path
import copy
import numpy as np
import pytest
from PIL import Image
from real2sim_builder.files import read, write, sha
from real2sim_builder.stage_artifacts import StageNeeds
from test_stage_pipeline import synthetic_project
from test_stage_decomposition import DecompositionModels


def stage_config():
    return {'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}}}


def assessment(**changes):
    return {'identity':'IDENTIFIED','box':'ASSOCIATED','memo':'CONSISTENT',
            'uncertainties':['HIDDEN_GEOMETRY','UNMEASURED_DIMENSIONS','FRONT'],**changes}


class ScopedModels(DecompositionModels):
    def __init__(self,identity='IDENTIFIED'):
        super().__init__();self.identity=identity
    def __call__(self,op,req,folder):
        response=super().__call__(op,req,folder)
        if op=='vlm'and req.get('task')=='scene_instances':
            response['answer'].update(uncertain=bool(response['answer']['objects']),memo_consistent=True)
            for obj in response['answer']['objects']:obj['assessment']=assessment(identity=self.identity)
        return response


def test_hidden_geometry_uncertainty_preserves_draft_and_provenance(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);w=ScopedModels()
    r=_run_stage_pipeline(p,candidate='test',config=stage_config(),worker=w,through_stage=5)
    assert r['status']=='STAGES_COMPLETE'
    data=read(r['stages']['5']['artifact'])['output_manifest']['data']
    assert data['objects'][0]['assessment']['uncertainties']
    with np.load(data['objects'][0]['observed'])as a:
        assert a['rgb_source'].shape==a['mask'].shape
        assert not a['rgb_source'][a['mask']].any()
        assert not a['depth_source'][a['mask']].any()


def test_ambiguous_identity_is_not_segmented_or_removed(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);w=ScopedModels('AMBIGUOUS')
    r=_run_stage_pipeline(p,candidate='test',config=stage_config(),worker=w,through_stage=5)
    assert r['status']=='NEEDS_REVIEW'
    assert 'segments'not in w.calls and 'image_edit'not in w.calls
    assert r['gate']['classification']=='OBJECT_REVIEW'
    assert r['gate']['object_ids']==['block']


def test_quality_rejection_retries_and_resume_never_uses_rejected_rgb(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    class QualityModels(DecompositionModels):
        def __init__(self):super().__init__();self.edits=0;self.reviews=0
        def __call__(self,op,req,folder):
            if op=='vlm'and req.get('task')=='removal_validity':
                self.reviews+=1
                return {'answer':{'removed':'yes'if self.reviews>1 else'no','object_remaining':'no'if self.reviews>1 else'yes',
                    'other_objects_preserved':'yes','background_continuous':'yes','uncertain':False,'reason':'synthetic pixel review','evidence':['target region']}}
            result=super().__call__(op,req,folder)
            if op=='image_edit':
                self.edits+=1;result.update(provider='comfy_gguf',raw_path=result['path'])
                # Change only the declared allowed region; green annotation is absent.
                rgb=np.asarray(Image.open(req['original_image']).convert('RGB')).copy();region=np.asarray(Image.open(req['mask']))>0
                rgb[region]=90 if self.edits==1 else 100;Image.fromarray(rgb).save(result['path'])
            return result
    p=synthetic_project(tmp_path);w=QualityModels();w.fail='depth_inpaint'
    first=_run_stage_pipeline(p,candidate='test',config=stage_config(),worker=w,through_stage=5)
    assert first['status']=='NEEDS_RUNTIME'and w.edits==2 and w.reviews==2
    w.fail=None
    final=_run_stage_pipeline(p,candidate='test',config=stage_config(),worker=w,through_stage=5)
    assert final['status']=='STAGES_COMPLETE'and w.edits==2 and w.reviews==2
    data=read(final['stages']['5']['artifact'])['output_manifest']['data']
    attempts=data['removal_history'][0]['removal_attempts']
    assert attempts[0]['accepted']is False and attempts[1]['accepted']is True
    assert len({a['review_folder']for a in attempts})==2


def test_cpd_point_selection_excludes_synthesized_and_low_confidence_by_default(tmp_path):
    from real2sim_builder.reconstruction_stages import pose_point_selection
    shape=(4,5);mask=np.ones(shape,bool);points=np.arange(60).reshape(20,3)/100
    a={'mask':mask,'camera_points':points,'rgb_source':np.zeros(shape,np.uint8),'depth_source':np.zeros(shape,np.uint8),'low_confidence':np.zeros(shape,bool)}
    a['rgb_source'][0,0]=1;a['depth_source'][0,1]=1;a['low_confidence'][0,2]=True
    selected,report=pose_point_selection(a,{})
    assert np.array_equal(selected,points[3:]) and report['generated_points']==2 and report['low_confidence_points']==1
    allpoints,explicit=pose_point_selection(a,{'point_policy':'include_generated','generated_evidence':['sensitivity experiment']})
    assert len(allpoints)==19 and explicit['sensitivity_required']is True
    with pytest.raises(ValueError):pose_point_selection(a,{'point_policy':'include_generated'})


def test_cpd_quality_reports_degeneracy_and_symmetry_without_accuracy_claim():
    from real2sim_builder.calibration.registration import pose_fit_quality
    cube=np.array([[x,y,z]for x in(-1,1)for y in(-1,1)for z in(-1,1)],float)
    candidates=[{'rotation':np.eye(3).tolist(),'translation':[0,0,0],'scale':1,'score':0},
                {'rotation':np.diag([-1,-1,1]).tolist(),'translation':[0,0,0],'scale':1,'score':0}]
    q=pose_fit_quality(cube,cube,voxel_m=.1,candidates=candidates)
    assert q['symmetric_chamfer_rmse_m']==0 and q['observed_coverage']==1 and q['candidate_score_gap']==0
    assert q['pose_ambiguity']=='CANDIDATE_TIE'and q['accuracy_verified']is False
    line=np.c_[np.arange(10),np.zeros((10,2))]
    assert pose_fit_quality(line,line,voxel_m=.1)['degenerate']is True


def dimension_reply(text,claims=None,dimensions=None):
    from test_modeling_handoff import semantic_reply
    geometry={'kind':'container','dimensions_m':dimensions or[None,None,.1],'source':'user_memo',
        'evidence_quote':text,'evidence':[],'wall_m':None,'support':None}
    if claims is not None:geometry['measurement_claims']=claims
    return semantic_reply([{'id':'cup','prompt':'cup','role':'receptacle','geometry':geometry}],text)


def claim(unit='mm',value='100',**kw):
    return {'field':'z','object_id':'cup','subject_quote':'cup','axis_quote':'height',
            'statement_quote':'cup height '+value+unit,'value_quote':value+unit,'value':value,'unit':unit,**kw}


@pytest.mark.parametrize('unit,value',[('mm','100'),('cm','10'),('m','0.1')])
def test_memo_numeric_witness_units_are_verified_before_measured(unit,value):
    import hashlib
    from real2sim_builder.authoring import parse_scene_analysis
    text='cup height '+value+unit;memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    parsed=parse_scene_analysis(dimension_reply(text,[claim(unit,value)]),memo)
    assert parsed['cup']['geometry']['provenance']=='measured'
    assert parsed['cup']['geometry']['numeric_evidence_verified']is True


@pytest.mark.parametrize('change',[{'value':'1000'},{'field':'x'},{'object_id':'other'},{'subject_quote':'other'},{'axis_quote':'width'}])
def test_memo_bad_numeric_subject_or_axis_claim_never_becomes_measured(change):
    import hashlib
    from real2sim_builder.authoring import parse_scene_analysis
    text='cup height 100mm; other width 200mm';memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    with pytest.raises(ValueError):parse_scene_analysis(dimension_reply(text,[claim(**change)]),memo)


def test_legacy_quote_only_geometry_is_not_promoted_to_measured():
    import hashlib
    from real2sim_builder.authoring import parse_scene_analysis
    text='cup height 100mm';memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    parsed=parse_scene_analysis(dimension_reply(text),memo)
    assert parsed['cup']['geometry']['provenance']=='estimated'
    assert parsed['cup']['geometry']['measurement_review']=='UNVERIFIED_NUMERIC_EVIDENCE'


def test_failed_removal_preserves_every_observation_and_blocks_dependencies(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    class TwoObjects(DecompositionModels):
        def __call__(self,op,req,folder):
            if op=='vlm':return {'answer':{'objects':[{'id':n,'prompt':n,'role':'manipulable_object','box_xyxy':box}for n,box in [('block',[12,12,20,20]),('other',[22,12,28,20])]]}}
            if op=='segments':
                folder.mkdir(parents=True,exist_ok=True);rows=[]
                for n,x in [('block',12),('other',22)]:
                    m=np.zeros((32,32),np.uint8);m[12:20,x:x+6]=255;file=folder/(n+'.png');Image.fromarray(m).save(file);rows.append({'id':n,'path':str(file),'status':'UNIQUE_ESTIMATED'})
                return {'objects':rows}
            if op=='removal':return {'order':['block','other']}
            if op=='image_edit':
                folder.mkdir(parents=True,exist_ok=True);file=folder/'green.png';Image.new('RGB',(32,32),(0,255,0)).save(file);return {'path':str(file)}
            return super().__call__(op,req,folder)
    p=synthetic_project(tmp_path);w=TwoObjects();cfg=stage_config();cfg['decomposition']={'removal_attempts':1,'removal_prompt_order':['mask']}
    r=_run_stage_pipeline(p,candidate='test',config=cfg,worker=w,through_stage=5)
    assert r['gate']['object_ids']==['block']and r['gate']['dependencies']==['other']
    failure=Path(r['failure_artifact']).parent;progress=next((failure/'partial').rglob('object_progress.json'));data=read(progress)
    assert data['objects']['other']['status']=='OBSERVATION_READY'
    assert Path(data['objects']['other']['observed']).is_file()
    assert 'depth_inpaint'not in w.calls


def test_sensor_hook_requires_independent_metric_anchor_before_registration(tmp_path):
    from types import SimpleNamespace
    from real2sim_builder.reconstruction_stages import register_stage_sensors
    p=SimpleNamespace(evidence={'images':[{'id':'capture','capture_manifest':'capture.json','camera_type':'wrist'}]})
    c=SimpleNamespace(project=p);scene={'robot_model':{'id':'existing'},'cameras':[]}
    with pytest.raises(StageNeeds,match='Metric Anchor')as error:
        register_stage_sensors(c,{'world_registration':{'provenance':'measured','evidence':['survey'],'support_to_world':np.eye(4).tolist()}},scene,{},tmp_path)
    assert error.value.gate['classification']=='DEPENDENCY_BLOCK'
    assert scene=={'robot_model':{'id':'existing'},'cameras':[]}


def test_sensor_hook_reuses_existing_registration_without_publishing_partial_scene(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from real2sim_builder import observations
    from real2sim_builder.reconstruction_stages import register_stage_sensors
    from real2sim_builder.stage_artifacts import digest
    from real2sim_builder.scene import empty
    image={'id':'capture','capture_manifest':'capture.json','camera_type':'side'}
    project=SimpleNamespace(evidence={'images':[image]},root=tmp_path)
    c=SimpleNamespace(project=project);scene=empty('sensor');scene['robot_model']={'id':'model'}
    anchors=[{'source':'measured','evidence':['caliper'],'observed_corners_camera_m':[[0,0,1],[.147,0,1],[.147,.151,1],[0,.151,1]],'dimensions_xy_m':[.147,.151]}]
    cfg={'world_registration':{'provenance':'measured','evidence':['survey'],'support_to_world':np.eye(4).tolist()},'metric_anchors':anchors,
         'sensor_registration':{'metric_review':{'accepted':True,'anchors_sha256':digest(anchors),'evidence':['independent scale check']}}}
    def register(candidate,config,*,scene=None,persist=True):
        assert persist is False;assert scene['reconstruction_observations']['clouds']==[]
        return {'status':'REGISTERED_ESTIMATED','views':[{'image_id':'capture'}],'needs':[],'scene':copy.deepcopy(scene)}
    monkeypatch.setattr(observations,'register_sensor_views',register)
    result,report=register_stage_sensors(c,cfg,scene,{6:{'objects':[]}},tmp_path)
    assert report['status']=='REGISTERED_ESTIMATED'and report['physical_verified']is False
    assert 'reconstruction_observations'in result and 'reconstruction_observations'not in scene


def test_actual_sensor_registration_can_be_prepared_without_saving_candidate(tmp_path):
    from real2sim_builder.project import Project
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.observations import register_image,register_sensor_views
    from real2sim_builder.scene import value
    p=Project.create(tmp_path/'projects','transactional sensor')
    file=tmp_path/'side.png';Image.new('RGB',(32,32),'gray').save(file)
    row=register_image(p,file,camera='sensor',camera_type='side',scene_state='layout')
    evidence=p.evidence;next(i for i in evidence['images']if i['id']==row['id'])['capture_manifest']='synthetic_capture.json';write(p.root/'input/evidence.yaml',evidence)
    c=Candidate.create(p,'test');scene=c.scene
    scene['cameras']=[{'id':'sensor','frame':'world','resolution':[32,32],
        'pose':value(np.eye(4).tolist(),'calibrated',['synthetic calibration']),
        'K':value([[30.,0,16],[0,30.,16],[0,0,1]],'calibrated',['synthetic calibration']),
        'distortion':value([0.]*5,'calibrated',['synthetic calibration'])}]
    c.save(scene);before=sha(c.root/'candidate_scene.yaml');input_before=sha(p.root/'input/evidence.yaml')
    result=register_sensor_views(c,{},scene=scene,persist=False)
    assert result['views'][0]['image_id']==row['id']
    assert result['scene']['view_registrations'] and not c.scene.get('view_registrations')
    assert sha(c.root/'candidate_scene.yaml')==before and sha(p.root/'input/evidence.yaml')==input_before
    assert not(c.root/'sensor-registration.json').exists()


def test_pose_review_keeps_independent_success_and_never_passes_degenerate_fit(tmp_path):
    from types import SimpleNamespace
    from real2sim_builder.reconstruction_stages import poses
    c=SimpleNamespace(project=SimpleNamespace(checkpoint=lambda:None))
    objects=[{'id':n,'mesh':'synthetic.obj','camera_points':'synthetic.npy','scale_protected':False}for n in ['bad','good']]
    def worker(op,request,folder):
        assert op=='cpd'
        return {'rotation':np.eye(3).tolist(),'translation':[0,0,1],'scale':1.,'quality':{'degenerate':folder.name=='bad','accuracy_verified':False}}
    with pytest.raises(StageNeeds)as caught:
        poses(c,{'pose':{'canonicalize_front':False}},{7:{'objects':objects},4:{'camera_to_support':np.eye(4).tolist()}},tmp_path,worker)
    assert caught.value.gate['object_ids']==['bad']
    retained=read(tmp_path/'object_progress.json');assert retained['objects'][0]['id']=='good'
    assert retained['objects'][0]['status']=='UNVERIFIED'


def test_generated_context_remains_marked_after_multiple_removals(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    class Revealed(DecompositionModels):
        def __call__(self,op,req,folder):
            if op=='vlm':
                self.identifications+=1
                names=['block','hidden']if self.identifications==1 else[]
                return {'answer':{'objects':[{'id':n,'prompt':n,'role':'manipulable_object','box_xyxy':[12,12,20,20]}for n in names]}}
            if op=='segments':
                folder.mkdir(parents=True,exist_ok=True);mask=np.zeros((32,32),np.uint8);mask[12:20,12:20]=255;file=folder/'mask.png';Image.fromarray(mask).save(file)
                return {'objects':[{'id':o['id'],'path':str(file),'status':'UNIQUE_ESTIMATED'}for o in req['objects']]}
            if op=='removal':return {'order':[o['id']for o in req['objects']]}
            return super().__call__(op,req,folder)
    p=synthetic_project(tmp_path);cfg=stage_config();cfg['decomposition']={'min_valid_pixel_prop':0.}
    # Use the same flat observed color so the original source's color-agreement
    # check passes; provenance must still identify generated pixels exactly.
    w=Revealed();r=_run_stage_pipeline(p,candidate='test',config=cfg,worker=w,through_stage=5)
    # The existing photometric gate may reject the fully hidden second mask.
    # Its snapshot is retained before the gate and must never masquerade as original.
    roots=Path(r.get('failure_artifact',r['stages'].get('5',{}).get('artifact',''))).parent
    files=[p for p in roots.rglob('hidden_observed.npz')if p.parent.name=='iteration_001']
    assert files
    with np.load(files[-1])as a:
        generated=(a['depth_source']>0)&a['mask']
        assert generated.any()
        from real2sim_builder.reconstruction_stages import pose_point_selection
        points,counts=pose_point_selection(a,{})
        assert len(points)==0 and counts['generated_points']==int(a['mask'].sum())


def test_robot_compilation_still_blocks_without_metric_anchor_even_with_transform(tmp_path,monkeypatch):
    from real2sim_builder.project import Project
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.reconstruction_stages import compile_scene
    p=Project.create(tmp_path/'projects','anchor required');c=Candidate.create(p,'test');scene=c.scene
    scene['robot_model']={'sentinel':'existing Robot Model'}
    monkeypatch.setattr(Candidate,'scene',property(lambda _:copy.deepcopy(scene)))
    before=copy.deepcopy(scene)
    cfg={'world_registration':{'support_to_world':np.eye(4).tolist(),'provenance':'measured','evidence':['transform alone']}}
    with pytest.raises(StageNeeds,match='Metric Anchor'):
        compile_scene(c,cfg,{},tmp_path,None)
    assert scene==before


def test_cpd_worker_quality_serializes_candidate_fits_with_stub_solver(tmp_path,monkeypatch):
    """Only geometry plumbing: no Open3D/probreg runtime or real CPD execution."""
    import sys,json
    from types import SimpleNamespace
    from real2sim_builder.stage_workers import cpd
    points=np.array([[x,y,z]for x in(-1,1)for y in(-1,1)for z in(-1,1)]*2,dtype=float)
    class Cloud:
        def __init__(self):self.points=points.copy()
        def get_oriented_bounding_box(self):return SimpleNamespace(extent=np.ptp(self.points,axis=0))
        def scale(self,s,center):self.points=self.points*s;return self
        def voxel_down_sample(self,v):return self
        def farthest_point_down_sample(self,num_samples):return self
        def remove_non_finite_points(self):return self
    mesh=SimpleNamespace(is_empty=lambda:False,sample_points_poisson_disk=lambda number_of_points:Cloud())
    o3d=SimpleNamespace(geometry=SimpleNamespace(PointCloud=Cloud),utility=SimpleNamespace(Vector3dVector=np.asarray),io=SimpleNamespace(read_triangle_mesh=lambda *a,**k:mesh))
    def solver(*a,**kw):return SimpleNamespace(rot=np.eye(3),t=np.zeros(3),scale=1.,transform=lambda x:np.asarray(x)),None,None
    monkeypatch.setitem(sys.modules,'open3d',o3d)
    monkeypatch.setitem(sys.modules,'probreg',SimpleNamespace(cpd=SimpleNamespace(registration_cpd=solver)))
    file=tmp_path/'points.npy';np.save(file,points)
    result=cpd({'mesh':'not_read.obj','points':str(file),'samples':1,'surface_samples':16,'scale_protected':True,'output':str(tmp_path)})
    assert result['quality']['accuracy_verified']is False
    assert len(result['candidate_fits'])==1 and 'candidate_fits'not in result['candidate_fits'][0]
    assert json.loads((tmp_path/'fit.json').read_text())['status']=='UNVERIFIED'


def test_runtime_failure_is_not_retried_as_generation_quality(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    w=DecompositionModels();w.fail='image_edit';p=synthetic_project(tmp_path)
    r=_run_stage_pipeline(p,candidate='test',config=stage_config(),worker=w,through_stage=5)
    assert r['status']=='NEEDS_RUNTIME' and w.calls.count('image_edit')==1
    assert 'depth_inpaint'not in w.calls


def test_same_memo_subject_cannot_transfer_different_numbers_between_instances():
    import hashlib
    from real2sim_builder.authoring import parse_scene_analysis
    text='cup height 100mm. cup height 200mm.';memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    a=dimension_reply(text,[claim(statement_quote='cup height 100mm.')])
    b=copy.deepcopy(a['objects'][0]);b['id']='cup_other';b['geometry']['dimensions_m'][2]=.2
    b['geometry']['measurement_claims']=[claim(value='200',value_quote='200mm',object_id='cup_other',statement_quote='cup height 200mm.')]
    a['objects'].append(b)
    with pytest.raises(ValueError,match='subject'):parse_scene_analysis(a,memo)


def test_legacy_unscoped_uncertainty_and_memo_conflict_remain_blocked():
    from real2sim_builder.reconstruction_stages import instance_gate
    row={'id':'cup','uncertainty':'unknown'}
    for answer in [{'objects':[row],'uncertain':True,'memo_consistent':True},
                   {'objects':[{**row,'assessment':assessment()}],'uncertain':True,'memo_consistent':False},
                   {'objects':[{**row,'assessment':assessment(box='AMBIGUOUS')}],'uncertain':False,'memo_consistent':True}]:
        with pytest.raises(StageNeeds):instance_gate(answer,'0'*64)


def test_unrecorded_point_provenance_is_not_silently_called_original():
    from real2sim_builder.reconstruction_stages import pose_point_selection
    with pytest.raises(StageNeeds,match='NOT_RECORDED'):
        pose_point_selection({'mask':np.ones((4,4),bool),'camera_points':np.ones((16,3))},{})


def test_unknown_memo_details_without_contradiction_do_not_discard_known_instance():
    from real2sim_builder.reconstruction_stages import instance_gate
    answer={'objects':[{'id':'cup','assessment':assessment(memo='UNKNOWN')}], 'uncertain':True,'memo_consistent':True}
    result=instance_gate(answer,'0'*64)
    assert result[0]['classification']=='ESTIMATED_CONTINUE'


def test_korean_literal_scalar_with_explicit_subject_and_axis_is_checked():
    import hashlib
    from real2sim_builder.authoring import parse_scene_analysis
    text='컵 높이는 100mm야.';memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    reply=dimension_reply(text,[claim(subject_quote='컵',axis_quote='높이',statement_quote=text)])
    reply['objects'][0]['prompt']='컵'
    assert parse_scene_analysis(reply,memo)['cup']['geometry']['numeric_evidence_verified']is True


def test_failed_stage_worker_cache_cannot_substitute_data_for_verified_response(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);w=DecompositionModels();w.fail='depth_inpaint'
    first=_run_stage_pipeline(p,candidate='test',config=stage_config(),worker=w,through_stage=5)
    assert first['status']=='NEEDS_RUNTIME'
    pending=Path(read(p.root/'scratch/agent/test/reconstruction/simfoundry/cache.json')['5']['pending'])
    cache=pending/'iteration_000/vlm/worker-cache.json';record=read(cache)
    record['data']['answer']['objects']=[];write(cache,record)
    before=list(w.calls);w.fail=None
    with pytest.raises(ValueError,match='response integrity'):
        _run_stage_pipeline(p,candidate='test',config=stage_config(),worker=w,through_stage=5)
    assert w.calls==before


def test_owned_worker_group_is_cleaned_even_when_leader_exits_first(tmp_path):
    import os,sys,time,signal,psutil
    from types import SimpleNamespace
    from real2sim_builder.inference import _run_worker
    from real2sim_builder import stage_workers
    file=tmp_path/'descendant.txt';wrapper=tmp_path/'wrapper'
    wrapper.write_text('#!'+sys.executable+'\nimport subprocess,sys\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"])\nPath('+repr(str(file))+').write_text(str(p.pid))\n')
    wrapper.chmod(0o700);pid=None
    try:
        _run_worker(SimpleNamespace(checkpoint=lambda:None),wrapper,'cpd',{},tmp_path/'worker',3,entrypoint=Path(stage_workers.__file__))
        pid=int(file.read_text());deadline=time.monotonic()+1
        while time.monotonic()<deadline:
            try:
                if psutil.Process(pid).status()==psutil.STATUS_ZOMBIE:break
            except psutil.NoSuchProcess:break
            time.sleep(.01)
        else:pytest.fail('Owned descendant survived successful leader exit')
    finally:
        if pid is None and file.exists():pid=int(file.read_text())
        if pid is not None:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass


def test_generated_fit_keeps_original_only_sensitivity_comparison(tmp_path):
    from types import SimpleNamespace
    from real2sim_builder.reconstruction_stages import poses
    points=np.array([[x,y,z]for x in(-1,1)for y in(-1,1)for z in(-1,1)]*2,float)
    primary=tmp_path/'selected.npy';np.save(primary,points)
    original=tmp_path/'original.npz';np.savez(original,camera_points=points)
    obj={'id':'cup','mesh':'not_read.obj','camera_points':str(primary),'original_points':str(original),'scale_protected':False,
         'point_provenance':{'selected_points':len(points),'sensitivity_required':True}}
    calls=[]
    def worker(op,request,folder):
        assert op=='cpd';calls.append(folder.name)
        return {'rotation':np.eye(3).tolist(),'translation':[0 if folder.name=='original_only'else .1,0,1.], 'scale':1.}
    c=SimpleNamespace(project=SimpleNamespace(checkpoint=lambda:None))
    result=poses(c,{'pose':{'canonicalize_front':False}}, {7:{'objects':[obj]},4:{'camera_to_support':np.eye(4).tolist()}},tmp_path,worker)
    fit=result['objects'][0]['fit']
    assert calls==['cup','original_only']
    assert fit['generated_sensitivity']['translation_delta_m']==pytest.approx(.1)
    assert fit['generated_sensitivity']['accuracy_verified']is False
    assert result['accuracy']=='NOT_VERIFIED'


def test_cached_sensor_stage_cannot_hide_changed_capture_rgb(tmp_path,monkeypatch):
    from real2sim_builder import reconstruction_stages as stages
    from real2sim_builder.automation import _run_stage_pipeline
    from real2sim_builder.observations import register_image
    from test_stage_pipeline import MockModels
    p=synthetic_project(tmp_path);file=tmp_path/'sensor.png';Image.new('RGB',(32,32),'blue').save(file)
    sensor=register_image(p,file,camera='sensor',camera_type='side',scene_state='layout')
    # Only Stage1-4 math is real here. Later handlers are explicitly inert;
    # this checks the orchestrator's cache boundary, not a Stage1-14 E2E.
    for name in ['decompose','prepare_objects','meshes','poses','articulate','compile_scene']:
        monkeypatch.setattr(stages,name,lambda *a,**kw:{'coordinate_frame':'synthetic cache fixture'})
    w=MockModels();r=_run_stage_pipeline(p,candidate='test',config=stage_config(),worker=w,through_stage=10)
    assert r['status']=='STAGES_COMPLETE';calls=list(w.calls)
    Image.new('RGB',(32,32),'green').save(p.root/sensor['path'])
    with pytest.raises(ValueError,match='SHA'):
        _run_stage_pipeline(p,candidate='test',config=stage_config(),worker=w,through_stage=10)
    assert w.calls==calls


@pytest.mark.parametrize('text,witness,dimensions',[
    ('othercup height 100mm',claim(statement_quote='othercup height 100mm'),[None,None,.1]),
    ('cup box 100mm',claim(field='x',axis_quote='x',statement_quote='cup box 100mm'),[.1,None,None]),
])
def test_measurement_labels_cannot_be_substrings_of_other_subjects_or_words(text,witness,dimensions):
    import hashlib
    from real2sim_builder.authoring import parse_scene_analysis
    memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
    with pytest.raises(ValueError,match='subject/axis'):
        parse_scene_analysis(dimension_reply(text,[witness],dimensions),memo)
