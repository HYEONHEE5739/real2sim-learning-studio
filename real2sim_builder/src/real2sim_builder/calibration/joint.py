"""Bounded landmark and raw-depth Camera/Object fitting; no control or physics."""
import copy
from collections import Counter

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from ..capture import observation_scene
from ..editing import preserve
from ..files import sha
from ..observations import annotation_evidence, registered_images,camera_type
from ..scene import frame_world, local_path, validate, value, world_pose
from .camera import project_point


def _mounted(scene, frame):
    while frame is not None:
        if frame.startswith('robot_link_'):
            return True
        frame = scene['frames'][frame]['parent']
    return False


def _support(scene, obj, explicit):
    """Use an explicit support or an already coincident horizontal box surface."""
    objects = {o['id']: o for o in scene['objects']}
    pose = world_pose(scene, obj)
    size = obj['dimensions']['value']
    if size is None or not np.allclose(pose[:3, 2], [0, 0, 1], atol=1e-7):
        return None
    candidates = [objects[explicit]] if explicit else [o for o in objects.values()
                  if o['role'] == 'support_surface' and o['id'] != obj['id']]
    found = []
    for support in candidates:
        dims = support['dimensions']['value']
        t = world_pose(scene, support)
        if (dims is None or support['collision']['type'] != 'box'
                or not np.allclose(t[:3, 2], [0, 0, 1], atol=1e-7)):
            continue
        height = t[2, 3] + dims[2]/2 + size[2]/2
        error = abs(pose[2, 3]-height)
        if explicit or error <= .002:
            found.append((error, support['id'], height))
    return min(found) if found else None


def _posed(candidate, cached):
    result = copy.deepcopy(candidate)
    result['frames'].update({k:v for k,v in cached['frames'].items()if k.startswith('robot_link_')})
    reference = {o['id']: o for o in cached['objects'] if o.get('link')}
    for obj in result['objects']:
        if obj['id'] in reference:
            obj['frame'] = reference[obj['id']]['frame']
            obj['pose'] = reference[obj['id']]['pose']
    return result


def fit_depth_bundle(project,scene,options=None):
    """Joint camera/mount/base/object/scale fit from raw optical observations.

    Backprojects each view on every evaluation. No stale World cloud can drive
    camera updates. Known poses/dimensions/URDF/q stay fixed; measured anchors or
    motion-resolved scale are required before this metric refinement.
    """
    from scipy.spatial import cKDTree
    from .hybrid import surface_points,assign_pose
    from ..files import write
    from ..scene import camera_calibration_signature
    import uuid
    options=options or{};observations=scene.get('reconstruction_observations',{}).get('clouds',[])
    images={i.get('id'):i for i in project.evidence['images']};rows=[];needs=[]
    if {r['group_id']for r in observations if r['split']=='train'}&{r['group_id']for r in observations if r['split']=='validation'}:
        raise ValueError('Train/holdout observation group leakage')
    original_nodes={o['id']:o for o in scene['objects']};models={}
    for row in observations:
        project.checkpoint();path=local_path(project.root,row['path'])
        if sha(path)!=row['sha256']:raise ValueError('Raw depth observation changed')
        with np.load(path,allow_pickle=False)as data:
            if 'points_camera_relative'not in data:continue
            raw={k:v.copy()for k,v in data.items()}
        image=images.get(row['image_id']);camera=row.get('camera')or(image or{}).get('camera')
        if camera is None:raise ValueError('Depth observation Camera missing')
        obj=original_nodes[row['object_id']]
        if obj['visual']['type']=='unknown'or obj['pose']['value']is None:continue
        if row['object_id']not in models:
            model=surface_points(obj,scene,project.root,int(options.get('surface_samples',2000)));models[row['object_id']]=cKDTree(model)
        count=len(raw['points_camera_relative']);take=np.linspace(0,count-1,min(count,700),dtype=int)
        raw={k:(v[take]if k in('points_camera_relative','uv_original','depth_relative')else v)for k,v in raw.items()}
        rows.append((row,raw,camera,image))
    training=[r for r in rows if r[0]['split']=='train']
    report={'status':'NEEDS_MORE_DATA','needs':needs,'physical_verified':False,'scope':'OPTIMIZED_UNVERIFIED_DRAFT'}
    if not training:return scene,{**report,'needs':['Raw optical depth observations with registered scale and visible object assets required']}
    blocks=[];bounds=[]
    def add(kind,name,seed,size,limits):
        blocks.append((kind,name,seed,len(bounds),size));bounds.extend(limits)
    cams={c['id']:c for c in scene['cameras']};observed={r[2]for r in training}
    translation=float(options.get('translation_bound_m',.08));angle=float(options.get('rotation_bound_rad',.35))
    if not np.isfinite([translation,angle]).all()or min(translation,angle)<=0:raise ValueError('Positive fitting bounds required')
    external={r[0]['image_id']for r in training if scene.get('view_registrations',{}).get(r[0]['image_id'],{}).get('T_world_camera')is not None}
    for name in options.get('cameras',sorted(observed)):
        cam=cams[name]
        if name not in observed:continue
        if cam['pose']['value']is not None and cam['pose']['provenance']not in('measured','calibrated'):
            add('camera',name,np.asarray(cam['pose']['value']),6,[translation]*3+[angle]*3)
        if options.get('optimize_intrinsics',False)and cam['K']['provenance']not in('measured','calibrated'):
            if any(r[2]==name and 'uv_original'not in r[1]for r in training):needs.append(name+': raw pixel rays required to refine K')
            else:add('intrinsics',name,np.asarray(cam['K']['value']),4,[.15,.15,cam['resolution'][0]*.05,cam['resolution'][1]*.05])
    for image_id in sorted(external):
        registration=scene['view_registrations'][image_id]
        if registration.get('status')=='REGISTERED_CALIBRATED':continue
        if options.get('external_views',True):add('view',image_id,np.asarray(registration['T_world_camera']),6,[translation]*3+[angle]*3)
    if options.get('robot_base')and 'robot_base'in scene['frames']and scene['frames']['robot_base']['transform']['provenance']not in('measured','calibrated'):
        add('base','robot_base',np.asarray(scene['frames']['robot_base']['transform']['value']),6,[translation]*3+[angle]*3)
    for name in options.get('objects',sorted({r[0]['object_id']for r in training})):
        obj=original_nodes[name]
        if name not in models or obj.get('link')or obj['role']=='reference_robot'or obj['pose']['provenance']in('measured','calibrated'):continue
        support=_support(scene,obj,options.get('supports',{}).get(name))
        add('object_support'if support else'object',name,(world_pose(scene,obj),support),3 if support else 6,[translation]*2+[angle]if support else[translation]*3+[angle]*3)
    if options.get('optimize_depth_scale',False):
        # Scale is shared by inference batch, never independently per object.
        for group in sorted({r[0].get('depth_batch',r[0]['image_id'])for r in training}):add('scale',group,0.,1,[.25])
    if not blocks:return scene,{**report,'needs':['All observed variables are protected or no variable was selected']}
    def assign(x):
        result=copy.deepcopy(scene);scales={}
        for kind,name,seed,start,count in blocks:
            delta=x[start:start+count]
            if kind=='scale':scales[name]=np.exp(delta[0]);continue
            if kind=='intrinsics':
                k=seed.copy();k[0,0]*=np.exp(delta[0]);k[1,1]*=np.exp(delta[1]);k[0,2]+=delta[2];k[1,2]+=delta[3]
                next(c for c in result['cameras']if c['id']==name)['K']=value(k.tolist(),'optimized',['raw depth bundle']);continue
            pose=seed[0].copy()if kind.startswith('object')else seed.copy()
            if kind=='object_support':
                pose[:2,3]+=delta[:2];pose[2,3]=seed[1][2];pose[:3,:3]=Rotation.from_euler('z',delta[2]).as_matrix()@pose[:3,:3]
            else:pose[:3,3]+=delta[:3];pose[:3,:3]=Rotation.from_rotvec(delta[3:]).as_matrix()@pose[:3,:3]
            if kind.startswith('object'):result=assign_pose(result,name,pose)
            elif kind=='camera':next(c for c in result['cameras']if c['id']==name)['pose']=value(pose.tolist(),'optimized',['raw depth bundle'])
            elif kind=='base':result['frames'][name]['transform']=value(pose.tolist(),'optimized',['raw depth bundle'])
            elif kind=='view':result['view_registrations'][name]['T_world_camera']=pose.tolist()
            if kind=='view':result['view_registrations'][name]['state']='OPTIMIZED'
        if result.get('geometry_constraints'):
            from ..initialization import apply_geometry_constraints
            result,_=apply_geometry_constraints(result,result['geometry_constraints'])
        return result,scales
    def world_points(trial,scales,row,raw,camera,image):
        posed=observation_scene(trial,image,project.root,complete=False)if image else trial
        cam=next(c for c in posed['cameras']if c['id']==camera);optical=raw['points_camera_relative']
        if 'uv_original'in raw:
            uv=raw['uv_original'];rays=np.linalg.solve(np.asarray(cam['K']['value']),np.c_[uv,np.ones(len(uv))].T).T
            optical=rays*raw['depth_relative'][:,None]
        scale=row.get('depth_scale',1.)*scales.get(row.get('depth_batch',row['image_id']),1.)
        pose=world_pose(posed,cam);world=(optical*scale)@pose[:3,:3].T+pose[:3,3]
        return world,posed
    def errors(x,selected=training,normalized=True):
        project.checkpoint();trial,scales=assign(x);errors=[]
        for row,raw,camera,image in selected:
            world,posed=world_points(trial,scales,row,raw,camera,image)
            obj=next(o for o in posed['objects']if o['id']==row['object_id']);pose=world_pose(posed,obj)
            local=(world-pose[:3,3])@pose[:3,:3];tree=models[row['object_id']];_,indexes=tree.query(local)
            errors.extend((local-tree.data[indexes]).ravel()/(np.sqrt(len(local))if normalized else 1.))
        return np.asarray(errors)
    zero=np.zeros(len(bounds));before=errors(zero);radius=np.asarray(bounds)
    solution=least_squares(lambda x:errors(x),zero,bounds=(-radius,radius),loss='soft_l1',f_scale=.005,
        max_nfev=int(options.get('max_nfev',80)),diff_step=1e-4)
    after=errors(solution.x);trial,scales=assign(solution.x)
    rank=int(np.linalg.matrix_rank(solution.jac*radius[None,:],tol=1e-7))
    def rmse(x,selected):return float(np.sqrt(np.mean(np.sum(errors(x,selected,False).reshape(-1,3)**2,axis=1))))
    report.update(before_rmse_m=rmse(zero,training),after_rmse_m=rmse(solution.x,training),
        rank=rank,parameter_count=len(radius),variables=[{'kind':b[0],'id':b[1]}for b in blocks],
        holdout_used_for_optimization=False,held_out_views=sorted({r[0]['image_id']for r in rows if r[0]['split']=='validation'}),
        world_cloud_reprojection='raw optical rays on each solver evaluation')
    held=[r for r in rows if r[0]['split']=='validation']
    if held:
        report['holdout_before_rmse_m']=rmse(zero,held)
        report['holdout_after_rmse_m']=rmse(solution.x,held)
    if rank<len(radius):return scene,{**report,'status':'UNRESOLVED','needs':needs+['Camera/Object/scale gauge or coverage is ambiguous; add a fixed visible reference or distinct wrist poses']}
    if np.linalg.norm(after)>=np.linalg.norm(before)-1e-9:return scene,{**report,'status':'NOT_IMPROVED'}
    if held and report['holdout_after_rmse_m']>report['holdout_before_rmse_m']+.001:return scene,{**report,'status':'NOT_IMPROVED','needs':['Independent view residual regressed']}
    preserve(scene,trial);validate(trial,project.root)
    # Publish new clouds, not edits of previous inference files.
    folder=project.root/'scratch/depth_bundle'/uuid.uuid4().hex;folder.mkdir(parents=True)
    for index,(row,raw,camera,image)in enumerate(rows):
        current=next(r for r in trial['reconstruction_observations']['clouds']if r['image_id']==row['image_id']and r['object_id']==row['object_id'])
        with np.load(local_path(project.root,row['path']),allow_pickle=False)as data:full={k:v.copy()for k,v in data.items()}
        world,_=world_points(trial,scales,row,full,camera,image);target=folder/f'{index}.npz'
        np.savez_compressed(target,**{**full,'points_world_m':world});current.update(path=target.relative_to(project.root).as_posix(),sha256=sha(target),
            depth_scale=row.get('depth_scale',1.)*scales.get(row.get('depth_batch',row['image_id']),1.))
        if current.get('dependencies'):
            current['dependencies']['camera_signature']=camera_calibration_signature(trial,next(c for c in trial['cameras']if c['id']==camera))
            current['dependencies']['camera_pose']=world_pose(observation_scene(trial,image,project.root,complete=False),next(c for c in observation_scene(trial,image,project.root,complete=False)['cameras']if c['id']==camera)).tolist()
    for image_id,binding in trial.get('view_registrations',{}).items():
        image=images.get(image_id)
        if image:binding['camera_signature']=camera_calibration_signature(trial,next(c for c in trial['cameras']if c['id']==image['camera']))
    report['status']='IMPROVED';write(folder/'report.json',report)
    return trial,report


def fit_joint_scene(project, scene, options=None):
    """Return a Candidate-only draft and per-camera/pose/object residual report."""
    options = dict(options or {})
    report = {'target': 'joint:scene', 'status': 'NEEDS_MORE_DATA', 'physical_verified': False,
              'scope': 'OPTIMIZED_UNVERIFIED_DRAFT', 'needs': [], 'mask_loss': 'NOT_IMPLEMENTED',
              'mask_metrics': 'Use Candidate.evaluate with approved silhouette annotations'}
    images, state, needs = registered_images(project, options.get('scene_state'),scene=scene)
    report.update(scene_state_id=state, needs=needs)
    if not images:
        return scene, report
    declared = scene.get('reconstruction_state', {}).get('id')
    if declared and declared != state:
        raise ValueError('Candidate and observations declare different layouts')
    evidence = annotation_evidence(project, scene)
    by_id = {i['id']: i for i in images}
    cameras = {c['id']: c for c in scene['cameras']}
    missing = [i['camera'] for i in images if i['camera'] not in cameras or
               any(cameras[i['camera']][field]['value'] is None for field in ('K', 'distortion'))or
               (cameras[i['camera']]['pose']['value']is None and not scene.get('view_registrations',{}).get(i['id'],{}).get('T_world_camera'))]
    if missing:
        report['needs'] = ['Initialize camera pose/K/distortion before joint fitting: ' + ', '.join(sorted(set(missing))),
                           'Use existing bootstrap/intrinsics fitting with explicit CAD correspondences']
        return scene, report
    model = scene.get('robot_model')
    if not model and any(i.get('session_id')or camera_type(i)=='wrist'for i in images):
        report['needs'] = ['Import the actual robot model and measured-joint mapping']
        return scene, report
    if model and sha(local_path(project.root, model['path'])) != model['model_sha256']:
        raise ValueError('Robot model bytes differ from Candidate identity')
    for image in images:
        if (image.get('q_measured')is not None and(not model or image['joint_names']!=model['joint_names']))or image['resolution']!=cameras[image['camera']]['resolution']:
            raise ValueError('Observation robot order or camera resolution differs')
    rows = [r for r in evidence.get('landmarks', []) if r.get('observation') in by_id
            and r.get('visible', True) and r.get('occluded') is not True
            and float(r.get('weight', 1)) > 0 and float(r.get('confidence', 1)) >= options.get('min_confidence', .2)]
    train = [r for r in rows if by_id[r['observation']]['split'] == 'train']
    held = [r for r in rows if by_id[r['observation']]['split'] == 'validation']
    if {by_id[r['observation']]['group_id'] for r in train} & {by_id[r['observation']]['group_id'] for r in held}:
        raise ValueError('Train/holdout group leakage')
    if len(train) < 4:
        report['needs'] = ['Review >=4 visible CAD-to-pixel correspondences; masks alone do not drive this MVP fit',
                           'Keep the metric Scene draft; request another unobscured camera/pose if needed']
        return scene, report
    for row in rows:
        uv = np.asarray(row['uv'], float)
        sigma = float(row.get('sigma_px', 3))
        confidence = float(row.get('confidence', 1))
        if (uv.shape != (2,) or not np.isfinite(uv).all() or not np.isfinite(sigma) or sigma <= 0
                or not np.isfinite(confidence) or not 0 < confidence <= 1):
            raise ValueError('Finite pixel/confidence and positive pixel uncertainty required')
    candidate = copy.deepcopy(scene)
    nodes = {o['id']: o for o in candidate['objects']}
    camera_nodes = {c['id']: c for c in candidate['cameras']}
    cached = {i['id']: observation_scene(scene, i, project.root, complete=False) for i in images}
    blocks = []
    lower, upper = [], []
    translation = float(options.get('translation_bound_m', .05))
    angle = float(options.get('rotation_bound_rad', .3))
    if not np.isfinite([translation, angle]).all() or min(translation, angle) <= 0:
        raise ValueError('Positive finite pose bounds required')
    observed_cameras = {by_id[r['observation']]['camera'] for r in train}
    for name in options.get('cameras', sorted(observed_cameras)):
        if name not in observed_cameras:
            continue
        if name not in camera_nodes:
            continue
        cam = camera_nodes[name]
        if cam['pose']['value']is None:continue  # External views have separate registered poses.
        if cam['pose']['provenance'] in ('measured', 'calibrated'):
            continue
        if (name == 'wrist') != _mounted(scene, cam['frame']):
            raise ValueError('Side must be fixed and Wrist must use a shared robot-link mount')
        blocks.append(('camera', name, np.asarray(cam['pose']['value'], float), len(lower), 6, None))
        lower.extend([-translation]*3 + [-angle]*3)
        upper.extend([translation]*3 + [angle]*3)
    observed_objects = {r.get('object') for r in train}
    selected = options.get('objects', [o['id'] for o in scene['objects']
                                     if o['id'] in observed_objects and o['role'] in ('manipulable_object', 'receptacle')])
    for name in selected:
        obj = nodes[name]
        if obj['pose']['provenance'] in ('measured', 'calibrated'):
            continue
        if obj.get('link') or _mounted(scene, obj['frame']):
            raise ValueError('Joint Scene objects must have static world poses, not robot-link poses')
        if obj['pose']['value'] is None:
            report['needs'] = ['Initialize a metric object pose: ' + name]
            return scene, report
        support = _support(scene, obj, options.get('supports', {}).get(name))
        count = 3 if support else 6
        blocks.append(('object', name, world_pose(scene, obj), len(lower), count, support))
        lower.extend([-translation]*2 + [-angle] if support else [-translation]*3 + [-angle]*3)
        upper.extend([translation]*2 + [angle] if support else [translation]*3 + [angle]*3)
    if not blocks:
        report['needs'] = ['All requested variables are measured/calibrated or no variable was selected']
        return scene, report
    moving = {name for kind, name, *_ in blocks if kind == 'object'}
    constraints = copy.deepcopy(scene.get('geometry_constraints'))
    if constraints:
        for row in constraints['distances']:
            pair = set(row['objects'])
            if pair & moving and any(n not in moving and nodes[n]['pose']['provenance'] not in ('measured', 'calibrated') for n in pair):
                raise ValueError('Select both members of a constrained pair or retain a measured pose anchor')
    def assign(x):
        nonlocal candidate
        candidate = copy.deepcopy(scene)
        current = {o['id']: o for o in candidate['objects']}
        cams = {c['id']: c for c in candidate['cameras']}
        for kind, name, seed, offset, count, support in blocks:
            delta = x[offset:offset+count]
            pose = seed.copy()
            if support:
                a = delta[2]
                rotation = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
                pose[:3, :3] = rotation @ seed[:3, :3]
                pose[:2, 3] += delta[:2]
                pose[2, 3] = support[2]
            else:
                pose[:3, :3] = Rotation.from_rotvec(delta[3:]).as_matrix() @ seed[:3, :3]
                pose[:3, 3] += delta[:3]
            target = cams[name] if kind == 'camera' else current[name]
            if kind == 'object':
                pose = np.linalg.inv(frame_world(candidate, target['frame'])) @ pose
            target['pose'] = value(pose.tolist(), 'optimized', ['bounded joint:scene image-derived draft'])
            if kind == 'camera':
                target['calibration_quality'] = {'state': 'ESTIMATED', 'physical_verified': False,
                                                 'scope': 'joint image-derived draft; no independent calibration'}
        if constraints and moving:
            from ..initialization import apply_geometry_constraints
            active = {'schema': constraints['schema'], 'units': constraints['units'],
                      'distances': [r for r in constraints['distances'] if set(r['objects']) & moving]}
            if active['distances']:
                candidate, _ = apply_geometry_constraints(candidate, active)
                candidate['geometry_constraints'] = copy.deepcopy(constraints)
        # Preserve each dependent fixture's object-relative pose (decals, etc.).
        current = {o['id']: o for o in candidate['objects']}
        original = {o['id']: o for o in scene['objects']}
        for obj in candidate['objects']:
            parent = obj.get('parent_object')
            if parent in moving and obj['id'] not in moving:
                relative = np.linalg.inv(world_pose(scene, original[parent])) @ world_pose(scene, original[obj['id']])
                world = world_pose(candidate, current[parent]) @ relative
                obj['pose'] = value((np.linalg.inv(frame_world(candidate, obj['frame'])) @ world).tolist(), 'optimized', ['parent object joint fit'])
    def errors(rows_to_measure):
        posed = {}
        result = []
        for row in rows_to_measure:
            key = row['observation']
            if key not in posed:
                posed[key] = _posed(candidate, cached[key])
            cam = next(c for c in posed[key]['cameras'] if c['id'] == by_id[key]['camera'])
            uv, depth = project_point(posed[key], cam, row)
            result.append((row, uv-np.asarray(row['uv'], float), float(depth)))
        return result
    def summarize(rows_to_measure):
        grouped, outliers = {}, []
        behind = 0
        for row, delta, z in errors(rows_to_measure):
            image = by_id[row['observation']]
            pose_id = image.get('session_id', 'registered')+':'+(image.get('snapshot_id') or image['id'])
            key = (image['camera'], pose_id, row.get('object', row.get('frame', 'world')))
            error = float(np.linalg.norm(delta))
            grouped.setdefault(key, []).append(error)
            outliers.append({'observation': image['id'], 'camera': image['camera'], 'object': row.get('object'), 'error_px': error})
            behind += int(z <= 0)
        flat = [e for values in grouped.values() for e in values]
        return {'count': len(flat), 'rmse_px': float(np.sqrt(np.mean(np.square(flat)))) if flat else None,
                'behind_camera': behind,
                'groups': [{'camera': k[0], 'pose': k[1], 'object': k[2], 'count': len(v),
                            'rmse_px': float(np.sqrt(np.mean(np.square(v))))} for k, v in sorted(grouped.items())],
                'worst_outliers': sorted(outliers, key=lambda r: r['error_px'], reverse=True)[:10]}
    counts = Counter((by_id[r['observation']]['camera'], r['observation'], r.get('object', r.get('frame', 'world'))) for r in train)
    radius = np.asarray(upper, float)
    def residual(x, prior=True):
        assign(x)
        values = []
        for row, delta, depth in errors(train):
            image = by_id[row['observation']]
            group = (image['camera'], row['observation'], row.get('object', row.get('frame', 'world')))
            weight = np.sqrt(float(row.get('weight', 1))*float(row.get('confidence', 1))/counts[group]) / float(row.get('sigma_px', 3))
            values.extend(delta*weight)
            values.append(max(0., .001-depth)*1e4)
        if prior:
            values.extend(x/radius*float(options.get('pose_prior', .2)))
        return np.asarray(values)
    # Baseline is the supplied Scene, before support projection or constraints.
    candidate = copy.deepcopy(scene)
    before = summarize(train)
    held_before = summarize(held)
    solution = least_squares(residual, np.zeros(len(lower)), bounds=(lower, upper), loss='soft_l1',
                             max_nfev=int(options.get('max_nfev', 100)))
    assign(solution.x)
    after, held_after = summarize(train), summarize(held)
    jac = solution.jac[:3*len(train)] * radius[None, :]
    singular = np.linalg.svd(jac, compute_uv=False)
    rank = int(np.linalg.matrix_rank(jac))
    condition = float(singular[0]/singular[-1]) if rank == len(lower) and singular[-1] > 1e-12 else None
    baseline = {(r['camera'], r['pose'], r['object']): r['rmse_px'] for r in before['groups']}
    limit = float(options.get('max_group_regression_px', 2))
    regressions = [r for r in after['groups'] if r['rmse_px'] > baseline[(r['camera'], r['pose'], r['object'])] + limit]
    observed_objects = {r.get('object') for r in train}
    anchored = any(o['id'] in observed_objects and
                   (o['dimensions']['provenance'] in ('measured', 'calibrated') or o.get('link'))
                   for o in scene['objects'])
    registration = scene.get('world_registration', {})
    if registration and not registration.get('metric_scale_verified'):
        anchored = False
    used_ids = {r['observation'] for r in train}
    used_images = [i for i in images if i['id'] in used_ids]
    report.update(before=before, after=after, holdout_before=held_before, holdout_after=held_after,
                  independent_verification=False, coverage={'eligible_images': len(images), 'images': len(used_images),
                                                          'poses': len({tuple(i.get('q_measured')or[])for i in used_images}),
                                                          'cameras': sorted(observed_cameras), 'layout': state},
                  changed_variables=[{'kind': b[0], 'id': b[1], 'mode': 'xy_yaw_on_support' if b[5] else 'pose6'} for b in blocks],
                  bounds={'lower': lower, 'upper': upper}, bound_hits=np.flatnonzero(np.isclose(abs(solution.x), radius, atol=1e-6)).tolist(),
                  jacobian_rank=rank, parameter_count=len(lower), condition_number=condition,
                  scaled_jacobian_singular_values=singular.tolist(), group_regressions=regressions,
                  metric_scale_anchored=anchored, relative_only=not anchored,
                  held_out_observations=sorted({r['observation'] for r in held}), solver_message=str(solution.message))
    if rank < len(lower):
        report['needs'].append('Rank-deficient draft: add distinct poses and CAD points at different depths; hard pair projection may also reduce effective dimension')
    if not anchored:
        report['needs'].append('Relative draft only: provide a measured size or known metric/world anchor')
    for missing_camera in {'side', 'wrist'} - observed_cameras:
        report['needs'].append(missing_camera+': add reviewed visible CAD points; this camera was not fitted')
    try:
        validate(candidate, project.root)
        preserve(scene, candidate)
    except ValueError as error:
        return scene, {**report, 'status': 'NOT_IMPROVED', 'reason': str(error)}
    held_regressed = bool(held and (held_after['behind_camera'] or held_after['rmse_px'] > held_before['rmse_px']+limit))
    held_groups = {(r['camera'], r['pose'], r['object']): r['rmse_px'] for r in held_before['groups']}
    held_regressions = [r for r in held_after['groups']
                        if r['rmse_px'] > held_groups[(r['camera'], r['pose'], r['object'])]+limit]
    report['holdout_group_regressions'] = held_regressions
    for kind, name, seed, _, _, support in blocks:
        target = next(n for n in candidate['cameras' if kind == 'camera' else 'objects'] if n['id'] == name)
        pose = np.asarray(target['pose']['value'], float) if kind == 'camera' else world_pose(candidate, target)
        if np.any(abs(pose[:3, 3]-seed[:3, 3]) > translation+1e-9):
            return scene, {**report, 'status': 'NOT_IMPROVED', 'reason': 'Support/distance projection exceeded pose bounds: '+name}
        if support and not np.isclose(pose[2, 3], support[2], atol=1e-9, rtol=0):
            return scene, {**report, 'status': 'NOT_IMPROVED', 'reason': 'Object support height changed: '+name}
    if after['behind_camera'] or regressions or held_regressed or held_regressions or after['rmse_px'] >= before['rmse_px']-1e-6:
        return scene, {**report, 'status': 'NOT_IMPROVED', 'reason': 'No aggregate improvement or a camera/pose/object regressed'}
    return candidate, {**report, 'status': 'IMPROVED'}
