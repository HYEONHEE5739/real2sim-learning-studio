"""Read-only Curation outcomes/statistics and explicit selected scope."""
import numpy as np
import pytest
from test_native_dataset import episode,execution
from robot_learning_workbench.data import native as n,curation as c

@pytest.fixture
def source(tmp_path):
    import torch
    cfg=execution('simulation_evaluation');cfg['recording'].update(units='m_rad_s',pose_frame='robot_base')
    with n.NativeRun(tmp_path/'source',cfg) as run:
        for i in range(2):
            seg=run.segment('ep'+str(i));claim=run.claim_attempt(seg);ep=episode(6)
            ep.data['joint_targets']=torch.arange(i*36,(i+1)*36,dtype=torch.float64).reshape(6,6)
            ep.data['obs']['policy']['joint_pos']=ep.data['joint_targets']*.5
            ep.data['obs']['events']={'grasp':torch.tensor([[0],[0],[1],[1],[1],[1]],dtype=torch.uint8)}
            ep.success=bool(i);seg.write_episode(ep,episode_id='e'+str(i),metadata={'category':'max_steps' if not i else 'placement_success','source_lineage':{'id':'original'}})
            seg.record_attempt(claim,status='success' if i else 'failure',episode_id='e'+str(i));seg.commit()
        seg=run.segment('cancel');claim=run.claim_attempt(seg);seg.record_attempt(claim,status='cancelled');seg.commit()
    return n.load_catalog(run.root)


def test_review_keeps_completed_failure_and_attempt_scope(source,tmp_path):
    view=c.save_curation(tmp_path/'v1.json',source,order=['e0'],frame_ranges={'e0':(2,5)})
    review=c.inspect_dataset(view)
    assert review['selected_frames']==3 and len(review['episodes'])==1
    assert review['episodes'][0]['recorded_success'] is False
    assert review['episodes'][0]['selection_range']==[2,5]
    assert len(review['source_attempts'])==3 and review['attempt_scope']=='original_native_run'
    assert c.filter_episodes(source,recorded_success=False)==('e0',)
    assert c.filter_episodes(source,category='placement_success')==('e1',)


def test_distribution_matches_selected_half_open_rows_not_whole_episode(source,tmp_path):
    view=c.save_curation(tmp_path/'view.json',source,frame_ranges={'e0':(1,4),'e1':(2,6)},splits={'train':['e0'],'val':['e1']})
    result=c.distribution(view,fields=('joint_targets','obs/events/grasp'),split='train',chunk_frames=2,bins=4)
    actual=n.read_array(view.episodes[0],'joint_targets')
    stats=result['fields']['joint_targets']
    assert result['scope']['split']=='train' and result['scope']['frames']==3
    np.testing.assert_allclose(stats['mean'],actual.mean(0),rtol=0,atol=0)
    np.testing.assert_allclose(stats['std'],actual.std(0),rtol=1e-14,atol=0)
    assert stats['source_dtypes']==['float64'] and stats['unit']=='rad'
    assert np.asarray(stats['histogram_counts']).sum(1).tolist()==[3]*6
    assert result['fields']['obs/events/grasp']['phase']=='pre_step'
    assert result['fields']['obs/events/grasp']['mean']==[2/3]


def test_missing_nonfinite_or_wrong_field_is_explicit(source,tmp_path):
    with pytest.raises(n.DataError):c.distribution(source,fields=('missing',))
    with pytest.raises(n.DataError):c.distribution(source,fields=('joint_targets',),chunk_frames=0)
    with pytest.raises(n.DataError):c.distribution(source,fields=('joint_targets',),bins=True)


def test_comparison_uses_shared_histogram_edges_and_contract(source,tmp_path):
    one=c.save_curation(tmp_path/'one.json',source,order=['e0']);two=c.save_curation(tmp_path/'two.json',source,order=['e1'])
    result=c.compare_distributions([one,two],fields=('joint_targets',),bins=5)
    a,b=result['datasets']
    assert a['fields']['joint_targets']['histogram_edges']==b['fields']['joint_targets']['histogram_edges']
    assert a['fields']['joint_targets']['mean']!=b['fields']['joint_targets']['mean']


def test_saved_revision_rejects_unknown_split_and_empty_or_malformed_rows(source,tmp_path):
    import json
    view=c.save_curation(tmp_path/'v.json',source)
    doc=n.read_json(view.root)
    for key,value in [('splits',{'typo':['e0']}),('selections',[]),('source',{'path':3})]:
        broken={**doc,key:value};path=tmp_path/(key+'.json');path.write_text(json.dumps(broken))
        with pytest.raises(n.DataError):c.load_curation(path)


def test_split_algorithm_preserves_original_order_and_global_rng(source):
    before=np.random.get_state();result=c.split_dataset(source,train_fraction=.5,seed=7)
    expected=np.random.default_rng(7).choice(['e0','e1'],1,replace=False).tolist()
    assert result['splits']['train']==expected
    assert result['splits']['val']==[id_ for id_ in ['e0','e1'] if id_ not in expected]
    np.testing.assert_array_equal(before[1],np.random.get_state()[1])


def test_position_distribution_uses_reference_scene_frame_and_selected_start(source,tmp_path):
    import h5py
    from types import SimpleNamespace
    for ep in source.episodes:
        with h5py.File(ep.file,'r+') as f:
            matrices=np.repeat(np.eye(4)[None],6,axis=0);matrices[:,0,3]=np.arange(6)
            f['data/'+ep.key].create_dataset('obs/datagen_info/object_pose/cube',data=matrices)
    # Explicit synthetic frame fixture, independent of live/dynamic engine state.
    scene=SimpleNamespace(scene={'frames':{'world':{'parent':None,'T_parent_from_frame':np.eye(4).tolist(),'state':'reference'},'robot_base':{'parent':'world','T_parent_from_frame':np.eye(4).tolist(),'state':'reference'},'workspace':{'parent':'world','T_parent_from_frame':np.array([[0.,-1,0,10],[1,0,0,0],[0,0,1,0],[0,0,0,1]]).tolist(),'state':'reference'}}},identity=__import__('scene_contract.package',fromlist=['SceneIdentity']).SceneIdentity(**source.execution['scene_identity']))
    view=c.save_curation(tmp_path/'view.json',n.load_catalog(source.root),order=['e0'],frame_ranges={'e0':(2,5)})
    result=c.position_distribution(view,'cube',scene=scene,frame='workspace')
    assert result['frame']=='workspace' and result['unit']=='m'
    np.testing.assert_array_equal(result['points'][0]['xyz_m'],[0,8,0])
    assert result['points'][0]['original_frame']==2


def test_unknown_units_do_not_enable_cross_dataset_comparison(source,tmp_path):
    from dataclasses import replace
    cfg={**source.execution,'recording':{**source.execution['recording'],'units':'unknown'}}
    with n.NativeRun(tmp_path/'unknown',cfg) as run:
        seg=run.segment('one');seg.write_episode(episode(6),episode_id='e0');seg.commit()
    unknown=n.load_catalog(run.root)
    with pytest.raises(n.DataError):c.compare_distributions([unknown,unknown],fields=('joint_targets',))


def test_split_seed_and_rule_survive_revision_reload(source,tmp_path):
    generated=c.split_dataset(source,seed=17,train_fraction=.5)
    v1=c.save_curation(tmp_path/'v1.json',source,splits=generated['splits'],split_provenance=generated)
    loaded=n.load_catalog(v1.root)
    assert loaded.metadata['split_provenance']['seed']==17
    assert loaded.metadata['split_provenance']['rule']==generated['rule']
    v2=c.save_curation(tmp_path/'v2.json',loaded)
    assert v2.metadata['split_provenance']==loaded.metadata['split_provenance']


def test_unknown_velocity_units_are_not_labelled_rad_s(source,tmp_path):
    import torch
    cfg={**source.execution,'recording':{**source.execution['recording'],'units':'degree'}}
    with n.NativeRun(tmp_path/'unknown',cfg) as run:
        seg=run.segment('a');ep=episode(3);ep.data['states']={'joint_vel':torch.zeros((3,6))};seg.write_episode(ep,episode_id='a');seg.commit()
    unknown=n.load_catalog(run.root)
    assert c.distribution(unknown,fields=('states/joint_vel',))['fields']['states/joint_vel']['unit']=='unknown'
    with pytest.raises(n.DataError):c.compare_distributions([unknown,unknown],fields=('states/joint_vel',))


def test_malformed_json_root_is_structured_error(tmp_path):
    p=tmp_path/'bad.json';p.write_text('[]')
    with pytest.raises(n.DataError):c.load_curation(p)


@pytest.mark.parametrize('bad',[{'fields':[[]]},{'fields':'joint_targets'},{'fields':[3]}])
def test_invalid_field_inputs_return_structured_error(source,bad):
    with pytest.raises(n.DataError):c.distribution(source,**bad)


def test_invalid_assignments_return_structured_error(source):
    with pytest.raises(n.DataError):c.split_dataset(source,assignments={'e0':[],'e1':'val'})


def test_identity_checked_relocation_is_usable_and_new_revision_persists_it(source,tmp_path):
    view=c.save_curation(tmp_path/'v1.json',source)
    moved=tmp_path/'moved';source.root.rename(moved)
    loaded=c.load_curation(view.root,relocations={str(source.root):str(moved)})
    assert c.inspect_dataset(loaded)['selected_frames']==12
    assert c.distribution(loaded)['scope']['frames']==12
    next_view=c.save_curation(tmp_path/'v2.json',loaded,order=['e1'])
    assert c.inspect_dataset(n.load_catalog(next_view.root))['selected_frames']==6
    assert c.revision_history(next_view)[-1]['path']==str(moved)


def test_curated_merged_official_statistics_keep_known_policy_units(tmp_path):
    from test_lerobot_dataset import source as create
    from robot_learning_workbench.data import lerobot
    one=create(tmp_path,'one');two=create(tmp_path,'two')
    merged=lerobot.merge([one,two],tmp_path/'merged',task='Pick red cube')
    view=c.save_curation(tmp_path/'view.json',merged)
    stats=c.distribution(view)
    assert stats['fields']['action']['unit']=='rad'
    assert stats['fields']['action']['joint_order']==one.execution['recording']['joint_order']


def test_force_statistics_preserve_matrix_component_shape(source):
    import h5py
    for ep in source.episodes:
        with h5py.File(ep.file,'r+') as file:file['data/'+ep.key].create_dataset('states/contact_force_w',data=np.ones((6,2,3),dtype=np.float32))
    stats=c.distribution(n.load_catalog(source.root),fields=('states/contact_force_w',))['fields']['states/contact_force_w']
    assert stats['component_shape']==[2,3] and stats['unit']=='N' and stats['joint_order'] is None
    assert stats['mean']==[1.]*6
