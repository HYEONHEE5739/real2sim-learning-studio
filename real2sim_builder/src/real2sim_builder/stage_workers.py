"""Sequential, offline-local model children for SimFoundry-style reconstruction.

Only a child imports Torch/Open3D/probreg/model providers. It owns its complete
CUDA lifetime; neither GUI nor the orchestration process imports these models.
"""
from pathlib import Path
import importlib.util
import json
import os
import sys


def video(request):
    """FFmpeg decode with original sorted-stride frame selection and actual PTS."""
    import subprocess
    import hashlib
    from PIL import Image
    path=Path(request['video'])
    with path.open('rb')as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    if digest!=request['source_sha256']:raise ValueError('Video source changed')
    samples=request.get('candidates',15)
    if type(samples)is not int or not 1<=samples<=1000:raise ValueError('Invalid video candidate count')
    raw=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_frames',
        '-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)],text=True)
    stamps=[float(f['best_effort_timestamp_time'])for f in json.loads(raw)['frames']]
    if not stamps:raise ValueError('Video has no timestamped frames')
    stride=max(1,len(stamps)//samples);indices=list(range(len(stamps)))[::stride][:samples]
    expression='+'.join('eq(n\\,'+str(i)+')'for i in indices)
    output=Path(request['output'])
    subprocess.run(['ffmpeg','-v','error','-nostdin','-i',str(path),'-vf','select='+expression,
                    '-vsync','0',str(output/'frame_%04d.png')],check=True)
    paths=sorted(output.glob('frame_*.png'))
    if len(paths)!=len(indices):raise ValueError('FFmpeg output/frame-index contract mismatch')
    frames=[]
    for index,file in zip(indices,paths):
        with Image.open(file)as im:resolution=list(im.size)
        with file.open('rb')as f:s=hashlib.file_digest(f,'sha256').hexdigest()
        frames.append({'id':'video_'+digest[:16]+'_'+str(index),'path':str(file),'sha256':s,
                       'frame_index':index,'timestamp':stamps[index],'resolution':resolution})
    return {'frames':frames,'source_sha256':digest,'sampling':'SimFoundry sorted-stride',
            'decoded_frame_count':len(stamps)}


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _geometry():
    return _module('r2s_stage_geometry', Path(__file__).parent/'calibration/simfoundry.py')


def da3(request):
    import numpy as np
    import torch
    if request.get('source'):
        sys.path.insert(0, request['source'])
    from depth_anything_3.api import DepthAnything3
    snapshot = Path(request['model'])
    if not snapshot.is_dir() or not (snapshot/'model.safetensors').is_file():
        raise FileNotFoundError('Existing local DA3 snapshot required')
    if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
        raise ImportError('CUDA BF16 runtime required')
    model = DepthAnything3.from_pretrained(str(snapshot), local_files_only=True,
                                         token=False, strict=True, map_location='cpu')
    model.to(dtype=torch.bfloat16)
    heads = ('model.da3.head', 'model.da3_metric.head', 'model.da3.cam_dec.fc_t',
             'model.da3.cam_dec.fc_qvec', 'model.da3.cam_dec.fc_fov')
    for name in heads:
        model.get_submodule(name).to(dtype=torch.float32)
    for name, p in model.named_parameters():
        dtype = torch.float32 if any(name.startswith(h+'.') for h in heads) else torch.bfloat16
        if p.dtype != dtype:
            raise ValueError('DA3 installed module precision contract mismatch: '+name)
    model.to('cuda').eval()
    torch.cuda.reset_peak_memory_stats()
    prediction = model.inference(image=request['images'], intrinsics=None, extrinsics=None,
                                 infer_gs=False, use_ray_pose=False,
                                 process_res=int(request.get('process_res', 336)),
                                 process_res_method='upper_bound_resize', export_dir=None)
    torch.cuda.synchronize()
    path = Path(request['output'])/'prediction.npz'
    arrays = {'depth': prediction.depth, 'conf': prediction.conf,
              'intrinsics': prediction.intrinsics, 'extrinsics': prediction.extrinsics,
              'image': prediction.processed_images}
    if any(v is None or not np.isfinite(v).all() for v in arrays.values()):
        raise ValueError('DA3 did not return finite Depth/Confidence/K/Pose/RGB')
    if np.any(arrays['depth'] <= 0):
        raise ValueError('DA3 returned nonpositive optical Z')
    np.savez_compressed(path, **arrays)
    from PIL import Image
    sizes=[]
    for file in request['images']:
        with Image.open(file)as image:sizes.append(list(image.size))
    affines=_geometry().da3_pixel_affines(sizes,int(request.get('process_res',336)),[arrays['depth'].shape[2],arrays['depth'].shape[1]])
    return {'original_to_processed':affines,'path': str(path), 'is_metric': int(prediction.is_metric),
            'model_scale_factor': float(prediction.scale_factor),
            'precision': {str(d): sum(p.dtype == d for p in model.parameters())
                          for d in (torch.bfloat16, torch.float32)},
            'torch_peak_allocated_bytes': torch.cuda.max_memory_allocated(),
            'torch_peak_reserved_bytes': torch.cuda.max_memory_reserved(),
            'coordinate_frame': 'DA3 world-to-camera optical', 'metric_verified': False}


def support_masks(request):
    """SAM-only child; no Open3D, official sam3, or semantic encoder imports."""
    import numpy as np
    from PIL import Image
    adapter = _module('r2s_sam31', Path(__file__).with_name('sam31_adapter.py'))
    options = dict(request.get('model_options', {}))
    options.pop('text_encoder', None); options.pop('encoder_options', None)
    model = adapter.SAM31(request['model'], **options)
    candidates=[]
    with np.load(request['prediction']) as data:
        for rgb in data['image']:
            rows=[]
            for category in request.get('categories', ['table', 'floor']):
                masks, boxes, scores = model.predict_segmentation(Image.fromarray(rgb), category)
                rows.extend((mask, category, float(score)) for mask, score in zip(masks, scores))
            candidates.append(rows)
    arrays={}; metadata=[]
    for i, rows in enumerate(candidates):
        metadata.append([])
        for j, (mask, category, score) in enumerate(rows):
            key=f'mask_{i}_{j}'; arrays[key]=mask
            metadata[-1].append({'key':key,'category':category,'score':score})
    path=Path(request['output'])/'sam_support.npz'; np.savez_compressed(path, **arrays)
    provenance=model.provenance(); model.close()
    return {'path':str(path),'candidates':metadata,'provenance':provenance}


def support(request):
    """Original Open3D plane math, using recorded SAM3.1 masks after GPU exit."""
    import numpy as np
    import open3d as o3d
    geometry = _geometry()
    with np.load(request['prediction']) as data:
        rgb, depth, K = data['image'], data['depth'], data['intrinsics']
    masks, planes = [], []
    recorded=request['sam_result']
    with np.load(recorded['path']) as data:
        candidates_by_image=[[(data[r['key']],r['category'],r['score']) for r in rows]
                             for rows in recorded['candidates']]
    if len(candidates_by_image)!=len(depth):raise ValueError('Support frame count mismatch')
    for candidates, z, k in zip(candidates_by_image, depth, K):
        candidates = [c for c in candidates if c[0].any()]
        if not candidates:
            masks.append(np.zeros(z.shape, bool));planes.append({'eligible': False, 'reason': 'No SAM3 support'});continue
        mask, category, score = max(candidates, key=lambda row: row[0].sum())
        if mask.shape != z.shape:
            raise ValueError('Support Mask is not in the processed RGB/Depth pixel frame')
        points = geometry.backproject(z, k)[mask]
        if len(points) < 100:
            masks.append(mask);planes.append({'eligible': False, 'reason': 'Insufficient support pixels'});continue
        cloud = o3d.geometry.PointCloud();cloud.points = o3d.utility.Vector3dVector(points)
        fits = []
        for iterations in (2000, 1000):
            coeff, indices = cloud.segment_plane(distance_threshold=.01, ransac_n=3, num_iterations=iterations)
            coeff = np.asarray(coeff, float)
            if coeff[2] > 0:coeff = -coeff
            center = points[indices].mean(0)
            origin = center - (center @ coeff[:3]+coeff[3])*coeff[:3]
            fits.append({'coefficients': coeff.tolist(), 'inliers': list(map(int, indices)),
                         'origin': origin.tolist(), 'iterations': iterations})
        masks.append(mask);planes.append({'eligible': True, 'category': category, 'score': score,
                                         'selection': fits[0], 'final': fits[1]})
    path = Path(request['output'])/'support_masks.npz'
    np.savez_compressed(path, masks=np.asarray(masks))
    return {'path': str(path), 'planes': planes, 'sam_provenance': recorded['provenance']}


def segments_raw(request):
    """Text-first/point-fallback SAM3.1 only; candidates carry no instance identity."""
    import numpy as np
    from PIL import Image
    pure=_module('r2s_decomposition_math',Path(__file__).parent/'calibration/decomposition.py')
    adapter=_module('r2s_sam31',Path(__file__).with_name('sam31_adapter.py'))
    options=dict(request.get('model_options',{}))
    options.pop('text_encoder',None); options.pop('encoder_options',None)
    model=adapter.SAM31(request['model'],**options)
    image=Image.open(request['image']).convert('RGB');objects=request['objects'];rows=[]
    categories={obj['id']:pure.get_primary_object_name(obj.get('category',obj['prompt']))for obj in objects}
    masks=[];boxes=[];scores=[];phrases=[];fallback=[]
    for category in dict.fromkeys(categories.values()):
        m,b,s=model.predict_segmentation(image,category)
        masks.extend(np.squeeze(x).astype(bool)for x in m);boxes.extend(b);scores.extend(s);phrases.extend([category]*len(m))
        if len(m)==0:
            for obj in (o for o in objects if categories[o['id']]==category):
                point,meta=pure.choose_prompt_point_from_bbox(obj['box_xyxy'],[o['box_xyxy']for o in objects if o['id']!=obj['id']],image.width,image.height)
                m,b,s=model.predict_segmentation_with_point(image,point_coords=[point],point_labels=[1],multimask_output=True)
                if len(m):
                    best=int(np.argmax(s));masks.append(np.squeeze(m[best]).astype(bool));boxes.append(b[best]);scores.append(s[best]);phrases.append(category)
                fallback.append({'id':obj['id'],'point':point,**meta})
    path=Path(request['output'])/'raw_masks.npz'
    np.savez_compressed(path,masks=np.asarray(masks,dtype=bool),boxes=np.asarray(boxes),scores=np.asarray(scores))
    provenance=model.provenance();model.close()
    return {'path':str(path),'phrases':phrases,'point_fallback':fallback,'provenance':provenance}


def segments(request):
    """Unchanged pruning/association in a CPU environment after SAM child exits."""
    import numpy as np
    from PIL import Image
    from sentence_transformers import SentenceTransformer
    pure=_module('r2s_decomposition_math',Path(__file__).parent/'calibration/decomposition.py')
    # Explicit local snapshot binding and CPU construction, no transient CUDA model.
    encoder_model=request.get('model')
    if not encoder_model or not Path(encoder_model).is_dir():raise FileNotFoundError('Local SBERT snapshot required')
    class Encoder:
        def __init__(self):self.backbone=SentenceTransformer(encoder_model,device='cpu',local_files_only=True)
        def get_text_features(self,text):return self.backbone.encode(text)
        def get_similarity_matrix(self,a,b):return self.backbone.similarity(a,b)
    encoder=Encoder();encoder_name='sbert_cpu'
    image=Image.open(request['image']).convert('RGB');objects=request['objects'];rows=[]
    raw=request['sam_result'];fallback=raw['point_fallback'];phrases=raw['phrases']
    with np.load(raw['path'])as data:
        masks=list(data['masks']);boxes=data['boxes'];scores=data['scores']
    if not masks:return {'objects':[{'id':o['id'],'status':'NOT_FOUND'}for o in objects],'point_fallback':fallback}
    if any(m.shape!=(image.height,image.width)for m in masks):raise ValueError('SAM3 pixel frame mismatch')
    if any(not m.any()for m in masks):raise ValueError('Degenerate empty SAM3 Mask')
    masks,boxes,scores,phrases=pure.prune_redundant_masks(masks,np.asarray(boxes),np.asarray(scores),phrases,
        polygon_relative_intersection_threshold=.97,polygon_relative_area_threshold=.9,
        obj_mask_intersect_area_threshold=.8,duplicate_mask_intersect_area_threshold=.95,
        boundary_proportion=.02,text_encoder=encoder,text_encoder_similarity_threshold=.85)
    if masks and request.get('world_points'):
        cloud=np.load(request['world_points'])
        masks,boxes,scores,phrases=pure.prune_masks_below_surface(masks,boxes,scores,phrases,cloud,
            valid_mask=np.ones(masks[0].shape,bool),z_threshold=-.05,z_threshold_proportion=.1)
    masks=pure.disentangle_masks(masks,phrases,overlap_threshold_proportion=.9)if masks else[]
    try:assignment=pure.associate_masks(objects,boxes)
    except ValueError:return {'objects':[{'id':o['id'],'status':'AMBIGUOUS'}for o in objects],'point_fallback':fallback,'pruned_instances':len(masks)}
    for obj in objects:
        i=assignment[obj['id']];mask=masks[i]
        if not mask.any():rows.append({'id':obj['id'],'status':'AMBIGUOUS'});continue
        path=Path(request['output'])/(obj['id']+'_mask.png');Image.fromarray(mask.astype('uint8')*255).save(path)
        rows.append({'id':obj['id'],'status':'UNIQUE_ESTIMATED','path':str(path),'confidence':float(scores[i]),'category':phrases[i]})
    return {'objects':rows,'point_fallback':fallback,'encoder':encoder_name,'sam_provenance':raw['provenance'],
            'policy':'original text-first/SBERT/prune/below-support/disentangle; stable IDs by unambiguous pixel assignment'}


def image_edit(request):
    """Original image provider, with local model downloads disabled by environment."""
    provider = request.get('provider', 'comfy_gguf')
    if provider == 'comfy_gguf':
        return _module('r2s_comfy_edit',Path(__file__).with_name('comfy_edit.py')).edit(request)
    if provider=='gemini':raise ValueError('Gemini image editing is retired; configure local comfy_gguf explicitly')
    from simfoundry.models.vlm import Imagen3, FLUX1
    cls = {'imagen3': Imagen3, 'flux': FLUX1}[provider]
    if request.get('task')=='describe':
        if not hasattr(cls,'IMAGE_SHAPES'):
            return {'provider':provider,'supported':False,'inference_executed':False,
                    'reason':'Provider has no original Stage6 native shape contract'}
        return {'provider':provider,'supported':True,'inference_executed':False,'image_shapes':[list(x)for x in cls.IMAGE_SHAPES]}
    model = cls(**request.get('model_options', {}))
    kwargs = {'prompt': request['prompt']}
    if request.get('task')=='removal':
        from simfoundry.utils import prompt_utils
        kwargs['prompt']=getattr(prompt_utils,'prompt_flux_object_removal_'+request['annotation_mode'])(obj_phrase=request['object_prompt'])
    if request.get('task')in('upsample','infill'):
        from simfoundry.utils import prompt_utils
        kwargs['prompt']=(prompt_utils.prompt_infill_image_no_conditioning(obj_name=request['object_prompt'])if request['task']=='infill'else
            prompt_utils.prompt_flux_object_completion_and_upsample_preserve(obj_phrase=request['object_prompt'])if provider=='flux'else prompt_utils.prompt_upsample_image_gemini())
    if 'seed'in request:kwargs['seed']=request['seed']
    kwargs['image_path']=request['image']
    if provider=='imagen3'and request.get('mask'):kwargs['mask_image_path']=request['mask']
    elif provider=='flux'and request.get('mask'):
        import numpy as np
        import cv2
        from PIL import Image
        rgb=np.array(Image.open(request['image']).convert('RGB'));mask=np.array(Image.open(request['mask']).convert('L'))
        contours,_=cv2.findContours((mask>0).astype('uint8'),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(rgb,contours,-1,(0,255,0),2)
        annotation=Path(request['output'])/'outlined.png';Image.fromarray(rgb).save(annotation)
        kwargs['image_path']=str(annotation)
        kwargs['prompt']='Remove the object outlined in green, including the green annotation. '+kwargs['prompt']
    result = model(**kwargs)
    if provider=='flux':images=[result]
    else:images = model.get_result_images(result)
    if not images:raise RuntimeError('Image provider returned no images')
    path = Path(request['output'])/'edited.png';images[0].save(path)
    return {'path': str(path), 'provider': provider}


def background_remove(request):
    """Original Bria RemBG inference, with an explicit local-only weight adapter."""
    from rembg import remove
    from rembg.sessions.bria_rmbg import BriaRmBgSession
    import onnxruntime as ort
    from PIL import Image
    model=Path(request.get('model',''))
    if not model.is_file() or model.suffix!='.onnx':raise FileNotFoundError('Existing Bria ONNX model required')
    class LocalBria(BriaRmBgSession):
        @classmethod
        def download_models(cls,*args,**kwargs):return str(model.resolve())
    session=LocalBria('bria-rmbg',ort.SessionOptions(),providers=['CPUExecutionProvider'])
    image=Image.open(request['image']).convert('RGBA');original=image.size
    max_side=request.get('max_side',1024)
    if type(max_side)is not int or not 32<=max_side<=2048:raise ValueError('Invalid RemBG resolution budget')
    if max(original)>max_side:
        ratio=max_side/max(original);image=image.resize(tuple(max(1,round(x*ratio))for x in original),Image.Resampling.LANCZOS)
    output=remove(image,session=session).convert('RGBA')
    if output.size!=original:
        restored=Image.open(request['image']).convert('RGBA');restored.putalpha(output.getchannel('A').resize(original,Image.Resampling.LANCZOS));output=restored
    path=Path(request['output'])/'transparent.png';output.save(path)
    import hashlib,importlib.metadata
    with model.open('rb')as stream:model_sha=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'path':str(path),'algorithm':'original Bria RemBG','model':str(model.resolve()),
            'model_sha256':model_sha,'model_bytes':model.stat().st_size,'network_download':False,
            'rembg_version':importlib.metadata.version('rembg'),'onnxruntime_version':ort.__version__,
            'execution_providers':session.inner_session.get_providers(),
            'alpha_source':'generated-image Bria refinement; not original SAM mask','provenance':'estimated foreground alpha'}


def removal(request):
    """Use the source occlusion/support ray algorithm, rather than mask order."""
    import numpy as np
    import trimesh
    import open3d as o3d
    module=_module('r2s_decomposition_math',Path(__file__).parent/'calibration/decomposition.py')
    denoise_obj_point_cloud_v2=module.denoise_obj_point_cloud_v2
    hulls = {}
    for obj in request['objects']:
        points = np.load(obj['points'])
        cloud=o3d.geometry.PointCloud();cloud.points=o3d.utility.Vector3dVector(points)
        pruned,_=denoise_obj_point_cloud_v2(pcd_obj=cloud,visualize_process=False,visualize_result=False,
            target_density_cm2=5.,outlier_removal_n_neighbors=None,outlier_removal_std_ratio=1.,
            dbscan_eps=.005,dbscan_min_pts=None,cluster_proportion_threshold=.06)
        points=np.asarray(pruned.points)
        if len(points)<4:raise ValueError('Insufficient original denoised object points for hull ordering')
        hull = trimesh.convex.convex_hull(points)
        hulls[obj['id']] = trimesh.convex.convex_hull(hull.vertices-.0025*hull.vertex_normals)
    order = []
    while hulls:
        name = module.compute_object_removal_order(hulls, np.asarray(request['camera_to_world']))
        order.append(name);del hulls[name]
    return {'order': order, 'algorithm': 'original occlusion/support/foreground ray ordering'}


def depth_inpaint(request):
    """Original PriorDepthAnything conditioning and keep-known-depth splice."""
    import numpy as np
    from PIL import Image
    from prior_depth_anything import PriorDepthAnything, Arguments
    import torch
    args=Arguments();args.K=5
    for key,value in request.get('model_options',{}).items():
        if not hasattr(args,key):raise ValueError('Unknown PriorDepthAnything option')
        setattr(args,key,value)
    checkpoint=Path(request.get('model',''))
    files=[checkpoint/name for name in ('depth_anything_v2_vitl.pth','prior_depth_anything_vitb.pth')]
    if any(not p.is_file()for p in files):raise FileNotFoundError('Explicit local PriorDepth v1.0 vitl/vitb checkpoints required')
    prior=np.load(request['prior']).astype(np.float32);geometric=np.load(request['geometric']).astype(np.float32)
    image=np.asarray(Image.open(request['image']).convert('RGB'))
    K=np.asarray(request['K'],float)
    if prior.shape!=image.shape[:2]or geometric.shape!=prior.shape or not np.isfinite(prior).all()or np.any(prior<0)or not np.isfinite(geometric).all()or np.any(geometric<=0):raise ValueError('RGB/prior/geometric optical-Z grid mismatch')
    if K.shape!=(3,3)or not np.isfinite(K).all()or min(K[0,0],K[1,1])<=0:raise ValueError('Valid Camera K required')
    if request.get('coordinate_frame')!='selected optical Camera Z; same RGB pixel grid':raise ValueError('Explicit optical-Z coordinate frame required')
    torch.cuda.reset_peak_memory_stats()
    model = PriorDepthAnything(device='cuda', mde_dir=str(checkpoint), ckpt_dir=str(checkpoint), frozen_model_size='vitl',
                              conditioned_model_size='vitb', coarse_only=False,
                              version='1.0', args=args)
    loaded_memory={'allocated':torch.cuda.memory_allocated(),'reserved':torch.cuda.memory_reserved()}
    def calc_scale_shift_fp32(k_sparse_targets,k_pred_targets,currk_dists=None,knn=False):
        # Same runtime-local override as original Stage5, not a library edit.
        with torch.autocast(device_type='cuda',enabled=False):
            y=k_sparse_targets.float();x=k_pred_targets.float()
            distances=currk_dists.float()if currk_dists is not None else None
            x=x+torch.rand_like(x)*1e-5;X=torch.stack([x,torch.ones_like(x)],dim=2)
            if knn>0:y,X=model.completion.perform_weighted(y,X,distances)
            elif x.shape[0]>1:y=y.unsqueeze(-1)
            solution=torch.linalg.lstsq(X,y)[0]
            return solution[:,0].squeeze(),solution[:,1].squeeze()
    model.completion.calc_scale_shift=calc_scale_shift_fp32
    prior = np.load(request['prior']).astype(np.float32)
    geometric = np.load(request['geometric']).astype(np.float32)
    image = np.asarray(Image.open(request['image']).convert('RGB'))
    prediction = model.infer_one_sample(image=image, prior=prior, geometric=geometric,
                                       visualize=False).detach().float().cpu().numpy()
    result = np.where(prior == 0, prediction, prior)
    if result.shape != prior.shape or not np.isfinite(result).all() or np.any(result <= 0):
        raise ValueError('Invalid conditioned depth inpainting output')
    path = Path(request['output'])/'depth.npy';np.save(path, result)
    generated=prior==0
    provenance=Path(request['output'])/'generated_pixels.npy';np.save(provenance,generated)
    torch.cuda.synchronize()
    return {'path': str(path), 'algorithm': 'PriorDepthAnything keep-known-depth splice',
            'generated_pixels':str(provenance),'known_pixels_preserved':bool(np.array_equal(result[~generated],prior[~generated])),
            'confidence':None,'provenance':'generated optical-Z is estimated; no calibrated confidence',
            'K':K.tolist(),'K_usage':'pixel-frame validation; PDA API does not accept K',
            'coordinate_frame':request['coordinate_frame'],'units':request.get('units','UNKNOWN'),
            'loaded_torch_bytes':loaded_memory,'peak_allocated_bytes':torch.cuda.max_memory_allocated(),
            'peak_reserved_bytes':torch.cuda.max_memory_reserved(),'model_files':[str(p.resolve())for p in files]}


def cpd(request):
    """Source Stage8 OBB/voxel/farthest/SO(3)/rigid CPD/NN/inverse-fit recipe.

    Native OBJ is used where the source reads a generated GLB. No alternative ICP
    solver or guessed pose is used if probreg/Open3D is unavailable.
    """
    import copy
    import numpy as np
    import open3d as o3d
    from probreg import cpd as registration
    from scipy.spatial.transform import Rotation
    from scipy.spatial import cKDTree
    observations=np.load(request['points'])
    observations=observations[np.isfinite(observations).all(1)]
    if len(observations)<10:raise ValueError('Insufficient observed CPD points')
    source=o3d.geometry.PointCloud();source.points=o3d.utility.Vector3dVector(observations)
    mesh=o3d.io.read_triangle_mesh(request['mesh'],enable_post_processing=True)
    if mesh.is_empty():raise ValueError('Empty native mesh')
    n=request.get('surface_samples',10000);starts=request.get('samples',10)
    if type(n)is not int or not 10<=n<=100000 or type(starts)is not int or not 1<=starts<=64:
        raise ValueError('Invalid bounded CPD sampling budget')
    target=mesh.sample_points_poisson_disk(number_of_points=n).remove_non_finite_points()
    observed_diag=np.linalg.norm(source.get_oriented_bounding_box().extent)
    mesh_diag=np.linalg.norm(target.get_oriented_bounding_box().extent)
    if min(observed_diag,mesh_diag)<=0:raise ValueError('Degenerate CPD object geometry')
    protected=bool(request['scale_protected'])
    pre_scale=1. if protected else float(observed_diag/mesh_diag)
    target.scale(pre_scale,center=np.zeros(3));voxel=observed_diag/30
    source=source.voxel_down_sample(voxel);target=target.voxel_down_sample(voxel)
    count=min(len(source.points),len(target.points))
    if count<10:raise ValueError('Insufficient CPD points after original voxel downsampling')
    target=target.farthest_point_down_sample(num_samples=count)
    rotations=Rotation.random(starts).as_matrix();candidates=[]
    for update_scale in ([False]if protected else[False,True]):
        for initial in rotations:
            trial=copy.deepcopy(source);trial.points=o3d.utility.Vector3dVector(np.asarray(trial.points)@initial.T)
            fit,_,_=registration.registration_cpd(trial,target,tf_type_name='rigid',use_color=False,
                                                   use_cuda=False,update_scale=update_scale)
            fitted=np.asarray(fit.transform(trial.points))
            distance,_=cKDTree(fitted).query(np.asarray(target.points),k=1)
            rot=np.asarray(fit.rot)@initial;scale=float(fit.scale);translation=np.asarray(fit.t)
            inverse_rotation=rot.T;inverse_scale=1/scale;inverse_translation=-inverse_rotation@translation/scale
            candidates.append({'rotation':inverse_rotation.tolist(),'translation':inverse_translation.tolist(),
                'scale':float(pre_scale*inverse_scale),'score':float(np.sum(distance**2)),
                'rmse_m':float(np.sqrt(np.mean(distance**2))),'scale_update':bool(update_scale)})
    result=copy.deepcopy(min(candidates,key=lambda c:c['score']))
    result.update(status='UNVERIFIED',algorithm='original rigid CPD multistart / one-sided NN squared sum',
                  pre_scale=pre_scale,voxel_m=float(voxel),source_points=len(source.points),
                  target_points=len(target.points),candidates=len(candidates),candidate_fits=sorted(candidates,key=lambda c:c['score']),accuracy_verified=False,
                  coordinate_frame='native mesh to selected optical Camera')
    quality=_module('r2s_pose_quality',Path(__file__).parent/'calibration/registration.py')
    # target already contains pre_scale. Keep the original candidate ranking;
    # report quality in the selected optical Camera after the inverse fit.
    predicted=np.asarray(target.points)@(np.asarray(result['rotation']).T)*(result['scale']/pre_scale)+np.asarray(result['translation'])
    result['quality']=quality.pose_fit_quality(predicted,np.asarray(source.points),voxel_m=voxel,candidates=candidates)
    path=Path(request['output'])/'fit.json';path.write_text(json.dumps(result,indent=2));return result


def front_views(request):
    """Original CPU software renders only; semantic judgment stays in Codex."""
    import numpy as np
    import trimesh
    from simfoundry.pipeline.front_canonicalization import render_yaw_views
    C=np.array([[1.,0,0],[0,0,1],[0,-1,0]])
    mesh=trimesh.load(request['mesh'],force='mesh',process=False)
    mesh.vertices=np.asarray(mesh.vertices)@np.asarray(request['tilt_rotation']).T@C.T
    coarse=request.get('coarse_azimuth')
    azimuths=tuple(range(0,360,45))if coarse is None else[float(coarse+d)for d in np.arange(-22.5,22.5+1e-9,7.5)]
    views=render_yaw_views(mesh,request['output'],azimuths_deg=azimuths)
    return {'views':[{'label':label,'azimuth_deg':az,'path':path}for label,az,path in views]}


def foundationpose(request):
    import numpy as np
    import trimesh
    import nvdiffrast.torch as dr
    from estimater import FoundationPose, ScorePredictor, PoseRefinePredictor
    with np.load(request['observed'])as a:rgb=a['image'];depth=a['depth'];K=a['K'];mask=a['mask']
    mesh=trimesh.load(request['mesh'],force='mesh',process=False)
    scale=float(request['initial_fit']['scale']);mesh.apply_scale(scale)
    model=FoundationPose(model_pts=mesh.vertices,model_normals=mesh.vertex_normals,mesh=mesh,
        scorer=ScorePredictor(),refiner=PoseRefinePredictor(),debug_dir=request['output'],
        debug=0,glctx=dr.RasterizeCudaContext())
    pose=model.register(K=K,rgb=rgb,depth=depth,ob_mask=mask,iteration=5)
    return {'rotation':pose[:3,:3].tolist(),'translation':pose[:3,3].tolist(),'scale':scale,
            'status':'UNVERIFIED','algorithm':'FoundationPose','accuracy_verified':False}



def _builder_runtime():
    # Child-only imports: keep Qt/parent free of engine and model initialization.
    root=Path(__file__).resolve().parents[3]
    sys.path.insert(0,str(root/'scene_contract/src'))
    sys.path.insert(0,str(root/'real2sim_builder/src'))


def physics(request):
    _builder_runtime()
    from real2sim_builder.project import Project
    from real2sim_builder.files import read
    from real2sim_builder.validation import physics_probe
    project=Project(request['project']);scene=read(request['scene'])
    launcher=None
    try:
        if request['engine']=='isaac':
            from isaaclab.app import AppLauncher
            launcher=AppLauncher(headless=True,enable_cameras=False,device='cpu',fast_shutdown=False)
        return physics_probe(project,scene,request['output'],steps=request['steps'],engine=request['engine'])
    finally:
        if launcher is not None:launcher.app.close()


def simulator(request):
    _builder_runtime()
    from real2sim_builder.files import read
    from real2sim_builder.export import verify_package
    from real2sim_builder.cameras import camera_roles,select_render_cameras
    from real2sim_builder.scene import validate
    from PIL import Image
    scene=read(request['scene']);root=Path(request['project']);verify_package(request['package'])
    validate(scene,root,complete=True)
    ids=request['camera_ids'];roles=camera_roles(scene,request.get('image_records',[]))
    if any(roles.get(name)not in('side','wrist')for name in ids):raise ValueError('Only metadata-identified sensors may be runtime cameras')
    descriptor=select_render_cameras(scene,camera_ids=ids,image_records=request.get('image_records',[]))if ids else {**scene,'cameras':[]}
    launcher=None;renderer=None;paths=[]
    try:
        if request['engine']=='isaac':
            from isaaclab.app import AppLauncher
            launcher=AppLauncher(headless=True,enable_cameras=bool(ids),device='cuda:0',fast_shutdown=False)
            from real2sim_builder.isaac_render import IsaacRenderer
            renderer=IsaacRenderer(descriptor,root,request['output'],data_types=('rgb',))
        else:
            from real2sim_builder.rendering import Renderer
            renderer=Renderer(descriptor,root,request['output'])
        for name in ids:
            path=Path(request['output'])/(name+'.png');Image.fromarray(renderer.rgb(name)).save(path);paths.append(str(path))
        return {'status':'NOT_VERIFIED','runtime_loaded':True,'physics_steps':0,
                'camera_ids':ids,'renders':paths,'q_scope':'candidate state only; no measured Capture comparison or hardware control'}
    finally:
        if renderer is not None:renderer.close()
        if launcher is not None:launcher.app.close()

def main(kind, request):
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_DATASETS_OFFLINE='1')
    folder = Path(request['output']);folder.mkdir(parents=True, exist_ok=True)
    if request.get('simfoundry_source'):
        sys.path.insert(0, request['simfoundry_source'])
    if request.get('source'):
        sys.path.insert(0,request['source'])
    operations = {'video': video, 'da3': da3, 'support_planes':support, 'segments_post':segments, 'support': support, 'support_masks':support_masks, 'segments': segments, 'segments_raw':segments_raw,
                  'image_edit': image_edit, 'background_remove':background_remove, 'removal': removal, 'depth_inpaint': depth_inpaint,
                  'cpd':cpd,'front_views':front_views,'foundationpose':foundationpose,'physics':physics,'simulator':simulator}
    try:
        result = operations[kind](request)
        record = {'status': 'COMPLETE', 'execution': 'real', 'data': result}
        code = 0
    except (ImportError, FileNotFoundError) as error:
        record = {'status': 'NEEDS_RUNTIME', 'execution': 'real',
                  'error': {'type': type(error).__name__, 'message': 'Configured local model/runtime dependency is unavailable'}}
        code = 2
    except Exception as error:
        # Avoid copying provider URLs, credentials or remote response text to a Project log.
        oom = 'out of memory' in str(error).lower()
        provider_code=None;cause=error
        for _ in range(5):
            if cause is None:break
            candidate_code=getattr(cause,'code',None)or getattr(cause,'status_code',None)
            if callable(candidate_code):candidate_code=candidate_code()
            if candidate_code is not None:provider_code=candidate_code;break
            cause=cause.__cause__
        auth=provider_code in(401,403,'UNAUTHENTICATED','PERMISSION_DENIED')
        quota=provider_code in(429,'RESOURCE_EXHAUSTED')
        record = {'status': 'NEEDS_RUNTIME'if(auth or quota)else'FAILED', 'execution': 'real',
                  'error': {'type': type(error).__name__, 'code': 'USAGE_LIMIT'if quota else'AUTHENTICATION_FAILED'if auth else'VRAM_OUT_OF_MEMORY' if oom else 'WORKER_FAILED'}}
        code = 2
    (folder/'result.json').write_text(json.dumps(record, indent=2, allow_nan=False))
    return code


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--worker':
        raise SystemExit('Internal stage worker: --worker KIND REQUEST.json')
    raise SystemExit(main(sys.argv[2], json.loads(Path(sys.argv[3]).read_text())))
