"""Learned SfM geometry and isolated installed MASt3R/COLMAP workers.

Coordinates are relative until the existing metric registration supplies evidence.
Official APIs: github.com/naver/mast3r/mast3r/cloud_opt/sparse_ga.py and
github.com/colmap/colmap/python/README.md. Heavy runtimes are imported in workers.
"""
from pathlib import Path
import numpy as np


def transform_points(points,similarity):
    from .scene import transform
    matrix=transform(similarity['T_target_source']);scale=float(similarity['scale'])
    if not np.isfinite(scale)or scale<=0:raise ValueError('Positive relative similarity scale required')
    return np.asarray(points)*scale@matrix[:3,:3].T+matrix[:3,3]


def robust_similarity(source,target,*,max_relative_rmse=.03,min_inliers=30):
    """One proper Sim(3) supported by pixel-associated sparse/dense 3D samples."""
    from .calibration.registration import align_points
    a,b=np.asarray(source,float),np.asarray(target,float)
    if a.shape!=b.shape or a.ndim!=2 or a.shape[1]!=3:raise ValueError('Corresponding Nx3 geometry required')
    if not np.isfinite(max_relative_rmse)or not 0<max_relative_rmse<.2 or min_inliers<3:raise ValueError('Invalid alignment limits')
    valid=np.isfinite(a).all(1)&np.isfinite(b).all(1);a,b=a[valid],b[valid]
    unavailable={'status':'UNRESOLVED','metric_scale_verified':False,'needs':['Consistent non-collinear sparse/pointmap correspondences required']}
    if len(a)<min_inliers or min(np.linalg.matrix_rank(a-a.mean(0)),np.linalg.matrix_rank(b-b.mean(0)))<2:return unavailable
    extent=float(np.linalg.norm(np.percentile(b,90,axis=0)-np.percentile(b,10,axis=0)))
    if extent<1e-10:return unavailable
    threshold=extent*max_relative_rmse;rng=np.random.default_rng(0);best=None
    for _ in range(256):
        index=rng.choice(len(a),3,replace=False);fit=align_points(a[index],b[index],estimate_scale=True)
        if fit['status']!='ESTIMATED':continue
        keep=np.linalg.norm(transform_points(a,fit)-b,axis=1)<=threshold
        if keep.sum()>=min_inliers and(best is None or keep.sum()>best.sum()):best=keep
    if best is None or best.sum()<max(min_inliers,.6*len(a)):return unavailable
    fit=align_points(a[best],b[best],estimate_scale=True)
    for _ in range(3):
        residual=np.linalg.norm(transform_points(a,fit)-b,axis=1);best=residual<=threshold
        if best.sum()<max(min_inliers,.6*len(a)):return unavailable
        fit=align_points(a[best],b[best],estimate_scale=True)
    if fit['rmse']>threshold:return unavailable
    return {**fit,'status':'ALIGNED_RELATIVE','inliers':int(best.sum()),'correspondences':len(a),
            'relative_rmse':fit['rmse']/extent,'threshold_relative':max_relative_rmse,'metric_scale_verified':False,
            'scope':'pixel-associated dense/sparse relative frame alignment; not metres'}


def optical_depth(points,confidence,k,world_to_camera,shape,*,distortion=(),source_pixels=None,max_reprojection_px=8.):
    """Project observed samples with optimized cameras, keeping frontmost optical Z.

    No interpolation, sparse-depth filling, or hidden surface generation occurs.
    """
    from .scene import transform
    from .cameras import project_pixels
    p=np.asarray(points,float);confidence=np.asarray(confidence,float);k=np.asarray(k,float)
    if p.ndim!=2 or p.shape[1]!=3 or confidence.shape!=(len(p),):raise ValueError('Nx3 observed points and per-point confidence required')
    if k.shape!=(3,3)or not np.isfinite(k).all()or min(k[0,0],k[1,1])<=0:raise ValueError('Valid processed K required')
    if len(shape)!=2 or min(shape)<=0 or not np.isfinite(max_reprojection_px)or max_reprojection_px<=0:raise ValueError('Invalid raster limits')
    t=transform(world_to_camera);optical=p@t[:3,:3].T+t[:3,3]
    finite=np.isfinite(optical).all(1)&np.isfinite(confidence)&(confidence>0);positive=optical[:,2]>0
    keep=finite&positive;ids=np.flatnonzero(keep)
    lens={'K':{'value':k},'distortion':{'value':list(distortion)if len(distortion)else[0.]*5}}
    pixels=project_pixels(lens,optical[ids])
    if source_pixels is not None:
        reference=np.asarray(source_pixels,float)
        if reference.shape!=(len(p),2):raise ValueError('Source pixel correspondences differ')
        consistent=np.isfinite(reference[ids]).all(1)&(np.linalg.norm(pixels-reference[ids],axis=1)<=max_reprojection_px)
        ids=ids[consistent];pixels=pixels[consistent]
    uv=np.rint(pixels).astype(int);h,w=shape
    inside=(uv[:,0]>=0)&(uv[:,1]>=0)&(uv[:,0]<w)&(uv[:,1]<h);ids=ids[inside];uv=uv[inside]
    depth=np.full((h,w),np.nan,np.float32);conf=np.zeros((h,w),np.float32)
    if len(ids):
        order=np.argsort(optical[ids,2],kind='stable');ids=ids[order];uv=uv[order]
        _,first=np.unique(uv[:,1]*w+uv[:,0],return_index=True);ids=ids[first];uv=uv[first]
        depth[uv[:,1],uv[:,0]]=optical[ids,2];conf[uv[:,1],uv[:,0]]=confidence[ids]
    return depth,conf,{'valid_pixels':len(ids),'cheirality_rejected':int((finite&~positive).sum()),
        'units':'sfm_relative','depth_kind':'optical_z','hidden_surface_generated':False,'hole_filling':False}


def backend(config):
    """One production geometry backend; old saved DA3 paths never execute."""
    geometry=config.get('geometry',{})
    name=geometry.get('backend','mast3r_colmap')
    if name!='mast3r_colmap':raise ValueError('Unknown or retired geometry backend: '+str(name)+'; configure mast3r_colmap runtimes')
    return name


def run_geometry(candidate,config,images,prepared,segments,root,*,include_capture=False):
    """Use existing process/cache boundaries; keep validation out of train SfM."""
    import json,uuid,os
    from PIL import Image
    from .files import read,write,sha
    from .inference import _runtime,_run_worker,_digest,associate_instances,validate_depth_output
    geometry=config.get('geometry',{});rows=[];needs=[]
    selected=associate_instances({'segments':segments},config['objects'],config.get('selections'))['segments']
    masks=root/'static_masks';masks.mkdir(exist_ok=True)
    for image in images:
        if image.get('role')=='model_reference'or image.get('capture_manifest')and not include_capture:
            needs.append(image['id']+': excluded from initial Scene SfM; model reference or sensor Capture')
            continue
        if image['split']!='train':
            needs.append(image['id']+': validation excluded from SfM/BA; separate localization not available');continue
        mask=np.zeros(tuple(image['resolution'][::-1]),bool);excluded=np.zeros_like(mask)
        for row in selected:
            spec=config['objects'].get(row['object_id'],{})
            if row['image_id']!=image['id']:continue
            dynamic=spec.get('role')=='reference_robot'or bool(spec.get('exclude_from_sfm'))
            if not dynamic and spec.get('role','manipulable_object')not in('support_surface','workspace','background','fixture','receptacle','manipulable_object'):continue
            # A union of static semantic masks is usable for camera matching;
            # this does not resolve which identical cup owns an Object cloud.
            for observed in row.get('masks',[]):
                path=Path(observed['path'])
                if sha(path)!=observed['sha256']:raise ValueError('Static segmentation identity changed')
                pixels=np.asarray(Image.open(path).convert('L'))>0
                if dynamic:excluded|=pixels
                else:mask|=pixels
        mask&=~excluded
        if not mask.any():needs.append(image['id']+': assigned static Object masks required; moving robot/hands are not SfM inputs');continue
        path=masks/(image['sha256']+'.png');Image.fromarray(np.uint8(mask)*255).save(path)
        row={**prepared[image['id']],'id':image['id'],'resolution':image['resolution'],'physical_camera_id':image.get('physical_camera_id',image['camera']),
            'camera_type':image.get('camera_type'),'split':'train','scene_state_id':image['scene_state_id'],
            'pixel_from_camera':image.get('pixel_from_camera'),
            'static_mask':str(path),'static_mask_sha256':sha(path)}
        # Explicit calibrated lenses condition SfM, never get overwritten by AI K.
        camera=next((c for c in candidate.scene['cameras']if c['id']==image['camera']),None)
        if camera and all(camera[k]['provenance']in('measured','calibrated')for k in('K','distortion')):
            from .cameras import camera_pixels
            affine,optical=camera_pixels(camera,image);k=affine@np.array(camera['K']['value'])@optical.T;d=camera['distortion']['value']
            if (not np.allclose(optical,np.eye(3))and any(d[2:4]))or any(d[4:]):
                needs.append(image['id']+': calibrated distortion cannot be represented by this SfM lens');continue
            row['known_lens']={'K':k.tolist(),'distortion':d}
        rows.append(row)
    if len(rows)<2:return [],{'backend':'mast3r_colmap','status':'UNRESOLVED','needs':needs+['At least two static training views required']}
    mast_spec={k:geometry.get(k,'')for k in('python','model','source')}
    colmap_spec={'python':geometry.get('colmap_python','')}
    mast,mast_identity=_runtime(candidate.project,{'mast3r':mast_spec},'mast3r',root/'mast3r-runtime')
    colmap,colmap_identity=_runtime(candidate.project,{'colmap':colmap_spec},'colmap',root/'colmap-runtime')
    parameters={k:v for k,v in geometry.items()if k not in('backend','python','model','source','colmap_python','timeout_s')}
    identity={'backend':'mast3r_colmap','mast3r':mast_identity,'colmap':colmap_identity,'parameters':parameters,'images':rows}
    key=_digest(identity);base=root/'mast3r_colmap'/key;base.mkdir(parents=True,exist_ok=True)
    def stage(name,python,request):
        record=base/(name+'.json')
        if record.exists():
            prior=read(record);folder=Path(prior['output'])
            if not(folder/'COMPLETE').is_file()or sha(folder/'result.json')!=prior['sha256']:raise ValueError('Incomplete/changed '+name+' cache')
            result=read(folder/'result.json')
            if any(sha(folder/p)!=digest for p,digest in result['files'].items()):raise ValueError('Changed '+name+' output cache')
            return folder,result
        folder=base/(name+'-'+uuid.uuid4().hex)
        candidate.project.update(status='RUNNING',stage='MASt3R Matching'if name=='mast3r'else'COLMAP Registration / Bundle Adjustment / Dense Geometry Alignment')
        print(json.dumps({'stage':name,'backend':'mast3r_colmap'}),flush=True)
        _run_worker(candidate.project,python,name,{**request,'output':str(folder),'progress':str(folder/'progress.json')},base/(name+'-job'),float(geometry.get('timeout_s',900)))
        if not(folder/'COMPLETE').exists():raise ValueError('Worker did not commit '+name+' outputs')
        result=read(folder/'result.json');write(record,{'output':str(folder),'sha256':sha(folder/'result.json')})
        return folder,result
    gpu,gpu_report=stage('mast3r',mast['python'],{'images':rows,'source':mast['source'],'model':mast['model'],'parameters':parameters})
    image_dir=base/'images';image_dir.mkdir(exist_ok=True)
    for i,row in enumerate(rows):
        target=image_dir/f'{i:04d}.png'
        if not target.exists():os.link(row['path'],target)
    cpu,result=stage('colmap',colmap['python'],{'mast3r':str(gpu),'images_directory':str(image_dir),'parameters':parameters})
    batches=[]
    for component in result['components']:
        if not component.get('path'):continue
        path=Path(component['path']);checksum=sha(path)
        with np.load(path,allow_pickle=False)as arrays:validate_depth_output(arrays,len(component['image_ids']))
        metadata={'backend':'mast3r_colmap','sha256':checksum,'units':'sfm_relative','metric_scale_verified':False,
            'extrinsic_convention':'world_to_camera_optical','depth_kind':'optical_z','common_frame':key+'/'+component['component'],
            # Full per-track residuals stay in the component report. Replicating
            # thousands of them for every Object/View bloats the Codex handoff.
            'alignment':{k:v for k,v in component['alignment'].items()if k!='residual'},'image_ids':component['image_ids']}
        batches.append({'image_ids':component['image_ids'],'path':str(path),'metadata':metadata,'cache_key':key+'/'+component['component']})
    return batches,{**result,'needs':needs+result['needs'],'runtime_identity':identity,'mast3r_output':str(gpu),'colmap_output':str(cpu)}


def publish(folder,data):
    import json
    from .files import sha
    folder=Path(folder)
    data['files']={p.relative_to(folder).as_posix():sha(p)for p in sorted(folder.rglob('*'))if p.is_file()and p.name not in('result.json','COMPLETE')}
    (folder/'result.json').write_text(json.dumps(data,indent=2,allow_nan=False));(folder/'COMPLETE').write_text('complete\n')


def probe(request):
    import importlib.metadata as meta
    import json,sys
    from .files import sha
    kind=request['kind'];info={'python':sys.version,'numpy':meta.version('numpy'),'worker_sha256':sha(Path(__file__))}
    if kind=='mast3r':
        source=Path(request['source']).resolve()
        if not(source/'mast3r/model.py').is_file():raise ValueError('Existing official MASt3R source directory required')
        info.update(torch=meta.version('torch'),source_files={str(p.relative_to(source)):sha(p)for name in('mast3r','dust3r/dust3r','dust3r/croco/models')for p in sorted((source/name).rglob('*.py'))})
    else:
        import pycolmap
        import importlib.util
        info.update(pycolmap=pycolmap.__version__,has_cuda=bool(pycolmap.has_cuda),binary_sha256=sha(Path(importlib.util.find_spec('pycolmap._core').origin)))
        if not pycolmap.has_cuda:raise ValueError('CUDA-enabled PyCOLMAP installation required')
    Path(request['output']).write_text(json.dumps(info,indent=2))


def view_components(views,edges):
    """Preserve independent observed graphs; isolated images have no 3D frame."""
    remaining=set(views);groups=[]
    for seed in views:
        if seed not in remaining:continue
        group={seed}
        while True:
            extended=group|{b for a,b in edges if a in group}|{a for a,b in edges if b in group}
            if extended==group:break
            group=extended
        groups.append([view for view in views if view in group]);remaining-=group
    return groups


def component_pairs(members,pairs):
    """Official optimizer indices are local to its image list, not all inputs."""
    indices={name:i for i,name in enumerate(members)}
    return [tuple({**view,'idx':indices[view['instance']]}for view in pair)
        for pair in pairs if all(view['instance']in indices for view in pair)]


def mast3r_worker(request):
    """Official MASt3R GPU APIs, then static-only correspondences and pointmaps.

    The local sparse alignment puts pointmaps in one relative MASt3R frame.
    COLMAP performs the final camera/triangulation/BA stage in its own worker.
    """
    import sys,tempfile,json,time
    started=time.monotonic()
    sys.path.insert(0,str(Path(request['source']).resolve()))
    import torch,cv2
    from PIL import Image
    from mast3r.model import AsymmetricMASt3R
    from mast3r.image_pairs import make_pairs
    from mast3r.cloud_opt.sparse_ga import sparse_global_alignment,forward_mast3r,convert_dust3r_pairs_naming
    from mast3r.utils.misc import hash_md5
    from dust3r.utils.image import load_images,_resize_pil_image
    from .files import sha
    rows=request['images'];options=request['parameters'];folder=Path(request['output']);folder.mkdir(parents=True,exist_ok=True)
    resolution=int(options.get('process_res',512));iterations=int(options.get('iterations',100))
    if resolution not in(224,336,448,512)or not 1<=iterations<=300 or not 2<=len(rows)<=16:raise ValueError('MASt3R resolution 224/336/448/512, 2..16 training images, 1..300 iterations required')
    for row in rows:
        if sha(row['path'])!=row['sha256']or sha(row['static_mask'])!=row['static_mask_sha256']:raise ValueError('MASt3R source RGB/static mask changed')
    torch.set_num_threads(4);torch.cuda.reset_peak_memory_stats()
    model=AsymmetricMASt3R.from_pretrained(request['model']).to(options.get('device','cuda:0')).eval()
    paths=[row['path']for row in rows];images=load_images(paths,size=resolution);affines=[];masks=[]
    for image,row in zip(images,rows):
        original=Image.open(row['path']);w0,h0=original.size
        resized=_resize_pil_image(original,resolution if resolution!=224 else round(resolution*max(w0/h0,h0/w0)))
        w,h=resized.size;hp,wp=map(int,image['true_shape'][0]);a=np.array([[w/w0,0,-(w//2-wp/2)],[0,h/h0,-(h//2-hp/2)],[0,0,1.]])
        mask=np.asarray(Image.open(row['static_mask']).convert('L'))>0
        if mask.shape!=(h0,w0):raise ValueError('Static mask must use upright original pixels')
        masks.append(cv2.warpPerspective(mask.astype('uint8'),a,(wp,hp),flags=cv2.INTER_NEAREST)>0);affines.append(a)
    pairs=make_pairs(images,scene_graph=options.get('pair_graph','complete'),prefilter=None,symmetrize=True)
    with tempfile.TemporaryDirectory(prefix='mast3r-',dir=folder)as scratch:
        named=convert_dust3r_pairs_naming(paths,pairs)
        with torch.inference_mode():cached,_=forward_mast3r(named,model,scratch,device=options.get('device','cuda:0'))
        lookup={p:i for i,p in enumerate(paths)}
        usable=set()
        for (first,second),(_,file)in cached.items():
            score,(a,b,confidence)=torch.load(file,map_location='cpu',weights_only=False)
            x,y=np.asarray(a).astype(int),np.asarray(b).astype(int);conf=np.asarray(confidence)
            good=(conf>=float(options.get('match_confidence',5.)))&masks[lookup[first]][x[:,1],x[:,0]]&masks[lookup[second]][y[:,1],y[:,0]]
            a,b,confidence=a[good],b[good],confidence[good]
            torch.save(((score[0],float(confidence.sum()),len(confidence)),(a,b,confidence)),file)
            if len(confidence):usable.add((first,second))
        # The official optimizer reduces each edge's confidence with max().
        # A static-mask-filtered empty edge is absent evidence, not a zero match.
        named=[pair for pair in named if(pair[0]['instance'],pair[1]['instance'])in usable]
        components=view_components(paths,usable);unregistered=[]
        # Different components have independent relative gauges. COLMAP will
        # register their learned-match graphs separately, with one Sim(3) each.
        for members in components:
            indices=[paths.index(path)for path in members]
            if len(members)<2:
                unregistered.extend(rows[i]['id']for i in indices)
                for i in indices:
                    shape=masks[i].shape
                    np.savez_compressed(folder/f'view_{i}.npz',points=np.full((*shape,3),np.nan,np.float32),
                        confidence=np.zeros(shape,np.float32),original_to_processed=affines[i])
                continue
            pairs=component_pairs(members,named)
            scene=sparse_global_alignment(members,pairs,scratch,None,device=options.get('device','cuda:0'),niter1=iterations,niter2=iterations,shared_intrinsics=False)
            points,_,confidence=scene.get_dense_pts3d(clean_depth=True)
            for i,p,c in zip(indices,points,confidence):
                mask=masks[i];p=p.detach().cpu().numpy().reshape(*mask.shape,3);c=c.detach().cpu().numpy().reshape(mask.shape)
                c=np.where(mask&np.isfinite(p).all(-1)&(c>=float(options.get('dense_confidence',2.))),c,0.)
                np.savez_compressed(folder/f'view_{i}.npz',points=p,confidence=c,original_to_processed=affines[i])
        matches=[]
        for i in range(len(rows)):
            for j in range(i+1,len(rows)):
                key=(paths[i],paths[j])
                if key not in cached:continue
                _,(x,y,c)=torch.load(cached[key][1],map_location='cpu',weights_only=False)
                def original(p,a):return(np.c_[np.asarray(p),np.ones(len(p))]@np.linalg.inv(a).T)[:,:2]
                np.savez_compressed(folder/f'matches_{i}_{j}.npz',uv1=original(x,affines[i]),uv2=original(y,affines[j]),confidence=np.asarray(c))
                matches.append({'i':i,'j':j,'path':f'matches_{i}_{j}.npz','count':len(c)})
    publish(folder,{'status':'POINTMAPS_READY','images':rows,'matches':matches,'frame':'per_component_relative_world','metric_scale_verified':False,
        'components':[[rows[paths.index(p)]['id']for p in group]for group in components],'unregistered_images':unregistered,
        'needs':[name+': no static cross-view matches; no pointmap estimated'for name in unregistered],
        'elapsed_s':time.monotonic()-started,
        'allocated_peak_mib':torch.cuda.max_memory_allocated()/2**20,'reserved_peak_mib':torch.cuda.max_memory_reserved()/2**20})


def lens_group(row):
    """Only a declared device/lens identity permits intrinsic sharing."""
    return (row.get('physical_camera_id')or('unassigned',row['id']),*row['resolution'],
        row.get('source_exif_orientation',1),str(row.get('pixel_from_camera')))


def colmap_worker(request):
    """Import learned matches; native verification/SfM/BA; align dense geometry."""
    import json,time
    started=time.monotonic()
    import pycolmap
    from .files import read,write
    source=Path(request['mast3r']);learned=read(source/'result.json');rows=learned['images'];options=request['parameters']
    folder=Path(request['output']);folder.mkdir(parents=True,exist_ok=True);dbpath=folder/'database.db'
    def progress(stage):
        if request.get('progress'):write(request['progress'],{'stage':stage})
    progress('COLMAP Registration / Bundle Adjustment')
    if learned['status']!='POINTMAPS_READY':
        publish(folder,{'status':'UNRESOLVED','components':[],'needs':learned.get('needs',[]),'backend':'mast3r_colmap'})
        return
    maps=[{}for _ in rows];uvs=[[]for _ in rows];pairs=[]
    for pair in learned['matches']:
        i,j=pair['i'],pair['j'];matched=[]
        with np.load(source/pair['path'],allow_pickle=False)as data:
            for a,b in zip(data['uv1'],data['uv2']):
                ids=[]
                for index,uv in((i,a),(j,b)):
                    key=tuple(np.round(uv,4))
                    if key not in maps[index]:maps[index][key]=len(uvs[index]);uvs[index].append(uv)
                    ids.append(maps[index][key])
                matched.append(ids)
        if matched:pairs.append((i,j,np.asarray(matched,np.uint32)))
    if not pairs:
        publish(folder,{'status':'UNRESOLVED','components':[],'needs':learned.get('needs',[])+['No static learned correspondences available for SfM/BA'],'backend':'mast3r_colmap',
            'registered_images':0,'elapsed_s':time.monotonic()-started})
        return
    image_ids=[];camera_groups={};constant_cameras=set()
    with pycolmap.Database.open(dbpath)as db:
        for i,row in enumerate(rows):
            w,h=row['resolution'];known=row.get('known_lens');key=lens_group(row)
            if key not in camera_groups:
                if known:
                    k=np.array(known['K']);d=known['distortion'];cam=pycolmap.Camera(model='OPENCV',width=w,height=h,params=[k[0,0],k[1,1],k[0,2],k[1,2],*d[:4]])
                else:cam=pycolmap.Camera(model='SIMPLE_RADIAL',width=w,height=h,params=[1.2*max(w,h),w/2,h/2,0.])
                camera_groups[key]=db.write_camera(cam)
                if known:constant_cameras.add(camera_groups[key])
            cid=camera_groups[key];iid=db.write_image(pycolmap.Image(name=f'{i:04d}.png',camera_id=cid));image_ids.append(iid)
            db.write_keypoints(iid,np.array(uvs[i],np.float32).reshape(-1,2))
        for i,j,matched in pairs:db.write_matches(image_ids[i],image_ids[j],matched)
    pair_file=folder/'pairs.txt';pair_file.write_text(''.join(f'{i:04d}.png {j:04d}.png\n'for i,j,_ in pairs))
    # This entry point verifies imported matches; it does not extract SIFT.
    pycolmap.verify_matches(dbpath,pair_file)
    with pycolmap.Database.open(dbpath)as db:
        _,verified=db.read_two_view_geometries()
        verification={'pairs':len(verified),'inlier_matches':sum(len(g.inlier_matches)for g in verified),
                      'learned_matches':sum(len(matches)for _,_,matches in pairs),'feature_source':'MASt3R only; no SIFT extraction'}
    settings=pycolmap.IncrementalPipelineOptions();settings.num_threads=4;settings.min_model_size=2
    settings.max_runtime_seconds=int(options.get('mapping_timeout_s',180));settings.constant_cameras=constant_cameras
    models=pycolmap.incremental_mapping(dbpath,Path(request['images_directory']),folder/'sparse',options=settings)
    components=[];registered=set();camera_states={row['id']:'UNREGISTERED'for row in rows}
    for component,model in models.items():
        ba=pycolmap.BundleAdjustmentOptions();ba.ceres.solver_options.num_threads=4
        # Keep explicit calibrated lenses constant during the additional BA too.
        config=pycolmap.BundleAdjustmentConfig()
        for iid in model.reg_image_ids():config.add_image(iid)
        for cid in constant_cameras:
            if cid in model.cameras:config.set_constant_cam_intrinsics(cid)
        adjuster=pycolmap.create_default_bundle_adjuster(ba,config,model);adjuster.solve()
        progress('Dense Geometry Alignment')
        directory=folder/f'component_{component}';directory.mkdir();model.write(directory);model.export_PLY(directory/'sparse.ply')
        # Materialize each compressed pointmap once, rather than decompressing
        # the whole image again for every sparse track observation.
        data={}
        for i in range(len(rows)):
            with np.load(source/f'view_{i}.npz',allow_pickle=False)as raw:data[i]={k:raw[k]for k in raw.files}
        a=[];b=[]
        for point in model.points3D.values():
            for track in point.track.elements:
                image=model.images[track.image_id];index=int(Path(image.name).stem);uv=image.points2D[track.point2D_idx].xy
                raw=data[index];pixel=raw['original_to_processed']@np.r_[uv,1.];u,v=np.rint(pixel[:2]).astype(int)
                if 0<=v<raw['confidence'].shape[0]and 0<=u<raw['confidence'].shape[1]and raw['confidence'][v,u]>0:
                    a.append(raw['points'][v,u]);b.append(point.xyz)
        alignment=robust_similarity(np.asarray(a).reshape(-1,3),np.asarray(b).reshape(-1,3),max_relative_rmse=float(options.get('max_relative_alignment_rmse',.03)))
        component_report={'component':str(component),'registered_images':model.num_reg_images(),'sparse_points':model.num_points3D(),
            'reprojection_px':float(model.compute_mean_reprojection_error()),'alignment':alignment,'images':[]}
        if alignment['status']=='ALIGNED_RELATIVE':
            ids=[];depths=[];ks=[];exts=[];affines=[];confs=[];distortions=[];diagnostics=[]
            shapes=[d['confidence'].shape for d in data.values()];shape=tuple(np.max(shapes,axis=0))
            for iid in model.reg_image_ids():
                image=model.images[iid];index=int(Path(image.name).stem);cam=model.cameras[image.camera_id];raw=data[index]
                w2c=np.eye(4);w2c[:3]=image.cam_from_world().matrix();k=cam.calibration_matrix();dist=np.zeros(5)
                if str(cam.model.name)=='SIMPLE_RADIAL':dist[0]=cam.params[3]
                elif str(cam.model.name)=='OPENCV':dist[:4]=cam.params[4:8]
                affine=raw['original_to_processed'];processed_k=affine@k
                v,u=np.nonzero(raw['confidence']>0);observed=raw['points'][v,u];world=transform_points(observed,alignment)
                z,conf,diagnostic=optical_depth(world,raw['confidence'][v,u],processed_k,w2c,shape,distortion=dist,
                    source_pixels=np.c_[u,v],max_reprojection_px=float(options.get('max_dense_reprojection_px',8.)))
                if diagnostic['valid_pixels']<50:
                    camera_states[rows[index]['id']]='DENSE_UNRESOLVED';continue
                ids.append(rows[index]['id']);depths.append(z);ks.append(processed_k);exts.append(w2c);affines.append(affine);confs.append(conf);distortions.append(dist)
                diagnostics.append(diagnostic);registered.add(index);camera_states[rows[index]['id']]='REGISTERED_RELATIVE'
                component_report['images'].append({'image_id':rows[index]['id'],'physical_camera_id':rows[index]['physical_camera_id'],
                    'K_original':k.tolist(),'T_world_camera':np.linalg.inv(w2c).tolist(),'distortion':dist.tolist(),'dense':diagnostic})
            if ids:
                path=directory/'depth.npz';np.savez_compressed(path,depth=np.array(depths),intrinsics=np.array(ks),extrinsics=np.array(exts),
                    original_to_processed=np.array(affines),conf=np.array(confs),distortion=np.array(distortions))
                component_report.update(path=str(path),image_ids=ids,status='ALIGNED_RELATIVE')
        components.append(component_report)
    needs=[]
    if not models:needs.append('Learned matches did not initialize COLMAP SfM; no SIFT fallback or fabricated pose')
    if len(models)>1:needs.append('Disconnected SfM components retained separately; add bridging views')
    for key,state in camera_states.items():
        if state!='REGISTERED_RELATIVE':needs.append(key+': '+state)
    for component in components:
        if component['alignment']['status']!='ALIGNED_RELATIVE':needs.append('Component '+component['component']+': dense/sparse Sim(3) unresolved')
    publish(folder,{'status':'GEOMETRY_READY'if any(c.get('path')for c in components)else'UNRESOLVED','components':components,
        'verification':verification,'elapsed_s':time.monotonic()-started,
        'camera_states':camera_states,'needs':needs,'backend':'mast3r_colmap','metric_scale_verified':False,'units':'sfm_relative',
        'extrinsic_convention':'world_to_camera_optical','depth_kind':'optical_z'})
