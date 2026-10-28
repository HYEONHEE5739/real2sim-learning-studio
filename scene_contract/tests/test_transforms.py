"""Reference-frame math, not simulator pose lookup or calibration execution."""
import copy
import numpy as np
import pytest

from scene_contract.package import SceneError
from scene_contract.transforms import validate_transform, validate_frames, resolve_transform


def frame(parent, matrix=None, **extra):
    return {"parent":parent, "T_parent_from_frame":np.eye(4).tolist() if matrix is None else matrix,
            "state":"reference", **extra}


def graph():
    return {"world":frame(None),
        "workspace":frame("world",[[0.,-1.,0.,.3],[1.,0.,0.,-.2],[0.,0.,1.,.01],[0.,0.,0.,1.]]),
        "object":frame("workspace",[[1.,0.,0.,.04],[0.,1.,0.,.02],[0.,0.,1.,.03],[0.,0.,0.,1.]])}


def test_column_vector_composition_inverse_and_input_preservation():
    frames=graph();before=copy.deepcopy(frames)
    expected=np.array(frames["workspace"]["T_parent_from_frame"])@np.array(frames["object"]["T_parent_from_frame"])
    actual=resolve_transform(frames,source="object",target="world")
    np.testing.assert_array_equal(actual,expected)
    inverse=resolve_transform(frames,source="world",target="object")
    np.testing.assert_array_equal(inverse,np.linalg.inv(expected))
    np.testing.assert_allclose(inverse@actual,np.eye(4),rtol=0,atol=1e-15)
    assert frames==before


@pytest.mark.parametrize("value", [[], np.eye(3).tolist(), [[1.,0.,0.,0.]]*4,
    np.diag([-1.,1.,1.,1.]).tolist(), np.diag([1.1,1.,1.,1.]).tolist(),
    np.full((4,4),np.nan).tolist(), np.full((4,4),np.inf).tolist(), np.eye(4).astype(str).tolist(),
    np.eye(4).astype(bool).tolist(), np.eye(4).astype(complex)])
def test_invalid_matrix_is_rejected_without_normalizing(value):
    with pytest.raises(SceneError):validate_transform(value)


@pytest.mark.parametrize("fault",["missing_world","missing_parent","cycle","extra_root","root_pose","state","quaternion"])
def test_invalid_frame_graph_is_rejected(fault):
    frames=graph()
    if fault=="missing_world":frames.pop("world")
    elif fault=="missing_parent":frames["workspace"]["parent"]="absent"
    elif fault=="cycle":frames["workspace"]["parent"]="object"
    elif fault=="extra_root":frames["object"]["parent"]=None
    elif fault=="root_pose":frames["world"]["T_parent_from_frame"][0][3]=1e-9
    elif fault=="state":frames["object"]["state"]="current"
    else:frames["object"]["quat_wxyz"]=[1.,0.,0.,0.]
    with pytest.raises(SceneError):validate_frames(frames)


def test_unknown_frame_and_current_pose_cannot_fall_back_to_reference():
    frames=graph();frames["object"]["dynamic_source"]={"mujoco":{"body":"robot_gripper"}}
    validate_frames(frames)
    assert resolve_transform(frames,source="object",target="world")[0,3]==pytest.approx(.28)
    with pytest.raises(SceneError) as raised:resolve_transform(frames,source="unknown",target="world")
    assert raised.value.code=="FRAME_UNRESOLVABLE"
    with pytest.raises(SceneError):resolve_transform(frames,source="object",target="world",state="current")


def test_long_frame_chain_does_not_depend_on_python_recursion_limit():
    frames={"world":frame(None)}
    for i in range(1200):frames[str(i)]=frame("world" if i==0 else str(i-1))
    np.testing.assert_array_equal(resolve_transform(frames,source="1199",target="world"),np.eye(4))


def test_accepted_roundoff_uses_full_inverse_not_rotation_transpose():
    matrix=np.eye(4);matrix[0,0]=1.000005
    frames={"world":frame(None),"approximate":frame("world",matrix.tolist())}
    actual=resolve_transform(frames,source="world",target="approximate")
    np.testing.assert_array_equal(actual,np.linalg.inv(matrix))
    assert actual[0,0]!=matrix[0,0]
