"""Builder editing projects, canonical working scenes, evidence and candidates.

Algorithms ported from the original local Builder; original files remain read-only.
Working authoring schema and exported immutable Scene schema are distinct.
"""
'Canonical metric scene: column vectors, right handed world Z up, optical cameras.'
import copy
import re
from pathlib import Path
import numpy as np
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
        from real2sim_builder.calibration.geometry import simulation_offsets
        simulation_offsets(scene['robot_model'])
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
WORKFLOW_SCHEMA = 'so101.scene-workflow/1'

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
GEOMETRY_CONSTRAINT_SCHEMA = 'real2sim.geometry-constraints/1'

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
'One current scene, atomic state, append-only history and isolated project assets.'
import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
import yaml
STAGES = ['ANALYZE', 'CAMERA & SCALE', 'GEOMETRY', 'VISUAL', 'PHYSICS', 'VALIDATION', 'EXPORT']
STATUSES = {'DRAFT', 'RUNNING', 'PAUSED', 'STOPPED', 'ACCEPTED', 'NEEDS_MORE_DATA', 'FAILED'}

def read(path):
    with Path(path).open() as stream:
        return yaml.safe_load(stream)

def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('w') as stream:
            if path.suffix == '.json':
                json.dump(data, stream, indent=2, allow_nan=False)
            else:
                yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

class Project:

    def __init__(self, root, *, read_only=None):
        self.root = Path(root).resolve()
        self.info = read(self.root / 'project.yaml')
        if not isinstance(self.info, dict) or self.info.get('schema') != 'real2sim.project/1':
            raise ValueError('Expected an existing real2sim.project/1 project')
        marker = self.root / 'working/owner.json'
        owned = marker.is_file() and read(marker) == {'schema':'real2sim.builder-owner/1','project_id':self.info['id']}
        if read_only is False and not owned:
            raise PermissionError('Unmarked source projects are read-only; clone_project into a new workspace first')
        self.read_only = not owned if read_only is None else bool(read_only)

    def require_writable(self):
        if self.read_only:
            raise PermissionError('Project is open for read-only inspection; create an isolated copy before editing')

    @classmethod
    def create(cls, projects, name):
        if not name.strip():
            raise ValueError('Scene name required')
        slug = re.sub('[^a-z0-9]+', '-', name.lower()).strip('-') or 'scene'
        root = Path(projects).resolve() / (slug + '-' + uuid.uuid4().hex[:8])
        root.mkdir(parents=True, exist_ok=False)
        for child in ('input', 'input/assets', 'working', 'scratch', 'exports'):
            (root / child).mkdir()
        write(root / 'project.yaml', {'schema': 'real2sim.project/1', 'id': root.name, 'name': name, 'created_at': time.time()})
        write(root / 'input/evidence.yaml', {'images': [], 'videos': [], 'landmarks': [], 'masks': [], 'motions': []})
        write(root / 'working/state.json', {'status': 'DRAFT', 'stage': None, 'iteration': 0, 'decision': 'CONTINUE', 'metrics': {}, 'needs': []})
        write(root/'working/owner.json', {'schema':'real2sim.builder-owner/1','project_id':root.name})
        return cls(root)

    @property
    def evidence(self):
        return read(self.root / 'input/evidence.yaml')

    @property
    def state(self):
        return read(self.root / 'working/state.json')

    @property
    def scene(self):
        return read(self.root / 'working/current_scene.yaml')

    def update(self, **fields):
        self.require_writable()
        state = {**self.state, **fields, 'updated_at': time.time()}
        if state['status'] not in STATUSES:
            raise ValueError('Invalid run status')
        write(self.root / 'working/state.json', state)
        with (self.root / 'history.jsonl').open('a') as stream:
            stream.write(json.dumps(state, allow_nan=False) + '\n')
        return state

    def control(self, command):
        self.require_writable()
        if command not in ('pause', 'resume', 'stop'):
            raise ValueError('Unknown command')
        write(self.root / 'working/control.json', {'command': command})

    def invalidate(self):
        self.require_writable()
        if self.state['status'] not in ('DRAFT', 'RUNNING', 'PAUSED'):
            self.update(status='DRAFT', stage=None, decision='CONTINUE', needs=[], export=None, error=None, task='Inputs changed; validation must be rerun')

    def signature(self, scene=None):
        """Bind a validation decision to the exact scene and local evidence bytes."""
        scene = scene if scene is not None else self.scene
        evidence = self.evidence
        files = {}

        def collect(node):
            if isinstance(node, dict):
                for key, item in node.items():
                    if key in ('path', 'mask') and isinstance(item, str):
                        files[item] = sha(local_path(self.root, item))
                    else:
                        collect(item)
            elif isinstance(node, list):
                for item in node:
                    collect(item)
        collect(evidence)
        collect(scene['assets'])

        def digest(data):
            return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return {'scene_sha256': digest(scene), 'evidence_sha256': digest(evidence), 'files': files}

    def checkpoint(self):
        self.require_writable()
        command = self.root / 'working/control.json'
        if not command.exists():
            return
        instruction = read(command)['command']
        command.unlink()
        if instruction == 'stop':
            raise InterruptedError('User stopped reconstruction')
        if instruction == 'pause':
            self.update(status='PAUSED')
            while True:
                time.sleep(0.1)
                if not command.exists():
                    continue
                instruction = read(command)['command']
                command.unlink()
                if instruction == 'stop':
                    raise InterruptedError('User stopped reconstruction')
                if instruction == 'resume':
                    break
            self.update(status='RUNNING')

    def save_scene(self, scene):
        self.require_writable()
        write(self.root / 'working/current_scene.yaml', scene)
        self.invalidate()
'Content-addressed input import. Reference projects are only read, never imported.'
import copy
from pathlib import Path
import shutil
import numpy as np
from PIL import Image, ImageOps
PROVENANCE = {'user_measured': 'measured', 'model_asset': 'derived', 'derived': 'derived', 'numerically_fitted': 'optimized', 'provisional': 'estimated', 'unmeasured': 'unknown', 'measured': 'measured', 'calibrated': 'calibrated', 'optimized': 'optimized', 'estimated': 'estimated', 'unknown': 'unknown'}

def copy_input(project, path, category='media'):
    project.require_writable()
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    relative = Path('input') / category / (sha(path) + path.suffix.lower())
    destination = project.root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(path, destination)
    return relative.as_posix()

def add_image(project, path, camera='side', split='train', timestamp=None, context_only=False):
    project.require_writable()
    identifier(camera)
    if split not in ('train', 'validation'):
        raise ValueError('Unknown evidence split')
    relative = copy_input(project, path)
    with Image.open(project.root / relative) as im:
        im = ImageOps.exif_transpose(im)
        resolution = list(im.size)
    evidence = project.evidence
    row = {'path': relative, 'camera': camera, 'split': split, 'timestamp': timestamp, 'resolution': resolution, 'sha256': sha(project.root / relative), 'source': str(Path(path).resolve())}
    if context_only:
        row.update(role='reference_context', eligible=False, exclusion_reasons=['reference_camera_not_calibrated_for_pixel_fitting'])
    if not any((relative in (e['path'], e.get('original_path')) and e['camera'] == camera for e in evidence['images'])):
        evidence['images'].append(row)
    write(project.root / 'input/evidence.yaml', evidence)
    project.invalidate()
    return row

def add_video(project, path, camera='side', split='train', max_frames=12):
    project.require_writable()
    import cv2
    identifier(camera)
    relative = copy_input(project, path)
    evidence = project.evidence
    video = {'path': relative, 'camera': camera, 'split': split, 'max_frames': int(max_frames), 'extracted': False}
    if split not in ('train', 'validation') or not 1 <= max_frames <= 1000:
        raise ValueError('Invalid video sampling')
    evidence['videos'].append(video)
    write(project.root / 'input/evidence.yaml', evidence)
    project.invalidate()

def extract_videos(project):
    project.require_writable()
    import cv2
    evidence = project.evidence
    for video in evidence['videos']:
        if video['extracted']:
            continue
        capture = cv2.VideoCapture(str(local_path(project.root, video['path'])))
        try:
            count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = float(capture.get(cv2.CAP_PROP_FPS))
            if not capture.isOpened() or count < 1 or (not np.isfinite(fps)) or (fps <= 0):
                raise ValueError('Unreadable video or missing timestamps')
            indices = np.unique(np.linspace(0, count - 1, min(count, video['max_frames'])).astype(int))
            previous = None
            for i in indices:
                project.checkpoint()
                capture.set(cv2.CAP_PROP_POS_FRAMES, int(i))
                ok, frame = capture.read()
                if not ok:
                    raise ValueError('Video frame could not be decoded')
                small = cv2.resize(frame, (64, 48))
                if previous is not None and np.mean(abs(small.astype(float) - previous)) < 2:
                    continue
                previous = small.astype(float)
                path = project.root / 'scratch' / f'video_frame_{i}.png'
                cv2.imwrite(str(path), frame)
                add_image(project, path, video['camera'], video['split'], float(i / fps))
            video['extracted'] = True
        finally:
            capture.release()
    current = project.evidence
    current['videos'] = evidence['videos']
    write(project.root / 'input/evidence.yaml', current)

def asset_importer(project, scene):
    project.require_writable()

    def import_asset(path):
        relative = copy_input(project, path, 'assets')
        key = 'asset_' + sha(project.root / relative)[:16]
        scene['assets'][key] = {'path': relative, 'sha256': sha(project.root / relative), 'source': str(Path(path).resolve())}
        return key
    return import_asset

def import_scene(project, path):
    project.require_writable()
    scene = read(path)
    validate(scene)
    for asset in scene['assets'].values():
        source = local_path(Path(path).parent, asset['path'])
        asset['path'] = copy_input(project, source, 'assets')
        asset['sha256'] = sha(project.root / asset['path'])
    scene['name'] = project.info['name']
    validate(scene, project.root)
    project.save_scene(scene)

def import_metadata(project, path, kind='measurements'):
    project.require_writable()
    payload = read(path)
    stored = copy_input(project, path, 'metadata')
    if payload.get('schema') == 'real2sim.scene/1':
        return import_scene(project, path)
    if payload.get('units') not in ('m', 'mm'):
        raise ValueError('Metadata requires explicit units: m or mm')
    payload = copy.deepcopy(payload)
    if payload['units'] == 'mm':

        def distance(node):
            if isinstance(node, dict) and 'value' in node:
                result = copy.deepcopy(node)
                result['value'] = None if node['value'] is None else (np.asarray(node['value'], float) / 1000).tolist()
                return result
            return (np.asarray(node, float) / 1000).tolist()

        def pose(node):
            result = copy.deepcopy(node)
            t = np.asarray(node['value'] if isinstance(node, dict) else node, float)
            if t.shape != (4, 4):
                raise ValueError('Expected homogeneous measurement pose')
            t[:3, 3] /= 1000
            if isinstance(result, dict):
                result['value'] = t.tolist()
            else:
                result = t.tolist()
            return result
        for obj in payload.get('objects', []):
            if 'dimensions' in obj:
                obj['dimensions'] = distance(obj['dimensions'])
            if 'pose' in obj:
                obj['pose'] = pose(obj['pose'])
            for key in ('visual', 'collision'):
                if obj.get(key, {}).get('wall') is not None:
                    obj[key]['wall'] = distance(obj[key]['wall'])
                if obj.get(key, {}).get('bottom_diameter_m') is not None:
                    obj[key]['bottom_diameter_m'] = float(obj[key]['bottom_diameter_m']) / 1000
        for frame in payload.get('frames', {}).values():
            frame['transform'] = pose(frame['transform'])
        for camera in payload.get('cameras', []):
            if camera.get('pose') is not None:
                camera['pose'] = pose(camera['pose'])
        for landmark in payload.get('landmarks', []):
            if 'point_m' in landmark:
                landmark['point_m'] = distance(landmark['point_m'])
        for row in payload.get('distances', []):
            for key in ('distance_m', 'uncertainty_m'):
                if key in row:
                    row[key] = float(row[key]) / 1000
        if any((payload.get(key) for key in ('depths', 'point_clouds', 'motions', 'actions'))):
            raise ValueError('Sensor arrays/actions require their explicit metre contracts; mm metadata only converts geometry')
        payload['units'] = 'm'
    scene = project.scene if (project.root / 'working/current_scene.yaml').exists() else empty(project.info['name'])
    source = 'calibrated' if kind == 'calibration' else 'measured'
    constraints = []
    for row in payload.get('distances', []):
        row = copy.deepcopy(row)
        names = row.get('objects', [])
        if len(names) != 2 or len(set(names)) != 2 or (not np.isfinite(row.get('distance_m', np.nan))) or (row['distance_m'] <= 0):
            raise ValueError('Measured distance requires two object IDs and positive metric length')
        for name in names:
            identifier(name)
        if not np.isfinite(row.get('uncertainty_m', 0.0)) or row.get('uncertainty_m', 0.0) < 0:
            raise ValueError('Invalid distance uncertainty')
        row.update(source=row.get('source', source), evidence=row.get('evidence', [stored]))
        constraints.append(row)

    def field(v):
        return v if isinstance(v, dict) and 'provenance' in v else value(v, source, [stored])

    def assign(node, key, incoming, identity):
        previous = node.get(key)
        if isinstance(previous, dict) and previous.get('provenance') in ('measured', 'calibrated'):
            if previous['value'] != incoming['value']:
                report = {'status': 'CONFLICT', 'field': identity + '.' + key, 'existing': previous, 'incoming': incoming, 'source': stored}
                write(project.root / 'working/measurement_conflicts' / (sha(project.root / stored) + '.json'), report)
                raise ValueError('Conflicting measured/calibrated field: ' + identity + '.' + key)
            return
        node[key] = incoming
    for key, frame in payload.get('frames', {}).items():
        old = scene['frames'].get(key)
        if old and old['parent'] != frame.get('parent', 'world') and (old['transform']['provenance'] in ('measured', 'calibrated')):
            raise ValueError('Protected measured/calibrated frame parent: ' + key)
        node = copy.deepcopy(old or {'parent': frame.get('parent', 'world')})
        assign(node, 'transform', field(frame['transform']), key)
        scene['frames'][key] = node
    for key, asset in payload.get('assets', {}).items():
        relative = copy_input(project, Path(path).parent / asset['path'], 'assets')
        scene['assets'][key] = {'path': relative, 'sha256': sha(project.root / relative), 'source': str((Path(path).parent / asset['path']).resolve())}
    objects = {o['id']: o for o in scene['objects']}
    for row in payload.get('objects', []):
        identifier(row['id'])
        obj = objects.get(row['id'], {'id': row['id'], 'role': row.get('role', 'fixture'), 'frame': row.get('frame', 'world'), 'pose': value(None), 'dimensions': value(None), 'visual': {'type': 'unknown'}, 'collision': {'type': 'unknown'}, 'color': value([0.6, 0.6, 0.6], 'estimated'), 'physics': {'mass_kg': value(None), 'friction': value(None)}})
        for key in ('pose', 'dimensions', 'color'):
            if key in row:
                assign(obj, key, field(row[key]), row['id'])
        for key in ('visual', 'collision', 'role', 'frame'):
            if key in row:
                obj[key] = copy.deepcopy(row[key])
        if 'shape' in row:
            obj['visual'] = {'type': row['shape']}
            obj['collision'] = copy.deepcopy(obj['visual'])
        for key, v in row.get('physics', {}).items():
            assign(obj['physics'], key, field(v), row['id'] + '.physics')
        if row.get('uncertainty'):
            obj['measurement_uncertainty'] = copy.deepcopy(row['uncertainty'])
        for geometry in (obj['visual'], obj['collision']):
            if geometry.get('wall') is not None:
                geometry['wall'] = field(geometry['wall'])
        objects[obj['id']] = obj
    scene['objects'] = list(objects.values())
    cameras = {c['id']: c for c in scene['cameras']}
    for row in payload.get('cameras', []):
        camera = cameras.get(row['id'], {'id': row['id'], 'frame': row.get('frame', 'world'), 'pose': value(None), 'K': value(None), 'resolution': row['resolution'], 'distortion': value([0.0] * 5, 'estimated')})
        for key in ('pose', 'K', 'distortion'):
            if key in row:
                assign(camera, key, field(row[key]), row['id'])
        for key in ('frame', 'resolution', 'purpose'):
            if key in row:
                camera[key] = row[key]
        cameras[row['id']] = camera
    scene['cameras'] = list(cameras.values())
    validate(scene, project.root)
    project.save_scene(scene)
    evidence = project.evidence
    sets = evidence.setdefault('measurement_sets', [])
    if not any((r['path'] == stored for r in sets)):
        sets.append({'path': stored, 'sha256': sha(project.root / stored), 'kind': kind})
    for row in constraints:
        if row not in evidence.setdefault('distances', []):
            evidence['distances'].append(row)
    for key in ('landmarks', 'motions'):
        evidence[key].extend(payload.get(key, []))
    for key in ('depths', 'point_clouds', 'actions'):
        for observation in payload.get(key, []):
            observation = copy.deepcopy(observation)
            for file_key in ('path', 'mask'):
                if observation.get(file_key):
                    observation[file_key] = copy_input(project, Path(path).parent / observation[file_key], 'metadata')
            evidence.setdefault(key, []).append(observation)
    for mask in payload.get('masks', []):
        mask = copy.deepcopy(mask)
        original = Path(path).parent / mask['path']
        mask['path'] = copy_input(project, original, 'metadata')
        source = (Path(path).parent / mask['image']).resolve()
        matches = [i for i in evidence['images'] if i['path'] == mask['image'] or i.get('source') == str(source)]
        if len(matches) != 1:
            raise ValueError('Mask image must identify one imported frame')
        mask['image'] = matches[0]['path']
        evidence['masks'].append(mask)
    write(project.root / 'input/evidence.yaml', evidence)

def import_robot(project, urdf, joints=None, base=None, recorded_links=None):
    project.require_writable()
    from real2sim_builder.calibration.geometry import reference_geometry, reference_model
    scene = project.scene if (project.root / 'working/current_scene.yaml').exists() else empty(project.info['name'])
    scene['frames']['robot_base'] = {'parent': 'world', 'transform': value(base if base is not None else np.eye(4).tolist(), 'measured' if base is not None else 'estimated')}
    if Path(urdf).suffix.lower() == '.urdf':
        objects, poses = reference_geometry(urdf, joints or {}, asset_importer(project, scene), recorded_links=recorded_links)
    else:
        objects, poses = reference_model(urdf, joints or {}, asset_importer(project, scene), project.root / 'scratch/reference_model')
    copy_input(project, urdf, 'models')
    scene['objects'] = [o for o in scene['objects'] if o['role'] != 'reference_robot'] + objects
    for name, t in poses.items():
        scene['frames']['robot_link_' + name] = {'parent': 'robot_base', 'transform': value(t.tolist(), 'derived')}
    validate(scene, project.root)
    project.save_scene(scene)

def import_reference(project, workspace, capture):
    project.require_writable()
    'Optional generic profile/URDF migration; intentionally reads no task/policy files.'
    workspace = Path(workspace).resolve()
    capture = Path(capture).resolve()
    profile = read(workspace / 'profile.json')
    state = read(capture / 'state.json')
    scene = empty(project.info['name'])
    origin = str(workspace / 'profile.json')

    def field(node, key, default=None):
        v = node.get(key, default)
        source = PROVENANCE.get(node.get('provenance', {}).get(key), 'unknown')
        if v is not None and source == 'unknown':
            source = 'estimated'
        return value(v, source, [origin])
    scene['frames']['workspace'] = {'parent': 'world', 'transform': field(profile['workspace'], 'T_world')}
    for name, row in [('table', profile['table']), *profile['objects'].items()]:
        if not row.get('render_enabled', True):
            scene['uncertainties'].append(name + ': disabled/incomplete reference geometry')
            continue
        dims = row.get('dimensions_m')
        shape = row['shape']
        if shape in ('cup', 'cup_proxy'):
            shape = 'container'
            if dims is None:
                dims = [row['top_outer_diameter_m']] * 2 + [row['height_m']]
        geom = {'type': shape}
        if shape == 'container':
            geom['wall'] = field(row, 'wall_m', row.get('wall_thickness_m'))
            geom['round'] = True
            if row.get('bottom_outer_diameter_m'):
                geom['bottom_diameter_m'] = row['bottom_outer_diameter_m']
        role = row.get('semantic_role') or ('support_surface' if name == 'table' else 'receptacle' if shape == 'container' else 'background' if name.startswith('background_') else 'fixture' if name.startswith('marker') else 'manipulable_object')
        scene['objects'].append({'id': name, 'role': role, 'frame': 'workspace', 'pose': field(row, 'T_workspace'), 'dimensions': value(dims, field(row, 'dimensions_m')['provenance'] if dims else 'unknown', [origin]), 'visual': geom, 'collision': copy.deepcopy(geom), 'color': field(row['appearance'], 'color'), 'physics': {'mass_kg': value(None), 'friction': value(None)}})
    for name, camera in profile['cameras'].items():
        frame = 'world' if camera['parent'] == 'world' else 'robot_link_' + camera['parent']
        scene['cameras'].append({'id': name, 'frame': frame, 'pose': field(camera, 'T_parent_camera'), 'K': field(camera, 'K'), 'distortion': field(camera, 'distortion'), 'resolution': camera['resolution']})
    project.save_scene(scene)
    urdf = workspace / profile.get('robot_asset', {}).get('urdf', 'assets/robot.urdf')
    if urdf.is_file():
        import_robot(project, urdf, state.get('sim_measured_joint_state_rad'), profile['robot_base']['T_world'], state.get('links_base'))
    scene = project.scene
    scene['frames']['robot_base']['transform'] = field(profile['robot_base'], 'T_world')
    scene['uncertainties'].append('Reference calibration and robot mapping are inherited evidence, not newly validated ground truth')
    project.save_scene(scene)
    for camera in scene['cameras']:
        image = capture / ('real_' + camera['id'] + '.png')
        if image.is_file():
            add_image(project, image, camera['id'], 'train' if camera['id'] == 'side' else 'validation')
    copy_input(project, workspace / 'profile.json', 'metadata')
    write(project.root / 'input/reference_observation.yaml', {'links_base': state.get('links_base'), 'joint_states_rad': state.get('sim_measured_joint_state_rad'), 'source': str(capture), 'quality': state.get('quality')})
    return project.scene

def add_brief(project, path):
    project.require_writable()
    relative = copy_input(project, path, 'notes')
    evidence = project.evidence
    evidence.setdefault('briefs', []).append({'path': relative, 'sha256': sha(project.root / relative)})
    write(project.root / 'input/evidence.yaml', evidence)
    project.invalidate()
    return relative
'Schema-aware candidate edits. Inferred values cannot replace measured fields.'
import copy
import numpy as np
PROTECTED = {'measured', 'calibrated'}

def preserve(before, after, path='scene'):
    if isinstance(before, dict):
        if (before.get('provenance') in tuple(PROTECTED) or before.get('source') in tuple(PROTECTED)) and before != after:
            raise ValueError('Protected measured/calibrated field: ' + path)
        if isinstance(after, dict):
            for key, old in before.items():
                if key in after:
                    preserve(old, after[key], path + '.' + key)
                else:
                    preserve(old, None, path + '.' + key)
        else:
            for key, old in before.items():
                preserve(old, None, path + '.' + key)
    elif isinstance(before, list):
        for i, old in enumerate(before):
            following = after[i] if isinstance(after, list) and i < len(after) else None
            preserve(old, following, path + '.' + str(i))

def check_scope(before, after, scope):
    """Object ID keyed locks; shared frames/cameras/lights and other objects stay exact."""
    if not scope:
        return
    name = scope['target_object']
    fields = set(scope['allow'])
    if before.get('scan_initialization') and fields & {'pose', 'dimensions'} and (not cameras_audited(before)):
        raise ValueError('Scan object pixel refinement requires audited camera calibration first')
    old = {o['id']: o for o in before['objects']}
    new = {o['id']: o for o in after['objects']}
    if old.keys() != new.keys():
        raise ValueError('Object scope forbids add/remove')
    for identity, obj in old.items():
        following = new[identity]
        if identity != name:
            if obj != following:
                raise ValueError('Locked object changed: ' + identity)
        else:
            for key in set(obj) | set(following):
                if key not in fields and obj.get(key) != following.get(key):
                    raise ValueError('Locked object field: ' + key)
    for key in (set(before) | set(after)) - {'objects', 'assets'}:
        if before.get(key) != after.get(key):
            raise ValueError('Locked scene group changed: ' + key)
    if 'visual' not in fields:
        if before['assets'] != after['assets']:
            raise ValueError('Locked assets changed')
    else:
        for key, row in before['assets'].items():
            if after['assets'].get(key) != row:
                raise ValueError('Accepted asset changed in place')

def apply(scene, operations, root):
    result = copy.deepcopy(scene)
    for operation in operations:
        op = operation['op']
        name = operation.get('id')
        if result.get('scan_initialization') and op in ('update_pose', 'update_dimensions') and (not cameras_audited(result)):
            raise ValueError('Scan object pixel refinement requires camera audit first; use measurement/registration evidence for metric initialization')
        if name:
            identifier(name)
        if op == 'add_object':
            if any((o['id'] == name for o in result['objects'])):
                raise ValueError('Duplicate object ID')
            t = operation.get('pose', np.eye(4).tolist())
            shape = operation.get('visual', {'type': 'box'})
            obj = {'id': name, 'role': operation.get('role', 'fixture'), 'frame': operation.get('frame', 'world'), 'pose': value(t, 'estimated'), 'dimensions': value(operation.get('dimensions')), 'color': value(operation.get('color', [0.6] * 3), 'estimated'), 'visual': shape, 'collision': operation.get('collision', {'type': 'unknown'}), 'physics': {'mass_kg': value(None), 'friction': value(None)}}
            if operation.get('dimensions') is not None:
                obj['dimensions'] = value(operation['dimensions'], 'estimated')
            result['objects'].append(obj)
        elif op == 'remove_object':
            obj = next((o for o in result['objects'] if o['id'] == name))
            result['objects'].remove(obj)
        elif op in ('update_pose', 'update_dimensions', 'set_material', 'set_visual_mesh', 'set_collision'):
            obj = next((o for o in result['objects'] if o['id'] == name))
            old = copy.deepcopy(obj)
            evidence = operation.get('evidence', ['agent candidate hypothesis'])
            if op in ('update_pose', 'update_dimensions'):
                obj['pose' if op == 'update_pose' else 'dimensions'] = value(operation['value'], 'estimated', evidence)
            elif op == 'set_material':
                if 'color' in operation:
                    obj['color'] = value(operation['color'], 'estimated', evidence)
                obj.setdefault('material', {}).update({k: value(v, 'estimated', evidence) for k, v in operation.items() if k in ('roughness', 'metallic')})
                if 'texture' in operation:
                    obj['visual']['texture'] = operation['texture']
            elif op == 'set_visual_mesh':
                obj['visual'] = {'type': 'mesh', 'asset': operation['asset'], 'scale': operation.get('scale', [1, 1, 1]), 'source': 'agent_authored', 'provenance': 'estimated'}
                if operation.get('texture'):
                    obj['visual']['texture'] = operation['texture']
            else:
                obj['collision'] = copy.deepcopy(operation['value'])
            preserve(old, obj, name)
        elif op == 'set_camera':
            cameras = result['cameras']
            existing = next((c for c in cameras if c['id'] == name), None)
            if existing is None:
                existing = {'id': name, 'frame': operation.get('frame', 'world'), 'pose': value(None), 'K': value(None), 'distortion': value([0.0] * 5, 'estimated'), 'resolution': operation['resolution']}
                cameras.append(existing)
            old = copy.deepcopy(existing)
            for key in ('pose', 'K', 'distortion'):
                if key in operation:
                    existing[key] = value(operation[key], 'estimated', operation.get('evidence', []))
            for key in ('frame', 'resolution', 'purpose'):
                if key in operation:
                    existing[key] = operation[key]
            preserve(old, existing, name)
        elif op == 'set_workflow':
            previous = result.get('workflow', {})
            result['workflow'] = copy.deepcopy(operation['value'])
            preserve(previous, result['workflow'], 'workflow')
        elif op == 'set_lighting':
            old = copy.deepcopy(result['lights'])
            result['lights']['ambient'] = value(operation['ambient'], 'estimated', operation.get('evidence', []))
            if 'sources' in operation:
                result['lights']['sources'] = [{'id': r['id'], 'type': r['type'], **{k: value(r[k], 'estimated') for k in ('pose', 'color', 'energy', 'size')}} for r in operation['sources']]
                for previous in old.get('sources', []):
                    following = next((r for r in result['lights']['sources'] if r['id'] == previous['id']), {})
                    preserve(previous, following, 'light.' + previous['id'])
            preserve(old, result['lights'], 'lights')
        else:
            raise ValueError('Unsupported edit operation: ' + op)
    validate(result, root)
    return result
'Independent capture contract importer and immutable measured-state observations.'
import copy
from pathlib import Path
import shutil
import numpy as np
CAPTURE_SCHEMA = 'real2sim.capture/1'

def mapping_contract(manifest):
    """Validate portable mapping evidence without importing SO-101 or motor SDKs."""
    import hashlib, json
    mapping = manifest.get('joint_mapping', {})
    precision = mapping.get('schema') == 'so101.precision-joint-mapping/1'
    legacy = mapping.get('version') == 'so101.sim-joint-mapping/1'
    if not precision and (not legacy):
        return
    payload = {k: v for k, v in mapping.items() if k != 'sha256'}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    if digest != mapping.get('sha256'):
        raise ValueError('Precision mapping hash mismatch' if precision else 'Legacy mapping hash mismatch')
    if mapping.get('joint_order') != manifest['joint_names'] or mapping.get('output') != 'urdf_joint_radian' or any((u != 'rad' for u in manifest['joint_units'])):
        raise ValueError('Precision observations must already be named URDF radians')
    if legacy:
        return
    profile = mapping.get('profile', {})
    if profile.get('schema') != 'so101.precision-calibration/1':
        raise ValueError('Unsupported precision profile')
    source_hash = manifest.get('source_robot_sha256')
    if not source_hash or profile.get('urdf_sha256') != source_hash:
        raise ValueError('Precision profile/source URDF identity differs or is missing')
    if not profile.get('joints'):
        raise ValueError('Precision profile requires joint evidence')
    for name, entry in profile.get('joints', {}).items():
        if name not in manifest['joint_names'] or entry.get('status') not in ('REVIEWED_MANUAL', 'VALIDATED_MANUAL'):
            raise ValueError('Unsupported precision joint review state')
        if not np.isfinite(entry.get('rad_per_count', np.nan)) or entry['rad_per_count'] == 0:
            raise ValueError('Invalid precision mapping coefficient')
    if manifest['robot'].get('mapping_verified') and (not mapping.get('physical_verified', False)):
        raise ValueError('Manual precision mapping cannot be relabelled physically verified')
    if mapping.get('physical_verified', False):
        raise ValueError('Manual precision mapping is not externally physically verified')

def load_session(root):
    root = Path(root).resolve()
    m = read(root / 'capture_manifest.yaml')
    if m.get('schema') == 'real2sim.snapshot/1':
        return load_snapshots(root)
    if m.get('schema') != CAPTURE_SCHEMA or not (root / 'COMPLETE').exists():
        raise ValueError('Incomplete/unsupported capture dataset')
    identifier(m['session_id'])
    identifier(m['group_id'])
    if m['split'] not in ('train', 'validation'):
        raise ValueError('Invalid capture split')
    if m['clock']['domain'] != 'host_monotonic_ns' or len(m['joint_units']) != len(m['joint_names']) or any((u not in ('rad', 'm') for u in m['joint_units'])):
        raise ValueError('Explicit monotonic-ns / model-radian contract required')
    if len(set(m['joint_names'])) != len(m['joint_names']) or m['q_measured_source'] != 'physical_follower_feedback_converted_to_model':
        raise ValueError('Invalid measured joint contract')
    if m.get('quality', {}).get('incomplete'):
        raise ValueError('Capture marked incomplete')
    for relative, digest in m['files'].items():
        if sha(local_path(root, relative)) != digest:
            raise ValueError('Immutable capture hash mismatch: ' + relative)
    for key in ('samples', 'events'):
        if m[key] not in m['files']:
            raise ValueError('Unhashed capture data')
    if m['robot']['path'] not in m['files']:
        raise ValueError('Unhashed robot model')
    validate_model_files(root, m)
    mapping_contract(m)
    samples = read(local_path(root, m['samples']))
    events = read(local_path(root, m['events']))
    previous = -1
    for row in samples:
        q = np.asarray(row['q_measured'], float)
        if q.shape != (len(m['joint_names']),) or not np.isfinite(q).all() or row['timestamp_ns'] <= previous:
            raise ValueError('Invalid measured joints or timestamps')
        previous = row['timestamp_ns']
        if {i['camera'] for i in row['images']} != {c['id'] for c in m['cameras']}:
            raise ValueError('Missing camera stream')
        for image in row['images']:
            if image['path'] not in m['files']:
                raise ValueError('Unhashed camera image')
    return (m, samples, events)

def align(samples, timestamp, names, discrete=(), max_skew_ns=100000000):
    times = np.array([s['timestamp_ns'] for s in samples], dtype=np.int64)
    right = int(np.searchsorted(times, timestamp))
    if right < len(times) and times[right] == timestamp:
        return np.asarray(samples[right]['q_measured'], float)
    if right == 0 or right == len(times):
        index = 0 if right == 0 else len(times) - 1
        if abs(int(times[index]) - timestamp) > max_skew_ns:
            raise ValueError('Joint sample outside maximum skew')
        return np.asarray(samples[index]['q_measured'], float)
    left = right - 1
    if max(timestamp - int(times[left]), int(times[right]) - timestamp) > max_skew_ns:
        raise ValueError('Joint interpolation gap exceeds maximum skew')
    a = np.asarray(samples[left]['q_measured'])
    b = np.asarray(samples[right]['q_measured'])
    alpha = (timestamp - times[left]) / float(times[right] - times[left])
    q = a * (1 - alpha) + b * alpha
    for name in discrete:
        index = names.index(name)
        q[index] = a[index]
    return q

def _import_session(project, root, max_skew_ns=100000000, loaded=None):
    project.require_writable()
    m, samples, events = loaded or load_session(root)
    if not samples:
        raise ValueError('Capture has no measured samples')
    known_groups = {i.get('group_id'): i['split'] for i in project.evidence['images'] if i.get('group_id')}
    if m['group_id'] in known_groups and known_groups[m['group_id']] != m['split']:
        raise ValueError('Train/holdout group leakage')
    destination = project.root / 'input/captures' / m['session_id']
    if destination.exists():
        raise ValueError('Capture session already imported')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root, destination)
    if not (project.root / 'working/current_scene.yaml').exists():
        project.save_scene(empty(project.info['name']))
    scene = project.scene
    if m.get('scene_state_id'):
        existing_state = scene.get('reconstruction_state')
        if existing_state and existing_state['id'] != m['scene_state_id']:
            raise ValueError('Different static object layouts require separate reconstruction projects')
        scene['reconstruction_state'] = {'id': m['scene_state_id'], 'assumption': 'fixed objects/base; varying measured robot pose'}
        project.save_scene(scene)
    if scene.get('robot_model'):
        if scene['robot_model']['model_sha256'] != sha(destination / m['robot']['path']):
            raise ValueError('Robot model differs across capture sessions')
        if scene['robot_model']['joint_names'] != m['joint_names'] or scene['robot_model']['mapping'] != m['joint_mapping']:
            raise ValueError('Joint mapping/order differs across capture sessions')
    else:
        if m['robot']['format'] not in ('urdf', 'mjcf'):
            raise ValueError('Capture articulation requires URDF or scalar-joint MJCF')
        import_robot(project, destination / m['robot']['path'], dict(zip(m['joint_names'], samples[0]['q_measured'])), m['robot']['T_world_base'])
        scene = project.scene
        from real2sim_builder.calibration.geometry import link_transforms
        fk = link_transforms(destination / m['robot']['path'], dict(zip(m['joint_names'], samples[0]['q_measured'])))
        for obj in scene['objects']:
            if obj.get('link'):
                obj['link_local_pose'] = (np.linalg.inv(fk[obj['link']]) @ np.asarray(obj['pose']['value'])).tolist()
        scene['robot_model'] = {'format': m['robot']['format'], 'path': (destination / m['robot']['path']).relative_to(project.root).as_posix(), 'model_sha256': sha(destination / m['robot']['path']), 'joint_names': m['joint_names'], 'mapping': m['joint_mapping'], 'mapping_verified': m['robot'].get('mapping_verified', False)}
        scene['robot_model']['source_robot_sha256'] = m.get('source_robot_sha256')
        scene['robot_model']['joint_coordinate_status'] = 'URDF_RAD_MANUAL_PRECISION' if m['joint_mapping'].get('schema') == 'so101.precision-joint-mapping/1' else 'LEGACY_OR_GENERIC_RECORDED_MAPPING'
        for path in (destination / 'robot_model').rglob('*'):
            if path.is_file():
                scene['assets']['robot_input_' + sha(path)[:16]] = {'path': path.relative_to(project.root).as_posix(), 'sha256': sha(path), 'source': 'immutable_capture_robot'}
        base_source = m['robot'].get('base_provenance', {})
        if isinstance(base_source, dict):
            base_source = base_source.get('T_world', 'estimated')
        scene['frames']['robot_base']['transform'] = value(m['robot']['T_world_base'], PROVENANCE.get(base_source, 'estimated'), ['capture robot base'])
    validate_joint_units(destination / m['robot']['path'], m['joint_names'], m['joint_units'])
    sessions = project.evidence.get('capture_sessions', [])
    if sessions:
        original = read(local_path(project.root, sessions[0]['path']))
        if original['cameras'] != m['cameras']:
            keys = ('id', 'parent', 'resolution', 'K', 'distortion')
            same_sensor = sorted([{k: c[k] for k in keys} for c in original['cameras']], key=lambda c: c['id']) == sorted([{k: c[k] for k in keys} for c in m['cameras']], key=lambda c: c['id'])
            if m.get('calibration_reconciliation') and m.get('paired_evidence'):
                keys = ('id', 'parent', 'resolution', 'distortion')
                compatible = sorted([{k: c[k] for k in keys} for c in original['cameras']], key=lambda c: c['id']) == sorted([{k: c[k] for k in keys} for c in m['cameras']], key=lambda c: c['id'])
                for camera in m['cameras']:
                    canonical = next((c for c in scene['cameras'] if c['id'] == camera['id']))
                    prior = next((c for c in original['cameras'] if c['id'] == camera['id']))
                    protected = prior.get('provenance', {}).get('K') in ('measured', 'calibrated', 'user_measured') and (not np.allclose(prior['K'], camera['K']))
                    compatible = compatible and (not protected) and (canonical['K']['provenance'] not in ('measured', 'calibrated')) and np.allclose(camera['K'], canonical['K']['value'])
                same_sensor = compatible
            if not m.get('paired_evidence') or not same_sensor:
                raise ValueError('Recorded sensor calibration changed; explicit calibration reconciliation is required')
    for row in m['cameras']:
        frame = 'world' if row['parent'] == 'world' else 'robot_base' if row['parent'] == 'robot_base' else 'robot_link_' + row['parent']
        if frame not in scene['frames']:
            raise ValueError('Unknown camera mount link ' + frame)

        def calibration_field(key):
            data = row[key]
            origin = row.get('provenance', {}).get(key)
            return value(data, 'unknown' if data is None else 'calibrated' if origin in ('calibrated', 'measured', 'user_measured') else 'optimized' if origin == 'numerically_fitted' else 'estimated')
        camera = {'id': row['id'], 'frame': frame, 'resolution': row['resolution'], 'pose': calibration_field('T_parent_camera'), 'K': calibration_field('K'), 'distortion': calibration_field('distortion')}
        camera['calibration_quality'] = {'state': 'UNKNOWN' if row['K'] is None or row['T_parent_camera'] is None else 'ESTIMATED', 'scope': 'inherited capture metadata; numerical fitting does not prove metric calibration', 'physical_verified': False}
        existing = next((c for c in scene['cameras'] if c['id'] == row['id']), None)
        if existing is None:
            scene['cameras'].append(camera)
        elif existing['frame'] != frame or existing['resolution'] != row['resolution']:
            raise ValueError('Camera mount/resolution changed between sessions')
    project.save_scene(scene)
    evidence = project.evidence
    observed = []
    seen = {}
    for sample in samples:
        for image in sample['images']:
            key = (image['camera'], image['sequence'])
            if key in seen:
                continue
            seen[key] = True
            t = int(image['timestamp_ns'])
            reasons = []
            if m['purpose'] != 'snapshot':
                reasons.extend(legacy_static_reasons(m, events, t))
            if image.get('stale'):
                reasons.append('stale_camera_sample')
            if image.get('blur_variance', 0) < 10:
                reasons.append('blur_or_textureless_image')
            try:
                q = align(sample.get('measured_history', samples), t, m['joint_names'], m.get('discrete_joints', []), max_skew_ns).tolist()
            except ValueError as exc:
                reasons.append(str(exc))
                q = None
            if not sample.get('quality', {}).get('eligible_for_calibration', False):
                reasons.append('capture_quality_not_static')
            relative = (destination / image['path']).relative_to(project.root).as_posix()
            observation = {'id': m.get('source_dataset_id', m['session_id']) + '_' + sample['id'] + '_' + image['camera'], 'path': relative, 'camera': image['camera'], 'split': sample.get('split', m['split']), 'snapshot_id': sample['id'] if m['purpose'] == 'snapshot' else None, 'scene_state_id': m.get('scene_state_id'), 'resolution': image['resolution'], 'sha256': sha(project.root / relative), 'timestamp_ns': t, 'group_id': sample.get('group_id', m['group_id']), 'session_id': m['session_id'], 'q_measured': q, 'joint_names': m['joint_names'], 'eligible': not reasons or bool(m.get('quality_override')), 'exclusion_reasons': [] if m.get('quality_override') else reasons, 'capture_quality_reasons': reasons, 'quality_override': m.get('quality_override'), 'capture_manifest': (destination / 'capture_manifest.yaml').relative_to(project.root).as_posix()}
            if image.get('runtime_baseline'):
                observation['runtime_baseline'] = copy.deepcopy(image['runtime_baseline'])
                observation['runtime_baseline']['path'] = (destination / image['runtime_baseline']['path']).relative_to(project.root).as_posix()
            if sample.get('metadata_path'):
                observation['snapshot_metadata'] = (destination / sample['metadata_path']).relative_to(project.root).as_posix()
            evidence['images'].append(observation)
            observed.append(observation)
    source = {'id': m['session_id'], 'path': (destination / 'capture_manifest.yaml').relative_to(project.root).as_posix(), 'sha256': sha(destination / 'capture_manifest.yaml')}
    if m['purpose'] == 'snapshot':
        source.update(schema=m['schema'], dataset_id=m['source_dataset_id'], scene_state_id=m['scene_state_id'], snapshot_ids=[s['id'] for s in samples])
        paths = set(m['files'])
        for sample in samples:
            metadata_path = sample['metadata_path']
            paths.add(metadata_path)
            folder = Path(metadata_path).parent
            for path in read(destination / metadata_path)['files']:
                paths.add((folder / path).as_posix())
        source['input_files'] = [{'path': (destination / p).relative_to(project.root).as_posix(), 'sha256': sha(destination / p)} for p in sorted(paths)]
    if m.get('quality_override'):
        source['quality_override'] = m['quality_override']
    if m.get('calibration_reconciliation'):
        source['calibration_reconciliation'] = m['calibration_reconciliation']
    evidence.setdefault('capture_sessions', []).append(source)
    write(project.root / 'input/evidence.yaml', evidence)
    project.invalidate()
    report = {'imported': len(observed), 'eligible': sum((o['eligible'] for o in observed)), 'excluded': [{'id': o['id'], 'reasons': o['exclusion_reasons']} for o in observed if not o['eligible']], 'physics_status': 'PHYSICS_NOT_VALIDATED', 'scope': 'KINEMATIC_REPLAY_ONLY'}
    write(project.root / 'working/capture_import.json', report)
    return report

def observation_scene(scene, image, root, complete=True):
    if not image.get('session_id'):
        return scene
    if not image.get('eligible') or image.get('q_measured') is None:
        raise ValueError('Observation excluded: ' + str(image.get('exclusion_reasons')))
    result = copy.deepcopy(scene)
    model = result['robot_model']
    if image['joint_names'] != model['joint_names']:
        raise ValueError('Observation joint order differs')
    from real2sim_builder.calibration.geometry import link_transforms, simulation_offsets
    offsets = simulation_offsets(model)
    if model.get('mapping', {}).get('schema') == 'so101.precision-joint-mapping/1' and np.any(abs(offsets) > 1e-12) and (not model['simulation_joint_offsets_rad'].get('precision_mapping_sha256')):
        raise ValueError('Precision URDF observations cannot also apply historical simulation joint offsets')
    reference = model.get('simulation_joint_offsets_rad', {}).get('precision_mapping_sha256')
    if reference and image.get('capture_manifest'):
        recorded = read(local_path(root, image['capture_manifest']))['joint_mapping']
        if recorded.get('sha256') != reference:
            raise ValueError('Simulation residual differs from capture Precision mapping')
    q_model = np.asarray(image['q_measured']) + offsets
    fk = link_transforms(local_path(root, model['path']), dict(zip(image['joint_names'], q_model)))
    for link, pose in fk.items():
        result['frames']['robot_link_' + link] = {'parent': 'robot_base', 'transform': value(pose.tolist(), 'derived', ['measured joint FK'])}
    for obj in result['objects']:
        if obj.get('link'):
            if 'link_local_pose' not in obj:
                raise ValueError('Missing reference geometry link-local transform')
            obj['frame'] = 'robot_base'
            obj['pose'] = value((fk[obj['link']] @ np.asarray(obj['link_local_pose'])).tolist(), 'derived', ['measured joint FK'])
    validate(result, root, complete=complete)
    return result

def import_session(project, root, max_skew_ns=100000000, loaded=None):
    project.require_writable()
    'Restore project metadata on failed import; never alter immutable source input.'
    m, _, _ = loaded or load_session(root)
    destination = project.root / 'input/captures' / m['session_id']
    if destination.exists():
        raise ValueError('Capture session already imported')
    paths = [project.root / p for p in ('working/current_scene.yaml', 'input/evidence.yaml', 'working/state.json')]
    paths.append(project.root / 'history.jsonl')
    previous = {p: p.read_bytes() if p.exists() else None for p in paths}
    try:
        return _import_session(project, root, max_skew_ns, loaded)
    except Exception:
        for p, data in previous.items():
            if data is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(data)
        if destination.exists():
            shutil.rmtree(destination)
        raise

def validate_joint_units(path, names, units):
    if Path(path).suffix.lower() == '.urdf':
        import xml.etree.ElementTree as ET
        kinds = {j.get('name'): 'm' if j.get('type') == 'prismatic' else 'rad' for j in ET.parse(path).findall('joint') if j.get('type') != 'fixed'}
    else:
        import mujoco
        model = mujoco.MjModel.from_xml_path(str(path))
        kinds = {mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i): 'm' if model.jnt_type[i] == mujoco.mjtJoint.mjJNT_SLIDE else 'rad' for i in range(model.njnt)}
    if dict(zip(names, units)) != kinds:
        raise ValueError('Measured joint names/units do not match kinematic model')

def validate_model_files(root, manifest):
    """Every file the model can load must stay within the hashed dataset."""
    import xml.etree.ElementTree as ET
    root = Path(root).resolve()
    visited = set()

    def inspect(path, meshdir='', texturedir=''):
        path = Path(path).resolve()
        if not path.is_relative_to(root) or path.relative_to(root).as_posix() not in manifest['files']:
            raise ValueError('Unhashed or external robot dependency')
        if path in visited:
            return
        visited.add(path)
        tree = ET.parse(path)
        compiler = tree.find('compiler')
        if compiler is not None:
            meshdir = compiler.get('meshdir', compiler.get('assetdir', meshdir))
            texturedir = compiler.get('texturedir', compiler.get('assetdir', texturedir))
        for node in tree.iter():
            name = node.get('filename') or node.get('file')
            if not name:
                continue
            if Path(name).is_absolute() or '://' in name:
                raise ValueError('Absolute/URI robot dependencies are not portable')
            prefix = meshdir if node.tag == 'mesh' else texturedir if node.tag == 'texture' else ''
            dependency = (path.parent / prefix / name).resolve()
            if not dependency.is_relative_to(root) or dependency.relative_to(root).as_posix() not in manifest['files']:
                raise ValueError('Unhashed or external robot dependency')
            if node.tag == 'include':
                inspect(dependency, meshdir, texturedir)
    inspect(root / manifest['robot']['path'])

def legacy_static_reasons(manifest, events, timestamp):
    """Old continuous captures only; snapshots never require grasp/event annotations."""
    active = [e for e in events if e['timestamp_ns'] <= timestamp]
    moving = False
    reasons = []
    for event in active:
        if event['event'] in ('grasp', 'lift', 'place', 'release', 'object_moved'):
            moving = True
        if event['event'] == 'scene_reset':
            moving = False
    if moving:
        reasons.append('object_moved_without_tracked_object_state')
    if manifest['purpose'] == 'demonstration' and (not any((e['event'] in ('static_hold', 'pre_grasp') for e in active))):
        reasons.append('no_explicit_static_or_pregrasp_interval')
    return reasons

def load_snapshots(root, validation=(), scene_state=None):
    """Read a committed dataset prefix. Its common assets and each snapshot are hashed."""
    root = Path(root).resolve()
    manifest = read(root / 'capture_manifest.yaml')
    if manifest.get('schema') != 'real2sim.snapshot/1' or not (root / 'COMPLETE').is_file():
        raise ValueError('Incomplete snapshot dataset')
    identifier(manifest['dataset_id'])
    if manifest['clock']['domain'] != 'host_monotonic_ns':
        raise ValueError('Explicit host monotonic timestamps required')
    names = manifest['joint_names']
    if len(set(names)) != len(names) or len(manifest['joint_units']) != len(names) or any((u not in ('rad', 'm') for u in manifest['joint_units'])):
        raise ValueError('Invalid measured joint units/order')
    if manifest['q_measured_source'] != 'physical_follower_feedback_converted_to_model':
        raise ValueError('Snapshot must contain actual measured feedback')
    for path, digest in manifest['files'].items():
        if sha(local_path(root, path)) != digest:
            raise ValueError('Snapshot common file hash mismatch: ' + path)
    validate_model_files(root, manifest)
    validate_joint_units(root / manifest['robot']['path'], names, manifest['joint_units'])
    mapping_contract(manifest)
    states = {row['scene_state_id'] for row in manifest['snapshots']}
    if not states:
        raise ValueError('Snapshot dataset has no committed observations')
    if scene_state is None:
        if len(states) != 1:
            raise ValueError('Choose --scene-state; different object layouts cannot share one static scene')
        scene_state = next(iter(states))
    identifier(scene_state)
    ids = [row['id'] for row in manifest['snapshots']]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate snapshot IDs')
    selected = [row for row in manifest['snapshots'] if row['scene_state_id'] == scene_state]
    if not selected:
        raise ValueError('No snapshots in selected scene state')
    validation = set(validation)
    if validation - {r['id'] for r in selected}:
        raise ValueError('Unknown validation snapshot IDs')
    samples = []
    for row in selected:
        identifier(row['id'])
        folder = local_path(root, row['path'])
        metadata = read(folder / 'metadata.json')
        if not (folder / 'COMPLETE').is_file() or sha(folder / 'metadata.json') != row['metadata_sha256']:
            raise ValueError('Incomplete or changed snapshot metadata')
        if metadata['id'] != row['id'] or metadata['scene_state_id'] != scene_state:
            raise ValueError('Snapshot identity/state mismatch')
        for path, digest in metadata['files'].items():
            if sha(local_path(folder, path)) != digest:
                raise ValueError('Snapshot file hash mismatch: ' + path)
        if 'state.json' not in metadata['files']:
            raise ValueError('Unhashed measured state')
        state = read(folder / 'state.json')
        history = state['measured_samples']
        previous = -1
        for measured in history:
            q = np.asarray(measured['q_measured'], float)
            if q.shape != (len(names),) or not np.isfinite(q).all() or measured['timestamp_ns'] <= previous:
                raise ValueError('Invalid measured history')
            previous = measured['timestamp_ns']
        if not history:
            raise ValueError('Missing measured history')
        if not np.allclose(state['q_measured'], align(history, state['timestamp_ns'], names, manifest.get('discrete_joints', []))):
            raise ValueError('Snapshot feedback/history mismatch')
        if {i['camera'] for i in metadata['images']} != {c['id'] for c in manifest['cameras']}:
            raise ValueError('Missing snapshot camera stream')
        images = []
        for image in metadata['images']:
            image = copy.deepcopy(image)
            if image['path'] not in metadata['files']:
                raise ValueError('Unhashed snapshot image')
            camera = next((c for c in manifest['cameras'] if c['id'] == image['camera']))
            from PIL import Image
            with Image.open(local_path(folder, image['path'])) as rgb:
                if list(rgb.size) != image['resolution'] or image['resolution'] != camera['resolution']:
                    raise ValueError('Snapshot image/calibration resolution mismatch')
            stamp = int(image['timestamp_ns'])
            if image['read_start_ns'] > stamp or abs(stamp - state['timestamp_ns']) > 100000000:
                raise ValueError('Snapshot camera timestamp skew exceeds limit')
            stability = state.get('real_stability', {})
            if not stability.get('stable') or image['read_start_ns'] < stability['window_start_ns'] or stamp > stability['window_end_ns']:
                raise ValueError('Snapshot not covered by stable measured feedback')
            q = align(history, image['timestamp_ns'], names, manifest.get('discrete_joints', []))
            if not np.allclose(q, image['q_measured'], atol=1e-08):
                raise ValueError('Camera-aligned measured q changed')
            image['path'] = (folder / image['path']).relative_to(root).as_posix()
            image['sequence'] = row['id']
            if 'pair.json' in metadata['files']:
                pair = read(folder / 'pair.json')
                if pair.get('schema') != 'real2sim.paired-observation/1' or pair.get('meaning') != 'historical_runtime_baseline_not_ground_truth':
                    raise ValueError('Invalid paired observation')
                baseline = pair['sim_images'][image['camera']]
                if baseline not in metadata['files']:
                    raise ValueError('Unhashed runtime baseline')
                with Image.open(local_path(folder, baseline)) as rgb:
                    if list(rgb.size) != image['resolution']:
                        raise ValueError('Runtime baseline resolution mismatch')
                image['runtime_baseline'] = {'path': (folder / baseline).relative_to(root).as_posix(), 'sha256': metadata['files'][baseline], 'engine': pair['engine'], 'workspace_context': pair['workspace_context'], 'quality': pair['quality'], 'sim_q_measured_rad': pair['sim_q_measured_rad'], 'sim_timestamp': pair['sim_timestamp'], 'sim_cameras': pair['sim_cameras'], 'joint_mapping': pair.get('joint_mapping'), 'runtime_profile': pair.get('runtime_profile'), 'pair_path': (folder / 'pair.json').relative_to(root).as_posix(), 'pair_sha256': metadata['files']['pair.json']}
            images.append(image)
        samples.append({'id': row['id'], 'timestamp_ns': state['timestamp_ns'], 'q_measured': state['q_measured'], 'measured_history': history, 'quality': {'eligible_for_calibration': all((i.get('runtime_baseline', {}).get('quality', {}).get('eligible', True) for i in images))}, 'images': images, 'metadata_path': (folder / 'metadata.json').relative_to(root).as_posix(), 'split': 'validation' if row['id'] in validation else 'train', 'group_id': manifest['dataset_id'] + '_' + row['id']})
    normalized = {**manifest, 'source_dataset_id': manifest['dataset_id'], 'session_id': manifest['dataset_id'] + '_' + sha(root / 'capture_manifest.yaml')[:12], 'group_id': manifest['dataset_id'], 'scene_state_id': scene_state, 'purpose': 'snapshot', 'split': 'train'}
    return (normalized, samples, [])

def import_snapshots(project, root, validation=(), scene_state=None, paired=False, reconciliation=None, include_flagged_reason=None):
    project.require_writable()
    import fcntl
    root = Path(root).resolve()
    lock = root / '.capture.lock'
    from contextlib import nullcontext
    with lock.open('r') if lock.exists() else nullcontext(None) as stream:
        if stream is not None:
            fcntl.flock(stream, fcntl.LOCK_SH)
        m, samples, events = load_snapshots(root, validation, scene_state)
        if paired:
            m['paired_evidence'] = True
        if include_flagged_reason:
            if not paired:
                raise ValueError('Flag override is only for explicit paired evidence review')
            m['quality_override'] = str(include_flagged_reason)
        if reconciliation:
            m['calibration_reconciliation'] = str(reconciliation)
        existing = project.evidence['images']
        new = []
        for sample in samples:
            prefix = m['source_dataset_id'] + '_' + sample['id'] + '_'
            previous = [i for i in existing if i.get('id', '').startswith(prefix)]
            if previous:
                if any((i['split'] != sample['split'] for i in previous)):
                    raise ValueError('Cannot reassign imported snapshot split; use a new project before fitting')
                continue
            new.append(sample)
        if not new:
            raise ValueError('No new snapshots to import')
        representatives = [(np.asarray(i['q_measured']), i['group_id'], i['split']) for i in existing if i.get('eligible') and i.get('q_measured')]
        for sample in new:
            q = np.asarray(sample['q_measured'])
            for pose, group, split in representatives:
                if pose.shape == q.shape and np.max(np.abs(pose - q)) < 0.01:
                    if split != sample['split']:
                        raise ValueError('Train/validation contains the same or near-identical measured pose')
                    sample['group_id'] = group
            representatives.append((q, sample['group_id'], sample['split']))
        return import_session(project, root, loaded=(m, new, events))

def import_paired(project, root, validation=(), scene_state=None, reconciliation=None, include_flagged_reason=None):
    project.require_writable()
    'Reuse Snapshot ingestion; runtime RGB is diagnostic evidence, never truth.'
    if not project.scene.get('robot_model'):
        raise ValueError('Import paired evidence into the existing reconstructed project')
    _, samples, _ = load_snapshots(root, validation, scene_state)
    if not all((i.get('runtime_baseline') for s in samples for i in s['images'])):
        raise ValueError('Selected observations must all contain paired runtime baselines')
    return import_snapshots(project, root, validation, scene_state, paired=True, reconciliation=reconciliation, include_flagged_reason=include_flagged_reason)
'One optical-to-render frame conversion shared by all scene exporters.'
import numpy as np
OPTICAL_TO_RENDER = np.diag([1.0, -1.0, -1.0, 1.0])
CLIP = (0.001, 1000.0)
CONVENTIONS = {'canonical': '+X right, +Y down, +Z forward', 'render': '+X right, +Y up, -Z forward', 'conversion': OPTICAL_TO_RENDER.tolist(), 'clip_m': list(CLIP)}

def render_pose(scene, camera):
    return world_pose(scene, camera) @ OPTICAL_TO_RENDER

def blender_intrinsics(camera):
    k = np.asarray(camera['K']['value'], float)
    w, h = camera['resolution']
    ratio = k[0, 0] / k[1, 1]
    return {'sensor_fit': 'HORIZONTAL', 'sensor_width': 36.0, 'lens': float(k[0, 0] * 36 / w), 'shift_x': float((w / 2 - k[0, 2]) / w), 'shift_y': float((k[1, 2] - h / 2) * ratio / w), 'pixel_aspect_x': 1.0, 'pixel_aspect_y': float(ratio)}
'Isolated proposals, immutable asset promotion, and one-step transactional rollback.'
import copy
from contextlib import contextmanager
import os
from pathlib import Path
import shutil

@contextmanager
def exclusive(project):
    project.require_writable()
    lock = project.root / 'working/run.lock'
    try:
        with lock.open('x') as stream:
            stream.write(str(os.getpid()))
    except FileExistsError:
        raise RuntimeError('Project is busy; stop the active worker before editing')
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)

class Candidate:

    def __init__(self, project, name):
        identifier(name)
        self.project = project
        self.name = name
        self.root = project.root / 'scratch/agent' / name
        if not (self.root / 'candidate.json').is_file():
            raise ValueError('Unknown candidate: ' + name)

    @classmethod
    def create(cls, project, name, target_object=None, allow=None):
        identifier(name)
        with exclusive(project):
            root = project.root / 'scratch/agent' / name
            scene = project.scene if (project.root / 'working/current_scene.yaml').exists() else empty(project.info['name'])
            scope = None
            if target_object is not None:
                if target_object not in {o['id'] for o in scene['objects']}:
                    raise ValueError('Unknown target object')
                fields = allow or ['pose']
                if not set(fields) <= {'pose', 'dimensions', 'visual', 'collision', 'color', 'material', 'physics'}:
                    raise ValueError('Invalid allowed object fields')
                scope = {'target_object': target_object, 'allow': fields}
            root.mkdir(parents=True, exist_ok=False)
            write(root / 'candidate_scene.yaml', scene)
            write(root / 'candidate.json', {'scope': scope, 'base_scene_sha256': sha(root / 'candidate_scene.yaml'), 'id': name, 'status': 'OPEN', 'base_signature': project.signature(scene), 'base_exists': (project.root / 'working/current_scene.yaml').exists()})
        return cls(project, name)

    @property
    def scene(self):
        return read(self.root / 'candidate_scene.yaml')

    @property
    def info(self):
        return read(self.root / 'candidate.json')

    def require_open(self):
        if self.info['status'] != 'OPEN':
            raise ValueError('Candidate is not open')

    def save(self, scene):
        self.project.require_writable()
        self.require_open()
        validate(scene, self.project.root)
        self.check_scope(scene)
        preserve(self.scene, scene)
        write(self.root / 'candidate_scene.yaml', scene)

    def check_scope(self, scene):
        if not self.info.get('scope'):
            return
        check_scope(self.project.scene, scene, self.info.get('scope'))

    def edit(self, operations):
        with exclusive(self.project):
            self.save(apply(self.scene, operations, self.project.root))
        return {'candidate': self.name, 'scene': str(self.root / 'candidate_scene.yaml')}

    def asset(self, path, kind='visual'):
        if kind not in ('visual', 'collision', 'textures'):
            raise ValueError('Unknown asset category')
        with exclusive(self.project):
            self.require_open()
            path = Path(path).resolve()
            digest = sha(path)
            dest = self.root / 'assets' / kind / (digest + path.suffix.lower())
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest != path:
                shutil.copy2(path, dest)
            scene = self.scene
            key = 'asset_' + digest[:16]
            scene['assets'][key] = {'path': dest.relative_to(self.project.root).as_posix(), 'sha256': digest, 'source': 'candidate imported asset', 'category': kind}
            self.save(scene)
        return {'asset': key, 'path': str(dest)}

    def evaluate(self, engine='blender', renderer='software-egl', validation=False, render_only=False):
        from real2sim_builder.rendering import Renderer
        from real2sim_builder.rendering import BlenderRenderer
        from real2sim_builder.validation import compare
        from real2sim_builder.reconstruction import validate_scene
        from PIL import Image, ImageOps
        import numpy as np
        with exclusive(self.project):
            self.require_open()
            scene = self.scene
            self.check_scope(scene)
            validate(scene, self.project.root, complete=engine != 'blender')
            validation = validation or ((bool(self.project.evidence.get('capture_sessions')) or bool(self.info.get('scope'))) and (not render_only))
            folder = self.root / 'renders' / engine
            factory = BlenderRenderer if engine == 'blender' else Renderer
            model = factory(scene, self.project.root, folder, renderer)
            blend = self.root / 'candidate.blend'
            if engine == 'blender' and blend.exists():
                build_signature = read(self.root / 'blender/canonical_signature.json')
                if build_signature != self.project.signature(scene):
                    raise ValueError('Blender workspace is stale; rebuild or sync explicitly')
                authored = read(self.root / 'blender/authored.json') if (self.root / 'blender/authored.json').exists() else {}
                sync = read(self.root / 'blender/sync.json') if (self.root / 'blender/sync.json').exists() else {}
                if authored.get('action') != 'build' or authored.get('blend_sha256') != sha(blend):
                    if sync.get('blend_sha256') != sha(blend) or sync.get('input_signature') != self.project.signature(scene):
                        raise ValueError('Explicit Blender synchronization required before evaluation; canonical is metric authority')
                model.blend = blend
            with model:
                if validation:
                    report, _ = validate_scene(self.project, scene, model, folder, {'mae': 0.12, 'reprojection_px': 5.0, 'silhouette_iou': 0.8})
                else:
                    rows = []
                    for index, obs in enumerate(self.project.evidence['images']):
                        if obs['split'] != 'train' or obs.get('eligible') is False:
                            continue
                        camera = next((c for c in scene['cameras'] if c['id'] == obs['camera']))
                        if camera['resolution'] != obs['resolution']:
                            raise ValueError('Camera/evidence resolution mismatch')
                        target = folder / 'previews' / f"{index:03d}_{obs['camera']}"
                        target.mkdir(parents=True, exist_ok=True)
                        from real2sim_builder.rendering import for_observation
                        with for_observation(self.project, scene, obs, model, folder / 'posed' / str(index)) as posed:
                            sim = posed.rgb(obs['camera'])
                        Image.fromarray(sim).save(target / (engine + '.png'))
                        metrics = {}
                        if not render_only:
                            real = np.asarray(ImageOps.exif_transpose(Image.open(local_path(self.project.root, obs['path']))).convert('RGB'))
                            metrics = compare(real, sim, target)
                            from real2sim_builder.validation import paired_diagnostics
                            paired = paired_diagnostics(self.project, obs, real, sim, target / 'paired')
                            if paired:
                                metrics['paired_diagnostics'] = paired
                        rows.append({'image': obs['path'], 'camera': obs['camera'], **metrics})
                    report = {'images': rows, 'scope': 'train render only' if render_only else 'train comparison', 'train_mae': float(np.mean([r['mae'] for r in rows])) if rows and (not render_only) else None, 'passed': False, 'needs': ['Independent held-out validation is required for acceptance']}
                report.update(engine=engine, input_signature=self.project.signature(scene))
                if engine == 'blender' and blend.exists():
                    report['blend_sha256'] = sha(blend)
            if validation and (self.project.evidence.get('capture_sessions') or self.info.get('scope')):
                baseline_folder = self.root / 'baseline' / engine
                with factory(self.project.scene, self.project.root, baseline_folder, renderer) as baseline_model:
                    baseline, _ = validate_scene(self.project, self.project.scene, baseline_model, baseline_folder, {'mae': 0.12, 'reprojection_px': 5.0, 'silhouette_iou': 0.8})
                report['baseline'] = baseline
                report['nonregression'] = nonregression(baseline, report, self.info.get('scope'))
            write(folder / 'metrics.json', report)
            write(self.root / 'metrics.json', report)
            if validation:
                import json
                with (self.project.root / 'working/calibration_holdout_usage.jsonl').open('a') as stream:
                    stream.write(json.dumps({'candidate': self.name, 'target': 'render_evaluation', 'holdout_observations': [r['observation'] for r in report.get('images', []) if r.get('observation') and r['split'] == 'validation']}) + '\n')
        return report

    def fit(self, target, options=None):
        from real2sim_builder.calibration.geometry import fit
        with exclusive(self.project):
            self.require_open()
            scene, report = fit(self.project, self.scene, target, options)
            if report['status'] == 'IMPROVED':
                self.save(scene)
            write(self.root / 'fit.json', report)
            if report.get('holdout_after'):
                import json
                images = {i.get('id'): i for i in self.project.evidence['images'] if i.get('id')}
                ids = report.get('holdout_observations') or sorted({r['observation'] for r in self.project.evidence['landmarks'] if r.get('observation') in images and images[r['observation']]['split'] == 'validation'})
                with (self.project.root / 'working/calibration_holdout_usage.jsonl').open('a') as stream:
                    stream.write(json.dumps({'candidate': self.name, 'target': target, 'holdout_observations': ids, 'status': report['status']}) + '\n')
        return report

    def reject(self):
        with exclusive(self.project):
            self.require_open()
            info = self.info
            info['status'] = 'REJECTED'
            write(self.root / 'candidate.json', info)
        return info

    def promote(self):
        with exclusive(self.project):
            self.require_open()
            p = self.project
            info = self.info
            scene = self.scene
            self.check_scope(scene)
            current = p.scene if (p.root / 'working/current_scene.yaml').exists() else empty(p.info['name'])
            preserve(current, scene)
            if p.signature(current) != info['base_signature']:
                raise ValueError('Candidate base is stale; create a new candidate')
            report = read(self.root / 'metrics.json')
            if report.get('input_signature') != p.signature(scene):
                raise ValueError('Candidate evaluation is stale')
            if (self.root / 'candidate.blend').exists():
                sync = read(self.root / 'blender/sync.json') if (self.root / 'blender/sync.json').exists() else {}
                if sync.get('blend_sha256') != sha(self.root / 'candidate.blend') or sync.get('input_signature') != p.signature(scene):
                    raise ValueError('Explicit Blender synchronization required before promotion')
            if report.get('scope') == 'train render only' or not report.get('images'):
                raise ValueError('Evaluate the candidate before promotion')
            if (p.evidence.get('capture_sessions') or info.get('scope')) and (not report.get('nonregression', {}).get('passed')):
                raise ValueError('Multi-pose promotion requires improved train metrics and non-regressing independent holdout: ' + str(report.get('nonregression')))
            validate(scene, p.root, complete=True)
            promoted = copy.deepcopy(scene)
            for asset in promoted['assets'].values():
                source = local_path(p.root, asset['path'])
                if source.is_relative_to(self.root):
                    category = asset.get('category', 'textures' if source.suffix.lower() in ('.png', '.jpg', '.jpeg') else 'visual')
                    target = p.root / 'working/assets' / category / (sha(source) + source.suffix.lower())
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if not target.exists():
                        shutil.copy2(source, target)
                    asset['path'] = target.relative_to(p.root).as_posix()
                    asset['sha256'] = sha(target)
            validate(promoted, p.root, complete=True)
            rollback = p.root / 'scratch/agent/rollback.json'
            current_blend = p.root / 'working/blender/current.blend'
            previous_blend = p.root / 'scratch/agent/rollback.blend'
            previous_blend.unlink(missing_ok=True)
            if current_blend.exists():
                shutil.copy2(current_blend, previous_blend)
            write(rollback, {'scene': current, 'existed': info['base_exists'], 'state': p.state, 'promoted_signature': p.signature(promoted), 'had_blend': current_blend.exists(), 'report': read(p.root / 'working/validation/report.json') if (p.root / 'working/validation/report.json').exists() else None})
            previous = p.state
            try:
                p.save_scene(promoted)
                write(p.root / 'working/validation/report.json', {**report, 'passed': False, 'input_signature': p.signature(promoted), 'needs': ['Final cross-engine validation required after promotion'], 'validation_scope': 'VISUAL_ONLY'})
                p.update(status='DRAFT', stage=None, decision='CONTINUE', export=None, task='Candidate promoted; final cross-engine validation required', candidate=self.name)
                info['status'] = 'PROMOTED'
                write(self.root / 'candidate.json', info)
                blend = self.root / 'candidate.blend'
                if not blend.exists():
                    current_blend.unlink(missing_ok=True)
                if blend.exists():
                    target = p.root / 'working/blender/current.blend'
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(blend, target)
            except Exception:
                if info['base_exists']:
                    write(p.root / 'working/current_scene.yaml', current)
                else:
                    (p.root / 'working/current_scene.yaml').unlink(missing_ok=True)
                write(p.root / 'working/state.json', previous)
                restore_report(p, read(rollback).get('report'))
                if previous_blend.exists():
                    shutil.copy2(previous_blend, current_blend)
                else:
                    current_blend.unlink(missing_ok=True)
                info['status'] = 'OPEN'
                write(self.root / 'candidate.json', info)
                raise
        return {'candidate': self.name, 'status': 'PROMOTED', 'acceptance': 'not yet validated'}

def rollback(project):
    project.require_writable()
    with exclusive(project):
        path = project.root / 'scratch/agent/rollback.json'
        record = read(path)
        if project.signature() != record['promoted_signature']:
            raise ValueError('Current scene changed after promotion; refusing rollback')
        if record['existed']:
            write(project.root / 'working/current_scene.yaml', record['scene'])
        else:
            (project.root / 'working/current_scene.yaml').unlink(missing_ok=True)
        blend = project.root / 'working/blender/current.blend'
        if record.get('had_blend'):
            blend.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project.root / 'scratch/agent/rollback.blend', blend)
        else:
            blend.unlink(missing_ok=True)
        restore_report(project, record.get('report'))
        project.update(**{k: v for k, v in record['state'].items() if k not in ('updated_at', 'task')}, task='Candidate promotion rolled back')
        path.unlink()
    return {'status': 'ROLLED_BACK'}

def restore_report(project, report):
    project.require_writable()
    path = project.root / 'working/validation/report.json'
    if report is None:
        path.unlink(missing_ok=True)
    else:
        write(path, report)

def nonregression(baseline, candidate, scope=None):
    """Photometry and geometry must not trade away held-out evidence."""
    failures = []
    improved = False
    for split in ('train', 'validation'):
        old = baseline.get('multipose', {}).get(split, {})
        new = candidate.get('multipose', {}).get(split, {})
        if not new.get('count') or new.get('count') != old.get('count'):
            failures.append(split + ' requires the same independent pose correspondences')
            continue
        if new['behind_camera'] > old['behind_camera']:
            failures.append(split + ' points behind camera')
        if split == 'train':
            improved |= new['rmse_px'] < old['rmse_px'] - 1e-06
            if new['rmse_px'] > old['rmse_px'] + 1e-06:
                failures.append('train reprojection regressed')
        elif new['rmse_px'] > old['rmse_px'] + 1e-06:
            failures.append('holdout reprojection regressed')
    old_rows = {r['image']: r for r in baseline['images']}
    if set(old_rows) != {r['image'] for r in candidate['images']}:
        failures.append('Evidence observations missing or added')
    for row in candidate['images']:
        old = old_rows.get(row['image'])
        if old is None:
            failures.append('Evidence changed')
            continue
        old_objects = {o['object']: o for o in old.get('objects', [])}
        if set(old_objects) != {o['object'] for o in row.get('objects', [])}:
            failures.append('Object evaluation coverage changed')
        for obj in row.get('objects', []):
            previous = old_objects.get(obj['object'], {})
            for key in ('landmark_rmse_px', 'boundary_chamfer_px', 'center_error_px'):
                a = previous.get(key)
                b = obj.get(key)
                if a is not None and (b is None or ((row['split'] == 'validation' or (scope and obj['object'] != scope['target_object'])) and b > a + 1e-06)):
                    failures.append('Object geometry regressed or evidence lost: ' + obj['object'] + ' ' + key)
                if row['split'] == 'train' and a is not None and (b is not None):
                    improved |= b < a - 1e-06
            if (row['split'] == 'validation' or (scope and obj['object'] != scope['target_object'])) and previous.get('iou') is not None and (obj.get('iou') is None or obj['iou'] < previous['iou'] - 1e-06):
                failures.append('Object IoU regressed: ' + obj['object'])
        if row['split'] == 'train':
            improved |= row['mae'] < old['mae'] - 1e-06
            continue
        if row['mae'] > old['mae'] + 1e-06:
            failures.append('holdout MAE regressed: ' + row['image'])
        old_masks = {r['object']: r for r in old['silhouettes']}
        for mask in row['silhouettes']:
            previous = old_masks[mask['object']]
            if mask['iou'] < previous['iou'] - 1e-06:
                failures.append('holdout silhouette regressed: ' + mask['object'])
            if previous['center_error_px'] is not None and (mask['center_error_px'] is None or mask['center_error_px'] > previous['center_error_px'] + 1e-06):
                failures.append('holdout center error regressed')
    if scope and set(scope['allow']) & {'pose', 'dimensions', 'visual', 'collision'}:
        geometric_gain = any((o.get(k) is not None and n.get(k) is not None and (n[k] < o[k] - 1e-06) for row in candidate['images'] if row['split'] == 'train' for n in row.get('objects', []) if n['object'] == scope['target_object'] for o in old_rows.get(row['image'], {}).get('objects', []) if o['object'] == n['object'] for k in ('landmark_rmse_px', 'boundary_chamfer_px', 'center_error_px')))
        if not geometric_gain:
            failures.append('Scoped geometry requires object evidence improvement; global MAE alone is insufficient')
    if not improved:
        failures.append('No train improvement')
    return {'passed': not failures, 'failures': failures, 'policy': 'train improvement and independent holdout nonregression; not final acceptance'}


def clone_project(source, destination):
    """Copy an existing authoring project to a new owned workspace, never edit it."""
    original=Project(source,read_only=True)
    if (original.root/'working/run.lock').exists():
        raise RuntimeError('Source project has an active or unresolved owner; cannot freeze a clone')
    destination=Path(destination).resolve()
    if destination.is_relative_to(original.root) or original.root.is_relative_to(destination):
        raise ValueError('Project clone requires a separate output directory')
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name('.'+destination.name+'.building-'+uuid.uuid4().hex)
    try:
        shutil.copytree(original.root,temporary,symlinks=False)
        write(temporary/'working/owner.json',{'schema':'real2sim.builder-owner/1','project_id':original.info['id']})
        # Working ownership locks are not copied as live process claims.
        (temporary/'working/run.lock').unlink(missing_ok=True)
        (temporary/'working/control.json').unlink(missing_ok=True)
        if (temporary/'working/current_scene.yaml').is_file():
            validate(read(temporary/'working/current_scene.yaml'),temporary)
        os.rename(temporary,destination)
        return Project(destination)
    finally:
        if temporary.exists():shutil.rmtree(temporary)


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
