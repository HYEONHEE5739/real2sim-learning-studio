"""Official Trainer subprocess lifetime only; no custom learning loop or hooks.

https://github.com/huggingface/lerobot/blob/v0.4.1/src/lerobot/scripts/lerobot_train.py
"""
import os,sys,re,time,subprocess,signal
from pathlib import Path
from ..data.native import DataError,atomic_json,load_catalog,DatasetIdentity,read_json
from ..data.lerobot import _pinned,control_contract
from .policy import checkpoint_record,seal_checkpoint


def validate_config(config: dict,*,dataset: Path,output: Path,mode: str) -> None:
    _pinned();p=config.get('policy',{});d=config.get('dataset',{})
    if not isinstance(p,dict) or not isinstance(p.get('type'),str):raise DataError('TRAIN_CONFIG_INVALID','policy','Explicit official Policy configuration required')
    if p.get('type')=='smolvla':
        if not p.get('vlm_model_name') or not (Path(p['vlm_model_name'])/'config.json').is_file():raise DataError('TRAIN_CONFIG_INVALID','vlm_model_name','Explicit cached local VLM snapshot required; no network fallback')
        if p.get('adapt_to_pi_aloha',False) or p.get('use_delta_joint_actions_aloha',False):raise DataError('TRAIN_CONFIG_INVALID','action','Absolute model-rad contract required')
    if not config.get('output_dir') or Path(config['output_dir']).resolve()!=output.resolve():raise DataError('TRAIN_CONFIG_INVALID','output_dir','Explicit new output must match Recipe')
    if not d.get('root') or Path(d['root']).resolve()!=dataset.resolve() or not isinstance(d.get('repo_id'),str):raise DataError('TRAIN_CONFIG_INVALID','dataset','Explicit local Dataset must match Recipe')
    if d.get('episodes') is not None or d.get('streaming') or d.get('revision'):raise DataError('TRAIN_CONFIG_INVALID','dataset','Use exact local materialization; no episodes filter/network revision')
    if p.get('push_to_hub',True) or config.get('wandb',{}).get('enable',False):raise DataError('TRAIN_CONFIG_INVALID','external','Hub and WandB disabled in this runner')
    if p.get('pretrained_backbone_weights') is not None:raise DataError('TRAIN_CONFIG_INVALID','weights','Use provisioned local pretrained Policy; no implicit backbone download')
    if mode=='scratch' and p.get('pretrained_path'):raise DataError('TRAIN_CONFIG_INVALID','weights','Scratch must not load Policy pretrained_path; select finetune')
    if mode=='finetune' and not p.get('pretrained_path'):raise DataError('TRAIN_CONFIG_INVALID','weights','Fine-tuning needs explicit local pretrained_path')
    if p.get('pretrained_path') and not (Path(p['pretrained_path'])/'model.safetensors').is_file():raise DataError('TRAIN_CONFIG_INVALID','weights','Local pretrained Policy weights required')
    if mode=='finetune':
        saved=read_json(Path(p['pretrained_path'])/'config.json')
        adjustable={'device','use_amp','push_to_hub','repo_id','private','tags','license','pretrained_path','pretrained_backbone_weights','load_vlm_weights'}
        if any(k not in adjustable and saved.get(k)!=v for k,v in p.items()):raise DataError('TRAIN_CONFIG_INVALID','policy.type/config','Fine-tune architecture/features must match pretrained config')
    if config.get('env') is not None or config.get('eval_freq',0)!=0:raise DataError('TRAIN_CONFIG_INVALID','evaluation','No automatic physical/evaluation environment')
    if bool(config.get('resume',False))!=(mode=='resume'):raise DataError('TRAIN_CONFIG_INVALID','resume','Recipe and official config differ')
    if any(type(config.get(k)) is not int or config[k]<1 for k in ('steps','batch_size','save_freq','log_freq')):raise DataError('TRAIN_CONFIG_INVALID','steps','Explicit positive steps/batch/save/log required')
    if config['log_freq']>config['steps']:raise DataError('TRAIN_CONFIG_INVALID','log_freq','At least one official loss logging step required')
    if not config.get('save_checkpoint',True):raise DataError('TRAIN_CONFIG_INVALID','save_checkpoint','Closed checkpoints required')

    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies import factory
    if p.get('type') not in PreTrainedConfig.get_known_choices():raise DataError('POLICY_UNSUPPORTED','policy','Policy is not registered in installed LeRobot')


def training_command(plan) -> tuple[list[str],dict]:
    from ..recipe import _plain,policy_model_path
    config=_plain(plan.input_documents['training_config']);dataset=Path(plan.resolved_inputs['dataset']['path']);mode=plan.effective_settings['execution']['mode']
    validate_config(config,dataset=dataset,output=plan.output_path,mode=mode)
    control_contract(load_catalog(dataset))  # Known IO must validate; external official data may have no Workbench provenance.
    if mode=='finetune':
        if 'policy' not in plan.resolved_inputs:raise DataError('TRAIN_CONFIG_INVALID','policy','Recipe must pin local fine-tune Policy')
        folder=policy_model_path(plan.resolved_inputs['policy']['path'])
        if folder!=Path(config['policy']['pretrained_path']).resolve():raise DataError('TRAIN_CONFIG_INVALID','policy','Recipe and official pretrained_path differ')
        if (folder.parent/'workbench-checkpoint.json').is_file():checkpoint_record(folder.parent)
    path=Path(plan.resolved_inputs['training_config']['path']);module='robot_learning_workbench.learning.smol_compat' if config['policy']['type']=='smolvla' else 'lerobot.scripts.lerobot_train';args=[sys.executable,'-B','-m',module,'--config_path='+str(path)]
    if mode=='resume':
        if 'checkpoint' not in plan.resolved_inputs:raise DataError('RESUME_INCOMPATIBLE','checkpoint','Explicit closed local checkpoint required')
        root=Path(plan.resolved_inputs['checkpoint']['path']);record=checkpoint_record(root)
        if record['dataset_identity']!=vars(load_catalog(dataset).identity):raise DataError('RESUME_INCOMPATIBLE','dataset','Dataset identity differs from checkpoint')
        if config['policy']['type']=='smolvla':
            from .smol_compat import identity
            if record.get('smol_compatibility')!=identity():raise DataError('RESUME_INCOMPATIBLE','smol_compatibility','Pinned loss patch identity differs or missing')
        old=record['config'];allowed={'steps','output_dir','resume'}
        if {k:v for k,v in old.items() if k not in allowed}!={k:v for k,v in config.items() if k not in allowed}:raise DataError('RESUME_INCOMPATIBLE','config','Only cumulative steps/new output/resume may change')
        if config['steps']<=record['step']:raise DataError('RESUME_INCOMPATIBLE','steps','New cumulative step target required')
        if config['steps']//config['log_freq']==record['step']//config['log_freq']:raise DataError('TRAIN_CONFIG_INVALID','log_freq','Resume interval must contain an official loss logging step')
        args[-1]='--config_path='+str(root/'pretrained_model/train_config.json')
        args+=['--resume=true','--output_dir='+str(plan.output_path),'--steps='+str(config['steps'])]
    return args,config


def freeze_inputs(plan,args: list[str],config: dict) -> list[str]:
    """Exact owned official config; Resume uses a standard linked checkpoint."""
    if plan.effective_settings['execution']['mode']=='resume':
        source=Path(plan.resolved_inputs['checkpoint']['path']);record=checkpoint_record(source)
        root=plan.output_path.with_name(plan.output_path.name+'.resume-input');root.mkdir()
        for name,sha in record['files'].items():
            p=source/name;target=root/name;target.parent.mkdir(parents=True,exist_ok=True)
            if name.endswith('.json'):
                raw=p.read_bytes()
                if __import__('hashlib').sha256(raw).hexdigest()!=sha:raise DataError('INPUT_CHANGED',name,'Checkpoint changed before snapshot')
                target.write_bytes(raw)
            else:os.link(p,target)
        path=root/'pretrained_model/train_config.json'
    else:
        path=plan.output_path.with_name(plan.output_path.name+'.official-config.json');atomic_json(path,config,exclusive=True)
    return ['--config_path='+str(path) if arg.startswith('--config_path=') else arg for arg in args]


def stop_child(process) -> int:
    if process.poll() is not None:return process.wait()
    os.killpg(process.pid,signal.SIGTERM)
    try:return process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGKILL);return process.wait()


def parse_metrics(text: str) -> list[dict]:
    metrics=[]
    for step,value in re.findall(r'step:([\d,]+).*?loss:([+\-\deE.]+)',text):
        try:metrics.append({'step':int(step.replace(',','')),'loss':float(value)})
        except ValueError:continue  # Official raw log remains available; optional display parser.
    return metrics


def nonfinite_step(text: str) -> int|None:
    steps=[int(s.replace(',','')) for s in re.findall(r'step:([\d,]+)[^\n]*(?:loss|grdn):(?:nan|[+-]?inf)\b',text,re.I)]
    return min(steps) if steps else None


def train(plan,*,events,commands):
    from ..recipe import verify_prepared_inputs
    from ..run import StageResult
    verify_prepared_inputs(plan);args,config=training_command(plan)
    if plan.output_path.exists():raise DataError('OUTPUT_EXISTS','output','New training output required')
    dataset_identity=vars(load_catalog(plan.resolved_inputs['dataset']['path']).identity)
    args=freeze_inputs(plan,args,config)
    # Validate through official parser before starting any optimization process.
    from lerobot.policies import factory
    from lerobot.configs.train import TrainPipelineConfig
    parsed=TrainPipelineConfig.from_pretrained(Path(next(a.split('=',1)[1] for a in args if a.startswith('--config_path='))),local_files_only=True)
    parsed.policy.validate_features() if parsed.policy.input_features else None
    log=plan.output_path.with_name(plan.output_path.name+'.official.log');intent=plan.output_path.with_name(plan.output_path.name+'.training-intent.json')
    atomic_json(intent,{'argv':args,'config':config,'recipe_sha256':plan.recipe_sha256,'dataset':dict(plan.resolved_inputs['dataset'])},exclusive=True)
    env=os.environ.copy();env.update(HF_HUB_OFFLINE='1',HF_DATASETS_OFFLINE='1',TRANSFORMERS_OFFLINE='1',WANDB_MODE='disabled',TOKENIZERS_PARALLELISM='false')
    if config['policy'].get('device')=='cpu':env['ACCELERATE_USE_CPU']='true'
    cancelled=False;offset=0;metrics=[];nonfinite=False;checkpoints=[];peak_rss_kib=0;started=time.perf_counter()
    def seal_finished(maximum=None):
        folders=(plan.output_path/'checkpoints');last=folders/'last'
        if not last.is_symlink():return
        cutoff=last.resolve()
        for folder in sorted(folders.glob('[0-9]*')):
            if folder.name>cutoff.name or (maximum is not None and int(folder.name)>maximum) or (folder/'workbench-checkpoint.json').exists():continue
            record=seal_checkpoint(folder,dataset=plan.resolved_inputs['dataset']['path'],config=config,recipe_sha256=plan.recipe_sha256,expected_dataset=dataset_identity)
            checkpoints.append({'path':str(folder),'step':record['step']})
    with log.open('xb',buffering=0) as stream:
        process=subprocess.Popen(args,stdout=stream,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        try:
            while process.poll() is None:
                for command in commands():
                    if command['kind']=='cancel':
                        cancelled=True
                        events({'kind':'command_ack','payload':{'command_id':command['command_id'],'status':'completed'}})
                if cancelled:break
                with log.open('r',errors='replace') as reader:
                    reader.seek(offset);chunk=reader.read();offset=reader.tell()
                if chunk:
                    if re.search(r'\b(?:loss|grdn):(?:nan|[+-]?inf)\b',chunk,re.I):
                        nonfinite=True
                        bad=nonfinite_step(chunk)
                        if bad is not None:seal_finished(maximum=bad-1)
                        break
                    events({'kind':'log','payload':{'level':'info','message':chunk[-16000:]}})
                seal_finished()
                try:
                    match=re.search(r'VmHWM:\s+(\d+)',Path(f'/proc/{process.pid}/status').read_text())
                    if match:peak_rss_kib=max(peak_rss_kib,int(match[1]))
                except FileNotFoundError:pass
                time.sleep(.1)
            code=stop_child(process) if cancelled or nonfinite else process.wait()
        finally:
            if process.poll() is None:
                stop_child(process)
    text=log.read_text(errors='replace')
    metrics=parse_metrics(text)
    nonfinite=nonfinite or bool(re.search(r'\b(?:loss|grdn):(?:nan|[+-]?inf)\b',text,re.I))
    if nonfinite:
        bad=nonfinite_step(text)
        if bad is not None:seal_finished(maximum=bad-1)
        raise DataError('TRAIN_NONFINITE','loss','Nonfinite official metric; previously sealed finite checkpoints preserved',effect='unknown')
    # Editable source config is for the next run; this child used frozen bytes.
    load_catalog(plan.resolved_inputs['dataset']['path'],expected=DatasetIdentity(**dataset_identity))
    for folder in sorted((plan.output_path/'checkpoints').glob('[0-9]*')):
        if folder.is_dir():
            if (folder/'workbench-checkpoint.json').exists():continue
            try:record=seal_checkpoint(folder,dataset=plan.resolved_inputs['dataset']['path'],config=config,recipe_sha256=plan.recipe_sha256,expected_dataset=dataset_identity)
            except (OSError,ValueError):
                if code==0 and not cancelled:raise
                continue
            checkpoints.append({'path':str(folder),'step':record['step']})
    if not cancelled and code:raise DataError('TRAIN_PROCESS_FAILED','official_trainer',f'Exit {code}; see {log}',effect='unknown')
    if not cancelled and (not checkpoints or checkpoints[-1]['step']!=config['steps']):raise DataError('CHECKPOINT_INCOMPLETE','training','Final closed checkpoint missing')
    if plan.output_path.exists():atomic_json(plan.output_path/'training-result.json',{'cancelled':cancelled,'exit_code':code,'metrics':metrics,'checkpoints':checkpoints,'argv':args,'elapsed_s':time.perf_counter()-started,'child_peak_rss_mib':peak_rss_kib/1024})
    return StageResult('cancelled' if cancelled else 'completed',tuple(c['path'] for c in checkpoints),0,{'metrics':metrics,'checkpoints':checkpoints,'official_exit_code':code})
