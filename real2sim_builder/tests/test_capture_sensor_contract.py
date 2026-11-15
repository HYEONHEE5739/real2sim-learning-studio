"""Capture producers and sensor consumers share measured identity, without hardware."""
import copy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from real2sim_builder.capture import (
    import_paired,
    import_session,
    import_snapshots,
    load_session,
    observation_scene,
)
from real2sim_builder.files import read, sha, write
from real2sim_builder.observations import register_sensor_views, registered_images
from real2sim_builder.project import Candidate, Project
from real2sim_builder.reconstruction_stages import register_stage_sensors
from real2sim_builder.scene import value, world_pose
from real2sim_builder.stage_artifacts import digest
from robot_learning_workbench.robot.calibration import (
    JOINTS,
    PrecisionMapper,
    fit_joint,
    native_from_raw,
    review_joint,
)
from robot_learning_workbench.robot.capture import save_session, snapshot_state
from robot_learning_workbench.robot.snapshots import SnapshotStore


def _robot(tmp_path):
    model = tmp_path / 'robot.urdf'
    xml = ['<robot name="synthetic"><link name="base"/>']
    parent = 'base'
    for index, name in enumerate(JOINTS):
        link = 'link_' + str(index)
        xml.append(
            f'<link name="{link}"/><joint name="{name}" type="revolute">'
            f'<parent link="{parent}"/><child link="{link}"/>'
            '<origin xyz=".03 .01 .04"/><axis xyz="0 0 1"/>'
            '<limit lower="-2" upper="2" effort="1" velocity="1"/></joint>'
        )
        parent = link
    model.write_text(''.join(xml) + '</robot>')
    entries = {}
    for index, name in enumerate(JOINTS):
        spec = {
            'resolution': 4096,
            'mode': 'DEGREES',
            'apply_drive_mode': False,
            'calibration_hash': 'a' * 64,
            'calibration': {'id': index + 1, 'range_min': 0, 'range_max': 4095,
                            'drive_mode': 0, 'homing_offset': 0},
        }
        refs = [
            {'joint': name, 'raw': raw, 'angle_rad': angle, 'split': 'train',
             'calibration_hash': spec['calibration_hash']}
            for raw, angle in ((1800, -.25), (2300, .25))
        ]
        # Reviewed legacy state isolates BUG-003 from the separate manual-state bug.
        entries[name] = review_joint(fit_joint(refs, spec, name, [-2, 2]))
    mapper = PrecisionMapper({
        'schema': 'so101.precision-calibration/1', 'urdf_sha256': sha(model),
        'role': 'follower', 'identity': {'id': 'memory_only'},
        'joints': entries, 'physical_verified': False,
    })
    return model, mapper


def _rgb():
    # Several-pixel edges have a nonzero Laplacian (unlike a 1px checkerboard).
    pattern = ((np.indices((480, 640)).sum(0) // 7) % 2 * 255).astype(np.uint8)
    return np.repeat(pattern[..., None], 3, axis=2)


def _package_camera_scene():
    side = np.eye(4)
    side[:3, 3] = [.6, -.3, .8]
    mount = np.eye(4)
    mount[:3, 3] = [.02, 0, .04]
    frames = {
        'world': {'parent': None, 'T_parent_from_frame': np.eye(4).tolist()},
        'robot_base': {'parent': 'world', 'T_parent_from_frame': np.eye(4).tolist()},
        'side_optics': {'parent': 'world', 'T_parent_from_frame': side.tolist()},
        'wrist_optics': {'parent': 'robot_link_link_5', 'T_parent_from_frame': mount.tolist()},
    }
    # The writer consumes the exported Scene frame contract, including state.
    frames['robot_link_link_5'] = {
        'parent': 'robot_base', 'T_parent_from_frame': np.eye(4).tolist(),
    }
    for frame in frames.values():
        frame['state'] = 'reference'
    cameras = {
        name: {'frame_id': name + '_optics', 'resolution': [640, 480],
               'K': [[400., 0, 320.], [0, 400., 240.], [0, 0, 1.]],
               'distortion': [0.] * 5}
        for name in ('side', 'wrist')
    }
    return SimpleNamespace(scene={'frames': frames, 'cameras': cameras})


def _bind_manifest(manifest):
    package = _package_camera_scene().scene
    manifest['robot'].update(format='urdf', T_world_base=np.eye(4).tolist())
    for camera in manifest['cameras']:
        source = package['cameras'][camera['id']]
        frame = package['frames'][source['frame_id']]
        camera.update(parent=frame['parent'].removeprefix('robot_link_'),
                      K=source['K'], distortion=source['distortion'],
                      T_parent_camera=frame['T_parent_from_frame'])


def _write_capture(tmp_path, model, mapper, *, bound):
    source = tmp_path / 'continuous_capture'
    q = [[-.2] * 6, [.3] * 6]
    save_session(
        source, model=model, mapping=mapper.metadata(),
        samples=[{'id': f'pose_{i}', 'timestamp_ns': 1_000_000_000 + i * 1_000_000_000,
                  'q_measured': pose} for i, pose in enumerate(q)],
        images=[{'side': _rgb(), 'wrist': _rgb()} for _ in q],
        metadata={'scene_state_id': 'layout'},
        scene=_package_camera_scene() if bound else None,
    )
    # Continuous recording deliberately has no static approval. Supply explicit
    # synthetic static evidence before freezing this fixture, never on user data.
    manifest = read(source / 'capture_manifest.yaml')
    samples = read(source / manifest['samples'])
    for sample in samples:
        sample['quality'] = {'eligible_for_calibration': True}
    write(source / manifest['samples'], samples)
    write(source / manifest['events'], [{'timestamp_ns': 0, 'event': 'static_hold'}])
    for key in ('samples', 'events'):
        manifest['files'][manifest[key]] = sha(source / manifest[key])
    write(source / 'capture_manifest.yaml', manifest)
    load_session(source)
    return source


def _write_snapshot(tmp_path, model, mapper, *, paired, bound):
    writer_project = Project.create(tmp_path / 'writer', 'snapshot producer')
    store = SnapshotStore(writer_project, session_id='session', model=model,
                          mapping=mapper.metadata())
    stamp = 2_000_000_000
    raw = dict.fromkeys(JOINTS, 2000)
    specs = {name: entry['motor'] for name, entry in mapper.profile['joints'].items()}
    native = {name: native_from_raw(raw[name], specs[name]) for name in JOINTS}
    interval = {'start': {'monotonic_ns': stamp - 1}, 'end': {'monotonic_ns': stamp}}
    history = [{'timestamp_ns': stamp - (6 - i) * 100_000_000, 'native': native,
                'raw': raw, 'feedback_interval': interval} for i in range(7)]
    packets = {name: {'read_start': {'monotonic_ns': stamp - 2_000_000},
                     'read_end': {'monotonic_ns': stamp - 1_000_000}, 'sequence': 1}
               for name in ('side', 'wrist')}
    device = SimpleNamespace(precision_mapper=mapper, motor_specs=specs,
                             identity={'id': 'memory_only'})
    state = snapshot_state(device, history, packets, {
        'stable': True, 'window_start_ns': stamp - 600_000_000, 'window_end_ns': stamp,
    })
    pending = store.prepare('snapshot_one', state,
                            {'real_side': _rgb(), 'real_wrist': _rgb()}, now_ns=stamp)
    if bound:
        path = Path(pending['staging']) / 'capture_manifest.yaml'
        manifest = read(path)
        _bind_manifest(manifest)
        write(path, manifest)
    rendered = None
    if paired:
        rendered = {
            'images': {'side': _rgb(), 'wrist': _rgb()},
            'measured_q_rad': pending['sample']['q_measured'],
            'applied_sim_joint_rad': [q + .01 for q in pending['sample']['q_measured']],
            'scene_identity': {'manifest_sha256': 'b' * 64},
            'engine': 'synthetic', 'sim_timestamp': {'monotonic_ns': stamp},
            'sim_cameras': {}, 'joint_mapping': mapper.metadata(),
        }
    saved = store.finish(pending, rendered=rendered)
    return Path(saved['path'])


def _existing_scene(project, model, mapper, layout, *, names=None):
    from real2sim_builder.evidence import import_robot
    import_robot(project, model, dict.fromkeys(JOINTS, 0.), np.eye(4).tolist())
    scene = project.scene
    scene['robot_model']['mapping'] = mapper.metadata()
    scene['reconstruction_state'] = {'id': layout}
    package = _package_camera_scene().scene
    for name in ('side', 'wrist'):
        source = package['cameras'][name]
        frame = package['frames'][source['frame_id']]
        scene['cameras'].append({
            'id': (names or {}).get(name, name),
            'frame': frame['parent'], 'resolution': source['resolution'],
            'pose': value(frame['T_parent_from_frame'], 'calibrated', ['synthetic mount']),
            'K': value(source['K'], 'calibrated', ['synthetic lens']),
            'distortion': value(source['distortion'], 'calibrated', ['synthetic lens']),
        })
    project.save_scene(scene)


def _source_hashes(source):
    return {path.relative_to(source).as_posix(): sha(path)
            for path in source.rglob('*') if path.is_file()}


def _stage_config():
    anchors = [{'source': 'measured', 'evidence': ['synthetic board dimensions'],
                'observed_corners_camera_m': [[0, 0, 1], [.15, 0, 1], [.15, .12, 1], [0, .12, 1]],
                'dimensions_xy_m': [.15, .12]}]
    return {
        'metric_anchors': anchors,
        'world_registration': {'provenance': 'measured', 'evidence': ['synthetic survey'],
                               'support_to_world': np.eye(4).tolist()},
        'sensor_registration': {'metric_review': {
            'accepted': True, 'anchors_sha256': digest(anchors),
            'evidence': ['synthetic scale review; no physical certification'],
        }},
    }


@pytest.mark.parametrize('kind', ['continuous', 'snapshot', 'pair'])
@pytest.mark.parametrize('bound', [True, False], ids=['bound', 'unbound'])
def test_writer_import_registration_and_stage10_keep_sensor_identity(tmp_path, kind, bound):
    model, mapper = _robot(tmp_path)
    source = (_write_capture(tmp_path, model, mapper, bound=bound) if kind == 'continuous'
              else _write_snapshot(tmp_path, model, mapper, paired=kind == 'pair', bound=bound))
    manifest, samples, _ = load_session(source)
    source_before = _source_hashes(source)
    project = Project.create(tmp_path / 'consumer', 'sensor consumer')
    _existing_scene(project, model, mapper, manifest['scene_state_id'])
    if kind == 'continuous':
        import_session(project, source)
    elif kind == 'snapshot':
        import_snapshots(project, source)
    else:
        import_paired(project, source)
    images = project.evidence['images']
    assert {camera['id']: camera.get('camera_type') for camera in manifest['cameras']} == {
        'side': 'side', 'wrist': 'wrist',
    }
    expected_q = {(sample['id'], image['camera']): image.get('q_measured', sample['q_measured'])
                  for sample in samples for image in sample['images']}
    for image in images:
        assert image.get('robot_model_sha256') == sha(model)
        assert image.get('mapping_sha256') == mapper.metadata()['sha256']
        assert image.get('joint_units') == ['rad'] * 6
        assert image.get('camera_type') == image['camera']
        assert image['joint_names'] == list(JOINTS)
        sample_id = next(sample['id'] for sample in samples
                         if image['id'].endswith('_' + sample['id'] + '_' + image['camera']))
        assert image['q_measured'] == expected_q[(sample_id, image['camera'])]
        assert image['role'] == 'capture'
        if kind == 'pair':
            assert image['runtime_baseline']['sim_q_measured_rad'] != image['q_measured']
            assert image['runtime_baseline']['quality']['physical_verified'] is False
    candidate = Candidate.create(project, 'registration')
    scene_before = copy.deepcopy(candidate.scene)
    immutable = {path: sha(project.root / path) for path in
                 ('working/current_scene.yaml', 'input/evidence.yaml',
                  'scratch/agent/registration/candidate_scene.yaml')}
    result = register_sensor_views(candidate, {}, scene=candidate.scene, persist=False)
    assert result['status'] == 'REGISTERED_ESTIMATED'
    assert len(result['views']) == len(images) and not result['needs']
    assert result['physical_verified'] is False
    folder = candidate.root / 'stage10'
    folder.mkdir()
    scene, report = register_stage_sensors(candidate, _stage_config(), result['scene'],
                                           {6: {'objects': []}}, folder)
    assert report['status'] == 'REGISTERED_ESTIMATED'
    assert not report['missing_capture_ids'] and not report['physical_verified']
    assert scene['cameras'] == scene_before['cameras']
    selected, _, _ = registered_images(project, scene=scene)
    assert len(selected) == len(images)
    side_poses = []
    wrist_poses = []
    from real2sim_builder.calibration.geometry import link_transforms
    for image in selected:
        posed = observation_scene(scene, image, project.root)
        camera = next(camera for camera in posed['cameras'] if camera['id'] == image['camera'])
        pose = world_pose(posed, camera)
        if image['camera_type'] == 'side':
            side_poses.append(pose)
        else:
            fk = link_transforms(model, dict(zip(JOINTS, image['q_measured'])))['link_5']
            mount = next(camera for camera in scene['cameras'] if camera['id'] == image['camera'])
            np.testing.assert_allclose(pose, fk @ np.asarray(mount['pose']['value']))
            wrist_poses.append(pose)
    if kind == 'continuous':
        np.testing.assert_allclose(side_poses[0], side_poses[1])
        assert not np.allclose(wrist_poses[0], wrist_poses[1])
    assert source_before == _source_hashes(source)
    assert all(sha(project.root / path) == stamp for path, stamp in immutable.items())


@pytest.mark.parametrize('bound', [True, False], ids=['bound', 'unbound'])
def test_explicit_roles_survive_nonstandard_ids_and_misleading_filenames(tmp_path, bound):
    model, mapper = _robot(tmp_path)
    source = _write_capture(tmp_path, model, mapper, bound=bound)
    names = {'side': 'rgb_A', 'wrist': 'rgb_B'}
    manifest = read(source / 'capture_manifest.yaml')
    for camera in manifest['cameras']:
        camera['camera_type'] = camera['id']
        camera['id'] = names[camera['id']]
    samples = read(source / manifest['samples'])
    for sample in samples:
        for image in sample['images']:
            image['camera'] = names[image['camera']]
            # Deliberately retain old side/wrist path names. Only metadata owns role.
    write(source / manifest['samples'], samples)
    manifest['files'][manifest['samples']] = sha(source / manifest['samples'])
    write(source / 'capture_manifest.yaml', manifest)
    before = _source_hashes(source)
    project = Project.create(tmp_path / 'projects', 'custom camera IDs')
    _existing_scene(project, model, mapper, 'layout', names=names)
    import_session(project, source)
    assert {image['camera']: image.get('camera_type') for image in project.evidence['images']} == {
        'rgb_A': 'side', 'rgb_B': 'wrist',
    }
    candidate = Candidate.create(project, 'custom_roles')
    result = register_sensor_views(candidate, {}, persist=False)
    assert {row['camera']: row['camera_type'] for row in result['views']} == {
        'rgb_A': 'side', 'rgb_B': 'wrist',
    }
    folder = candidate.root / 'stage10'
    folder.mkdir()
    _, report = register_stage_sensors(candidate, _stage_config(), result['scene'],
                                        {6: {'objects': []}}, folder)
    assert not report['missing_capture_ids'] and report['status'] == 'REGISTERED_ESTIMATED'
    assert before == _source_hashes(source)


@pytest.mark.parametrize('field', ['robot_model_sha256', 'mapping_sha256', 'joint_names', 'joint_units'])
def test_sensor_registration_rejects_measured_identity_conflicts(tmp_path, field):
    model, mapper = _robot(tmp_path)
    source = _write_capture(tmp_path, model, mapper, bound=False)
    project = Project.create(tmp_path / 'projects', 'identity conflict')
    _existing_scene(project, model, mapper, 'layout')
    import_session(project, source)
    evidence = project.evidence
    wrist = next(image for image in evidence['images'] if image['camera'] == 'wrist')
    if field.endswith('sha256'):
        wrist[field] = '0' * 64
    elif field == 'joint_names':
        wrist[field] = list(reversed(wrist[field]))
    else:
        wrist[field] = ['m'] + ['rad'] * 5
    write(project.root / 'input/evidence.yaml', evidence)
    candidate = Candidate.create(project, 'conflict')
    before = sha(candidate.root / 'candidate_scene.yaml')
    source_before = _source_hashes(source)
    with pytest.raises(ValueError, match='identity|units|radian'):
        register_sensor_views(candidate, {}, persist=False)
    assert sha(candidate.root / 'candidate_scene.yaml') == before
    assert source_before == _source_hashes(source)


def test_stage10_accepts_legacy_capture_rows_with_recorded_side_wrist_ids(tmp_path):
    model, mapper = _robot(tmp_path)
    source = _write_capture(tmp_path, model, mapper, bound=False)
    project = Project.create(tmp_path / 'projects', 'legacy observations')
    _existing_scene(project, model, mapper, 'layout')
    import_session(project, source)
    evidence = project.evidence
    for image in evidence['images']:
        # Pre-fix unbound observations already retain all measured identities;
        # their exact stream IDs carry the old writer's fixed sensor semantics.
        image.pop('camera_type', None)
    write(project.root / 'input/evidence.yaml', evidence)
    candidate = Candidate.create(project, 'legacy')
    registered = register_sensor_views(candidate, {}, persist=False)
    assert len(registered['views']) == 4 and not registered['needs']
    folder = candidate.root / 'stage10'
    folder.mkdir()
    _, report = register_stage_sensors(candidate, _stage_config(), registered['scene'],
                                        {6: {'objects': []}}, folder)
    assert report['status'] == 'REGISTERED_ESTIMATED'
    assert not report['missing_capture_ids'] and not report['physical_verified']


@pytest.mark.parametrize('bound', [True, False])
def test_legacy_writer_stream_roles_stay_readable_without_changing_archive(tmp_path, bound):
    model, mapper = _robot(tmp_path)
    source = _write_capture(tmp_path, model, mapper, bound=bound)
    path = source / 'capture_manifest.yaml'
    manifest = read(path)
    for camera in manifest['cameras']:
        camera.pop('camera_type', None)
    write(path, manifest)
    before = _source_hashes(source)
    load_session(source)
    project = Project.create(tmp_path / 'projects', 'old writer')
    _existing_scene(project, model, mapper, 'layout')
    import_session(project, source)
    assert {row['camera_type'] for row in project.evidence['images']} == {'side', 'wrist'}
    assert before == _source_hashes(source)


@pytest.mark.parametrize('bad_role', [None, 'unknown'])
def test_nonstandard_capture_requires_an_explicit_known_sensor_role(tmp_path, bad_role):
    model, mapper = _robot(tmp_path)
    source = _write_capture(tmp_path, model, mapper, bound=False)
    path = source / 'capture_manifest.yaml'
    manifest = read(path)
    for camera in manifest['cameras']:
        camera['id'] = 'rgb_' + camera['id']
        camera.pop('camera_type', None)
        if bad_role is not None:
            camera['camera_type'] = bad_role
    samples = read(source / manifest['samples'])
    for sample in samples:
        for image in sample['images']:
            image['camera'] = 'rgb_' + image['camera']
    write(source / manifest['samples'], samples)
    manifest['files'][manifest['samples']] = sha(source / manifest['samples'])
    write(path, manifest)
    before = _source_hashes(source)
    project = Project.create(tmp_path / 'projects', 'missing sensor role')
    with pytest.raises(ValueError, match='[Cc]amera|[Ss]ensor|role|type'):
        import_session(project, source)
    assert not project.evidence['images']
    assert before == _source_hashes(source)
