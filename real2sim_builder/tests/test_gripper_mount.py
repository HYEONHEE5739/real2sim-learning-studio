import copy
import numpy as np
from real2sim_builder.files import sha


def fixture(tmp_path):
    from types import SimpleNamespace
    from real2sim_builder.scene import empty,value
    p=SimpleNamespace(root=tmp_path,checkpoint=lambda:None)
    urdf=tmp_path/'gripper.urdf';urdf.write_text('<robot name="gripper"><link name="base"/><link name="tool"><visual><geometry><box size="0.02 0.02 0.02"/></geometry></visual></link><joint name="arm" type="revolute"><parent link="base"/><child link="tool"/><axis xyz="0 0 1"/></joint></robot>')
    scene=empty('mount');scene['robot_model']={'path':urdf.name,'model_sha256':sha(urdf),'joint_names':['arm'],'mapping':{'sha256':'a'*64}}
    scene['cameras']=[{'id':'optics','frame':'robot_link_tool','camera_type':'wrist','K':value([[400,0,160],[0,400,120],[0,0,1]],'calibrated'),
        'pose':value(None),'distortion':value([0.]*5,'calibrated'),'resolution':[320,240]}]
    truth=np.eye(4);truth[2,3]=-.12
    points=np.array([[x,y,z]for x in(-.01,.01)for y in(-.01,.01)for z in(-.01,.01)])
    rows=[]
    for q in(.1,.6):
        optical=points-truth[:3,3];uv=optical[:,:2]/optical[:,2:]*400+[160,120]
        rows.append({'id':str(q),'split':'train','group_id':str(q),'camera':'optics','q_measured':[q],'joint_names':['arm'],
            'robot_model_sha256':sha(urdf),'mapping_sha256':'a'*64,
            'landmarks':[{'link':'tool','point_m':x.tolist(),'uv':v.tolist(),'confidence':1.}for x,v in zip(points,uv)]})
    return p,scene,rows,truth


def test_gripper_mount_is_shared_and_arm_motion_does_not_create_new_view(tmp_path):
    from real2sim_builder.calibration.wrist import fit_gripper_mount
    p,s,rows,truth=fixture(tmp_path);before=copy.deepcopy(s)
    report=fit_gripper_mount(p,s,'optics',rows)
    assert report['status']=='ESTIMATED',report
    np.testing.assert_allclose(report['T_link_camera'],truth,atol=1e-5)
    assert report['independent_relative_configurations']==1
    assert report['rank']==6 and report['world_pose_observable']is False
    assert report['training_rmse_px']<1e-4 and s==before


def test_insufficient_gripper_points_or_missing_q_stay_unresolved(tmp_path):
    from real2sim_builder.calibration.wrist import fit_gripper_mount
    p,s,rows,truth=fixture(tmp_path)
    for r in rows:r['landmarks']=r['landmarks'][:2]
    report=fit_gripper_mount(p,s,'optics',rows)
    assert report['status']=='NEEDS_MORE_DATA'and 'T_link_camera'not in report


def test_gripper_crop_coordinates_and_holdout_leak_are_explicit(tmp_path):
    import pytest
    from real2sim_builder.calibration.wrist import fit_gripper_mount
    p,s,rows,T=fixture(tmp_path)
    for r in rows:
        r['resolution']=[640,480];r['pixel_from_camera']=[[2,0,0],[0,2,0],[0,0,1]]
        for point in r['landmarks']:point['uv']=(np.array(point['uv'])*2).tolist()
    result=fit_gripper_mount(p,s,'optics',rows)
    np.testing.assert_allclose(result['T_link_camera'],T,atol=1e-5)
    rows[1]['split']='validation';rows[1]['group_id']=rows[0]['group_id']
    with pytest.raises(ValueError,match='leakage'):fit_gripper_mount(p,s,'optics',rows)


def test_gripper_holdout_error_uses_actual_observation_pixels(tmp_path):
    import pytest
    from real2sim_builder.calibration.wrist import fit_gripper_mount
    p,scene,rows,truth=fixture(tmp_path)
    held=copy.deepcopy(rows[0]);held.update(id='held',split='validation',group_id='held',
        resolution=[640,480],pixel_from_camera=[[2,0,0],[0,2,0],[0,0,1]])
    for point in held['landmarks']:point['uv']=(np.array(point['uv'])*2+[4,0]).tolist()
    report=fit_gripper_mount(p,scene,'optics',rows+[held])
    assert report['status']=='ESTIMATED'
    assert report['holdout_rmse_px']==pytest.approx(4.,abs=1e-4)
