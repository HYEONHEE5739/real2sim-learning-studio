"""Known-size static multi-view fitting; no robot, joint, scale or mesh changes.

Uses trimmed observed-to-model correspondences as in RoboSkills track.py, but
estimates one shared World pose rather than a per-frame motion track. Algorithms
are implemented here using existing NumPy/SciPy; no external agent framework.
"""
import copy
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from .registration import align_points
from ..scene import transform


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


def initial_poses(scene,obj,points,support_id=None,*,upright=False):
    """Keep symmetric alternatives; horizontal support constrains roll/pitch/Z."""
    from ..scene import world_pose
    center=(np.percentile(points,2,axis=0)+np.percentile(points,98,axis=0))/2
    seeds=[]
    if obj['pose']['value']is not None:seeds.append(world_pose(scene,obj))
    if support_id:
        support=next(o for o in scene['objects']if o['id']==support_id)
        base=world_pose(scene,support)
        if not np.allclose(base[:3,2],[0,0,1],atol=1e-6):raise ValueError('A horizontal measured support is required for upright initialization')
        center[2]=base[2,3]+support['dimensions']['value'][2]/2+obj['dimensions']['value'][2]/2
        axes=np.eye(3)
    elif upright:axes=np.eye(3)
    else:
        _,_,vt=np.linalg.svd(points-points.mean(0),full_matrices=False);axes=vt.T
        if np.linalg.det(axes)<0:axes[:,-1]*=-1
    for yaw in(0,np.pi/2,np.pi,3*np.pi/2):
        pose=np.eye(4);pose[:3,:3]=axes@Rotation.from_euler('z',yaw).as_matrix();pose[:3,3]=center
        seeds.append(pose)
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
    for obj in scene['objects']:
        name=obj['id'];active=[r for r in rows if r['object_id']==name and r['split']=='train']
        if selected and name not in selected:continue
        if not active or obj['pose']['provenance']in('measured','calibrated')or obj.get('link')or obj['role']=='reference_robot':continue
        if obj['dimensions']['provenance']not in('measured','calibrated')and not obj.get('object_asset'):
            needs.append(name+': measured geometry required');continue
        points=[]
        for row in active:
            with np.load(local_path(project.root,row['path']),allow_pickle=False)as data:points.append(data['points_world_m'])
        points=np.concatenate(points)
        if len(points)>20000:points=points[np.linspace(0,len(points)-1,20000,dtype=int)]
        model=surface_points(obj,scene,project.root)
        upright=bool(options.get('supports',{}).get(name))or any(r.get('same_support_plane')and name in r['objects']for r in scene.get('geometry_constraints',{}).get('distances',[]))
        report=trimmed_icp(model,points,initial_poses(scene,obj,points,options.get('supports',{}).get(name),upright=upright),
            trim=options.get('trim',.8),iterations=options.get('iterations',30),checkpoint=project.checkpoint,upright=upright)
        reports[name]=report
        if report['status']=='ESTIMATED':
            pose=np.asarray(report['T_world_object']);support=options.get('supports',{}).get(name)
            if support:
                # Preserve the explicitly declared horizontal support after ICP;
                # do not accept an RGB fit that tips the table/object to match.
                anchor=next(o for o in scene['objects']if o['id']==support);base=world_pose(scene,anchor)
                yaw=np.arctan2(pose[1,0],pose[0,0]);pose[:3,:3]=Rotation.from_euler('z',yaw).as_matrix()
                pose[2,3]=base[2,3]+anchor['dimensions']['value'][2]/2+obj['dimensions']['value'][2]/2
                report['support_projection_applied']=True
            result=assign_pose(result,name,pose)
        else:needs.extend(name+': '+reason for reason in report['needs'])
    constraints=None
    if scene.get('geometry_constraints'):
        from ..initialization import apply_geometry_constraints
        result,constraints=apply_geometry_constraints(result,scene['geometry_constraints'])
    return result,{'status':'ESTIMATED'if reports and not needs else'NEEDS_MORE_DATA','objects':reports,'needs':needs,'measured_constraints':constraints,
                  'fit_views':sorted({r['image_id']for r in rows if r['split']=='train'}),'physical_verified':False}


def refine_masks(project,scene,folder,options=None):
    """Refine shared object poses against actual native occlusion-aware masks.

    Fragment annotations use a one-sided coverage loss: the unobserved part is
    not treated as background. Complete silhouettes also penalize excess area.
    All held-out views are measured only after optimization.
    """
    from contextlib import ExitStack
    from PIL import Image
    from scipy.ndimage import distance_transform_edt
    from scipy.optimize import minimize
    from ..scene import local_path,world_pose,validate
    from ..observations import registered_images
    from ..capture import observation_scene
    from ..rendering import Renderer
    from ..editing import preserve
    options=options or{};rows=cloud_inputs(project,scene);result=copy.deepcopy(scene)
    images,_,needs=registered_images(project,scene=scene);images={i['id']:i for i in images}
    active=[r for r in rows if r['image_id']in images]
    if not any(r['split']=='train'for r in active):return scene,{'status':'NEEDS_MORE_DATA','needs':['Registered training masks required']}
    try:
        for image in images.values():validate(observation_scene(scene,image,project.root,complete=False),project.root,complete=True)
    except ValueError as error:return scene,{'status':'NEEDS_MORE_DATA','needs':[str(error)]}
    with ExitStack()as stack:
        renderers={};targets={}
        for row in active:
            key=row['image_id']
            if key not in renderers:
                posed=observation_scene(result,images[key],project.root)
                renderers[key]=stack.enter_context(Renderer(posed,project.root,folder/key,options.get('renderer','software-egl')))
            mask=np.asarray(Image.open(local_path(project.root,row['mask'])).convert('L'))>0
            if not mask.any():raise ValueError('Empty refinement mask')
            targets[(key,row['object_id'])]=(mask,distance_transform_edt(~mask))
        def measure(selected):
            metrics=[]
            for row in selected:
                key,name=row['image_id'],row['object_id'];target,distance=targets[(key,name)]
                rendered=renderers[key].mask(images[key]['camera'],name)
                if rendered.shape!=target.shape:raise ValueError('SAM and rendered mask pixels differ')
                missing=float((target&~rendered).sum()/target.sum())
                excess=float(distance[rendered].mean())if rendered.any()else float(np.hypot(*target.shape))
                full=row.get('mask_kind')=='silhouette'
                loss=missing+(excess/10 if full else 0.)
                metrics.append({'image_id':key,'object_id':name,'split':row['split'],'loss':loss,
                    'iou':float((target&rendered).sum()/max(1,(target|rendered).sum())),
                    'mask_kind':row.get('mask_kind','visible_fragment'),'missing_fraction':missing,
                    'boundary_distance_px':excess if full else None})
            return metrics
        before=measure(active);solvers=[]
        for obj in list(result['objects']):
            name=obj['id'];selected=options.get('objects')
            training=[r for r in active if r['object_id']==name and r['split']=='train']
            if not training or(selected and name not in selected)or obj.get('link')or obj['role']=='reference_robot'or obj['pose']['provenance']in('measured','calibrated'):continue
            seed=world_pose(result,obj);support=options.get('supports',{}).get(name)
            samples=surface_points(obj,result,project.root);tree=cKDTree(samples);visible=[]
            for row in training:
                with np.load(local_path(project.root,row['path']),allow_pickle=False)as data:visible.append(data['points_world_m'])
            visible=np.concatenate(visible)
            if len(visible)>10000:visible=visible[np.linspace(0,len(visible)-1,10000,dtype=int)]
            depth_sigma=float(options.get('depth_sigma_m',.005));depth_weight=float(options.get('depth_weight',.25))
            if not np.isfinite([depth_sigma,depth_weight]).all()or depth_sigma<=0 or depth_weight<=0:
                raise ValueError('Positive depth residual scale/weight required; a fragment cannot set optical depth alone')
            upright=bool(support)or any(r.get('same_support_plane')and name in r['objects']for r in result.get('geometry_constraints',{}).get('distances',[]))
            count=3 if upright else 6;translation=options.get('translation_bound_m',.03);angle=options.get('rotation_bound_rad',.2)
            if not np.isfinite([translation,angle]).all()or min(translation,angle)<=0:raise ValueError('Positive finite mask pose bounds required')
            bounds=[(-translation,translation)]*(2 if upright else 3)+[(-angle,angle)]*(1 if upright else 3)
            def move(x):
                pose=seed.copy()
                if upright:
                    pose[:2,3]+=x[:2];pose[:3,:3]=Rotation.from_euler('z',x[2]).as_matrix()@seed[:3,:3]
                else:
                    pose[:3,3]+=x[:3];pose[:3,:3]=Rotation.from_rotvec(x[3:]).as_matrix()@seed[:3,:3]
                trial=assign_pose(result,name,pose)
                if result.get('geometry_constraints'):
                    from ..initialization import apply_geometry_constraints
                    trial,_=apply_geometry_constraints(trial,result['geometry_constraints'])
                for node in trial['objects']:
                    if node.get('link')or node['role']=='reference_robot':continue
                    world=world_pose(trial,node)
                    for renderer in renderers.values():renderer.set_object_pose(node['id'],world)
                return trial
            best=[float('inf'),np.zeros(count)]
            def objective(x):
                project.checkpoint();trial=move(x);pose=world_pose(trial,next(o for o in trial['objects']if o['id']==name))
                score=float(np.mean([r['loss']for r in measure(training)]))
                distances=tree.query((visible-pose[:3,3])@pose[:3,:3])[0]
                trimmed=np.sort(distances)[:max(1,int(.8*len(distances)))]
                score+=depth_weight*float(np.sqrt(np.mean(np.minimum(trimmed/depth_sigma,3.)**2)))
                if score<best[0]:best[:]=[score,np.asarray(x).copy()]
                return score
            objective(np.zeros(count))
            solution=minimize(objective,np.zeros(count),method='Powell',bounds=bounds,
                options={'maxfev':int(options.get('max_evaluations',100)),'xtol':.0005,'ftol':.0001})
            result=move(best[1])
            solvers.append({'object_id':name,'evaluations':int(solution.nfev),'message':str(solution.message),
                            'depth_sigma_m':depth_sigma,'depth_weight':depth_weight,
                            'bound_hit':bool(np.any(np.isclose(abs(best[1]),np.asarray(bounds)[:,1],atol=1e-4)))})
        after=measure(active)
    preserve(scene,result)
    return result,{'status':'OPTIMIZED_UNVERIFIED'if solvers else'NEEDS_MORE_DATA','before':before,'after':after,'solvers':solvers,
                   'physics_steps':0,'physical_verified':False,'cameras':'fixed registered poses; landmark joint fitter handles shared unverified mounts',
                   'needs':needs,'scope':'native visible masks; IoU on fragments is diagnostic, not full-shape accuracy'}


def alignment_metrics(project,scene,folder,options=None):
    """Common per-view metrics/overlays for every backend, with honest units."""
    from PIL import Image,ImageOps
    from ..validation import compare,mask_metrics
    from ..rendering import Renderer
    from ..capture import observation_scene
    from ..observations import registered_images
    from ..scene import local_path,world_pose,validate
    from ..files import write
    options=options or{};rows=cloud_inputs(project,scene);images,state,needs=registered_images(project,scene=scene)
    result=[];models={}
    for image in images:
        active=[r for r in rows if r['image_id']==image['id']]
        if not active:continue
        project.checkpoint();posed=observation_scene(scene,image,project.root,complete=False)
        try:validate(posed,project.root,complete=True)
        except ValueError as error:needs.append(str(error));continue
        destination=folder/'previews'/image['id']
        with Renderer(posed,project.root,folder/'native'/image['id'],options.get('renderer','software-egl'))as renderer:
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
                    'observed_point_surface_rmse_m':float(np.sqrt(np.mean(trimmed**2))),
                    'independent_3d_position_error_m':None,'rotation_error_rad':None,
                    'scope':'derived depth surface residual; not independent measured pose accuracy'})
            result.append({'image_id':image['id'],'image':image['path'],'camera':image['camera'],'split':image['split'],**metrics,'objects':objects})
    report={'images':result,'scene_state_id':state,'needs':list(dict.fromkeys(needs)),
            'input_signature':project.signature(scene),'passed':False,'physics_steps':0,'scope':'common draft comparison'}
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
        if name!='landmark':trial,stages['masks']=refine_masks(project,trial,folder/name,options)
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


def trimmed_icp(model,observed,initial_poses,*,trim=.8,iterations=30,checkpoint=lambda:None,upright=False):
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
        pose=transform(initial).copy();valid=True
        for iteration in range(iterations):
            checkpoint();local=(observed-pose[:3,3])@pose[:3,:3]
            distances,indices=tree.query(local);keep=np.argsort(distances)[:keep_count]
            update=align_points(model[indices[keep]],observed[keep])
            if update['status']!='ESTIMATED':valid=False;break
            previous=pose;pose=np.asarray(update['T_target_source'])
            if upright:
                pose[:3,:3]=Rotation.from_euler('z',np.arctan2(pose[1,0],pose[0,0])).as_matrix()
                pose[:3,3]=observed[keep].mean(0)-model[indices[keep]].mean(0)@pose[:3,:3].T
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
