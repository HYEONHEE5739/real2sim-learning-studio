"""Actual Native/engine DataGen boundaries; no physical devices."""
from pathlib import Path
import json
import numpy as np
import pytest
ROOT=Path(__file__).resolve().parents[2]


def test_datagen_reset_rng_continues_by_attempt_not_success():
    from robot_learning_workbench.engines.mujoco.datagen import reset_seeds
    from robot_learning_workbench.generation.mimic import attempt_seed
    rng=np.random.default_rng(attempt_seed(1047,0))
    expected=[int(rng.integers(2**32)) for _ in range(5)]
    assert reset_seeds(1047,5)==expected
    assert reset_seeds(1047,3)[-1]==expected[2]


def test_native_annotation_pool_and_fixed_ik_binding():
    from robot_learning_workbench.engines.mujoco.datagen import load_inputs
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    import tempfile,yaml
    settings=json.loads((ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text())
    with tempfile.TemporaryDirectory() as directory:
        path=Path(directory)/'r.yaml';spec=dict(schema_version=1,stage='datagen',engine='mujoco',inputs={'scene':str(Path(settings['package_root'])/'scene.json'),'dataset':str(ROOT/'docs/evidence/mujoco-workflows/runs-final/annotation-auto')},execution={'target_successes':1,'max_attempts':2,'seed':1047},output={'directory':'new'},objects={name:{'placement':{'function':'placement.fixed_xy','params':{'frame':'world','support':'table','xy_m':[i*.05,-.22]}}} for i,name in enumerate(('cube_red','cube_blue','cube_green'))},functions={'acceptance':{'function':'pick_place.v8_datagen','params':{'object':'cube_red','target':'cup_a'}}})
        path.write_text(yaml.safe_dump(spec,sort_keys=False));registry=load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement'))
        plan=prepare_recipe(read_recipe(path),tasks=registry)
        catalog,pool,config,kin=load_inputs(plan)
        assert pool.episode_ids==tuple(e.episode_id for e in catalog.episodes)
        assert pool.subtask_boundaries['tool0']==[[(0,224),(224,388)]]
        assert kin.identity['solver']=='pinocchio_dls' and kin.identity['policy']=='best_effort'


def test_mujoco_datagen_runner_exists_before_engine_connection():
    from robot_learning_workbench.engines.mujoco import datagen
    assert callable(datagen.generate_attempt)
    assert callable(datagen.run)


def test_mujoco_real_generation_cancel_and_invalid_ik_never_publish(tmp_path,monkeypatch):
    import yaml
    from robot_learning_workbench.engines.mujoco import datagen
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    from robot_learning_workbench.data.native import load_catalog,history
    from robot_learning_workbench.generation.mimic import IKFailure
    template=yaml.safe_load((ROOT/'docs/evidence/simulation-workflows/mujoco-first.yaml').read_text())
    registry=load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement'))
    path=tmp_path/'r.yaml';template['output']['directory']=str(tmp_path/'cancelled');template['execution']['max_attempts']=1
    path.write_text(yaml.safe_dump(template,sort_keys=False));events=[]
    result=datagen.run(prepare_recipe(read_recipe(path),tasks=registry),events=events.append,commands=lambda:({'command_id':'stop','kind':'cancel'},) if events[-1]['payload']['tick']==2 else ())
    assert result.status=='cancelled' and not load_catalog(tmp_path/'cancelled').episodes
    assert history(tmp_path/'cancelled')[0]['diagnostics']['steps']==2
    template['output']['directory']=str(tmp_path/'invalid');path.write_text(yaml.safe_dump(template,sort_keys=False))
    original=datagen.mimic.solve_dls;calls=[]
    def invalid(*a,**kw):
        calls.append(1)
        if len(calls)==2:raise IKFailure({'failure_reason':'candidate_jump','command_applied':False})
        return original(*a,**kw)
    monkeypatch.setattr(datagen.mimic,'solve_dls',invalid)
    result=datagen.run(prepare_recipe(read_recipe(path),tasks=registry),events=lambda row:None,commands=lambda:())
    assert result.completed_episodes==0 and result.attempt_summary['budget_exhausted']
    assert not load_catalog(tmp_path/'invalid').episodes
    record=history(tmp_path/'invalid')[0]
    assert record['status']=='ik_failure' and record['diagnostics']['steps']==1
    assert record['diagnostics']['ik_summary']['applied_steps']==1
    assert record['diagnostics']['initial_snapshot']
    assert record['diagnostics']['last_applied_ik']['command_applied']
    assert not record['diagnostics']['invalid_ik']['command_applied']


def test_datagen_cannot_silently_ignore_engine_override(tmp_path):
    import yaml
    from robot_learning_workbench.recipe import read_recipe
    spec=yaml.safe_load((ROOT/'docs/evidence/simulation-workflows/mujoco-first.yaml').read_text())
    spec['inputs']['engine_config']='unexpected.json'
    p=tmp_path/'bad.yaml';p.write_text(yaml.safe_dump(spec))
    with pytest.raises(ValueError):read_recipe(p)


def test_float32_gripper_request_saturates_and_retains_physical_task_failure(tmp_path,monkeypatch):
    import yaml
    from robot_learning_workbench.engines.mujoco import datagen
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    from robot_learning_workbench.data.native import history,load_catalog
    spec=yaml.safe_load((ROOT/'docs/evidence/simulation-workflows/mujoco-first.yaml').read_text());spec['output']['directory']=str(tmp_path/'rejected');spec['execution']['max_attempts']=1
    path=tmp_path/'r.yaml';path.write_text(yaml.safe_dump(spec,sort_keys=False));plan=prepare_recipe(read_recipe(path),tasks=load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement')))
    catalog,pool,cfg,kin=datagen.load_inputs(plan);upper=float(np.nextafter(np.float32(kin.limits[5,1]),np.float32(np.inf)))
    assert 0<upper-kin.limits[5,1]<1e-7  # First float32 input above the actual pinned model bound.
    for info in pool.datagen_infos:info.gripper_action['tool0'].fill_(upper)
    monkeypatch.setattr(datagen,'load_inputs',lambda plan:(catalog,pool,cfg,kin))
    result=datagen.run(plan,events=lambda row:None,commands=lambda:())
    record=history(plan.output_path)[0]
    assert result.completed_episodes==0 and not load_catalog(plan.output_path).episodes
    assert record['status']=='failure' and record['diagnostics']['steps']==399
    assert record['diagnostics']['saturation']['per_joint_counts']['gripper']==399
    assert record['diagnostics']['category']=='grasp_failure'
    assert 'invalid_ik' not in record['diagnostics']
