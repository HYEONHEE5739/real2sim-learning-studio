"""tool0 remains a coordinate frame, never a preview or observation marker."""
from types import SimpleNamespace

import av
import mujoco
import numpy as np

from scene_contract.package import SceneIdentity
from robot_learning_workbench.run import preview_session,read_preview_frame
from robot_learning_workbench.engines.mujoco.model import JOINTS
from robot_learning_workbench.engines.mujoco.source import collect_episode


def marker_model():
    bodies=''.join(f'''<body name="link{i}" pos="{i*.1} 0 .15">
        <joint name="{name}" axis="0 0 1" range="-2 2"/>
        <geom type="sphere" size=".01" mass=".1" rgba=".2 .2 .2 1" contype="0" conaffinity="0"/>
        {('<site name="tool0" size=".04" pos="0 0 .05" rgba="0 1 0 1"/>' if i==0 else '')}
        </body>''' for i,name in enumerate(JOINTS))
    actuators=''.join(f'<position joint="{name}" kp="10"/>'for name in JOINTS)
    model=mujoco.MjModel.from_xml_string(f'''<mujoco><option timestep="{1/30}" gravity="0 0 0"/>
        <worldbody><light pos="0 0 2"/><geom type="plane" size="1 1 .1" rgba=".5 .5 .5 1"/>
        <camera name="side" pos="0 0 1"/><camera name="wrist" pos="0 0 1"/>{bodies}</worldbody>
        <actuator>{actuators}</actuator></mujoco>''')
    data=mujoco.MjData(model);mujoco.mj_forward(model,data)
    binding=SimpleNamespace(model_sha256='0'*64,scene_identity=SceneIdentity('fixture','marker','0'*64),
        q_indices=tuple(range(6)),v_indices=tuple(range(6)),actuator_ids=tuple(range(6)),
        limits=np.tile([-2.,2.],(6,1)),world_from_robot_base=np.eye(4),object_body_ids={},
        eef_id=model.site('tool0').id,decimation=1)
    return model,data,binding


def green_pixels(rgb):
    rgb=rgb.astype(int)
    return int(((rgb[:,:,1]>150)&(rgb[:,:,1]>rgb[:,:,0]+70)&(rgb[:,:,1]>rgb[:,:,2]+70)).sum())


def test_source_preview_and_mp4_hide_tool_marker_with_one_render_per_camera(tmp_path,monkeypatch):
    model,data,binding=marker_model();before=data.site_xpos[binding.eef_id].copy()
    rgba=model.site_rgba.copy();run=tmp_path/'run';run.mkdir()
    renders=[];render=mujoco.Renderer.render
    def counted(renderer,*args,**kwargs):renders.append(True);return render(renderer,*args,**kwargs)
    monkeypatch.setattr(mujoco.Renderer,'render',counted)
    with preview_session(run,lambda _:None,interval_s=0):
        episode,media,_,status=collect_episode(model,data,binding,SimpleNamespace(folder=tmp_path/'media'),
            episode_id='source-1',frames=2,read_target=lambda:np.zeros(6),events=lambda _:None,commands=lambda:())
        assert status=='completed' and episode.seed is None
        for camera,path in media.items():
            metadata,ppm=read_preview_frame(run,camera)
            preview=np.frombuffer(ppm.split(b'\n255\n',1)[1],np.uint8).reshape(480,640,3)
            assert green_pixels(preview)==0,'tool0 leaked into the Source preview'
            assert metadata['frame_index']==1
            with av.open(str(path))as container:frames=list(container.decode(video=0))
            assert len(frames)==2
            assert all(green_pixels(frame.to_ndarray(format='rgb24'))==0 for frame in frames), 'tool0 leaked into training MP4'
    np.testing.assert_array_equal(data.site_xpos[binding.eef_id],before)
    np.testing.assert_array_equal(model.site_rgba,rgba)
    assert data.time==2/30  # Preview drawing cannot advance the simulation.
    assert len(renders)==4  # Two cameras * two frames, with no extra preview render.
    assert episode.data['initial_state']


def test_clean_camera_retains_green_object_material_and_tool_coordinates():
    from robot_learning_workbench.engines.mujoco.rendering import camera_rgb
    model,data,binding=marker_model()
    # A green physical object is not a debug marker and must stay in the RGB.
    model.geom_rgba[model.body('link2').geomadr[0]]=[0,1,0,1]
    before=data.site_xpos[binding.eef_id].copy()
    with mujoco.Renderer(model,height=480,width=640)as renderer:
        clean=camera_rgb(renderer,data,'wrist')
        repeated=camera_rgb(renderer,data,'wrist')
    assert green_pixels(clean)>0
    np.testing.assert_array_equal(clean,repeated)
    np.testing.assert_array_equal(data.site_xpos[binding.eef_id],before)
    assert data.time==0
