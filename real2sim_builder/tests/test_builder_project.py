"""Original Builder project/candidate/evidence meaning in new owning module."""
import copy,json
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from real2sim_builder.project import Project,Candidate,read,write,sha,empty,value,validate,world_pose,frame_world,local_path,apply,rollback,add_image,import_metadata


def measured_scene():
    scene=empty('Synthetic measured workspace')
    def obj(name,role,dimensions,xyz):
        t=np.eye(4);t[:3,3]=xyz
        return {'id':name,'role':role,'frame':'world','pose':value(t.tolist(),'measured'),'dimensions':value(dimensions,'measured'),'visual':{'type':'box'},'collision':{'type':'box'},'color':value([.6,.3,.2],'measured'),'physics':{'mass_kg':value(None),'friction':value(.1,'measured')}}
    scene['objects']=[obj('table','support_surface',[1,.8,.04],[0,0,-.02]),obj('block','manipulable_object',[.06]*3,[0,0,.03])]
    t=np.eye(4);t[:3,:3]=[[1,0,0],[0,-1,0],[0,0,-1]];t[:3,3]=[0,0,1]
    scene['cameras']=[{'id':'side','frame':'world','pose':value(t.tolist(),'calibrated'),'K':value([[160.,0,80.],[0,160.,60.],[0,0,1]],'calibrated'),'resolution':[160,120],'distortion':value([0.]*5,'calibrated')}]
    return scene


def test_saved_project_reload_and_input_hash_ownership(tmp_path):
    project=Project.create(tmp_path/'projects','Fixture');project.save_scene(measured_scene());source=tmp_path/'image.png';Image.new('RGB',(160,120),'blue').save(source);original=source.read_bytes()
    row=add_image(project,source);loaded=Project(project.root)
    assert loaded.info['schema']=='real2sim.project/1' and loaded.scene==project.scene
    assert loaded.evidence['images'][0]['sha256']==sha(source) and source.read_bytes()==original
    assert loaded.signature()==project.signature() and row['path'].startswith('input/')
    validate(loaded.scene,loaded.root,complete=True)


def test_candidate_isolated_edit_scope_reject_and_stale_signature(tmp_path):
    p=Project.create(tmp_path,'Fixture');scene=measured_scene();scene['objects'][1]['pose']['provenance']='estimated';p.save_scene(scene);before=sha(p.root/'working/current_scene.yaml')
    c=Candidate.create(p,'candidate',target_object='block',allow=['pose'])
    new=c.scene;new['objects'][1]['pose']['value'][0][3]=.02;c.save(new)
    assert sha(p.root/'working/current_scene.yaml')==before and c.scene!=p.scene
    wrong=c.scene;wrong['objects'][0]['dimensions']['value'][0]=2
    with pytest.raises(ValueError):c.save(wrong)
    c.reject();assert c.info['status']=='REJECTED'
    with pytest.raises(ValueError):c.save(new)


def test_candidates_require_current_evaluation_and_keep_rollback(tmp_path):
    p=Project.create(tmp_path,'Fixture');p.save_scene(measured_scene());c=Candidate.create(p,'candidate');scene=c.scene
    scene['lights']['ambient']=value([.2]*3,'estimated');c.save(scene)
    write(c.root/'metrics.json',{'input_signature':p.signature(scene),'images':[{'image':'fixture'}],'passed':False,'scope':'train comparison'})
    assert c.promote()['status']=='PROMOTED' and p.scene['lights']['ambient']['value']==[.2]*3
    assert rollback(p)['status']=='ROLLED_BACK' and p.scene['lights']['ambient']['value']==[.3]*3
    assert p.state['status']=='DRAFT'


def test_measurement_conflict_never_overwrites_previous_measured_value(tmp_path):
    p=Project.create(tmp_path/'projects','Fixture');path=tmp_path/'measurement.yaml';write(path,{'units':'mm','objects':[{'id':'block','dimensions':[24]*3}]});import_metadata(p,path)
    original=sha(p.root/'working/current_scene.yaml');write(path,{'units':'mm','objects':[{'id':'block','dimensions':[30,24,24]}]})
    with pytest.raises(ValueError,match='Conflicting'):import_metadata(p,path)
    assert sha(p.root/'working/current_scene.yaml')==original and list((p.root/'working/measurement_conflicts').glob('*.json'))


def test_original_saved_project_is_read_only_when_opened_explicitly(tmp_path):
    p=Project.create(tmp_path,'Fixture');p.save_scene(measured_scene());before={x:sha(x) for x in p.root.rglob('*') if x.is_file()}
    readonly=Project(p.root,read_only=True)
    assert readonly.scene==p.scene
    for call in [lambda:readonly.save_scene(readonly.scene),lambda:readonly.update(status='DRAFT'),lambda:readonly.control('stop'),lambda:Candidate.create(readonly,'new')]:
        with pytest.raises(PermissionError):call()
    assert before=={x:sha(x) for x in p.root.rglob('*') if x.is_file()}


def test_original_scene_frames_and_provenance_validation_boundaries(tmp_path):
    scene=measured_scene();validate(scene,complete=True)
    malformed=copy.deepcopy(scene);malformed['objects'][0]['dimensions']['provenance']='guessed_truth'
    with pytest.raises(ValueError):validate(malformed)
    malformed=copy.deepcopy(scene);malformed['frames']['world']['parent']='world'
    with pytest.raises(ValueError):validate(malformed)
    with pytest.raises(ValueError):local_path(tmp_path,'../outside')
    with pytest.raises(ValueError):local_path(tmp_path,'/etc/passwd')


@pytest.fixture
def scene():
    return measured_scene()

from real2sim_builder.project import preserve,check_scope,nonregression,add_video,extract_videos
from real2sim_builder.reconstruction import run,import_scan,initialize


# Original offline cases: test_core.py
def test_video_frames_and_timestamps_are_imported_automatically(tmp_path):
    import cv2
    source = tmp_path / 'clip.avi'
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*'MJPG'), 10.0, (64, 48))
    if not writer.isOpened():
        pytest.skip('MJPG codec unavailable')
    for i in range(10):
        writer.write(np.full((48, 64, 3), i * 20, np.uint8))
    writer.release()
    project = Project.create(tmp_path / 'projects', 'Video')
    add_video(project, source, split='validation', max_frames=4)
    extract_videos(project)
    images = project.evidence['images']
    assert len(images) == 4 and all((i['split'] == 'validation' for i in images))
    assert [i['timestamp'] for i in images] == [0, 0.3, 0.6, 0.9]
    extract_videos(project)
    assert len(project.evidence['images']) == 4

def test_stop_then_resume_uses_saved_scene(tmp_path, scene):
    from real2sim_builder.reconstruction import run
    project = Project.create(tmp_path, 'Resume')
    project.save_scene(scene)
    project.control('stop')
    result = run(project)
    assert result['status'] == 'STOPPED'
    result = run(project)
    assert result['status'] == 'NEEDS_MORE_DATA'
    assert project.scene == scene
    assert not (project.root / 'working/run.lock').exists()

def test_pause_checkpoint_waits_for_resume(tmp_path):
    import threading, time
    project = Project.create(tmp_path, 'Pause')
    project.update(status='RUNNING')
    project.control('pause')
    worker = threading.Thread(target=project.checkpoint)
    worker.start()
    try:
        deadline = time.monotonic() + 2
        while project.state['status'] != 'PAUSED' and time.monotonic() < deadline:
            time.sleep(0.01)
        assert project.state['status'] == 'PAUSED' and worker.is_alive()
        project.control('resume')
        worker.join(timeout=2)
        assert not worker.is_alive() and project.state['status'] == 'RUNNING'
    finally:
        if worker.is_alive():
            project.control('stop')
            worker.join(timeout=2)

# Original offline cases: test_agent_toolkit.py
def setup_project(tmp_path, scene):
    p = Project.create(tmp_path, 'Agent test')
    p.save_scene(scene)
    image = tmp_path / 'image.png'
    Image.fromarray(np.full((120, 160, 3), 80, np.uint8)).save(image)
    add_image(p, image, 'side')
    return p

def test_edit_protection_and_reject(tmp_path, scene):
    p = setup_project(tmp_path, scene)
    before = (p.root / 'working/current_scene.yaml').read_bytes()
    c = Candidate.create(p, 'trial')
    with pytest.raises(ValueError, match='Protected'):
        c.edit([{'op': 'update_dimensions', 'id': 'block', 'value': [0.1, 0.1, 0.1]}])
    c.edit([{'op': 'add_object', 'id': 'new_bin', 'role': 'receptacle', 'dimensions': [0.2, 0.2, 0.1]}])
    assert c.scene['objects'][-1]['dimensions']['provenance'] == 'estimated'
    c.reject()
    assert (p.root / 'working/current_scene.yaml').read_bytes() == before
    with pytest.raises(ValueError, match='not open'):
        c.edit([])

def test_stale_candidate_and_report_rejected(tmp_path, scene):
    p = setup_project(tmp_path, scene)
    c = Candidate.create(p, 'trial')
    c.evaluate('mujoco')
    c.edit([{'op': 'set_lighting', 'ambient': [0.4] * 3}])
    with pytest.raises(ValueError, match='stale'):
        c.promote()
    c.evaluate('mujoco')
    changed = p.scene
    changed['lights']['ambient']['value'] = [0.2] * 3
    p.save_scene(changed)
    with pytest.raises(ValueError, match='base is stale'):
        c.promote()

def test_promotion_exception_restores_canonical(tmp_path, scene, monkeypatch):
    p = setup_project(tmp_path, scene)
    c = Candidate.create(p, 'rollback_failure')
    c.edit([{'op': 'set_lighting', 'ambient': [0.5] * 3}])
    c.evaluate('mujoco')
    before = p.scene
    monkeypatch.setattr(p, 'update', lambda **kwargs: (_ for _ in ()).throw(RuntimeError('injected state write failure')))
    with pytest.raises(RuntimeError, match='injected'):
        c.promote()
    assert p.scene == before and c.info['status'] == 'OPEN'

def test_no_measured_nested_overwrite():
    from real2sim_builder.project import preserve
    with pytest.raises(ValueError, match='Protected'):
        preserve({'material': {'roughness': value(0.2, 'measured')}}, {'material': {}})

def test_unsynchronized_blend_cannot_promote(tmp_path, scene):
    p = setup_project(tmp_path, scene)
    c = Candidate.create(p, 'unsafe_blend')
    c.evaluate('mujoco')
    (c.root / 'candidate.blend').write_bytes(b'changed authoring scene')
    with pytest.raises(ValueError, match='synchronization'):
        c.promote()

# Original offline cases: test_v2_toolkit.py
def project(tmp_path, scene):
    p = Project.create(tmp_path / 'projects', 'V2 fixture')
    p.save_scene(scene)
    return p

def test_object_scope_rejects_shared_and_foreign_changes(tmp_path, scene):
    scene['objects'][1]['pose']['provenance'] = 'estimated'
    p = project(tmp_path, scene)
    c = Candidate.create(p, 'cup_scoped', 'block', ['pose'])
    t = copy.deepcopy(c.scene['objects'][1]['pose']['value'])
    t[0][3] = 0.02
    c.edit([{'op': 'update_pose', 'id': 'block', 'value': t}])
    assert p.scene == scene
    with pytest.raises(ValueError, match='Locked'):
        c.edit([{'op': 'set_lighting', 'ambient': [0.9] * 3}])
    bad = c.scene
    bad['cameras'][0]['resolution'] = [320, 240]
    with pytest.raises(ValueError, match='Locked'):
        c.save(bad)
    assert c.info['scope']['target_object'] == 'block'
    c.reject()
    assert p.scene == scene

def test_direct_save_cannot_overwrite_measurements(tmp_path, scene):
    p = project(tmp_path, scene)
    c = Candidate.create(p, 'protected')
    s = c.scene
    s['objects'][1]['dimensions']['value'] = [1, 1, 1]
    with pytest.raises(ValueError, match='Protected'):
        c.save(s)

def test_object_holdout_and_missing_view_block_global_gain():
    a = {'multipose': {s: {'count': 8, 'rmse_px': 2.0, 'behind_camera': 0} for s in ('train', 'validation')}, 'images': [{'image': 'held', 'split': 'validation', 'mae': 0.1, 'silhouettes': [], 'objects': [{'object': 'cup', 'landmark_rmse_px': 2}]}]}
    b = copy.deepcopy(a)
    b['multipose']['train']['rmse_px'] = 1.0
    b['images'][0]['mae'] = 0.09
    b['images'][0]['objects'][0]['landmark_rmse_px'] = 10
    assert not nonregression(a, b)['passed']
    b = copy.deepcopy(a)
    b['multipose']['train']['rmse_px'] = 1.0
    b['images'] = []
    assert not nonregression(a, b)['passed']

def test_sim_only_offsets_do_not_rewrite_recorded_joint_evidence(tmp_path, scene):
    from real2sim_builder.calibration.geometry import link_transforms, simulation_offsets
    from real2sim_builder.project import observation_scene
    from real2sim_builder.project import validate
    p = project(tmp_path, scene)
    urdf = p.root / 'input/robot.urdf'
    urdf.write_text('<robot name="offset"><link name="base"/><link name="arm"/><joint name="j" type="revolute"><parent link="base"/><child link="arm"/><axis xyz="0 0 1"/><origin xyz=".1 0 0"/></joint></robot>')
    s = p.scene
    s['robot_model'] = {'path': 'input/robot.urdf', 'format': 'urdf', 'joint_names': ['j'], 'simulation_joint_offsets_rad': value([0.1], 'optimized', ['synthetic hypothesis'])}
    s['frames']['robot_base'] = {'parent': 'world', 'transform': value(np.eye(4).tolist(), 'estimated')}
    o = {'session_id': 'synthetic', 'eligible': True, 'joint_names': ['j'], 'q_measured': [0.3]}
    old = copy.deepcopy(o)
    digest = sha(urdf)
    posed = observation_scene(s, o, p.root)
    assert np.allclose(posed['frames']['robot_link_arm']['transform']['value'], link_transforms(urdf, {'j': 0.4})['arm'])
    assert o == old and sha(urdf) == digest
    s['robot_model']['simulation_joint_offsets_rad']['value'] = [2.0]
    with pytest.raises(ValueError, match='bounded'):
        validate(s, p.root)

def test_invalid_scope_does_not_leave_candidate_directory(tmp_path, scene):
    p = project(tmp_path, scene)
    with pytest.raises(ValueError, match='Unknown target'):
        Candidate.create(p, 'invalid', 'absent', ['pose'])
    assert not (p.root / 'scratch/agent/invalid').exists()

# Original offline cases: test_scan_initialization.py
def measured_pair_scene():
    s = empty('distorted cups')
    for name, position in [('cup_a', [0.094, -0.045, 0.116]), ('cup_b', [0.107, 0.032, 0.115])]:
        pose = np.eye(4)
        pose[:3, 3] = position
        geometry = {'type': 'container', 'round': True, 'wall': value(0.004, 'estimated')}
        s['objects'].append(dict(id=name, role='receptacle', frame='world', pose=value(pose.tolist(), 'estimated'), dimensions=value([0.07, 0.07, 0.065], 'measured', ['user dimensions']), visual=copy.deepcopy(geometry), collision=geometry, color=value([0.9] * 3, 'estimated'), physics={'mass_kg': value(None), 'friction': value(None)}))
    s['scan_initialization'] = {'registration': {'status': 'NEEDS_MORE_DATA', 'scale': 0.3146254628948635, 'metric_scale_verified': False}}
    return s

def measured_pair_constraints():
    return {'schema': 'real2sim.geometry-constraints/1', 'units': 'mm', 'distances': [{'objects': ['cup_a', 'cup_b'], 'distance_m': 90.0, 'rim_gap_m': 20.0, 'same_support_plane': True, 'source': 'measured', 'evidence': ['user: same plane, top diameter 70mm, gap 20mm']}]}

def test_measured_constraints_change_scene_preserve_gauge_and_unknown_world():
    from real2sim_builder.reconstruction import apply_geometry_constraints
    from real2sim_builder.project import world_pose, geometry_constraint_metrics
    s = measured_pair_scene()
    original = copy.deepcopy(s)
    revised, report = apply_geometry_constraints(s, measured_pair_constraints())
    before = np.array([world_pose(s, o)[:3, 3] for o in s['objects']])
    after = np.array([world_pose(revised, o)[:3, 3] for o in revised['objects']])
    assert np.allclose(before.mean(0), after.mean(0))
    assert np.isclose(np.linalg.norm(after[1] - after[0]), 0.09) and np.isclose(after[0, 2], after[1, 2])
    assert np.allclose((before[1] - before[0])[:2] / np.linalg.norm((before[1] - before[0])[:2]), (after[1] - after[0])[:2] / 0.09)
    metrics = geometry_constraint_metrics(revised, revised['geometry_constraints']['distances'][0])
    assert abs(metrics['rim_gap_m'] - 0.02) < 1e-12 and metrics['derived_distance_m'] == pytest.approx(0.09)
    assert report['constraints'][0]['scan_conflict']
    assert s == original and revised['scan_initialization']['registration'] == s['scan_initialization']['registration']
    assert all((o['pose']['provenance'] == 'estimated' for o in revised['objects']))
    assert all((o['dimensions'] == old['dimensions'] for o, old in zip(revised['objects'], s['objects'])))

def test_constraints_reject_inconsistent_derived_gap_and_locked_poses(tmp_path):
    from real2sim_builder.reconstruction import constrain, apply_geometry_constraints
    p = Project.create(tmp_path / 'projects', 'conflict')
    c = Candidate.create(p, 'pair')
    c.save(measured_pair_scene())
    config = measured_pair_constraints()
    config['distances'][0]['distance_m'] = 78.25
    path = tmp_path / 'relative.yaml'
    write(path, config)
    before = sha(c.root / 'candidate_scene.yaml')
    report = constrain(c, path)
    assert report['status'] == 'CONFLICT' and 'diameters plus rim gap' in report['reason']
    assert sha(c.root / 'candidate_scene.yaml') == before
    s = measured_pair_scene()
    for o in s['objects']:
        o['pose']['provenance'] = 'measured'
    with pytest.raises(ValueError, match='locked measured'):
        apply_geometry_constraints(s, measured_pair_constraints())

def test_future_scene_edits_cannot_break_relative_measurements_but_pair_can_translate():
    from real2sim_builder.reconstruction import apply_geometry_constraints
    s, _ = apply_geometry_constraints(measured_pair_scene(), measured_pair_constraints())
    both = copy.deepcopy(s)
    for o in both['objects']:
        o['pose']['value'][0][3] += 0.02
    validate(both)
    broken = copy.deepcopy(s)
    broken['objects'][0]['pose']['value'][0][3] += 0.005
    with pytest.raises(ValueError, match='geometry constraint violated'):
        validate(broken)
    from real2sim_builder.project import apply
    with pytest.raises(ValueError, match='camera audit'):
        apply(s, [{'op': 'update_pose', 'id': 'cup_a', 'value': both['objects'][0]['pose']['value']}], None)

def test_initialization_enforces_existing_measured_distance(tmp_path):
    import trimesh
    from real2sim_builder.project import import_metadata
    p = Project.create(tmp_path / 'projects', 'pair scan')
    source = tmp_path / 'cups.glb'
    scan_scene = trimesh.Scene()
    for i in range(2):
        scan_scene.add_geometry(trimesh.creation.box(extents=[0.06, 0.06, 0.05]), node_name='cup' + str(i), transform=trimesh.transformations.translation_matrix([i * 0.078, 0, 0]))
    source.write_bytes(scan_scene.export(file_type='glb'))
    scan = import_scan(p, source)
    measurements = tmp_path / 'measurements.yaml'
    write(measurements, {'units': 'm', 'objects': [{'id': 'cup_a', 'role': 'receptacle', 'dimensions': [0.07, 0.07, 0.065]}, {'id': 'cup_b', 'role': 'receptacle', 'dimensions': [0.07, 0.07, 0.065]}], 'distances': [{'objects': ['cup_a', 'cup_b'], 'distance_m': 0.09, 'source': 'measured', 'evidence': ['fixture']}]})
    import_metadata(p, measurements)
    c = Candidate.create(p, 'initialized')
    config = tmp_path / 'scan.yaml'
    write(config, {'schema': 'real2sim.scan-initialization/1', 'registration': registered(), 'objects': [{'id': 'cup_a', 'role': 'receptacle', 'shape': 'container', 'roi_scan': [[-0.031, -0.031, -0.026], [0.031, 0.031, 0.026]], 'wall_m': 0.002}, {'id': 'cup_b', 'role': 'receptacle', 'shape': 'container', 'roi_scan': [[0.047, -0.031, -0.026], [0.109, 0.031, 0.026]], 'wall_m': 0.002}]})
    before = sha(p.root / 'working/current_scene.yaml')
    report = initialize(c, scan['id'], config)
    assert report['status'] == 'INITIALIZED_ESTIMATED'
    assert report['distance_comparison'][0]['candidate_distance_m'] == pytest.approx(0.09)
    assert report['geometry_constraints']['constraints'][0]['scan_conflict']
    assert sha(p.root / 'working/current_scene.yaml') == before

def test_constraints_keep_scan_mesh_only_as_visual_prior():
    from real2sim_builder.reconstruction import apply_geometry_constraints
    s = measured_pair_scene()
    s['assets']['oldmesh'] = {'path': 'input/assets/old.obj'}
    s['objects'][0]['visual'] = {'type': 'mesh', 'asset': 'oldmesh'}
    config = measured_pair_constraints()
    config['measured_visuals'] = ['cup_a']
    revised, _ = apply_geometry_constraints(s, config)
    assert revised['objects'][0]['visual']['type'] == 'container'
    assert revised['objects'][0]['scan_visual_prior'] == s['objects'][0]['visual']
    assert revised['assets'] == s['assets']
    repeated, _ = apply_geometry_constraints(revised, config)
    assert repeated['objects'][0]['scan_visual_prior'] == s['objects'][0]['visual']

from test_builder_reconstruction import glb,registered


def test_unmarked_original_projects_are_view_only_and_clone_is_explicit(tmp_path):
    from real2sim_builder.project import clone_project
    p=Project.create(tmp_path/'projects','Original');p.save_scene(measured_scene());(p.root/'working/owner.json').unlink()
    before={str(x.relative_to(p.root)):sha(x) for x in p.root.rglob('*') if x.is_file()}
    assert Project(p.root).read_only
    with pytest.raises(PermissionError):Project(p.root,read_only=False)
    with pytest.raises(PermissionError):Candidate.create(Project(p.root),'forbidden')
    clone=clone_project(p.root,tmp_path/'clone');assert not clone.read_only and clone.scene==p.scene
    c=Candidate.create(clone,'new');c.reject()
    assert Project(clone.root).read_only is False
    assert before=={str(x.relative_to(p.root)):sha(x) for x in p.root.rglob('*') if x.is_file()}
    with pytest.raises((FileExistsError,ValueError)):clone_project(p.root,tmp_path/'clone')
    with pytest.raises(ValueError):clone_project(p.root,p.root/'nested')


def test_working_scene_schema_and_capture_schema_never_alias():
    from real2sim_builder.project import SCHEMA
    assert SCHEMA=='real2sim.scene/1'
    assert empty('scene')['schema']=='real2sim.scene/1'


def test_read_only_candidate_direct_save_cannot_bypass_project_guard(tmp_path):
    p=Project.create(tmp_path,'Candidate');p.save_scene(measured_scene());c=Candidate.create(p,'candidate');before=sha(c.root/'candidate_scene.yaml')
    viewed=Candidate(Project(p.root,read_only=True),'candidate');scene=viewed.scene;scene['lights']['ambient']=value([.1]*3,'estimated')
    with pytest.raises(PermissionError):viewed.save(scene)
    assert sha(c.root/'candidate_scene.yaml')==before


def test_clone_never_treats_a_locked_project_as_a_frozen_source(tmp_path):
    from real2sim_builder.project import clone_project
    p=Project.create(tmp_path/'source','source');p.save_scene(measured_scene());write(p.root/'working/run.lock',{'owner':'unresolved'})
    with pytest.raises(RuntimeError):clone_project(p.root,tmp_path/'copy')
    assert not (tmp_path/'copy').exists()


def test_readonly_empty_evidence_analysis_and_rectification_never_write(tmp_path):
    from real2sim_builder.project import Project,write
    from real2sim_builder.reconstruction import analyze
    from real2sim_builder.calibration.geometry import undistort_evidence
    from test_builder_export import legacy_scene
    project=Project.create(tmp_path/'projects','guarded');scene=legacy_scene();scene['cameras'][0]['distortion']['value'][0]=.1;project.save_scene(scene)
    readonly=Project(project.root,read_only=True);before={p:p.read_bytes() for p in project.root.rglob('*') if p.is_file()}
    with pytest.raises(PermissionError):analyze(readonly)
    with pytest.raises(PermissionError):undistort_evidence(readonly)
    assert before=={p:p.read_bytes() for p in project.root.rglob('*') if p.is_file()}
