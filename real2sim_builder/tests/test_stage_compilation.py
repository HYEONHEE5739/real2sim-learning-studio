import copy
import numpy as np
import pytest
from real2sim_builder.files import read, sha
from real2sim_builder.candidate import Candidate
from test_stage_pipeline import synthetic_project
from test_stage_pose import PoseModels, fake_codex_mesh


class FullModels(PoseModels):
    def __call__(self,operation,request,folder):
        if operation in ('physics','simulator'):
            self.calls.append(operation)
            assert request['scene'] and request['engine']=='mujoco'
            if operation=='physics':return {'mujoco':{'status':'STEPPED','steps':500,'settled':True},'physical_verified':False}
            assert request['camera_ids']==[]  # Photos remain reference cameras.
            return {'status':'NOT_VERIFIED','runtime_loaded':True,'physics_steps':0,'camera_ids':[]}
        return super().__call__(operation,request,folder)


def full_config():
    return {'scene_state_id':'layout','execute_modeling':True,
        'support':{'frame_selection':{'mode':'heuristic','min_component_px':4}},
        'image_preparation':{'size':32},
        'physics':{'properties':{'block':{'mass_kg':{'value':.03,'provenance':'estimated','evidence':['synthetic fixture']},
                                          'friction':{'value':.5,'provenance':'estimated','evidence':['synthetic fixture']}}}}}


def test_real_all14_orchestrator_package_and_mock_provenance(tmp_path,monkeypatch):
    from real2sim_builder.automation import _run_stage_pipeline
    from real2sim_builder.export import verify_package
    from real2sim_builder.cameras import camera_roles
    p=synthetic_project(tmp_path);worker=FullModels()
    monkeypatch.setattr('real2sim_builder.authoring.run_codex_modeling',fake_codex_mesh)
    before=sha(p.root/'input/evidence.yaml')
    r=_run_stage_pipeline(p,candidate='test',config=full_config(),worker=worker)
    assert r['status']=='DRAFT_READY'and len(r['stages'])==14
    data={int(k):read(v['artifact'])['output_manifest']['data']for k,v in r['stages'].items()}
    c=Candidate(p,'test');assert all(v=='reference'for v in camera_roles(c.scene,p.evidence['images']).values())
    assert len(c.scene['cameras'])==4 and c.info['status']=='OPEN'
    verify_package(data[13]['package'])
    assert data[12]['actual_physics_steps']==0 and data[12]['execution']=='mock'
    assert data[14]['sensor_status']=='NOT_VERIFIED'
    assert sha(p.root/'input/evidence.yaml')==before
    again=_run_stage_pipeline(p,candidate='test',config=full_config(),worker=worker)
    assert all(v['reused']for v in again['stages'].values())
    assert worker.calls.count('physics')==1


def test_robot_world_is_not_assumed_and_articulation_not_faked(tmp_path,monkeypatch):
    from real2sim_builder.reconstruction_stages import articulate, compile_scene
    from real2sim_builder.stage_artifacts import StageNeeds
    p=synthetic_project(tmp_path);c=Candidate.create(p,'test')
    with pytest.raises(StageNeeds,match='Articulation'):
        articulate(c,{'articulation':{'objects':['block']}},{},tmp_path,None)
    scene=c.scene;scene['robot_model']={'sentinel':'existing URDF'}
    monkeypatch.setattr(Candidate,'scene',property(lambda self:copy.deepcopy(scene)))
    with pytest.raises(StageNeeds,match='Robot World'):
        compile_scene(c,{}, {7:{},8:{'objects':[]},9:{},4:{'camera_to_support':np.eye(4).tolist()}},tmp_path,None)


@pytest.mark.parametrize('stage',range(1,15))
@pytest.mark.parametrize('failure',['runtime','stop'])
def test_every_stage_failure_stop_and_resume_retains_predecessors(tmp_path,monkeypatch,stage,failure):
    from real2sim_builder import reconstruction_stages as processing
    from real2sim_builder.automation import _run_stage_pipeline
    from real2sim_builder.stage_artifacts import StageNeeds,StageArtifact
    handlers=['prepare','depth','support','world','decompose','prepare_objects','meshes','poses',
              'articulate','compile_scene','simulation_ready','stabilize','package_scene','simulator_integration']
    p=synthetic_project(tmp_path);worker=FullModels();name=handlers[stage-1];original=getattr(processing,name);once=[True]
    monkeypatch.setattr('real2sim_builder.authoring.run_codex_modeling',fake_codex_mesh)
    def interrupted(*args):
        if once[0]:
            once[0]=False
            if failure=='stop':raise InterruptedError('synthetic Stop')
            raise StageNeeds('NEEDS_RUNTIME','synthetic missing runtime')
        return original(*args)
    monkeypatch.setattr(processing,name,interrupted)
    r=_run_stage_pipeline(p,candidate='test',config=full_config(),worker=worker)
    assert r['failed_stage']==stage and len(r['stages'])==stage-1
    failure_artifact=read(r['failure_artifact'])
    StageArtifact(**failure_artifact).validate(__import__('pathlib').Path(r['failure_artifact']).parent)
    predecessors={k:sha(v['artifact'])for k,v in r['stages'].items()}
    final=_run_stage_pipeline(p,candidate='test',config=full_config(),worker=worker)
    assert final['status']=='DRAFT_READY'
    assert all(sha(final['stages'][k]['artifact'])==v and final['stages'][k]['reused']for k,v in predecessors.items())
    assert worker.calls.count('physics')==1


def test_unmeasured_asset_scale_creates_new_native_version_without_editing_original(tmp_path):
    from test_object_assets import asset_fixture
    from real2sim_builder.object_assets import register_object_asset,instance_operation,scaled_asset_operation
    p=synthetic_project(tmp_path);c=Candidate.create(p,'test')
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='native')
    c.edit([instance_operation(p,asset['manifest'],'native')]);node=c.scene['objects'][0]
    before={path:sha((p.root/asset['manifest']).parent/path)for path in asset['files']}
    obj={'id':'native','asset_reference':node['object_asset']}
    operation=scaled_asset_operation(c,obj,1.2,c.root/'scale')
    c.edit([operation]);new=c.scene['objects'][0]
    assert new['object_asset']['version']!=asset['version']
    np.testing.assert_allclose(new['dimensions']['value'],np.array(asset['dimensions']['value'])*1.2)
    assert all(sha((p.root/asset['manifest']).parent/path)==value for path,value in before.items())
    assert scaled_asset_operation(c,obj,1.2,c.root/'scale')['object_asset']==operation['object_asset']


def test_canonical_asset_rotation_bakes_visual_and_collision_and_preserves_source(tmp_path):
    from scipy.spatial.transform import Rotation
    from test_object_assets import asset_fixture
    from real2sim_builder.object_assets import register_object_asset,instance_operation,scaled_asset_operation
    from real2sim_builder.calibration.hybrid import surface_mesh
    p=synthetic_project(tmp_path);c=Candidate.create(p,'rotate')
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='native')
    c.edit([instance_operation(p,asset['manifest'],'native')]);node=c.scene['objects'][0]
    before=surface_mesh(node,c.scene,p.root).vertices.copy()
    stamp=sha(p.root/asset['manifest']);r=Rotation.from_euler('z',23,degrees=True).as_matrix()
    op=scaled_asset_operation(c,{'id':'native','asset_reference':node['object_asset']},1.,c.root/'canonical',rotation=r)
    c.edit([op]);after=surface_mesh(c.scene['objects'][0],c.scene,p.root).vertices
    np.testing.assert_allclose(after,before@r.T,atol=1e-7)
    assert sha(p.root/asset['manifest'])==stamp
    assert c.scene['objects'][0]['object_asset']['version']!=asset['version']


def test_new_support_asset_requires_explicit_dimensions_and_preserves_existing(tmp_path,monkeypatch):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);cfg=full_config();cfg['support_asset']={'id':'support','dimensions':{'value':[.4,.3,.02],'provenance':'estimated','evidence':['synthetic explicit support extents']},'T_support_object':np.eye(4).tolist()}
    monkeypatch.setattr('real2sim_builder.authoring.run_codex_modeling',fake_codex_mesh)
    r=_run_stage_pipeline(p,candidate='test',config=cfg,worker=FullModels(),through_stage=10)
    assert r['status']=='STAGES_COMPLETE'
    c=Candidate(p,'test');support=next(o for o in c.scene['objects']if o['id']=='support')
    assert support['object_asset'] and support['role']=='workspace'
    assert support['dimensions']['provenance']=='estimated'


def test_support_registration_retry_after_candidate_save_is_idempotent(tmp_path):
    from real2sim_builder.object_assets import support_asset_operation
    p=synthetic_project(tmp_path);c=Candidate.create(p,'retry')
    spec={'id':'support','dimensions':{'value':[.4,.3,.02],'provenance':'estimated','evidence':['synthetic']},'T_support_object':np.eye(4).tolist()}
    folder=c.root/'support';op=support_asset_operation(c,spec,np.eye(4),folder);c.edit([op]);before=c.scene
    again=support_asset_operation(c,spec,np.eye(4),folder)
    assert again['op']=='use_object_asset'
    c.edit([again]);assert c.scene==before
