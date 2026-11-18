"""Existing Builder evidence responsibilities; authoring schemas unchanged."""
from PIL import Image, ImageOps
from pathlib import Path
import copy
from .scene import empty, identifier, local_path, validate, value
import numpy as np
from .files import read, sha, write
import shutil


PROVENANCE = {'user_measured': 'measured', 'model_asset': 'derived', 'derived': 'derived', 'numerically_fitted': 'optimized', 'provisional': 'estimated', 'unmeasured': 'unknown', 'measured': 'measured', 'calibrated': 'calibrated', 'optimized': 'optimized', 'estimated': 'estimated', 'unknown': 'unknown'}


def save_reconstruction_memo(project,text,source_scene):
    """A source-bound improvement request, separate from the original Scene Memo."""
    from .candidate import exclusive
    from .export import verify_package
    import hashlib
    if not isinstance(text,str):raise ValueError('Reconstruction Memo must be text')
    path=Path(source_scene).resolve()
    if path.is_file():path=path.parent
    if not path.is_relative_to(project.root):raise ValueError('Memo source must belong to the selected Project')
    package=verify_package(path)
    from dataclasses import asdict
    record={'text':text,'sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),
        'source_identity':asdict(package.identity),'source_package':path.relative_to(project.root).as_posix()}
    with exclusive(project):write(project.root/'working/reconstruction_memo.json',record)
    return record


def copy_input(project, path, category='media'):
    project.require_writable()
    path = Path(path).resolve()
    if path.suffix.lower() in ('.glb','.gltf'):
        raise ValueError('LEGACY_UNSUPPORTED: GLB/glTF inputs are retired; use measured primitives or OBJ/STL assets')
    if not path.is_file():
        raise FileNotFoundError(path)
    from scene_contract.naming import copy_named
    destination=copy_named(path,project.root/'input'/category)
    return destination.relative_to(project.root).as_posix()


def add_image(project, path, camera='side', split='train', timestamp=None, context_only=False, role='scene_photo'):
    project.require_writable()
    identifier(camera)
    if split not in ('train', 'validation'):
        raise ValueError('Unknown evidence split')
    if role not in('scene_photo','model_reference'):raise ValueError('Unknown input image role')
    relative = copy_input(project, path,'model_references'if role=='model_reference'else'scene_photos')
    with Image.open(project.root / relative) as im:
        im = ImageOps.exif_transpose(im)
        resolution = list(im.size)
    evidence = project.evidence
    row = {'path': relative, 'camera': camera, 'split': split, 'timestamp': timestamp, 'resolution': resolution, 'sha256': sha(project.root / relative), 'source': str(Path(path).resolve()),'original_name':Path(path).name,'role':role}
    if context_only:
        row.update(eligible=False, exclusion_reasons=['reference_camera_not_calibrated_for_pixel_fitting'])
    if not any((relative in (e['path'], e.get('original_path')) and e['camera'] == camera for e in evidence['images'])):
        evidence['images'].append(row)
    project.write_evidence(evidence)
    project.invalidate()
    return row


def register_observation_images(project, root):
    """One locked Evidence publication for an already sealed camera observation."""
    from .candidate import exclusive
    root=Path(root).resolve()
    if not root.is_relative_to((project.root/'input/observations').resolve()):
        raise ValueError('Observation images must be owned by this Project')
    document=root/'observation.json'
    record=read(document)
    if not(root/'COMPLETE').is_file():raise ValueError('Original observation is not sealed')
    digest=sha(document);relative=document.relative_to(project.root).as_posix()
    if read(root/'COMPLETE').get('observation_sha256')!=digest:raise ValueError('Sealed observation metadata changed')
    with exclusive(project):
        evidence=project.read_evidence(resolve=False)
        previous=next((r for r in evidence.get('documents',[])if r['path']==relative),None)
        if previous:
            if previous['sha256']!=digest:raise ValueError('Registered observation identity changed')
            return
        for name in('side','wrist'):
            source=root/(name+'.png')
            if sha(source)!=record['image_sha256'][name]:raise ValueError('Sealed observation image changed')
            with Image.open(source)as image:resolution=list(image.size)
            evidence['images'].append({'path':source.relative_to(project.root).as_posix(),'camera':name,'split':'train',
                'timestamp':record['camera_timing'][name]['read_end']['monotonic_ns'],'resolution':resolution,
                'sha256':record['image_sha256'][name],'source':str(source),'original_name':source.name,'role':'scene_photo',
                'eligible':False,'exclusion_reasons':['reference_camera_not_calibrated_for_pixel_fitting']})
        evidence.setdefault('documents',[]).append({'path':relative,'sha256':digest,'role':'unbound_sdk_camera_observation','status':'UNVERIFIED'})
        project.write_evidence(evidence)
        project.invalidate()


def add_video(project, path, camera='side', split='train', max_frames=12, *, role=None, scene_state=None):
    project.require_writable()
    import cv2
    identifier(camera)
    relative = copy_input(project, path)
    evidence = project.evidence
    video = {'path': relative, 'camera': camera, 'split': split, 'max_frames': int(max_frames), 'extracted': False}
    if role is not None:
        if role!='scene_video' or not scene_state:raise ValueError('Scene Video requires an explicit static layout')
        identifier(scene_state)
        video.update(role=role,scene_state_id=scene_state,sha256=sha(project.root/relative),original_name=Path(path).name)
    if split not in ('train', 'validation') or not 1 <= max_frames <= 1000:
        raise ValueError('Invalid video sampling')
    evidence['videos'].append(video)
    project.write_evidence(evidence)
    project.invalidate()


def extract_videos(project,paths=None):
    project.require_writable()
    import cv2
    evidence = project.evidence
    for video in evidence['videos']:
        if paths is not None and video['path']not in paths:continue
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
                added=add_image(project, path, video['camera'], video['split'], float(i / fps))
                current=project.evidence
                row=next(r for r in current['images']if r['path']==added['path']and r['camera']==video['camera'])
                row.update(source_video=video['path'],source_video_sha256=sha(local_path(project.root,video['path'])),video_frame_index=int(i))
                project.write_evidence(current)
            video['extracted'] = True
        finally:
            capture.release()
    current = project.evidence
    current['videos'] = evidence['videos']
    project.write_evidence(current)


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
    project.write_evidence(evidence)


def import_robot(project, urdf, joints=None, base=None, recorded_links=None):
    project.require_writable()
    from real2sim_builder.calibration.geometry import reference_geometry, reference_model
    scene = project.scene if (project.root / 'working/current_scene.yaml').exists() else empty(project.info['name'])
    scene['frames']['robot_base'] = {'parent': 'world', 'transform': value(base if base is not None else np.eye(4).tolist(), 'measured' if base is not None else 'estimated')}
    if Path(urdf).suffix.lower() == '.urdf':
        objects, poses = reference_geometry(urdf, joints or {}, asset_importer(project, scene), recorded_links=recorded_links)
    else:
        objects, poses = reference_model(urdf, joints or {}, asset_importer(project, scene), project.root / 'scratch/reference_model')
    from .export import copy_native_asset
    model=copy_native_asset(Path(urdf).resolve(),project.root/'input/robot')
    import xml.etree.ElementTree as ET
    xml=ET.parse(model).getroot()
    names=[j.get('name')for j in xml.findall('joint')if j.get('type')!='fixed']if model.suffix.lower()=='.urdf'else list(joints or {})
    previous=scene.get('robot_model',{})
    scene['robot_model']={'format':'urdf'if model.suffix.lower()=='.urdf'else'mjcf','path':model.relative_to(project.root).as_posix(),'model_sha256':sha(model),'joint_names':names,'mapping_verified':False}
    if previous.get('model_sha256')==sha(model):scene['robot_model'].update({k:v for k,v in previous.items()if k not in('path','simulation_joint_offsets_rad')})
    scene['objects'] = [o for o in scene['objects'] if o['role'] != 'reference_robot'] + objects
    for name, t in poses.items():
        scene['frames']['robot_link_' + name] = {'parent': 'robot_base', 'transform': value(t.tolist(), 'derived')}
    validate(scene, project.root)
    project.save_scene(scene)


def create_robot_rig(source_urdf, assembly_manifest_path, destination, *, mount_link,
                     T_link_mount, T_mount_optical, evidence):
    """Freeze a native URDF variant with one fixed accessory; preserve kinematics.

    Object Library remains the assembly owner. This portable variant snapshots
    that version and the original robot closure without changing their bytes.
    Neither an inferred mount nor its optical frame is a Calibration result.
    """
    import copy,os,shutil,xml.etree.ElementTree as ET
    from scipy.spatial.transform import Rotation
    from .scene import transform,local_path
    from .export import copy_native_asset,verify_native_closure
    from .calibration.geometry import link_transforms
    source=Path(source_urdf).resolve();manifest=Path(assembly_manifest_path).resolve();target=Path(destination).resolve()
    if source.suffix.lower()!='.urdf':raise ValueError('Rig source must be an explicit expanded URDF')
    if not isinstance(evidence,list)or not evidence or any(not isinstance(v,str)or not v.strip()for v in evidence):
        raise ValueError('Estimated mounting evidence required')
    mount=transform(T_link_mount);optical=transform(T_mount_optical)
    root=ET.parse(source).getroot();links={l.get('name')for l in root.findall('link')}
    if root.tag!='robot'or mount_link not in links:raise ValueError('Unknown existing Robot mounting link')
    if links&{'wrist_camera_mount_link','camera_optical_frame'}:raise ValueError('Robot already has this Camera Rig')
    joints=[j.get('name')for j in root.findall('joint')if j.get('type')!='fixed']
    link_transforms(source,dict.fromkeys(joints,0.))
    asset=read(manifest)
    if asset.get('schema')!='real2sim.object-asset/1'or not asset.get('visual')or not asset.get('collision'):
        raise ValueError('Rig requires a registered Visual/Collision Object Asset')
    for file,expected in asset['files'].items():
        if sha(local_path(manifest.parent,file))!=expected:raise ValueError('Assembly Asset SHA changed')
    target.mkdir(parents=True,exist_ok=False)
    copied=copy_native_asset(source,target/'source')
    if sha(copied)!=sha(source):raise ValueError('Source Robot snapshot must preserve exact URDF bytes')
    assembly=target/'assembly';shutil.copytree(manifest.parent,assembly)
    variant=copy.deepcopy(root);variant.set('name',root.get('name','robot')+'_wrist_camera')
    # MuJoCo defaults for URDF strip mesh directories, discard visual meshes
    # and fuse fixed links. Preserve this portable closure and optical frame
    # explicitly in the derived variant, without editing the source URDF.
    mujoco=variant.find('mujoco')
    if mujoco is None:mujoco=ET.SubElement(variant,'mujoco')
    compiler=mujoco.find('compiler')
    if compiler is None:compiler=ET.SubElement(mujoco,'compiler')
    compiler.set('strippath','false');compiler.set('discardvisual','false');compiler.set('fusestatic','false')
    # The copied original keeps its mesh layout, while the new URDF can refer to
    # that snapshot with portable relative paths. No original Joint is edited.
    for node in variant.findall('.//mesh'):
        name=node.get('filename')
        if not name or name.startswith(('package://','/')):raise ValueError('Resolve Robot mesh paths before creating a Rig')
        node.set('filename',os.path.relpath((copied.parent/name).resolve(),target))
    link=ET.SubElement(variant,'link',name='wrist_camera_mount_link')
    def origin_node(parent,T):
        matrix=transform(T);rpy=Rotation.from_matrix(matrix[:3,:3]).as_euler('xyz')
        ET.SubElement(parent,'origin',xyz=' '.join(format(v,'.17g')for v in matrix[:3,3]),rpy=' '.join(format(v,'.17g')for v in rpy))
    for kind in('visual','collision'):
        for index,part in enumerate(asset[kind]):
            if part.get('type')!='mesh':raise ValueError('Rig assembly must use registered native Mesh parts')
            row=ET.SubElement(link,kind,name='camera_'+kind+'_'+str(index));origin_node(row,part['pose'])
            mesh=ET.SubElement(ET.SubElement(row,'geometry'),'mesh',filename='assembly/'+part['file'])
            if part.get('scale'):mesh.set('scale',' '.join(map(str,part['scale'])))
            if kind=='visual':
                material=ET.SubElement(row,'material',name='camera_material_'+str(index))
                ET.SubElement(material,'color',rgba=' '.join(map(str,part.get('color',[.03,.03,.03])+[1.])))
                if part.get('texture'):
                    # Existing native closure follows OBJ->MTL->texture refs.
                    # Keep the registered assembly bytes intact; derive only
                    # the URDF-facing OBJ/MTL in a separate owned directory.
                    native=target/'urdf_meshes';native.mkdir(exist_ok=True)
                    obj=native/('visual_'+str(index)+'.obj');mtl=obj.with_suffix('.mtl')
                    obj.write_text('mtllib '+mtl.name+'\nusemtl camera_surface\n'+(assembly/part['file']).read_text())
                    texture=os.path.relpath(assembly/part['texture'],native)
                    mtl.write_text('newmtl camera_surface\nKd 1 1 1\nmap_Kd '+texture+'\n')
                    mesh.set('filename',obj.relative_to(target).as_posix())
    ET.SubElement(variant,'link',name='camera_optical_frame')
    for name,parent,child,T in [('wrist_camera_mount_joint',mount_link,'wrist_camera_mount_link',mount),
        ('camera_optical_joint','wrist_camera_mount_link','camera_optical_frame',optical)]:
        if name in {j.get('name')for j in root.findall('joint')}:raise ValueError('Accessory Joint identifier already exists')
        joint=ET.SubElement(variant,'joint',name=name,type='fixed');ET.SubElement(joint,'parent',link=parent);ET.SubElement(joint,'child',link=child);origin_node(joint,T)
    model=target/'so101_wrist_camera.urdf';ET.indent(variant);ET.ElementTree(variant).write(model,encoding='utf-8',xml_declaration=True)
    verify_native_closure(target,model)
    # A retained source tree lets every load verify exactly which fixed-only
    # extension was created, including original Joint attributes and limits.
    record={'schema':'real2sim.robot-rig/1','name':'SO-ARM101 + Wrist Camera','model':{'path':model.name,'sha256':sha(model)},
        'source_robot':copied.relative_to(target).as_posix(),'source_robot_sha256':sha(source),
        'assembly':{'asset_id':asset['asset_id'],'version':asset['version'],'manifest':'assembly/manifest.json',
            'content_sha256':asset['content_sha256']},'joint_names':joints,'mount_link':mount_link,
        'mount_frame':'wrist_camera_mount_link','optical_frame':'camera_optical_frame',
        'T_link_mount':mount.tolist(),'T_mount_optical':optical.tolist(),'mount_status':'estimated',
        'calibration_status':'uncalibrated','intrinsics':None,'distortion':None,'physical_verified':False,
        'evidence':evidence,'units':'m/rad','optical_axes':'X right / Y down / Z forward',
        'files':{p.relative_to(target).as_posix():sha(p)for p in target.rglob('*')if p.is_file()}}
    write(target/'rig.yaml',record)
    return load_robot_rig(target/'rig.yaml')


def load_robot_rig(path):
    """Read-only verification of the immutable native Robot/Assembly closure."""
    import xml.etree.ElementTree as ET
    from .scene import local_path,transform
    from .export import verify_native_closure
    from .calibration.geometry import link_transforms
    path=Path(path).resolve();root=path.parent;record=read(path)
    if record.get('schema')!='real2sim.robot-rig/1'or record.get('mount_status')!='estimated'or record.get('calibration_status')!='uncalibrated':
        raise ValueError('Unsupported Robot Rig state; calibrated mounts require the existing Calibration workflow')
    if record.get('intrinsics')is not None or record.get('distortion')is not None or record.get('physical_verified')is not False:
        raise ValueError('Uncalibrated Rig cannot manufacture sensor Calibration')
    if not record.get('files'):raise ValueError('Robot Rig must have a frozen file manifest')
    for name,expected in record['files'].items():
        if sha(local_path(root,name))!=expected:raise ValueError('Robot Rig file SHA/integrity changed: '+name)
    model=local_path(root,record['model']['path']);source=local_path(root,record['source_robot'])
    if sha(model)!=record['model']['sha256']or sha(source)!=record['source_robot_sha256']:raise ValueError('Robot identity changed')
    verify_native_closure(root,model)
    old=ET.parse(source).getroot();new=ET.parse(model).getroot()
    def structural(node):return(node.tag,dict(node.attrib),(node.text or'').strip(),[structural(c)for c in node])
    original={j.get('name'):j for j in old.findall('joint')};updated={j.get('name'):j for j in new.findall('joint')}
    if len(updated)!=len(new.findall('joint'))or set(updated)-original.keys()!={'wrist_camera_mount_joint','camera_optical_joint'}:
        raise ValueError('Rig must add only the two declared fixed Camera Joints')
    if any(n not in updated or structural(j)!=structural(updated[n])for n,j in original.items()):raise ValueError('Rig changed original Robot Joint kinematics')
    if any(updated[n].get('type')!='fixed'for n in set(updated)-original.keys()):raise ValueError('Camera accessory cannot introduce an actuated Joint')
    names=[j.get('name')for j in new.findall('joint')if j.get('type')!='fixed']
    if names!=record['joint_names']:raise ValueError('Rig Robot Joint mapping/order changed')
    poses=link_transforms(model,dict.fromkeys(names,0.));base=link_transforms(source,dict.fromkeys(names,0.))
    if any(not np.allclose(poses[n],T,atol=1e-12,rtol=0)for n,T in base.items()):raise ValueError('Rig changed original Robot FK')
    mount=transform(record['T_link_mount']);optical=transform(record['T_mount_optical'])
    if not np.allclose(poses[record['mount_frame']],poses[record['mount_link']]@mount,atol=1e-10,rtol=0):raise ValueError('Rig mount Transform mismatch')
    if not np.allclose(poses[record['optical_frame']],poses[record['mount_frame']]@optical,atol=1e-10,rtol=0):raise ValueError('Rig Optical Transform mismatch')
    return {**record,'path':str(path)}


def import_robot_rig(candidate,path,*,joints=None):
    """Import an explicitly selected Rig into one Candidate, never Current Scene.

    A variant has a distinct model SHA. Existing measured-q/Calibration records
    are not relabelled to that new identity or implicitly re-approved.
    """
    from .export import copy_native_asset
    from .calibration.geometry import reference_geometry
    import copy
    rig=load_robot_rig(path);scene=candidate.scene;existing=scene.get('robot_model')
    if existing:
        if existing.get('model_sha256')!=rig['model']['sha256']:raise ValueError('Cannot replace a different existing Candidate Robot; explicitly use a new Candidate')
        if scene.get('robot_rig',{}).get('rig_sha256')!=sha(rig['path']):raise ValueError('Existing Robot Rig identity differs')
        return {'status':'REUSED','physical_verified':False,'rig':scene['robot_rig']}
    candidate.project.checkpoint();candidate.require_open()
    source=Path(rig['path']).parent/rig['model']['path'];model=copy_native_asset(source,candidate.project.root/'input/robot')
    states=dict.fromkeys(rig['joint_names'],0.)if joints is None else joints
    scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated',['Unregistered Robot Base gauge; not calibrated World pose'])}
    imported={}
    def import_native_mesh(path):
        # A Rig's OBJ may reference MTL/PNG files. Snapshot its native closure
        # through the existing exporter instead of copying one bare mesh file.
        snapshot=copy_native_asset(path,candidate.project.root/'input/assets',copied=imported)
        digest=sha(snapshot);key='asset_'+digest[:16]
        scene['assets'][key]={'path':snapshot.relative_to(candidate.project.root).as_posix(),
            'sha256':digest,'source':str(Path(path).resolve())}
        return key
    objects,poses=reference_geometry(model,states,import_native_mesh)
    assembly=Path(rig['path']).parent/rig['assembly']['manifest']
    parts=read(assembly)['visual'];camera_objects=[o for o in objects if o['link']==rig['mount_frame']]
    if len(camera_objects)!=len(parts):raise ValueError('Robot Rig Visual/Assembly part count differs')
    for obj,part in zip(camera_objects,parts):
        if part.get('texture'):obj['visual']['texture']=import_native_mesh(assembly.parent/part['texture'])
    scene['objects'].extend(objects)
    for name,T in poses.items():scene['frames']['robot_link_'+name]={'parent':'robot_base','transform':value(T.tolist(),'derived',['URDF FK at explicit input q; no new measurement'])}
    scene['robot_model']={'format':'urdf','path':model.relative_to(candidate.project.root).as_posix(),
        'model_sha256':sha(model),'source_robot_sha256':rig['source_robot_sha256'],'joint_names':rig['joint_names'],
        'mapping_verified':False,'joint_coordinate_status':'URDF_RAD; existing Capture identity not rebound'}
    scene['robot_rig']={k:copy.deepcopy(rig[k])for k in('schema','name','assembly','mount_link','mount_frame','optical_frame',
        'T_link_mount','T_mount_optical','mount_status','calibration_status','intrinsics','distortion','source_robot_sha256','evidence')}
    scene['robot_rig'].update(rig_sha256=sha(rig['path']),model_sha256=sha(model),physical_verified=False)
    candidate.save(scene)
    return {'status':'IMPORTED','physical_verified':False,'rig':scene['robot_rig']}


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


def scene_memo(project):
    """Current literal prompt, with one read-only fallback for legacy Projects."""
    import hashlib
    path=project.root/'input/scene_memo.txt';relative='input/scene_memo.txt'
    if not path.exists():
        evidence=project.evidence
        selected=evidence.get('current_brief')or next(iter(reversed(evidence.get('briefs',[]))),None)
        if selected is None:return {'path':None,'text':'','sha256':hashlib.sha256(b'').hexdigest(),'saved':False}
        relative=selected['path'];path=local_path(project.root,relative)
        if not path.is_relative_to(project.root/'input')or not path.is_file()or sha(path)!=selected['sha256']:
            raise ValueError('Legacy Scene memo missing or changed')
    if path.is_symlink():raise ValueError('Scene memo symlink is forbidden')
    data=path.read_bytes()
    return {'path':relative,'text':data.decode('utf-8'),'sha256':hashlib.sha256(data).hexdigest(),'saved':True}


def save_scene_memo(project,text):
    """Update one prompt atomically; execution snapshots belong to Candidate."""
    import os,uuid
    from .candidate import exclusive
    if not isinstance(text,str):raise ValueError('Scene memo must be text')
    with exclusive(project):
        path=project.root/'input/scene_memo.txt';data=text.encode('utf-8')
        if path.is_file()and not path.is_symlink()and path.read_bytes()==data:return scene_memo(project)
        temporary=path.with_name('.scene_memo_'+uuid.uuid4().hex)
        try:
            with temporary.open('xb')as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
        project.invalidate()
        return scene_memo(project)
