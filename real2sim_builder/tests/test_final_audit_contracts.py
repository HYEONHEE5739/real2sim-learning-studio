"""Independent cross-phase contracts found during the final Working Tree audit."""
import copy
import json
from itertools import product

import numpy as np
import pytest
from PIL import Image

from real2sim_builder import observations, reconstruction_stages as stages
from real2sim_builder.calibration import hybrid, joint
from real2sim_builder.calibration.camera import project_point
from real2sim_builder.calibration.geometry import fit, metrics
from real2sim_builder.files import sha, write
from real2sim_builder.scene import camera_calibration_signature, value
from test_builder_calibration import fixture
from test_direct_fit_observation_refresh import _fixture, _move


def test_actual_joint_fit_keeps_stage_world_points_consumable_without_inventing_raw_depth(tmp_path):
    project, candidate, image, raw, _ = _fixture(tmp_path, 'camera')
    picture = tmp_path / 'second.png'
    Image.new('RGB', (160, 120), (10, 80, 60)).save(picture)
    second = observations.register_image(project, picture, camera='side', camera_type='side', scene_state='layout')
    scene = candidate.scene
    scene['view_registrations'][second['id']] = {
        'status': 'REGISTERED_ESTIMATED', 'source_image_sha256': second['sha256'],
        'image_record_sha256': observations.source_record_digest(second), 'scene_state_id': 'layout',
        'camera': 'side', 'camera_signature': camera_calibration_signature(scene, scene['cameras'][0]),
        'T_world_camera': None, 'calibration_evidence': ['synthetic shared Camera']}
    original = candidate.root / 'stage-original.npz'
    pixels = np.array([[45., 35.], [65., 35.], [65., 55.], [45., 55.]])
    np.savez_compressed(original, camera_points=np.c_[pixels / 100, np.ones(4)], uv_processed=pixels)
    mask = candidate.root / 'mask.png'
    Image.new('L', (160, 120), 255).save(mask)
    previous = {2: {'frames': [{'id': second['id'], 'role': 'scene_photo'}],
                    'original_to_processed': [np.eye(3).tolist()]},
                4: {'camera_to_support': np.eye(4).tolist()},
                6: {'objects': [{'id': 'block', 'source_frame_id': second['id'],
                                  'original_points': str(original), 'mask': str(mask)}]}}
    folder = candidate.root / 'stage-clouds'
    folder.mkdir()
    scene = stages.stage_sensor_clouds(candidate, scene, previous, folder,
                                       {'scale': 1., 'support_to_world': np.eye(4).tolist()})
    candidate.save(scene)
    fixed = next(row for row in hybrid.cloud_inputs(project, scene) if row['image_id'] == second['id'])
    fixed_sha = fixed['sha256']
    truth = _move(scene, 'camera', .02)
    evidence = project.evidence
    evidence['landmarks'] = []
    for point in product((-.025, .025), repeat=3):
        row = {'observation': image['id'], 'object': 'block', 'point_m': list(point), 'sigma_px': 1.}
        uv, z = project_point(truth, truth['cameras'][0], row)
        assert z > 0
        evidence['landmarks'].append({**row, 'uv': uv.tolist()})
    write(project.root / 'input/evidence.yaml', evidence)
    protected = {path: sha(path) for path in (raw, original, mask, project.root / 'working/current_scene.yaml')}
    report = candidate.fit('joint:scene', {'objects': [], 'cameras': ['side'], 'external_views': False,
                                           'robot_base': False, 'pose_prior': 0., 'max_nfev': 100})
    assert report['status'] == 'IMPROVED' and report['jacobian_rank'] == report['parameter_count'] == 6
    rows = hybrid.cloud_inputs(project, candidate.scene)
    retained = next(row for row in rows if row['image_id'] == second['id'])
    assert retained['path'] == fixed['path'] and sha(project.root / retained['path']) == fixed_sha
    with np.load(project.root / retained['path'], allow_pickle=False) as data:
        assert 'points_camera_relative' not in data and 'depth_relative' not in data
    assert all(sha(path) == digest for path, digest in protected.items())
    # An unknown legacy World array cannot acquire a fabricated dependency policy.
    unknown = copy.deepcopy(candidate.scene)
    row = next(row for row in unknown['reconstruction_observations']['clouds'] if row['image_id'] == second['id'])
    row.pop('geometry_binding', None)
    unknown['cameras'][0]['pose']['value'][0][3] += .01
    refreshed = hybrid.reproject_observations(project, unknown, {}, candidate.root / 'legacy-refresh')
    with pytest.raises(ValueError, match='stale'):
        hybrid.cloud_inputs(project, refreshed)


def _holdout_problem(tmp_path):
    project, scene = fixture(tmp_path, wrist=True)
    camera = scene['cameras'][0]
    camera['frame'] = 'world'
    camera['K'] = value([[400, 0, 320], [0, 400, 240], [0, 0, 1]], 'optimized')
    pose = np.eye(4)
    pose[:3, 3] = [.03, -.015, .02]
    camera['pose'] = value(pose.tolist(), 'optimized')
    scene['robot_model']['model_sha256'] = sha(project.root / scene['robot_model']['path'])
    evidence = project.evidence
    for index, image in enumerate(evidence['images']):
        path = project.root / ('input/synthetic-' + str(index) + '.png')
        Image.new('RGB', (640, 480), (20 + index * 30, 60, 80)).save(path)
        image.update(camera_type='side', path=path.relative_to(project.root).as_posix(), sha256=sha(path),
                     scene_state_id='layout', resolution=[640, 480], role='capture')
    for row in evidence['landmarks']:
        row['uv'] = project_point(scene, camera, row)[0].tolist()
    write(project.root / 'input/evidence.yaml', evidence)
    return project, scene


@pytest.mark.parametrize('consumer', ['joint_veto', 'joint_report_only', 'pose_metrics'])
def test_consumed_holdout_cannot_be_reused_as_independent_camera_audit(tmp_path, consumer):
    project, truth = _holdout_problem(tmp_path)
    evidence_sha = sha(project.root / 'input/evidence.yaml')
    if consumer.startswith('joint'):
        initial = copy.deepcopy(truth)
        initial['cameras'][0]['pose']['value'][0][3] += .005
        scene, report = joint.fit_joint_scene(project, initial, {
            'cameras': ['camera'], 'objects': [], 'external_views': False, 'pose_prior': 0.,
            'max_nfev': 100, 'holdout_policy': 'report_only' if consumer.endswith('only') else 'veto'})
        assert report['status'] == 'IMPROVED' and report['holdout_after']['count'] == 16
        assert report['independent_verification'] is False
    else:
        scene = truth
        held = [row for row in project.evidence['landmarks'] if row['observation'] == 'pose_3']
        assert metrics(project, scene, held)['count'] == 16
    retained, audit = fit(project, scene, 'quality:camera', {'pixel_uncertainty_px': .1})
    assert audit['status'] == 'NEEDS_MORE_DATA' and 'fresh holdout' in audit['need']
    assert retained == scene
    journal = project.root / 'working/calibration_holdout_usage.jsonl'
    assert 'pose_3' in {identity for line in journal.read_text().splitlines()
                        for identity in json.loads(line)['holdout_observations']}
    assert sha(project.root / 'input/evidence.yaml') == evidence_sha


def test_fresh_fixed_scene_audit_still_reports_its_limited_scope(tmp_path):
    project, scene = _holdout_problem(tmp_path)
    result, report = fit(project, scene, 'quality:camera', {'pixel_uncertainty_px': .1})
    assert report['status'] == 'IMPROVED'
    assert result['cameras'][0]['calibration_quality']['physical_verified'] is False
    assert result['cameras'][0]['pose'] == scene['cameras'][0]['pose']
    assert result['cameras'][0]['K'] == scene['cameras'][0]['K']


def test_repeated_scene_validation_reports_diagnostics_not_independent_geometry_validation(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from real2sim_builder.reconstruction import validate_scene
    project, scene = _holdout_problem(tmp_path)
    # This is a synthetic metric/render contract. Images are returned by an
    # explicit renderer double; the pixel/CAD diagnostics and ledger are real.
    scene['robot_model']['mapping_verified'] = True
    @contextmanager
    def render(project, scene, image, default, folder):
        rgb = np.asarray(Image.open(project.root / image['path']).convert('RGB'))
        yield SimpleNamespace(scene=scene, rgb=lambda _: rgb, mask=lambda *_: np.zeros(rgb.shape[:2], bool))
    monkeypatch.setattr('real2sim_builder.rendering.for_observation', render)
    report, _ = validate_scene(project, scene, SimpleNamespace(engine='mock'), tmp_path / 'validation',
                               {'mae': .12, 'reprojection_px': 5., 'silhouette_iou': .8})
    assert report['passed'] is True  # Declared criteria, never physical/final-test approval.
    assert report['validation_scope'] == 'MULTIPOSE_GEOMETRY_DIAGNOSTIC'
    assert report['independent_verification'] is False
    assert report['final_independent_test'] == 'NOT_RECORDED'
    assert report['physics_status'] == 'PHYSICS_NOT_VALIDATED'
    rows = [json.loads(line) for line in (project.root / 'working/calibration_holdout_usage.jsonl').read_text().splitlines()]
    assert any(row['target'] == 'scene_validation' and row['holdout_observations'] == ['pose_3'] for row in rows)
