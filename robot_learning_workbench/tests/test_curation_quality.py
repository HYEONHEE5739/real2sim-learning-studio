"""Idle/Jitter hints prompt review without changing outcomes or selections."""
import numpy as np
from test_native_dataset import episode,execution
from robot_learning_workbench.data.native import NativeRun,load_catalog,file_sha256
from robot_learning_workbench.ui.operations import execute


def test_catalog_marks_relative_idle_and_jitter_outliers_without_excluding(tmp_path):
    import torch
    settings=execution('source');settings['recording'].update(units='m_rad_s',pose_frame='robot_base',fps=30)
    with NativeRun(tmp_path/'source',settings)as run:
        segment=run.segment('batch')
        for i in range(6):
            ep=episode(90);times=np.arange(90)/30;q=np.tile(times[:,None]*.1,(1,6));eef=np.tile(np.eye(4),(90,1,1));eef[:,0,3]=times*.01
            if i==5:q[:,0]=np.where(np.arange(90)%2,.2,-.2);eef[:,0,3]=0
            ep.data['joint_targets']=torch.from_numpy(q);ep.data['obs']['datagen_info']={'eef_pose':{'tool0':torch.from_numpy(eef)},'object_pose':{'cube_red':torch.from_numpy(np.tile(np.eye(4),(90,1,1)))}}
            segment.write_episode(ep,episode_id='e'+str(i),metadata={'success_source':'recording_only'})
        segment.commit()
    before=file_sha256(load_catalog(run.root).episodes[0].file)
    result=execute({'operation':'catalog','arguments':{'path':str(run.root)}})
    rows=result['inspection']['episodes'];quality=rows[-1]['quality']
    assert 'EE 정지 비율 높음'in quality['flags'] and '명령 Jitter 높음'in quality['flags']
    assert quality['stop_fraction']==1 and quality['jitter']>100
    assert not rows[0]['quality']['flags']
    assert len(rows)==6 and all(row['success_source']=='recording_only'for row in rows)
    assert file_sha256(load_catalog(run.root).episodes[0].file)==before


def test_excluding_short_episodes_does_not_reclassify_unchanged_motion(tmp_path):
    import torch
    from robot_learning_workbench.data.revisions import save_revision,editor_catalog
    from robot_learning_workbench.data.quality import motion_quality
    settings=execution('source');settings['recording'].update(units='m_rad_s',pose_frame='robot_base',fps=30)
    workspace=tmp_path/'space'
    with NativeRun(workspace/'source/demo',settings)as run:
        segment=run.segment('batch')
        for index,stationary in enumerate((.7,.7,.2,.75,.75,.2,.2,.2,.2,.4),1):
            frames=5 if index in(4,5)else 90
            ep=episode(frames);distance=np.maximum(0,np.arange(frames)-round(stationary*(frames-1)))/30
            ep.data['joint_targets']=torch.from_numpy(np.tile((distance*.1)[:,None],(1,6)))
            eef=np.tile(np.eye(4),(frames,1,1));eef[:,0,3]=distance*.01
            ep.data['obs']['datagen_info']={'eef_pose':{'tool0':torch.from_numpy(eef)}}
            segment.write_episode(ep,episode_id=f'source-{index}')
        segment.commit()
    original=load_catalog(run.root);before=file_sha256(original.episodes[0].file)
    full=motion_quality(original)
    assert full['source-1']['flags']==full['source-2']['flags']==[]
    assert all('짧은 시간'in full[key]['flags']for key in('source-4','source-5'))
    revision=save_revision(workspace,original,'selected',exclude=['source-4','source-5'])['all']
    rows=editor_catalog(workspace,revision.root)['inspection']['episodes']
    assert len(rows)==8
    for row in rows:assert row['quality']==full[row['selection_id']]
    second=save_revision(workspace,revision,'selected',exclude=['source-10'])['all']
    assert motion_quality(second)['source-1']==full['source-1']
    assert file_sha256(original.episodes[0].file)==before


def test_trim_recomputes_metrics_against_the_original_quality_reference(tmp_path):
    from robot_learning_workbench.data.curation import save_curation
    from robot_learning_workbench.data.quality import motion_quality
    with NativeRun(tmp_path/'source',execution('source'))as run:
        segment=run.segment('batch')
        for i in range(5):segment.write_episode(episode(90),episode_id=f'e{i}')
        segment.commit()
    revision=save_curation(tmp_path/'trim.json',run.root,order=['e0'],frame_ranges={'e0':(0,15)})
    quality=motion_quality(revision)['e0']
    assert quality['duration']==.5
    assert '짧은 시간'in quality['flags']
    detail=next(row for row in quality['flag_details']if row['metric']=='duration')
    assert detail['group_size']==5 and detail['median']==3.
