from dataclasses import asdict
import hashlib,json
from pathlib import Path
import pytest
from scene_contract.package import load_scene
from robot_learning_workbench import recipe as r
from robot_learning_workbench.tasks.registry import load_registry
from robot_learning_workbench.data.native import NativeRun
from test_placement import scene as v8_scene


@pytest.fixture
def scene(tmp_path):
    root=tmp_path/'scene';root.mkdir();v8_scene.__wrapped__(root)
    data=json.loads((root/'scene.json').read_text());(root/'entry.xml').write_text('<mujoco/>')
    data['engines']={'mujoco':{'asset_path':'entry.xml'},'isaac':{'asset_path':'entry.xml'}}
    data['objects']['cup']={'role':'environment','frame_id':'world','task_geometry':{'dimensions_m':[.1,.1,.1],'wall_m':.002,'bottom_diameter_m':.08}}
    (root/'scene.json').write_text(json.dumps(data))
    entries=[{'path':p.name,'size_bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in [root/'scene.json',root/'calibration.json',root/'entry.xml']]
    (root/'manifest.json').write_text(json.dumps({'schema_version':1,'files':entries}));return load_scene(root/'scene.json')


def source_doc(tmp_path,objects=None,**changes):
    import yaml
    data={'schema_version':1,'stage':'source','engine':'mujoco','inputs':{'scene':'scene/scene.json','device_profile':'leader.json'},
        'objects':objects or {'cube_red':{'placement':{'function':'placement.random_xy','params':{'frame':'workspace','support':'marker_top','rules':'v8_preserved'}}}},
        'execution':{'episodes':2,'seed':42},'output':{'directory':'new'}}
    data.update(changes);(tmp_path/'leader.json').write_text('{"role":"leader"}')
    p=tmp_path/'recipe.yaml';p.write_text(yaml.safe_dump(data,sort_keys=False));return r.read_recipe(p)


def registry():return load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement'))


def test_scene_object_order_params_and_input_identity_are_fixed(tmp_path,scene):
    objects={n:{'placement':{'function':'placement.random_xy','params':{'frame':'workspace','support':'marker_top'}}} for n in ('cube_blue','cube_red')}
    doc=source_doc(tmp_path,objects);plan=r.prepare_recipe(doc,scene=scene,tasks=registry(),inputs={})
    assert plan.object_order==('cube_blue','cube_red') and plan.scene_identity==asdict(scene.identity)
    assert plan.function_bindings['objects.cube_red.placement'].params.object=='cube_red'
    assert plan.output_path==tmp_path/'new' and plan.engine=='mujoco'
    r.verify_prepared_inputs(plan)
    (tmp_path/'leader.json').write_text('{"changed":true}')
    with pytest.raises(r.RecipeError) as error:r.verify_prepared_inputs(plan)
    assert error.value.code=='INPUT_CHANGED'


def test_fixed_request_values_are_separate_from_registered_params(tmp_path,scene):
    obj={'cube_red':{'placement':{'function':'placement.fixed_xy','params':{'frame':'workspace','support':'marker_top','xy_m':[.02,-.24]}}}}
    plan=r.prepare_recipe(source_doc(tmp_path,obj),scene=scene,tasks=registry(),inputs={})
    binding=plan.function_bindings['objects.cube_red.placement']
    assert binding.request_fields['xy_m']==(.02,-.24)
    assert not hasattr(binding.params,'xy_m')


def dataset(tmp_path,scene):
    with NativeRun(tmp_path/'data',{'stage':'source','scene_identity':asdict(scene.identity),'active_objects':['cube_red']}):pass


def annotation_doc(tmp_path):
    p=tmp_path/'annotation.yaml';p.write_text('''schema_version: 1
stage: annotation
engine: mujoco
inputs: {dataset: data, scene: scene/scene.json}
functions:
  acceptance: {function: pick_place.v8_annotation, params: {object: cube_red, target: cup}}
execution: {mode: auto}
output: {directory: annotation}
''');return r.read_recipe(p)


def test_acceptance_only_binds_one_grasp_tracker_without_running_it(tmp_path,scene):
    dataset(tmp_path,scene);plan=r.prepare_recipe(annotation_doc(tmp_path),scene=scene,tasks=registry(),inputs={})
    assert plan.function_bindings['signals.grasp'].params.object=='cube_red'
    assert plan.function_bindings['signals.grasp'].phase=='post_step'
    assert plan.function_bindings['acceptance'].phase=='episode_end'
    assert len([b for b in plan.function_bindings.values() if b.kind=='tracker'])==1
    assert plan.object_order==()  # recorded initial, never random reset


def test_missing_historical_scene_identity_is_not_latest_fallback(tmp_path,scene):
    with NativeRun(tmp_path/'data',{'stage':'source'}):pass
    with pytest.raises(r.RecipeError):r.prepare_recipe(annotation_doc(tmp_path),scene=scene,tasks=registry(),inputs={})


def test_training_preparation_has_no_scene_or_task_requirement(tmp_path):
    data=tmp_path/'official/meta';data.mkdir(parents=True);(data/'info.json').write_text('{"features":{}}')
    (tmp_path/'train.json').write_text('{"policy":{"type":"act"}}')
    p=tmp_path/'train.yaml';p.write_text('''schema_version: 1
stage: train
inputs: {dataset: official, training_config: train.json}
execution: {mode: scratch}
output: {directory: model}
''')
    plan=r.prepare_recipe(r.read_recipe(p),scene=None,tasks=None,inputs={})
    assert plan.scene_identity is None and not plan.function_bindings
    assert 'official_training_validation' in plan.pending_checks


@pytest.mark.parametrize('bad',['object','frame','function','selection'])
def test_bad_refs_and_removed_objects_rejected(tmp_path,scene,bad):
    doc=source_doc(tmp_path)
    data=r._plain(doc.spec)
    if bad=='object':data['objects']={'missing':data['objects']['cube_red']}
    if bad=='frame':data['objects']['cube_red']['placement']['params']['frame']='missing'
    if bad=='function':data['objects']['cube_red']['placement']['function']='unknown.reset'
    if bad=='selection':
        data['functions']={'metrics':{'function':'pick_place.v8_metrics','params':{'object':'cube_blue','target':'cup'}}}
    import yaml
    (tmp_path/'recipe.yaml').write_text(yaml.safe_dump(data,sort_keys=False))
    with pytest.raises(ValueError):r.prepare_recipe(r.read_recipe(tmp_path/'recipe.yaml'),scene=scene,tasks=registry(),inputs={})


def test_cli_uses_same_preparation_and_does_not_execute_stage(tmp_path,capsys):
    from robot_learning_workbench.cli import main
    official=tmp_path/'official/meta';official.mkdir(parents=True);(official/'info.json').write_text('{}');(tmp_path/'train.json').write_text('{"policy":{"type":"act"}}')
    p=tmp_path/'train.yaml';p.write_text('''schema_version: 1
stage: train
inputs: {dataset: official, training_config: train.json}
execution: {mode: scratch}
output: {directory: model}
''')
    assert main(['prepare',str(p),'--stage','train'])==0
    result=json.loads(capsys.readouterr().out)
    assert result['status']=='prepared' and 'official_training_validation' in result['pending_checks']
    assert not (tmp_path/'model').exists()


def test_datagen_fixed_contract_is_provenance_not_fake_runtime_identity(tmp_path,scene):
    dataset(tmp_path,scene)
    doc=source_doc(tmp_path,stage='datagen',inputs={'scene':'scene/scene.json','dataset':'data'},
        functions={'acceptance':{'function':'pick_place.v8_datagen','params':{'object':'cube_red','target':'cup'}}},
        execution={'seed':1047,'target_successes':2,'max_attempts':4})
    plan=r.prepare_recipe(doc,scene=scene,tasks=registry(),inputs={})
    policy=plan.effective_settings['ik_policy_contract']
    assert policy['algorithm']=='pinocchio_dls' and policy['failure_policy']=='best_effort'
    assert 'code_sha256' not in policy and 'datagen_ik_runtime_identity' in plan.pending_checks


def test_changed_scene_and_task_code_conflicts(tmp_path,scene):
    doc=source_doc(tmp_path);plan=r.prepare_recipe(doc,scene=scene,tasks=registry(),inputs={})
    (tmp_path/'scene/entry.xml').write_text('mutated asset')
    with pytest.raises(r.RecipeError) as ex:r.verify_prepared_inputs(plan)
    assert ex.value.code=='INPUT_CHANGED'


def test_annotation_supplied_scene_is_pinned_even_without_recipe_location(tmp_path,scene):
    dataset(tmp_path,scene);doc=annotation_doc(tmp_path)
    text=doc.raw.decode().replace(', scene: scene/scene.json','');doc.path.write_text(text)
    plan=r.prepare_recipe(r.read_recipe(doc.path),scene=scene,tasks=registry(),inputs={})
    assert plan.resolved_inputs['scene']['identity']==asdict(scene.identity)
    (tmp_path/'scene/entry.xml').write_text('changed')
    with pytest.raises(r.RecipeError):r.verify_prepared_inputs(plan)


def test_new_task_module_needs_no_core_change_and_changed_code_is_blocked(tmp_path,scene,monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path));path=tmp_path/'extra_recipe_task.py'
    path.write_text('''from dataclasses import dataclass
from robot_learning_workbench.tasks.registry import FunctionSpec
called=0
@dataclass(frozen=True)
class Params:
 threshold: float=.5
def metrics(sample,*,params):
 global called
 called+=1
 return {"x":1.}
FUNCTIONS={"extra.metrics":FunctionSpec(kind="metrics",stages={"source"},engines={"independent"},params_type=Params,callable=metrics)}
''')
    tasks=load_registry(('robot_learning_workbench.tasks.placement','extra_recipe_task'))
    doc=source_doc(tmp_path,functions={'metrics':{'function':'extra.metrics','params':{'threshold':.2}}})
    plan=r.prepare_recipe(doc,scene=scene,tasks=tasks,inputs={})
    import extra_recipe_task
    assert extra_recipe_task.called==0 and plan.function_bindings['metrics'].params.threshold==.2
    path.write_text(path.read_text()+'\n# changed code identity\n')
    with pytest.raises(r.RecipeError):r.verify_prepared_inputs(plan)


def test_excluded_minivla_policy_is_rejected_before_official_loader(tmp_path):
    data=tmp_path/'official/meta';data.mkdir(parents=True);(data/'info.json').write_text('{}');(tmp_path/'train.json').write_text('{"policy":{"type":"minivla"}}')
    path=tmp_path/'train.yaml';path.write_text('''schema_version: 1
stage: train
inputs: {dataset: official, training_config: train.json}
execution: {mode: scratch}
output: {directory: model}
''')
    with pytest.raises(r.RecipeError):r.prepare_recipe(r.read_recipe(path),scene=None,tasks=None,inputs={})


def test_official_train_config_cannot_override_saved_output(tmp_path):
    data=tmp_path/'official/meta';data.mkdir(parents=True);(data/'info.json').write_text('{}')
    (tmp_path/'train.json').write_text(json.dumps({'policy':{'type':'act'},'output_dir':str(tmp_path/'other')}))
    path=tmp_path/'train.yaml';path.write_text('''schema_version: 1
stage: train
inputs: {dataset: official, training_config: train.json}
execution: {mode: scratch}
output: {directory: model}
''')
    with pytest.raises(r.RecipeError) as ex:r.prepare_recipe(r.read_recipe(path),scene=None,tasks=None,inputs={})
    assert ex.value.code=='INPUT_CONFLICT'


def test_official_resume_requires_explicit_checkpoint_before_any_output_change(tmp_path):
    data=tmp_path/'official/meta';data.mkdir(parents=True);(data/'info.json').write_text('{}');(tmp_path/'train.json').write_text('{"policy":{"type":"act"},"resume":true}')
    (tmp_path/'model').mkdir()
    path=tmp_path/'train.yaml';path.write_text('''schema_version: 1
stage: train
inputs: {dataset: official, training_config: train.json}
execution: {mode: resume}
output: {directory: model}
''')
    with pytest.raises(r.RecipeError) as ex:r.prepare_recipe(r.read_recipe(path),scene=None,tasks=None,inputs={})
    assert ex.value.code=='RESUME_INCOMPATIBLE'


def test_official_snapshot_file_symlinks_are_hashed_without_copying(tmp_path):
    model=tmp_path/'snapshot';model.mkdir();blob=tmp_path/'blob';blob.write_bytes(b'fixture weight bytes')
    (model/'model.safetensors').symlink_to(blob)
    artifact=r._artifact(model)
    assert artifact['files']['model.safetensors']==hashlib.sha256(blob.read_bytes()).hexdigest()
    blob.write_bytes(b'changed bytes');assert r._artifact(model)['identity']!=artifact['identity']


def test_pinned_hub_catalog_uses_local_snapshot_without_network_or_scene(tmp_path):
    official=tmp_path/'snapshot/meta';official.mkdir(parents=True);(official/'info.json').write_text('{}');(tmp_path/'train.json').write_text('{"policy":{"type":"act"}}')
    path=tmp_path/'train.yaml';path.write_text('''schema_version: 1
stage: train
inputs: {dataset: 'hf://owner/data', training_config: train.json}
execution: {mode: scratch}
output: {directory: model}
''')
    artifact=r._artifact(official.parent)
    entry={**artifact,'source_uri':'hf://owner/data','revision':'1'*40}
    plan=r.prepare_recipe(r.read_recipe(path),scene=None,tasks=None,inputs={'dataset':entry})
    assert plan.resolved_inputs['dataset']['revision']=='1'*40 and plan.scene_identity is None


def test_orientation_booleans_are_not_coerced_to_rotation_numbers(tmp_path,scene):
    objects={'cube_red':{'placement':{'function':'placement.random_xy','params':{'frame':'workspace','support':'marker_top','orientation':[[True,False,False],[False,True,False],[False,False,True]]}}}}
    with pytest.raises(r.RecipeError):r.prepare_recipe(source_doc(tmp_path,objects),scene=scene,tasks=registry(),inputs={})

@pytest.mark.parametrize('kind',['retired_workbench_index','official_policy_projection'])
def test_replay_preparation_requires_native_recording_not_generic_artifact(tmp_path,scene,kind):
    data=tmp_path/'data';data.mkdir()
    if kind=='retired_workbench_index':(data/'dataset.json').write_text('{"dataset_id":"retired","episodes":[]}')
    else:
        (data/'meta').mkdir();(data/'meta/info.json').write_text('{}')
    with pytest.raises(r.RecipeError) as exc:r.prepare_recipe(annotation_doc(tmp_path),scene=scene,tasks=registry(),inputs={})
    assert exc.value.code=='INPUT_FORMAT_UNSUPPORTED'
