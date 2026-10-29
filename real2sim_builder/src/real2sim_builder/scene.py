"""Canonical metric authoring Scene, evidence values and geometry validation."""
import copy,re
from pathlib import Path
import numpy as np
from .files import sha
GEOMETRY_CONSTRAINT_SCHEMA = 'real2sim.geometry-constraints/1'
WORKFLOW_SCHEMA = 'so101.scene-workflow/1'

SCHEMA = 'real2sim.scene/1'
SOURCES = {'measured', 'calibrated', 'derived', 'optimized', 'estimated', 'unknown'}
ROLES = {'workspace', 'support_surface', 'manipulable_object', 'receptacle', 'fixture', 'background', 'reference_robot'}

def value(data, source='unknown', evidence=None):
    if source not in SOURCES or (data is None and source != 'unknown'):
        raise ValueError('Invalid evidence provenance')
    return {'value': data, 'provenance': source, 'evidence': evidence or []}


def transform(data):
    t = np.asarray(data, dtype=float)
    if t.shape != (4, 4) or not np.isfinite(t).all() or (not np.allclose(t[3], [0, 0, 0, 1])):
        raise ValueError('Expected finite 4x4 homogeneous transform')
    if not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-05) or not np.isclose(np.linalg.det(t[:3, :3]), 1):
        raise ValueError('Rotation must be right handed and orthonormal')
    return t


def empty(name):
    return {'schema': SCHEMA, 'name': name, 'units': 'm', 'coordinates': {'handedness': 'right', 'up': '+Z', 'camera': 'x_right_y_down_z_forward', 'matrix': 'T_parent_child; column vectors'}, 'frames': {'world': {'parent': None, 'transform': value(np.eye(4).tolist(), 'derived')}}, 'objects': [], 'cameras': [], 'assets': {}, 'lights': {'ambient': value([0.3, 0.3, 0.3], 'estimated')}, 'uncertainties': []}


def checked_value(node):
    if not isinstance(node, dict) or node.get('provenance') not in SOURCES or 'value' not in node:
        raise ValueError('Every reconstructed field needs explicit provenance')
    if node['value'] is None and node['provenance'] != 'unknown':
        raise ValueError('Null field must be unknown')
    return node['value']


def cameras_audited(scene):
    cameras = [c for c in scene['cameras'] if c.get('purpose', 'observation') != 'inspection']
    return bool(cameras) and all((c.get('calibration_quality', {}).get('state') == 'CALIBRATED' and c['calibration_quality'].get('input_sha256') == camera_calibration_signature(scene, c) for c in cameras))


def camera_calibration_signature(scene, camera):
    import hashlib, json
    data = {k: camera.get(k) for k in ('id', 'frame', 'purpose', 'resolution', 'K', 'pose', 'distortion')}
    data['world_registration'] = scene.get('scan_initialization', {}).get('registration')
    data['world'] = scene['frames']['world']
    if camera['frame'].startswith('robot_link_'):
        data['robot_model'] = scene.get('robot_model')
        data['robot_base'] = scene['frames'].get('robot_base')
    elif camera['frame'] != 'world':
        data['camera_parent_world'] = frame_world(scene, camera['frame']).tolist()
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def identifier(name):
    if not isinstance(name, str) or not re.fullmatch('[A-Za-z_][A-Za-z0-9_]*', name):
        raise ValueError('IDs must be ASCII identifiers')
    return name


def local_path(root, relative):
    if Path(relative).is_absolute():
        raise ValueError('Assets must be package-relative')
    p = (Path(root) / relative).resolve()
    if not p.is_relative_to(Path(root).resolve()):
        raise ValueError('Asset path escapes package')
    return p


def validate(scene, root=None, complete=False):
    if scene.get('schema') != SCHEMA or scene.get('units') != 'm':
        raise ValueError('Unsupported scene schema/units')
    convention = empty('')['coordinates']
    if scene.get('coordinates') != convention:
        raise ValueError('Unsupported coordinate convention; explicitly convert to metre/+Z/optical frames')
    if scene.get('robot_model', {}).get('simulation_joint_offsets_rad') is not None:
        raise ValueError('historical runtime joint offsets are unsupported; archive the calibration and use explicit validated geometry')
    frames = scene.get('frames', {})
    if 'world' not in frames or frames['world']['parent'] is not None:
        raise ValueError('Missing world root')
    for name, frame in frames.items():
        identifier(name)
        transform(checked_value(frame['transform']))
        chain = set()
        current = name
        while current is not None:
            if current in chain or current not in frames:
                raise ValueError('Cyclic or missing frame parent')
            chain.add(current)
            current = frames[current]['parent']
    ids = set()
    for obj in scene['objects']:
        identifier(obj['id'])
        if obj['id'] in ids or obj['role'] not in ROLES or obj['frame'] not in frames:
            raise ValueError('Invalid object identity/frame/role')
        ids.add(obj['id'])
        pose = checked_value(obj['pose'])
        dims = checked_value(obj['dimensions'])
        if complete and (pose is None or dims is None):
            raise ValueError('Metric geometry is incomplete: ' + obj['id'])
        if pose is not None:
            transform(pose)
        if dims is not None and (np.asarray(dims).shape != (3,) or not np.isfinite(dims).all() or np.any(np.asarray(dims) <= 0)):
            raise ValueError('Positive finite full dimensions required')
        for field in ('visual', 'collision'):
            geometry = obj[field]
            if field == 'collision' and (not obj.get('collision_enabled', True)):
                continue
            if geometry['type'] not in ('box', 'sphere', 'cylinder', 'container', 'mesh', 'compound', 'unknown'):
                raise ValueError('Unsupported geometry')
            if complete and geometry['type'] == 'unknown':
                raise ValueError('Unknown geometry')
            if geometry['type'] == 'compound':
                from real2sim_builder.calibration.geometry import parts
                parts(obj, field)
            if geometry.get('texture') and geometry['texture'] not in scene['assets']:
                raise ValueError('Unknown texture asset')
            if geometry['type'] == 'mesh':
                scale = geometry.get('scale', [1, 1, 1])
                if np.asarray(scale).shape != (3,) or not np.isfinite(scale).all() or min(scale) <= 0:
                    raise ValueError('Invalid mesh scale')
                if geometry['asset'] not in scene['assets']:
                    raise ValueError('Unknown mesh asset')
                if field == 'collision' and root:
                    from real2sim_builder.calibration.geometry import mesh_data
                    vertices, faces = mesh_data(local_path(root, scene['assets'][geometry['asset']]['path']))
                    unique = np.unique(vertices, axis=0)
                    for face in faces:
                        triangle = vertices[face]
                        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
                        length = np.linalg.norm(normal)
                        if length < 1e-12:
                            continue
                        distance = (unique - triangle[0]) @ (normal / length)
                        if distance.min() < -1e-06 and distance.max() > 1e-06:
                            raise ValueError('Concave collision mesh: use primitive/convex compound decomposition')
            if geometry['type'] == 'container':
                wall = checked_value(geometry['wall'])
                if complete and (wall is None or dims is None):
                    raise ValueError('Incomplete open container geometry')
                if wall is not None and (not np.isfinite(wall) or wall <= 0 or (dims is not None and wall >= min(dims) / 2)):
                    raise ValueError('Invalid open container wall thickness')
        for physics in obj['physics'].values():
            number = checked_value(physics)
            if number is not None and (not np.isfinite(number).all() or np.any(np.asarray(number) < 0)):
                raise ValueError('Invalid physics')
        for key, field in obj.get('material', {}).items():
            if key not in ('roughness', 'metallic'):
                raise ValueError('Unsupported material parameter')
            v = checked_value(field)
            if v is None or not np.isfinite(v) or (not 0 <= v <= 1):
                raise ValueError('Material value outside [0,1]')
        color = checked_value(obj['color'])
        if color is not None and (len(color) != 3 or not np.isfinite(color).all() or min(color) < 0 or (max(color) > 1)):
            raise ValueError('RGB color outside [0,1]')
    ambient = checked_value(scene['lights']['ambient'])
    if np.asarray(ambient).shape != (3,) or not np.isfinite(ambient).all() or min(ambient) < 0:
        raise ValueError('Invalid ambient light')
    for light in scene['lights'].get('sources', []):
        identifier(light['id'])
        transform(checked_value(light['pose']))
        if light['type'] not in ('point', 'area', 'sun'):
            raise ValueError('Unsupported light type')
        for key in ('energy', 'size'):
            v = checked_value(light[key])
            if v is None or not np.isfinite(v) or v < 0:
                raise ValueError('Invalid light parameter')
        rgb = checked_value(light['color'])
        if np.asarray(rgb).shape != (3,) or not np.isfinite(rgb).all() or min(rgb) < 0:
            raise ValueError('Invalid light color')
    names = set()
    for camera in scene['cameras']:
        identifier(camera['id'])
        if camera.get('purpose', 'observation') not in ('observation', 'inspection'):
            raise ValueError('Invalid camera purpose')
        if camera['id'] in names or camera['frame'] not in frames:
            raise ValueError('Invalid camera identity/frame')
        names.add(camera['id'])
        quality = camera.get('calibration_quality')
        if quality:
            if quality.get('state') not in ('UNKNOWN', 'ESTIMATED', 'CALIBRATED'):
                raise ValueError('Invalid camera calibration quality state')
            if quality['state'] == 'CALIBRATED' and (not quality.get('independent_session_holdout')):
                raise ValueError('CALIBRATED quality requires independent session validation')
        pose = checked_value(camera['pose'])
        k = checked_value(camera['K'])
        if complete and (pose is None or k is None):
            raise ValueError('Camera calibration is incomplete')
        if pose is not None:
            transform(pose)
        distortion = checked_value(camera['distortion'])
        if distortion is None or np.asarray(distortion).ndim != 1 or len(distortion) not in (4, 5, 8, 12, 14) or (not np.isfinite(distortion).all()):
            raise ValueError('Invalid OpenCV pinhole distortion coefficients')
        if k is not None:
            k = np.asarray(k)
            if k.shape != (3, 3) or not np.isfinite(k).all() or min(k[0, 0], k[1, 1]) <= 0 or (not np.allclose(k[2], [0, 0, 1])) or (abs(k[0, 1]) > 1e-09):
                raise ValueError('Invalid zero-skew camera K')
        w, h = camera['resolution']
        if type(w) is not int or type(h) is not int or min(w, h) < 1:
            raise ValueError('Invalid camera resolution')
    if complete and (not scene['cameras']):
        raise ValueError('At least one reconstructed camera required')
    for asset in scene['assets'].values():
        if root:
            file = local_path(root, asset['path'])
            if not file.is_file():
                raise ValueError('Asset missing')
            if asset.get('sha256') and sha(file) != asset['sha256']:
                raise ValueError('Source asset hash changed')
    if 'geometry_constraints' in scene:
        validate_geometry_constraints(scene)
    if 'workflow' in scene:
        validate_workflow(scene)
    return scene


def frame_world(scene, name):
    frame = scene['frames'][name]
    t = transform(frame['transform']['value'])
    return t if frame['parent'] is None else frame_world(scene, frame['parent']) @ t


def world_pose(scene, node):
    return frame_world(scene, node['frame']) @ transform(node['pose']['value'])


def uncertainties(scene):
    result = list(scene.get('uncertainties', []))
    for obj in scene['objects']:
        for field in ('pose', 'dimensions'):
            if obj[field]['provenance'] in ('unknown', 'estimated'):
                result.append(f"{obj['id']}.{field}: {obj[field]['provenance']}")
        for key, field in obj['physics'].items():
            if field['provenance'] in ('unknown', 'estimated'):
                result.append(f"{obj['id']}.physics.{key}: {field['provenance']}")
    return list(dict.fromkeys(result))


def validate_workflow(scene):
    """Declarative SO-101 pick/place intent. No control, LLM or inferred physics."""
    w = scene['workflow']
    if not isinstance(w, dict) or w.get('schema') != WORKFLOW_SCHEMA:
        raise ValueError('Unsupported workflow schema')
    allowed = {'schema', 'support_surface', 'observation_cameras', 'real_camera_bindings', 'tasks', 'reset', 'physics', 'object_physics', 'roles', 'provenance'}
    if set(w) - allowed:
        raise ValueError('Unknown workflow fields: ' + str(sorted(set(w) - allowed)))
    objects = {o['id']: o for o in scene['objects']}
    cameras = {c['id'] for c in scene['cameras']}
    if objects.get(w.get('support_surface'), {}).get('role') != 'support_surface':
        raise ValueError('workflow support_surface must reference a support_surface object')
    views = w.get('observation_cameras', [])
    if not views or len(set(views)) != len(views) or (not set(views) <= cameras):
        raise ValueError('Unknown/duplicate workflow observation camera')
    bindings = w.get('real_camera_bindings', {})
    if not set(bindings) <= cameras or len(set(bindings.values())) != len(bindings):
        raise ValueError('Invalid workflow real camera bindings')
    for key in bindings.values():
        identifier(key)
    tasks = w.get('tasks', [])
    if not tasks:
        raise ValueError('workflow requires explicit pick/place tasks')
    seen = set()
    for t in tasks:
        identifier(t.get('id'))
        if t['id'] in seen:
            raise ValueError('Duplicate workflow task ID')
        seen.add(t['id'])
        if objects.get(t.get('pick'), {}).get('role') != 'manipulable_object' or objects.get(t.get('place'), {}).get('role') != 'receptacle':
            raise ValueError('Invalid workflow task pick/place role')
        if not isinstance(t.get('instruction'), str) or not t['instruction'].strip():
            raise ValueError('workflow task instruction required')
        success = t.get('success', {})
        if set(success) - {'relation', 'max_speed_m_s', 'bounds_m'}:
            raise ValueError('Unknown workflow success fields')
        speed = success.get('max_speed_m_s')
        if not isinstance(speed, (int, float)) or not np.isfinite(speed) or speed <= 0:
            raise ValueError('Positive workflow success speed required')
        if success.get('relation') == 'inside_region_and_settled':
            b = np.asarray(success.get('bounds_m'), float)
            if b.shape != (2, 3) or not np.isfinite(b).all() or np.any(b[0] >= b[1]):
                raise ValueError('workflow success requires target-local bounds_m [min,max]')
        elif success.get('relation') == 'contained_and_settled':
            g = objects[t['place']]['collision']
            if g.get('type') != 'container' or not g.get('round'):
                raise ValueError('Round container success requires a round target')
        else:
            raise ValueError('Unsupported workflow success relation')
    reset = w.get('reset', {})
    if set(reset) - {'mode', 'seed', 'support_object', 'margin_m', 'clearance_m', 'separation_m', 'yaw_rad', 'xy_jitter_m'}:
        raise ValueError('Unknown workflow reset fields')
    if reset.get('mode', 'uniform') not in ('uniform', 'four_anchors') or reset.get('yaw_rad', [0.0, 0.0]) != [0.0, 0.0]:
        raise ValueError('Unsupported workflow reset mode/yaw')
    if 'support_object' in reset and objects.get(reset['support_object'], {}).get('role') not in ('workspace', 'support_surface'):
        raise ValueError('Unknown workflow reset support object')
    for k in ('margin_m', 'clearance_m', 'separation_m', 'xy_jitter_m'):
        if k in reset and (not np.isfinite(reset[k]) or reset[k] < 0):
            raise ValueError('Invalid workflow reset distance')

    def physical(values):
        if set(values) - {'mass_kg', 'static_friction', 'dynamic_friction', 'restitution', 'provenance', 'note'}:
            raise ValueError('Unknown workflow physics fields')
        for k in ('mass_kg', 'static_friction', 'dynamic_friction', 'restitution'):
            if k in values and (not np.isfinite(values[k]) or values[k] < 0 or (k == 'mass_kg' and values[k] == 0) or (k == 'restitution' and values[k] > 1)):
                raise ValueError('Invalid workflow physics value')
    physical(w.get('physics', {}))
    for name, values in w.get('object_physics', {}).items():
        if objects.get(name, {}).get('role') not in ('manipulable_object', 'receptacle'):
            raise ValueError('Unknown workflow physics object')
        physical(values)
    for name, role in w.get('roles', {}).items():
        if name not in objects or objects[name]['role'] in ('manipulable_object', 'receptacle', 'reference_robot') or role not in ('STATIC_SUPPORT', 'STATIC_GEOMETRY', 'VISUAL_ONLY'):
            raise ValueError('Invalid workflow static role override')
    provenance = w.get('provenance', {})
    required = {'tasks', 'success', 'reset', 'physics'}
    if not required <= provenance.keys():
        raise ValueError('workflow provenance requires tasks/success/reset/physics')
    for key, row in provenance.items():
        if not isinstance(row, dict) or row.get('source') not in SOURCES or row.get('status') not in ('UNVALIDATED', 'VALIDATED', 'NOT_APPLICABLE'):
            raise ValueError('Invalid workflow provenance/status: ' + key)
        if not isinstance(row.get('evidence'), list) or not all((isinstance(e, str) for e in row['evidence'])):
            raise ValueError('workflow evidence must be an explicit list')
        if row['source'] == 'unknown' and row['status'] == 'VALIDATED':
            raise ValueError('Unknown workflow values cannot be validated')
    return w


def geometry_constraint_metrics(scene, row):
    """Metric relative evidence; no absolute pose, scan scale or camera assertion."""
    allowed = {'objects', 'distance_m', 'rim_gap_m', 'same_support_plane', 'uncertainty_m', 'source', 'evidence'}
    if set(row) - allowed:
        raise ValueError('Unknown geometry constraint fields')
    names = row.get('objects', [])
    if len(names) != 2 or len(set(names)) != 2:
        raise ValueError('Constraint requires two distinct object IDs')
    if row.get('source') not in ('measured', 'calibrated') or not isinstance(row.get('evidence'), list) or (not row['evidence']) or (not all((isinstance(x, str) and x.strip() for x in row['evidence']))):
        raise ValueError('Relative constraint requires explicit measured evidence')
    for key in ('distance_m', 'rim_gap_m', 'uncertainty_m'):
        if key in row and (not isinstance(row[key], (int, float)) or not np.isfinite(row[key]) or row[key] < 0):
            raise ValueError('Invalid relative measurement: ' + key)
    if 'same_support_plane' in row and type(row['same_support_plane']) is not bool:
        raise ValueError('Expected same_support_plane boolean')
    objects = {o['id']: o for o in scene['objects']}
    try:
        pair = [objects[n] for n in names]
    except KeyError as e:
        raise ValueError('Missing relative constraint object: ' + str(e)) from e
    poses = [world_pose(scene, o) for o in pair]
    delta = poses[1][:3, 3] - poses[0][:3, 3]
    target = row.get('distance_m')
    derived = None
    support_error = None
    gap = None
    if row.get('same_support_plane') or 'rim_gap_m' in row:
        if any((o['dimensions']['value'] is None for o in pair)):
            raise ValueError('Missing constrained dimensions')
        up = poses[0][:3, 2]
        if not np.allclose(up, poses[1][:3, 2], atol=1e-07):
            raise ValueError('Shared support requires parallel upright object axes')
        heights = [o['dimensions']['value'][2] for o in pair]
        support_error = float(delta @ up - (heights[1] - heights[0]) / 2)
    if 'rim_gap_m' in row:
        if not row.get('same_support_plane'):
            raise ValueError('Rim gap requires same_support_plane')
        for o in pair:
            dims = o['dimensions']
            g = o['collision']
            if dims['provenance'] not in ('measured', 'calibrated') or g.get('type') != 'container' or (not g.get('round')) or (not np.isclose(dims['value'][0], dims['value'][1])):
                raise ValueError('Rim relation requires measured round container diameters')
        if not np.isclose(heights[0], heights[1], atol=1e-08):
            raise ValueError('Aligned rim centres require equal cup heights')
        radii = sum((o['dimensions']['value'][0] / 2 for o in pair))
        derived = float(radii + row['rim_gap_m'])
        if target is None:
            target = derived
        elif abs(target - derived) > max(1e-08, row.get('uncertainty_m', 0)):
            raise ValueError('CONFLICT: centre distance disagrees with measured diameters plus rim gap')
        gap = float(np.linalg.norm(delta - up * (delta @ up)) - radii)
    if target is None or target <= 0:
        raise ValueError('Positive centre distance or derived rim distance required')
    actual = float(np.linalg.norm(delta))
    return {'objects': names, 'distance_m': actual, 'target_m': float(target), 'derived_distance_m': derived, 'distance_residual_m': actual - target, 'rim_gap_m': gap, 'rim_gap_residual_m': None if gap is None else gap - row['rim_gap_m'], 'support_plane_residual_m': support_error}


def validate_geometry_constraints(scene):
    config = scene['geometry_constraints']
    if config.get('schema') != GEOMETRY_CONSTRAINT_SCHEMA or config.get('units') != 'm':
        raise ValueError('Unsupported relative geometry schema/units')
    rows = config.get('distances', [])
    if not rows:
        raise ValueError('Empty relative geometry constraints')
    for row in rows:
        metrics = geometry_constraint_metrics(scene, row)
        tolerance = max(1e-08, row.get('uncertainty_m', 0))
        for key in ('distance_residual_m', 'rim_gap_residual_m', 'support_plane_residual_m'):
            if metrics[key] is not None and abs(metrics[key]) > tolerance:
                raise ValueError('Measured geometry constraint violated: ' + key)
    return config


def validate_horizontal_layout(scene: dict,*,table: str,workspace: str,blocks: list[str],robot_frame: str='robot_base') -> dict:
    """Opt-in initial-layout check for a future Scene, never a calibration repair.

    Explicit box geometry only. Cameras, links, joint poses and provenance are not
    edited or approved. Z placement comes from actual box bottoms and table top.
    """
    validate(scene)
    objects={obj['id']:obj for obj in scene['objects']};issues=[]
    def box(name,role):
        obj=objects[name]
        if obj['role']!=role or obj['collision'].get('type')!='box':
            raise ValueError('Horizontal defaults require explicit '+role+' box collision: '+name)
        return world_pose(scene,obj),np.array(checked_value(obj['dimensions']),float)
    def aligned(name,pose):
        if not np.allclose(pose[:3,2],[0,0,1],atol=1e-10,rtol=0):issues.append(name+': local +Z is not world +Z')
    table_pose,table_size=box(table,'support_surface');workspace_pose,workspace_size=box(workspace,'workspace')
    base=frame_world(scene,robot_frame)
    for name,pose in ((table,table_pose),(workspace,workspace_pose),(robot_frame,base)):aligned(name,pose)
    top=table_pose@np.array([0,0,table_size[2]/2,1.]);inverse=np.linalg.inv(workspace_pose)
    if not np.isclose(workspace_pose[2,3],top[2],atol=1e-9,rtol=0):issues.append(workspace+': origin must lie on table surface')
    table_inverse=np.linalg.inv(table_pose)
    corners=np.array([[x,y,0] for x in (-workspace_size[0]/2,workspace_size[0]/2) for y in (-workspace_size[1]/2,workspace_size[1]/2)])
    world=corners@workspace_pose[:3,:3].T+workspace_pose[:3,3]
    local=world@table_inverse[:3,:3].T+table_inverse[:3,3]
    if np.any(abs(local[:,:2])>table_size[:2]/2+1e-12):issues.append(workspace+': region outside table')
    for name in blocks:
        pose,size=box(name,'manipulable_object');aligned(name,pose)
        vertices=np.array([[x,y,z] for x in (-.5,.5) for y in (-.5,.5) for z in (-.5,.5)])*size
        world=vertices@pose[:3,:3].T+pose[:3,3]
        if not np.isclose(world[:,2].min(),top[2],atol=1e-9,rtol=0):issues.append(name+': bottom is not on table surface')
        local=world@inverse[:3,:3].T+inverse[:3,3]
        if np.any(abs(local[:,:2])>workspace_size[:2]/2+1e-12):issues.append(name+': rotated footprint outside workspace')
        local=world@table_inverse[:3,:3].T+table_inverse[:3,3]
        if np.any(abs(local[:,:2])>table_size[:2]/2+1e-12):issues.append(name+': footprint outside table')
    return {'passed':not issues,'issues':issues,'table_surface_world_z_m':float(top[2]),
            'robot_base_world_position_m':base[:3,3].tolist(),'workspace_dimensions_m':workspace_size[:2].tolist(),
            'calibration_verified':False,'scope':'new_scene_initial_box_layout_only'}

