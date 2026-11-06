"""Automatic variable choice uses training geometry, never holdout support."""
import copy
import numpy as np
from scipy.spatial.transform import Rotation
from test_builder_export import legacy_scene


def fixture(views=1,kind='side'):
    scene=legacy_scene();cam=scene['cameras'][0]
    cam['pose']['provenance']=cam['K']['provenance']='estimated'
    scene['objects'][1]['pose']['provenance']='estimated'
    rows=[]
    for i in range(views):
        pose=np.array(cam['pose']['value']);pose[:3,:3]=Rotation.from_rotvec([.1*i,.03*i*i,0]).as_matrix()@pose[:3,:3];pose[0,3]+=.05*i
        rows.append(dict(image_id=f'v{i}',object_id='block',camera='side',camera_type=kind,split='train',
            camera_pose=pose.tolist(),has_raw_depth=True,depth_batch='batch',cloud_rank=3,measured_q=kind=='wrist'))
    return scene,rows


def selected(scene,rows,options=None,stage='geometry'):
    from real2sim_builder.calibration.joint import select_parameters
    blocks,radius,indices,report=select_parameters(scene,rows,options or{},stage=stage)
    return {(b[0],b[1]):[i-b[3]for i in indices if b[3]<=i<b[3]+b[4]] for b in blocks if any(b[3]<=i<b[3]+b[4]for i in indices)},report


def test_single_view_camera_object_gauge_preserves_camera_but_fits_relative_object():
    scene,rows=fixture();original=copy.deepcopy(scene)
    active,report=selected(scene,rows)
    assert ('camera','side')not in active and ('object_support','block')in active
    assert any(r['reason']=='unanchored_camera_object_gauge'for r in report['frozen'])
    assert report['needs']and scene==original


def test_fixed_visible_reference_allows_camera_but_unobserved_reference_does_not():
    scene,rows=fixture()
    assert ('camera','side')not in selected(scene,rows)[0]
    rows.append({**rows[0],'object_id':'table'})
    assert ('camera','side')in selected(scene,rows)[0]


def test_holdout_never_unlocks_wrist_or_lens_and_repeated_views_are_not_motion():
    scene,rows=fixture(4,'wrist')
    for row in rows[1:]:row['split']='validation'
    active,report=selected(scene,rows,{'optimize_intrinsics':True})
    assert ('camera','side')not in active and ('intrinsics','side')not in active
    for row in rows:row['split']='train';row['camera_pose']=rows[0]['camera_pose']
    assert ('camera','side')not in selected(scene,rows)[0]


def test_diverse_wrist_with_fixed_reference_unlocks_shared_mount_and_lens():
    scene,rows=fixture(5,'wrist')
    rows += [{**r,'object_id':'table'}for r in rows]
    active,report=selected(scene,rows)
    assert ('camera','side')in active and ('intrinsics','side')in active
    assert ('scale','batch')in active
    assert not report['needs']


def test_uniform_upright_cylinder_keeps_yaw_but_updates_xy():
    scene,rows=fixture(2);scene['cameras'][0]['pose']['provenance']='calibrated'
    block=scene['objects'][1];block['visual']={'type':'cylinder'};block['collision']={'type':'cylinder'}
    active,report=selected(scene,rows)
    assert active['object_support','block']==[0,1]
    block['visual']['texture']='pattern'
    assert selected(scene,rows)[0]['object_support','block']==[0,1,2]


def test_geometry_and_appearance_are_separate_and_free_albedo_does_not_unlock_lighting():
    scene,rows=fixture(2);scene['objects'][1]['color']['provenance']='estimated'
    scene['lights']['ambient']['provenance']='estimated'
    options={'optimize_appearance':True,'optimize_lighting':True}
    active,_=selected(scene,rows,options)
    assert ('color','block')not in active
    active,report=selected(scene,rows,options,stage='appearance')
    assert ('color','block')in active and ('ambient','ambient')not in active
    assert not any(k[0]in('camera','intrinsics','object','object_support','scale')for k in active)
    assert any(r['reason']=='albedo_lighting_ambiguity'for r in report['frozen'])


def test_native_solver_runs_geometry_then_appearance_and_reports_frozen_variables(tmp_path):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder.calibration.hybrid import fit_scene
    scene_project,truth,scene=rendered_fixture(tmp_path)
    scene['objects'][1]['color']['provenance']='estimated'
    original=copy.deepcopy(scene)
    fitted,report=fit_scene(scene_project,scene,scene_project.root/'scratch/strategy',
        {'optimize_appearance':True,'max_iterations':4,'max_evaluations':60})
    stages=[r['strategy']['stage']for r in report['history']]
    assert stages==sorted(stages,key=['geometry','appearance'].index)and set(stages)=={'geometry','appearance'}
    assert report['observability']['holdout_used']is False
    assert fitted['objects'][1]['dimensions']==original['objects'][1]['dimensions']and scene==original


def test_missing_observability_cannot_be_promoted_by_low_loss(tmp_path):
    from real2sim_builder.automation import draft_readiness
    from real2sim_builder.project import Project
    project=Project.create(tmp_path/'scenes','draft gate');scene=legacy_scene()
    report={'status':'OPTIMIZED_UNVERIFIED','converged':True,'training_view_count':2,'after_loss':.001,
        'observability':{'needs':['wrist: capture distinct measured-q rotations']}}
    result=draft_readiness(project,scene,report)
    assert result['status']=='NEEDS_MORE_DATA'and any('wrist'in n for n in result['needs'])


def test_single_axis_wrist_rotation_or_missing_q_never_unlocks_mount():
    scene,rows=fixture(5,'wrist')
    for i,row in enumerate(rows):
        pose=np.array(row['camera_pose']);pose[:3,:3]=Rotation.from_euler('z',i*.2).as_matrix();row['camera_pose']=pose.tolist()
    rows += [{**r,'object_id':'table'}for r in rows]
    assert ('camera','side')not in selected(scene,rows)[0]
    scene,rows=fixture(5,'wrist')
    for row in rows:row['measured_q']=False
    rows += [{**r,'object_id':'table'}for r in rows]
    assert ('camera','side')not in selected(scene,rows)[0]


def test_moving_robot_base_is_not_its_own_world_reference():
    from real2sim_builder.scene import value
    scene,rows=fixture(5,'wrist')
    scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated')}
    scene['objects'][0]['frame']='robot_base'
    rows += [{**r,'object_id':'table'}for r in rows]
    active,report=selected(scene,rows)
    assert ('base','robot_base')not in active
    assert ('camera','side')not in active


def test_disconnected_camera_cannot_borrow_unrelated_anchor():
    scene,rows=fixture()
    other=copy.deepcopy(scene['cameras'][0]);other['id']='reference';other['pose']['provenance']='calibrated';scene['cameras'].append(other)
    rows.append({**rows[0],'camera':'reference','image_id':'ref','object_id':'table'})
    assert ('camera','side')not in selected(scene,rows)[0]


def test_moving_base_cannot_use_disconnected_fixed_camera_as_world_anchor():
    from real2sim_builder.scene import value
    scene,rows=fixture(5,'wrist')
    scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated')}
    other=copy.deepcopy(scene['cameras'][0]);other['id']='reference';other['pose']['provenance']='calibrated';scene['cameras'].append(other)
    rows.append({**rows[0],'camera':'reference','camera_type':'side','image_id':'ref','object_id':'table'})
    assert ('base','robot_base')not in selected(scene,rows)[0]


def test_sphere_rotation_freezes_but_asymmetric_collision_is_preserved():
    scene,rows=fixture(2);obj=scene['objects'][1];obj['visual']={'type':'sphere'};obj['collision']={'type':'sphere'}
    obj['pose']['value'][2][3]=.2
    assert selected(scene,rows)[0]['object','block']==[0,1,2]
    obj['collision']={'type':'box'}
    assert selected(scene,rows)[0]['object','block']==list(range(6))


def test_world_only_cloud_fits_object_with_fixed_camera_but_cannot_refit_camera():
    scene,rows=fixture();rows[0]['has_raw_depth']=False
    scene['cameras'][0]['pose']['provenance']='calibrated'
    assert ('object_support','block')in selected(scene,rows)[0]
    scene['cameras'][0]['pose']['provenance']='estimated'
    rows.append({**rows[0],'object_id':'table'})
    active,report=selected(scene,rows)
    assert ('camera','side')not in active
    assert any(r['reason']=='raw_camera_rays_required'for r in report['frozen'])


def test_native_single_view_keeps_unanchored_camera_and_returns_actionable_need(tmp_path):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder.calibration.hybrid import fit_scene
    from real2sim_builder.scene import camera_calibration_signature
    from real2sim_builder.files import write
    project,truth,scene=rendered_fixture(tmp_path)
    evidence=project.evidence
    evidence['images']=[i for i in evidence['images']if i['camera']=='side']
    write(project.root/'input/evidence.yaml',evidence)
    scene['reconstruction_observations']['clouds']=scene['reconstruction_observations']['clouds'][:1]
    scene['view_registrations']={k:v for k,v in scene['view_registrations'].items()if v['camera']=='side'}
    camera=scene['cameras'][0];camera['pose']['provenance']='estimated'
    for binding in scene['view_registrations'].values():binding['camera_signature']=camera_calibration_signature(scene,camera)
    original=copy.deepcopy(camera)
    fitted,report=fit_scene(project,scene,project.root/'scratch/limited',{'max_iterations':1,'max_evaluations':30})
    assert fitted['cameras'][0]==original and report['observability']['needs']
    assert all(r['action']for r in report['observability']['geometry']['frozen']if r['reason']!='uniform_primitive_rotation_symmetry')


def test_native_camera_requires_pixels_even_when_optical_points_are_available(tmp_path):
    from test_multiview_pipeline import rendered_fixture
    from real2sim_builder.calibration.hybrid import fit_scene
    from real2sim_builder.scene import camera_calibration_signature
    from real2sim_builder.files import sha
    project,truth,scene=rendered_fixture(tmp_path)
    camera=scene['cameras'][0];camera['pose']['provenance']='estimated'
    scene['objects'][1]['pose']['provenance']='calibrated'
    for binding in scene['view_registrations'].values():
        if binding['camera']=='side':binding['camera_signature']=camera_calibration_signature(scene,camera)
    for row in scene['reconstruction_observations']['clouds']:
        path=project.root/row['path']
        with np.load(path)as data:raw={k:data[k]for k in ('points_world_m','points_camera_relative')}
        np.savez(path,**raw);row['sha256']=sha(path)
    original=copy.deepcopy(camera)
    fitted,report=fit_scene(project,scene,project.root/'scratch/no-pixels',{'max_iterations':1,'max_evaluations':15})
    assert fitted['cameras'][0]==original
    assert any(r['kind']=='camera'and r['reason']=='raw_camera_rays_required'
        for r in report['observability']['geometry']['frozen'])
