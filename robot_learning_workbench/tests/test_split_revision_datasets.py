"""Split saves are independent Dataset inputs, published as one versioned group."""
from pathlib import Path
import json
import pytest
from test_curation_revisions import dataset
from robot_learning_workbench.data import native,curation,revisions


def test_split_saves_only_each_role_and_preserves_trim_original_and_input_contract(tmp_path):
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo')
    before={p:native.file_sha256(p)for p in source.root.rglob('*')if p.is_file()}
    saved=revisions.save_revision(workspace,source,'selected',exclude=['e1'],frame_ranges={'e0':(1,4)},splits={'train':['e0'],'val':['e2']})
    assert set(saved)=={'train','val'}
    for role,id_,interval in [('train','e0',(1,4)),('val','e2',(0,6))]:
        catalog=native.load_catalog(saved[role].root)
        assert saved[role].root==workspace/f'curation/source/demo/selected_r001/{role}.json'
        assert [(ep.episode_id,ep.start,ep.stop)for ep in catalog.episodes]==[(id_,*interval)]
        assert catalog.splits=={role:[id_]}
        assert revisions.editor_catalog(workspace,catalog)['inspection']['episodes'][0]['episode_id']==id_
        assert revisions.editor_state(catalog)['original'].root==source.root
    assert len(revisions.list_revisions(workspace,source))==2
    assert before=={p:native.file_sha256(p)for p in source.root.rglob('*')if p.is_file()}


def test_mixed_assigned_and_blank_split_is_not_silently_dropped(tmp_path):
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo')
    with pytest.raises(native.DataError,match='Split'):
        revisions.save_revision(workspace,source,'selected',splits={'train':['e0'],'val':['e1']})
    assert not revisions.list_revisions(workspace,source)


def test_failed_second_split_never_publishes_the_first(tmp_path,monkeypatch):
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo');write=curation.save_curation
    def fail(path,*args,**kwargs):
        if Path(path).name=='val.json':raise OSError('controlled full disk')
        return write(path,*args,**kwargs)
    monkeypatch.setattr(curation,'save_curation',fail)
    with pytest.raises(OSError,match='controlled full disk'):
        revisions.save_revision(workspace,source,'selected',splits={'train':['e0','e1'],'val':['e2']})
    assert not revisions.list_revisions(workspace,source)
    folder=workspace/'curation/source/demo'
    assert not list(folder.glob('.pending-*')) and not(folder/'selected_r001').exists()


def test_split_child_does_not_depend_on_previous_revision_and_keeps_one_role(tmp_path):
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo')
    saved=revisions.save_revision(workspace,source,'selected',splits={'train':['e0','e1'],'val':['e2']})
    child=revisions.save_revision(workspace,saved['train'],'selected',exclude=['e1'])
    assert set(child)=={'train'} and child['train'].root.parent.name=='selected_r002'
    parent_id=saved['train'].identity.dataset_id
    for catalog in saved.values():catalog.root.unlink()
    reloaded=native.load_catalog(child['train'].root)
    assert [ep.episode_id for ep in reloaded.episodes]==['e0']
    assert json.loads(child['train'].root.read_text())['revision']['parent_id']==parent_id
    with pytest.raises(native.DataError):revisions.save_revision(workspace,reloaded,'bad',order=['e2'])


def test_concurrent_split_saves_publish_distinct_complete_versions(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo')
    def save(_):return revisions.save_revision(workspace,source,'selected',splits={'train':['e0','e1'],'val':['e2']})
    with ThreadPoolExecutor(max_workers=3)as pool:groups=list(pool.map(save,range(3)))
    assert {saved['train'].root.parent.name for saved in groups}=={'selected_r001','selected_r002','selected_r003'}
    assert all(len(saved['train'].episodes)==2 and len(saved['val'].episodes)==1 for saved in groups)


def test_legacy_combined_revision_remains_readable_and_resaves_as_two_files(tmp_path):
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo')
    old_path=workspace/'curation/source/demo/selected_r001.json'
    old=curation.save_curation(old_path,source,splits={'train':['e0','e1'],'val':['e2']},revision={'name':'selected','number':1})
    before=native.file_sha256(old_path)
    saved=revisions.save_revision(workspace,old,'selected')
    assert all(catalog.root.parent.name=='selected_r002'for catalog in saved.values())
    assert [len(saved[role].episodes)for role in('train','val')]==[2,1]
    assert native.file_sha256(old_path)==before and len(native.load_catalog(old_path).episodes)==3
