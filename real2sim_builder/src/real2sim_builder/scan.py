"""Existing scan algorithms; scan/Scene formats and calculations unchanged."""
from pathlib import Path
from real2sim_builder.evidence import asset_importer, copy_input
import base64
import copy
from real2sim_builder.candidate import exclusive
import io
import json
import numpy as np
from real2sim_builder.files import read, sha, write
import struct
from real2sim_builder.scene import value


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
    from real2sim_builder.scene import empty
    from real2sim_builder.rendering import BlenderRenderer, description, invoke
    from real2sim_builder.rendering import Renderer
    from PIL import Image
    with exclusive(project):
        scan = next((r for r in project.evidence.get('scans', []) if r['id'] == scan_id))
        source = project.root / scan['path']
        if sha(source) != scan['sha256']:
            raise ValueError('Scan evidence changed')
        if candidate_name:
            from real2sim_builder.candidate import Candidate
            from real2sim_builder.scene import world_pose
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

