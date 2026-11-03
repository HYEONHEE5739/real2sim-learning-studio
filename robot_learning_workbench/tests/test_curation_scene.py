"""Review uses the recorded model and joint/object poses, without simulation."""
import numpy as np
from robot_learning_workbench.data.native import file_sha256


def test_robot_visual_moves_with_recorded_joint_and_preserves_model_bytes(tmp_path):
    from real2sim_builder.calibration.geometry import write_stl
    from robot_learning_workbench.data.review_scene import RobotVisual,box_triangles
    triangles=box_triangles(np.array([.02,.01,.01]));vertices=triangles.reshape(-1,3)
    write_stl(tmp_path/'link.stl',vertices,np.arange(len(vertices)).reshape(-1,3))
    urdf=tmp_path/'robot.urdf';urdf.write_text('''<robot name="review"><link name="base"/><link name="arm"><visual><origin xyz=".02 0 0"/><geometry><mesh filename="link.stl"/></geometry></visual></link><joint name="turn" type="revolute"><parent link="base"/><child link="arm"/><axis xyz="0 0 1"/></joint></robot>''')
    before=file_sha256(urdf);model=RobotVisual(urdf)
    zero=np.array(model.poses({'turn':0.})['arm']);turned=np.array(model.poses({'turn':np.pi/2})['arm'])
    point=np.array(model.parts[0]['triangles'])[0,0]
    p0=zero[:3,:3]@point+zero[:3,3];p1=turned[:3,:3]@point+turned[:3,3]
    assert not np.allclose(p0,p1)
    np.testing.assert_allclose(np.linalg.norm(p0),np.linalg.norm(p1),rtol=0,atol=1e-12)
    assert file_sha256(urdf)==before
