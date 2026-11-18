"""Actual Stage5/6/7 handlers; only the remote correction is a fixture."""
import copy
import pytest
from test_semantic_stage_handoff import prepared
from real2sim_builder import reconstruction_stages as stages,authoring
from real2sim_builder.files import read,sha
from real2sim_builder.evidence import scene_memo
from real2sim_builder.stage_artifacts import digest,StageNeeds


def corrected_case(tmp_path):
    c,config,previous,folder,preview=prepared(tmp_path)
    import shutil
    from pathlib import Path
    frame=previous[1]['frames'][0];target=c.root/'retained-photo.png'
    shutil.copyfile(frame['path'],target)
    for stage in(1,2):previous[stage]['frames'][0]['path']=str(target)
    record=preview['scene_analysis'];memo=scene_memo(c.project);plan=read(record['path'])
    record['validation']={'status':'VISUAL_ONLY','strict_error':'Shared plural measurement needs correction'}
    packet={'scene_memo_sha256':memo['sha256'],'source_plan_sha256':digest(plan),
        'replaces_geometry_ids':[],'capture_layouts':[],'groups':[],
        'constraints':[{'id':'block_edge','kind':'shared_dimension','group_id':None,'objects':['block'],
            'reference_objects':[],'axis':None,'source_quote':memo['text'],
            'quantities':[{'quantity':'cube_edge_length','value':'24','unit':'mm','value_quote':'24 mm'}],
            'assumptions':[],'evidence':'The observed block is the Memo block'}],
        'assemblies':[],'needs':['Robot Mount unresolved']}
    config['decomposition']={'observed_only':True,'repair_memo_constraints':True}
    config['image_preparation']={'upsample':False,'infill':False,'size':64}
    return c,config,previous,folder,packet


def test_one_correction_reuses_plan_masks_then_independent_object_tasks_preserve_constraints(tmp_path):
    c,config,p,folder,packet=corrected_case(tmp_path);calls=[]
    def provider(operation,request,path):
        assert operation=='vlm'and request['task']=='scene_memo_constraints'
        assert request['context']['namespaces']['capture_layout_ids']==[]
        assert request['context']['namespaces']['object_ids']==['block','robot']
        calls.append(operation);return {'answer':packet}
    out=folder/'stage5';out.mkdir();p[5]=stages.decompose(c,config,p,out,provider)
    assert calls==['vlm']and p[5]['constraints_status']=='PASS'and p[5]['status']=='PARTIAL'
    assert next(r for r in p[5]['semantic_coverage']if r['id']=='block')['memo_constraints_applied']is True
    assert {o['id']for o in p[5]['objects']}=={'block'}
    original={o['id']:sha(o['mask'])for o in p[5]['objects']}
    def forbidden(*args,**kwargs):pytest.fail('No model or extra correction allowed')
    assert stages.decompose(c,config,p,out,forbidden)==p[5]
    out6=folder/'stage6';out6.mkdir();p[6]=stages.prepare_objects(c,config,p,out6,forbidden)
    assert p[6]['objects'][0]['memo_binding']['quantities_m']['cube_edge_length']==.024
    assert original=={o['id']:sha(o['mask'])for o in p[6]['objects']}
    out7=folder/'stage7';out7.mkdir()
    with pytest.raises(StageNeeds,match='explicit run-modeling'):
        stages.meshes(c,config,p,out7,forbidden)
    task=read(c.root/'modeling/tasks.json')
    assert task['status']=='WAITING_FOR_CODEX'
    assert set(task['groups'])=={'block'},'Unobserved/context Objects cannot become extra partial modeling Instances'
    assert task['groups']['block']['member_specs'][0]['shape_constraints']['memo_binding']['quantities_m']['cube_edge_length']==.024
    assert task['composition_feedback']['memo_constraints']['scene_registration']=='UNRESOLVED'
    assert task['composition_feedback']['scene_complete']is False
    assert not c.scene['objects']


def test_invalid_correction_is_not_cached_or_repeated(tmp_path):
    c,config,p,folder,packet=corrected_case(tmp_path);packet['constraints'][0]['objects']=['absent'];calls=[]
    def provider(*args):calls.append(1);return {'answer':packet}
    out=folder/'stage5';out.mkdir()
    with pytest.raises(StageNeeds,match='strict validation'):stages.decompose(c,config,p,out,provider)
    assert (out/'iteration_000/object_progress.json').is_file()
    assert not(out/'memo_constraints/binding.json').exists()
    with pytest.raises(StageNeeds,match='strict validation'):stages.decompose(c,config,p,out,provider)
    assert calls==[1]


def test_stage7_rejects_lost_binding_before_modeling(tmp_path):
    c,config,p,folder,packet=corrected_case(tmp_path)
    out=folder/'stage5';out.mkdir();p[5]=stages.decompose(c,config,p,out,lambda *a:{'answer':packet})
    out6=folder/'stage6';out6.mkdir();p[6]=stages.prepare_objects(c,config,p,out6,lambda *a:pytest.fail('CPU only'))
    p[6]['objects'][0]['memo_binding']['quantities_m']['cube_edge_length']=.025
    with pytest.raises(ValueError,match='binding changed'):
        stages.meshes(c,config,p,folder/'stage7',lambda *a:pytest.fail('No model'))


def test_partial_observed_scope_cannot_be_published_as_complete_pipeline_stage(tmp_path,monkeypatch):
    from test_stage_pipeline import synthetic_project,MockModels
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.automation import _run_stage_pipeline
    from real2sim_builder.files import write
    p=synthetic_project(tmp_path);worker=MockModels()
    def observed_inputs(candidate,config,previous,folder,provider):
        write(folder/'observed.json',{'real_geometry':'not asserted','objects':['known']})
        return {'status':'PARTIAL','mode':'observed_only','complete':False,'objects':[]}
    monkeypatch.setattr(stages,'decompose',observed_inputs)
    config={'scene_state_id':'layout','support':{'frame_selection':{'mode':'heuristic','min_component_px':4}}}
    result=_run_stage_pipeline(p,candidate='partial',config=config,worker=worker,through_stage=6)
    assert result['status']=='NEEDS_REVIEW'and result['failed_stage']==5
    assert result['error_code']=='OBSERVED_INPUTS_READY'
    assert set(result['stages'])=={'1','2','3','4'}
    c=Candidate(p,'partial');index=read(c.root/'reconstruction/simfoundry/cache.json')
    assert 'artifact'not in index['5']
    assert not list((c.root/'reconstruction/simfoundry/stage_05').rglob('artifact.json'))
    assert list(c.root.rglob('observed.json'))


def test_changed_protected_measurement_is_never_overwritten_by_binding(tmp_path):
    c,config,p,folder,packet=corrected_case(tmp_path)
    config['objects']['block']['geometry']['dimensions_m']=[.025]*3
    before=copy.deepcopy(config['objects'])
    out=folder/'stage5';out.mkdir()
    with pytest.raises(StageNeeds,match='protected Object dimensions'):
        stages.decompose(c,config,p,out,lambda *a:{'answer':packet})
    assert config['objects']==before


def test_legacy_full_with_unverified_memo_dimensions_still_requires_typed_binding(tmp_path):
    c,config,p,folder,packet=corrected_case(tmp_path)
    from real2sim_builder.files import write
    record=p[3]['semantic_preview']['scene_analysis'];plan=read(record['path'])
    plan['objects'][0]['geometry']={'kind':'box','dimensions_m':[None]*3,'source':'user_memo',
        'evidence_quote':scene_memo(c.project)['text'],'evidence':[],'wall_m':None,'support':None,
        'measurement_claims':[],'dimension_relations':[]}
    write(record['path'],plan);record['sha256']=sha(record['path']);record['validation']={'status':'FULL','strict_error':None}
    packet['source_plan_sha256']=digest(plan);packet['replaces_geometry_ids']=['block'];calls=[]
    def provider(operation,request,path):calls.append(operation);return {'answer':packet}
    out=folder/'stage5';out.mkdir();result=stages.decompose(c,config,p,out,provider)
    assert calls==['vlm']and result['constraints_status']=='PASS'
    assert result['objects'][0]['memo_binding']['quantities_m']['cube_edge_length']==.024
