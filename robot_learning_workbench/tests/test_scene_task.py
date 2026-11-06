"""Typed memo intent uses the existing Task registry, not a language parser."""
import copy
import pytest
from test_pick_place import task_scene, scene, final_sample
from robot_learning_workbench.tasks.registry import load_registry, validate_params


def intent():
    return dict(kind='pick_place', instruction='Put the red block in the cup.',
                object_id='red', target_id='cup', steps=['pick', 'place'],
                required_observations=['contacts', 'placement_points'], needs=[])


@pytest.mark.parametrize('engine', ['mujoco', 'isaac'])
def test_task_proposal_reuses_registered_functions_and_physical_acceptance(task_scene, engine):
    from robot_learning_workbench.tasks.scene import task_recipe
    registry=load_registry(('robot_learning_workbench.tasks.pick_place',))
    original=copy.deepcopy(intent())
    for stage in ('annotation','datagen','simulation_evaluation'):
        result=task_recipe(task_scene,original,registry,stage,engine)
        assert result['status']=='CONFIGURED' and result['source_sha256']==dict(registry.source_sha256)
        role='success' if stage=='simulation_evaluation' else 'acceptance'
        binding=result['functions'][role]; spec=registry.functions[binding['function']]
        params=validate_params(registry,binding['function'],binding['params'],kind=spec.kind,stage=stage,engine=engine,scene=task_scene)
        assert spec.callable(final_sample(),params=params)
        assert not spec.callable(final_sample(placed=False),params=params)
        if role=='acceptance':assert not spec.callable(final_sample(grasp=False),params=params)
        assert result['execution_verified'] is False
    assert original==intent()


@pytest.mark.parametrize('change', [dict(kind='fold_cloth'),dict(needs=['drawer joint']),dict(required_observations=['cloth_vertices'])])
def test_missing_task_capabilities_do_not_fall_back_to_pick_place(task_scene,change):
    from robot_learning_workbench.tasks.scene import task_recipe
    registry=load_registry(('robot_learning_workbench.tasks.pick_place',))
    result=task_recipe(task_scene,intent()|change,registry,'datagen','mujoco')
    assert result['status']=='NEEDS_IMPLEMENTATION' and result['needs']
    assert result['functions']=={} and result['execution_verified'] is False


def test_scene_only_and_invalid_task_reference(task_scene):
    from robot_learning_workbench.tasks.scene import task_recipe
    registry=load_registry(('robot_learning_workbench.tasks.pick_place',))
    assert task_recipe(task_scene,None,registry,'annotation','mujoco')['status']=='NO_TASK'
    with pytest.raises(ValueError,match='unknown Object'):
        task_recipe(task_scene,intent()|dict(target_id='missing'),registry,'annotation','mujoco')


def test_exported_task_reads_owned_config_and_rejects_changed_bytes(task_scene):
    import hashlib,json,yaml
    from scene_contract.package import load_scene
    from robot_learning_workbench.tasks.scene import exported_task
    root=task_scene.root
    config=root/'task.yaml';config.write_text(yaml.safe_dump({'task':intent()}))
    authored=root/'authored_scene.json'
    authored.write_text(json.dumps({'reconstruction_configuration':{'path':'task.yaml','sha256':hashlib.sha256(config.read_bytes()).hexdigest()}}))
    manifest=json.loads((root/'manifest.json').read_text())
    for path in (config,authored):
        manifest['files'].append(dict(path=path.name,size_bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    (root/'manifest.json').write_text(json.dumps(manifest))
    package=load_scene(root/'scene.json')
    assert exported_task(package)==intent()
    config.write_text(yaml.safe_dump({'task':intent()|dict(target_id='other')}))
    with pytest.raises(ValueError,match='changed'):exported_task(package)
