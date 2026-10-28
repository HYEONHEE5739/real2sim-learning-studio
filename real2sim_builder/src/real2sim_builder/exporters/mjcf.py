# Algorithms ported from the original Builder; source SHA/AST in BU evidence.
# Official formats: https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html
# https://openusd.org/release/api/class_usd_geom_camera.html
"""Compile the canonical description directly to MJCF. No USD dependency."""
from pathlib import Path
import xml.etree.ElementTree as ET
import os
import json
import numpy as np
from scipy.spatial.transform import Rotation
from ..project import validate, world_pose, local_path
from ..calibration.geometry import parts


def numbers(x):return ' '.join(format(float(v),'.12g') for v in np.asarray(x).ravel())
def pose(t):
    q=Rotation.from_matrix(t[:3,:3]).as_quat()
    return {'pos':numbers(t[:3,3]),'quat':numbers(np.r_[q[3],q[:3]])}


def export(scene,root,path):
    validate(scene,root,complete=True);path=Path(path)
    model=ET.Element('mujoco',model=scene['name']);ET.SubElement(model,'compiler',angle='radian',autolimits='true')
    custom=ET.SubElement(model,'custom')
    ET.SubElement(custom,'text',name='canonical_frames',data=json.dumps(scene['frames'],sort_keys=True))
    ET.SubElement(custom,'text',name='semantic_roles',data=json.dumps({o['id']:o['role'] for o in scene['objects']},sort_keys=True))
    ET.SubElement(model,'option',timestep='.002',gravity='0 0 -9.81')
    visual=ET.SubElement(model,'visual')
    width=max(c['resolution'][0] for c in scene['cameras']);height=max(c['resolution'][1] for c in scene['cameras'])
    ET.SubElement(visual,'global',offwidth=str(width),offheight=str(height))
    from ..project import CLIP
    ET.SubElement(model,'statistic',extent='1')
    ET.SubElement(visual,'map',znear=str(CLIP[0]),zfar=str(CLIP[1]))
    ET.SubElement(visual,'quality',offsamples='4')
    ET.SubElement(visual,'headlight',ambient=numbers(scene['lights']['ambient']['value']),diffuse='.7 .7 .7',specular='.1 .1 .1')
    assets=ET.SubElement(model,'asset');world=ET.SubElement(model,'worldbody');mesh_names={};texture_names={}
    for obj in scene['objects']:
        body=ET.SubElement(world,'body',name=obj['id'],**pose(world_pose(scene,obj)))
        mass=obj['physics']['mass_kg']['value'];dynamic=obj['role']=='manipulable_object' and mass is not None and mass>0
        if dynamic: ET.SubElement(body,'freejoint',name=obj['id']+'_free')
        collisions=parts(obj,'collision')
        for field in ('visual','collision'):
            for i,part in enumerate(parts(obj,field)):
                attrs={'name':obj['id']+'_'+field+'_'+str(i),**pose(part['pose']),
                    'contype':'0' if field=='visual' else '1','conaffinity':'0' if field=='visual' else '1',
                    'group':'1' if field=='visual' else '3','rgba':numbers([*(obj['color']['value'] or [.5]*3),1 if field=='visual' else 0]),
                    'mass':str(float(mass)/len(collisions)) if dynamic and field=='collision' else '0'}
                kind=part['type'];dims=part['dimensions'];attrs['type']=kind
                if kind=='box':attrs['size']=numbers(dims/2)
                elif kind=='sphere':
                    if not np.allclose(dims,dims[0]):raise ValueError('Sphere requires equal dimensions')
                    attrs['size']=str(dims[0]/2)
                elif kind=='cylinder':
                    if not np.isclose(dims[0],dims[1]):raise ValueError('Cylinder requires equal diameters')
                    attrs['size']=numbers([dims[0]/2,dims[2]/2])
                elif kind=='mesh':
                    key=(part['asset'],tuple(part.get('scale',[1,1,1])))
                    if key not in mesh_names:
                        name='mesh_'+str(len(mesh_names));mesh_names[key]=name
                        ET.SubElement(assets,'mesh',name=name,file=os.path.relpath(local_path(root,scene['assets'][part['asset']]['path']),path.parent),scale=numbers(key[1]))
                    attrs['mesh']=mesh_names[key]
                friction=obj['physics']['friction']['value']
                if friction is not None:attrs['friction']=numbers([friction,.005,.0001])
                texture=obj['visual'].get('texture') if field=='visual' else None
                if texture:
                    if texture not in texture_names:
                        name='texture_'+str(len(texture_names));texture_names[texture]=name
                        ET.SubElement(assets,'texture',name=name,type='2d',file=os.path.relpath(local_path(root,scene['assets'][texture]['path']),path.parent))
                        ET.SubElement(assets,'material',name=name,texture=name,texrepeat='1 1',texuniform='true')
                    attrs['material']=texture_names[texture]
                ET.SubElement(body,'geom',**attrs)
    for light in scene['lights'].get('sources',[]):
        t=np.asarray(light['pose']['value']);gain=float(light['energy']['value'])/1000
        ET.SubElement(world,'light',name='light_'+light['id'],pos=numbers(t[:3,3]),dir=numbers(-t[:3,2]),
            directional='true' if light['type']=='sun' else 'false',diffuse=numbers(np.asarray(light['color']['value'])*gain))
    from ..project import OPTICAL_TO_RENDER
    conversion=OPTICAL_TO_RENDER
    for camera in scene['cameras']:
        k=np.asarray(camera['K']['value']);w,h=camera['resolution']
        if np.any(np.asarray(camera['distortion']['value'])!=0):raise ValueError('Undistort evidence before exporting pinhole simulator cameras')
        ET.SubElement(world,'camera',name=camera['id'],**pose(world_pose(scene,camera)@conversion),
            resolution=f'{w} {h}',sensorsize=f'{w} {h}',focalpixel=numbers([k[0,0],k[1,1]]),
            principalpixel=numbers([w/2-k[0,2],k[1,2]-h/2]))
    ET.indent(model);ET.ElementTree(model).write(path,encoding='unicode',xml_declaration=True)
    return {o['id']:'/worldbody/'+o['id'] for o in scene['objects']}


def load_robot_collision(root,binding):
    """Read SO101 collision inputs strictly from the exported package declaration.

    Returns the original offline vertex/contact-pad payloads for the consuming
    engine builder. It never searches ROOT/assets or applies a robot command.
    """
    import hashlib
    root=Path(root).resolve();result={}
    def local(path):
        p=Path(path)
        if p.is_absolute() or (root/p).resolve().is_relative_to(root) is False:raise ValueError('Collision input escapes package')
        target=root/p
        if not target.is_file():raise ValueError('Missing collision input: '+str(path))
        return target
    schemas={'finger_convex_parts':'so101.finger-convex-parts/1','contact_pads':'so101.usd-contact-pads/1'}
    if set(binding)!=set(schemas):raise ValueError('Both Finger Collision and contact pad declarations are required')
    for kind,schema in schemas.items():
        declaration=binding[kind];data=json.loads(local(declaration['asset_path']).read_text())
        if data.get('schema')!=schema:raise ValueError('Unknown collision input schema: '+kind)
        required={row['mesh']:row['source_sha256'] for row in data['meshes']} if kind=='finger_convex_parts' else data['source_sha256']
        if set(required)!=set(declaration['sources']):raise ValueError('Collision source identity list mismatch')
        for name,digest in required.items():
            source=declaration['sources'][name]
            if source['sha256']!=digest or hashlib.sha256(local(source['asset_path']).read_bytes()).hexdigest()!=digest:raise ValueError('Collision source changed: '+name)
        result[kind]=data
    return result
