"""Capture registration should reuse one locked Evidence read across import."""
from pathlib import Path
import sys
import copy
import numpy as np
import pytest
from test_capture_save_continuity import active_session


def test_snapshot_registration_reads_the_evidence_index_once(tmp_path,monkeypatch):
    from real2sim_builder import files
    with active_session(tmp_path,'scene_prepare')as(session,events,pending):
        session.control.stop();reads=[];read=files.read
        def counted(path,*args,**kwargs):
            if Path(path)==session.project.root/'input/evidence.yaml':reads.append(str(path))
            return read(path,*args,**kwargs)
        for name,module in list(sys.modules.items()):
            if name.startswith('real2sim_builder')and getattr(module,'read',None)is read:monkeypatch.setattr(module,'read',counted)
        result=session.store.finish(pending)
        assert result['status']=='SAVED'
        assert len(reads)==1,f'One capture needlessly parsed the same index {len(reads)} times'


def test_pair_context_is_stored_once_and_old_consumers_receive_complete_fields(tmp_path):
    from real2sim_builder.files import read,sha
    with active_session(tmp_path,'scene_prepare')as(session,events,pending):
        session.control.stop()
        rendered=dict(images={n:np.full((480,640,3),90,np.uint8)for n in('side','wrist')},
            measured_q_rad=pending['sample']['q_measured'],applied_sim_joint_rad=pending['sample']['q_measured'],
            scene_identity={'manifest_sha256':'a'*64},engine='synthetic',sim_cameras={},joint_mapping=session.store.mapping,
            sim_timestamp={'monotonic_ns':pending['sample']['timestamp_ns']},runtime_profile={'padding':'x'*80_000})
        result=session.store.finish(pending,rendered=rendered)
        index=read(session.project.root/'input/evidence.yaml')
        assert len(index['images'])==2
        assert all('runtime_baseline'not in row and row['runtime_baseline_ref']for row in index['images'])
        assert (session.project.root/'input/evidence.yaml').stat().st_size<16_000
        expanded=session.project.evidence
        for row in expanded['images']:
            baseline=row['runtime_baseline']
            assert baseline['runtime_profile']==rendered['runtime_profile']
            assert baseline['joint_mapping']==session.store.mapping
            assert baseline['scene_identity']==rendered['scene_identity']
            assert baseline['sha256']==sha(session.project.root/baseline['path'])
        before=copy.deepcopy(index)
        session.project.write_evidence(expanded)
        assert read(session.project.root/'input/evidence.yaml')==before
        pair=Path(result['path'])/'pair.json';pair.write_text('{}')
        with pytest.raises(ValueError,match='hash mismatch'):session.project.evidence


def test_legacy_inline_evidence_is_not_migrated_by_new_writes(tmp_path):
    from real2sim_builder.project import Project
    from real2sim_builder.files import write,read
    project=Project.create(tmp_path,'legacy')
    legacy={'images':[{'id':'legacy','runtime_baseline':{'runtime_profile':{'any':'original'},'custom':'retained'}}]}
    write(project.root/'input/evidence.yaml',legacy)
    assert project.evidence==legacy
    project.write_evidence(project.evidence)
    assert read(project.root/'input/evidence.yaml')==legacy


def test_safe_yaml_parser_retains_aliases_scalars_and_rejects_python_objects(tmp_path):
    from real2sim_builder.files import read,write
    path=tmp_path/'index.yaml'
    path.write_text("base: &b {flag: true, text: 'yes', count: 3, empty: null}\nother: *b\n")
    value=read(path);assert value['base']=={'flag':True,'text':'yes','count':3,'empty':None}
    write(path,value);assert read(path)==value
    path.write_text('!!python/object/apply:os.system ["echo prohibited"]')
    with pytest.raises(Exception):read(path)


def test_new_evidence_writes_use_the_existing_json_fastpath_and_keep_legacy_types(tmp_path,monkeypatch):
    import datetime
    from real2sim_builder.project import Project
    from real2sim_builder import files
    project=Project.create(tmp_path,'index')
    expected={'images':[],'note':'원본 텍스트·단위 보존','nested':{'empty':None,'boolean':True}}
    project.write_evidence(expected)
    with monkeypatch.context()as scoped:
        scoped.setattr(files.yaml,'load',lambda *a,**k:pytest.fail('Growing Capture index still needs YAML parsing'))
        assert project.read_evidence(resolve=False)==expected
    legacy={**expected,'legacy_date':datetime.date(2026,1,2)}
    project.write_evidence(legacy)
    assert project.read_evidence(resolve=False)==legacy


def test_sealed_raw_capture_can_be_recovered_after_its_session_owner_closed(tmp_path):
    from robot_learning_workbench.robot.snapshots import SnapshotStore
    from real2sim_builder.files import sha
    from real2sim_builder.capture import load_session
    with active_session(tmp_path,'scene_prepare')as(session,events,pending):
        root=Path(pending['staging']);before={str(p.relative_to(root)):sha(p)for p in root.rglob('*')if p.is_file()}
        project=session.project;q=pending['sample']['q_measured']
    result=SnapshotStore.recover(project,root)
    final=Path(result['path'])
    assert result['status']=='SAVED'and result['paired']is False
    assert before=={str(p.relative_to(final)):sha(p)for p in final.rglob('*')if p.is_file()}
    assert load_session(final)[1][0]['q_measured']==q
    assert SnapshotStore.recover(project,final)['registration']['status']=='ALREADY_REGISTERED'


def test_frozen_render_paths_are_decoded_only_by_the_save_consumer(tmp_path,monkeypatch):
    import time
    from PIL import Image
    from real2sim_builder.files import write,sha
    from robot_learning_workbench.robot.render_transport import RenderProcess
    with active_session(tmp_path,'real_sim')as(session,events,pending):
        session.control.stop()
        transport=RenderProcess.__new__(RenderProcess);transport.root=tmp_path/'render';transport.root.mkdir()
        files={}
        for camera in('side','wrist'):
            path=transport.root/(camera+'.png');Image.fromarray(np.full((480,640,3),90,np.uint8)).save(path)
            files[camera]=dict(path=str(path),sha256=sha(path))
        write(transport.root/'capture-result.json',dict(id=pending['id'],files=files,requested_ns=time.monotonic_ns(),
            measured_q_rad=pending['sample']['q_measured'],applied_sim_joint_rad=pending['sample']['q_measured'],
            scene_identity={'manifest_sha256':'a'*64},engine='synthetic',sim_cameras={},
            sim_timestamp={'monotonic_ns':pending['sample']['timestamp_ns']}))
        with monkeypatch.context()as scoped:
            scoped.setattr(Image,'open',lambda *a,**k:pytest.fail('Frozen PNG decoded in the serial-control interpreter'))
            rendered=transport._read('capture-result.json',decode=False)
        assert rendered['images']=={} and rendered['files']==files
        result=session.store.finish(pending,rendered=rendered)
        assert result['paired']is True
        for camera,source in files.items():
            assert sha(Path(result['images']['sim_'+camera]))==source['sha256']
