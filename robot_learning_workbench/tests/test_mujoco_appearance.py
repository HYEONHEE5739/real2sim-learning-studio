import xml.etree.ElementTree as ET
import numpy as np
import pytest


def test_explicit_color_transfer_leaves_collision_geometry_and_alpha_unchanged():
    from robot_learning_workbench.engines.mujoco.model import apply_visual_gamma
    root = ET.fromstring('<mujoco><worldbody><geom name="paint" group="2" rgba=".04 .16 .64 .5" contype="0"/><geom name="collision" group="3" rgba="0 0 0 0" size=".012 .012 .012"/></worldbody></mujoco>')
    collision = ET.tostring(root.find('.//geom[@name="collision"]'))
    apply_visual_gamma(root, .5)
    np.testing.assert_allclose(np.fromstring(root.find('.//geom[@name="paint"]').get('rgba'), sep=' '), [.2,.4,.8,.5])
    assert ET.tostring(root.find('.//geom[@name="collision"]')) == collision


@pytest.mark.parametrize('gamma', [0, -1, float('nan'), float('inf'), True])
def test_invalid_visual_transfer_rejected(gamma):
    from robot_learning_workbench.engines.mujoco.model import apply_visual_gamma
    with pytest.raises(ValueError):
        apply_visual_gamma(ET.Element('mujoco'), gamma)
