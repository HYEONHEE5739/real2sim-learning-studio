"""Permanent selections of Native data. No payload copy and no implicit unexclude."""
from dataclasses import asdict,replace
from pathlib import Path
import os
import uuid
from .native import Catalog,DatasetIdentity,DataError,atomic_json,read_json,digest,load_catalog


def save_curation(path,source,*,exclude=(),order=None,frame_ranges=None,splits=None,split_provenance=None):
    source=_catalog(source)
    path=Path(path).resolve()
    if path.exists():raise DataError('OUTPUT_EXISTS',str(path),'new Curation revision required')
    # Source identity is rechecked before persisting references; no array SHA pass.
    by_id={e.selection_id or e.episode_id:e for e in source.episodes}
    excluded=set(exclude)
    if not excluded<=by_id.keys():raise DataError('CURATION_INVALID','exclude','not present in this revision')
    order=list(by_id) if order is None else list(order)
    if len(set(order))!=len(order) or not set(order)<=by_id.keys():raise DataError('CURATION_INVALID','order','duplicate or not in current revision')
    ranges=frame_ranges or {}
    if not set(ranges)<=set(order):raise DataError('CURATION_INVALID','ranges','range for unselected Episode')
    selections=[]
    for id_ in order:
        if id_ in excluded:continue
        ep=by_id[id_];low=ep.start;high=ep.num_frames if ep.stop is None else ep.stop
        start,stop=ranges.get(id_,(low,high))
        if type(start) is not int or type(stop) is not int or not low<=start<stop<=high:raise DataError('CURATION_INVALID',id_,'range expands parent or is empty')
        selections.append({'selection_id':id_,'episode_id':ep.episode_id,'start':start,'stop':stop})
    if not selections:raise DataError('CURATION_INVALID','selection','empty Dataset')
    ids={row['selection_id'] for row in selections}
    resolved_splits={k:[x for x in v if x in ids] for k,v in (source.splits or {}).items()} if splits is None else {k:list(v) for k,v in splits.items()}
    assigned=[]
    for name,values in resolved_splits.items():
        if name not in ('train','val','test') or not set(values)<=ids or len(set(values))!=len(values):raise DataError('CURATION_INVALID','splits','unknown split/selection or duplicate')
        assigned.extend(values)
    if len(assigned)!=len(set(assigned)):raise DataError('CURATION_INVALID','splits','membership overlaps')
    _split_origins(tuple(by_id[id_] for id_ in ids),resolved_splits)
    document={'kind':'curated_native','schema_version':1,'view_id':uuid.uuid4().hex,
        'source':{'path':os.path.relpath(source.root,path.parent),'identity':asdict(source.identity)},
        'selections':selections,'splits':resolved_splits}
    if split_provenance is not None:
        if not isinstance(split_provenance,dict) or split_provenance.get('splits')!=resolved_splits or split_provenance.get('selection_identity')!=asdict(source.identity):raise DataError('CURATION_INVALID','split_provenance','Generated allocation must match exact source and membership')
        _check_split_provenance(split_provenance)
        document['split_provenance']=split_provenance
    elif splits is None and (source.metadata or {}).get('split_provenance') is not None:
        document['split_provenance']=source.metadata['split_provenance']
    else:document['split_provenance']={'rule':'explicit_episode_membership','seed':None}
    if (source.metadata or {}).get('resolved_relocations'):
        document['relocations']={os.path.relpath(old,path.parent):os.path.relpath(new,path.parent) for old,new in source.metadata['resolved_relocations'].items()}
    path.parent.mkdir(parents=True,exist_ok=True);atomic_json(path,document,exclusive=True)
    return load_curation(path)


def load_curation(path,*,expected=None,relocations=None,_seen=None):
    path=Path(path).resolve();seen=set(_seen or ())
    if path in seen:raise DataError('CURATION_INVALID',str(path),'reference cycle')
    seen.add(path);document=read_json(path)
    if not isinstance(document,dict) or document.get('kind')!='curated_native' or document.get('schema_version')!=1:raise DataError('SCHEMA_UNSUPPORTED',str(path),'curated Native Metadata required')
    if (not isinstance(document.get('source'),dict) or not isinstance(document['source'].get('path'),str)
        or not isinstance(document['source'].get('identity'),dict) or set(document['source']['identity'])!={'dataset_id','metadata_sha256'}
        or not isinstance(document.get('view_id'),str) or not document['view_id']
        or not isinstance(document.get('selections'),list) or not document['selections']
        or not isinstance(document.get('splits'),dict)):
        raise DataError('CURATION_INVALID',str(path),'Invalid saved source/identity/selection/split structure')
    saved=document.get('relocations',{})
    if not isinstance(saved,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in saved.items()):raise DataError('CURATION_INVALID','relocations','Explicit path mapping required')
    resolved={str((path.parent/old).resolve()):str((path.parent/new).resolve()) for old,new in saved.items()}
    resolved.update(relocations or {})
    source=(path.parent/document['source']['path']).resolve()
    source=Path(resolved.get(str(source),source)).resolve()
    identity=DatasetIdentity(**document['source']['identity'])
    try:
        parent=load_curation(source,expected=identity,relocations=resolved,_seen=seen) if source.is_file() else load_catalog(source,expected=identity)
    except (OSError,ValueError) as exc:raise DataError('CURATION_SOURCE_INVALID',str(source),'source moved/deleted/changed; explicit identity-checked relocation required') from exc
    by_id={e.selection_id or e.episode_id:e for e in parent.episodes};episodes=[];selected=set()
    for row in document['selections']:
        if not isinstance(row,dict) or set(row)!={'selection_id','episode_id','start','stop'} or not isinstance(row['selection_id'],str):raise DataError('CURATION_INVALID','selections','Invalid saved selection row')
        id_=row['selection_id']
        if id_ in selected or id_ not in by_id:raise DataError('CURATION_INVALID',id_,'duplicate/absent parent selection')
        ep=by_id[id_];start=row['start'];stop=row['stop'];high=ep.num_frames if ep.stop is None else ep.stop
        if ep.episode_id!=row['episode_id'] or type(start) is not int or type(stop) is not int or not ep.start<=start<stop<=high:raise DataError('CURATION_INVALID',id_,'invalid saved Episode/range')
        selected.add(id_);episodes.append(replace(ep,start=start,stop=stop,selection_id=id_))
    if any(k not in ('train','val','test') or not isinstance(v,list) or any(not isinstance(x,str) for x in v) for k,v in document['splits'].items()):raise DataError('CURATION_INVALID','splits','Unknown split or invalid membership list')
    assigned=[x for values in document['splits'].values() for x in values]
    if len(set(assigned))!=len(assigned) or not set(assigned)<=selected:raise DataError('CURATION_INVALID','splits','overlap/unknown saved membership')
    _split_origins(episodes,document['splits'])
    current=DatasetIdentity(document['view_id'],digest(document))
    if expected is not None and current!=expected:raise DataError('INPUT_CHANGED',str(path),'Curation revision changed')
    provenance=document.get('split_provenance')
    if provenance is not None:_check_split_provenance(provenance)
    inherited=(parent.metadata or {}).get('resolved_relocations',{})
    return Catalog(path,current,tuple(episodes),parent.execution,'curated',document['splits'],{'parent_identity':document['source']['identity'],'source_kind':parent.kind,'split_provenance':provenance,'resolved_relocations':{**inherited,**resolved}})


def select_split(catalog,split=None):
    if split is None:return catalog.episodes
    if not catalog.splits or split not in catalog.splits:raise DataError('CURATION_INVALID','split','explicit saved split required')
    membership=set(catalog.splits[split])
    return tuple(e for e in catalog.episodes if (e.selection_id or e.episode_id) in membership)


def export_native(source,output,*,split=None,segment_episodes=10):
    """Independent full-Episode archive using the official HDF5 writer.

    A trimmed training range is materialized by data.lerobot instead. It is not a
    replay Episode: its new physical initial state was never measured.
    """
    from .native import NativeRun,open_native,load_catalog
    source=_catalog(source)
    episodes=select_split(source,split)
    output=Path(output).resolve()
    if not episodes or type(segment_episodes) is not int or segment_episodes<1:raise DataError('CURATION_INVALID','export','nonempty selection and positive segment size required')
    if any(e.format!='isaac_hdf5' or e.start or e.stop not in (None,e.num_frames) for e in episodes):raise DataError('REPLAY_INITIAL_UNAVAILABLE','selection','full official HDF5 Episodes required; trimmed ranges use explicit LeRobot materialization')
    if any(output.is_relative_to(e.source_root) or e.source_root.is_relative_to(output) for e in episodes):raise DataError('OUTPUT_CONFLICT','output','separate export space required')
    base=load_catalog(episodes[0].source_root)
    with NativeRun(output,{**source.execution,'archive_only':True},metadata={**(base.metadata or {}),'export_source_identity':asdict(source.identity),'independent_export':True}) as run:
        for index,ep in enumerate(episodes):
            if index%segment_episodes==0:segment=run.segment(f'export-{index:08d}')
            handler=open_native(ep)
            try:data=handler.load_episode(ep.key,'cpu')
            finally:handler.close()
            segment.write_episode(data,episode_id=ep.episode_id,metadata=ep.metadata,media=ep.media,independent_media=True)
            if (index+1)%segment_episodes==0 or index==len(episodes)-1:segment.commit()
    return load_catalog(output)


def _catalog(source):
    catalog=source if isinstance(source,Catalog) else load_catalog(source)
    if catalog.kind=='curated':return load_curation(catalog.root,expected=catalog.identity,relocations=(catalog.metadata or {}).get('resolved_relocations'))
    return load_catalog(catalog.root,expected=catalog.identity)


def _check_split_provenance(value):
    if not isinstance(value,dict) or not isinstance(value.get('rule'),str) or (value.get('seed') is not None and (type(value['seed']) is not int or value['seed']<0)):raise DataError('CURATION_INVALID','split_provenance','Explicit rule and nonnegative seed or unknown required')


def _parent(catalog):
    document=read_json(catalog.root);paths=(catalog.metadata or {}).get('resolved_relocations',{})
    path=(catalog.root.parent/document['source']['path']).resolve();path=Path(paths.get(str(path),str(path)))
    identity=DatasetIdentity(**document['source']['identity'])
    return load_curation(path,expected=identity,relocations=paths) if path.is_file() else load_catalog(path,expected=identity)


def _scope(catalog,split,episodes):
    return dict(identity=asdict(catalog.identity),kind=catalog.kind,split=split,range_convention='half_open_original_frames',
                episodes=len(episodes),frames=sum((e.num_frames if e.stop is None else e.stop)-e.start for e in episodes),
                selections=[dict(id=e.selection_id or e.episode_id,start=e.start,stop=e.num_frames if e.stop is None else e.stop) for e in episodes])


def inspect_dataset(source,*,split=None):
    """Small read-only outcomes/lineage; run attempts never masquerade as selected rows."""
    import h5py
    from .native import history,recover_unlocked
    catalog=_catalog(source);episodes=select_split(catalog,split);rows=[];cache={};attempts=[];pending=[];runs=[]
    for ep in episodes:
        success=None;seed=None;metadata=ep.metadata
        if ep.format=='isaac_hdf5':
            with h5py.File(ep.file,'r') as file:
                attrs=file['data/'+ep.key].attrs
                success=bool(attrs['success']) if 'success' in attrs else None;seed=int(attrs['seed']) if 'seed' in attrs else None
        if ep.source_root not in cache:cache[ep.source_root]=load_catalog(ep.source_root)
        base=cache[ep.source_root]
        rows.append(dict(selection_id=ep.selection_id or ep.episode_id,episode_id=ep.episode_id,selection_range=[ep.start,ep.num_frames if ep.stop is None else ep.stop],
            original_frames=ep.num_frames,env_index=metadata.get('env_index'),recorded_success=success,success_scope='original_episode_not_trimmed_task_reassessment',seed=seed,
            category=metadata.get('category') or metadata.get('status'),success_source=metadata.get('success_source'),
            source_identity=asdict(base.identity),source_lineage=metadata.get('source_lineage'),
            historical_source_partition=metadata.get('source_partition',metadata.get('legacy_attributes',{}).get('source_partition',base.execution.get('partition'))),
            split=next((name for name,ids in (catalog.splits or {}).items() if (ep.selection_id or ep.episode_id) in ids),None),
            cameras=list(ep.media),format=ep.format))
    # A cancelled/failed run can legitimately contain no completed Episodes.
    base=catalog
    while base.kind=='curated':
        base=_parent(base)
    if base.kind=='native':
        attempts=history(base.root);pending=recover_unlocked(base.root);record=read_json(base.root/'run.json')
        runs=[dict(identity=asdict(base.identity),closed=record['closed'])]
    return dict(scope=_scope(catalog,split,episodes),selected_frames=_scope(catalog,split,episodes)['frames'],episodes=rows,
                source_attempts=attempts,unresolved_source_intents=pending,attempt_scope='original_native_run' if base.kind=='native' else 'unavailable_in_official_projection',source_runs=runs,
                original_curated_materialized=catalog.kind,parent_identity=(catalog.metadata or {}).get('parent_identity'))


def filter_episodes(source,*,recorded_success=None,category=None,split=None):
    if recorded_success is not None and type(recorded_success) is not bool:raise DataError('CURATION_INVALID','recorded_success','bool or None required')
    return tuple(row['selection_id'] for row in inspect_dataset(source,split=split)['episodes']
                 if (recorded_success is None or row['recorded_success'] is recorded_success) and (category is None or row['category']==category))


def _field_semantics(catalog,name):
    recording=catalog.execution.get('recording',{});unit=None;phase=None;frame=None
    contract=(catalog.metadata or {}).get('control_contract')
    if catalog.episodes and catalog.episodes[0].format=='lerobot':
        from .lerobot import control_contract
        contract=control_contract(catalog)
    if name in ('joint_targets','obs/policy/joint_pos','commands/applied_joint_rad','commands/requested_joint_rad','commands/saturation_delta_rad','states/joint_pos','observation.state','action'):
        unit='rad' if recording.get('units') in ('m_rad_s','model_rad') or contract else 'unknown'
        phase='post_step' if name.startswith('states/') else 'pre_step' if name in ('obs/policy/joint_pos','observation.state') else 'command_for_step_t'
    elif name in ('obs/policy/joint_vel','states/joint_vel'):unit='rad/s' if recording.get('units') in ('m_rad_s','model_rad') else 'unknown';phase='pre_step' if name.startswith('obs/') else 'post_step'
    elif name.startswith(('obs/events/','states/grasp','states/placement','states/finger_contact')):unit='bool';phase='pre_step' if name.startswith('obs/') else 'post_step'
    elif name=='states/contact_force_w':unit='N';phase='post_step';frame='world'
    elif name in ('obs/timestamp','action_timestamp','timestamp','source.timestamp'):unit='s';phase='recorded_clock'
    else:raise DataError('CURATION_FIELD_UNSUPPORTED',name,'Explicit supported observation/action/event field required; no inferred unit/frame')
    joints=(recording.get('joint_order') or (contract or {}).get('joint_order')) if name in ('joint_targets','obs/policy/joint_pos','commands/applied_joint_rad','commands/requested_joint_rad','commands/saturation_delta_rad','states/joint_pos','observation.state','action','obs/policy/joint_vel','states/joint_vel') else None
    return dict(unit=unit,phase=phase,frame=frame,joint_order=joints)


def _chunks(episodes,name,size,official):
    """Bounded HDF5 hyperslabs or official HF row slices, preserving raw dtype.

    https://docs.h5py.org/en/stable/high/dataset.html#reading-writing-data
    """
    import h5py,numpy as np
    for ep in episodes:
        stop=ep.num_frames if ep.stop is None else ep.stop
        if ep.format=='isaac_hdf5':
            with h5py.File(ep.file,'r') as file:
                key='data/'+ep.key+'/'+name
                if key not in file:raise DataError('CURATION_FIELD_MISSING',name,'Field not recorded in '+ep.episode_id)
                data=file[key]
                if not data.shape or data.shape[0]!=ep.num_frames:raise DataError('CURATION_INVALID',name,'Not an aligned time-series field')
                for start in range(ep.start,stop,size):yield data[start:min(start+size,stop)]
        else:
            if ep.source_root not in official:
                from lerobot.datasets.lerobot_dataset import LeRobotDataset
                official[ep.source_root]=LeRobotDataset('workbench/native',root=ep.source_root,video_backend='pyav')
            ds=official[ep.source_root]
            if name not in ds.features or ds.features[name]['dtype'] in ('video','image','string'):raise DataError('CURATION_FIELD_MISSING',name,'Numeric official feature required')
            offset=ep.metadata['dataset_from_index'];data=ds.hf_dataset.with_format(None)
            for start in range(ep.start,stop,size):yield np.asarray(data[offset+start:offset+min(start+size,stop)][name],dtype=ds.features[name]['dtype'])


def _numeric(values,name):
    import numpy as np
    array=np.asarray(values)
    if array.dtype.kind not in 'biuf' or array.ndim not in (1,2,3) or not np.isfinite(array).all():raise DataError('CURATION_INVALID',name,'Finite scalar/vector or contact-matrix rows required')
    return array.reshape(len(array),-1)


def _histogram(episodes,name,edges,size,official):
    import numpy as np
    counts=np.zeros((len(edges),len(edges[0])-1),dtype=np.int64)
    for block in _chunks(episodes,name,size,official):
        values=_numeric(block,name)
        for index,bins in enumerate(edges):counts[index]+=np.histogram(values[:,index].astype(float),bins=bins)[0]
    return counts.tolist()


def distribution(source,*,fields=None,split=None,bins=20,chunk_frames=2048):
    """Per-component population moments/histograms for exactly the selected rows."""
    import numpy as np
    catalog=_catalog(source);episodes=select_split(catalog,split)
    if fields is not None and (not isinstance(fields,(list,tuple)) or any(not isinstance(name,str) for name in fields)):raise DataError('CURATION_INVALID','fields','Explicit numeric field name sequence required')
    fields=tuple(fields) if fields is not None else ('observation.state','action') if episodes and episodes[0].format=='lerobot' else ('obs/policy/joint_pos','joint_targets')
    if not episodes or not fields or len(set(fields))!=len(fields) or type(bins) is not int or bins<1 or type(chunk_frames) is not int or chunk_frames<1:raise DataError('CURATION_INVALID','distribution','Nonempty explicit selection/fields and positive bin/chunk sizes required')
    result={};official={}
    for name in fields:
        semantics=_field_semantics(catalog,name);count=0;mean=None;m2=None;low=None;high=None;dtypes=set();shape=None
        for block in _chunks(episodes,name,chunk_frames,official):
            values=_numeric(block,name);dtypes.add(str(values.dtype));values=values.astype(np.float64);n=len(values)
            if shape is None:shape=list(block.shape[1:])
            elif shape!=list(block.shape[1:]):raise DataError('CURATION_INVALID',name,'Mixed component shape')
            if mean is None:mean=np.zeros(values.shape[1]);m2=mean.copy();low=np.full_like(mean,np.inf);high=-low
            if values.shape[1]!=len(mean):raise DataError('CURATION_INVALID',name,'Mixed vector shape')
            delta=values.mean(0)-mean;combined=count+n
            m2+=np.square(values-values.mean(0)).sum(0)+np.square(delta)*count*n/combined
            mean+=delta*n/combined;count=combined;low=np.minimum(low,values.min(0));high=np.maximum(high,values.max(0))
        edges=[np.histogram_bin_edges([],bins=bins,range=(float(a),float(b))).tolist() for a,b in zip(low,high)]
        result[name]={**semantics,'component_shape':shape,'count':count,'mean':mean.tolist(),'std':np.sqrt(m2/count).tolist(),'min':low.tolist(),'max':high.tolist(),'source_dtypes':sorted(dtypes),
                      'statistic_dtype':'float64','std_ddof':0,'histogram_edges':edges,'histogram_counts':_histogram(episodes,name,edges,chunk_frames,official)}
    return dict(scope=_scope(catalog,split,episodes),fields=result)


def compare_distributions(sources,*,fields=None,split=None,bins=20,chunk_frames=2048):
    """Read-only comparison on common bin edges; no automatic Merge or recommendation."""
    import numpy as np
    catalogs=[_catalog(source) for source in sources]
    if len(catalogs)<2:raise DataError('CURATION_INVALID','comparison','At least two sources required')
    results=[distribution(cat,fields=fields,split=split,bins=bins,chunk_frames=chunk_frames) for cat in catalogs]
    for name in results[0]['fields']:
        rows=[r['fields'].get(name) for r in results]
        if any(row is None or row['unit'] in (None,'unknown') or any(row[key]!=rows[0][key] for key in ('unit','phase','frame','joint_order')) or len(row['mean'])!=len(rows[0]['mean']) for row in rows):raise DataError('CURATION_INCOMPATIBLE',name,'Cannot compare unknown/different units/phase/frame/joint order or shape')
        edges=[np.histogram_bin_edges([],bins=bins,range=(min(row['min'][i] for row in rows),max(row['max'][i] for row in rows))).tolist() for i in range(len(rows[0]['mean']))]
        for catalog,result in zip(catalogs,results):
            row=result['fields'][name];row['histogram_edges']=edges;row['histogram_counts']=_histogram(select_split(catalog,split),name,edges,chunk_frames,{})
    return dict(datasets=results,comparison='common_component_bins_no_merge_or_distribution_recommendation')


def _split_origins(episodes,splits):
    """Reject known duplicate original Episode across roles; no guessed global dedup."""
    from .lerobot import _origin
    cache={};owners={}
    for ep in episodes:
        role=next((name for name,ids in splits.items() if (ep.selection_id or ep.episode_id) in ids),None)
        if role is None:continue
        origin=_origin(ep,cache)
        for key in (origin['uid'],origin.get('native_alias')):
            if key is None:continue
            if key in owners and owners[key]!=role:raise DataError('CURATION_INVALID','splits','Known original Episode overlaps train/val/test roles')
            owners[key]=role


def split_dataset(source,*,train_fraction=.8,seed=0,assignments=None):
    """Original v8 explicit/seeded Episode allocation; never alter payload or global RNG."""
    import numpy as np
    catalog=_catalog(source);ids=[ep.selection_id or ep.episode_id for ep in catalog.episodes]
    if type(train_fraction) not in (float,int) or not np.isfinite(train_fraction) or not 0<train_fraction<1 or type(seed) is not int or seed<0 or len(ids)<2:raise DataError('CURATION_INVALID','split','At least two Episodes and finite ratio/seed required')
    if assignments is None:
        count=max(1,min(len(ids)-1,int(len(ids)*train_fraction+.5)))
        train=set(np.random.default_rng(seed).choice(ids,count,replace=False));assignments={id_:('train' if id_ in train else 'val') for id_ in ids}
    if not isinstance(assignments,dict) or set(assignments)!=set(ids) or any(not isinstance(role,str) for role in assignments.values()) or set(assignments.values())!={'train','val'}:raise DataError('CURATION_INVALID','assignments','Cover each selected Episode with train or val; both nonempty')
    splits={role:[id_ for id_ in ids if assignments[id_]==role] for role in ('train','val')};_split_origins(catalog.episodes,splits)
    return dict(splits=splits,seed=seed,train_fraction=float(train_fraction),selection_identity=asdict(catalog.identity),
                rule='v8_episode_choice_without_replacement_round_half_up',lineage_scope='known original Episode identity only; shared task/source ancestry is not proof of independence')


def _episode(catalog,selection_id):
    matches=[ep for ep in catalog.episodes if (ep.selection_id or ep.episode_id)==selection_id]
    if len(matches)!=1:raise DataError('CURATION_INVALID','selection_id','Exactly one current selection required')
    return matches[0]


def _video_frames(ep,camera,start,stop):
    """Seek to a keyframe, then require each exact CFR PTS. No previous-frame fallback.

    https://pyav.org/docs/stable/api/container.html#av.container.InputContainer.seek
    """
    import av,numpy as np
    if camera not in ep.media:raise DataError('CURATION_VIDEO_MISSING',camera,'Camera not recorded')
    info=ep.media[camera];fps=float(info['fps']);offset=float(info.get('from_timestamp',0.))
    if not np.isfinite(fps) or fps<=0 or not np.isfinite(offset):raise DataError('CURATION_INVALID',camera,'Finite video clock required')
    with av.open(str(info['path'])) as container:
        stream=container.streams.video[0];first=offset+start/fps
        container.seek(int(first/float(stream.time_base)),stream=stream,backward=True)
        index=start
        for frame in container.decode(video=0):
            if frame.pts is None:raise DataError('CURATION_VIDEO_MISSING',camera,'Decoded frame PTS unavailable')
            timestamp=float(frame.pts*frame.time_base);expected=offset+index/fps
            if timestamp<expected-1e-5:continue
            if abs(timestamp-expected)>1e-5:raise DataError('CURATION_VIDEO_MISSING',camera,'Selected frame missing or non-CFR timing; no nearest fallback')
            rgb=frame.to_ndarray(format='rgb24')
            if list(rgb.shape)!=list(info['shape']) or rgb.dtype!=np.uint8:raise DataError('CURATION_INVALID',camera,'Decoded RGB shape/dtype differs')
            yield index,timestamp,rgb
            index+=1
            if index>=stop:return
    raise DataError('CURATION_VIDEO_MISSING',camera,'Selected video interval incomplete')


def review_frame(source,selection_id,frame,*,cameras=None,fields=None):
    """UI-ready original/selection ordinal, recorded values and decoded RGB copies."""
    from dataclasses import replace
    catalog=_catalog(source);ep=_episode(catalog,selection_id);stop=ep.num_frames if ep.stop is None else ep.stop
    if type(frame) is not int or not 0<=frame<stop-ep.start:raise DataError('CURATION_INVALID','frame','Selection-relative frame outside half-open range')
    index=ep.start+frame;single=replace(ep,start=index,stop=index+1)
    fields=fields if fields is not None else ('observation.state','action') if ep.format=='lerobot' else ('obs/policy/joint_pos','joint_targets')
    values={name:next(_chunks((single,),name,1,{}))[0].copy() for name in fields}
    cameras=tuple(ep.media) if cameras is None else tuple(cameras);rgb={};pts={}
    for name in cameras:
        _,pts[name],rgb[name]=next(_video_frames(ep,name,index,index+1))
    return dict(selection_id=selection_id,selection_frame=frame,original_frame=index,values=values,rgb=rgb,video_pts_s=pts,source_identity=asdict(catalog.identity),frame_convention='zero_based_selection_and_original_ordinals')


def rgb_statistics(source,camera,*,split=None,stride=1):
    """Streaming decoded-channel distribution; sampling is explicit, never whole-image buffering."""
    import numpy as np
    if type(stride) is not int or stride<1:raise DataError('CURATION_INVALID','stride','Positive frame stride required')
    catalog=_catalog(source);episodes=select_split(catalog,split);count=0;decoded=0;pixels=0;total=np.zeros(3);square=np.zeros(3);low=np.full(3,255);high=np.zeros(3)
    for ep in episodes:
        stop=ep.num_frames if ep.stop is None else ep.stop
        for index,_,rgb in _video_frames(ep,camera,ep.start,stop):
            decoded+=1
            if (index-ep.start)%stride:continue
            image=rgb.reshape(-1,3).astype(np.float64);total+=image.sum(0);square+=np.square(image).sum(0);low=np.minimum(low,image.min(0));high=np.maximum(high,image.max(0));pixels+=len(image);count+=1
    if not count:raise DataError('CURATION_VIDEO_MISSING',camera,'No selected RGB frames')
    mean=total/pixels
    return dict(scope=_scope(catalog,split,episodes),camera=camera,decoded_frames=decoded,sampled_frames=count,sampled=stride!=1,stride=stride,unit='uint8_rgb_0_255',
                pixel_count=pixels,mean_rgb_0_255=mean.tolist(),std_rgb_0_255=np.sqrt(np.maximum(square/pixels-mean**2,0)).tolist(),min_rgb=low.tolist(),max_rgb=high.tolist(),distribution_source='decoded_stored_MP4_not_original_uncompressed_sensor')


def position_distribution(source,object_id,*,scene,frame,split=None):
    """One selected-start point per Episode; reference coordinate transform, meters."""
    import numpy as np,h5py
    from scene_contract.transforms import resolve_transform,validate_transform
    catalog=_catalog(source);recording=catalog.execution.get('recording',{})
    if recording.get('pose_frame')!='robot_base' or recording.get('units')!='m_rad_s':raise DataError('CURATION_FRAME_UNKNOWN','recording','Explicit robot_base matrix pose in meters required')
    if asdict(scene.identity)!=catalog.execution.get('scene_identity'):raise DataError('CURATION_INCOMPATIBLE','scene','Exact recorded Scene Revision required')
    transform=resolve_transform(scene.scene['frames'],source='robot_base',target=frame);points=[]
    for ep in select_split(catalog,split):
        if ep.format!='isaac_hdf5':raise DataError('CURATION_FIELD_MISSING','object_pose','Official training projection has no original object pose; inspect its Native source')
        with h5py.File(ep.file,'r') as file:
            name='data/'+ep.key+'/obs/datagen_info/object_pose/'+object_id
            if name not in file:raise DataError('CURATION_FIELD_MISSING',object_id,'Recorded object matrix missing')
            matrix=validate_transform(file[name][ep.start])
        point=(transform@matrix)[:3,3]
        points.append(dict(selection_id=ep.selection_id or ep.episode_id,original_frame=ep.start,xyz_m=point.tolist(),xy_m=point[:2].tolist()))
    return dict(scope=_scope(catalog,split,select_split(catalog,split)),object_id=object_id,frame=frame,source_frame='robot_base',unit='m',
                sampling='selected_interval_first_recorded_pose_not_physics_reset_state',points=points,transform_state='reference')


def revision_history(source):
    """Current revision -> parent -> immutable original/materialized identity."""
    catalog=_catalog(source);rows=[]
    while True:
        rows.append(dict(path=str(catalog.root),identity=asdict(catalog.identity),kind=catalog.kind,episodes=len(catalog.episodes),
                         frames=sum((e.num_frames if e.stop is None else e.stop)-e.start for e in catalog.episodes)))
        if catalog.kind!='curated':return rows
        catalog=_parent(catalog)
