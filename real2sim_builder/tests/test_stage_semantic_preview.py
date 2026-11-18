"""Target-aware canonical selection at the actual Stage3 producer boundary.

The heavy semantic/SAM provider is replaced, but projection, footprint, component
metrics, original eligibility limits and Stage3 output are real CPU code.
"""
import copy
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from real2sim_builder import reconstruction_stages as stages
from real2sim_builder.candidate import Candidate
from real2sim_builder.evidence import save_scene_memo
from real2sim_builder.files import sha
from real2sim_builder.observations import register_image
from real2sim_builder.project import Project
from real2sim_builder.stage_artifacts import StageNeeds


def selection_case(tmp_path, *, equipment=True, target_clipped=False):
    project=Project.create(tmp_path/'projects','Semantic canonical frame')
    save_scene_memo(project,'A measured 24 mm green block and the existing robot; one cup is not observed.')
    candidate=Candidate.create(project,'test')
    folder=candidate.root/'selection';folder.mkdir()
    size=64;depth=np.ones((size,size),np.float32)
    robot=np.zeros((size,size),bool)
    if equipment:robot[8:56,:18]=True
    target=np.zeros_like(robot)
    if target_clipped:target[45:60,58:]=True
    else:target[28:40,38:50]=True
    depth[robot|target]=.9
    rgb=np.full((size,size,3),140,np.uint8)
    rgb[robot]=[80,70,180];rgb[target]=[20,170,40]
    image=folder/'original.png';Image.fromarray(rgb).save(image)
    observed=register_image(project,image,camera='phone',camera_type='external',scene_state='layout')
    frame={'id':observed['id'],'path':str(project.root/observed['path']),
           'sha256':observed['sha256'],'resolution':[size,size],'role':'scene_photo','scene_state_id':'layout'}
    prediction=folder/'prediction.npz'
    K=np.array([[[60.,0.,32.],[0.,60.,32.],[0.,0.,1.]]])
    E=np.array([np.c_[np.eye(3),np.zeros(3)]])
    np.savez(prediction,depth=depth[None],conf=np.ones_like(depth[None]),image=rgb[None],intrinsics=K,extrinsics=E)
    support=depth==1;support_path=folder/'support.npz';np.savez(support_path,masks=support[None])
    fit={'coefficients':[0.,0.,-1.,1.],'origin':[0.,0.,1.],
         'inliers':list(range(int(support.sum())))}
    response={'path':str(support_path),'planes':[{'eligible':True,'category':'table','score':.95,
                                                'selection':fit,'final':fit}]}
    associations=[]
    for name,role,mask in [('block','manipulable_object',target),('robot','reference_robot',robot)]:
        if not mask.any():continue
        path=folder/(name+'_mask.png');Image.fromarray(mask.astype('uint8')*255).save(path)
        associations.append({'id':name,'role':role,'status':'UNIQUE_ESTIMATED',
                             'mask':str(path),'mask_sha256':sha(path)})
    preview={'schema':'scene-semantic-preview/1','frames':[{'frame_id':frame['id'],
                'associations':associations}],'scene_analysis':{}}
    config={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic'}},
            'objects':{'block':{'prompt':'green block','role':'manipulable_object',
                'geometry':{'kind':'box','dimensions_m':[.024,.024,.024],
                            'provenance':'measured','evidence':['controlled caliper record']}},
                'cup_unobserved':{'prompt':'cup not visible','role':'receptacle'}}}
    previous={1:{'frames':[frame]},2:{'prediction':str(prediction),'frames':[frame]}}
    calls=[]
    def provider(operation,request,path):
        calls.append(operation)
        assert operation=='support','No model/provider is allowed in this test'
        return response
    return candidate,config,previous,folder,provider,preview,calls


def install_preview(monkeypatch,preview):
    calls=[]
    def semantic_preview(candidate,config,previous,folder,provider):
        calls.append(True)
        return copy.deepcopy(preview)
    monkeypatch.setattr(stages,'semantic_preview',semantic_preview,raising=False)
    return calls


def test_intact_target_survives_clipped_robot_without_relaxing_global_limit(tmp_path,monkeypatch):
    candidate,config,previous,folder,provider,preview,calls=selection_case(tmp_path)
    preview_calls=install_preview(monkeypatch,preview)
    before_config=copy.deepcopy(config);before_scene=copy.deepcopy(candidate.scene)
    memo=candidate.project.root/'input/scene_memo.txt'
    sources=[memo,Path(previous[2]['prediction']),Path(previous[2]['frames'][0]['path'])]
    before={str(p):sha(p)for p in sources}

    result=stages.support(candidate,config,previous,folder,provider)

    assert result['selected_index']==0
    assert result['selected_frame_id']==previous[2]['frames'][0]['id']
    assert len(preview_calls)==1 and calls==['support']
    assert result['global_scores'][0]['clipped_frac']>.5
    assert result['scores'][0]['eligible']
    assert result['scores'][0]['target_clipped_frac']==0
    assert result['semantic_preview']['frames'][0]['associations'][0]['id']=='block'
    assert config==before_config and candidate.scene==before_scene
    assert config['objects']['block']['geometry']['dimensions_m']==[.024,.024,.024]
    assert all(sha(Path(p))==digest for p,digest in before.items())


@pytest.mark.parametrize('failure',['unassociated_robot','ambiguous_robot','ambiguous_target'])
def test_unresolved_association_cannot_turn_unknown_geometry_into_background(tmp_path,monkeypatch,failure):
    candidate,config,previous,folder,provider,preview,_=selection_case(tmp_path)
    rows=preview['frames'][0]['associations']
    if failure=='unassociated_robot':rows[:]=[r for r in rows if r['id']!='robot']
    else:
        name='robot'if failure=='ambiguous_robot'else'block'
        next(r for r in rows if r['id']==name)['status']='AMBIGUOUS'
    install_preview(monkeypatch,preview)
    with pytest.raises(StageNeeds):
        stages.support(candidate,config,previous,folder,provider)


def test_semantic_mask_integrity_is_checked_before_ignoring_equipment(tmp_path,monkeypatch):
    candidate,config,previous,folder,provider,preview,_=selection_case(tmp_path)
    next(r for r in preview['frames'][0]['associations']if r['id']=='robot')['mask_sha256']='0'*64
    install_preview(monkeypatch,preview)
    with pytest.raises((StageNeeds,ValueError),match='(?i)integrity|sha|changed|identity|mask'):
        stages.support(candidate,config,previous,folder,provider)


def test_semantic_preview_does_not_allow_a_clipped_target(tmp_path,monkeypatch):
    candidate,config,previous,folder,provider,preview,_=selection_case(tmp_path,target_clipped=True)
    install_preview(monkeypatch,preview)
    with pytest.raises(StageNeeds):
        stages.support(candidate,config,previous,folder,provider)


def test_existing_eligible_heuristic_path_does_not_require_semantics(tmp_path,monkeypatch):
    candidate,config,previous,folder,provider,_,calls=selection_case(tmp_path,equipment=False)
    def forbidden(*args,**kwargs):raise AssertionError('Normal eligible frame does not require full Object recognition')
    monkeypatch.setattr(stages,'semantic_preview',forbidden,raising=False)
    result=stages.support(candidate,config,previous,folder,provider)
    assert result['selected_index']==0 and calls==['support']
    assert result['scores'][0]['clipped_frac']==0
