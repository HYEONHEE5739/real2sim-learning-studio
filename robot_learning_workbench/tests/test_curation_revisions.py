"""Managed revisions own only selection JSON; original payload stays immutable."""
from pathlib import Path
import json
import pytest
from test_native_dataset import episode,execution
from robot_learning_workbench.data import native,curation


def dataset(root,stage='source'):
    with native.NativeRun(root,execution(stage))as owner:
        segment=owner.segment('one')
        for i in range(3):segment.write_episode(episode(6),episode_id='e'+str(i))
        segment.commit()
    return native.load_catalog(root)


def test_managed_versions_use_original_root_and_allow_excluded_episode_back(tmp_path):
    from robot_learning_workbench.data.revisions import save_revision,editor_state,list_revisions
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo1')
    before={p:native.file_sha256(p)for p in source.root.rglob('*')if p.is_file()}
    first=save_revision(workspace,source.root,'기본선별',exclude=['e1'],frame_ranges={'e0':(1,4)})['all']
    assert first.root==workspace/'curation/source/demo1/기본선별_r001.json'
    state=editor_state(first.root)
    assert len(state['original'].episodes)==3 and len(state['selection'].episodes)==2
    assert state['original'].root==source.root
    assert state['name']=='기본선별' and state['number']==1
    second=save_revision(workspace,source.root,state['name'],parent=first.root,exclude=['e2'],frame_ranges={'e0':(0,6)})['all']
    assert second.root.name=='기본선별_r002.json'
    document=json.loads(second.root.read_text())
    assert (second.root.parent/document['source']['path']).resolve()==source.root
    assert document['revision']['parent_id']==first.identity.dataset_id
    assert [r['number']for r in list_revisions(workspace,source.root)]==[2,1]
    first.root.unlink()  # The next revision never needs the previous JSON to read data.
    reopened=native.load_catalog(second.root)
    assert [ep.episode_id for ep in reopened.episodes]==['e0','e1']
    assert reopened.episodes[0].start==0 and reopened.episodes[0].stop==6
    assert before=={p:native.file_sha256(p)for p in source.root.rglob('*')if p.is_file()}


@pytest.mark.parametrize('stage',['source','annotation','datagen','lerobot'])
def test_revisions_are_grouped_by_original_dataset_kind(tmp_path,stage):
    from robot_learning_workbench.data.revisions import save_revision
    workspace=tmp_path/'space'
    source=dataset(workspace/(stage if stage!='lerobot'else'source')/'demo1',stage if stage!='lerobot'else'source')
    if stage=='lerobot':
        from robot_learning_workbench.data.lerobot import materialize
        source=native.load_catalog(materialize(source,workspace/'dataset/official'))
    revision=save_revision(workspace,source.root,'clean')['all']
    assert revision.root.parent==workspace/'curation'/stage/source.root.name
    assert native.load_catalog(revision.root).kind=='curated'


def test_same_named_external_datasets_do_not_mix_revision_lists(tmp_path):
    from robot_learning_workbench.data.revisions import save_revision,list_revisions
    workspace=tmp_path/'space';one=dataset(tmp_path/'a/demo');two=dataset(tmp_path/'b/demo')
    first=save_revision(workspace,one.root,'clean')['all'];second=save_revision(workspace,two.root,'clean')['all']
    assert first.root.parent!=second.root.parent
    assert [r['path']for r in list_revisions(workspace,one.root)]==[str(first.root)]
    assert [r['path']for r in list_revisions(workspace,two.root)]==[str(second.root)]
    for bad in ('','..','../escape','a/b','a\\b'):
        with pytest.raises(ValueError):save_revision(workspace,one.root,bad)['all']


def test_concurrent_saves_never_overwrite_a_version(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from robot_learning_workbench.data.revisions import save_revision
    workspace=tmp_path/'space';source=dataset(workspace/'datagen/demo','datagen')
    with ThreadPoolExecutor(max_workers=3)as pool:
        paths=list(pool.map(lambda _:save_revision(workspace,source.root,'clean')['all'].root,range(3)))
    assert sorted(p.name for p in paths)==['clean_r001.json','clean_r002.json','clean_r003.json']
    assert all(len(native.load_catalog(p).episodes)==3 for p in paths)


def test_editor_opens_only_the_selected_dataset(tmp_path):
    from robot_learning_workbench.data.revisions import save_revision,editor_catalog
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo')
    revision=save_revision(workspace,source.root,'clean',exclude=['e1'],frame_ranges={'e0':(1,4)})['all']
    result=editor_catalog(workspace,revision.root)
    assert result['original_path']==str(source.root) and result['path']==str(revision.root)
    rows=result['inspection']['episodes']
    assert [row['episode_id']for row in rows]==['e0','e2']
    assert rows[0]['selection_range']==rows[0]['edit_range']==[1,4]
    assert all(row['included']for row in rows)
    assert result['original']['episodes']==3 and result['original']['frames']==18
    assert len(result['revisions'])==1 and result['revision']['name']=='clean'


def test_ten_to_eight_to_seven_is_a_subset_dataset_without_payload_changes(tmp_path):
    from robot_learning_workbench.data.revisions import save_revision,editor_catalog
    workspace=tmp_path/'space';root=workspace/'source/demo'
    with native.NativeRun(root,execution('source'))as owner:
        segment=owner.segment('one')
        for i in range(1,11):segment.write_episode(episode(6),episode_id=f'source-{i}')
        segment.commit()
    before={p:native.file_sha256(p)for p in root.rglob('*')if p.is_file()}
    first=save_revision(workspace,root,'selected',exclude=['source-4','source-5'])['all']
    assert len(editor_catalog(workspace,first.root)['inspection']['episodes'])==8
    second=save_revision(workspace,first.root,'selected',exclude=['source-8'])['all']
    ids=[ep.episode_id for ep in native.load_catalog(second.root).episodes]
    assert ids==['source-1','source-2','source-3','source-6','source-7','source-9','source-10']
    assert len(editor_catalog(workspace,second.root)['inspection']['episodes'])==7
    doc=json.loads(second.root.read_text())
    assert(second.root.parent/doc['source']['path']).resolve()==root
    assert doc['revision']['parent_id']==first.identity.dataset_id
    assert 'excluded'not in doc['revision']
    assert len(editor_catalog(workspace,root)['inspection']['episodes'])==10
    with pytest.raises(native.DataError):save_revision(workspace,first.root,'invalid',order=['source-4'])['all']
    first.root.unlink()
    assert len(native.load_catalog(second.root).episodes)==7
    assert before=={p:native.file_sha256(p)for p in root.rglob('*')if p.is_file()}


def test_child_revision_preserves_parent_trim_and_splits_and_cannot_expand_them(tmp_path):
    from robot_learning_workbench.data.revisions import save_revision
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo')
    first=save_revision(workspace,source.root,'clean',exclude=['e1'],frame_ranges={'e0':(1,4)},splits={'train':['e0','e2']})['train']
    second=save_revision(workspace,first.root,'clean',exclude=['e2'])['train']
    assert [(e.episode_id,e.start,e.stop)for e in second.episodes]==[('e0',1,4)]
    assert second.splits=={'train':['e0']}
    with pytest.raises(native.DataError):save_revision(workspace,first.root,'invalid',frame_ranges={'e0':(0,6)})['all']


def test_broken_revision_is_visible_and_changed_original_is_not_silently_rebound(tmp_path):
    from dataclasses import asdict
    from robot_learning_workbench.data.revisions import save_revision,list_revisions,editor_state
    workspace=tmp_path/'space';source=dataset(workspace/'source/demo')
    revision=save_revision(workspace,source.root,'clean')['all'];broken=revision.root.with_name('broken.json');broken.write_text('[]')
    entries=list_revisions(workspace,source.root)
    assert len(entries)==2 and next(r for r in entries if r['path']==str(broken))['readable']is False
    doc=json.loads((source.root/'run.json').read_text());doc['test_changed_original']=True;(source.root/'run.json').write_text(json.dumps(doc))
    entries=list_revisions(workspace,source.root)
    assert next(r for r in entries if r['path']==str(revision.root))['readable']is False
    with pytest.raises(native.DataError):editor_state(revision.root)
    with pytest.raises(native.DataError):save_revision(workspace,source.root,'clean',expected_original=asdict(source.identity))['all']
    assert not revision.root.with_name('clean_r002.json').exists()
