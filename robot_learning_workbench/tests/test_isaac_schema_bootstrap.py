"""Fresh-process USD/Camera bootstrap; no Kit, GPU, camera or robot devices."""
import os
from pathlib import Path
import subprocess
import sys


def test_real_render_worker_registers_lens_schema_before_app_creates_the_first_stage(tmp_path):
    result=subprocess.run([sys.executable,'-B','-c',r'''
import json,sys,time
from pathlib import Path
from types import ModuleType,SimpleNamespace
import numpy as np
from pxr import Usd,UsdGeom
from robot_learning_workbench.data.native import atomic_json
from robot_learning_workbench.robot import render_worker,scene_render,pose_render
from robot_learning_workbench.engines.isaac import env_cfg
root=Path(sys.argv[1]);identity={'source':'synthetic-schema-bootstrap'}
atomic_json(root/'config.json',dict(engine='isaac',scene='',settings='',mapping={},identity=identity))
atomic_json(root/'latest.json',dict(id='live1',q=[0.]*6,requested_ns=time.monotonic_ns()))
state={}
class App:
    def close(self):state['closed']=True
class AppLauncher:
    def __init__(self,**kwargs):
        # Kit creates stages during initialization. Keep that real USD boundary
        # while replacing only the expensive simulator launcher.
        self.app=App();stage=Usd.Stage.CreateInMemory();state['camera']=UsdGeom.Camera.Define(stage,'/Camera');state['stage']=stage
module=ModuleType('isaaclab.app');module.AppLauncher=AppLauncher
sys.modules['isaaclab']=ModuleType('isaaclab');sys.modules['isaaclab.app']=module
scene_render.SceneView=lambda *args:SimpleNamespace(identity=identity,render_type='native',simulation_mode='pose')
k=np.array([[600.,0.,300.],[0.,800.,210.],[0.,0.,1.]])
class Renderer:
    def __enter__(self):
        camera=state['camera'];env_cfg._set_native_pinhole(camera,k,(640,480),env_cfg._pinhole_properties(k,(640,480)))
        assert np.array_equal(env_cfg._native_pinhole_matrix(camera,(640,480)),k)
        return self
    def __exit__(self,*args):pass
    def render(self,q):
        (root/'stop').touch()
        return dict(images={'side':np.zeros((12,16,3),np.uint8)})
pose_render.create_pose_renderer=lambda *args:Renderer()
render_worker.run(root)
assert state['closed'] and not(root/'error.json').exists()
assert json.loads((root/'ready.json').read_text())['ready']
assert json.loads((root/'live-result.json').read_text())['id']=='live1'
''',str(tmp_path)],capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_native_stage14_registers_schema_before_package_parser_opens_a_stage(tmp_path):
    result=subprocess.run([sys.executable,'-B','-c',r'''
import sys
import numpy as np
from pxr import Usd,UsdGeom
from real2sim_builder import export,stage_workers
from robot_learning_workbench.engines.isaac import env_cfg
class Checked(Exception):pass
def package(*args):
    stage=Usd.Stage.CreateInMemory();camera=UsdGeom.Camera.Define(stage,'/Camera')
    k=np.array([[600.,0.,300.],[0.,800.,210.],[0.,0.,1.]])
    env_cfg._set_native_pinhole(camera,k,(640,480),env_cfg._pinhole_properties(k,(640,480)))
    assert np.array_equal(env_cfg._native_pinhole_matrix(camera,(640,480)),k)
    raise Checked()
export.verify_package=package
try:stage_workers.simulator({'engine':'isaac','package':'unused'})
except Checked:pass
else:raise AssertionError('Package parser boundary was not reached')
'''],capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_schema_bootstrap_is_repeatable_and_preserves_original_camera_values():
    result=subprocess.run([sys.executable,'-B','-c',r'''
import numpy as np
from pxr import Usd,UsdGeom
from robot_learning_workbench.engines.isaac import env_cfg
env_cfg.prepare_camera_schema()
stage=Usd.Stage.CreateInMemory();camera=UsdGeom.Camera.Define(stage,'/Camera')
k=np.array([[600.,0.,300.],[0.,800.,210.],[0.,0.,1.]])
env_cfg._set_native_pinhole(camera,k,(640,480),env_cfg._pinhole_properties(k,(640,480)))
before=stage.GetRootLayer().ExportToString()
env_cfg.prepare_camera_schema()
assert before==stage.GetRootLayer().ExportToString()
assert np.array_equal(env_cfg._native_pinhole_matrix(camera,(640,480)),k)
'''],capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_missing_installed_schema_is_explicit_and_does_not_create_a_fallback(tmp_path):
    result=subprocess.run([sys.executable,'-B','-c',r'''
import importlib.metadata,sys
from pathlib import Path
from types import SimpleNamespace
from robot_learning_workbench.engines.isaac import env_cfg
root=Path(sys.argv[1]);importlib.metadata.distribution=lambda name:SimpleNamespace(locate_file=lambda path:root)
try:env_cfg.prepare_camera_schema()
except RuntimeError as error:assert 'NEEDS_RUNTIME'in str(error)and'omni_lens_distortion'in str(error)
else:raise AssertionError('Missing schema must not use physical aperture/default intrinsics instead')
assert not list(root.iterdir())
''',str(tmp_path)],capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),timeout=15)
    assert result.returncode==0,result.stdout+result.stderr


def test_native_package_parser_cannot_freeze_out_the_installed_physx_schema():
    result=subprocess.run([sys.executable,'-B','-c',r'''
from importlib.metadata import distribution
from pathlib import Path
from pxr import Plug,Usd,UsdPhysics
from robot_learning_workbench.engines.isaac.env_cfg import prepare_camera_schema
prepare_camera_schema()
stage=Usd.Stage.CreateInMemory();scene=UsdPhysics.Scene.Define(stage,'/World/Physics').GetPrim()
# Kit discovers these after the Package parser in Source/Stage14. That must
# still work, so the bootstrap must have registered them before this Stage.
root=Path(distribution('isaacsim').locate_file('isaacsim/extscache'))
for path in root.glob('omni.usd.schema.physx-*/plugins/*/resources'):
    Plug.Registry().RegisterPlugins(str(path))
assert scene.CanApplyAPI('PhysxSceneAPI')
assert scene.ApplyAPI('PhysxSceneAPI')
'''],capture_output=True,text=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'),timeout=15)
    assert result.returncode==0,result.stdout+result.stderr
