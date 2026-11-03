"""Explicit offline calibration projections, independent of interactive simulation."""
from .scene_render import NativeRenderer
from .calibration import JOINTS


class PoseRenderer(NativeRenderer):
    state_application='native_measured_joint_state'

    def _advance(self,measured):
        if self.view.engine=='mujoco':
            import mujoco
            self.data.qpos[list(self.binding.q_indices)]=measured
            self.data.qvel[list(self.binding.v_indices)]=0
            mujoco.mj_forward(self.model,self.data)
        else:
            import torch
            env=self.env;robot=env.scene['robot'];ids=[robot.joint_names.index(n)for n in JOINTS]
            pose=robot.data.joint_pos.clone();pose[:,ids]=torch.as_tensor(measured,dtype=pose.dtype,device=env.device)
            robot.write_joint_state_to_sim(pose,torch.zeros_like(pose))
            env.scene.write_data_to_sim();env.sim.forward();env.scene.update(env.physics_dt)
        return measured.copy(),0


def create_pose_renderer(view,directory):
    if view.render_type=='authored':
        from .authored_render import AuthoredRenderer
        return AuthoredRenderer(view,directory)
    return PoseRenderer(view,directory)
