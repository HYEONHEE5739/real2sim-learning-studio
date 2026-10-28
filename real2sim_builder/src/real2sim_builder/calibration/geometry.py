"""Metric geometry, reference FK and held-out fitting; no control or actuators.

Original Builder algorithm bodies are consolidated here to share native geometry
with USD/MJCF without adding a second geometry layer. See calibration-source.json.
"""
from pathlib import Path
import re
import struct
import numpy as np
from scipy.spatial.transform import Rotation


def mesh_data(path):
    path=Path(path)
    if path.suffix.lower()=='.obj':
        vertices, faces, _ = obj_data(path)
    elif path.suffix.lower()=='.stl':
        data=path.read_bytes()
        count=struct.unpack('<I',data[80:84])[0] if len(data)>=84 else 0
        if len(data)==84+50*count:
            triangles=np.frombuffer(data, dtype=np.dtype([('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attr','<u2')]), offset=84,count=count)['vertices'].astype(float)
        else:
            points=re.findall(rb'vertex\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)',data)
            triangles=np.asarray(points,dtype=float).reshape(-1,3,3)
        vertices=triangles.reshape(-1,3);faces=np.arange(len(vertices)).reshape(-1,3)
    else:
        import trimesh
        mesh=trimesh.load(path,force='mesh',process=False)
        vertices=np.asarray(mesh.vertices);faces=np.asarray(mesh.faces)
    if not len(vertices) or not np.isfinite(vertices).all(): raise ValueError('Invalid mesh vertices')
    return vertices,faces


def parts(obj, field):
    geom=obj[field];kind=geom['type'];dims=np.asarray(obj['dimensions']['value'],float)
    if field=='collision' and not obj.get('collision_enabled',True):return []
    if kind == 'compound':
        from ..project import transform
        result = []
        for part in geom.get('parts', []):
            size = np.asarray(part['dimensions'], float)
            if part['type'] not in ('box','sphere','cylinder') or size.shape != (3,) or not np.isfinite(size).all() or min(size) <= 0:
                raise ValueError('Compound collision requires positive primitive dimensions')
            result.append({**part, 'pose': transform(part['pose']), 'dimensions': size})
        if not result: raise ValueError('Empty compound geometry')
        return result
    if kind in ('box','sphere','cylinder','mesh'):
        return [{**geom,'pose':np.eye(4),'dimensions':dims}]
    if kind!='container':raise ValueError('Unsupported/incomplete geometry: '+obj['id'])
    wall=float(geom['wall']['value']);x,y,z=dims
    def box(size,xyz,angle=0):
        pose=np.eye(4);pose[:3,3]=xyz;pose[:3,:3]=Rotation.from_euler('z',angle).as_matrix()
        return {'type':'box','pose':pose,'dimensions':np.asarray(size)}
    if not geom.get('round',False):
        return [box([x,y,wall],[0,0,-z/2+wall/2]),
            box([wall,y,z],[-(x-wall)/2,0,0]),box([wall,y,z],[(x-wall)/2,0,0]),
            box([x-2*wall,wall,z],[0,-(y-wall)/2,0]),box([x-2*wall,wall,z],[0,(y-wall)/2,0])]
    top=x/2;bottom=float(geom.get('bottom_diameter_m',x))/2
    result=[{'type':'cylinder','pose':np.eye(4),'dimensions':np.array([2*bottom,2*bottom,wall])}]
    result[0]['pose'][2,3]=-z/2+wall/2
    for ring in range(4):
        radius=bottom+(top-bottom)*(ring+.5)/4-wall/2
        for segment in range(32):
            angle=2*np.pi*segment/32
            result.append(box([wall,2*radius*np.tan(np.pi/32)*1.01,z/4],
                [radius*np.cos(angle),radius*np.sin(angle),-z/2+(ring+.5)*z/4],angle))
    return result


def write_stl(path,vertices,faces):
    """Canonical derived mesh snapshot, preserving metre vertices without scaling."""
    path=Path(path)
    with path.open('wb') as stream:
        stream.write(b'Real2Sim derived reference geometry'.ljust(80,b'\0'));stream.write(struct.pack('<I',len(faces)))
        for face in faces:
            triangle=np.asarray(vertices)[face]
            normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0]);length=np.linalg.norm(normal)
            normal=normal/length if length else np.zeros(3)
            stream.write(struct.pack('<12fH',*normal,*triangle.ravel(),0))


def obj_data(path):
    """Triangulated OBJ with expanded corners, preserving UV seams for both exporters."""
    source=[]; uv=[]; vertices=[]; texcoords=[]; faces=[]
    for line in Path(path).read_text().splitlines():
        row=line.split()
        if not row: continue
        if row[0]=='v': source.append([float(x) for x in row[1:4]])
        elif row[0]=='vt': uv.append([float(x) for x in row[1:3]])
        elif row[0]=='f':
            corners=row[1:]
            for i in range(1,len(corners)-1):
                face=[]
                for token in (corners[0],corners[i],corners[i+1]):
                    indexes=token.split('/'); vi=int(indexes[0]); face.append(len(vertices))
                    vertices.append(source[vi-1 if vi>0 else vi])
                    ti=int(indexes[1]) if len(indexes)>1 and indexes[1] else 0
                    texcoords.append(uv[ti-1 if ti>0 else ti] if ti else [0.,0.])
                faces.append(face)
    if not vertices: raise ValueError('OBJ has no faces')
    return np.asarray(vertices),np.asarray(faces),np.asarray(texcoords)


import xml.etree.ElementTree as ET
from ..project import transform, value


def origin(node):
    t = np.eye(4)
    if node is not None:
        t[:3,3] = np.fromstring(node.get('xyz','0 0 0'), sep=' ')
        t[:3,:3] = Rotation.from_euler('xyz', np.fromstring(node.get('rpy','0 0 0'), sep=' ')).as_matrix()
    return t


def simulation_offsets(model):
    node=model.get('simulation_joint_offsets_rad')
    if node is None:return np.zeros(len(model['joint_names']))
    from ..project import checked_value
    offsets=np.asarray(checked_value(node),float)
    if offsets.shape!=(len(model['joint_names']),) or not np.isfinite(offsets).all() or np.any(abs(offsets)>.35):
        raise ValueError('Finite bounded named simulation joint offsets required')
    if node['provenance'] not in ('estimated','optimized') or not node.get('evidence'):
        raise ValueError('Simulation joint offsets are an evidence-backed unvalidated hypothesis')
    if 'precision_mapping_sha256' in node:
        import re
        reference = node['precision_mapping_sha256']
        mapping = model.get('mapping', {})
        if (not isinstance(reference, str) or not re.fullmatch(r'[0-9a-f]{64}', reference)
                or mapping.get('schema') != 'so101.precision-joint-mapping/1'
                or reference != mapping.get('sha256')):
            raise ValueError('Simulation residual requires its recorded Precision mapping')
    return offsets


def link_transforms(urdf, joints):
    if Path(urdf).suffix.lower() in ('.xml','.mjcf'):
        import mujoco
        model=mujoco.MjModel.from_xml_path(str(urdf));data=mujoco.MjData(model)
        names=[]
        for index in range(model.njnt):
            name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,index);names.append(name)
            if model.jnt_type[index] not in (mujoco.mjtJoint.mjJNT_HINGE,mujoco.mjtJoint.mjJNT_SLIDE):raise ValueError('Capture FK requires scalar named MJCF joints')
            if name not in joints or not np.isfinite(joints[name]):raise ValueError('Missing/nonfinite MJCF measured joint: '+str(name))
            data.qpos[model.jnt_qposadr[index]]=joints[name]
        if set(joints)!=set(names):raise ValueError('Measured joint names differ from model')
        mujoco.mj_forward(model,data);poses={}
        for index in range(model.nbody):
            name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,index) or 'body_'+str(index)
            t=np.eye(4);t[:3,:3]=data.xmat[index].reshape(3,3);t[:3,3]=data.xpos[index];poses[name]=t
        return poses
    root = ET.parse(urdf).getroot()
    expected={j.get('name') for j in root.findall('joint') if j.get('type')!='fixed'}
    if set(joints)!=expected:raise ValueError('Measured joint names differ from model')
    edges = root.findall('joint'); children = {j.find('child').get('link') for j in edges}
    roots = {l.get('name') for l in root.findall('link')} - children
    if len(roots) != 1: raise ValueError('URDF must be a single tree')
    poses = {next(iter(roots)):np.eye(4)}
    pending = list(edges)
    while pending:
        before = len(pending)
        for joint in pending[:]:
            parent = joint.find('parent').get('link'); child = joint.find('child').get('link')
            if parent not in poses: continue
            kind = joint.get('type'); motion = np.eye(4)
            if kind != 'fixed':
                if joint.get('name') not in joints: raise ValueError('Reference joint state missing: '+joint.get('name'))
                q = float(joints[joint.get('name')])
                if not np.isfinite(q): raise ValueError('Nonfinite joint state')
                axis_node = joint.find('axis')
                axis = np.fromstring(axis_node.get('xyz','1 0 0') if axis_node is not None else '1 0 0', sep=' ')
                if np.linalg.norm(axis) == 0: raise ValueError('Zero joint axis')
                axis /= np.linalg.norm(axis)
                if kind in ('revolute','continuous'): motion[:3,:3] = Rotation.from_rotvec(axis*q).as_matrix()
                elif kind == 'prismatic': motion[:3,3] = axis*q
                else: raise ValueError('Unsupported reference joint: '+kind)
            poses[child] = poses[parent] @ origin(joint.find('origin')) @ motion
            pending.remove(joint)
        if before == len(pending): raise ValueError('Cyclic/disconnected URDF')
    return poses


def reference_geometry(urdf, joints, import_asset, frame='robot_base', recorded_links=None):
    root = ET.parse(urdf).getroot()
    poses = {k:transform(v) for k,v in recorded_links.items()} if recorded_links else link_transforms(urdf,joints)
    result = []
    for link in root.findall('link'):
        for i, visual in enumerate(link.findall('visual')):
            geometry = visual.find('geometry'); mesh = geometry.find('mesh')
            if link.get('name') not in poses: raise ValueError('Missing reference FK link')
            if mesh is not None:
                path = mesh.get('filename')
                if path.startswith('package://'): raise ValueError('Resolve package:// meshes explicitly before import')
                source = (Path(urdf).parent/path).resolve()
                scale = np.fromstring(mesh.get('scale','1 1 1'),sep=' ').tolist()
                geom = {'type':'mesh','asset':import_asset(source),'scale':scale}
                
                vertices,_ = mesh_data(source)
                dims = np.maximum(np.ptp(vertices*np.asarray(scale),axis=0),1e-8).tolist()
            else:
                box=geometry.find('box'); sphere=geometry.find('sphere'); cylinder=geometry.find('cylinder')
                if box is not None: dims=np.fromstring(box.get('size'),sep=' ').tolist(); geom={'type':'box'}
                elif sphere is not None: dims=[2*float(sphere.get('radius'))]*3; geom={'type':'sphere'}
                elif cylinder is not None: dims=[2*float(cylinder.get('radius'))]*2+[float(cylinder.get('length'))]; geom={'type':'cylinder'}
                else: raise ValueError('Unsupported URDF visual')
            color=visual.find('material/color')
            rgb=np.fromstring(color.get('rgba'),sep=' ')[:3].tolist() if color is not None else [.55,.3,.8]
            result.append({'id':'robot_'+link.get('name')+'_'+str(i),'role':'reference_robot','frame':frame,
                'pose':value((poses[link.get('name')]@origin(visual.find('origin'))).tolist(),'derived',[str(urdf)]),
                'dimensions':value(dims,'derived',[str(urdf)]),'visual':geom,'collision':{'type':'unknown'},
                'color':value(rgb,'estimated'),'physics':{'mass_kg':value(None),'friction':value(None)},
                'collision_enabled':False,'link':link.get('name'),
                'link_local_pose':origin(visual.find('origin')).tolist()})
    return result,poses


def reference_model(path,joints,import_asset,scratch):
    """MJCF/USD reference snapshots. Derive geometry, never import control/task code."""
    
    path=Path(path);scratch=Path(scratch);scratch.mkdir(parents=True,exist_ok=True);objects=[]
    def append(name,vertices,faces,t,color):
        mesh=scratch/(name+'.stl');write_stl(mesh,vertices,faces);asset=import_asset(mesh)
        dimensions=np.maximum(np.ptp(vertices,axis=0),1e-8).tolist()
        objects.append({'id':name,'role':'reference_robot','frame':'robot_base','pose':value(t.tolist(),'derived',[str(path)]),
            'dimensions':value(dimensions,'derived',[str(path)]),'visual':{'type':'mesh','asset':asset},'collision':{'type':'unknown'},
            'collision_enabled':False,'color':value(color,'derived',[str(path)]),'physics':{'mass_kg':value(None),'friction':value(None)}})
    import trimesh
    poses={'root':np.eye(4)}
    if path.suffix.lower() in ('.xml','.mjcf'):
        import mujoco
        model=mujoco.MjModel.from_xml_path(str(path));data=mujoco.MjData(model)
        for j in range(model.njnt):
            name=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_JOINT,j)
            if model.jnt_type[j] not in (mujoco.mjtJoint.mjJNT_HINGE,mujoco.mjtJoint.mjJNT_SLIDE):raise ValueError('MJCF reference requires scalar joints or a baked static model')
            if name not in joints:raise ValueError('Reference joint state missing: '+str(name))
            data.qpos[model.jnt_qposadr[j]]=float(joints[name])
        mujoco.mj_forward(model,data)
        poses=link_transforms(path,joints)
        for i in range(model.ngeom):
            size=model.geom_size[i];kind=model.geom_type[i]
            if kind==mujoco.mjtGeom.mjGEOM_MESH:
                m=model.geom_dataid[i];v=model.mesh_vertadr[m];f=model.mesh_faceadr[m]
                vertices=model.mesh_vert[v:v+model.mesh_vertnum[m]];faces=model.mesh_face[f:f+model.mesh_facenum[m]]
            elif kind==mujoco.mjtGeom.mjGEOM_BOX:
                mesh=trimesh.creation.box(extents=2*size);vertices,faces=mesh.vertices,mesh.faces
            elif kind==mujoco.mjtGeom.mjGEOM_SPHERE:
                mesh=trimesh.creation.icosphere(subdivisions=2,radius=size[0]);vertices,faces=mesh.vertices,mesh.faces
            elif kind==mujoco.mjtGeom.mjGEOM_CYLINDER:
                mesh=trimesh.creation.cylinder(radius=size[0],height=2*size[1]);vertices,faces=mesh.vertices,mesh.faces
            elif kind==mujoco.mjtGeom.mjGEOM_CAPSULE:
                mesh=trimesh.creation.capsule(radius=size[0],height=2*size[1]);vertices,faces=mesh.vertices,mesh.faces
            else:raise ValueError('Unsupported MJCF reference visual geom: '+str(kind))
            t=np.eye(4);t[:3,3]=data.geom_xpos[i];t[:3,:3]=data.geom_xmat[i].reshape(3,3)
            append('reference_geom_'+str(i),vertices,faces,t,model.geom_rgba[i,:3].tolist())
            body=int(model.geom_bodyid[i]);objects[-1]['link']=mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_BODY,body) or 'body_'+str(body)
    elif path.suffix.lower() in ('.usd','.usda','.usdc'):
        if joints:raise ValueError('USD references must be baked poses; use URDF/MJCF for joint FK')
        from pxr import Usd,UsdGeom
        stage=Usd.Stage.Open(str(path))
        if stage is None:raise ValueError('Cannot open USD reference')
        scale=UsdGeom.GetStageMetersPerUnit(stage);up=UsdGeom.GetStageUpAxis(stage)
        conversion=np.eye(3) if up=='Z' else Rotation.from_euler('x',90,degrees=True).as_matrix()
        for prim in stage.Traverse():
            if not prim.IsA(UsdGeom.Gprim) or prim.GetAttribute('visibility').Get()=='invisible':continue
            if prim.IsA(UsdGeom.Mesh):
                geom=UsdGeom.Mesh(prim);vertices=np.asarray(geom.GetPointsAttr().Get(),float);indices=list(geom.GetFaceVertexIndicesAttr().Get());counts=list(geom.GetFaceVertexCountsAttr().Get());faces=[];offset=0
                for count in counts:
                    polygon=indices[offset:offset+count];offset+=count
                    faces.extend([[polygon[0],polygon[j],polygon[j+1]] for j in range(1,count-1)])
                faces=np.asarray(faces,int)
            elif prim.IsA(UsdGeom.Cube):
                mesh=trimesh.creation.box(extents=[UsdGeom.Cube(prim).GetSizeAttr().Get()]*3);vertices,faces=mesh.vertices,mesh.faces
            elif prim.IsA(UsdGeom.Sphere):
                mesh=trimesh.creation.icosphere(subdivisions=2,radius=UsdGeom.Sphere(prim).GetRadiusAttr().Get());vertices,faces=mesh.vertices,mesh.faces
            elif prim.IsA(UsdGeom.Cylinder):
                geom=UsdGeom.Cylinder(prim)
                if geom.GetAxisAttr().Get()!='Z':raise ValueError('USD reference cylinder requires Z axis')
                mesh=trimesh.creation.cylinder(radius=geom.GetRadiusAttr().Get(),height=geom.GetHeightAttr().Get());vertices,faces=mesh.vertices,mesh.faces
            else:raise ValueError('Unsupported USD reference Gprim: '+prim.GetTypeName())
            t=np.asarray(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T
            vertices=(np.c_[vertices,np.ones(len(vertices))]@t.T)[:,:3]*scale;vertices=vertices@conversion.T
            color=UsdGeom.Gprim(prim).GetDisplayColorAttr().Get();rgb=list(color[0]) if color else [.6,.6,.6]
            append('reference_geom_'+str(len(objects)),vertices,faces,np.eye(4),rgb)
    else:raise ValueError('Reference model must be URDF, MJCF/XML or USD')
    if not objects:raise ValueError('Reference model has no supported geometry')
    return objects,poses


import copy
from scipy.optimize import least_squares
from ..project import observation_scene
from ..project import value,cameras_audited,camera_calibration_signature
from .camera import project_point


def metrics(project,scene,rows):
    observations={i.get('id'):i for i in project.evidence['images'] if i.get('id')}
    grouped={};errors=[];behind=0
    for row in rows:
        if row.get('visible',True) is False or row.get('weight',1)<=0:continue
        image=observations[row['observation']]
        if not image.get('eligible',False):continue
        posed=observation_scene(scene,image,project.root,complete=False);camera=next(c for c in posed['cameras'] if c['id']==image['camera'])
        uv,z=project_point(posed,camera,row);err=float(np.linalg.norm(uv-np.asarray(row['uv'])))
        errors.append(err);behind+=int(z<=0);grouped.setdefault(image['id'],[]).append(err)
    return {'count':len(errors),'rmse_px':float(np.sqrt(np.mean(np.square(errors)))) if errors else None,'behind_camera':behind,
            'per_observation':{k:float(np.sqrt(np.mean(np.square(v)))) for k,v in grouped.items()}}


def fit(project,scene,target,options=None):
    options=options or {}
    candidate=copy.deepcopy(scene);kind,name=target.split(':',1)
    registration=scene.get('scan_initialization',{}).get('registration')
    if registration and (registration.get('status')=='NEEDS_MORE_DATA' or not registration.get('metric_scale_verified')):
        return scene,{'status':'NEEDS_MORE_DATA','need':'Register scan to metric robot world before camera/image optimization'}
    if kind=='bootstrap':
        return bootstrap(project,scene,name,options)
    if kind=='quality':
        return assess_camera(project,scene,name,options)
    if kind in ('camera','intrinsics','distortion'):
        node=next(c for c in candidate['cameras'] if c['id']==name);field='K' if kind=='intrinsics' else 'distortion' if kind=='distortion' else 'pose'
    elif kind=='base':node=candidate['frames'][name];field='transform'
    elif kind in ('object','dimensions'):
        node=next(o for o in candidate['objects'] if o['id']==name);field='dimensions' if kind=='dimensions' else 'pose'
        if scene.get('scan_initialization'):
            if not cameras_audited(scene):
                return scene,{'status':'NEEDS_MORE_DATA','need':'Camera calibration confidence must be established before scan object pixel refinement'}
    else:raise ValueError('Fit one camera/intrinsics/base/object/dimensions group')
    if node[field]['provenance'] in ('measured','calibrated'):raise ValueError('Measured/calibrated parameter locked')
    observations={i.get('id'):i for i in project.evidence['images'] if i.get('id')}
    rows=[r for r in project.evidence['landmarks'] if r.get('observation') in observations and observations[r['observation']]['eligible'] and r.get('visible',True) and r.get('weight',1)>0]
    if kind in ('camera','intrinsics','distortion'):rows=[r for r in rows if observations[r['observation']]['camera']==name]
    train=[r for r in rows if observations[r['observation']]['split']=='train'];held=[r for r in rows if observations[r['observation']]['split']=='validation']
    groups={observations[r['observation']]['group_id'] for r in train};hold_groups={observations[r['observation']]['group_id'] for r in held}
    if groups & hold_groups:raise ValueError('Train/holdout group leakage')
    poses={tuple(observations[r['observation']]['q_measured']) for r in train}
    if len(poses)<2 or len(train)<8 or not held:
        return scene,{'status':'NEEDS_MORE_DATA','need':'Two distinct measured poses with >=8 train landmarks and independent held-out pose landmarks'}
    if field=='distortion':
        camera_points=np.array([r['uv'] for r in train],float);k=np.asarray(node['K']['value'])
        radial=np.linalg.norm((camera_points-k[:2,2])/np.array([k[0,0],k[1,1]]),axis=1)
        if np.max(radial)<.5 or np.ptp(radial)<.25:
            return scene,{'status':'NEEDS_MORE_DATA','need':'Peripheral and central correspondences are required before radial distortion fitting'}
        seed=np.array([node['distortion']['value'][0]]);radius=np.array([.2])
        def assign(x):
            node[field]['value']=list(node[field]['value']);node[field]['value'][0]=float(x[0])
    elif field=='K':
        k=np.asarray(node[field]['value']);seed=np.array([k[0,0],k[1,1],k[0,2],k[1,2]]);radius=np.array([seed[0]*.2,seed[1]*.2,30,30])
        def assign(x):node[field]['value']=[[float(x[0]),0,float(x[2])],[0,float(x[1]),float(x[3])],[0,0,1]]
    elif field=='dimensions':
        seed=np.asarray(node[field]['value']);radius=seed*.2
        def assign(x):node[field]['value']=x.tolist()
    else:
        t=np.asarray(node[field]['value']);seed=np.r_[t[:3,3],Rotation.from_matrix(t[:3,:3]).as_rotvec()];radius=np.r_[[.1]*3,[.4]*3]
        def assign(x):
            t=np.eye(4);t[:3,3]=x[:3];t[:3,:3]=Rotation.from_rotvec(x[3:]).as_matrix();node[field]['value']=t.tolist()
    def residual(x):
        assign(x);result=[]
        for row in train:
            image=observations[row['observation']];posed=observation_scene(candidate,image,project.root,complete=False)
            camera=next(c for c in posed['cameras'] if c['id']==image['camera'])
            uv,z=project_point(posed,camera,row);weight=np.sqrt(row.get('weight',1.))
            result.extend((uv-np.asarray(row['uv']))*weight);result.append(max(0,.001-z)*10000)
        return result
    before=metrics(project,scene,train);hold_before=metrics(project,scene,held)
    solution=least_squares(residual,seed,bounds=(seed-radius,seed+radius),loss='soft_l1',max_nfev=100)
    singular=np.linalg.svd(solution.jac*radius[None,:],compute_uv=False)
    rank=int(np.linalg.matrix_rank(solution.jac));assign(solution.x)
    condition=float(singular[0]/singular[-1]) if singular[-1]>1e-12 else None
    variance=float(np.sum(solution.fun**2)/max(1,len(solution.fun)-len(seed)))
    covariance=np.linalg.pinv(solution.jac.T@solution.jac)*variance
    after=metrics(project,candidate,train);hold_after=metrics(project,candidate,held)
    report={'target':target,'scaled_jacobian_singular_values':singular.tolist(),'condition_number':condition,
            'uncertainty_std':np.sqrt(np.maximum(0,np.diag(covariance))).tolist(),'uncertainty_scope':'local linearized robust residual; not hardware confidence',
            'bounds':{'lower':(seed-radius).tolist(),'upper':(seed+radius).tolist()},'jacobian_rank':rank,'parameter_count':len(seed),'train_before':before,'train_after':after,
            'holdout_before':hold_before,'holdout_after':hold_after,'scope':'KINEMATIC_REPLAY_ONLY','physics_status':'PHYSICS_NOT_VALIDATED'}
    if rank<len(seed) or condition is None or condition>1e8:return scene,{**report,'status':'NEEDS_MORE_DATA','need':'Independent non-collinear measured landmarks and more diverse poses; parameter group is unobservable'}
    if after['rmse_px']>=before['rmse_px']-1e-6 or hold_after['rmse_px']>hold_before['rmse_px']+1e-6 or hold_after['behind_camera']:
        return scene,{**report,'status':'REJECTED','reason':'Train did not improve or independent holdout regressed'}
    node[field]['provenance']='optimized';node[field]['evidence'].append('multi-pose train-only robust landmark fit; independent holdout checked')
    return candidate,{**report,'status':'IMPROVED'}


def bootstrap(project,scene,name,options):
    """Train-only multi-start pinhole K+shared pose initialization, one holdout test.

    This extends the existing robust reprojection fitter. It does not create
    per-snapshot camera transforms or fit geometry to compensate for K.
    """
    import cv2
    from .camera import point_world
    from ..project import frame_world
    candidate=copy.deepcopy(scene);node=next(c for c in candidate['cameras'] if c['id']==name)
    if node['K']['provenance'] in ('measured','calibrated') or node['pose']['provenance'] in ('measured','calibrated'):
        raise ValueError('Bootstrap requires unknown/estimated K and pose; use scoped fitting for unlocked fields')
    images={i['id']:i for i in project.evidence['images'] if i.get('id') and i.get('eligible') and i['camera']==name and i.get('role')!='reference_context'}
    rows=[r for r in project.evidence['landmarks'] if r.get('observation') in images and r.get('visible',True) and r.get('weight',1)>0]
    train=[r for r in rows if images[r['observation']]['split']=='train'];held=[r for r in rows if images[r['observation']]['split']=='validation']
    train_groups={images[r['observation']]['group_id'] for r in train};held_groups={images[r['observation']]['group_id'] for r in held}
    if train_groups & held_groups:raise ValueError('Train/holdout group leakage')
    wrist=node['frame'].startswith('robot_link_')
    observations=sorted({r['observation'] for r in train})
    poses={tuple(images[i].get('q_measured',[])) for i in observations}
    base_report={'target':'bootstrap:'+name,'camera':name,'scope':'PINHOLE_SHARED_K_AND_MOUNT' if wrist else 'PINHOLE_FIXED_CAMERA',
                 'holdout_used_for_seed_selection':False,'physics_status':'PHYSICS_NOT_VALIDATED'}
    def need(reason,**extra):return scene,{**base_report,**extra,'status':'NEEDS_MORE_DATA','need':reason}
    if len(train)<12 or len(held)<4 or (wrist and len(poses)<3):
        return need('>=12 train and >=4 independent holdout landmarks; Wrist additionally needs >=3 diverse measured poses')
    # Bootstrap needs stable metric anchors, not unconstrained object estimates.
    for row in train+held:
        if row.get('object'):
            obj=next(o for o in scene['objects'] if o['id']==row['object'])
            if any(obj[k]['provenance'] not in ('measured','calibrated') for k in ('pose','dimensions')):
                return need('Measured object pose/dimensions required for camera anchors; isolate object refinement')
        if row.get('source')=='registered_scan' and not scene.get('scan_initialization',{}).get('registration',{}).get('metric_scale_verified'):
            return need('Scan landmarks require metric world registration')
    # Pose camera-frame points once per measured q. q is never adjusted.
    point_sets={};points=[]
    for row in train:
        posed=observation_scene(candidate,images[row['observation']],project.root,complete=False)
        point=point_world(posed,row);points.append(point)
        parent=frame_world(posed,node['frame'])
        local=(np.linalg.inv(parent)@np.r_[point,1])[:3]
        point_sets.setdefault(row['observation'],[]).append((local,row))
    points=np.asarray(points);sv=np.linalg.svd(points-points.mean(0),compute_uv=False)
    if sv[-1]<max(sv[0]*1e-3,1e-6):
        return need('Noncoplanar metric anchors at multiple depths; planar K/depth/translation ambiguity is unresolved',point_singular_values=sv.tolist())
    if wrist:
        parents=[frame_world(observation_scene(candidate,images[i],project.root,complete=False),node['frame']) for i in observations]
        angles=[Rotation.from_matrix(a[:3,:3].T@b[:3,:3]).magnitude() for a in parents for b in parents]
        if max(angles)<np.deg2rad(10):return need('Wrist mount initialization needs robot orientation diversity >10 degrees')
    w,h=node['resolution'];fovs=options.get('fov_seeds_deg',[40.,60.,80.])
    if not fovs or len(fovs)>8 or any(not 15<=float(f)<=140 for f in fovs):raise ValueError('FOV seeds must be 15..140 degrees, at most 8')
    original=copy.deepcopy(node);aspect=float(options.get('aspect_ratio',1.))
    if not np.isfinite(aspect) or not .5<=aspect<=2:raise ValueError('Bounded positive fy/fx aspect required')
    # Principal point fixed to image center for stable bootstrap. Later intrinsics group unlocks it.
    def assign(x):
        t=np.eye(4);t[:3,3]=x[1:4];t[:3,:3]=Rotation.from_rotvec(x[4:]).as_matrix()
        node['pose']=value(t.tolist(),'estimated');node['K']=value([[float(x[0]),0,w/2],[0,float(x[0]*aspect),h/2],[0,0,1]],'estimated')
        node['distortion']=value([0.]*5,'estimated')
    def residual(x):
        assign(x);result=[]
        inv=np.linalg.inv(np.asarray(node['pose']['value']))
        for observation,entries in point_sets.items():
            for p,row in entries:
                q=(inv@np.r_[p,1])[:3];z=max(q[2],1e-6)
                uv=[x[0]*q[0]/z+w/2,x[0]*aspect*q[1]/z+h/2]
                confidence=.25 if row.get('source') in ('estimated','registered_scan') else 1.
                result.extend((np.asarray(uv)-row['uv'])*np.sqrt(row.get('weight',1)*confidence))
                result.append(max(0,.001-q[2])*1e4)
        return np.asarray(result)
    solutions=[]
    for fov in fovs:
        focal=w/(2*np.tan(np.deg2rad(fov)/2));k=np.array([[focal,0,w/2],[0,focal*aspect,h/2],[0,0,1]])
        for obs,entries in point_sets.items():
            if len(entries)<6:continue
            xx=np.asarray([p for p,_ in entries]);uv=np.asarray([r['uv'] for _,r in entries],float)
            ok,rv,tv=cv2.solvePnP(xx,uv,k,np.zeros(5),flags=cv2.SOLVEPNP_SQPNP)
            if not ok:continue
            extrinsic=np.eye(4);extrinsic[:3,:3]=cv2.Rodrigues(rv)[0];extrinsic[:3,3]=tv.ravel();pose=np.linalg.inv(extrinsic)
            x=np.r_[focal,pose[:3,3],Rotation.from_matrix(pose[:3,:3]).as_rotvec()]
            lower=np.r_[w/(2*np.tan(np.deg2rad(140)/2)),x[1:4]-.5,x[4:]-1.5]
            upper=np.r_[w/(2*np.tan(np.deg2rad(15)/2)),x[1:4]+.5,x[4:]+1.5]
            solution=least_squares(residual,x,bounds=(lower,upper),loss='soft_l1',max_nfev=150,x_scale='jac')
            solutions.append((float(np.mean(residual(solution.x)**2)),solution,lower,upper))
            break  # one reproducible train pose seeds each FOV, never held-out selection
    if not solutions:return need('At least six metric correspondences in a training observation for PnP seed')
    _,solution,lower,upper=min(solutions,key=lambda r:r[0]);assign(solution.x)
    radius=(upper-lower)/2;singular=np.linalg.svd(solution.jac*radius[None,:],compute_uv=False)
    rank=int(np.count_nonzero(singular>singular[0]*1e-7));condition=float(singular[0]/max(singular[-1],1e-30))
    variance=float(np.sum(solution.fun**2)/max(1,len(solution.fun)-7))
    std=np.sqrt(np.maximum(0,np.diag(np.linalg.pinv(solution.jac.T@solution.jac)*variance)))
    fitted=metrics(project,candidate,train)
    report={**base_report,'train_after':fitted,'parameter_names':['fx_shared_fy_ratio','tx','ty','tz','rx','ry','rz'],
        'fixed_parameters':['aspect_ratio','cx','cy','distortion'],'fov_seeds_deg':fovs,'selected_by':'train reprojection only',
        'point_singular_values':sv.tolist(),'jacobian_rank':rank,'parameter_count':7,'condition_number':condition,
        'uncertainty_std':std.tolist(),'uncertainty_scope':'local linearization; not physical certification',
        'bounds':{'lower':lower.tolist(),'upper':upper.tolist()},'seed_train_costs':[r[0] for r in solutions]}
    if rank<7 or condition>1e7 or np.max(std/radius)>.25 or fitted['behind_camera']:
        return need('K/depth/translation or principal point/rotation ambiguity: add metric depths and pose diversity',**report)
    held_metrics=metrics(project,candidate,held);report['holdout_after']=held_metrics
    if held_metrics['behind_camera'] or held_metrics['rmse_px']>float(options.get('reprojection_px',5.)):
        return scene,{**report,'status':'REJECTED','reason':'Independent holdout failed; do not search seeds using this holdout'}
    sessions={images[r['observation']].get('session_id') for r in train}
    held_sessions={images[r['observation']].get('session_id') for r in held}
    independent=bool(held_sessions and None not in held_sessions and not sessions & held_sessions)
    anchors_verified=all(r.get('source') in ('measured','calibrated','verified') and r.get('evidence') for r in train+held)
    mapping_verified=not wrist or bool(scene.get('robot_model',{}).get('mapping_verified'))
    # Bootstrap leaves cx/cy/aspect/distortion uncalibrated. Full K remains ESTIMATED.
    node['K']['provenance']='optimized';node['pose']['provenance']='optimized'
    for key in ('K','pose'):node[key]['evidence']=['train-only pinhole initialization; holdout checked']
    node['calibration_quality']={'state':'ESTIMATED','intrinsic_state':'ESTIMATED','extrinsic_state':'ESTIMATED',
        'fixed_unverified_parameters':['aspect_ratio','cx','cy','distortion'], 'independent_session_holdout':independent,
        'metric_anchors_verified':anchors_verified,'robot_mapping_verified':mapping_verified,
        'holdout_rmse_px':held_metrics['rmse_px'],'scope':report['scope'],'physical_verified':False}
    return candidate,{**report,'status':'IMPROVED','calibration_quality':node['calibration_quality'],
        'holdout_observations':sorted({r['observation'] for r in held}),
        'additional_evidence':['Verify principal point/aspect, peripheral distortion and independent metric poses before CALIBRATED']}


def assess_camera(project,scene,name,options):
    """No fitting: audit full pinhole K + shared extrinsic on fixed metric evidence."""
    from .camera import point_world
    from ..project import frame_world
    candidate=copy.deepcopy(scene);node=next(c for c in candidate['cameras'] if c['id']==name)
    images={i['id']:i for i in project.evidence['images'] if i.get('id') and i.get('eligible') and i['camera']==name and i.get('role')!='reference_context'}
    rows=[r for r in project.evidence['landmarks'] if r.get('observation') in images and r.get('visible',True) and r.get('weight',1)>0]
    train=[r for r in rows if images[r['observation']]['split']=='train'];held=[r for r in rows if images[r['observation']]['split']=='validation']
    def missing(need,**extra):return scene,{**extra,'status':'NEEDS_MORE_DATA','target':'quality:'+name,'need':need}
    if len(train)<12 or len(held)<6:return missing('At least 12 train and 6 independent-session verification landmarks required')
    journal=project.root/'working/calibration_holdout_usage.jsonl'
    if journal.exists():
        import json
        used={identity for line in journal.read_text().splitlines() for identity in json.loads(line).get('holdout_observations',[])}
        if used & {r['observation'] for r in held}:return missing('Final calibration audit needs fresh holdout images not used in previous candidate/seed review')
    if {images[r['observation']].get('session_id') for r in train} & {images[r['observation']].get('session_id') for r in held}:
        return missing('Holdout must be from a separately collected session, not adjacent frames')
    if any(not images[r['observation']].get('session_id') for r in rows):return missing('Explicit independent session identity is required')
    if any(r.get('source') not in ('measured','calibrated','verified') or not r.get('evidence') for r in rows):
        return missing('Verified metric anchors with explicit evidence are required')
    for r in rows:
        if r.get('object'):
            obj=next(o for o in scene['objects'] if o['id']==r['object'])
            if any(obj[k]['provenance'] not in ('measured','calibrated') for k in ('pose','dimensions')):return missing('Metric object anchors must be locked and measured')
    if node['frame'].startswith('robot_link_') and not scene.get('robot_model',{}).get('mapping_verified'):
        return missing('Wrist FK/joint mapping is manually estimated; camera physical calibration remains unverified')
    if node['K']['value'] is None or node['pose']['value'] is None:return missing('Initialize camera first')
    k=np.asarray(node['K']['value']);t=np.asarray(node['pose']['value'])
    x=np.r_[k[0,0],k[1,1],k[0,2],k[1,2],t[:3,3],Rotation.from_matrix(t[:3,:3]).as_rotvec()]
    def residual(params):
        proposal=copy.deepcopy(scene);camera=next(c for c in proposal['cameras'] if c['id']==name)
        camera['K']['value']=[[params[0],0,params[2]],[0,params[1],params[3]],[0,0,1]]
        pose=np.eye(4);pose[:3,3]=params[4:7];pose[:3,:3]=Rotation.from_rotvec(params[7:]).as_matrix();camera['pose']['value']=pose.tolist()
        result=[]
        for r in train:
            posed=observation_scene(proposal,images[r['observation']],project.root,complete=False)
            uv,z=project_point(posed,camera,r);result.extend(uv-r['uv'])
        return np.asarray(result)
    scale=np.r_[x[:2]*.2,[30,30],[.1]*3,[.4]*3];step=np.maximum(abs(x)*1e-6,1e-6)
    jac=np.column_stack([(residual(x+np.eye(10)[i]*step[i])-residual(x-np.eye(10)[i]*step[i]))/(2*step[i]) for i in range(10)])
    singular=np.linalg.svd(jac*scale[None,:],compute_uv=False)
    rank=int(np.count_nonzero(singular>singular[0]*1e-7));condition=float(singular[0]/max(singular[-1],1e-30))
    variance=max(float(options.get('pixel_uncertainty_px',1.))**2,float(np.mean(residual(x)**2)))
    if not np.isfinite(variance) or variance<=0:raise ValueError('Positive finite pixel uncertainty required')
    std=np.sqrt(np.maximum(0,np.diag(np.linalg.pinv(jac.T@jac)*variance)))
    if rank<10 or condition>1e7 or np.max(std/scale)>.25:return missing('Full K/pose remains unobservable or uncertain; supply noncoplanar depths and broader image coverage',jacobian_rank=rank,condition_number=condition,uncertainty_std=std.tolist())
    before=metrics(project,scene,train);validation=metrics(project,scene,held)
    if validation['behind_camera'] or validation['rmse_px']>float(options.get('reprojection_px',5.)):
        return scene,{'status':'REJECTED','target':'quality:'+name,'holdout_after':validation}
    node['calibration_quality']={'state':'CALIBRATED','intrinsic_state':'CALIBRATED','extrinsic_state':'CALIBRATED',
        'scope':'independent metric reprojection pinhole audit; not external physical certification',
        'independent_session_holdout':True,'physical_verified':False,'distortion_state':'ESTIMATED',
        'robot_mapping_verified':bool(scene.get('robot_model',{}).get('mapping_verified')),
        'holdout_rmse_px':validation['rmse_px'],'jacobian_rank':rank}
    node['calibration_quality']['input_sha256']=camera_calibration_signature(candidate,node)
    return candidate,{'status':'IMPROVED','target':'quality:'+name,'train_after':before,'holdout_after':validation,
        'jacobian_rank':rank,'condition_number':condition,'uncertainty_std':std.tolist(),'calibration_quality':node['calibration_quality'],
        'holdout_observations':sorted({r['observation'] for r in held}),'holdout_used_for_fitting':False}


from PIL import Image
from ..project import frame_world, world_pose, local_path, value


def array(path):
    if path.suffix.lower() == '.npy':
        return np.load(path, allow_pickle=False)
    if path.suffix.lower() == '.npz':
        with np.load(path, allow_pickle=False) as stored:
            if len(stored.files) != 1:
                raise ValueError('Cloud/depth NPZ must contain one named array')
            return stored[stored.files[0]]
    return np.loadtxt(path)


def fit_depth_geometry(scene, evidence, root):
    """Partial observations yield bounds only; full extents need explicit coverage."""
    candidate = copy.deepcopy(scene)
    reports = []
    observations = [('cloud', r) for r in evidence.get('point_clouds', [])]
    observations += [('depth', r) for r in evidence.get('depths', [])]
    for kind, row in observations:
        if row.get('split', 'train') != 'train':
            continue
        if not row.get('object'):
            raise ValueError('Depth/cloud bounds need a segmented object ID')
        obj = next(o for o in candidate['objects'] if o['id'] == row['object'])
        pixels = array(local_path(root, row['path'])).astype(float)
        if pixels.size > 6_000_000:
            raise ValueError('Downsample depth/cloud observations to at most two million points/pixels')
        if kind == 'cloud':
            if pixels.ndim != 2 or pixels.shape[1] != 3:
                raise ValueError('Point cloud must be N x 3 XYZ in metres')
            points = pixels[np.isfinite(pixels).all(axis=1)]
            reference = frame_world(candidate, row.get('frame', 'world'))
        else:
            camera = next(c for c in candidate['cameras'] if c['id'] == row['camera'])
            if camera['K']['value'] is None or camera['pose']['value'] is None:
                reports.append({'object':obj['id'],'decision':'NEEDS_MORE_DATA','need':'calibrated camera intrinsics/pose for metric depth'})
                continue
            if pixels.shape != tuple(camera['resolution'][::-1]):
                raise ValueError('Depth and camera resolutions differ')
            if np.any(camera.get('original_distortion', camera['distortion'])['value']):
                raise ValueError('Rectify depth with its calibrated RGB stream before import')
            if not row.get('mask'):
                raise ValueError('Depth geometry requires an explicit segmented object mask')
            selection = np.asarray(Image.open(local_path(root, row['mask'])).convert('L')) > 0
            if selection.shape != pixels.shape:
                raise ValueError('Depth mask resolution differs')
            selection &= np.isfinite(pixels) & (pixels > 0)
            y, x = np.nonzero(selection)
            depth = pixels[y, x]
            k = np.asarray(camera['K']['value'], float)
            points = np.column_stack([(x-k[0, 2])*depth/k[0, 0], (y-k[1, 2])*depth/k[1, 1], depth])
            reference = world_pose(candidate, camera)
        if len(points) < 4:
            raise ValueError('At least four finite segmented metric points are needed')
        world_points = (np.c_[points, np.ones(len(points))] @ reference.T)[:, :3]
        if obj['pose']['value'] is None:
            reports.append({'object': obj['id'], 'decision': 'NEEDS_MORE_DATA', 'need': 'object orientation/pose to interpret point bounds'})
            continue
        local = (np.c_[world_points, np.ones(len(points))] @ np.linalg.inv(world_pose(candidate, obj)).T)[:, :3]
        lo, hi = local.min(0), local.max(0)
        report = {'object': obj['id'], 'points': len(points), 'observed_extent_m': (hi-lo).tolist(), 'complete_coverage': bool(row.get('full_bounds', False))}
        # The caller must declare opposing-face coverage; a single visible depth
        # surface is not enough to determine the hidden object's thickness.
        if row.get('full_bounds', False) and obj['visual']['type'] == 'box':
            extent = hi-lo
            if min(extent) <= 0:
                raise ValueError('Full box bounds must have volume')
            if obj['dimensions']['provenance'] in ('unknown', 'estimated'):
                obj['dimensions'] = value(extent.tolist(), 'derived', [row['path'], 'declared opposing-face coverage'])
                pose = np.asarray(obj['pose']['value'], float)
                pose[:3, 3] += pose[:3, :3] @ ((hi+lo)/2)
                obj['pose'] = value(pose.tolist(), 'derived', [row['path'], 'calibrated point bounds'])
                report['applied'] = True
        reports.append(report)
    return candidate, reports


import cv2
from PIL import Image, ImageOps
from ..project import write, sha
from ..project import local_path, value
from ..project import copy_input


def undistort_evidence(project):
    project.require_writable()
    if not (project.root / 'working/current_scene.yaml').exists():
        return
    scene = project.scene
    evidence = project.evidence
    changed = False
    for camera in scene['cameras']:
        distortion = np.asarray(camera.get('original_distortion', camera['distortion'])['value'], float)
        if not np.any(distortion) or camera['K']['value'] is None:
            continue
        k = np.asarray(camera['K']['value'], float)
        resolution = tuple(camera['resolution'])
        maps = cv2.initUndistortRectifyMap(k, distortion, None, k, resolution, cv2.CV_32FC1)
        for image in evidence['images']:
            if image.get('eligible') is False or image['camera'] != camera['id'] or image.get('rectification'):
                continue
            if tuple(image['resolution']) != resolution:
                raise ValueError('Distortion calibration and image resolutions differ')
            project.checkpoint()
            old_path = image['path']
            pixels = np.asarray(ImageOps.exif_transpose(Image.open(local_path(project.root, old_path))).convert('RGB'))
            corrected = cv2.remap(pixels, *maps, cv2.INTER_LINEAR)
            scratch = project.root / 'scratch/undistorted.png'
            Image.fromarray(corrected).save(scratch)
            image['original_path'] = old_path
            image['original_sha256'] = image['sha256']
            image['path'] = copy_input(project, scratch, 'calibrated')
            image['sha256'] = sha(project.root / image['path'])
            image['rectification'] = 'calibrated OpenCV pinhole; original K retained'
            for mask in evidence['masks']:
                if mask['image'] != old_path:
                    continue
                pixels = np.asarray(Image.open(local_path(project.root, mask['path'])).convert('L'))
                if pixels.shape[::-1] != resolution:
                    raise ValueError('Rectification mask has wrong resolution')
                Image.fromarray(cv2.remap(pixels, *maps, cv2.INTER_NEAREST)).save(scratch)
                mask['original_path'] = mask['path']
                mask['path'] = copy_input(project, scratch, 'calibrated')
                mask['image'] = image['path']
        for landmark in evidence['landmarks']:
            if landmark['camera'] == camera['id'] and 'original_uv' not in landmark:
                uv = np.asarray(landmark['uv'], float).reshape(1, 1, 2)
                landmark['original_uv'] = copy.deepcopy(landmark['uv'])
                landmark['uv'] = cv2.undistortPoints(uv, k, distortion, P=k).ravel().tolist()
        if 'original_distortion' not in camera:
            camera['original_distortion'] = copy.deepcopy(camera['distortion'])
        camera['distortion'] = value([0.] * len(distortion), 'derived', ['calibrated pinhole evidence rectification'])
        changed = True
    if changed:
        write(project.root / 'input/evidence.yaml', evidence)
        project.save_scene(scene)
