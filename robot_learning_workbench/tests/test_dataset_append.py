from pathlib import Path
import pytest
from robot_learning_workbench.data.native import NativeRun,native_api,load_catalog,history,DataError,read_json


def execution():
    return dict(stage='source',engine='mujoco',scene_identity={'revision':'r'},model_sha256='model',calibration={},task_code={},seed=7,recording={'joint_order':['q'],'position_target_policy':'saturation_inward_v1'},active_objects=['cube'],partition='unpartitioned',rng_policy='source_base_seed_plus_attempt_minus_one',episodes=2)


def add(owner):
    import torch
    number=max((r['attempt'] for r in history(owner.root)),default=0)+1
    segment=owner.segment('source-'+str(number));claim=owner.claim_attempt(segment);ep=native_api()[0]();ep.data={'actions':torch.zeros((2,7))};ep.success=True
    segment.write_episode(ep,episode_id='source-'+str(number));segment.record_attempt(claim,status='success',episode_id='source-'+str(number));segment.commit()


def test_same_path_append_keeps_old_official_bytes_and_unique_ids(tmp_path):
    path=tmp_path/'data';cfg=execution()
    with NativeRun(path,cfg) as run:add(run);add(run)
    before=load_catalog(path);original={ep.file:ep.file.read_bytes() for ep in before.episodes};dataset_id=before.identity.dataset_id
    with NativeRun(path,{**cfg,'episodes':4},append=True) as run:add(run);add(run)
    after=load_catalog(path);assert after.identity.dataset_id==dataset_id
    assert [e.episode_id for e in after.episodes]==['source-1','source-2','source-3','source-4']
    assert all(p.read_bytes()==data for p,data in original.items()) and len(history(path))==4


def test_append_mismatch_and_concurrent_owner_cannot_modify_dataset(tmp_path):
    path=tmp_path/'data';cfg=execution()
    with NativeRun(path,cfg) as owner:
        add(owner)
        with pytest.raises(DataError):NativeRun(path,cfg,append=True)
    raw=(path/'run.json').read_bytes()
    for field in ['scene_identity','model_sha256','recording','stage']:
        with pytest.raises(DataError):NativeRun(path,{**cfg,field:'different'},append=True)
        assert (path/'run.json').read_bytes()==raw
    with pytest.raises(DataError):NativeRun(path,cfg)


def test_explicit_append_marks_dead_incomplete_attempt_unknown_never_promotes(tmp_path):
    path=tmp_path/'data';cfg=execution()
    with NativeRun(path,cfg) as run:
        add(run);segment=run.segment('source-2');run.claim_attempt(segment)
    with NativeRun(path,cfg,append=True) as run:add(run)
    assert [e.episode_id for e in load_catalog(path).episodes]==['source-1','source-3']
    assert [r['status'] for r in history(path)]==['success','interrupted_unknown','success']
    assert not (path/'segments/00000001-source-2').exists()


def test_recipe_uses_additional_count_and_existing_output_only_with_explicit_resume(tmp_path):
    import yaml
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    root=Path(__file__).resolve().parents[2]
    spec=yaml.safe_load((root/'docs/evidence/simulation-workflows/mujoco-worker-final.yaml').read_text());spec['execution'].pop('target_successes');spec['execution'].update(num_episodes=2,resume=False,env_num=1);spec['output']['directory']=str(tmp_path/'data')
    path=tmp_path/'r.yaml';path.write_text(yaml.safe_dump(spec));registry=load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement'))
    plan=prepare_recipe(read_recipe(path),tasks=registry);assert plan.effective_settings['execution']['num_episodes']==2
    cfg=execution();cfg['stage']='source'
    with NativeRun(tmp_path/'data',cfg) as owner:add(owner)
    with pytest.raises(ValueError):prepare_recipe(read_recipe(path),tasks=registry)
    # Wrong stage still rejected as early as preparation, before engine or append.
    spec['execution']['resume']=True;path.write_text(yaml.safe_dump(spec))
    with pytest.raises(ValueError):prepare_recipe(read_recipe(path),tasks=registry)


def test_additional_success_goal_and_attempt_budget_are_separate(tmp_path):
    from robot_learning_workbench.data.native import collection_settings
    cfg=execution();path=tmp_path/'data'
    with NativeRun(path,cfg) as run:
        add(run);add(run)
        s=run.segment('source-3');c=run.claim_attempt(s);s.record_attempt(c,status='failure');s.commit()
    settings=collection_settings({'num_episodes':2,'resume':True,'max_attempts':5},path,stage='datagen')
    assert settings['target_successes']==4 and settings['max_attempts']==8
    assert settings['previous_episodes']==2 and settings['requested_additions']==2


def test_append_records_new_producer_code_without_relabeling_old_closed_segments(tmp_path):
    cfg={**execution(),'workflow_code':{'source.py':'version-one'}};path=tmp_path/'data'
    with NativeRun(path,cfg) as owner:add(owner)
    old=load_catalog(path).episodes[0];header=old.file.parent/'segment.json.gz';raw=header.read_bytes()
    with NativeRun(path,{**cfg,'workflow_code':{'source.py':'version-two'},'episodes':2},append=True) as owner:add(owner)
    assert header.read_bytes()==raw and len(load_catalog(path).episodes)==2
    record=read_json(path/'run.json')
    assert record['execution']['workflow_code']['source.py']=='version-two'
    assert record['execution_history'][0]['workflow_code']['source.py']=='version-one'
    with pytest.raises(DataError):NativeRun(path,{**cfg,'task_code':{'task':'different'}},append=True)


def test_recorded_source_can_use_its_original_initial_without_placement_override(tmp_path):
    import yaml
    from robot_learning_workbench.recipe import read_recipe
    spec={'schema_version':1,'stage':'source','engine':'mujoco','inputs':{'scene':'scene.json','source_dataset':'original'},'execution':{'num_episodes':2,'seed':7},'output':{'directory':'new'}}
    path=tmp_path/'r.yaml';path.write_text(yaml.safe_dump(spec));assert not read_recipe(path).spec.objects
    spec['inputs'].pop('source_dataset');spec['inputs']['device_profile']='leader.json';path.write_text(yaml.safe_dump(spec))
    with pytest.raises(ValueError):read_recipe(path)


def test_append_does_not_ignore_changed_control_kinematics_or_state_code(tmp_path):
    cfg={**execution(),'workflow_code':{'source.py':'one','robot/control.py':'safe','state.py':'state'}};path=tmp_path/'data'
    with NativeRun(path,cfg) as owner:add(owner)
    for changed in ({'source.py':'two','robot/control.py':'unsafe','state.py':'state'},{'source.py':'two','robot/control.py':'safe','state.py':'other'}):
        with pytest.raises(DataError):NativeRun(path,{**cfg,'workflow_code':changed},append=True)


def test_new_output_resume_preserves_validated_mixed_producer_history(tmp_path):
    from robot_learning_workbench.data.native import resume_to
    cfg={**execution(),'workflow_code':{'source.py':'one'}};path=tmp_path/'data'
    with NativeRun(path,cfg) as owner:add(owner)
    cfg={**cfg,'workflow_code':{'source.py':'two'}}
    with NativeRun(path,cfg,append=True) as owner:add(owner)
    headers={e.episode_id:(e.file.parent/'segment.json.gz').read_bytes() for e in load_catalog(path).episodes}
    with resume_to(path,tmp_path/'clone',{**cfg,'episodes':3}) as owner:
        assert len(load_catalog(owner.root).episodes)==2
        add(owner)
    after=load_catalog(tmp_path/'clone');assert len(after.episodes)==3
    for e in after.episodes[:2]:assert (e.file.parent/'segment.json.gz').read_bytes()==headers[e.episode_id]
