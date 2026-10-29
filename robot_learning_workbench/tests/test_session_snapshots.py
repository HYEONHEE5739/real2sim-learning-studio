import json
from pathlib import Path
import numpy as np
import pytest
from real2sim_builder.project import Project
from real2sim_builder.capture import load_session,import_session
from robot_learning_workbench.robot.capture import save_session
from robot_learning_workbench.robot.calibration import JOINTS


def snapshot(root,model):
    save_session(root,model=model,mapping={'joint_order':list(JOINTS),'description':'controlled mapping fixture'},
        samples=[{'id':'sample1','timestamp_ns':100,'q_measured':[0.]*6,'command_applied':False}],
        images=[{n:np.full((480,640,3),17,np.uint8)for n in('side','wrist')}],metadata={'session_identity':'session1'})


def test_scene_free_capture_registers_without_inventing_camera_or_base(tmp_path):
    project=Project.create(tmp_path/'projects','New capture');model=tmp_path/'robot.urdf'
    model.write_text('<robot>'+''.join('<joint name="'+n+'" type="revolute"/>'for n in JOINTS)+'</robot>')
    source=tmp_path/'snapshot';snapshot(source,model);before=(source/'capture_manifest.yaml').read_bytes()
    result=import_session(project,source)
    assert result['status']=='NEEDS_MORE_DATA'and result['imported']==2 and result['eligible']==0
    assert len(project.evidence['images'])==2 and len(project.evidence['capture_sessions'])==1
    assert all(not row['eligible']and 'unbound_capture_calibration'in row['exclusion_reasons']for row in project.evidence['images'])
    assert not(project.root/'working/current_scene.yaml').exists()
    assert (source/'capture_manifest.yaml').read_bytes()==before
    with pytest.raises(ValueError,match='already imported'):import_session(project,source)


def test_project_owned_capture_registers_in_place_without_second_bulk_copy(tmp_path):
    project=Project.create(tmp_path/'projects','In place');model=tmp_path/'robot.urdf';model.write_text('<robot>'+''.join('<joint name="'+n+'" type="revolute"/>'for n in JOINTS)+'</robot>')
    source=project.root/'input/captures/snapshot';source.parent.mkdir();snapshot(source,model)
    image=source/'images/00000000-side.png';before=image.stat().st_ino
    result=import_session(project,source);assert result['imported']==2 and image.stat().st_ino==before
    assert len(list(project.root.rglob('*side.png')))==1
    with pytest.raises(ValueError,match='already imported'):import_session(project,source)


def test_failed_registration_restores_project_and_keeps_owned_measurements(tmp_path,monkeypatch):
    from real2sim_builder import capture
    project=Project.create(tmp_path/'projects','Rollback');model=tmp_path/'robot.urdf';model.write_text('<robot>'+''.join('<joint name="'+n+'" type="revolute"/>'for n in JOINTS)+'</robot>')
    source=project.root/'input/captures/snapshot';source.parent.mkdir();snapshot(source,model)
    before=(project.root/'input/evidence.yaml').read_bytes();write=capture.write
    def fail(path,data):
        if Path(path).name=='capture_import.json':raise OSError('injected commit failure')
        return write(path,data)
    monkeypatch.setattr(capture,'write',fail)
    with pytest.raises(OSError):import_session(project,source)
    assert (project.root/'input/evidence.yaml').read_bytes()==before
    assert load_session(source)[1][0]['q_measured']==[0.]*6


def test_snapshot_store_repeats_without_reopening_devices_or_duplication(tmp_path):
    from test_robot_lifecycle import make
    from test_precision_calibration import CURRENT
    from robot_learning_workbench.robot.snapshots import SnapshotStore
    from robot_learning_workbench.robot.capture import snapshot_state
    f,_,trace=make(tmp_path);f.connect()
    try:
        native,interval=f.read();t=interval['end']['monotonic_ns'];history=[{'timestamp_ns':t-(6-i)*100_000_000,'native':native,'raw':dict(f.last_raw),'feedback_interval':interval}for i in range(7)]
        packets={n:{'read_start':{'monotonic_ns':t-2_000_000},'read_end':{'monotonic_ns':t-1_000_000},'sequence':1}for n in('side','wrist')}
        state=snapshot_state(f,history,packets,{'stable':True,'window_start_ns':t-600_000_000,'window_end_ns':t})
        project=Project.create(tmp_path/'projects','Repeated');store=SnapshotStore(project,session_id='session1',model=CURRENT,mapping=f.precision_mapper.metadata())
        rgb={n:np.full((480,640,3),31,np.uint8)for n in('real_side','real_wrist')}
        a=store.prepare('capture1',state,rgb,now_ns=t);one=store.finish(a)
        packets={n:{**p,'sequence':2}for n,p in packets.items()};state=snapshot_state(f,history,packets,state['real_stability'])
        b=store.prepare('capture2',state,rgb,now_ns=t);two=store.finish(b)
        assert len(project.evidence['capture_sessions'])==2 and len(project.evidence['images'])==4
        assert trace.count('connect')==1 and not one['calibration_approved']and not two['calibration_approved']
        for root in(one['path'],two['path']):
            m,rows,_=load_session(root);assert rows[0]['q_measured']==state['physical_q_measured']
            assert m['command_source']=='measured_observation_no_training_action'
        assert store.finish(b)['id']==two['id']
        with pytest.raises(ValueError,match='reused'):store.prepare('capture3',state,rgb,now_ns=t)
    finally:f.close()
