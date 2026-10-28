"""Measured-world and FK landmarks drive bounded camera fitting, never scale guessing."""
# OpenCV 4.11 pinhole/PnP: https://docs.opencv.org/4.11.0/d9/d0c/group__calib3d.html
# Bounded robust fit: https://docs.scipy.org/doc/scipy-1.15.3/reference/generated/scipy.optimize.least_squares.html
import copy
import cv2
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from real2sim_builder.scene import transform, world_pose, frame_world, value


def point_world(scene,row):
    point=np.asarray(row.get('point_m',[0,0,0]),float)
    if row.get('point_fraction') is not None:
        obj=next(o for o in scene['objects'] if o['id']==row['object'])
        point=np.asarray(row['point_fraction'],float)*np.asarray(obj['dimensions']['value'])
    if point.shape!=(3,) or not np.isfinite(point).all():raise ValueError('Invalid metric landmark')
    if row.get('object'):
        obj=next(o for o in scene['objects'] if o['id']==row['object'])
        if row.get('point_fraction') is None and obj['dimensions']['provenance'] in ('unknown','estimated'):raise ValueError('Estimated geometry cannot anchor metric calibration')
        t=world_pose(scene,obj)
    else:t=frame_world(scene,row.get('frame','world'))
    return (t@np.r_[point,1])[:3]


def project_point(scene,camera,row):
    p=(np.linalg.inv(world_pose(scene,camera))@np.r_[point_world(scene,row),1])[:3]
    uv,_=cv2.projectPoints(p.reshape(1,3),np.zeros(3),np.zeros(3),np.asarray(camera['K']['value'],float),np.asarray(camera['distortion']['value'],float))
    return uv.ravel(),p[2]


def landmark_metrics(scene,rows):
    errors=[];behind=0
    for row in rows:
        camera=next(c for c in scene['cameras'] if c['id']==row['camera'])
        uv,z=project_point(scene,camera,row);actual=np.asarray(row['uv'],float)
        if actual.shape!=(2,) or not np.isfinite(actual).all():raise ValueError('Invalid pixel landmark')
        errors.append(float(np.linalg.norm(uv-actual)));behind+=int(z<=0)
    return {'count':len(errors),'rmse_px':float(np.sqrt(np.mean(np.square(errors)))) if errors else None,
        'max_px':max(errors) if errors else None,'behind_camera':behind}


def fit_cameras(scene,landmarks):
    candidate=copy.deepcopy(scene);report=[]
    for camera in candidate['cameras']:
        rows=[r for r in landmarks if r['camera']==camera['id'] and r.get('split','train')=='train']
        if len(rows)<4 or camera['K']['value'] is None:continue
        points=np.array([point_world(candidate,r) for r in rows]);uv=np.array([r['uv'] for r in rows],float)
        if np.linalg.matrix_rank(points-points.mean(0))<2:raise ValueError('Camera landmarks are collinear')
        if camera['pose']['value'] is None:
            ok,rvec,tvec=cv2.solvePnP(points,uv,np.asarray(camera['K']['value'],float),np.asarray(camera['distortion']['value'],float),flags=cv2.SOLVEPNP_SQPNP)
            if not ok:continue
            optical_world=np.eye(4);optical_world[:3,:3]=cv2.Rodrigues(rvec)[0];optical_world[:3,3]=tvec.ravel()
            t=np.linalg.inv(frame_world(candidate,camera['frame']))@np.linalg.inv(optical_world)
            camera['pose']=value(t.tolist(),'derived',['measured 3D/2D correspondences'])
        original=transform(camera['pose']['value']);seed=np.r_[original[:3,3],Rotation.from_matrix(original[:3,:3]).as_rotvec()]
        def set_pose(x):
            t=np.eye(4);t[:3,3]=x[:3];t[:3,:3]=Rotation.from_rotvec(x[3:]).as_matrix();camera['pose']['value']=t.tolist()
        def residual(x):
            set_pose(x);values=[]
            for row in rows:
                projected,z=project_point(candidate,camera,row)
                values.extend(projected-row['uv']);values.append(max(0,.001-z)*1e4)
            return values
        fit=least_squares(residual,seed,bounds=(seed-np.r_[[.25]*3,[.8]*3],seed+np.r_[[.25]*3,[.8]*3]),loss='soft_l1',max_nfev=100)
        set_pose(fit.x)
        if np.linalg.matrix_rank(fit.jac)<6:
            camera['pose']['value']=original.tolist();report.append({'camera':camera['id'],'decision':'NEEDS_MORE_DATA','reason':'camera pose is unobservable'});continue
        camera['pose']['provenance']='optimized';camera['pose']['evidence'].append('bounded least-squares measured-landmark fit')
        report.append({'camera':camera['id'],'decision':'CONTINUE','points':len(rows),'cost':float(fit.cost)})
    return candidate,report


def fit_geometry(scene,landmarks):
    """Recover object pose from measured local geometry and calibrated image corners."""
    candidate=copy.deepcopy(scene);report=[]
    for obj in candidate['objects']:
        if obj['pose']['provenance'] in ('measured','calibrated'):continue
        rows=[r for r in landmarks if r.get('object')==obj['id'] and r.get('split','train')=='train']
        if not rows or obj['dimensions']['value'] is None or obj['dimensions']['provenance'] in ('unknown','estimated'):continue
        camera_ids={r['camera'] for r in rows}
        for camera_id in sorted(camera_ids):
            camera=next(c for c in candidate['cameras'] if c['id']==camera_id)
            if camera['pose']['value'] is None or camera['K']['value'] is None:continue
            observed=[r for r in rows if r['camera']==camera_id]
            if len(observed)<4:continue
            points=np.array([r['point_m'] for r in observed],float);uv=np.array([r['uv'] for r in observed],float)
            if np.linalg.matrix_rank(points-points.mean(0))<2:raise ValueError('Object corners must be non-collinear')
            ok,rvec,tvec=cv2.solvePnP(points,uv,np.asarray(camera['K']['value'],float),np.asarray(camera['distortion']['value'],float),flags=cv2.SOLVEPNP_SQPNP)
            if not ok:continue
            camera_obj=np.eye(4);camera_obj[:3,:3]=cv2.Rodrigues(rvec)[0];camera_obj[:3,3]=tvec.ravel()
            parent_obj=np.linalg.inv(frame_world(candidate,obj['frame']))@world_pose(candidate,camera)@camera_obj
            obj['pose']=value(parent_obj.tolist(),'derived',['measured local corners and calibrated pixel observations'])
            report.append({'object':obj['id'],'camera':camera_id,'points':len(observed)})
            break
    return candidate,report
