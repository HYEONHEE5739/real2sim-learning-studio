"""Iterator scheduling contracts; real vector physics is a separate app probe."""
import numpy as np


def test_vector_tick_preserves_pending_pre_rows_while_one_env_restarts(monkeypatch):
    from robot_learning_workbench.engines.isaac import mdp
    from types import SimpleNamespace as NS
    import torch
    env=NS(num_envs=2,cfg=NS(workbench_joint_order=['q'+str(i) for i in range(6)]),scene={'robot':NS(joint_names=['q'+str(i) for i in range(6)],data=NS(joint_pos_target=torch.zeros(2,6)))})
    steps=[];resumed=[]
    monkeypatch.setattr(mdp,'apply_joint_targets',lambda e,q:steps.append(q.copy()))
    def one(i,length):
        for t in range(length):yield np.full(6,10*i+t);resumed.append((i,t))
        return 'done-'+str(i)
    streams={0:one(0,1),1:one(1,3)};ready={}
    assert mdp.advance_streams(env,streams,ready)==({},True)
    done,stepped=mdp.advance_streams(env,streams,ready);assert done=={0:'done-0'} and not stepped
    assert resumed==[(0,0),(1,0)] and len(steps)==1
    streams[0]=one(2,1)
    assert mdp.advance_streams(env,streams,ready)==({},True)
    np.testing.assert_array_equal(steps[-1][:,0],[20,11])
    assert resumed==[(0,0),(1,0)]


def test_global_pause_preserves_prepared_rows_until_real_vector_step(monkeypatch):
    from robot_learning_workbench.engines.isaac import mdp
    from types import SimpleNamespace as NS
    import torch
    env=NS(num_envs=2,cfg=NS(workbench_joint_order=['q'+str(i) for i in range(6)]),scene={'robot':NS(joint_names=['q'+str(i) for i in range(6)],data=NS(joint_pos_target=torch.zeros(2,6)))})
    applied=[];monkeypatch.setattr(mdp,'apply_joint_targets',lambda e,t:applied.append(t.copy()))
    def steps():yield np.ones(6);raise AssertionError('Cannot resume post logic without physics')
    streams={0:steps(),1:steps()};ready={}
    assert mdp.advance_streams(env,streams,ready,pause_check=lambda:True)==({},False)
    assert len(ready)==2 and not applied
    assert mdp.advance_streams(env,streams,ready,pause_check=lambda:False)==({},True)
    assert len(applied)==1 and not ready
