"""Unbound observations are Builder evidence, never fabricated model states/actions."""
import time
from types import SimpleNamespace
import numpy as np
import pytest
from real2sim_builder.project import Project
from real2sim_builder.files import read


def test_camera_only_material_capture_owns_original_rgb_without_robot_state(tmp_path):
    from robot_learning_workbench.robot.scene_observation import save_materials
    project=Project.create(tmp_path,'Camera Scene');now=time.monotonic_ns()
    packets={name:{'rgb':np.zeros((480,640,3),np.uint8),'sequence':3,'read_start':{'monotonic_ns':now-1000000,'unix_ns':time.time_ns()},'read_end':{'monotonic_ns':now,'unix_ns':time.time_ns()}}for name in('side','wrist')}
    row=save_materials(project,'shot_one',packets,None,now_ns=now)
    assert row['q_measured']==[]and row['images'].keys()=={'side','wrist'}
    record=read(row['path']+'/observation.json');assert record['model_state']is None and record['action']is None and not record['eligible_for_calibration']
    assert len(project.evidence['images'])==2 and len(project.evidence['documents'])==1
    packets['wrist']['read_end']['monotonic_ns']-=300000000
    with pytest.raises(ValueError,match='stale|skew'):save_materials(project,'shot_two',packets,None,now_ns=now)


def test_raw_sdk_observer_has_no_motor_write_or_precision_requirement(tmp_path):
    from robot_learning_workbench.robot.scene_observation import SDKObservation
    from robot_learning_workbench.robot.calibration import JOINTS
    class Bus:
        port='/fixture/port';motors={n:SimpleNamespace(id=i+1)for i,n in enumerate(JOINTS)}
        def sync_read(self,register,normalize):assert register=='Present_Position'and not normalize;return {n:2048 for n in JOINTS}
        def _normalize(self,values):return {i:0. for i in values}
    device=SimpleNamespace(bus=Bus());o=SDKObservation(device,{'role':'follower'},tmp_path/'cal.json');o.connected=True
    native,interval=o.read();assert set(native)==set(JOINTS)and o.last_raw['gripper']==2048
    assert not hasattr(o,'send')and not hasattr(o,'activate')
