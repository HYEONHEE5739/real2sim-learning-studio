"""Candidate-local image proposals reviewed by Codex, never measured evidence."""
import copy
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .files import read, sha, write
from .scene import identifier, local_path


def _digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _scene_digest(scene):
    return _digest({k: v for k, v in scene.items() if k != 'derived_observations'})


def input_images(project,scene_state=None):
    """Identity-checked RGB inputs, including unregistered external views."""
    images=[i for i in project.evidence['images']if i.get('id')and i.get('scene_state_id')]
    states = {i.get('scene_state_id') for i in images if i.get('scene_state_id')}
    if scene_state is None:
        if len(states) != 1:
            return [], None, ['Choose one scene_state_id from registered RGB inputs']
        scene_state = next(iter(states))
    identifier(scene_state)
    images = [i for i in images if i.get('scene_state_id') == scene_state]
    for image in images:
        path = local_path(project.root, image['path'])
        if not image.get('sha256') or sha(path) != image['sha256']:
            raise ValueError('Registered image SHA mismatch: ' + image['id'])
        if image.get('q_measured')is not None:
            q=np.asarray(image['q_measured'],float)
            if q.shape!=(len(image['joint_names']),)or not np.isfinite(q).all():raise ValueError('Invalid measured joints: '+image['id'])
        if camera_type(image)=='wrist'and image.get('q_measured')is None:raise ValueError('Wrist image requires measured q: '+image['id'])
    train={i['sha256']for i in images if i.get('split')=='train'}
    held={i['sha256']for i in images if i.get('split')=='validation'}
    if train&held:raise ValueError('Train/holdout source-image leakage')
    if {i['group_id']for i in images if i.get('split')=='train'}&{i['group_id']for i in images if i.get('split')=='validation'}:
        raise ValueError('Train/holdout observation-group leakage')
    return images,scene_state,[]if images else['No registered RGB inputs in this layout']


def camera_type(image):
    kind=image.get('camera_type','wrist'if image['camera']=='wrist'else'side'if image['camera']=='side'else'external')
    if kind not in('side','wrist','external'):raise ValueError('Camera type must be side, wrist or external')
    return kind


def source_record_digest(image):
    return image.get('_source_record_sha256')or _digest(image)


def view_quality_reasons(image):
    """Registration resolves a missing camera, never source blur/skew warnings."""
    if image.get('quality_override'):return []
    return [r for r in image.get('capture_quality_reasons',image.get('exclusion_reasons',[]))
        if r not in('unbound_capture_calibration','Camera-to-World registration required')]


def registered_images(project,scene_state=None,*,scene=None):
    scene_state=scene_state or(scene or{}).get('reconstruction_state',{}).get('id')
    images,state,needs=input_images(project,scene_state);result=[]
    registrations=(scene or{}).get('view_registrations',{})
    for original in images:
        image=copy.deepcopy(original);registration=registrations.get(image['id'])
        if registration:
            if registration['source_image_sha256']!=image['sha256']or registration['image_record_sha256']!=_digest(original):raise ValueError('View registration source changed')
            from .scene import camera_calibration_signature
            cam=next(c for c in scene['cameras']if c['id']==image['camera'])
            if registration.get('camera_signature')!=camera_calibration_signature(scene,cam):raise ValueError('View registration Camera calibration changed; register again')
            image['_source_record_sha256']=_digest(original)
            image['eligible']=registration['status']in('REGISTERED_ESTIMATED','REGISTERED_CALIBRATED')and not view_quality_reasons(original)
            image['registration_status']=registration['status']
        if image.get('eligible')is True:result.append(image)
    return result,state,needs or([]if result else['No World-registered eligible views in this layout'])


def register_image(project,path,*,camera,camera_type,scene_state,split='train',timestamp=None,observed_objects=(),joint_record=None):
    """Register RGB identity and its declared static layout; never synthesize q/pose."""
    from .evidence import add_image
    identifier(camera);identifier(scene_state)
    if camera_type not in('side','wrist','external'):raise ValueError('Unknown camera type')
    if split not in('train','validation'):raise ValueError('Invalid image split')
    if timestamp is not None and not np.isfinite(timestamp):raise ValueError('Finite image timestamp required')
    if camera_type=='wrist':
        if not joint_record or any(k not in joint_record for k in('q_measured','joint_names','mapping_sha256','robot_model_sha256','image_timestamp_ns','joint_timestamp_ns')):
            raise ValueError('Wrist requires measured q, mapping identity and image/joint timestamps; use Capture import')
        q=np.asarray(joint_record['q_measured'],float)
        if q.shape!=(len(joint_record['joint_names']),)or not np.isfinite(q).all()or joint_record.get('joint_units')!=['rad']*len(q):raise ValueError('Wrist measured model-radian mapping required')
        if abs(joint_record['image_timestamp_ns']-joint_record['joint_timestamp_ns'])>100_000_000:raise ValueError('Wrist image/joint skew exceeds 100ms')
        import re
        if any(not re.fullmatch('[0-9a-f]{64}',str(joint_record[key]))for key in('mapping_sha256','robot_model_sha256')):
            raise ValueError('Wrist requires actual model and mapping SHA256 identities')
    path=Path(path).resolve();digest=sha(path)
    old=next((i for i in project.evidence['images']if i.get('sha256')==digest and i['camera']==camera),None)
    if old and old.get('scene_state_id')and old['scene_state_id']!=scene_state:raise ValueError('The same image cannot be relabelled into another layout')
    if old and(old.get('session_id')or old.get('snapshot_id')):
        if old['split']!=split:raise ValueError('Image already registered as Capture; retain its original split/metadata')
        return copy.deepcopy(old)
    if old and old.get('camera_type'):
        if old['camera_type']!=camera_type or old['split']!=split or old.get('observed_objects',[])!=list(observed_objects):
            raise ValueError('Image already registered with different metadata; keep the original registration')
        if joint_record and any(old.get(key)!=val for key,val in joint_record.items()):
            raise ValueError('Image already registered with different measured joints; retain original metadata')
        return copy.deepcopy(old)
    row=add_image(project,path,camera,split,timestamp,context_only=True)
    evidence=project.evidence;record=next(i for i in evidence['images']if i['path']==row['path']and i['camera']==camera)
    from PIL import Image
    with Image.open(path)as raw:orientation=raw.getexif().get(274,1)
    record.update(exif_orientation=orientation,id=camera+'_'+digest[:20],camera_type=camera_type,physical_camera_id=camera,scene_state_id=scene_state,
                  group_id=camera+'_'+digest[:20],observed_objects=list(observed_objects),q_measured=None,
                  registration_status='UNREGISTERED',eligible=False,exclusion_reasons=['Camera-to-World registration required'])
    if record.get('source_video_sha256'):record['group_id']='video_'+record['source_video_sha256']
    if joint_record:
        for key in('q_measured','joint_names','joint_units','mapping_sha256','robot_model_sha256','image_timestamp_ns','joint_timestamp_ns'):
            record[key]=copy.deepcopy(joint_record[key])
    write(project.root/'input/evidence.yaml',evidence)
    return copy.deepcopy(record)


def register_sources(project,paths,**metadata):
    """Register photos or sampled external video with one shared video group."""
    from .evidence import copy_input,add_video,extract_videos
    from .candidate import exclusive
    rows=[]
    with exclusive(project):
        for path in paths:
            path=Path(path)
            if path.suffix.lower()not in('.mp4','.mov','.avi'):
                rows.append(register_image(project,path,**metadata));continue
            if metadata['camera_type']=='wrist':raise ValueError('Wrist video requires synchronized measured-q Capture import')
            relative=copy_input(project,path);digest=sha(project.root/relative)
            if not any(v['path']==relative and v['camera']==metadata['camera']for v in project.evidence['videos']):
                add_video(project,path,camera=metadata['camera'],split=metadata.get('split','train'))
            extract_videos(project,paths={relative})
            frames=[r for r in project.evidence['images']if r.get('source_video_sha256')==digest and r['camera']==metadata['camera']]
            for frame in frames:rows.append(register_image(project,project.root/frame['path'],**metadata))
    return rows


def register_views(candidate,anchors=None,*,scene_state=None):
    """Metric PnP for external views; calibrated fixed/mounted cameras stay fixed."""
    from .candidate import exclusive
    from .calibration.registration import camera_from_anchors
    from .scene import frame_world,value,world_pose
    anchors=anchors or{}
    with exclusive(candidate.project):
        candidate.require_open();scene=candidate.scene;images,state,needs=input_images(candidate.project,scene_state)
        if scene.get('reconstruction_state',{}).get('id',state)!=state:raise ValueError('Use one Candidate per static layout')
        cameras={c['id']:c for c in scene['cameras']};registrations=copy.deepcopy(scene.get('view_registrations',{}));rows=[]
        for image in images:
            cam=cameras.get(image['camera']);binding=anchors.get(image['id'],{})
            if cam is None or any(cam[k]['value']is None for k in('K','distortion')):
                needs.append(image['id']+': known Camera Intrinsics/distortion or a separately assessed intrinsic estimate required');continue
            from .cameras import camera_pixels
            try:pixel_affine,optical_rotation=camera_pixels(cam,image)
            except ValueError as error:needs.append(image['id']+': '+str(error));continue
            kind=camera_type(image)
            prior=registrations.get(image['id'])
            if not binding and prior and prior['status']in('REGISTERED_ESTIMATED','REGISTERED_CALIBRATED'):
                from .scene import camera_calibration_signature
                if prior['source_image_sha256']!=image['sha256']or prior['image_record_sha256']!=_digest(image)or prior['camera_signature']!=camera_calibration_signature(scene,cam):
                    raise ValueError('Camera registration is stale; initialize again')
                rows.append(prior);continue
            calibrated=all(cam[k]['provenance']in('measured','calibrated')for k in('K','pose','distortion'))
            if kind in('side','wrist'):
                if not calibrated:
                    needs.append(image['id']+': verified fixed Camera or Wrist mount calibration required');continue
                if kind=='wrist':
                    model=scene.get('robot_model',{})
                    if image.get('joint_names')!=model.get('joint_names')or not model.get('mapping',{}).get('sha256'):
                        needs.append(image['id']+': verified measured-q model mapping required');continue
                    from .capture import mapping_contract
                    mapping_contract({'joint_mapping':model['mapping'],'joint_names':model['joint_names'],
                        'joint_units':['rad']*len(model['joint_names']),'robot':model,'source_robot_sha256':model.get('source_robot_sha256')})
                    if sha(local_path(candidate.project.root,model['path']))!=model['model_sha256']:raise ValueError('Wrist Robot model changed')
                    if image.get('mapping_sha256',model['mapping']['sha256'])!=model['mapping']['sha256']or image.get('robot_model_sha256',model['model_sha256'])!=model['model_sha256']:
                        raise ValueError('Wrist measured q belongs to a different model or mapping')
                pose=None;status='REGISTERED_CALIBRATED';report={'source':'existing Camera calibration'}
            else:
                if binding.get('source')not in('measured','calibrated')or not binding.get('evidence'):
                    needs.append(image['id']+': metric World anchors are required; DA3 pose alone is not registration');continue
                report=camera_from_anchors(binding.get('world_points_m',[]),binding.get('uv_px',[]),(pixel_affine@np.asarray(cam['K']['value'])@optical_rotation.T).tolist(),cam['distortion']['value'])
                if report['status']!='ESTIMATED':needs.extend(image['id']+': '+n for n in report['needs']);continue
                pose=report['T_world_camera'];status='REGISTERED_ESTIMATED'
            from .scene import camera_calibration_signature
            row={'image_id':image['id'],'source_image_sha256':image['sha256'],'image_record_sha256':_digest(image),
                 'scene_state_id':state,'camera_type':kind,'camera':image['camera'],'status':status,'T_world_camera':pose,
                 'camera_signature':camera_calibration_signature(scene,cam),'pixel_from_camera':pixel_affine.tolist(),'optical_from_camera':optical_rotation.tolist(),'metric_anchors':copy.deepcopy(binding),
                 'calibration_evidence':binding.get('evidence',cam['pose'].get('evidence',[])),
                 'metric_scale_verified':True,'provenance':'derived','physical_verified':False,'report':report}
            registrations[image['id']]=row;rows.append(row)
        if rows:
            scene['view_registrations']=registrations;scene['reconstruction_state']={'id':state,'static_layout_verified':False};candidate.save(scene)
        return {'status':'REGISTERED_ESTIMATED'if rows and not needs else'NEEDS_MORE_DATA','views':rows,'needs':needs,'scene_state_id':state,'physical_verified':False}


def predict_views(candidate,inferred,options=None):
    """DA3 camera initialization without user-entered K, poses or board clicks.

    Relative DA3 frames are joined only through overlapping depth observations.
    Metric alignment requires observable calibrated baselines or measured wrist
    motion. Predictions stay PREDICTED/UNRESOLVED until that evidence exists.
    """
    from .calibration.registration import align_depth_batches,align_points,wrist_from_motion
    from .calibration.geometry import link_transforms
    from .scene import value,world_pose,frame_world,camera_calibration_signature
    from .capture import observation_scene
    from .candidate import exclusive
    options=options or{}
    with exclusive(candidate.project):
        scene=candidate.scene;images={i['id']:i for i in inferred.get('images',[])};predicted={}
        alignment=align_depth_batches(inferred.get('depth_batches',[]));needs=[]
        for batch,binding in zip(inferred.get('depth_batches',[]),alignment['batches']):
            if binding['state']=='UNRESOLVED':needs.extend(binding['needs']);continue
            with np.load(batch['path'],allow_pickle=False)as data:
                for index,name in enumerate(batch['image_ids']):
                    if name in predicted:continue
                    ext=np.eye(4);ext[:data['extrinsics'][index].shape[0]]=data['extrinsics'][index]
                    pose=np.linalg.inv(ext);common=np.asarray(binding['T_common_batch']);pose[:3,3]*=binding['scale'];pose=common@pose
                    affine=data['original_to_processed'][index];k=np.linalg.inv(affine)@data['intrinsics'][index]
                    predicted[name]={'K':k.tolist(),'T_relative_camera':pose.tolist(),'batch_scale':binding['scale'],
                        'depth_batch':batch.get('cache_key',batch['path']),'state':'PREDICTED','physical_verified':False}
        cameras={c['id']:c for c in scene['cameras']};relative=[];metric=[];known=[]
        def physical_pose(image):
            # DA3 sees upright RGB. A fixed lens/mount lives in one physical
            # optical frame even when EXIF rotates individual photographs.
            from .cameras import camera_pixels
            reference=cameras.get(image['camera'])
            if reference is None:
                first=next(i for i in images.values()if i['camera']==image['camera'])
                reference={'resolution':first['resolution'],'reference_orientation':first.get('exif_orientation',1)}
            _,rotation=camera_pixels(reference,image)
            pose=np.asarray(predicted[image['id']]['T_relative_camera']).copy();pose[:3,:3]=pose[:3,:3]@rotation
            return pose
        for name,pred in predicted.items():
            image=images[name];cam=cameras.get(image['camera'])
            if image['split']!='train'or cam is None or view_quality_reasons(image):continue
            if all(cam[f]['provenance']in('measured','calibrated')for f in('K','pose')):
                posed=observation_scene(scene,image,candidate.project.root,complete=False);actual=next(c for c in posed['cameras']if c['id']==image['camera'])
                relative.append(np.asarray(pred['T_relative_camera'])[:3,3]);metric.append(world_pose(posed,actual)[:3,3]);known.append(name)
        registration=None
        if len(known)>=3:
            fit=align_points(relative,metric,estimate_scale=True)
            if fit['status']=='ESTIMATED'and fit['rmse']<.02:registration={'scale':fit['scale'],'T_world_relative':fit['T_target_source'],'source':'calibrated camera baseline','evidence':known}
        motion=None;wrist_link=options.get('wrist_link')
        if registration is None and scene.get('robot_model'):
            model=scene['robot_model'];model_path=local_path(candidate.project.root,model['path'])
            if sha(model_path)!=model['model_sha256']:raise ValueError('Robot model changed during automatic camera initialization')
            wrist=[i for i in images.values()if i['id']in predicted and i['split']=='train'and camera_type(i)=='wrist'and not view_quality_reasons(i)]
            if wrist:
                camera=cameras.get(wrist[0]['camera'])
                if not wrist_link and camera and camera['frame'].startswith('robot_link_'):wrist_link=camera['frame'].removeprefix('robot_link_')
            if not wrist_link and len(wrist)>=4:
                fk_views=[link_transforms(model_path,dict(zip(i['joint_names'],i['q_measured'])))for i in wrist]
                hypotheses=[]
                for link in sorted(fk_views[0]):
                    candidate.project.checkpoint()
                    result=wrist_from_motion([f[link]for f in fk_views],[physical_pose(i)for i in wrist])
                    if result['status']=='OPTIMIZED':hypotheses.append((result['rmse'],link,result))
                if hypotheses:
                    hypotheses.sort(key=lambda item:item[0]);wrist_link=hypotheses[0][1]
                    # Links related by a constant rigid transform have equivalent
                    # mounts; report that gauge instead of claiming physical identity.
                    needs.append('Wrist attachment inferred from motion; equivalent fixed-link gauges: '+', '.join(h[1]for h in hypotheses if h[0]<hypotheses[0][0]+1e-5))
            if wrist_link:
                fk=[];poses=[]
                for image in wrist:
                    if image['joint_names']!=model['joint_names']or image.get('robot_model_sha256',model['model_sha256'])!=model['model_sha256']or image.get('mapping_sha256',model.get('mapping',{}).get('sha256'))!=model.get('mapping',{}).get('sha256'):raise ValueError('Measured wrist model/mapping identity differs')
                    fk.append(link_transforms(model_path,dict(zip(image['joint_names'],image['q_measured'])))[wrist_link]);poses.append(physical_pose(image))
                if fk:motion=wrist_from_motion(fk,poses)
                if motion and motion['status']=='OPTIMIZED':
                    if 'robot_base'not in scene['frames']:scene['frames']['robot_base']={'parent':'world','transform':value(np.eye(4).tolist(),'estimated',['explicit robot-base coordinate gauge; not measured World registration'])}
                    registration={'scale':motion['scale'],'T_world_relative':(frame_world(scene,'robot_base')@np.linalg.inv(motion['T_relative_base'])).tolist(),
                        'source':'measured-q metric hand-eye','evidence':[i['id']for i in wrist]}
                    frame='robot_link_'+wrist_link
                    if frame not in scene['frames']:scene['frames'][frame]={'parent':'robot_base','transform':value(fk[0].tolist(),'derived',['measured-q FK'])}
                    for image in wrist:
                        cam=cameras.get(image['camera'])
                        if cam is None:
                            cam={'id':image['camera'],'frame':frame,'pose':value(None),'K':value(None),'resolution':image['resolution'],'reference_orientation':image.get('exif_orientation',1),'distortion':value([0.]*5,'estimated',['DA3 pinhole hypothesis'])};scene['cameras'].append(cam);cameras[cam['id']]=cam
                        if cam['pose']['provenance']not in('measured','calibrated','optimized'):cam.update(frame=frame,pose=value(motion['T_link_camera'],'optimized',['measured-q hand-eye initialization']))
            elif wrist:needs.append('Wrist attachment/motion is unresolved; capture distinct rotations/translations while objects stay fixed')
        if registration is None and options.get('measurements'):
            from .calibration.registration import metric_plane
            from .inference import object_points
            for measure in options['measurements']:
                if measure.get('role')!='support_surface'or measure.get('kind')!='box'or not measure.get('evidence'):continue
                samples=[];centers=[];ids=[]
                for segment in inferred.get('segments',[]):
                    if segment['object_id']!=measure['id']or images[segment['image_id']]['split']!='train':continue
                    assigned=segment.get('association',{})
                    if assigned.get('status')!='ASSIGNED_ESTIMATED':continue
                    name=segment['image_id'];pred=predicted.get(name)
                    if not pred:continue
                    batch=next(b for b in inferred['depth_batches']if name in b['image_ids']);index=batch['image_ids'].index(name)
                    if sha(assigned['mask_path'])!=assigned['mask_sha256']:raise ValueError('Metric support mask changed')
                    with np.load(batch['path'],allow_pickle=False)as data:
                        from PIL import Image
                        mask=np.asarray(Image.open(assigned['mask_path']).convert('L'))>0
                        points,_=object_points(data['depth'][index],mask,data['intrinsics'][index],data['original_to_processed'][index],erode_px=0,max_points=10000)
                    pose=np.asarray(pred['T_relative_camera']);samples.append((points*pred['batch_scale'])@pose[:3,:3].T+pose[:3,3]);centers.append(pose[:3,3]);ids.append(name)
                if not samples:continue
                reference=next((o for o in scene['objects']if o['id']==measure['id']and o['pose']['provenance']in('measured','calibrated')),None)
                target=world_pose(scene,reference)if reference else None
                if target is not None:target[:3,3]+=target[:3,2]*measure['dimensions_m'][2]/2
                fit=metric_plane(np.concatenate(samples),measure['dimensions_m'],target_pose=target,camera_centers=centers)
                if fit['status']=='ESTIMATED':
                    registration={**fit,'evidence':measure['evidence']+ids}
                    support=next((o for o in scene['objects']if o['id']==measure['id']),None)
                    if support and support['pose']['value']is None:
                        pose=np.eye(4);pose[2,3]=-measure['dimensions_m'][2]/2
                        support['pose']=value(pose.tolist(),'estimated',['support-centered coordinate gauge from visible plane; not measured World pose'])
                    break
        if not registration:needs.append('Scale/World alignment unresolved: add overlapping views with distinct wrist motions or visible metric references; no manual matrix input required')
        registrations=scene.setdefault('view_registrations',{});rows=[]
        for name,pred in predicted.items():
            image=images[name];kind=camera_type(image);cam=cameras.get(image['camera'])
            if view_quality_reasons(image):needs.append(name+': original Capture quality exclusions retained');continue
            if cam is None:
                cam={'id':image['camera'],'frame':'world','pose':value(None),'K':value(None),'resolution':image['resolution'],
                    'reference_orientation':image.get('exif_orientation',1),'distortion':value([0.]*5,'estimated',['DA3 pinhole hypothesis; distortion not measured'])};scene['cameras'].append(cam);cameras[cam['id']]=cam
            from .cameras import camera_pixels
            try:pixel_affine,optical_rotation=camera_pixels(cam,image)
            except ValueError as error:needs.append(name+': '+str(error));continue
            if cam['K']['provenance']not in('measured','calibrated','optimized'):
                # Same physical lens shares K, fitted only from training views.
                source=[]
                for key,p in predicted.items():
                    if images[key]['camera']!=image['camera']or images[key]['split']!='train':continue
                    try:
                        affine,optical=camera_pixels(cam,images[key]);source.append((np.linalg.inv(affine)@np.asarray(p['K'])@optical).tolist())
                    except ValueError:continue
                if source:cam['K']=value(np.median(source,axis=0).tolist(),'estimated',['DA3 predicted intrinsics in original pixels'])
            if not registration:continue
            pose=np.asarray(pred['T_relative_camera']);pose[:3,3]*=registration['scale'];pose=np.asarray(registration['T_world_relative'])@pose
            if kind=='side':
                source=[]
                for key,p in predicted.items():
                    if images[key]['camera']==image['camera']and images[key]['split']=='train':
                        t=physical_pose(images[key]);t[:3,3]*=registration['scale'];source.append(np.asarray(registration['T_world_relative'])@t)
                if not source:continue
                fixed=source[0].copy();fixed[:3,3]=np.median([t[:3,3]for t in source],axis=0)
                from scipy.spatial.transform import Rotation
                fixed[:3,:3]=Rotation.from_matrix(np.array(source)[:,:3,:3]).mean().as_matrix()
                if cam['pose']['provenance']not in('measured','calibrated','optimized'):cam.update(frame='world',pose=value(fixed.tolist(),'estimated',['shared fixed camera DA3 initialization']))
            if kind=='wrist'and not cam['frame'].startswith('robot_link_'):
                needs.append(name+': shared Wrist mount is unresolved');continue
            previous=registrations.get(name)
            if previous and(previous['status']=='REGISTERED_CALIBRATED'or previous.get('state')=='OPTIMIZED'):continue
            registrations[name]={'image_id':name,'camera':image['camera'],'camera_type':kind,'scene_state_id':image['scene_state_id'],
                'source_image_sha256':image['sha256'],'image_record_sha256':_digest(image),'status':'REGISTERED_ESTIMATED',
                'T_world_camera':pose.tolist()if kind=='external'else None,'camera_signature':camera_calibration_signature(scene,cam),'pixel_from_camera':pixel_affine.tolist(),'optical_from_camera':optical_rotation.tolist(),
                'calibration_evidence':registration['evidence'],'depth_scale':registration['scale']*pred['batch_scale'],
                'depth_scale_source':registration,'metric_scale_verified':False,'state':'PREDICTED','physical_verified':False}
            rows.append(registrations[name])
        # Every registration must bind the final shared K, never a transient one.
        for name,binding in registrations.items():
            if name in images:binding['camera_signature']=camera_calibration_signature(scene,cameras[images[name]['camera']])
        scene['camera_predictions']={'views':predicted,'batch_alignment':alignment,'metric_alignment':registration,'motion':motion,'state':'PREDICTED'if registration else'UNRESOLVED'}
        if inferred.get('scene_state_id'):scene['reconstruction_state']={'id':inferred['scene_state_id'],'static_layout_verified':False}
        candidate.save(scene)
        return {'status':'PREDICTED'if rows else'UNRESOLVED','views':rows,'scene_state_id':inferred.get('scene_state_id'),'needs':list(dict.fromkeys(needs)),
            'physical_verified':False,'metric_alignment':registration,'motion':motion}


def annotation_evidence(project, scene):
    """Merge an approved Candidate layer for readers; leave input/evidence.yaml intact."""
    result = copy.deepcopy(project.evidence)
    layer = scene.get('derived_observations', {})
    images = {i.get('id'): i for i in result['images'] if i.get('id')}
    for row in layer.get('sources', []):
        image = images.get(row['image_id'])
        if image is None or image['sha256'] != row['source_image_sha256']:
            raise ValueError('Approved observation source identity changed')
        if (image.get('scene_state_id') != row['scene_state_id']
                or _digest(image) != row['image_record_sha256']
                or sha(local_path(project.root, image['path'])) != image['sha256']):
            raise ValueError('Approved observation layout/image changed')
    for row in layer.get('masks', []):
        if sha(local_path(project.root, row['path'])) != row['sha256']:
            raise ValueError('Approved mask changed')
    for kind in ('landmarks', 'masks'):
        result.setdefault(kind, []).extend(copy.deepcopy(layer.get(kind, [])))
    if scene.get('view_registrations'):
        registered,_,_=registered_images(project,scene=scene)
        active={i['id']:i for i in registered}
        result['images']=[active.get(i.get('id'),i)for i in result['images']]
    return result


def _patterns(gray, config):
    if not config:
        return []
    aruco = getattr(cv2, 'aruco', None)
    if aruco is None:
        return []
    dictionary = aruco.getPredefinedDictionary(getattr(aruco, config['dictionary']))
    if config['type'] == 'aruco':
        corners, ids, _ = aruco.ArucoDetector(dictionary).detectMarkers(gray)
        return [] if ids is None else [(f'aruco_{int(n)}_corner_{j}', p.tolist(),
                                        config.get('object_ids', {}).get(str(int(n))))
                                       for points, n in zip(corners, ids.ravel())
                                       for j, p in enumerate(points.reshape(-1, 2))]
    if config['type'] == 'charuco':
        board = aruco.CharucoBoard(tuple(config['squares']), config['square_length_m'],
                                  config['marker_length_m'], dictionary)
        corners, ids, _, _ = aruco.CharucoDetector(board).detectBoard(gray)
        return [] if ids is None else [(f'charuco_corner_{int(n)}', p.tolist(), config.get('object_id'))
                                       for p, n in zip(corners.reshape(-1, 2), ids.ravel())]
    raise ValueError('Pattern must explicitly be aruco or charuco')


def _image_proposals(rgb, scene, options):
    """Color components and rim/quad suggestions carry hints, not semantic certainty."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    rows = []
    for obj in scene['objects']:
        if obj['role'] not in ('manipulable_object', 'receptacle', 'workspace', 'reference_robot'):
            continue
        spec = options.get('objects', {}).get(obj['id'], {})
        roi = np.zeros(rgb.shape[:2], np.uint8)
        x, y, w, h = spec.get('roi_xywh', [0, 0, rgb.shape[1], rgb.shape[0]])
        if not (0 <= x < x + w <= rgb.shape[1] and 0 <= y < y + h <= rgb.shape[0]):
            raise ValueError('ROI must be inside the original image')
        roi[y:y+h, x:x+w] = 1
        color = obj.get('color', {}).get('value')
        if color is not None:
            sample = np.uint8(np.clip(np.array(color) * 255, 0, 255)).reshape(1, 1, 3)
            hue, saturation, _ = cv2.cvtColor(sample, cv2.COLOR_RGB2HSV)[0, 0]
            if saturation > 50:
                delta = abs(hsv[:, :, 0].astype(int) - int(hue))
                mask = ((np.minimum(delta, 180-delta) <= spec.get('hue_radius', 12))
                        & (hsv[:, :, 1] > 50) & (hsv[:, :, 2] > 35) & (roi > 0)).astype('uint8')
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
                count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
                indices = sorted(range(1, count), key=lambda i: int(stats[i, 4]), reverse=True)
                for index in indices[:options.get('max_components', 3)]:
                    if stats[index, 4] < options.get('min_area_px', 50):
                        continue
                    component = np.uint8(labels == index)
                    contour, _ = cv2.findContours(component, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    contour = max(contour, key=cv2.contourArea)
                    quad = cv2.approxPolyDP(contour, .025 * cv2.arcLength(contour, True), True)
                    rows.append({'object_hint': obj['id'], 'feature_id': 'visible_color_component',
                                 'mask': component, 'mask_kind': 'silhouette',
                                 'bbox_xywh': stats[index, :4].tolist(), 'detector': 'hsv_component',
                                 'confidence': .5, 'corner_candidates_px': quad[:, 0].tolist()
                                 if len(quad) == 4 else [], 'corner_order_verified': False})
        if obj['role'] not in ('receptacle', 'workspace'):
            continue
        edges = cv2.Canny(rgb, 70, 160) * roi
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:options.get('max_components', 3)]:
            if cv2.contourArea(contour) < options.get('min_area_px', 50):
                continue
            if obj['role'] == 'receptacle' and len(contour) >= 12:
                ellipse = cv2.fitEllipse(contour)
                mask = np.zeros(rgb.shape[:2], np.uint8)
                cv2.ellipse(mask, ellipse, 1, 2)
                mask *= roi
                rows.append({'object_hint': obj['id'], 'feature_id': 'rim_candidate', 'mask': mask,
                             'mask_kind': 'visible_rim', 'ellipse': ellipse, 'detector': 'edge_ellipse',
                             'confidence': .3, 'inspection_only': True})
            elif obj['role'] == 'workspace':
                quad = cv2.approxPolyDP(contour, .02 * cv2.arcLength(contour, True), True)
                if len(quad) == 4:
                    rows.append({'object_hint': obj['id'], 'feature_id': 'paper_quad_candidate',
                                 'corner_candidates_px': quad[:, 0].tolist(), 'detector': 'edge_quad',
                                 'confidence': .3, 'corner_order_verified': False, 'inspection_only': True})
    return rows


def propose_observations(project, *, scene_state=None, options=None, candidate=None):
    from .candidate import Candidate, exclusive
    options = copy.deepcopy(options or {})
    name = candidate or 'auto_observations'
    identifier(name)
    c = Candidate(project, name) if (project.root/'scratch/agent'/name/'candidate.json').exists() else Candidate.create(project, name)
    with exclusive(project):
        c.require_open()
        images, state, needs = registered_images(project, scene_state,scene=c.scene)
        scene = c.scene
        payload = {'images': images, 'options': options, 'scene': _scene_digest(scene), 'scene_state_id': state}
        digest = _digest(payload)
        folder = c.root/'observations'/digest[:20]
        path = folder/'proposals.json'
        if path.exists():
            return read(path)
        proposals = []
        for image in images:
            rgb = np.asarray(Image.open(local_path(project.root, image['path'])).convert('RGB'))
            if list(rgb.shape[1::-1]) != image['resolution']:
                raise ValueError('Image resolution changed')
            preview = Image.fromarray(rgb)
            draw = ImageDraw.Draw(preview)
            image_options = copy.deepcopy(options)
            image_options['objects'] = {**options.get('objects', {}),
                                        **options.get('images', {}).get(image['id'], {}).get('objects', {})}
            raw = _image_proposals(rgb, scene, image_options)
            corners = []
            for row in raw:
                for index, uv in enumerate(row.get('corner_candidates_px', [])):
                    corners.append({'object_hint': row['object_hint'], 'feature_id': row['feature_id']+f'_corner_{index}',
                                    'uv_px': uv, 'detector': row['detector'], 'confidence': row['confidence'],
                                    'corner_order_verified': False})
            raw.extend(corners)
            pattern = options.get('pattern')
            if pattern and getattr(cv2, 'aruco', None) is None:
                needs.append('OpenCV aruco module unavailable; no pattern detector was run')
            raw.extend({'feature_id': feature, 'uv_px': uv, 'object_hint': hint,
                        'detector': pattern['type'], 'confidence': .9}
                       for feature, uv, hint in _patterns(cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY), pattern))
            for index, row in enumerate(raw):
                key = hashlib.sha256(f"{digest}:{image['id']}:{index}".encode()).hexdigest()[:24]
                mask = row.pop('mask', None)
                row.update(id=key, image_id=image['id'], scene_state_id=state, camera=image['camera'],
                           object_id=None, occluded=None, source_image_sha256=image['sha256'],
                           image_record_sha256=source_record_digest(image),
                           provenance='derived', correspondence_verified=False)
                if mask is not None:
                    target = folder/(key+'.png')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(mask*255).save(target)
                    row.update(mask_path=target.relative_to(project.root).as_posix(), mask_sha256=sha(target))
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for contour in contours:
                        points = [tuple(map(int, p)) for p in contour[:, 0]]
                        if len(points) > 1:
                            draw.line(points+[points[0]], fill='red', width=2)
                            draw.text(points[0], key[:8], fill='red')
                if row.get('corner_candidates_px'):
                    points = [tuple(p) for p in row['corner_candidates_px']]
                    draw.line(points+[points[0]], fill='orange', width=2)
                if row.get('bbox_xywh'):
                    x, y, w, h = row['bbox_xywh']
                    draw.rectangle((x, y, x+w, y+h), outline='red', width=2)
                    draw.text((x, y), key[:8], fill='red')
                if row.get('uv_px'):
                    x, y = row['uv_px']
                    draw.ellipse((x-3, y-3, x+3, y+3), fill='red')
                proposals.append(row)
            folder.mkdir(parents=True, exist_ok=True)
            preview.save(folder/(hashlib.sha256(image['id'].encode()).hexdigest()[:20]+'_preview.png'))
        report = {'schema': 'real2sim.observation-proposals/1', 'candidate': name,
                  'scene_state_id': state, 'project_id': project.info['id'], 'input_digest': digest,
                  'scene_sha256': _scene_digest(scene),
                  'proposal_file': path.relative_to(project.root).as_posix(), 'proposals': proposals,
                  'needs': needs or ([] if proposals else ['No reliable feature proposed; retain the Scene draft']),
                  'status': 'PROPOSED' if proposals else 'NEEDS_MORE_DATA', 'physical_verified': False}
        write(path, report)
        return report


def commit_observation_proposals(project, proposal_file, *, selections=None):
    """Codex explicitly binds proposal IDs to objects/CAD points, not a user checklist."""
    from .candidate import Candidate, exclusive
    path = Path(proposal_file)
    path = local_path(project.root, path.relative_to(project.root).as_posix()) if path.is_absolute() else local_path(project.root, str(path))
    proposal = read(path)
    if proposal.get('schema') != 'real2sim.observation-proposals/1' or proposal.get('project_id') != project.info['id']:
        raise ValueError('Proposal belongs to another Project/schema')
    c = Candidate(project, proposal['candidate'])
    if not path.is_relative_to(c.root/'observations') or selections is None:
        raise ValueError('Candidate-local proposal and explicit Codex selections are required')
    with exclusive(project):
        c.require_open()
        scene = c.scene
        if _scene_digest(scene) != proposal['scene_sha256']:
            raise ValueError('Candidate geometry changed; generate proposals again')
        objects = {o['id']: o for o in scene['objects']}
        images, state, _ = registered_images(project, proposal['scene_state_id'],scene=scene)
        images = {i['id']: i for i in images}
        proposals = {r['id']: r for r in proposal['proposals']}
        layer = copy.deepcopy(scene.get('derived_observations', {'landmarks': [], 'masks': [], 'sources': []}))
        if any(s['scene_state_id'] != state for s in layer['sources']):
            raise ValueError('Use a separate Candidate for a different static layout')
        for selection in selections:
            row = proposals[selection['proposal_id']]
            image = images[row['image_id']]
            if image['sha256'] != row['source_image_sha256'] or source_record_digest(image) != row['image_record_sha256']:
                raise ValueError('Proposal image changed')
            object_id = selection.get('object_id')
            if object_id not in objects:
                raise ValueError('Codex must identify an existing object explicitly')
            common = {'proposal_id': row['id'], 'observation': image['id'], 'object': object_id,
                      'camera': image['camera'], 'split': image['split'], 'scene_state_id': state,
                      'provenance': 'derived', 'source_image_sha256': image['sha256'],
                      'confidence': row['confidence'], 'occluded': selection.get('occluded', row['occluded']),
                      'detector': row['detector'], 'physical_verified': False}
            common['feature_id'] = row['feature_id']
            uv = selection.get('uv_px', row.get('uv_px'))
            point = {k: selection[k] for k in ('point_m', 'point_fraction') if k in selection}
            if point:
                if len(point) != 1 or uv is None or selection.get('correspondence_verified') is not True:
                    raise ValueError('A visible CAD-to-pixel correspondence must be explicitly reviewed')
                if np.asarray(uv).shape != (2,) or not np.isfinite(uv).all() or not (0 <= uv[0] < image['resolution'][0] and 0 <= uv[1] < image['resolution'][1]):
                    raise ValueError('Pixel must be finite and inside the original image')
                coordinates = np.asarray(next(iter(point.values())), float)
                if coordinates.shape != (3,) or not np.isfinite(coordinates).all():
                    raise ValueError('CAD point must contain three finite coordinates')
                if 'point_fraction' in point and objects[object_id]['dimensions']['value'] is None:
                    raise ValueError('Initialize CAD dimensions before binding a fractional point')
                sigma = float(selection.get('sigma_px', 3))
                if not np.isfinite(sigma) or sigma <= 0:
                    raise ValueError('Pixel uncertainty must be finite and positive')
                record = {**common, **point, 'uv': list(uv), 'visible': common['occluded'] is not True,
                          'sigma_px': sigma, 'weight': 1.}
                kind = 'landmarks'
            elif row.get('mask_path'):
                mask = local_path(project.root, row['mask_path'])
                if not mask.is_relative_to(c.root/'observations') or sha(mask) != row['mask_sha256']:
                    raise ValueError('Proposal mask changed or is outside this Candidate')
                record = {**common, 'image': image['path'], 'path': row['mask_path'],
                          'sha256': row['mask_sha256'], 'mask_kind': row['mask_kind']}
                if record['mask_kind'] == 'silhouette' and common['occluded'] is not False:
                    record['mask_kind'] = 'visible_fragment'
                kind = 'masks'
            else:
                raise ValueError('Inspection-only corners need an explicit uv_px and CAD point')
            def same_feature(existing):
                if existing.get('proposal_id') == row['id']:
                    return True
                if existing['observation'] != image['id'] or existing['object'] != object_id:
                    return False
                if kind == 'masks':
                    return existing.get('mask_kind') == record.get('mask_kind')
                return any(k in record and existing.get(k) == record[k] for k in ('point_m', 'point_fraction'))
            layer[kind] = [r for r in layer[kind] if not same_feature(r)]+[record]
            source = {'image_id': image['id'], 'scene_state_id': state, 'source_image_sha256': image['sha256'],
                      'image_record_sha256': source_record_digest(image)}
            if source not in layer['sources']:
                layer['sources'].append(source)
        scene['derived_observations'] = layer
        c.save(scene)
        return {'status': 'COMMITTED_DERIVED', 'candidate': c.name,
                'landmarks': len(layer['landmarks']), 'masks': len(layer['masks']), 'physical_verified': False}
