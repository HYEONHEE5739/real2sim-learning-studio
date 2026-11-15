"""Partial official writers stay diagnostic artifacts, not published Datasets."""
from pathlib import Path
import shutil
import pytest
from test_lerobot_dataset import source
from robot_learning_workbench.data import native as n,lerobot as l,curation as c


def test_failure_after_one_official_episode_is_not_discoverable_or_directly_readable(tmp_path,monkeypatch):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset,LeRobotDatasetMetadata
    cat=source(tmp_path,'source');base=tmp_path/'workspace/dataset';base.mkdir(parents=True)
    good=l.materialize(cat,base/'good',task='pick cube');before={p:n.file_sha256(p)for p in good.rglob('*')if p.is_file()}
    save=LeRobotDatasetMetadata.save_episode;write=LeRobotDataset._save_episode_data;count=0;during=[]
    def observed(self,*args,**kwargs):
        result=save(self,*args,**kwargs);during.extend(c.discover_datasets(base.parent));return result
    def failed(self,*args,**kwargs):
        nonlocal count
        count+=1
        if count==2:raise OSError('second Episode disk failure')
        return write(self,*args,**kwargs)
    monkeypatch.setattr(LeRobotDatasetMetadata,'save_episode',observed);monkeypatch.setattr(LeRobotDataset,'_save_episode_data',failed)
    with pytest.raises(OSError,match='second Episode'):l.materialize(cat,base/'failed',task='pick cube')
    pending=base/'failed.staging';assert pending.is_dir()and not(base/'failed').exists()
    evidence={p:n.file_sha256(p)for p in pending.rglob('*')if p.is_file()}
    assert all(Path(row['path'])!=pending for row in during)
    assert all(Path(row['path'])!=pending for row in c.discover_datasets(base.parent))
    with pytest.raises(n.DataError):n.load_catalog(pending)
    with pytest.raises(n.DataError):l.lerobot_catalog(pending)
    assert evidence=={p:n.file_sha256(p)for p in pending.rglob('*')if p.is_file()}
    assert before=={p:n.file_sha256(p)for p in good.rglob('*')if p.is_file()}


def test_failed_final_rename_cannot_be_read_even_after_writers_are_closed(tmp_path,monkeypatch):
    cat=source(tmp_path);output=tmp_path/'workspace/dataset/final';output.parent.mkdir(parents=True)
    rename=l.os.rename
    def failed(a,b):
        if Path(b)==output:raise OSError('publish rename denied')
        return rename(a,b)
    monkeypatch.setattr(l.os,'rename',failed)
    with pytest.raises(OSError,match='publish rename denied'):l.materialize(cat,output,task='pick cube')
    pending=output.with_name('final.staging')
    assert not output.exists()and pending.is_dir()
    with pytest.raises(n.DataError):n.load_catalog(pending)
    assert c.discover_datasets(tmp_path/'workspace')==[]
    renamed=output.parent/'renamed-failure';shutil.copytree(pending,renamed)
    with pytest.raises(n.DataError):n.load_catalog(renamed)


def test_published_and_external_legacy_official_datasets_remain_readable(tmp_path):
    cat=source(tmp_path);base=tmp_path/'workspace/dataset';base.mkdir(parents=True)
    good=l.materialize(cat,base/'good',task='pick cube')
    legacy=base/'external';shutil.copytree(good,legacy)
    (legacy/'workbench-publication.json').unlink(missing_ok=True)
    assert len(n.load_catalog(good).episodes)==2 and len(n.load_catalog(legacy).episodes)==2
    assert {row['name']for row in c.discover_datasets(base.parent)if row['readable']}=={'good','external'}


def test_failed_publication_intent_write_closes_official_dataset(tmp_path,monkeypatch):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    close=LeRobotDataset.finalize;closed=[];atomic=l.atomic_json
    def tracked(self):closed.append(self.root);return close(self)
    def fail(path,*args,**kwargs):
        if Path(path).name=='workbench-publication.json':raise OSError('intent write failed')
        return atomic(path,*args,**kwargs)
    monkeypatch.setattr(LeRobotDataset,'finalize',tracked);monkeypatch.setattr(l,'atomic_json',fail)
    with pytest.raises(OSError,match='intent write failed'):
        l.create_staging(tmp_path/'out',features={'action':{'dtype':'float32','shape':(6,),'names':None}},fps=30)
    assert tmp_path/'out.staging'in closed
    assert not(tmp_path/'out').exists()and(tmp_path/'out.staging').is_dir()
