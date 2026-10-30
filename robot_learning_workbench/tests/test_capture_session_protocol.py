import json,yaml
from pathlib import Path
import pytest
from real2sim_builder.project import Project
from robot_learning_workbench.recipe import read_recipe,prepare_recipe,verify_prepared_inputs
from robot_learning_workbench.run import _command


def session_recipe(tmp_path):
    root=Path(__file__).resolve().parents[2];e=root/'docs/evidence/hardware-read-gripper'
    project=Project.create(tmp_path/'projects','Session project')
    from test_precision_calibration import INV,CURRENT
    data=dict(schema_version=1,stage='capture_session',inputs={'project':str(project.root),'device_profile':str(e/'follower-device.json'),'calibration_profile':INV['roles']['follower']['profile_path'],
        'leader_device_profile':str(e/'leader-device.json'),'leader_calibration_profile':INV['roles']['leader']['profile_path'],'camera_config':str(e/'cameras.json'),'robot_model':str(CURRENT)},
        execution={'device_source':'memory'},output={'directory':str(tmp_path/'session-output')})
    path=tmp_path/'session.yaml';path.write_text(yaml.safe_dump(data));return path,project,data


def test_session_prepared_identity_pins_project_identity_but_allows_new_evidence(tmp_path):
    p,project,_=session_recipe(tmp_path);plan=prepare_recipe(read_recipe(p));verify_prepared_inputs(plan)
    project.update(task='new immutable capture registered');verify_prepared_inputs(plan)
    info=project.root/'project.yaml';info.write_text(info.read_text().replace('Session project','Different Project'))
    with pytest.raises(Exception,match='changed'):verify_prepared_inputs(plan)


def test_session_control_uses_explicit_existing_r03_envelope(tmp_path):
    for kind,payload in [('session_snapshot',{}),('session_disconnect',{}),('session_finish',{}),('teleop_prepare',{}),('teleop_stop',{})]:
        assert _command({'command_id':'one','kind':kind,'payload':payload})['kind']==kind
    with pytest.raises(Exception):_command({'command_id':'one','kind':'teleop_start','payload':{'approved':True}})


def test_session_heartbeat_is_bounded_latest_liveness_not_durable_user_commands(tmp_path):
    import time
    from robot_learning_workbench.run import touch_session,RunHandle,_poll_commands
    root=tmp_path/'runone';root.mkdir();(root/'commands').mkdir();(root/'run.json').write_text(json.dumps({'request_id':'req','stage':'capture_session'}))
    handle=RunHandle('runone','req',root)
    for _ in range(5):touch_session(handle,time.monotonic_ns())
    assert not list((root/'commands').iterdir())
    state={'seen_commands':set(),'command_seq':0}
    rows=_poll_commands(root,state,'capture_session');assert rows[-1]['kind']=='session_heartbeat'
    assert len(list(root.glob('session-heartbeat.json')))==1 and not state['seen_commands']
