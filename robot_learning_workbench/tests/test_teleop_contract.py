"""No manual limits; existing coordinate/approval/watchdog contracts remain."""
import pytest,yaml
from test_ui_restoration import qt


def test_teleop_start_has_no_numeric_setup_or_device_fields(tmp_path):
    qt('''
from pathlib import Path
import sys
from PyQt6.QtWidgets import QApplication
from robot_learning_workbench.ui.app import Window
app=QApplication([]);w=Window('/no/worker',Path(sys.argv[1])/'modules',Path(sys.argv[1])/'workspace');w.show();app.processEvents();p=w.sessions['capture']
assert not hasattr(p.settings,'motion_limits')
p.client.running=True;p.client.stage='capture_session';p.last_progress={'session_state':'OBSERVING','teleoperation_available':True};sent=[];p.client.send=lambda kind,payload=None:sent.append((kind,payload));p.buttons(True)
p.start_teleop_button.click();assert sent==[('teleop_prepare',None)]
p.client.running=False;w.close();app.processEvents()
''',tmp_path)


def test_memory_control_needs_no_extra_limits_and_hardware_requires_verified_spec(tmp_path):
    from test_supervised_session import devices,approval
    from robot_learning_workbench.robot.supervised import Teleoperation
    l,f,_,trace,_=devices(tmp_path);bounds={n:e['limits']for n,e in f.profile['joints'].items()}
    try:
        memory=Teleoperation(l,f,model_bounds=bounds,session_id='memory',hardware=False)
        p=memory.propose();memory.start(approval(p));assert memory.active;memory.stop()
        before=len(trace);hardware=Teleoperation(l,f,model_bounds=bounds,session_id='hardware',hardware=True)
        with pytest.raises(Exception,match='CONTROL_SPEC_UNVERIFIED'):hardware.propose()
        assert not any(x.startswith('write_')or x=='send'for x in trace[before:])
    finally:l.close();f.close()


def test_retired_numeric_recipe_fields_are_not_kept_as_hidden_defaults(tmp_path):
    from robot_learning_workbench.recipe import read_recipe
    from test_capture_session_protocol import session_recipe
    path,_,data=session_recipe(tmp_path)
    for key in('max_command_step_rad','max_follow_error_rad'):
        data['execution']={'device_source':'memory',key:.1};path.write_text(yaml.safe_dump(data))
        with pytest.raises(ValueError,match='unknown'):read_recipe(path)
