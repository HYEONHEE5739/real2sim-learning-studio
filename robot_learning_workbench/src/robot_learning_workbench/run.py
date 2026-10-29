"""Local worker lifecycle, durable claims and JSON IPC; no launcher/service layer."""
from dataclasses import dataclass,field,replace
from pathlib import Path
from types import MappingProxyType
import fcntl
import importlib
import json
import os
import re
import struct
import subprocess
import sys
import threading
import time
import uuid
from .recipe import RecipeError,Issue,read_recipe,verify_prepared_inputs,_plain,_bytes,_sha


class RunError(RecipeError):pass

def _fail(code,field,reason):raise RunError(code,field,reason)
def _identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,159}',value) or value in ('.','..'):_fail('REQUEST_INVALID','id','safe non-path identifier required')
    return value

def _sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)

def _atomic(path,value):
    temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    try:
        with temp.open('xb') as f:f.write(_bytes(value));f.flush();os.fsync(f.fileno())
        os.replace(temp,path);_sync(path.parent)
    finally:temp.unlink(missing_ok=True)

def _exclusive(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'wb') as f:f.write(_bytes(value));f.flush();os.fsync(f.fileno())
    finally:_sync(path.parent)

def _decode(raw):
    def unique(pairs):
        out={}
        for key,value in pairs:
            if key in out:raise ValueError('duplicate JSON key')
            out[key]=value
        return out
    data=json.loads(raw,object_pairs_hook=unique);_bytes(data);return data


def _read(path):
    try:
        return _decode(path.read_bytes())
    except (OSError,ValueError,TypeError) as exc:raise RunError('RUN_STATE_UNKNOWN',str(path),'missing/incomplete state') from exc


@dataclass(frozen=True)
class StartRequest:
    request_id:str
    recipe_path:Path
    expected_recipe_sha256:str
    expected_stage:str
    output_path:Path
    task_modules_path:Path|None=None
    expected_modules_sha256:str|None=None
    expected_prepared_sha256:str|None=None


@dataclass(frozen=True)
class WorkerRequest:
    request:StartRequest
    run_id:str
    run_dir:Path
    python_executable:str
    worker_token:str


@dataclass(frozen=True)
class RunHandle:
    run_id:str
    request_id:str
    run_dir:Path


@dataclass(frozen=True)
class RunStatus:
    status:str
    phase:str
    progress:object
    last_event_seq:int
    error:object=None


@dataclass(frozen=True)
class StageResult:
    status:str
    output_refs:tuple=()
    completed_episodes:int=0
    attempt_summary:object=field(default_factory=dict)


@dataclass(frozen=True)
class RunResult:
    run_id:str
    status:str
    output_refs:tuple=()
    error:object=None


def _error(exc,effect=None):
    return {'code':getattr(exc,'code','WORKER_ERROR'),'message':str(exc),'issues':_plain(getattr(exc,'issues',())),
        'effect':effect or getattr(exc,'effect','unknown')}


def _status(path,status,phase,*,error=None,**extra):
    data=_read(path/'run.json') if (path/'run.json').exists() else {'progress':{},'last_event_seq':0}
    _atomic(path/'run.json',{**data,**extra,'status':status,'phase':phase,'error':error})


def _worker_identity():
    raw=Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()
    return {'pid':os.getpid(),'start_ticks':raw[19],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def read_status(run_dir):
    path=Path(run_dir);data=_read(path/'run.json');error=data.get('error');status=data['status'];phase=data['phase']
    identity=data.get('worker_identity')
    spawn=_read(path/'spawn.json') if (path/'spawn.json').is_file() else {}
    if identity is None:identity=spawn.get('process_identity')
    if status not in ('completed','cancelled','failed') and identity is None and spawn.get('identity_unobservable'):
        return RunStatus('unknown','unknown',data.get('progress',{}),data.get('last_event_seq',0),{'code':'RUN_STATE_UNKNOWN','message':'spawned process identity was not observable','effect':'unknown','issues':[]})
    if status not in ('completed','cancelled','failed') and identity:
        try:
            raw=Path(f"/proc/{identity['pid']}/stat").read_text().rsplit(')',1)[1].split()
            alive=raw[0]!='Z' and raw[19]==identity['start_ticks'] and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==identity['boot_id']
        except (OSError,KeyError,IndexError):alive=False
        if not alive:status='unknown';phase='unknown';error={'code':'RUN_STATE_UNKNOWN','message':'worker identity no longer observable','effect':'unknown','issues':[]}
    return RunStatus(status,phase,data.get('progress',{}),data.get('last_event_seq',0),error)


def _monitor(process,run_dir):
    code=process.wait()
    try:
        current=_read(run_dir/'run.json')
        if current['status'] not in ('completed','cancelled','failed'):
            _status(run_dir,'failed','terminal',error={'code':'WORKER_EXITED','message':f'worker exited with {code} before terminal record','issues':[],'effect':'unknown'})
    except (RunError,OSError):pass


def start(request,*,run_root=None):
    _identifier(request.request_id)
    req=replace(request,recipe_path=Path(request.recipe_path).resolve(),output_path=Path(request.output_path).absolute(),
        task_modules_path=Path(request.task_modules_path).resolve() if request.task_modules_path else None)
    root=Path(run_root).absolute() if run_root else req.output_path.parent/'.workbench-runs'
    claim=root/'requests'/(_sha(req.request_id.encode())+'.json');pre_doc=None
    if not claim.exists():
        pre_doc=read_recipe(req.recipe_path,expected_stage=req.expected_stage)
    (root/'requests').mkdir(parents=True,exist_ok=True)
    payload=_sha(_bytes(req));run_id=uuid.uuid4().hex;run_dir=root/run_id
    try:fd=os.open(claim,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        old=_read(claim)
        if old.get('payload_sha256')!=payload:_fail('REQUEST_CONFLICT','request_id','same ID with different payload')
        if not old.get('run_id') or not old.get('run_dir') or not (Path(old['run_dir'])/'run.json').is_file():_fail('RUN_STATE_UNKNOWN','request_id','claim incomplete; no automatic restart')
        known=Path(old['run_dir']);status=_read(known/'run.json')
        if status['status'] not in ('completed','failed','cancelled') and not (known/'spawn.json').exists() and not (known/'worker.claim').exists():_fail('RUN_STATE_UNKNOWN','request_id','spawn acknowledgement missing; no automatic restart')
        return RunHandle(old['run_id'],req.request_id,Path(old['run_dir']))
    run_dir.mkdir();info={'run_id':run_id,'run_dir':str(run_dir),'payload_sha256':payload}
    with os.fdopen(fd,'wb') as f:f.write(_bytes(info));f.flush();os.fsync(f.fileno())
    _sync(claim.parent);_status(run_dir,'prepared','preparing',request_id=req.request_id,run_id=run_id,stage=req.expected_stage,claim_path=str(claim))
    try:
        doc=pre_doc or read_recipe(req.recipe_path,expected_stage=req.expected_stage)
        if doc.sha256!=req.expected_recipe_sha256:_fail('INPUT_CHANGED','recipe','saved YAML changed')
        output=(doc.base_dir/doc.spec.output['directory']).resolve()
        if output!=req.output_path.resolve():_fail('REQUEST_CONFLICT','output','must match saved Recipe')
        appending=doc.spec.stage in ('source','datagen') and doc.spec.execution.get('resume',False)
        if output.exists() and not appending:_fail('OUTPUT_EXISTS','output','new output required')
        if appending:
            from .data.native import load_catalog
            existing=load_catalog(output)
            expected_engine='isaac' if doc.spec.engine=='isaaclab' else doc.spec.engine
            if existing.kind!='native' or existing.execution.get('stage')!=doc.spec.stage or existing.execution.get('engine')!=expected_engine:_fail('RESUME_INCOMPATIBLE','output','matching recording stage/engine required')
        if (doc.spec.objects or doc.spec.functions) and (req.task_modules_path is None or req.expected_modules_sha256 is None):_fail('TASK_MODULES_INVALID','task_modules','explicit list and expected bytes SHA required')
        for key,value in doc.spec.inputs.items():
            if key in ('repo_id','revision') or isinstance(value,tuple) or value.startswith('hf://'):continue
            source=(doc.base_dir/value).resolve()
            boundary=source.parent if key=='scene' else source if source.is_dir() else None
            if boundary is not None and output.is_relative_to(boundary):_fail('OUTPUT_EXISTS','output','immutable input boundary')
        output.parent.mkdir(parents=True,exist_ok=True)
        reservation=output.parent/('.workbench-output-'+_sha(str(output).encode())+'.json')
        with reservation.with_suffix('.lock').open('a+b') as reservation_lock:
            fcntl.flock(reservation_lock,fcntl.LOCK_EX)
            if reservation.exists():
                old=_read(reservation)
                if not appending or read_status(old['run_dir']).status not in ('completed','cancelled','failed','unknown'):_fail('OUTPUT_EXISTS','output','reserved by another active run')
                _atomic(reservation,info)
            else:_exclusive(reservation,info)
        for folder in ('commands','acks'):(run_dir/folder).mkdir()
        wire=WorkerRequest(req,run_id,run_dir,sys.executable,uuid.uuid4().hex);_atomic(run_dir/'worker_request.json',_plain(wire))
        info['worker_request_sha256']=_sha((run_dir/'worker_request.json').read_bytes());_atomic(claim,info)
        with (run_dir/'stdout.log').open('ab',buffering=0) as log:
            process=subprocess.Popen([sys.executable,'-B','-m','robot_learning_workbench.cli','worker',str(run_dir)],env=_worker_environment(),stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,close_fds=True)
        spawn={'worker_token':wire.worker_token,'process_spawn_returned':True}
        if type(getattr(process,'pid',None)) is int:
            try:
                stat=Path(f'/proc/{process.pid}/stat').read_text().rsplit(')',1)[1].split()
                spawn['process_identity']={'pid':process.pid,'start_ticks':stat[19],'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
            except OSError:spawn['identity_unobservable']=True
        _atomic(run_dir/'spawn.json',spawn)
        if hasattr(process,'wait'):threading.Thread(target=_monitor,args=(process,run_dir),daemon=True).start()
        return RunHandle(run_id,req.request_id,run_dir)
    except Exception as exc:
        _status(run_dir,'failed','terminal',error=_error(exc,'not_started'));raise


@dataclass(frozen=True)
class EventPage:
    items:tuple
    next_seq:int


@dataclass(frozen=True)
class CommandReceipt:
    command_id:str
    status:str
    applied_tick:int|None=None
    reason:str|None=None


def load_worker_request(run_dir):
    path=Path(run_dir).resolve();data=_read(path/'worker_request.json');req=data['request']
    for key in ('recipe_path','output_path','task_modules_path'):
        if req.get(key) is not None:req[key]=Path(req[key])
    return WorkerRequest(StartRequest(**req),data['run_id'],Path(data['run_dir']),data['python_executable'],data['worker_token'])


def _append_event(run_dir,state,kind,payload):
    seq=state['seq']+1;event={'protocol_version':1,'run_id':run_dir.name,'seq':seq,'kind':kind,'payload':_plain(payload)}
    raw=_bytes(event)
    if len(raw)>65536:_fail('PROTOCOL_INVALID','event','control message exceeds 64KiB; images use Preview channel')
    with (run_dir/'events.jsonl').open('ab') as stream:
        offset=stream.tell();stream.write(raw+b'\n');stream.flush();os.fsync(stream.fileno())
    with (run_dir/'events.idx').open('ab') as index:index.write(struct.pack('<Q',offset));index.flush();os.fsync(index.fileno())
    state['seq']=seq;current=_read(run_dir/'run.json');current['last_event_seq']=seq
    if kind=='status':
        for key in ('status','phase','progress'):
            if key in payload:current[key]=_plain(payload[key])
        for key in ('episode_id','env_index','tick'):
            if key in payload:state['context'][key]=payload[key]
        if 'env_index' in payload:
            state.setdefault('env_contexts',{}).setdefault(payload['env_index'],{}).update({k:payload[k] for k in ('episode_id','env_index','tick') if k in payload})
    if state.get('preview') is not None:current['latest_preview']=state['preview']
    _atomic(run_dir/'run.json',current)
    return event


def read_events(run_dir,after_seq=0,limit=200):
    if type(after_seq) is not int or after_seq<0 or type(limit) is not int or not 1<=limit<=1000:_fail('PROTOCOL_INVALID','page','invalid seq/limit')
    root=Path(run_dir);path=root/'events.idx'
    if not path.exists():return EventPage((),after_seq)
    size=path.stat().st_size
    if size%8:_fail('RUN_STATE_UNKNOWN','events.idx','incomplete event index')
    count=size//8
    if after_seq>count:_fail('PROTOCOL_INVALID','after_seq','beyond recorded stream')
    if after_seq==count:return EventPage((),after_seq)
    rows=[]
    with path.open('rb') as index,(root/'events.jsonl').open('rb') as stream:
        index.seek(after_seq*8);offset=struct.unpack('<Q',index.read(8))[0];stream.seek(offset)
        for expected in range(after_seq+1,min(count,after_seq+limit)+1):
            raw=stream.readline(65538)
            try:row=json.loads(raw)
            except ValueError as exc:raise RunError('RUN_STATE_UNKNOWN','events','incomplete event') from exc
            if type(row.get('protocol_version')) is not int or row['protocol_version']!=1 or type(row.get('seq')) is not int or row['seq']!=expected or row['run_id']!=root.name:_fail('PROTOCOL_INVALID','event','stream identity/sequence mismatch')
            rows.append(row)
    return EventPage(tuple(rows),after_seq+len(rows))


def read_preview(run_dir):return _read(Path(run_dir)/'run.json').get('latest_preview')


def _ack(run_dir,state,command_id,status,*,applied_tick=None,reason=None):
    path=run_dir/'acks'/(_identifier(command_id)+'.json');receipt=CommandReceipt(command_id,status,applied_tick,reason)
    if path.exists():
        old=_read(path)
        if old['status'] in ('completed','rejected'):
            if old!=_plain(receipt):_fail('REQUEST_CONFLICT','command_ack','different terminal acknowledgement')
            return CommandReceipt(**old)
    _atomic(path,_plain(receipt));_append_event(run_dir,state,'command_ack',_plain(receipt));return receipt


_COMMANDS={'gripper_approve':{'proposal_sha256','target_raw','supervised','clear','stop_ready'},'cancel':{'reason'},'pause':set(),'resume':set(),'step':{'count'},'mark':{'event','frame'},'skip':{'reason'},'save':set(),'discard':{'reason'}}
_SESSION_COMMANDS={'session_snapshot':set(),'session_disconnect':set(),'session_finish':set(),'teleop_prepare':set(),'teleop_stop':set(),
                   'teleop_start':{'proposal_sha256','supervised','clear','stop_ready','direction_checked','ranges_checked','preserve_torque'},'session_import':{'snapshot_id'}}
_COMMANDS.update(_SESSION_COMMANDS)


def _command(command):
    if not isinstance(command,dict) or set(command)-{'command_id','kind','payload','episode_id','env_index'}:_fail('PROTOCOL_INVALID','command','unknown envelope fields')
    _identifier(command.get('command_id'));kind=command.get('kind');payload=command.get('payload',{})
    if kind not in _COMMANDS or not isinstance(payload,dict) or set(payload)-_COMMANDS[kind]:_fail('PROTOCOL_INVALID','command','unsupported kind/payload fields')
    if kind in _SESSION_COMMANDS and set(payload)!=_SESSION_COMMANDS[kind]:_fail('PROTOCOL_INVALID',kind,'exact session command fields required')
    if kind=='session_import':_identifier(payload['snapshot_id'])
    if kind=='teleop_start'and(not isinstance(payload['proposal_sha256'],str)or len(payload['proposal_sha256'])!=64 or any(payload[k]is not True for k in _SESSION_COMMANDS[kind]-{'proposal_sha256'})):_fail('PROTOCOL_INVALID',kind,'fresh proposal SHA and explicit on-site confirmations required')
    if kind=='gripper_approve' and (set(payload)!=_COMMANDS[kind] or not isinstance(payload.get('proposal_sha256'),str) or len(payload['proposal_sha256'])!=64 or type(payload.get('target_raw'))is not int or any(type(payload.get(k))is not bool for k in ('supervised','clear','stop_ready'))):_fail('PROTOCOL_INVALID','gripper_approve','Exact SHA/target and explicit safety confirmations required')
    if kind=='step' and (type(payload.get('count')) is not int or not 1<=payload['count']<=1000):_fail('PROTOCOL_INVALID','step.count','expected 1..1000')
    if kind=='mark' and (not isinstance(payload.get('event'),str) or type(payload.get('frame')) is not int or payload['frame']<0):_fail('PROTOCOL_INVALID','mark','event and nonnegative frame required')
    if kind in ('mark','skip','save','discard') and not command.get('episode_id'):_fail('PROTOCOL_INVALID','episode_id','explicit target required')
    if 'episode_id' in command:_identifier(command['episode_id'])
    if 'env_index' in command and (type(command['env_index']) is not int or command['env_index']<0):_fail('PROTOCOL_INVALID','env_index','nonnegative integer required')
    if len(_bytes(command))>65536:_fail('PROTOCOL_INVALID','command','control payload exceeds 64KiB')
    if 'reason' in payload and not isinstance(payload['reason'],str):_fail('PROTOCOL_INVALID','reason','string required')
    return command


def send_command(handle,command):
    command=_command(_plain(command));root=Path(handle.run_dir)
    record=_read(root/'run.json')
    if handle.run_id!=root.name or handle.request_id!=record.get('request_id'):_fail('REQUEST_CONFLICT','handle','run identity mismatch')
    command_id=command['command_id'];path=root/'commands'/(command_id+'.json')
    with (root/'control.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if path.exists():
            old=_read(path)
            if old['payload']!=command:_fail('REQUEST_CONFLICT','command_id','same ID with different command')
        else:
            counter=root/'commands.seq';seq=(_read(counter) if counter.exists() else 0)+1;_atomic(counter,seq)
            envelope={'protocol_version':1,'run_id':handle.run_id,'seq':seq,'kind':'command','payload':command};_exclusive(path,envelope)
        ack=root/'acks'/(command_id+'.json')
        if ack.exists():return CommandReceipt(**_read(ack))
        if read_status(root).status in ('completed','failed','cancelled','unknown'):
            receipt=CommandReceipt(command_id,'rejected',reason='run is terminal or unknown');_atomic(ack,_plain(receipt));return receipt
    return CommandReceipt(command_id,'queued')


def touch_session(handle,timestamp_ns):
    """Latest UI liveness only. User commands still use durable ACK transactions."""
    root=Path(handle.run_dir);record=_read(root/'run.json')
    if type(timestamp_ns)is not int or timestamp_ns<=0 or handle.run_id!=root.name or handle.request_id!=record.get('request_id') or record.get('stage')not in('capture_session','paired_session'):
        _fail('PROTOCOL_INVALID','heartbeat','Current session handle and monotonic timestamp required')
    _atomic(root/'session-heartbeat.json',{'run_id':handle.run_id,'timestamp_ns':timestamp_ns})


def _poll_commands(root,state,stage):
    with (root/'control.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        rows=[]
        for path in (root/'commands').glob('*.json'):
            if path.stem in state['seen_commands']:continue
            row=_read(path)
            if row.get('payload',{}).get('command_id')!=path.stem:_fail('PROTOCOL_INVALID','command_id','file identity mismatch')
            rows.append(row)
    rows.sort(key=lambda row:row['seq']);out=[]
    allowed={'cancel'}|({'pause','resume','step'} if stage in ('source','annotation','datagen','simulation_evaluation','real_sim') else set())|({'mark','skip'} if stage=='annotation' else set())|({'save','discard'} if stage=='source' else set())
    if stage in('capture_session','paired_session'):allowed|=set(_SESSION_COMMANDS)
    for row in rows:
        if type(row.get('protocol_version')) is not int or row['protocol_version']!=1 or row.get('run_id')!=root.name or type(row.get('seq')) is not int or row['seq']<1:_fail('PROTOCOL_INVALID','command','stream identity/sequence mismatch')
        command=_command(row['payload']);cid=command['command_id']
        if cid in state['seen_commands']:continue
        if row['seq']<=state['command_seq']:_fail('PROTOCOL_INVALID','command','duplicate/out-of-order sequence')
        state['seen_commands'].add(cid);state['command_seq']=row['seq']
        reason=None
        if command['kind'] not in allowed:reason='command unsupported by this stage'
        target_context=(state['env_contexts'].get(command.get('env_index'),{}) if 'env_contexts' in state and 'env_index' in command else state['context'])
        for key in ('episode_id','env_index'):
            if key in command and command[key]!=target_context.get(key):reason='command target is not the current Episode/environment'
        if reason:_ack(root,state,cid,'rejected',reason=reason);continue
        _ack(root,state,cid,'accepted');out.append(command)
        if command['kind']=='cancel':_append_event(root,state,'status',{'status':'running','phase':'stopping'})
    if stage in('capture_session','paired_session')and(root/'session-heartbeat.json').is_file():
        heartbeat=_read(root/'session-heartbeat.json')
        if heartbeat.get('run_id')!=root.name or type(heartbeat.get('timestamp_ns'))is not int:_fail('PROTOCOL_INVALID','heartbeat','Invalid session liveness')
        out.append({'kind':'session_heartbeat','command_id':'liveness','payload':{'timestamp_ns':heartbeat['timestamp_ns']}})
    return tuple(out)


def _stage_event(root,state,event):
    if not isinstance(event,dict) or set(event)!={'kind','payload'} or not isinstance(event['payload'],dict):_fail('PROTOCOL_INVALID','event','kind/payload required')
    kind=event['kind'];payload=event['payload'];_validate_event_payload(kind,payload);_bytes(payload)
    if kind=='command_ack':
        cid=payload.get('command_id');_identifier(cid);ack=root/'acks'/(cid+'.json')
        if not ack.exists() or _read(ack)['status'] not in ('accepted','completed'):_fail('PROTOCOL_INVALID','command_ack','command must be accepted first')
        if payload.get('status')=='rejected':
            if set(payload)!={'command_id','status','reason'} or not isinstance(payload['reason'],str) or not payload['reason']:_fail('PROTOCOL_INVALID','command_ack','rejection reason required')
            return _ack(root,state,cid,'rejected',reason=payload['reason'])
        command=_read(root/'commands'/(cid+'.json'))['payload'];tick=payload.get('applied_tick')
        if payload.get('status')!='completed' or (command['kind'] in ('mark','skip','step','save','discard') and (type(tick) is not int or tick<0)):_fail('PROTOCOL_INVALID','command_ack','completion/applied tick required')
        return _ack(root,state,cid,'completed',applied_tick=tick)
    if kind=='preview':
        if set(payload)-{'camera','slot','generation','frame_index','time_s','env_index','shape','published_monotonic_ns'} or not {'camera','slot','generation','frame_index','time_s'}<=set(payload) or any(type(payload[k]) is not int or payload[k]<0 for k in ('slot','generation','frame_index')):_fail('PROTOCOL_INVALID','preview','metadata only; slot/generation/frame required')
        state['preview_seq']+=1;state['preview']={'protocol_version':1,'run_id':root.name,'seq':state['preview_seq'],'kind':kind,'payload':payload};return
    if kind not in ('status','log','error','episode_committed'):_fail('PROTOCOL_INVALID','kind','unknown worker event')
    if kind=='status' and (set(payload)-{'status','phase','progress','episode_id','env_index','tick'} or payload.get('status','running')!='running' or payload.get('phase','running') not in ('running','stopping')):_fail('PROTOCOL_INVALID','status','stage may report progress, not terminal completion')
    if kind=='episode_committed':
        from .data.native import load_catalog,DatasetIdentity
        dataset=load_catalog(payload['dataset_path'],expected=DatasetIdentity(**payload['dataset_identity']))
        if not any(e.episode_id==payload['episode_id'] for e in dataset.episodes):_fail('PROTOCOL_INVALID','episode_id','not in a published Native segment')
    return _append_event(root,state,kind,payload)


def _run_stage(plan,*,events,commands):
    package=Path(__file__).parent
    if plan.stage in ('source','annotation','datagen','simulation_evaluation'):
        filename='evaluation' if plan.stage=='simulation_evaluation' else plan.stage
        module=f'engines.{plan.engine}.{filename}';function='run'
    elif plan.stage=='paired_rerender':module='robot.real_sim';function='rerender'
    elif plan.stage in('capture_session','paired_session'):module='robot.session';function='run'
    elif plan.stage in ('capture','precision_calibration','real_evaluation','real_sim'):
        module='robot.offline' if plan.effective_settings['execution'].get('mode')=='offline' else 'robot.teleoperation' if plan.effective_settings['execution'].get('mode')=='fake_all' else 'robot.live';function='run'
    elif plan.stage=='teleoperation':module='robot.teleoperation';function='run'
    elif plan.stage in ('hub_download','hub_upload'):module='learning.hub';function='run'
    elif plan.stage in ('convert','merge'):module='data.lerobot';function='run'
    elif plan.stage=='train':module='learning.train';function='train'
    elif plan.stage=='offline_validation':module='learning.validate';function='evaluate'
    else:_fail('STAGE_UNAVAILABLE','stage','this stage runner has not been implemented')
    if not (package/Path(*module.split('.'))).with_suffix('.py').is_file():_fail('STAGE_UNAVAILABLE','stage',module+' is not implemented')
    launcher=None
    try:
        if plan.engine=='isaac' and (plan.stage in ('source','annotation','datagen','simulation_evaluation') or plan.stage=='real_sim' and plan.effective_settings['execution'].get('mode')!='offline'):
            from isaaclab.app import AppLauncher
            # SimulationApp5.1 fast_shutdown=True may exit the process inside
            # close(), before execute() publishes its terminal run record.
            # Official config: isaacsim.simulation_app.SimulationApp.
            launcher=AppLauncher(headless=plan.effective_settings['execution'].get('headless',False),enable_cameras=True,device='cuda:0',fast_shutdown=False)
        return getattr(importlib.import_module('.'+module,package='robot_learning_workbench'),function)(plan,events=events,commands=commands)
    finally:
        if launcher is not None:launcher.app.close()


def execute(request,*,_runner=None):
    root=Path(request.run_dir).resolve();_identifier(request.run_id)
    if Path(request.python_executable).resolve()!=Path(sys.executable).resolve():_fail('REQUEST_CONFLICT','python_executable','different worker interpreter')
    if root.name!=request.run_id or _plain(load_worker_request(root))!=_plain(request):_fail('REQUEST_CONFLICT','worker','worker request differs from saved intent')
    initial=_read(root/'run.json');claim=_read(Path(initial['claim_path']))
    if _sha((root/'worker_request.json').read_bytes())!=claim.get('worker_request_sha256') or _sha(_bytes(request.request))!=claim['payload_sha256']:
        _fail('INPUT_CHANGED','worker_request','saved request identity changed')
    try:_exclusive(root/'worker.claim',{'worker_token':request.worker_token,'identity':_worker_identity()})
    except FileExistsError:_fail('RUN_STATE_UNKNOWN','worker','worker claim already exists; no restart/replay')
    state={'seq':0,'context':{},'seen_commands':set(),'command_seq':0,'preview_seq':0,'preview':None};lock=threading.RLock();started=False
    _status(root,'prepared','preparing',worker_identity=_worker_identity(),fixture_runner=_runner is not None)
    def events(event):
        with lock:return _stage_event(root,state,event)
    def commands():
        with lock:return _poll_commands(root,state,request.request.expected_stage)
    try:
        from .recipe import _parse_recipe,prepare_recipe
        raw=request.request.recipe_path.read_bytes()
        if _sha(raw)!=request.request.expected_recipe_sha256:_fail('INPUT_CHANGED','recipe','saved YAML changed before worker read')
        doc=_parse_recipe(request.request.recipe_path,raw,request.request.expected_stage)
        if str(request.request.output_path.resolve())!=str((doc.base_dir/doc.spec.output['directory']).resolve()):_fail('REQUEST_CONFLICT','output','worker output differs from Recipe')
        tasks=None;module_path=request.request.task_modules_path
        if module_path is not None:
            raw_modules=module_path.read_bytes()
            if _sha(raw_modules)!=request.request.expected_modules_sha256:_fail('INPUT_CHANGED','task_modules','module list changed')
            from .tasks.registry import read_module_names,load_registry
            tasks=load_registry(read_module_names(module_path))
            if _sha(module_path.read_bytes())!=_sha(raw_modules):_fail('INPUT_CHANGED','task_modules','module list changed during import')
            with (root/'task_modules.yaml').open('xb') as f:f.write(raw_modules);f.flush();os.fsync(f.fileno())
        plan=prepare_recipe(doc,scene=None,tasks=tasks,inputs={})
        if request.request.expected_prepared_sha256 is not None and request.request.expected_prepared_sha256!=plan.sha256:_fail('INPUT_CHANGED','prepared','validated plan/input identities changed')
        with (root/'recipe.yaml').open('xb') as f:f.write(doc.raw);f.flush();os.fsync(f.fileno())
        _atomic(root/'prepared.json',plan.summary());_sync(root)
        _append_event(root,state,'status',{'status':'prepared','phase':'preparing'})
        verify_prepared_inputs(plan)
        _append_event(root,state,'status',{'status':'running','phase':'running'})
        started=True
        with preview_session(root,events):
            result=(_runner or _run_stage)(plan,events=events,commands=commands)
        if not isinstance(result,StageResult) or not isinstance(result.output_refs,(tuple,list)) or result.status not in ('completed','cancelled') or type(result.completed_episodes) is not int or result.completed_episodes<0 or not isinstance(result.attempt_summary,dict):
            _fail('STAGE_RESULT_INVALID','stage','concrete StageResult with valid counters required')
        for ref in result.output_refs:
            path=Path(ref['path'] if isinstance(ref,dict) else ref)
            if not path.is_absolute():path=plan.output_path/path
            if not path.exists():_fail('STAGE_RESULT_INVALID','output_refs','returned artifact does not exist')
        if result.completed_episodes:
            from .data.native import load_catalog
            dataset=load_catalog(plan.output_path)
            if len(dataset.episodes)<result.completed_episodes:_fail('STAGE_RESULT_INVALID','completed_episodes','more than published Native Episodes')
        outcome=RunResult(request.run_id,result.status,tuple(result.output_refs));_atomic(root/'result.json',_plain(outcome))
        _status(root,result.status,'terminal',output_refs=_plain(result.output_refs),completed_episodes=result.completed_episodes,attempt_summary=result.attempt_summary)
        _append_event(root,state,'status',{'status':result.status,'phase':'terminal'});return outcome
    except Exception as exc:
        import traceback
        traceback.print_exc()
        error=_error(exc,'unknown' if started and getattr(exc,'code',None)!='STAGE_UNAVAILABLE' else 'not_started')
        result=RunResult(request.run_id,'failed',error=error)
        _atomic(root/'result.json',_plain(result));_status(root,'failed','terminal',error=error)
        try:_append_event(root,state,'error',error);_append_event(root,state,'status',{'status':'failed','phase':'terminal'})
        except (OSError,RunError):pass
        return result


def _worker_environment():
    # Source checkouts and installed packages use the same interpreter/environment.
    # Propagate only the two project package locations, not arbitrary UI sys.path entries.
    import importlib.util
    roots=[str(Path(__file__).parent.parent)]
    spec=importlib.util.find_spec('scene_contract')
    if spec is not None and spec.origin:roots.append(str(Path(spec.origin).parent.parent))
    current=os.environ.get('PYTHONPATH')
    if current:roots.append(current)
    return {**os.environ,'PYTHONPATH':os.pathsep.join(roots),'PYTHONDONTWRITEBYTECODE':'1'}


def _validate_event_payload(kind,payload):
    if kind=='log':
        if set(payload)-{'level','message','source'} or payload.get('level') not in ('debug','info','warning','error') or not isinstance(payload.get('message'),str):
            _fail('PROTOCOL_INVALID','log','level and string message required')
    elif kind=='status':
        if 'progress' in payload and not isinstance(payload['progress'],dict):_fail('PROTOCOL_INVALID','progress','counter mapping required')
        for key in ('env_index','tick'):
            if key in payload and (type(payload[key]) is not int or payload[key]<0):_fail('PROTOCOL_INVALID',key,'nonnegative integer required')
        if 'episode_id' in payload:_identifier(payload['episode_id'])
    elif kind=='preview':
        import math
        if not isinstance(payload.get('camera'),str) or not payload['camera'] or type(payload.get('time_s')) not in (int,float) or not math.isfinite(payload['time_s']):
            _fail('PROTOCOL_INVALID','preview','camera and finite recorded time required')
    elif kind=='error':
        if not isinstance(payload.get('code'),str) or not isinstance(payload.get('message'),str) or payload.get('effect') not in ('not_started','not_applied','applied','unknown'):
            _fail('PROTOCOL_INVALID','error','structured code/message/effect required')
    elif kind=='episode_committed':
        if set(payload)!={'dataset_path','dataset_identity','episode_id'} or not isinstance(payload['dataset_identity'],dict):
            _fail('PROTOCOL_INVALID','episode_committed','completed Dataset index identity required')


from contextlib import contextmanager


@contextmanager
def preview_session(run_dir,events,*,interval_s=1/30):
    """Two owned PPM slots per camera, process-local sink, no recording dependency."""
    import shutil,mmap
    from .data import video
    root=Path(run_dir);folder=root/'preview'
    try:folder.mkdir(exist_ok=False)
    except OSError as error:
        events({'kind':'log','payload':{'level':'warning','message':'Preview setup unavailable: '+str(error)}})
        yield
        return
    previous=video._preview_sink;generation={};last={};warned=False;preview_lock=threading.RLock();slots={}
    def publish_frame(camera,image,frame_index,time_s,env_index=0):
        nonlocal warned
        if camera not in ('side','wrist','sim_side','sim_wrist'):return
        selection=folder/'selection.json'
        selected=_read(selection).get('env_index',0) if selection.is_file() else 0
        if selected!=env_index:return
        now=time.monotonic()
        if now-last.get(camera,-float('inf'))<interval_s:return
        last[camera]=now;number=generation.get(camera,0)+1;generation[camera]=number;slot=number%2
        try:
            rgb=image;height,width=rgb.shape[:2]
            stamp=f'{root.name} {camera} {number:020d}'
            ppm=f'P6\n# {stamp}\n{width} {height}\n255\n'.encode()+rgb.tobytes()
            path=folder/f'{camera}-{slot}.ppm'
            if path not in slots:
                file=path.open('w+b');file.truncate(len(ppm));slots[path]=(file,mmap.mmap(file.fileno(),len(ppm)))
            mapping=slots[path][1]
            mapping[0:1]=b'X'  # Invalidate before touching payload; commit the header last.
            header_size=len(ppm)-rgb.nbytes
            mapping[header_size:]=ppm[header_size:];mapping[1:header_size]=ppm[1:header_size];mapping[0:1]=b'P'
            metadata=dict(run_id=root.name,camera=camera,slot=slot,generation=number,frame_index=frame_index,time_s=time_s,env_index=env_index,shape=list(rgb.shape),published_monotonic_ns=time.monotonic_ns())
            # Existing IPC preview envelope stays metadata-only.
            target=folder/(camera+'.json');temporary=folder/(camera+'.json.tmp')
            temporary.write_bytes(_bytes(metadata));os.replace(temporary,target)
            events({'kind':'preview','payload':{k:v for k,v in metadata.items() if k!='run_id'}})
        except Exception as error:
            if not warned:
                warned=True;events({'kind':'log','payload':{'level':'warning','message':'Preview unavailable: '+str(error)}})
    def publish(*args):
        if not preview_lock.acquire(blocking=False):return
        try:publish_frame(*args)
        except Exception as error:
            nonlocal warned
            if not warned:
                warned=True;events({'kind':'log','payload':{'level':'warning','message':'Preview unavailable: '+str(error)}})
        finally:preview_lock.release()
    video._preview_sink=publish
    try:yield
    finally:
        video._preview_sink=previous
        for file,mapping in slots.values():
            mapping.close();file.close()
        try:
            if folder.is_dir():shutil.rmtree(folder)
            else:folder.unlink(missing_ok=True)
        except OSError as error:events({'kind':'log','payload':{'level':'warning','message':'Preview cleanup unavailable: '+str(error)}})


def read_preview_frame(run_dir,camera):
    """Latest self-identifying PPM bytes; mismatch during overwrite is a dropped preview."""
    if camera not in ('side','wrist','sim_side','sim_wrist'):raise ValueError('Known Real/Sim Side/Wrist preview required')
    root=Path(run_dir);folder=root/'preview'
    try:
        meta=_read(folder/(camera+'.json'))
        if meta['run_id']!=root.name or meta['camera']!=camera or meta['slot'] not in (0,1):return None
        raw=(folder/f'{camera}-{meta["slot"]}.ppm').read_bytes()
        prefix=f'P6\n# {root.name} {camera} {meta["generation"]:020d}\n'.encode()
        if not raw.startswith(prefix):return None
        with (folder/f'{camera}-{meta["slot"]}.ppm').open('rb') as current:
            if current.read(len(prefix))!=prefix:return None
        return meta,raw
    except (OSError,ValueError,KeyError,RunError):return None


def select_preview_env(run_dir,env_index):
    if type(env_index) is not int or env_index<0:raise ValueError('Nonnegative preview env required')
    folder=Path(run_dir)/'preview'
    if folder.is_dir():_atomic(folder/'selection.json',{'env_index':env_index})


def execution_failure(error,*,phase,steps,applying=False):
    import traceback
    traceback.print_exception(type(error),error,error.__traceback__)
    effect='unknown' if applying or phase in ('task','reset') else getattr(error,'effect','not_applied')
    error.effect=effect  # Propagate the observed execution effect with the same error/cause.
    return dict(success=False,category='engine_error' if phase in ('physics','reset') else 'camera_error' if phase=='camera' else 'policy_error' if phase=='policy' else 'execution_error',
                error={'phase':phase,**_error(error,effect=effect)},steps=steps,_exception=error)



def abort_videos(videos,report):
    errors=[]
    for writer in videos.values():
        if writer._closed:continue
        try:writer.abort()
        except Exception as error:errors.append(error)
    if errors:report.update(execution_failure(ExceptionGroup('Video cleanup failed',errors),phase='recording_cleanup',steps=report.get('steps',0),applying=True))

