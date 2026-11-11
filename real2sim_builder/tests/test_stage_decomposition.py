from pathlib import Path
import types
import pytest
import sys
import numpy as np
from PIL import Image
from test_stage_pipeline import MockModels, synthetic_project
from real2sim_builder.files import read


class DecompositionModels(MockModels):
    def __init__(self):super().__init__();self.identifications=0
    def __call__(self,operation,request,folder):
        from real2sim_builder.stage_artifacts import StageNeeds
        if operation=='support'or(operation=='da3'and len(request['images'])==4):
            return super().__call__(operation,request,folder)
        self.calls.append(operation);folder.mkdir(parents=True,exist_ok=True)
        if self.fail==operation:raise StageNeeds('NEEDS_RUNTIME','Unavailable synthetic provider')
        if operation=='vlm':
            self.identifications+=1
            return {'answer':{'objects':[{'id':'block','prompt':'red block','role':'manipulable_object','box_xyxy':[12,12,20,20]}]if self.identifications==1 else[]}}
        if operation=='segments':
            a=np.zeros((32,32),np.uint8);a[12:20,12:20]=255;path=folder/'mask.png';Image.fromarray(a).save(path)
            return {'objects':[{'id':'block','status':'UNIQUE_ESTIMATED','path':str(path)}]}
        if operation=='removal':return {'order':['block']}
        if operation=='background_remove':
            path=folder/'alpha.png';Image.open(request['image']).convert('RGBA').save(path);return {'path':str(path)}
        if operation=='image_edit' and request.get('task')=='describe':return {'provider':'comfy_gguf','image_shapes':[[32,32]]}
        if operation=='image_edit':
            path=folder/'edited.png'
            if request.get('mask'):Image.new('RGB',(32,32),(100,100,100)).save(path)
            else:Image.open(request['image']).save(path)
            return {'path':str(path)}
        if operation=='da3':
            path=folder/'depth.npz';np.savez(path,depth=np.ones((1,32,32),np.float32));return {'path':str(path),'is_metric':1}
        if operation=='depth_inpaint':
            prior=np.load(request['prior']);result=np.where(prior==0,1,prior);path=folder/'filled.npy';np.save(path,result)
            return {'path':str(path)}
        raise AssertionError(operation)


def test_decomposition_uses_real_data_flow_and_preserves_original_depth(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);worker=DecompositionModels()
    config={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}},'image_preparation':{'size':32}}
    r=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=6)
    assert r['status']=='STAGES_COMPLETE'
    d=read(r['stages']['5']['artifact'])['output_manifest']['data'];assert len(d['objects'])==1
    assert d['removal_history'][0]['inpainting_is_measured']is False
    with np.load(d['objects'][0]['observed'])as a:assert np.allclose(a['camera_points'][:,2],.9)
    o=read(r['stages']['6']['artifact'])['output_manifest']['data']['objects'][0]
    rgba=np.asarray(Image.open(o['crops']['context']['path']))
    assert rgba.shape==(32,32,4)and rgba[...,3].min()==0 and rgba[...,3].max()==255
    assert worker.calls.count('depth_inpaint')==1


def test_incomplete_decomposition_reuses_completed_remote_calls(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    p=synthetic_project(tmp_path);worker=DecompositionModels();worker.fail='depth_inpaint'
    config={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}}}
    first=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=5)
    assert first['status']=='NEEDS_RUNTIME'and first['failed_stage']==5
    worker.fail=None
    final=_run_stage_pipeline(p,candidate='test',config=config,worker=worker,through_stage=5)
    assert final['status']=='STAGES_COMPLETE'
    assert worker.calls.count('image_edit')==1 and worker.calls.count('segments')==1
    assert worker.calls.count('depth_inpaint')==2


def test_imagen_rgb_removal_receives_the_actual_mask(tmp_path,monkeypatch):
    from real2sim_builder.stage_workers import image_edit
    seen={}
    class ImageProvider:
        def __init__(self,**kw):pass
        def __call__(self,**kw):seen.update(kw);return object()
        def get_result_images(self,result):return [Image.new('RGB',(8,8))]
    module=types.ModuleType('simfoundry.models.vlm');module.Imagen3=ImageProvider;module.FLUX1=ImageProvider
    monkeypatch.setitem(sys.modules,'simfoundry',types.ModuleType('simfoundry'))
    monkeypatch.setitem(sys.modules,'simfoundry.models',types.ModuleType('simfoundry.models'))
    monkeypatch.setitem(sys.modules,'simfoundry.models.vlm',module)
    rgb=tmp_path/'rgb.png';mask=tmp_path/'mask.png';Image.new('RGB',(8,8)).save(rgb);Image.new('L',(8,8)).save(mask)
    image_edit({'provider':'imagen3','image':str(rgb),'mask':str(mask),'prompt':'remove selected object','output':str(tmp_path)})
    assert seen['image_path']==str(rgb)and seen['mask_image_path']==str(mask)


def test_preparation_uses_provider_ratio_infill_alpha_and_typed_validation(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    class PreparationModels(DecompositionModels):
        def __call__(self,op,req,folder):
            if op=='image_edit' and req.get('task')=='describe':
                return {'provider':'comfy_gguf','image_shapes':[[48,32],[32,48]]}
            if op=='background_remove':
                folder.mkdir(parents=True,exist_ok=True);a=Image.open(req['image']).convert('RGBA');a.save(folder/'alpha.png');return {'path':str(folder/'alpha.png')}
            if op=='vlm' and req.get('task')=='object_validity':return {'answer':{'validity':'no'}}
            return super().__call__(op,req,folder)
    p=synthetic_project(tmp_path);worker=PreparationModels()
    cfg={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}},'image_preparation':{'size':32,'infill':True,'check_valid':True}}
    r=_run_stage_pipeline(p,candidate='test',config=cfg,worker=worker,through_stage=6)
    assert r['status']=='NEEDS_REVIEW' and r['failed_stage']==6
    cfg['image_preparation']['check_valid']=False
    r=_run_stage_pipeline(p,candidate='test',config=cfg,worker=worker,through_stage=6)
    assert r['status']=='STAGES_COMPLETE'
    obj=read(r['stages']['6']['artifact'])['output_manifest']['data']['objects'][0]
    assert obj['provider_crop']['target_wh']==[32,48]
    assert obj['enhanced']['alpha_source']=='rembg'
    assert obj['enhanced']['depth_frame']=='observed_original_only'


def test_removal_all_nine_retries_fail_without_depth_invention(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    class GreenResidual(DecompositionModels):
        def __init__(self):super().__init__();self.attempts=[]
        def __call__(self,op,req,folder):
            if op=='image_edit':
                self.attempts.append((req['annotation_mode'],req['seed']));folder.mkdir(parents=True,exist_ok=True)
                file=folder/'green.png';Image.new('RGB',(32,32),(0,255,0)).save(file);return {'path':str(file)}
            return super().__call__(op,req,folder)
    p=synthetic_project(tmp_path);w=GreenResidual();cfg={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}}}
    result=_run_stage_pipeline(p,candidate='test',config=cfg,worker=w,through_stage=5)
    assert result['status']=='NEEDS_REVIEW'and result['failed_stage']==5
    assert w.attempts==[(mode,i)for mode in('mask','outline','bbox')for i in range(3)]
    assert 'depth_inpaint'not in w.calls and w.calls.count('da3')==1


def test_provider_without_original_stage6_shapes_does_not_initialize_model(tmp_path,monkeypatch):
    from real2sim_builder.stage_workers import image_edit
    class Provider:
        def __init__(self,**kw):pytest.fail('Metadata inspection must not initialize a model or authenticate')
    module=types.ModuleType('simfoundry.models.vlm');module.Imagen3=Provider;module.FLUX1=Provider
    monkeypatch.setitem(sys.modules,'simfoundry.models.vlm',module)
    result=image_edit({'provider':'imagen3','task':'describe','output':str(tmp_path)})
    assert result['supported']is False and result['inference_executed']is False


def test_stage6_unsupported_provider_preserves_completed_decomposition(tmp_path):
    from real2sim_builder.automation import _run_stage_pipeline
    class WithoutShapes(DecompositionModels):
        def __call__(self,op,req,folder):
            if op=='image_edit'and req.get('task')=='describe':return {'provider':'imagen3','supported':False,'inference_executed':False}
            return super().__call__(op,req,folder)
    p=synthetic_project(tmp_path);w=WithoutShapes();cfg={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}}}
    result=_run_stage_pipeline(p,candidate='test',config=cfg,worker=w,through_stage=6)
    assert result['status']=='NOT_SUPPORTED'and result['failed_stage']==6
    assert result['stages']['5']['status']=='COMPLETE'
