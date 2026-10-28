"""E05 pure planning preserves official Mimic math and v8 RNG/phase semantics."""
import asyncio,copy,json
from pathlib import Path
import numpy as np
import pytest
import torch


def test_attempt_seed_matches_recorded_v8_and_does_not_change_global_rng():
    from robot_learning_workbench.generation.mimic import attempt_seed
    before=np.random.get_state()
    assert attempt_seed(1047,1)==892243098
    assert np.array_equal(before[1],np.random.get_state()[1])
    for seed,attempt in ((1,0),(1047,20),(2**32-1,2)):
        assert attempt_seed(seed,attempt)==int(np.random.SeedSequence([seed,attempt]).generate_state(1)[0])
    for values in ((-1,1),(1,-1),(True,1),(1,1.2)):
        with pytest.raises(ValueError):attempt_seed(*values)


def test_random_stream_nested_isolation_and_exception_restore():
    from robot_learning_workbench.generation.mimic import RandomStream
    np_before=np.random.get_state();torch_before=torch.random.get_rng_state().clone()
    stream=RandomStream(91)
    with stream.active():
        a=np.random.rand()
        with stream.active():b=torch.rand(3)
    with pytest.raises(RuntimeError):
        with stream.active():
            c=np.random.rand();raise RuntimeError('abort')
    reference=np.random.RandomState(91)
    assert a==reference.rand() and c==reference.rand()
    assert torch.equal(b,torch.rand(3,generator=torch.Generator().manual_seed(91)))
    assert all(np.array_equal(a,b) if isinstance(a,np.ndarray) else a==b for a,b in zip(np_before,np.random.get_state()))
    assert torch.equal(torch_before,torch.random.get_rng_state())


def test_reference_object_transform_keeps_original_multiply_order():
    from robot_learning_workbench.generation.reference.data_generator import transform_source_data_segment_using_object_pose
    from robot_learning_workbench.generation.reference.math import pose_inv
    theta=torch.tensor(.3);a=torch.eye(4);a[:2,:2]=torch.stack([torch.stack([theta.cos(),-theta.sin()]),torch.stack([theta.sin(),theta.cos()])]);a[:3,3]=torch.tensor([.2,-.1,.05])
    old=torch.eye(4);old[:3,3]=torch.tensor([.12,.08,.2]);poses=torch.eye(4).repeat(4,1,1);poses[:,:3,3]=torch.tensor([.03,-.04,.25])
    result=transform_source_data_segment_using_object_pose(a,poses,old)
    torch.testing.assert_close(result,a@(pose_inv(old)@poses),rtol=0,atol=0)


def episode(length=45,grasp=12,offset=0.):
    pose=torch.eye(4).repeat(length,1,1);pose[:,0,3]=torch.arange(length)*.001
    block=torch.eye(4).repeat(length,1,1);block[:,1,3]=offset
    cup=torch.eye(4).repeat(length,1,1);cup[:,0,3]=.2
    signal=torch.zeros(length,1,dtype=torch.uint8);signal[grasp:]=1
    return {'actions':torch.zeros(length,7,dtype=torch.float64),'obs':{'datagen_info':{'eef_pose':{'tool0':pose.clone()},'target_eef_pose':{'tool0':pose.clone()},'object_pose':{'block':block,'cup':cup},'subtask_term_signals':{'grasp':signal}}}}


def test_source_pool_preserves_explicit_order_dtype_boundary_and_input_bytes():
    from robot_learning_workbench.generation.mimic import source_pool,configuration
    data=episode(grasp=12);before=copy.deepcopy(data)
    pool=source_pool([('demo_10',data),('demo_2',episode(grasp=17))],configuration('block','cup'))
    assert pool.episode_ids==('demo_10','demo_2')
    assert pool.subtask_boundaries=={'tool0':[[(0,13),(13,45)],[(0,18),(18,45)]]}
    assert pool.datagen_infos[0].gripper_action['tool0'].dtype==torch.float32
    assert torch.equal(data['actions'],before['actions']) and data['actions'].dtype==torch.float64
    assert torch.equal(data['obs']['datagen_info']['subtask_term_signals']['grasp'],before['obs']['datagen_info']['subtask_term_signals']['grasp'])
    with pytest.raises(ValueError):source_pool([('same',data),('same',data)],configuration('block','cup'))
    with pytest.raises(ValueError):source_pool([],configuration('block','cup'))


def test_invalid_annotation_is_not_shifted_or_invented_to_make_a_subtask():
    from robot_learning_workbench.generation.mimic import source_pool,configuration
    for mutation in ('missing','all_zero','starts_true','nonbinary','falling','nonfinite','missing_object'):
        data=episode();info=data['obs']['datagen_info']
        if mutation=='missing':del info['subtask_term_signals']['grasp']
        elif mutation=='all_zero':info['subtask_term_signals']['grasp'][:]=0
        elif mutation=='starts_true':info['subtask_term_signals']['grasp'][:]=1
        elif mutation=='nonbinary':info['subtask_term_signals']['grasp'][20]=2
        elif mutation=='falling':info['subtask_term_signals']['grasp'][25]=0
        elif mutation=='nonfinite':info['eef_pose']['tool0'][5,0,0]=float('nan')
        elif mutation=='missing_object':del info['object_pose']['block']
        with pytest.raises(ValueError):source_pool([('demo',data)],configuration('block','cup'))


def test_randomized_offsets_match_reference_draw_order_and_keep_final_end():
    from robot_learning_workbench.generation.mimic import source_pool,configuration,RandomStream,randomize_boundaries
    pool=source_pool([('demo_0',episode()),('demo_1',episode(grasp=14))],configuration('block','cup'))
    stream=RandomStream(892243098);out=randomize_boundaries(pool,stream=stream)['tool0']
    expected=np.array(pool.subtask_boundaries['tool0']);rng=np.random.RandomState(892243098)
    expected[:,0,0]+=rng.randint(0,1,size=2)
    expected[:,0,1]+=rng.randint(0,11,size=2);expected[:,1,0]=expected[:,0,1];expected[:,1,1]+=rng.randint(0,1,size=2)
    np.testing.assert_array_equal(out,expected)
    np.testing.assert_array_equal(stream.numpy[1],rng.get_state()[1])
    assert out[:,-1,1].tolist()==[45,45]


def test_single_arm_subtask_plan_source_selection_interpolation_and_gripper():
    from robot_learning_workbench.generation.mimic import source_pool,configuration,RandomStream,randomize_boundaries,plan_subtask
    pool=source_pool([('demo_0',episode()),('demo_1',episode(offset=.04))],configuration('block','cup'))
    stream=RandomStream(44);boundaries=randomize_boundaries(pool,stream=stream);eef=torch.eye(4);objects={'block':torch.eye(4),'cup':torch.eye(4)}
    grasp=plan_subtask(pool,0,boundaries,eef_pose=eef,object_poses=objects,stream=stream)
    assert grasp.source_index in (0,1) and grasp.source_episode==pool.episode_ids[grasp.source_index]
    assert len(grasp.waypoints)==int(np.diff(boundaries['tool0'][grasp.source_index,0])[0])+6
    before=stream.torch.clone()
    place=plan_subtask(pool,1,boundaries,eef_pose=eef,object_poses=objects,stream=stream,previous=grasp)
    assert place.source_index==grasp.source_index and torch.equal(before,stream.torch)
    assert all(w.pose.shape==(4,4) and w.gripper_action.shape==(1,) and w.noise==0. for w in place.waypoints)
    with pytest.raises(ValueError):plan_subtask(pool,1,boundaries,eef_pose=eef,object_poses=objects,stream=stream)
    with pytest.raises(ValueError):plan_subtask(pool,0,boundaries,eef_pose=eef,object_poses={'block':torch.full((4,4),float('nan'))},stream=stream)


def test_subtask_declarations_reject_unsupported_execution_and_offset_fields():
    from robot_learning_workbench.generation.mimic import Subtask,subtask_configuration
    for task in (Subtask('block',None,(0,1)),Subtask(None,None),Subtask('block',None,nn_k=0),Subtask('block',None,action_noise=.03),Subtask('block',None,first_subtask_start_offset_range=(0,5)),Subtask('block',None,selection_strategy='IK')):
        with pytest.raises(ValueError):subtask_configuration([task])


@pytest.mark.parametrize('selection',['random','nearest_neighbor_object','nearest_neighbor_robot_distance'])
def test_all_v8_selection_strategies_reuse_original_reference_and_order(selection):
    from robot_learning_workbench.generation.mimic import source_pool,Subtask,subtask_configuration,RandomStream,randomize_boundaries,plan_subtask
    tasks=[Subtask('block','grasp',(0,2),selection_strategy=selection,nn_k=2),Subtask('cup',None)]
    pool=source_pool([('demo_10',episode(offset=.3)),('demo_2',episode(offset=.02)),('demo_1',episode(offset=.06))],subtask_configuration(tasks))
    a=RandomStream(99);b=RandomStream(99);first=randomize_boundaries(pool,stream=a);second=randomize_boundaries(pool,stream=b)
    objects={'block':torch.eye(4),'cup':torch.eye(4)}
    p=plan_subtask(pool,0,first,eef_pose=torch.eye(4),object_poses=objects,stream=a)
    q=plan_subtask(pool,0,second,eef_pose=torch.eye(4),object_poses=objects,stream=b)
    assert p.source_index==q.source_index and p.source_episode==('demo_10','demo_2','demo_1')[p.source_index]
    assert torch.equal(a.torch,b.torch)
    assert all(torch.equal(x.pose,y.pose) and torch.equal(x.gripper_action,y.gripper_action) for x,y in zip(p.waypoints,q.waypoints))


def test_invalid_live_plan_ownership_and_boundaries_fail_without_extra_draw():
    from robot_learning_workbench.generation.mimic import source_pool,configuration,RandomStream,randomize_boundaries,plan_subtask
    pool=source_pool([('a',episode())],configuration('block','cup'));stream=RandomStream(10);boundaries=randomize_boundaries(pool,stream=stream)
    before=stream.torch.clone();kwargs=dict(eef_pose=torch.eye(4),object_poses={'block':torch.eye(4)},stream=stream)
    for invalid in ({'tool0':np.array([[[0,999],[999,1000]]])},{'tool0':boundaries['tool0'].astype(float)},{'wrong':boundaries['tool0']}):
        with pytest.raises(ValueError):plan_subtask(pool,0,invalid,**kwargs)
    assert torch.equal(before,stream.torch)


@pytest.mark.parametrize('bad',['bad',None,True])
def test_nonnumeric_source_arrays_fail_at_input_boundary(bad):
    from robot_learning_workbench.generation.mimic import source_pool,configuration
    data=episode();data['obs']['datagen_info']['eef_pose']['tool0']=bad
    with pytest.raises(ValueError):source_pool([('a',data)],configuration('block','cup'))


@pytest.mark.parametrize('case',['datagen_mujoco_A_valid','datagen_mujoco_B'])
def test_actual_B01_preIK_waypoints_match_without_running_IK(case):
    import h5py
    from robot_learning_workbench.generation import mimic as m
    root=Path(__file__).resolve().parents[2]/'docs/evidence/b01/runs'/case
    recipe=json.loads((root/'input-recipe.json').read_text())
    def arrays(group):return {key:arrays(value) if isinstance(value,h5py.Group) else value[()] for key,value in group.items()}
    with h5py.File(recipe['input'],'r') as source:
        # B01 explicitly selected this Episode before loading the Mimic source pool.
        source_record=source['data'][recipe['options']['episode']]
        record={'actions':source_record['actions'][()],'obs':{'datagen_info':arrays(source_record['obs/datagen_info'])}}
    pool=m.source_pool([(recipe['options']['episode'],record)],m.configuration('cube_red','cup_a'));stream=m.RandomStream(m.attempt_seed(recipe['options']['generation_seed'],1));boundaries=m.randomize_boundaries(pool,stream=stream)
    with h5py.File(root/'data/dataset.hdf5','r') as saved:
        group=saved['data/demo_0'];previous=None;eef=group['obs/datagen_info/eef_pose/tool0'][0];objects={key:value[0] for key,value in group['obs/datagen_info/object_pose'].items()}
        for index in (0,1):
            result=m.plan_subtask(pool,index,boundaries,eef_pose=eef,object_poses=objects,stream=stream,previous=previous)
            np.testing.assert_array_equal(torch.stack([w.pose for w in result.waypoints]).numpy(),group['mimic_plan'][str(index)]['target_eef_pose'][()])
            np.testing.assert_array_equal(torch.stack([w.gripper_action for w in result.waypoints]).numpy(),group['mimic_plan'][str(index)]['gripper_action'][()])
            np.testing.assert_array_equal(np.array([w.noise for w in result.waypoints]),group['mimic_plan'][str(index)]['action_noise'][()])
            assert result.source_index==0 and result.boundary==((0,225) if index==0 else (225,388));previous=result
