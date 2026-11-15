"""Motion hints use explicit Task identity, with no Dataset row/outcome edits."""
import numpy as np
import pytest
from test_native_dataset import execution,episode
from robot_learning_workbench.data import native as n
from robot_learning_workbench.data.quality import motion_quality


@pytest.mark.parametrize('order',[['distractor','target'],['target','distractor']])
def test_lift_and_movement_follow_explicit_target_independent_of_active_order(tmp_path,order):
    import torch
    config=execution('source');config.update(active_objects=order,task_objects=['target']);config['recording'].update(units='m_rad_s',pose_frame='robot_base',fps=30)
    with n.NativeRun(tmp_path/'data',config)as owner:
        ep=episode(4);fixed=np.tile(np.eye(4),(4,1,1));moving=fixed.copy();moving[:,2,3]=[0,.1,.2,.2]
        ep.data['obs']['datagen_info']={'object_pose':{'distractor':torch.from_numpy(fixed),'target':torch.from_numpy(moving)}}
        segment=owner.segment('one');segment.write_episode(ep,episode_id='one');segment.commit()
    before={p:n.file_sha256(p)for p in owner.root.rglob('*')if p.is_file()}
    quality=motion_quality(n.load_catalog(owner.root))['one']
    assert quality['lift_height_m']==pytest.approx(.2)and quality['target_movement_m']==pytest.approx(.2)
    assert quality['target_object_id']=='target'and quality['target_metric_status']=='AVAILABLE'
    assert set(quality['initial_objects'])=={'target'}
    assert before=={p:n.file_sha256(p)for p in owner.root.rglob('*')if p.is_file()}


@pytest.mark.parametrize('targets,status',[([], 'NO_TASK_OBJECT'),(['one','two'],'MULTIPLE_TASK_OBJECTS'),(['missing'],'NOT_RECORDED')])
def test_unavailable_task_target_is_explicit_without_inventing_scalar_motion(tmp_path,targets,status):
    import torch
    config=execution('source');config.update(active_objects=['one','two'],task_objects=targets);config['recording'].update(units='m_rad_s',pose_frame='robot_base',fps=30)
    with n.NativeRun(tmp_path/'data',config)as owner:
        ep=episode();poses=np.tile(np.eye(4),(3,1,1));ep.data['obs']['datagen_info']={'object_pose':{'one':torch.from_numpy(poses),'two':torch.from_numpy(poses)}}
        segment=owner.segment('one');segment.write_episode(ep,episode_id='one');segment.commit()
    quality=motion_quality(n.load_catalog(owner.root))['one']
    assert quality['target_movement_m']is None and quality['lift_height_m']is None
    assert quality['target_metric_status']==status


def test_legacy_single_object_keeps_its_previous_motion_hint(tmp_path):
    import torch
    config=execution('source');config['recording'].update(units='m_rad_s',pose_frame='robot_base',fps=30)
    with n.NativeRun(tmp_path/'data',config)as owner:
        ep=episode();poses=np.tile(np.eye(4),(3,1,1));poses[:,2,3]=[0,.05,.1]
        ep.data['obs']['datagen_info']={'object_pose':{'cube_red':torch.from_numpy(poses)}}
        segment=owner.segment('one');segment.write_episode(ep,episode_id='one');segment.commit()
    assert motion_quality(n.load_catalog(owner.root))['one']['lift_height_m']==pytest.approx(.1)
