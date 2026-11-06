"""Fresh physics recordings for runner tests, never relabel historical data."""
import atexit
from functools import lru_cache
import json
from pathlib import Path
import tempfile


@lru_cache(maxsize=1)
def current_recordings():
    import mujoco
    import yaml
    from robot_learning_workbench.data.native import NativeRun,load_catalog,open_native
    from robot_learning_workbench.engines.mujoco import source,annotation
    from robot_learning_workbench.engines.mujoco.state import restore_episode
    from robot_learning_workbench.recipe import prepare_recipe,read_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    root=Path(__file__).resolve().parents[2]
    temporary=tempfile.TemporaryDirectory(prefix='workbench-mujoco-fixture-')
    atexit.register(temporary.cleanup);folder=Path(temporary.name)
    old=load_catalog(root/'docs/evidence/mujoco-workflows/runs-final/source')
    settings=json.loads((root/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text())
    spec=dict(schema_version=1,stage='source',engine='mujoco',
        inputs={'scene':str(Path(settings['package_root'])/'scene.json'),'source_dataset':str(old.root)},
        execution={'num_episodes':1},output={'directory':str(folder/'source')})
    path=folder/'source.yaml';path.write_text(yaml.safe_dump(spec))
    plan=prepare_recipe(read_recipe(path))
    cfg=source.resolved_model_config(plan,old.execution['model_config'])
    model,b=source.build_model(plan.scene,cfg);data=mujoco.MjData(model)
    row=old.episodes[0];reader=open_native(row)
    try:recorded=reader.load_episode(row.key,'cpu')
    finally:reader.close()
    def arrays(value):return {k:arrays(v)for k,v in value.items()}if isinstance(value,dict)else value.numpy().copy()
    # Canonical recorded initial + numeric targets are inputs to a NEW run.
    # The old opaque snapshot/model identity is never changed or reused.
    restore_episode(model,data,b,arrays(recorded.data['initial_state']))
    targets=iter(recorded.data['joint_targets'].numpy())
    with NativeRun(folder/'source',source.execution_contract(plan,b,cfg))as owner:
        segment=owner.segment('recorded-input');claim=owner.claim_attempt(segment)
        episode,media,snapshot,status=source.collect_episode(model,data,b,segment,
            episode_id='recorded-input',frames=len(recorded.data['joint_targets']),
            read_target=lambda:next(targets),events=lambda _:None,commands=lambda:())
        assert status=='completed'
        segment.write_episode(episode,episode_id='recorded-input',metadata={'success_source':'recording_only','initial_snapshot':snapshot},media=media)
        segment.record_attempt(claim,status='success',episode_id='recorded-input');segment.commit()
    spec.update(stage='annotation',inputs={'scene':spec['inputs']['scene'],'dataset':str(folder/'source')},
        execution={'mode':'auto'},functions={'acceptance':{'function':'pick_place.annotation','params':{'object':'cube_red','target':'cup_a'}}},
        output={'directory':str(folder/'annotation')})
    path=folder/'annotation.yaml';path.write_text(yaml.safe_dump(spec))
    result=annotation.run(prepare_recipe(read_recipe(path),tasks=load_registry(('robot_learning_workbench.tasks.pick_place',))),events=lambda _:None,commands=lambda:())
    assert result.completed_episodes==1,'Fresh physics fixture did not pass Annotation'
    return folder/'source',folder/'annotation'
