"""L03 policy/control meaning and exact Native materialization boundaries."""
import copy,json
from pathlib import Path
import numpy as np
import pytest
from robot_learning_workbench.data import native as n,lerobot as l,curation as c
ROOT=Path(__file__).resolve().parents[2]


def source(tmp_path,name='source',engine='mujoco',dtype='float64'):
    import torch
    # Declared synthetic numerical fixture, not a physical robot/simulation trial.
    meta=json.loads((ROOT/'docs/evidence/l03-lerobot/input-contracts.json').read_text())[engine]['execution']
    with n.NativeRun(tmp_path/name,copy.deepcopy(meta)) as run:
        seg=run.segment('batch')
        for i in range(2):
            e=n.native_api()[0]();q=np.arange(18,dtype=dtype).reshape(3,6)/100+i
            e.data={'actions':torch.zeros((3,7),dtype=torch.float64),'obs':{'policy':{'joint_pos':torch.from_numpy(q)},'timestamp':torch.arange(3,dtype=torch.float64).reshape(-1,1)/30},'joint_targets':torch.from_numpy(q.astype('float64')+.25),'states':{'joint_pos':torch.from_numpy(q+10)},'ik':{'applied_joint_rad':torch.from_numpy(q+.5)}}
            e.success=True;seg.write_episode(e,episode_id='ep'+str(i))
        seg.commit()
    return n.load_catalog(run.root)


def test_control_contract_is_measured_pre_state_and_recorded_absolute_model_rad(tmp_path):
    src=source(tmp_path)
    contract=l.control_contract(src)
    assert contract['joint_order']==src.execution['recording']['joint_order']
    assert contract['observation']['source']=='obs/policy/joint_pos'
    assert contract['observation']['phase']=='pre_step'
    assert contract['action']['source']=='joint_targets'
    assert contract['action']['meaning']=='absolute_model_joint_position_target'
    assert contract['action']['units']==['rad']*6
    assert contract['policy_tensor_dtype']=='float32'


@pytest.mark.parametrize('wrong',['ik/applied_joint_rad','states/joint_pos','actions'])
def test_diagnostic_or_post_step_action_never_silently_replaces_target(tmp_path,wrong):
    src=source(tmp_path)
    with pytest.raises(n.DataError):l.materialize(src,tmp_path/'out',feature_map={'observation.state':'obs/policy/joint_pos','action':wrong})
    assert not (tmp_path/'out.staging').exists()


def test_named_features_and_projection_keep_raw_precision_and_exclude_diagnostics(tmp_path):
    src=source(tmp_path);out=l.materialize(src,tmp_path/'out',task='pick red cube')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    d=LeRobotDataset('workbench/native',root=out,video_backend='pyav');raw=d.hf_dataset.with_format(None)[:]
    np.testing.assert_array_equal(np.asarray(raw['action']),n.read_array(src.episodes[0],'joint_targets').tolist()+n.read_array(src.episodes[1],'joint_targets').tolist())
    assert d.features['action']['dtype']=='float64'
    assert d.features['action']['names']==src.execution['recording']['joint_order']
    assert set(k for k in d.features if k.startswith(('ik','states'))) == set()
    assert json.loads((out/'workbench.json').read_text())['control_contract']['action']['source']=='joint_targets'


def test_cross_engine_merge_promotes_storage_without_changing_policy_units(tmp_path):
    a=source(tmp_path,'mj','mujoco');b=source(tmp_path,'isaac','isaac','float32')
    out=l.merge([a,b],tmp_path/'merged',task='pick red cube')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    d=LeRobotDataset('workbench/native',root=out,video_backend='pyav');raw=d.hf_dataset.with_format(None)[:]
    assert len(d)==12 and d.num_episodes==4 and d.features['observation.state']['dtype']=='float64'
    expected=np.concatenate([n.read_array(ep,'obs/policy/joint_pos') for cat in (a,b) for ep in cat.episodes])
    np.testing.assert_array_equal(np.asarray(raw['observation.state']),expected)
    assert len(set(e.episode_id for e in n.load_catalog(out).episodes))==4
    assert len(set(raw['source.dataset_id']))==2 and len(set(raw['source.episode_uid']))==4


def test_merge_rejects_unproven_control_spaces_and_duplicate_samples_before_creation(tmp_path):
    from dataclasses import replace
    a=source(tmp_path)
    altered=copy.deepcopy(a.execution);altered['recording']['units']='degree'
    with pytest.raises(n.DataError):l.merge([a,replace(a,execution=altered)],tmp_path/'bad')
    with pytest.raises(n.DataError):l.merge([a,a],tmp_path/'duplicate')
    assert not (tmp_path/'bad.staging').exists() and not (tmp_path/'duplicate.staging').exists()


def test_merge_detects_episode_leakage_between_independently_saved_views(tmp_path):
    a=source(tmp_path)
    train=c.save_curation(tmp_path/'train.json',a,order=['ep0'],frame_ranges={'ep0':(0,2)},splits={'train':['ep0']})
    val=c.save_curation(tmp_path/'val.json',a,order=['ep0'],frame_ranges={'ep0':(1,3)},splits={'val':['ep0']})
    with pytest.raises(n.DataError):l.merge([train,val],tmp_path/'leaked')
    assert not (tmp_path/'leaked.staging').exists()


def test_policy_dataset_requires_language_instruction_not_code_hash_as_task(tmp_path):
    src=source(tmp_path)
    with pytest.raises(n.DataError):l.materialize(src,tmp_path/'unlabelled')
    assert not (tmp_path/'unlabelled.staging').exists()


def test_official_merge_and_rematerialized_split_keep_original_ids(tmp_path):
    a=source(tmp_path,'mj','mujoco');b=source(tmp_path,'isaac','isaac','float32')
    views=[c.save_curation(tmp_path/(name+'.json'),cat,frame_ranges={'ep0':(1,3)},splits={'train':['ep0'],'val':['ep1']}) for name,cat in [('mj',a),('isaac',b)]]
    merged=l.merge(views,tmp_path/'all',task='pick red cube')
    cat=n.load_catalog(merged)
    assert sorted(map(len,cat.splits.values()))==[2,2]
    train=l.materialize(cat,tmp_path/'train',split='train')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    d=LeRobotDataset('workbench/native',root=train,video_backend='pyav');raw=d.hf_dataset.with_format(None)[:]
    assert len(d)==4 and raw['source.frame_index']==[1,2,1,2]
    assert set(raw['source.episode_id'])=={'ep0'}
    # No dtype/units special case for official inputs.
    left=l.materialize(a,tmp_path/'left',task='pick red cube');right=l.materialize(b,tmp_path/'right',task='pick red cube')
    out=l.merge([left,right],tmp_path/'official-merge')
    assert len(n.load_catalog(out).episodes)==4


def test_same_engine_independent_datasets_are_supported_and_saved_contract_cannot_change_phase(tmp_path):
    a=source(tmp_path,'a');b=source(tmp_path,'b')
    out=l.merge([a,b],tmp_path/'same-engine',task='pick red cube')
    assert len(n.load_catalog(out).episodes)==4
    doc=json.loads((out/'workbench.json').read_text());doc['control_contract']['observation']['phase']='post_step';(out/'workbench.json').write_text(json.dumps(doc))
    with pytest.raises(n.DataError):l.materialize(out,tmp_path/'mislabelled',task='pick red cube')
    assert not (tmp_path/'mislabelled.staging').exists()


def test_curation_of_merged_official_dataset_preserves_verified_control_contract(tmp_path):
    a=source(tmp_path,'a');b=source(tmp_path,'b','isaac','float32')
    out=l.merge([a,b],tmp_path/'merged',task='pick red cube');cat=n.load_catalog(out)
    view=c.save_curation(tmp_path/'selected.json',cat,order=[cat.episodes[0].episode_id])
    selected=l.materialize(view,tmp_path/'selected')
    assert n.load_catalog(selected).metadata['control_contract']==cat.metadata['control_contract']


def test_merge_checks_second_official_joint_order_before_relabelling(tmp_path):
    left=l.materialize(source(tmp_path,'a'),tmp_path/'left',task='pick red cube')
    right=l.materialize(source(tmp_path,'b','isaac','float32'),tmp_path/'right',task='pick red cube')
    p=right/'meta/info.json';doc=json.loads(p.read_text());doc['features']['action']['names'].reverse();p.write_text(json.dumps(doc))
    with pytest.raises(n.DataError):l.merge([left,right],tmp_path/'wrong-order')
    assert not (tmp_path/'wrong-order.staging').exists()


@pytest.mark.parametrize('key,value',[('pose_frame','world'),('control_hz',60),('cameras',{'side':{'shape':[480,640,3],'fps':30,'color':'rgb'}})])
def test_saved_contract_must_match_frame_clock_and_official_camera_metadata(tmp_path,key,value):
    out=l.materialize(source(tmp_path),tmp_path/'original',task='pick red cube')
    p=out/'workbench.json';doc=json.loads(p.read_text());doc['control_contract'][key]=value;p.write_text(json.dumps(doc))
    with pytest.raises(n.DataError):l.materialize(out,tmp_path/'wrong',task='pick red cube')
    assert not (tmp_path/'wrong.staging').exists()


def test_unknown_curated_archive_origin_is_not_automatically_merged(tmp_path):
    src=source(tmp_path)
    view=c.save_curation(tmp_path/'v.json',src,order=['ep0'])
    archive=c.export_native(view,tmp_path/'archive')
    with pytest.raises(n.DataError):l.merge([src,archive],tmp_path/'duplicate-archive',task='pick red cube')
    assert not (tmp_path/'duplicate-archive.staging').exists()


def test_original_nan_timestamp_never_publishes(tmp_path):
    import h5py
    src=source(tmp_path)
    with h5py.File(src.episodes[0].file,'r+') as f:f['data/'+src.episodes[0].key+'/obs/timestamp'][1]=np.nan
    with pytest.raises(n.DataError):l.materialize(src,tmp_path/'bad-time',task='pick red cube')
    assert not (tmp_path/'bad-time').exists()


def test_copied_resume_cannot_bypass_episode_duplicate_checks_via_official_conversion(tmp_path):
    src=source(tmp_path,'fixture');reader=n.open_native(src.episodes[0])
    try:data=reader.load_episode(src.episodes[0].key,'cpu')
    finally:reader.close()
    with n.NativeRun(tmp_path/'original',src.execution) as owner:
        seg=owner.segment('one');claim=owner.claim_attempt(seg);seg.write_episode(data,episode_id='e0');seg.record_attempt(claim,status='success',episode_id='e0');seg.commit()
    with n.resume_to(owner.root,tmp_path/'copy',src.execution,independent=True):pass
    with pytest.raises(n.DataError):l.merge([owner.root,tmp_path/'copy'],tmp_path/'raw-duplicate',task='pick red cube')
    first=l.materialize(owner.root,tmp_path/'official-original',task='pick red cube');second=l.materialize(tmp_path/'copy',tmp_path/'official-copy',task='pick red cube')
    with pytest.raises(n.DataError):l.merge([first,second],tmp_path/'official-duplicate')


def test_known_workbench_recording_with_reversed_order_cannot_become_generic_projection(tmp_path):
    from dataclasses import replace
    src=source(tmp_path);bad=copy.deepcopy(src.execution);bad['recording']['joint_order'].reverse()
    with pytest.raises(n.DataError):l.materialize(replace(src,execution=bad),tmp_path/'bad-order',task='pick red cube')
    assert not (tmp_path/'bad-order.staging').exists()
