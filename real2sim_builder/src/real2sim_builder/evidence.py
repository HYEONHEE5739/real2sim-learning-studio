"""Existing Builder evidence responsibilities; authoring schemas unchanged."""
from PIL import Image, ImageOps
from pathlib import Path
import copy
from .scene import empty, identifier, local_path, validate, value
import numpy as np
from .files import read, sha, write
import shutil


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

