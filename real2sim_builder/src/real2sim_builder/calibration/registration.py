"""Numerical point/plane registration, independent of any scanner file format."""
import numpy as np


def align_points(source,target,*,weights=None,estimate_scale=False):
    """Weighted proper rigid/similarity alignment; caller supplies metric anchors."""
    x,y=np.asarray(source,float),np.asarray(target,float)
    if x.ndim!=2 or x.shape[1:]!=(3,)or x.shape!=y.shape or not np.isfinite(x).all()or not np.isfinite(y).all():
        raise ValueError('Matching finite Nx3 point arrays required')
    if len(x)<3:return {'status':'NEEDS_MORE_DATA','needs':['At least three non-collinear 3D anchors']}
    w=np.ones(len(x))if weights is None else np.asarray(weights,float)
    if w.shape!=(len(x),)or not np.isfinite(w).all()or np.any(w<=0):raise ValueError('Positive finite point weights required')
    w=w/w.sum();a=w@x;b=w@y;xx=x-a;yy=y-b
    rank=[int(np.linalg.matrix_rank(v))for v in (xx,yy)]
    if min(rank)<2:return {'status':'NEEDS_MORE_DATA','rank':rank,'needs':['Non-collinear anchors; rotation is ambiguous']}
    u,s,vt=np.linalg.svd((xx*w[:,None]).T@yy)
    sign=np.diag([1.,1.,np.linalg.det(vt.T@u.T)]);rotation=vt.T@sign@u.T
    scale=float(np.sum(s*np.diag(sign))/np.sum(w[:,None]*xx**2))if estimate_scale else 1.
    if not np.isfinite(scale)or scale<=0:raise ValueError('Positive registration scale required')
    pose=np.eye(4);pose[:3,:3]=rotation;pose[:3,3]=b-rotation@(scale*a)
    error=np.linalg.norm(scale*x@rotation.T+pose[:3,3]-y,axis=1)
    return {'status':'ESTIMATED','scale':scale,'T_target_source':pose.tolist(),'residual':error.tolist(),
            'rmse':float(np.sqrt(w@(error**2))),'rank':rank,'singular_values':s.tolist(),
            'provenance':'derived','physical_verified':False}


def plane(points,tolerance=.005):
    """Robust visible-point plane; neither semantic support nor metric evidence."""
    points=np.asarray(points,float)
    if points.ndim!=2 or points.shape[1:]!=(3,)or not np.isfinite(points).all()or not np.isfinite(tolerance)or tolerance<=0:
        raise ValueError('Finite Nx3 points and positive plane tolerance required')
    if len(points)<3:return {'status':'NEEDS_MORE_DATA'}
    rng=np.random.default_rng(0);sample=points if len(points)<=20000 else points[rng.choice(len(points),20000,replace=False)]
    best=np.zeros(len(sample),bool)
    for _ in range(128):
        triangle=sample[rng.choice(len(sample),3,replace=False)];normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])
        length=np.linalg.norm(normal)
        if length<1e-12:continue
        mask=abs((sample-triangle[0])@(normal/length))<=tolerance
        if mask.sum()>best.sum():best=mask
    if best.sum()<3:return {'status':'NEEDS_MORE_DATA'}
    center=sample[best].mean(0);_,s,vt=np.linalg.svd(sample[best]-center,full_matrices=False)
    if s[1]<1e-10:return {'status':'NEEDS_MORE_DATA','needs':['Plane points are collinear']}
    normal=vt[-1]
    if normal[2]<0:normal=-normal
    return {'status':'ESTIMATED','normal':normal.tolist(),'center':center.tolist(),'inlier_fraction':float(best.mean()),
            'rmse':float(np.sqrt(np.mean(((sample[best]-center)@normal)**2))),
            'provenance':'derived','scope':'visible point plane; metric scale and support identity require anchors'}


def camera_from_anchors(world_points,uv,k,distortion,*,max_rmse_px=3.):
    """Known-K PnP in optical axes; output is camera-to-World, never DA3 scale."""
    import cv2
    points=np.asarray(world_points,float);pixels=np.asarray(uv,float);matrix=np.asarray(k,float);dist=np.asarray(distortion,float)
    if points.ndim!=2 or points.shape[1:]!=(3,)or pixels.shape!=(len(points),2)or len(points)<4:
        return {'status':'NEEDS_MORE_DATA','needs':['At least four measured World-to-image anchor correspondences']}
    if matrix.shape!=(3,3)or not all(np.isfinite(v).all()for v in(points,pixels,matrix,dist))or min(matrix[0,0],matrix[1,1])<=0:
        raise ValueError('Finite metric anchors, pixels and valid pinhole K required')
    if np.linalg.matrix_rank(points-points.mean(0))<2:
        return {'status':'NEEDS_MORE_DATA','needs':['Camera anchors are collinear']}
    ok,rv,tv=cv2.solvePnP(points,pixels,matrix,dist,flags=cv2.SOLVEPNP_SQPNP)
    if not ok:return {'status':'NEEDS_MORE_DATA','needs':['PnP did not find a camera pose']}
    pose=np.eye(4);pose[:3,:3]=cv2.Rodrigues(rv)[0];pose[:3,3]=tv.ravel()
    depths=(points@pose[:3,:3].T+pose[:3,3])[:,2]
    projected,_=cv2.projectPoints(points,rv,tv,matrix,dist);error=np.linalg.norm(projected.reshape(-1,2)-pixels,axis=1)
    rmse=float(np.sqrt(np.mean(error**2)))
    if min(depths)<=0 or rmse>max_rmse_px:return {'status':'NEEDS_MORE_DATA','needs':['Metric-anchor reprojection or cheirality failed'],'rmse_px':rmse}
    return {'status':'ESTIMATED','T_world_camera':np.linalg.inv(pose).tolist(),'rmse_px':rmse,
            'anchor_count':len(points),'provenance':'optimized','physical_verified':False,
            'scope':'known-intrinsic metric-anchor PnP; independent validation is separate'}
