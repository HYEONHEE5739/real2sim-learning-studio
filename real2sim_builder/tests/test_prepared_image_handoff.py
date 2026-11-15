"""Stage6 generated image selection/validity -> actual Stage7 task References.

Only remote editing/alpha/VLM are fakes; Stage preparation and modeling task
creation use real CPU code. Stage7 stops at its existing modeling-run boundary.
"""
from pathlib import Path
import copy

import numpy as np
import pytest
from PIL import Image

from real2sim_builder import reconstruction_stages as stages
from real2sim_builder.files import read,sha
from real2sim_builder.project import Candidate,Project
from real2sim_builder.observations import register_image
from real2sim_builder.stage_artifacts import StageNeeds
from test_reconstruction_followup import validity


class Images:
    def __init__(self,*,bad_alpha=False):self.calls=[];self.bad_alpha=bad_alpha
    def __call__(self,operation,request,folder):
        self.calls.append((operation,copy.deepcopy(request)));folder.mkdir(parents=True,exist_ok=True)
        if operation=='image_edit'and request.get('task')=='describe':
            return {'provider':'comfy_gguf','image_shapes':[[32,32]]}
        if operation=='image_edit':
            path=folder/'generated.png'
            Image.new('RGB',(32,32),(210,125,35)if request['task']=='infill'else(35,125,210)).save(path)
            return {'path':str(path)}
        if operation=='background_remove':
            path=folder/'alpha.png';image=Image.open(request['image']).convert('RGBA')
            image.putalpha(0 if self.bad_alpha else 255);image.save(path);return {'path':str(path)}
        if operation=='vlm':return {'answer':validity()}
        raise AssertionError(operation)


def _observed(tmp_path):
    project=Project.create(tmp_path/'projects','prepared final image');rgb=np.full((32,32,3),120,np.uint8)
    mask=np.zeros((32,32),bool);mask[12:20,12:20]=True;rgb[mask]=[220,20,20]
    path=tmp_path/'photo.png';Image.fromarray(rgb).save(path)
    row=register_image(project,path,camera='phone',camera_type='external',scene_state='layout')
    candidate=Candidate.create(project,'draft')
    stage1=candidate.root/'stage1';stage1.mkdir()
    prepared=stages.prepare(candidate,{'scene_state_id':'layout'},{},stage1,None)
    frame=prepared['frames'][0]
    folder=candidate.root/'stage5';folder.mkdir()
    rgb_path=folder/'observed.png';Image.fromarray(rgb).save(rgb_path)
    mask_path=folder/'mask.png';Image.fromarray(mask.astype('uint8')*255).save(mask_path)
    yy,xx=np.where(mask);points=np.c_[xx/32,yy/32,np.ones(len(xx))]
    observed=folder/'observed.npz';np.savez_compressed(observed,image=rgb,mask=mask,camera_points=points,
        rgb_source=np.zeros(mask.shape,np.uint8),depth_source=np.zeros(mask.shape,np.uint8),
        low_confidence=np.zeros(mask.shape,np.uint8),depth=np.ones(mask.shape),K=np.eye(3))
    obj={'id':'block','prompt':'red block','role':'manipulable_object','source_frame_id':frame['id'],
        'observed_rgb':str(rgb_path),'mask':str(mask_path),'observed':str(observed),'provenance':'observed RGB and model-estimated depth'}
    return candidate,{1:prepared,5:{'objects':[obj],'selected_frame_id':frame['id']}},obj


def _handoff(candidate,config,previous,folder):
    folder.mkdir()
    with pytest.raises(StageNeeds)as error:stages.meshes(candidate,config,previous,folder,None)
    assert error.value.status=='NEEDS_RUNTIME'
    task=read(candidate.root/'modeling/tasks.json')
    return next(row for row in task['groups']['block']['references']if row['role']=='derived_object_observation')


@pytest.mark.parametrize('infill',[False,True])
@pytest.mark.parametrize('upsample',[False,True])
@pytest.mark.parametrize('check_valid',[False,True])
def test_final_prepared_image_reaches_validity_and_stage7_with_same_actual_sha(tmp_path,infill,upsample,check_valid):
    candidate,previous,obj=_observed(tmp_path);provider=Images()
    protected={Path(obj[key]):sha(obj[key])for key in('observed_rgb','mask','observed')}
    config={'scene_state_id':'layout','image_preparation':{'size':32,'infill':infill,'upsample':upsample,'check_valid':check_valid}}
    folder=candidate.root/'stage6';folder.mkdir()
    previous[6]=stages.prepare_objects(candidate,config,previous,folder,provider)
    prepared=previous[6]['objects'][0]
    final=(prepared['enhanced']or prepared['infilled']or prepared['crops']['focus'])['path']
    checks=[request for operation,request in provider.calls if operation=='vlm']
    if check_valid and(infill or upsample):
        assert len(checks)==1,'Requested final generated-image validity was not executed'
        assert Path(checks[0]['images'][-1])==Path(final)
        assert prepared['validity_gate']['input_sha256']==sha(final)
    else:assert not checks
    ref=_handoff(candidate,config,previous,candidate.root/'stage7')
    matching=[row for row in ref['crops']if Path(row['path'])==Path(final)]
    assert len(matching)==1,'Stage7 omitted the actual final generated Object reference'
    assert matching[0]['sha256']==sha(final)
    assert ref['original']==obj['observed_rgb']and ref['masks'][0]['sha256']==protected[Path(obj['mask'])]
    assert ref['depth_batches'][0]['metadata']['sha256']==protected[Path(obj['observed'])]
    assert all(sha(path)==digest for path,digest in protected.items())


@pytest.mark.parametrize('infill,upsample',[(True,False),(False,True),(True,True)])
def test_empty_generated_alpha_never_becomes_a_stage7_reference(tmp_path,infill,upsample):
    candidate,previous,obj=_observed(tmp_path);provider=Images(bad_alpha=True)
    before={Path(obj[key]):sha(obj[key])for key in('observed_rgb','mask','observed')}
    config={'image_preparation':{'size':32,'infill':infill,'upsample':upsample,'check_valid':True}}
    folder=candidate.root/'stage6';folder.mkdir()
    with pytest.raises((StageNeeds,ValueError)):stages.prepare_objects(candidate,config,previous,folder,provider)
    assert not(candidate.root/'modeling/tasks.json').exists()
    assert all(sha(path)==digest for path,digest in before.items())


def test_wrong_observed_mask_grid_cannot_be_silently_bound_to_modeling_reference(tmp_path):
    candidate,previous,obj=_observed(tmp_path)
    # A disposable malformed Stage5 fixture, not a mutation of user data.
    Image.new('L',(16,16),255).save(obj['mask'])
    folder=candidate.root/'stage6';folder.mkdir()
    config={'image_preparation':{'size':32,'infill':False,'upsample':False}}
    try:previous[6]=stages.prepare_objects(candidate,config,previous,folder,Images())
    except(StageNeeds,ValueError):return
    handoff=candidate.root/'stage7';handoff.mkdir()
    with pytest.raises((StageNeeds,ValueError)):stages.meshes(candidate,config,previous,handoff,None)
