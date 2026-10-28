from robot_learning_workbench.ui import operations


def test_ui_never_offers_unimplemented_or_hardware_stages():
    assert operations.stage_support('datagen')['runnable']
    assert operations.stage_support('train')['runnable']
    assert operations.stage_support('source')['runnable']
    assert 'Source' in operations.stage_support('source')['reason']
    assert operations.stage_support('hub_upload')['runnable']
    for name in ('real_evaluation','capture'):
        support=operations.stage_support(name)
        assert not support['runnable'] and support['reason']


def test_worker_end_is_not_target_completion_or_task_success():
    state={'status':'completed','completed_episodes':0,'attempt_summary':{'target_reached':False,'budget_exhausted':False,'fresh_worker_required':True}}
    outcome=operations.run_outcome(state)
    assert outcome['worker_finished'] and outcome['needs_resume'] and outcome['goal_reached'] is False
    assert outcome['task_success'] is None


def test_cancel_ack_cannot_override_running_worker():
    outcome=operations.run_outcome({'status':'running','completed_episodes':0})
    assert not outcome['worker_finished']


def test_missing_dataset_error_does_not_return_fake_catalog(tmp_path):
    import pytest
    with pytest.raises(ValueError):operations.execute({'operation':'catalog','arguments':{'path':str(tmp_path/'missing')}})


def test_ui_curation_calls_existing_functions_directly(tmp_path,monkeypatch):
    from robot_learning_workbench.data import curation
    seen=[];monkeypatch.setattr(curation,'save_curation',lambda **kw:seen.append(kw))
    path=tmp_path/'revision.json'
    result=operations.execute({'operation':'save_curation','arguments':{'path':str(path),'source':'original','exclude':['bad']}})
    assert result['path']==str(path) and seen[0]['exclude']==['bad']


def test_actual_evaluation_failure_counts_are_distinct_from_worker_complete():
    state={'status':'completed','completed_episodes':2,'attempt_summary':{'successes':0,'failures':2,'attempts':2,'success_rate':0.,'latest':{'success':False}}}
    value=operations.run_outcome(state)
    assert value['worker_finished'] and value['successes']==0 and value['failures']==2 and value['task_success'] is False


def test_start_rejects_changed_recipe_before_worker_creation(tmp_path,monkeypatch):
    import pytest
    from types import SimpleNamespace
    from robot_learning_workbench import recipe
    from robot_learning_workbench.data import native
    monkeypatch.setattr(recipe,'read_recipe',lambda p:SimpleNamespace(sha256='changed',base_dir=tmp_path,spec=SimpleNamespace(output={'directory':'out'})))
    monkeypatch.setattr(operations,'prepared',lambda *a:{'runnable':True,'prepared_sha256':'new'})
    monkeypatch.setattr(native,'file_sha256',lambda p:'modulehash')
    with pytest.raises(ValueError,match='변경'):
        operations.execute({'operation':'start','arguments':{'path':'r','modules':'m','request_id':'same','expected_recipe_sha256':'checked','expected_prepared_sha256':'old'}})


def test_worker_death_before_claim_is_detected_from_spawn_identity(tmp_path):
    import json
    from robot_learning_workbench.run import read_status
    (tmp_path/'run.json').write_text(json.dumps({'status':'prepared','phase':'preparing'}))
    (tmp_path/'spawn.json').write_text(json.dumps({'process_spawn_returned':True,'process_identity':{'pid':999999999,'start_ticks':'0','boot_id':'not-live'}}))
    assert read_status(tmp_path).status=='unknown'


def test_unobservable_spawn_without_claim_is_unknown(tmp_path):
    import json
    from robot_learning_workbench.run import read_status
    (tmp_path/'run.json').write_text(json.dumps({'status':'prepared','phase':'preparing'}))
    (tmp_path/'spawn.json').write_text(json.dumps({'identity_unobservable':True}))
    assert read_status(tmp_path).status=='unknown'


def test_training_start_preserves_prepare_without_task_modules(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from robot_learning_workbench import recipe,run
    seen=[];doc=SimpleNamespace(sha256='same',path=tmp_path/'r.yaml',base_dir=tmp_path,spec=SimpleNamespace(stage='train',objects={},functions={},output={'directory':'out'}))
    monkeypatch.setattr(recipe,'read_recipe',lambda p:doc)
    monkeypatch.setattr(operations,'prepared',lambda *a:{'runnable':True,'prepared_sha256':'ready'})
    monkeypatch.setattr(run,'start',lambda req:seen.append(req) or run.RunHandle('r','i',tmp_path/'run'))
    operations.execute({'operation':'start','arguments':{'path':'r','modules':'missing_modules','request_id':'i','expected_recipe_sha256':'same','expected_prepared_sha256':'ready'}})
    assert seen[0].task_modules_path is None and seen[0].expected_modules_sha256 is None


def test_backend_error_serializes_recipe_issues_without_losing_cause(monkeypatch,capsys):
    import io,json
    from robot_learning_workbench.recipe import RecipeError
    monkeypatch.setattr(operations.sys,'stdin',io.StringIO('{"operation":"prepare"}'))
    def fail(_):raise RecipeError('INPUT_CONFLICT','inputs.training_config.resume','differs from saved mode')
    monkeypatch.setattr(operations,'execute',fail)
    assert operations.main()==2
    result=json.loads(capsys.readouterr().out)
    assert result['error']['code']=='INPUT_CONFLICT' and result['error']['issues'][0]['field']=='inputs.training_config.resume'
