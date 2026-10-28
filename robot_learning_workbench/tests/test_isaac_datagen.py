"""Isaac DataGen binding, without importing or simulating an Isaac app."""
from pathlib import Path
import json
import pytest
ROOT=Path(__file__).resolve().parents[2]


def test_isaac_annotation_model_and_pool_are_ready_for_fixed_ik(tmp_path):
    import yaml
    from robot_learning_workbench.engines.isaac.datagen import load_inputs
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    settings=json.loads((ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text())
    spec=dict(schema_version=1,stage='datagen',engine='isaaclab',inputs={'scene':str(Path(settings['package_root'])/'scene.json'),'dataset':str(ROOT/'docs/evidence/simulation-workflows/isaac-production-annotation-second/annotation')},execution={'target_successes':1,'max_attempts':2,'seed':1047,'headless':True},output={'directory':str(tmp_path/'out')},objects={n:{'placement':{'function':'placement.fixed_xy','params':{'frame':'world','support':'table','xy_m':[i*.055,-.22]}}} for i,n in enumerate(('cube_red','cube_blue','cube_green'))},functions={'acceptance':{'function':'pick_place.v8_datagen','params':{'object':'cube_red','target':'cup_a'}}})
    p=tmp_path/'r.yaml';p.write_text(yaml.safe_dump(spec,sort_keys=False));plan=prepare_recipe(read_recipe(p),tasks=load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement')))
    catalog,pool,settings,kin=load_inputs(plan)
    assert len(catalog.episodes)==1 and pool.subtask_boundaries['tool0']==[[(0,223),(223,388)]]
    assert kin.identity['policy']=='best_effort'


def test_legacy_seeded_random_is_rejected_by_new_datagen_policy():
    from types import SimpleNamespace
    from robot_learning_workbench.engines.isaac.datagen import validate_placements
    fixed=SimpleNamespace(function_bindings={'objects.cube.placement':SimpleNamespace(kind='placement',name='placement.fixed_xy')})
    validate_placements(fixed)
    random=SimpleNamespace(function_bindings={'objects.cube.placement':SimpleNamespace(kind='placement',name='placement.random_xy')})
    with pytest.raises(ValueError,match='random_workspace'):
        validate_placements(random)
