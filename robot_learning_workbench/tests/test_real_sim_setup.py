import copy,os,shutil
from pathlib import Path
import pytest
from real2sim_builder.project import Project
from real2sim_builder.files import read,write
from robot_learning_workbench.robot.registration import save_configuration,bind_configuration
from robot_learning_workbench.ui.session_operations import real_sim_setup
R=Path(__file__).resolve().parents[2]


def test_real_sim_setup_checks_registered_manifest_before_selecting_scene(tmp_path):
    source=R/'workbench_runs/scenes/pickplace-colorblock-b7a5592b';p=Project.create(tmp_path/'scenes','Chosen Scene')
    shutil.copytree(source/'exports/scene-v8-native',p.root/'exports/scene-v8-native',copy_function=os.link)
    for engine in('mujoco','isaac'):write(p.root/'configuration'/(engine+'.json'),read(source/'configuration'/(engine+'.json')))
    record=copy.deepcopy(read(source/'project.yaml')['execution_packages'][0]);record['manifest_sha256']='0'*64;info=read(p.root/'project.yaml');info['execution_packages']=[record];write(p.root/'project.yaml',info)
    config=save_configuration(tmp_path,'devices',read(R/'workbench_runs/devices/so101-pickplace-0b794e7c/capture.yaml'));bind_configuration(p.root,config,tmp_path)
    with pytest.raises(ValueError,match='[Ii]dentity|[Mm]anifest|[Rr]evision'):real_sim_setup(tmp_path,p.root,p.root/'exports/scene-v8-native/scene.json','mujoco')
