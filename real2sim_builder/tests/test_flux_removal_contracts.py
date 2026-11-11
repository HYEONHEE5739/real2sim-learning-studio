"""Small prompt/evidence/routing contracts. No model Forward or paid requests."""
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from PIL import Image


def test_explicit_removal_prompt_reaches_workflow_without_losing_context():
    from real2sim_builder.comfy_edit import edit_prompt,workflow
    request={'task':'removal','object_prompt':'red cube','object_id':'cube_1','annotation_mode':'outline',
             'prompt':'Remove only the red cube and its shadow. Continue the straight horizontal wood grain.',
             'scene_context':'The cup is behind the cube; preserve it.','preserve_objects':['cup_2']}
    prompt=edit_prompt(request)
    assert request['prompt'] in prompt
    assert 'cube_1' in prompt and 'cup_2' in prompt
    assert request['scene_context'] in prompt and 'green' in prompt.lower()
    graph=workflow('input.png',prompt,{'unet':'m.gguf','clip':'c.safetensors','t5':'t.safetensors','vae':'a.safetensors'},seed=0,size=512,steps=20)
    assert graph['3']['inputs']['text']==prompt


def test_stage5_6_provider_routing_is_explicit_and_keeps_default():
    from real2sim_builder.stage_runtime import runtime_key,validate_configuration
    cfg={'runtimes':{'image_edit':{'python':'default'},'image_edit_removal':{'python':'removal'},'image_edit_objects':{'python':'objects'}}}
    validate_configuration(cfg)
    assert runtime_key(cfg,'image_edit_removal')=='image_edit_removal'
    assert runtime_key(cfg,'image_edit_objects')=='image_edit_objects'
    assert runtime_key({'runtimes':{'image_edit':{'python':'default'}}},'image_edit_removal')=='image_edit'


def test_removed_yes_cannot_override_unchanged_rgb_or_missing_evidence(tmp_path):
    from real2sim_builder.reconstruction_stages import reviewed_removal,removal_review_schema
    from real2sim_builder.stage_artifacts import StageNeeds
    before=tmp_path/'before.png';after=tmp_path/'after.png';mask=tmp_path/'mask.png';object_mask=tmp_path/'object.png'
    a=np.full((12,16,3),100,np.uint8);region=np.zeros((12,16),bool);region[3:9,5:11]=True
    for path,data in [(before,a),(after,a),(mask,region.astype('uint8')*255),(object_mask,region.astype('uint8')*255)]:Image.fromarray(data).save(path)
    edit={'provider':'comfy_gguf','path':str(after),'raw_path':str(after)}
    review={'removed':'yes','reason':'Looks empty','object_remaining':'no','other_objects_preserved':'yes','background_continuous':'yes','uncertain':False,'evidence':['cube absent']}
    with pytest.raises(StageNeeds):reviewed_removal(edit,review,before=before,mask=mask,object_mask=object_mask)
    b=a.copy();b[region]=160;Image.fromarray(b).save(after)
    assert reviewed_removal(edit,review,before=before,mask=mask,object_mask=object_mask)
    b[0,0]=0;Image.fromarray(b).save(after)
    with pytest.raises(StageNeeds):reviewed_removal(edit,review,before=before,mask=mask,object_mask=object_mask)
    assert removal_review_schema()['properties']['uncertain']['type']=='boolean'




def test_stage5_6_one_mock_smoke_blocks_failed_edit_before_depth(tmp_path):
    from real2sim_builder import reconstruction_stages as stages
    from real2sim_builder.stage_artifacts import StageNeeds
    import json
    project=SimpleNamespace(root=tmp_path/'project',evidence={'images':[]},checkpoint=lambda:None)
    candidate=SimpleNamespace(project=project,scene={'frames':{}})
    shape=(32,48);rgb=np.full((*shape,3),150,np.uint8);rgb[10:22,16:30]=[220,30,20]
    z=np.ones(shape,np.float32);K=np.array([[60,0,24],[0,60,16],[0,0,1.]])
    depth=tmp_path/'input.npz';np.savez(depth,image=rgb[None],depth=z[None],intrinsics=K[None])
    mask=tmp_path/'target.png';m=np.zeros(shape,np.uint8);m[10:22,16:30]=255;Image.fromarray(m).save(mask)
    calls=[]
    def provider(op,request,folder):
        calls.append(op);folder.mkdir(parents=True,exist_ok=True)
        if op=='vlm':return {'answer':{'objects':[{'id':'cube_1','prompt':'red cube','role':'manipulable_object','box_xyxy':[16,10,30,22]}]}}
        if op=='segments':return {'objects':[{'id':'cube_1','status':'UNIQUE_ESTIMATED','path':str(mask)}]}
        if op=='removal':return {'order':['cube_1']}
        if op=='image_edit':
            assert request['image_edit_role']=='removal'
            path=folder/'unchanged.png';Image.open(request['original_image']).save(path)
            return {'provider':'comfy_gguf','path':str(path),'raw_path':str(path)}
        raise AssertionError('No DA3 or PriorDepth after an unchanged edit')
    previous={1:{'frames':[]},2:{'prediction':str(depth)},3:{'selected_index':0,'selected_frame_id':'synthetic'},4:{'camera_to_support':np.eye(4).tolist()}}
    folder=tmp_path/'stage5';folder.mkdir()
    with pytest.raises(StageNeeds,match='pixel evidence'):stages.decompose(candidate,{},previous,folder,provider)
    assert calls==['vlm','segments','removal','image_edit']
    observed=next(folder.rglob('cube_1_observed.npz'))
    object_row={'id':'cube_1','prompt':'red cube','observed':str(observed)}
    stage6=tmp_path/'stage6';stage6.mkdir()
    def no_models(*a,**kw):raise AssertionError('Observed crop requires no generator or Bria')
    result=stages.prepare_objects(candidate,{'image_preparation':{'size':64,'upsample':False,'infill':False}}, {5:{'objects':[object_row],'selected_frame_id':'synthetic'}},stage6,no_models)
    assert result['objects'][0]['enhanced']is None
    assert Image.open(result['objects'][0]['crops']['focus']['path']).mode=='RGBA'
