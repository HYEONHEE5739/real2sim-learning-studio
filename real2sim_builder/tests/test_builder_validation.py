"""Real array diagnostics retain original Builder's numeric interpretation."""
import importlib.util
from pathlib import Path
import numpy as np
import pytest


def reference_metrics():
    path=Path('/home/hyeonhee/soarm_isaaclab/real2sim-builder/app/validation/metrics.py')
    spec=importlib.util.spec_from_file_location('builder_original_metrics',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_rgb_and_silhouette_metrics_match_original_and_keep_missing_geometry_unknown(tmp_path):
    from real2sim_builder.validation import compare,mask_metrics
    ref=reference_metrics();a=np.zeros((12,16,3),np.uint8);b=a.copy();b[3:8,4:11]=200
    assert compare(a,b,tmp_path/'new')==ref.compare(a,b,tmp_path/'old')
    x=np.zeros((12,16),bool);x[3:8,4:11]=True
    assert mask_metrics(x,np.roll(x,1,axis=0))==ref.mask_metrics(x,np.roll(x,1,axis=0))
    with pytest.raises(ValueError):compare(a,b[:1],tmp_path/'bad')
    with pytest.raises(ValueError):mask_metrics(np.zeros_like(x),x)


def test_renderer_selection_requires_separate_worker_and_missing_blender_is_explicit(monkeypatch):
    from real2sim_builder import rendering as r
    monkeypatch.setenv('REAL2SIM_BLENDER','/not-an-installed-blender')
    assert r.capability()['available'] is False
    with pytest.raises(r.Unavailable):r.invoke({},Path('/not-used'))
    with pytest.raises(ValueError):r.configure('made-up-renderer')
    monkeypatch.setenv('PYTHONPATH','/foreign/numpy')
    assert 'PYTHONPATH' not in r.worker_environment()
    assert __import__('os').environ['PYTHONPATH']=='/foreign/numpy'


def test_actual_mujoco_renderer_in_separate_worker_has_owned_rgb_and_object_mask(tmp_path):
    import os,subprocess,sys
    code='''
import ast,json,sys,numpy as np
from pathlib import Path
from real2sim_builder.project import empty,value
from real2sim_builder.rendering import Renderer
source=Path('/home/hyeonhee/soarm_isaaclab/real2sim-builder/tests/conftest.py').read_text()
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='scene');node.decorator_list=[]
exec(compile(ast.Module(body=[node],type_ignores=[]),'original_scene_fixture','exec'))
canonical=scene()
with Renderer(canonical,Path(sys.argv[1]),Path(sys.argv[1])/'renderer','software-egl') as renderer:
 rgb=renderer.rgb('side');mask=renderer.mask('side','block')
 assert rgb.dtype==np.uint8 and rgb.shape==(120,160,3) and mask.shape==(120,160) and mask.any()
 before=rgb.copy();renderer.rgb('left');assert np.array_equal(rgb,before)
 print(json.dumps({'rendered':True,'shape':list(rgb.shape),'mask_pixels':int(mask.sum()),'physics_step':False}))
'''
    env=os.environ.copy();env.pop('MUJOCO_GL',None)
    result=subprocess.run([sys.executable,'-B','-c',code,str(tmp_path)],capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stdout+result.stderr
