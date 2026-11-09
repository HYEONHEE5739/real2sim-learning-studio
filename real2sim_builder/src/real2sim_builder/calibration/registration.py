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
    """Known-K PnP in optical axes; output is camera-to-World, never Geometry scale."""
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


def camera_from_correspondences(world_points,uv,*,resolution,k=None,distortion=None):
    """Robust PnP initialization on derived metric matches, not calibration approval.

    Reuses OpenCV PnP/calibration and the existing anchor evaluator. Unknown
    lenses require non-planar geometry; centered principal point, square pixels
    and zero distortion stay explicit unverified hypotheses.
    """
    import cv2
    points=np.asarray(world_points,float);pixels=np.asarray(uv,float)
    missing={'status':'NEEDS_MORE_DATA','physical_verified':False,'needs':['At least twelve nondegenerate metric 3D/2D matches required for sensor initialization']}
    if points.ndim!=2 or points.shape[1:]!=(3,)or pixels.shape!=(len(points),2)or len(points)<12:return missing
    if not np.isfinite(points).all()or not np.isfinite(pixels).all():raise ValueError('Finite sensor correspondences required')
    if k is None and np.linalg.matrix_rank(points-points.mean(0),tol=1e-6)<3:
        return {**missing,'needs':['Unknown sensor focal/depth is ambiguous on a planar match set']}
    w,h=resolution;dist=np.zeros(5)if distortion is None else np.asarray(distortion,float)
    matrices=[np.asarray(k,float)]if k is not None else[np.array([[w/(2*np.tan(np.deg2rad(fov)/2)),0,w/2],[0,w/(2*np.tan(np.deg2rad(fov)/2)),h/2],[0,0,1]])for fov in(40.,60.,80.)]
    solutions=[]
    for matrix in matrices:
        ok,rv,tv,inliers=cv2.solvePnPRansac(points,pixels,matrix,dist,iterationsCount=300,reprojectionError=3.,confidence=.999,flags=cv2.SOLVEPNP_EPNP)
        if not ok or inliers is None or len(inliers)<12:continue
        ids=inliers.ravel();xx=points[ids];pp=pixels[ids]
        if k is None:
            flags=cv2.CALIB_USE_INTRINSIC_GUESS|cv2.CALIB_FIX_PRINCIPAL_POINT|cv2.CALIB_FIX_ASPECT_RATIO|cv2.CALIB_ZERO_TANGENT_DIST|cv2.CALIB_FIX_K1|cv2.CALIB_FIX_K2|cv2.CALIB_FIX_K3
            try:_,matrix,_,_,_=cv2.calibrateCamera([xx.astype('float32')],[pp.astype('float32')],(w,h),matrix,dist.copy(),flags=flags)
            except cv2.error:continue
            if not w/(2*np.tan(np.deg2rad(140)/2))<matrix[0,0]<w/(2*np.tan(np.deg2rad(15)/2)):continue
        fitted=camera_from_anchors(xx,pp,matrix,dist)
        if fitted['status']=='ESTIMATED':solutions.append({**fitted,'K':matrix.tolist(),'distortion':dist.tolist(),'inliers':ids.tolist(),
            'intrinsic_source':'preserved'if k is not None else'estimated focal; principal point/aspect/distortion unverified',
            'scope':'derived feature registration; no held-out accuracy or physical calibration claim'})
    return min(solutions,key=lambda r:(-len(r['inliers']),r['rmse_px']))if solutions else missing


def wrist_from_motion(link_poses,camera_poses):
    """Metric hand-eye/robot-world fit: s*C_i = X*FK(q_i)*Mount.

    Geometry camera poses must already share one relative frame. Joint values and
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
    """Align independent Geometry batches using actual shared-image depth points.

    A shared camera center alone cannot determine scale. Matching pixels in the
    shared depth view provide 3D correspondences. Explicit SfM frames retain
    the largest registered train component as the reference and leave other
    components unresolved; they are never joined through unrelated origins.
    Legacy overlapping depth batches map into their first batch.
    """
    from ..files import sha
    frames=[b.get('metadata',{}).get('common_frame')for b in batches]
    if any(frames):
        # Identity is only a relative coordinate gauge, never a metre scale.
        # Disjoint components are not aligned through unrelated camera origins.
        if not all(frames):
            return {'batches':[{'state':'UNRESOLVED','needs':['Disconnected/mixed SfM components need bridging observations']}for _ in batches],
                    'metric_scale_verified':False,'physical_verified':False}
        for batch in batches:
            if sha(batch['path'])!=batch['metadata']['sha256']:raise ValueError('SfM geometry bytes changed')
        counts={frame:len({image for batch,key in zip(batches,frames)if key==frame for image in batch.get('image_ids',[])})for frame in frames}
        primary=max(dict.fromkeys(frames),key=lambda frame:counts[frame])
        return {'batches':[{'state':'PREDICTED','scale':1.,'T_common_batch':np.eye(4).tolist(),
                'scope':'selected relative SfM component; identity transform is not metric scale'}if frame==primary else
                {'state':'UNRESOLVED','needs':['Separate SfM component retained; bridging evidence required before joining the selected component']}for frame in frames],
                'selected_common_frame':primary,'selection':'largest registered train component; no held-out views or component merge',
                'metric_scale_verified':False,'physical_verified':False}
    loaded=[]
    for batch in batches:
        if sha(batch['path'])!=batch['metadata']['sha256']:raise ValueError('Geometry batch bytes changed')
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
    return {'batches':[resolved.get(i,{'state':'UNRESOLVED','needs':['Add overlapping views; independent Geometry frames were not merged']})for i in range(len(batches))],
            'metric_scale_verified':False,'physical_verified':False}


def metric_plane(points,dimensions,*,target_pose=None,camera_centers=()):
    """Measured rectangular support, visible plane; World origin/yaw may be a gauge.

    Returns an estimate only when the two observed extents agree on scale.
    Occlusion/truncation is not silently treated as a complete measurement.
    """
    from scipy.spatial import ConvexHull
    points=np.asarray(points,float);size=np.asarray(dimensions,float)
    if points.ndim!=2 or points.shape[1]!=3 or len(points)<50 or size.shape!=(3,)or not np.isfinite(points).all()or not np.isfinite(size[:2]).all()or np.any(size[:2]<=0):
        return {'status':'UNRESOLVED','needs':['Visible rectangular support and measured dimensions required']}
    center=np.median(points,axis=0);_,singular,vt=np.linalg.svd(points-center,full_matrices=False)
    if singular[1]<1e-9 or singular[2]>singular[1]*.08:return {'status':'UNRESOLVED','needs':['Measured support mask is not a visible plane']}
    normal=vt[2];centers=np.asarray(camera_centers)
    if len(centers)and normal@(centers.mean(0)-center)<0:normal=-normal
    flat=(points-center)@vt[:2].T;hull=flat[ConvexHull(flat).vertices]
    best=None
    for edge in np.diff(np.vstack([hull,hull[0]]),axis=0):
        direction=edge/np.linalg.norm(edge);axes=np.column_stack([direction,[-direction[1],direction[0]]]);projected=flat@axes
        extent=np.ptp(projected,axis=0);area=np.prod(extent)
        if best is None or area<best[0]:best=(area,axes,extent,(projected.max(0)+projected.min(0))/2)
    _,axes,extent,offset=best
    if (extent[0]>extent[1])!=(size[0]>size[1]):axes=axes[:,::-1];extent=extent[::-1];offset=offset[::-1]
    scales=size[:2]/extent
    if np.ptp(scales)/np.mean(scales)>.12:return {'status':'UNRESOLVED','needs':['Observed support aspect ratio disagrees with measurements; check mask/occlusion']}
    basis=vt[:2].T@axes;x=basis[:,0];y=np.cross(normal,x);rotation=np.column_stack([x,y,normal])
    source_center=center+basis@offset;scale=float(np.mean(scales))
    target=np.eye(4)if target_pose is None else np.asarray(target_pose,float)
    pose=np.eye(4);pose[:3,:3]=target[:3,:3]@rotation.T;pose[:3,3]=target[:3,3]-pose[:3,:3]@(scale*source_center)
    return {'status':'ESTIMATED','scale':scale,'T_world_relative':pose.tolist(),'source':'measured rectangular support dimensions',
        'plane_rmse_relative':float(singular[2]/np.sqrt(len(points))),'provenance':'derived','physical_verified':False,
        'gauge':'support center/normal; in-plane axis sign is not independently calibrated'}
