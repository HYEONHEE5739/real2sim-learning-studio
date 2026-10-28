# Reused from the original Builder metrics/parity; source SHA recorded in evidence.
"""Diagnostics do not confuse global image similarity with geometric correctness."""
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps
import cv2


def compare(real,sim,folder):
    real=np.asarray(real,dtype=np.uint8);sim=np.asarray(sim,dtype=np.uint8)
    if real.shape!=sim.shape or real.ndim!=3 or real.shape[2]!=3:raise ValueError('Real/sim RGB resolution mismatch')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    error=np.abs(real.astype(float)-sim.astype(float))/255.
    edge_a=cv2.Canny(real,70,160)>0;edge_b=cv2.Canny(sim,70,160)>0
    union=np.count_nonzero(edge_a|edge_b)
    metrics={'mae':float(error.mean()),'rmse':float(np.sqrt(np.mean(error**2))),
        'edge_iou':float(np.count_nonzero(edge_a&edge_b)/union) if union else 1.}
    for name,array in {'real':real,'sim':sim,'side_by_side':np.concatenate([real,sim],axis=1),
        'overlay':np.rint((real.astype(float)+sim)/2).astype(np.uint8),'difference':np.uint8(np.clip(error*255,0,255))}.items():
        Image.fromarray(array).save(folder/(name+'.png'))
    return metrics


def mask_metrics(observed,rendered):
    a=np.asarray(observed,bool);b=np.asarray(rendered,bool)
    if a.shape!=b.shape or not a.any():raise ValueError('Invalid silhouette masks')
    union=np.count_nonzero(a|b);ca=np.argwhere(a).mean(0);cb=np.argwhere(b).mean(0) if b.any() else None
    return {'iou':float(np.count_nonzero(a&b)/union),'center_error_px':float(np.linalg.norm(ca-cb)) if cb is not None else None}


def paired_diagnostics(project, observation, real, candidate, folder, scene=None, engine=None):
    """Three-way comparison; numerical clues require external agent interpretation."""
    baseline=observation.get('runtime_baseline')
    if not baseline:return None
    from .project import local_path
    from .project import sha
    path=local_path(project.root,baseline['path'])
    if sha(path)!=baseline['sha256']:raise ValueError('Runtime baseline modified after import')
    runtime=np.asarray(Image.open(path).convert('RGB'))
    return {'real_runtime':compare(real,runtime,Path(folder)/'real_runtime'),
        'candidate_runtime':compare(candidate,runtime,Path(folder)/'candidate_runtime'),
        'identity':paired_identity(scene,observation,engine,project.root) if scene is not None else {'geometry_comparable':False,'reasons':['scene unavailable']},
        'workspace_context':baseline['workspace_context'],'runtime_engine':baseline['engine'],
        'meaning':'historical runtime baseline, not optimization ground truth',
        'diagnosis':'Agent must distinguish scene mismatch from adapter/render mismatch; image metrics alone do not establish cause'}


def object_metrics(project, scene, observation, masks):
    """Object/observation keyed geometry. Missing real evidence remains null."""
    from .project import local_path, world_pose
    from .project import sha
    from .calibration.camera import project_point
    from scipy.ndimage import binary_erosion, distance_transform_edt
    rows=[];evidence=project.evidence
    camera=next(c for c in scene['cameras'] if c['id']==observation['camera'])
    annotations=[m for m in evidence.get('masks',[]) if m['image']==observation['path']]
    landmarks=[r for r in evidence.get('landmarks',[]) if
               (r.get('observation')==observation.get('id') if r.get('observation') else
                r.get('camera')==observation['camera'] and r.get('split','train')==observation['split'])
               and r.get('visible',True) and r.get('weight',1)>0]
    for obj in scene['objects']:
        identity=obj['id'];sim=masks.get(identity);sources=[]
        row={'object':identity,'observation':observation.get('id',observation['path']),
             'camera':observation['camera'],'split':observation['split'],'role':obj['role'],
             'landmark_rmse_px':None,'landmark_residual_xy':None,'landmark_count':0,
             'iou':None,'boundary_chamfer_px':None,'centroid_residual_xy':None,
             'center_error_px':None,'bbox_scale_ratio':None,'visible_area_ratio':None,
             'predicted_visible_pixels':int(np.count_nonzero(sim)) if sim is not None else None,
             'evidence_status':'NOT_EVALUABLE','annotation_sources':sources}
        pts=[r for r in landmarks if r.get('object')==identity]
        if pts:
            residuals=[];weights=[]
            for point in pts:
                uv,z=project_point(scene,camera,point)
                if z<=0:continue
                residuals.append(uv-np.asarray(point['uv']));weights.append(float(point.get('weight',1)))
                import hashlib,json
                sources.append({'type':'landmark','sha256':hashlib.sha256(json.dumps(point,sort_keys=True).encode()).hexdigest(),
                                'provenance':point.get('provenance','provided_unverified')})
            if weights:
                row.update(landmark_count=len(weights),landmark_rmse_px=float(np.sqrt(np.average(np.sum(np.square(residuals),axis=1),weights=weights))),
                           landmark_residual_xy=np.average(residuals,axis=0,weights=weights).tolist())
        a=next((m for m in annotations if m['object']==identity),None)
        if a is not None:
            path=local_path(project.root,a['path']);real=np.asarray(Image.open(path).convert('L'))>0
            sources.append({'type':'real_mask','path':a['path'],'sha256':sha(path),'provenance':a.get('provenance','provided_unverified')})
            if sim is None:raise ValueError('Missing rendered object ID mask: '+identity)
            row.update(mask_metrics(real,sim))
            if sim.any():
                ea=real & ~binary_erosion(real);eb=sim & ~binary_erosion(sim)
                row['boundary_chamfer_px']=float((distance_transform_edt(~eb)[ea].mean()+distance_transform_edt(~ea)[eb].mean())/2)
                ra=np.argwhere(real);rb=np.argwhere(sim)
                row['centroid_residual_xy']=(rb.mean(0)-ra.mean(0))[::-1].tolist()
                row['bbox_scale_ratio']=((np.ptp(rb,axis=0)+1)/(np.ptp(ra,axis=0)+1))[::-1].tolist()
                row['visible_area_ratio']=float(sim.sum()/real.sum())
        row['evidence_status']='EVALUATED_PROVIDED_EVIDENCE' if sources else 'NOT_EVALUABLE'
        delta=world_pose(scene,camera)[:3,3]-world_pose(scene,obj)[:3,3]
        row['predicted_view_direction']=(world_pose(scene,obj)[:3,:3].T@delta/np.linalg.norm(delta)).tolist() if np.linalg.norm(delta)>1e-9 else None
        rows.append(row)
    return rows


def paired_identity(scene,observation,runtime_engine=None,root=None):
    """Historical RGB is comparable as a diagnostic, not an adapter parity proof."""
    from .project import world_pose
    baseline=observation.get('runtime_baseline',{});checks={};reasons=[]
    q=baseline.get('sim_q_measured_rad');measured=observation.get('q_measured')
    delta=np.asarray(q)-np.asarray(measured) if q is not None and measured is not None else None
    checks['joint_max_abs_delta_rad']=float(np.max(abs(delta))) if delta is not None else None
    checks['same_q']=bool(delta is not None and delta.shape==(len(scene.get('robot_model',{}).get('joint_names',q)),) and np.allclose(delta,0,atol=1e-6))
    recorded=baseline.get('sim_cameras',{}).get(observation['camera'],{})
    camera=next(c for c in scene['cameras'] if c['id']==observation['camera'])
    checks['same_resolution']=recorded.get('resolution')==camera['resolution']
    checks['same_K']=bool('K' in recorded and np.allclose(recorded['K'],camera['K']['value'],atol=1e-6))
    checks['same_world_optical_pose']=bool('T_world_optical' in recorded and np.allclose(recorded['T_world_optical'],world_pose(scene,camera),atol=1e-6))
    mapping=baseline.get('joint_mapping');expected=scene.get('robot_model',{}).get('mapping')
    checks['same_mapping']=mapping==expected if mapping is not None else None
    checks['same_engine']=runtime_engine==baseline.get('engine') if runtime_engine else None
    # Stable identity is only available if importer retained original Workspace context.
    context=baseline.get('workspace_context',{});checks['workspace_identity_present']=bool(context.get('workspace_id') and context.get('content_sha256') and context.get('builder',{}).get('manifest_sha256'))
    checks['same_scene_asset_version']=None  # portable canonical and historical Workspace hashes differ in representation
    for key in ('same_q','same_resolution','same_K','same_world_optical_pose','same_mapping','same_engine','same_scene_asset_version'):
        if checks[key] is not True:reasons.append(key+': '+('unknown' if checks[key] is None else 'different'))
    return {'checks':checks,'geometry_comparable':not reasons,'reasons':reasons,
            'interpretation':'Do not diagnose adapter geometry from unmatched historical RGB; replay matching pose/version first'}


"""Read exported MJCF and USD back; compare geometry and cameras to the canonical recipe."""
import xml.etree.ElementTree as ET
import json
from scipy.spatial.transform import Rotation

TOLERANCE=1e-5


def check(scene,root,mjcf,usd):
    from .project import world_pose,local_path,render_pose
    from .calibration.geometry import parts,mesh_data
    failures=[];checks=[]
    def equal(name,actual,expected):
        a=np.asarray(actual);b=np.asarray(expected)
        okay=a.shape==b.shape and np.allclose(a,b,atol=TOLERANCE,rtol=TOLERANCE)
        (checks if okay else failures).append(name)
    def truth(name,condition): (checks if condition else failures).append(name)
    def pose(node):
        t=np.eye(4);t[:3,3]=np.fromstring(node.get('pos','0 0 0'),sep=' ')
        q=np.fromstring(node.get('quat','1 0 0 0'),sep=' ');t[:3,:3]=Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix();return t
    tree=ET.parse(mjcf).getroot();bodies={b.get('name'):b for b in tree.findall('worldbody/body')}
    ids={o['id'] for o in scene['objects']};truth('mujoco object IDs/count',set(bodies)==ids)
    meshes={m.get('name'):m for m in tree.findall('asset/mesh')}
    try:
        from pxr import Usd,UsdGeom
    except ImportError:
        return {'status':'UNAVAILABLE','reason':'pxr USD bindings required for structural parity (Isaac runtime not required)', 'failures':failures}
    stage=Usd.Stage.Open(str(usd))
    if stage is None: return {'status':'FAIL','failures':['USD load']}
    frame_node=tree.find("custom/text[@name='canonical_frames']")
    truth('MJCF canonical frame graph metadata',frame_node is not None and json.loads(frame_node.get('data'))==scene['frames'])
    frame_attr=stage.GetPrimAtPath('/Scene').GetAttribute('canonical_frames').Get()
    truth('USD canonical frame graph metadata',bool(frame_attr) and json.loads(frame_attr)==scene['frames'])
    role_node=tree.find("custom/text[@name='semantic_roles']")
    truth('MJCF semantic roles',role_node is not None and json.loads(role_node.get('data'))=={o['id']:o['role'] for o in scene['objects']})
    usd_objects={p.GetName() for p in stage.GetPrimAtPath('/Scene').GetChildren() if p.IsA(UsdGeom.Xform)}
    truth('usd object IDs/count',usd_objects==ids)
    equal('usd metre units',UsdGeom.GetStageMetersPerUnit(stage),1.)
    truth('usd Z up',UsdGeom.GetStageUpAxis(stage)=='Z')
    for obj in scene['objects']:
        name=obj['id'];body=bodies.get(name);prim=stage.GetPrimAtPath('/Scene/'+name)
        if body is None or not prim: failures.append(name+' missing');continue
        equal(name+' MJCF world pose',pose(body),world_pose(scene,obj))
        equal(name+' USD world pose',np.asarray(UsdGeom.Xformable(prim).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T,world_pose(scene,obj))
        truth(name+' USD semantic role',prim.GetAttribute('semantic_role').Get()==obj['role'])
        dynamic=obj['role']=='manipulable_object' and (obj['physics']['mass_kg']['value'] or 0)>0
        truth(name+' MJCF dynamic intent',(body.find('freejoint') is not None)==dynamic)
        truth(name+' USD dynamic intent',bool(prim.GetAttribute('physics:rigidBodyEnabled').Get())==dynamic)
        expected_count=sum(len(parts(obj,f)) for f in ('visual','collision'))
        equal(name+' MJCF part count',len(body.findall('geom')),expected_count)
        equal(name+' USD part count',len(list(prim.GetChildren())),expected_count)
        for field in ('visual','collision'):
            for i,part in enumerate(parts(obj,field)):
                label=name+'_'+field+'_'+str(i);node=body.find("geom[@name='"+label+"']")
                sub=stage.GetPrimAtPath('/Scene/'+name+'/'+field+'_'+str(i))
                if node is None or not sub: failures.append(label+' missing');continue
                equal(label+' MJCF local pose',pose(node),part['pose'])
                expected=part['pose'].copy();kind=part['type'];dims=part['dimensions']
                if kind=='box':expected[:3,:3]=expected[:3,:3]@np.diag(dims/2)
                equal(label+' USD local pose/scale',np.asarray(UsdGeom.Xformable(sub).GetLocalTransformation()).T,expected)
                truth(label+' primitive kind',node.get('type')==kind and sub.GetTypeName()=={'box':'Cube','sphere':'Sphere','cylinder':'Cylinder','mesh':'Mesh'}[kind])
                if kind in ('box','sphere','cylinder'):
                    expected_size=dims/2 if kind=='box' else [dims[0]/2] if kind=='sphere' else [dims[0]/2,dims[2]/2]
                    equal(label+' MJCF dimensions',np.fromstring(node.get('size'),sep=' '),expected_size)
                    if kind=='box':equal(label+' USD size',UsdGeom.Cube(sub).GetSizeAttr().Get(),2.)
                    elif kind=='sphere':equal(label+' USD radius',UsdGeom.Sphere(sub).GetRadiusAttr().Get(),dims[0]/2)
                    else:
                        equal(label+' USD radius',UsdGeom.Cylinder(sub).GetRadiusAttr().Get(),dims[0]/2)
                        equal(label+' USD height',UsdGeom.Cylinder(sub).GetHeightAttr().Get(),dims[2])
                else:
                    mesh=meshes[node.get('mesh')];asset=local_path(root,scene['assets'][part['asset']]['path'])
                    truth(label+' visual asset reference',(Path(mjcf).parent/mesh.get('file')).resolve()==asset)
                    scale=part.get('scale',[1,1,1]);equal(label+' mesh scale',np.fromstring(mesh.get('scale','1 1 1'),sep=' '),scale)
                    vertices,faces=mesh_data(asset);usdmesh=UsdGeom.Mesh(sub)
                    equal(label+' USD mesh vertices',usdmesh.GetPointsAttr().Get(),vertices*np.asarray(scale))
                    equal(label+' USD mesh faces',usdmesh.GetFaceVertexIndicesAttr().Get(),faces.ravel())
                texture=obj['visual'].get('texture') if field=='visual' else None
                if texture:
                    material=tree.find("asset/material[@name='"+node.get('material','')+"']")
                    tex=tree.find("asset/texture[@name='"+material.get('texture','')+"']") if material is not None else None
                    expected_asset=local_path(root,scene['assets'][texture]['path'])
                    truth(label+' MJCF texture reference',tex is not None and (Path(mjcf).parent/tex.get('file')).resolve()==expected_asset)
                    shader=stage.GetPrimAtPath('/Scene/material_'+name+'/Image')
                    usd_texture=shader.GetAttribute('inputs:file').Get() if shader else None
                    truth(label+' USD texture reference',usd_texture is not None and (Path(usd).parent/usd_texture.path).resolve()==expected_asset)
                truth(label+' collision meaning',(node.get('contype')=='1')==(field=='collision'))
                truth(label+' USD collision meaning',bool(sub.GetAttribute('physics:collisionEnabled').Get())==(field=='collision'))
    cameras={c.get('name'):c for c in tree.findall('worldbody/camera')}
    truth('camera IDs',set(cameras)=={c['id'] for c in scene['cameras']})
    for c in scene['cameras']:
        name=c['id'];k=np.asarray(c['K']['value']);w,h=c['resolution'];node=cameras.get(name)
        usd_cam=UsdGeom.Camera(stage.GetPrimAtPath('/Scene/'+name))
        if node is None or not usd_cam:failures.append(name+' camera missing');continue
        equal(name+' MJCF camera pose',pose(node),render_pose(scene,c))
        equal(name+' USD camera pose',np.asarray(UsdGeom.Xformable(usd_cam).ComputeLocalToWorldTransform(Usd.TimeCode.Default())).T,render_pose(scene,c))
        equal(name+' resolution',np.fromstring(node.get('resolution'),sep=' '),[w,h])
        equal(name+' MJCF focal pixels',np.fromstring(node.get('focalpixel'),sep=' '),[k[0,0],k[1,1]])
        equal(name+' MJCF principal pixels',np.fromstring(node.get('principalpixel'),sep=' '),[w/2-k[0,2],k[1,2]-h/2])
        focal=usd_cam.GetFocalLengthAttr().Get();ha=usd_cam.GetHorizontalApertureAttr().Get();va=usd_cam.GetVerticalApertureAttr().Get()
        equal(name+' USD focal pixels',[w*focal/ha,h*focal/va],[k[0,0],k[1,1]])
        equal(name+' USD principal pixels',[w/2-usd_cam.GetHorizontalApertureOffsetAttr().Get()*w/ha,h/2+usd_cam.GetVerticalApertureOffsetAttr().Get()*h/va],[k[0,2],k[1,2]])
    return {'status':'PASS' if not failures else 'FAIL','absolute_tolerance':TOLERANCE,'relative_tolerance':TOLERANCE,
            'checks':len(checks),'failures':failures,'hierarchy':'canonical frame graph is baked to equal world transforms; frame graph retained in manifest',
            'scope':'exported structural geometry/camera parity; not Isaac runtime/photometric parity'}
