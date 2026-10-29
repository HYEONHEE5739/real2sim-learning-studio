"""Existing Builder capture responsibilities; authoring schemas unchanged."""
from .evidence import PROVENANCE, import_robot
from pathlib import Path
import copy
from .scene import empty, identifier, local_path, validate, value
import numpy as np
from .files import read, sha, write
import shutil


CAPTURE_SCHEMA = 'real2sim.capture/1'


def register_unbound(project, destination, manifest, samples):
    """Archive measured input before a base/camera calibration exists.

    Registration is intentionally not robot import or calibration approval.
    """
    evidence=project.evidence;observed=[]
    for sample in samples:
        for image in sample['images']:
            relative=(destination/image['path']).relative_to(project.root).as_posix()
            row=dict(id=manifest['session_id']+'_'+sample['id']+'_'+image['camera'],path=relative,camera=image['camera'],
                     split=manifest['split'],group_id=manifest['group_id'],session_id=manifest['session_id'],
                     sha256=sha(project.root/relative),timestamp_ns=image['timestamp_ns'],resolution=image['resolution'],
                     joint_names=manifest['joint_names'],q_measured=sample['q_measured'],eligible=False,
                     exclusion_reasons=['unbound_capture_calibration'],capture_manifest=(destination/'capture_manifest.yaml').relative_to(project.root).as_posix())
            if image.get('runtime_baseline'):
                row['runtime_baseline']=copy.deepcopy(image['runtime_baseline'])
                for key in ('path','pair_path'):row['runtime_baseline'][key]=(destination/image['runtime_baseline'][key]).relative_to(project.root).as_posix()
            evidence['images'].append(row);observed.append(row)
    source=dict(id=manifest['session_id'],path=(destination/'capture_manifest.yaml').relative_to(project.root).as_posix(),sha256=sha(destination/'capture_manifest.yaml'),
        status='NEEDS_MORE_DATA',needs=['robot_base','camera_intrinsics','camera_extrinsics'],source_robot_sha256=manifest['source_robot_sha256'],schema=manifest['schema'],dataset_id=manifest.get('source_dataset_id'))
    paths=set(manifest['files'])
    for sample in samples:
        if sample.get('metadata_path'):
            metadata=sample['metadata_path'];paths.add(metadata)
            paths.update((Path(metadata).parent/p).as_posix()for p in read(destination/metadata)['files'])
    source['input_files']=[dict(path=(destination/p).relative_to(project.root).as_posix(),sha256=sha(destination/p))for p in sorted(paths)]
    evidence.setdefault('capture_sessions',[]).append(source)
    write(project.root/'input/evidence.yaml',evidence);project.invalidate()
    report=dict(imported=len(observed),eligible=0,status='NEEDS_MORE_DATA',scope='ARCHIVED_OBSERVATIONS_ONLY',physical_verified=False)
    write(project.root/'working/capture_import.json',report);return report


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
    in_place=root.resolve()==destination.resolve()
    if any(s['id']==m['session_id']for s in project.evidence.get('capture_sessions',[]))or(destination.exists()and not in_place):
        raise ValueError('Capture session already imported')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not in_place:shutil.copytree(root, destination)
    bound=all(m['robot'].get(k)is not None for k in('format','T_world_base'))and all(all(c.get(k)is not None for k in('parent','K','T_parent_camera'))for c in m['cameras'])
    if not bound:return register_unbound(project,destination,m,samples)
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
                observation['runtime_baseline']['pair_path'] = (destination / image['runtime_baseline']['pair_path']).relative_to(project.root).as_posix()
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
    in_place=root.resolve()==destination.resolve()
    if any(s['id']==m['session_id']for s in project.evidence.get('capture_sessions',[]))or(destination.exists()and not in_place):
        raise ValueError('Capture session already imported')
    paths = [project.root / p for p in ('working/current_scene.yaml', 'input/evidence.yaml', 'working/state.json')]
    paths.append(project.root / 'history.jsonl')
    paths.append(project.root / 'working/capture_import.json')
    previous = {p: p.read_bytes() if p.exists() else None for p in paths}
    try:
        return _import_session(project, root, max_skew_ns, loaded)
    except Exception:
        for p, data in previous.items():
            if data is None:
                p.unlink(missing_ok=True)
            else:
                p.write_bytes(data)
        if destination.exists()and not in_place:
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

