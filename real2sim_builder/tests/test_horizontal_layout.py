"""New Scene defaults are validation only; historical alignment is never edited."""
import copy
import numpy as np
import pytest
from real2sim_builder import project as p
from test_builder_project import measured_scene


def horizontal():
    scene=measured_scene()
    table,block=scene['objects'];table['pose']['value'][2][3]=.48;block['pose']['value'][2][3]=.53
    workspace=copy.deepcopy(table);workspace.update(id='workspace',role='workspace');workspace['dimensions']['value']=[.15,.15,.001];workspace['pose']['value'][2][3]=.5;scene['objects'].append(workspace)
    t=np.eye(4);t[:3,3]=[.3,0,.6]
    scene['frames']['robot_base']={'parent':'world','transform':p.value(t.tolist(),'measured')}
    return scene


def test_horizontal_check_preserves_height_base_and_tilted_camera():
    s=horizontal();before=copy.deepcopy(s)
    report=p.validate_horizontal_layout(s,table='table',workspace='workspace',blocks=['block'])
    assert report['passed'] and report['table_surface_world_z_m']==.5
    assert report['robot_base_world_position_m']==[.3,0,.6]
    assert report['workspace_dimensions_m']==[.15,.15]
    assert s==before and not report['calibration_verified']

@pytest.mark.parametrize('target',['table','block','robot_base','workspace'])
def test_tilt_is_reported_without_editing(target):
    s=horizontal();c,t=np.cos(.1),np.sin(.1);r=np.array([[1,0,0],[0,c,-t],[0,t,c]])
    pose=s['frames'][target]['transform']['value'] if target=='robot_base' else next(o for o in s['objects'] if o['id']==target)['pose']['value']
    a=np.array(pose);a[:3,:3]=r
    for i in range(4):pose[i]=a[i].tolist()
    before=copy.deepcopy(s);report=p.validate_horizontal_layout(s,table='table',workspace='workspace',blocks=['block'])
    assert not report['passed'] and s==before


def test_yaw_is_allowed_but_rotated_footprint_must_fit():
    s=horizontal();b=s['objects'][1];b['pose']['value'][0][3]=.06
    assert not p.validate_horizontal_layout(s,table='table',workspace='workspace',blocks=['block'])['passed']


def test_workspace_region_itself_must_fit_table():
    s=horizontal();s['objects'][2]['dimensions']['value']=[2,2,.001]
    assert not p.validate_horizontal_layout(s,table='table',workspace='workspace',blocks=[])['passed']


def test_yaw_is_not_tilt_and_uses_actual_rotated_corners():
    s=horizontal();block=s['objects'][1];block['pose']['value'][0][3]=.04
    assert p.validate_horizontal_layout(s,table='table',workspace='workspace',blocks=['block'])['passed']
    a=np.pi/4;c,t=np.cos(a),np.sin(a);rotation=[[c,-t,0],[t,c,0],[0,0,1]]
    for i in range(3):block['pose']['value'][i][:3]=rotation[i]
    report=p.validate_horizontal_layout(s,table='table',workspace='workspace',blocks=['block'])
    assert not report['passed'] and not any('local +Z' in x for x in report['issues'])
    block['pose']['value'][0][3]=0
    assert p.validate_horizontal_layout(s,table='table',workspace='workspace',blocks=['block'])['passed']
