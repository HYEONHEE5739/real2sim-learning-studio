"""Focused local boundaries: no Forward, CPD, DA3, full pipeline or Scene edits."""
from pathlib import Path
from types import SimpleNamespace
import copy
import numpy as np
import pytest
from PIL import Image
from real2sim_builder.files import write


def test_workspace_runtimes_only_fill_missing_installation_keys(tmp_path, monkeypatch):
    from real2sim_builder import stage_runtime, automation
    workspace=tmp_path/'workspace';project=SimpleNamespace(root=workspace/'scenes/example')
    settings=workspace/'runtime/reconstruction.yaml'
    write(settings,{'runtimes':{'sam3':{'python':'/installed/sam31','model':'/installed/sam.pt'},'pose':{'python':'/installed/cpd'}}})
    config={'runtimes':{'sam3':{'python':'/custom/sam'}},'scene_state_id':'preserve','objects':{'cup':{'measured':.1}}}
    frozen=copy.deepcopy(config)
    effective=stage_runtime.workspace_configuration(project,config)
    assert config==frozen
    assert effective['runtimes']['sam3']=={'python':'/custom/sam','model':'/installed/sam.pt'}
    assert effective['runtimes']['pose']['python']=='/installed/cpd'
    assert effective['objects']==config['objects']
    monkeypatch.setattr(automation,'_run_stage_pipeline',lambda p,**kw:kw['config'])
    called=automation.reconstruct(project,candidate='never_created',config=config)
    assert called['runtimes']==effective['runtimes']
    assert not(project.root).exists()
    write(settings,{'runtimes':{'image_edit':{'model_options':{'api_key':'forbidden'}}}})
    with pytest.raises(ValueError,match='credentials'):stage_runtime.workspace_configuration(project,config)


def test_shared_rgb_depth_region_and_stage3_5_6_smoke(tmp_path,monkeypatch):
    """One CPU smoke across retained SAM, Stage5 depth payload and Stage6 crop math."""
    from real2sim_builder import reconstruction_stages as stages,stage_workers
    from real2sim_builder.calibration.decomposition import removal_region
    from real2sim_builder.comfy_edit import protect_pixels
    image=np.full((32,48,3),140,np.uint8);mask=np.zeros((32,48),bool);mask[12:20,19:27]=True
    z=np.full((32,48),1.2,np.float32);K=np.array([[60.,0,24],[0,60,16],[0,0,1]])
    region=removal_region(mask)
    assert region.sum()>mask.sum()
    base=Image.fromarray(image);result=protect_pixels(base,Image.new('RGB',base.size,'orange'),Image.fromarray(region.astype('uint8')*255))
    payload=stages.depth_inpainting_inputs(np.asarray(result),image,z,K,region,tmp_path/'depth')
    prior=np.load(payload['prior']);assert np.array_equal(prior==0,region)
    assert np.array_equal(prior[~region],z[~region])
    assert np.array_equal(np.asarray(result)[~region],image[~region])
    assert payload['K']==K.tolist() and payload['rgb_original_to_current']==np.eye(3).tolist()
    # A retained real output may be reused for known-pixel/shape contracts without a new PDA call.
    fake=np.where(region,1.7,prior).astype('float32')
    assert np.array_equal(fake[~region],z[~region])
    raw=tmp_path/'sam.npz';np.savez(raw,mask_0_0=mask)
    prediction=tmp_path/'prediction.npz';np.savez(prediction,image=image[None],depth=z[None],intrinsics=K[None])
    support=tmp_path/'support';support.mkdir()
    # Insufficient (<100) support pixels produce an explicit ineligible artifact;
    # the unneeded Open3D dependency is a double, no fake plane is generated.
    import sys
    monkeypatch.setitem(sys.modules,'open3d',SimpleNamespace())
    data=stage_workers.support({'output':str(support),'prediction':str(prediction),'sam_result':{'path':str(raw),'candidates':[[{'key':'mask_0_0','category':'table','score':.8}]],'provenance':{'execution':'retained synthetic mask'}}})
    assert data['planes'][0]['eligible']is False
    # Stage3's retained shape and explicit plane failure are separate contracts.
    with np.load(prediction)as p, np.load(raw)as r:assert r['mask_0_0'].shape==p['depth'][0].shape
    low=np.zeros(mask.shape,np.uint8);low[12,19]=1  # Binary masks need not be stored as bool.
    observed=tmp_path/'observed.npz';np.savez(observed,image=image,mask=mask,camera_points=np.ones((mask.sum(),3)),depth=z,K=K,
        rgb_source=np.zeros(mask.shape,np.uint8),depth_source=np.zeros(mask.shape,np.uint8),low_confidence=low)
    previous={5:{'objects':[{'id':'cup_1','prompt':'cup','observed':str(observed)}],'selected_frame_id':'synthetic'}}
    candidate=SimpleNamespace(project=SimpleNamespace(checkpoint=lambda:None))
    def forbidden(*a,**kw):raise AssertionError('Observed-only Stage6 must not call an image/RemBG model')
    stage6=tmp_path/'stage6';stage6.mkdir()
    outputs=stages.prepare_objects(candidate,{'image_preparation':{'size':64,'upsample':False,'infill':False,'remove_background':False}},previous,stage6,forbidden)
    assert not outputs['upsampling_executed']
    focus=Image.open(outputs['objects'][0]['crops']['focus']['path'])
    assert focus.mode=='RGBA' and np.asarray(focus)[...,3].max()==255
    assert outputs['objects'][0]['enhanced']is None
    with np.load(outputs['objects'][0]['original_points'])as points:
        assert len(points['camera_points'])==len(points['uv_processed'])==int(mask.sum())-1


def test_local_removal_needs_explicit_quality_review():
    from real2sim_builder.reconstruction_stages import reviewed_removal
    from real2sim_builder.stage_artifacts import StageNeeds
    edit={'provider':'comfy_gguf','path':'result.png'}
    with pytest.raises(StageNeeds,match='removal'):
        reviewed_removal(edit,{'removed':'no','reason':'cube is still present'})
    with pytest.raises(StageNeeds):reviewed_removal(edit,{'removed':True})
    with pytest.raises(StageNeeds):reviewed_removal(edit,{'removed':'yes','reason':'target absent but no pixel evidence'})
    assert reviewed_removal({'provider':'imagen3'},None)


def test_physics_child_receives_explicit_installed_usd_library_path(tmp_path,monkeypatch):
    from real2sim_builder import inference,stage_workers
    import sys
    source=tmp_path/'existing_usd';(source/'pxr').mkdir(parents=True);(source/'bin').mkdir()
    called=[]
    class Child:
        returncode=0
        pid=99999999
        def poll(self):return 0
        def wait(self,timeout=None):return 0
    def launch(*a,**kw):
        called.append(kw['env'])
        return Child()
    monkeypatch.setattr(inference.subprocess,'Popen',launch)
    monkeypatch.setenv('LD_LIBRARY_PATH','/keep/library')
    inference._run_worker(SimpleNamespace(checkpoint=lambda:None),sys.executable,'physics',{'source':str(source)},tmp_path/'worker',2,entrypoint=Path(stage_workers.__file__))
    assert called[0]['LD_LIBRARY_PATH']==str(source/'bin')+':/keep/library'
    assert 'PYTHONPATH' not in called[0]


def test_workspace_blender_path_is_scoped_and_restores_existing_environment(tmp_path,monkeypatch):
    from real2sim_builder.stage_runtime import runtime_environment
    import os
    executable=tmp_path/'existing-blender';executable.write_text('#!/bin/sh\nexit 0\n');executable.chmod(0o700)
    monkeypatch.setenv('REAL2SIM_BLENDER','/preserve/original-setting')
    with runtime_environment({'runtimes':{'blender':{'executable':str(executable)}}}):
        assert os.environ['REAL2SIM_BLENDER']==str(executable)
    assert os.environ['REAL2SIM_BLENDER']=='/preserve/original-setting'
