from pathlib import Path

import numpy as np
import pytest

from real2sim_builder.adaptive_geometry import build_plan, create_asset
from real2sim_builder.automation import _run_stage_pipeline
from real2sim_builder.evidence_dashboard import generate
from real2sim_builder.files import read, sha
from test_stage_compilation import FullModels, full_config
from test_stage_pipeline import synthetic_project


def measured(kind, dims, **extras):
    return {'kind':kind,'dimensions_m':dims,'evidence':['test measurement'],'provenance':'measured',**extras}


def test_direct_dispatch_to_registered_package_and_dashboard(tmp_path):
    project=synthetic_project(tmp_path)
    worker=FullModels()
    config=full_config()
    config['objects']={'block':{'prompt':'red box','role':'manipulable_object','geometry':measured('box',[.24]*3)}}
    r=_run_stage_pipeline(project,candidate='adaptive',config=config,worker=worker,through_stage=13)
    assert r['status']=='STAGES_COMPLETE',r.get('needs')
    assert 'image_edit' not in worker.calls and worker.calls.count('da3')==1
    assert worker.calls.count('cpd')==1
    data=read(r['stages']['7']['artifact'])['output_manifest']['data']
    assert data['modeling_calls']==0 and data['objects'][0]['geometry_build_plan']['route']=='primitive'
    from real2sim_builder.export import verify_package
    verify_package(read(r['stages']['13']['artifact'])['output_manifest']['data']['package'])
    candidate=project.root/'scratch/agent/adaptive'
    before={f:sha(f) for f in candidate.rglob('*') if f.is_file()}
    page=generate(candidate,tmp_path/'dashboard')
    body=page.read_text()
    assert 'Preview unavailable' not in body and body.count('<section id=')==14
    assert 'data-cloud=' in body and 'data-layer=' in body and 'estimated optical Z' in body
    assert (page.parent/'fit-0.png').is_file()
    assert (candidate/'evidence/index.html').read_text().count('<section id=')==14
    assert not r.get('preview_error')
    assert all(sha(f)==v for f,v in before.items())
    assert {f for f in candidate.rglob('*') if f.is_file()}==set(before)


@pytest.mark.parametrize('name',['red','blue','green'])
def test_small_block_or_dimension_conflict(tmp_path,name):
    obs=tmp_path/'observation.npz'
    mask=np.ones((8,8),bool);zero=np.zeros_like(mask);ij=np.indices(mask.shape).reshape(2,-1).T
    def record(scale):
        np.savez(obs,mask=mask,image=np.zeros((8,8,3),np.uint8),camera_points=np.c_[ij*scale,np.ones(64)],
                 rgb_source=zero,depth_source=zero,low_confidence=zero)
    obj={'id':name,'role':'manipulable_object'}
    spec={'geometry':measured('box',[.024]*3)}
    record(.003)
    assert build_plan(None,obj,spec,obs,{})['route']=='primitive'
    record(.02)
    plan=build_plan(None,obj,spec,obs,{})
    assert plan['route']=='needs_review' and plan['geometry']['dimensions_m']==[.024]*3


def test_open_container_and_asset_reuse(tmp_path):
    project=synthetic_project(tmp_path)
    obs=tmp_path/'observed.npz';mask=np.ones((8,8),bool);zero=np.zeros_like(mask)
    np.savez(obs,mask=mask,image=np.zeros((8,8,3),np.uint8),camera_points=np.c_[np.indices(mask.shape).reshape(2,-1).T*.002,np.ones(64)],
             rgb_source=zero,depth_source=zero,low_confidence=zero)
    for name in ('cup_1','cup_2'):
        obj={'id':name,'role':'receptacle'}
        g=measured('container',[.08,.08,.063],round=True,bottom_diameter_m=.068,wall_m=.002)
        plan=build_plan(project,obj,{'geometry':g},obs,{})
        assert plan['route']=='parametric'
        asset=create_asset(project,plan,tmp_path/name)
        assert len(asset['collision'])>1 and len(asset['collision'])==len(asset['visual'])
        # A 24mm cube fits at mid-height. Test the actual registered
        # convex collision volumes, including the wall and closed floor.
        from scipy.spatial import ConvexHull
        from real2sim_builder.calibration.geometry import mesh_data
        root=(project.root/asset['manifest']).parent
        hulls=[ConvexHull(mesh_data(root/part['file'])[0]).equations for part in asset['collision']]
        def inside(point):
            return any(np.all(eq[:,:3]@point+eq[:,3]<=1e-8) for eq in hulls)
        from itertools import product
        assert all(not inside(np.array(corner)) for corner in product([-.012,.012],repeat=3))
        assert inside([0,0,-.031]) and inside([.038,0,.025])
        assert not inside([0,0,.030])
        reused=build_plan(project,obj,{'geometry':g,'asset_manifest':asset['manifest']},obs,{})
        assert reused['route']=='existing_asset'
        del g['bottom_diameter_m']
        assert build_plan(project,obj,{'geometry':g},obs,{})['route']=='reconstructed_mesh'


class MixedModels(FullModels):
    """One measured block next to a second, unmeasured detailed object."""
    def __call__(self,operation,request,folder):
        from PIL import Image
        if operation=='segments':
            self.calls.append(operation)
            rows=[]
            for obj in request['objects']:
                x,y,right,bottom=obj['box_xyxy']
                mask=np.zeros((32,32),np.uint8)
                mask[y:bottom,x:right]=255
                folder.mkdir(exist_ok=True,parents=True)
                path=folder/(obj['id']+'.png')
                Image.fromarray(mask).save(path)
                rows.append(dict(id=obj['id'],status='UNIQUE_ESTIMATED',path=str(path)))
            return dict(objects=rows)
        if operation=='removal':
            self.calls.append(operation)
            return dict(order=[obj['id'] for obj in request['objects']])
        result=super().__call__(operation,request,folder)
        if operation=='vlm' and request.get('task')=='scene_instances' and 'scene_analysis' in result['answer']:
            answer=result['answer']
            answer['objects'].append(dict(id='tool',role='manipulable_object',prompt='irregular tool',box_xyxy=[26,12,31,20]))
            if self.occludes:answer['objects'][0]['relations']=['occludes tool']
            semantic=answer['scene_analysis']['objects']
            semantic.append({**semantic[0],'id':'tool','prompt':'irregular tool','category':'tool'})
        return result


@pytest.mark.parametrize('occludes',[False,True])
def test_mixed_native_and_detailed_asset_share_stage_chain(tmp_path,monkeypatch,occludes):
    project=synthetic_project(tmp_path)
    worker=MixedModels()
    worker.occludes=occludes
    config=full_config()
    config['objects']={'block':{'prompt':'red box','role':'manipulable_object','geometry':measured('box',[.24]*3)}}
    config['physics']['properties']['tool']=config['physics']['properties']['block']
    def model_tool(candidate,**kwargs):
        candidate.edit([{'op':'add_object','id':'tool','role':'manipulable_object','dimensions':[.1]*3,
                        'visual':{'type':'box'},'collision':{'type':'box'},'unknown_pose':True}])
        return {'status':'REGISTERED_UNVALIDATED'}
    monkeypatch.setattr('real2sim_builder.authoring.run_codex_modeling',model_tool)
    result=_run_stage_pipeline(project,candidate='mixed',config=config,worker=worker,through_stage=13)
    assert result['status']=='STAGES_COMPLETE',(result.get('error'),result.get('needs'))
    stage=lambda i:read(result['stages'][str(i)]['artifact'])['output_manifest']['data']
    assert {o['id']:o['geometry_build_plan']['route'] for o in stage(7)['objects']}=={'tool':'reconstructed_mesh','block':'primitive'}
    removed=[row['removed'] for row in stage(5)['removal_history']]
    assert ('block' in removed)==occludes
    assert stage(7)['modeling_calls']==1 and worker.calls.count('cpd')==2 and worker.calls.count('depth_inpaint')>=1
    from real2sim_builder.export import verify_package
    verify_package(stage(13)['package'])


def test_same_inputs_detailed_reference_and_adaptive(tmp_path,monkeypatch):
    from real2sim_builder import adaptive_geometry
    from real2sim_builder.files import write
    from test_stage_pose import fake_codex_mesh
    config=full_config()
    config['objects']={'block':{'prompt':'red box','role':'manipulable_object','geometry':measured('box',[.24]*3)}}
    monkeypatch.setattr('real2sim_builder.authoring.run_codex_modeling',fake_codex_mesh)
    results={}
    for label in ('direct','detailed'):
        folder=tmp_path/label
        folder.mkdir()
        p=synthetic_project(folder)
        if label=='detailed':
            monkeypatch.setattr(adaptive_geometry,'build_plan',lambda *a:{**build_plan(*a),'route':'reconstructed_mesh'})
        worker=FullModels()
        r=_run_stage_pipeline(p,candidate='comparison',config=config,worker=worker,through_stage=8)
        assert r['status']=='STAGES_COMPLETE',r.get('needs')
        data=read(r['stages']['7']['artifact'])['output_manifest']['data']
        results[label]={'workers':worker.calls,'modeling_calls':data['modeling_calls'],
                        'source_hashes':[i['sha256'] for i in p.evidence['images']]}
    assert results['direct']['source_hashes']==results['detailed']['source_hashes']
    assert results['direct']['modeling_calls']==0 and results['detailed']['modeling_calls']==1
    assert results['direct']['workers'].count('da3')<results['detailed']['workers'].count('da3')
    write(tmp_path/'comparison.json',results)


def test_older_candidate_is_readable_without_rewriting_it(tmp_path):
    from real2sim_builder.files import write
    p=synthetic_project(tmp_path)
    r=_run_stage_pipeline(p,candidate='older',config=full_config(),worker=FullModels(),through_stage=2)
    root=Path(r['stages']['2']['artifact']).parents[2]
    cache=read(root/'cache.json')
    del cache['geometry_policy']
    write(root/'cache.json',cache)
    before={f:sha(f) for f in root.rglob('*') if f.is_file()}
    with pytest.raises(ValueError,match='이전 제작 정책'):
        _run_stage_pipeline(p,candidate='older',config=full_config(),worker=FullModels(),through_stage=2)
    assert generate(root.parents[1],tmp_path/'older-view').exists()
    assert before=={f:sha(f) for f in root.rglob('*') if f.is_file()}
