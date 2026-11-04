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


def wrist_from_motion(link_poses,camera_poses):
    """Metric hand-eye/robot-world fit: s*C_i = X*FK(q_i)*Mount.

    DA3 camera poses must already share one relative frame. Joint values and
    model geometry are fixed. A full-rank multi-motion solve supplies scale;
    simply having a URDF does not. World is the robot-base gauge, not a measured
    tabletop/world registration.
    """
    from scipy.optimize import least_squares
    from scipy.spatial.transform import Rotation
    a=np.asarray(link_poses,float);b=np.asarray(camera_poses,float)
    if a.shape!=b.shape or a.ndim!=3 or a.shape[1:]!=(4,4)or not np.isfinite(a).all()or not np.isfinite(b).all():raise ValueError('Matching finite FK and relative Camera poses required')
    unresolved={'status':'UNRESOLVED','physical_verified':False,'needs':['Move the wrist through distinct rotations and translations while objects remain fixed']}
    if len(a)<4:return unresolved
    def pose(v):
        t=np.eye(4);t[:3,:3]=Rotation.from_rotvec(v[3:]).as_matrix();t[:3,3]=v[:3];return t
    def pack(t):return np.r_[t[:3,3],Rotation.from_matrix(t[:3,:3]).as_rotvec()]
    def residual(x):
        base=pose(x[:6]);mount=pose(x[6:12]);scale=np.exp(x[12]);out=[]
        for f,c in zip(a,b):
            predicted=base@f@mount
            out.extend(predicted[:3,3]-c[:3,3]*scale)
            out.extend(Rotation.from_matrix(predicted[:3,:3]@c[:3,:3].T).as_rotvec())
        return np.asarray(out)
    solutions=[]
    for scale in(.1,1.,10.):
        seed=b[0].copy();seed[:3,3]*=scale
        initial=np.r_[pack(seed@np.linalg.inv(a[0])),np.zeros(6),np.log(scale)]
        solutions.append(least_squares(residual,initial,loss='soft_l1',f_scale=.01,max_nfev=300,
            bounds=(np.r_[np.full(12,-np.inf),-8.],np.r_[np.full(12,np.inf),8.])))
    best=min(solutions,key=lambda s:np.linalg.norm(residual(s.x)));rank=int(np.linalg.matrix_rank(best.jac,tol=1e-7))
    rmse=float(np.sqrt(np.mean(residual(best.x)**2)))
    if rank<13 or rmse>.02:return {**unresolved,'rank':rank,'rmse':rmse}
    return {'status':'OPTIMIZED','scale':float(np.exp(best.x[12])),'T_relative_base':pose(best.x[:6]).tolist(),
        'T_link_camera':pose(best.x[6:12]).tolist(),'rank':rank,'rmse':rmse,'physical_verified':False,
        'gauge':'robot_base; absolute tabletop/world pose not measured','provenance':'optimized'}


def align_depth_batches(batches):
    """Align independent DA3 batches using actual shared-image depth points.

    A shared camera center alone cannot determine scale. Matching pixels in the
    shared depth view provide 3D correspondences; disconnected components stay
    unresolved. Returned similarities map each batch into the first batch.
    """
    from ..files import sha
    loaded=[]
    for batch in batches:
        if sha(batch['path'])!=batch['metadata']['sha256']:raise ValueError('DA3 batch bytes changed')
        with np.load(batch['path'],allow_pickle=False)as data:loaded.append({k:v.copy()for k,v in data.items()})
    def points(index,name):
        data=loaded[index];i=batches[index]['image_ids'].index(name);depth=data['depth'][i];k=data['intrinsics'][i]
        h,w=depth.shape;v,u=np.mgrid[0:h:max(1,h//35),0:w:max(1,w//45)]
        z=depth[v,u].ravel();rays=np.linalg.solve(k,np.array([u.ravel(),v.ravel(),np.ones(u.size)]))
        ext=np.eye(4);ext[:data['extrinsics'][i].shape[0]]=data['extrinsics'][i];pose=np.linalg.inv(ext)
        return (rays.T*z[:,None])@pose[:3,:3].T+pose[:3,3],(h,w)
    resolved={0:{'state':'PREDICTED','scale':1.,'T_common_batch':np.eye(4).tolist(),'scope':'relative reference frame; metric scale unresolved'}}if batches else{}
    while True:
        progress=False
        for target in range(len(batches)):
            if target in resolved:continue
            for parent,binding in list(resolved.items()):
                common=set(batches[parent]['image_ids'])&set(batches[target]['image_ids'])
                sources=[];targets=[]
                for name in sorted(common):
                    a,shape=points(target,name);b,other=points(parent,name)
                    if shape!=other:continue
                    keep=np.isfinite(a).all(1)&np.isfinite(b).all(1)
                    if keep.sum()<30:continue
                    matrix=np.asarray(binding['T_common_batch']);sources.append(a[keep]);targets.append((b[keep]*binding['scale'])@matrix[:3,:3].T+matrix[:3,3])
                if not sources:continue
                a=np.concatenate(sources);b=np.concatenate(targets)
                fit=align_points(a,b,estimate_scale=True)
                if fit['status']!='ESTIMATED':continue
                for _ in range(3):
                    errors=np.asarray(fit['residual']);keep=errors<=np.percentile(errors,80)
                    fit=align_points(a[keep],b[keep],estimate_scale=True)
                    matrix=np.asarray(fit.get('T_target_source',np.eye(4)));errors=np.linalg.norm(a*fit.get('scale',1)@matrix[:3,:3].T+matrix[:3,3]-b,axis=1)
                    fit['residual']=errors.tolist()
                if fit['status']!='ESTIMATED'or fit['rmse']>max(1e-5,np.linalg.norm(np.ptp(b,axis=0))*.03):continue
                resolved[target]={'state':'PREDICTED','scale':fit['scale'],'T_common_batch':fit['T_target_source'],
                    'overlap':sorted(common),'rmse':fit['rmse'],'scope':'overlap depth similarity; metric scale unresolved'}
                progress=True;break
        if not progress:break
    return {'batches':[resolved.get(i,{'state':'UNRESOLVED','needs':['Add overlapping views; independent DA3 frames were not merged']})for i in range(len(batches))],
            'metric_scale_verified':False,'physical_verified':False}
