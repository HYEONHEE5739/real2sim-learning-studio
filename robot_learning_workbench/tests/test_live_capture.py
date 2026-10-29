import json
from pathlib import Path
import numpy as np
import pytest
from test_precision_calibration import bound,CURRENT,OLD
from robot_learning_workbench.robot import capture


def test_capture_writer_reuses_builder_reader_and_preserves_model_and_measurements(tmp_path):
    _,mapper=bound('follower')
    from robot_learning_workbench.robot.calibration import JOINTS
    samples=[{'id':'sample1','timestamp_ns':100,'q_measured':[0.]*6,'images':[],'joint_skew_ns':0,'command_applied':False}]
    images={'side':np.zeros((480,640,3),np.uint8),'wrist':np.full((480,640,3),17,np.uint8)}
    source=tmp_path/'source';source.mkdir();model=source/'robot.urdf'
    # A fixture with exact six-joint unit declarations, no external mesh deps.
    model.write_text('<robot name="fixture">'+''.join('<joint name="'+n+'" type="revolute"/>'for n in JOINTS)+'</robot>')
    mapping={'joint_order':list(JOINTS),'description':'controlled fixture; no robot approval'}
    output=tmp_path/'capture'
    capture.save_session(output,model=model,mapping=mapping,samples=samples,images=[images],metadata={'hardware_connected':False})
    from real2sim_builder.capture import load_session
    m,rows,_=load_session(output)
    assert rows[0]['q_measured']==[0.]*6 and rows[0]['command_applied'] is False
    assert len(rows[0]['images'])==2 and m['clock']['hardware_synchronized'] is False
    assert model.read_bytes()==(output/m['robot']['path']).read_bytes()
    assert samples[0]['images']==[]
    with pytest.raises(FileExistsError):capture.save_session(output,model=model,mapping=mapping,samples=samples,images=[images],metadata={})


def test_capture_rejects_metadata_that_relabels_measured_data(tmp_path):
    from robot_learning_workbench.robot.calibration import JOINTS
    model=tmp_path/'robot.urdf';model.write_text('<robot>'+''.join('<joint name="'+n+'" type="revolute"/>'for n in JOINTS)+'</robot>')
    with pytest.raises(ValueError,match='reserved'):
        capture.save_session(tmp_path/'bad',model=model,mapping={},samples=[{'id':'s','timestamp_ns':1,'q_measured':[0.]*6}],images=[{n:np.zeros((480,640,3),np.uint8)for n in ('side','wrist')}],metadata={'q_measured_source':'policy_prediction'})


def test_capture_completion_is_not_public_during_reader_validation(tmp_path,monkeypatch):
    from real2sim_builder import capture as reader
    from robot_learning_workbench.robot.calibration import JOINTS
    model=tmp_path/'robot.urdf';model.write_text('<robot>'+''.join('<joint name="'+n+'" type="revolute"/>'for n in JOINTS)+'</robot>')
    output=tmp_path/'capture';load=reader.load_session
    def validate(staging):
        assert not (output/'COMPLETE').exists()
        return load(staging)
    monkeypatch.setattr(reader,'load_session',validate)
    capture.save_session(output,model=model,mapping={},samples=[{'id':'s','timestamp_ns':1,'q_measured':[0.]*6}],images=[{n:np.zeros((480,640,3),np.uint8)for n in ('side','wrist')}],metadata={})
    assert (output/'COMPLETE').is_file() and not (output/'.pending').exists()
