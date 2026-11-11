import numpy as np
import pytest
from real2sim_builder.scene import value


def test_actual_cpu_physics_records_poses_motion_and_stable_window(tmp_path):
    from test_support_constraints import supported
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.project import Project
    from real2sim_builder.validation import physics_probe
    scene,_=project_supports(supported());scene['objects'][1]['physics']['mass_kg']=value(.03,'estimated',['synthetic'])
    p=Project.create(tmp_path/'projects','synthetic physics')
    result=physics_probe(p,scene,tmp_path/'probe',steps=300)
    row=result['mujoco']['objects']['block']
    assert row['T_world_before'] and row['T_world_after'] and row['sample_count']==301
    assert row['stable_window'] and row['position_delta_last_m']<1e-4
    assert np.isfinite(row['orientation_delta_total_rad'])
    assert 'tangential_displacement_m'in row and 'up_axis_change_rad'in row
    assert result['physical_verified']is False


def test_stabilized_pose_requires_matching_review_and_protects_measured_values():
    from real2sim_builder.validation import reviewed_stabilized_scene
    from test_support_constraints import supported
    from real2sim_builder.stage_artifacts import digest
    s=supported();target=np.eye(4);target[:3,3]=[.02,0,.5]
    proposals={'block':{'T_world_after':target.tolist(),'stable_window':True}}
    with pytest.raises(ValueError,match='review'):
        reviewed_stabilized_scene(s,proposals,{})
    approval={'approved':True,'source_scene_sha256':digest(s),'evidence':['synthetic explicit review']}
    s['objects'][1]['pose']['provenance']='measured';approval['source_scene_sha256']=digest(s)
    with pytest.raises(ValueError,match='Protected'):
        reviewed_stabilized_scene(s,proposals,approval)


def test_mock_physics_cannot_apply_poses_even_with_success_claim(tmp_path):
    from real2sim_builder.reconstruction_stages import stabilize
    from real2sim_builder.project import Project
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.stage_artifacts import StageNeeds
    p=Project.create(tmp_path/'projects','fake physics');c=Candidate.create(p,'test')
    def worker(*args):return {'_execution':'mock','mujoco':{'steps':500,'settled':True,'objects':{'x':{'stable_window':True}}}}
    with pytest.raises(StageNeeds,match='Actual stable physics'):
        stabilize(c,{'physics':{'apply_stabilized_poses':True}},{11:{'scene':'unused'}},tmp_path,worker)


def test_matching_review_can_update_estimated_candidate_pose_with_support_intact():
    from real2sim_builder.validation import reviewed_stabilized_scene
    from test_support_constraints import supported
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.stage_artifacts import digest
    from real2sim_builder.scene import world_pose
    s,_=project_supports(supported());before=s['objects'][1]['pose']['value']
    target=world_pose(s,s['objects'][1]).copy();target[0,3]+=.02
    result=reviewed_stabilized_scene(s,{'block':{'T_world_after':target.tolist(),'stable_window':True}},
        {'approved':True,'source_scene_sha256':digest(s),'evidence':['synthetic reviewed proposal']})
    assert result['geometry_constraints']==s['geometry_constraints']
    assert s['objects'][1]['pose']['value']==before
    assert result['objects'][1]['pose']['value']!=before


def test_actual_cpu_settling_review_can_resume_after_candidate_save(tmp_path):
    from test_support_constraints import supported
    from real2sim_builder.initialization import project_supports
    from real2sim_builder.project import Project
    from real2sim_builder.candidate import Candidate
    from real2sim_builder.files import write
    from real2sim_builder.stage_artifacts import digest
    from real2sim_builder.validation import physics_probe
    from real2sim_builder.reconstruction_stages import stabilize
    s,_=project_supports(supported());s['objects'][1]['physics']['mass_kg']=value(.03,'estimated',['synthetic'])
    p=Project.create(tmp_path/'projects','reviewed synthetic physics');c=Candidate.create(p,'test');c.save(s)
    ready=tmp_path/'ready.yaml';write(ready,s)
    actual=physics_probe(p,s,tmp_path/'actual',steps=300)
    assert actual['mujoco']['settled']
    def cached_actual(*args):return {**actual,'_execution':'real'}
    cfg={'physics':{'steps':300,'apply_stabilized_poses':True,'pose_review':{'approved':True,'source_scene_sha256':digest(s),'evidence':['synthetic explicit review']}}}
    out=tmp_path/'stage12';out.mkdir()
    result=stabilize(c,cfg,{11:{'scene':str(ready)}},out,cached_actual)
    assert result['applied_to_candidate']and result['actual_physics_steps']==300
    after=digest(c.scene)
    assert stabilize(c,cfg,{11:{'scene':str(ready)}},out,cached_actual)['applied_to_candidate']
    assert digest(c.scene)==after
