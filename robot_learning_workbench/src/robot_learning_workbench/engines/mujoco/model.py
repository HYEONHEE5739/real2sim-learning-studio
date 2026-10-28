"""Direct MuJoCo3.3.7 model compilation from a verified Scene package.

Official APIs: https://mujoco.readthedocs.io/en/3.3.7/python.html
Native position servos: https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html#actuator-position
No engine wrapper, SDK, IK, task runner or original repository runtime access.
"""
from pathlib import Path
from dataclasses import dataclass
from collections.abc import Mapping
import copy,hashlib,json,xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from ...robot.calibration import JOINTS
from scene_contract.transforms import resolve_transform,validate_transform

KP=(55.,30.,25.,12.,7.,4.)
KD=(.7,.8,.7,.5,.5,.3)
SO101_POSITION_FORCE_LIMIT=30.

def numbers(values):
    return ' '.join((f'{float(v):.12g}' for v in np.asarray(values).reshape(-1)))

def transform(value):
    t = np.asarray(value, dtype=float)
    if t.shape != (4, 4) or not np.isfinite(t).all() or (not np.allclose(t[3], [0, 0, 0, 1])) or (not np.allclose(t[:3, :3].T @ t[:3, :3], np.eye(3), atol=1e-06)) or (not np.isclose(np.linalg.det(t[:3, :3]), 1.0, atol=1e-06)):
        raise ValueError('Expected finite rigid 4x4 transform')
    return t

def pose_attrs(value):
    t = transform(value)
    q = Rotation.from_matrix(t[:3, :3]).as_quat()
    return {'pos': numbers(t[:3, 3]), 'quat': numbers(q[[3, 0, 1, 2]])}

def origin(node):
    t = np.eye(4)
    if node is not None:
        t[:3, 3] = np.fromstring(node.get('xyz', '0 0 0'), sep=' ')
        t[:3, :3] = Rotation.from_euler('xyz', np.fromstring(node.get('rpy', '0 0 0'), sep=' ')).as_matrix()
    return t

def robot_xml(urdf, base_pose, finger_convex, contact_pads):
    # The selected URDF already contains the baked Geometry residual.
    offsets = dict.fromkeys(JOINTS, 0.)
    root = ET.parse(urdf).getroot()
    links = {link.get('name'): link for link in root.findall('link')}
    joints = root.findall('joint')
    children = {j.find('child').get('link') for j in joints}
    bases = set(links) - children
    if len(bases) != 1:
        raise ValueError('URDF must have a single fixed robot base')
    movable = {j.get('name'): j for j in joints if j.get('type') != 'fixed'}
    if set(movable) != set(JOINTS):
        raise ValueError('URDF must have the six named SO101 revolute joints')
    result = ET.Element('mujocoinclude')
    assets = ET.SubElement(result, 'asset')
    meshes = {}
    source_hashes = {str(urdf): hashlib.sha256(urdf.read_bytes()).hexdigest()}
    if finger_convex.get('schema') != 'so101.finger-convex-parts/1':
        raise ValueError('Unknown SO101 finger collision export')
    convex_parts = {(entry['link'], entry['collision_index']): entry for entry in finger_convex['meshes']}
    materials = {m.get('name'): m.find('color').get('rgba') for m in root.findall('material')}
    world = ET.SubElement(result, 'worldbody')

    def add_link(parent, name, frame, joint=None):
        if joint is not None and joint.get('type') != 'fixed':
            axis = np.fromstring(joint.find('axis').get('xyz'), sep=' ')
            motion = np.eye(4)
            motion[:3, :3] = Rotation.from_rotvec(axis / np.linalg.norm(axis) * offsets[joint.get('name')]).as_matrix()
            frame = frame @ motion
        if name == 'tool0':
            ET.SubElement(parent, 'site', name='tool0', size='.002', rgba='0 1 0 1', **pose_attrs(frame))
            return
        body = ET.SubElement(parent, 'body', name='robot_' + name, **pose_attrs(frame))
        if joint is not None and joint.get('type') != 'fixed':
            if joint.get('type') != 'revolute':
                raise ValueError('Only SO101 revolute joints supported')
            limit = joint.find('limit')
            ET.SubElement(body, 'joint', name=joint.get('name'), type='hinge', axis=joint.find('axis').get('xyz'), range=f"{limit.get('lower')} {limit.get('upper')}", damping='0', armature='.001')
        inertial = links[name].find('inertial')
        tensor = inertial.find('inertia').attrib
        inertia = np.array([[float(tensor['ixx']), float(tensor['ixy']), float(tensor['ixz'])], [float(tensor['ixy']), float(tensor['iyy']), float(tensor['iyz'])], [float(tensor['ixz']), float(tensor['iyz']), float(tensor['izz'])]])
        inertial_pose = origin(inertial.find('origin'))
        inertia = inertial_pose[:3, :3] @ inertia @ inertial_pose[:3, :3].T
        ET.SubElement(body, 'inertial', pos=numbers(inertial_pose[:3, 3]), mass=inertial.find('mass').get('value'), fullinertia=numbers([inertia[0, 0], inertia[1, 1], inertia[2, 2], inertia[0, 1], inertia[0, 2], inertia[1, 2]]))
        for kind in ('visual', 'collision'):
            for (index, geom) in enumerate(links[name].findall(kind)):
                mesh = geom.find('geometry/mesh')
                if mesh is None:
                    raise ValueError('Expected SO101 mesh geometry')
                path = (urdf.parent / mesh.get('filename')).resolve()
                scale = mesh.get('scale', '1 1 1')
                key = (str(path), scale)
                if key not in meshes:
                    meshes[key] = f'mesh_{len(meshes)}'
                    ET.SubElement(assets, 'mesh', name=meshes[key], file=str(path), scale=scale)
                    source_hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
                attributes = {'name': f'{name}_{kind}_{index}', 'type': 'mesh', 'mesh': meshes[key], **pose_attrs(origin(geom.find('origin')))}
                if kind == 'collision' and name in ('gripper', 'jaw'):
                    entry = convex_parts.get((name, index))
                    if not entry or entry['source_sha256'] != source_hashes[str(path)]:
                        raise ValueError('Finger collision STL changed; regenerate offline convex export: ' + str(path))
                    if not entry['parts']:
                        raise ValueError('Empty finger collision export')
                    for (part_index, part) in enumerate(entry['parts']):
                        part_name = f'{name}_collision_{index}_part_{part_index}'
                        ET.SubElement(assets, 'mesh', name=part_name, vertex=numbers(part['vertices']), face=' '.join((str(int(v)) for row in part['faces'] for v in row)), scale=scale)
                        ET.SubElement(body, 'geom', **{**attributes, 'name': part_name, 'mesh': part_name, 'contype': '2', 'conaffinity': '1', 'group': '3', 'rgba': '0 0 0 0'})
                    continue
                if kind == 'visual':
                    material = geom.find('material')
                    attributes.update(contype='0', conaffinity='0', group='2', rgba=materials.get(material.get('name') if material is not None else '', '.7 .7 .7 1'))
                else:
                    attributes.update(contype='2', conaffinity='1', group='3', rgba='0 0 0 0')
                ET.SubElement(body, 'geom', **attributes)
        for child_joint in joints:
            if child_joint.find('parent').get('link') == name:
                add_link(body, child_joint.find('child').get('link'), origin(child_joint.find('origin')), child_joint)
    add_link(world, next(iter(bases)), base_pose)
    actuators = ET.SubElement(result, 'actuator')
    limits = []
    for (index, name) in enumerate(JOINTS):
        limit = movable[name].find('limit')
        limits.append([float(limit.get('lower')), float(limit.get('upper'))])
        effort = SO101_POSITION_FORCE_LIMIT
        ET.SubElement(actuators, 'position', name='target_' + name, joint=name, kp=str(KP[index]), kv=str(KD[index]), ctrlrange=numbers(limits[-1]), forcerange=numbers([-effort, effort]))
    if contact_pads.get('schema') != 'so101.usd-contact-pads/1':
        raise ValueError('Unknown SO101 contact pad export')
    for pad in contact_pads['pads']:
        body = result.find(".//body[@name='robot_" + pad['link'] + "']")
        if body is None: raise ValueError('Contact pad link missing: ' + pad['link'])
        ET.SubElement(body, 'geom', name=pad['link']+'_contact_pad', type='box',
            size=numbers(np.asarray(pad['dimensions_m'])/2), **pose_attrs(pad['T_link']),
            rgba=numbers(pad['rgba']), contype='2' if pad['collision'] else '0',
            conaffinity='1' if pad['collision'] else '0', friction=numbers([pad['dynamic_friction'],.005,.0001]),
            priority='1',condim='4',solref='.004 1',solimp='.95 .99 .001')
    result.tag='mujoco'
    ET.SubElement(result,'compiler',angle='radian',autolimits='true',inertiafromgeom='false')
    return result, limits, source_hashes


@dataclass(frozen=True)
class ModelConfig:
    """Resolved engine inputs, never hidden defaults from an original workspace."""
    initial_joint_rad: tuple
    active_object_ids: tuple
    object_physics: Mapping
    physics_timestep_s: float = 1/300
    decimation: int = 10
    width: int = 640
    height: int = 480
    object_ids: tuple | None = None


@dataclass(frozen=True)
class ModelBindings:
    scene_identity: object
    model_sha256: str
    urdf_sha256: str
    joint_ids: tuple
    q_indices: tuple
    v_indices: tuple
    actuator_ids: tuple
    limits: np.ndarray
    initial_joint_rad: np.ndarray
    dynamic_objects: tuple
    object_indices: Mapping
    object_body_ids: Mapping
    eef_id: int
    finger_body_ids: tuple
    finger_geom_ids: tuple
    camera_ids: Mapping
    world_from_robot_base: np.ndarray
    decimation: int
    width: int
    height: int
    collision_sources: Mapping


def _local(package, path):
    root=Path(package.root).resolve();candidate=Path(path)
    if candidate.is_absolute() or '..' in candidate.parts or '\\' in str(path):raise ValueError('Package-relative asset path required')
    target=(root/candidate).resolve()
    if not target.is_relative_to(root) or not target.is_file():raise ValueError('Missing/escaping package Asset: '+str(path))
    entry=next((f for f in package.files if f.path==candidate.as_posix()),None)
    if entry is None or hashlib.sha256(target.read_bytes()).hexdigest()!=entry.sha256:raise ValueError('Unregistered/changed package Asset: '+str(path))
    return target


def _collision_inputs(package):
    binding=package.scene['robot']['collision'];result={}
    for kind,schema in [('finger_convex_parts','so101.finger-convex-parts/1'),('contact_pads','so101.usd-contact-pads/1')]:
        declaration=binding[kind];payload=json.loads(_local(package,declaration['asset_path']).read_text())
        if payload.get('schema')!=schema:raise ValueError('Unknown Collision schema')
        identities={row['mesh']:row['source_sha256'] for row in payload['meshes']} if kind=='finger_convex_parts' else payload['source_sha256']
        if set(identities)!=set(declaration['sources']):raise ValueError('Collision source identity set mismatch')
        for name,digest in identities.items():
            source=declaration['sources'][name]
            if source['sha256']!=digest or hashlib.sha256(_local(package,source['asset_path']).read_bytes()).hexdigest()!=digest:raise ValueError('Collision source hash mismatch')
        result[kind]=payload
    return result


def _execution_urdf(package):
    records=[record for record in package.calibration['records'].values() if record['kind']=='robot_residual' and record['application']['mode']=='baked']
    if len(records)!=1:raise ValueError('One explicit baked robot model binding required; no reference-snapshot or active-profile fallback')
    record=records[0]
    paths=[p for p in record['application']['asset_paths'] if str(p).endswith('.urdf')]
    if len(paths)!=1:raise ValueError('One calibrated URDF Asset required')
    path=_local(package,paths[0])
    if hashlib.sha256(path.read_bytes()).hexdigest()!=record['execution_model_sha256']:raise ValueError('Execution model identity mismatch')
    return path


def build_model(scene, prepared):
    """Compile the package's authored geometry with one real calibrated SO101.

    `prepared` is a resolved ModelConfig (or PreparedRun effective_settings['mujoco']
    carrying exactly those constructor fields). No original project path is read.
    """
    import mujoco
    if isinstance(prepared,ModelConfig):cfg=prepared
    elif hasattr(prepared,'effective_settings') and isinstance(prepared.effective_settings.get('mujoco'),Mapping):cfg=ModelConfig(**prepared.effective_settings['mujoco'])
    else:raise ValueError('Explicit resolved MuJoCo ModelConfig required; Recipe engine preparation is not implicit')
    raw_initial=np.asarray(cfg.initial_joint_rad)
    if raw_initial.dtype.kind not in 'fiu':raise ValueError('Numeric model radians required; bool/string units are invalid')
    initial=raw_initial.astype(float)
    if initial.shape!=(6,) or not np.isfinite(initial).all() or tuple(scene.scene['robot']['joint_order'])!=tuple(JOINTS):raise ValueError('Exact finite SO101 model-radian joint order required')
    if type(cfg.decimation) is not int or cfg.decimation<1 or not np.isfinite(cfg.physics_timestep_s) or not 0<cfg.physics_timestep_s<=.01:raise ValueError('Invalid physics/control clock')
    if type(cfg.width) is not int or type(cfg.height) is not int or min(cfg.width,cfg.height)<1:raise ValueError('Invalid image resolution')
    if len(set(cfg.active_object_ids))!=len(cfg.active_object_ids) or any(name not in scene.scene['objects'] or scene.scene['objects'][name]['role']!='task_object' for name in cfg.active_object_ids):raise ValueError('Invalid active object selection')
    if cfg.object_ids is not None and (len(set(cfg.object_ids))!=len(cfg.object_ids) or not set(cfg.active_object_ids)<=set(cfg.object_ids) or any(name not in scene.scene['objects'] or scene.scene['objects'][name]['role'] not in ('task_object','receptacle') for name in cfg.object_ids)):raise ValueError('Explicit task object selection is invalid')
    canonical=json.loads(_local(scene,'provenance.json').read_text())['original_scene']
    objects={obj['id']:obj for obj in canonical['objects']};frames=scene.scene['frames']
    base=resolve_transform(frames,source='robot_base',target='world')
    urdf=_execution_urdf(scene);collision=_collision_inputs(scene)
    robot,limits,hashes=robot_xml(urdf,base,collision['finger_convex_parts'],collision['contact_pads'])
    limits=np.asarray(limits)
    if np.any(initial<limits[:,0]) or np.any(initial>limits[:,1]):raise ValueError('Initial joints outside model limits')
    native_path=_local(scene,scene.scene['engines']['mujoco']['asset_path']);authored=ET.parse(native_path).getroot()
    output=ET.Element('mujoco',model='so101_workbench')
    ET.SubElement(output,'compiler',angle='radian',autolimits='true',inertiafromgeom='false')
    option=ET.SubElement(output,'option',timestep=str(cfg.physics_timestep_s),integrator='implicitfast',gravity='0 0 -9.81',cone='elliptic',iterations='100',tolerance='1e-10',impratio='10',noslip_iterations='10')
    ET.SubElement(option,'flag',multiccd='enable')
    default=ET.SubElement(output,'default');ET.SubElement(default,'geom',friction='1 .005 .0001',condim='3',contype='1',conaffinity='3',solref='.01 1')
    visual=ET.SubElement(output,'visual');ET.SubElement(visual,'global',offwidth=str(cfg.width),offheight=str(cfg.height));ET.SubElement(visual,'quality',shadowsize='2048',offsamples='4');ET.SubElement(visual,'map',znear='.001');ET.SubElement(visual,'headlight',ambient='.45 .45 .45',diffuse='.2 .2 .2',specular='0 0 0')
    assets=robot.find('asset');renames={node.get('name'):'builder_'+node.get('name') for node in authored.find('asset')}
    for original in authored.find('asset'):
        asset=copy.deepcopy(original);asset.set('name',renames[asset.get('name')])
        for key in ('mesh','material','texture'):
            if asset.get(key) in renames:asset.set(key,renames[asset.get(key)])
        if asset.get('file'):asset.set('file',str(_local(scene,(native_path.parent/asset.get('file')).relative_to(scene.root).as_posix())))
        assets.append(asset)
    output.append(assets);world=robot.find('worldbody');output.append(world);output.append(robot.find('actuator'))
    ET.SubElement(world,'light',pos='0 0 1',dir='-.3 -.4 -1',directional='true',castshadow='false',ambient='.25 .25 .25',diffuse='.5 .5 .5',specular='.05 .05 .05')
    dynamic=tuple(cfg.active_object_ids);replaced={obj['link'] for obj in objects.values() if obj['role']=='reference_robot'}
    for body in world.findall('.//body'):
        if body.get('name').removeprefix('robot_') in replaced:
            for geom in list(body.findall('geom')):
                if '_visual_' in geom.get('name',''):body.remove(geom)
    def world_pose(name):return resolve_transform(frames,source=scene.scene['objects'][name]['frame_id'],target='world')
    def mounted(frame):
        while frame!='world':
            if frame=='robot_link_gripper':return True
            if frame.startswith('robot_link_'):raise ValueError('Unsupported robot fixture mount: '+frame)
            frame=canonical['frames'][frame]['parent']
        return False
    excluded={name for name,obj in objects.items() if obj['role']=='manipulable_object' and name not in dynamic}
    if cfg.object_ids is not None:excluded.update(name for name,obj in objects.items() if obj['role'] in ('manipulable_object','receptacle') and name not in cfg.object_ids)
    while True:
        dependent={name for name,obj in objects.items() if obj.get('parent_object') in excluded}
        if dependent<=excluded:break
        excluded|=dependent
    for source in authored.find('worldbody').findall('body'):
        name=source.get('name');obj=objects[name]
        if name in excluded:continue
        physical=cfg.object_physics.get(name);local=np.eye(4)
        if obj['role']=='reference_robot':
            body=world.find(".//body[@name='robot_"+obj['link']+"']");local=transform(obj['link_local_pose'])
        elif mounted(obj['frame']):
            body=world.find(".//body[@name='robot_gripper']");local=np.linalg.inv(resolve_transform(frames,source='robot_link_gripper',target='world'))@world_pose(name)
        elif obj.get('parent_object'):
            parent=obj['parent_object'];body=world.find("body[@name='"+parent+"']");local=np.linalg.inv(world_pose(parent))@world_pose(name)
        else:
            body=ET.SubElement(world,'body',name=name,**pose_attrs(world_pose(name)))
            if name in dynamic:
                if physical is None or physical['role']!='DYNAMIC_MANIPULAND' or not physical['mass_kg']>0:raise ValueError('Dynamic object requires explicit positive mass/physics')
                ET.SubElement(body,'freejoint',name='object_free_'+name)
                size=np.asarray(scene.scene['objects'][name]['task_geometry']['dimensions_m'],float);mass=float(physical['mass_kg'])
                ET.SubElement(body,'inertial',pos='0 0 0',mass=str(mass),diaginertia=numbers(mass/12*(size@size-size**2)))
        if body is None:raise ValueError('Missing runtime geometry owner: '+name)
        for original in source.findall('geom'):
            visual_geom='_visual_' in original.get('name','');is_collision=not visual_geom and physical is not None and physical['collision']
            if not visual_geom and not is_collision:continue
            geom=copy.deepcopy(original);t=np.eye(4);t[:3,3]=np.fromstring(geom.get('pos','0 0 0'),sep=' ');q=np.fromstring(geom.get('quat','1 0 0 0'),sep=' ');t[:3,:3]=Rotation.from_quat(q[[1,2,3,0]]).as_matrix();geom.attrib.update(pose_attrs(local@t));geom.set('name','builder_'+geom.get('name'))
            for key in ('mesh','material'):
                if geom.get(key):geom.set(key,renames[geom.get(key)])
            geom.set('contype','1' if is_collision else '0');geom.set('conaffinity','3' if is_collision else '0');geom.set('mass','0');geom.set('group','3' if is_collision else '2')
            if is_collision:geom.set('rgba','0 0 0 0');geom.set('friction',numbers([physical['material']['dynamic_friction'],.005,.0001]))
            body.append(geom)
    for name,camera in scene.scene['cameras'].items():
        original=next(c for c in canonical['cameras'] if c['id']==name)
        if any(camera['distortion']):raise ValueError('MuJoCo requires explicitly undistorted camera input')
        if original['frame']=='robot_link_gripper':parent=world.find(".//body[@name='robot_gripper']");pose=np.array(original['pose']['value'],float)
        elif original['frame']=='world':parent=world;pose=resolve_transform(frames,source=camera['frame_id'],target='world')
        else:raise ValueError('Unsupported dynamic camera parent')
        pose[:3,:3]=pose[:3,:3]@np.diag([1.,-1.,-1.]);k=np.array(camera['K'],float);k[0]*=cfg.width/camera['resolution'][0];k[1]*=cfg.height/camera['resolution'][1]
        ET.SubElement(parent,'camera',name=name,**pose_attrs(pose),resolution=f'{cfg.width} {cfg.height}',sensorsize=f'{cfg.width} {cfg.height}',focalpixel=numbers([k[0,0],k[1,1]]),principalpixel=numbers([cfg.width/2-k[0,2],k[1,2]-cfg.height/2]))
    xml=ET.tostring(output,encoding='unicode');model=mujoco.MjModel.from_xml_string(xml)
    def ids(kind,names):
        result=tuple(int(mujoco.mj_name2id(model,kind,name)) for name in names)
        if any(i<0 for i in result):raise ValueError('Compiled model binding missing')
        return result
    joints=ids(mujoco.mjtObj.mjOBJ_JOINT,JOINTS);actuators=ids(mujoco.mjtObj.mjOBJ_ACTUATOR,['target_'+name for name in JOINTS]);objects_ids={name:model.body(name).id for name in scene.scene['objects'] if mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,name)>=0}
    object_indices={name:(int(model.jnt_qposadr[model.joint('object_free_'+name).id]),int(model.jnt_dofadr[model.joint('object_free_'+name).id])) for name in dynamic}
    for value in (initial,limits,base):value.setflags(write=False)
    finger_bodies=ids(mujoco.mjtObj.mjOBJ_BODY,['robot_gripper','robot_jaw']);finger_geom_ids=tuple(i for i in range(model.ngeom) if model.geom_bodyid[i] in finger_bodies and model.geom_contype[i])
    model_sha=hashlib.sha256((xml.replace(str(scene.root),'package:')+scene.identity.manifest_sha256).encode()).hexdigest()
    return model,ModelBindings(scene.identity,model_sha,hashlib.sha256(urdf.read_bytes()).hexdigest(),joints,tuple(map(int,model.jnt_qposadr[list(joints)])),tuple(map(int,model.jnt_dofadr[list(joints)])),actuators,limits,initial,dynamic,object_indices,objects_ids,model.site('tool0').id,finger_bodies,finger_geom_ids,{name:model.camera(name).id for name in scene.scene['cameras']},base,cfg.decimation,cfg.width,cfg.height,scene.scene['robot']['collision'])
