from pathlib import Path
from PIL import Image
import pytest
from real2sim_builder.project import Project
from real2sim_builder.candidate import Candidate
from real2sim_builder.files import read,sha


def test_actual_artifacts_and_first_scene_remain_immutable_across_resume(tmp_path):
    from real2sim_builder.visual_evidence import record,freeze_scene
    project=Project.create(tmp_path,'Evidence')
    candidate=Candidate.create(project,'auto')
    image=candidate.root/'render.png';Image.new('RGB',(32,24),'red').save(image)
    first=freeze_scene(candidate,'03_first_scene',images=[image],summary='First actual render')
    original=sha(first/'scene_state.json');rendered=sha(first/'artifacts/render.png')
    Image.new('RGB',(32,24),'blue').save(image)
    again=freeze_scene(candidate,'03_first_scene',images=[image],summary='Resume')
    assert first==again and sha(first/'scene_state.json')==original
    assert sha(first/'artifacts/render.png')==rendered!=sha(image)
    stopped=record(candidate,'04_iterations','STOPPED',summary='Interrupted before next render')
    index=read(candidate.root/'evidence/index.json')
    assert [r['status']for r in index['stages']]==['COMPLETE','STOPPED']
    assert index['stages'][0]['images'][0]['sha256']==rendered
    assert (candidate.root/'evidence/index.html').is_file()
    assert not list(stopped.glob('*.png'))


def test_evidence_does_not_fabricate_images_or_accept_escape_or_symlinks(tmp_path):
    from real2sim_builder.visual_evidence import record
    project=Project.create(tmp_path/'projects','Evidence')
    candidate=Candidate.create(project,'auto')
    missing=candidate.root/'missing.png'
    with pytest.raises(ValueError,match='Missing'):record(candidate,'01_scene_analysis','COMPLETE',images=[missing])
    outside=tmp_path/'outside.png';Image.new('RGB',(5,5)).save(outside)
    with pytest.raises(ValueError,match='outside'):record(candidate,'01_scene_analysis','COMPLETE',images=[outside])
    link=candidate.root/'link.png';link.symlink_to(outside)
    with pytest.raises(ValueError,match='symlink|outside'):record(candidate,'01_scene_analysis','COMPLETE',images=[link])
    with pytest.raises(ValueError):record(candidate,'../../escape','COMPLETE')
    assert not(candidate.root/'evidence/index.json').exists()


def test_evidence_index_escapes_model_text_and_records_files_sha(tmp_path):
    from real2sim_builder.visual_evidence import record
    project=Project.create(tmp_path,'Evidence');candidate=Candidate.create(project,'auto')
    script=candidate.root/'author.py';script.write_text('# retained actual Blender script\n')
    stage=record(candidate,'02_object_modeling','FAILED',files=[script],summary='<script>bad()</script>',details={'reused':False,'unverified':['back side']})
    entry=read(stage/'stage.json');assert entry['files'][0]['sha256']==sha(script)
    html=(candidate.root/'evidence/index.html').read_text()
    assert '<script>bad()'not in html and '&lt;script&gt;'in html
    assert entry['status']=='FAILED'and not entry['images']


def test_new_memo_keeps_the_old_first_scene_and_creates_a_distinct_run(tmp_path):
    from real2sim_builder.visual_evidence import freeze_scene
    from real2sim_builder.evidence import save_scene_memo
    project=Project.create(tmp_path,'runs');candidate=Candidate.create(project,'auto')
    first=freeze_scene(candidate,'03_first_scene')
    save_scene_memo(project,'A different requested layout')
    second=freeze_scene(candidate,'03_first_scene')
    assert first!=second and(first/'checkpoint.json').is_file()
    stages=read(candidate.root/'evidence/index.json')['stages']
    assert stages[0]['run_identity']!=stages[1]['run_identity']


def test_checkpoint_json_retains_scientific_numeric_transform_values(tmp_path):
    from real2sim_builder.visual_evidence import freeze_scene
    from real2sim_builder.scene import value
    import numpy as np
    project=Project.create(tmp_path,'numeric evidence');candidate=Candidate.create(project,'auto')
    scene=candidate.scene;t=np.eye(4);t[0,3]=1e-7
    scene['frames']['estimate']={'parent':'world','transform':value(t.tolist(),'estimated')};candidate.save(scene)
    stage=freeze_scene(candidate,'03_first_scene')
    saved=read(stage/'scene_state.json')
    assert isinstance(saved['frames']['estimate']['transform']['value'][0][3],float)
    assert saved==candidate.scene
