"""Gripper self-observation seeds for one shared link-to-camera transform.

No actuator or URDF edits. Reviewed CAD-to-pixel matches are required to assign
semantic identity; image corners alone cannot identify a gripper feature.
"""
import copy
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from ..scene import local_path,transform
from ..files import sha
from ..cameras import project_pixels
from .geometry import link_transforms


def gripper_features(rgb,mask):
    import cv2
    rgb=np.asarray(rgb);mask=np.asarray(mask)
    if rgb.ndim!=3 or rgb.shape[:2]!=mask.shape or not np.any(mask):raise ValueError('Nonempty gripper Mask on the exact RGB grid required')
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY);binary=(mask>0).astype('uint8')*255
    contours,_=cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    corners=cv2.goodFeaturesToTrack(gray,64,.01,5,mask=binary)
    return {'contours':[c.reshape(-1,2).tolist()for c in contours],
        'keypoints':[]if corners is None else corners.reshape(-1,2).tolist(),
        'association':'UNRESOLVED until reviewed URDF Visual correspondences','metric_verified':False}


def fit_gripper_mount(project,scene,camera_id,observations,options=None):
    import cv2
    options=options or{};camera=next(c for c in scene['cameras']if c['id']==camera_id)
    report={'status':'NEEDS_MORE_DATA','camera':camera_id,'physical_verified':False,'world_pose_observable':False,
        'needs':[],'candidates':[],'visual_mesh_match':'NOT_VERIFIED; actual hardware/URDF visual mismatch requires review'}
    if not camera['frame'].startswith('robot_link_'):raise ValueError('Wrist camera requires an actual Robot Link parent')
    if camera['K']['value']is None or camera['distortion']['value']is None:return {**report,'needs':['Known or separately assessed Intrinsics/Distortion required for gripper seed']}
    model=scene.get('robot_model',{});path=local_path(project.root,model['path'])
    if sha(path)!=model['model_sha256']:raise ValueError('Robot model identity changed')
    import xml.etree.ElementTree as ET
    visual={n.attrib['name']for n in ET.parse(path).getroot().findall('link')if n.find('visual')is not None}
    mount_link=camera['frame'].removeprefix('robot_link_');rows=[];groups={};configurations=[]
    for image in observations:
        if image['camera']!=camera_id:continue
        if image.get('q_measured')is None or image.get('joint_names')!=model['joint_names']or image.get('robot_model_sha256')!=model['model_sha256']or image.get('mapping_sha256')!=model.get('mapping',{}).get('sha256'):raise ValueError('Gripper measured-q/model/mapping mismatch')
        q=np.asarray(image['q_measured'],float)
        if q.shape!=(len(model['joint_names']),)or not np.isfinite(q).all():raise ValueError('Invalid measured q')
        fk=link_transforms(path,dict(zip(model['joint_names'],q)));relative=[]
        for landmark in image.get('landmarks',[]):
            if landmark.get('visible',True)is False or landmark.get('occluded')is True or landmark.get('confidence',1)<options.get('min_confidence',.2):continue
            if landmark['link']not in visual:return {**report,'needs':['URDF Visual Geometry required on link '+landmark['link']]}
            point=np.asarray(landmark['point_m'],float);uv=np.asarray(landmark['uv'],float)
            if point.shape!=(3,)or uv.shape!=(2,)or not np.isfinite(np.r_[point,uv]).all():raise ValueError('Finite CAD point and original pixel required')
            from ..cameras import camera_pixels
            A,_=camera_pixels(camera,{**image,'resolution':image.get('resolution',camera['resolution'])})
            width,height=image.get('resolution',camera['resolution'])
            if not(0<=uv[0]<width and 0<=uv[1]<height):raise ValueError('Gripper pixel outside source resolution')
            normalized=np.linalg.inv(A)@np.r_[uv,1];uv=normalized[:2]/normalized[2]
            T=np.linalg.inv(fk[mount_link])@fk[landmark['link']];p=(T@np.r_[point,1])[:3];relative.append(p)
            sigma=float(landmark.get('sigma_px',3.))
            if not np.isfinite(sigma)or sigma<=0:raise ValueError('Positive pixel uncertainty required')
            rows.append((image,p,uv,sigma,A))
        if image['split']=='train'and relative:configurations.append(np.asarray(relative))
        groups.setdefault(image['split'],set()).add(image['group_id'])
    if groups.get('train',set())&groups.get('validation',set()):raise ValueError('Gripper Train/Holdout group leakage')
    if {r[0]['sha256']for r in rows if r[0]['split']=='train'and r[0].get('sha256')}&{r[0]['sha256']for r in rows if r[0]['split']=='validation'and r[0].get('sha256')}:raise ValueError('Gripper Train/Holdout image leakage')
    train=[r for r in rows if r[0]['split']=='train'];held=[r for r in rows if r[0]['split']=='validation']
    unique=[]
    for c in configurations:
        if not any(c.shape==v.shape and np.allclose(c,v,atol=1e-9,rtol=0)for v in unique):unique.append(c)
    report['independent_relative_configurations']=len(unique)
    if len(train)<4 or np.linalg.matrix_rank(np.array([r[1]for r in train])-np.mean([r[1]for r in train],axis=0))<2:return {**report,'needs':['>=4 non-collinear reviewed gripper Visual CAD/pixel points required; arm motion alone may repeat the same relative view']}
    def pose(x):
        T=np.eye(4);T[:3,3]=x[:3];T[:3,:3]=Rotation.from_rotvec(x[3:]).as_matrix();return T
    def pack(T):
        T=np.asarray(T,float)
        return np.r_[T[:3,3],Rotation.from_matrix(T[:3,:3]).as_rotvec()]
    def errors(x,records,weighted=False):
        T=pose(x);out=[]
        for image,point,uv,sigma,A in records:
            optical=(np.linalg.inv(T)@np.r_[point,1])[:3]
            predicted=project_pixels(camera,optical[None]).ravel()
            # sigma and reported errors belong to the actual RGB grid; the
            # canonical Camera grid is only used for the PnP seed.
            delta=A[:2,:2]@(predicted-uv);out.extend(delta/(sigma if weighted else 1.))
            if weighted:out.append(max(0.,.001-optical[2])*1e4)
        return np.asarray(out)
    def rms(x,records):return float(np.sqrt(np.mean(np.sum(errors(x,records).reshape(-1,2)**2,axis=1))))
    seeds=[transform(s)for s in options.get('seeds',[])]
    if camera['pose']['value']is not None:seeds.append(transform(camera['pose']['value']))
    points=np.array([r[1]for r in train]);pixels=np.array([r[2]for r in train])
    # Existing pinhole solver supplies a seed, never calibration approval.
    from .registration import camera_from_anchors
    initial=camera_from_anchors(points,pixels,camera['K']['value'],camera['distortion']['value'])
    if initial['status']=='ESTIMATED':seeds.append(np.asarray(initial['T_world_camera']))
    if not seeds:return {**report,'needs':['PnP seed unresolved; review Visual correspondences or supply finite initial Mount candidates']}
    x=pack(seeds[-1]);seeds += [pose(x+np.r_[np.zeros(3),angle,0,0])for angle in(-.1,.1)]
    for seed in seeds[:8]:
        project.checkpoint();x=pack(seed);radius=np.r_[[.05]*3,[.35]*3]
        fit=least_squares(lambda v:errors(v,train,True),x,bounds=(x-radius,x+radius),loss='soft_l1',max_nfev=100)
        T=pose(fit.x);depth=[(np.linalg.inv(T)@np.r_[r[1],1])[2]for r in train]
        report['candidates'].append({'T_link_camera':T.tolist(),'training_rmse_px':rms(fit.x,train),
            'rank':int(np.linalg.matrix_rank(fit.jac)),'positive_depth':bool(min(depth)>0)})
    valid=[r for r in report['candidates']if r['rank']==6 and r['positive_depth']]
    if not valid:return {**report,'needs':['Mount remains rank-deficient/behind-camera; add independent gripper geometry or Scene observations']}
    best=min(valid,key=lambda r:r['training_rmse_px']);sigma=float(np.median([r[3]for r in train]))
    alternatives=[r for r in valid if r['training_rmse_px']<=best['training_rmse_px']+sigma and not np.allclose(r['T_link_camera'],best['T_link_camera'],atol=1e-5,rtol=0)]
    if alternatives:return {**report,'status':'AMBIGUOUS','needs':['Similar-error Mount candidates within annotated pixel uncertainty; add Scene/FK observations'],'rank':best['rank']}
    T=best['T_link_camera'];return {**report,**best,'status':'ESTIMATED','holdout_rmse_px':rms(pack(T),held)if held else None,
        'needs':['Self observation does not certify independent Mount accuracy or Robot World'],'provenance':'estimated'}


def initialize_gripper_mount(candidate,scene,config,folder):
    """Stage10 adapter: identity-checked Capture + reviewed URDF Visual matches."""
    from ..observations import input_images
    from ..files import write
    from ..scene import value
    from PIL import Image,ImageOps
    result=copy.deepcopy(scene);reports={};spec=copy.deepcopy(config.get('sensor_registration',{}).get('gripper_mount',{}))
    # Existing approved CAD annotations can seed this path without a new form.
    from ..observations import annotation_evidence
    evidence=annotation_evidence(candidate.project,scene)if scene.get('view_registrations')else candidate.project.evidence
    images={r.get('id'):r for r in candidate.project.evidence['images']};nodes={o['id']:o for o in scene.get('objects',[])}
    automatic={}
    for row in evidence.get('landmarks',[]):
        image=images.get(row.get('observation'));node=nodes.get(row.get('object'));frame=row.get('frame')
        if not image or image.get('camera_type')!='wrist'or not row.get('visible',True)or row.get('occluded')is True:continue
        if node:frame=node.get('frame')
        if not frame or not frame.startswith('robot_link_')or row.get('point_m')is None:continue
        point=np.asarray(row['point_m'],float)
        if node:
            if node['pose']['value']is None:continue
            point=(transform(node['pose']['value'])@np.r_[point,1])[:3]
        record=automatic.setdefault(image['camera'],{}).setdefault(image['id'],{'image_id':image['id'],'landmarks':[]})
        record['landmarks'].append({**row,'link':frame.removeprefix('robot_link_'),'point_m':point.tolist()})
    for camera,records in automatic.items():spec.setdefault(camera,{'observations':list(records.values())})
    for camera_id,options in spec.items():
        records=[]
        for row in options.get('observations',[]):
            original=next((r for r in candidate.project.evidence['images']if r.get('id')==row['image_id']),None)
            if original is None or original.get('camera_type')!='wrist'or original['camera']!=camera_id:raise ValueError('Gripper observation must bind an existing Wrist image')
            images,_,_=input_images(candidate.project,original['scene_state_id'])
            image=copy.deepcopy(next(r for r in images if r['id']==row['image_id']));image['landmarks']=row.get('landmarks',[])
            if row.get('mask'):
                path=local_path(candidate.project.root,row['mask'])
                if sha(path)!=row.get('mask_sha256'):raise ValueError('Gripper Mask source changed')
                rgb=np.asarray(ImageOps.exif_transpose(Image.open(local_path(candidate.project.root,image['path']))).convert('RGB'))
                image['features']=gripper_features(rgb,np.asarray(Image.open(path).convert('L'))>0)
            records.append(image)
        camera=next((c for c in result['cameras']if c['id']==camera_id),None)
        if camera is None:reports[camera_id]={'status':'NEEDS_MORE_DATA','needs':['Initialize actual Wrist camera metadata/Link/K first']};continue
        report=fit_gripper_mount(candidate.project,result,camera_id,records,options);reports[camera_id]=report
        if report['status']=='ESTIMATED':
            if camera['pose']['provenance']in('measured','calibrated'):
                report['status']='PROTECTED';report['needs']+=['Existing protected Mount retained; seed is diagnostic only']
            else:camera['pose']=value(report['T_link_camera'],'estimated',['Shared gripper Visual CAD-to-pixel seed; independent accuracy NOT_VERIFIED'])
    if reports:
        write(folder/'gripper_initialization.json',reports);write(folder/'gripper_seed_scene.yaml',result)
    return result,reports
