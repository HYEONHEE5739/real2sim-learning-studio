"""C02 independent and official export reuse; exact video/frame review."""
import numpy as np
from pathlib import Path
import pytest
from test_native_dataset import episode,execution
from robot_learning_workbench.data import native as n,curation as c

@pytest.fixture
def video_source(tmp_path):
    from robot_learning_workbench.data.video import AsyncVideoWriter
    video=tmp_path/'camera.mp4';writer=AsyncVideoWriter(video,width=64,height=48)
    for i in range(6):writer.write(np.full((48,64,3),i*30,np.uint8))
    writer.close()
    with n.NativeRun(tmp_path/'source',execution()) as run:
        segment=run.segment('one');segment.write_episode(episode(6),episode_id='e0',media={'side':video});segment.commit()
    return n.load_catalog(run.root)


def test_selected_video_review_uses_absolute_frame_without_previous_fallback(video_source,tmp_path):
    view=c.save_curation(tmp_path/'view.json',video_source,frame_ranges={'e0':(2,5)})
    item=c.review_frame(view,'e0',0,cameras=('side',))
    assert item['original_frame']==2 and item['selection_frame']==0
    assert abs(item['rgb']['side'].mean()-60)<3 and item['video_pts_s']['side']==pytest.approx(2/30)
    np.testing.assert_array_equal(item['values']['joint_targets'],n.read_array(view.episodes[0],'joint_targets')[0])
    with pytest.raises(n.DataError):c.review_frame(view,'e0',3)
    with pytest.raises(n.DataError):c.review_frame(view,'e0',0,cameras=('missing',))


def test_rgb_statistics_state_sampling_scope(video_source,tmp_path):
    view=c.save_curation(tmp_path/'view.json',video_source,frame_ranges={'e0':(2,5)})
    stats=c.rgb_statistics(view,'side',stride=1)
    assert stats['decoded_frames']==3 and stats['scope']['frames']==3
    assert len(stats['mean_rgb_0_255'])==3 and abs(stats['mean_rgb_0_255'][0]-90)<3
    assert stats['sampled'] is False and stats['unit']=='uint8_rgb_0_255'


def test_revision_lineage_reload_and_independent_export_are_unchanged(video_source,tmp_path):
    v1=c.save_curation(tmp_path/'v1.json',video_source)
    v2=c.save_curation(tmp_path/'v2.json',n.load_catalog(v1.root))
    before=n.file_sha256(video_source.episodes[0].file)
    archive=c.export_native(v2,tmp_path/'archive')
    assert archive.execution['archive_only'] is True
    assert archive.episodes[0].file.stat().st_ino!=video_source.episodes[0].file.stat().st_ino
    assert Path(archive.episodes[0].media['side']['path']).stat().st_ino!=Path(video_source.episodes[0].media['side']['path']).stat().st_ino
    np.testing.assert_array_equal(n.read_array(archive.episodes[0],'joint_targets'),n.read_array(video_source.episodes[0],'joint_targets'))
    assert n.file_sha256(video_source.episodes[0].file)==before
    history=c.revision_history(v2)
    assert [r['kind'] for r in history]==['curated','curated','native']
    assert history[0]['identity']==__import__('dataclasses').asdict(v2.identity)


def test_rgb_stride_counts_actual_decoded_and_used_frames_separately(video_source):
    stats=c.rgb_statistics(video_source,'side',stride=2)
    assert stats['decoded_frames']==6 and stats['sampled_frames']==3


def test_recipe_worker_convert_reuses_materialize_and_official_consumer(tmp_path):
    import yaml
    from test_lerobot_dataset import source
    from robot_learning_workbench.recipe import read_recipe,prepare_recipe
    from robot_learning_workbench.run import _run_stage
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    src=source(tmp_path);path=tmp_path/'convert.yaml'
    path.write_text(yaml.safe_dump(dict(schema_version=1,stage='convert',inputs={'dataset':str(src.root)},execution={'task_instruction':'pick red cube'},output={'directory':str(tmp_path/'official')})))
    result=_run_stage(prepare_recipe(read_recipe(path)),events=lambda _:None,commands=lambda:())
    assert result.status=='completed'
    d=LeRobotDataset('workbench/native',root=tmp_path/'official',video_backend='pyav')
    assert len(d)==6 and tuple(d[0]['action'].shape)==(6,)
