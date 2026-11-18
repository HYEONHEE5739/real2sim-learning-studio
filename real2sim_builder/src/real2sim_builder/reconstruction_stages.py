"""Stage processing for the existing automation.reconstruct entrypoint.

Algorithms/data processing live here; Project locks, control, artifact publication
and resumption stay in automation. Heavy dependencies cross stage_runtime only.
"""
from pathlib import Path
import copy
import json
import numpy as np
from .files import read, write, sha
from .stage_artifacts import StageNeeds, digest as stage_digest
from .calibration.simfoundry import backproject, world_points, plan_chunks, merge_chunks, support_transform, metric_qa


def typed_record(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def instance_schema(*,initial=False):
    fields={k:{'type':'string'}for k in ('id','prompt','role','category','description','uncertainty')}
    fields['box_xyxy']={'type':'array','items':{'type':'number'},'minItems':4,'maxItems':4}
    fields['support']={'type':['string','null']}
    fields['relations']={'type':'array','items':{'type':'string'}}
    fields['assessment']=typed_record({
        'identity':{'type':'string','enum':['IDENTIFIED','AMBIGUOUS']},
        'box':{'type':'string','enum':['ASSOCIATED','AMBIGUOUS']},
        'memo':{'type':'string','enum':['CONSISTENT','CONFLICT','UNKNOWN']},
        'uncertainties':{'type':'array','items':{'type':'string','enum':['HIDDEN_GEOMETRY','UNMEASURED_DIMENSIONS','FRONT','IDENTITY','BOX','MEMO','REMOVAL_QUALITY']}}})
    props={'objects':{'type':'array','items':typed_record(fields)},'memo_consistent':{'type':'boolean'},
        'uncertain':{'type':'boolean'},'evidence':{'type':'array','items':{'type':'string'},'minItems':1}}
    if initial:
        from .authoring import scene_analysis_schema
        props['scene_analysis']=scene_analysis_schema()
    return typed_record(props)


def instance_gate(answer, input_sha256):
    """Typed uncertainty only; never interpret free-form uncertainty text."""
    if answer.get('memo_consistent')is False:
        raise StageNeeds('NEEDS_REVIEW','Scene Memo conflicts with observed layout',code='MEMO_CONFLICT',classification='OBJECT_REVIEW',input_sha256=input_sha256)
    outcomes=[]
    for obj in answer['objects']:
        assessment=obj.get('assessment')
        if assessment is not None:
            from .codex_cli import validate_answer
            validate_answer(assessment,instance_schema()['properties']['objects']['items']['properties']['assessment'])
            safe=(assessment['identity']=='IDENTIFIED'and assessment['box']=='ASSOCIATED'and assessment['memo']!='CONFLICT'
                  and not set(assessment['uncertainties'])-{'HIDDEN_GEOMETRY','UNMEASURED_DIMENSIONS','FRONT'})
        else:safe=not answer.get('uncertain',False)  # Old unscoped uncertainty stays blocked.
        if not safe:
            raise StageNeeds('NEEDS_REVIEW','Unresolved Instance identity/Box/Memo: '+obj['id'],code='INSTANCE_ASSOCIATION',
                classification='OBJECT_REVIEW',scope='object',object_ids=[obj['id']],input_sha256=input_sha256)
        if assessment and assessment['uncertainties']:
            outcomes.append({'classification':'ESTIMATED_CONTINUE','scope':'object','object_ids':[obj['id']],
                'reasons':assessment['uncertainties'],'input_sha256':input_sha256,'physical_verified':False})
    if answer.get('uncertain')and not answer['objects']:
        raise StageNeeds('NEEDS_REVIEW','Uncertain empty scene is not termination evidence',code='UNCERTAIN_TERMINATION',classification='OBJECT_REVIEW',input_sha256=input_sha256)
    return outcomes


def pose_point_selection(arrays, options):
    """Observed RGB with original model-estimated Z is the default CPD input."""
    mask=np.asarray(arrays['mask'],bool);points=np.asarray(arrays['camera_points'])
    if points.shape!=(int(mask.sum()),3)or not np.isfinite(points).all():raise ValueError('Point/pixel provenance mismatch')
    fields=('rgb_source','depth_source','low_confidence')
    if not all(k in arrays for k in fields):
        raise StageNeeds('NEEDS_REVIEW','Point provenance NOT_RECORDED; regenerate Stage5 artifact',code='POINT_PROVENANCE',classification='OBJECT_REVIEW')
    maps=[np.asarray(arrays[k])for k in fields]
    if any(m.shape!=mask.shape for m in maps)or any(not np.isin(m,[0,1]).all()for m in maps):raise ValueError('Invalid provenance pixel grid/labels')
    generated=(maps[0].astype(bool)|maps[1].astype(bool))[mask];low=maps[2].astype(bool)[mask]
    policy=options.get('point_policy','original_only')
    if policy not in ('original_only','include_generated'):raise ValueError('Unknown CPD point provenance policy')
    if policy=='include_generated'and not options.get('generated_evidence'):raise ValueError('Generated CPD input requires explicit sensitivity evidence')
    keep=~low if policy=='include_generated'else~(generated|low)
    return points[keep],{'policy':policy,'selected_points':int(keep.sum()),'original_points':int((~(generated|low)).sum()),
        'generated_points':int(generated.sum()),'low_confidence_points':int(low.sum()),
        'sensitivity_required':policy=='include_generated','confidence_calibrated':False,
        'depth_provenance':'model-estimated optical Z, never measured','independent_accuracy':False}


def prepare(candidate, config, previous, folder, provider):
    from PIL import Image, ImageOps, ImageDraw
    project = candidate.project
    state = config.get('scene_state_id')
    images = [i for i in project.evidence['images']
              if i.get('role') == 'scene_photo' and i.get('camera_type') == 'external'
              and not i.get('runtime_baseline') and i.get('split', 'train') == 'train']
    videos = [v for v in project.evidence.get('videos', []) if v.get('role') == 'scene_video']
    layouts = {i.get('scene_state_id') for i in images+videos}
    if state is None and len(layouts) != 1:
        raise StageNeeds('NEEDS_MORE_DATA', 'Select one explicitly identified static photo/video layout')
    state = state if state is not None else next(iter(layouts))
    images = [i for i in images if i.get('scene_state_id') == state]
    videos = [v for v in videos if v.get('scene_state_id') == state]
    frames = []
    for index, image in enumerate(images):
        project.checkpoint()
        source = project.root/image['path']
        if sha(source) != image['sha256']:
            raise ValueError('Scene Photo source SHA changed')
        target = folder/f'photo_{index:04d}.png'
        with Image.open(source) as im:
            ImageOps.exif_transpose(im).convert('RGB').save(target)
        with Image.open(target) as im:size = list(im.size)
        frames.append({'id': image['id'], 'path': str(target), 'sha256': sha(target),
                       'source': image['path'], 'source_sha256': image['sha256'],
                       'source_camera': image['camera'], 'scene_state_id': state,
                       'frame_index': None, 'timestamp': image.get('timestamp'),
                       'resolution': size, 'role': 'scene_photo'})
    for video in videos:
        result = provider('video', {'video': str(project.root/video['path']),
                                    'source_sha256': video['sha256'],
                                    'candidates': config.get('video_candidates', 15)}, folder/'video'/video['sha256'])
        for frame in result['frames']:
            frames.append({**frame, 'source': video['path'], 'source_sha256': video['sha256'],
                           'source_camera': None, 'scene_state_id': state, 'role': 'scene_video_frame'})
    if not frames:
        raise StageNeeds('NEEDS_MORE_DATA', 'No eligible external Scene Photos/Video in this layout')
    canvas = Image.new('RGB', (320*4, 264*((len(frames)+3)//4)), '#15202b')
    draw = ImageDraw.Draw(canvas)
    for i, frame in enumerate(frames):
        with Image.open(frame['path']) as im:im = ImageOps.contain(im.convert('RGB'), (320, 240))
        x, y = (i % 4)*320, (i//4)*264
        canvas.paste(im, (x, y+24));draw.text((x+5, y+5), str(i)+': '+frame['id'], fill='white')
    canvas.save(folder/'contact_sheet.png')
    return {'frames': frames, 'scene_state_id': state, 'candidate_count': len(frames),
            'coordinate_frame': 'original EXIF-upright RGB pixels'}


def depth(candidate, config, previous, folder, provider):
    frames = previous[1]['frames']
    setting = config.get('depth', {})
    res = setting.get('process_res', 336)
    if type(res) is not int or res not in (336, 448):
        raise ValueError('Measured DA3 resolution 336 or 448 required')
    batch = setting.get('batch_size', 4)
    if type(batch) is not int or not 1 <= batch <= (4 if res == 448 else 8):
        raise ValueError('Unmeasured concurrent DA3 batch size')
    starts, sizes = plan_chunks(len(frames), batch, setting.get('overlap', 3))
    chunks, metadata, transforms = [], [], [None]*len(frames)
    for i, (start, count) in enumerate(zip(starts, sizes)):
        candidate.project.checkpoint()
        result = provider('da3', {'images': [f['path'] for f in frames[start:start+count]],
                                  'frame_ids': [f['id'] for f in frames[start:start+count]],
                                  'process_res': res}, folder/f'chunk_{i:03d}')
        with np.load(result['path'], allow_pickle=False) as arrays:
            chunk = {k: arrays[k] for k in ('depth', 'conf', 'intrinsics', 'extrinsics', 'image')}
        n, h, w = chunk['depth'].shape
        if n != count or chunk['conf'].shape != (n,h,w) or chunk['image'].shape != (n,h,w,3):
            raise ValueError('DA3 frame/Depth/Confidence/RGB contract mismatch')
        if chunk['intrinsics'].shape != (n,3,3) or chunk['extrinsics'].shape != (n,3,4):
            raise ValueError('DA3 K/World-to-Camera contract mismatch')
        for j in range(n):world_points(chunk['depth'][j], chunk['intrinsics'][j], chunk['extrinsics'][j])
        if not np.isfinite(chunk['conf']).all():raise ValueError('Nonfinite DA3 Confidence')
        affines=np.asarray(result.get('original_to_processed'),float)
        if affines.shape!=(count,3,3)or not np.isfinite(affines).all()or any(abs(np.linalg.det(A))<1e-12 or not np.allclose(A[2],[0,0,1])for A in affines):
            raise ValueError('DA3 requires explicit original-to-processed pixel affine per frame')
        if chunks and chunks[0]['depth'].shape[1:]!=chunk['depth'].shape[1:]:
            raise StageNeeds('NEEDS_MORE_DATA','DA3 chunks produced different batch crop grids; do not silently resize or combine Depth/K')
        for j,A in enumerate(affines):
            if transforms[start+j]is None:transforms[start+j]=A.tolist()
        chunks.append(chunk);metadata.append(result)
    try:merged, alignment = merge_chunks(chunks, starts, sizes, len(frames))
    except ValueError as error:raise StageNeeds('NEEDS_MORE_DATA', str(error)) from error
    path = folder/'prediction.npz';np.savez_compressed(path, **merged)
    h, w = merged['depth'].shape[1:]
    return {'prediction': str(path), 'frames': frames, 'processed_resolution': [w,h],
            'original_to_processed': transforms, 'chunks': metadata, 'alignment': alignment,
            'is_metric': all(row.get('is_metric') == 1 for row in metadata),
            'metric_verified': False, 'coordinate_frame': 'DA3 world; optical World-to-Camera poses',
            'depth_units': 'model_estimated_m', 'precision_policy': 'nested-bf16-backbones-fp32-heads/1'}


def semantic_preview(candidate, config, previous, folder, provider):
    """Reuse the existing typed analysis and SAM boundary before Stage3 gates.

    The full Memo plan includes unobserved/context entities. A Mask association
    is pixel evidence, not a physical identity or measurement certificate.
    """
    from PIL import Image
    from . import authoring
    from .evidence import scene_memo
    from .codex_cli import validate_answer
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    frames=previous[1]['frames'];memo=scene_memo(candidate.project)
    references=[{**r,'path':str(candidate.project.root/r['path'])}for r in candidate.project.evidence['images']if r.get('role')=='model_reference']
    records=frames+references
    for row in records:
        if sha(row['path'])!=row['sha256']:raise ValueError('Semantic source RGB SHA changed')
    guidance=authoring._codex_guidance()[1]
    links=[f.removeprefix('robot_link_')for f in candidate.scene.get('frames',{})if f.startswith('robot_link_')]
    import os
    identity={'memo_sha256':memo['sha256'],'guide_sha256':guidance['sha256'],
              'images':[{k:r.get(k)for k in ('id','sha256','role','resolution')}for r in records],
              'prediction_sha256':sha(previous[2]['prediction']),
              'original_to_processed':previous[2].get('original_to_processed'),
              'model':os.environ.get('REAL2SIM_CODEX_MODEL'),'effort':os.environ.get('REAL2SIM_CODEX_EFFORT'),
              'objects':copy.deepcopy(config.get('objects',{})),'robot_links':links,
              'runtime_settings':{k:config.get('runtimes',{}).get(k,{})for k in ('vlm','sam3','decomposition')}}
    if candidate.scene.get('robot_rig'):identity['robot_rig']=copy.deepcopy(candidate.scene['robot_rig'])
    cache=folder/'semantic-preview.json'
    if cache.is_file():
        saved=read(cache)
        if saved['identity']!=identity:raise ValueError('Semantic preview input identity changed; use a new stage attempt')
        analysis=saved['scene_analysis']
        if sha(analysis['path'])!=analysis['sha256']:raise ValueError('Semantic analysis SHA changed')
        for frame in saved['frames']:
            for row in frame['associations']:
                if row.get('mask')and sha(row['mask'])!=row['mask_sha256']:raise ValueError('Semantic Mask SHA identity changed')
        return saved
    request={'task':'scene_semantic_preview','images':[r['path']for r in records],
        'response_schema':authoring.scene_analysis_schema(),
        'context':{'memo':memo,'images':[{'image_index':i+1,**{k:r.get(k)for k in ('id','role','resolution','sha256','scene_state_id')}}for i,r in enumerate(records)],
                   'namespaces':authoring.semantic_namespaces(records,config.get('objects',{}),links),
                   'robot_links':links,'existing_measurements':config.get('objects',{}),
                   'robot_rig':candidate.scene.get('robot_rig')},
        'prompt':'Interpret the exact Scene Memo and attached Scene Photos/Model References using guide section2. '
            'Return all Memo entities, distinct observed instances, roles, literal measurements, relationships and unresolved needs. '
            'Give each visible scene_photo observation a tight original-upright pixel box and positive surface point. '
            'Keep reference_robot/support/background/fixtures separate from manipulation targets. Model References are appearance links, '
            'not extra Scene instances. Keep absent entities unresolved with empty observations. Never invent a Robot Link/Calibration; '
            'robot_attachment must be null if robot_links is empty. capture_layouts may refer ONLY to namespaces.capture_layout_ids; '
            'Photo/Reference layout IDs are not Capture layouts. If no Capture layout IDs are allowed, return capture_layouts=[]. '
            'A selected robot_rig is reusable hardware: keep its Camera Assembly components as fixture evidence, '
            'use the exact registered assembly asset_id as the semantic assembly ID, and never request a second Robot or sensor. '
            'This is a semantic preview, not complete reconstruction.'}
    answer=provider('vlm',request,folder/'vlm')['answer'];validate_answer(answer,request['response_schema'])
    validated=authoring.parse_visual_scene_analysis(answer,memo,{r['id']for r in records},image_records=records,robot_links=links)
    parsed=validated['objects'];raw_objects={r['id']:r for r in answer['objects']}
    for name,spec in parsed.items():
        protected=config.get('objects',{}).get(name,{}).get('geometry')
        if protected and protected.get('provenance')in('measured','calibrated'):
            proposed=spec.get('geometry',{}).get('dimensions_m',[None]*3)
            if any(a is not None and b is not None and not np.isclose(a,b,rtol=1e-9,atol=1e-12)for a,b in zip(protected['dimensions_m'],proposed)):
                raise StageNeeds('NEEDS_REVIEW','Semantic preview conflicts with protected dimensions: '+name)
            spec['geometry']=copy.deepcopy(protected)
    scene_ids={r['id']for r in frames}
    if any(set(spec.get('images',{}))-scene_ids for spec in parsed.values()):raise ValueError('Model Reference cannot be a Scene observation')
    analysis_path=folder/'scene_analysis.json';write(analysis_path,answer)
    analysis={'path':str(analysis_path),'sha256':sha(analysis_path),'memo_sha256':memo['sha256'],
              'guidance_sha256':guidance['sha256'],'source_images':records,
              'validation':validated['validation'],'deferred_constraints':validated['deferred']}
    with np.load(previous[2]['prediction'])as arrays:images=arrays['image']
    output=[]
    for index,(frame,image)in enumerate(zip(frames,images)):
        sub=folder/f'frame_{index:03d}';sub.mkdir(exist_ok=True)
        image_path=sub/'processed.png';Image.fromarray(image).save(image_path);h,w=image.shape[:2]
        affines=previous[2].get('original_to_processed')
        affine=np.asarray(affines[index]if affines else np.eye(3),float)
        if not affines and frame['resolution']!=[w,h]:raise ValueError('Semantic pixel affine is required')
        proposals=[];associations=[]
        for name,spec in parsed.items():
            hint=spec.get('images',{}).get(frame['id'],{});box=hint.get('box_xyxy')
            if box is None:continue
            a,b,c,d=map(float,box);corners=np.array([[a,b,1],[c,b,1],[c,d,1],[a,d,1]])@affine.T
            lower=corners[:,:2].min(0);upper=corners[:,:2].max(0)
            clipped=np.r_[np.maximum(lower,[0,0]),np.minimum(upper,[w,h])]
            row={'id':name,'role':spec['role'],'category':spec['category'],'box_original':box,
                 'box_xyxy':clipped.tolist(),'box_truncated_by_processing':bool(np.any(lower<0)or np.any(upper>[w,h])),
                 'status':'OUTSIDE_PROCESSED_GRID','mask':None,'confidence':None,
                 'identity_verified':False,'semantic_source_sha256':analysis['sha256']}
            associations.append(row)
            if np.any(clipped[2:]<=clipped[:2]):continue
            raw_geometry=raw_objects[name].get('geometry')or{}
            # Do not run a separate segmentation for every tiny camera part or
            # unrelated background item merely to choose a canonical frame.
            # Their original Boxes/unknowns remain in the complete semantic plan.
            if spec['role']not in ('manipulable_object','receptacle','workspace','reference_robot')and not(
                    spec['role']=='background'and raw_geometry.get('source')=='user_memo'):
                row['status']='BOX_ONLY_NOT_SEGMENTED';continue
            proposals.append({'id':name,'prompt':spec['prompt'],'category':spec['category'].replace('_',' '),
                              'role':spec['role'],'box_xyxy':clipped.tolist()})
        if proposals:
            result=provider('segments',{'image':str(image_path),'objects':proposals,'association_policy':'semantic_preview'},sub/'sam3')
            by_id={r['id']:r for r in result['objects']}
            if set(by_id)!={r['id']for r in proposals}:raise ValueError('Semantic/SAM Object ID mismatch')
            for row in associations:
                if row['id']not in by_id:continue
                observed=by_id[row['id']];row['status']=observed['status'];row['sam_provenance']=result.get('sam_provenance')
                row['confidence']=observed.get('confidence')
                if observed.get('path'):
                    path=Path(observed['path']);mask=np.asarray(Image.open(path).convert('L'))>0
                    if mask.shape!=(h,w)or not mask.any():raise ValueError('Semantic/SAM Mask pixel grid mismatch')
                    row.update(mask=str(path),mask_sha256=sha(path))
        output.append({'frame_id':frame['id'],'rgb_sha256':frame['sha256'],'processed_rgb':str(image_path),
                       'processed_rgb_sha256':sha(image_path),'original_to_processed':affine.tolist(),'associations':associations})
    result={'schema':'scene-semantic-preview/1','identity':identity,'scene_analysis':analysis,
            'objects':parsed,'frames':output,'physical_identity_verified':False}
    write(cache,result);return result


def support(candidate, config, previous, folder, provider):
    import cv2
    from dataclasses import asdict
    from .calibration.frame_selection import DEFAULT_SELECTION_CFG, FrameScore, rank_frames, _object_mask_above_plane, _sharpness
    data = previous[2]
    response = provider('support', {'prediction': data['prediction'],
                                    'categories': config.get('support', {}).get('categories', ['table','floor'])}, folder/'sam3')
    with np.load(data['prediction']) as arrays:
        depth, K, rgb = arrays['depth'], arrays['intrinsics'], arrays['image']
    with np.load(response['path']) as arrays:masks = arrays['masks']
    if masks.shape != depth.shape or len(response['planes']) != len(depth):
        raise ValueError('Support artifact pixel/frame mismatch')
    settings = {**DEFAULT_SELECTION_CFG, 'max_tilt': .125,
                **config.get('support', {}).get('frame_selection', {})}
    scores = [];object_masks={}
    def visibility(row,mask):
        n,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype('uint8'),8)
        kept=[j for j in range(1,n)if stats[j,cv2.CC_STAT_AREA]>=settings['min_component_px']]
        area=sum(int(stats[j,cv2.CC_STAT_AREA])for j in kept)
        edge=set(labels[0])|set(labels[-1])|set(labels[:,0])|set(labels[:,-1])
        row.n_objects=len(kept);row.object_coverage=area/mask.size
        row.clipped_frac=sum(int(stats[j,cv2.CC_STAT_AREA])for j in kept if j in edge)/max(area,1)
        return bool(kept)
    def plane_ok(row):
        return (row.floor_category is not None and row.tilt<=settings['max_tilt']and
                row.plane_inlier_ratio>=settings['min_plane_inlier_ratio']and
                row.support_coverage>=settings['min_support_coverage'])
    for i, (z,k,image,mask,record) in enumerate(zip(depth,K,rgb,masks,response['planes'])):
        row = FrameScore(idx=i)
        if not record.get('eligible'):
            row.eligible=False;row.reject_reason=record.get('reason','No support');row.tilt=0;scores.append(row);continue
        coeff = np.asarray(record['selection']['coefficients']);indices = record['selection']['inliers']
        points = backproject(z,k).reshape(-1,3);support_points = points[mask.reshape(-1)]
        row.floor_category=record['category'];row.floor_logit=record['score'];row.support_coverage=float(mask.mean())
        row.tilt=abs(float(coeff[0]));row.plane_inlier_ratio=len(indices)/len(support_points)
        object_mask = _object_mask_above_plane(points,coeff[:3],coeff[3],z.shape,
                            (points[:,2]>.05)&(points[:,2]<config.get('z_far',5)),settings,support_points[indices])
        if object_mask is None:
            row.eligible=False;row.reject_reason='Degenerate support footprint';scores.append(row);continue
        object_mask=cv2.morphologyEx(object_mask.astype('uint8'),cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        object_masks[i]=object_mask.astype(bool);kept=visibility(row,object_mask)
        row.sharpness=_sharpness(data['frames'][i]['path'],image,object_mask.astype(bool))
        if row.tilt>settings['max_tilt'] or row.plane_inlier_ratio<settings['min_plane_inlier_ratio'] or row.support_coverage<settings['min_support_coverage'] or not kept or row.clipped_frac>settings['max_clipped_frac']:
            row.eligible=False;row.reject_reason='Original frame eligibility thresholds not met'
        scores.append(row)
    global_scores=[asdict(s)for s in scores];preview=None;target_clipping={}
    ranked = rank_frames(scores,settings)
    if not ranked and any(plane_ok(s)and s.clipped_frac>settings['max_clipped_frac']for s in scores):
        from PIL import Image
        preview=semantic_preview(candidate,config,previous,folder/'semantic',provider)
        frames={r['frame_id']:r for r in preview['frames']}
        for row in scores:
            if not plane_ok(row)or row.idx not in object_masks:continue
            target=np.zeros(depth[row.idx].shape,bool);context=np.zeros_like(target)
            frame=frames.get(data['frames'][row.idx]['id'],{})
            for association in frame.get('associations',[]):
                if not association.get('mask'):continue
                path=Path(association['mask'])
                if sha(path)!=association.get('mask_sha256'):raise ValueError('Semantic Mask SHA identity changed')
                mask=np.asarray(Image.open(path).convert('L'))>0
                if mask.shape!=target.shape:raise ValueError('Semantic Mask pixel grid mismatch')
                if association['status']!='UNIQUE_ESTIMATED':continue
                role=association['role']
                if role in ('manipulable_object','receptacle'):target|=mask
                elif role in ('reference_robot','background','fixture'):context|=mask
            target_score=FrameScore(idx=row.idx);has_target=visibility(target_score,target)
            target_clipping[row.idx]=target_score.clipped_frac
            # Keep unknown geometry. Only a recorded, role-bound SAM Mask can
            # remove equipment; overlapping Target pixels always take priority.
            scoped=object_masks[row.idx]&~(context&~target)
            has_geometry=visibility(row,scoped)
            row.eligible=bool(has_target and has_geometry and row.clipped_frac<=settings['max_clipped_frac']
                              and target_score.clipped_frac<=settings['max_clipped_frac'])
            row.reject_reason=None if row.eligible else'Unresolved Target/context association or clipped geometry'
        ranked=rank_frames(scores,settings)
    diagnostics={'global_scores':global_scores,'scores':[{**asdict(s),**({'target_clipped_frac':target_clipping[s.idx]}if s.idx in target_clipping else{})}for s in scores],
                 'thresholds':settings,'semantic_preview':preview}
    folder.mkdir(parents=True,exist_ok=True);write(folder/'frame-selection.json',diagnostics)
    if not ranked:raise StageNeeds('NEEDS_MORE_DATA','No canonical frame satisfies support/object/visibility requirements')
    chosen = ranked[0].idx
    if settings['mode'] != 'heuristic' and preview is not None:
        # Reuse the VLM's per-object representative views instead of paying for
        # another judgment of the same photographs. Numeric eligibility wins.
        from collections import Counter
        votes=Counter(o.get('representative_view')for o in preview.get('objects',{}).values()
                      if o['role']in('manipulable_object','receptacle'))
        chosen=max(ranked,key=lambda s:(votes[data['frames'][s.idx]['id']],s.score)).idx
    elif settings['mode'] != 'heuristic':
        shortlist=[s.idx for s in ranked[:settings['vlm_top_k']]]
        result=provider('vlm',{'images':[data['frames'][i]['path']for i in shortlist],
                             'task':'canonical_frame','response_schema':typed_record({'selected_index':{'type':'integer','enum':shortlist}}),
                             'prompt':'Select the best canonical reconstruction view for object separation and visibility. Return JSON {"selected_index": INDEX}. Allowed indices: '+json.dumps(shortlist)},folder/'selection')
        chosen=result['answer']['selected_index']
        if type(chosen) is not int or chosen not in shortlist:raise ValueError('VLM selected a frame outside the eligible shortlist')
    return {'selected_index':chosen,'selected_frame_id':data['frames'][chosen]['id'],
            'scores':diagnostics['scores'],'global_scores':global_scores,'semantic_preview':preview,'support_masks':response['path'],
            'plane':response['planes'][chosen]['final'],'coordinate_frame':'selected optical Camera',
            'selection_mode':'semantic_preview_hybrid'if preview is not None else settings['mode']}


def world(candidate, config, previous, folder, provider):
    data, selected = previous[2], previous[3]
    index=selected['selected_index'];plane=selected['plane']
    T=support_transform(plane['coefficients'][:3],plane['origin'])
    with np.load(data['prediction'])as a:
        E=np.eye(4);E[:3]=a['extrinsics'][index];support_from_da3=T@E
        clouds=np.array([world_points(z,k,e)@support_from_da3[:3,:3].T+support_from_da3[:3,3]
                         for z,k,e in zip(a['depth'],a['intrinsics'],a['extrinsics'])])
    path=folder/'world_points.npz';np.savez_compressed(path,points=clouds,support_from_da3=support_from_da3,camera_to_support=T)
    qa=[]
    for anchor in config.get('metric_anchors',[]):
        if anchor.get('source')not in('measured','calibrated') or not anchor.get('evidence'):
            raise ValueError('Metric QA requires explicit measured provenance')
        qa.append(metric_qa(anchor['observed_corners_camera_m'],anchor['dimensions_xy_m']))
    up=T[:3,:3]@np.asarray(plane['coefficients'][:3])
    return {'world_points':str(path),'camera_to_support':T.tolist(),'support_from_da3':support_from_da3.tolist(),
            'selected_index':index,'selected_frame_id':selected['selected_frame_id'],
            'normal_after_original_rotation':up.tolist(),'metric_qa':qa,
            'metric_verified':False,'robot_world_registered':False,
            'coordinate_frame':'estimated support frame; not Robot World'}


def depth_inpainting_inputs(rgb, original_rgb, original_depth, K, generated_mask, folder):
    """Freeze one shared RGB/Z edit region in the selected optical pixel grid.

    A resized FLUX render must have been returned to this original grid before
    this boundary. No new pose, K adjustment or metric-scale claim is invented.
    """
    from PIL import Image
    rgb=np.asarray(rgb);original_rgb=np.asarray(original_rgb)
    depth=np.asarray(original_depth);region=np.asarray(generated_mask,bool);K=np.asarray(K,float)
    if rgb.shape!=original_rgb.shape or rgb.ndim!=3 or rgb.shape[-1]!=3 or rgb.shape[:2]!=depth.shape or region.shape!=depth.shape:
        raise ValueError('Inpainting RGB/Depth/Mask pixel-frame mismatch')
    if K.shape!=(3,3)or not np.isfinite(K).all()or min(K[0,0],K[1,1])<=0:raise ValueError('Valid optical K required')
    if not np.isfinite(depth).all()or np.any(depth<=0)or not region.any():raise ValueError('Positive observed Z and generated region required')
    if not np.array_equal(rgb[~region],original_rgb[~region]):raise ValueError('RGB edit changed protected observed pixels')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    paths={key:folder/name for key,name in [('image','generated_rgb.png'),('original_rgb','observed_rgb.png'),('original_depth','observed_depth.npy'),('generated_pixels','generated_pixels.npy'),('prior','prior.npy')]}
    Image.fromarray(rgb.astype('uint8')).save(paths['image']);Image.fromarray(original_rgb.astype('uint8')).save(paths['original_rgb'])
    np.save(paths['original_depth'],depth);np.save(paths['generated_pixels'],region)
    prior=depth.copy();prior[region]=0;np.save(paths['prior'],prior)
    result={key:str(path)for key,path in paths.items()}
    result.update(K=K.tolist(),rgb_original_to_current=np.eye(3).tolist(),
        coordinate_frame='selected optical Camera Z; same RGB pixel grid',units='model-estimated m',
        provenance='Known Z retained from previous state; hole is estimated, never measured')
    write(folder/'contract.json',result)
    return result


def removal_review_schema():
    choices={'type':'string','enum':['yes','no','unknown']}
    properties={name:copy.deepcopy(choices)for name in ('removed','object_remaining','other_objects_preserved','background_continuous')}
    properties.update(reason={'type':'string'},uncertain={'type':'boolean'},
                      evidence={'type':'array','items':{'type':'string'}})
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}


def removal_evidence(edit, *, before, mask, object_mask):
    """Observable RGB invariants, not a universal semantic removal classifier."""
    from PIL import Image
    paths={'before':before,'mask':mask,'object_mask':object_mask,'after':edit.get('path'),'raw':edit.get('raw_path')}
    if any(not path or not Path(path).is_file()for path in paths.values()):
        raise StageNeeds('NEEDS_REVIEW','Missing local removal image/Mask evidence')
    arrays={key:np.asarray(Image.open(path).convert('L'if key in ('mask','object_mask')else'RGB'))for key,path in paths.items()}
    original=arrays['before'];after=arrays['after'];region=arrays['mask']>0;target=arrays['object_mask']>0
    if original.shape!=after.shape or region.shape!=original.shape[:2]or target.shape!=region.shape or not target.any()or np.any(target&~region):
        raise StageNeeds('NEEDS_REVIEW','Removal pixel/Mask evidence is inconsistent')
    changed=np.any(original!=after,axis=-1)
    result={'generated_rgb_exists':True,'raw_rgb_exists':True,'non_edit_pixels_exact':bool(not changed[~region].any()),
            'changed_region_pixels':int(changed[region].sum()),'changed_target_pixels':int(changed[target].sum()),
            'object_remaining':'NOT_INDEPENDENTLY_VERIFIED','other_objects':'Protected outside region; overlapping/occluded objects require review'}
    if not result['non_edit_pixels_exact']or not result['changed_region_pixels']or not result['changed_target_pixels']:
        raise StageNeeds('NEEDS_REVIEW','Local removal pixel evidence contradicts success')
    return result


def reviewed_removal(edit, answer, *, before=None, mask=None, object_mask=None):
    """Reject missing/conflicting evidence even when a VLM says removed=yes."""
    if edit.get('provider')!='comfy_gguf':return True
    removal_evidence(edit,before=before,mask=mask,object_mask=object_mask)
    if not isinstance(answer,dict)or set(answer)!=set(removal_review_schema()['required']):
        raise StageNeeds('NEEDS_REVIEW','Local FLUX removal needs a complete structured quality review')
    if (answer['removed']!='yes'or answer['object_remaining']!='no'or answer['other_objects_preserved']!='yes'or
        answer['background_continuous']!='yes'or answer['uncertain']is not False or
        not isinstance(answer['reason'],str)or not answer['reason'].strip()or
        not isinstance(answer['evidence'],list)or not answer['evidence']or
        any(not isinstance(row,str)or not row.strip()for row in answer['evidence'])):
        raise StageNeeds('NEEDS_REVIEW','Local FLUX object removal evidence is uncertain or conflicting',code='REMOVAL_QUALITY',classification='RETRYABLE',scope='object')
    return True


def preview_instances(previous):
    """Stage5's initial observations in the selected DA3 pixel grid only."""
    preview=previous[3].get('semantic_preview')
    if preview is None:return None
    if sha(previous[2]['prediction'])!=preview['identity']['prediction_sha256']:
        raise ValueError('Semantic preview Depth prediction SHA changed')
    analysis=preview['scene_analysis']
    if sha(analysis['path'])!=analysis['sha256']:raise ValueError('Retained semantic analysis SHA changed')
    for source in analysis['source_images']:
        if sha(source['path'])!=source['sha256']:raise ValueError('Retained semantic source SHA changed')
    selected=next((r for r in preview['frames']if r['frame_id']==previous[3]['selected_frame_id']),None)
    if selected is None:raise ValueError('Semantic preview has no selected frame')
    raw={o['id']:o for o in read(analysis['path'])['objects']};objects=[];masks=[];coverage=[]
    for name,spec in preview['objects'].items():
        row=next((r for r in selected['associations']if r['id']==name),None)
        geometry=raw[name].get('geometry')or{}
        applicable=spec['role']in('manipulable_object','receptacle','workspace')or(
            spec['role']=='background'and geometry.get('source')=='user_memo')
        ready=bool(row and row['status']=='UNIQUE_ESTIMATED'and row.get('mask'))
        coverage.append({'id':name,'role':spec['role'],'applicable_to_decomposition':applicable,
            'status':'OBSERVATION_READY'if applicable and ready else'UNRESOLVED'if applicable else'CONTEXT_ONLY',
            'physical_identity_verified':False,'memo_constraints_applied':analysis.get('validation',{}).get('status')=='FULL'})
        if not applicable or not ready:continue
        if sha(row['mask'])!=row['mask_sha256']:raise ValueError('Retained semantic Mask SHA changed')
        objects.append({'id':name,'prompt':spec['prompt'],'role':spec['role'],'category':spec['category'],
            'description':spec['modeling_notes'],'box_xyxy':row['box_xyxy'],
            'uncertainty':'UNIQUE_ESTIMATED pixel association; physical identity remains unverified',
            'relations':[],'support':(spec.get('support')or{}).get('support')})
        masks.append({'id':name,'status':'UNIQUE_ESTIMATED','path':row['mask'],'confidence':row.get('confidence')})
    if not objects:raise StageNeeds('NEEDS_REVIEW','Semantic preview has no usable selected-frame object association')
    return {'objects':objects,'masks':masks,'coverage':coverage,'scene_analysis':analysis}


def bind_memo_constraints(candidate, config, analysis, folder, provider):
    """One bounded typed correction; immutable visual plan/Mask IDs are reused."""
    from . import authoring
    from .evidence import scene_memo
    memo=scene_memo(candidate.project);records=analysis['source_images']
    if sha(analysis['path'])!=analysis['sha256']or analysis['memo_sha256']!=memo['sha256']:
        raise ValueError('Constraint correction source plan/Memo changed')
    if analysis['guidance_sha256']!=authoring._codex_guidance()[1]['sha256']:
        raise ValueError('Constraint correction Guide changed')
    if any(sha(r['path'])!=r['sha256']for r in records):raise ValueError('Constraint source image changed')
    plan=read(analysis['path']);links=[f.removeprefix('robot_link_')for f in candidate.scene.get('frames',{})if f.startswith('robot_link_')]
    request_context={'memo':memo,'source_plan_sha256':stage_digest(plan),
        'robot_rig':candidate.scene.get('robot_rig'),
        'protected_objects':copy.deepcopy(config.get('objects',{})),
        'namespaces':authoring.semantic_namespaces(records,[r['id']for r in plan['objects']],links),
        'source_objects':[{k:r[k]for k in('id','role','prompt','category','modeling_notes','observations','model_references','geometry')}for r in plan['objects']],
        'replaces_geometry_ids':[r['id']for r in plan['objects']if r['geometry']is not None],
        'prior_validation':analysis.get('validation'),
        'images':[{'image_index':i+1,**{k:r.get(k)for k in('id','role','resolution','sha256','scene_state_id')}}for i,r in enumerate(records)]}
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    cache=folder/'binding.json';identity=stage_digest(request_context)
    if cache.is_file():
        record=read(cache)
        if record['identity']!=identity or sha(record['path'])!=record['sha256']:raise ValueError('Constraint binding cache identity changed')
        packet=read(record['path'])
    elif (folder/'answer.json').is_file():
        if stage_digest(read(folder/'validation-input.json'))!=identity:raise ValueError('Saved correction input identity changed')
        path=folder/'answer.json';packet=read(path)
        record={'identity':identity,'path':str(path),'sha256':sha(path)}
    else:
        attempted=folder/'attempt.json'
        if attempted.exists():raise StageNeeds('NEEDS_REVIEW','Memo correction already attempted; inspect failure without automatic retry',code='MEMO_CONSTRAINT_REVIEW')
        write(folder/'validation-input.json',request_context)
        write(attempted,{'identity':identity,'attempts':1,'maximum':1,'status':'ATTEMPTED'})
        request={'task':'scene_memo_constraints','images':[r['path']for r in records],
            'context':request_context,'response_schema':authoring.scene_constraint_schema(),
            'prompt':('Correct only the cached semantic plan\'s Memo constraints. Preserve ALL existing Object IDs/roles/observations; do not redetect. '
                'Return one compact typed correction. Allowed IDs are explicitly listed in namespaces. capture_layouts may use only actual '
                'capture_layout_ids, NEVER Photo/Reference scene_state_id; return [] if that allowlist is empty. '
                'Explicitly list all replaces_geometry_ids; the old raw plan stays immutable, and old invalid scalar claims are not applied. '
                'Interpret the exact Memo, including group cardinality and shared dimensions. Bind each group to every existing member with actual '
                'Scene Photo evidence. Do not substitute image/reference IDs for Object IDs, or merge/split instances. '
                'Use exact unique source_quote spans and literal value_quote number+unit; zero tilt may quote a bare 0 in degrees. '
                'shared_dimension quantities are cube_edge_length, upper_rim_diameter, height. Upper rim diameter is NEVER bottom/internal diameter or wall. '
                'rectangle_border requires outer_x/outer_y/inner_x/inner_y/border_width together; inward border is not Z thickness. '
                'pair_spacing requires exactly two receptacles with edge gap and center distance; explicitly list PARALLEL_AXES, EQUAL_RIM_HEIGHT, '
                'CIRCULAR_UPPER_RIMS as assumptions, not verified facts. Do not issue pose moves. '
                'axis_relation uses workspace axis y parallel to the reference pair, x perpendicular; reference_objects has the two existing IDs. '
                'Axis sign, world origin, Robot World and unmeasured Mount stay unresolved. orientation represents only Memo support tilt. '
                'reuse_existing binds the reference_robot to its existing URDF, no new Robot geometry. '
                'One physical Wrist Camera and its named fixture components form ONE assembly with physical_sensor_count=1, existing Robot parent, '
                'and if robot_rig is selected use its exact registered assembly asset_id as that assembly ID for explicit reuse. '
                'link null when no known Robot link, T_link_assembly null; do not create independent sensors. '
                'Only Memo-supported quantities; unmeasured shape stays unknown. Missing/ambiguous membership must remain unresolved, not fabricated. '
                'Do not include a geometry numeric value merely because it appeared in a previous model/asset. No tools, generation, calibration or modeling.')}
        packet=provider('vlm',request,folder/'vlm')['answer']
        path=folder/'answer.json';write(path,packet)
        record={'identity':identity,'path':str(path),'sha256':sha(path)}
    try:bound=authoring.validate_scene_constraints(packet,plan,memo,image_records=records,robot_links=links)
    except ValueError as error:
        write(folder/'validation.json',{'status':'REVIEW','error':str(error),'source_plan_sha256':stage_digest(plan)})
        raise StageNeeds('NEEDS_REVIEW','Memo constraint correction failed strict validation: '+str(error),code='MEMO_CONSTRAINT_REVIEW')from error
    write(folder/'validated.json',bound);write(cache,record)
    return {**copy.deepcopy(analysis),'constraint_binding':record,
        'validation':{'status':'BOUND_OBJECTS','strict_error':None,'scene_registration':'UNRESOLVED'}},rig_semantic_binding(candidate,bound)


def rig_semantic_binding(candidate,bound):
    """Reuse only the explicitly matched typed Assembly, never Memo name guessing."""
    rig=candidate.scene.get('robot_rig')
    if not rig:return bound
    matched=[a for a in bound['assemblies']if a['id']==rig['assembly']['asset_id']]
    component_binding=any(spec.get('shape_constraints',{}).get('memo_binding',{}).get('assembly_id')==rig['assembly']['asset_id']
        for spec in bound['objects'].values())
    if (bound['assemblies']or component_binding)and len(matched)!=1:
        raise StageNeeds('NEEDS_REVIEW','Selected Robot Rig has no unique explicit semantic Assembly binding',code='ROBOT_RIG_ASSOCIATION')
    if not matched:return bound
    for name in matched[0]['members']:
        bound['objects'][name]['robot_rig_component']={'rig_sha256':rig['rig_sha256'],
            'asset_id':rig['assembly']['asset_id'],'version':rig['assembly']['version'],
            'mount_status':rig['mount_status'],'calibration_status':rig['calibration_status']}
        bound['objects'][name]['modeling_readiness']='REUSED_ROBOT_RIG'
    bound['reused_rig_components']=list(matched[0]['members'])
    matched[0]['appearance_status']='REUSED_REGISTERED_ASSEMBLY'
    # Optical/Mount accuracy and Robot World remain unresolved, even if the
    # accessory has a visually useful initial rigid placement in the URDF.
    return bound


def bound_analysis(candidate,record):
    """Revalidate the exact binding at every consumer, including cached handoff."""
    from . import authoring
    from .evidence import scene_memo
    binding=record['constraint_binding'];memo=scene_memo(candidate.project)
    if record['guidance_sha256']!=authoring._codex_guidance()[1]['sha256']or record['memo_sha256']!=memo['sha256']:
        raise ValueError('Retained constraint Guide/Memo identity changed')
    if sha(record['path'])!=record['sha256']or sha(binding['path'])!=binding['sha256']:
        raise ValueError('Retained constraint/semantic plan SHA changed')
    if any(sha(r['path'])!=r['sha256']for r in record['source_images']):raise ValueError('Retained constraint source image changed')
    links=[f.removeprefix('robot_link_')for f in candidate.scene.get('frames',{})if f.startswith('robot_link_')]
    return rig_semantic_binding(candidate,authoring.validate_scene_constraints(read(binding['path']),read(record['path']),memo,
        image_records=record['source_images'],robot_links=links))


def decompose(candidate, config, previous, folder, provider):
    """VLM/SAM instances, original ray ordering, RGB removal and conditioned Z.

    RGB/Depth inpainting is synthetic evidence for later hidden surfaces. The
    original DA3 arrays and pre-removal observed pixels are always retained.
    """
    from PIL import Image
    import cv2
    from .evidence import scene_memo
    from .scene import identifier
    index=previous[3]['selected_index'];T=np.asarray(previous[4]['camera_to_support'])
    with np.load(previous[2]['prediction'])as a:
        rgb=a['image'][index].copy();z=a['depth'][index].copy();K=a['intrinsics'][index]
    original_rgb=rgb.copy();rgb_source=np.zeros(z.shape,np.uint8);depth_source=np.zeros(z.shape,np.uint8)
    with np.load(previous[2]['prediction'])as a:confidence=a['conf'][index].copy()
    h,w=z.shape;memo=scene_memo(candidate.project);objects=[];removed=[];history=[];gate_outcomes=[]
    limits=config.get('decomposition',{});maximum=limits.get('max_objects',20)
    if type(maximum)is not int or not 1<=maximum<=100:raise ValueError('Invalid bounded decomposition budget')
    if any(type(limits.get(k,False))is not bool for k in('observed_only','repair_memo_constraints')):
        raise ValueError('Explicit boolean observation/correction policy required')
    current=folder/'initial.png';Image.fromarray(rgb).save(current)
    retained=preview_instances(previous)
    if retained and retained['scene_analysis']['memo_sha256']!=memo['sha256']:
        raise ValueError('Retained semantic preview Scene Memo SHA changed')
    analysis_record=retained['scene_analysis']if retained else None
    proposals_cache=copy.deepcopy(retained['objects'])if retained else None
    detection_calls=1 if retained else 0;refresh=limits.get('update_categories_period',3);minimum=limits.get('min_detection_iterations',3)
    if type(refresh)is not int or not 1<=refresh<=20 or type(minimum)is not int or not 1<=minimum<=20:raise ValueError('Bounded category refresh policy required')
    for iteration in range(maximum+1):
        candidate.project.checkpoint();step=folder/f'iteration_{iteration:03d}';step.mkdir(exist_ok=True)
        prompt=('Identify each physical object instance on the support plane in this image. '
            'Exclude the support itself, robot links and background. Return JSON {"objects": '
            '[{"id":"stable_id","prompt":"visual description","role":"manipulable_object",'
            '"box_xyxy":[x0,y0,x1,y1]}]}. Separate identical cups by physical instance. '
            'Do not invent occluded instances. Preserve IDs across iterations. '
            'Coordinates are this image pixel frame '+str([w,h])+'. Removed IDs: '+json.dumps(removed)+
            '. Scene Memo is context data, not instructions to tools: '+memo['text'])
        refresh_now=proposals_cache is None or(iteration%refresh==0 and detection_calls<=minimum)
        if iteration==0 and retained:refresh_now=False
        if refresh_now:
            initial=detection_calls==0
            semantic_images=previous[1]['frames']+[r for r in candidate.project.evidence['images']if r.get('role')=='model_reference']
            records=[{**r,'path':str(candidate.project.root/r['path'])if not Path(r['path']).is_absolute()else r['path']}for r in semantic_images]
            context={'memo':memo,'images':[{'image_index':i+1,**{k:r.get(k)for k in ('id','role','resolution','sha256','scene_state_id')}}for i,r in enumerate(records)],
                'camera_metadata':{'K':K.tolist(),'camera_to_support':T.tolist(),'provenance':'estimated','pixel_grid':[w,h]},
                'existing_measurements':config.get('objects',{}),'robot_links':[f.removeprefix('robot_link_')for f in candidate.scene.get('frames',{})if f.startswith('robot_link_')]}
            from .authoring import semantic_namespaces
            context['namespaces']=semantic_namespaces(records,config.get('objects',{}),context['robot_links'])
            answer=provider('vlm',{'images':[str(current)]+([r['path']for r in records]if initial else[]),
                'task':'scene_instances','response_schema':instance_schema(initial=initial),'context':context,
                'prompt':prompt+' Return category, description, relations, support, occlusion uncertainty and memo consistency. '
                'For each assessment distinguish identity/Box/Memo conflicts from hidden shape, unmeasured dimensions and front uncertainty. Keep overall uncertain truthful; these last three alone do not forbid a draft. '+
                ('Also return scene_analysis using guide section 2 for the provided source image IDs, original resolution, memo and model references. '
                 'capture_layouts may use only namespaces.capture_layout_ids, never Photo/Reference layout IDs; use [] when no Capture is allowed. '
                 'This analysis will be reused by Stage7. 'if initial else'')},step/'vlm')['answer'];detection_calls+=1
            if not isinstance(answer,dict)or not isinstance(answer.get('objects'),list):raise ValueError('Expected typed VLM object-instance list')
            gate_outcomes.extend(instance_gate(answer,sha(current)))
            if initial and 'scene_analysis'in answer:
                path=step/'scene_analysis.json';write(path,answer['scene_analysis'])
                from .authoring import _codex_guidance,parse_visual_scene_analysis
                checked=parse_visual_scene_analysis(answer['scene_analysis'],memo,{r['id']for r in records},
                    image_records=records,robot_links=context['robot_links'])
                analysis_record={'path':str(path),'sha256':sha(path),'memo_sha256':memo['sha256'],
                    'guidance_sha256':_codex_guidance()[1]['sha256'],'source_images':records,
                    'validation':checked['validation'],'deferred_constraints':checked['deferred']}
            proposals_cache=answer['objects']
        active=[o for o in proposals_cache if o['id']not in removed]
        if not active:
            if detection_calls>=minimum:
                if not objects:raise StageNeeds('NEEDS_MORE_DATA','VLM found no reconstruction objects')
                break
            continue
        if iteration==maximum:raise StageNeeds('NEEDS_REVIEW','Scene decomposition object budget exhausted')
        ids=set();proposals=[]
        for obj in active:
            if not {'id','prompt','role','box_xyxy'}<=set(obj)or set(obj)-{'id','prompt','role','box_xyxy','category','description','uncertainty','relations','support','assessment'}:raise ValueError('Unexpected VLM instance fields')
            name=identifier(obj['id']);box=np.asarray(obj['box_xyxy'],float)
            if name in ids or name in removed or box.shape!=(4,)or not np.isfinite(box).all()or not(0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h):
                raise StageNeeds('NEEDS_REVIEW','Ambiguous/repeated Instance ID or invalid observation bounds')
            if obj['role']not in('manipulable_object','receptacle','background','workspace','support_surface')or not isinstance(obj['prompt'],str)or not obj['prompt'].strip():
                raise ValueError('Invalid VLM object role/description')
            ids.add(name);proposals.append(copy.deepcopy(obj))
        world_map=step/'support_world.npy';np.save(world_map,backproject(z,K)@T[:3,:3].T+T[:3,3])
        segment={'objects':retained['masks'],'reused_from':'Stage3 semantic preview'}if iteration==0 and retained else provider(
            'segments',{'image':str(current),'objects':proposals,'world_points':str(world_map)},step/'sam3')
        masks={row['id']:row for row in segment['objects']}
        if set(masks)!=ids or any(row['status']!='UNIQUE_ESTIMATED'for row in masks.values()):
            raise StageNeeds('NEEDS_REVIEW','SAM3 instance association is missing or ambiguous',code='MASK_ASSOCIATION',classification='OBJECT_REVIEW',scope='object',object_ids=sorted(ids),input_sha256=sha(current))
        clouds=[];camera_points=backproject(z,K);snapshots={}
        threshold=limits.get('minimum_depth_confidence')
        if threshold is not None and(type(threshold)not in(int,float)or not np.isfinite(threshold)):raise ValueError('Finite explicit Depth confidence threshold required')
        low_confidence=((~np.isfinite(confidence)) if threshold is None else(~np.isfinite(confidence))|(confidence<threshold))&(depth_source==0)
        for obj in proposals:
            mask=np.asarray(Image.open(masks[obj['id']]['path']).convert('L'))>0
            if mask.shape!=z.shape:raise ValueError('Object mask and optical-Z pixel grids disagree')
            if mask.sum()<10:raise StageNeeds('NEEDS_MORE_DATA','Insufficient observed object mask points',code='OBJECT_POINTS',classification='OBJECT_REVIEW',scope='object',object_ids=[obj['id']],input_sha256=sha(current))
            points=camera_points[mask]@T[:3,:3].T+T[:3,3]
            file=step/(obj['id']+'_world_points.npy');np.save(file,points);clouds.append({'id':obj['id'],'points':str(file)})
            snapshot=step/(obj['id']+'_observed.npz')
            np.savez_compressed(snapshot,image=rgb,mask=mask,depth=z,K=K,camera_points=camera_points[mask],
                rgb_source=rgb_source,depth_source=depth_source,low_confidence=low_confidence,confidence=confidence)
            snapshots[obj['id']]={'observed':str(snapshot),'sha256':sha(snapshot),'mask_sha256':sha(masks[obj['id']]['path']),
                'input_sha256':sha(current),'status':'OBSERVATION_READY','provenance':'original_and_generated_pixel_maps'}
        # Every current observation is frozen before the first edit. A failed
        # removal cannot discard independent, already completed observations.
        progress={'schema':'decomposition-progress/1','objects':snapshots,'removed':list(removed),
            'successful_objects':[o['id']for o in objects],'current_rgb_sha256':sha(current),
            'dependency_policy':'Sequential occlusion/support order; absence of dependency evidence is not independence'}
        if retained:progress['semantic_coverage']=retained['coverage']
        write(step/'object_progress.json',progress)
        bound=None
        requires_binding=analysis_record and analysis_record.get('validation',{}).get('status')!='FULL'
        if analysis_record and not analysis_record.get('constraint_binding')and not requires_binding:
            # A valid legacy envelope can still contain only unverified/null
            # Memo dimensions. FULL syntax is not authenticated measurement.
            requires_binding=any((r.get('geometry')or{}).get('source')=='user_memo'
                and not(r['geometry'].get('measurement_claims')or r['geometry'].get('dimension_relations'))
                for r in read(analysis_record['path'])['objects']
                if r['role']in('manipulable_object','receptacle','workspace'))
        if analysis_record and analysis_record.get('constraint_binding'):
            bound=bound_analysis(candidate,analysis_record)
        elif requires_binding:
            if limits.get('repair_memo_constraints',True):
                analysis_record,bound=bind_memo_constraints(candidate,config,analysis_record,folder/'memo_constraints',provider)
            else:
                raise StageNeeds('NEEDS_REVIEW','Scene Memo constraints require review; initial Object observations retained before generation',
                                 code='MEMO_CONSTRAINT_REVIEW',classification='OBJECT_REVIEW')
        if bound:
            for obj in proposals:
                spec=bound['objects'][obj['id']]
                if spec['role']!=obj['role']:raise ValueError('Bound/observed Object role mismatch')
                if spec['modeling_readiness']!='READY_FOR_MODELING':
                    raise StageNeeds('NEEDS_REVIEW','Observed Object still has unbound Memo dimensions: '+obj['id'],code='MEMO_CONSTRAINT_REVIEW')
                locked=config.get('objects',{}).get(obj['id'],{}).get('geometry',{})
                if locked.get('provenance')in('measured','calibrated'):
                    proposed=spec.get('geometry',{}).get('dimensions_m',[None]*3)
                    if any(a is not None and b is not None and not np.isclose(a,b,rtol=1e-9,atol=1e-12)
                           for a,b in zip(locked['dimensions_m'],proposed)):
                        raise StageNeeds('NEEDS_REVIEW','Memo constraint conflicts with protected Object dimensions: '+obj['id'],code='MEMO_CONSTRAINT_REVIEW')
                obj['memo_binding']=copy.deepcopy(spec['shape_constraints']['memo_binding'])
            if retained:
                for row in retained['coverage']:
                    row['memo_constraints_applied']=bool(bound['objects'][row['id']]['shape_constraints']['memo_binding']['constraint_ids'])
                    row['constraint_validation']='VALIDATED_OBJECT_BINDING'
                progress['semantic_coverage']=retained['coverage']
                write(step/'object_progress.json',progress)
        if limits.get('observed_only',False):
            # Explicit input-preparation scope: no removal/inpainting/hidden surface
            # claims. The orchestrator must retain this as PARTIAL, not COMPLETE.
            for obj in proposals:
                objects.append({**obj,'mask':masks[obj['id']]['path'],'observed':snapshots[obj['id']]['observed'],
                    'observed_rgb':str(current),'source_frame_id':previous[3]['selected_frame_id'],'iteration':0,
                    'provenance':'original_rgb_model_estimated_depth','model_reference_ids':[],
                    'original_pixel_agreement':1.,'modeling_readiness':'READY_FOR_MODELING',
                    'confidence_policy':{'minimum':threshold,'calibrated':False,'generated_confidence':'UNKNOWN'}})
            result={'objects':objects,'selected_frame_id':previous[3]['selected_frame_id'],'scene_analysis':analysis_record,
                'status':'PARTIAL','mode':'observed_only','complete':False,'constraints_status':'PASS'if bound else'LEGACY_VALIDATED',
                'scene_registration':'UNRESOLVED','coordinate_frame':'observed selected optical Camera XYZ',
                'semantic_coverage':retained['coverage']if retained else[],
                'unresolved':bound['unresolved']if bound else[],'generated_rgb_depth':False}
            write(folder/'observation-inputs.json',result)
            return result
        result=provider('removal',{'objects':clouds,'camera_to_world':T.tolist()},step/'order')
        order=result['order']
        if not isinstance(order,list)or len(order)!=len(ids)or set(order)!=ids:raise ValueError('Invalid occlusion/support removal ordering')
        name=order[0];obj=next(o for o in proposals if o['id']==name)
        mask=np.asarray(Image.open(masks[name]['path']).convert('L'))>0
        valid_pixel_proportion=float((np.linalg.norm(original_rgb.astype(np.float32)-rgb.astype(np.float32),axis=-1)[mask]<50).mean())
        if valid_pixel_proportion<=limits.get('min_valid_pixel_prop',.10):
            raise StageNeeds('NEEDS_REVIEW','Object contains insufficient pixels aligned to the original canonical RGB: '+name)
        observed=Path(snapshots[name]['observed'])
        observed_rgb=step/(name+'_observed.png');Image.fromarray(rgb).save(observed_rgb)
        objects.append({**obj,'mask':masks[name]['path'],'observed':str(observed),
                        'observed_rgb':str(observed_rgb),
                        'source_frame_id':previous[3]['selected_frame_id'],'iteration':iteration,
                        'provenance':'original_rgb_model_estimated_depth'if iteration==0 else'original_and_generated_pixel_maps',
                        'confidence_policy':{'minimum':threshold,'calibrated':False,'generated_confidence':'UNKNOWN'},
                        'model_reference_ids':[],'original_pixel_agreement':valid_pixel_proportion})
        from .calibration.decomposition import removal_annotation,removal_is_valid,removal_region
        region=removal_region(mask)
        edit_mask=step/'edit_region.png';Image.fromarray(region.astype('uint8')*255).save(edit_mask)
        attempts=[];edited=None
        modes=limits.get('removal_prompt_order',['mask','outline','bbox']);tries=limits.get('removal_attempts',3)
        if not isinstance(modes,list)or not modes or len(modes)>3 or any(m not in('mask','outline','bbox')for m in modes)or type(tries)is not int or not 1<=tries<=3:raise ValueError('Original bounded removal retry policy required')
        for mode in modes:
            annotated,check=removal_annotation(rgb,mask,mode)
            annotation=step/('annotated_'+mode+'.png');Image.fromarray(annotated).save(annotation)
            for seed in range(tries):
                progress.update(active_object=name,active_operation='RGB_REMOVAL',input_sha256=sha(current),dependencies=order[1:])
                write(step/'object_progress.json',progress)
                edit=provider('image_edit',{'image':str(annotation),'original_image':str(current),'mask':str(edit_mask),
                    'prompt':'Remove only '+obj['prompt']+' and its cast shadow. Reconstruct the surface and background that it occludes, preserving visible texture, lighting and perspective.',
                    'task':'removal','image_edit_role':'removal','annotation_mode':mode,
                    'object_id':name,'scene_context':memo['text'],'preserve_objects':[o['id']for o in proposals if o['id']!=name],
                    'object_prompt':obj['prompt'],'seed':seed},step/'rgb_inpaint'/mode/('seed_'+str(seed)))
                image=np.asarray(Image.open(edit['path']).convert('RGB'))
                if image.shape!=rgb.shape:image=cv2.resize(image,(w,h),interpolation=cv2.INTER_LINEAR)
                accepted=removal_is_valid(image,check)
                review_folder=step/'removal_review'/mode/('seed_'+str(seed))
                attempts.append({'mode':mode,'seed':seed,'path':edit['path'],'accepted':False,'annotation_valid':accepted,'review_folder':str(review_folder)})
                if accepted:
                    try:
                        review=None
                        if edit.get('provider')=='comfy_gguf':
                            evidence=removal_evidence(edit,before=current,mask=edit_mask,object_mask=masks[name]['path'])
                            write(step/'removal_pixels.json',evidence)
                            review=provider('vlm',{'images':[str(current),str(edit_mask),edit['path']],'task':'removal_validity',
                                'response_schema':removal_review_schema(),'context':{'memo_sha256':memo['sha256'],'object_id':name,'preserved_ids':[o['id']for o in proposals if o['id']!=name],'pixel_evidence':evidence},
                                'prompt':'Compare before and edited RGB. Confirm the target '+obj['prompt']+
                                ' is actually absent, its shadow is removed and the exposed support is continuous. A vanished annotation alone is insufficient. '
                                'Check object_remaining, other_objects_preserved, background_continuous, uncertainty and visible evidence. '
                                'Return the complete requested JSON Schema.'},review_folder)['answer']
                        attempts[-1]['quality_review']=review
                        reviewed_removal(edit,review,before=current,mask=edit_mask,object_mask=masks[name]['path'])
                    except StageNeeds as error:
                        if error.code!='REMOVAL_QUALITY':raise  # Never retry auth/Runtime/contract failures as generation.
                        attempts[-1]['gate']=error.gate
                    else:
                        attempts[-1]['accepted']=True;edited=image
                write(step/'removal_attempts.json',{'object_id':name,'input_sha256':sha(current),'attempts':attempts})
                if edited is not None:break
            if edited is not None:break
        if edited is None:
            pending=[o['id']for o in proposals if o['id']!=name]
            progress['objects'][name].update(status='OBJECT_REVIEW',reason='REMOVAL_RETRIES_EXHAUSTED')
            progress.update(dependency_blocked=pending,dependency_evidence='Ordered next RGB depends on this accepted removal; independent observation snapshots remain available')
            write(step/'object_progress.json',progress)
            raise StageNeeds('NEEDS_REVIEW','Original removal retries exhausted; no unverified RGB/Depth advanced',code='REMOVAL_RETRIES_EXHAUSTED',
                classification='OBJECT_REVIEW',scope='object',object_ids=[name],dependencies=pending,input_sha256=sha(current))
        before_edit=rgb.copy();rgb=np.where(region[...,None],edited,rgb)
        contract=depth_inpainting_inputs(rgb,before_edit,z,K,region,step/'depth_inputs')
        current=Path(contract['image']);prior=np.load(contract['prior'])
        geometric=provider('da3',{'images':[str(current)],'frame_ids':[previous[3]['selected_frame_id']+'_inpaint'],
                                'process_res':config.get('depth',{}).get('process_res',336)},step/'geometric_depth')
        with np.load(geometric['path'])as a:g=cv2.resize(a['depth'][0],(w,h),interpolation=cv2.INTER_LINEAR)
        geometric_path=step/'geometric.npy';np.save(geometric_path,g.astype('float32'))
        inpaint=provider('depth_inpaint',{**contract,'geometric':str(geometric_path)},step/'prior_depth')
        restored=np.load(inpaint['path'])
        if restored.shape!=z.shape or not np.isfinite(restored).all()or np.any(restored<=0):raise ValueError('Invalid inpainted optical depth')
        if not np.array_equal(restored[~region],prior[~region]):raise ValueError('Depth inpainting changed retained observed depth')
        z=restored;rgb_source[region]=1;depth_source[region]=1;confidence[region]=np.nan
        progress['objects'][name]['status']='REMOVAL_COMPLETE';write(step/'object_progress.json',progress)
        removed.append(name);history.append({'removed':name,'rgb_after':str(current),'depth_after':inpaint['path'],
            'order':order,'depth_input_contract':str(step/'depth_inputs/contract.json'),'removal_attempts':attempts,'new_single_view_pose_used':False,'inpainting_is_measured':False})
    else:
        raise StageNeeds('NEEDS_REVIEW','Category detection budget exhausted before confirming decomposition termination')
    return {'objects':objects,'scene_analysis':analysis_record,'category_detection_calls':detection_calls,'removal_history':history,'gate_outcomes':gate_outcomes,'selected_frame_id':previous[3]['selected_frame_id'],
            'selected_index':index,'camera_to_support':T.tolist(),'coordinate_frame':'selected optical Camera; synthetic hidden-surface evidence marked',
            'warnings':['RGB/Depth inpainting is synthesized evidence, never a measured or independently verified observation']}


def object_validity_schema():
    return typed_record({'validity':{'type':'string','enum':['yes','no','unknown']},
        'identity_preserved':{'type':'boolean'},'other_objects_present':{'type':'boolean'},
        'uncertain':{'type':'boolean'},'reason':{'type':'string'},
        'assessment':typed_record({'observed_shape_preserved':{'type':'boolean'},
            'foreground_valid':{'type':'boolean'},'measurement_consistent':{'type':'boolean'},
            'uncertainties':{'type':'array','items':{'type':'string','enum':[
                'OBJECT_IDENTITY','FOREGROUND_MASK','OTHER_OBJECT_CONTAMINATION','HIDDEN_GEOMETRY',
                'UNMEASURED_DIMENSIONS','TEXTURE_APPEARANCE','GENERATION_ARTIFACT']}}})})


def object_validity_gate(answer, object_id, input_sha256):
    """Keep hidden uncertainty without accepting identity/alpha/observed damage."""
    safe=False
    if isinstance(answer,dict):
        assessment=answer.get('assessment')
        if assessment is not None:
            from .codex_cli import validate_answer
            validate_answer(answer,object_validity_schema())
            safe=all(assessment[k]is True for k in('observed_shape_preserved','foreground_valid','measurement_consistent'))
            safe=safe and set(assessment['uncertainties'])<={'HIDDEN_GEOMETRY','UNMEASURED_DIMENSIONS'}
            safe=safe and (answer.get('uncertain')is False or bool(assessment['uncertainties']))
        else:safe=answer.get('uncertain')is False  # Historical strict answers only.
        safe=safe and answer.get('validity')=='yes'and answer.get('identity_preserved')is True and answer.get('other_objects_present')is False
    if not safe:
        raise StageNeeds('NEEDS_REVIEW','Generated Object identity/foreground/observed shape/measurement validity unresolved: '+object_id,
            code='OBJECT_IMAGE_VALIDITY',classification='OBJECT_REVIEW',scope='object',object_ids=[object_id],input_sha256=input_sha256)
    return {'classification':'ESTIMATED_CONTINUE','object_id':object_id,'input_sha256':input_sha256,
            'uncertainties':copy.deepcopy(answer.get('assessment',{}).get('uncertainties',[])),
            'physical_verified':False}


def prepare_objects(candidate, config, previous, folder, provider):
    """Source-style mask crops, 50% context / 10% focus padding, RGBA and editing."""
    from PIL import Image
    import cv2
    result=[];setting=config.get('image_preparation',{});size=setting.get('size',1024)
    if type(size)is not int or not 32<=size<=2048:raise ValueError('Invalid bounded object image size')
    for obj in previous[5]['objects']:
        candidate.project.checkpoint();out=folder/obj['id'];out.mkdir(exist_ok=True)
        with np.load(obj['observed'])as a:
            rgb=a['image'];mask=a['mask'];points,point_provenance=pose_point_selection(a,config.get('pose',{}))
            original_points,original_provenance=pose_point_selection(a,{})
            yy_original,xx_original=np.where(mask & (a['rgb_source']==0)&(a['depth_source']==0)&~a['low_confidence'].astype(bool))
        if mask.shape!=rgb.shape[:2]:raise ValueError('Observed RGB/Mask/Depth grids differ')
        # Crop-only callers can supply the self-contained observation NPZ.
        # Validate separate Stage5 references whenever they are supplied.
        if obj.get('observed_rgb') and np.asarray(Image.open(obj['observed_rgb'])).shape[:2]!=mask.shape:
            raise ValueError('Observed RGB/Mask/Depth grids differ')
        if obj.get('mask'):
            observed_mask=np.asarray(Image.open(obj['mask']).convert('L'))>0
            if observed_mask.shape!=mask.shape or not np.array_equal(observed_mask,mask):
                raise ValueError('Observed mask identity differs from the depth observation')
        yy,xx=np.where(mask)
        if not len(xx):raise StageNeeds('NEEDS_MORE_DATA','Cannot crop an empty object mask')
        crops={}
        for name,margin in [('context',.5),('focus',.1)]:
            pad=int(np.ceil(max(np.ptp(xx),np.ptp(yy))*margin));x0,y0=max(0,int(xx.min())-pad),max(0,int(yy.min())-pad)
            x1,y1=min(rgb.shape[1],int(xx.max())+pad+1),min(rgb.shape[0],int(yy.max())+pad+1)
            crop=rgb[y0:y1,x0:x1];alpha=mask[y0:y1,x0:x1].astype('uint8')*255
            rgba=np.dstack([np.where(alpha[...,None]>0,crop,255),alpha]);side=max(rgba.shape[:2]);square=np.full((side,side,4),255,np.uint8);square[...,3]=0
            dx,dy=(side-rgba.shape[1])//2,(side-rgba.shape[0])//2;square[dy:dy+rgba.shape[0],dx:dx+rgba.shape[1]]=rgba
            path=out/(name+'.png')
            resized=np.dstack([cv2.resize(square[...,:3],(size,size),interpolation=cv2.INTER_LINEAR),
                              cv2.resize(square[...,3],(size,size),interpolation=cv2.INTER_NEAREST)])
            Image.fromarray(resized).save(path)
            crops[name]={'path':str(path),'crop_xyxy':[x0,y0,x1,y1],'padding_xy':[dx,dy],'size':size,'sha256':sha(path)}
        enhanced=None;provider_crop=None;infilled=None;validity={'status':'NOT_VERIFIED'};validity_gate=None
        if setting.get('upsample',True) or setting.get('infill',False):
            description=provider('image_edit',{'task':'describe','image_edit_role':'objects'},out/'provider_metadata')
            if description.get('supported')is False:
                raise StageNeeds('NOT_SUPPORTED','Image provider has no original Stage6 native ratio contract; preserve Stage5 results')
            shapes=np.asarray(description['image_shapes'])
            if shapes.ndim!=2 or shapes.shape[1]!=2 or len(shapes)==0 or not np.isfinite(shapes).all() or np.any(shapes<=0):raise ValueError('Invalid provider-native image shapes')
            ratio=float(np.ptp(xx)/max(1,np.ptp(yy)));target=shapes[np.argmin(abs(shapes[:,0]/shapes[:,1]-ratio))].astype(int)
            crop_info=crops['focus'];x0,y0,x1,y1=crop_info['crop_xyxy'];alpha=mask[y0:y1,x0:x1].astype('uint8')*255
            rgba=np.dstack([rgb[y0:y1,x0:x1],alpha]);ch,cw=rgba.shape[:2];desired=target[0]/target[1]
            nw,nh=(cw,int(cw/desired))if cw/ch>desired else(int(ch*desired),ch)
            left,top=(nw-cw)//2,(nh-ch)//2
            padded=cv2.copyMakeBorder(rgba,top,nh-ch-top,left,nw-cw-left,cv2.BORDER_CONSTANT,value=(0,0,0,0))
            if description['provider']=='flux':
                padded=np.dstack([cv2.resize(padded[...,:3],tuple(target)),cv2.resize(padded[...,3],tuple(target),interpolation=cv2.INTER_NEAREST)])
            path=out/'provider_crop.png';Image.fromarray(padded).save(path)
            provider_crop={'path':str(path),'target_wh':target.tolist(),'crop_xyxy':[x0,y0,x1,y1],'padding_xy':[left,top],
                           'provider':description['provider'],'alpha_interpolation':'nearest','source_depth':obj['observed']}
            source=str(path)
            if setting.get('infill',False):
                infilled=provider('image_edit',{'image':source,'task':'infill','image_edit_role':'objects','object_prompt':obj['prompt'],'prompt':''},out/'infill')
                infilled=provider('background_remove',{'image':infilled['path'],'max_side':setting.get('remove_bg_max_side',1024)},out/'infill_alpha')
                infilled.update(alpha_source='rembg',depth_frame='observed_original_only')
                image=np.asarray(Image.open(infilled['path']))
                if image.ndim!=3 or image.shape[-1]!=4 or not np.any(image[...,3]>0):
                    raise StageNeeds('NEEDS_REVIEW','RemBG returned no foreground alpha')
                source=infilled['path']
            if setting.get('upsample',True):
                enhanced=provider('image_edit',{'image':source,'task':'upsample','image_edit_role':'objects','object_prompt':obj['prompt'],'prompt':''},out/'upsample')
                if setting.get('remove_background',True):
                    enhanced=provider('background_remove',{'image':enhanced['path'],'max_side':setting.get('remove_bg_max_side',1024)},out/'upsample_alpha')
                    enhanced['alpha_source']='rembg'
                else:enhanced['alpha_source']='NOT_REFINED'
                enhanced['depth_frame']='observed_original_only'
            generated=enhanced or infilled
            image=np.asarray(Image.open(generated['path']))
            if image.ndim!=3 or not np.isfinite(image).all() or image.shape[-1]not in(3,4):raise ValueError('Invalid generated object image')
            if setting.get('remove_background',True) and(image.shape[-1]!=4 or not np.any(image[...,3]>0)):
                raise StageNeeds('NEEDS_REVIEW','RemBG returned no foreground alpha')
            if setting.get('check_valid',False):
                validity=provider('vlm',{'images':[obj['observed_rgb'],str(obj['mask']),generated['path']],'task':'object_validity',
                    'response_schema':object_validity_schema(),
                    'context':{'instance':obj,'scene_analysis':previous[5].get('scene_analysis')},'prompt':
                    'Compare observed RGB, its Mask and generated RGB for '+obj['prompt']+'. Check intact identity, foreground alpha, observed shape, foreign objects and protected measurements. Separate hidden geometry/unmeasured dimensions from observed damage. Preserve uncertain=true when warranted. Return every requested field.'},out/'validity')['answer']
                try:validity_gate=object_validity_gate(validity,obj['id'],sha(generated['path']))
                except StageNeeds as error:
                    write(folder/'object_progress.json',{'objects':result,'held_object':obj['id'],'gate':error.gate,
                        'dependencies':'Subsequent compilation requires all requested Object results; independence not inferred'})
                    raise
        cloud=out/'camera_points.npy';np.save(cloud,points)
        original_cloud=out/'original_points.npz';np.savez_compressed(original_cloud,camera_points=original_points,uv_processed=np.c_[xx_original,yy_original])
        final=enhanced or infilled or crops['focus']
        prepared_image={'path':final['path'],'sha256':sha(final['path']),'source':'enhanced'if enhanced else'infilled'if infilled else'observed_crop','depth_frame':'observed_original_only'}
        result.append({**obj,'crops':crops,'prepared_image':prepared_image,'provider_crop':provider_crop,'enhanced':enhanced,'infilled':infilled,'validity':validity,'validity_gate':validity_gate,'camera_points':str(cloud),
            'point_provenance':point_provenance,'original_points':str(original_cloud),'original_point_provenance':original_provenance})
        write(folder/'object_progress.json',{'objects':result,'status':'PARTIAL','physical_verified':False})
    return {'objects':result,'selected_frame_id':previous[5]['selected_frame_id'],
            'coordinate_frame':'object crop pixels / observed selected optical Camera XYZ',
            'upsampling_executed':setting.get('upsample',True)}


def meshes(candidate, config, previous, folder, provider):
    """Use the existing Codex + Sandbox Blender boundary for Mesh only."""
    from . import authoring
    from .calibration.hybrid import surface_mesh
    objects=previous[6]['objects'];expected={o['id']for o in objects}
    if len(expected)!=len(objects):raise ValueError('Duplicate Stage6 modeling Object ID')
    preview=previous[3].get('semantic_preview')
    retained=copy.deepcopy(previous[5].get('scene_analysis'))
    bound=bound_analysis(candidate,retained)if retained and retained.get('constraint_binding')else None
    partial_inputs=previous[5].get('mode')=='observed_only'
    if bound:
        source_ids={o['id']for o in previous[5]['objects']}
        if source_ids!=expected:raise ValueError('Stage5/Stage7 modeling Object IDs disagree')
        for obj in objects:
            if obj['role']!=bound['objects'][obj['id']]['role']:raise ValueError('Stage5/Stage7 modeling Object roles disagree')
            if obj.get('memo_binding')!=bound['objects'][obj['id']]['shape_constraints']['memo_binding']:
                raise ValueError('Stage5/Stage7 Memo constraint binding changed or lost')
    if preview:
        analysis=preview['scene_analysis']
        if not bound and analysis.get('validation',{}).get('status')!='FULL':
            raise StageNeeds('NEEDS_REVIEW','Scene Memo constraints require review before Mesh generation',
                             code='MEMO_CONSTRAINT_REVIEW',classification='OBJECT_REVIEW')
        raw={r['id']:r for r in read(analysis['path'])['objects']};required=set()
        for name,spec in preview['objects'].items():
            if bound and name in bound.get('reused_rig_components',[]):continue
            memo_geometry=(raw[name].get('geometry')or{}).get('source')=='user_memo'
            if spec['role']in('manipulable_object','receptacle','workspace','fixture')or(spec['role']=='background'and memo_geometry):
                required.add(name)
            if spec['role']=='support_surface'and not config.get('support_asset'):
                required.add(name)
        missing=required-expected
        if missing and not(bound and partial_inputs):raise StageNeeds('NEEDS_REVIEW','Scene Memo Objects have no modeling observations: '+', '.join(sorted(missing)),
            code='MEMO_OBJECT_MISSING',classification='OBJECT_REVIEW',scope='object',object_ids=sorted(missing))
    path=candidate.root/'reconstruction-config.yaml'
    local=read(path)if path.is_file()else copy.deepcopy(config)
    for key in('codex','modeling','execute_modeling','max_modeling_calls'):
        if key in config:local[key]=copy.deepcopy(config[key])
    local['authoring_mode']='codex'
    local['stage_source_views']=[{**frame,'path':Path(frame['path']).relative_to(candidate.project.root).as_posix(),
        'camera':frame['source_camera']or 'reference_'+frame['id'],'camera_type':'external','split':'train'}for frame in previous[1]['frames']]
    if retained:
        from .evidence import scene_memo
        memo=scene_memo(candidate.project);source=Path(retained['path'])
        if sha(source)!=retained['sha256']or retained['memo_sha256']!=memo['sha256']or retained['guidance_sha256']!=authoring._codex_guidance()[1]['sha256']:
            raise ValueError('Stage5 semantic analysis identity changed')
        if any(sha(r['path'])!=r['sha256']for r in retained['source_images']):raise ValueError('Stage5 semantic source changed')
        answer=read(source);records=retained['source_images']
        parsed=copy.deepcopy(bound['objects'])if bound else authoring.parse_scene_analysis(answer,memo,{r['id']for r in records},
            existing_objects=[o['id']for o in candidate.scene['objects']],image_records=records,
            robot_links=[f.removeprefix('robot_link_')for f in candidate.scene.get('frames',{})if f.startswith('robot_link_')])
        if not expected<=parsed.keys():raise StageNeeds('NEEDS_REVIEW','Stage5 semantic analysis omitted an observed Instance')
        reused={name for name,spec in parsed.items()if spec.get('robot_rig_component')
            or(spec['role']=='reference_robot'and candidate.scene.get('robot_model'))}
        # Explicit Rig reuse also supersedes retained per-component authoring
        # settings. Keep the input Memo/config file intact; filter this run's
        # modeling copy so old hardware requests cannot recreate the accessory.
        local['objects']={name:spec for name,spec in local.get('objects',{}).items()if name not in reused}
        for name,spec in parsed.items():
            if spec.get('robot_rig_component')or(spec['role']=='reference_robot'and candidate.scene.get('robot_model')):continue
            if name not in expected and not spec.get('robot_attachment'):continue
            old=local.get('objects',{}).get(name,{})
            measured=old.get('geometry',{})
            proposed=spec.get('geometry',{})
            if measured.get('provenance')in('measured','calibrated'):
                if proposed and any(a is not None and b is not None and not np.isclose(a,b,rtol=1e-9,atol=1e-12)for a,b in zip(measured['dimensions_m'],proposed['dimensions_m'])):
                    raise ValueError('Stage5 analysis conflicts with protected measurements')
                spec['geometry']=copy.deepcopy(measured)
            for key in ('asset_manifest','modeling_action','modeling_request_id'):
                if key in old:spec[key]=copy.deepcopy(old[key])
            local.setdefault('objects',{})[name]=spec
        authoring.geometry_specs(local,candidate.scene)
        retained['stage_source_views_sha256']=stage_digest(local['stage_source_views'])
        local['stage_scene_analysis']=retained
        local['task']=authoring.task_intent(answer,parsed)
        local['capture_layouts']=answer.get('capture_layouts',[])
    local.setdefault('objects',{})
    for obj in objects:
        local['objects'].setdefault(obj['id'],{'prompt':obj['prompt'],'role':obj['role']})
    local['prepared_objects']={o['id']:{'image':o['observed_rgb'],'image_id':o['source_frame_id'],
        'mask':o['mask'],'observed':o['observed'],'crops':list(dict.fromkeys([x['path']for x in o['crops'].values()]+
        ([(o.get('prepared_image')or o.get('enhanced')or o.get('infilled'))['path']]if o.get('prepared_image')or o.get('enhanced')or o.get('infilled')else[]))),'provenance':o['provenance']}for o in objects}
    local['composition_feedback']={'stage_owner':'Stage8 CPD owns final object pose; author Mesh only',
                                   'required_instance_ids':sorted(expected)}
    if bound:
        local['composition_feedback'].update(memo_constraints={k:copy.deepcopy(bound[k])for k in(
            'schema','memo_sha256','source_plan_sha256','groups','constraints','assemblies','unresolved','scene_registration')},
            modeling_scope='OBSERVED_OBJECTS_ONLY'if partial_inputs else'FULL_REQUESTED_OBJECTS',
            deferred_instance_ids=sorted(set(bound['objects'])-expected),scene_complete=False)
        local['composition_feedback']['reused_rig_components']=bound.get('reused_rig_components',[])
        if partial_inputs:
            # Keep non-observed assembly/support requirements explicit, without
            # manufacturing their geometry or blocking independent Object inputs.
            deferred=set(local['objects'])-expected
            local['composition_feedback']['deferred_instance_ids']=sorted(
                set(local['composition_feedback']['deferred_instance_ids'])|deferred)
            local['objects']={n:s for n,s in local['objects'].items()if n in expected}
    maximum=config.get('max_modeling_calls',6)
    state_path=folder/'calls.json';calls=read(state_path)['calls']if state_path.is_file()else 0
    while True:
        candidate.project.checkpoint();write(path,local)
        task=authoring.modeling_tasks(candidate,local,{})
        if task['status']=='ASSETS_READY':break
        if not config.get('execute_modeling',False):raise StageNeeds('NEEDS_RUNTIME','Codex Mesh authoring requires explicit run-modeling execution')
        if calls>=maximum:raise StageNeeds('NEEDS_RUNTIME','Codex modeling call budget reached; completed assets retained')
        # Persist attempted-call accounting even when authentication/quota fails.
        try:
            response=authoring.run_codex_modeling(candidate,timeout_s=config.get('modeling_timeout_s',900))
        except Exception as error:
            if getattr(error,'remote_attempted',False):calls+=1;write(state_path,{'calls':calls})
            if isinstance(error,InterruptedError):raise
            if getattr(error,'code',None):raise StageNeeds('NEEDS_RUNTIME','Codex '+str(error.code)+'; assets and stage calls retained',code=error.code)from None
            raise
        if not response.get('reused'):calls+=1
        write(state_path,{'calls':calls})
        if response['status']=='ANALYZED_OBJECT_PROPOSALS':
            saved=Path(response.get('configuration',candidate.root/'review-config.yaml'));updated=read(saved)
            # Model-reference bodies may be explicitly attached to a real link,
            # but they never become extra observed Scene instances through naming.
            extras=set(updated.get('objects',{}))-expected
            if any(not updated['objects'][name].get('robot_attachment')for name in extras):
                raise StageNeeds('NEEDS_REVIEW','Codex Memo analysis changed the observed Instance set')
            local={**local,**updated,'prepared_objects':local['prepared_objects']}
            continue
        if response['status']not in('REGISTERED_UNVALIDATED','ASSETS_READY'):
            raise StageNeeds('NEEDS_RUNTIME','Codex/Blender did not produce validated native assets')
    attached=authoring.attach_modeled_assets(candidate,local,{})
    if attached.get('needs'):raise StageNeeds('NEEDS_REVIEW','; '.join(attached['needs']))
    result=[];nodes={o['id']:o for o in candidate.scene['objects']}
    for obj in objects:
        if obj['id']not in nodes:raise StageNeeds('NEEDS_MORE_DATA','Missing modeled Object '+obj['id'])
        node=nodes[obj['id']];mesh=surface_mesh(node,candidate.scene,candidate.project.root)
        file=folder/(obj['id']+'.obj');mesh.export(file,file_type='obj')
        constraints=node['dimensions'].get('constraints',{})
        measured=node['dimensions']['provenance']in('measured','calibrated')or any(v is not None for v in constraints.get('value',constraints.get('dimensions_m',[])))
        result.append({**obj,'mesh':str(file),'mesh_sha256':sha(file),'asset_reference':node.get('object_asset'),
                       'scale_protected':measured,'pose_owner':'Stage8','source_dimensions':node['dimensions']})
    return {'objects':result,'modeling_calls':calls,'coordinate_frame':'native Object-local mesh in m',
            'world_pose_authored_by_codex':False}


def poses(candidate, config, previous, folder, provider):
    result=[];review=[]
    for obj in previous[7]['objects']:
        candidate.project.checkpoint()
        if obj.get('point_provenance',{}).get('selected_points',10)<10:
            review.append(obj['id']);continue
        if obj.get('point_provenance'):
            points=np.load(obj['camera_points'])
            if points.ndim!=2 or points.shape[1]!=3 or not np.isfinite(points).all():raise ValueError('Invalid selected CPD point array')
            if np.linalg.matrix_rank(points-points.mean(0))<2:
                review.append(obj['id']);continue
        fit=provider('cpd',{'mesh':obj['mesh'],'points':obj['camera_points'],
            'scale_protected':obj['scale_protected'],'samples':config.get('pose',{}).get('samples',10),
            'surface_samples':config.get('pose',{}).get('surface_samples',10000)},folder/obj['id'])
        r=np.asarray(fit['rotation'],float);t=np.asarray(fit['translation'],float);s=fit['scale']
        if r.shape!=(3,3)or t.shape!=(3,):raise ValueError('Invalid pose dimensions')
        if not np.isfinite(r).all()or not np.isfinite(t).all()or not np.isfinite(s)or s<=0 or not np.allclose(r@r.T,np.eye(3),atol=1e-4)or not np.isclose(np.linalg.det(r),1,atol=1e-4):raise ValueError('Invalid CPD transform')
        if obj['scale_protected']and not np.isclose(s,1,rtol=0,atol=1e-8):raise ValueError('CPD attempted to change protected measured dimensions')
        quality=fit.get('quality',{'accuracy_verified':False,'status':'NOT_RECORDED'})
        write(folder/(obj['id']+'_fit_quality.json'),{'object_id':obj['id'],'fit':fit,'point_provenance':obj.get('point_provenance',{'status':'NOT_RECORDED'})})
        if quality.get('degenerate'):
            review.append(obj['id']);continue  # Other independent fits may still be retained.
        if obj.get('point_provenance',{}).get('sensitivity_required'):
            original=obj.get('original_points')
            if not original:raise ValueError('Generated fit requires retained original-only sensitivity input')
            with np.load(original)as a:points=a['camera_points']
            if len(points)<10 or np.linalg.matrix_rank(points-points.mean(0))<2:
                review.append(obj['id']);continue
            comparison=folder/(obj['id']+'_original_only.npy');np.save(comparison,points)
            baseline=provider('cpd',{'mesh':obj['mesh'],'points':str(comparison),'scale_protected':obj['scale_protected'],
                'samples':config.get('pose',{}).get('samples',10),'surface_samples':config.get('pose',{}).get('surface_samples',10000)},folder/obj['id']/'original_only')
            fit['generated_sensitivity']={'original_only_fit':baseline,'selected_fit_uses_generated':True,'accuracy_verified':False,
                'translation_delta_m':float(np.linalg.norm(t-np.asarray(baseline['translation']))),'scale_delta':float(s-baseline['scale'])}
        if config.get('pose',{}).get('foundationpose',False):
            cpd_diagnostics=copy.deepcopy(fit)
            fit=provider('foundationpose',{'mesh':obj['mesh'],'observed':obj['observed'],'initial_fit':fit},folder/obj['id']/'foundationpose')
            fit['cpd_diagnostics']=cpd_diagnostics
        r=np.asarray(fit['rotation'],float);t=np.asarray(fit['translation'],float);s=fit['scale']
        if type(s)not in(int,float)or s<=0 or not np.isfinite(s)or r.shape!=(3,3)or t.shape!=(3,)or not np.isfinite(t).all()or not np.allclose(r@r.T,np.eye(3),atol=1e-4)or not np.isclose(np.linalg.det(r),1,atol=1e-4):raise ValueError('Invalid final native pose transform')
        if obj['scale_protected']and not np.isclose(s,1,rtol=0,atol=1e-8):raise ValueError('Final pose changed protected scale')
        from .calibration.canonicalization import native_tilt,native_yaw_snap
        import trimesh
        options=config.get('pose',{});candidates=fit.get('candidate_fits',[fit]);gravity=np.asarray(previous[4]['camera_to_support'])[:3,:3].T@np.array([0.,0,1.])
        tilt,tilt_info=native_tilt([x['rotation']for x in candidates],gravity,enabled=options.get('bake_fitted_tilt','auto'),shape_model='codex_blender')
        canonical=tilt;orientation={'tilt':tilt_info,'front':{'status':'DISABLED'},'symmetry':'NOT_VERIFIED'}
        if options.get('canonicalize_front',True):
            front=provider('canonicalize',{'mesh':obj['mesh'],'tilt_rotation':tilt.tolist(),'photo':obj.get('observed_rgb'),
                'category':obj.get('prompt'),'refine':bool(options.get('front_refine',True)and tilt_info['status']=='baked')},folder/obj['id']/'front')
            f=np.asarray(front['rotation']);canonical=f@tilt;orientation['front']=front['front']
            if not np.allclose(f@f.T,np.eye(3),atol=1e-8)or not np.isclose(np.linalg.det(f),1):raise ValueError('Invalid semantic-front rotation')
        if tilt_info['status']=='baked' and options.get('front_yaw_snap',True):
            mesh=trimesh.load(obj['mesh'],force='mesh',process=False);snap,snap_info=native_yaw_snap(np.asarray(mesh.vertices)@canonical.T)
            canonical=snap@canonical;orientation['yaw_snap']=snap_info
        if obj['scale_protected']and not np.allclose(canonical,np.eye(3),atol=1e-8):
            raise StageNeeds('NEEDS_REVIEW','Canonical rotation changes protected dimension axes; explicit measured-axis mapping required')
        fit={**fit,'rotation':(r@canonical.T).tolist()}
        orientation['rotation']=canonical.tolist();orientation['world_geometry_preserved']=True
        result.append({**obj,'fit':fit,'canonicalization':orientation,'status':'UNVERIFIED','coordinate_frame':'selected optical Camera'})
        write(folder/'object_progress.json',{'objects':result,'review':review,'accuracy':'NOT_VERIFIED'})
    if review:
        write(folder/'object_progress.json',{'objects':result,'review':review,'accuracy':'NOT_VERIFIED'})
        raise StageNeeds('NEEDS_REVIEW','Degenerate or unsupported observed pose fit',code='CPD_GEOMETRY',classification='OBJECT_REVIEW',scope='object',object_ids=review)
    return {'objects':result,'coordinate_frame':'mesh-to-selected-optical-Camera','accuracy':'NOT_VERIFIED'}


def articulate(candidate, config, previous, folder, provider):
    """Rigid scenes legitimately omit articulation; unsupported joints never pass."""
    requested=config.get('articulation',{}).get('objects',[])
    if requested:
        raise StageNeeds('NOT_SUPPORTED','Articulation: original articulate-anything/Hunyuan part generation has no verified native USD joint adapter; preserve the existing Robot URDF')
    return {'objects':[], 'applicable':False,'reason':'No articulated Object requested',
            'robot_model_changed':False,'articulation_executed':False}


def resolve_stage_world(config, robot, folder):
    """Reuse proper Sim(3) alignment with independent, explicitly paired anchors.

    Four board corners supply scale only. Robot World requires non-collinear
    corresponding points in that frame; validation anchors never enter the fit.
    Scale stays separate from the rigid transform and from calibration approval.
    """
    from .calibration.registration import align_points
    from .scene import transform
    report={'robot_world':'UNRESOLVED'if robot else'NOT_REQUESTED','metric_scale_estimate':None,
            'independent_accuracy_verified':False,'needs':[]}
    anchors=config.get('metric_anchors',[])
    scales=[]
    for anchor in anchors:
        if anchor.get('source')not in('measured','calibrated')or not anchor.get('evidence'):raise ValueError('Metric Anchor provenance required')
        qa=metric_qa(anchor['observed_corners_camera_m'],anchor['dimensions_xy_m'])
        p=np.asarray(anchor['observed_corners_camera_m'],float);w,h=anchor['dimensions_xy_m']
        lengths=np.linalg.norm(np.roll(p,-1,axis=0)-p,axis=1)
        scales.append(float(lengths@np.array([w,h,w,h])/(lengths@lengths)))
        report.setdefault('board_qa',[]).append(qa)
    if scales:report['metric_scale_estimate']=float(np.median(scales))
    supplied=config.get('world_registration')
    if supplied:
        if supplied.get('provenance')not in('measured','calibrated')or not supplied.get('evidence'):raise ValueError('World registration needs independent measured/calibrated provenance')
        transform(supplied['support_to_world'])
        report.update(robot_world='EXPLICIT',scale_policy='Existing metric coordinates retained; scale QA is diagnostic')
        write(folder/'world_resolution.json',report)
        return copy.deepcopy(supplied),report
    rows=config.get('sensor_registration',{}).get('world_anchors',[])
    if rows:
        expected={'id','group_id','split','support_point','robot_world_point_m','source','evidence'}
        for r in rows:
            if set(r)!=expected or r['split']not in('train','validation')or r['source']not in('measured','calibrated')or not r['evidence']or not r['id']or not r['group_id']:
                raise ValueError('Independent world anchor identity/provenance/split required')
            for k in('support_point','robot_world_point_m'):
                if np.asarray(r[k]).shape!=(3,)or not np.isfinite(np.asarray(r[k],float)).all():raise ValueError('Finite world anchor Nx3 correspondence required')
        if len({r['id']for r in rows})!=len(rows):raise ValueError('Duplicate world anchor ID')
        train=[r for r in rows if r['split']=='train'];held=[r for r in rows if r['split']=='validation']
        if {r['group_id']for r in train}&{r['group_id']for r in held}or any(
            a[k]==b[k]for a in train for b in held for k in('support_point','robot_world_point_m')):
            raise ValueError('World anchor train/holdout leakage')
        fit=align_points(np.asarray([r['support_point']for r in train]).reshape(-1,3),
                         np.asarray([r['robot_world_point_m']for r in train]).reshape(-1,3),estimate_scale=True)
        report.update(anchor_sha256=stage_digest(rows),fit=fit,train_ids=[r['id']for r in train],holdout_ids=[r['id']for r in held])
        if fit['status']=='ESTIMATED':
            R=np.asarray(fit['T_target_source'])[:3,:3];t=np.asarray(fit['T_target_source'])[:3,3];s=fit['scale']
            residual=[float(np.linalg.norm(s*R@r['support_point']+t-r['robot_world_point_m']))for r in held]
            report.update(robot_world='ESTIMATED',metric_scale_estimate=s,train_rmse_m=fit['rmse'],
                holdout_rmse_m=float(np.sqrt(np.mean(np.square(residual))))if residual else None,
                holdout_residual_m=residual,needs=[]if residual else['Independent validation anchors not recorded'])
            registration={'support_to_world':fit['T_target_source'],'scale':s,'provenance':'estimated',
                'evidence':['Independent paired support/Robot World anchors SHA '+stage_digest(rows)],
                'method':'paired_world_anchors','anchor_sha256':stage_digest(rows)}
            write(folder/'world_resolution.json',report)
            return registration,report
        report['needs'].extend(fit.get('needs',[]))
    if robot:
        report['needs']+=['Provide >=3 non-collinear support/Robot World point pairs with measured metric coordinates and evidence',
            'Board dimensions alone do not determine Robot Base pose; alternatively localize >=4 diverse measured-q Wrist poses against a common metric cloud and review shared FK/mount consistency']
        write(folder/'world_resolution.json',report)
        raise StageNeeds('NEEDS_MORE_DATA','Robot World UNRESOLVED: '+ '; '.join(report['needs']),
            code='ROBOT_WORLD_REQUIRED',classification='DEPENDENCY_BLOCK')
    write(folder/'world_resolution.json',report)
    return None,report


def registered_world_pose(registration, support_pose):
    """Apply a similarity to a pose without scaling its rotation matrix."""
    from .scene import transform
    local=transform(support_pose).copy();local[:3,3]*=float((registration or{}).get('scale',1.))
    return transform(registration['support_to_world'])@local if registration else local


def stage_sensor_clouds(candidate, scene, previous, folder, registration):
    """Retain original pixel/point evidence in an explicit diagnostic gauge."""
    from .scene import transform
    from .observations import source_record_digest
    from .scene import camera_calibration_signature
    from PIL import Image
    import cv2
    scene=copy.deepcopy(scene);clouds=scene.setdefault('reconstruction_observations',{}).setdefault('clouds',[])
    existing={(row['image_id'],row['object_id'])for row in clouds}
    images={image['id']:image for image in candidate.project.evidence['images']}
    for obj in previous[6]['objects']:
        file=obj.get('original_points')
        if not file:raise StageNeeds('NEEDS_MORE_DATA','Original pixel/point correspondence required: '+obj['id'],code='SENSOR_CORRESPONDENCES',classification='DEPENDENCY_BLOCK')
        with np.load(file)as a:points=a['camera_points'];pixels=a['uv_processed']
        frame=next(f for f in previous[2]['frames']if f['id']==obj['source_frame_id'])
        if frame['role']!='scene_photo':continue  # Video frames are not Project sensor-binding observations.
        if (frame['id'],obj['id'])in existing:continue
        image=images[frame['id']]
        index=previous[2]['frames'].index(frame);A=np.asarray(previous[2]['original_to_processed'][index],float)
        if A.shape!=(3,3)or not np.isfinite(A).all()or not np.allclose(A[2],[0,0,1])or abs(np.linalg.det(A))<1e-12:raise ValueError('Valid original-to-processed pixel affine required')
        if points.shape!=(len(pixels),3)or pixels.shape[1:]!=(2,)or not np.isfinite(points).all()or not np.isfinite(pixels).all():raise ValueError('Original point correspondence mismatch')
        T=transform(previous[4]['camera_to_support']);W=transform(registration['support_to_world']);scale=float(registration.get('scale',1.))
        uv=np.c_[pixels,np.ones(len(pixels))]@np.linalg.inv(A).T
        support_points=points@T[:3,:3].T+T[:3,3]
        target=folder/(obj['id']+'_sensor_cloud.npz');np.savez_compressed(target,uv_original=uv[:,:2]/uv[:,2:],points_world_m=(support_points*scale)@W[:3,:3].T+W[:3,3])
        mask=np.asarray(Image.open(obj['mask']).convert('L'))
        width,height=image['resolution']
        original_mask=cv2.warpPerspective(mask,np.linalg.inv(A),(width,height),flags=cv2.INTER_NEAREST)
        if not np.any(original_mask):raise StageNeeds('NEEDS_MORE_DATA','No original photo Mask pixels for render refinement')
        mask_path=folder/(obj['id']+'_original_mask.png');Image.fromarray(original_mask).save(mask_path)
        camera=next(c for c in scene['cameras']if c['id']==image['camera'])
        clouds.append({'image_id':frame['id'],'object_id':obj['id'],'path':target.relative_to(candidate.project.root).as_posix(),
            'sha256':sha(target),'mask':mask_path.relative_to(candidate.project.root).as_posix(),'mask_sha256':sha(mask_path),
            'camera':image['camera'],'split':image['split'],'group_id':image['group_id'],'units':'m','frame':'world',
            'points':len(points),'identity_verified':False,'depth_source':'DA3 estimated; anchor-constrained scale',
            'geometry_binding':'fixed_world',
            'dependencies':{'image_sha256':image['sha256'],'image_record_sha256':source_record_digest(image),
                'camera_signature':camera_calibration_signature(scene,camera)},
            'provenance':'original RGB with DA3-estimated Z and anchor-constrained scale; not independently measured points'})
        existing.add((frame['id'],obj['id']))
    return scene


def resolve_sensor_world(candidate, config, scene, previous, folder, world_report):
    """Initialize Robot Base from metric support + existing shared FK/hand-eye.

    The temporary support gauge is explicitly not Robot World. Only a full-rank
    measured-q motion fit supplies its transform; partial estimates stay local
    diagnostic drafts and never replace Candidate calibration.
    """
    from . import observations
    from .scene import transform,value,frame_world
    report=copy.deepcopy(world_report);scale=report.get('metric_scale_estimate')
    base=scene.get('frames',{}).get('robot_base',{})
    if not scene.get('robot_model')or scale is None or config.get('sensor_registration',{}).get('enabled')is False:
        raise StageNeeds('NEEDS_MORE_DATA','Robot World UNRESOLVED: independent metric corners and archived measured-q Robot model required',code='ROBOT_WORLD_REQUIRED',classification='DEPENDENCY_BLOCK')
    if base.get('parent')!='world':
        raise StageNeeds('NEEDS_REVIEW','Existing Robot Base hierarchy requires explicit Support registration',code='ROBOT_WORLD_REQUIRED',classification='DEPENDENCY_BLOCK')
    protected_base=base['transform']['provenance']in('measured','calibrated')
    protected_world=any(c['frame']=='world'and c['pose']['provenance']in('measured','calibrated')for c in scene.get('cameras',[]))or any(
        o['frame']=='world'and o['pose']['provenance']in('measured','calibrated')for o in scene.get('objects',[]))
    if protected_world and not protected_base:
        raise StageNeeds('NEEDS_MORE_DATA','Preserve existing calibrated World: Robot Base pose or independent Support/World anchors required',code='ROBOT_WORLD_REQUIRED',classification='DEPENDENCY_BLOCK')
    out=folder/'support_sensor_initialization';out.mkdir(exist_ok=True)
    relative={'support_to_world':np.eye(4).tolist(),'scale':scale}  # Support-to-support gauge only.
    draft=stage_sensor_clouds(candidate,scene,previous,out,relative)
    local=copy.deepcopy(config)
    local['image_ids']=[i['id']for i in candidate.project.evidence['images']if i.get('capture_manifest')and i.get('camera_type')=='wrist']
    if not local['image_ids']:
        raise StageNeeds('NEEDS_MORE_DATA','Robot World UNRESOLVED: no Wrist Capture with measured q; fixed Side alone cannot locate Robot Base',code='ROBOT_WORLD_REQUIRED',classification='DEPENDENCY_BLOCK')
    candidate.project.checkpoint()
    result=observations.register_sensor_views(candidate,local,scene=draft,persist=False,initialize_base=True)
    candidate.project.checkpoint()
    draft=result.pop('scene',draft);write(out/'registration.json',result);write(out/'support_gauge_scene.yaml',draft)
    motions=[r for r in result.get('diagnostics',[])if r.get('motion',{}).get('status')=='OPTIMIZED'and r['motion'].get('rank',0)>=13]
    report.update(support_sensor_registration=result,gauge='temporary support metric frame; not Robot World',
        robot_world='UNRESOLVED',independent_accuracy_verified=False)
    if not motions:
        report['needs']=result.get('needs',[])+['Localize >=4 diverse measured-q Wrist poses against unchanged metric Photo points; shared mount/base motion fit must be full rank']
        write(folder/'world_resolution.json',report)
        raise StageNeeds('NEEDS_MORE_DATA','Robot World UNRESOLVED: '+'; '.join(report['needs']),code='ROBOT_WORLD_REQUIRED',classification='DEPENDENCY_BLOCK')
    motion=motions[0]['motion'];B=transform(motion['T_relative_base'])
    W=(frame_world(scene,'robot_base')if protected_base else np.eye(4))@np.linalg.inv(B)
    from scipy.spatial.transform import Rotation
    for other in motions[1:]:
        T=transform(other['motion']['T_relative_base'])
        if np.linalg.norm(T[:3,3]-B[:3,3])>1e-6 or np.linalg.norm(Rotation.from_matrix(T[:3,:3]@B[:3,:3].T).as_rotvec())>1e-6:
            report['needs']=['Multiple Wrist fits disagree on shared Robot Base; review cross-sensor consistency']
            write(folder/'world_resolution.json',report)
            raise StageNeeds('NEEDS_REVIEW',report['needs'][0],code='ROBOT_BASE_CONFLICT',classification='DEPENDENCY_BLOCK')
    # The new World gauge is the base located by measured-q FK, not an invented identity.
    if not protected_base:
        draft['frames']['robot_base']['transform']=value(np.eye(4).tolist(),'estimated',
            ['Robot Base gauge derived from full-rank shared Wrist FK/mount fit; not independent calibration'])
    # Photo clouds/registrations are rebuilt below in the resolved World frame.
    draft.pop('view_registrations',None)
    registration={'support_to_world':W.tolist(),'scale':scale,'provenance':'estimated','method':'wrist_fk_metric_support',
        'anchor_sha256':stage_digest(config['metric_anchors']),
        'evidence':['Explicit full metric Support corners + full-rank measured-q FK/shared mount fit'],
        'support_from_robot_base':B.tolist()}
    report.update(robot_world='ESTIMATED',gauge='Existing protected Robot Base World'if protected_base else'Robot Base estimated from shared measured-q FK',
        needs=['Independent Robot Base/Side/Wrist holdout accuracy remains NOT_VERIFIED'],motion=motion)
    write(folder/'world_resolution.json',report)
    return registration,draft,report


def register_stage_sensors(candidate, config, scene, previous, folder, *, resolved_registration=None):
    """Bridge retained original points to existing sensor registration atomically.

    No new Camera solver: explicit metric evidence first, then existing shared
    Side/PnP and Wrist measured-q/FK routines. Joint refinement still needs
    reviewed landmarks and independent pairs; it is not silently run here.
    """
    from . import observations
    from .scene import transform
    captures=[i for i in candidate.project.evidence['images']if i.get('capture_manifest')and observations.camera_type(i)in('side','wrist')]
    options=config.get('sensor_registration',{})
    if not captures or options.get('enabled')is False:
        return scene,{'status':'NOT_REQUESTED'if captures else'NOT_AVAILABLE','physical_verified':False,
                      'needs':['Sensor registration deferred; final approval unverified']if captures else[]}
    anchors=config.get('metric_anchors',[]);registration=resolved_registration or config.get('world_registration')
    method=(resolved_registration or{}).get('method')
    identity=options.get('world_anchors',[])if method=='paired_world_anchors'else anchors
    automatic=bool(resolved_registration and method in('paired_world_anchors','wrist_fk_metric_support')
        and resolved_registration.get('anchor_sha256')==stage_digest(identity))
    if not anchors and not automatic:
        raise StageNeeds('NEEDS_MORE_DATA','Independent measured Metric Anchor required before Robot World/sensor registration',
            code='METRIC_ANCHOR_REQUIRED',classification='DEPENDENCY_BLOCK')
    if not scene.get('robot_model')or not registration:
        raise StageNeeds('NEEDS_MORE_DATA','Robot model, measured-q mapping and explicit support-to-Robot World registration required',
            code='ROBOT_WORLD_REQUIRED',classification='DEPENDENCY_BLOCK')
    if not automatic and(registration.get('provenance')not in('measured','calibrated')or not registration.get('evidence')):raise ValueError('Protected World registration provenance required')
    for anchor in anchors:
        if anchor.get('source')not in('measured','calibrated')or not anchor.get('evidence'):raise ValueError('Metric Anchor provenance required')
        metric_qa(anchor['observed_corners_camera_m'],anchor['dimensions_xy_m'])
    review=options.get('metric_review',{})
    if not automatic and(review.get('accepted')is not True or review.get('anchors_sha256')!=stage_digest(anchors)or not review.get('evidence')):
        raise StageNeeds('NEEDS_REVIEW','Metric QA requires explicit review bound to current Anchor SHA; no automatic scale certification',
            code='METRIC_REVIEW_REQUIRED',classification='DEPENDENCY_BLOCK',input_sha256=stage_digest(anchors))
    scene=stage_sensor_clouds(candidate,scene,previous,folder,registration)
    reports=[]
    if options.get('view_anchors'):
        result=observations.register_views(candidate,options['view_anchors'],scene_state=config.get('scene_state_id'),scene=scene,persist=False)
        scene=result.pop('scene');reports.append(result)
    result=observations.register_sensor_views(candidate,config,scene=scene,persist=False)
    scene=result.pop('scene',scene);reports.append(result)
    ids={r['image_id']for r in result['views']};missing=[i['id']for i in captures if i['id']not in ids]
    report={'status':result['status'],'reports':reports,'needs':result.get('needs',[]),'missing_capture_ids':missing,
        'physical_verified':False,'metric_accuracy_verified':False,'joint_refinement':{'status':'NOT_RUN','needs':['Reviewed CAD landmarks and independent measured-q pairs required']}}
    write(folder/'sensor_registration.json',report)
    if missing or result.get('needs')or any(r.get('needs')for r in reports):
        write(folder/'sensor_partial_scene.yaml',scene)
        raise StageNeeds('NEEDS_MORE_DATA','Sensor registration incomplete: '+('; '.join(report['needs'])or'eligible captures/metric correspondences/measured-q FK missing'),
            code='SENSOR_REGISTRATION_INCOMPLETE',classification='DEPENDENCY_BLOCK')
    joint=options.get('joint',{})
    landmarks=candidate.project.evidence.get('landmarks',[])+scene.get('derived_observations',{}).get('landmarks',[])
    if joint.get('enabled',True)and landmarks:
        from .calibration.joint import fit_joint_scene
        candidate.project.checkpoint()
        before=scene
        scene,report['joint_refinement']=fit_joint_scene(candidate.project,scene,{k:v for k,v in joint.items()if k!='enabled'})
        solver=report['joint_refinement']
        # Match Numeric Refinement's application gate. A lower residual may
        # still be a rank-deficient diagnostic draft for direct/Hybrid callers.
        if solver.get('status')=='IMPROVED'and solver.get('jacobian_rank',-1)<solver.get('parameter_count',0):
            scene=before
            report['joint_refinement']={**solver,'status':'UNRESOLVED','solver_status':'IMPROVED','scene_adopted':False,
                'needs':solver.get('needs',[])+['Rank-deficient shared Camera/Base/Object fit retained as diagnostic; pre-fit Scene is unchanged']}
        else:
            from .calibration.hybrid import reproject_observations
            scene=reproject_observations(candidate.project,scene,{},folder/'joint_observations')
        candidate.project.checkpoint()
    if options.get('render_refinement',{}).get('enabled',False):
        from .calibration.hybrid import fit_scene,alignment_metrics
        render_options={k:v for k,v in options['render_refinement'].items()if k!='enabled'}
        candidate.project.checkpoint()
        scene,report['render_refinement']=fit_scene(candidate.project,scene,folder/'sensor_fit',render_options)
        report['render_comparison']=alignment_metrics(candidate.project,scene,folder/'sensor_comparison',render_options)
        candidate.project.checkpoint()
    report['verification']={'side_reprojection':'See joint_refinement per-camera groups',
        'wrist_reprojection':'See joint_refinement per-camera groups',
        'shared_mount':'See registration motion rank/rmse; measured-q/FK fixed',
        'robot_base':'estimated consistency only; independent accuracy NOT_VERIFIED',
        'object_pose':'estimated joint changes; independent accuracy NOT_VERIFIED',
        'holdout':'See joint holdout groups / optional render comparison; absent means NOT_RECORDED'}
    write(folder/'sensor_registration.json',report)
    return scene,report


def compile_scene(candidate, config, previous, folder, provider):
    from .scene import value, transform, world_pose, validate
    scene=candidate.scene
    if not scene.get('robot_model'):
        captures=[i for i in candidate.project.evidence['images']if i.get('capture_manifest')and i.get('q_measured')is not None]
        if captures:
            from .automation import captured_robot
            robot_reference=captured_robot(candidate,captures);write(folder/'robot_reference.json',robot_reference);scene=candidate.scene
    from .calibration.wrist import initialize_gripper_mount
    scene,gripper=initialize_gripper_mount(candidate,scene,config,folder)
    robot=bool(scene.get('robot_model'))or any(o['role']=='reference_robot'for o in scene['objects'])
    try:registration,world_report=resolve_stage_world(config,robot,folder)
    except StageNeeds as error:
        if error.code!='ROBOT_WORLD_REQUIRED'or not scene.get('robot_model')or not config.get('metric_anchors'):raise
        registration,scene,world_report=resolve_sensor_world(candidate,config,scene,previous,folder,read(folder/'world_resolution.json'))
    world_scale=float((registration or{}).get('scale',1.))
    if robot and not config.get('metric_anchors')and not config.get('sensor_registration',{}).get('world_anchors'):
        raise StageNeeds('NEEDS_MORE_DATA','Independent measured Metric Anchor required before Robot World compilation',code='METRIC_ANCHOR_REQUIRED',classification='DEPENDENCY_BLOCK')
    W=np.eye(4)
    if registration:
        if registration.get('provenance')not in('measured','calibrated','estimated')or not registration.get('evidence'):
            raise ValueError('World registration needs independent measured/calibrated provenance')
        W=transform(registration['support_to_world'])
    T=transform(previous[4]['camera_to_support']);nodes={o['id']:o for o in scene['objects']}
    for obj in previous[8]['objects']:
        node=nodes[obj['id']];fit=obj['fit'];scale=float(fit['scale'])*world_scale
        if obj['scale_protected']and not np.isclose(world_scale,1,atol=1e-8,rtol=0):
            raise StageNeeds('NEEDS_REVIEW','Anchor scale changed: refit Stage8 against corrected original points before preserving measured Object '+obj['id'],
                code='METRIC_SCALE_REQUIRES_REFIT',classification='DEPENDENCY_BLOCK',object_ids=[obj['id']])
        source=np.asarray(obj['source_dimensions']['value'],float)
        canonical=np.asarray(obj.get('canonicalization',{}).get('rotation',np.eye(3)),float)
        rotated=not np.allclose(canonical,np.eye(3),atol=1e-8)
        if rotated or not np.isclose(scale,1,atol=1e-8,rtol=0):
            if obj['scale_protected']:raise ValueError('Protected measured geometry cannot be scaled')
            if node.get('object_asset'):
                from .object_assets import scaled_asset_operation
                operation=scaled_asset_operation(candidate,obj,scale,folder/obj['id'],rotation=canonical)
                from .editing import apply
                scene=apply(scene,[operation],candidate.project.root);nodes={o['id']:o for o in scene['objects']};node=nodes[obj['id']]
            else:
                if rotated:raise StageNeeds('NEEDS_REVIEW','Canonical baking requires an independently versioned Native Asset')
                node['dimensions']=value((source*scale).tolist(),'estimated',['Stage8 CPD estimated scale; accuracy unverified'])
        pose=np.eye(4);pose[:3,:3]=fit['rotation'];pose[:3,3]=fit['translation']
        pose=registered_world_pose(registration,T@pose)
        # SimFoundry: scale mesh, mesh-to-selected-camera, then camera-to-world.
        local=np.linalg.inv(world_pose(scene,{'frame':node['frame'],'pose':value(np.eye(4).tolist())}))@pose
        if node['pose']['provenance']in('measured','calibrated'):
            if not np.allclose(node['pose']['value'],local,rtol=0,atol=1e-8):raise StageNeeds('NEEDS_REVIEW','CPD disagrees with protected Object pose '+obj['id'])
        else:node['pose']=value(local.tolist(),'estimated',['Stage8 CPD + original support transform; NOT_VERIFIED'])
    with np.load(previous[2]['prediction'])as arrays:
        for i,frame in enumerate(previous[2]['frames']):
            name=frame['source_camera']or 'reference_'+frame['id']
            camera=next((c for c in scene['cameras']if c['id']==name),None)
            if camera and camera.get('camera_type')in('side','wrist'):raise ValueError('Photo Camera conflicts with a robot sensor')
            E=np.eye(4);E[:3]=arrays['extrinsics'][i]
            pose=registered_world_pose(registration,np.asarray(previous[4]['support_from_da3'])@np.linalg.inv(E))
            # K remains in the exact DA3 processed image frame.
            new={'id':name,'frame':'world','pose':value(pose.tolist(),'estimated',['DA3 multiview World-to-Camera inversion']),
                 'K':value(arrays['intrinsics'][i].tolist(),'estimated',['DA3 processed pixel frame']),
                 'distortion':value([0.]*5,'estimated',['DA3 pinhole assumption; not calibrated']),
                 'resolution':previous[2]['processed_resolution'],'camera_type':'external','purpose':'inspection',
                 'source_image_id':frame['id'],'source_sha256':frame['source_sha256'],
                 'original_to_processed':previous[2]['original_to_processed'][i]}
            if camera:
                if any(camera[k]['provenance']in('measured','calibrated')for k in('pose','K','distortion')):
                    raise StageNeeds('NEEDS_REVIEW','Preserve protected Photo calibration '+name)
                camera.update(new)
            else:scene['cameras'].append(new)
    if config.get('support_asset'):
        if not np.isclose(world_scale,1,atol=1e-8,rtol=0):
            raise StageNeeds('NEEDS_REVIEW','Explicit Support Asset transform must be reviewed in corrected metric frame',code='SUPPORT_METRIC_FRAME',classification='DEPENDENCY_BLOCK')
        from .object_assets import support_asset_operation
        from .editing import apply
        operation=support_asset_operation(candidate,config['support_asset'],W,folder/'support_asset')
        scene=apply(scene,[operation],candidate.project.root)
    scene,sensors=register_stage_sensors(candidate,config,scene,previous,folder,resolved_registration=registration)
    validate(scene,candidate.project.root)
    candidate.save(scene);write(folder/'compiled_scene.yaml',scene)
    return {'scene':str(folder/'compiled_scene.yaml'),'scene_sha256':sha(folder/'compiled_scene.yaml'),
            'coordinate_frame':'Robot World'if robot else'estimated support World',
            'robot_world_registered':bool(registration),'metric_verified':False,
            'world_resolution':world_report,'world_scale':world_scale,
            'gripper_initialization':gripper,
            'sensor_registration':sensors,
            'camera_policy':'Photo reference views preserved; Side/Wrist calibration and FK unchanged',
            'warnings':['DA3 metric scale and CPD poses remain unverified']}


def simulation_ready(candidate, config, previous, folder, provider):
    from .scene import value, validate, support_metrics
    scene=candidate.scene;properties=config.get('physics',{}).get('properties',{})
    if config.get('physics',{}).get('collision_decomposition'):
        raise StageNeeds('NOT_SUPPORTED','Additional CoACD/VHACD conversion has no verified native adapter; supply separate authored convex/compound collision via Stage7')
    unknown=[o for o in scene['objects']if o['role']=='manipulable_object'and
             any(o['physics'][f]['value']is None for f in('mass_kg','friction'))and o['id']not in properties]
    if unknown:
        # Original Stage11 asks the VLM for physical estimates. It is never a
        # measurement, and absence of a provider is an explicit Runtime stop.
        answer=provider('vlm',{'images':[o['observed_rgb']for o in previous[7]['objects']if o['id']in{o['id']for o in unknown}],
            'task':'physical_estimates','response_schema':typed_record({'objects':typed_record({o['id']:typed_record({'mass_kg':{'type':'number','minimum':0},'friction':{'type':'number','minimum':0}})for o in unknown})}),
            'prompt':'Estimate physical parameters for these instances, in order '+json.dumps([o['id']for o in unknown])+'. Return JSON {"objects": {ID: {"mass_kg": NUMBER, "friction": NUMBER}}}. Mass in kg, friction nonnegative. These are uncertain visual estimates.'},folder/'properties')['answer']
        if not isinstance(answer,dict)or set(answer)!={'objects'}:raise ValueError('Typed physical property estimates required')
        properties={**properties,**{name:{k:value(v,'estimated',['VLM visual physics estimate; NOT_MEASURED'])for k,v in row.items()}for name,row in answer['objects'].items()}}
    records=[]
    for obj in scene['objects']:
        if obj['visual']['type']=='unknown'or(obj.get('collision_enabled',True)and obj['collision']['type']=='unknown'):
            raise StageNeeds('NEEDS_MORE_DATA','Missing separate visual/collision geometry: '+obj['id'])
        for field,record in properties.get(obj['id'],{}).items():
            if field not in('mass_kg','friction')or not isinstance(record,dict)or record.get('provenance')not in('estimated','measured','calibrated')or not record.get('evidence'):
                raise ValueError('Explicit physical property provenance required')
            v=record['value']
            if type(v)not in(int,float)or not np.isfinite(v)or v<0 or(field=='mass_kg'and v==0):raise ValueError('Invalid physical estimate')
            old=obj['physics'][field]
            if old['value']is None:obj['physics'][field]=copy.deepcopy(record)
            elif old['provenance']in('measured','calibrated')and old!=record:raise ValueError('Protected measured physical property')
        if obj['role']=='manipulable_object'and any(obj['physics'][f]['value']is None for f in('mass_kg','friction')):
            raise StageNeeds('NEEDS_MORE_DATA','Unknown mass/friction: '+obj['id'])
        records.append({'id':obj['id'],'visual':obj['visual']['type'],'collision':obj['collision']['type'],
                        'physics':obj['physics'],'physical_verified':False})
    validate(scene,candidate.project.root,complete=True)
    contacts=support_metrics(scene,root=candidate.project.root)
    candidate.save(scene);write(folder/'ready_scene.yaml',scene)
    return {'scene':str(folder/'ready_scene.yaml'),'objects':records,'support_constraints':contacts,
            'physical_verified':False,'coordinate_frame':previous[10]['coordinate_frame'],
            'collision_scope':'existing native convex/compound validation; no visual-to-collision substitution'}


def stabilize(candidate, config, previous, folder, provider):
    steps=config.get('physics',{}).get('steps',500);engine=config.get('physics',{}).get('engine','mujoco')
    if type(steps)is not int or not 1<=steps<=10000:raise ValueError('Bounded 1..10000 physics steps required')
    if engine not in('mujoco','isaac'):raise ValueError('Unsupported native physics engine')
    result=provider('physics',{'project':str(candidate.project.root),'candidate':candidate.name,
        'scene':previous[11]['scene'],'engine':engine,'steps':steps},folder/'native')
    executed=result.get('_execution')=='real'
    count=result.get('mujoco',{}).get('steps',0)if engine=='mujoco'else result.get('isaac',{}).get('physics_steps',0)
    if executed and(count!=steps):raise StageNeeds('NEEDS_MORE_DATA','Native passive physics did not perform the requested steps')
    motion=result.get(engine,{}).get('objects',{});proposals=folder/'stabilized_pose_proposals.json'
    write(proposals,{'source_scene_sha256':stage_digest(candidate.scene),
        'objects':motion,'execution':'real'if executed else'mock','settled':result.get(engine,{}).get('settled'),
        'approved':False,'physical_verified':False})
    applied=False
    if config.get('physics',{}).get('apply_stabilized_poses',False):
        if not executed or count<=0 or result.get(engine,{}).get('settled')is not True or not motion:
            raise StageNeeds('NEEDS_REVIEW','Actual stable physics and per-object pose evidence required for application')
        from .validation import reviewed_stabilized_scene
        source_scene=read(previous[11]['scene'])
        updated=reviewed_stabilized_scene(source_scene,motion,config['physics'].get('pose_review',{}),candidate.project.root)
        current=stage_digest(candidate.scene)
        if current not in(stage_digest(source_scene),stage_digest(updated)):raise ValueError('Candidate changed outside the reviewed stabilization result')
        if current!=stage_digest(updated):candidate.save(updated)
        applied=True
    return {'probe':result,'execution':'real'if executed else'mock','actual_physics_steps':count if executed else 0,
            'physical_verified':False,'settled':result.get(engine,{}).get('settled'),'pose_proposals':str(proposals),
            'pose_application':'reviewed Candidate estimate'if applied else'diagnostic proposal only',
            'applied_to_candidate':applied,'warnings':['Passive motion and settling do not certify slip/topple stability, gripper physics or Task success']}



def package_scene(candidate, config, previous, folder, provider):
    from .export import export_revision, verify_package
    from dataclasses import asdict
    from .stage_runtime import validate_configuration
    validate_configuration(config)
    # This is an explicitly UNVALIDATED review package, not automatic promotion.
    package=folder/'package'
    if package.exists():
        identity=verify_package(package).identity
    else:
        report={'passed':False,'input_signature':candidate.project.signature(candidate.scene),
                'pipeline':'simfoundry/1','validation_scope':'NOT_VERIFIED',
                'needs':['Independent metric, sensor, physics and Task validation required'],
                'stage12':previous[12]}
        write(folder/'review.json',report)
        # Preserve historical metrics before exposing this current review report.
        metrics=candidate.root/'metrics.json'
        if metrics.exists()and not(folder/'prior_metrics.json').exists():write(folder/'prior_metrics.json',read(metrics))
        write(metrics,report)
        identity=export_revision(candidate.project,destination=package,candidate=candidate.name,
                                 allow_unvalidated=True,revision='simfoundry-review-'+folder.name,
                                 native_options=config.get('simulator',{}).get('native_options'))
    spec=read(package/'scene.json')
    records=candidate.project.info.get('execution_packages',[])
    registered=next((r for r in records if r['manifest_sha256']==identity.manifest_sha256),{})
    return {'package':str(package),'identity':asdict(identity),'approved':False,'candidate_promoted':False,
            'physical_verified':False,'coordinate_frame':previous[10]['coordinate_frame'],
            'execution_mode':'native',
            'native_readiness':spec['validation'].get('native_readiness',{}),
            'engine_config':registered.get('engine_config',{})}


def simulator_integration(candidate, config, previous, folder, provider):
    from .export import verify_package
    from .cameras import camera_roles
    from .stage_runtime import validate_configuration
    validate_configuration(config)
    verify_package(previous[13]['package'])
    scene=candidate.scene;roles=camera_roles(scene,candidate.project.evidence['images'])
    sensors=[name for name,role in roles.items()if role in('side','wrist')]
    engine=config.get('simulator',{}).get('engine','mujoco')
    if engine not in('mujoco','isaac'):raise ValueError('Unsupported simulator')
    settings=previous[13].get('engine_config',{}).get(engine)
    if not settings:
        readiness=previous[13].get('native_readiness',{}).get(engine,{})
        raise StageNeeds('NEEDS_MORE_DATA','Native '+engine+' is not ready: '+'; '.join(readiness.get('needs',['No loader-checked execution settings'])))
    render_scene=folder/'simulator_scene.yaml';write(render_scene,scene)
    result=provider('simulator',{'project':str(candidate.project.root),'scene':str(render_scene),
        'package':previous[13]['package'],'engine':engine,'camera_ids':sensors,'image_records':candidate.project.evidence['images'],
        'engine_config':str(candidate.project.root/settings)},folder/'native')
    if result.get('camera_ids')!=sensors:raise ValueError('Runtime sensor selection changed')
    missing=[role for role in('side','wrist')if role not in roles.values()]
    return {'runtime':result,'render_scene':str(render_scene),'render_scene_sha256':sha(render_scene),'sensor_ids':sensors,'missing_sensors':missing,
            'sensor_status':'NOT_VERIFIED','physical_verified':False,
            'reference_camera_ids':[n for n,r in roles.items()if r=='reference'],
            'package_identity':previous[13]['identity'],'real_sim':'existing package/Capture identity and measured-q paths; no hardware invoked',
            'warnings':['Runtime import/render is separate from held-out Real/Sim alignment and Task success']}
