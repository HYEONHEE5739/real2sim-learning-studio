"""Bounded reconstruction review loop; scan and initialization own their inputs."""
from PIL import Image, ImageOps
from pathlib import Path
import copy
import cv2
from real2sim_builder.scene import empty, local_path, validate, value
from real2sim_builder.evidence import extract_videos
import numpy as np
from real2sim_builder.files import read, write
from .scan import load, inspect_file, import_scan, registration, scale_from_lengths, plane, selection, mesh_asset, segment, preview
from .initialization import apply_geometry_constraints, constrain, initialize


def analyze(project):
    project.require_writable()
    scene = project.scene if (project.root / 'working/current_scene.yaml').exists() else empty(project.info['name'])
    rows = []
    for image in project.evidence['images']:
        project.checkpoint()
        rgb = np.asarray(ImageOps.exif_transpose(Image.open(project.root / image['path'])).convert('RGB'))
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        foreground = ((hsv[:, :, 1] > 65) & (hsv[:, :, 2] > 35)).astype(np.uint8)
        count, _, stats, centers = cv2.connectedComponentsWithStats(foreground)
        components = [{'bounds_xywh': s[:4].tolist(), 'center_uv': centers[i].tolist(), 'area_px': int(s[4]), 'role': 'unknown', 'depth_m': None, 'dimensions_m': None} for i, s in enumerate(stats) if i and s[4] > max(30, rgb.shape[0] * rgb.shape[1] * 0.0003)]
        rows.append({'image': image['path'], 'camera': image['camera'], 'resolution': image['resolution'], 'colored_regions': components, 'metric_scale': 'unknown_without_supporting_evidence'})
        if image.get('role') != 'reference_context' and (not any((c['id'] == image['camera'] for c in scene['cameras']))):
            scene['cameras'].append({'id': image['camera'], 'frame': 'world', 'pose': value(None), 'K': value(None), 'resolution': image['resolution'], 'distortion': value([0.0] * 5, 'estimated')})
    write(project.root / 'working/analysis.json', {'images': rows, 'videos': project.evidence['videos'], 'objects': [{'id': o['id'], 'role': o['role']} for o in scene['objects']], 'note': 'Image components are an inventory, not semantic identities or measured 3D geometry'})
    return scene


def missing_geometry(scene):
    needs = []
    if not scene['objects']:
        needs.append({'need': 'metric dimensions and pose of one support surface, with its visible corners identified', 'reason': 'Images alone do not determine metric scale, depth or hidden object geometry'})
    for camera in scene['cameras']:
        if camera['K']['value'] is None:
            needs.append({'need': f"{camera['id']}: camera intrinsics at the input resolution", 'reason': 'Pixel size cannot be separated from focal length and scene scale'})
        if camera['pose']['value'] is None:
            needs.append({'need': f"{camera['id']}: at least four non-collinear 3D/2D correspondences", 'reason': 'Camera extrinsics are not observable from the current evidence'})
    for obj in scene['objects']:
        for field in ('visual', 'collision'):
            if field == 'collision' and (not obj.get('collision_enabled', True)):
                continue
            geometry = obj[field]
            if geometry['type'] == 'unknown':
                needs.append({'need': f"{obj['id']}: supported {field} primitive or measured mesh", 'reason': 'The shape cannot be inferred from the available metric evidence'})
            if geometry['type'] == 'container' and geometry['wall']['value'] is None:
                needs.append({'need': f"{obj['id']}: measured wall thickness", 'reason': 'Open receptacle collision requires an identifiable floor/wall thickness'})
        for field in ('dimensions', 'pose'):
            if obj[field]['value'] is None:
                needs.append({'need': f"{obj['id']}: {field} in metres/workspace frame", 'reason': 'Interaction-critical geometry is unresolved'})
    return needs


def reports(project, candidate=None, engine='mujoco'):
    path = project.root / ('scratch/agent/' + candidate + '/renders/' + engine + '/metrics.json' if candidate else 'working/validation/report.json')
    if not path.exists():
        return None
    report = read(path)
    scene = read(project.root / 'scratch/agent' / candidate / 'candidate_scene.yaml') if candidate else project.scene
    if report.get('input_signature') != project.signature(scene):
        raise ValueError('Diagnostic render/report is stale')
    return report


def diagnose(report):
    if report is None:
        return {'status': 'NEEDS_MORE_DATA', 'needs': ['Run candidate evaluate or validate to generate fresh metrics'], 'hypotheses': []}
    rows = [o for image in report.get('images', []) for o in image.get('objects', [])]
    hypotheses = []
    vectors = [r for r in rows if r.get('centroid_residual_xy') is not None or r.get('landmark_residual_xy') is not None]
    by_object = {}
    for row in vectors:
        by_object.setdefault(row['object'], []).append(row)
    if len(by_object) > 1:
        per_object = [np.mean([r.get('centroid_residual_xy') or r['landmark_residual_xy'] for r in v], axis=0) for v in by_object.values()]
        common = np.mean(per_object, axis=0)
        spread = np.std(per_object, axis=0)
        if np.linalg.norm(common) > 3 and np.linalg.norm(spread) < np.linalg.norm(common):
            hypotheses.append({'cause': 'camera_or_base', 'confidence': 'tentative', 'evidence': {'common_residual_xy': common.tolist(), 'object_spread_xy': spread.tolist()}, 'experiment': 'Lock objects and test one camera extrinsic or robot-base candidate; compare all views'})
    for name, rr in by_object.items():
        err = max((r.get('center_error_px') or r.get('landmark_rmse_px') or 0 for r in rr))
        if err > 5:
            hypotheses.append({'cause': 'object_pose_or_geometry', 'object': name, 'confidence': 'tentative', 'error_px': err, 'experiment': 'Object-scoped pose candidate first; lock camera/base/dimensions and protect other objects'})
    wrist = [r for r in vectors if r['camera'] == 'wrist']
    if len({r['observation'] for r in wrist}) > 1:
        vv = np.array([r.get('centroid_residual_xy') or r['landmark_residual_xy'] for r in wrist])
        if np.linalg.norm(np.std(vv, axis=0)) > 5:
            hypotheses.append({'cause': 'wrist_mount_or_FK', 'confidence': 'tentative', 'experiment': 'Compare robot-fixed fingertip landmarks and static-object landmarks across poses; measured q stays frozen'})
    pairs = [r['paired_diagnostics'] for r in report.get('images', []) if r.get('paired_diagnostics')]
    unmatched = [p['identity'] for p in pairs if not p.get('identity', {}).get('geometry_comparable')]
    if unmatched:
        hypotheses.insert(0, {'cause': 'historical_runtime_identity_mismatch', 'confidence': 'confirmed_metadata_mismatch_only', 'count': len(unmatched), 'experiment': 'Rerender Builder and Runtime at exactly recorded measured q, same package/camera; RGB alone cannot prove adapter error'})
    elif pairs and any((p['candidate_runtime']['mae'] > 0.05 for p in pairs)):
        hypotheses.append({'cause': 'adapter_or_engine_appearance', 'confidence': 'tentative', 'experiment': 'Compare same-pose projected landmarks/ID silhouettes and world transforms before changing canonical geometry'})
    if not vectors:
        hypotheses.append({'cause': 'geometry_evidence_missing', 'confidence': 'known_missing_evidence', 'experiment': 'Provide real object masks or image landmarks with explicit annotation provenance; global MAE is appearance evidence'})
    if any((not p.get('identity', {}).get('same_q', True) for p in pairs)):
        hypotheses.insert(0, {'cause': 'tracking_or_timing', 'confidence': 'metadata_hypothesis', 'experiment': 'Use static measured-q replay; do not automatically change geometry to compensate for moving plant/time differences'})
    if report.get('camera_calibration'):
        for camera, quality in report['camera_calibration'].items():
            if quality.get('state') != 'CALIBRATED':
                hypotheses.insert(0, {'cause': 'unknown_camera_intrinsic_or_registration', 'camera': camera, 'confidence': 'unverified_calibration', 'experiment': 'Lock measured geometry; initialize K/pose with metric landmarks before object refinement'})
    for rank, hypothesis in enumerate(hypotheses, 1):
        hypothesis['rank'] = rank
    return {'status': 'DIAGNOSTIC_HYPOTHESES', 'hypotheses': hypotheses, 'source_signature': report.get('input_signature'), 'cause_not_established': True, 'photometry_is_not_geometry_acceptance': True}


def coverage(report):
    if report is None:
        return {'status': 'NEEDS_MORE_DATA', 'objects': [], 'recommendations': []}
    by_object = {}
    for image in report.get('images', []):
        for row in image.get('objects', []):
            by_object.setdefault(row['object'], []).append(row)
    objects = []
    recommendations = []
    for name, rows in by_object.items():
        if rows[0].get('role') not in (None, 'support_surface', 'manipulable_object', 'receptacle', 'workspace'):
            continue
        visible = [r for r in rows if (r.get('predicted_visible_pixels') or 0) > 0]
        directions = np.array([r['predicted_view_direction'] for r in visible if r.get('predicted_view_direction')])
        diversity = None
        if len(directions):
            diversity = float(np.rad2deg(np.arccos(np.clip((directions @ directions.T).min(), -1, 1))))
        real = [r for r in rows if r.get('annotation_sources')]
        verified = [r for r in real if any((a.get('provenance') in ('measured', 'verified', 'user_verified') for a in r['annotation_sources']))]
        row = {'object': name, 'predicted_visible_observations': len(visible), 'observation_count': len(rows), 'predicted_direction_diversity_deg': diversity, 'predicted_direction_bins': sorted(set(('top' if v[2] > 0.5 else 'bottom' if v[2] < -0.5 else 'side' for v in directions))), 'provided_real_evidence_observations': len(real), 'verified_real_evidence_observations': len(verified), 'surface_coverage': 'unknown; ID mask does not identify unseen surface normals', 'rim_or_interior_coverage': 'unknown', 'scope': 'simulation visibility prediction; actual exposure/occlusion needs real annotations'}
        objects.append(row)
        if not visible or diversity is None or diversity < 20 or (not verified):
            recommendations.append({'object': name, 'status': 'TENTATIVE', 'manual_teleop_only': True, 'direction': '사용자가 안전한 높이의 사선 Wrist 시점에서 물체를 그리퍼로 가리지 않게 정지 촬영하고, 반대쪽 시점을 추가합니다. 컵은 테두리와 내부가 함께 보이게 합니다.', 'reason': 'Low predicted visibility/diversity or unverified real coverage', 'hardware_command': None})
    return {'status': 'PREDICTED_COVERAGE', 'objects': objects, 'recommendations': recommendations, 'source_signature': report.get('input_signature'), 'automatic_hardware_motion': False}


def validate_scene(project, scene, renderer, folder, thresholds):
    from real2sim_builder.calibration.camera import fit_cameras, fit_geometry, landmark_metrics
    from real2sim_builder.validation import compare, mask_metrics
    images = project.evidence['images']
    masks = project.evidence.get('masks', [])
    rows = []
    rendered = {}
    excluded = []
    for index, image in enumerate(images):
        if image.get('eligible') is False:
            excluded.append({'id': image.get('id'), 'reasons': image.get('exclusion_reasons')})
            continue
        project.checkpoint()
        camera = next((c for c in scene['cameras'] if c['id'] == image['camera']))
        if camera['resolution'] != image['resolution']:
            raise ValueError('Camera calibration resolution differs from evidence; rescale K explicitly')
        real = np.asarray(ImageOps.exif_transpose(Image.open(local_path(project.root, image['path']))).convert('RGB'))
        from real2sim_builder.rendering import for_observation
        with for_observation(project, scene, image, renderer, folder / 'posed' / str(index)) as posed_renderer:
            sim = posed_renderer.rgb(image['camera'])
            ids = {o['id'] for o in scene['objects'] if o['role'] in ('support_surface', 'manipulable_object', 'receptacle', 'workspace')} | {m['object'] for m in masks if m['image'] == image['path']}
            rendered_masks = {n: posed_renderer.mask(image['camera'], n) for n in ids}
            from real2sim_builder.validation import object_metrics
            objects = object_metrics(project, posed_renderer.scene, image, rendered_masks)
            posed_scene = posed_renderer.scene
        rendered[image['path']] = sim
        metrics = compare(real, sim, folder / 'previews' / f"{index:03d}_{image['camera']}")
        if getattr(renderer, 'engine', None) == 'blender':
            Image.fromarray(sim).save(folder / 'previews' / f"{index:03d}_{image['camera']}" / 'blender.png')
        from real2sim_builder.validation import paired_diagnostics
        paired = paired_diagnostics(project, image, real, sim, folder / 'previews' / f"{index:03d}_{image['camera']}" / 'paired', posed_scene, getattr(renderer, 'engine', 'mujoco'))
        if paired:
            metrics['paired_diagnostics'] = paired
        metrics['silhouettes'] = []
        for mask in masks:
            if mask['image'] != image['path']:
                continue
            observed = np.asarray(Image.open(local_path(project.root, mask['path'])).convert('L')) > 0
            metrics['silhouettes'].append({'object': mask['object'], **mask_metrics(observed, rendered_masks[mask['object']])})
        rows.append({'image': image['path'], 'observation': image.get('id'), 'camera': image['camera'], 'split': image['split'], 'objects': objects, **metrics})
    train = [r for r in project.evidence['landmarks'] if r.get('split', 'train') == 'train' and (not r.get('observation'))]
    held = [r for r in project.evidence['landmarks'] if r.get('split', 'train') == 'validation' and (not r.get('observation'))]
    calibration = {'train': landmark_metrics(scene, train), 'validation': landmark_metrics(scene, held)}
    held_images = [r for r in rows if r['split'] == 'validation']
    needs = []
    if not held_images:
        needs.append({'need': 'one independent validation image from a reconstructed camera', 'reason': 'The current scene has no held-out view/frame'})
    constrained = {m['object'] for r in held_images for m in r['silhouettes']}
    for object_id in {r['object'] for r in held if r.get('object')}:
        points = np.array([r['point_m'] for r in held if r.get('object') == object_id])
        if len(points) >= 4 and np.linalg.matrix_rank(points - points.mean(0)) >= 2:
            constrained.add(object_id)
    observation_ids = {i.get('id'): i for i in images if i.get('id') and i.get('eligible') is not False}
    held_pose = [r for r in project.evidence['landmarks'] if r.get('observation') in observation_ids and observation_ids[r['observation']]['split'] == 'validation' and r.get('visible', True) and (r.get('weight', 1) > 0)]
    for object_id in {r['object'] for r in held_pose if r.get('object')}:
        points = np.array([r.get('point_fraction', r.get('point_m')) for r in held_pose if r.get('object') == object_id])
        if len(points) >= 4 and np.linalg.matrix_rank(points - points.mean(0)) >= 2:
            constrained.add(object_id)
    critical = {o['id'] for o in scene['objects'] if o['role'] in ('support_surface', 'manipulable_object', 'receptacle')}
    unconstrained = critical - constrained
    if unconstrained:
        needs.append({'need': 'held-out object masks or measured corner landmarks for ' + ', '.join(sorted(unconstrained)), 'reason': 'Global image similarity does not independently verify interaction-critical geometry'})
    from real2sim_builder.calibration.geometry import metrics as pose_metrics
    ids = {i.get('id'): i for i in images if i.get('id')}
    pose_rows = [r for r in project.evidence['landmarks'] if r.get('observation') in ids]
    multipose = {split: pose_metrics(project, scene, [r for r in pose_rows if ids[r['observation']]['split'] == split]) for split in ('train', 'validation')}
    if project.evidence.get('capture_sessions'):
        train_groups = {i['group_id'] for i in ids.values() if i.get('eligible') and i['split'] == 'train' and i.get('group_id')}
        held_groups = {i['group_id'] for i in ids.values() if i.get('eligible') and i['split'] == 'validation' and i.get('group_id')}
        poses = {tuple(i['q_measured']) for i in ids.values() if i.get('eligible') and i['split'] == 'train' and i.get('q_measured')}
        if train_groups & held_groups:
            raise ValueError('Train/holdout group leakage')
        if len(poses) < 2:
            needs.append({'need': 'at least two distinct measured calibration poses', 'reason': 'Multi-pose consistency is unobservable from one pose'})
        if multipose['validation']['count'] == 0:
            needs.append({'need': 'independent held-out pose landmarks', 'reason': 'Multi-pose kinematic accuracy not validated'})
        if not scene.get('robot_model', {}).get('mapping_verified'):
            needs.append({'need': 'verified real-feedback to model joint mapping', 'reason': 'Capture mapping remains unverified'})
    from real2sim_builder.scene import camera_calibration_signature
    camera_quality = {c['id']: dict(c.get('calibration_quality', {'state': 'ESTIMATED', 'scope': 'no explicit calibration assessment'})) for c in scene['cameras'] if c.get('purpose', 'observation') != 'inspection'}
    for camera in scene['cameras']:
        quality = camera_quality.get(camera['id'])
        if quality and quality['state'] == 'CALIBRATED' and (quality.get('input_sha256') != camera_calibration_signature(scene, camera)):
            quality.update(state='ESTIMATED', reason='Calibration audit is stale after camera/registration/FK changes')
    if scene.get('scan_initialization'):
        if not camera_quality:
            needs.append({'need': 'Actual observation cameras with metric calibration evidence', 'reason': 'Inspection cameras do not validate the physical Side/Wrist projection'})
        registration = scene['scan_initialization']['registration']
        if registration.get('status') == 'NEEDS_MORE_DATA' or not registration.get('metric_scale_verified'):
            needs.append({'need': 'Metric scan-to-robot-world registration', 'reason': 'Nominal glTF local preview is not a registered physical workspace'})
        for camera, quality in camera_quality.items():
            if quality.get('state') != 'CALIBRATED':
                needs.append({'need': camera + ' metric camera calibration with independent evidence', 'reason': 'Scan pixel similarity does not establish camera/geometry consistency'})
    photometric = bool(held_images) and all((r['mae'] <= thresholds['mae'] for r in held_images))
    geometric = all((m['iou'] >= thresholds['silhouette_iou'] and m['center_error_px'] is not None and (m['center_error_px'] <= thresholds['reprojection_px']) for r in held_images for m in r['silhouettes']))
    if held:
        geometric = geometric and calibration['validation']['rmse_px'] <= thresholds['reprojection_px'] and (calibration['validation']['behind_camera'] == 0)
    if multipose['validation']['count']:
        geometric = geometric and multipose['validation']['rmse_px'] <= thresholds['reprojection_px'] and (multipose['validation']['behind_camera'] == 0)
    report = {'camera_calibration': camera_quality, 'excluded_observations': excluded, 'multipose': multipose, 'physics_status': 'PHYSICS_NOT_VALIDATED', 'validation_scope': 'MULTIPOSE_GEOMETRY_VALIDATED' if not needs and photometric and geometric and pose_rows else 'VISUAL_ONLY', 'passed': not needs and photometric and geometric, 'images': rows, 'landmarks': calibration, 'needs': needs, 'thresholds': thresholds, 'train_mae': float(np.mean([r['mae'] for r in rows if r['split'] == 'train'])) if any((r['split'] == 'train' for r in rows)) else None, 'holdout_used_for_fitting': False, 'input_signature': project.signature(scene)}
    report['diagnosis'] = diagnose(report)
    report['coverage'] = coverage(report)
    return (report, rendered)


def refine_visual(project, scene, rendered):
    candidate = copy.deepcopy(scene)
    changes = []
    images = {i['path']: i for i in project.evidence['images']}
    for mask in project.evidence.get('masks', []):
        image = images.get(mask['image'])
        if image is None or image['split'] != 'train' or image['path'] not in rendered:
            continue
        selection = np.asarray(Image.open(local_path(project.root, mask['path'])).convert('L')) > 0
        real = np.asarray(Image.open(project.root / image['path']).convert('RGB')) / 255.0
        sim = rendered[image['path']] / 255.0
        if selection.shape != real.shape[:2] or not selection.any():
            raise ValueError('Empty/wrong-resolution fitting mask')
        linear = lambda x: np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
        gain = np.clip(linear(real[selection]).mean(0) / np.maximum(linear(sim[selection]).mean(0), 0.01), 0.5, 2.0)
        obj = next((o for o in candidate['objects'] if o['id'] == mask['object']))
        original = np.asarray(obj['color']['value'])
        updated = np.clip(original * gain, 0, 1)
        if np.max(abs(original - updated)) > 0.002:
            obj['color']['value'] = updated.tolist()
            obj['color']['provenance'] = 'optimized'
            obj['color']['evidence'].append('train-only object-mask rendered response refinement')
            changes.append(obj['id'])
    return (candidate, changes)


def run(project, renderer='software-egl', max_iterations=8, thresholds=None, *, destination=None):
    project.require_writable()
    from real2sim_builder.calibration.camera import fit_cameras, fit_geometry, landmark_metrics
    from real2sim_builder.rendering import Renderer
    thresholds = thresholds or {'mae': 0.12, 'reprojection_px': 5.0, 'silhouette_iou': 0.8}
    if not 1 <= max_iterations <= 100:
        raise ValueError('max_iterations must be in [1,100]')
    if any((not np.isfinite(v) or v < 0 for v in thresholds.values())):
        raise ValueError('Invalid acceptance thresholds')
    lock = project.root / 'working/run.lock'
    try:
        handle = lock.open('x')
    except FileExistsError as exc:
        raise RuntimeError('Project is busy or its prior owner is unknown; explicit recovery required') from exc
    import os
    handle.write(str(os.getpid()))
    handle.close()
    try:
        project.update(status='RUNNING', needs=[], error=None)
        project.checkpoint()
        project.update(stage='ANALYZE', task='Extract video frames and inventory evidence')
        extract_videos(project)
        from real2sim_builder.calibration.geometry import undistort_evidence
        undistort_evidence(project)
        if not project.evidence['images']:
            return project.update(status='NEEDS_MORE_DATA', decision='NEEDS_MORE_DATA', needs=[{'need': 'one real workspace image or video', 'reason': 'No visual evidence was imported'}])
        scene = analyze(project)
        project.save_scene(scene)
        start = project.state.get('iteration', 0)
        for iteration in range(start, start + max_iterations):
            project.checkpoint()
            project.update(stage='CAMERA & SCALE', iteration=iteration + 1, task='Fit only supported camera parameters', decision='CONTINUE')
            camera_rows = [r for r in project.evidence['landmarks'] if not r.get('observation') and (not r.get('object') or next((o for o in scene['objects'] if o['id'] == r['object']))['pose']['provenance'] in ('measured', 'calibrated', 'derived'))]
            candidate, fit_report = fit_cameras(scene, camera_rows)
            candidate, geometry_report = fit_geometry(candidate, [r for r in project.evidence['landmarks'] if not r.get('observation')])
            from real2sim_builder.calibration.geometry import fit_depth_geometry
            candidate, depth_report = fit_depth_geometry(candidate, project.evidence, project.root)
            scene = candidate
            project.save_scene(scene)
            project.update(metrics={'camera_fit': fit_report, 'geometry_fit': geometry_report, 'depth_bounds': depth_report})
            needs = missing_geometry(scene)
            if needs:
                return project.update(status='NEEDS_MORE_DATA', decision='NEEDS_MORE_DATA', needs=needs)
            project.update(stage='GEOMETRY', task='Check metric geometry, frame graph and collision representations')
            validate(scene, project.root, complete=True)
            project.update(stage='VISUAL', task='Render calibrated cameras; preserve geometry while fitting appearance')
            folder = project.root / 'working/validation'
            with Renderer(scene, project.root, project.root / 'scratch', renderer) as engine:
                project.update(stage='PHYSICS', task='Check passive scene integrity; do not infer unobservable physical parameters')
                motion_report = []
                if project.evidence.get('motions'):
                    from real2sim_builder.calibration.physics import fit
                    try:
                        scene, motion_report = fit(scene, project.root, project.root / 'scratch', project.evidence['motions'])
                    except ValueError as exc:
                        return project.update(status='NEEDS_MORE_DATA', decision='NEEDS_MORE_DATA', needs=[{'need': 'measured passive-motion evidence sufficient to separate mass, support contact and timing', 'reason': str(exc)}])
                    project.save_scene(scene)
                    if any((r['split'] == 'validation' and r['rmse_m'] > 0.005 for r in motion_report)):
                        return project.update(status='NEEDS_MORE_DATA', decision='NEEDS_MORE_DATA', needs=[{'need': 'independent contact geometry/timing measurements for the failed passive-motion case', 'reason': 'Held-out dynamics error exceeds 5 mm; physics parameters must not hide geometry/timing errors'}])
                data = engine.mj.MjData(engine.model)
                for _ in range(20):
                    engine.mj.mj_step(engine.model, data)
                if not np.isfinite(data.qpos).all():
                    raise RuntimeError('Nonfinite passive physics')
                project.update(stage='VALIDATION', task='Compare pixels, silhouettes and held-out metric landmarks')
                report, rendered = validate_scene(project, scene, engine, folder, thresholds)
                report.update(iteration=iteration + 1, camera_fit=fit_report, geometry_fit=geometry_report, depth_bounds=depth_report, physics={'scope': 'passive finite scene check; unknown parameters not guessed', 'motions': motion_report}, renderer=renderer)
            write(folder / 'report.json', report)
            project.update(metrics={'train_mae': report['train_mae'], 'holdout_landmarks': report['landmarks']['validation']}, task='Diagnose dominant mismatch')
            if report['passed']:
                project.update(stage='EXPORT', decision='CONTINUE', task='Write and load dual-engine package')
                if destination is None:
                    return project.update(status='DRAFT', stage='VALIDATION', decision='CONTINUE', task='Validation passed; select a new explicit export destination', needs=[])
                from real2sim_builder.export import export_revision
                identity = export_revision(project, destination=Path(destination))
                return project.update(status='ACCEPTED', decision='ACCEPTED', export=str(Path(destination).resolve()), export_identity={'scene_id':identity.scene_id,'revision':identity.revision,'manifest_sha256':identity.manifest_sha256}, needs=[])
            if report['needs']:
                return project.update(status='NEEDS_MORE_DATA', decision='NEEDS_MORE_DATA', needs=report['needs'])
            candidate, changes = refine_visual(project, scene, rendered)
            if not changes:
                return project.update(status='NEEDS_MORE_DATA', decision='NEEDS_MORE_DATA', needs=[{'need': 'measured landmarks or a train object mask for the camera/object with the largest mismatch', 'reason': 'Current evidence does not support another identifiable camera/appearance correction'}])
            with Renderer(candidate, project.root, project.root / 'scratch', renderer) as engine:
                trial, _ = validate_scene(project, candidate, engine, project.root / 'scratch/candidate', thresholds)
            if report['train_mae'] is None or trial['train_mae'] is None or trial['train_mae'] >= report['train_mae'] - 1e-05:
                return project.update(status='NEEDS_MORE_DATA', decision='NEEDS_MORE_DATA', needs=[{'need': 'material/lighting reference for ' + ', '.join(changes), 'reason': 'Train render response does not improve; color and illumination remain ambiguous'}])
            scene = candidate
            project.save_scene(scene)
            project.update(decision='RETRY', task='Train fit improved; rerender without geometry changes')
        return project.update(status='FAILED', decision='FAILED', error='Iteration budget exhausted without validation acceptance')
    except InterruptedError:
        return project.update(status='STOPPED', decision='CONTINUE', task='Resume from working/current_scene.yaml')
    except Exception as exc:
        project.update(status='FAILED', decision='FAILED', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        lock.unlink(missing_ok=True)


def evaluate_project(project, engine='blender', renderer='software-egl'):
    from real2sim_builder.rendering import Renderer
    'No fitting: final held-out evaluation, MuJoCo sanity, structural dual-engine parity.'
    from real2sim_builder.candidate import exclusive
    from real2sim_builder.rendering import BlenderRenderer
    from real2sim_builder.exporters import mjcf as mujoco, usd
    from real2sim_builder.validation import check
    with exclusive(project):
        scene = project.scene
        validate(scene, project.root, complete=True)
        factory = BlenderRenderer if engine == 'blender' else Renderer
        folder = project.root / 'working/validation'
        with factory(scene, project.root, project.root / 'scratch/final_render', renderer) as model:
            report, _ = validate_scene(project, scene, model, folder, {'mae': 0.12, 'reprojection_px': 5.0, 'silhouette_iou': 0.8})
        with Renderer(scene, project.root, project.root / 'scratch/final_physics', renderer) as physics:
            data = physics.mj.MjData(physics.model)
            for _ in range(20):
                physics.mj.mj_step(physics.model, data)
            finite = bool(np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all())
        parity_dir = project.root / 'scratch/final_parity'
        parity_dir.mkdir(parents=True, exist_ok=True)
        mujoco.export(scene, project.root, parity_dir / 'scene.xml')
        usd.export(scene, project.root, parity_dir / 'scene.usd')
        parity = check(scene, project.root, parity_dir / 'scene.xml', parity_dir / 'scene.usd')
        report.update(engine=engine, physics={'finite': finite, 'scope': '20 passive steps; not identified dynamics'}, cross_engine_parity=parity)
        report['passed'] = bool(report['passed'] and finite and (parity['status'] == 'PASS'))
        if parity['status'] != 'PASS':
            report['needs'].append({'need': 'Cross-engine structural parity PASS', 'reason': str(parity)})
        write(folder / 'report.json', report)
        if not report['passed']:
            project.update(status='NEEDS_MORE_DATA' if report['needs'] else 'FAILED', stage='VALIDATION', decision='NEEDS_MORE_DATA' if report['needs'] else 'FAILED', needs=report['needs'], metrics={'train_mae': report['train_mae']}, export=None)
        else:
            project.update(status='DRAFT', stage='VALIDATION', decision='CONTINUE', task='Validation passed; export to accept')
        return report

