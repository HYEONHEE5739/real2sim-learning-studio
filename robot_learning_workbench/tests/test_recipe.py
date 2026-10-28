from pathlib import Path
import pytest
from robot_learning_workbench import recipe as r


def source_yaml():
    return '''schema_version: 1
stage: source
engine: mujoco
inputs: {scene: scene/scene.json, device_profile: leader.json}
objects:
  red:
    placement: {function: placement.random_xy, params: {frame: workspace, support: top, rules: v8_preserved}}
execution: {episodes: 2, seed: 42}
output: {directory: outputs/source}
'''


def save(tmp_path,text):
    p=tmp_path/'recipe.yaml';p.write_text(text);return p


def test_recipe_exact_bytes_order_and_no_task_import(tmp_path):
    text=source_yaml().replace('  red:', '  blue:\n    placement: {function: placement.random_xy, params: {frame: workspace, support: top}}\n  red:')
    doc=r.read_recipe(save(tmp_path,text),expected_stage='source')
    assert doc.raw==text.encode() and doc.base_dir==tmp_path
    assert tuple(doc.spec.objects)==('blue','red')
    with pytest.raises(TypeError):doc.spec.execution['seed']=0


@pytest.mark.parametrize('change',[
 lambda s:s+'surprise: true\n',lambda s:s.replace('seed: 42','seed: true'),lambda s:s.replace('episodes: 2','episodes: 0'),
 lambda s:s.replace('engine: mujoco','engine: bullet'),lambda s:s.replace('seed: 42','seed: .nan'),
 lambda s:s.replace('schema_version: 1','schema_version: 2'),lambda s:s.replace('seed: 42','seed: 1, seed: 2'),
 lambda s:s.replace('inputs: {scene:', 'inputs: &a {scene:'),lambda s:s.replace('seed: 42','seed: !!python/object:os.system {}'),
 lambda s:s.replace('stage: source','stage: unknown'),lambda s:s.replace('episodes: 2','episodes: "2"'),
 lambda s:s.replace('objects:','functions: {success: {function: x, params: {}}}\nobjects:'),
])
def test_invalid_yaml_or_stage_fields_are_structured(tmp_path,change):
    with pytest.raises(r.RecipeError) as error:r.read_recipe(save(tmp_path,change(source_yaml())))
    assert error.value.code in ('RECIPE_INVALID','SCHEMA_UNSUPPORTED') and error.value.issues[0].source


def test_annotation_has_no_objects_and_train_has_no_engine_requirement(tmp_path):
    train='''schema_version: 1
stage: train
inputs: {dataset: data, training_config: train.json}
execution: {mode: scratch}
output: {directory: models/new}
'''
    assert r.read_recipe(save(tmp_path,train)).spec.engine is None
    with pytest.raises(r.RecipeError):r.read_recipe(save(tmp_path,train+'engine: mujoco\n'))
    with pytest.raises(r.RecipeError):r.read_recipe(save(tmp_path,train),expected_stage='annotation')


@pytest.mark.parametrize('key',['ik_solver','ik_failure_policy','ik_parameters','ik_identity'])
def test_datagen_ik_selection_rejected_even_when_fixed_value(tmp_path,key):
    text='''schema_version: 1
stage: datagen
engine: mujoco
inputs: {scene: scene.json, dataset: dataset.json}
objects: {red: {placement: {function: placement.random_xy, params: {frame: world, support: top}}}}
functions: {acceptance: {function: pick_place.v8_datagen, params: {object: red, target: cup}}}
execution: {seed: 1, target_successes: 2, max_attempts: 4}
output: {directory: new}
'''
    text=text.replace('seed: 1',key+': best_effort, seed: 1')
    with pytest.raises(r.RecipeError) as error:r.read_recipe(save(tmp_path,text))
    assert error.value.code=='RECIPE_INVALID'


@pytest.mark.parametrize('extra',['functions: {}','objects: {}','engine: mujoco'])
def test_engine_independent_stage_rejects_irrelevant_sections(tmp_path,extra):
    text='''schema_version: 1
stage: offline_validation
inputs: {dataset: data, policy: model}
execution: {batch_size: 4}
output: {directory: results}
'''+extra+'\n'
    with pytest.raises(r.RecipeError):r.read_recipe(save(tmp_path,text))


def test_recipe_symlink_has_same_parent_semantics_in_cli_api_and_worker(tmp_path):
    target=tmp_path/'target';target.mkdir();alias=tmp_path/'alias';alias.mkdir()
    saved=save(target,source_yaml());link=alias/'recipe.yaml';link.symlink_to(saved)
    doc=r.read_recipe(link)
    assert doc.path==saved.resolve() and doc.base_dir==target.resolve()
