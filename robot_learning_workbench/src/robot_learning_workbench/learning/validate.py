"""Independent saved Policy inference on validation data; never called by Trainer."""
from pathlib import Path
import time,resource
import numpy as np
from ..data.native import load_catalog,DatasetIdentity,atomic_json,DataError,read_json
from ..data.lerobot import control_contract
from .policy import load_policy,infer,predict


def evaluate(plan,*,events,commands):
    from ..recipe import verify_prepared_inputs,_plain
    from ..run import StageResult
    verify_prepared_inputs(plan);dataset=load_catalog(plan.resolved_inputs['dataset']['path']);contract=control_contract(dataset)
    policy,pre,post,record=load_policy(plan.resolved_inputs['policy']['path'])
    declared=_plain(plan.input_documents.get('policy_contract'));owned=record.get('control_contract')
    if owned is not None:
        if contract!=owned or declared is not None and declared!=owned:raise DataError('POLICY_INCOMPATIBLE','dataset','Scene/model/control/feature semantics differ')
    elif declared!=contract:
        raise DataError('POLICY_INCOMPATIBLE','policy_contract','External robot Policy needs an explicit contract matching the Dataset; dimensions do not establish action meaning')
    contract_source='checkpoint' if owned is not None else 'explicit_policy_contract' if declared is not None else 'features_only'
    def ids(catalog):return {e.metadata['official_episode_metadata'].get('workbench/source_episode_uid') for e in catalog.episodes}
    overlap=None
    if record.get('dataset_path'):
        training=load_catalog(record['dataset_path'],expected=DatasetIdentity(**record['dataset_identity']))
        if dataset.identity==training.identity:raise DataError('DATA_LEAKAGE','validation','Training Dataset is not independent validation')
        if None not in ids(dataset) and None not in ids(training):
            overlap=len(ids(dataset)&ids(training))
            if overlap:raise DataError('DATA_LEAKAGE','validation','Original train/validation Episodes overlap')
        elif contract is not None:raise DataError('DATA_LEAKAGE','validation','Known Workbench lineage missing')
    from lerobot.datasets.utils import dataset_to_policy_features
    metadata=read_json(dataset.root/'meta/info.json');features=dataset_to_policy_features(metadata['features'])
    expected={**policy.config.input_features,**policy.config.output_features}
    if not policy.config.input_features or set(policy.config.output_features)!={'action'} or any(k not in features or features[k].type!=v.type or tuple(features[k].shape)!=tuple(v.shape) for k,v in expected.items()):raise DataError('POLICY_INCOMPATIBLE','features','Official Policy and Dataset features/types/shapes differ')
    if contract is not None:
        if any(metadata['features'].get(k,{}).get('names')!=contract['joint_order'] for k in ('observation.state','action')) or any(getattr(policy.config,k,False) for k in ('adapt_to_pi_aloha','use_delta_joint_actions_aloha')):raise DataError('POLICY_INCOMPATIBLE','features','State/action joint order or absolute model-radian meaning differs')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from torch.utils.data import DataLoader
    # select_action owns observation history and action queues. Training delta
    # timestamps would supply a second history axis to Diffusion/VQBeT here.
    d=LeRobotDataset(repo_id='workbench/native',root=dataset.root,video_backend='pyav')
    # Single-step queued inference: clear chunk on each Episode boundary.
    opts=plan.effective_settings['execution'];batch_size=opts.get('batch_size',1)
    if batch_size!=1:raise ValueError('Sequential Policy action queue validation requires batch_size=1')
    loader=DataLoader(d,batch_size=1,shuffle=False,num_workers=0);errors=[];latencies=[];last=None;cancelled=False
    for index,batch in enumerate(loader):
        if index>=opts.get('max_batches',len(d)):break
        for command in commands():
            if command['kind']=='cancel':cancelled=True;events({'kind':'command_ack','payload':{'command_id':command['command_id'],'status':'completed'}})
        if cancelled:break
        episode=int(batch['episode_index'][0])
        if episode!=last:policy.reset();last=episode
        started=time.perf_counter();action=infer(policy,pre,post,batch,contract=contract) if contract is not None else predict(policy,pre,post,batch)
        latencies.append(time.perf_counter()-started);target=batch['action'].numpy()
        if not np.isfinite(target).all():raise DataError('DATA_INVALID','action','Nonfinite validation target')
        if action.shape!=target.shape:raise DataError('POLICY_INCOMPATIBLE','action','Policy and Dataset target shape differ')
        errors.append(action-target)
        events({'kind':'status','payload':{'progress':{'batches':index+1}}})
    if not errors and not cancelled:raise DataError('VALIDATION_EMPTY','validation','No real inference batches')
    metrics={'batches':len(errors),'mae_rad':np.abs(errors).mean(axis=(0,1)).tolist() if errors else None,'rmse_rad':np.sqrt(np.square(errors).mean(axis=(0,1))).tolist() if errors else None,'latency_mean_s':float(np.mean(latencies)) if latencies else None,'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'control_contract':contract,'physical_success':'unmeasured','checkpoint_step':record['step'],'train_val_episode_overlap':overlap,'lineage_status':'verified' if overlap==0 else 'unverified_external_provenance','units':'rad' if contract else 'unspecified_dataset_units','contract_source':contract_source,'robot_control_approved':False}
    if contract is None:
        metrics['mae']=metrics.pop('mae_rad');metrics['rmse']=metrics.pop('rmse_rad')
    plan.output_path.mkdir();atomic_json(plan.output_path/'validation.json',metrics)
    return StageResult('cancelled' if cancelled else 'completed',(str(plan.output_path/'validation.json'),),0,metrics)
