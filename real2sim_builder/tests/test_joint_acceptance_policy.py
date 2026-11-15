"""Real synthetic joint solves at diagnostic, Stage10 and Best boundaries.

Sensor/cloud preparation and render metrics are explicit stubs; no model,
device, actual Capture archive or user Scene is read by these fixtures.
"""
import copy
from itertools import product
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from real2sim_builder.calibration.camera import project_point
from real2sim_builder.calibration.joint import fit_joint_scene
from real2sim_builder.files import read, sha, write
from real2sim_builder.observations import register_image, register_views
from real2sim_builder.project import Candidate, Project
from real2sim_builder.scene import value
from test_builder_export import legacy_scene
from test_reconstruction_followup import world_anchors


def _problem(tmp_path, *, full_rank=False, holdout=False):
    project = Project.create(tmp_path / 'projects', 'joint acceptance')
    truth = legacy_scene()
    model = project.root / 'input/model.urdf'
    model.write_text('<robot name="synthetic"><link name="base"/></robot>')
    truth['robot_model'] = {'path': 'input/model.urdf', 'model_sha256': sha(model),
        'format': 'urdf', 'joint_names': [], 'mapping': {}}
    truth['frames']['robot_base'] = {'parent': 'world', 'transform': value(np.eye(4).tolist(), 'calibrated')}
    scene = copy.deepcopy(truth)
    scene['objects'][1]['pose']['provenance'] = 'estimated'
    scene['objects'][1]['pose']['value'][0][3] += .01
    project.save_scene(scene)
    points = list(product((-.025, .025), repeat=3)) if full_rank else [[0., 0., 0.]] * 4
    images = []
    for index, split in enumerate(('train', 'validation') if holdout else ('train',)):
        path = tmp_path / f'{split}.png'
        Image.new('RGB', (160, 120), (24 + index * 30, 34, 54)).save(path)
        images.append(register_image(project, path, camera='side', camera_type='side', scene_state='layout', split=split))
    evidence = project.evidence
    # The Stage10 boundary receives an already prepared valid sensor registration.
    for image in evidence['images']:
        image['capture_manifest'] = 'input/synthetic-prepared-registration/capture_manifest.yaml'
        for point in points:
            row = {'observation': image['id'], 'object': 'block', 'point_m': list(point), 'sigma_px': 1.}
            row['uv'] = project_point(truth, truth['cameras'][0], row)[0].tolist()
            evidence['landmarks'].append(row)
    write(project.root / 'input/evidence.yaml', evidence)
    candidate = Candidate.create(project, 'draft')
    scene = register_views(candidate, scene=scene, scene_state='layout', persist=False)['scene']
    candidate.save(scene)
    return project, candidate, scene, images


def _options(**changes):
    return {'objects': ['table', 'block'], 'cameras': ['side'], 'robot_base': True,
        'external_views': False, 'pose_prior': 0., 'max_nfev': 60, **changes}


def _prepared_registration(monkeypatch, images):
    from real2sim_builder import observations, reconstruction_stages as stages
    monkeypatch.setattr(stages, 'stage_sensor_clouds', lambda candidate, scene, *args: scene)
    monkeypatch.setattr(observations, 'register_sensor_views', lambda candidate, config, **kw: {
        'scene': copy.deepcopy(kw['scene']), 'status': 'REGISTERED_ESTIMATED',
        'views': [{'image_id': image['id']} for image in images], 'needs': []})


def _stage(candidate, scene, folder, options):
    from real2sim_builder import reconstruction_stages as stages
    folder.mkdir()
    config = {'scene_state_id': 'layout', 'sensor_registration': {'world_anchors': world_anchors(), 'joint': options}}
    registration, _ = stages.resolve_stage_world(config, True, folder)
    return stages.register_stage_sensors(candidate, config, scene, {}, folder, resolved_registration=registration)


def _protected_equal(before, after):
    assert after['cameras'] == before['cameras']
    assert after['objects'][0] == before['objects'][0]
    assert after['objects'][1]['dimensions'] == before['objects'][1]['dimensions']
    assert after['frames']['robot_base'] == before['frames']['robot_base']
    assert after['robot_model'] == before['robot_model']


@pytest.mark.parametrize('pose_prior', [0., .2])
def test_stage10_rejects_rank_two_of_six_even_when_training_rmse_improves(tmp_path, monkeypatch, pose_prior):
    project, candidate, scene, images = _problem(tmp_path)
    original = copy.deepcopy(scene)
    immutable = {path: sha(path) for path in [project.root / 'working/current_scene.yaml',
        project.root / 'input/evidence.yaml', candidate.root / 'candidate_scene.yaml']}
    options = _options(pose_prior=pose_prior)
    draft, diagnostic = fit_joint_scene(project, scene, options)
    assert diagnostic['status'] == 'IMPROVED'
    assert diagnostic['jacobian_rank'] == 2 and diagnostic['parameter_count'] == 6
    assert diagnostic['after']['rmse_px'] < diagnostic['before']['rmse_px']
    assert draft['objects'][1]['pose'] != scene['objects'][1]['pose']
    _prepared_registration(monkeypatch, images)

    retained, report = _stage(candidate, scene, candidate.root / 'stage10', options)

    assert report['joint_refinement']['status'] == 'UNRESOLVED', report
    assert retained == original
    assert report['joint_refinement']['jacobian_rank'] == 2
    assert report['joint_refinement']['after'] == diagnostic['after']
    assert report['joint_refinement']['after']['rmse_px'] < report['joint_refinement']['before']['rmse_px']
    assert report['physical_verified'] is False and report['metric_accuracy_verified'] is False
    assert read(candidate.root / 'stage10/sensor_registration.json')['joint_refinement'] == report['joint_refinement']
    _protected_equal(original, retained)
    assert scene == original and all(sha(path) == digest for path, digest in immutable.items())


def test_stage10_accepts_independent_full_rank_landmarks_but_does_not_certify_calibration(tmp_path, monkeypatch):
    project, candidate, scene, images = _problem(tmp_path, full_rank=True, holdout=True)
    original = copy.deepcopy(scene)
    current = sha(project.root / 'working/current_scene.yaml')
    _prepared_registration(monkeypatch, images)

    accepted, report = _stage(candidate, scene, candidate.root / 'stage10', _options())

    joint = report['joint_refinement']
    assert joint['status'] == 'IMPROVED', report
    assert joint['jacobian_rank'] == joint['parameter_count'] == 6
    assert joint['after']['rmse_px'] < 1e-6
    assert joint['holdout_after']['count'] == 8 and joint['holdout_after']['rmse_px'] < 1e-6
    assert joint['held_out_observations'] == [images[1]['id']]
    assert {row['id'] for row in joint['changed_variables']} == {'block'}
    assert joint['independent_verification'] is False and joint['physical_verified'] is False
    assert report['physical_verified'] is False and report['metric_accuracy_verified'] is False
    assert accepted['objects'][1]['pose'] != original['objects'][1]['pose']
    _protected_equal(original, accepted)
    assert scene == original and current == sha(project.root / 'working/current_scene.yaml')


def test_stage10_stop_then_restart_still_rejects_underconstrained_result(tmp_path, monkeypatch):
    from real2sim_builder.calibration import joint
    project, candidate, scene, images = _problem(tmp_path)
    _prepared_registration(monkeypatch, images)
    original = candidate.scene
    current = sha(project.root / 'working/current_scene.yaml')
    real_fit = joint.fit_joint_scene
    stopped = []
    def solve(*args, **kwargs):
        result = real_fit(*args, **kwargs)
        if not stopped:
            stopped.append(True)
            project.control('stop')
        return result
    monkeypatch.setattr(joint, 'fit_joint_scene', solve)
    with pytest.raises(InterruptedError):
        _stage(candidate, scene, candidate.root / 'interrupted', _options())
    assert candidate.scene == original
    project.control('resume')

    retained, report = _stage(candidate, candidate.scene, candidate.root / 'restarted', _options())

    assert report['joint_refinement']['status'] == 'UNRESOLVED'
    assert retained == original and candidate.scene == original
    assert current == sha(project.root / 'working/current_scene.yaml')


def test_stage10_training_solution_does_not_use_validation_landmarks(tmp_path, monkeypatch):
    project, candidate, scene, images = _problem(tmp_path, full_rank=True, holdout=True)
    _prepared_registration(monkeypatch, images)
    options = _options(holdout_policy='report_only')
    first, first_report = _stage(candidate, scene, candidate.root / 'original-validation', options)
    evidence = project.evidence
    for row in evidence['landmarks']:
        if row['observation'] == images[1]['id']:
            row['uv'][0] += 25.
            row['uv'][1] -= 15.
    write(project.root / 'input/evidence.yaml', evidence)

    second, second_report = _stage(candidate, scene, candidate.root / 'changed-validation', options)

    one, two = first_report['joint_refinement'], second_report['joint_refinement']
    assert one['status'] == two['status'] == 'IMPROVED'
    assert first == second and one['after'] == two['after']
    assert two['holdout_after']['rmse_px'] > one['holdout_after']['rmse_px'] + 20.
    assert two['independent_verification'] is False
    assert candidate.scene == scene


def test_numeric_rejects_actual_rank_deficient_solve_and_keeps_best_scene(tmp_path, monkeypatch):
    from real2sim_builder import automation
    from real2sim_builder.calibration import hybrid
    project, candidate, scene, images = _problem(tmp_path)
    _prepared_registration(monkeypatch, images)
    current = sha(project.root / 'working/current_scene.yaml')
    def metrics(project, scene, folder, options):
        error = abs(scene['objects'][1]['pose']['value'][0][3])
        return {'input_signature': project.signature(scene), 'needs': [], 'images': [
            {'image_id': images[0]['id'], 'split': 'train', 'camera_type': 'side',
             'mae': error, 'rmse': error, 'edge_iou': 1-error, 'objects': []}]}
    monkeypatch.setattr(hybrid, 'alignment_metrics', metrics)
    report = automation.refine_numeric_pairs(candidate, {
        'numeric_refinement': {'max_iterations': 2, 'render_fit': False}, 'fitting': _options()})

    assert report['accepted_iterations'] == 0 and report['status'] == 'NEEDS_MORE_DATA'
    solver = report['history'][0]['solver']
    assert solver['status'] == 'UNRESOLVED' and solver['jacobian_rank'] == 2
    assert solver['after']['rmse_px'] < solver['before']['rmse_px']
    best = Path(report['selected_checkpoint'])
    assert candidate.scene == read(best / 'scene.yaml') == scene
    assert len(list((candidate.root / 'fitting/checkpoints').iterdir())) == 1
    assert report['holdout_used_for_selection'] is False and report['physical_verified'] is False
    assert current == sha(project.root / 'working/current_scene.yaml')


def test_direct_candidate_fit_keeps_rank_deficient_unverified_diagnostic_draft(tmp_path):
    project, candidate, scene, _ = _problem(tmp_path)
    current = sha(project.root / 'working/current_scene.yaml')

    report = candidate.fit('joint:scene', _options())

    assert report['status'] == 'IMPROVED' and report['jacobian_rank'] == 2
    assert report['scope'] == 'OPTIMIZED_UNVERIFIED_DRAFT'
    assert report['physical_verified'] is False and report['independent_verification'] is False
    assert candidate.scene['objects'][1]['pose'] != scene['objects'][1]['pose']
    assert read(candidate.root / 'joint-fit.json') == report
    _protected_equal(scene, candidate.scene)
    assert current == sha(project.root / 'working/current_scene.yaml')


def test_hybrid_comparison_keeps_low_rank_diagnostic_artifacts_without_a_verified_winner(tmp_path, monkeypatch):
    from real2sim_builder.calibration import hybrid
    project, candidate, scene, images = _problem(tmp_path)
    current = sha(project.root / 'working/current_scene.yaml')
    monkeypatch.setattr(hybrid, 'cloud_inputs', lambda *args: [{'split': 'train', 'image_id': images[0]['id']}])
    monkeypatch.setattr(hybrid, 'fit_clouds', lambda project, scene, options: (scene, {'status': 'ESTIMATED', 'objects': {}}))
    monkeypatch.setattr(hybrid, 'fit_scene', lambda project, scene, *args: (scene, {'status': 'NOT_REQUESTED'}))
    from real2sim_builder.calibration import joint
    monkeypatch.setattr(joint, 'fit_depth_bundle', lambda project, scene, *args: (scene, {'status': 'NEEDS_MORE_DATA'}))
    monkeypatch.setattr(hybrid, 'alignment_metrics', lambda project, scene, *args: {
        'images': [{'split': 'train', 'image_id': images[0]['id'], 'mae': .1}], 'needs': []})

    folder = candidate.root / 'comparison'
    draft, report = hybrid.compare_backends(project, scene, folder, {**_options(), 'backend': 'hybrid'})

    diagnostic = report['backends']['hybrid']['stages']['joint']
    assert diagnostic['status'] == 'IMPROVED' and diagnostic['jacobian_rank'] == 2
    assert report['default_backend'] is None and report['winner'] is None
    assert report['independent_pose_accuracy_mm'] is None
    assert report['backends']['hybrid']['physical_verified'] is False
    assert draft == read(folder / 'hybrid.yaml')
    assert draft['objects'][1]['pose'] != scene['objects'][1]['pose']
    assert candidate.scene == scene
    _protected_equal(scene, draft)
    assert current == sha(project.root / 'working/current_scene.yaml')
