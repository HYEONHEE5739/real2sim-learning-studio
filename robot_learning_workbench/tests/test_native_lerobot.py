"""Pinned official Dataset/Factory consumers and unchanged original MP4."""
from pathlib import Path
import json
import numpy as np
import pytest
from test_native_dataset import episode,execution
from robot_learning_workbench.data import native as n,curation as c,lerobot as l


def test_exact_train_val_and_frame_range_through_official_factory(tmp_path):
    with n.NativeRun(tmp_path/'source',execution()) as run:
        seg=run.segment('source')
        for i in range(6):seg.write_episode(episode(5),episode_id=f'e{i}')
        seg.commit()
    view=c.save_curation(tmp_path/'view.json',n.load_catalog(run.root),order=['e4','e2','e5'],frame_ranges={'e4':(1,4)},splits={'train':['e4','e2'],'val':['e5']})
    train=l.materialize(view,tmp_path/'train',split='train');val=l.materialize(view,tmp_path/'val',split='val')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    a=LeRobotDataset('workbench/native',root=train,video_backend='pyav');b=LeRobotDataset('workbench/native',root=val,video_backend='pyav')
    assert len(a)==8 and len(b)==5 and a.num_episodes==2 and b.num_episodes==1
    assert set(a.hf_dataset.unique('source.episode_id'))=={'e4','e2'} and set(b.hf_dataset.unique('source.episode_id'))=={'e5'}
    raw=a.hf_dataset.with_format(None)[:]
    assert raw['source.frame_index']==[1,2,3,0,1,2,3,4]
    assert raw['source.timestamp']==pytest.approx([1/30,2/30,3/30,0,1/30,2/30,3/30,4/30])
    from lerobot.datasets.factory import make_dataset
    from lerobot.datasets.transforms import ImageTransformsConfig
    from types import SimpleNamespace as NS
    cfg=NS(dataset=NS(repo_id='workbench/native',root=train,revision=None,episodes=None,streaming=False,image_transforms=ImageTransformsConfig(enable=False),video_backend='pyav',use_imagenet_stats=False),policy=NS(reward_delta_indices=None,action_delta_indices=None,observation_delta_indices=None))
    official=make_dataset(cfg)
    from torch.utils.data import DataLoader
    actual=[]
    for batch in DataLoader(official,batch_size=3,shuffle=False,num_workers=0):actual.extend(batch['source.episode_id'])
    assert actual==['e4']*3+['e2']*5


def test_original_video_is_linked_and_clip_offsets_decode_exactly(tmp_path):
    samples=json.loads((Path(__file__).resolve().parents[2]/'docs/evidence/b02/samples.json').read_text())
    source=n.import_hdf5(samples['historical_source']['path'],tmp_path/'source',stage='source',groups=['demo_0'])
    view=c.save_curation(tmp_path/'clip.json',source,frame_ranges={'demo_0':(10,18)})
    output=l.materialize(view,tmp_path/'training')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    ds=LeRobotDataset('workbench/native',root=output,video_backend='pyav')
    assert len(ds)==8 and len(ds.meta.video_keys)==2
    import av
    for camera,info in source.episodes[0].media.items():
        key='observation.images.'+camera;video_path=output/ds.meta.get_video_file_path(0,key)
        assert video_path.stat().st_ino==Path(info['path']).stat().st_ino
        assert n.file_sha256(video_path)==n.file_sha256(info['path'])
        frames=[]
        with av.open(info['path']) as container:
            for i,frame in enumerate(container.decode(video=0)):
                if 10<=i<18:frames.append(frame.to_ndarray(format='rgb24'))
                if i>=18:break
        for i in (0,3,7):
            actual=(ds[i][key].permute(1,2,0).numpy()*255).round().astype(np.uint8)
            np.testing.assert_array_equal(actual,frames[i])

    # Re-edit an already materialized official video Dataset, retaining offsets.
    official_view=c.save_curation(tmp_path/'second-clip.json',n.load_catalog(output),frame_ranges={'demo_0':(1,4)})
    second=l.materialize(official_view,tmp_path/'second-training')
    data=LeRobotDataset('workbench/native',root=second,video_backend='pyav')
    assert len(data)==3 and data.hf_dataset.with_format(None)[:]['source.frame_index']==[11,12,13]
    for camera,info in source.episodes[0].media.items():
        key='observation.images.'+camera
        with av.open(info['path']) as container:
            expected=next(frame.to_ndarray(format='rgb24') for i,frame in enumerate(container.decode(video=0)) if i==11)
        actual=(data[0][key].permute(1,2,0).numpy()*255).round().astype(np.uint8)
        np.testing.assert_array_equal(actual,expected)


def test_official_dataset_can_be_curated_and_rematerialized_without_sdk_selection(tmp_path):
    with n.NativeRun(tmp_path/'source',execution()) as run:
        seg=run.segment('initial')
        for i in range(4):seg.write_episode(episode(5),episode_id=f'e{i}')
        seg.commit()
    first=l.materialize(run.root,tmp_path/'first')
    official=n.load_catalog(first)
    view=c.save_curation(tmp_path/'curated.json',official,order=['e3','e1'],frame_ranges={'e3':(1,4)})
    output=l.materialize(view,tmp_path/'second')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    data=LeRobotDataset('workbench/native',root=output,video_backend='pyav')
    assert len(data)==8 and list(data.hf_dataset.unique('source.episode_id'))==['e3','e1']
    assert data.hf_dataset.with_format(None)[:]['source.frame_index']==[1,2,3,0,1,2,3,4]


def test_failed_official_parquet_write_never_publishes_and_does_not_change_prior(tmp_path,monkeypatch):
    with n.NativeRun(tmp_path/'source',execution()) as run:
        seg=run.segment('first');seg.write_episode(episode(),episode_id='e');seg.commit()
    first=l.materialize(run.root,tmp_path/'good');before={p:n.file_sha256(p) for p in first.rglob('*') if p.is_file()}
    import pyarrow.parquet as pq
    def fail(*args,**kwargs):raise OSError('disk full')
    with monkeypatch.context() as patch:
        patch.setattr(pq,'ParquetWriter',fail)
        with pytest.raises(OSError):l.materialize(run.root,tmp_path/'broken')
    assert not (tmp_path/'broken').exists()
    assert before=={p:n.file_sha256(p) for p in first.rglob('*') if p.is_file()}
    with pytest.raises(n.DataError):l.materialize(run.root,tmp_path/'broken')


def test_materialization_refuses_writing_inside_original_native_dataset(tmp_path):
    with n.NativeRun(tmp_path/'source',execution()) as run:
        s=run.segment('one');s.write_episode(episode(),episode_id='first');s.commit()
    before=set(run.root.rglob('*'))
    with pytest.raises(n.DataError):l.materialize(run.root,run.root/'training')
    assert before==set(run.root.rglob('*'))


def test_no_video_dataset_uses_recorded_clock_instead_of_assuming_30hz(tmp_path):
    import torch
    cfg=execution();cfg['recording']['fps']=50
    with n.NativeRun(tmp_path/'source',cfg) as run:
        s=run.segment('one');e=episode(4);e.data['obs']['timestamp']=torch.arange(4,dtype=torch.float64).reshape(-1,1)/50;s.write_episode(e,episode_id='e');s.commit()
    out=l.materialize(run.root,tmp_path/'training')
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    d=LeRobotDataset('workbench/native',root=out,video_backend='pyav')
    assert d.meta.fps==50
    assert d.hf_dataset.with_format(None)[:]['timestamp']==pytest.approx([0,.02,.04,.06])

@pytest.mark.parametrize('fps',[0,-1,True])
def test_invalid_recorded_fps_is_rejected_before_official_creation(tmp_path,fps):
    cfg=execution();cfg['recording']['fps']=fps
    with n.NativeRun(tmp_path/'source',cfg) as run:
        s=run.segment('one');s.write_episode(episode());s.commit()
    with pytest.raises(n.DataError):l.materialize(run.root,tmp_path/'invalid')
    assert not (tmp_path/'invalid.staging').exists()
