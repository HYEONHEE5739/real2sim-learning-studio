"""Existing semantic schema/SAM observation identity before canonical selection."""
import copy
from pathlib import Path
import numpy as np
import pytest
from test_stage_semantic_preview import selection_case
from real2sim_builder import reconstruction_stages as stages
from real2sim_builder.evidence import scene_memo
from real2sim_builder.files import sha


def preview_provider(candidate,previous,folder):
    frame=previous[1]['frames'][0];memo=scene_memo(candidate.project)
    rows=[]
    for name,role,category,box in [('block','manipulable_object','block',[38,28,50,40]),
                                   ('robot','reference_robot','robot',[0,8,18,56])]:
        rows.append({'id':name,'prompt':name,'role':role,'category':category,'modeling_notes':'Controlled observation',
            'representative_view':{'image_id':frame['id'],'evidence':'controlled RGB'},
            'observations':[{'image_id':frame['id'],'box_xyxy':box,'points':[],'evidence':'controlled RGB'}],
            'geometry':None,'model_references':[],'robot_attachment':None,'support_relation':None})
    answer={'scene_memo_sha256':memo['sha256'],'objects':rows,'capture_layouts':[],'task':None,'needs':[]}
    masks=[];boxes=[]
    for row in rows:
        x0,y0,x1,y1=row['observations'][0]['box_xyxy'];mask=np.zeros((64,64),bool);mask[y0:y1,x0:x1]=True
        masks.append(mask);boxes.append([x0,y0,x1,y1])
    path=folder/'raw.npz';np.savez(path,masks=np.asarray(masks),boxes=boxes,scores=[.93,.91])
    calls=[]
    def provider(operation,request,path_out):
        calls.append(operation)
        if operation=='vlm':
            assert request['context']['memo']['sha256']==memo['sha256']
            assert request['task']=='scene_semantic_preview'
            return {'answer':copy.deepcopy(answer),'execution':'mock'}
        assert operation=='segments'
        assert {o['id']for o in request['objects']}=={'block','robot'}
        from PIL import Image
        instances=[]
        for i,row in enumerate(rows):
            target=folder/(row['id']+'_associated.png');Image.fromarray(masks[i].astype('uint8')*255).save(target)
            instances.append({'id':row['id'],'path':str(target),'status':'UNIQUE_ESTIMATED','confidence':[.93,.91][i]})
        return {'objects':instances,'sam_provenance':{'execution':'mock'}}
    return provider,calls


def test_preview_reuses_existing_schema_and_retains_role_bound_real_mask_contract(tmp_path):
    candidate,config,previous,folder,_,_,_=selection_case(tmp_path)
    provider,calls=preview_provider(candidate,previous,folder)
    before=copy.deepcopy(config)
    result=stages.semantic_preview(candidate,config,previous,folder/'semantic',provider)
    assert result['schema']=='scene-semantic-preview/1'
    assert calls==['vlm','segments']
    assert result['scene_analysis']['memo_sha256']==scene_memo(candidate.project)['sha256']
    rows=result['frames'][0]['associations'];assert {r['id']for r in rows}=={'block','robot'}
    assert all(r['status']=='UNIQUE_ESTIMATED'and sha(r['mask'])==r['mask_sha256']for r in rows)
    assert next(r for r in rows if r['id']=='block')['confidence']==.93
    assert config==before and not candidate.scene['objects']
    # Frozen, matching identity avoids another remote/GPU call.
    def forbidden(*args):raise AssertionError('Completed semantic/mask result must be reusable')
    assert stages.semantic_preview(candidate,config,previous,folder/'semantic',forbidden)==result


def test_completed_preview_rejects_changed_mask_bytes(tmp_path):
    candidate,config,previous,folder,_,_,_=selection_case(tmp_path)
    provider,_=preview_provider(candidate,previous,folder)
    result=stages.semantic_preview(candidate,config,previous,folder/'semantic',provider)
    Path(result['frames'][0]['associations'][0]['mask']).write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='(?i)sha|changed|identity|mask'):
        stages.semantic_preview(candidate,config,previous,folder/'semantic',provider)


@pytest.mark.parametrize('change',['measurements','robot_links'])
def test_preview_cache_identity_binds_protected_measurements_and_robot_link_contract(tmp_path,change):
    candidate,config,previous,folder,_,_,_=selection_case(tmp_path)
    provider,_=preview_provider(candidate,previous,folder)
    stages.semantic_preview(candidate,config,previous,folder/'semantic',provider)
    if change=='measurements':config['objects']['block']['geometry']['dimensions_m'][0]=.025
    else:
        scene=candidate.scene;scene['frames']['robot_link_wrist']={'parent':'world','transform':{'value':np.eye(4).tolist(),'provenance':'estimated','evidence':['controlled']}}
        candidate.save(scene)
    with pytest.raises(ValueError,match='identity changed'):
        stages.semantic_preview(candidate,config,previous,folder/'semantic',provider)
