"""Independent native MjData and thread-owned EGL contexts, not mocked physics."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import numpy as np
from scene_contract.package import load_scene
from robot_learning_workbench.data.native import NativeRun,load_catalog,read_array
from robot_learning_workbench.engines.mujoco.model import build_model,ModelConfig,JOINTS
from robot_learning_workbench.engines.mujoco.state import restore_episode,read_sample
from robot_learning_workbench.engines.mujoco.source import collect_episode
ROOT=Path(__file__).resolve().parents[2]


def actual_model():
    s=json.loads((ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text());p=Path(s['package_root'])
    cfg=ModelConfig(tuple(s['initial_joint_rad'][n] for n in JOINTS),('cube_red',),json.loads((p/s['baseline_metadata']['compiled_physics']['asset_path']).read_text())['objects'])
    return build_model(load_scene(p/'scene.json'),cfg)


def test_four_actual_independent_states_render_contexts_and_single_native_publisher(tmp_path):
    import mujoco,threading
    model,b=actual_model();states=[mujoco.MjData(model) for _ in range(4)];threads=set();barrier=threading.Barrier(4);events=[]
    for i,d in enumerate(states):
        restore_episode(model,d,b,None);d.qpos[b.q_indices[0]]+=i*.01;mujoco.mj_forward(model,d)
    before=[d.qpos.copy() for d in states]
    with NativeRun(tmp_path/'out',{'stage':'source','seed':7}) as owner:
        segments=[owner.segment('env-'+str(i)) for i in range(4)]
        def collect(i):
            threads.add(threading.get_ident());barrier.wait(timeout=10)
            target=states[i].qpos[list(b.q_indices)].copy();target[0]+=.005
            result=collect_episode(model,states[i],b,segments[i],episode_id='e'+str(i),env_index=i,seed=7+i,frames=2,read_target=lambda:target,events=events.append,commands=lambda:())
            return i,result
        with ThreadPoolExecutor(max_workers=4) as pool:
            for future in as_completed([pool.submit(collect,i) for i in range(4)]):
                i,(ep,media,snapshot,status)=future.result();assert status=='completed'
                segments[i].write_episode(ep,episode_id='e'+str(i),metadata={'env_index':i},media=media);segments[i].commit()
        untouched=states[1].qpos.copy();restore_episode(model,states[0],b,None)
        np.testing.assert_array_equal(states[1].qpos,untouched)
    catalog=load_catalog(tmp_path/'out');assert len(catalog.episodes)==4 and len(threads)==4
    for ep in catalog.episodes:
        i=ep.metadata['env_index'];np.testing.assert_array_equal(read_array(ep,'obs/policy/joint_pos')[0],before[i][list(b.q_indices)])
        assert {m['frames'] for m in ep.media.values()}=={2}
        assert read_sample(model,states[i],b,'post_step',1,env_index=i)['env_index']==i
    assert {e['payload']['env_index'] for e in events}==set(range(4))


def test_manual_commands_are_targeted_and_cancel_reaches_all_envs():
    from robot_learning_workbench.engines.mujoco.source import command_channels
    rows=iter([[{'command_id':'m','kind':'mark','env_index':3,'episode_id':'e3','payload':{'frame':2,'event':'grasp'}}],[{'command_id':'c','kind':'cancel'}]])
    channels,send=command_channels(lambda:next(rows,[]),lambda e:None,4)
    assert channels[0]()==[] and channels[3]()[0]['kind']=='cancel'
    assert {r['kind'] for r in channels[3]()}=={'cancel'}
    assert channels[1]()[0]['kind']=='cancel'


def test_random_evaluation_reuses_workspace_contract_and_placement_gate(tmp_path):
    import yaml
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.tasks.registry import load_registry
    from robot_learning_workbench.engines.mujoco.evaluation import evaluation_execution
    path=tmp_path/'r.yaml';spec=yaml.safe_load((ROOT/'docs/evidence/p01-rollout/mujoco-verified.yaml').read_text())
    random=yaml.safe_load((ROOT/'docs/evidence/random-placement/release/random.yaml').read_text());spec['objects']=random['objects'];spec['execution']['env_num']=4;spec['output']['directory']=str(tmp_path/'out');path.write_text(yaml.safe_dump(spec))
    plan=prepare_recipe(read_recipe(path),tasks=load_registry(('robot_learning_workbench.tasks.pick_place','robot_learning_workbench.tasks.placement')))
    record={'step':4,'files':{}}
    value=evaluation_execution(plan,{'recording':{}},record)
    assert value['rng_policy']=='entropy_workspace_poses_no_rng_resume_v1'
    assert plan.function_bindings['success'].name=='pick_place.v8_evaluation'


def test_peer_failure_interrupts_paused_loop_without_fake_cancel_ack():
    import pytest
    from robot_learning_workbench.engines.mujoco.source import command_channels
    events=[];polls,send=command_channels(lambda:(),events.append,4);send.stop()
    with pytest.raises(RuntimeError,match='Sibling'):polls[3]()
    assert events==[]


def test_vector_pause_is_global_and_step_is_explicitly_rejected():
    from robot_learning_workbench.engines.mujoco.source import command_channels
    queue=[{'command_id':'pause','kind':'pause','env_index':2,'episode_id':'e2'},{'command_id':'step','kind':'step','env_index':2,'payload':{'count':1}}];events=[]
    polls,send=command_channels(lambda:queue.copy() if not events else (),events.append,4,vector=True)
    send.refresh();assert send.paused() and events[0]['payload']['status']=='rejected'
    for poll in polls:
        rows=poll();assert rows==[{'command_id':'pause','kind':'pause'}]


def test_annotation_refuses_trimmed_source_without_fabricating_new_initial_state():
    import pytest
    from types import SimpleNamespace as NS
    from robot_learning_workbench.engines.mujoco.annotation import validate_source_ranges
    validate_source_ranges(NS(episodes=[NS(start=0,stop=None,num_frames=10),NS(start=0,stop=10,num_frames=10)]))
    with pytest.raises(ValueError,match='complete Source'):validate_source_ranges(NS(episodes=[NS(start=2,stop=8,num_frames=10)]))
