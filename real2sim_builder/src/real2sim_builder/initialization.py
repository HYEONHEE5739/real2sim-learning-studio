"""Existing initialization algorithms; scan/Scene formats and calculations unchanged."""
from real2sim_builder.evidence import asset_importer, copy_input
import copy
from real2sim_builder.candidate import exclusive
from real2sim_builder.scene import identifier, transform, validate, value
from .scan import load, mesh_asset, plane, registration, scale_from_lengths, selection
import numpy as np
from real2sim_builder.files import read, sha, write


def apply_geometry_constraints(scene, config):
    """Project independent measured pairs, retaining their centroid and prior direction.

    No scan objective or global scaling. Overlapping pairs require a coupled solver
    and are explicitly refused rather than moving a previously constrained object.
    """
    from real2sim_builder.scene import GEOMETRY_CONSTRAINT_SCHEMA
    from real2sim_builder.scene import geometry_constraint_metrics, world_pose, frame_world
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
            from real2sim_builder.editing import preserve
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
                from real2sim_builder.scene import world_pose
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
        from real2sim_builder.scene import world_pose
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

