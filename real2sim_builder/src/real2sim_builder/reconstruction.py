"""Stored scan reconstruction, registration/segmentation and bounded review loop.
No engine or device is imported until its explicit rendering/physics path is used.
"""
# Port of original reconstruction/scan.py
"""GLB reconstruction evidence: immutable import, explicit ROI and metric registration.

Texture/geometry are scan estimates, never raw LiDAR or automatic semantic labels.
The only optional dependency is the existing mesh extra (trimesh).
"""
import copy
import json
import struct
import io
import base64
from pathlib import Path
import numpy as np
from real2sim_builder.project import read, write, sha
from real2sim_builder.project import value, transform, identifier, validate
from real2sim_builder.project import copy_input, asset_importer
from real2sim_builder.project import exclusive

def load(path, textures=False):
    import trimesh
    path = Path(path)
    data = path.read_bytes()
    if len(data) < 20 or struct.unpack('<III', data[:12]) != (1179937895, 2, len(data)):
        raise ValueError('Expected intact glTF 2 binary GLB')
    length, kind = struct.unpack('<II', data[12:20])
    if kind != 1313821514 or length > len(data) - 20:
        raise ValueError('Missing GLB JSON chunk')
    header = json.loads(data[20:20 + length])
    for row in header.get('images', []) + header.get('buffers', []):
        if row.get('uri') and (not row['uri'].startswith('data:')):
            raise ValueError('GLB external dependencies must be embedded before import')
    preview_header = copy.deepcopy(header)
    preview_header['images'] = []
    preview_header['textures'] = []
    binary_start = 20 + length + 8
    for material in preview_header.get('materials', []):
        pbr = material.get('pbrMetallicRoughness', {})
        for key in list(material):
            if key not in ('pbrMetallicRoughness', 'name', 'doubleSided', 'alphaMode', 'alphaCutoff'):
                material.pop(key)
        pbr.pop('metallicRoughnessTexture', None)
        texture = pbr.pop('baseColorTexture', None)
        if textures and texture:
            image_index = header['textures'][texture['index']]['source']
            image_row = header['images'][image_index]
            if 'bufferView' not in image_row:
                raise ValueError('Embedded GLB bufferView images required for textured preview')
            view = header['bufferViews'][image_row['bufferView']]
            offset = binary_start + view.get('byteOffset', 0)
            from PIL import Image
            with Image.open(io.BytesIO(data[offset:offset + view['byteLength']])) as image:
                image.draft('RGB', (2048, 2048))
                image.thumbnail((2048, 2048))
                image = image.convert('RGB')
                stream = io.BytesIO()
                image.save(stream, format='PNG')
            i = len(preview_header['images'])
            preview_header['images'].append({'uri': 'data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode()})
            preview_header['textures'].append({'source': i})
            pbr['baseColorTexture'] = {'index': i}
    encoded = json.dumps(preview_header).encode()
    encoded += b' ' * (-len(encoded) % 4)
    binary = data[20 + length:]
    sanitized = struct.pack('<III', 1179937895, 2, 20 + len(encoded) + len(binary)) + struct.pack('<II', len(encoded), 1313821514) + encoded + binary
    scene = trimesh.load(io.BytesIO(sanitized), file_type='glb', force='scene', process=False)
    instances = []
    for name in sorted(scene.graph.nodes_geometry):
        matrix, geometry = scene.graph[name]
        mesh = scene.geometry[geometry].copy()
        mesh.apply_transform(matrix)
        if not len(mesh.faces) or not np.isfinite(mesh.vertices).all():
            raise ValueError('Empty/nonfinite GLB geometry')
        instances.append((name, mesh, np.asarray(matrix)))
    if not instances:
        raise ValueError('GLB contains no triangle meshes')
    expected = sum((len(m.get('primitives', [])) for m in header.get('meshes', [])))
    if len(scene.geometry) < expected:
        raise ValueError('GLB primitive/texture decode failed; partial import is not allowed')
    return (header, instances)

def inspect_file(path):
    header, instances = load(path)
    reports = []
    for name, mesh, matrix in instances:
        edges, count = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
        material = getattr(mesh.visual, 'material', None)
        image = getattr(material, 'baseColorTexture', None) or getattr(material, 'image', None)
        uv = getattr(mesh.visual, 'uv', None)
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        adjacent = mesh.face_adjacency
        components = connected_components(coo_matrix((np.ones(len(adjacent)), (adjacent[:, 0], adjacent[:, 1])), shape=(len(mesh.faces), len(mesh.faces))), directed=False, return_labels=False)
        reports.append(dict(node=name, node_transform=matrix.tolist(), bounds_scan=mesh.bounds.tolist(), vertices=len(mesh.vertices), faces=len(mesh.faces), degenerate_faces=int(np.count_nonzero(mesh.area_faces < 1e-14)), open_boundary_edges=int(np.count_nonzero(count == 1)), nonmanifold_edges=int(np.count_nonzero(count > 2)), watertight=bool(mesh.is_watertight), connected_components=int(components), texture_loaded=False, texture_decoding='inspection is geometry-only; bounded base-colour decode occurs at initialization', uv_present=uv is not None, uv_finite=bool(np.isfinite(uv).all()) if uv is not None else None, material_type=type(material).__name__, unsupported_material_channels=['normal/occlusion/emissive maps are retained in source GLB, not baked by canonical exporter']))
    bounds = np.array([r['bounds_scan'] for r in reports])
    image_reports = []
    issues = []
    data = Path(path).read_bytes()
    length = struct.unpack('<I', data[12:16])[0]
    start = 20 + length + 8
    from PIL import Image
    for index, image in enumerate(header.get('images', [])):
        try:
            view = header['bufferViews'][image['bufferView']]
            offset = start + view.get('byteOffset', 0)
            if offset + view['byteLength'] > len(data):
                raise ValueError('Image buffer outside GLB')
            with Image.open(io.BytesIO(data[offset:offset + view['byteLength']])) as decoded:
                image_reports.append({'index': index, 'resolution': list(decoded.size), 'format': decoded.format})
                decoded.verify()
        except Exception as exc:
            issues.append({'index': index, 'error': str(exc)})
    return dict(schema='real2sim.scan/1', source_sha256=sha(path), evidence_kind='reconstructed_textured_mesh_not_sensor_depth', gltf_coordinates='right-handed +Y up; node transforms baked; convert explicitly to +Z world', gltf_declared_units='metres per glTF specification; scanner metric accuracy unverified', metric_scale_status='UNKNOWN', asset=header.get('asset', {}), nodes=reports, bounds_scan=[bounds[:, 0].min(0).tolist(), bounds[:, 1].max(0).tolist()], embedded_images=len(header.get('images', [])), images=image_reports, texture_issues=issues, texture_policy='Original maps immutable; derived preview base colour capped at 2048px; normal/occlusion/roughness maps not baked', physics_status='PHYSICS_NOT_VALIDATED')

def import_scan(project, path):
    with exclusive(project):
        report = inspect_file(path)
        stored = copy_input(project, path, 'scans')
        evidence = project.evidence
        row = {'id': 'scan_' + report['source_sha256'][:16], 'path': stored, 'sha256': report['source_sha256'], 'kind': report['evidence_kind']}
        if not any((r['sha256'] == row['sha256'] for r in evidence.get('scans', []))):
            evidence.setdefault('scans', []).append(row)
            write(project.root / 'input/evidence.yaml', evidence)
            project.invalidate()
        write(project.root / 'working/scans' / row['id'] / 'inspection.json', report)
        return {**row, 'inspection': report}

def registration(config):
    """Weighted rigid/similarity registration, with explicit scale evidence."""
    rows = config.get('correspondences', [])
    if len(rows) < 3:
        return {'status': 'NEEDS_MORE_DATA', 'needs': ['At least 3 non-collinear scan/world 3D correspondences with metric world evidence']}
    if any((r.get('source') not in ('measured', 'calibrated') or not r.get('evidence') for r in rows)):
        raise ValueError('Registration world points require measured/calibrated evidence identity')
    x = np.asarray([r['scan'] for r in rows], float)
    y = np.asarray([r['world_m'] for r in rows], float)
    weights = np.asarray([r.get('weight', 1.0) for r in rows], float)
    if x.shape != y.shape or x.shape[1:] != (3,) or (not np.isfinite(x).all()) or (not np.isfinite(y).all()) or (not np.isfinite(weights).all()) or (min(weights) <= 0):
        raise ValueError('Finite 3D registration points and positive weights required')
    weights /= weights.sum()
    a = weights @ x
    b = weights @ y
    xx = x - a
    yy = y - b
    ranks = [int(np.linalg.matrix_rank(t)) for t in (xx, yy)]
    if min(ranks) < 2:
        return {'status': 'NEEDS_MORE_DATA', 'rank': ranks, 'needs': ['Non-collinear points; baseline orientation is ambiguous']}
    u, singular, vt = np.linalg.svd((xx * weights[:, None]).T @ yy)
    sign = np.diag([1.0, 1.0, np.linalg.det(vt.T @ u.T)])
    rotation = vt.T @ sign @ u.T
    fitted_scale = float(np.sum(singular * np.diag(sign)) / np.sum(weights[:, None] * xx ** 2))
    similarity = bool(config.get('fit_scale', False))
    scale = fitted_scale if similarity else float(config.get('scale', 1.0))
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError('Positive registration scale required')
    t = np.eye(4)
    t[:3, :3] = rotation
    t[:3, 3] = b - rotation @ (a * scale)
    residual = np.linalg.norm(x * scale @ rotation.T + t[:3, 3] - y, axis=1)
    ratios = []
    for i in range(len(x)):
        for j in range(i):
            distance = np.linalg.norm(x[i] - x[j])
            if distance > 1e-09:
                ratios.append(float(np.linalg.norm(y[i] - y[j]) / distance))
    tolerance = float(config.get('tolerance_m', 0.005))
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError('Positive registration tolerance required')
    metric = similarity or bool(config.get('metric_scale_evidence'))
    passed = metric and max(residual) <= tolerance
    return dict(status='ESTIMATED' if passed else 'NEEDS_MORE_DATA', scale=scale, T_world_scan=t.tolist(), residual_m=residual.tolist(), rmse_m=float(np.sqrt(weights @ residual ** 2)), rank=ranks, singular_values=singular.tolist(), correspondences=rows, metric_scale_verified=metric, scale_ratios=ratios, scale_diagnosis='possible local scan distortion' if ratios and np.std(ratios) / np.mean(ratios) > 0.03 else 'consistent global scale within sampled landmarks', uncertainty_scope='registration evidence only; planar points do not verify unseen scan depth', needs=[] if passed else ['Metric scale evidence and registration residual within tolerance required'])

def scale_from_lengths(rows):
    """Robust nominal scan scale from measured lengths, not full world registration."""
    if not rows:
        return {'status': 'UNKNOWN', 'scale': 1.0, 'metric_scale_verified': False}
    ratios = []
    for row in rows:
        if row.get('source') != 'measured' or not row.get('evidence'):
            raise ValueError('Length scale anchors require measured source/evidence')
        a = float(row['scan_distance'])
        b = float(row['measured_distance_m'])
        if not np.isfinite([a, b]).all() or min(a, b) <= 0:
            raise ValueError('Positive finite scale lengths required')
        ratios.append(b / a)
    scale = float(np.median(ratios))
    spread = float(np.std(ratios) / max(np.mean(ratios), 1e-12))
    return {'status': 'ESTIMATED', 'scale': scale, 'ratios': ratios, 'relative_ratio_std': spread, 'metric_scale_verified': False, 'evidence': rows, 'diagnosis': 'possible local scan distortion or incomplete extent evidence' if spread > 0.03 else 'sampled measured lengths suggest a consistent global scale', 'scope': 'measured length anchors + reconstructed scan extents; not surveyed world registration or full-scan metric certification'}

def plane(points, tolerance=0.005, seed=0):
    if len(points) < 3:
        return {'status': 'NEEDS_MORE_DATA'}
    rng = np.random.default_rng(seed)
    sample = points if len(points) < 20000 else points[rng.choice(len(points), 20000, replace=False)]
    best = np.zeros(len(sample), dtype=bool)
    for _ in range(128):
        triangle = sample[rng.choice(len(sample), 3, replace=False)]
        n = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        length = np.linalg.norm(n)
        if length < 1e-12:
            continue
        mask = abs((sample - triangle[0]) @ (n / length)) <= tolerance
        if mask.sum() > best.sum():
            best = mask
    if best.sum() < 3:
        return {'status': 'NEEDS_MORE_DATA'}
    center = sample[best].mean(0)
    _, _, vt = np.linalg.svd(sample[best] - center, full_matrices=False)
    normal = vt[-1]
    if normal[2] < 0:
        normal = -normal
    return dict(status='ESTIMATED', normal=normal.tolist(), center=center.tolist(), inlier_fraction=float(best.mean()), rmse=float(np.sqrt(np.mean(((sample[best] - center) @ normal) ** 2))), source='scan RANSAC/SVD; plane does not establish metric scale or semantic table identity')

def selection(mesh, bounds, exclusions=()):
    bounds = np.asarray(bounds, float)
    if bounds.shape != (2, 3) or not np.isfinite(bounds).all() or np.any(bounds[0] >= bounds[1]):
        raise ValueError('ROI bounds_scan must be finite [min,max]')
    centers = mesh.triangles_center
    keep = ((centers >= bounds[0]) & (centers <= bounds[1])).all(1)
    for excluded in exclusions:
        b = np.asarray(excluded, float)
        if b.shape != (2, 3) or not np.isfinite(b).all() or np.any(b[0] >= b[1]):
            raise ValueError('Invalid exclusion ROI')
        keep &= ~((centers >= b[0]) & (centers <= b[1])).all(1)
    return mesh.submesh([np.flatnonzero(keep)], append=True, repair=False) if keep.any() else None

def mesh_asset(mesh, folder, name, importing):
    """OBJ/UV/base colour are shared by Blender, MJCF and USD exporters."""
    uv = getattr(mesh.visual, 'uv', None)
    path = folder / (name + '.obj')
    with path.open('w') as stream:
        for vertex in mesh.vertices:
            stream.write('v ' + ' '.join(map(str, vertex)) + '\n')
        if uv is not None:
            for coord in uv:
                stream.write('vt ' + ' '.join(map(str, coord)) + '\n')
        for face in mesh.faces:
            stream.write('f ' + ' '.join((f'{int(i) + 1}/{int(i) + 1}' if uv is not None else str(int(i) + 1) for i in face)) + '\n')
    visual = {'type': 'mesh', 'asset': importing(path), 'scale': [1, 1, 1]}
    material = getattr(mesh.visual, 'material', None)
    image = getattr(material, 'baseColorTexture', None) or getattr(material, 'image', None)
    if image is not None:
        texture = folder / (name + '.png')
        image.save(texture)
        visual['texture'] = importing(texture)
    factor = getattr(material, 'baseColorFactor', None)
    color = (np.asarray(factor[:3], float) / 255 if factor is not None else np.array([1.0] * 3 if image is not None else [0.6] * 3)).tolist()
    return (visual, color)

def segment(project, scan_id, config_path):
    """Plane removal + voxel spatial clustering, including connected scan surfaces.

    Outputs anonymous proposals. External agent/inventory chooses identities or ROI.
    """
    from scipy.spatial import cKDTree
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    with exclusive(project):
        scan = next((r for r in project.evidence.get('scans', []) if r['id'] == scan_id))
        source = project.root / scan['path']
        if sha(source) != scan['sha256']:
            raise ValueError('Scan evidence changed')
        config = read(config_path)
        config_ref = copy_input(project, config_path, 'metadata')
        _, instances = load(source, textures=True)
        chosen = [selection(mesh, config['roi_scan'], config.get('exclude_roi_scan', [])) for _, mesh, _ in instances]
        points = np.vstack([m.vertices for m in chosen if m is not None]) if any((m is not None for m in chosen)) else np.empty((0, 3))
        fitted = plane(points, float(config.get('plane_tolerance_scan', 0.005)))
        if fitted['status'] == 'NEEDS_MORE_DATA':
            return {'status': 'NEEDS_MORE_DATA', 'needs': ['ROI must contain a support-plane point distribution']}
        up = np.asarray(config.get('up_scan', [0, 1, 0]), float)
        if up.shape != (3,) or not np.isfinite(up).all() or np.linalg.norm(up) < 1e-12:
            raise ValueError('Explicit scan up vector required')
        normal = np.asarray(fitted['normal'])
        if normal @ up < 0:
            normal = -normal
        fitted['normal'] = normal.tolist()
        if abs(normal @ up / np.linalg.norm(up)) < 0.8:
            return {'status': 'NEEDS_MORE_DATA', 'plane': fitted, 'needs': ['Dominant ROI plane is not aligned with supplied support up; tighten table ROI']}
        distance = (points - np.asarray(fitted['center'])) @ normal
        above = config.get('height_range_scan', [0.008, 0.3])
        object_points = points[(distance > above[0]) & (distance < above[1])]
        voxel = float(config.get('voxel_scan', 0.004))
        gap = float(config.get('cluster_gap_scan', 0.015))
        if not np.isfinite([voxel, gap]).all() or not 0 < voxel <= gap:
            raise ValueError('Positive voxel <= cluster gap required')
        _, indices = np.unique(np.floor(object_points / voxel).astype(np.int64), axis=0, return_index=True)
        cloud = object_points[indices]
        if len(cloud) > 50000:
            return {'status': 'NEEDS_MORE_DATA', 'needs': ['Use tighter ROI or coarser voxel; at most 50,000 cluster points']}
        pairs = cKDTree(cloud).query_pairs(gap, output_type='ndarray') if len(cloud) else np.empty((0, 2), int)
        count, labels = connected_components(coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(cloud), len(cloud))), directed=False)
        proposals = []
        for label in range(count):
            q = cloud[labels == label]
            if len(q) < int(config.get('min_cluster_points', 12)):
                continue
            lo, hi = (q.min(0) - voxel, q.max(0) + voxel)
            proposals.append({'index': len(proposals), 'roi_scan': [lo.tolist(), hi.tolist()], 'points': len(q), 'center_scan': q.mean(0).tolist(), 'extent_scan': (hi - lo).tolist(), 'identity': 'unknown', 'confidence': 'tentative spatial cluster; touching objects can remain merged, incomplete faces can split'})
        report = {'status': 'PROPOSALS_ONLY' if proposals else 'NEEDS_MORE_DATA', 'source': scan, 'configuration': config_ref, 'plane': fitted, 'segments': proposals, 'method': 'dominant-plane removal + voxel Euclidean connectivity; explicit inventory/ROI selects semantic objects', 'metric_scale_status': 'UNKNOWN', 'texture_role': 'preserved for external visual interpretation; no internal semantic classifier', 'needs': ['Review cluster ROIs against reference photos/inventory; specify per-object ROI for merged or split geometry']}
        write(project.root / 'working/scans' / scan_id / 'segmentation.json', report)
        return report

def preview(project, scan_id, engine='blender', renderer='software-egl', candidate_name=None):
    """Unregistered inspection only: arbitrary views, never Side/Wrist calibration."""
    from real2sim_builder.project import empty
    from real2sim_builder.rendering import BlenderRenderer, description, invoke
    from real2sim_builder.rendering import Renderer
    from PIL import Image
    with exclusive(project):
        scan = next((r for r in project.evidence.get('scans', []) if r['id'] == scan_id))
        source = project.root / scan['path']
        if sha(source) != scan['sha256']:
            raise ValueError('Scan evidence changed')
        if candidate_name:
            from real2sim_builder.project import Candidate
            from real2sim_builder.project import world_pose
            from itertools import product
            candidate = Candidate(project, candidate_name)
            candidate.require_open()
            scene = copy.deepcopy(candidate.scene)
            folder = candidate.root / 'scan/preview'
            folder.mkdir(parents=True, exist_ok=True)
            if not scene['objects']:
                return {'status': 'NEEDS_MORE_DATA', 'needs': ['Initialize object geometry before candidate preview']}
            corners = np.asarray(list(product([-0.5, 0.5], repeat=3)))
            points = []
            for obj in scene['objects']:
                if obj['dimensions']['value'] is None or obj['pose']['value'] is None:
                    return {'status': 'NEEDS_MORE_DATA', 'needs': ['Object dimensions/pose must exist for initial candidate preview: ' + obj['id']]}
                t = world_pose(scene, obj)
                points.append(corners * np.asarray(obj['dimensions']['value']) @ t[:3, :3].T + t[:3, 3])
            points = np.vstack(points)
            scene['cameras'] = []
        else:
            header, instances = load(source, textures=True)
            folder = project.root / 'working/scans' / scan_id / 'preview'
            folder.mkdir(parents=True, exist_ok=True)
            scene = empty('UNREGISTERED SCAN INSPECTION')
            importing = asset_importer(project, scene)
            conversion = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0.0]])
            for index, (node, mesh, _) in enumerate(instances):
                mesh.vertices = np.asarray(mesh.vertices) @ conversion.T
                visual, color = mesh_asset(mesh, folder, 'scan_' + str(index), importing)
                scene['objects'].append(dict(id='scan_' + str(index), role='background', frame='world', pose=value(np.eye(4).tolist(), 'estimated', [scan['path']]), dimensions=value(np.maximum(np.ptp(mesh.vertices, axis=0), 1e-06).tolist(), 'estimated', [scan['path']]), visual=visual, collision={'type': 'unknown'}, collision_enabled=False, color=value(color, 'estimated'), physics={'mass_kg': value(None), 'friction': value(None)}))
            points = np.vstack([m.vertices for _, m, _ in instances])
        center = (points.min(0) + points.max(0)) / 2
        radius = float(np.linalg.norm(np.ptp(points, axis=0)))
        for name, direction in [('inspection', [0.6, -1, 0.7]), ('top', [0, -0.001, 1.0])]:
            eye = center + radius * np.asarray(direction)
            forward = center - eye
            forward /= np.linalg.norm(forward)
            right = np.cross(forward, [0, 0, 1])
            right /= np.linalg.norm(right)
            down = np.cross(forward, right)
            t = np.eye(4)
            t[:3, :3] = np.column_stack([right, down, forward])
            t[:3, 3] = eye
            scene['cameras'].append(dict(id=name, frame='world', purpose='inspection', pose=value(t.tolist(), 'estimated', ['arbitrary inspection view']), K=value([[420, 0, 320], [0, 420, 240], [0, 0, 1]], 'estimated'), resolution=[640, 480], distortion=value([0.0] * 5, 'estimated'), calibration_quality={'state': 'UNKNOWN', 'scope': 'inspection only'}))
        write(folder / 'scene.yaml', scene)
        output = folder / engine
        if engine == 'blender':
            invoke({'action': 'build', 'scene': description(scene, project.root), 'output': str(output / 'build'), 'blend': str(folder / 'inspection.blend')}, output / 'build')
            model = BlenderRenderer(scene, project.root, output)
            model.blend = folder / 'inspection.blend'
        else:
            model = Renderer(scene, project.root, output, renderer)
        with model:
            for camera in scene['cameras']:
                rgb = model.rgb(camera['id'])
                Image.fromarray(rgb).save(output / (camera['id'] + '.png'))
                if candidate_name:
                    for obj in scene['objects']:
                        if obj.get('parent_object'):
                            continue
                        mask = model.mask(camera['id'], obj['id'])
                        y, x = np.nonzero(mask)
                        if not len(x):
                            continue
                        target = output / 'objects' / obj['id']
                        target.mkdir(parents=True, exist_ok=True)
                        Image.fromarray(rgb[y.min():y.max() + 1, x.min():x.max() + 1]).save(target / (camera['id'] + '.png'))
        report = {'status': 'INSPECTION_ONLY', 'source_sha256': scan['sha256'], 'engine': engine, 'paths': [str(output / (c['id'] + '.png')) for c in scene['cameras']], 'scope': 'Candidate geometry inspection; not real-camera validation' if candidate_name else 'UNREGISTERED visual scan; scanned robot may be visible in diagnostic only, never imported as controllable articulation', 'metric_scale_verified': False, 'camera_calibration': 'UNKNOWN', 'texture_policy': '2K derived base colour; original 8K maps unchanged'}
        write(output / 'report.json', report)
        return report

def apply_geometry_constraints(scene, config):
    """Project independent measured pairs, retaining their centroid and prior direction.

    No scan objective or global scaling. Overlapping pairs require a coupled solver
    and are explicitly refused rather than moving a previously constrained object.
    """
    from real2sim_builder.project import GEOMETRY_CONSTRAINT_SCHEMA, geometry_constraint_metrics, world_pose, frame_world
    if config.get('schema') != GEOMETRY_CONSTRAINT_SCHEMA or config.get('units') not in ('m', 'mm'):
        raise ValueError('Unsupported relative geometry schema/units')
    result = copy.deepcopy(scene)
    normalized = copy.deepcopy(config)
    normalized['units'] = 'm'
    if config['units'] == 'mm':
        for row in normalized.get('distances', []):
            for key in ('distance_m', 'rim_gap_m', 'uncertainty_m'):
                if key in row:
                    row[key] *= 0.001
    rows = normalized.get('distances', [])
    if not rows:
        raise ValueError('Measured distances required')
    occupied = set()
    changes = []
    for row in rows:
        before = geometry_constraint_metrics(result, row)
        if occupied.intersection(row['objects']):
            raise ValueError('Overlapping measured pairs need a coupled constraint solve')
        occupied.update(row['objects'])
        pair = [next((o for o in result['objects'] if o['id'] == n)) for n in row['objects']]
        poses = [world_pose(result, o) for o in pair]
        positions = np.array([t[:3, 3] for t in poses])
        delta = positions[1] - positions[0]
        length = before['target_m']
        offset = np.zeros(3)
        if row.get('same_support_plane'):
            up = poses[0][:3, 2]
            height_delta = (pair[1]['dimensions']['value'][2] - pair[0]['dimensions']['value'][2]) / 2
            delta -= up * (delta @ up)
            offset = up * height_delta
            if length <= abs(height_delta):
                raise ValueError('Centre distance cannot satisfy support plane')
            length = float(np.sqrt(length ** 2 - height_delta ** 2))
        norm = np.linalg.norm(delta)
        if norm < 1e-12:
            raise ValueError('No initial relative direction; need measured bearing')
        desired = delta / norm * length + offset
        locked = [o['pose']['provenance'] in ('measured', 'calibrated') for o in pair]
        if all(locked):
            if not np.allclose(positions[1] - positions[0], desired, atol=max(1e-08, row.get('uncertainty_m', 0))):
                raise ValueError('CONFLICT: locked measured object poses disagree with relative constraint')
            corrected = positions.copy()
        elif locked[0]:
            corrected = np.array([positions[0], positions[0] + desired])
        elif locked[1]:
            corrected = np.array([positions[1] - desired, positions[1]])
        else:
            center = positions.mean(0)
            corrected = np.array([center - desired / 2, center + desired / 2])
        for i, obj in enumerate(pair):
            if locked[i]:
                continue
            pose = poses[i].copy()
            pose[:3, 3] = corrected[i]
            local = np.linalg.inv(frame_world(result, obj['frame'])) @ pose
            obj['pose'] = value(local.tolist(), 'estimated', list(dict.fromkeys(obj['pose'].get('evidence', []) + row['evidence'])))
            for child in result['objects']:
                if child.get('parent_object') == obj['id']:
                    child_world = world_pose(result, child).copy()
                    child_world[:3, 3] += corrected[i] - positions[i]
                    child['pose'] = value((np.linalg.inv(frame_world(result, child['frame'])) @ child_world).tolist(), 'estimated', obj['pose']['evidence'])
        after = geometry_constraint_metrics(result, row)
        changes.append({'before': before, 'after': after, 'scan_conflict': abs(before['distance_residual_m']) > max(1e-08, row.get('uncertainty_m', 0)), 'pose_delta_m': {o['id']: (corrected[i] - positions[i]).tolist() for i, o in enumerate(pair)}, 'gauge': 'preserved pair centroid and prior direction' if not any(locked) else 'existing measured pose anchor'})
    result['geometry_constraints'] = {k: normalized[k] for k in ('schema', 'units', 'distances')}
    for name in config.get('measured_visuals', []):
        obj = next((o for o in result['objects'] if o['id'] == name))
        if obj['dimensions']['provenance'] not in ('measured', 'calibrated') or obj['collision']['type'] not in ('box', 'container', 'cylinder', 'sphere'):
            raise ValueError('Measured visual needs measured dimensions and primitive geometry')
        obj.setdefault('scan_visual_prior', copy.deepcopy(obj['visual']))
        obj['visual'] = copy.deepcopy(obj['collision'])
        obj['visual_geometry_status'] = 'measured outer dimensions; unmeasured wall/taper remain hypotheses; scan retained as reference'
        result['objects'] = [o for o in result['objects'] if o.get('parent_object') != name]
    if result.get('scan_initialization'):
        result['scan_initialization']['prior_policy'] = {'confidence': 'LOW', 'purpose': 'initial inventory, relative bearing and surface reference', 'objective': 'measured constraints; never similarity to GLB', 'absolute_registration': 'unchanged; requires evidence'}
    validate(result)
    return (result, {'status': 'MEASURED_RELATIVE_GEOMETRY_APPLIED', 'constraints': changes, 'world_registration': 'not established by relative measurements', 'physics_status': 'PHYSICS_NOT_VALIDATED'})

def constrain(candidate, config_path):
    """Apply explicit metric evidence without the camera/image-edit path."""
    with exclusive(candidate.project):
        candidate.require_open()
        config = read(config_path)
        try:
            scene, report = apply_geometry_constraints(candidate.scene, config)
            validate(scene, candidate.project.root)
            from real2sim_builder.project import preserve
            preserve(candidate.scene, scene)
            candidate.check_scope(scene)
        except ValueError as error:
            report = {'status': 'CONFLICT', 'reason': str(error), 'candidate_changed': False}
            write(candidate.root / 'scan/geometry_constraints_report.json', report)
            return report
        reference = copy_input(candidate.project, config_path, 'metadata')
        report['config'] = reference
        candidate.save(scene)
        report['input_signature'] = candidate.project.signature(scene)
        write(candidate.root / 'scan/geometry_constraints_report.json', report)
        return report

def initialize(candidate, scan_id, config_path):
    """Explicit inventory + spatial/colour/connectivity diagnostics; no hidden semantics."""
    with exclusive(candidate.project):
        candidate.require_open()
        project = candidate.project
        scan = next((r for r in project.evidence.get('scans', []) if r['id'] == scan_id))
        source = project.root / scan['path']
        if sha(source) != scan['sha256']:
            raise ValueError('Scan evidence changed')
        config = read(config_path)
        if config.get('schema') != 'real2sim.scan-initialization/1':
            raise ValueError('Unsupported scan configuration')
        config_ref = copy_input(project, config_path, 'metadata')
        report = registration(config.get('registration', {}))
        folder = candidate.root / 'scan'
        folder.mkdir(exist_ok=True)
        write(folder / 'configuration.yaml', config)
        write(folder / 'registration.json', report)
        local_only = bool(config.get('allow_unregistered_initialization', False))
        if report['status'] == 'NEEDS_MORE_DATA' and (not local_only):
            return report
        if report['status'] == 'NEEDS_MORE_DATA':
            scale_evidence = scale_from_lengths(config.get('scale_anchors', []))
            report = {**report, 'scale': scale_evidence['scale'], 'scale_initialization': scale_evidence, 'T_world_scan': [[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], 'metric_scale_verified': False, 'scope': 'nominal glTF metre/local inspection frame; not robot-world registration'}
        scale = report['scale']
        world = transform(report['T_world_scan'])
        _, instances = load(source, textures=True)
        scene = copy.deepcopy(candidate.scene)
        importing = asset_importer(project, scene)
        outcomes = []
        inventory = config.get('objects', [])
        if not inventory:
            return {'status': 'NEEDS_MORE_DATA', 'needs': ['Explicit object inventory and per-object ROI; components are not semantic objects']}
        occupied = set()
        assigned_rois = []
        for row in inventory:
            identifier(row['id'])
            role = row['role']
            if role == 'reference_robot':
                raise ValueError('Scanned robot geometry must be excluded; import original URDF instead')
            if row['id'] in occupied:
                raise ValueError('Duplicate inventory ID')
            occupied.add(row['id'])
            shape = row.get('shape', 'box')
            bounds = np.asarray(row['roi_scan'], float)
            for previous in assigned_rois:
                if np.all(np.minimum(bounds[1], previous[1]) - np.maximum(bounds[0], previous[0]) > 0):
                    raise ValueError('Object ROI volumes overlap; explicit disjoint segmentation prevents duplicate scan geometry')
            assigned_rois.append(bounds)
            if shape not in ('box', 'container', 'cylinder', 'sphere', 'mesh'):
                raise ValueError('Unsupported initial geometry')
            pieces = []
            for node, mesh, _ in instances:
                selected = selection(mesh, row['roi_scan'], config.get('exclude_roi_scan', []))
                if selected is not None:
                    pieces.append((node, selected))
            if not pieces:
                outcomes.append({'object': row['id'], 'status': 'NEEDS_MORE_DATA', 'need': 'ROI has no faces'})
                continue
            points = np.vstack([m.vertices for _, m in pieces]) * scale
            points = points @ world[:3, :3].T + world[:3, 3]
            lo, hi = (points.min(0), points.max(0))
            extent = hi - lo
            obj = next((o for o in scene['objects'] if o['id'] == row['id']), None)
            if obj is None:
                obj = dict(id=row['id'], role=role, frame='world', pose=value(None), dimensions=value(None), visual={'type': 'unknown'}, collision={'type': 'unknown'}, color=value([0.6] * 3, 'estimated'), physics={'mass_kg': value(None), 'friction': value(None)})
                scene['objects'].append(obj)
            if obj['role'] != role:
                raise ValueError('Inventory role conflicts with existing object')
            measured = obj['dimensions']['provenance'] in ('measured', 'calibrated')
            if obj['dimensions']['value'] is None:
                if not row.get('full_bounds', False):
                    outcomes.append({'object': row['id'], 'status': 'NEEDS_MORE_DATA', 'observed_extent_m': extent.tolist(), 'need': 'Measured dimensions or explicit opposing-face coverage; partial scan cannot determine hidden extents'})
                    continue
                obj['dimensions'] = value(np.maximum(extent, 1e-06).tolist(), 'estimated', [scan['path'], 'declared scan coverage'])
            dims = np.asarray(obj['dimensions']['value'])
            pose = np.eye(4)
            pose[:3, 3] = (hi + lo) / 2
            if obj['pose']['value'] is None or obj['pose']['provenance'] not in ('measured', 'calibrated'):
                obj['pose'] = value(pose.tolist(), 'estimated', [scan['path'], config_ref])
                obj['frame'] = 'world'
            geometry = {'type': shape}
            if shape == 'container':
                wall = row.get('wall_m')
                old = obj['collision'].get('wall')
                wall_node = old if isinstance(old, dict) else value(wall, 'estimated', [config_ref]) if wall is not None else value(None)
                if wall_node['value'] is None:
                    outcomes.append({'object': row['id'], 'status': 'NEEDS_MORE_DATA', 'need': 'Container wall thickness for open collision'})
                    continue
                geometry.update(wall=wall_node, round=row.get('round', True))
            obj['visual'] = copy.deepcopy(geometry)
            obj['collision'] = copy.deepcopy(geometry)
            if shape == 'mesh' or row.get('scan_visual', False):
                if shape == 'mesh':
                    obj['collision'] = {'type': 'box'}
                from real2sim_builder.project import world_pose
                local_inverse = np.linalg.inv(world_pose(scene, obj))
                for index, (node, mesh) in enumerate(pieces):
                    v = np.asarray(mesh.vertices) * scale @ world[:3, :3].T + world[:3, 3]
                    mesh.vertices = (np.c_[v, np.ones(len(v))] @ local_inverse.T)[:, :3]
                    visual, color = mesh_asset(mesh, folder, row['id'] + f'_{index}', importing)
                    child = dict(id=row['id'] + f'_scan_visual_{index}', role='background', frame=obj['frame'], pose=copy.deepcopy(obj['pose']), dimensions=value(np.maximum(np.ptp(mesh.vertices, axis=0), 1e-06).tolist(), 'estimated', [scan['path']]), visual=visual, collision={'type': 'unknown'}, collision_enabled=False, color=value(color, 'estimated', [scan['path']]), physics={'mass_kg': value(None), 'friction': value(None)}, parent_object=row['id'])
                    if any((o['id'] == child['id'] for o in scene['objects'])):
                        raise ValueError('Scan visual ID already exists; use a fresh candidate')
                    scene['objects'].append(child)
                first = next((o for o in scene['objects'] if o.get('parent_object') == row['id']))
                obj['visual'] = first['visual']
                obj['color'] = first['color']
                scene['objects'].remove(first)
            outcomes.append(dict(object=row['id'], status='ESTIMATED', segmentation='explicit ROI face-center assignment', confidence='manual_roi_not_verified', observed_extent_m=extent.tolist(), dimensions_m=dims.tolist(), dimension_source=obj['dimensions']['provenance'], dimension_conflict=(abs(extent - dims) > 0.005).tolist() if measured else None, components='see scan inspection; ROI can cut connected surfaces', plane=plane(points), scan_nodes=[n for n, _ in pieces]))
        scene['scan_initialization'] = {'schema': 'real2sim.scan-initialization/1', 'source': scan, 'source_asset': importing(source), 'config': config_ref, 'registration': report, 'object_reports': outcomes, 'physics_status': 'PHYSICS_NOT_VALIDATED'}
        relative = config.get('geometry_constraints', scene.get('geometry_constraints'))
        if relative is None and project.evidence.get('distances'):
            relative = {'schema': 'real2sim.geometry-constraints/1', 'units': 'm', 'distances': project.evidence['distances']}
        constraint_report = None
        if relative:
            try:
                scene, constraint_report = apply_geometry_constraints(scene, relative)
            except ValueError as error:
                failure = {'status': 'CONFLICT', 'reason': str(error), 'candidate_changed': False}
                write(folder / 'geometry_constraints_report.json', failure)
                return failure
        from real2sim_builder.project import world_pose
        distances = []
        for constraint in project.evidence.get('distances', []):
            objects = [next((o for o in scene['objects'] if o['id'] == name), None) for name in constraint['objects']]
            if any((o is None or o['pose']['value'] is None for o in objects)):
                continue
            actual = float(np.linalg.norm(world_pose(scene, objects[0])[:3, 3] - world_pose(scene, objects[1])[:3, 3]))
            distances.append({'measurement': constraint, 'candidate_distance_m': actual, 'error_m': actual - constraint['distance_m'], 'conflict': abs(actual - constraint['distance_m']) > max(0.005, constraint.get('uncertainty_m', 0.0)), 'scope': 'nominal scan units, not verified metric scale' if not report.get('metric_scale_verified') else 'registered scan object-centre hypothesis'})
        scene['scan_initialization']['distance_comparison'] = distances
        validate(scene, project.root)
        candidate.save(scene)
        result = {'status': 'NEEDS_MORE_DATA' if report['status'] == 'NEEDS_MORE_DATA' or any((r['status'] == 'NEEDS_MORE_DATA' for r in outcomes)) else 'INITIALIZED_ESTIMATED', 'objects': outcomes, 'registration': report, 'input_signature': project.signature(scene), 'distance_comparison': distances, 'geometry_constraints': constraint_report, 'camera_calibration': 'not required for initial geometry; camera pixel fitting requires calibration evidence'}
        write(folder / 'initialization.json', result)
        return result

# Port of original reconstruction/analysis.py
"""Deterministic visual inventory and minimal, specific missing-evidence requests."""
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps
from real2sim_builder.project import empty, value
from real2sim_builder.project import write

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

# Port of original reconstruction/diagnostics.py
"""Read-only hypotheses and predicted view coverage, never robot motion commands."""
import numpy as np
from real2sim_builder.project import read

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

# Port of original reconstruction/pipeline.py
"""Deterministic fitting loop; external Codex selects hypotheses through Candidates."""
import copy
from pathlib import Path
import time
import cv2
import numpy as np
from PIL import Image, ImageOps
from real2sim_builder.project import write
from real2sim_builder.project import validate, local_path
from real2sim_builder.project import extract_videos

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
    from real2sim_builder.project import camera_calibration_signature
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
    from real2sim_builder.project import exclusive
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
