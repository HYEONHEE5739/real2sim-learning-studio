"""Official HDF5 files, immutable segment lifetime and execution metadata.

No array serializer, Dataset index, per-Episode descriptor or legacy-format reader.
Isaac Lab 2.3 EpisodeData/handler are imported only when their data API is needed.
"""
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path
import base64
import hashlib
import json
import gzip
import os
import re
import shutil
import uuid
import h5py
import numpy as np


class DataError(ValueError):
    def __init__(self,code,field,reason,effect='not_started'):
        self.code=code;self.message=f'{field}: {reason}';self.effect=effect
        self.issues=({'field':field,'reason':reason},)
        super().__init__(self.message)


def plain(v):
    if isinstance(v,Mapping):return {k:plain(x) for k,x in v.items()}
    if isinstance(v,(tuple,list)):return [plain(x) for x in v]
    if isinstance(v,np.ndarray):
        if v.dtype.hasobject:return {'dtype':v.dtype.str,'shape':list(v.shape),'values':[plain(x) for x in v.flat]}
        return {'dtype':v.dtype.str,'shape':list(v.shape),'base64':base64.b64encode(v.tobytes()).decode()}
    if isinstance(v,np.generic):return plain(v.item())
    if isinstance(v,bytes):return {'bytes_base64':base64.b64encode(v).decode()}
    if isinstance(v,Path):return str(v)
    return v


def encoded(v):return json.dumps(plain(v),sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(v):return hashlib.sha256(encoded(v)).hexdigest()
def file_sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()


def decode_json(raw):
    def pairs(rows):
        d={}
        for k,v in rows:
            if k in d:raise DataError('DATA_INVALID','JSON','duplicate key')
            d[k]=v
        return d
    value=json.loads(raw,object_pairs_hook=pairs);encoded(value);return value


def read_json(path):
    try:
        raw=Path(path).read_bytes()
        if str(path).endswith('.gz'):raw=gzip.decompress(raw)
        return decode_json(raw)
    except (OSError,ValueError) as exc:raise DataError('DATA_INVALID',str(path),str(exc)) from exc


def _sync(directory):
    fd=os.open(directory,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def atomic_json(path,value,*,exclusive=False):
    path=Path(path);raw=encoded(value)
    if path.suffix=='.gz':raw=gzip.compress(raw,mtime=0)
    if exclusive:
        with path.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    else:
        tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with tmp.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
        finally:tmp.unlink(missing_ok=True)
    _sync(path.parent)


def _id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}',value):raise DataError('DATA_INVALID','id','unsafe/empty identifier')
    return value


def _path(root,relative):
    p=Path(relative)
    if p.is_absolute() or '..' in p.parts or not p.parts:raise DataError('DATA_INVALID','path','package-relative path required')
    target=root/p
    if not target.resolve().is_relative_to(root.resolve()):raise DataError('DATA_INVALID','path','path escapes segment')
    return target


def native_api():
    from isaaclab.utils.datasets import EpisodeData,HDF5DatasetFileHandler
    return EpisodeData,HDF5DatasetFileHandler


def semantic_identity(execution):
    return digest({k:v for k,v in execution.items() if k not in ('max_attempts','target_successes','episodes')})


@dataclass(frozen=True)
class DatasetIdentity:
    dataset_id:str
    metadata_sha256:str


@dataclass(frozen=True)
class NativeEpisode:
    episode_id:str
    file:Path
    key:str
    num_frames:int
    metadata:dict
    media:dict
    source_root:Path
    start:int=0
    stop:int|None=None
    selection_id:str|None=None
    format:str='isaac_hdf5'


@dataclass(frozen=True)
class Catalog:
    root:Path
    identity:DatasetIdentity
    episodes:tuple
    execution:dict
    kind:str='native'
    splits:dict|None=None
    metadata:dict|None=None


def open_native(episode):
    _,Handler=native_api();handler=Handler();handler.open(str(episode.file),'r');return handler


def load_catalog(path,*,expected=None):
    root=Path(path).resolve()
    if root.is_file():
        from .curation import load_curation
        return load_curation(root,expected=expected)
    if (root/'meta/info.json').is_file():
        from .lerobot import lerobot_catalog
        return lerobot_catalog(root,expected=expected)
    record=read_json(root/'run.json')
    if record.get('kind')!='native_run' or record.get('schema_version')!=1:raise DataError('SCHEMA_UNSUPPORTED','run','Native run required')
    metadata=read_json(_path(root,record['metadata_file']))
    rows=[];metas=[];seen=set()
    producer_identities={semantic_identity(record['execution'])}
    for previous in record.get('execution_history',[]):
        if not isinstance(previous,dict):raise DataError('DATA_INVALID','execution_history','producer execution records required')
        producer_identities.add(semantic_identity(previous))
    for folder in sorted((root/'segments').iterdir()):
        if not folder.is_dir():continue
        meta=read_json(folder/'segment.json.gz');metas.append(meta)
        if meta.get('execution_identity') not in producer_identities:raise DataError('RESUME_INCOMPATIBLE','execution','segment identity mismatch')
        if meta.get('complete') is not True:raise DataError('DATA_INCOMPLETE',str(folder),'unsealed published segment')
        with h5py.File(folder/'data.hdf5','r') as f:
            names=set(f['data'])
            if names!=set(meta['episodes']):raise DataError('DATA_INCOMPLETE',str(folder),'published header/count mismatch')
            for key in meta['episode_order']:
                item=meta['episodes'][key]
                if item['episode_id'] in seen:raise DataError('EPISODE_CONFLICT','episode_id','duplicate completed identity')
                seen.add(item['episode_id']);count=int(f['data/'+key].attrs['num_samples'])
                if count!=item['num_frames']:raise DataError('DATA_INCOMPLETE',key,'frame count mismatch')
                media={camera:{**info,'path':str(_path(folder,info['path']))} for camera,info in item['media'].items()}
                for info in media.values():
                    p=Path(info['path'])
                    if not p.is_file() or p.stat().st_size!=info['size_bytes']:raise DataError('DATA_MISSING',str(p),'media missing/size changed')
                rows.append(NativeEpisode(item['episode_id'],folder/'data.hdf5',key,count,item['metadata'],media,root))
    identity=DatasetIdentity(record['dataset_id'],digest({'run':{k:v for k,v in record.items() if k!='closed'},'segments':metas,'metadata':metadata}))
    if expected is not None and identity!=expected:raise DataError('INPUT_CHANGED',str(root),'Native metadata identity changed')
    return Catalog(root,identity,tuple(rows),record['execution'],metadata=metadata)


def mimic_episodes(catalog):
    return tuple(sorted(catalog.episodes,key=lambda e:e.metadata['pool_key']))


def read_array(episode,name,*,frames=True):
    """Bounded official HDF5 hyperslab, avoiding a full Episode tensor copy for export."""
    if episode.format!='isaac_hdf5':raise DataError('DATA_INVALID','format','HDF5 array path required')
    with h5py.File(episode.file,'r') as f:
        d=f['data/'+episode.key+'/'+name]
        return d[episode.start:episode.stop if episode.stop is not None else episode.num_frames] if frames else d[()]


def share_file(source,target,*,independent=False):
    source=Path(source).resolve();target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    if independent:shutil.copyfile(source,target)
    else:
        try:os.link(source,target)
        except OSError as exc:raise DataError('SHARING_UNAVAILABLE',str(source),'same-filesystem hardlink required; request independent copy explicitly') from exc


@dataclass(frozen=True)
class PublishedSegment:
    path:Path
    episodes:tuple
    published:bool=True


class NativeRun:
    """Own the lifetime of immutable official files, not an Episode serialization API."""
    def __init__(self,output,execution,*,metadata=None,append=False):
        import fcntl
        self.root=Path(output).resolve();self.execution=read_execution=plain(execution)
        if execution.get('stage') not in ('source','annotation','datagen','simulation_evaluation','real_evaluation'):raise DataError('DATA_INVALID','execution.stage','recording stage required')
        if append:
            self._append_existing(metadata)
            return
        try:self.root.mkdir(parents=True,exist_ok=False)
        except FileExistsError as exc:raise DataError('OUTPUT_EXISTS',str(output),'new output required') from exc
        self._lock=(self.root/'.writer.lock').open('xb');fcntl.flock(self._lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for name in ('segments','.staging','.claims','attempts'):(self.root/name).mkdir()
        self.metadata=plain(metadata or {})
        atomic_json(self.root/'provenance.json.gz',self.metadata,exclusive=True)
        self.record={'kind':'native_run','schema_version':1,'dataset_id':uuid.uuid4().hex,'execution':read_execution,'closed':False,'metadata_file':'provenance.json.gz'}
        atomic_json(self.root/'run.json',self.record,exclusive=True)
        self._pending=[];self._ordinal=0;self._episode_ordinal=0;self._episode_ids=set();self._closed=False

    def _append_existing(self,metadata):
        """Explicit same-path continuation; never reopen a published HDF5 file."""
        self._lock=_inactive(self.root)
        try:
            catalog=load_catalog(self.root);_validate_continuation(catalog,self.execution,allow_producer_update=True)
            if metadata is not None and plain(metadata)!=catalog.metadata:raise DataError('RESUME_INCOMPATIBLE','metadata','Existing provenance must be preserved')
            # The explicit append request may continue past an inactive crashed
            # attempt. Preserve its unknown outcome and consume its ID, no retry.
            completed={r['attempt'] for r in history(self.root)}
            for path in (self.root/'.claims').glob('*.json'):
                claim=read_json(path)
                if claim['state']=='claimed' and not (self.root/claim['target']).is_dir():
                    claim['state']='interrupted_unknown';atomic_json(path,claim)
            for path in (self.root/'attempts').glob('*.json'):
                row=read_json(path)
                if row['attempt'] not in completed:row['state']='interrupted_unknown';atomic_json(path,row)
            self.metadata=catalog.metadata;self.record=read_json(self.root/'run.json')
            if semantic_identity(self.record['execution'])!=semantic_identity(self.execution):
                self.record.setdefault('execution_history',[]).append(self.record['execution'])
            self.record['execution']=self.execution;self.record['closed']=False
            atomic_json(self.root/'run.json',self.record)
            self._pending=[];self._closed=False
            ordinals=[int(p.name.split('-')[0]) for p in (self.root/'segments').iterdir()]
            ordinals += [int(Path(read_json(p)['target']).name.split('-')[0]) for p in (self.root/'.claims').glob('*.json')]
            self._ordinal=max(ordinals,default=-1)+1;self._episode_ordinal=len(catalog.episodes);self._episode_ids={ep.episode_id for ep in catalog.episodes}
        except BaseException:self._lock.close();raise

    def claim_attempt(self,segment):
        if segment.owner is not self or segment.closed:raise DataError('DATA_INVALID','attempt','live owned segment required')
        numbers=[int(p.stem) for p in (self.root/'attempts').glob('*.json')]
        number=max(numbers,default=0)+1
        limit=self.execution.get('max_attempts')
        if limit is not None and number>limit:raise DataError('BUDGET_EXHAUSTED','attempt','global max attempts reached')
        base=self.execution.get('seed')
        if type(base) is not int or base<0:raise DataError('DATA_INVALID','seed','explicit seed required')
        seed=int(np.random.SeedSequence([base,number]).generate_state(1)[0]) if self.execution['stage']=='datagen' else (base+number-1)%2**32
        claim={'attempt':number,'seed':seed,'intent_id':segment.claim['intent_id'],'state':'claimed'}
        atomic_json(self.root/'attempts'/f'{number:08d}.json',claim,exclusive=True)
        return claim

    def segment(self,intent_id,*,request=None):
        if self._closed:raise DataError('DATA_INVALID','run','closed owner')
        _id(intent_id);request=plain(request or {});claim_path=self.root/'.claims'/(intent_id+'.json')
        if claim_path.exists():
            claim=read_json(claim_path)
            if claim['request_sha256']!=digest(request):raise DataError('REQUEST_CONFLICT',intent_id,'same intent with different payload')
            target=_path(self.root,claim['target'])
            if target.is_dir():
                catalog=load_catalog(self.root)
                return PublishedSegment(target,tuple(e for e in catalog.episodes if e.file.parent==target))
            raise DataError('NATIVE_STATE_UNKNOWN',intent_id,'claimed but not published; explicit recovery, never automatic retry')
        target=f'segments/{self._ordinal:08d}-{intent_id}';self._ordinal+=1
        claim={'intent_id':intent_id,'request_sha256':digest(request),'target':target,'state':'claimed'}
        atomic_json(claim_path,claim,exclusive=True)
        segment=NativeSegment(self,claim);self._pending.append(segment);return segment

    def close(self):
        if self._closed:return
        try:
            for segment in self._pending:
                if not segment.published:segment.abort()
            self.record['closed']=True;atomic_json(self.root/'run.json',self.record)
        finally:self._lock.close();self._closed=True

    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class NativeSegment:
    """Pending official HDF5 file(s). Only commit publishes an acknowledged segment."""
    def __init__(self,owner,claim):
        _,Handler=native_api()
        self.owner=owner;self.claim=claim;self.folder=owner.root/'.staging'/claim['intent_id'];self.folder.mkdir()
        env_args=owner.metadata.get('source_data_attrs',{}).get('env_args')
        recorded=json.loads(env_args) if isinstance(env_args,str) else {}
        self.handler=Handler();self.handler.create(str(self.folder/'data.hdf5'),env_name=owner.execution.get('env_name',recorded.get('env_name','')))
        # Original potentially large legacy env_args is losslessly retained once
        # in provenance.json.gz; each native file has the official env identity.
        self.rows={};self.attempts=[];self.failed=False;self.published=False;self.closed=False

    def record_attempt(self,claim,*,status,episode_id=None,diagnostics=None):
        if self.closed or claim['intent_id']!=self.claim['intent_id']:raise DataError('DATA_INVALID','attempt','wrong owner/closed segment')
        if status not in ('success','failure','ik_failure','cancelled','interrupted'):raise DataError('DATA_INVALID','status','unknown attempt outcome')
        if status=='success' and not any(row['episode_id']==episode_id for row in self.rows.values()):raise DataError('DATA_INVALID','attempt','success needs a pending real Episode')
        actual=read_json(self.owner.root/'attempts'/f'{claim["attempt"]:08d}.json')
        if actual!=claim:raise DataError('REQUEST_CONFLICT','attempt','claim identity changed')
        record={**claim,'status':status,'episode_id':episode_id,'diagnostics':plain(diagnostics or {})}
        if any(row['attempt']==claim['attempt'] for row in self.attempts):raise DataError('REQUEST_CONFLICT','attempt','already completed')
        self.attempts.append(record)

    def write_episode(self,episode,*,episode_id=None,metadata=None,media=None,independent_media=False):
        if self.closed or self.failed:raise DataError('DATA_INVALID','segment','not writable')
        episode_id=_id(episode_id or uuid.uuid4().hex)
        if episode_id in self.owner._episode_ids:raise DataError('EPISODE_CONFLICT',episode_id,'duplicate run Episode identity')
        try:
            episode.pre_export()
            if 'actions' not in episode.data or len(episode.data['actions'])<1:raise DataError('DATA_INVALID','actions','nonempty official actions required')
            count=len(episode.data['actions']);key=f'demo_{self.handler.demo_count}'
            def lengths(data,prefix=''):
                for name,value in data.items():
                    field=prefix+name
                    if isinstance(value,dict):lengths(value,field+'/')
                    elif field.split('/')[0] in ('actions','joint_targets','obs','states','collection','ik') and (not hasattr(value,'shape') or not value.shape or value.shape[0]!=count):
                        raise DataError('DATA_INVALID',field,'known time-series count mismatch')
            lengths(episode.data)
            self.handler.write_episode(episode)  # Installed official gzip/Tensor implementation.
            stored={}
            for camera,item in (media or {}).items():
                _id(camera);info={'path':str(item)} if isinstance(item,(str,Path)) else dict(item)
                source=Path(info['path']);target=self.folder/'media'/key/(camera+'.mp4')
                import av
                with av.open(str(source)) as container:
                    stream=container.streams.video[0]
                    if stream.frames!=count:raise DataError('DATA_INVALID',camera,'finalized video/frame count mismatch')
                    header={'frames':count,'fps':str(stream.average_rate),'shape':[stream.height,stream.width,3]}
                share_file(source,target,independent=independent_media)
                stored[camera]={**header,'path':target.relative_to(self.folder).as_posix(),'size_bytes':target.stat().st_size}
            ep_metadata={'pool_key':f'demo_{self.owner._episode_ordinal}','official_success':episode.success,**plain(metadata or {})}
            self.owner._episode_ordinal+=1
            self.owner._episode_ids.add(episode_id)
            self.rows[key]={'episode_id':episode_id,'num_frames':count,'metadata':ep_metadata,'media':stored}
            return key  # Pending, never a completion acknowledgement.
        except BaseException:self.failed=True;raise

    def commit(self):
        if self.published:return self.result
        if self.failed or self.closed:raise DataError('DATA_INCOMPLETE','segment','failed/closed segment cannot publish')
        try:
            self.handler.flush();self.handler.close();self.closed=True
            with h5py.File(self.folder/'data.hdf5','r') as f:
                if set(f['data'])!=set(self.rows):raise DataError('DATA_INCOMPLETE','header','unexpected partial Episode')
                for key,row in self.rows.items():
                    if int(f['data/'+key].attrs['num_samples'])!=row['num_frames']:raise DataError('DATA_INCOMPLETE',key,'known count mismatch')
            with (self.folder/'data.hdf5').open('rb') as f:os.fsync(f.fileno())
            metadata={'complete':True,'execution_identity':semantic_identity(self.owner.execution),'intent':self.claim,'episodes':self.rows,'episode_order':list(self.rows),'attempts':self.attempts}
            atomic_json(self.folder/'segment.json.gz',metadata,exclusive=True)
            for row in self.rows.values():
                for info in row['media'].values():
                    with (self.folder/info['path']).open('rb') as f:os.fsync(f.fileno())
            _sync(self.folder)
            target=_path(self.owner.root,self.claim['target']);os.rename(self.folder,target);_sync(target.parent)
            self.published=True
            refs=tuple(NativeEpisode(row['episode_id'],target/'data.hdf5',key,row['num_frames'],row['metadata'],
                       {camera:{**info,'path':str(target/info['path'])} for camera,info in row['media'].items()},self.owner.root) for key,row in self.rows.items())
            self.result=PublishedSegment(target,refs);return self.result
        except BaseException:self.failed=True;raise

    def abort(self):
        if self.published:return
        try:self.handler.close()
        finally:self.closed=True;self.failed=True


def _inactive(root):
    import fcntl
    try:
        lock=(root/'.writer.lock').open('rb');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as exc:raise DataError('RUN_ACTIVE',str(root),'source writer is still active') from exc
    else:return lock


def history(root):
    root=Path(root);rows=[]
    for path in sorted((root/'segments').glob('*/segment.json.gz')):rows.extend(read_json(path)['attempts'])
    for path in sorted((root/'attempts').glob('*.json')):
        row=read_json(path)
        if row.get('state')=='interrupted_unknown':rows.append({**row,'status':'interrupted_unknown'})
    numbers=[row['attempt'] for row in rows]
    if len(set(numbers))!=len(numbers):raise DataError('DATA_INVALID','attempts','duplicate attempt history')
    return sorted(rows,key=lambda row:row['attempt'])


def recover(root,*,acknowledge_interrupted=False):
    """Explicit recovery only, with no live owner and no automatic staging promotion."""
    root=Path(root).resolve();lock=_inactive(root)
    try:
        catalog=load_catalog(root);unresolved=[];claimed=[]
        for path in sorted((root/'.claims').glob('*.json')):
            row=read_json(path)
            if not (root/row['target']).is_dir() and row['state']=='claimed':
                unresolved.append(row['intent_id'])
                if acknowledge_interrupted:row['state']='interrupted_unknown';atomic_json(path,row)
        completed={row['attempt'] for row in history(root)}
        for path in sorted((root/'attempts').glob('*.json')):
            row=read_json(path)
            if row['attempt'] not in completed:
                claimed.append(row['attempt'])
                if acknowledge_interrupted:row['state']='interrupted_unknown';atomic_json(path,row)
        return {'completed_episodes':len(catalog.episodes),'unresolved_intents':unresolved,'interrupted_attempts':claimed,
                'acknowledged':acknowledge_interrupted,'staging_promoted':False}
    finally:lock.close()


def _validate_continuation(catalog,execution,*,allow_producer_update=False):
    old=catalog.execution
    required={'scene_identity','calibration','task_code','seed','engine','recording','model_sha256','active_objects','partition','rng_policy'}
    if old.get('stage')=='simulation_evaluation':required.update(('policy_identity','evaluation_contract'))
    if old.get('stage')=='datagen':required.update(('annotated_input','source_pool_order'))
    if not required<=old.keys() or any(old[k] is None for k in required) or old.get('archive_only') or (old['stage']=='datagen' and not old.get('ik')):raise DataError('RESUME_INCOMPATIBLE','execution','essential historical identity missing')
    if old['stage']=='source' and old.get('partition')!='unpartitioned':raise DataError('RESUME_INCOMPATIBLE','partition','partitioned Source cannot continue collection')
    if old['stage']=='datagen':
        ik=old['ik']
        if ik.get('solver')!='pinocchio_dls' or ik.get('policy')!='best_effort':raise DataError('RESUME_INCOMPATIBLE','ik','only fixed Pinocchio DLS + Best Effort continuation is supported')
        fields={'solver','policy','code_sha256','model_sha256','frame','joint_order','parameters','safety','seed_reference'}
        if not fields<=ik.keys() or any(ik[k] is None for k in fields):raise DataError('RESUME_INCOMPATIBLE','ik','complete explicit solver/code/model/frame/parameters/safety/seed binding required')
    # A same-path append may use updated workflow orchestration, recorded per
    # immutable producer segment. Task/IK code and every data/physics contract
    # remain strict; historical segments are never relabeled with new code.
    def semantic_core(value):
        result=dict(value)
        if allow_producer_update and 'workflow_code' in result:
            # These shared producer helpers were moved from the same exempt
            # concrete loops. Keep their existing class, not physics/IK/Task math.
            orchestration={'source.py','annotation.py','datagen.py','evaluation.py','run.py','recipe.py','cli.py','native.py','recording.py','publication.py','commands.py','configuration.py'}
            result['workflow_code']={k:v for k,v in result['workflow_code'].items() if Path(k).name not in orchestration}
        return result
    before=semantic_core(old);after=semantic_core(execution)
    if old['stage'] not in ('source','datagen','simulation_evaluation') or semantic_identity(before)!=semantic_identity(after):raise DataError('RESUME_INCOMPATIBLE','execution','different policy/Scene/Task/Calibration/seed/phase')
    attempts=history(catalog.root)
    success_ids=[row.get('episode_id') for row in attempts if row['status']=='success' or (old['stage']=='simulation_evaluation' and row['status']=='failure' and row.get('episode_id') is not None)]
    if set(success_ids)!={ep.episode_id for ep in catalog.episodes} or len(success_ids)!=len(catalog.episodes):raise DataError('RESUME_INCOMPATIBLE','history','accepted attempts and completed Episodes disagree or history is missing')
    if execution.get('max_attempts',10**18)<max((row['attempt'] for row in attempts),default=0):raise DataError('RESUME_INCOMPATIBLE','max_attempts','budget below consumed global attempts')
    if execution.get('target_successes',execution.get('episodes',10**18))<len(catalog.episodes):raise DataError('RESUME_INCOMPATIBLE','target','cumulative target below completed Episodes')


def resume_to(previous,output,execution,*,independent=False):
    """Reuse closed official segments in a new run, never append to an old file."""
    previous=Path(previous).resolve();lock=_inactive(previous)
    try:
        catalog=load_catalog(previous);old=catalog.execution
        _validate_continuation(catalog,execution)
        if recover_unlocked(previous):raise DataError('NATIVE_STATE_UNKNOWN','resume','unresolved execution intent/attempt; explicit recovery acknowledgement required')
        run=NativeRun(output,execution,metadata=catalog.metadata)
        try:
            producer_history=read_json(previous/'run.json').get('execution_history')
            if producer_history:
                run.record['execution_history']=producer_history
                atomic_json(run.root/'run.json',run.record)
            for folder in (previous/'segments').iterdir():
                if not folder.is_dir():continue
                target=run.root/'segments'/folder.name;staging=run.root/'.staging'/('clone-'+folder.name);staging.mkdir()
                for path in folder.rglob('*'):
                    if path.is_file():share_file(path,staging/path.relative_to(folder),independent=independent)
                _sync(staging);os.rename(staging,target);_sync(target.parent)
            for path in (previous/'attempts').glob('*.json'):shutil.copyfile(path,run.root/'attempts'/path.name)
            run._ordinal=max((int(p.name.split('-')[0]) for p in (run.root/'segments').iterdir()),default=-1)+1
            run._episode_ordinal=len(catalog.episodes)
            run._episode_ids={ep.episode_id for ep in catalog.episodes}
            run.record['parent']={'dataset_id':catalog.identity.dataset_id,'metadata_sha256':catalog.identity.metadata_sha256}
            atomic_json(run.root/'run.json',run.record)
            return run
        except BaseException:run.close();raise
    finally:lock.close()


def recover_unlocked(root):
    completed={row['attempt'] for row in history(root)}
    unknown=[row for path in (root/'.claims').glob('*.json') if (row:=read_json(path))['state']=='claimed' and not (root/row['target']).is_dir()]
    unknown.extend(read_json(path) for path in (root/'attempts').glob('*.json') if read_json(path)['attempt'] not in completed)
    return unknown


def import_hdf5(source,output,*,stage,groups=None,segment_episodes=10,execution=None,independent_media=False):
    """Explicit existing official/Common HDF5 -> official Native segments.

    No Workbench A-format compatibility. Original arrays retain their native names,
    dtype and phase; unsupported Tensor leaves and attrs are provenance only.
    """
    import torch
    EpisodeData,_=native_api();source=Path(source).resolve()
    if source==Path(output).resolve() or Path(output).resolve().is_relative_to(source.parent):
        raise DataError('OUTPUT_CONFLICT','output','separate validation/output space required')
    if type(segment_episodes) is not int or segment_episodes<1:raise DataError('DATA_INVALID','segment_episodes','positive count required')
    with h5py.File(source,'r') as f:
        names=sorted(f['data'],key=lambda name:int(name.split('_')[-1])) if groups is None else list(groups)
        if not names or len(set(names))!=len(names) or not set(names)<=set(f['data']):raise DataError('DATA_INVALID','groups','empty/duplicate/missing native Episodes')
        root_metadata={'source_sha256':file_sha256(source),'source_root_attrs':plain(dict(f.attrs)),
                       'source_data_attrs':plain(dict(f['data'].attrs)),'source_pool_order':list(f['data'])}
        extra={}
        def external(name,node):
            if name=='data' or name.startswith('data/'):return
            extra[name]={'attrs':plain(dict(node.attrs))}
            if isinstance(node,h5py.Dataset):extra[name]['value']=plain(node[()])
        f.visititems(external);root_metadata['source_other_groups']=extra
        cfg=execution or {'stage':stage,'archive_only':True,'identity_availability':'recorded legacy Metadata only; exact runtime Resume not established'}
        with NativeRun(output,cfg,metadata=root_metadata) as run:
            segment=None
            for index,name in enumerate(names):
                if index%segment_episodes==0:segment=run.segment(f'import-{index:08d}',request={'source_sha256':root_metadata['source_sha256'],'groups':names[index:index+segment_episodes]})
                group=f['data/'+name];arrays={};unsupported={}
                def collect(key,node):
                    if not isinstance(node,h5py.Dataset):return
                    if node.is_virtual or node.external:raise DataError('DATA_INVALID',key,'external/virtual arrays require explicit resolution')
                    value=node[()]
                    if value.dtype.kind in 'biufc':arrays[key]=torch.from_numpy(value)
                    else:unsupported[key]=plain(value)
                group.visititems(collect)
                data={}
                for key,value in arrays.items():
                    target=data;parts=key.split('/')
                    for part in parts[:-1]:target=target.setdefault(part,{})
                    target[parts[-1]]=value
                ep=EpisodeData();ep.data=data
                if 'seed' in group.attrs:ep.seed=int(group.attrs['seed'])
                if 'success' in group.attrs:ep.success=bool(group.attrs['success'])
                attrs=plain(dict(group.attrs));videos=json.loads(group.attrs.get('external_videos','{}'))
                media={camera:_path(source.parent,info['file']) for camera,info in videos.items()}
                segment.write_episode(ep,episode_id=name,metadata={'pool_key':name,'legacy_attributes':attrs,'non_tensor_arrays':unsupported,
                    'requested_applied_availability':'only recorded fields; missing telemetry is not reconstructed',
                    'event_phase':'original pre-step stored boundary; post-step latch/manual mark not shifted'},media=media,independent_media=independent_media)
                if (index+1)%segment_episodes==0 or index==len(names)-1:segment.commit()
        return load_catalog(run.root)


def import_canonical(source,output,*,stage,episode_ids=None,segment_episodes=10,independent_media=False):
    """One-shot original Canonical NPY import, not a runtime compatibility reader.

    No FK, frame reinterpretation, MiniVLA model or guessed simulation initial state.
    """
    import torch
    EpisodeData,_=native_api();source=Path(source).resolve();output=Path(output).resolve()
    if output.is_relative_to(source) or source.is_relative_to(output):raise DataError('OUTPUT_CONFLICT','output','separate output space required')
    manifest=read_json(source/'manifest.json')
    if manifest.get('schema_version')!=1:raise DataError('SCHEMA_UNSUPPORTED','manifest','explicit original Canonical /1 required')
    by_id={row['id']:row for row in manifest['episodes']};ids=list(by_id) if episode_ids is None else list(episode_ids)
    if not ids or len(set(ids))!=len(ids) or not set(ids)<=by_id.keys():raise DataError('DATA_INVALID','episodes','invalid original selection')
    metadata={'canonical_manifest':manifest,'source_manifest_sha256':file_sha256(source/'manifest.json')}
    if (source/'project_provenance.json').is_file():metadata['project_provenance']=read_json(source/'project_provenance.json')
    with NativeRun(output,{'stage':stage,'archive_only':True},metadata=metadata) as run:
        for i,id_ in enumerate(ids):
            if i%segment_episodes==0:segment=run.segment(f'import-{i:08d}')
            row=by_id[id_];folder=_path(source,row['path']);arrays={p.name:np.load(p,allow_pickle=False) for p in sorted(folder.glob('*.npy'))}
            if not {'raw_state.npy','raw_action.npy','timestamp.npy'}<=arrays.keys():raise DataError('DATA_INVALID',id_,'explicit raw model arrays/time required')
            paths={'raw_state.npy':'obs/policy/joint_pos','raw_action.npy':'actions','timestamp.npy':'obs/timestamp'}
            paths.update({name:'obs/legacy/'+Path(name).stem for name in arrays if name not in paths})
            data={}
            for name,value in arrays.items():
                if value.dtype.kind not in 'biuf':raise DataError('DATA_INVALID',name,'numeric original arrays required')
                d=data;parts=paths[name].split('/')
                for part in parts[:-1]:d=d.setdefault(part,{})
                d[parts[-1]]=torch.from_numpy(value)
            extras={p.stem:read_json(p) for p in folder.glob('*.json')}
            ep=EpisodeData();ep.data=data
            success=extras.get('outcome',{}).get('success')
            if isinstance(success,bool):ep.success=success
            segment.write_episode(ep,episode_id=id_,metadata={'canonical_entry':row,'original_json':extras,'array_paths':paths,
                'recorded_policy_units':manifest.get('units'),'pool_key':id_,'replay_resume_available':False,
                'action_semantics':'original raw model joint targets; not Mimic TCP deltas; no missing datagen_info synthesized'},
                media={camera:_path(folder,info['file']) for camera,info in row.get('videos',{}).items()},independent_media=independent_media)
            if (i+1)%segment_episodes==0 or i==len(ids)-1:segment.commit()
    return load_catalog(run.root)


def collection_settings(options,output,*,stage):
    """Additional requested episodes/budget -> runtime cumulative counters only."""
    settings=dict(options)
    if 'num_episodes' not in settings:return settings
    count=0;attempt=0
    if settings.get('resume'):
        catalog=load_catalog(output);count=len(catalog.episodes)
        attempt=max((row['attempt'] for row in history(output)),default=0)
        # A killed in-flight attempt also consumes its allocated number.
        attempt=max(attempt,max((int(p.stem) for p in (Path(output)/'attempts').glob('*.json')),default=0))
    settings['episodes' if stage=='source' else 'target_successes']=count+settings['num_episodes']
    if stage=='datagen':settings['max_attempts']=attempt+settings['max_attempts']
    settings['previous_episodes']=count;settings['requested_additions']=settings['num_episodes']
    return settings
