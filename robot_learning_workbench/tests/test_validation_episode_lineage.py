"""Real Native Resume -> official materialization -> offline leakage gate.

Only Policy loading/inference and unrelated PreparedRun pinning are replaced.
Native HDF5, attempts, Resume, Curation and official Parquet are real fixtures.
"""
import copy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from robot_learning_workbench.data import curation,lerobot,native
from robot_learning_workbench.learning import validate


ROOT=Path(__file__).resolve().parents[2]


def _write_native(path,execution):
    import torch
    with native.NativeRun(path,copy.deepcopy(execution))as owner:
        for number in range(2):
            segment=owner.segment('batch-'+str(number));claim=owner.claim_attempt(segment)
            episode=native.native_api()[0]()
            q=torch.arange(18,dtype=torch.float64).reshape(3,6)/100+number
            episode.data={'actions':torch.zeros((3,7),dtype=torch.float64),
                'obs':{'policy':{'joint_pos':q},'timestamp':torch.arange(3,dtype=torch.float64).reshape(-1,1)/30},
                'joint_targets':q+.25}
            episode.success=True;identifier='ep'+str(number)
            segment.write_episode(episode,episode_id=identifier)
            segment.record_attempt(claim,status='success',episode_id=identifier);segment.commit()
    return native.load_catalog(path)


@pytest.fixture(scope='module')
def lineage_data(tmp_path_factory):
    root=tmp_path_factory.mktemp('real-native-lineage')
    execution=json.loads((ROOT/'docs/evidence/l03-lerobot/input-contracts.json').read_text())['mujoco']['execution']
    execution.update(stage='source',partition='unpartitioned',rng_policy='source_base_seed_plus_attempt_minus_one',episodes=2)
    execution['model_sha256']=execution['urdf_sha256']
    original=_write_native(root/'original',execution)
    original_files={path:native.file_sha256(path)for path in original.root.rglob('*')if path.is_file()}
    with native.resume_to(original.root,root/'resume-hardlink',execution):pass
    with native.resume_to(original.root,root/'resume-copy',execution,independent=True):pass
    hardlink=native.load_catalog(root/'resume-hardlink');copied=native.load_catalog(root/'resume-copy')
    independent=_write_native(root/'independent',execution)
    def export(label,catalog,episode='ep0',window=None):
        view=curation.save_curation(root/(label+'.json'),catalog,order=[episode],
            frame_ranges={}if window is None else{episode:window})
        return lerobot.materialize(view,root/label,task='pick red cube')
    rows={'root':root,'original_native':original,'hardlink_native':hardlink,'copy_native':copied,
        'independent_native':independent,'train':export('train',original),
        'hardlink':export('hardlink',hardlink),'copy':export('copy',copied),
        'trim':export('trim',hardlink,window=(1,3)),
        'repeat_export':export('repeat-export',original),
        'independent':export('independent-export',independent),
        'new_episode':export('new-episode',original,episode='ep1')}
    rows['official_rematerialize']=lerobot.materialize(rows['hardlink'],root/'official-again')
    yield rows
    assert original_files=={path:native.file_sha256(path)for path in original.root.rglob('*')if path.is_file()}


def _origin(path):
    row=native.load_catalog(path).episodes[0].metadata['official_episode_metadata']
    return {name:row.get('workbench/source_'+name)for name in
        ('episode_uid','native_alias','dataset_id','parent_dataset_id','original_episode_id','start','stop')}


def _evaluate(monkeypatch,tmp_path,training,validation,*,external=False,checkpoint=None):
    from lerobot.datasets.utils import dataset_to_policy_features
    training=native.load_catalog(training);dataset=native.load_catalog(validation)
    features=dataset_to_policy_features(native.read_json(dataset.root/'meta/info.json')['features'])
    config=SimpleNamespace(input_features={'observation.state':features['observation.state']},
        output_features={'action':features['action']})
    policy=SimpleNamespace(config=config,reset=lambda:None)
    record={'dataset_path':str(training.root),'dataset_identity':vars(training.identity),
        'control_contract':lerobot.control_contract(training),'step':1,'external_official':external}
    if checkpoint is not None:
        from robot_learning_workbench.learning.policy import checkpoint_record
        record=checkpoint_record(checkpoint)
    monkeypatch.setattr(validate,'load_policy',lambda *args:(policy,None,None,record))
    import robot_learning_workbench.recipe as recipe
    monkeypatch.setattr(recipe,'verify_prepared_inputs',lambda plan:None)
    calls=[]
    def inference(policy,pre,post,batch,**kwargs):
        calls.append(int(batch['episode_index'][0]));return np.zeros(tuple(batch['action'].shape))
    monkeypatch.setattr(validate,'infer',inference);monkeypatch.setattr(validate,'predict',inference)
    plan=SimpleNamespace(input_documents={},resolved_inputs={'dataset':{'path':str(dataset.root)},
        'policy':{'path':'inference-is-replaced'}},output_path=tmp_path/'validation',
        effective_settings={'execution':{'max_batches':1,'batch_size':1}})
    return plan,calls


@pytest.mark.parametrize('variant',['hardlink','copy','trim','repeat_export','official_rematerialize'])
def test_inherited_or_reexported_episode_is_rejected_before_inference(tmp_path,monkeypatch,lineage_data,variant):
    training=_origin(lineage_data['train']);validation=_origin(lineage_data[variant])
    assert training['original_episode_id']==validation['original_episode_id']=='ep0'
    original=lineage_data['original_native'].episodes[0]
    resumed=lineage_data['hardlink_native'if variant!='copy'else'copy_native'].episodes[0]
    if variant in('hardlink','trim','official_rematerialize'):
        assert training['episode_uid']!=validation['episode_uid']
        assert training['native_alias']==validation['native_alias']
        assert(original.file.stat().st_dev,original.file.stat().st_ino)==(resumed.file.stat().st_dev,resumed.file.stat().st_ino)
    if variant=='copy':
        assert original.file.stat().st_ino!=resumed.file.stat().st_ino
        assert training['native_alias']!=validation['native_alias']
        assert validation['parent_dataset_id']==lineage_data['original_native'].identity.dataset_id
        np.testing.assert_array_equal(native.read_array(original,'joint_targets'),native.read_array(resumed,'joint_targets'))
    if variant=='trim':assert(validation['start'],validation['stop'])==(1,3)
    plan,calls=_evaluate(monkeypatch,tmp_path,lineage_data['train'],lineage_data[variant])
    with pytest.raises(native.DataError)as error:validate.evaluate(plan,events=lambda _:None,commands=lambda:())
    assert error.value.code=='DATA_LEAKAGE'
    assert not calls and not plan.output_path.exists()


@pytest.mark.parametrize('variant',['independent','new_episode'])
def test_proven_independent_episodes_allow_validation_even_with_equal_names_or_arrays(tmp_path,monkeypatch,lineage_data,variant):
    before=_origin(lineage_data['train']);after=_origin(lineage_data[variant])
    assert before['episode_uid']!=after['episode_uid']and before['native_alias']!=after['native_alias']
    if variant=='independent':
        assert before['original_episode_id']==after['original_episode_id']=='ep0'
        # Payload equality is not lineage: independently recorded fixtures may
        # contain the same numbers and Episode ID without sharing an origin.
        np.testing.assert_array_equal(native.read_array(lineage_data['original_native'].episodes[0],'joint_targets'),
            native.read_array(lineage_data['independent_native'].episodes[0],'joint_targets'))
    plan,calls=_evaluate(monkeypatch,tmp_path,lineage_data['train'],lineage_data[variant])
    result=validate.evaluate(plan,events=lambda _:None,commands=lambda:())
    assert result.status=='completed'and calls==[0]
    report=native.read_json(plan.output_path/'validation.json')
    assert report['lineage_status']=='verified'and report['train_val_episode_overlap']==0
    assert report['robot_control_approved']is False


@pytest.mark.parametrize('external',[False,True])
def test_incomplete_legacy_origin_is_never_certified_independent(tmp_path,monkeypatch,lineage_data,external):
    import pyarrow.parquet as pq
    copied=tmp_path/'legacy';shutil.copytree(lineage_data['independent'],copied)
    for path in(copied/'meta/episodes').glob('*/*.parquet'):
        table=pq.read_table(path)
        table=table.drop([key for key in ('workbench/source_parent_dataset_id','workbench/source_native_alias')if key in table.column_names])
        pq.write_table(table,path)
    plan,calls=_evaluate(monkeypatch,tmp_path,lineage_data['train'],copied,external=external)
    if external:
        try:validate.evaluate(plan,events=lambda _:None,commands=lambda:())
        except native.DataError:
            assert not calls and not plan.output_path.exists()
        else:assert native.read_json(plan.output_path/'validation.json')['lineage_status']!='verified'
    else:
        with pytest.raises(native.DataError):validate.evaluate(plan,events=lambda _:None,commands=lambda:())
        assert not calls and not plan.output_path.exists()


def test_copy_with_same_saved_lineage_is_still_the_original_episode(tmp_path,monkeypatch,lineage_data):
    copied=tmp_path/'copied-native';shutil.copytree(lineage_data['original_native'].root,copied)
    catalog=native.load_catalog(copied)
    original=lineage_data['original_native'].episodes[0]
    assert catalog.identity==lineage_data['original_native'].identity
    assert catalog.episodes[0].file.stat().st_ino!=original.file.stat().st_ino
    view=curation.save_curation(tmp_path/'selection.json',catalog,order=['ep0'])
    exported=lerobot.materialize(view,tmp_path/'copied-export',task='pick red cube')
    assert _origin(exported)['episode_uid']==_origin(lineage_data['train'])['episode_uid']
    plan,calls=_evaluate(monkeypatch,tmp_path,lineage_data['train'],exported)
    with pytest.raises(native.DataError,match='overlap'):validate.evaluate(plan,events=lambda _:None,commands=lambda:())
    assert not calls and not plan.output_path.exists()


def test_mixed_validation_is_rejected_before_even_the_first_independent_batch(tmp_path,monkeypatch,lineage_data):
    view=curation.save_curation(tmp_path/'mixed.json',lineage_data['hardlink_native'],order=['ep1','ep0'])
    exported=lerobot.materialize(view,tmp_path/'mixed-export',task='pick red cube')
    assert len(native.load_catalog(exported).episodes)==2
    plan,calls=_evaluate(monkeypatch,tmp_path,lineage_data['train'],exported)
    with pytest.raises(native.DataError,match='overlap'):validate.evaluate(plan,events=lambda _:None,commands=lambda:())
    assert not calls and not plan.output_path.exists()


def test_new_episode_after_resume_is_independent_in_canonical_run_selections(tmp_path,monkeypatch,lineage_data):
    import torch
    original=lineage_data['original_native'];execution=copy.deepcopy(original.execution)
    execution['episodes']=3
    with native.resume_to(original.root,tmp_path/'canonical-resume',execution)as owner:
        segment=owner.segment('new-after-resume');claim=owner.claim_attempt(segment)
        episode=native.native_api()[0]();q=torch.zeros((3,6),dtype=torch.float64)
        episode.data={'actions':torch.zeros((3,7),dtype=torch.float64),'joint_targets':q+.5,
            'obs':{'policy':{'joint_pos':q},'timestamp':torch.arange(3,dtype=torch.float64).reshape(-1,1)/30}}
        episode.success=True;segment.write_episode(episode,episode_id='new-ep')
        segment.record_attempt(claim,status='success',episode_id='new-ep');segment.commit()
    canonical=native.load_catalog(owner.root)
    assert len(canonical.episodes)==3
    exports=[]
    for name,identifier in [('train','ep0'),('val','new-ep')]:
        view=curation.save_curation(tmp_path/(name+'.json'),canonical,order=[identifier])
        exports.append(lerobot.materialize(view,tmp_path/(name+'-export'),task='pick red cube'))
    assert _origin(exports[0])['dataset_id']==_origin(exports[1])['dataset_id']
    plan,calls=_evaluate(monkeypatch,tmp_path,*exports)
    assert validate.evaluate(plan,events=lambda _:None,commands=lambda:()).status=='completed'
    assert calls==[0]and native.read_json(plan.output_path/'validation.json')['lineage_status']=='verified'


@pytest.mark.parametrize('variant',['hardlink','independent'])
def test_official_sealed_training_record_feeds_real_validation_recipe(tmp_path,monkeypatch,lineage_data,variant):
    import yaml
    import robot_learning_workbench.recipe as recipe
    from test_checkpoint_config_resolution import _ui_config,_official_validate,_tiny_checkpoint
    from robot_learning_workbench.learning.policy import seal_checkpoint
    verify=recipe.verify_prepared_inputs
    requested=_ui_config(lineage_data['train'],tmp_path/'training-output')
    resolved=_official_validate(requested,tmp_path/'request/train_config.json',monkeypatch)
    checkpoint=_tiny_checkpoint(tmp_path/'checkpoint/000001',resolved)
    seal_checkpoint(checkpoint,dataset=lineage_data['train'],config=requested,recipe_sha256='d'*64)
    _,calls=_evaluate(monkeypatch,tmp_path,lineage_data['train'],lineage_data[variant],checkpoint=checkpoint)
    monkeypatch.setattr(recipe,'verify_prepared_inputs',verify)
    path=tmp_path/'validation.yaml'
    path.write_text(yaml.safe_dump({'schema_version':1,'stage':'offline_validation',
        'inputs':{'dataset':str(lineage_data[variant]),'policy':str(checkpoint)},
        'execution':{'batch_size':1,'max_batches':1},'output':{'directory':str(tmp_path/'validation')}}))
    plan=recipe.prepare_recipe(recipe.read_recipe(path))
    if variant=='hardlink':
        with pytest.raises(native.DataError)as error:validate.evaluate(plan,events=lambda _:None,commands=lambda:())
        assert error.value.code=='DATA_LEAKAGE'and not calls and not plan.output_path.exists()
    else:
        assert validate.evaluate(plan,events=lambda _:None,commands=lambda:()).status=='completed'
        assert calls==[0]and native.read_json(plan.output_path/'validation.json')['lineage_status']=='verified'
