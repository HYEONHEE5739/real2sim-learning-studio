"""No serial devices: approved command lifecycle over the existing SDK arithmetic double."""
import copy,time
import numpy as np
import pytest
from test_robot_lifecycle import make
from robot_learning_workbench.robot.calibration import JOINTS,raw_from_native


def devices(tmp_path):
    leader,ls,lt=make(tmp_path,'leader');follower,fs,ft=make(tmp_path,'follower')
    leader.read_only=True;follower.read_only=True;leader.connect();follower.connect()
    q=follower.precision_mapper.calibrated_to_urdf(follower.read()[0])
    native=leader.precision_mapper.urdf_to_calibrated(q)
    ls.bus.present={n:round(raw_from_native(native[n],leader.motor_specs[n]))for n in JOINTS}
    registers={'Torque_Enable':dict.fromkeys(JOINTS,0),'Operating_Mode':dict.fromkeys(JOINTS,0)}
    read=fs.bus.sync_read;write=fs.bus.sync_write
    fs.bus.sync_read=lambda name,**kw:dict(registers[name])if name in registers else read(name,**kw)
    def update(name,packet,**kw):
        if name in registers:ft.append('write_'+name);registers[name].update(packet)
        else:write(name,packet,**kw)
    fs.bus.sync_write=update
    return leader,follower,lt,ft,registers


def approval(proposal):
    return {'proposal_sha256':proposal['sha256'],**dict.fromkeys(('supervised','clear','stop_ready','direction_checked','ranges_checked','preserve_torque'),True)}


def controller(tmp_path):
    from robot_learning_workbench.robot.supervised import Teleoperation
    l,f,lt,ft,registers=devices(tmp_path)
    control=Teleoperation(l,f,model_bounds={n:e['limits']for n,e in f.profile['joints'].items()},session_id='session',max_step_rad=.1,max_follow_error_rad=.5)
    return control,l,f,lt,ft,registers


def test_observing_does_not_grant_command_rights_and_approval_is_one_use(tmp_path):
    c,l,f,lt,ft,_=controller(tmp_path)
    try:
        with pytest.raises(Exception,match='approved'):c.tick()
        p=c.propose();assert not any(t.startswith('write_')or t=='send'for t in ft)
        bad=approval(p);bad['supervised']=False
        with pytest.raises(Exception,match='approval'):c.start(bad)
        assert not any(t.startswith('write_')for t in ft)
        c.start(approval(p));assert c.active and f.read_only
        with pytest.raises(Exception,match='consumed|active'):c.start(approval(p))
        assert ft.count('write_Torque_Enable')==1 and 'configure'not in ft
        row=c.tick();assert len(row['measured_model_rad'])==6 and len(row['applied_model_rad'])==6
        before=len(ft);c.stop();f.close();assert 'send'not in ft[before:]and 'disable'not in ft
    finally:l.close();f.close()


@pytest.mark.parametrize('fault',['goal','mode','stale_approval','heartbeat','send'])
def test_unsafe_start_stale_session_or_unknown_send_blocks_further_commands(tmp_path,fault):
    c,l,f,lt,ft,registers=controller(tmp_path)
    try:
        if fault=='goal':
            f.bus.goal['wrist_flex']+=20
            with pytest.raises(Exception,match='Goal'):c.propose()
        elif fault=='mode':
            registers['Operating_Mode']['gripper']=1
            with pytest.raises(Exception,match='mode'):c.propose()
        else:
            p=c.propose()
            if fault=='stale_approval':
                c.proposal['expires_ns']=0
                with pytest.raises(Exception,match='expired'):c.start(approval(p))
            else:
                c.start(approval(p))
                if fault=='heartbeat':c.last_heartbeat_ns=0
                else:f.bus.fault='send'
                with pytest.raises(Exception):c.tick()
                assert not c.active
                sends=ft.count('send')
                with pytest.raises(Exception):c.tick()
                assert ft.count('send')==sends
    finally:l.close();f.close()


def test_changed_identity_or_mapping_cannot_reuse_approval(tmp_path):
    c,l,f,_,ft,_=controller(tmp_path)
    try:
        p=c.propose();f.profile['identity']['id']='changed'
        with pytest.raises(Exception):c.start(approval(p))
        assert not any(x.startswith('write_')for x in ft)
    finally:l.close();f.close()
