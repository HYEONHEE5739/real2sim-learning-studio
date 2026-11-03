"""Source has no user/placeholder Seed; placement owns fresh entropy."""
import copy
import numpy as np
import pytest
from test_placement import scene,params,request
from test_native_dataset import execution,episode
from robot_learning_workbench.tasks import placement
from robot_learning_workbench.data import native


def test_random_xy_creates_a_new_unseeded_generator_per_call(scene,monkeypatch):
    generators=[np.random.default_rng(7),np.random.default_rng(8)];calls=[]
    def fresh(*args,**kwargs):
        calls.append((args,kwargs));return generators[len(calls)-1]
    monkeypatch.setattr(placement.np.random,'default_rng',fresh)
    first=placement.random_xy(request(),params=params(scene));second=placement.random_xy(request(),params=params(scene))
    assert calls==[((),{}),((),{})]
    assert not np.array_equal(first.pose,second.pose)
    with pytest.raises(placement.TaskError):placement.random_xy(request(rng=generators[0]),params=params(scene))


@pytest.mark.parametrize('stage',['source','annotation'])
def test_source_and_annotation_claims_do_not_fabricate_seed_and_source_can_resume(tmp_path,stage):
    cfg=copy.deepcopy(execution(stage));cfg.pop('seed');cfg['rng_policy']='entropy_placement_per_call_v1';cfg['task_code']={'placement.py':'b'*64}
    with native.NativeRun(tmp_path/'data',cfg)as run:
        seg=run.segment('one');claim=run.claim_attempt(seg);assert 'seed'not in claim
        ep=episode();ep.seed=None;seg.write_episode(ep,episode_id='one');seg.record_attempt(claim,status='success',episode_id='one');seg.commit()
    record=native.load_catalog(run.root).episodes[0];reader=native.open_native(record)
    try:assert reader.load_episode(record.key,'cpu').seed is None
    finally:reader.close()
    if stage=='source':
        with native.NativeRun(run.root,cfg,append=True)as resumed:
            claim=resumed.claim_attempt(resumed.segment('two'));assert claim['attempt']==2 and 'seed'not in claim


def test_source_recipe_requires_no_seed_and_rejects_the_retired_field(tmp_path):
    from test_recipe import source_yaml,save
    from robot_learning_workbench.recipe import read_recipe,RecipeError
    doc=read_recipe(save(tmp_path,source_yaml()))
    assert 'seed'not in doc.spec.execution
    with pytest.raises(RecipeError):read_recipe(save(tmp_path,source_yaml().replace('episodes: 2','episodes: 2, seed: 1047')))


def test_seedless_source_converts_without_inventing_episode_seed(tmp_path):
    from robot_learning_workbench.robot.calibration import JOINTS
    from robot_learning_workbench.data.lerobot import materialize
    from robot_learning_workbench.data.curation import inspect_dataset
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    cfg=copy.deepcopy(execution('source'));cfg.pop('seed')
    cfg.update(single_task='Pick the red cube.',calibration={'records':{}},urdf_sha256='d'*64)
    cfg['recording'].update(joint_order=list(JOINTS),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',task_phase='post_step',fps=30)
    with native.NativeRun(tmp_path/'source',cfg)as run:
        segment=run.segment('one');claim=run.claim_attempt(segment);ep=episode(4);ep.seed=None
        segment.write_episode(ep,episode_id='one');segment.record_attempt(claim,status='success',episode_id='one');segment.commit()
    assert inspect_dataset(run.root)['episodes'][0]['seed']is None
    root=materialize(run.root,tmp_path/'official');dataset=LeRobotDataset('workbench/native',root=root,video_backend='pyav')
    assert dataset.num_episodes==1 and len(dataset)==4 and dataset[0]['task']=='Pick the red cube.'
