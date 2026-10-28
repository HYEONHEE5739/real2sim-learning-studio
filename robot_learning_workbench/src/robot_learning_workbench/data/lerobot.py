"""Explicit Native materialization using installed LeRobot 0.4.1 APIs.

No Dataset subclass, monkeypatch, intermediate payload format or Trainer hook.
The pinned _save_episode_data boundary is used because save_episode re-encodes
existing MP4. Metadata.save_episode and feature statistics remain official.
"""
from dataclasses import asdict
from collections.abc import Sequence
from pathlib import Path
import uuid
from importlib.metadata import version
import os
import av
import numpy as np
from .native import (Catalog,DatasetIdentity,NativeEpisode,DataError,load_catalog,read_array,
                     atomic_json,read_json,share_file,digest,_sync)
from .curation import select_split


def _pinned():
    if version('lerobot')!='0.4.1':raise DataError('VERSION_UNSUPPORTED','lerobot','pinned explicit converter requires 0.4.1')


def _camera_contract(catalog: Catalog,fps: int) -> dict:
    cameras=None
    for ep in catalog.episodes:
        current={name:{'shape':list(info['shape']),'fps':float(info['fps']),'color':'rgb'} for name,info in ep.media.items()}
        if cameras is not None and cameras!=current:raise DataError('CONTROL_CONTRACT_INVALID','cameras','Mixed camera contracts')
        if any(value['fps']!=fps or len(value['shape'])!=3 or value['shape'][2]!=3 for value in current.values()):raise DataError('CONTROL_CONTRACT_INVALID','cameras','RGB shape or camera/control FPS differs')
        cameras=current
    return cameras or {}


def control_contract(source: Catalog|Path|str) -> dict|None:
    """Recorded SO101 learning IO meaning, not evidence of Policy performance.

    Original v8 convert_isaac2lerobot.py uses joint_targets; the official
    processors normalize numbers but do not infer robotics units or semantics.
    External datasets need no Workbench provenance to remain readable.
    """
    from ..robot.calibration import JOINTS
    catalog=source if isinstance(source,Catalog) else load_catalog(source)
    if catalog.kind=='curated' and catalog.episodes and catalog.episodes[0].format=='lerobot':
        return control_contract(load_catalog(catalog.episodes[0].source_root))
    saved=(catalog.metadata or {}).get('control_contract')
    if saved is not None:
        if (not isinstance(saved,dict) or saved.get('schema_version')!=1 or saved.get('joint_order')!=list(JOINTS)
                or saved.get('observation')!={'source':'obs/policy/joint_pos','phase':'pre_step','meaning':'measured_model_joint_position','units':['rad']*6}
                or saved.get('action')!={'source':'joint_targets','phase':'command_for_step_t','meaning':'absolute_model_joint_position_target','units':['rad']*6}
                or saved.get('policy_tensor_dtype')!='float32' or saved.get('pose_frame')!='robot_base'
                or not isinstance(saved.get('scene_identity'),dict) or not saved['scene_identity'].get('manifest_sha256')
                or not saved.get('robot_model_sha256') or not saved.get('calibration_sha256')):
            raise DataError('CONTROL_CONTRACT_INVALID','control_contract','Unsupported or inconsistent stored policy meaning')
        fps=read_json(catalog.root/'meta/info.json')['fps'] if catalog.kind=='lerobot' else catalog.execution.get('recording',{}).get('fps')
        if type(saved.get('control_hz')) is not int or saved['control_hz']!=fps or saved.get('cameras')!=_camera_contract(catalog,fps):
            raise DataError('CONTROL_CONTRACT_INVALID','control_contract','Saved camera/clock and actual official metadata differ')
        if 'command_processing' in saved and saved['command_processing']!={'position_target_policy':'saturation_inward_v1','training_target':'applied'}:
            raise DataError('CONTROL_CONTRACT_INVALID','command_processing','Unknown action processing contract')
        return saved
    execution=catalog.execution;recording=execution.get('recording',{})
    if recording.get('joint_order')!=list(JOINTS):
        if recording.get('units')=='m_rad_s' and recording.get('observation_phase')=='pre_step':
            raise DataError('CONTROL_CONTRACT_INVALID','joint_order','Recorded Workbench joints differ; explicit remapping required')
        return None
    if (recording.get('units')!='m_rad_s' or recording.get('observation_phase')!='pre_step'
            or recording.get('task_phase')!='post_step' or recording.get('pose_frame')!='robot_base'):
        raise DataError('CONTROL_CONTRACT_INVALID','recording','Explicit pre-step model-radian contract required')
    calibration=execution.get('calibration');scene=execution.get('scene_identity')
    if not isinstance(calibration,dict) or not scene or not scene.get('manifest_sha256'):
        raise DataError('CONTROL_CONTRACT_INVALID','identity','Scene and Calibration identity required')
    models=[execution.get('urdf_sha256'),execution.get('ik',{}).get('model_sha256')]
    models += [r.get('execution_model_sha256') for r in calibration.get('records',{}).values() if r.get('kind')=='robot_residual']
    models=[value for value in models if value]
    if not models or len(set(models))!=1:raise DataError('CONTROL_CONTRACT_INVALID','model','Unambiguous execution kinematic model required')
    fps=recording.get('fps')
    if type(fps) is not int or fps<=0:raise DataError('CONTROL_CONTRACT_INVALID','fps','Explicit integer control/recording FPS required')
    cameras=_camera_contract(catalog,fps)
    contract=dict(schema_version=1,scene_identity=scene,calibration_sha256=digest(calibration),robot_model_sha256=models[0],
        joint_order=list(JOINTS),pose_frame='robot_base',control_hz=fps,cameras=cameras,policy_tensor_dtype='float32',
        observation={'source':'obs/policy/joint_pos','phase':'pre_step','meaning':'measured_model_joint_position','units':['rad']*6},
        action={'source':'joint_targets','phase':'command_for_step_t','meaning':'absolute_model_joint_position_target','units':['rad']*6})
    if recording.get('position_target_policy') is not None:
        if recording.get('position_target_policy')!='saturation_inward_v1' or recording.get('joint_targets_role')!='applied':raise DataError('CONTROL_CONTRACT_INVALID','recording','Unknown or ambiguous command policy/target role')
        contract['command_processing']={'position_target_policy':'saturation_inward_v1','training_target':'applied'}
    return contract


def lerobot_catalog(root,*,expected=None):
    _pinned();root=Path(root).resolve()
    if not list((root/'meta/episodes').glob('*/*.parquet')) or not (root/'meta/tasks.parquet').is_file():raise DataError('DATA_INCOMPLETE',str(root),'finalized official Metadata required; no implicit Hub fallback')
    from lerobot.datasets.lerobot_dataset import LeRobotDatasetMetadata
    meta=LeRobotDatasetMetadata('workbench/native',root=root)
    rows=[meta.episodes[i] for i in range(meta.total_episodes)]
    provenance=read_json(root/'workbench.json') if (root/'workbench.json').is_file() else {}
    identity=DatasetIdentity(provenance.get('dataset_id','lerobot:'+digest({'features':meta.features,'version':meta.info['codebase_version']})),digest({'info':meta.info,'episodes':rows,'provenance':provenance}))
    if expected is not None and identity!=expected:raise DataError('INPUT_CHANGED',str(root),'official Native Metadata changed')
    episodes=[];ids=set();splits={}
    for index,row in enumerate(rows):
        id_=row.get('workbench/source_episode_id',f'episode_{index}')
        if id_ in ids:id_=f'episode_{index}'
        ids.add(id_);media={}
        role=row.get('workbench/source_split')
        if role:
            if role not in ('train','val','test'):raise DataError('CURATION_INVALID','split','Unknown saved role')
            splits.setdefault(role,[]).append(id_)
        for key in meta.video_keys:
            path=root/meta.get_video_file_path(index,key)
            if not path.is_file():raise DataError('DATA_MISSING',str(path),'video missing')
            camera=key.removeprefix('observation.images.')
            media[camera]={'path':str(path),'feature_key':key,'frames':row['length'],'fps':str(meta.fps),'shape':meta.features[key]['shape'],
                          'from_timestamp':row[f'videos/{key}/from_timestamp'],'to_timestamp':row[f'videos/{key}/to_timestamp'],'size_bytes':path.stat().st_size}
        metadata={'official_episode_index':index,'dataset_from_index':row['dataset_from_index'],'official_episode_metadata':row}
        episodes.append(NativeEpisode(id_,root/meta.get_data_file_path(index),str(index),row['length'],metadata,media,root,format='lerobot'))
    return Catalog(root,identity,tuple(episodes),provenance.get('execution',{}),'lerobot',splits=splits or None,metadata=provenance)


def create_staging(output,*,features,fps,repo_id='workbench/native'):
    """Return the unmodified official Dataset; only publish makes it visible."""
    _pinned();output=Path(output).resolve();staging=output.with_name(output.name+'.staging')
    if output.exists():raise DataError('OUTPUT_EXISTS',str(output),'immutable Native Dataset exists')
    if staging.exists():raise DataError('NATIVE_STATE_UNKNOWN',str(staging),'unfinished conversion; explicit inspection/discard required')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    return LeRobotDataset.create(repo_id,fps=fps,features=features,root=staging,video_backend='pyav')


def publish(dataset,output):
    """Close official writers and check footers/counts, not full arrays/video decode."""
    import pyarrow.parquet as pq
    output=Path(output).resolve();staging=dataset.root
    if staging!=output.with_name(output.name+'.staging'):raise DataError('DATA_INVALID','staging','wrong owned output')
    dataset.finalize()
    info=read_json(staging/'meta/info.json')
    frames=sum(pq.read_metadata(p).num_rows for p in (staging/'data').rglob('*.parquet'))
    episodes=sum(pq.read_metadata(p).num_rows for p in (staging/'meta/episodes').rglob('*.parquet'))
    if frames!=info['total_frames'] or episodes!=info['total_episodes']:raise DataError('DATA_INCOMPLETE','footer','official counts/footers disagree')
    for path in staging.rglob('*'):
        if path.is_file():
            with path.open('rb') as f:os.fsync(f.fileno())
    _sync(staging)
    if output.exists():raise DataError('OUTPUT_EXISTS',str(output),'publish target already exists')
    os.rename(staging,output);_sync(output.parent);return output


def _video_window(info,start,stop):
    """Decode through the selected interval and sample official stats; never encode packets."""
    from lerobot.datasets.compute_stats import sample_indices,auto_downsample_height_width,get_feature_stats
    fps=float(info['fps']);sampled=set(sample_indices(stop-start));images=[];first=None;last=None;previous=None;index=0
    offset=float(info.get('from_timestamp',0.))
    with av.open(str(info['path'])) as container:
        for frame in container.decode(video=0):
            seconds=float(frame.pts*frame.time_base)
            if seconds<offset-1e-6:continue
            if index>=stop:break
            if index>=start:
                if (frame.height,frame.width,3)!=tuple(info['shape']):raise DataError('DATA_INVALID','video','Decoded frame and declared RGB shape differ')
                if previous is not None and abs(seconds-previous-1/fps)>1e-5:raise DataError('VIDEO_UNSUPPORTED','PTS','non-CFR selection needs an explicit timing conversion')
                if first is None:first=seconds
                previous=last=seconds
                if index-start in sampled:images.append(auto_downsample_height_width(frame.to_ndarray(format='rgb24').transpose(2,0,1)))
            index+=1
    if index<stop or first is None:raise DataError('DATA_INCOMPLETE','video','selected frame range missing')
    stats=get_feature_stats(np.stack(images),axis=(0,2,3),keepdims=True)
    stats={k:v if k=='count' else np.squeeze(v/255.,axis=0) for k,v in stats.items()}
    return first,last+1/fps,stats


def _origin(episode: NativeEpisode,cache: dict[Path,Catalog]) -> dict:
    """Small provenance identity survives Curation and hardlinked Native Resume."""
    if episode.source_root not in cache:cache[episode.source_root]=load_catalog(episode.source_root)
    base=cache[episode.source_root]
    if episode.format=='lerobot':
        row=episode.metadata['official_episode_metadata']
        return {'dataset_id':row.get('workbench/source_dataset_id',base.identity.dataset_id),
                'episode_id':row.get('workbench/source_original_episode_id',episode.episode_id),
                'uid':row.get('workbench/source_episode_uid',digest({'dataset':base.identity.dataset_id,'episode':episode.episode_id})),
                'native_alias':row.get('workbench/source_native_alias'),'engine':row.get('workbench/source_engine'),
                'parent':row.get('workbench/source_parent_dataset_id'),'lineage_known':'workbench/source_parent_dataset_id' in row}
    metadata=read_json(episode.file.parent/'segment.json.gz')
    # An old archive's export_source_identity may be a Curation view ID, not
    # the underlying Episode origin. Never relabel it as an original Dataset.
    dataset_id=base.identity.dataset_id
    stat=episode.file.stat()
    parent=read_json(base.root/'run.json').get('parent',{})
    return {'dataset_id':dataset_id,'episode_id':episode.episode_id,
            'uid':digest({'dataset':dataset_id,'episode':episode.episode_id}),
            'engine':base.execution.get('engine'),'parent':parent.get('dataset_id',''),'lineage_known':True,
            'native_alias':digest({'device':stat.st_dev,'inode':stat.st_ino,'key':episode.key,'metadata':metadata['episodes'][episode.key]})}


def _split_name(catalog: Catalog,ep: NativeEpisode) -> str|None:
    if catalog.splits:
        return next((name for name,ids in catalog.splits.items() if (ep.selection_id or ep.episode_id) in ids),None)
    return ep.metadata.get('official_episode_metadata',{}).get('workbench/source_split') or None


def _task_text(catalog: Catalog,ep: NativeEpisode,explicit: str|None,requires_language: bool) -> str:
    definition=ep.metadata.get('legacy_attributes',{}).get('task_definition')
    recorded=ep.metadata.get('official_episode_metadata',{}).get('tasks',[])
    value=explicit or (definition.get('language_instruction') if isinstance(definition,dict) else definition)
    if value is None and len(recorded)==1:value=recorded[0]
    if value is None and not requires_language:value=catalog.execution.get('task_code')
    if value is None or (requires_language and (not isinstance(value,str) or not value.strip())):
        raise DataError('DATA_INVALID','task','Explicit language instruction required; code hashes are not task text')
    return value if isinstance(value,str) else str(value)


def merge(sources: Sequence[Catalog|Path|str],output: Path|str,*,split: str|None=None,independent: bool=False,task: str|None=None) -> Path:
    """Explicit compatible Native/official sources, same materialization writer.

    Official aggregate_datasets copies/concatenates videos and requires identical
    storage dtype. Reuse the pinned native writer boundary instead: promote only
    numeric storage and share unchanged MP4 with official episode offsets.
    """
    catalogs=[s if isinstance(s,Catalog) else load_catalog(s) for s in sources]
    if len(catalogs)<2:raise DataError('MERGE_INCOMPATIBLE','sources','At least two explicit sources required')
    return materialize(catalogs,output,split=split,independent=independent,task=task)


def materialize(source: Catalog|Path|str|Sequence[Catalog|Path|str],output: Path|str,*,split: str|None=None,feature_map: dict[str,str]|None=None,independent: bool=False,task: str|None=None) -> Path:
    """Build exactly the chosen rows in an official Dataset; episodes= is not used."""
    catalogs=source if isinstance(source,Sequence) and not isinstance(source,str) else [source]
    catalogs=[s if isinstance(s,Catalog) else load_catalog(s) for s in catalogs]
    if not catalogs:raise DataError('MERGE_INCOMPATIBLE','sources','Empty source list')
    for cat in catalogs:load_catalog(cat.root,expected=cat.identity)
    catalog=catalogs[0];merged=len(catalogs)>1;contracts=[control_contract(cat) for cat in catalogs]
    if merged and any(cat.execution.get('archive_only') for cat in catalogs):raise DataError('MERGE_INCOMPATIBLE','origin','Archive per-Episode origin is unproven; use the original saved selection')
    if merged and (any(c is None for c in contracts) or any(c!=contracts[0] for c in contracts[1:])):
        raise DataError('MERGE_INCOMPATIBLE','control_contract','Scene/Calibration/model/state/action/camera/control meanings differ or are unproven')
    pairs=[(cat,ep) for cat in catalogs for ep in select_split(cat,split)]
    chosen=[ep for _,ep in pairs];origins={};memberships={};seen=set();aliases=set();families={}
    for cat in catalogs:
        for ep in cat.episodes:
            origin=_origin(ep,origins);role=_split_name(cat,ep)
            if merged:
                if not origin['lineage_known'] or not origin['engine']:raise DataError('MERGE_INCOMPATIBLE','origin','Explicit original domain and Resume lineage required')
                families.setdefault(origin['engine'],{})[origin['dataset_id']]=origin['parent']
            if role:
                for identity in (origin['uid'],origin.get('native_alias')):
                    if identity:
                        if identity in memberships and memberships[identity]!=role:raise DataError('CURATION_INVALID','splits','Same original Episode crosses saved splits')
                        memberships[identity]=role
    # Native Resume stores a parent run, not each inherited Episode creator.
    # Copies have new inodes. One canonical resumed Dataset per domain avoids
    # guessing which Episodes were inherited across separate Resume branches.
    if any(len(group)>1 and any(group.values()) for group in families.values()):
        raise DataError('MERGE_INCOMPATIBLE','origin','Resume-family origins are not proven disjoint; use one canonical Dataset per engine and its saved selections')
    for ep in chosen:
        origin=_origin(ep,origins);uid=origin['uid'];alias=origin.get('native_alias')
        if uid in seen or (alias and alias in aliases):raise DataError('MERGE_INCOMPATIBLE','episodes','Duplicate original Episode/Resume alias; use one saved selection')
        seen.add(uid)
        if alias:aliases.add(alias)
    if chosen and len({ep.format for ep in chosen})!=1:raise DataError('MERGE_INCOMPATIBLE','format','Convert Native and official format families separately before merging')
    output=Path(output).resolve()
    if any(output.is_relative_to(ep.source_root) or ep.source_root.is_relative_to(output) for ep in chosen):raise DataError('OUTPUT_CONFLICT','output','separate materialization space required')
    if not chosen:raise DataError('CURATION_INVALID','selection','empty requested split')
    official={}
    if chosen[0].format=='lerobot':
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
        for ep in chosen:
            if ep.source_root not in official:official[ep.source_root]=LeRobotDataset('workbench/native',root=ep.source_root,video_backend='pyav')
        original=official[chosen[0].source_root]
        if any(ft['dtype']=='image' for ft in original.features.values()):raise DataError('VIDEO_UNSUPPORTED','image','embedded-image import requires an explicit conversion; never omit a feature silently')
        defaults={'timestamp','frame_index','episode_index','index','task_index'}
        mapping=feature_map or {key:key for key,ft in original.features.items() if key not in defaults and ft['dtype'] not in ('video','image') and not key.startswith('source.')}
        features={key:original.features[name].copy() for key,name in mapping.items()}
    else:
        mapping=feature_map or {'observation.state':'obs/policy/joint_pos','action':'joint_targets'}
        features={}
    contract=contracts[0]
    if contract is not None:
        expected={'observation.state':'observation.state','action':'action'} if chosen[0].format=='lerobot' else {'observation.state':'obs/policy/joint_pos','action':'joint_targets'}
        if mapping!=expected:raise DataError('CONTROL_CONTRACT_INVALID','feature_map','Recorded state/target only; diagnostics and post-step telemetry are not policy targets')
    labels=[_task_text(cat,ep,task,contract is not None) for cat,ep in pairs]
    import h5py
    if chosen[0].format=='isaac_hdf5':
        with h5py.File(chosen[0].file,'r') as f:
            for key,name in mapping.items():
                d=f['data/'+chosen[0].key+'/'+name]
                features[key]={'dtype':d.dtype.name,'shape':d.shape[1:],'names':None}
        if merged:
            for ep in chosen[1:]:
                with h5py.File(ep.file,'r') as f:
                    for key,name in mapping.items():
                        d=f['data/'+ep.key+'/'+name]
                        if tuple(d.shape[1:])!=tuple(features[key]['shape']) or d.dtype.kind!='f':raise DataError('MERGE_INCOMPATIBLE',key,'Numeric joint feature shapes differ')
                        features[key]['dtype']=np.result_type(features[key]['dtype'],d.dtype).name
    elif merged:
        for ep in chosen[1:]:
            for key,name in mapping.items():
                ft=official[ep.source_root].features[name]
                if tuple(ft['shape'])!=tuple(features[key]['shape']) or np.dtype(ft['dtype']).kind!='f' or ft['names']!=contract['joint_order']:raise DataError('MERGE_INCOMPATIBLE',key,'Joint feature shape/dtype/order differs')
                features[key]['dtype']=np.result_type(features[key]['dtype'],ft['dtype']).name
    if contract is not None:
        for key in ('observation.state','action'):
            if tuple(features[key]['shape'])!=(6,):raise DataError('CONTROL_CONTRACT_INVALID',key,'Six model joints required')
            if features[key]['dtype'] not in ('float32','float64'):raise DataError('CONTROL_CONTRACT_INVALID',key,'Recorded floating joint values required')
            if chosen[0].format=='lerobot' and features[key]['names']!=contract['joint_order']:raise DataError('CONTROL_CONTRACT_INVALID',key,'Official feature joint order differs')
            features[key]['names']=contract['joint_order']
    for key,dtype in [('source.episode_id','string'),('source.dataset_id','string'),('source.episode_uid','string'),('source.frame_index','int64'),('source.timestamp','float64')]:features[key]={'dtype':dtype,'shape':(1,),'names':None}
    cameras=tuple(chosen[0].media)
    if cameras:fps_value=float(next(iter(chosen[0].media.values()))['fps'])
    elif chosen[0].format=='lerobot':fps_value=float(original.meta.fps)
    else:
        fps_value=catalog.execution.get('recording',{}).get('fps')
        if fps_value is None:
            times=read_array(chosen[0],'obs/timestamp',frames=False).reshape(-1)
            if len(times)<2 or not np.isfinite(times).all() or not np.allclose(np.diff(times),times[1]-times[0],rtol=1e-6,atol=1e-9) or times[1]<=times[0]:raise DataError('DATA_INVALID','fps','recorded FPS or uniform original clock required')
            rate=1./float(times[1]-times[0]);rounded=round(rate)
            if abs(rate-rounded)>1e-5:raise DataError('VIDEO_UNSUPPORTED','fps','integer official FPS requires an explicit timing conversion')
            fps_value=rounded
    if isinstance(fps_value,bool) or not isinstance(fps_value,(int,float)) or not np.isfinite(fps_value) or fps_value<=0:raise DataError('DATA_INVALID','fps','finite positive recorded FPS required')
    if float(fps_value)!=int(fps_value):raise DataError('VIDEO_UNSUPPORTED','fps','official integer FPS needs an explicit timing conversion')
    fps=int(fps_value)
    for camera in cameras:features[chosen[0].media[camera].get('feature_key','observation.images.'+camera)]={'dtype':'video','shape':tuple(chosen[0].media[camera]['shape']),'names':['height','width','channels']}
    ds=create_staging(output,features=features,fps=fps)
    try:
        from lerobot.datasets.compute_stats import compute_episode_stats
        from lerobot.datasets.utils import write_info
        videos={camera:{} for camera in cameras}
        for index,(source_catalog,ep) in enumerate(pairs):
            origin=_origin(ep,origins)
            stop=ep.num_frames if ep.stop is None else ep.stop;nframes=stop-ep.start
            if any(info['fps']!=chosen[0].media[camera]['fps'] or list(info['shape'])!=list(chosen[0].media[camera]['shape']) for camera,info in ep.media.items() if camera in cameras):raise DataError('DATA_INVALID','video','mixed camera FPS/shape')
            if tuple(ep.media)!=cameras:raise DataError('DATA_INVALID','cameras','mixed camera contracts')
            if ep.format=='isaac_hdf5':
                payload={key:read_array(ep,name) for key,name in mapping.items()};source_frames=np.arange(ep.start,stop);source_time=read_array(ep,'obs/timestamp').reshape(-1)
                source_ids=np.array([origin['episode_id']]*nframes);dataset_ids=np.array([origin['dataset_id']]*nframes);episode_uids=np.array([origin['uid']]*nframes)
            elif ep.format=='lerobot':
                original=official[ep.source_root];offset=ep.metadata['dataset_from_index'];data=original.hf_dataset.with_format(None)[offset+ep.start:offset+stop]
                payload={key:np.asarray(data[name],dtype=features[key]['dtype']) for key,name in mapping.items()}
                source_frames=np.asarray(data.get('source.frame_index',np.arange(ep.start,stop)),dtype=np.int64)
                source_time=np.asarray(data.get('source.timestamp',data['timestamp']),dtype=np.float64)
                source_ids=np.asarray(data.get('source.episode_id',[origin['episode_id']]*nframes));dataset_ids=np.asarray(data.get('source.dataset_id',[origin['dataset_id']]*nframes));episode_uids=np.asarray(data.get('source.episode_uid',[origin['uid']]*nframes))
            else:raise DataError('DATA_INVALID','format','mixed unsupported data formats')
            if source_time.shape!=(nframes,) or not np.isfinite(source_time).all():raise DataError('DATA_INVALID','source.timestamp','Finite original frame timestamps required')
            if source_frames.shape!=(nframes,) or source_frames.dtype.kind not in 'iu' or np.any(source_frames<0):raise DataError('DATA_INVALID','source.frame_index','Nonnegative integer original frame indices required')
            # Preserve original v8 converter clock validation, without resampling.
            if nframes>1 and (np.any(np.diff(source_frames)<=0) or not np.allclose(np.diff(source_time),1/fps,rtol=0,atol=.2/fps)):
                raise DataError('DATA_INVALID','source.timestamp','Original frame clock differs from recorded FPS')
            if merged:
                payload={key:value.astype(features[key]['dtype']) for key,value in payload.items()}
            for key,value in payload.items():
                if features[key]['dtype']!='string' and (value.dtype.name!=features[key]['dtype'] or (value.shape!=(nframes,*features[key]['shape']) and not (features[key]['shape'] in ((1,),[1]) and value.shape==(nframes,)))):raise DataError('DATA_INVALID',key,'mixed dtype/shape or phase contract')
                if value.dtype.kind in 'fiu' and not np.isfinite(value).all():raise DataError('DATA_INVALID',key,'Nonfinite numeric feature')
            payload.update({'source.episode_id':source_ids,'source.dataset_id':dataset_ids,'source.episode_uid':episode_uids,'source.frame_index':source_frames,
                'source.timestamp':source_time,'timestamp':np.arange(nframes,dtype=np.float64)/fps,
                'frame_index':np.arange(nframes),'index':np.arange(ds.meta.total_frames,ds.meta.total_frames+nframes),'episode_index':np.full(nframes,index)})
            task_text=labels[index]
            ds.meta.save_episode_tasks([task_text]);payload['task_index']=np.full(nframes,ds.meta.get_task_index(task_text))
            numeric_features={key:value for key,value in ds.features.items() if value['dtype']!='video'}
            stats=compute_episode_stats(payload,numeric_features)
            ep_meta=ds._save_episode_data(payload)  # Pinned official Parquet/shard writer.
            for camera in cameras:
                info=ep.media[camera];key=info.get('feature_key','observation.images.'+camera);cache=videos[camera];source_path=str(Path(info['path']).resolve())
                if source_path not in cache:
                    number=len(cache);chunk,file=divmod(number,ds.meta.chunks_size)
                    target=ds.root/ds.meta.video_path.format(video_key=key,chunk_index=chunk,file_index=file)
                    share_file(source_path,target,independent=independent);cache[source_path]=(chunk,file)
                chunk,file=cache[source_path];first,last,video_stats=_video_window(info,ep.start,stop)
                stats[key]=video_stats
                ep_meta.update({f'videos/{key}/chunk_index':chunk,f'videos/{key}/file_index':file,
                                f'videos/{key}/from_timestamp':first,f'videos/{key}/to_timestamp':last})
                if index==0:ds.meta.update_video_info(key)
            output_id=origin['uid']+':'+origin['episode_id'] if merged else ep.episode_id
            ep_meta.update({'workbench/source_episode_id':output_id,'workbench/source_original_episode_id':str(source_ids[0]),'workbench/source_dataset_id':str(dataset_ids[0]),'workbench/source_episode_uid':str(episode_uids[0]),'workbench/source_engine':origin.get('engine') or '', 'workbench/source_parent_dataset_id':origin.get('parent') or '', 'workbench/source_native_alias':origin.get('native_alias'),'workbench/source_split':_split_name(source_catalog,ep) or '', 'workbench/source_start':ep.start,'workbench/source_stop':stop})
            ds.meta.save_episode(index,nframes,[task_text],stats,ep_meta)
        write_info(ds.meta.info,ds.root)
        atomic_json(ds.root/'workbench.json',{'schema_version':1,'dataset_id':uuid.uuid4().hex,'source_identity':asdict(catalog.identity),'split':split,
            'execution':catalog.execution if not merged else {'stage':'learning_dataset','domains':[cat.execution.get('engine','unknown') for cat in catalogs]},'feature_map':mapping,'control_contract':contract,
            'source_identities':[asdict(cat.identity) for cat in catalogs],'merged':merged,
            'source_locations':[{'identity':asdict(cat.identity),'path':os.path.relpath(cat.root,ds.root)} for cat in catalogs],
            'semantics':{'observation':'recorded measured model rad' if contract else 'unverified explicit projection','action':'recorded joint target, not separately measured applied telemetry' if contract else 'unverified explicit projection','timestamp':'official relative clock; original in source.timestamp'},'independent':independent})
        return publish(ds,output)
    finally:ds.finalize()
