"""Isaac Lab2.3 RGB for posed authoring Candidates; no physics Step or robot target.

Uses existing Builder USD geometry/camera export and the installed Camera sensor.
This is static measured-FK rendering, not a v8 Native physics rollout.
"""
from pathlib import Path
import numpy as np


class StaticRenderer:
    def __init__(self,scene,root,directory):
        import isaaclab.sim as sim
        from isaaclab.sensors import Camera,CameraCfg
        from real2sim_builder.exporters.usd import export
        import omni.usd
        self.sim=sim.SimulationContext(sim.SimulationCfg(dt=1/30,device='cuda:0'));self.cameras={}
        usd=Path(directory)/'candidate.usda';export(scene,root,usd)
        cfg=sim.UsdFileCfg(usd_path=str(usd));cfg.func('/World/Candidate',cfg)
        self.stage=omni.usd.get_context().get_stage()
        for name in('side','wrist'):
            self.cameras[name]=Camera(CameraCfg(prim_path='/World/Candidate/'+name,spawn=None,width=640,height=480,data_types=['rgb'],update_latest_camera_pose=True))
        self.sim.reset()

    def render(self,scene):
        from pxr import Gf
        from real2sim_builder.scene import world_pose
        from real2sim_builder.cameras import OPTICAL_TO_RENDER
        for row in scene['objects']+scene['cameras']:
            pose=world_pose(scene,row)
            if row in scene['cameras']:pose=pose@OPTICAL_TO_RENDER
            attr=self.stage.GetPrimAtPath('/World/Candidate/'+row['id']).GetAttribute('xformOp:transform')
            if not attr:raise ValueError('Candidate USD transform unavailable: '+row['id'])
            matrix=Gf.Matrix4d(*pose.T.ravel().tolist());attr.Set(matrix)
            if not np.allclose(np.asarray(attr.Get()),pose.T,atol=1e-12):raise ValueError('USD measured-pose application readback differs')
        for _ in range(3):self.sim.render()
        for sensor in self.cameras.values():sensor.update(1/30,force_recompute=True)
        return {name:sensor.data.output['rgb'][0,:,:,:3].detach().cpu().numpy().copy()for name,sensor in self.cameras.items()}

    def close(self):
        self.sim.stop();self.cameras.clear();self.sim.clear_all_callbacks();self.sim.clear_instance()
