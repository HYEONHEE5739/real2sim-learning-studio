"""Random reset must rest above a physical workspace sheet, not inside it."""
from types import SimpleNamespace
from unittest.mock import patch

import mujoco
import numpy as np
import pytest

from scene_contract.package import SceneIdentity
from robot_learning_workbench.tasks import placement
from robot_learning_workbench.tasks.registry import load_registry
from robot_learning_workbench.engines.mujoco.source import reset_placements
from robot_learning_workbench.engines.mujoco.state import snapshot


def workspace_scene(sheet_z):
    def frame(z):
        pose=np.eye(4);pose[2,3]=z
        return {'parent':'world','T_parent_from_frame':pose.tolist(),'state':'reference'}
    def box(role,frame_id,dimensions):
        return {'role':role,'frame_id':frame_id,'collision':{'kind':'primitive','primitive':'box','dimensions_m':dimensions}}
    return SimpleNamespace(scene={
        'frames':{'world':{'parent':None,'T_parent_from_frame':np.eye(4).tolist(),'state':'reference'},
                  'table_frame':frame(.025),'object_marker':frame(sheet_z),'red_frame':frame(.08)},
        'objects':{'table':box('support','table_frame',[1.,.8,.05]),
                   'marker':box('workspace','object_marker',[.15,.15,.0005]),
                   'cube_red':box('task_object','red_frame',[.024,.024,.024])},
        'supports':{'table':{'object_id':'table'}}})


@pytest.mark.parametrize('sheet_z', [.05,.049])
def test_random_reset_clears_sheet_and_table_and_rests_on_highest_surface(sheet_z):
    scene=workspace_scene(sheet_z)
    params=placement.WorkspaceParams('cube_red','object_marker','table','marker')
    placement.validate_params(params,scene)
    plan=SimpleNamespace(scene=scene,object_order=('cube_red',),
        tasks=load_registry(('robot_learning_workbench.tasks.placement',)),
        function_bindings={'objects.cube_red.placement':SimpleNamespace(
            name='placement.random_workspace',kind='placement',params=params,request_fields={})})
    model=mujoco.MjModel.from_xml_string(f'''<mujoco><worldbody>
        <body name="table" pos="0 0 .025"><geom name="table" type="box" size=".5 .4 .025"/></body>
        <body name="marker" pos="0 0 {sheet_z}"><geom name="paper" type="box" size=".075 .075 .00025"/></body>
        <body name="cube_red" pos="0 0 .08"><freejoint/><geom name="red" type="box" size=".012 .012 .012" mass=".02"/></body>
        </worldbody></mujoco>''')
    data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    bindings=SimpleNamespace(model_sha256='0'*64,scene_identity=SceneIdentity('fixture','sheet','0'*64),
        object_body_ids={name:model.body(name).id for name in scene.scene['objects']},
        object_indices={'cube_red':(0,0)})
    with patch.object(np.random,'default_rng',return_value=np.random.Generator(np.random.PCG64(0))):
        records=reset_placements(plan,model,data,bindings)
    assert records['cube_red']['applied']
    bottom=data.xpos[model.body('cube_red').id,2]-.012
    assert bottom==pytest.approx(max(.05,sheet_z+.00025),abs=1e-12)
    assert min((c.dist for c in data.contact),default=0)>=-1e-12
    assert data.time==0  # No settling step or arbitrary lift replaces geometry.


def test_real_penetration_is_still_rejected_and_reset_is_rolled_back():
    from robot_learning_workbench.engines.mujoco.state import reset_object_poses
    model=mujoco.MjModel.from_xml_string('''<mujoco><worldbody>
        <geom name="table" type="box" size=".5 .4 .025" pos="0 0 .025"/>
        <body name="cube_red" pos="0 0 .08"><freejoint/><geom type="box" size=".012 .012 .012" mass=".02"/></body>
        </worldbody></mujoco>''')
    data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    bindings=SimpleNamespace(model_sha256='0'*64,scene_identity=SceneIdentity('fixture','sheet','0'*64),
        object_body_ids={'cube_red':model.body('cube_red').id},object_indices={'cube_red':(0,0)})
    before=snapshot(model,data,bindings);pose=np.eye(4);pose[2,3]=.05
    with pytest.raises(ValueError,match='penetrates'):
        reset_object_poses(model,data,bindings,[('cube_red',pose)])
    assert snapshot(model,data,bindings)==before
