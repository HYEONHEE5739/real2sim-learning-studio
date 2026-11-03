"""DataGen inherits Annotation physics; an explicit conflicting file is not ignored."""
from copy import deepcopy
from dataclasses import asdict,replace
from importlib import import_module
import json
import pytest
from robot_learning_workbench import recipe
from robot_learning_workbench.data.native import NativeRun,load_catalog
from robot_learning_workbench.robot.calibration import JOINTS
from test_recipe_preparation import scene,source_doc,registry


def inputs(tmp_path,scene,engine,declared):
    settings={'initial_joint_rad':[0.]*6,'active_object_ids':['cube_red'],
              'object_physics':{'cube_red':{'mass_kg':.05,'material':{'static_friction':1.,'dynamic_friction':1.,'restitution':0.}}}}
    if engine=='isaac':settings['isaac']={'physics_timestep_s':1/300,'decimation':10}
    execution={'stage':'annotation','engine':engine,'scene_identity':asdict(scene.identity),
               'model_config':settings,'active_objects':['cube_red'],'partition':'unpartitioned',
               'recording':dict(joint_order=list(JOINTS),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',task_phase='post_step',fps=30,resolution=[640,480])}
    with NativeRun(tmp_path/'annotation',execution)as owner:pass
    values={'scene':'scene/scene.json','dataset':str(owner.root)}
    if declared is not None:
        override=deepcopy(settings);declared(override)
        path=tmp_path/'engine.json';path.write_text(json.dumps(override));values['engine_config']=str(path)
    doc=source_doc(tmp_path,stage='datagen',engine='isaaclab'if engine=='isaac'else engine,inputs=values,
        functions={'acceptance':{'function':'pick_place.v8_datagen','params':{'object':'cube_red','target':'cup'}}},
        execution={'seed':1047,'num_episodes':1,'max_attempts':2})
    plan=recipe.prepare_recipe(doc,scene=scene,tasks=registry())
    return plan,load_catalog(owner.root)


@pytest.mark.parametrize('engine',['mujoco','isaac'])
@pytest.mark.parametrize('field',['mass_kg','dynamic_friction'])
def test_both_datagen_loaders_reject_conflicting_explicit_physics_before_source_selection(tmp_path,scene,engine,field,monkeypatch):
    def change(cfg):
        target=cfg['object_physics']['cube_red']
        if field=='dynamic_friction':target=target['material']
        target[field]=.2
    plan,catalog=inputs(tmp_path,scene,engine,change)
    module=import_module('robot_learning_workbench.engines.'+engine+'.datagen')
    from robot_learning_workbench.tasks import execution
    def source_selection(*args):raise AssertionError('Explicit engine_config was ignored before source selection')
    monkeypatch.setattr(execution,'mimic_objects',source_selection)
    if engine=='isaac':monkeypatch.setattr(module,'model_identity',lambda *args:catalog.execution.get('model_sha256'))
    with pytest.raises(recipe.RecipeError)as error:module.load_inputs(plan)
    assert error.value.code=='INPUT_CONFLICT'and error.value.effect=='not_started'
    assert field in str(error.value)and 'inputs.engine_config'in str(error.value)
    assert not plan.output_path.exists()


@pytest.mark.parametrize('engine',['mujoco','isaac'])
@pytest.mark.parametrize('explicit',[False,True])
def test_inherited_settings_work_without_override_and_accept_equivalent_explicit_settings(tmp_path,scene,engine,explicit):
    from robot_learning_workbench.data.recording import datagen_settings
    def equivalent(cfg):
        cfg['package_root']='/different/local/package/location'
        cfg['initial_joint_rad']=dict(zip(JOINTS,cfg['initial_joint_rad']))
        cfg['active_object_ids']+=['cube_blue','cube_green']
    plan,catalog=inputs(tmp_path,scene,engine,equivalent if explicit else None)
    before=recipe._plain(catalog.execution);declared=recipe._plain(plan.input_documents)
    settings=recipe._plain(datagen_settings(plan,catalog))
    assert settings['object_physics']==before['model_config']['object_physics']
    assert settings['active_object_ids']==['cube_red']
    assert recipe._plain(catalog.execution)==before and recipe._plain(plan.input_documents)==declared
    assert not plan.output_path.exists()


@pytest.mark.parametrize('engine',['mujoco','isaac'])
def test_missing_recorded_settings_cannot_fall_back_to_a_new_config(tmp_path,scene,engine):
    from robot_learning_workbench.data.recording import datagen_settings
    plan,catalog=inputs(tmp_path,scene,engine,lambda cfg:None)
    changed=dict(catalog.execution);changed.pop('model_config')
    with pytest.raises(recipe.RecipeError,match='model_config'):
        datagen_settings(plan,replace(catalog,execution=changed))


@pytest.mark.parametrize('engine',['mujoco','isaac'])
def test_runtime_rechecks_a_conflicting_plan_even_when_input_binding_already_exists(tmp_path,scene,engine):
    from robot_learning_workbench.data.recording import datagen_settings
    plan,catalog=inputs(tmp_path,scene,engine,lambda cfg:None)
    documents=recipe._plain(plan.input_documents);documents['engine_config']['decimation'if engine=='mujoco'else'isaac']=(20 if engine=='mujoco'else{'physics_timestep_s':1/600,'decimation':20})
    if engine=='mujoco':documents['engine_config']['physics_timestep_s']=1/600
    with pytest.raises(recipe.RecipeError,match='decimation'):
        datagen_settings(replace(plan,input_documents=documents),catalog)


@pytest.mark.parametrize('engine',['mujoco','isaac'])
def test_equivalent_angle_representation_does_not_drop_an_extra_joint(tmp_path,scene,engine):
    from robot_learning_workbench.data.recording import datagen_settings
    plan,catalog=inputs(tmp_path,scene,engine,lambda cfg:cfg['initial_joint_rad'].append(0.))
    with pytest.raises(recipe.RecipeError,match='initial_joint_rad'):
        datagen_settings(plan,catalog)
