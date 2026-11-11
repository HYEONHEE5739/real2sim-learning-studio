import numpy as np
import pytest
from PIL import Image
from real2sim_builder.files import read, write, sha
from real2sim_builder.project import Project
from real2sim_builder.observations import register_image
from real2sim_builder.candidate import Candidate


def synthetic_project(tmp_path):
    p=Project.create(tmp_path/'projects','Synthetic stages')
    for i in range(4):
        rgb=np.full((32,32,3),100,np.uint8);rgb[12:20,12:20]=[220,20,20]
        path=tmp_path/f'photo{i}.png';Image.fromarray(rgb).save(path)
        register_image(p,path,camera=f'view_{i}',camera_type='external',scene_state='layout')
    path=tmp_path/'reference.png';Image.new('RGB',(32,32),'blue').save(path)
    register_image(p,path,camera='body_reference',camera_type='external',scene_state='layout',role='model_reference')
    return p


class MockModels:
    runtime_identity={'kind':'mock','version':'fixture-v1'}
    def __init__(self):self.calls=[];self.fail=None
    def __call__(self,operation,request,folder):
        from real2sim_builder.stage_artifacts import StageNeeds
        self.calls.append(operation)
        if self.fail==operation:raise StageNeeds('NEEDS_RUNTIME','Mock runtime missing')
        folder.mkdir(parents=True,exist_ok=True)
        if operation=='da3':
            assert len(request['images'])==4
            assert all('reference'not in x for x in request['frame_ids'])
            images=np.array([np.asarray(Image.open(p))for p in request['images']]);n,h,w=images.shape[:3]
            depth=np.ones((n,h,w));depth[:,12:20,12:20]=.9
            K=np.tile([[32.,0,16],[0,32,16],[0,0,1]],(n,1,1));E=np.tile(np.c_[np.eye(3),np.zeros(3)],(n,1,1))
            path=folder/'prediction.npz';np.savez(path,depth=depth,conf=np.ones_like(depth),image=images,intrinsics=K,extrinsics=E)
            return {'path':str(path),'is_metric':1,'model_scale_factor':1,'original_to_processed':np.tile(np.eye(3),(n,1,1)).tolist()}
        if operation=='support':
            with np.load(request['prediction'])as a:masks=a['depth']==1
            records=[]
            for m in masks:
                fit={'coefficients':[0,0,-1,1],'origin':[0,0,1],'inliers':list(range(int(m.sum())))}
                records.append({'eligible':True,'category':'table','score':.9,'selection':fit,'final':fit})
            path=folder/'masks.npz';np.savez(path,masks=masks);return {'path':str(path),'planes':records}
        raise AssertionError('Unexpected heavy worker '+operation)


def test_real_first_four_stages_cache_and_role_boundaries(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);before=sha(p.root/'input/evidence.yaml');worker=MockModels()
    config={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}}}
    result=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=4)
    assert result['status']=='STAGES_COMPLETE'
    assert worker.calls==['da3','support']
    assert sha(p.root/'input/evidence.yaml')==before
    c=Candidate(p,'test');a=read(result['stages']['4']['artifact'])
    assert a['provenance']['execution']=='mock'
    assert a['output_manifest']['data']['robot_world_registered']is False
    resumed=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=4)
    assert all(s['reused']for s in resumed['stages'].values())
    assert worker.calls==['da3','support']


def test_missing_worker_preserves_previous_stage_and_resumes(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);worker=MockModels();worker.fail='support'
    config={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}}}
    result=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=4)
    assert result['status']=='NEEDS_RUNTIME'and result['failed_stage']==3
    stage2=Path(result['stages']['2']['artifact'])
    before=sha(stage2);worker.fail=None
    result=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=4)
    assert result['status']=='STAGES_COMPLETE'and sha(stage2)==before
    assert worker.calls.count('da3')==1


def test_corrupted_depth_blocks_resume_before_any_next_worker(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);worker=MockModels()
    config={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}}}
    result=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=2)
    artifact=read(result['stages']['2']['artifact']);Path(artifact['output_manifest']['data']['prediction']).write_bytes(b'corrupt')
    with pytest.raises(ValueError,match='integrity'):
        _run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=4)
    assert worker.calls==['da3']


def test_stop_before_stage_keeps_completed_checkpoint(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);worker=MockModels()
    config={'scene_state_id':'layout'}
    first=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=1)
    p.control('stop')
    result=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=2)
    assert result['status']=='STOPPED'and not worker.calls
    assert first['stages']['1']['artifact']==result['stages']['1']['artifact']


def test_new_model_reference_or_memo_does_not_regenerate_phone_depth(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    from real2sim_builder.evidence import save_scene_memo
    p=synthetic_project(tmp_path);worker=MockModels();config={'scene_state_id':'layout'}
    _run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=2)
    file=tmp_path/'new_model.png';Image.new('RGB',(24,24),'yellow').save(file)
    register_image(p,file,camera='body_detail',camera_type='external',scene_state='layout',role='model_reference')
    save_scene_memo(p,'Additional model appearance instructions')
    r=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=2)
    assert all(s['reused']for s in r['stages'].values())
    assert worker.calls==['da3']


from pathlib import Path
