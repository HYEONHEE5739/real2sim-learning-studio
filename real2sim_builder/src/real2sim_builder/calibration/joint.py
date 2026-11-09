"""Bounded landmark and raw-depth Camera/Object fitting; no control or physics."""
from scene_contract.naming import numbered_path
import copy
from collections import Counter

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from ..capture import observation_scene
from ..cameras import optical_rays
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


def _support(scene, obj, explicit=None,root=None):
    """Bind declared contact independently of the initial pose; never auto-confirm proximity."""
    from ..scene import support_relations,supported_pose
    name=obj['id'];relations=support_relations(scene,{name:explicit}if explicit is not None else None)
    row=relations.get(name)
    if row is None or row['status']!='CONFIRMED':return None
    pose=world_pose(scene,obj)if 'pose'in obj else frame_world(scene,name)
    if 'yaw_bound_rad'in row and 'yaw_reference_rad'not in row:
        from ..scene import support_binding
        binding=support_binding(scene,name,row,root);relative=binding['basis'].T@pose[:3,:3]@binding['relative_rotation'].T
        row['yaw_reference_rad']=float(np.arctan2(relative[1,0],relative[0,0]))
    return {'relation':row,'pose':supported_pose(scene,name,row,pose,root),'root':root}


def _posed(candidate, cached):
    result = copy.deepcopy(candidate)
    result['frames'].update({k:v for k,v in cached['frames'].items()if k.startswith('robot_link_')})
    reference = {o['id']: o for o in cached['objects'] if o.get('link')}
    for obj in result['objects']:
        if obj['id'] in reference:
            obj['frame'] = reference[obj['id']]['frame']
            obj['pose'] = reference[obj['id']]['pose']
    return result


def parameter_blocks(scene,observations,options,*,root=None):
    """One parameter definition for raw-depth and native-render optimization."""
    blocks=[];bounds=[];cams={c['id']:c for c in scene['cameras']};nodes={o['id']:o for o in scene['objects']}
    train=[r for r in observations if r['split']=='train'];observed={r['camera']for r in train};observed_objects={r.get('object_id')for r in train}&nodes.keys()
    translation=float(options.get('translation_bound_m',.08));angle=float(options.get('rotation_bound_rad',.35))
    if not np.isfinite([translation,angle]).all()or min(translation,angle)<=0:raise ValueError('Positive fitting bounds required')
    def add(kind,name,seed,size,radius):blocks.append((kind,name,seed,len(bounds),size));bounds.extend(radius)
    external={r['image_id']for r in train if scene.get('view_registrations',{}).get(r['image_id'],{}).get('T_world_camera')is not None}
    for name in options.get('cameras',sorted(observed)):
        cam=cams[name]
        if name not in observed:continue
        # External photos share K but have per-view pose, never a second global pose.
        if cam['pose']['value']is not None and cam['pose']['provenance']not in('measured','calibrated')and not all(r['image_id']in external for r in train if r['camera']==name):
            add('camera',name,np.asarray(cam['pose']['value']),6,[translation]*3+[angle]*3)
        if options.get('optimize_intrinsics',False)and cam['K']['provenance']not in('measured','calibrated'):
            add('intrinsics',name,np.asarray(cam['K']['value']),4,[.15,.15,cam['resolution'][0]*.05,cam['resolution'][1]*.05])
    if options.get('external_views',True):
        for key in sorted(external):
            r=scene['view_registrations'][key]
            if r['status']!='REGISTERED_CALIBRATED':add('view',key,np.asarray(r['T_world_camera']),6,[translation]*3+[angle]*3)
    if options.get('robot_base')and 'robot_base'in scene['frames']and scene['frames']['robot_base']['transform']['provenance']not in('measured','calibrated'):
        support=_support(scene,{'id':'robot_base'},options.get('supports',{}).get('robot_base'),root)
        add('base_support'if support else'base','robot_base',(support['pose'],support)if support else frame_world(scene,'robot_base'),(2 if support['relation'].get('yaw_bound_rad')==0 else 3)if support else 6,([translation]*2+([]if support['relation'].get('yaw_bound_rad')==0 else[min(angle,support['relation'].get('yaw_bound_rad',angle))]))if support else[translation]*3+[angle]*3)
    default=[n for n in sorted(observed_objects)if nodes[n]['role']not in('support_surface','fixture')]
    for name in options.get('objects',default):
        obj=nodes[name]
        if name not in{r['object_id']for r in train}or obj.get('link')or obj['role']=='reference_robot'or obj['pose']['value']is None or obj['pose']['provenance']in('measured','calibrated'):continue
        support=_support(scene,obj,options.get('supports',{}).get(name),root)
        add('object_support'if support else'object',name,(support['pose']if support else world_pose(scene,obj),support),(2 if support['relation'].get('yaw_bound_rad')==0 else 3)if support else 6,([translation]*2+([]if support['relation'].get('yaw_bound_rad')==0 else[min(angle,support['relation'].get('yaw_bound_rad',angle))]))if support else[translation]*3+[angle]*3)
    if options.get('optimize_dimensions',False):
        from .geometry import dimension_axes
        radius=float(options.get('dimension_log_bound',.2))
        if not np.isfinite(radius) or not 0<radius<=.5:raise ValueError('dimension_log_bound must be in (0, .5]')
        for name in sorted(observed_objects):
            obj=nodes[name];axes=dimension_axes(obj)
            if axes:add('dimensions',name,(np.asarray(obj['dimensions']['value']),axes),len(axes),[radius]*len(axes))
    if options.get('optimize_depth_scale',False):
        for key in sorted({r.get('depth_batch',r['image_id'])for r in train}):add('scale',key,0.,1,[.25])
    if options.get('optimize_appearance',False):
        for name in sorted(observed_objects):
            obj=nodes[name]
            # Library assets keep one immutable shared material identity. Scene
            # lighting can change without silently editing the asset's bytes.
            if obj.get('object_asset')or obj.get('link')or obj['role']=='reference_robot':continue
            color=obj['color']
            if color['value']is not None and color['provenance']not in('measured','calibrated')and not obj['visual'].get('texture'):
                add('color',name,np.asarray(color['value']),3,[.25]*3)
            for field,record in obj.get('material',{}).items():
                if record['provenance']not in('measured','calibrated'):add(field,name,float(record['value']),1,[.25])
    if options.get('optimize_lighting',False):
        ambient=scene['lights']['ambient']
        if ambient['provenance']not in('measured','calibrated'):add('ambient','ambient',np.asarray(ambient['value']),3,[.15]*3)
        for light in scene['lights'].get('sources',[]):
            if light['energy']['provenance']not in('measured','calibrated')and light['energy']['value']>0:
                add('light_energy',light['id'],float(light['energy']['value']),1,[.5])
    return blocks,np.asarray(bounds)


def select_parameters(scene,observations,options,*,stage='geometry',root=None):
    """Conservative training-only eligibility, not a calibration certificate.

    Keep parameter definitions in parameter_blocks. Select their coordinates
    here so a known symmetry can lock rotation without losing translation.
    """
    if stage not in('geometry','appearance'):raise ValueError('Unknown fitting stage')
    requested={**options}
    for key in('optimize_intrinsics','optimize_depth_scale','robot_base'):requested.setdefault(key,True)
    requested.setdefault('optimize_dimensions',True)
    rows=[r for r in observations if r['split']=='train']
    blocks,radius=parameter_blocks(scene,rows,requested,root=root)
    nodes={o['id']:o for o in scene['objects']};cameras={c['id']:c for c in scene['cameras']}
    images={r['image_id']:r for r in rows};frozen=[];needs=[];indices=[]
    report={'stage':stage,'training_images':sorted(images),'frozen':frozen,'needs':needs,
        'scope':'geometric eligibility and coordinate gauges; not full numerical identifiability or physical calibration'}
    def diverse(records):
        poses=[]
        for row in records:
            if row.get('camera_pose')is None:continue
            pose=np.asarray(row['camera_pose'])
            if not any(np.linalg.norm(pose[:3,3]-p[:3,3])<.005 and
                    np.linalg.norm(Rotation.from_matrix(pose[:3,:3]@p[:3,:3].T).as_rotvec())<.035 for p in poses):poses.append(pose)
        return poses
    def motion(records):
        poses=diverse(records)
        if len(poses)<3:return False
        turns=np.array([Rotation.from_matrix(p[:3,:3]@poses[0][:3,:3].T).as_rotvec()for p in poses[1:]])
        return np.linalg.svd(turns,compute_uv=False)[1]>.05
    moving={b[1]for b in blocks if b[0].startswith('object')}
    moving_cameras={b[1]for b in blocks if b[0]=='camera'}
    moving_views={b[1]for b in blocks if b[0]=='view'}
    moving_base=any(b[0]in('base','base_support')for b in blocks)
    def moves_with_base(frame):
        while frame is not None:
            if frame=='robot_base':return moving_base
            frame=scene['frames'][frame]['parent']
        return False
    # Anchor only to visible fixed geometry or a camera already held fixed.
    # A table elsewhere in the Scene is not evidence for the current image.
    anchored_objects={r['object_id']for r in rows if r['object_id']not in moving and not moves_with_base(nodes[r['object_id']]['frame'])}
    anchored_images={key for key,row in images.items()if row['camera']not in moving_cameras and key not in moving_views
        and not _mounted(scene,cameras[row['camera']]['frame'])and not moves_with_base(cameras[row['camera']]['frame'])}
    for _ in range(len(images)+1):
        previous=(len(anchored_objects),len(anchored_images))
        anchored_objects.update(r['object_id']for r in rows if r['image_id']in anchored_images)
        anchored_images.update(r['image_id']for r in rows if r['object_id']in anchored_objects)
        if previous==(len(anchored_objects),len(anchored_images)):break
    fixed_color=any(nodes[r['object_id']].get('object_asset')or nodes[r['object_id']]['color']['provenance']in('measured','calibrated')
        or not options.get('optimize_appearance',False) for r in rows)
    for kind,name,seed,start,count in blocks:
        appearance=kind in('color','roughness','metallic','ambient','light_energy')
        if appearance!=(stage=='appearance'):continue
        reason=None;locked=[];required=False
        related=[r for r in rows if r['camera']==name]if kind in('camera','intrinsics')else rows
        if kind=='view':related=[r for r in rows if r['image_id']==name]
        if kind in('camera','view'):
            if not any(r['image_id']in anchored_images for r in related):
                reason='unanchored_camera_object_gauge';required=True
            if any(r.get('camera_type')=='wrist'for r in related)and(not all(r.get('measured_q')for r in related)or not motion(related)):
                reason='insufficient_wrist_motion';required=True
            if not all(r.get('has_raw_depth')or r.get('has_image_observation')for r in related):reason='raw_camera_rays_required';required=True
        elif kind=='intrinsics':
            if len(diverse(related))<3 or not any(r.get('cloud_rank',0)==3 for r in related):reason='insufficient_lens_view_geometry'
            elif not any(r['image_id']in anchored_images for r in related):reason='unanchored_lens_pose_gauge'
            elif not all(r.get('has_raw_depth')for r in related):reason='raw_camera_rays_required'
        elif kind in('base','base_support'):
            wrist=[r for r in rows if r.get('camera_type')=='wrist'and r.get('measured_q')]
            if not motion(wrist)or not any(r['image_id']in anchored_images for r in wrist)or not all(r.get('has_raw_depth')for r in wrist):reason='insufficient_world_hand_eye_constraints'
        elif kind=='scale':
            related=[r for r in rows if r.get('depth_batch',r['image_id'])==name]
            metric=any(nodes[r['object_id']]['dimensions']['provenance']in('measured','calibrated')for r in related)
            if not metric or len(diverse(related))<2 or not all(r.get('has_raw_depth')for r in related):reason='insufficient_metric_scale_constraints'
        elif kind=='dimensions':
            related=[r for r in rows if r['object_id']==name]
            if len(diverse(related))<2 or not any(r.get('cloud_rank',0)==3 for r in related) or not all(r.get('has_raw_depth') for r in related):
                reason='insufficient_dimension_geometry'
            elif not all(r['image_id']in anchored_images for r in related):reason='insufficient_dimension_geometry'
        elif kind.startswith('object'):
            obj=nodes[name];related=[r for r in rows if r['object_id']==name]
            if not any(r.get('cloud_rank',0)>=2 and(r.get('has_raw_depth')or
                    (r['camera']not in moving_cameras and r['image_id']not in moving_views))for r in related)and len(diverse(related))<2:
                reason='insufficient_object_geometry';required=True
            shape=obj['visual']['type'];dims=obj['dimensions']['value']
            symmetric=(not obj.get('object_asset')and not obj['visual'].get('texture')and obj['collision']['type']==shape
                and not any(o.get('parent_object')==name for o in nodes.values()))
            if symmetric and shape=='sphere'and np.allclose(dims,[dims[0]]*3):locked=list(range(3,count))if kind=='object'else[2]
            if symmetric and shape=='cylinder'and np.isclose(dims[0],dims[1])and np.allclose(world_pose(scene,obj)[:3,2],[0,0,1]):locked=[5]if kind=='object'else[2]
        elif kind in('ambient','light_energy')and not fixed_color:reason='albedo_lighting_ambiguity'
        if reason:
            actions={
                'unanchored_camera_object_gauge':'같은 물체가 보이는 고정 기준 Camera 또는 위치가 알려진 기준 물체 관측을 추가하세요.',
                'insufficient_wrist_motion':'같은 정적 배치에서 서로 다른 두 축으로 회전한 Wrist 자세 3개 이상과 실제 q를 확보하세요.',
                'insufficient_lens_view_geometry':'같은 렌즈의 서로 다른 시점 3개 이상과 깊이가 다양한 물체 관측을 추가하세요.',
                'unanchored_lens_pose_gauge':'World 기준을 확보한 뒤 초점·Camera 위치를 함께 정합하세요.',
                'insufficient_world_hand_eye_constraints':'고정 World 기준과 여러 축으로 움직인 Wrist의 measured-q 관측을 추가하세요.',
                'insufficient_metric_scale_constraints':'실측 크기와 raw depth가 연결된 서로 다른 시점 관측을 확보하세요.',
                'insufficient_object_geometry':'유효한 depth 또는 같은 물체를 보는 서로 다른 시점을 추가하세요.',
                'albedo_lighting_ambiguity':'색이 고정된 물체 관측이 없으므로 현재 조명을 유지하고 물체 외관만 조정합니다.'}
            actions['raw_camera_rays_required']='Camera를 변경하려면 원 pixel ray/depth 관측을 복구하세요. World 점군만으로 Camera를 재정합하지 않습니다.'
            actions['insufficient_dimension_geometry']='물체 크기는 World 기준과 raw metric depth가 있는 서로 다른 시점·입체 관측으로 정합합니다.'
            frozen.append({'kind':kind,'id':name,'coordinates':list(range(count)),'reason':reason,'action':actions[reason]})
            if required:needs.append(name+': '+actions[reason])
            continue
        if locked:frozen.append({'kind':kind,'id':name,'coordinates':locked,'reason':'uniform_primitive_rotation_symmetry'})
        indices.extend(i for i in range(start,start+count)if i-start not in locked)
    report['active']=[{'kind':k,'id':n,'coordinates':[i-s for i in indices if s<=i<s+c]}for k,n,_,s,c in blocks if any(s<=i<s+c for i in indices)]
    return blocks,radius,np.asarray(indices,dtype=int),report


def apply_parameters(scene,blocks,x,*,root=None):
    from .hybrid import assign_pose
    result=copy.deepcopy(scene);scales={}
    for kind,name,seed,start,count in blocks:
        delta=x[start:start+count]
        if kind=='scale':scales[name]=float(np.exp(delta[0]));continue
        if kind=='dimensions':
            obj=next(o for o in result['objects']if o['id']==name);dims=seed[0].copy()
            for axes,change in zip(seed[1],delta):dims[list(axes)]*=np.exp(change)
            obj['dimensions']={**obj['dimensions'],**value(dims.tolist(),'optimized',['native multiview dimension fit; not measured'])}
            continue
        if kind in('color','roughness','metallic','ambient','light_energy'):
            if kind=='light_energy':
                target=next(l for l in result['lights']['sources']if l['id']==name);field='energy';updated=float(seed*np.exp(delta[0]))
            elif kind=='ambient':target=result['lights'];field='ambient';updated=np.maximum(0,seed+delta).tolist()
            else:
                target=next(o for o in result['objects']if o['id']==name);field=kind
                if kind=='color':updated=np.clip(seed+delta,0,1).tolist()
                else:target=target['material'];updated=float(np.clip(seed+delta[0],0,1))
            target[field]=value(updated,'optimized',['native multiview appearance fit; not measured material']);continue
        if kind=='intrinsics':
            k=seed.copy();k[0,0]*=np.exp(delta[0]);k[1,1]*=np.exp(delta[1]);k[0,2]+=delta[2];k[1,2]+=delta[3]
            next(c for c in result['cameras']if c['id']==name)['K']=value(k.tolist(),'optimized',['joint image/depth fit']);continue
        pose=seed[0].copy()if kind.startswith('object')or kind=='base_support'else seed.copy()
        if kind in('object_support','base_support'):
            from ..scene import support_binding
            basis=support_binding(result,name,seed[1]['relation'],root)['basis']
            pose[:3,3]+=basis[:,:2]@delta[:2]
            pose[:3,:3]=Rotation.from_rotvec(basis[:,2]*(delta[2]if count==3 else 0.)).as_matrix()@pose[:3,:3]
        else:pose[:3,3]+=delta[:3];pose[:3,:3]=Rotation.from_rotvec(delta[3:]).as_matrix()@pose[:3,:3]
        if kind.startswith('object'):result=assign_pose(result,name,pose)
        elif kind=='camera':next(c for c in result['cameras']if c['id']==name)['pose']=value(pose.tolist(),'optimized',['joint image/depth fit'])
        elif kind in('base','base_support'):
            parent=result['frames'][name]['parent'];local=np.linalg.inv(frame_world(result,parent))@pose
            result['frames'][name]['transform']=value(local.tolist(),'optimized',['joint image/depth fit'])
        elif kind=='view':result['view_registrations'][name].update(T_world_camera=pose.tolist(),state='OPTIMIZED')
    from ..initialization import project_supports
    declared={name:seed[1]['relation']for kind,name,seed,_,_ in blocks if kind in('object_support','base_support')}
    result,_=project_supports(result,declared,root)
    if result.get('geometry_constraints'):
        from ..initialization import apply_geometry_constraints
        result,_=apply_geometry_constraints(result,result['geometry_constraints'],root=root)
    return result,scales


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
    options=options or{}
    from ..initialization import project_supports
    scene,physical=project_supports(scene,options.get('supports'),project.root)
    observations=scene.get('reconstruction_observations',{}).get('clouds',[])
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
    report={'status':'NEEDS_MORE_DATA','needs':needs,'physical_verified':False,'scope':'OPTIMIZED_UNVERIFIED_DRAFT','physical_constraints':physical}
    if not training:return scene,{**report,'needs':['Raw optical depth observations with registered scale and visible object assets required']}
    observations=[{**r[0],'camera':r[2]}for r in training]
    blocks,bounds=parameter_blocks(scene,observations,options,root=project.root)
    if not blocks:return scene,{**report,'needs':['All observed variables are protected or no variable was selected']}
    def assign(x):return apply_parameters(scene,blocks,x,root=project.root)
    def world_points(trial,scales,row,raw,camera,image):
        posed=observation_scene(trial,image,project.root,complete=False)if image else trial
        cam=next(c for c in posed['cameras']if c['id']==camera);optical=raw['points_camera_relative']
        if 'uv_original'in raw:
            uv=raw['uv_original'];rays=optical_rays(cam,uv)
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
    folder=numbered_path(project.root/'scratch/depth_bundle','fit');folder.mkdir(parents=True)
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
    from ..scene import support_metrics
    report['physical_constraints']=support_metrics(trial,root=project.root)
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
    from ..initialization import project_supports
    scene,physical=project_supports(scene,options.get('supports'),project.root)
    candidate=copy.deepcopy(scene);nodes={o['id']:o for o in scene['objects']}
    cached={i['id']:observation_scene(scene,i,project.root,complete=False)for i in images}
    observed_cameras={by_id[r['observation']]['camera']for r in train}
    for name in observed_cameras:
        cam=cameras[name]
        if (name=='wrist')!=_mounted(scene,cam['frame']):
            raise ValueError('Side must be fixed and Wrist must use a shared robot-link mount')
    observed_objects={r.get('object')for r in train}&nodes.keys()
    selected=options.get('objects',[n for n in observed_objects if nodes[n]['role']in('manipulable_object','receptacle')])
    for name in selected:
        obj=nodes[name]
        if obj.get('link')or _mounted(scene,obj['frame']):raise ValueError('Joint Scene objects must have static world poses, not robot-link poses')
        if obj['pose']['value']is None:
            return scene,{**report,'needs':['Initialize a metric object pose: '+name]}
    records=[dict(split='train',camera=by_id[r['observation']]['camera'],image_id=r['observation'],object_id=r.get('object'))for r in train]
    translation=float(options.get('translation_bound_m',.05))
    settings={**options,'objects':selected,'translation_bound_m':translation,'rotation_bound_rad':options.get('rotation_bound_rad',.3),
        'optimize_dimensions':False,'optimize_intrinsics':False,'optimize_appearance':False,'optimize_lighting':False,'optimize_depth_scale':False}
    blocks,radius=parameter_blocks(scene,records,settings,root=project.root)
    lower=(-radius).tolist();upper=radius.tolist()
    if not blocks:return scene,{**report,'needs':['All requested variables are measured/calibrated or no variable was selected']}
    moving={name for kind,name,*_ in blocks if kind.startswith('object')}
    for row in scene.get('geometry_constraints',{}).get('distances',[]):
        pair=set(row['objects'])
        if pair&moving and any(n not in moving and nodes[n]['pose']['provenance']not in('measured','calibrated')for n in pair):
            raise ValueError('Select both members of a constrained pair or retain a measured pose anchor')
    def assign(x):
        nonlocal candidate
        candidate,_=apply_parameters(scene,blocks,x,root=project.root)
        for kind,name,*_ in blocks:
            if kind=='camera':
                next(c for c in candidate['cameras']if c['id']==name)['calibration_quality']={
                    'state':'ESTIMATED','physical_verified':False,'scope':'joint image-derived draft; no independent calibration'}
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
    # Measure after physical initialization; optimizing pixels cannot undo contact.
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
                  changed_variables=[{'kind': b[0], 'id': b[1], 'mode': 'xy_yaw_on_support' if b[0]in('object_support','base_support') else 'pose6'} for b in blocks],
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
    from ..scene import support_metrics
    report['physical_constraints']=support_metrics(candidate,root=project.root)
    for kind,name,seed,_,_ in blocks:
        if kind not in('object','camera','base'):continue
        target=next(n for n in candidate['cameras'if kind=='camera'else'objects']if n['id']==name)if kind!='base'else None
        pose=frame_world(candidate,name)if kind=='base'else np.asarray(target['pose']['value'])if kind=='camera'else world_pose(candidate,target)
        initial=seed[0]if kind=='object'else seed
        if np.any(abs(pose[:3,3]-initial[:3,3])>translation+1e-9):
            return scene,{**report,'status':'NOT_IMPROVED','reason':'Support/distance projection exceeded pose bounds: '+name}
    if after['behind_camera'] or regressions or held_regressed or held_regressions or after['rmse_px'] >= before['rmse_px']-1e-6:
        return scene, {**report, 'status': 'NOT_IMPROVED', 'reason': 'No aggregate improvement or a camera/pose/object regressed'}
    return candidate, {**report, 'status': 'IMPROVED'}
