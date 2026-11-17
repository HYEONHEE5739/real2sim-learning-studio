"""Capture JSON/YAML semantics and avoiding unnecessary metadata rewrites."""
import json
import pytest
from real2sim_builder import files


def test_json_capture_manifest_uses_json_parser_even_with_yaml_extension(tmp_path,monkeypatch):
    path=tmp_path/'capture_manifest.yaml'
    expected={'joint_mapping':{'values':[1.0,1e-20,None,True],'id':'yes'},'schema':'real2sim.snapshot/1'}
    path.write_text(json.dumps(expected))
    monkeypatch.setattr(files.yaml,'safe_load',lambda *_:pytest.fail('Capture JSON was needlessly parsed as YAML'))
    assert files.read(path)==expected


def test_yaml_block_and_flow_configuration_remain_supported(tmp_path):
    for text in ['role: follower\nids: [1, 2]\n','{role: follower, ids: [1, 2]}\n']:
        path=tmp_path/'settings.yaml';path.write_text(text)
        assert files.read(path)=={'role':'follower','ids':[1,2]}


def test_unpaired_capture_publication_keeps_the_sealed_manifest_bytes(tmp_path):
    from pathlib import Path
    from test_capture_save_continuity import active_session
    from real2sim_builder.capture import load_session
    with active_session(tmp_path,'scene_prepare')as(session,events,pending):
        before=(Path(pending['staging'])/'capture_manifest.yaml').read_bytes()
        result=session.store.finish(pending)
        assert (Path(result['path'])/'capture_manifest.yaml').read_bytes()==before
        manifest,rows,_=load_session(result['path'])
        assert manifest['schema']=='real2sim.snapshot/1'
        assert rows[0]['q_measured']==pending['sample']['q_measured']


def test_paired_capture_uses_fast_lossless_png_for_generated_diagnostics(tmp_path,monkeypatch):
    import numpy as np
    from pathlib import Path
    from PIL import Image
    from robot_learning_workbench.robot.pairs import write_pair
    from robot_learning_workbench.data.native import atomic_json
    root=tmp_path/'shot';root.mkdir();rgb=np.full((48,64,3),90,np.uint8)
    for camera in('side','wrist'):Image.fromarray(rgb).save(root/(camera+'.png'))
    atomic_json(root/'metadata.json',{'files':{},'images':[{'camera':n,'path':n+'.png'}for n in('side','wrist')]})
    manifest={'project_id':'test','snapshots':[{'path':'.'}]};pending={'sample':{'q_measured':[0.]*6,'timestamp_ns':1},'quality':[]}
    rendered={'images':dict.fromkeys(('side','wrist'),rgb),'measured_q_rad':[0.]*6,'applied_sim_joint_rad':[0.]*6,'scene_identity':{'manifest_sha256':'a'*64}}
    options=[];save=Image.Image.save
    def encode(image,path,*args,**kwargs):options.append((Path(path),kwargs.get('compress_level',6)));return save(image,path,*args,**kwargs)
    monkeypatch.setattr(Image.Image,'save',encode)
    write_pair(root,manifest,pending,rendered)
    assert len(options)==8 and all(level==1 for _,level in options),'Pair diagnostics still use slow default PNG compression'
    assert np.array_equal(np.asarray(Image.open(root/'comparison/side/side_by_side.png')),np.concatenate([rgb,rgb],axis=1))
