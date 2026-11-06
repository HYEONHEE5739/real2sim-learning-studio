"""Measured geometry initialization and independent metric constraints."""
from real2sim_builder.evidence import copy_input
import copy
from real2sim_builder.candidate import exclusive
from real2sim_builder.scene import identifier, validate, value
import numpy as np
from real2sim_builder.files import read, sha, write


def measured_geometry(scene, measurements):
    """Record measurements; new visuals await a Codex/Blender object asset.

    This cannot change a robot, a protected measurement, or a camera. No hidden
    surface or physics material is inferred from RGB/depth.
    """
    result=copy.deepcopy(scene);objects={o['id']:o for o in result['objects']}
    for spec in measurements:
        name=identifier(spec['id']);kind=spec['kind'];evidence=spec.get('evidence',[])
        raw=spec['dimensions_m'];known=[d for d in raw if d is not None];complete=all(d is not None for d in raw)
        dims=np.asarray(raw,float);provenance=spec.get('provenance','measured')
        if not evidence or dims.shape!=(3,)or any(type(d)not in(int,float)or not np.isfinite(d)or d<=0 for d in known)or provenance not in('measured','calibrated','estimated'):
            raise ValueError('Positive measured dimensions and their evidence are required')
        if kind not in('box','cylinder','sphere','container','mesh'):raise ValueError('Unknown measured object kind')
        existing=objects.get(name)
        if existing and (existing.get('link')or existing['role']=='reference_robot'):raise ValueError('Robot geometry is locked')
        if existing and existing['dimensions']['provenance']in('measured','calibrated')and any(d is not None and d!=existing['dimensions']['value'][i]for i,d in enumerate(raw)):
            raise ValueError('Existing measured dimensions are locked: '+name)
        if existing and existing['dimensions']['provenance']in('measured','calibrated'):
            continue
        geometry={'type':kind}
        if kind=='container':
            geometry.update(wall=value(spec.get('wall_m'),provenance if spec.get('wall_m')is not None else'unknown',evidence),round=bool(spec.get('round',False)))
            if 'bottom_diameter_m'in spec:geometry['bottom_diameter_m']=spec['bottom_diameter_m']
        if existing:
            # Measurements do not replace an existing CAD/compound visual or
            # collision record. Their dimensions are the authority.
            if complete:existing['dimensions']=value(dims.tolist(),provenance,evidence)
            continue
        role=spec.get('role','manipulable_object')
        obj={'id':name,'role':role,'frame':'world','pose':value(None),
             'dimensions':value(dims.tolist(),provenance,evidence)if complete else value(None),'visual':{'type':'unknown'},'collision':copy.deepcopy(geometry)if complete and kind!='mesh'else{'type':'unknown'},
             'color':value(spec.get('color',[.5,.5,.5]),'estimated',['display default; not a color measurement']),
             'physics':{'mass_kg':value(None),'friction':value(None)}}
        for field in('mass_kg','friction'):
            if field in spec:obj['physics'][field]=value(spec[field],spec.get('physics_source','estimated'),evidence)
        result['objects'].append(obj);objects[name]=obj
    validate(result)
    return result


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
        changes.append({'before': before, 'after': after, 'prior_conflict': abs(before['distance_residual_m']) > max(1e-08, row.get('uncertainty_m', 0)), 'pose_delta_m': {o['id']: (corrected[i] - positions[i]).tolist() for i, o in enumerate(pair)}, 'gauge': 'preserved pair centroid and prior direction' if not any(locked) else 'existing measured pose anchor'})
    result['geometry_constraints'] = {k: normalized[k] for k in ('schema', 'units', 'distances')}
    for name in config.get('measured_visuals', []):
        obj = next((o for o in result['objects'] if o['id'] == name))
        if obj['dimensions']['provenance'] not in ('measured', 'calibrated') or obj['collision']['type'] not in ('box', 'container', 'cylinder', 'sphere'):
            raise ValueError('Measured visual needs measured dimensions and primitive geometry')
        obj.setdefault('visual_geometry_prior', copy.deepcopy(obj['visual']))
        obj['visual'] = copy.deepcopy(obj['collision'])
        obj['visual_geometry_status'] = 'measured outer dimensions; unmeasured wall/taper remain hypotheses; previous visual retained as reference'
        result['objects'] = [o for o in result['objects'] if o.get('parent_object') != name]
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
            write(candidate.root / 'geometry_constraints_report.json', report)
            return report
        reference = copy_input(candidate.project, config_path, 'metadata')
        report['config'] = reference
        candidate.save(scene)
        report['input_signature'] = candidate.project.signature(scene)
        write(candidate.root / 'geometry_constraints_report.json', report)
        return report
