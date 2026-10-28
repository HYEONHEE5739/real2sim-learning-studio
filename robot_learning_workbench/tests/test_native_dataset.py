"""Official Native data files and minimal publish lifecycle, no engine/device."""
import copy,json,os
from pathlib import Path
import numpy as np
import pytest
from robot_learning_workbench.data import native as n

def episode(frames=3):
    from isaaclab.utils.datasets import EpisodeData
    import torch
    e=EpisodeData();e.data={'actions':torch.arange(frames*7,dtype=torch.float64).reshape(frames,7),'joint_targets':torch.ones((frames,6),dtype=torch.float64),'obs':{'policy':{'joint_pos':torch.zeros((frames,6),dtype=torch.float64)},'timestamp':torch.arange(frames,dtype=torch.float64).reshape(-1,1)/30}}
    e.seed=1047;e.success=True;return e

def execution(stage='datagen'):
    return {'stage':stage,'seed':1047,'scene_identity':{'scene_id':'scene','revision':'v8','manifest_sha256':'a'*64},'calibration':'cal1','task_code':'b'*64,'ik':{'solver':'pinocchio_dls','policy':'best_effort','code_sha256':'c'*64,'model_sha256':'d'*64,'frame':'robot_base/tool0','joint_order':['a','b','c','d','e'],'parameters':{'damping':.001},'safety':{'max_arm_command_jump_rad':.5},'seed_reference':'measured_model_q'},'max_attempts':10,'target_successes':3,'engine':'mujoco','recording':{'phase':'pre_step','joint_order':['a','b','c','d','e','gripper'],'units':'model_rad'},'model_sha256':'d'*64,'active_objects':['cube_red'],'partition':'unpartitioned','rng_policy':'attempt_seed_v1','annotated_input':{'sha256':'e'*64},'source_pool_order':['demo_0']}

def test_official_segment_multi_episode_pending_then_atomic_publish(tmp_path):
    run=n.NativeRun(tmp_path/'data',execution())
    segment=run.segment('batch-1',request={'input':'one'})
    a=segment.write_episode(episode(),episode_id='one',metadata={'phase':'pre_step','lineage':['source1']})
    segment.write_episode(episode(4),episode_id='two')
    assert not n.load_catalog(run.root).episodes
    published=segment.commit();assert len(published.episodes)==2
    run.close();catalog=n.load_catalog(run.root)
    assert catalog.kind=='native' and [e.episode_id for e in catalog.episodes]==['one','two']
    assert catalog.episodes[0].num_frames==3 and catalog.episodes[0].metadata['phase']=='pre_step'
    reader=n.open_native(catalog.episodes[0]);loaded=reader.load_episode(a,'cpu');reader.close()
    assert loaded.data['actions'].numpy().dtype==np.float64
    assert len(list(run.root.rglob('*.hdf5')))==1
    assert not list(run.root.rglob('*descriptor*')) and not (run.root/'dataset.json').exists()


def test_same_intent_is_idempotent_but_unknown_intent_not_restarted(tmp_path):
    run=n.NativeRun(tmp_path/'data',execution());seg=run.segment('batch',request={'x':1});seg.write_episode(episode(),episode_id='a');seg.commit()
    assert run.segment('batch',request={'x':1}).published
    with pytest.raises(n.DataError):run.segment('batch',request={'x':2})
    pending=run.segment('unknown',request={})
    with pytest.raises(n.DataError):run.segment('unknown',request={})
    pending.abort();run.close()


def test_partial_official_write_cannot_publish_or_hide_prior_commits(tmp_path,monkeypatch):
    run=n.NativeRun(tmp_path/'data',execution());first=run.segment('first');first.write_episode(episode(),episode_id='one');first.commit()
    before=(run.root/'segments/00000000-first/data.hdf5').read_bytes()
    segment=run.segment('broken');original=__import__('h5py').Group.create_dataset
    def fail(group,name,*args,**kw):
        if group.name.endswith('/obs'):raise OSError('disk full')
        return original(group,name,*args,**kw)
    with monkeypatch.context() as patch:
        patch.setattr(__import__('h5py').Group,'create_dataset',fail)
        with pytest.raises(OSError):segment.write_episode(episode(),episode_id='bad')
    with pytest.raises(n.DataError):segment.commit()
    run.close();assert [e.episode_id for e in n.load_catalog(run.root).episodes]==['one']
    assert (run.root/'segments/00000000-first/data.hdf5').read_bytes()==before


def test_attempt_seed_budget_and_resume_share_closed_native_files(tmp_path):
    run=n.NativeRun(tmp_path/'original',execution());seg=run.segment('batch')
    claim=run.claim_attempt(seg);assert claim['attempt']==1 and claim['seed']==892243098
    seg.write_episode(episode(),episode_id='saved');seg.record_attempt(claim,status='success',episode_id='saved');seg.commit();run.close()
    requested={**execution(),'max_attempts':12,'target_successes':4}
    resumed=n.resume_to(run.root,tmp_path/'resumed',requested)
    assert len(n.load_catalog(resumed.root).episodes)==1
    seg=resumed.segment('next');claim=resumed.claim_attempt(seg);assert claim['attempt']==2
    assert claim['seed']==int(np.random.SeedSequence([1047,2]).generate_state(1)[0])
    seg.record_attempt(claim,status='ik_failure');seg.commit();resumed.close()
    a=n.load_catalog(run.root).episodes[0].file;b=n.load_catalog(tmp_path/'resumed').episodes[0].file
    assert a.stat().st_ino==b.stat().st_ino
    for key,value in [('seed',2),('calibration','other'),('task_code','other'),('ik',{'solver':'scipy_ls','policy':'strict'})]:
        with pytest.raises(n.DataError):n.resume_to(run.root,tmp_path/('bad-'+key),{**requested,key:value})


def test_interrupted_attempt_requires_explicit_recovery_and_never_repeats_seed(tmp_path):
    run=n.NativeRun(tmp_path/'data',execution());seg=run.segment('pending');claim=run.claim_attempt(seg);run.close()
    with pytest.raises(n.DataError):n.resume_to(run.root,tmp_path/'blocked',execution())
    assert not (tmp_path/'blocked').exists()
    report=n.recover(run.root,acknowledge_interrupted=True)
    assert report['interrupted_attempts']==[1]
    resumed=n.resume_to(run.root,tmp_path/'next',execution());seg=resumed.segment('new');new=resumed.claim_attempt(seg)
    assert new['attempt']==2 and new['seed']!=claim['seed'];resumed.close()


def test_dataset_order_is_numeric_record_order_and_mimic_pool_order_is_explicit(tmp_path):
    with n.NativeRun(tmp_path/'data',execution()) as run:
        seg=run.segment('many')
        for i in range(12):seg.write_episode(episode(),episode_id=f'ep{i}')
        seg.commit()
    catalog=n.load_catalog(run.root)
    assert [e.episode_id for e in catalog.episodes]==[f'ep{i}' for i in range(12)]
    assert [e.episode_id for e in n.mimic_episodes(catalog)]==['ep0','ep1','ep10','ep11','ep2','ep3','ep4','ep5','ep6','ep7','ep8','ep9']

@pytest.mark.parametrize('name',['source_mujoco','source_isaac','annotation_mujoco','annotation_isaac','datagen_mujoco','evaluation_mujoco','evaluation_isaac','historical_source','historical_annotation','historical_datagen','manual_annotation'])
def test_original_hdf5_import_keeps_arrays_and_non_tensor_diagnostics(tmp_path,name):
    import h5py,base64
    samples=json.loads((Path(__file__).resolve().parents[2]/'docs/evidence/b02/samples.json').read_text());path=Path(samples[name]['path'])
    catalog=n.import_hdf5(path,tmp_path/'native',stage='datagen' if 'datagen' in name else 'annotation' if 'annotation' in name else 'source',groups=['demo_0'])
    ep=catalog.episodes[0]
    with h5py.File(path,'r') as f:
        def check(key,node):
            if not isinstance(node,h5py.Dataset):return
            original=node[()]
            if original.dtype.kind in 'biufc':
                actual=n.read_array(ep,key,frames=False);assert actual.dtype==original.dtype and actual.shape==original.shape and actual.tobytes()==original.tobytes()
            else:
                saved=ep.metadata['non_tensor_arrays'][key]
                assert saved['dtype']==original.dtype.str and saved['shape']==list(original.shape) and base64.b64decode(saved['base64'])==original.tobytes()
        f['data/demo_0'].visititems(check)
    for camera,info in ep.media.items():
        original=path.parent/json.loads(__import__('h5py').File(path,'r')['data/demo_0'].attrs['external_videos'])[camera]['file']
        assert n.file_sha256(info['path'])==n.file_sha256(original)
    with pytest.raises(n.DataError):n.resume_to(catalog.root,tmp_path/'invalid-resume',catalog.execution)


def test_normal_commit_never_hashes_arrays_or_decodes_video(tmp_path,monkeypatch):
    with n.NativeRun(tmp_path/'run',execution()) as run:
        seg=run.segment('fast')
        def expensive(*args,**kwargs):raise AssertionError('normal path must not hash payload')
        monkeypatch.setattr(n,'file_sha256',expensive)
        seg.write_episode(episode(),episode_id='e');seg.commit()
    assert len(n.load_catalog(run.root).episodes)==1


def test_known_series_length_mismatch_blocks_publish(tmp_path):
    with n.NativeRun(tmp_path/'run',execution()) as run:
        seg=run.segment('broken');ep=episode();ep.data['obs']['policy']['joint_pos']=ep.data['obs']['policy']['joint_pos'][:1]
        with pytest.raises(n.DataError):seg.write_episode(ep)
        with pytest.raises(n.DataError):seg.commit()
    assert not n.load_catalog(run.root).episodes

CANONICAL=json.loads((Path(__file__).resolve().parents[2]/'docs/evidence/b02/legacy-rng.json').read_text())['legacy_folders']
@pytest.mark.parametrize('row',CANONICAL,ids=[str(i) for i in range(len(CANONICAL))])
def test_original_canonical_arrays_are_explicitly_imported_not_legacy_reader_fallback(tmp_path,row):
    source=Path(row['path']);catalog=n.import_canonical(source,tmp_path/'native',stage='source',episode_ids=[row['first_episode']]);ep=catalog.episodes[0]
    entry=next(v for v in json.loads((source/'manifest.json').read_text())['episodes'] if v['id']==row['first_episode'])
    for filename in row['fields']:
        original=np.load(source/entry['path']/filename,allow_pickle=False)
        value=n.read_array(ep,ep.metadata['array_paths'][filename],frames=False)
        assert original.dtype==value.dtype and original.shape==value.shape and original.tobytes()==value.tobytes()
    assert ep.metadata['replay_resume_available'] is False


def test_duplicate_episode_identity_and_inconsistent_attempt_history_cannot_poison_run(tmp_path):
    run=n.NativeRun(tmp_path/'run',execution());a=run.segment('one');a.write_episode(episode(),episode_id='same');a.commit()
    b=run.segment('two')
    with pytest.raises(n.DataError):b.write_episode(episode(),episode_id='same')
    run.close()
    assert [e.episode_id for e in n.load_catalog(run.root).episodes]==['same']
    n.recover(run.root,acknowledge_interrupted=True)
    with pytest.raises(n.DataError):n.resume_to(run.root,tmp_path/'bad',execution())  # no recorded attempt history


def test_resume_requires_complete_explicit_ik_binding_and_cumulative_budget(tmp_path):
    cfg=execution();cfg['ik']={'solver':'pinocchio_dls','policy':'best_effort'}
    with n.NativeRun(tmp_path/'run',cfg) as run:
        s=run.segment('one');a=run.claim_attempt(s);s.write_episode(episode(),episode_id='one');s.record_attempt(a,status='success',episode_id='one');s.commit()
    with pytest.raises(n.DataError):n.resume_to(run.root,tmp_path/'bad',cfg)


def test_independent_export_of_full_native_selection_keeps_arrays_and_original_untouched(tmp_path):
    from robot_learning_workbench.data.curation import save_curation,export_native
    with n.NativeRun(tmp_path/'source',execution(),metadata={'original_global_evidence':'recorded seed/history/units'}) as run:
        s=run.segment('one')
        for i in range(4):s.write_episode(episode(),episode_id=f'e{i}')
        s.commit()
    view=save_curation(tmp_path/'view.json',run.root,order=['e3','e1'])
    output=export_native(view,tmp_path/'independent')
    assert [e.episode_id for e in output.episodes]==['e3','e1']
    assert output.metadata['original_global_evidence']=='recorded seed/history/units'
    assert n.read_array(output.episodes[0],'actions').tobytes()==n.read_array(view.episodes[0],'actions').tobytes()
    assert len(n.load_catalog(run.root).episodes)==4
    trimmed=save_curation(tmp_path/'trim.json',view,frame_ranges={'e3':(1,3)})
    with pytest.raises(n.DataError):export_native(trimmed,tmp_path/'invalid')
    assert not (tmp_path/'invalid').exists()  # no fabricated mid-trajectory initial state


def test_owner_close_does_not_change_already_published_data_identity(tmp_path):
    run=n.NativeRun(tmp_path/'run',execution());s=run.segment('one');s.write_episode(episode());s.commit()
    identity=n.load_catalog(run.root).identity;run.close()
    assert n.load_catalog(run.root,expected=identity).identity==identity

@pytest.mark.parametrize('missing',['engine','recording','model_sha256','active_objects','partition','rng_policy','annotated_input','source_pool_order'])
def test_incomplete_runtime_identity_never_claims_exact_resume(tmp_path,missing):
    cfg=execution();cfg.pop(missing)
    with n.NativeRun(tmp_path/'run',cfg) as run:
        s=run.segment('one');a=run.claim_attempt(s);s.write_episode(episode(),episode_id='e');s.record_attempt(a,status='success',episode_id='e');s.commit()
    with pytest.raises(n.DataError):n.resume_to(run.root,tmp_path/'next',cfg)
    assert not (tmp_path/'next').exists()


def test_original_provenance_is_compressed_once_not_duplicated_in_every_native_segment(tmp_path):
    metadata={'source_data_attrs':{'env_args':json.dumps({'env_name':'SO101','legacy_long_evidence':'abc'*100000})}}
    with n.NativeRun(tmp_path/'run',execution(),metadata=metadata) as run:
        for i in range(2):
            s=run.segment(str(i));s.write_episode(episode(),episode_id=str(i));s.commit()
    assert n.load_catalog(run.root).metadata==metadata
    assert (run.root/'run.json').stat().st_size<5000
    assert sum(e.file.stat().st_size for e in n.load_catalog(run.root).episodes)<100000
    h=n.open_native(n.load_catalog(run.root).episodes[0]);assert h.get_env_name()=='SO101';h.close()


def test_source_seed_wrap_and_partition_lock(tmp_path):
    cfg={**execution('source'),'seed':2**32-1}
    with n.NativeRun(tmp_path/'source',cfg) as run:
        s=run.segment('first');a=run.claim_attempt(s);assert a['seed']==2**32-1
        s.write_episode(episode(),episode_id='first');s.record_attempt(a,status='success',episode_id='first');s.commit()
    with n.resume_to(run.root,tmp_path/'next',cfg) as resumed:
        s=resumed.segment('second');assert resumed.claim_attempt(s)['seed']==0
    signed={**cfg,'partition':{'locked':True,'membership':['first']}}
    with n.NativeRun(tmp_path/'signed',signed) as run:
        s=run.segment('first');a=run.claim_attempt(s);s.write_episode(episode(),episode_id='first');s.record_attempt(a,status='success',episode_id='first');s.commit()
    with pytest.raises(n.DataError):n.resume_to(run.root,tmp_path/'wrong',signed)


def test_publish_response_loss_is_resolved_by_same_intent_without_duplicate_write(tmp_path,monkeypatch):
    with n.NativeRun(tmp_path/'run',execution()) as run:
        s=run.segment('same',request={'input':'a'});s.write_episode(episode(),episode_id='one')
        sync=n._sync
        def fail_after_publish(directory):
            if Path(directory)==run.root/'segments':raise OSError('publish succeeded, acknowledgement lost')
            sync(directory)
        with monkeypatch.context() as patch:
            patch.setattr(n,'_sync',fail_after_publish)
            with pytest.raises(OSError):s.commit()
        result=run.segment('same',request={'input':'a'})
        assert result.published and [e.episode_id for e in result.episodes]==['one']
        assert len(n.load_catalog(run.root).episodes)==1


def test_completed_evaluation_failure_is_complete_without_becoming_task_success(tmp_path):
    with n.NativeRun(tmp_path/'evaluation',execution('simulation_evaluation')) as run:
        s=run.segment('evaluation');e=episode();e.success=False;s.write_episode(e,episode_id='failure',metadata={'outcome':'task_failure'});s.commit()
    ep=n.load_catalog(run.root).episodes[0];handler=n.open_native(ep)
    assert not handler.load_episode(ep.key,'cpu').success and ep.metadata['outcome']=='task_failure';handler.close()
    with pytest.raises(n.DataError):n.resume_to(run.root,tmp_path/'wrong',execution('simulation_evaluation'))
