"""Candidate-local image proposals reviewed by Codex, never measured evidence."""
import copy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .files import read, sha, write
from .scene import identifier, local_path


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _scene_digest(scene):
    return _digest({k: v for k, v in scene.items() if k != 'derived_observations'})


def registered_images(project, scene_state=None):
    """Select one declared layout; do not discover media outside Evidence."""
    images = [i for i in project.evidence['images']
              if i.get('eligible') is True and i.get('id')
              and i.get('camera') in ('side', 'wrist') and i.get('q_measured') is not None]
    states = {i.get('scene_state_id') for i in images if i.get('scene_state_id')}
    if scene_state is None:
        if len(states) != 1:
            return [], None, ['Choose one scene_state_id from registered eligible captures']
        scene_state = next(iter(states))
    identifier(scene_state)
    images = [i for i in images if i.get('scene_state_id') == scene_state]
    for image in images:
        path = local_path(project.root, image['path'])
        if not image.get('sha256') or sha(path) != image['sha256']:
            raise ValueError('Registered image SHA mismatch: ' + image['id'])
        q = np.asarray(image['q_measured'], float)
        if q.shape != (len(image['joint_names']),) or not np.isfinite(q).all():
            raise ValueError('Invalid measured joints: ' + image['id'])
    return images, scene_state, [] if images else ['No eligible measured-q images in this layout']


def annotation_evidence(project, scene):
    """Merge an approved Candidate layer for readers; leave input/evidence.yaml intact."""
    result = copy.deepcopy(project.evidence)
    layer = scene.get('derived_observations', {})
    images = {i.get('id'): i for i in result['images'] if i.get('id')}
    for row in layer.get('sources', []):
        image = images.get(row['image_id'])
        if image is None or image['sha256'] != row['source_image_sha256']:
            raise ValueError('Approved observation source identity changed')
        if (image.get('scene_state_id') != row['scene_state_id']
                or _digest(image) != row['image_record_sha256']
                or sha(local_path(project.root, image['path'])) != image['sha256']):
            raise ValueError('Approved observation layout/image changed')
    for row in layer.get('masks', []):
        if sha(local_path(project.root, row['path'])) != row['sha256']:
            raise ValueError('Approved mask changed')
    for kind in ('landmarks', 'masks'):
        result.setdefault(kind, []).extend(copy.deepcopy(layer.get(kind, [])))
    return result


def _patterns(gray, config):
    if not config:
        return []
    aruco = getattr(cv2, 'aruco', None)
    if aruco is None:
        return []
    dictionary = aruco.getPredefinedDictionary(getattr(aruco, config['dictionary']))
    if config['type'] == 'aruco':
        corners, ids, _ = aruco.ArucoDetector(dictionary).detectMarkers(gray)
        return [] if ids is None else [(f'aruco_{int(n)}_corner_{j}', p.tolist(),
                                        config.get('object_ids', {}).get(str(int(n))))
                                       for points, n in zip(corners, ids.ravel())
                                       for j, p in enumerate(points.reshape(-1, 2))]
    if config['type'] == 'charuco':
        board = aruco.CharucoBoard(tuple(config['squares']), config['square_length_m'],
                                  config['marker_length_m'], dictionary)
        corners, ids, _, _ = aruco.CharucoDetector(board).detectBoard(gray)
        return [] if ids is None else [(f'charuco_corner_{int(n)}', p.tolist(), config.get('object_id'))
                                       for p, n in zip(corners.reshape(-1, 2), ids.ravel())]
    raise ValueError('Pattern must explicitly be aruco or charuco')


def _image_proposals(rgb, scene, options):
    """Color components and rim/quad suggestions carry hints, not semantic certainty."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    rows = []
    for obj in scene['objects']:
        if obj['role'] not in ('manipulable_object', 'receptacle', 'workspace', 'reference_robot'):
            continue
        spec = options.get('objects', {}).get(obj['id'], {})
        roi = np.zeros(rgb.shape[:2], np.uint8)
        x, y, w, h = spec.get('roi_xywh', [0, 0, rgb.shape[1], rgb.shape[0]])
        if not (0 <= x < x + w <= rgb.shape[1] and 0 <= y < y + h <= rgb.shape[0]):
            raise ValueError('ROI must be inside the original image')
        roi[y:y+h, x:x+w] = 1
        color = obj.get('color', {}).get('value')
        if color is not None:
            sample = np.uint8(np.clip(np.array(color) * 255, 0, 255)).reshape(1, 1, 3)
            hue, saturation, _ = cv2.cvtColor(sample, cv2.COLOR_RGB2HSV)[0, 0]
            if saturation > 50:
                delta = abs(hsv[:, :, 0].astype(int) - int(hue))
                mask = ((np.minimum(delta, 180-delta) <= spec.get('hue_radius', 12))
                        & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 35) & (roi > 0)).astype('uint8')
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
                count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
                indices = sorted(range(1, count), key=lambda i: int(stats[i, 4]), reverse=True)
                for index in indices[:options.get('max_components', 3)]:
                    if stats[index, 4] < options.get('min_area_px', 50):
                        continue
                    component = np.uint8(labels == index)
                    contour, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    contour = max(contour, key=cv2.contourArea)
                    quad = cv2.approxPolyDP(contour, .025 * cv2.arcLength(contour, True), True)
                    rows.append({'object_hint': obj['id'], 'feature_id': 'visible_color_component',
                                 'mask': component, 'mask_kind': 'silhouette',
                                 'bbox_xywh': stats[index, :4].tolist(), 'detector': 'hsv_component',
                                 'confidence': .5, 'corner_candidates_px': quad[:, 0].tolist()
                                 if len(quad) == 4 else [], 'corner_order_verified': False})
        if obj['role'] not in ('receptacle', 'workspace'):
            continue
        edges = cv2.Canny(rgb, 70, 160) * roi
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:options.get('max_components', 3)]:
            if cv2.contourArea(contour) < options.get('min_area_px', 50):
                continue
            if obj['role'] == 'receptacle' and len(contour) >= 12:
                ellipse = cv2.fitEllipse(contour)
                mask = np.zeros(rgb.shape[:2], np.uint8)
                cv2.ellipse(mask, ellipse, 1, 2)
                mask *= roi
                rows.append({'object_hint': obj['id'], 'feature_id': 'rim_candidate', 'mask': mask,
                             'mask_kind': 'visible_rim', 'ellipse': ellipse, 'detector': 'edge_ellipse',
                             'confidence': .3, 'inspection_only': True})
            elif obj['role'] == 'workspace':
                quad = cv2.approxPolyDP(contour, .02 * cv2.arcLength(contour, True), True)
                if len(quad) == 4:
                    rows.append({'object_hint': obj['id'], 'feature_id': 'paper_quad_candidate',
                                 'corner_candidates_px': quad[:, 0].tolist(), 'detector': 'edge_quad',
                                 'confidence': .3, 'corner_order_verified': False, 'inspection_only': True})
    return rows


def propose_observations(project, *, scene_state=None, options=None, candidate=None):
    from .candidate import Candidate, exclusive
    options = copy.deepcopy(options or {})
    name = candidate or 'auto_observations'
    identifier(name)
    c = Candidate(project, name) if (project.root/'scratch/agent'/name/'candidate.json').exists() else Candidate.create(project, name)
    with exclusive(project):
        c.require_open()
        images, state, needs = registered_images(project, scene_state)
        scene = c.scene
        payload = {'images': images, 'options': options, 'scene': _scene_digest(scene), 'scene_state_id': state}
        digest = _digest(payload)
        folder = c.root/'observations'/digest[:20]
        path = folder/'proposals.json'
        if path.exists():
            return read(path)
        proposals = []
        for image in images:
            rgb = np.asarray(Image.open(local_path(project.root, image['path'])).convert('RGB'))
            if list(rgb.shape[1::-1]) != image['resolution']:
                raise ValueError('Image resolution changed')
            preview = Image.fromarray(rgb)
            draw = ImageDraw.Draw(preview)
            image_options = copy.deepcopy(options)
            image_options['objects'] = {**options.get('objects', {}),
                                        **options.get('images', {}).get(image['id'], {}).get('objects', {})}
            raw = _image_proposals(rgb, scene, image_options)
            corners = []
            for row in raw:
                for index, uv in enumerate(row.get('corner_candidates_px', [])):
                    corners.append({'object_hint': row['object_hint'], 'feature_id': row['feature_id']+f'_corner_{index}',
                                    'uv_px': uv, 'detector': row['detector'], 'confidence': row['confidence'],
                                    'corner_order_verified': False})
            raw.extend(corners)
            pattern = options.get('pattern')
            if pattern and getattr(cv2, 'aruco', None) is None:
                needs.append('OpenCV aruco module unavailable; no pattern detector was run')
            raw.extend({'feature_id': feature, 'uv_px': uv, 'object_hint': hint,
                        'detector': pattern['type'], 'confidence': .9}
                       for feature, uv, hint in _patterns(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), pattern))
            for index, row in enumerate(raw):
                key = hashlib.sha256(f"{digest}:{image['id']}:{index}".encode()).hexdigest()[:24]
                mask = row.pop('mask', None)
                row.update(id=key, image_id=image['id'], scene_state_id=state, camera=image['camera'],
                           object_id=None, occluded=None, source_image_sha256=image['sha256'],
                           image_record_sha256=_digest(image),
                           provenance='derived', correspondence_verified=False)
                if mask is not None:
                    target = folder/(key+'.png')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(mask*255).save(target)
                    row.update(mask_path=target.relative_to(project.root).as_posix(), mask_sha256=sha(target))
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for contour in contours:
                        points = [tuple(map(int, p)) for p in contour[:, 0]]
                        if len(points) > 1:
                            draw.line(points+[points[0]], fill='red', width=2)
                            draw.text(points[0], key[:8], fill='red')
                if row.get('corner_candidates_px'):
                    points = [tuple(p) for p in row['corner_candidates_px']]
                    draw.line(points+[points[0]], fill='orange', width=2)
                if row.get('bbox_xywh'):
                    x, y, w, h = row['bbox_xywh']
                    draw.rectangle((x, y, x+w, y+h), outline='red', width=2)
                    draw.text((x, y), key[:8], fill='red')
                if row.get('uv_px'):
                    x, y = row['uv_px']
                    draw.ellipse((x-3, y-3, x+3, y+3), fill='red')
                proposals.append(row)
            folder.mkdir(parents=True, exist_ok=True)
            preview.save(folder/(hashlib.sha256(image['id'].encode()).hexdigest()[:20]+'_preview.png'))
        report = {'schema': 'real2sim.observation-proposals/1', 'candidate': name,
                  'scene_state_id': state, 'project_id': project.info['id'], 'input_digest': digest,
                  'scene_sha256': _scene_digest(scene),
                  'proposal_file': path.relative_to(project.root).as_posix(), 'proposals': proposals,
                  'needs': needs or ([] if proposals else ['No reliable feature proposed; retain the Scene draft']),
                  'status': 'PROPOSED' if proposals else 'NEEDS_MORE_DATA', 'physical_verified': False}
        write(path, report)
        return report


def commit_observation_proposals(project, proposal_file, *, selections=None):
    """Codex explicitly binds proposal IDs to objects/CAD points, not a user checklist."""
    from .candidate import Candidate, exclusive
    path = Path(proposal_file)
    path = local_path(project.root, path.relative_to(project.root).as_posix()) if path.is_absolute() else local_path(project.root, str(path))
    proposal = read(path)
    if proposal.get('schema') != 'real2sim.observation-proposals/1' or proposal.get('project_id') != project.info['id']:
        raise ValueError('Proposal belongs to another Project/schema')
    c = Candidate(project, proposal['candidate'])
    if not path.is_relative_to(c.root/'observations') or selections is None:
        raise ValueError('Candidate-local proposal and explicit Codex selections are required')
    with exclusive(project):
        c.require_open()
        scene = c.scene
        if _scene_digest(scene) != proposal['scene_sha256']:
            raise ValueError('Candidate geometry changed; generate proposals again')
        objects = {o['id']: o for o in scene['objects']}
        images, state, _ = registered_images(project, proposal['scene_state_id'])
        images = {i['id']: i for i in images}
        proposals = {r['id']: r for r in proposal['proposals']}
        layer = copy.deepcopy(scene.get('derived_observations', {'landmarks': [], 'masks': [], 'sources': []}))
        if any(s['scene_state_id'] != state for s in layer['sources']):
            raise ValueError('Use a separate Candidate for a different static layout')
        for selection in selections:
            row = proposals[selection['proposal_id']]
            image = images[row['image_id']]
            if image['sha256'] != row['source_image_sha256'] or _digest(image) != row['image_record_sha256']:
                raise ValueError('Proposal image changed')
            object_id = selection.get('object_id')
            if object_id not in objects:
                raise ValueError('Codex must identify an existing object explicitly')
            common = {'proposal_id': row['id'], 'observation': image['id'], 'object': object_id,
                      'camera': image['camera'], 'split': image['split'], 'scene_state_id': state,
                      'provenance': 'derived', 'source_image_sha256': image['sha256'],
                      'confidence': row['confidence'], 'occluded': selection.get('occluded', row['occluded']),
                      'detector': row['detector'], 'physical_verified': False}
            common['feature_id'] = row['feature_id']
            uv = selection.get('uv_px', row.get('uv_px'))
            point = {k: selection[k] for k in ('point_m', 'point_fraction') if k in selection}
            if point:
                if len(point) != 1 or uv is None or selection.get('correspondence_verified') is not True:
                    raise ValueError('A visible CAD-to-pixel correspondence must be explicitly reviewed')
                if np.asarray(uv).shape != (2,) or not np.isfinite(uv).all() or not (0 <= uv[0] < image['resolution'][0] and 0 <= uv[1] < image['resolution'][1]):
                    raise ValueError('Pixel must be finite and inside the original image')
                coordinates = np.asarray(next(iter(point.values())), float)
                if coordinates.shape != (3,) or not np.isfinite(coordinates).all():
                    raise ValueError('CAD point must contain three finite coordinates')
                if 'point_fraction' in point and objects[object_id]['dimensions']['value'] is None:
                    raise ValueError('Initialize CAD dimensions before binding a fractional point')
                sigma = float(selection.get('sigma_px', 3))
                if not np.isfinite(sigma) or sigma <= 0:
                    raise ValueError('Pixel uncertainty must be finite and positive')
                record = {**common, **point, 'uv': list(uv), 'visible': common['occluded'] is not True,
                          'sigma_px': sigma, 'weight': 1.}
                kind = 'landmarks'
            elif row.get('mask_path'):
                mask = local_path(project.root, row['mask_path'])
                if not mask.is_relative_to(c.root/'observations') or sha(mask) != row['mask_sha256']:
                    raise ValueError('Proposal mask changed or is outside this Candidate')
                record = {**common, 'image': image['path'], 'path': row['mask_path'],
                          'sha256': row['mask_sha256'], 'mask_kind': row['mask_kind']}
                if record['mask_kind'] == 'silhouette' and common['occluded'] is not False:
                    record['mask_kind'] = 'visible_fragment'
                kind = 'masks'
            else:
                raise ValueError('Inspection-only corners need an explicit uv_px and CAD point')
            def same_feature(existing):
                if existing.get('proposal_id') == row['id']:
                    return True
                if existing['observation'] != image['id'] or existing['object'] != object_id:
                    return False
                if kind == 'masks':
                    return existing.get('mask_kind') == record.get('mask_kind')
                return any(k in record and existing.get(k) == record[k] for k in ('point_m', 'point_fraction'))
            layer[kind] = [r for r in layer[kind] if not same_feature(r)]+[record]
            source = {'image_id': image['id'], 'scene_state_id': state, 'source_image_sha256': image['sha256'],
                      'image_record_sha256': _digest(image)}
            if source not in layer['sources']:
                layer['sources'].append(source)
        scene['derived_observations'] = layer
        c.save(scene)
        return {'status': 'COMMITTED_DERIVED', 'candidate': c.name,
                'landmarks': len(layer['landmarks']), 'masks': len(layer['masks']), 'physical_verified': False}
