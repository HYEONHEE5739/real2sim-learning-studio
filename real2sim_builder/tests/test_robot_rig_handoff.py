"""Registered hardware reuse crosses actual Memo/Stage5/6/7 consumer boundaries."""
import copy
from pathlib import Path

import pytest

from real2sim_builder import authoring,reconstruction_stages as stages
from real2sim_builder.candidate import Candidate
from real2sim_builder.evidence import scene_memo,save_scene_memo
from real2sim_builder.files import read,write,sha
from real2sim_builder.stage_artifacts import StageNeeds,digest


def handoff_case(tmp_path,*,select_rig=True,stale_component_config=False):
    from test_constraint_stage_handoff import corrected_case
    from test_robot_rig import rig_fixture
    from real2sim_builder.evidence import create_robot_rig,import_robot_rig
    c,config,previous,folder,packet=corrected_case(tmp_path)
    _,source,manifest,mount,optical=rig_fixture(tmp_path/'native-hardware')
    rig=create_robot_rig(source,manifest,tmp_path/'registered-rig',mount_link='wrist',
        T_link_mount=mount.tolist(),T_mount_optical=optical.tolist(),
        evidence=['Synthetic native Camera assembly, shared without physical calibration'])
    if select_rig:import_robot_rig(c,rig['path'],joints={'hinge':.2,'gripper':.1})
    text='One wrist camera assembly consists of housing and bracket.'
    old=scene_memo(c.project)
    save_scene_memo(c.project,old['text']+'\n'+text);memo=scene_memo(c.project)
    preview=previous[3]['semantic_preview'];record=preview['scene_analysis'];plan=read(record['path'])
    components=['camera_housing','camera_bracket']
    for name in components:
        obj=copy.deepcopy(plan['objects'][0]);obj.update(id=name,prompt=name,role='fixture',category='camera_component')
        obj['geometry']=None;plan['objects'].append(obj)
    plan['scene_memo_sha256']=memo['sha256'];write(record['path'],plan)
    record.update(sha256=sha(record['path']),memo_sha256=memo['sha256'])
    preview['identity']['memo_sha256']=memo['sha256']
    preview['objects']=authoring.parse_visual_scene_analysis(plan,memo,{r['id']for r in record['source_images']},
        image_records=record['source_images'])['objects']
    packet.update(scene_memo_sha256=memo['sha256'],source_plan_sha256=digest(plan))
    packet['assemblies']=[{'id':rig['assembly']['asset_id'],'members':components,'parent_object_id':'robot',
        'source_quote':text,'physical_sensor_count':1,'link':None,'T_link_assembly':None,
        'evidence':'One Camera contains these observed housing/bracket components'}]
    if stale_component_config:
        for name in components:config['objects'][name]=copy.deepcopy(preview['objects'][name])
    return c,config,previous,folder,packet,rig


def validated_bound(c,previous,packet):
    record=previous[3]['semantic_preview']['scene_analysis'];plan=read(record['path'])
    return authoring.validate_scene_constraints(packet,plan,scene_memo(c.project),
        image_records=record['source_images'],robot_links=['base','wrist','jaw'])


def test_exact_selected_native_assembly_marks_only_its_components_as_reused(tmp_path):
    c,config,p,folder,packet,rig=handoff_case(tmp_path);bound=validated_bound(c,p,packet)
    result=stages.rig_semantic_binding(c,bound)
    assert set(result['reused_rig_components'])=={'camera_housing','camera_bracket'}
    for name in result['reused_rig_components']:
        obj=result['objects'][name]
        assert obj['modeling_readiness']=='REUSED_ROBOT_RIG'
        assert obj['robot_rig_component']['asset_id']==rig['assembly']['asset_id']
        assert obj['robot_rig_component']['rig_sha256']==sha(rig['path'])
        assert obj['robot_rig_component']['calibration_status']=='uncalibrated'
    assert result['objects']['block']['modeling_readiness']=='READY_FOR_MODELING'
    assert 'robot_rig_component'not in result['objects']['block']
    assert result['scene_registration']=='UNRESOLVED'


def test_mismatched_assembly_is_an_explicit_review_not_implicit_hardware_reuse(tmp_path):
    c,config,p,folder,packet,rig=handoff_case(tmp_path)
    packet['assemblies'][0]['id']='some_other_registered_camera'
    bound=validated_bound(c,p,packet)
    with pytest.raises(StageNeeds)as failure:stages.rig_semantic_binding(c,bound)
    assert failure.value.code=='ROBOT_RIG_ASSOCIATION'
    assert failure.value.status=='NEEDS_REVIEW'


def test_missing_typed_assembly_cannot_silently_discard_explicit_component_membership(tmp_path):
    c,config,p,folder,packet,rig=handoff_case(tmp_path);bound=validated_bound(c,p,packet)
    assert bound['objects']['camera_housing']['shape_constraints']['memo_binding']['assembly_id']==rig['assembly']['asset_id']
    bound['assemblies']=[]
    with pytest.raises(StageNeeds)as failure:stages.rig_semantic_binding(c,bound)
    assert failure.value.code=='ROBOT_RIG_ASSOCIATION'


def test_no_rig_does_not_mark_new_hardware_as_preexisting_or_change_constraints(tmp_path):
    c,config,p,folder,packet,rig=handoff_case(tmp_path,select_rig=False)
    bound=validated_bound(c,p,packet);before=copy.deepcopy(bound)
    assert stages.rig_semantic_binding(c,bound)==before
    assert not bound.get('reused_rig_components')
    assert all('robot_rig_component'not in obj for obj in bound['objects'].values())


@pytest.mark.parametrize('stale_config',[False,True])
@pytest.mark.parametrize('observed_scope',[True,False])
def test_stage7_reuses_hardware_and_still_creates_scene_object_modeling_task(tmp_path,monkeypatch,stale_config,observed_scope):
    c,config,p,folder,packet,rig=handoff_case(tmp_path,stale_component_config=stale_config)
    calls=[]
    def provider(operation,request,path):
        assert operation=='vlm'and request['task']=='scene_memo_constraints'
        calls.append(operation);return {'answer':packet}
    out=folder/'stage5';out.mkdir();p[5]=stages.decompose(c,config,p,out,provider)
    out6=folder/'stage6';out6.mkdir()
    def forbidden(*args,**kwargs):pytest.fail('No extra online models or Blender are authorized')
    p[6]=stages.prepare_objects(c,config,p,out6,forbidden)
    config['objects'].pop('cup_unobserved',None)  # Unrelated placeholder is outside this explicit input fixture.
    if not observed_scope:
        # A full-scope Stage7 input fixture; this test does not claim to execute
        # generative Stage5 decomposition or hidden-surface reconstruction.
        p[5].pop('mode')
    monkeypatch.setattr(authoring,'run_codex_modeling',forbidden)
    before_rig=copy.deepcopy(c.scene['robot_rig']);out7=folder/'stage7';out7.mkdir()
    with pytest.raises(StageNeeds,match='explicit run-modeling'):
        stages.meshes(c,config,p,out7,forbidden)
    task=read(c.root/'modeling/tasks.json')
    assert task['status']=='WAITING_FOR_CODEX'
    assert set(task['groups'])=={'block'},'Only non-hardware Scene geometry needs a new modeling task'
    assert {member for task in task['objects']for member in task['members']}=={'block'}
    assert set(task['composition_feedback']['reused_rig_components'])=={'camera_housing','camera_bracket'}
    assert task['groups']['block']['member_specs'][0]['measurement']['dimensions_m']==[.024]*3
    assert c.scene['robot_rig']==before_rig and not c.scene.get('cameras')
    assert calls==['vlm'],'The saved typed analysis must not trigger another semantic call'


def test_no_selected_rig_keeps_unobserved_hardware_review_gate(tmp_path,monkeypatch):
    c,config,p,folder,packet,rig=handoff_case(tmp_path,select_rig=False)
    out=folder/'stage5';out.mkdir();p[5]=stages.decompose(c,config,p,out,lambda *args:{'answer':packet})
    out6=folder/'stage6';out6.mkdir();p[6]=stages.prepare_objects(c,config,p,out6,lambda *a:pytest.fail('CPU crop only'))
    p[5].pop('mode')  # Strict full-scope consumer fixture, not actual full decomposition.
    monkeypatch.setattr(authoring,'run_codex_modeling',lambda *a:pytest.fail('Missing hardware observation must be reviewed first'))
    with pytest.raises(StageNeeds)as failure:
        stages.meshes(c,config,p,folder/'stage7',lambda *a:pytest.fail('No online provider'))
    assert failure.value.code=='MEMO_OBJECT_MISSING'
    assert set(failure.value.gate['object_ids'])=={'camera_housing','camera_bracket'}


def test_explicit_rig_pipeline_import_is_real_and_does_not_modify_working_scene(tmp_path):
    from test_stage_pipeline import synthetic_project,MockModels
    from test_robot_rig import rig_fixture
    from real2sim_builder.evidence import create_robot_rig
    from real2sim_builder.automation import _run_stage_pipeline
    project=synthetic_project(tmp_path/'scene-data')
    _,source,manifest,mount,optical=rig_fixture(tmp_path/'hardware')
    rig=create_robot_rig(source,manifest,tmp_path/'rig-choice',mount_link='wrist',
        T_link_mount=mount.tolist(),T_mount_optical=optical.tolist(),evidence=['Uncalibrated synthetic hardware'])
    model_before=sha(source);worker=MockModels()
    result=_run_stage_pipeline(project,candidate='rig_selected',config={'scene_state_id':'layout','robot_rig':rig['path']},
        worker=worker,through_stage=1)
    assert result['status']=='STAGES_COMPLETE'and worker.calls==[]
    c=Candidate(project,'rig_selected');assert c.scene['robot_model']['joint_names']==['hinge','gripper']
    assert c.scene['robot_rig']['rig_sha256']==sha(rig['path'])
    assert not c.scene['robot_model']['mapping_verified']
    assert 'robot_link_camera_optical_frame'in c.scene['frames']
    assert not(project.root/'working/current_scene.yaml').exists()
    assert sha(source)==model_before


def test_new_rig_choice_cannot_migrate_preexisting_completed_pipeline_artifact(tmp_path):
    from test_stage_pipeline import synthetic_project,MockModels
    from test_robot_rig import rig_fixture
    from real2sim_builder.evidence import create_robot_rig
    from real2sim_builder.automation import _run_stage_pipeline
    project=synthetic_project(tmp_path/'scene-data');worker=MockModels()
    completed=_run_stage_pipeline(project,candidate='old_candidate',config={'scene_state_id':'layout'},worker=worker,through_stage=1)
    c=Candidate(project,'old_candidate');before_scene=sha(c.root/'candidate_scene.yaml')
    artifact=Path(completed['stages']['1']['artifact']);before_artifact=sha(artifact)
    _,source,manifest,mount,optical=rig_fixture(tmp_path/'hardware')
    rig=create_robot_rig(source,manifest,tmp_path/'new-choice',mount_link='wrist',
        T_link_mount=mount.tolist(),T_mount_optical=optical.tolist(),evidence=['New independent hardware choice'])
    with pytest.raises(ValueError,match='new Candidate|artifacts are preserved'):
        _run_stage_pipeline(project,candidate='old_candidate',config={'scene_state_id':'layout','robot_rig':rig['path']},
            worker=worker,through_stage=1)
    assert sha(artifact)==before_artifact and sha(c.root/'candidate_scene.yaml')==before_scene
    assert worker.calls==[]
