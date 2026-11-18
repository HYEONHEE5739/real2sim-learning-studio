"""Semantic preview consumers preserve evidence without repeating inference."""
import copy
import numpy as np
import pytest
from test_stage_semantic_preview import selection_case
from test_semantic_preview_contract import preview_provider
from real2sim_builder import reconstruction_stages as stages
from real2sim_builder.files import read
from real2sim_builder.stage_artifacts import StageNeeds


def prepared(tmp_path,*,protected_size=True):
    c,config,previous,folder,_,_,_=selection_case(tmp_path)
    if not protected_size:del config['objects']['block']['geometry']
    provider,calls=preview_provider(c,previous,folder)
    preview=stages.semantic_preview(c,config,previous,folder/'semantic',provider)
    previous[3]={'semantic_preview':preview,'selected_index':0,'selected_frame_id':previous[1]['frames'][0]['id']}
    previous[1]['frames'][0]['source_camera']='phone'
    previous[4]={'camera_to_support':np.eye(4).tolist()}
    return c,config,previous,folder,preview


@pytest.mark.parametrize('protected_size',[False,True])
def test_stage5_freezes_real_observation_contract_without_repeating_preview_models(tmp_path,protected_size):
    c,config,previous,folder,preview=prepared(tmp_path,protected_size=protected_size);output=folder/'stage5';output.mkdir();calls=[]
    class StopBeforeGeneration(Exception):pass
    def provider(operation,request,path):
        calls.append(operation)
        assert operation=='removal','No extra VLM/SAM/FLUX/DA3 forward is allowed'
        raise StopBeforeGeneration()
    if protected_size:
        with pytest.raises(StageNeeds,match='exceeds declared bounding diagonal'):
            stages.decompose(c,config,previous,output,provider)
        assert calls==[]
    else:
        # Exercise the original detailed-mesh handoff without a conflicting
        # caliper measurement. Both cases retain the same input observations.
        with pytest.raises(StopBeforeGeneration):stages.decompose(c,config,previous,output,provider)
        assert calls==['removal']
    progress=read(output/'iteration_000/object_progress.json')
    assert set(progress['objects'])=={'block'}
    assert next(r for r in progress['semantic_coverage']if r['id']=='robot')['status']=='CONTEXT_ONLY'
    with np.load(progress['objects']['block']['observed'])as a:
        assert np.array_equal(a['depth'],np.load(previous[2]['prediction'])['depth'][0])
        assert not a['rgb_source'].any()and not a['depth_source'].any()
    assert not c.scene['objects']


def test_stage7_blocks_deferred_memo_constraints_before_modeling(tmp_path,monkeypatch):
    c,config,previous,folder,preview=prepared(tmp_path)
    preview['scene_analysis']['validation']={'status':'VISUAL_ONLY','strict_error':'Unbound numeric claim'}
    previous[5]={'scene_analysis':preview['scene_analysis']};previous[6]={'objects':[]}
    def forbidden(*args,**kwargs):raise AssertionError('Deferred Memo constraints must block model generation first')
    from real2sim_builder import authoring
    monkeypatch.setattr(authoring,'modeling_tasks',forbidden)
    with pytest.raises(StageNeeds,match='(?i)memo|constraint|semantic'):
        stages.meshes(c,config,previous,folder/'stage7',forbidden)


def test_stage5_deferred_constraints_preserve_observations_before_generation_gate(tmp_path):
    c,config,previous,folder,preview=prepared(tmp_path)
    config['decomposition']={'repair_memo_constraints':False}  # Explicit offline/legacy review path.
    preview['scene_analysis']['validation']={'status':'VISUAL_ONLY','strict_error':'Unbound numeric claim'}
    output=folder/'stage5';output.mkdir()
    def forbidden(*args):raise AssertionError('No generation/removal provider before Memo constraint review')
    with pytest.raises(StageNeeds,match='(?i)memo|constraint|semantic'):
        stages.decompose(c,config,previous,output,forbidden)
    progress=read(output/'iteration_000/object_progress.json')
    assert set(progress['objects'])=={'block'}
    assert progress['semantic_coverage'][0]['memo_constraints_applied']is False


def test_full_semantic_plan_cannot_silently_omit_observed_memo_object_at_stage7(tmp_path,monkeypatch):
    c,config,previous,folder,preview=prepared(tmp_path)
    previous[5]={'scene_analysis':preview['scene_analysis']};previous[6]={'objects':[]}
    from real2sim_builder import authoring
    monkeypatch.setattr(authoring,'modeling_tasks',lambda *args:pytest.fail('Missing Object must be reported first'))
    with pytest.raises(StageNeeds,match='Scene Memo Objects')as error:
        stages.meshes(c,config,previous,folder/'stage7',lambda *args:None)
    assert error.value.code=='MEMO_OBJECT_MISSING'and error.value.gate['object_ids']==['block']


def test_stage5_cannot_reuse_a_preview_from_an_older_memo(tmp_path):
    c,config,previous,folder,preview=prepared(tmp_path)
    from real2sim_builder.evidence import save_scene_memo
    save_scene_memo(c.project,'New Memo changes the scene identity')
    output=folder/'stage5';output.mkdir()
    with pytest.raises(ValueError,match='(?i)memo'):
        stages.decompose(c,config,previous,output,lambda *args:pytest.fail('No provider on stale Memo'))
