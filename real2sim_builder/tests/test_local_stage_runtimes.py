"""Small contracts only: no model constructors, Forward, download, or full E2E."""
import importlib.util
from pathlib import Path
import sys
import types
import numpy as np
import pytest
from PIL import Image


def test_sam31_preserves_rgb_pixel_frame_confidence_and_one_object_point_hints(monkeypatch, tmp_path):
    from real2sim_builder.sam31_adapter import SAM31
    seen = []
    class Tensor:
        def __init__(self, a): self.a = np.asarray(a)
        def detach(self): return self
        def cpu(self): return self
        def numpy(self): return self.a
    class Predictor:
        def __init__(self, overrides):
            assert overrides['half'] and overrides['quantize'] == 16
        def set_image(self, image):
            assert image.shape == (5, 7, 3)
            assert image[0, 0].tolist() == [3, 2, 1]  # RGB -> BGR once
        def __call__(self, **kw):
            seen.append(kw)
            return [types.SimpleNamespace(masks=types.SimpleNamespace(data=Tensor(np.ones((1,5,7)))),
                    boxes=types.SimpleNamespace(xyxy=Tensor([[0,0,7,5]]),conf=Tensor([.8])))]
    monkeypatch.setitem(sys.modules,'ultralytics.models.sam',types.SimpleNamespace(SAM3Predictor=Predictor,SAM3SemanticPredictor=Predictor))
    path=tmp_path/'existing.pt';path.write_bytes(b'synthetic fixture')
    model=SAM31(path)
    image=Image.new('RGB',(7,5),(1,2,3))
    masks,boxes,scores=model.predict_segmentation(image,'cup')
    assert masks[0].shape == (5,7) and scores[0] == .8
    model.predict_segmentation_with_point(image,point_coords=[[2,3]],point_labels=[1])
    assert seen==[{'text':['cup']},{'points':[[[2,3]]],'labels':[[1]]}]
    model.close()


def test_comfy_workflow_and_protected_composite(tmp_path):
    from real2sim_builder.comfy_edit import workflow, protect_pixels
    image=Image.new('RGB',(32,24),(20,30,40))
    edited=Image.new('RGB',(32,24),(200,100,0))
    mask=Image.new('L',image.size,0)
    mask.paste(255,(8,8,16,16))
    output=protect_pixels(image,edited,mask)
    a,b=np.asarray(image),np.asarray(output)
    assert np.array_equal(a[np.asarray(mask)==0],b[np.asarray(mask)==0])
    assert not np.array_equal(a[10,10],b[10,10])
    graph=workflow('input.png','remove cup',dict(unet='model.gguf',clip='clip.safetensors',t5='t5.safetensors',vae='ae.safetensors'),seed=0,size=512,steps=20)
    assert graph['1']['class_type']=='UnetLoaderGGUF'
    assert graph['8']['class_type']=='ReferenceLatent'
    assert graph['7']['inputs']['batch_size']==1
    assert graph['8']['inputs']['latent']==['6',0]
    assert graph['9']['inputs']['latent_image']==['7',0]


def test_local_comfy_rejects_remote_and_unknown_graph():
    from real2sim_builder.comfy_edit import validate_server
    for url in ['http://example.com:8188','http://127.0.0.1.evil:8188','http://user:pass@127.0.0.1:8188']:
        with pytest.raises(ValueError): validate_server(url)


def test_stage_3_5_dispatch_sam_then_cpu_and_6_8_stay_owned(tmp_path,monkeypatch):
    from real2sim_builder import stage_runtime,inference
    import json
    calls=[]
    class Project:
        def checkpoint(self):pass
    class Candidate:project=Project()
    config={'runtimes':{k:{'python':sys.executable}for k in ['sam3','pose','decomposition','image_edit']}}
    def run(project,python,kind,payload,folder,timeout,**kw):
        calls.append((kind,payload))
        (folder/'result.json').write_text(json.dumps({'execution':'real','status':'COMPLETE','data':{'from':kind}}))
    monkeypatch.setattr(inference,'_run_worker',run)
    monkeypatch.setattr(stage_runtime.subprocess,'check_output',lambda *a,**kw:'7000\n')
    for operation in ['support','segments','image_edit','cpd']:
        stage_runtime.invoke(Candidate(),config,operation,{},tmp_path/operation)
    assert [k for k,p in calls]==['support_masks','support_planes','segments_raw','segments_post','image_edit','cpd']
    assert calls[1][1]['sam_result']=={'from':'support_masks'}
    assert calls[3][1]['sam_result']=={'from':'segments_raw'}
