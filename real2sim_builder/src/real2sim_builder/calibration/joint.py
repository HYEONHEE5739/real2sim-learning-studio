"""Bounded multi-view landmark fitting of shared cameras and object poses.

No renderer, hardware, joint-offset, intrinsic or physics optimization is performed.
"""
import copy
from collections import Counter

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from ..capture import observation_scene
from ..editing import preserve
from ..files import sha
from ..observations import annotation_evidence, registered_images,camera_type
from ..scene import frame_world, local_path, validate, value, world_pose
from .camera import project_point


def _mounted(scene, frame):
    while frame is not None:
        if frame.startswith('robot_link_'):
            return True
        frame = scene['frames'][frame]['parent']
    return False


def _support(scene, obj, explicit):
    """Use an explicit support or an already coincident horizontal box surface."""
    objects = {o['id']: o for o in scene['objects']}
    pose = world_pose(scene, obj)
    size = obj['dimensions']['value']
    if size is None or not np.allclose(pose[:3, 2], [0, 0, 1], atol=1e-7):
        return None
    candidates = [objects[explicit]] if explicit else [o for o in objects.values()
                  if o['role'] == 'support_surface' and o['id'] != obj['id']]
    found = []
    for support in candidates:
        dims = support['dimensions']['value']
        t = world_pose(scene, support)
        if (dims is None or support['collision']['type'] != 'box'
                or not np.allclose(t[:3, 2], [0, 0, 1], atol=1e-7)):
            continue
        height = t[2, 3] + dims[2]/2 + size[2]/2
        error = abs(pose[2, 3]-height)
        if explicit or error <= .002:
            found.append((error, support['id'], height))
    return min(found) if found else None


def _posed(candidate, cached):
    result = copy.deepcopy(candidate)
    result['frames'] = cached['frames']
    reference = {o['id']: o for o in cached['objects'] if o.get('link')}
    for obj in result['objects']:
        if obj['id'] in reference:
            obj['frame'] = reference[obj['id']]['frame']
            obj['pose'] = reference[obj['id']]['pose']
    return result


def fit_joint_scene(project, scene, options=None):
    """Return a Candidate-only draft and per-camera/pose/object residual report."""
    options = dict(options or {})
    report = {'target': 'joint:scene', 'status': 'NEEDS_MORE_DATA', 'physical_verified': False,
              'scope': 'OPTIMIZED_UNVERIFIED_DRAFT', 'needs': [], 'mask_loss': 'NOT_IMPLEMENTED',
              'mask_metrics': 'Use Candidate.evaluate with approved silhouette annotations'}
    images, state, needs = registered_images(project, options.get('scene_state'),scene=scene)
    report.update(scene_state_id=state, needs=needs)
    if not images:
        return scene, report
    declared = scene.get('reconstruction_state', {}).get('id')
    if declared and declared != state:
        raise ValueError('Candidate and observations declare different layouts')
    evidence = annotation_evidence(project, scene)
    by_id = {i['id']: i for i in images}
    cameras = {c['id']: c for c in scene['cameras']}
    missing = [i['camera'] for i in images if i['camera'] not in cameras or
               any(cameras[i['camera']][field]['value'] is None for field in ('K', 'distortion'))or
               (cameras[i['camera']]['pose']['value']is None and not scene.get('view_registrations',{}).get(i['id'],{}).get('T_world_camera'))]
    if missing:
        report['needs'] = ['Initialize camera pose/K/distortion before joint fitting: ' + ', '.join(sorted(set(missing))),
                           'Use existing bootstrap/intrinsics fitting with explicit CAD correspondences']
        return scene, report
    model = scene.get('robot_model')
    if not model and any(i.get('session_id')or camera_type(i)=='wrist'for i in images):
        report['needs'] = ['Import the actual robot model and measured-joint mapping']
        return scene, report
    if model and sha(local_path(project.root, model['path'])) != model['model_sha256']:
        raise ValueError('Robot model bytes differ from Candidate identity')
    for image in images:
        if (image.get('q_measured')is not None and(not model or image['joint_names']!=model['joint_names']))or image['resolution']!=cameras[image['camera']]['resolution']:
            raise ValueError('Observation robot order or camera resolution differs')
    rows = [r for r in evidence.get('landmarks', []) if r.get('observation') in by_id
            and r.get('visible', True) and r.get('occluded') is not True
            and float(r.get('weight', 1)) > 0 and float(r.get('confidence', 1)) >= options.get('min_confidence', .2)]
    train = [r for r in rows if by_id[r['observation']]['split'] == 'train']
    held = [r for r in rows if by_id[r['observation']]['split'] == 'validation']
    if {by_id[r['observation']]['group_id'] for r in train} & {by_id[r['observation']]['group_id'] for r in held}:
        raise ValueError('Train/holdout group leakage')
    if len(train) < 4:
        report['needs'] = ['Review >=4 visible CAD-to-pixel correspondences; masks alone do not drive this MVP fit',
                           'Keep the metric Scene draft; request another unobscured camera/pose if needed']
        return scene, report
    for row in rows:
        uv = np.asarray(row['uv'], float)
        sigma = float(row.get('sigma_px', 3))
        confidence = float(row.get('confidence', 1))
        if (uv.shape != (2,) or not np.isfinite(uv).all() or not np.isfinite(sigma) or sigma <= 0
                or not np.isfinite(confidence) or not 0 < confidence <= 1):
            raise ValueError('Finite pixel/confidence and positive pixel uncertainty required')
    candidate = copy.deepcopy(scene)
    nodes = {o['id']: o for o in candidate['objects']}
    camera_nodes = {c['id']: c for c in candidate['cameras']}
    cached = {i['id']: observation_scene(scene, i, project.root, complete=False) for i in images}
    blocks = []
    lower, upper = [], []
    translation = float(options.get('translation_bound_m', .05))
    angle = float(options.get('rotation_bound_rad', .3))
    if not np.isfinite([translation, angle]).all() or min(translation, angle) <= 0:
        raise ValueError('Positive finite pose bounds required')
    observed_cameras = {by_id[r['observation']]['camera'] for r in train}
    for name in options.get('cameras', sorted(observed_cameras)):
        if name not in observed_cameras:
            continue
        if name not in camera_nodes:
            continue
        cam = camera_nodes[name]
        if cam['pose']['value']is None:continue  # External views have separate registered poses.
        if cam['pose']['provenance'] in ('measured', 'calibrated'):
            continue
        if (name == 'wrist') != _mounted(scene, cam['frame']):
            raise ValueError('Side must be fixed and Wrist must use a shared robot-link mount')
        blocks.append(('camera', name, np.asarray(cam['pose']['value'], float), len(lower), 6, None))
        lower.extend([-translation]*3 + [-angle]*3)
        upper.extend([translation]*3 + [angle]*3)
    observed_objects = {r.get('object') for r in train}
    selected = options.get('objects', [o['id'] for o in scene['objects']
                                     if o['id'] in observed_objects and o['role'] in ('manipulable_object', 'receptacle')])
    for name in selected:
        obj = nodes[name]
        if obj['pose']['provenance'] in ('measured', 'calibrated'):
            continue
        if obj.get('link') or _mounted(scene, obj['frame']):
            raise ValueError('Joint Scene objects must have static world poses, not robot-link poses')
        if obj['pose']['value'] is None:
            report['needs'] = ['Initialize a metric object pose: ' + name]
            return scene, report
        support = _support(scene, obj, options.get('supports', {}).get(name))
        count = 3 if support else 6
        blocks.append(('object', name, world_pose(scene, obj), len(lower), count, support))
        lower.extend([-translation]*2 + [-angle] if support else [-translation]*3 + [-angle]*3)
        upper.extend([translation]*2 + [angle] if support else [translation]*3 + [angle]*3)
    if not blocks:
        report['needs'] = ['All requested variables are measured/calibrated or no variable was selected']
        return scene, report
    moving = {name for kind, name, *_ in blocks if kind == 'object'}
    constraints = copy.deepcopy(scene.get('geometry_constraints'))
    if constraints:
        for row in constraints['distances']:
            pair = set(row['objects'])
            if pair & moving and any(n not in moving and nodes[n]['pose']['provenance'] not in ('measured', 'calibrated') for n in pair):
                raise ValueError('Select both members of a constrained pair or retain a measured pose anchor')
    def assign(x):
        nonlocal candidate
        candidate = copy.deepcopy(scene)
        current = {o['id']: o for o in candidate['objects']}
        cams = {c['id']: c for c in candidate['cameras']}
        for kind, name, seed, offset, count, support in blocks:
            delta = x[offset:offset+count]
            pose = seed.copy()
            if support:
                a = delta[2]
                rotation = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
                pose[:3, :3] = rotation @ seed[:3, :3]
                pose[:2, 3] += delta[:2]
                pose[2, 3] = support[2]
            else:
                pose[:3, :3] = Rotation.from_rotvec(delta[3:]).as_matrix() @ seed[:3, :3]
                pose[:3, 3] += delta[:3]
            target = cams[name] if kind == 'camera' else current[name]
            if kind == 'object':
                pose = np.linalg.inv(frame_world(candidate, target['frame'])) @ pose
            target['pose'] = value(pose.tolist(), 'optimized', ['bounded joint:scene image-derived draft'])
            if kind == 'camera':
                target['calibration_quality'] = {'state': 'ESTIMATED', 'physical_verified': False,
                                                 'scope': 'joint image-derived draft; no independent calibration'}
        if constraints and moving:
            from ..initialization import apply_geometry_constraints
            active = {'schema': constraints['schema'], 'units': constraints['units'],
                      'distances': [r for r in constraints['distances'] if set(r['objects']) & moving]}
            if active['distances']:
                candidate, _ = apply_geometry_constraints(candidate, active)
                candidate['geometry_constraints'] = copy.deepcopy(constraints)
        # Preserve each dependent fixture's object-relative pose (decals, etc.).
        current = {o['id']: o for o in candidate['objects']}
        original = {o['id']: o for o in scene['objects']}
        for obj in candidate['objects']:
            parent = obj.get('parent_object')
            if parent in moving and obj['id'] not in moving:
                relative = np.linalg.inv(world_pose(scene, original[parent])) @ world_pose(scene, original[obj['id']])
                world = world_pose(candidate, current[parent]) @ relative
                obj['pose'] = value((np.linalg.inv(frame_world(candidate, obj['frame'])) @ world).tolist(), 'optimized', ['parent object joint fit'])
    def errors(rows_to_measure):
        posed = {}
        result = []
        for row in rows_to_measure:
            key = row['observation']
            if key not in posed:
                posed[key] = _posed(candidate, cached[key])
            cam = next(c for c in posed[key]['cameras'] if c['id'] == by_id[key]['camera'])
            uv, depth = project_point(posed[key], cam, row)
            result.append((row, uv-np.asarray(row['uv'], float), float(depth)))
        return result
    def summarize(rows_to_measure):
        grouped, outliers = {}, []
        behind = 0
        for row, delta, z in errors(rows_to_measure):
            image = by_id[row['observation']]
            pose_id = image.get('session_id', 'registered')+':'+(image.get('snapshot_id') or image['id'])
            key = (image['camera'], pose_id, row.get('object', row.get('frame', 'world')))
            error = float(np.linalg.norm(delta))
            grouped.setdefault(key, []).append(error)
            outliers.append({'observation': image['id'], 'camera': image['camera'], 'object': row.get('object'), 'error_px': error})
            behind += int(z <= 0)
        flat = [e for values in grouped.values() for e in values]
        return {'count': len(flat), 'rmse_px': float(np.sqrt(np.mean(np.square(flat)))) if flat else None,
                'behind_camera': behind,
                'groups': [{'camera': k[0], 'pose': k[1], 'object': k[2], 'count': len(v),
                            'rmse_px': float(np.sqrt(np.mean(np.square(v))))} for k, v in sorted(grouped.items())],
                'worst_outliers': sorted(outliers, key=lambda r: r['error_px'], reverse=True)[:10]}
    counts = Counter((by_id[r['observation']]['camera'], r['observation'], r.get('object', r.get('frame', 'world'))) for r in train)
    radius = np.asarray(upper, float)
    def residual(x, prior=True):
        assign(x)
        values = []
        for row, delta, depth in errors(train):
            image = by_id[row['observation']]
            group = (image['camera'], row['observation'], row.get('object', row.get('frame', 'world')))
            weight = np.sqrt(float(row.get('weight', 1))*float(row.get('confidence', 1))/counts[group]) / float(row.get('sigma_px', 3))
            values.extend(delta*weight)
            values.append(max(0., .001-depth)*1e4)
        if prior:
            values.extend(x/radius*float(options.get('pose_prior', .2)))
        return np.asarray(values)
    # Baseline is the supplied Scene, before support projection or constraints.
    candidate = copy.deepcopy(scene)
    before = summarize(train)
    held_before = summarize(held)
    solution = least_squares(residual, np.zeros(len(lower)), bounds=(lower, upper), loss='soft_l1',
                             max_nfev=int(options.get('max_nfev', 100)))
    assign(solution.x)
    after, held_after = summarize(train), summarize(held)
    jac = solution.jac[:3*len(train)] * radius[None, :]
    singular = np.linalg.svd(jac, compute_uv=False)
    rank = int(np.linalg.matrix_rank(jac))
    condition = float(singular[0]/singular[-1]) if rank == len(lower) and singular[-1] > 1e-12 else None
    baseline = {(r['camera'], r['pose'], r['object']): r['rmse_px'] for r in before['groups']}
    limit = float(options.get('max_group_regression_px', 2))
    regressions = [r for r in after['groups'] if r['rmse_px'] > baseline[(r['camera'], r['pose'], r['object'])] + limit]
    observed_objects = {r.get('object') for r in train}
    anchored = any(o['id'] in observed_objects and
                   (o['dimensions']['provenance'] in ('measured', 'calibrated') or o.get('link'))
                   for o in scene['objects'])
    registration = scene.get('world_registration', {})
    if registration and not registration.get('metric_scale_verified'):
        anchored = False
    used_ids = {r['observation'] for r in train}
    used_images = [i for i in images if i['id'] in used_ids]
    report.update(before=before, after=after, holdout_before=held_before, holdout_after=held_after,
                  independent_verification=False, coverage={'eligible_images': len(images), 'images': len(used_images),
                                                          'poses': len({tuple(i.get('q_measured')or[])for i in used_images}),
                                                          'cameras': sorted(observed_cameras), 'layout': state},
                  changed_variables=[{'kind': b[0], 'id': b[1], 'mode': 'xy_yaw_on_support' if b[5] else 'pose6'} for b in blocks],
                  bounds={'lower': lower, 'upper': upper}, bound_hits=np.flatnonzero(np.isclose(abs(solution.x), radius, atol=1e-6)).tolist(),
                  jacobian_rank=rank, parameter_count=len(lower), condition_number=condition,
                  scaled_jacobian_singular_values=singular.tolist(), group_regressions=regressions,
                  metric_scale_anchored=anchored, relative_only=not anchored,
                  held_out_observations=sorted({r['observation'] for r in held}), solver_message=str(solution.message))
    if rank < len(lower):
        report['needs'].append('Rank-deficient draft: add distinct poses and CAD points at different depths; hard pair projection may also reduce effective dimension')
    if not anchored:
        report['needs'].append('Relative draft only: provide a measured size or known metric/world anchor')
    for missing_camera in {'side', 'wrist'} - observed_cameras:
        report['needs'].append(missing_camera+': add reviewed visible CAD points; this camera was not fitted')
    try:
        validate(candidate, project.root)
        preserve(scene, candidate)
    except ValueError as error:
        return scene, {**report, 'status': 'NOT_IMPROVED', 'reason': str(error)}
    held_regressed = bool(held and (held_after['behind_camera'] or held_after['rmse_px'] > held_before['rmse_px']+limit))
    held_groups = {(r['camera'], r['pose'], r['object']): r['rmse_px'] for r in held_before['groups']}
    held_regressions = [r for r in held_after['groups']
                        if r['rmse_px'] > held_groups[(r['camera'], r['pose'], r['object'])]+limit]
    report['holdout_group_regressions'] = held_regressions
    for kind, name, seed, _, _, support in blocks:
        target = next(n for n in candidate['cameras' if kind == 'camera' else 'objects'] if n['id'] == name)
        pose = np.asarray(target['pose']['value'], float) if kind == 'camera' else world_pose(candidate, target)
        if np.any(abs(pose[:3, 3]-seed[:3, 3]) > translation+1e-9):
            return scene, {**report, 'status': 'NOT_IMPROVED', 'reason': 'Support/distance projection exceeded pose bounds: '+name}
        if support and not np.isclose(pose[2, 3], support[2], atol=1e-9, rtol=0):
            return scene, {**report, 'status': 'NOT_IMPROVED', 'reason': 'Object support height changed: '+name}
    if after['behind_camera'] or regressions or held_regressed or held_regressions or after['rmse_px'] >= before['rmse_px']-1e-6:
        return scene, {**report, 'status': 'NOT_IMPROVED', 'reason': 'No aggregate improvement or a camera/pose/object regressed'}
    return candidate, {**report, 'status': 'IMPROVED'}
