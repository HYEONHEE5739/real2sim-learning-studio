"""Real registration/solver contracts on synthetic RGB and measured geometry only."""
import copy
import hashlib
import json
from itertools import product

import numpy as np
import pytest
from PIL import Image

from real2sim_builder.calibration.camera import project_point
from real2sim_builder.calibration.joint import fit_joint_scene
from real2sim_builder.candidate import Candidate
from real2sim_builder.capture import observation_scene
from real2sim_builder.files import sha, write
from real2sim_builder.observations import register_image, register_views
from real2sim_builder.project import Project
from real2sim_builder.scene import value, world_pose
from test_builder_export import legacy_scene


POINTS = list(product((-.025, .025), repeat=3))
ANCHORS = list(product((-.12, .12), (-.1, .1), (.01, .14)))


def _pixels(scene, camera, row, affine):
    uv, depth = project_point(scene, camera, row)
    assert depth > 0
    pixel = affine @ np.r_[uv, 1.]
    return (pixel[:2] / pixel[2]).tolist()


def _external_photos(tmp_path, *, global_pose=False, processed=False, holdout=False):
    project = Project.create(tmp_path / 'projects', 'joint per view')
    truth = legacy_scene()
    camera = truth['cameras'][0]
    camera.update(id='shared_phone', camera_type='external')
    camera['K'] = value([[180., 0, 72.], [0, 155., 56.], [0, 0, 1]], 'calibrated', ['synthetic lens'])
    camera['distortion'] = value([.08, -.02, .003, -.004, .001], 'calibrated', ['synthetic lens'])
    scene = copy.deepcopy(truth)
    if not global_pose:
        scene['cameras'][0]['pose'] = value(None)
    scene['objects'][1]['pose']['provenance'] = 'estimated'
    project.save_scene(scene)
    images, bindings, landmarks = [], {}, []
    count = 3 if holdout else 2
    for index in range(count):
        orientation = 3 if processed and index == 1 else 1
        exif = Image.Exif()
        exif[274] = orientation
        path = tmp_path / f'photo-{index}.png'
        Image.new('RGB', (160, 120), (20 + index * 40, 70, 90)).save(path, exif=exif)
        image = register_image(project, path, camera='shared_phone', camera_type='external',
                               scene_state='layout', split='validation' if index == 2 else 'train')
        # Explicit same-sized crop/resize, composed after EXIF 180 degrees.
        crop = np.array([[1.1, 0, -8.], [0, 1.05, -3.], [0, 0, 1.]]) if orientation == 3 else np.eye(3)
        exif_pixels = np.array([[-1., 0, 159.], [0, -1., 119.], [0, 0, 1.]]) if orientation == 3 else np.eye(3)
        affine = crop @ exif_pixels
        if orientation == 3:
            evidence = project.evidence
            next(row for row in evidence['images'] if row['id'] == image['id'])['pixel_from_camera'] = crop.tolist()
            write(project.root / 'input/evidence.yaml', evidence)
            image['pixel_from_camera'] = crop.tolist()
        view = copy.deepcopy(camera)
        view['pose']['value'][0][3] += .09 * index
        view['pose']['value'][1][3] -= .07 * index
        view['pose']['value'][2][3] += .02 * index
        bindings[image['id']] = {
            'source': 'measured', 'evidence': ['synthetic surveyed 3D points'],
            'world_points_m': [list(point) for point in ANCHORS],
            'uv_px': [_pixels(truth, view, {'frame': 'world', 'point_m': list(point)}, affine) for point in ANCHORS],
        }
        for point in POINTS:
            row = {'observation': image['id'], 'object': 'block', 'point_m': list(point), 'sigma_px': 1.}
            landmarks.append({**row, 'uv': _pixels(truth, view, row, affine)})
        images.append(image)
    evidence = project.evidence
    evidence['landmarks'] = landmarks
    write(project.root / 'input/evidence.yaml', evidence)
    candidate = Candidate.create(project, 'joint')
    registered = register_views(candidate, bindings, scene=scene, scene_state='layout', persist=False)
    assert registered['status'] == 'REGISTERED_ESTIMATED', registered
    scene = registered['scene']
    assert len(scene['view_registrations']) == count
    assert scene['cameras'][0]['K'] == camera['K']
    return project, scene, images, truth


@pytest.mark.parametrize('processed', [False, True], ids=['original_pixels', 'exif180_crop_affine'])
def test_joint_fit_uses_two_registered_photos_with_no_global_camera_pose(tmp_path, processed):
    project, scene, images, truth = _external_photos(tmp_path, processed=processed)
    scene['objects'][1]['pose']['value'][0][3] += .012
    scene['objects'][1]['pose']['value'][1][3] -= .006
    original = copy.deepcopy(scene)
    current_sha = sha(project.root / 'working/current_scene.yaml')
    evidence_sha = sha(project.root / 'input/evidence.yaml')
    assert scene['cameras'][0]['pose']['value'] is None
    assert not np.allclose(scene['view_registrations'][images[0]['id']]['T_world_camera'],
                           scene['view_registrations'][images[1]['id']]['T_world_camera'])

    fitted, report = fit_joint_scene(project, scene, {'objects': ['block'], 'cameras': [],
        'external_views': False, 'pose_prior': 0., 'max_nfev': 80})

    assert report['status'] == 'IMPROVED', report
    assert report['after']['rmse_px'] < 1e-5
    assert len(report['after']['groups']) == 2
    np.testing.assert_allclose(fitted['objects'][1]['pose']['value'], truth['objects'][1]['pose']['value'], atol=1e-5)
    assert fitted['cameras'] == original['cameras']
    assert fitted['view_registrations'] == original['view_registrations']
    assert scene == original
    assert sha(project.root / 'working/current_scene.yaml') == current_sha
    assert sha(project.root / 'input/evidence.yaml') == evidence_sha


def test_joint_fit_changes_only_the_perturbed_view_residual_and_updates_its_extrinsic(tmp_path):
    project, scene, images, _ = _external_photos(tmp_path, global_pose=True)
    scene['objects'][1]['pose']['provenance'] = 'measured'
    changed_id = images[1]['id']
    scene['view_registrations'][changed_id]['T_world_camera'][0][3] += .015
    original = copy.deepcopy(scene)
    expected = {}
    for image in images:
        adapted = observation_scene(scene, image, project.root, complete=False)
        camera = adapted['cameras'][0]
        errors = [np.linalg.norm(project_point(adapted, camera, row)[0] - row['uv'])
                  for row in project.evidence['landmarks'] if row['observation'] == image['id']]
        expected['registered:' + image['id']] = np.sqrt(np.mean(np.square(errors)))

    fitted, report = fit_joint_scene(project, scene, {'objects': [], 'cameras': [], 'pose_prior': 0., 'max_nfev': 80})

    before = {row['pose']: row['rmse_px'] for row in report['before']['groups']}
    assert before == pytest.approx(expected, abs=1e-8)
    assert before['registered:' + images[0]['id']] < 1e-6
    assert before['registered:' + changed_id] > 1.
    assert report['status'] == 'IMPROVED', report
    assert report['after']['rmse_px'] < 1e-5
    assert fitted['view_registrations'][changed_id]['T_world_camera'] != original['view_registrations'][changed_id]['T_world_camera']
    assert fitted['cameras'] == original['cameras']
    assert fitted['objects'] == original['objects']
    assert scene == original


def test_joint_fit_excludes_validation_photo_from_variables_and_training_solution(tmp_path):
    project, scene, images, _ = _external_photos(tmp_path, global_pose=True, holdout=True)
    scene['objects'][1]['pose']['provenance'] = 'measured'
    scene['view_registrations'][images[0]['id']]['T_world_camera'][0][3] += .01
    scene['view_registrations'][images[1]['id']]['T_world_camera'][1][3] -= .012
    original = copy.deepcopy(scene)
    options = {'objects': [], 'cameras': [], 'pose_prior': 0., 'holdout_policy': 'report_only', 'max_nfev': 80}

    first, report = fit_joint_scene(project, scene, options)
    evidence = project.evidence
    for row in evidence['landmarks']:
        if row['observation'] == images[2]['id']:
            row['uv'][0] += 35.
            row['uv'][1] -= 20.
    write(project.root / 'input/evidence.yaml', evidence)
    second, changed_report = fit_joint_scene(project, scene, options)

    assert report['status'] == changed_report['status'] == 'IMPROVED'
    assert first == second
    assert report['after'] == changed_report['after']
    assert changed_report['holdout_after']['rmse_px'] > report['holdout_after']['rmse_px'] + 30.
    assert report['held_out_observations'] == [images[2]['id']]
    assert {row['id'] for row in report['changed_variables']} == {image['id'] for image in images[:2]}
    assert first['view_registrations'][images[2]['id']] == original['view_registrations'][images[2]['id']]
    assert first['cameras'] == original['cameras']
    assert scene == original


def test_joint_fit_preserves_fixed_side_and_shared_wrist_mount_at_distinct_measured_q(tmp_path):
    project = Project.create(tmp_path / 'projects', 'shared sensors')
    truth = legacy_scene()
    model = project.root / 'input/robot.urdf'
    model.write_text('<robot name="fixture"><link name="base"/><link name="hand"/>'
        '<joint name="hinge" type="revolute"><parent link="base"/><child link="hand"/>'
        '<origin xyz="0.1 0 0"/><axis xyz="0 0 1"/><limit lower="-1" upper="1" effort="1" velocity="1"/>'
        '</joint></robot>')
    mapping = {'version': 'so101.sim-joint-mapping/1', 'joint_order': ['hinge'], 'output': 'urdf_joint_radian'}
    mapping['sha256'] = hashlib.sha256(json.dumps(mapping, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    truth['robot_model'] = {'format': 'urdf', 'path': 'input/robot.urdf', 'model_sha256': sha(model),
        'joint_names': ['hinge'], 'mapping': mapping, 'mapping_verified': False}
    truth['frames']['robot_base'] = {'parent': 'world', 'transform': value(np.eye(4).tolist(), 'calibrated')}
    from real2sim_builder.calibration.geometry import link_transforms
    for link, transform in link_transforms(model, {'hinge': 0.}).items():
        truth['frames']['robot_link_' + link] = {'parent': 'robot_base', 'transform': value(transform.tolist(), 'derived')}
    side = truth['cameras'][0]
    side.update(id='fixed_sensor', camera_type='side')
    wrist = copy.deepcopy(side)
    mount = np.linalg.inv(link_transforms(model, {'hinge': 0.})['hand']) @ np.asarray(side['pose']['value'])
    wrist.update(id='tool_sensor', camera_type='wrist', frame='robot_link_hand', pose=value(mount.tolist(), 'calibrated', ['synthetic shared mount']))
    truth['cameras'].append(wrist)
    project.save_scene(truth)
    images = []
    for index, (camera_id, kind, q) in enumerate([('fixed_sensor', 'side', None), ('tool_sensor', 'wrist', -.25), ('tool_sensor', 'wrist', .3)]):
        path = tmp_path / f'sensor-{index}.png'
        Image.new('RGB', (160, 120), (30 + index * 40, 20, 10)).save(path)
        joint = None if q is None else {'q_measured': [q], 'joint_names': ['hinge'], 'joint_units': ['rad'],
            'mapping_sha256': mapping['sha256'], 'robot_model_sha256': sha(model),
            'image_timestamp_ns': 1000 + index, 'joint_timestamp_ns': 1000 + index}
        images.append(register_image(project, path, camera=camera_id, camera_type=kind, scene_state='layout', joint_record=joint))
    candidate = Candidate.create(project, 'joint')
    registered = register_views(candidate, scene=truth, scene_state='layout', persist=False)
    assert registered['status'] == 'REGISTERED_ESTIMATED', registered
    scene = registered['scene']
    evidence = project.evidence
    for image in images:
        posed = observation_scene(scene, image, project.root, complete=False)
        camera = next(row for row in posed['cameras'] if row['id'] == image['camera'])
        for point in POINTS:
            row = {'observation': image['id'], 'object': 'block', 'point_m': list(point), 'sigma_px': 1.}
            evidence['landmarks'].append({**row, 'uv': _pixels(posed, camera, row, np.eye(3))})
    write(project.root / 'input/evidence.yaml', evidence)
    scene['objects'][1]['pose']['provenance'] = 'estimated'
    scene['objects'][1]['pose']['value'][0][3] += .01
    original = copy.deepcopy(scene)
    current_sha, evidence_sha = sha(project.root / 'working/current_scene.yaml'), sha(project.root / 'input/evidence.yaml')

    fitted, report = fit_joint_scene(project, scene, {'objects': ['block'], 'cameras': [], 'pose_prior': 0., 'max_nfev': 80})

    assert report['status'] == 'IMPROVED', report
    assert report['after']['rmse_px'] < 1e-5
    assert len(report['after']['groups']) == 3
    assert fitted['cameras'] == original['cameras']
    assert fitted['robot_model'] == original['robot_model']
    for image in images:
        posed = observation_scene(fitted, image, project.root, complete=False)
        camera = next(row for row in posed['cameras'] if row['id'] == image['camera'])
        expected = np.asarray(side['pose']['value']) if image['camera_type'] == 'side' else link_transforms(model, {'hinge': image['q_measured'][0]})['hand'] @ mount
        np.testing.assert_allclose(world_pose(posed, camera), expected, atol=1e-12)
    assert scene == original
    assert sha(project.root / 'working/current_scene.yaml') == current_sha
    assert sha(project.root / 'input/evidence.yaml') == evidence_sha
