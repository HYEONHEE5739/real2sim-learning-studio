"""Real array diagnostics retain original Builder's numeric interpretation."""
from pathlib import Path
import numpy as np
import pytest


def test_rgb_and_silhouette_metrics_match_original_and_keep_missing_geometry_unknown(tmp_path):
    from real2sim_builder.validation import compare,mask_metrics
    a=np.zeros((12,16,3),np.uint8);b=a.copy();b[3:8,4:11]=200
    # Known changed area/intensity, independent of the implementation under test.
    expected={'mae':35/192*200/255,'rmse':np.sqrt(35/192)*200/255,'edge_iou':0.}
    assert compare(a,b,tmp_path/'new')==pytest.approx(expected)
    x=np.zeros((12,16),bool);x[3:8,4:11]=True
    assert mask_metrics(x,np.roll(x,1,axis=0))==pytest.approx({'iou':28/42,'center_error_px':1.})
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
source=Path(sys.argv[2]).read_text()
node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name=='scene');node.decorator_list=[]
exec(compile(ast.Module(body=[node],type_ignores=[]),'original_scene_fixture','exec'))
canonical=scene()
from copy import deepcopy
left=deepcopy(canonical['cameras'][0]);left['id']='left';canonical['cameras'].append(left)
with Renderer(canonical,Path(sys.argv[1]),Path(sys.argv[1])/'renderer','software-egl') as renderer:
 rgb=renderer.rgb('side');mask=renderer.mask('side','block')
 assert rgb.dtype==np.uint8 and rgb.shape==(120,160,3) and mask.shape==(120,160) and mask.any()
 before=rgb.copy();renderer.rgb('left');assert np.array_equal(rgb,before)
 print(json.dumps({'rendered':True,'shape':list(rgb.shape),'mask_pixels':int(mask.sum()),'physics_step':False}))
'''
    env=os.environ.copy();env.pop('MUJOCO_GL',None)
    fixture=Path(__file__).with_name('test_builder_calibration.py')
    result=subprocess.run([sys.executable,'-B','-c',code,str(tmp_path),str(fixture)],capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stdout+result.stderr
def test_comparison_fast_png_retains_default_pixels_and_metrics(tmp_path):
    import numpy as np
    from PIL import Image
    from real2sim_builder.validation import compare
    rng=np.random.default_rng(47);a=rng.integers(0,256,(24,32,3),dtype=np.uint8);b=rng.integers(0,256,a.shape,dtype=np.uint8)
    original=compare(a,b,tmp_path/'default');fast=compare(a,b,tmp_path/'fast',png_compress_level=1)
    assert original==fast
    assert {p.name for p in(tmp_path/'default').iterdir()}=={p.name for p in(tmp_path/'fast').iterdir()}
    for p in(tmp_path/'default').iterdir():assert np.array_equal(np.asarray(Image.open(p)),np.asarray(Image.open(tmp_path/'fast'/p.name)))
