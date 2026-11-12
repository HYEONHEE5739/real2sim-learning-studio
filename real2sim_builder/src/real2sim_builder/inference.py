"""Sequential local perception workers and explicit RGB/depth coordinates.

Workers use the already installed environments; this module installs/downloads nothing.
Sources: Ultralytics SAM3SemanticPredictor and DepthAnything3.inference (see docs).
"""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def validate_depth_output(arrays,count):
    import numpy as np
    depth=np.asarray(arrays['depth']);k=np.asarray(arrays['intrinsics']);ext=np.asarray(arrays['extrinsics'])
    if depth.ndim!=3 or depth.shape[0]!=count or k.shape!=(count,3,3)or ext.shape not in((count,3,4),(count,4,4)):
        raise ValueError('Geometry depth/Camera batch shapes differ from ordered source images')
    if not np.isfinite(k).all()or np.any(k[:,(0,1),(0,1)]<=0)or not np.allclose(k[:,2],[0,0,1]):raise ValueError('Invalid Geometry intrinsic matrices')
    rotation=ext[:,:3,:3]
    if not np.isfinite(ext).all()or not np.allclose(rotation.transpose(0,2,1)@rotation,np.eye(3),atol=1e-3)or not np.allclose(np.linalg.det(rotation),1,atol=1e-3):raise ValueError('Invalid Geometry world-to-camera extrinsics')
    if ext.shape[1]==4 and not np.allclose(ext[:,3],[0,0,0,1]):raise ValueError('Invalid Geometry homogeneous row')
    if any(not np.any(np.isfinite(row)&(row>0))for row in depth):raise ValueError('Geometry has no valid positive depth in a view')
    if 'conf'in arrays:
        conf=np.asarray(arrays['conf'])
        if conf.shape!=depth.shape or not np.isfinite(conf).all()or np.any(conf<0):raise ValueError('Invalid Geometry confidence/depth pixels')
    if 'original_to_processed'in arrays:
        affine=np.asarray(arrays['original_to_processed'])
        if affine.shape!=(count,3,3)or not np.isfinite(affine).all()or np.any(abs(np.linalg.det(affine))<1e-12):raise ValueError('Invalid original-to-processed pixel transform')
    if 'distortion'in arrays:
        distortion=np.asarray(arrays['distortion'])
        if distortion.shape!=(count,5)or not np.isfinite(distortion).all():raise ValueError('Invalid Geometry lens distortion')


def object_points(depth,mask,k,original_to_processed,*,confidence=None,min_confidence=0.,erode_px=1,max_points=20000,distortion=None,distortion_rotation=None,relative_units='geometry_relative'):
    """Backproject only observed mask pixels in the depth model's optical frame."""
    import cv2
    import numpy as np
    z=np.asarray(depth,float);source=np.asarray(mask);matrix=np.asarray(k,float);a=np.asarray(original_to_processed,float)
    if z.ndim!=2 or source.ndim!=2 or a.shape!=(3,3)or not np.isfinite(a).all()or abs(np.linalg.det(a))<1e-12:
        raise ValueError('Explicit invertible original-to-processed pixel transform required')
    if matrix.shape!=(3,3)or not np.isfinite(matrix).all()or min(matrix[0,0],matrix[1,1])<=0:raise ValueError('Valid processed-resolution Camera K required')
    if type(erode_px)is not int or erode_px<0 or type(max_points)is not int or max_points<1:raise ValueError('Invalid point filtering settings')
    aligned=cv2.warpPerspective((source>0).astype('uint8'),a,(z.shape[1],z.shape[0]),flags=cv2.INTER_NEAREST)
    if erode_px:aligned=cv2.erode(aligned,np.ones((erode_px*2+1,erode_px*2+1),np.uint8))
    keep=(aligned>0)&np.isfinite(z)&(z>0)
    if confidence is not None:
        confidence=np.asarray(confidence)
        if confidence.shape!=z.shape:raise ValueError('Confidence/depth pixels differ')
        keep&=np.isfinite(confidence)&(confidence>=min_confidence)
    v,u=np.nonzero(keep)
    if len(u)>max_points:
        selected=np.linspace(0,len(u)-1,max_points,dtype=int);v,u=v[selected],u[selected]
    from .cameras import optical_rays
    lens={'K':{'value':matrix},'distortion':{'value':distortion if distortion is not None else [0.]*5}}
    if distortion_rotation is not None:lens['distortion_rotation']=distortion_rotation
    rays=optical_rays(lens,np.c_[u,v])
    points=rays*z[v,u,None]
    return points,{'points':len(points),'frame':'camera_optical','units':relative_units,'provenance':'derived',
                   'processed_resolution':[z.shape[1],z.shape[0]],'original_resolution':[source.shape[1],source.shape[0]],
                   'original_to_processed':a.tolist(),'hidden_surface_generated':False}


def metric_points(points,anchor,world_from_camera):
    import numpy as np
    from .scene import transform
    if anchor is None or world_from_camera is None:
        return {'status':'NEEDS_MORE_DATA','needs':['Measured scale anchor and Camera-to-World registration required']}
    scale=anchor.get('scale')
    if anchor.get('source')not in('measured','calibrated')or not anchor.get('evidence')or not isinstance(scale,(int,float))or not np.isfinite(scale)or scale<=0:
        raise ValueError('Positive depth scale with measured/calibrated anchor evidence required')
    pose=transform(world_from_camera);points=np.asarray(points,float)
    if points.ndim!=2 or points.shape[1:]!=(3,)or not np.isfinite(points).all():raise ValueError('Finite optical points required')
    world=(points*scale)@pose[:3,:3].T+pose[:3,3]
    return {'status':'METRIC_ESTIMATED','points_world_m':world,'units':'m','frame':'world',
            'provenance':'derived','anchor':anchor,'physical_verified':False}


def depth_scale_from_anchors(depth,original_to_processed,uv,world_points,world_from_camera,evidence):
    """Robust depth ratio at measured World anchors; never use scale=1 fallback."""
    import numpy as np
    from .scene import transform
    if len(uv)<4 or not evidence:
        return {'status':'NEEDS_MORE_DATA','needs':['Four visible measured depth anchors and registered Camera required']}
    pixels=np.asarray(uv,float);points=np.asarray(world_points,float);z=np.asarray(depth,float)
    a=np.asarray(original_to_processed,float);pose=transform(world_from_camera)
    if pixels.shape!=(len(points),2)or points.shape[1:]!=(3,)or not all(np.isfinite(v).all()for v in(pixels,points,a)):
        raise ValueError('Finite corresponding original pixels and measured World anchors required')
    processed=np.c_[pixels,np.ones(len(pixels))]@a.T;processed=processed[:,:2]/processed[:,2:]
    camera=(points-pose[:3,3])@pose[:3,:3];ratios=[]
    for pixel,point in zip(processed,camera):
        u,v=np.rint(pixel).astype(int)
        patch=z[max(v-1,0):v+2,max(u-1,0):u+2]if 0<=u<z.shape[1]and 0<=v<z.shape[0]else np.array([])
        valid=patch[np.isfinite(patch)&(patch>0)]
        if len(valid)and point[2]>0:ratios.append(point[2]/np.median(valid))
    if len(ratios)<4:return {'status':'NEEDS_MORE_DATA','needs':['Depth is invalid at measured anchor pixels']}
    scale=float(np.median(ratios));dispersion=float(np.median(np.abs(np.asarray(ratios)/scale-1)))
    if dispersion>.1:return {'status':'NEEDS_MORE_DATA','needs':['Depth ratios disagree with measured anchors'],'relative_mad':dispersion}
    return {'status':'ESTIMATED','anchor':{'scale':scale,'source':'measured','evidence':evidence},
            'relative_mad':dispersion,'anchor_count':len(ratios),'scope':'derived depth scale from measured anchors; not independently validated'}


def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def cross_view_associations(report,objects):
    """Extend seeded instance tracks in one relative geometry frame, without SAM order identity.

    Only geometry resolves another view. Unseeded symmetric instances remain
    ambiguous; missing masks are view-local and never change Asset Identity.
    """
    import numpy as np
    from PIL import Image
    from scipy.optimize import linear_sum_assignment
    from .calibration.registration import align_depth_batches
    from .files import sha
    batches=report.get('depth_batches',[])
    if not batches or len({r['image_id']for r in report.get('segments',[])})<2:return report
    alignment=align_depth_batches(batches);views={};cache={};tracks={}
    for batch,binding in zip(batches,alignment['batches']):
        if binding['state']=='UNRESOLVED':continue
        with np.load(batch['path'],allow_pickle=False)as data:
            validate_depth_output(data,len(batch['image_ids']))
            for i,key in enumerate(batch['image_ids']):
                if key in views:continue
                ext=np.eye(4);ext[:data['extrinsics'][i].shape[0]]=data['extrinsics'][i]
                pose=np.linalg.inv(ext);common=np.asarray(binding['T_common_batch'])
                views[key]=({k:v[i].copy()for k,v in data.items()},pose,common,binding['scale'])
    def geometry(image,mask):
        key=(image,mask['sha256'])
        if key in cache:return cache[key]
        if image not in views:return None
        if sha(mask['path'])!=mask['sha256']:raise ValueError('Association Mask SHA changed')
        raw,pose,common,scale=views[image]
        pixels=np.asarray(Image.open(mask['path']).convert('L'))>0
        points,_=object_points(raw['depth'],pixels,raw['intrinsics'],raw['original_to_processed'],confidence=raw.get('conf'),max_points=1500)
        if len(points)<20:return None
        points=(points@pose[:3,:3].T+pose[:3,3])*scale
        points=points@common[:3,:3].T+common[:3,3]
        center=np.median(points,axis=0);size=max(1e-8,float(np.linalg.norm(np.percentile(points,95,axis=0)-np.percentile(points,5,axis=0))))
        cache[key]=(center,size)
        return cache[key]
    for row in report.get('segments',[]):
        a=row.get('association',{})
        if a.get('status')!='ASSIGNED_ESTIMATED':continue
        reference=objects.get(row['object_id'],{}).get('representative_view')
        if reference and row['image_id']!=reference:continue
        data=geometry(row['image_id'],{'path':a['mask_path'],'sha256':a['mask_sha256']})
        if data:tracks.setdefault(row['object_id'],[]).append(data)
    for row in report.get('segments',[]):
        reference=objects.get(row['object_id'],{}).get('representative_view')
        a=row.get('association',{});track=tracks.get(row['object_id'])
        if not reference or row['image_id']==reference or not track or a.get('status')!='ASSIGNED_ESTIMATED':continue
        data=geometry(row['image_id'],{'path':a['mask_path'],'sha256':a['mask_sha256']})
        if data:
            center=np.median([t[0]for t in track],axis=0);size=np.median([t[1]for t in track])
            if np.linalg.norm(center-data[0])/max(size,data[1])>.65:
                row['association']={'status':'AMBIGUOUS','basis':'Semantic/representative 3D conflict','conflict':True}
    for image in views:
        rows=[r for r in report.get('segments',[])if r['image_id']==image]
        unresolved=[r for r in rows if r['object_id']in tracks and r.get('association',{}).get('status')!='ASSIGNED_ESTIMATED'and not r.get('association',{}).get('conflict')]
        used={r['association']['mask_sha256']for r in rows if r.get('association',{}).get('status')=='ASSIGNED_ESTIMATED'}
        masks={m['sha256']:m for r in unresolved for m in r['masks']if m['sha256']not in used}
        masks=[m for m in masks.values()if geometry(image,m)]
        if not unresolved or not masks:continue
        cost=np.full((len(unresolved),len(masks)),1e6)
        for i,row in enumerate(unresolved):
            track=tracks[row['object_id']];center=np.median([t[0]for t in track],axis=0);size=np.median([t[1]for t in track])
            allowed={m['sha256']for m in row['masks']}
            for j,mask in enumerate(masks):
                if mask['sha256']not in allowed:continue
                observed,extent=geometry(image,mask)
                cost[i,j]=np.linalg.norm(center-observed)/max(size,extent)
        ri,ci=linear_sum_assignment(cost)
        for i,j in zip(ri,ci):
            score=cost[i,j];alternatives=np.delete(cost[i],j);competitors=np.delete(cost[:,j],i)
            if score>.65 or np.any(alternatives<score+.2)or np.any(competitors<score+.2):continue
            row=unresolved[i];mask=masks[j];index=next(k for k,m in enumerate(row['masks'])if m['sha256']==mask['sha256'])
            row['association']={'status':'ASSIGNED_ESTIMATED','basis':'cross_view_geometry','mask_index':index,'mask_path':mask['path'],
                'mask_sha256':mask['sha256'],'provenance':'derived','physical_identity_verified':False,'normalized_center_error':float(score)}
            tracks[row['object_id']].append(geometry(image,mask))
        for row in unresolved:
            if row.get('association',{}).get('status')!='ASSIGNED_ESTIMATED'and row['masks']:
                row['association']={'status':'NOT_FOUND','basis':'No compatible cross-view 3D candidate; occlusion or missed detection'}
    return report


def associate_instances(report,objects,selections=None):
    """Assign per-image observations independently from shared asset identity.

    No mask-order/left-to-right identity guess and no Camera/3D assumptions.
    Explicit selections, image boxes or an unambiguous unique candidate suffice.
    Conflicting assignments remain unresolved for the existing mask-selection UI.
    """
    import copy
    import numpy as np
    from PIL import Image
    from .files import sha
    result=copy.deepcopy(report);used={};needs=[];selections=selections or{}
    for row in result.get('segments',[]):
        name=row['object_id'];image=row['image_id'];masks=row['masks'];selected=selections.get(image,{}).get(name)
        basis='explicit_selection';index=None;external=None
        if isinstance(selected,str):external=Path(selected)
        elif selected is not None:
            if type(selected)is not int or not 0<=selected<len(masks):raise ValueError('Mask selection index is outside candidates')
            index=selected
        else:
            query=objects.get(name,{});hint=query.get('images',{}).get(image,{})
            box=hint.get('box_xyxy',query.get('box_xyxy'));points=hint.get('points',[])
            if points:
                compatible=[]
                for k,mask in enumerate(masks):
                    if sha(mask['path'])!=mask['sha256']:raise ValueError('Association Mask SHA changed')
                    with Image.open(mask['path'])as rgb:a=np.asarray(rgb.convert('L'))>0
                    if all(0<=int(p['xy'][0])<a.shape[1] and 0<=int(p['xy'][1])<a.shape[0]
                           and bool(a[int(p['xy'][1]),int(p['xy'][0])])==bool(p['label'])for p in points):compatible.append(k)
                if len(compatible)==1:index=compatible[0];basis='image_points'
            if box is not None:
                scores=[]
                for mask in masks:
                    if sha(mask['path'])!=mask['sha256']:raise ValueError('Association Mask SHA changed')
                    with Image.open(mask['path'])as rgb:a=np.asarray(rgb.convert('L'))>0
                    x0,y0,x1,y1=map(int,box)
                    scores.append(float(a[max(0,y0):max(0,y1),max(0,x0):max(0,x1)].sum()/max(1,a.sum())))
                ranked=sorted(range(len(scores)),key=lambda i:scores[i],reverse=True)
                if not points and ranked and scores[ranked[0]]>.5 and(len(ranked)==1 or scores[ranked[0]]-scores[ranked[1]]>.1):index=ranked[0];basis='image_box'
            elif not points and len(masks)==1:index=0;basis='unique_candidate'
        if index is None and external is None:
            row['association']={'status':'AMBIGUOUS'if masks else'NOT_FOUND','basis':'No unique Object observation correspondence'}
            needs.append(image+'/'+name+': choose a Mask; Asset Group is not Object association');continue
        file=external or Path(masks[index]['path'])
        if external is None and sha(file)!=masks[index]['sha256']:raise ValueError('Association Mask SHA changed')
        with Image.open(file)as rgb:a=np.asarray(rgb.convert('L'))>0
        signature=hashlib.sha256(str(a.shape).encode()+a.tobytes()).hexdigest()
        row['association']={'status':'ASSIGNED_ESTIMATED','basis':basis,'mask_index':index,'mask_path':str(file),
            'mask_sha256':sha(file),'provenance':'user_selected'if selected is not None else'derived','physical_identity_verified':False}
        used.setdefault((image,signature),[]).append(row)
    for rows in used.values():
        if len(rows)>1:
            names=', '.join(r['object_id']for r in rows)
            # A sole visible candidate can belong to either occluded instance;
            # geometry may resolve that ambiguity. Explicit conflicting hints
            # must instead remain unresolved for review.
            explicit=any(r['association']['basis']!='unique_candidate' for r in rows)
            for row in rows:row['association']={'status':'AMBIGUOUS','basis':'Conflicting same Mask assignments','conflict':explicit}
            needs.append(rows[0]['image_id']+': same Mask assigned to multiple Objects: '+names)
    # Different PNGs can encode the same instance with slightly different edges.
    # Reject near-duplicate masks, not genuine occlusion/contained objects.
    assigned=[r for r in result.get('segments',[])if r['association']['status']=='ASSIGNED_ESTIMATED']
    for i,left in enumerate(assigned):
        for right in assigned[i+1:]:
            if left['image_id']!=right['image_id']:continue
            with Image.open(left['association']['mask_path'])as rgb:a=np.asarray(rgb.convert('L'))>0
            with Image.open(right['association']['mask_path'])as rgb:b=np.asarray(rgb.convert('L'))>0
            if a.shape!=b.shape:raise ValueError('Association masks have different resolutions')
            if (a&b).sum()/max(1,(a|b).sum())>.9:
                for row in(left,right):row['_duplicate_mask']=True
    for row in assigned:
        if row.pop('_duplicate_mask',False):row['association']={'status':'AMBIGUOUS','basis':'Near-duplicate instance masks','conflict':True}
    result=cross_view_associations(result,objects)
    result['association_needs']=[r['image_id']+'/'+r['object_id']+': '+r['association']['basis']for r in result.get('segments',[])if r['association']['status']!='ASSIGNED_ESTIMATED']
    return result


def build_point_clouds(candidate,report,*,selections=None):
    """Join masks and depth only through registered metric cameras and anchors.

    Selection values are explicit mask indices or edited original-resolution PNG
    files. Ambiguous SAM components never receive an automatic identity.
    """
    import numpy as np
    from PIL import Image
    from .files import read,write,sha
    from .scene import world_pose,camera_calibration_signature
    from .observations import registered_images,source_record_digest
    from .capture import observation_scene
    from .candidate import exclusive
    selections=selections or{}
    config_path=candidate.root/'reconstruction-config.yaml'
    config=read(config_path)if config_path.is_file()else{}
    report=associate_instances(report,config.get('objects',{}),selections)
    with exclusive(candidate.project):
        candidate.require_open();scene=candidate.scene
        images,state,needs=registered_images(candidate.project,report['scene_state_id'],scene=scene)
        by_id={i['id']:i for i in images};depths={};records=[]
        for batch in report['depth_batches']:
            file=Path(batch['path'])
            if not file.resolve().is_relative_to(candidate.root.resolve())or sha(file)!=batch['metadata']['sha256']:
                raise ValueError('Depth artifact identity or Candidate ownership changed')
            with np.load(file,allow_pickle=False)as data:
                validate_depth_output(data,len(batch['image_ids']))
                for index,image_id in enumerate(batch['image_ids']):
                    prediction=scene.get('camera_predictions',{}).get('views',{}).get(image_id)
                    if prediction and prediction.get('depth_batch')!=batch.get('cache_key',batch['path']):continue
                    depths.setdefault(image_id,({k:v[index].copy()for k,v in data.items()},batch))
        for segment in report['segments']:
            candidate.project.checkpoint();image=by_id.get(segment['image_id']);name=segment['object_id'];label=segment['image_id']+'/'+name
            if image is None:needs.append(label+': Camera not metric-registered');continue
            if segment['image_id']not in depths:needs.append(label+': geometry Camera/Depth unresolved');continue
            if image['sha256']!=segment['source_image_sha256']:raise ValueError('Segmentation source identity changed')
            registration=scene.get('view_registrations',{}).get(image['id'],{});binding=registration.get('metric_anchors',{})
            motion_scale=registration.get('depth_scale')
            if motion_scale is None and(binding.get('source')not in('measured','calibrated')or not binding.get('evidence')):
                needs.append(label+': visible measured scale anchors required');continue
            association=segment.get('association',{})
            if association.get('status')!='ASSIGNED_ESTIMATED':
                needs.append(label+': unresolved Mask/Object association');continue
            selected=selections.get(image['id'],{}).get(name,association.get('mask_index'))
            if selected is None and len(segment['masks'])!=1:
                needs.append(label+': select the correct mask or supply an edited mask');continue
            if isinstance(selected,str):source=Path(selected).resolve();digest=sha(source)
            else:
                index=0 if selected is None else selected
                if type(index)is not int or not 0<=index<len(segment['masks']):raise ValueError('Mask selection index is outside candidates')
                record=segment['masks'][index];source=Path(record['path']).resolve();digest=record['sha256']
                if not source.is_relative_to(candidate.root.resolve())or sha(source)!=digest:raise ValueError('SAM mask changed or escaped Candidate')
            mask=np.asarray(Image.open(source).convert('L'))>0
            if mask.shape!=tuple(image['resolution'][::-1]):raise ValueError('Edited mask must use original RGB resolution')
            posed=observation_scene(scene,image,candidate.project.root,complete=False)
            cam=next(c for c in posed['cameras']if c['id']==image['camera']);camera_pose=world_pose(posed,cam)
            if (motion_scale is None and any(cam[field]['provenance']not in('measured','calibrated')for field in('K','distortion'))):
                needs.append(label+': calibrated lens rays required for depth clouds');continue
            arrays,batch=depths[image['id']];affine=arrays['original_to_processed']
            scale={'status':'ESTIMATED','anchor':{'scale':motion_scale,'source':'measured','evidence':registration.get('calibration_evidence',[])},
                'scope':'estimated registration scale from recorded metric baseline/motion; not physical calibration'}if motion_scale is not None else depth_scale_from_anchors(arrays['depth'],affine,binding.get('uv_px',[]),binding.get('world_points_m',[]),camera_pose,binding.get('evidence',[]))
            if scale['status']!='ESTIMATED':needs.extend(label+': '+reason for reason in scale['needs']);continue
            k=affine@np.asarray(cam['K']['value']);points,info=object_points(arrays['depth'],mask,k,affine,confidence=arrays.get('conf'),
                distortion=cam['distortion']['value'],distortion_rotation=cam.get('distortion_rotation'),relative_units=batch['metadata'].get('units','geometry_relative'))
            world=metric_points(points,scale['anchor'],camera_pose)['points_world_m']
            if len(world)<50:needs.append(label+': fewer than 50 valid visible points');continue
            dependencies={'mask_sha256':digest,'depth_sha256':batch['metadata']['sha256'],'image_sha256':image['sha256'],
                          'image_record_sha256':source_record_digest(image),
                          'camera_signature':camera_calibration_signature(scene,next(c for c in scene['cameras']if c['id']==image['camera'])),
                          'camera_pose':camera_pose.tolist(),'scale':scale,'algorithm_sha256':sha(Path(__file__))}
            folder=candidate.root/'.cache/inference/clouds'/_digest(dependencies);folder.mkdir(parents=True,exist_ok=True)
            stored_mask=folder/'mask.png';Image.fromarray(mask.astype('uint8')*255).save(stored_mask)
            cloud=folder/'points.npz'
            from .cameras import project_pixels
            original=project_pixels(cam,points)
            np.savez_compressed(cloud,points_world_m=world,points_camera_relative=points,uv_original=original,depth_relative=points[:,2])
            records.append({'image_id':image['id'],'object_id':name,'split':image['split'],'group_id':image['group_id'],
                'path':cloud.relative_to(candidate.project.root).as_posix(),'sha256':sha(cloud),
                'mask':stored_mask.relative_to(candidate.project.root).as_posix(),'mask_sha256':sha(stored_mask),
                'mask_kind':'visible_fragment','points':len(world),'units':'m','frame':'world','provenance':'derived',
                'identity_verified':False,'dependencies':dependencies,'point_filter':info,'camera':image['camera'],
                'depth_scale':scale['anchor']['scale'],'depth_batch':batch.get('cache_key',batch['path'])})
        scene['reconstruction_observations']={'scene_state_id':state,'clouds':records};candidate.save(scene)
        result={'status':'METRIC_ESTIMATED'if records else'NEEDS_MORE_DATA','clouds':records,'needs':list(dict.fromkeys(needs)),
                'physical_verified':False,'scene_state_id':state}
        write(candidate.root/'.cache/inference/clouds.json',result);return result


def build_render_observations(candidate,report,*,same_layout=False):
    """Append registered RGB/mask constraints without inventing sensor depth.

    A different/ambiguous static layout may constrain recorded robot geometry,
    but cannot move the photo Scene's objects to explain another arrangement.
    """
    import numpy as np
    from .observations import registered_images,source_record_digest
    from .scene import camera_calibration_signature,local_path
    from .files import sha,write
    scene=candidate.scene;images,_,needs=registered_images(candidate.project,scene=scene)
    by_id={i['id']:i for i in images};nodes={o['id']:o for o in scene['objects']};records=[]
    for segment in report.get('segments',[]):
        image=by_id.get(segment['image_id']);obj=nodes.get(segment['object_id']);association=segment.get('association',{})
        if image is None or obj is None:continue
        if not same_layout and obj['role']!='reference_robot':continue
        if association.get('status')!='ASSIGNED_ESTIMATED':continue
        source=Path(association['mask_path']);digest=association['mask_sha256']
        if not source.resolve().is_relative_to(candidate.root.resolve())or sha(source)!=digest:raise ValueError('Sensor Mask changed or escaped Candidate')
        cam=next(c for c in scene['cameras']if c['id']==image['camera'])
        dependencies={'image_sha256':image['sha256'],'image_record_sha256':source_record_digest(image),'mask_sha256':digest,
                      'camera_signature':camera_calibration_signature(scene,cam)}
        folder=candidate.root/'.cache/inference/clouds'/_digest(dependencies);folder.mkdir(parents=True,exist_ok=True)
        cloud=folder/'image-observation.npz'
        if not cloud.exists():np.savez_compressed(cloud,points_world_m=np.empty((0,3)))
        records.append({'image_id':image['id'],'camera':image['camera'],'object_id':obj['id'],'split':image['split'],'group_id':image['group_id'],
            'path':cloud.relative_to(candidate.project.root).as_posix(),'sha256':sha(cloud),
            'mask':source.relative_to(candidate.project.root).as_posix(),'mask_sha256':digest,'mask_kind':'silhouette',
            'points':0,'units':'m','frame':'world','render_only':True,'provenance':'derived','dependencies':dependencies,'identity_verified':False})
    observation=scene.setdefault('reconstruction_observations',{'clouds':[]})
    replacing={i['id']for i in report.get('images',[])}
    observation['clouds']=[r for r in observation['clouds']if r['image_id']not in replacing]+records
    candidate.save(scene)
    return {'status':'IMAGE_OBSERVATIONS_READY'if records else'NEEDS_MORE_DATA','clouds':records,
        'needs':needs+([]if records else['No eligible sensor Mask/Object correspondences; source Captures retained']),'depth_generated':False}


def _run_worker(project,python,kind,request,folder,timeout,*,entrypoint=None):
    """Own one child only; its exit releases GPU memory before the next model."""
    from .files import write
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);path=folder/'request.json';write(path,request)
    env=dict(os.environ,HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',
             YOLO_AUTOINSTALL='false',YOLO_CONFIG_DIR=str(folder/'ultralytics'))
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    # These engine children use the existing Isaac USD bindings, not a new USD
    # installation. The dynamic loader needs this before Python starts.
    if kind in ('physics','simulator') and entrypoint is not None and request.get('source'):
        usd=Path(request['source']).resolve()
        if not(usd/'pxr').is_dir()or not(usd/'bin').is_dir():
            raise FileNotFoundError('Configured existing USD binding/bin bootstrap required')
        env['LD_LIBRARY_PATH']=str(usd/'bin')+(':'+env['LD_LIBRARY_PATH']if env.get('LD_LIBRARY_PATH')else'')
    started=time.monotonic()
    last_stage=None
    with (folder/'worker.log').open('w')as log:
        script=Path(__file__).resolve() if entrypoint is None else Path(entrypoint).resolve()
        if script.parent!=Path(__file__).resolve().parent:raise ValueError('Worker entrypoint must be package-owned')
        child=subprocess.Popen([str(python),'-B',str(script),'--worker',kind,str(path)],stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        try:
            while child.poll()is None:
                project.checkpoint()
                if request.get('progress')and Path(request['progress']).is_file():
                    progress=json.loads(Path(request['progress']).read_text())
                    stage=progress.get('stage')
                    if stage and stage!=last_stage:
                        project.update(status='RUNNING',stage=stage);last_stage=stage
                if time.monotonic()-started>timeout:raise TimeoutError(kind+' worker deadline exceeded')
                time.sleep(.1)
            if child.returncode:
                tail=(folder/'worker.log').read_text(errors='replace')[-16000:]
                reason='VRAM_OUT_OF_MEMORY'if any(t in tail.lower()for t in('cuda out of memory','outofmemoryerror','cuda error: out of memory'))else'MODEL_EXECUTION_FAILED'
                raise RuntimeError(kind+' '+reason+'; inspect '+str(folder/'worker.log'))
        finally:
            # A runtime/tool descendant may outlive the group leader, even on
            # exit 0. Reuse the existing Codex owned-group cleanup boundary.
            from .codex_cli import stop_child
            stop_child(child)
    return time.monotonic()-started


def _runtime(project,config,kind,folder):
    from .files import sha,read
    spec=config.get(kind,{})
    python=Path(spec.get('python',''));model=Path(spec.get('model',''))
    if not python.is_file()or not os.access(python,os.X_OK):raise ValueError(kind+': configure an existing Python interpreter')
    files=sorted(p for p in model.rglob('*')if p.is_file()and p.suffix in('.json','.safetensors'))if model.is_dir()else[model]
    if not files or any(not p.is_file()for p in files):raise ValueError(kind+': configure existing local model/checkpoint files')
    _run_worker(project,python,'probe',{'kind':kind,'source':spec.get('source'),'output':str(folder/'probe.json')},folder,60)
    identity={'python':str(python.resolve()),'runtime':read(folder/'probe.json'),'files':{str(p.resolve()):sha(p)for p in files},'worker_sha256':sha(Path(__file__))}
    return spec,identity


def prepare_rgb(candidate,images):
    """Decode EXIF orientation identically for perception; retain source SHA/bytes."""
    from PIL import Image,ImageOps
    from .files import sha
    from .scene import local_path
    result={};folder=candidate.root/'.cache/inference/rgb';folder.mkdir(parents=True,exist_ok=True)
    for image in images:
        source=local_path(candidate.project.root,image['path'])
        if sha(source)!=image['sha256']:raise ValueError('Original RGB changed before model decoding')
        with Image.open(source)as decoded:
            orientation=decoded.getexif().get(274,1);rgb=ImageOps.exif_transpose(decoded).convert('RGB')
            if list(rgb.size)!=image['resolution']:raise ValueError('Decoded RGB and registered pixel coordinates differ')
            target=folder/(image['sha256']+'.png')
            if not target.exists():rgb.save(target)
            else:
                import numpy as np
                with Image.open(target)as cached:
                    if not np.array_equal(np.asarray(cached),np.asarray(rgb)):raise ValueError('Normalized RGB cache changed')
        result[image['id']]={'path':str(target),'sha256':sha(target),'source_sha256':image['sha256'],
                             'source_exif_orientation':orientation,'pixel_frame':'EXIF-upright registered RGB'}
    return result


def run_models(candidate,config,*,scene_state=None,sensor_alignment=False,segmentation_only=False):
    """Explicit SAM observations; geometry belongs to DA3 Stage2.

    Existing reports remain readable through validate_depth_output/object_points.
    Calling the removed geometry executor cannot silently replace its backend.
    """
    if not segmentation_only:
        raise ValueError('LEGACY_GEOMETRY_UNSUPPORTED: use SimFoundry DA3 Stage2; saved Depth/Camera metadata is preserved')
    from .files import read,write,sha
    from .observations import input_images,camera_type
    from .candidate import exclusive
    images,state,needs=input_images(candidate.project,scene_state)
    if not sensor_alignment and not segmentation_only:
        images=[i for i in images if not i.get('capture_manifest')]
        if not images:needs=needs+['Initial Scene reconstruction requires Scene Photos; Captures are reserved for sensor registration']
    if not images:return {'status':'NEEDS_MORE_DATA','needs':needs,'physical_verified':False}
    if config.get('image_ids'):
        requested=config['image_ids'];by_id={i['id']:i for i in images}
        if len(set(requested))!=len(requested)or not set(requested)<=by_id.keys():raise ValueError('Explicit image IDs must be unique and belong to the selected layout')
        images=[by_id[key]for key in requested]
    with exclusive(candidate.project):
        candidate.require_open();root=candidate.root/'.cache/inference';root.mkdir(parents=True,exist_ok=True)
        prepared=prepare_rgb(candidate,images)
        config=json.loads(json.dumps(config));objects=config.get('objects',{})
        if not objects:return {'status':'NEEDS_MORE_DATA','needs':['Object IDs with SAM prompts or explicit box hints required']}
        sam,sam_identity=_runtime(candidate.project,config,'sam',root/'sam-runtime')
        tasks=[];segments=[];queued=set()
        for image in images:
            for name,query in objects.items():
                from .scene import identifier
                identifier(name)
                hint=query.get('images',{}).get(image['id'],{})
                params={'prompt':query.get('prompt'),'box_xyxy':hint.get('box_xyxy',query.get('box_xyxy')),
                        'points':hint.get('points',[]),
                        'conf':sam.get('conf',.25),'imgsz':sam.get('imgsz',1024),'half':True,'device':sam.get('device','cuda:0')}
                if not params['prompt']and params['box_xyxy']is None and not params['points']:raise ValueError('SAM query, points or box required for '+name)
                key=_digest({'image':image['sha256'],'parameters':params,'model':sam_identity})
                folder=root/'sam'/key;record=folder/'result.json'
                if (folder/'COMPLETE').exists():
                    cached=read(record)
                    if any(sha(Path(m['path']))!=m['sha256']for m in cached['masks']):raise ValueError('Cached SAM mask changed')
                elif key not in queued:
                    queued.add(key);tasks.append({'image':prepared[image['id']]['path'],'sha256':prepared[image['id']]['sha256'],
                    'source_sha256':image['sha256'],'image_id':image['id'],'object_id':name,'parameters':params,'output':str(folder)})
                segments.append({'image_id':image['id'],'object_id':name,'path':str(record),'cache_key':key})
        if tasks:_run_worker(candidate.project,sam['python'],'sam',{'model':sam['model'],'tasks':tasks},root/'sam-job',float(sam.get('timeout_s',900)))
        for row in segments:
            name=row['object_id'];image=row['image_id'];row.update(read(row['path']));row.update(object_id=name,image_id=image)
        association=associate_instances({'segments':segments},objects,config.get('selections'))
        segments=association['segments']
        batches,geometry=[],{'status':'NOT_REQUESTED','needs':[],'scope':'SAM only; geometry is DA3 Stage2'}
        report={'status':'SEGMENTED'if segmentation_only else'INFERRED'if batches else'NEEDS_MORE_DATA','scene_state_id':state,'images':images,'segments':segments,
            'depth_batches':batches,'models':{'sam':sam_identity,'geometry':geometry.get('runtime_identity')},'geometry':geometry,
            'backend':'segmentation_only','prepared_rgb':prepared,'derived':True,'physical_verified':False,
            'metric_scale':'NOT_ESTABLISHED_BY_AI','needs':needs+geometry['needs']}
        report=associate_instances(report,objects,config.get('selections'))
        write(root/('sensor_'+state+'.json'if segmentation_only else'results.json'),report);return report


def _worker(kind,request):
    """Only this child imports model runtimes; no Builder dependency is needed."""
    def checksum(path):
        with Path(path).open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    def publish(folder,data):
        folder=Path(folder);folder.mkdir(exist_ok=True,parents=True)
        (folder/'result.json').write_text(json.dumps(data,indent=2,allow_nan=False));(folder/'COMPLETE').write_text('complete\n')
    if kind=='probe':
        if request['kind']!='sam':raise ValueError('Unknown inference worker probe')
        import importlib.metadata as meta
        import importlib.util
        package='ultralytics'
        distribution='ultralytics'
        spec=importlib.util.find_spec(package)
        if spec is None:raise ImportError(package+' is not installed in this configured interpreter')
        package_root=Path(spec.origin).parent if spec.origin else Path(next(iter(spec.submodule_search_locations)))
        source=package_root/'models/sam/predict.py'
        Path(request['output']).write_text(json.dumps({'python':sys.version,'package':distribution,'version':meta.version(distribution),
            'torch':meta.version('torch'),'api_sha256':checksum(source)}));return
    if kind!='sam':raise ValueError('Unknown inference worker')
    import numpy as np
    import torch
    if kind=='sam':
        from ultralytics.models.sam import SAM3SemanticPredictor,SAM3Predictor
        predictor=None;current=None;predictor_kind=None
        for task in request['tasks']:
            if checksum(task['image'])!=task['sha256']:raise ValueError('SAM source image changed')
            params=task['parameters'];folder=Path(task['output']);folder.mkdir(parents=True,exist_ok=True)
            kind='interactive'if params.get('points')else'semantic'
            if predictor is None or kind!=predictor_kind:
                del predictor
                torch.cuda.empty_cache();current=None;predictor_kind=kind
                cls=SAM3Predictor if kind=='interactive'else SAM3SemanticPredictor
                predictor=cls(overrides={'model':request['model'],'task':'segment','mode':'predict','half':True,'device':params['device'],
                    'conf':params['conf'],'imgsz':params['imgsz'],'save':False,'verbose':False})
            if task['image']!=current:predictor.set_image(task['image']);current=task['image']
            if kind=='interactive':
                # One task is one Object with multiple positive/negative hints, not N Objects.
                result=predictor(points=[[p['xy']for p in params['points']]],labels=[[p['label']for p in params['points']]],bboxes=[params['box_xyxy']]if params['box_xyxy']is not None else None)[0]
            else:result=predictor(text=[params['prompt']]if params['prompt']else None,bboxes=params['box_xyxy'])[0]
            rows=[]
            if result.masks is not None:
                from PIL import Image
                masks=result.masks.data.detach().cpu().numpy()
                for index,mask in enumerate(masks):
                    path=folder/f'mask_{index}.png';Image.fromarray(np.uint8(mask>0)*255).save(path)
                    rows.append({'path':str(path),'sha256':checksum(path),'confidence':float(result.boxes.conf[index]),
                                 'bbox_xyxy':result.boxes.xyxy[index].cpu().tolist(),'mask_kind':'visible_fragment'})
            publish(folder,{'image_id':task['image_id'],'object_id':task['object_id'],'source_image_sha256':task['source_sha256'],
                'parameters':params,'masks':rows,'status':'UNIQUE_ESTIMATED'if len(rows)==1 else'AMBIGUOUS'if rows else'NOT_FOUND',
                'provenance':'derived','identity_verified':False})
        del predictor
    else:raise ValueError('Unknown inference worker')
    if torch.cuda.is_available():torch.cuda.empty_cache()


if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--worker':raise SystemExit('Internal worker: --worker probe|sam REQUEST.json')
    _worker(sys.argv[2],json.loads(Path(sys.argv[3]).read_text()))
