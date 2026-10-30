"""Leader teleoperation must survive the UI → Recipe → Worker boundary.

Only saved configuration and command envelopes are exercised here. No serial
connection, camera acquisition, Goal or Torque call is permitted by these tests.
"""
import copy,json
from pathlib import Path

import yaml

from robot_learning_workbench.recipe import prepare_recipe,read_recipe
from robot_learning_workbench.robot.registration import bind_configuration,save_configuration
from robot_learning_workbench.ui.session_operations import real_sim_setup
from test_real_sim_observation import observation_recipe

R=Path(__file__).resolve().parents[2]


def configured_scene(tmp_path):
    path,project,data=observation_recipe(tmp_path)
    config=yaml.safe_load((R/'workbench_runs/devices/so101-pickplace-0b794e7c/capture.yaml').read_text())
    config['execution'].update(device_source='memory')
    stored=save_configuration(tmp_path,'Reviewed Leader and Follower',config)
    bind_configuration(project.root,stored,tmp_path)
    return path,project,data,config


def test_real_sim_setup_preserves_reviewed_leader_mapping(tmp_path):
    _,project,data,config=configured_scene(tmp_path)
    result=real_sim_setup(tmp_path,project.root,data['inputs']['scene'],'mujoco')['recipe']
    for name in('leader_device_profile','leader_calibration_profile'):
        assert result['inputs'].get(name)==config['inputs'][name],f'Real/Sim discarded {name}; Leader cannot drive Follower'
    assert result['execution']==config['execution'],'Real/Sim discarded the explicitly reviewed motion limits'
    assert 'candidate'not in result['inputs']


def test_paired_recipe_prepares_leader_without_connecting_devices(tmp_path):
    path,project,data,config=configured_scene(tmp_path)
    for name in('leader_device_profile','leader_calibration_profile'):data['inputs'][name]=config['inputs'][name]
    data['execution']=copy.deepcopy(config['execution']);path.write_text(yaml.safe_dump(data))
    plan=prepare_recipe(read_recipe(path))
    assert plan.resolved_inputs['leader_device_profile']['files']
    assert plan.resolved_inputs['leader_calibration_profile']['files']
    assert plan.effective_settings['execution']=={'device_source':'memory'}


def test_paired_worker_accepts_current_session_teleoperation_commands(tmp_path,monkeypatch):
    import robot_learning_workbench.run as run
    root=tmp_path/'paired-worker';(root/'commands').mkdir(parents=True)
    commands=[{'command_id':'proposal','kind':'teleop_prepare','payload':{}},
              {'command_id':'start','kind':'teleop_start','payload':{'proposal_sha256':'a'*64,**dict.fromkeys(('supervised','clear','stop_ready','direction_checked','ranges_checked','preserve_torque','initialize_goal'),True)}},
              {'command_id':'stop','kind':'teleop_stop','payload':{}}]
    for index,command in enumerate(commands,1):
        (root/'commands'/(command['command_id']+'.json')).write_text(json.dumps({'protocol_version':1,'run_id':root.name,'seq':index,'payload':command}))
    acknowledgements=[]
    monkeypatch.setattr(run,'_ack',lambda root,state,cid,status,**kwargs:acknowledgements.append((cid,status)))
    actual=run._poll_commands(root,{'seen_commands':set(),'command_seq':0,'context':{}},'paired_session')
    assert list(actual)==commands,'The paired Worker discarded Leader teleoperation commands before execution'
    assert acknowledgements==[(command['command_id'],'accepted')for command in commands]


def memory_controller(tmp_path,monkeypatch):
    from test_supervised_session import controller
    import robot_learning_workbench.robot.devices as devices
    serial_lease=devices.serial_lease
    monkeypatch.setattr(devices,'serial_lease',lambda port:serial_lease(str(tmp_path/('memory-'+Path(port).name))))
    return controller(tmp_path)


def test_unpowered_stale_goal_can_be_reviewed_without_any_motion_or_torque_write(tmp_path,monkeypatch):
    c,leader,follower,_,trace,registers=memory_controller(tmp_path,monkeypatch)
    try:
        follower.bus.goal['wrist_flex']+=20
        assert not any(registers['Torque_Enable'].values())
        proposal=c.propose()
        state=proposal['state']
        assert state['goal']['wrist_flex']!=state['raw']['wrist_flex']
        assert not c.active and not any(item.startswith('write_')or item=='send'for item in trace)
    finally:leader.close();follower.close()


def test_single_encoder_count_jitter_keeps_explicit_approval_usable(tmp_path,monkeypatch):
    from test_supervised_session import approval
    c,leader,follower,_,trace,_=memory_controller(tmp_path,monkeypatch)
    try:
        proposal=c.propose()
        follower.bus.present['shoulder_pan']+=1
        c.start(approval(proposal))
        assert c.active
        assert 'send'not in trace,'Starting must not issue an unrequested Leader target'
    finally:c.stop();leader.close();follower.close()


def test_powered_stale_goal_is_still_rejected_before_approval_or_motion(tmp_path,monkeypatch):
    import pytest
    c,leader,follower,_,trace,registers=memory_controller(tmp_path,monkeypatch)
    try:
        follower.bus.goal['wrist_flex']+=20
        registers['Torque_Enable']['wrist_flex']=1
        with pytest.raises(Exception,match='Goal|goal'):c.propose()
        assert not c.active and not any(item.startswith('write_')or item=='send'for item in trace)
    finally:leader.close();follower.close()


def test_approved_leader_motion_reaches_follower_and_native_sim_then_four_image_capture(tmp_path):
    import time,numpy as np
    from robot_learning_workbench.robot.real_sim import RealSimSession
    from robot_learning_workbench.robot.session_devices import construct
    from robot_learning_workbench.robot.calibration import JOINTS,raw_from_native
    from test_supervised_session import approval
    path,project,data,config=configured_scene(tmp_path)
    for name in('leader_device_profile','leader_calibration_profile'):data['inputs'][name]=config['inputs'][name]
    data['execution']=copy.deepcopy(config['execution']);path.write_text(yaml.safe_dump(data));plan=prepare_recipe(read_recipe(path));devices,cameras,bounds=construct(plan);plan.output_path.mkdir();events=[]
    s=RealSimSession(plan,devices,cameras,events=events.append)
    def until(predicate):
        deadline=time.monotonic()+20
        while not predicate():
            s.observe();time.sleep(.02)
            assert time.monotonic()<deadline,(s.state,events[-2:])
    try:
        s.connect();until(lambda:s.state=='OBSERVING')
        assert not s.teleoperation.active
        s.dispatch([{'kind':'teleop_prepare','command_id':'proposal','payload':{}}]);p=s.teleoperation.proposal;assert p
        s.dispatch([{'kind':'teleop_start','command_id':'start','payload':approval(p)}]);assert s.teleoperation.active
        q=dict(zip(JOINTS,s.history[-1]['q_measured']));q['shoulder_pan']+=.03
        leader=devices['leader'];native=leader.precision_mapper.urdf_to_calibrated(q)
        changed={n:round(raw_from_native(native[n],leader.motor_specs[n]))for n in JOINTS};read=leader.bus.sync_read
        leader.bus.sync_read=lambda name,**kwargs:dict(changed)if name=='Present_Position'else read(name,**kwargs)
        until(lambda:abs(s.renderer.last_live['measured_q_rad'][0]-q['shoulder_pan'])<.005)
        assert abs(s.history[-1]['q_measured'][0]-q['shoulder_pan'])<.005
        s.dispatch([{'kind':'session_snapshot','command_id':'pair','payload':{}}]);until(lambda:len(s.snapshots)==1)
        assert set(s.snapshots[0]['images'])=={'side','wrist','sim_side','sim_wrist'}
        shot=next((Path(s.snapshots[0]['path'])/'shots').iterdir());pair=json.loads((shot/'pair.json').read_text());state=json.loads((shot/'state.json').read_text())
        np.testing.assert_array_equal(pair['measured_q_rad'],state['q_measured']);assert pair['physics_steps']==0
        s.dispatch([{'kind':'teleop_start','command_id':'late','payload':approval(p)},{'kind':'cancel','command_id':'stop','payload':{}}]);assert s.terminal and not s.teleoperation.active
    finally:s.close()


def test_approved_unpowered_start_initializes_goal_before_torque_and_records_attempt(tmp_path,monkeypatch):
    from test_supervised_session import approval
    c,leader,follower,_,trace,registers=memory_controller(tmp_path,monkeypatch)
    try:
        follower.bus.goal['wrist_flex']+=20;proposal=c.propose();bad=approval(proposal);bad['initialize_goal']=False
        import pytest
        with pytest.raises(Exception,match='approval'):c.start(bad)
        assert not any(t.startswith('write_')for t in trace)
        c.start(approval(proposal))
        assert follower.bus.goal==follower.bus.present and c.active
        assert trace.index('write_Goal_Position')<trace.index('write_Torque_Enable')
        assert c.last_activation['effect']=='sdk_returned'and c.last_activation['goal_initialized']
    finally:c.stop();leader.close();follower.close()


def test_leader_torque_is_released_only_by_explicit_session_approval(tmp_path,monkeypatch):
    from test_supervised_session import approval
    c,leader,follower,trace,_,_=memory_controller(tmp_path,monkeypatch);torque=dict.fromkeys(c.leader.profile['joints'],1)
    read=leader.bus.sync_read;write=leader.bus.sync_write
    def read_register(name,**kwargs):return dict(torque)if name=='Torque_Enable'else read(name,**kwargs)
    def write_register(name,packet,**kwargs):
        if name=='Torque_Enable':trace.append('approved_leader_release');torque.update(packet)
        else:write(name,packet,**kwargs)
    leader.bus.sync_read=read_register;leader.bus.sync_write=write_register
    try:
        proposal=c.propose();assert all(torque.values())and 'approved_leader_release'not in trace
        c.start(approval(proposal));assert not any(torque.values())and trace.count('approved_leader_release')==1
    finally:c.stop();leader.close();follower.close()


def test_capture_can_start_and_follow_leader(tmp_path):
    import time
    from test_capture_session_protocol import session_recipe
    from test_precision_calibration import OLD
    from test_supervised_session import approval
    from robot_learning_workbench.robot.session_devices import construct
    from robot_learning_workbench.robot.session import HardwareSession
    from robot_learning_workbench.robot.calibration import JOINTS,raw_from_native
    path,_,data=session_recipe(tmp_path);data['inputs']['source_robot_model']=str(OLD);data['execution']={'device_source':'memory'};path.write_text(yaml.safe_dump(data))
    plan=prepare_recipe(read_recipe(path));devices,cameras,bounds=construct(plan);s=HardwareSession(plan,devices,cameras,bounds,events=lambda e:None)
    try:
        s.connect();s.command({'kind':'teleop_prepare','command_id':'limits','payload':{}})
        assert s.teleoperation.proposal
        s.command({'kind':'teleop_start','command_id':'start','payload':approval(s.teleoperation.proposal)});assert s.teleoperation.active
        s.read_observation();before=s.history[-1]['q_measured'][0];target=dict(zip(JOINTS,s.history[-1]['q_measured']));target['shoulder_pan']+=.03
        l=devices['leader'];native=l.precision_mapper.urdf_to_calibrated(target);raw={n:round(raw_from_native(native[n],l.motor_specs[n]))for n in JOINTS};read=l.bus.sync_read
        l.bus.sync_read=lambda name,**kw:raw.copy()if name=='Present_Position'else read(name,**kw)
        deadline=time.monotonic()+1
        while abs(s.history[-1]['q_measured'][0]-before)<=.02:
            s.observe();time.sleep(.02);assert time.monotonic()<deadline
        s.command({'kind':'teleop_stop','command_id':'stop','payload':{}});assert not s.teleoperation.active and s.state=='OBSERVING'
    finally:s.close()


def test_ui_production_prepare_reaches_real_sim_runtime_without_device_connections(tmp_path):
    from robot_learning_workbench.ui.operations import prepared
    path,project,data,config=configured_scene(tmp_path)
    data['inputs'].update({k:config['inputs'][k]for k in('leader_device_profile','leader_calibration_profile')});data['execution']=config['execution'];path.write_text(yaml.safe_dump(data))
    result=prepared(str(path),str(R/'robot_learning_workbench/task_modules.yaml'))
    assert result['runnable']and result['state']=='runtime_ready'and result['prepared_sha256']
