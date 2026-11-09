"""Known-size static multi-view fitting; no robot, joint, scale or mesh changes.

Uses trimmed observed-to-model correspondences as in RoboSkills track.py, but
estimates one shared World pose rather than a per-frame motion track. Algorithms
are implemented here using existing NumPy/SciPy; no external agent framework.
"""
from scene_contract.naming import numbered_path
import copy
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from .registration import align_points
from ..scene import transform


def view_priority(images,weights):
    """Role budgets, not per-photo votes: phone count cannot swamp Wrist."""
    from ..observations import camera_type
    weights={**{'wrist':4.,'side':2.,'external':.5},**weights}
    if set(weights)!={'wrist','side','external'}or any(not np.isfinite(v)or v<=0 for v in weights.values()):
        raise ValueError('Positive finite wrist/side/external view weights required')
    roles={i['id']:camera_type(i) for i in images}
    return {'weights':weights,'roles':roles,'wrist_observed':'wrist'in roles.values(),
            'scope':'Wrist primary, Side secondary; external views support reconstruction; not accuracy certification'}


def view_loss(metrics,priority):
    groups={}
    for row in metrics:groups.setdefault(priority['roles'][row['image_id']],[]).append(row['loss'])
    return float(sum(priority['weights'][role]*np.mean(values)for role,values in groups.items())/
                 sum(priority['weights'][role]for role in groups))


def surface_points(obj,scene,root,count=2000):
    """Sample the declared known geometry, not an invented hidden observation."""
    import trimesh
    from .geometry import parts,mesh_data
    from ..scene import local_path
    meshes=[]
    for part in parts(obj,'visual'):
        size=part['dimensions'];kind=part['type']
        if kind=='box':mesh=trimesh.creation.box(extents=size)
        elif kind=='cylinder':mesh=trimesh.creation.cylinder(radius=size[0]/2,height=size[2],sections=32)
        elif kind=='sphere':mesh=trimesh.creation.icosphere(subdivisions=2,radius=size[0]/2)
        elif kind=='mesh':
            vertices,faces=mesh_data(local_path(root,scene['assets'][part['asset']]['path']))
            mesh=trimesh.Trimesh(vertices*np.asarray(part.get('scale',[1,1,1])),faces,process=False)
        else:raise ValueError('Unsupported measured surface geometry')
        mesh.apply_transform(part['pose']);meshes.append(mesh)
    mesh=trimesh.util.concatenate(meshes);triangles=mesh.triangles;areas=mesh.area_faces
    if not np.isfinite(areas).all()or areas.sum()<=0:raise ValueError('Invalid model surface area')
    rng=np.random.default_rng(0);selected=triangles[rng.choice(len(areas),count,p=areas/areas.sum())]
    u=rng.random(count);v=rng.random(count);u=np.sqrt(u)
    return selected[:,0]*(1-u[:,None])+selected[:,1]*(u*(1-v))[:,None]+selected[:,2]*(u*v)[:,None]


def initial_poses(scene,obj,points,support_id=None,*,upright=False,root=None):
    """Keep symmetric alternatives; horizontal support constrains roll/pitch/Z."""
    from ..scene import world_pose
    center=(np.percentile(points,2,axis=0)+np.percentile(points,98,axis=0))/2
    seeds=[]
    if obj['pose']['value']is not None:seeds.append(world_pose(scene,obj))
    relation=None
    if support_id:
        from ..scene import support_relations,support_binding,supported_pose
        relation=support_relations(scene,{obj['id']:support_id})[obj['id']]
        if relation['status']=='CONFIRMED':
            binding=support_binding(scene,obj['id'],relation,root);axes=binding['basis']@binding['relative_rotation']
        else:support_id=None
    if not support_id and upright:axes=np.eye(3)
    elif not support_id:
        _,_,vt=np.linalg.svd(points-points.mean(0),full_matrices=False);axes=vt.T
        if np.linalg.det(axes)<0:axes[:,-1]*=-1
    for yaw in(0,np.pi/2,np.pi,3*np.pi/2):
        pose=np.eye(4);pose[:3,:3]=((binding['basis']@Rotation.from_euler('z',yaw).as_matrix()@binding['relative_rotation'])if support_id else axes@Rotation.from_euler('z',yaw).as_matrix());pose[:3,3]=center
        seeds.append(pose)
    if support_id and relation['status']=='CONFIRMED':seeds=[supported_pose(scene,obj['id'],relation,p,root)for p in seeds]
    return seeds


def assign_pose(scene,name,pose):
    from ..scene import frame_world,world_pose,value
    result=copy.deepcopy(scene);obj=next(o for o in result['objects']if o['id']==name)
    if obj['pose']['provenance']in('measured','calibrated')or obj.get('link')or obj['role']=='reference_robot':raise ValueError('Measured pose and robot are locked')
    original=next(o for o in scene['objects']if o['id']==name)
    old=world_pose(scene,original)if original['pose']['value']is not None else None
    obj['pose']=value((np.linalg.inv(frame_world(scene,obj['frame']))@pose).tolist(),'optimized',['metric visible-cloud/mask reconstruction'])
    if old is not None:
        for child in result['objects']:
            if child.get('parent_object')==name:
                before=next(o for o in scene['objects']if o['id']==child['id'])
                world=pose@np.linalg.inv(old)@world_pose(scene,before)
                child['pose']=value((np.linalg.inv(frame_world(scene,child['frame']))@world).tolist(),'optimized',obj['pose']['evidence'])
    return result


def cloud_inputs(project,scene):
    from ..files import sha
    from ..scene import local_path
    rows=scene.get('reconstruction_observations',{}).get('clouds',[])
    for row in rows:
        if row['units']!='m'or row['frame']!='world':raise ValueError('Metric World observations required')
        for key,digest in(('path','sha256'),('mask','mask_sha256')):
            if sha(local_path(project.root,row[key]))!=row[digest]:raise ValueError('Reconstruction observation changed')
        if row.get('dependencies'):
            from ..scene import camera_calibration_signature
            from ..observations import source_record_digest
            image=next((i for i in project.evidence['images']if i.get('id')==row['image_id']),None)
            camera=next((c for c in scene['cameras']if image and c['id']==image['camera']),None)
            if image is None or camera is None or image['sha256']!=row['dependencies']['image_sha256']or camera_calibration_signature(scene,camera)!=row['dependencies']['camera_signature']:
                raise ValueError('Metric cloud Camera/source is stale; rebuild from cached depth')
            if source_record_digest(image)!=row['dependencies']['image_record_sha256']:
                raise ValueError('Metric cloud measured-q/time/layout record changed; rebuild from cached depth')
    if {r['group_id']for r in rows if r['split']=='train'}&{r['group_id']for r in rows if r['split']=='validation'}:
        raise ValueError('Train/holdout observation group leakage')
    return rows


def fit_clouds(project,scene,options=None):
    from ..scene import local_path,world_pose
    options=options or{};result=copy.deepcopy(scene);rows=cloud_inputs(project,scene);reports={};needs=[]
    selected=options.get('objects')
    from ..scene import support_relations
    relations=support_relations(result,options.get('supports'))
    ordered=[]
    def visit(name):
        if name in ordered:return
        if name in relations:visit(relations[name]['support'])
        ordered.append(name)
    for obj in scene['objects']:visit(obj['id'])
    for name in ordered:
        obj=next((o for o in result['objects']if o['id']==name),None)
        if obj is None:continue
        active=[r for r in rows if r['object_id']==name and r['split']=='train']
        if selected and name not in selected:continue
        if not active or obj['pose']['provenance']in('measured','calibrated')or obj.get('link')or obj['role']=='reference_robot':continue
        if obj['dimensions']['provenance']not in('measured','calibrated')and not obj.get('object_asset'):
            needs.append(name+': measured geometry required');continue
        points=[]
        for row in active:
            with np.load(local_path(project.root,row['path']),allow_pickle=False)as data:points.append(data['points_world_m'])
        points=np.concatenate(points)
        if not len(points):continue  # RGB-only sensor rows carry no metric initialization evidence.
        if len(points)>20000:points=points[np.linspace(0,len(points)-1,20000,dtype=int)]
        model=surface_points(obj,scene,project.root)
        from ..scene import support_relations,supported_pose
        relations=support_relations(result,options.get('supports'));relation=relations.get(name)
        support=relation if relation and relation['status']=='CONFIRMED'else None
        if support and next(o for o in result['objects']if o['id']==support['support'])['pose']['value']is None:
            needs.append(name+': support '+support['support']+' has no metric pose observations');continue
        project_pose=(lambda pose:supported_pose(result,name,support,pose,project.root))if support else None
        # A confirmed same-support pair fixes relative roll/pitch even when no
        # absolute support Object/plane was recorded in the historical Scene.
        pair_plane=any(name in r['objects']and r.get('same_support_plane')for r in result.get('geometry_constraints',{}).get('distances',[]))
        if project_pose is None and pair_plane and obj['pose']['value']is not None:
            reference=world_pose(result,obj)[:3,:3]
            def project_pose(pose):
                pose=np.asarray(pose).copy();relative=reference.T@pose[:3,:3]
                pose[:3,:3]=reference@Rotation.from_euler('z',np.arctan2(relative[1,0],relative[0,0])).as_matrix()
                return pose
        report=trimmed_icp(model,points,initial_poses(result,obj,points,support,root=project.root),
            trim=options.get('trim',.8),iterations=options.get('iterations',30),checkpoint=project.checkpoint,project_pose=project_pose)
        reports[name]=report
        if report['status']=='ESTIMATED':
            result=assign_pose(result,name,np.asarray(report['T_world_object']))
            report['support_projection_applied']=bool(support)
        else:needs.extend(name+': '+reason for reason in report['needs'])
    from ..initialization import project_supports
    result,physical=project_supports(result,options.get('supports'),project.root,allow_incomplete=True)
    constraints=None
    if result.get('geometry_constraints')and physical['status']!='NEEDS_MORE_DATA':
        from ..initialization import apply_geometry_constraints
        result,constraints=apply_geometry_constraints(result,result['geometry_constraints'],root=project.root)
    return result,{'status':'ESTIMATED'if reports and not needs else'NEEDS_MORE_DATA','objects':reports,'needs':needs,'measured_constraints':constraints,'physical_constraints':physical,
                  'fit_views':sorted({r['image_id']for r in rows if r['split']=='train'}),'physical_verified':False}


def fit_scene(project,scene,folder,options=None):
    """One native Render-to-Real loop over a shared Scene and all usable views.

    RGB is in [0,1], silhouette/edge distances in image diagonals, depth in
    metres/depth_sigma_m. Measured fields and recorded robot q are never fitted.
    Validation views are reported after the solve, not used to optimize/select.
    """
    if (options or{}).get('engine','mujoco')=='isaac'and 'renderer_factory'not in(options or{}):
        from ..isaac_render import run_job
        return run_job(project,scene,folder,options,'fit')
    if (options or{}).get('engine','mujoco')not in('mujoco','isaac'):raise ValueError('Fitting engine must be mujoco or isaac')
    from pathlib import Path
    from PIL import Image,ImageOps
    import cv2
    import time
    from scipy.optimize import minimize
    from scipy.ndimage import distance_transform_edt,binary_erosion
    from .joint import select_parameters,apply_parameters
    from ..scene import local_path,world_pose,validate,camera_calibration_signature
    from ..observations import registered_images,camera_type
    from ..capture import observation_scene
    from ..rendering import Renderer,render_scene
    from ..editing import preserve
    from ..files import write,sha
    options=dict(options or{});folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    from ..initialization import project_supports
    try:scene,physical=project_supports(scene,options.get('supports'),project.root)
    except ValueError as error:return scene,{'status':'CONSTRAINT_CONFLICT'if 'CONSTRAINT_CONFLICT'in str(error)else'NEEDS_MORE_DATA','needs':[str(error)],'physical_verified':False}
    rows=cloud_inputs(project,scene);images,_,needs=registered_images(project,scene=scene)
    by_id={i['id']:i for i in images};rows=[r for r in rows if r['image_id']in by_id]
    training=[r for r in rows if r['split']=='train']
    report={'status':'NEEDS_MORE_DATA','engine':options.get('engine','mujoco'),'physics_steps':0,'physical_verified':False,'needs':needs,
        'scope':'native multiview fitting; not independent calibration/Task approval','holdout_used_for_optimization':False,'physical_constraints':physical}
    if not training:return scene,{**report,'needs':['Metric training observations required']}
    max_iterations=int(options.get('max_iterations',4));budget=int(options.get('max_evaluations',120))
    max_seconds=float(options.get('max_seconds',900))
    if not np.isfinite(max_seconds)or max_seconds<=0:raise ValueError('Positive finite max_seconds required')
    started=time.monotonic()
    class TimeBudget(Exception):pass
    patience=int(options.get('patience',2));minimum=float(options.get('minimum_improvement',1e-4))
    sigma=float(options.get('depth_sigma_m',.005));regression=float(options.get('max_view_regression',.05))
    weights={**{'rgb':.15,'mask':1.,'edge':.5,'depth':.25,'metric':.25,'prior':.005},**options.get('loss_weights',{})}
    if max_iterations<1 or budget<1 or patience<1 or minimum<0 or sigma<=0 or regression<0 or not np.isfinite([minimum,sigma,regression,*weights.values()]).all()or min(weights.values())<0:
        raise ValueError('Finite positive iteration/loss settings required')
    train_ids=sorted(i['id']for i in images if i['split']=='train');all_ids=sorted(by_id)
    targets={};models={};loaded={}
    for key in all_ids:
        image=by_id[key];real=np.asarray(ImageOps.exif_transpose(Image.open(local_path(project.root,image['path']))).convert('RGB'))
        targets[key]={'rgb':real,'rows':[r for r in rows if r['image_id']==key],'masks':{}}
        for row in targets[key]['rows']:
            name=row['object_id'];mask=np.asarray(Image.open(local_path(project.root,row['mask'])).convert('L'))>0
            if mask.shape!=real.shape[:2]or not mask.any():raise ValueError('Mask/RGB pixels differ or mask is empty')
            boundary=mask^binary_erosion(mask)
            targets[key]['masks'][name]=(mask,boundary,distance_transform_edt(~boundary))
            path=local_path(project.root,row['path'])
            with np.load(path,allow_pickle=False)as data:raw={k:v.copy()for k,v in data.items()}
            loaded[key,name]=raw
            if name not in models:models[name]=cKDTree(surface_points(next(o for o in scene['objects']if o['id']==name),scene,project.root))
    first=observation_scene(scene,by_id[train_ids[0]],project.root,complete=False)
    strategy_rows=[]
    from ..cameras import camera_pixels,optical_rays
    for row in training:
        image=by_id[row['image_id']];posed=observation_scene(scene,image,project.root,complete=False)
        cam=next(c for c in posed['cameras']if c['id']==image['camera'])
        original_cam=next(c for c in scene['cameras']if c['id']==image['camera'])
        _,optical=camera_pixels(original_cam,image)
        physical_pose=world_pose(posed,cam).copy();physical_pose[:3,:3]=physical_pose[:3,:3]@optical
        raw=loaded[row['image_id'],row['object_id']];points=raw['points_world_m']
        singular=np.linalg.svd(points-points.mean(0),compute_uv=False)if len(points)else np.array([])
        rank=int(np.count_nonzero(singular>max(float(singular[0])*1e-3,1e-6)))if len(singular)else 0
        strategy_rows.append({**row,'camera':image['camera'],'camera_type':camera_type(image),
            'camera_pose':physical_pose.tolist(),'measured_q':image.get('q_measured')is not None,
            # The render loss reprojects pixel rays with the current K/pose.
            # Optical-only archives are usable as fixed World geometry, but
            # cannot supply that residual when the Camera changes.
            'has_raw_depth':'uv_original'in raw and 'depth_relative'in raw,'has_image_observation':row.get('render_only',False),'cloud_rank':rank})
    geometry_plan=select_parameters(scene,strategy_rows,options,stage='geometry',root=project.root)[3]
    appearance_plan=select_parameters(scene,strategy_rows,options,stage='appearance',root=project.root)[3]
    report['observability']={'holdout_used':False,'geometry':geometry_plan,'appearance':appearance_plan,'needs':geometry_plan['needs']}
    report['needs']=list(dict.fromkeys([*report['needs'],*geometry_plan['needs']]))
    has_appearance=bool(appearance_plan['active']);geometry_done=False;previous_stage=None
    renderer_factory=options.pop('renderer_factory',Renderer)
    history=[];evaluations=0;best=copy.deepcopy(scene);best_scales={};best_loss=float('inf');best_metrics=[]
    priority=view_priority(images,options.get('view_weights',{}));report['view_priority']=priority
    def summarize(metrics):return view_loss(metrics,priority)
    # One compiled native Scene and context, reused sequentially across views.
    with renderer_factory(first,project.root,folder/'native',options.get('renderer','software-egl'))as renderer:
        def measure(trial,scales,keys):
            metrics=[]
            for key in keys:
                project.checkpoint();image=by_id[key];posed=observation_scene(trial,image,project.root,complete=False)
                renderer.update_scene(posed);cam=next(c for c in posed['cameras']if c['id']==image['camera']);camera_pose=world_pose(posed,cam)
                rgb=renderer.rgb(image['camera']);target=targets[key];real=target['rgb']
                if rgb.shape!=real.shape:raise ValueError('Native/Real RGB resolution differs')
                diagonal=float(np.hypot(*real.shape[:2]));union=np.zeros(real.shape[:2],bool);object_metrics=[]
                native_depth=None
                for row in target['rows']:
                    name=row['object_id'];mask,boundary,distance=target['masks'][name];rendered=renderer.mask(image['camera'],name)
                    union|=mask|rendered;edge=rendered^binary_erosion(rendered)
                    missing=float((mask&~rendered).sum()/mask.sum());full=row.get('mask_kind')=='silhouette'
                    extra=float((rendered&~mask).sum()/max(1,rendered.sum()))if full else 0.
                    edge_loss=float(distance_transform_edt(~edge)[boundary].mean()/diagonal)
                    if full and edge.any():edge_loss+=float(distance[edge].mean()/diagonal)
                    raw=loaded[key,name];scale=row.get('depth_scale',1.)*scales.get(row.get('depth_batch',key),1.)
                    obj=next(o for o in posed['objects']if o['id']==name);pose=world_pose(posed,obj)
                    if 'uv_original'in raw and 'depth_relative'in raw:
                        uv=raw['uv_original'];rays=optical_rays(cam,uv)
                        optical=rays*raw['depth_relative'][:,None]*scale;world=optical@camera_pose[:3,:3].T+camera_pose[:3,3]
                        if native_depth is None:native_depth=renderer.depth(image['camera'])
                        pixels=np.rint(uv).astype(int);h,w=mask.shape;valid=(pixels[:,0]>=0)&(pixels[:,0]<w)&(pixels[:,1]>=0)&(pixels[:,1]<h)
                        pixels=pixels[valid];z=optical[valid,2]
                        visible=mask[pixels[:,1],pixels[:,0]]&rendered[pixels[:,1],pixels[:,0]]
                        residual=abs(native_depth[pixels[:,1],pixels[:,0]][visible]-z[visible])/sigma
                        depth_loss=float(np.minimum(residual,3).mean())if len(residual)else 0.
                    else:
                        world=raw['points_world_m'];depth_loss=0.
                    base_obj=next(o for o in scene['objects']if o['id']==name)
                    tree=models[name]
                    if obj['dimensions']['value']!=base_obj['dimensions']['value']:
                        tree=cKDTree(surface_points(obj,posed,project.root))
                    distances=tree.query((world-pose[:3,3])@pose[:3,:3])[0]
                    trimmed=np.sort(distances)[:max(1,int(len(distances)*.8))]
                    metric_loss=float(np.minimum(trimmed/sigma,3).mean())if len(trimmed)else 0.
                    object_metrics.append({'object_id':name,'mask':missing+extra,'edge':edge_loss,'depth':depth_loss,'metric':metric_loss,
                        'iou':float((mask&rendered).sum()/max(1,(mask|rendered).sum()))})
                rgb_loss=float(np.minimum(abs(rgb.astype(float)-real.astype(float))[union]/255.,.3).mean())if union.any()else float(np.minimum(abs(rgb.astype(float)-real.astype(float))/255.,.3).mean())
                losses={name:float(np.mean([r[name]for r in object_metrics]))if object_metrics else 0. for name in('mask','edge','depth','metric')}
                losses['rgb']=rgb_loss;total=sum(weights[k]*v for k,v in losses.items())
                metrics.append({'image_id':key,'camera_type':camera_type(image),'split':image['split'],'loss':float(total),'components':losses,'objects':object_metrics,
                    'iou':float(np.mean([r['iou']for r in object_metrics]))if object_metrics else None})
            return metrics
        baseline=measure(best,{},train_ids);best_metrics=baseline;best_loss=summarize(baseline)
        write(folder/'best-scene.yaml',best);idle=0;stop='max_iterations'
        try:
            for iteration in range(max_iterations):
                if evaluations>=budget:stop='max_evaluations';break
                if time.monotonic()-started>=max_seconds:stop='max_seconds';break
                project.checkpoint();seed=copy.deepcopy(best);seed_scales=dict(best_scales)
                stage='appearance'if has_appearance and(geometry_done or iteration>=(max_iterations+1)//2)else'geometry'
                blocks,radius,indices,strategy=select_parameters(seed,strategy_rows,options,stage=stage,root=project.root)
                if not len(indices)and stage=='geometry'and has_appearance:
                    geometry_done=True;stage='appearance'
                    blocks,radius,indices,strategy=select_parameters(seed,strategy_rows,options,stage=stage,root=project.root)
                if not len(indices):stop='unobservable'if report['observability']['needs']else'no_variables';break
                if stage!=previous_stage:idle=0;previous_stage=stage
                selected_blocks=[b for b in blocks if any(b[3]<=i<b[3]+b[4]for i in indices)]
                zero=np.zeros(len(indices));start=best_loss
                def objective(unit):
                    nonlocal evaluations,best_loss,best,best_scales,best_metrics
                    if time.monotonic()-started>=max_seconds:raise TimeBudget()
                    project.checkpoint();delta=np.zeros(len(radius));delta[indices]=unit*radius[indices]
                    trial,scales=apply_parameters(seed,selected_blocks,delta,root=project.root);evaluations+=1
                    scales={key:seed_scales.get(key,1.)*scales.get(key,1.)for key in seed_scales.keys()|scales.keys()}
                    preserve(scene,trial);validate(render_scene(trial),project.root,complete=True)
                    metrics=measure(trial,scales,train_ids);score=summarize(metrics)
                    penalty=weights['prior']*float(np.mean(unit**2))
                    acceptable=all(new['loss']<=old['loss']+regression for new,old in zip(metrics,baseline))
                    if acceptable and score<best_loss:
                        best_loss,best,best_scales,best_metrics=score,trial,scales,metrics
                    return score+penalty
                solution=minimize(objective,zero,method='Powell',bounds=[(-1.,1.)]*len(zero),
                    options={'maxfev':max(1,(budget-evaluations)//(max_iterations-iteration)),'xtol':.002,'ftol':minimum})
                improvement=start-best_loss;idle=idle+1 if improvement<minimum else 0
                history.append({'iteration':iteration+1,'loss':best_loss,'improvement':improvement,'evaluations':int(solution.nfev),
                    'solver_converged':bool(solution.success),'variables':strategy['active'],'strategy':strategy})
                # A native worker may be killed before the next checkpoint.
                # Publish a self-consistent completed iteration, while keeping
                # raw rays and cumulative scale factors for the ongoing solve.
                saved=reproject_observations(project,best,best_scales,folder/'observations')
                preserve(scene,saved);validate(render_scene(saved),project.root,complete=True)
                write(folder/'best-scene.yaml',saved);write(folder/'iterations.json',history)
                if evaluations>=budget:stop='max_evaluations';break
                if idle>=patience or(solution.success and improvement<minimum):
                    if stage=='geometry'and has_appearance:geometry_done=True;continue
                    stop='no_improvement'if idle>=patience else'converged';break
        except TimeBudget:
            stop='max_seconds'
        except (InterruptedError,ValueError,RuntimeError)as error:
            best=reproject_observations(project,best,best_scales,folder/'observations')
            preserve(scene,best);validate(render_scene(best),project.root,complete=True)
            write(folder/'best-scene.yaml',best)
            error.best_scene=best  # Caller can retain the accepted Candidate on Stop.
            report.update(status='STOPPED'if isinstance(error,InterruptedError)else'FAILED',error=str(error),stop_reason='user_stop'if isinstance(error,InterruptedError)else'invalid_scene_or_render_failure')
            write(folder/'report.json',{**report,'before':baseline,'after':best_metrics,'history':history,'best_loss':best_loss});raise
        held=measure(best,best_scales,[key for key in all_ids if key not in train_ids])
    # Refresh derived World points and camera dependency hashes once, after the
    # final accepted state. The raw observations and source frames are immutable.
    best=reproject_observations(project,best,best_scales,folder/'observations')
    preserve(scene,best);validate(render_scene(best),project.root,complete=True)
    improved=best_loss<summarize(baseline)-minimum
    exhausted=stop in('max_iterations','max_evaluations','max_seconds')
    status='UNRESOLVED'if stop=='unobservable'else'BUDGET_EXHAUSTED'if exhausted else'OPTIMIZED_UNVERIFIED'if improved else'NOT_IMPROVED'
    report.update(status=status,before=baseline,after=best_metrics,before_loss=summarize(baseline),after_loss=best_loss,
        holdout=held,training_view_count=len(train_ids),evaluations=evaluations,history=history,stop_reason=stop,
        weights=weights,depth_sigma_m=sigma,max_view_regression=regression,
        budget={'max_iterations':max_iterations,'max_evaluations':budget,'max_seconds':max_seconds,
                'scope':'whole fit call; objective evaluations; baseline and final evaluation reported separately'},
        best_scene=str(folder/'best-scene.yaml'),converged=stop in('converged','no_improvement'),
        metric_constraints='measured dimensions/poses locked; explicit support projection',robot_constraints='fixed measured q/FK; one shared mount per physical camera')
    from ..scene import support_metrics
    report['physical_constraints']=support_metrics(best,root=project.root)
    write(folder/'best-scene.yaml',best);write(folder/'report.json',report)
    return best,report


def reproject_observations(project,scene,scales,folder):
    """Own updated derived World clouds; preserve source optical rays and masks."""
    from pathlib import Path
    from ..files import sha
    from ..scene import local_path,camera_calibration_signature,world_pose
    from ..capture import observation_scene
    import uuid
    folder=Path(folder)
    if not folder.resolve().is_relative_to(project.root):folder=project.root/'scratch/render-fit-observations'
    folder=numbered_path(folder,'iteration');folder.mkdir(parents=True,exist_ok=True);result=copy.deepcopy(scene)
    from ..cameras import optical_rays
    images={i.get('id'):i for i in project.evidence['images']}
    for index,row in enumerate(result.get('reconstruction_observations',{}).get('clouds',[])):
        image=images.get(row['image_id'])
        if not image:continue
        source=local_path(project.root,row['path'])
        if sha(source)!=row['sha256']:raise ValueError('Source optical observation changed')
        with np.load(source,allow_pickle=False)as data:raw={k:v.copy()for k,v in data.items()}
        if 'points_camera_relative'not in raw:
            if row.get('render_only')and row.get('dependencies'):
                row['dependencies']['camera_signature']=camera_calibration_signature(result,next(c for c in result['cameras']if c['id']==image['camera']))
            continue
        posed=observation_scene(result,image,project.root,complete=False);cam=next(c for c in posed['cameras']if c['id']==image['camera'])
        points=raw['points_camera_relative']
        if 'uv_original'in raw:points=optical_rays(cam,raw['uv_original'])*raw['depth_relative'][:,None]
        row['depth_scale']=row.get('depth_scale',1.)*scales.get(row.get('depth_batch',row['image_id']),1.)
        pose=world_pose(posed,cam);raw['points_world_m']=(points*row['depth_scale'])@pose[:3,:3].T+pose[:3,3]
        target=folder/f'{index}.npz'
        np.savez_compressed(target,**raw);row.update(path=target.relative_to(project.root).as_posix(),sha256=sha(target))
        if row.get('dependencies'):
            row['dependencies'].update(camera_signature=camera_calibration_signature(result,next(c for c in result['cameras']if c['id']==image['camera'])),camera_pose=pose.tolist())
    for key,binding in result.get('view_registrations',{}).items():
        if key in images:binding['camera_signature']=camera_calibration_signature(result,next(c for c in result['cameras']if c['id']==images[key]['camera']))
    return result


def alignment_metrics(project,scene,folder,options=None):
    """Common per-view metrics/overlays for every backend, with honest units."""
    if (options or{}).get('engine','mujoco')=='isaac'and 'renderer_factory'not in(options or{}):
        from ..isaac_render import run_job
        return run_job(project,scene,folder,options,'compare')
    from PIL import Image,ImageOps
    from ..validation import compare,mask_metrics,camera_quality
    from ..rendering import Renderer,render_scene
    from ..capture import observation_scene
    from ..observations import registered_images,camera_type
    from ..scene import local_path,world_pose,validate
    from ..files import write
    options=options or{};rows=cloud_inputs(project,scene);images,state,needs=registered_images(project,scene=scene)
    result=[];models={};renderer=None
    from contextlib import ExitStack
    with ExitStack()as stack:
        for image in images:
            active=[r for r in rows if r['image_id']==image['id']]
            project.checkpoint();posed=observation_scene(scene,image,project.root,complete=False)
            try:validate(render_scene(posed),project.root,complete=True)
            except ValueError as error:needs.append(str(error));continue
            destination=folder/'previews'/image['id']
            if renderer is None:
                renderer=stack.enter_context(options.get('renderer_factory',Renderer)(posed,project.root,folder/'native',options.get('renderer','software-egl')))
            else:renderer.update_scene(posed)
            real=np.asarray(ImageOps.exif_transpose(Image.open(local_path(project.root,image['path']))).convert('RGB'))
            metrics=compare(real,renderer.rgb(image['camera']),destination);objects=[]
            for row in active:
                name=row['object_id'];obj=next(o for o in scene['objects']if o['id']==name)
                target=np.asarray(Image.open(local_path(project.root,row['mask'])).convert('L'))>0
                mask=renderer.mask(image['camera'],name);diagnostic=mask_metrics(target,mask)
                if name not in models:models[name]=surface_points(obj,scene,project.root)
                pose=world_pose(scene,obj);samples=models[name]@pose[:3,:3].T+pose[:3,3]
                with np.load(local_path(project.root,row['path']),allow_pickle=False)as data:
                    distance=cKDTree(samples).query(data['points_world_m'])[0]
                trimmed=np.sort(distance)[:max(1,int(.8*len(distance)))]
                objects.append({'object_id':name,'mask_kind':row.get('mask_kind','visible_fragment'),**diagnostic,
                    'observed_point_surface_rmse_m':float(np.sqrt(np.mean(trimmed**2)))if len(trimmed)else None,
                    'independent_3d_position_error_m':None,'rotation_error_rad':None,
                    'scope':'derived depth surface residual; not independent measured pose accuracy'})
            scope=scene.get('view_registrations',{}).get(image['id'],{}).get('comparison_scope','full_scene')
            result.append({'image_id':image['id'],'image':image['path'],'camera':image['camera'],'camera_type':camera_type(image),'q_measured':image.get('q_measured'),'split':image['split'],**metrics,'objects':objects,
                'comparison_scope':scope,'use_for_best_selection':scope=='full_scene'})
    report={'images':result,'scene_state_id':state,'needs':list(dict.fromkeys(needs)),
            'input_signature':project.signature(scene),'passed':False,'physics_steps':0,'scope':'common draft comparison','camera_quality':camera_quality(result,options.get('camera_quality'))}
    write(folder/'metrics.json',report);return report


def backend_ready(result):
    """A successful solve and finite rendered training comparisons, not just a report."""
    stages=result.get('stages',{}).values()
    if not any(r.get('status')in('ESTIMATED','IMPROVED','OPTIMIZED_UNVERIFIED')for r in stages):return False
    if any(r.get('status')in('FAILED','UNRESOLVED','STOPPED')for r in stages):return False
    if any(r.get('status')!='ESTIMATED'for r in result.get('stages',{}).get('icp',{}).get('objects',{}).values()):return False
    rows=[r for r in result.get('metrics',{}).get('images',[])if r.get('split')=='train']
    def finite(node):
        if isinstance(node,dict):return all(finite(v)for v in node.values())
        if isinstance(node,(list,tuple)):return all(finite(v)for v in node)
        return bool(np.isfinite(node))if isinstance(node,(float,int))else True
    return bool(rows)and all(isinstance(r.get('mae'),(float,int))for r in rows)and finite(result)


def compare_backends(project,scene,folder,options=None):
    """Run A/B/C from identical inputs; no default winner without a fair holdout.

    Hybrid refines raw optical depth and shared Camera/Object variables, then
    republishes World clouds before mask fitting. Legacy clouds without raw
    rays retain the fixed-camera baseline and report the missing inputs.
    """
    from pathlib import Path
    import time
    from .joint import fit_joint_scene,fit_depth_bundle
    from ..scene import validate
    from ..editing import preserve
    from ..files import write
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);options=dict(options or{})
    rows=cloud_inputs(project,scene)
    if not any(r['split']=='train'for r in rows):
        return scene,{'status':'NEEDS_MORE_DATA','needs':['Registered metric training clouds required'],'default_backend':None,'backends':{}}
    results={};candidates={};baseline=alignment_metrics(project,scene,folder.parent/'renders/auto_baseline',options)
    for name in('landmark','icp_mask','hybrid'):
        project.checkpoint();started=time.monotonic();trial=copy.deepcopy(scene);stages={}
        if name!='landmark':trial,stages['icp']=fit_clouds(project,trial,options)
        if name!='icp_mask':
            trial,stages['joint']=fit_joint_scene(project,trial,{**options,'cameras':[]})
        if name=='hybrid':trial,stages['depth_bundle']=fit_depth_bundle(project,trial,options)
        if name!='landmark':trial,stages['render']=fit_scene(project,trial,folder/name,options)
        preserve(scene,trial);validate(trial,project.root)
        candidates[name]=trial
        results[name]={'stages':stages,'runtime_s':time.monotonic()-started,
            'train_views':sorted({r['image_id']for r in rows if r['split']=='train'}),
            'validation_views':sorted({r['image_id']for r in rows if r['split']=='validation'}),
            'measured_fields_preserved':True,'physical_verified':False}
        results[name]['metrics']=alignment_metrics(project,trial,folder.parent/'renders'/('auto_'+name),options)
        results[name]['runtime_s']=time.monotonic()-started
        results[name]['status']='FITTED_DRAFT'if backend_ready(results[name])else'NEEDS_MORE_DATA'
        write(folder/(name+'.yaml'),trial)
    held=any(r['split']=='validation'for r in rows)
    report={'status':'PROVISIONAL_COMPARISON','baseline':baseline,'backends':results,'requested_backend':options.get('backend','hybrid'),
            'default_backend':None,'winner':None,'independent_pose_accuracy_mm':None,
            'needs':(['Independent held-out observations required']if not held else[])+[
                'Default backend selection requires comparable landmark/mask/depth metrics and independent validation',
                'Draft fitting is not independent metric/physical validation'],
            'scope':'A/B/C draft outputs and solver diagnostics; not a completed accuracy benchmark'}
    selected=report['requested_backend']
    if selected not in candidates:raise ValueError('Backend must be landmark, icp_mask or hybrid')
    if results[selected]['status']!='FITTED_DRAFT':
        report['status']='NEEDS_MORE_DATA';report['needs'].append('Selected backend has no valid solved and rendered training result')
    write(folder/'comparison.json',report)
    return candidates[selected],report


def trimmed_icp(model,observed,initial_poses,*,trim=.8,iterations=30,checkpoint=lambda:None,upright=False,project_pose=None):
    """Rigid model-to-World multi-start fit with explicit degeneracy reporting."""
    model=np.asarray(model,float);observed=np.asarray(observed,float)
    for points in(model,observed):
        if points.ndim!=2 or points.shape[1:]!=(3,)or not np.isfinite(points).all():raise ValueError('Finite Nx3 ICP points required')
    if not .5<=trim<=1 or not 1<=iterations<=100:raise ValueError('ICP trim .5..1 and iterations 1..100 required')
    if min(len(model),len(observed))<50:return {'status':'NEEDS_MORE_DATA','needs':['At least 50 visible object points and model samples required']}
    singular=np.linalg.svd(observed-observed.mean(0),compute_uv=False)
    if singular[-1]<singular[0]*1e-3:
        return {'status':'NEEDS_MORE_DATA','needs':['Visible cloud is degenerate; obtain another surface/view'],'singular_values':singular.tolist()}
    tree=cKDTree(model);solutions=[];keep_count=max(3,int(len(observed)*trim))
    for initial in initial_poses:
        pose=transform(initial).copy();pose=project_pose(pose)if project_pose else pose;valid=True
        for iteration in range(iterations):
            checkpoint();local=(observed-pose[:3,3])@pose[:3,:3]
            distances,indices=tree.query(local);keep=np.argsort(distances)[:keep_count]
            update=align_points(model[indices[keep]],observed[keep])
            if update['status']!='ESTIMATED':valid=False;break
            previous=pose;pose=np.asarray(update['T_target_source'])
            if upright:
                pose[:3,:3]=Rotation.from_euler('z',np.arctan2(pose[1,0],pose[0,0])).as_matrix()
                pose[:3,3]=observed[keep].mean(0)-model[indices[keep]].mean(0)@pose[:3,:3].T
            if project_pose:pose=project_pose(pose)
            if np.max(abs(pose-previous))<1e-8:break
        if not valid:continue
        distances,indices=tree.query((observed-pose[:3,3])@pose[:3,:3]);keep=np.argsort(distances)[:keep_count]
        solutions.append({'T_world_object':pose.tolist(),'rmse_m':float(np.sqrt(np.mean(distances[keep]**2))),
                          'model_coverage':float(len(np.unique(indices[keep]))/len(model)),'iterations':iteration+1})
    if not solutions:return {'status':'NEEDS_MORE_DATA','needs':['Initial hypotheses have no non-degenerate model correspondences']}
    solutions.sort(key=lambda row:row['rmse_m']);best=solutions[0]
    if best['model_coverage']<.05:return {'status':'NEEDS_MORE_DATA',**best,'needs':['Model correspondence coverage is below 5%; obtain another view']}
    return {'status':'ESTIMATED',**best,'scale':1.,'outliers_removed':len(observed)-keep_count,
            'alternatives':solutions,'ambiguity':'symmetry and partial visibility may leave multiple poses',
            'physical_verified':False,'scope':'visible surface fit; residual is not independent 3D accuracy'}
