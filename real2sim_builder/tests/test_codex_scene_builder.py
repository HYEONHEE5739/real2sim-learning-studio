"""Advanced Codex/source-refit contracts retained alongside the default staged pipeline."""
import numpy as np
from PIL import Image
from real2sim_builder.project import Project
from real2sim_builder.candidate import Candidate
from real2sim_builder.files import read,sha
from test_builder_export import legacy_scene


def test_native_scene_render_and_first_checkpoint_need_no_depth_models(tmp_path,monkeypatch):
    from real2sim_builder.automation import _refit_reconstruct as reconstruct
    from real2sim_builder.observations import register_image
    from real2sim_builder.rendering import Renderer
    p=Project.create(tmp_path,'Codex native');p.save_scene(legacy_scene());scene=p.scene
    with Renderer(scene,p.root,tmp_path/'native')as renderer:real=renderer.rgb('side')
    path=tmp_path/'real.png';Image.fromarray(real).save(path)
    image=register_image(p,path,camera='side',camera_type='side',scene_state='layout')
    cam=scene['cameras'][0]
    plan={'object_poses':[],'cameras':[{'id':'side','frame':'world','pose':cam['pose']['value'],'K':cam['K']['value'],'distortion':cam['distortion']['value'],'resolution':cam['resolution'],'image_ids':[image['id']],'evidence':['existing calibrated camera']}],'needs':[]}
    def forbidden(*a,**kw):raise AssertionError('Retired inference backend must not be executed')
    monkeypatch.setattr('real2sim_builder.inference.run_models',forbidden)
    before=sha(p.root/'working/current_scene.yaml')
    result=reconstruct(p,candidate='auto',config={'objects':{'block':{'prompt':'block'}},'scene_state_id':'layout','scene_plan':plan,'sam':{'python':'missing'},'geometry':{'backend':'not-installed'}})
    assert result['stages']['first_scene']['status']=='RENDERED'
    c=Candidate(p,'auto');index=read(c.root/'evidence/index.json')
    first=next(s for s in index['stages']if s['id']=='03_first_scene')
    assert first['images']and(c.root/'evidence'/first['path']/'checkpoint.json').is_file()
    assert read(c.root/'metrics.json')['images'][0]['mae']==0
    assert not(c.root/'.cache/inference').exists()
    assert sha(p.root/'working/current_scene.yaml')==before
    assert not list((p.root/'exports').iterdir())


def test_existing_codex_boundary_gets_actual_images_for_typed_scene_composition(tmp_path):
    import json,sys
    from real2sim_builder.authoring import modeling_tasks,run_codex_modeling
    from real2sim_builder.observations import register_image
    from real2sim_builder.files import write
    p=Project.create(tmp_path,'actual image handoff');p.save_scene(legacy_scene());c=Candidate.create(p,'auto')
    path=tmp_path/'photo.png';Image.new('RGB',(160,120),(12,34,56)).save(path)
    image=register_image(p,path,camera='side',camera_type='side',scene_state='layout')
    cam=c.scene['cameras'][0]
    plan={'object_poses':[],'cameras':[{'id':'side','frame':'world','pose':cam['pose']['value'],'K':cam['K']['value'],'distortion':cam['distortion']['value'],'resolution':cam['resolution'],'image_ids':[image['id']],'evidence':['existing camera']}],'needs':[]}
    config={'authoring_mode':'codex','objects':{'block':{'prompt':'block'}},'scene_state_id':'layout'}
    write(c.root/'reconstruction-config.yaml',config);modeling_tasks(c,config,{})
    exe=tmp_path/'codex';exe.write_text('#!'+sys.executable+'\n'+'''import json,sys
from pathlib import Path
from PIL import Image
args=sys.argv;work=Path(args[args.index('--cd')+1]);assert '--image'in args
files=[Path(args[i+1])for i,a in enumerate(args)if a=='--image']
assert any(Image.open(p).convert('RGB').getpixel((0,0))==(12,34,56)for p in files)
assert (work/'BUILDER_GUIDE.md').is_file()and 'Read BUILDER_GUIDE.md'in args[-1]
schema=json.loads((work/'schema.json').read_text());assert 'object_poses'in schema['required']
Path(args[args.index('--output-last-message')+1]).write_text('''+repr(json.dumps(plan))+')\n');exe.chmod(0o700)
    result=run_codex_modeling(c,executable=exe,compose_scene=True)
    assert result['status']=='SCENE_COMPOSED'
    assert read(c.root/'review-config.yaml')['scene_plan']==plan
    entry=read(c.root/'evidence/index.json')['stages'][-1]
    assert entry['id']=='03_scene_composition'and entry['files']


def test_actual_native_iteration_preserves_first_before_after_and_best(tmp_path,monkeypatch):
    from real2sim_builder import authoring
    from real2sim_builder.automation import _refit_reconstruct as reconstruct
    from real2sim_builder.observations import register_image
    from real2sim_builder.rendering import Renderer
    scene=legacy_scene();scene['objects'][1]['pose']['provenance']='estimated'
    p=Project.create(tmp_path,'iterations');p.save_scene(scene)
    with Renderer(scene,p.root,tmp_path/'native')as renderer:real=renderer.rgb('side')
    imagepath=tmp_path/'real.png';Image.fromarray(real).save(imagepath)
    image=register_image(p,imagepath,camera='side',camera_type='side',scene_state='layout');cam=scene['cameras'][0]
    good=np.asarray(scene['objects'][1]['pose']['value']);bad=good.copy();bad[0,3]+=.04
    def plan(pose):return {'object_poses':[{'id':'block','pose':pose.tolist(),'image_ids':[image['id']],'evidence':['observed block position']}],
        'cameras':[{'id':'side','frame':'world','pose':cam['pose']['value'],'K':cam['K']['value'],'distortion':cam['distortion']['value'],'resolution':cam['resolution'],'image_ids':[image['id']],'evidence':['existing calibration']}],'needs':[]}
    decisions=[{'action':'numeric','objects':['block'],'evidence':[image['id']],'reason':'block is offset','scene_plan':plan(good)},
               {'action':'complete','objects':[],'evidence':[image['id']],'reason':'matches','scene_plan':None}]
    def judge(*a,**kw):assert kw.get('review_fitting');return {'status':'REVIEWED','decision':decisions.pop(0)}
    monkeypatch.setattr(authoring,'run_codex_modeling',judge)
    before=sha(p.root/'working/current_scene.yaml')
    result=reconstruct(p,candidate='auto',config={'objects':{'block':{'prompt':'block'}},'scene_state_id':'layout','scene_plan':plan(bad)},run_modeling=True)
    c=Candidate(p,'auto');assert result['status']=='VISUAL_DRAFT_REVIEWED'
    assert read(c.root/'metrics.json')['images'][0]['mae']==0
    first=next(r for r in read(c.root/'evidence/index.json')['stages']if r['id']=='03_first_scene')
    assert read(c.root/'evidence'/first['path']/'scene_state.json')['objects'][1]['pose']['value'][0][3]==.04
    iteration=next((c.root/'evidence/04_iterations').glob('iteration_*'))
    assert sha(next((iteration/'sim_before').glob('*.png')))!=sha(next((iteration/'sim_after').glob('*.png')))
    assert read(iteration/'changes.json')['applied']
    assert (iteration/'checkpoint.json').is_file()
    assert sha(p.root/'working/current_scene.yaml')==before


def test_unmeasured_physics_keeps_initial_native_contacts_but_never_claims_stepping(tmp_path):
    from real2sim_builder.validation import physics_probe
    p=Project.create(tmp_path,'initial contacts');scene=legacy_scene()
    result=physics_probe(p,scene,tmp_path/'physics')
    assert result['collision_query']['status']=='QUERIED'
    assert result['collision_query']['physics_steps']==0
    assert result['collision_query']['enabled_geometries']>0
    assert result['mujoco']['steps']==0 and not result['physical_verified']
    assert scene['objects'][1]['physics']['mass_kg']['value']is None


def test_entire_codex_loop_analyzes_authors_composes_and_reviews_using_actual_blender(tmp_path,monkeypatch):
    import sys,json
    from real2sim_builder import authoring
    from real2sim_builder.automation import _refit_reconstruct as reconstruct
    from real2sim_builder.observations import register_image
    from real2sim_builder.files import write
    p=Project.create(tmp_path,'complete loop');path=tmp_path/'real.png';Image.new('RGB',(160,120),'white').save(path)
    image=register_image(p,path,camera='photo',camera_type='external',scene_state='layout')
    config={'scene_state_id':'layout','geometry':{'backend':'retired'},'sam':{'python':'absent'}}
    write(p.root/'input/reconstruction.yaml',config)
    pose=np.eye(4);pose[:3,:3]=np.diag([1,-1,-1]);pose[2,3]=1
    plan={'object_poses':[{'id':'block','pose':np.eye(4).tolist(),'image_ids':[image['id']],'evidence':['visible cube']}],
        'cameras':[{'id':'photo','frame':'world','pose':pose.tolist(),'K':[[140,0,80],[0,140,60],[0,0,1]],'distortion':[0]*5,'resolution':[160,120],'image_ids':[image['id']],'evidence':['estimated photo']}],'lighting':None,'needs':[]}
    from test_modeling_handoff import semantic_reply
    reply=semantic_reply([{'id':'block','prompt':'white cube','role':'manipulable_object','observations':[{'image_id':image['id'],'box_xyxy':[40,20,120,100],'evidence':'visible cube'}]}])
    executable=tmp_path/'codex'
    executable.write_text('#!'+sys.executable+'\n'+'''import json,sys
from pathlib import Path
args=sys.argv;work=Path(args[args.index('--cd')+1]);schema=json.loads((work/'schema.json').read_text());props=schema['properties']
if 'scene_memo_sha256'in props:answer='''+repr(reply)+'''
elif 'object_poses'in props:answer='''+repr(plan)+'''
elif 'action'in props:answer={'action':'complete','objects':[],'evidence':['''+repr(image['id'])+'''],'reason':'visual draft reviewed','scene_plan':None}
else:
 (work/'author.py').write_text('import bpy\\nbpy.ops.mesh.primitive_cube_add(size=.03)\\nobj=bpy.context.object;obj["r2s_id"]="block"\\nbpy.ops.mesh.primitive_cube_add(size=.03)\\ncol=bpy.context.object;col.parent=obj;col["r2s_collision"]=True\\n')
 answer={'script':'author.py'}
Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(answer))
''');executable.chmod(0o700)
    run=authoring.run_codex_modeling
    monkeypatch.setattr(authoring,'run_codex_modeling',lambda candidate,**kw:run(candidate,executable=executable,**kw))
    result=reconstruct(p,candidate='auto',config=config,run_modeling=True,max_modeling_calls=4)
    assert result['status']=='VISUAL_DRAFT_REVIEWED'
    assert result['modeling_calls']==3 and result['review_calls']==1
    c=Candidate(p,'auto');stages=read(c.root/'evidence/index.json')['stages']
    assert {'01_scene_analysis','02_object_modeling','03_scene_composition','03_first_scene','06_final_comparison'}<={s['id']for s in stages}
    model=next(s for s in stages if s['id']=='02_object_modeling'and s['status']=='COMPLETE')
    assert len(model['images'])==4
    assert read(p.root/'input/reconstruction.yaml')==config
    assert not(c.root/'.cache/inference').exists()


def test_current_evidence_never_labels_stale_preview_as_a_new_render(tmp_path):
    from real2sim_builder.automation import _refit_reconstruct as reconstruct
    from real2sim_builder.observations import register_image
    from real2sim_builder.rendering import Renderer
    p=Project.create(tmp_path,'stale preview');p.save_scene(legacy_scene());c=Candidate.create(p,'auto')
    with Renderer(p.scene,p.root,tmp_path/'native')as renderer:rgb=renderer.rgb('side')
    real=tmp_path/'real.png';Image.fromarray(rgb).save(real)
    image=register_image(p,real,camera='side',camera_type='side',scene_state='layout')
    stale=c.root/'fitting/final/previews/old_view/sim.png';stale.parent.mkdir(parents=True);Image.new('RGB',(160,120),'red').save(stale)
    result=reconstruct(p,candidate='auto',config={'objects':{'block':{'prompt':'block'}},'scene_state_id':'layout','scene_plan':{'object_poses':[],'cameras':[],'needs':[]}})
    index=read(c.root/'evidence/index.json')
    for stage in index['stages']:
        assert all('old_view'not in r['source']for r in stage['images'])
    assert stale.is_file()  # Historical bytes remain available.


def test_existing_candidate_asset_is_preserved_when_new_analysis_changes_category_words(tmp_path):
    from real2sim_builder.authoring import modeling_tasks,record_modeling_results,attach_modeled_assets
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','reuse existing');c=Candidate.create(p,'auto')
    record=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='block')
    old={'authoring_mode':'codex','objects':{'block':{'prompt':'red cube','category':'cube'}}}
    modeling_tasks(c,old,{})
    record_modeling_results(c,[record]);attach_modeled_assets(c,old,{})
    before=c.scene['objects'][0]['object_asset']
    new={'authoring_mode':'codex','objects':{'block':{'prompt':'red cube with hole','category':'colored block'}}}
    result=modeling_tasks(c,new,{})
    assert result['status']=='ASSETS_READY'and not result['pending']
    assert c.scene['objects'][0]['object_asset']==before
    new['objects']['block']['modeling_action']='new'
    assert modeling_tasks(c,new,{})['status']=='WAITING_FOR_CODEX'


def test_codex_modeling_review_never_reads_retired_cached_inference(tmp_path):
    from real2sim_builder.authoring import modeling_tasks
    from real2sim_builder.files import write
    p=Project.create(tmp_path,'no stale inference');c=Candidate.create(p,'auto')
    write(c.root/'.cache/inference/results.json',{'segments':[{'image_id':'nonexistent','object_id':'block'}],'depth_batches':[{'path':'missing'}]})
    before=sha(c.root/'.cache/inference/results.json')
    modeling_tasks(c,{'authoring_mode':'codex','objects':{'block':{'prompt':'block'}}},None)
    task=read(c.root/'modeling/tasks.json')
    assert task['groups']['block']['references']==[]
    assert sha(c.root/'.cache/inference/results.json')==before


def test_stop_in_physics_still_has_the_first_rendered_scene_checkpoint(tmp_path,monkeypatch):
    from real2sim_builder.automation import _refit_reconstruct as reconstruct
    from real2sim_builder.observations import register_image
    from real2sim_builder.rendering import Renderer
    p=Project.create(tmp_path,'stop after render');p.save_scene(legacy_scene())
    with Renderer(p.scene,p.root,tmp_path/'native')as renderer:rgb=renderer.rgb('side')
    real=tmp_path/'real.png';Image.fromarray(rgb).save(real)
    register_image(p,real,camera='side',camera_type='side',scene_state='layout')
    def stop(*a,**k):raise InterruptedError('Stop before physics execution')
    monkeypatch.setattr('real2sim_builder.validation.physics_probe',stop)
    result=reconstruct(p,candidate='auto',config={'objects':{'block':{'prompt':'block'}},'scene_state_id':'layout','scene_plan':{'object_poses':[],'cameras':[],'needs':[]}})
    assert result['status']=='STOPPED'
    c=Candidate(p,'auto');first=next(r for r in read(c.root/'evidence/index.json')['stages']if r['id']=='03_first_scene')
    assert first['status']=='COMPLETE'
    assert (c.root/'evidence'/first['path']/'checkpoint.json').is_file()


def test_failed_remote_response_consumes_call_budget_and_retains_evidence(tmp_path,monkeypatch):
    import sys
    import pytest
    from real2sim_builder import authoring
    from real2sim_builder.automation import _refit_reconstruct as reconstruct
    p=Project.create(tmp_path,'failed remote');exe=tmp_path/'codex'
    exe.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index("--output-last-message")+1]).write_text("{}")\n');exe.chmod(0o700)
    run=authoring.run_codex_modeling
    monkeypatch.setattr(authoring,'run_codex_modeling',lambda c,**k:run(c,executable=exe,**k))
    with pytest.raises(ValueError):reconstruct(p,candidate='auto',config={},run_modeling=True,max_modeling_calls=1)
    c=Candidate(p,'auto');report=read(c.root/'reconstruction.json')
    assert report['modeling_calls']==1
    assert read(c.root/'evidence/index.json')['stages'][-1]['status']=='FAILED'
    result=reconstruct(p,candidate='auto',config={},run_modeling=True,max_modeling_calls=1)
    assert result['stop_reason']=='max_modeling_calls'


def test_native_initial_compile_keeps_camera_distortion_and_warps_actual_pixels(tmp_path):
    import copy
    from real2sim_builder.rendering import Renderer
    from real2sim_builder.cameras import distort_render
    from real2sim_builder.validation import physics_probe
    scene=legacy_scene();clean=copy.deepcopy(scene)
    scene['cameras'][0]['distortion']['value']=[.15,0,0,0,0]
    original=copy.deepcopy(scene);p=Project.create(tmp_path,'distorted camera')
    with Renderer(clean,p.root,tmp_path/'clean')as renderer:ideal=renderer.rgb('side')
    with Renderer(scene,p.root,tmp_path/'distorted')as renderer:actual=renderer.rgb('side')
    assert np.array_equal(actual,distort_render(scene['cameras'][0],ideal))
    assert not np.array_equal(actual,ideal)
    report=physics_probe(p,scene,tmp_path/'contacts')
    assert report['collision_query']['status']=='QUERIED'
    assert scene==original


def test_new_image_analysis_invalidates_previous_scene_composition(tmp_path):
    import sys,json
    from real2sim_builder.authoring import modeling_tasks,run_codex_modeling
    from real2sim_builder.files import write
    from real2sim_builder.observations import register_image
    from test_modeling_handoff import semantic_reply
    p=Project.create(tmp_path,'new camera evidence');c=Candidate.create(p,'auto')
    rgb=tmp_path/'front.png';Image.new('RGB',(160,120),'white').save(rgb)
    register_image(p,rgb,camera='front_ref',camera_type='external',scene_state='refs',role='model_reference')
    old={'authoring_mode':'codex','objects':{},'scene_plan':{'object_poses':[],'cameras':[],'needs':['old mount unresolved']}}
    write(c.root/'reconstruction-config.yaml',old);modeling_tasks(c,old,{})
    executable=tmp_path/'codex';executable.write_text('#!'+sys.executable+'\nimport sys,json\nfrom pathlib import Path\nargs=sys.argv\nPath(args[args.index("--output-last-message")+1]).write_text('+repr(json.dumps(semantic_reply([])))+')\n');executable.chmod(0o700)
    run_codex_modeling(c,executable=executable)
    updated=read(c.root/'review-config.yaml')
    assert 'scene_plan'not in updated
    assert updated['composition_feedback']['previous_plan']==old['scene_plan']


def test_actual_review_has_per_view_optical_pose_for_shared_mount_corrections(tmp_path):
    from real2sim_builder.observations import register_image
    from real2sim_builder.calibration.hybrid import alignment_metrics
    from real2sim_builder.rendering import Renderer
    scene=legacy_scene();p=Project.create(tmp_path,'review camera frame');p.save_scene(scene)
    with Renderer(scene,p.root,tmp_path/'native')as renderer:rgb=renderer.rgb('side')
    path=tmp_path/'real.png';Image.fromarray(rgb).save(path)
    register_image(p,path,camera='side',camera_type='side',scene_state='layout')
    from real2sim_builder.authoring import apply_scene_plan
    c=Candidate.create(p,'review')
    apply_scene_plan(c,{'object_poses':[],'cameras':[],'needs':[]},scene_state='layout')
    result=alignment_metrics(p,c.scene,p.root/'scratch/review')
    row=result['images'][0]
    assert row['render_context']['optical_convention']=='+X right, +Y down, +Z forward'
    assert np.allclose(row['render_context']['T_world_camera'],scene['cameras'][0]['pose']['value'])
    assert row['render_context']['camera_frame']=='world'


def test_ui_cli_configuration_is_an_override_not_a_project_input_edit(tmp_path,monkeypatch):
    from real2sim_builder.cli import main
    from real2sim_builder.files import write
    p=Project.create(tmp_path,'ui config protection')
    original={'objects':{},'scene_state_id':'saved'};write(p.root/'input/reconstruction.yaml',original)
    override=tmp_path/'ui-config.yaml';write(override,{'objects':{},'scene_state_id':'candidate'})
    before=sha(p.root/'input/reconstruction.yaml')
    def reconstruct(project,**kw):
        assert kw['config']['scene_state_id']=='candidate'
        return {'status':'NEEDS_MORE_DATA'}
    monkeypatch.setattr('real2sim_builder.automation.reconstruct',reconstruct)
    assert main(['reconstruct',str(p.root),'--candidate','auto','--config',str(override)])==2
    assert sha(p.root/'input/reconstruction.yaml')==before


def test_reused_attachment_does_not_undo_a_later_visual_pose_correction(tmp_path):
    from real2sim_builder.authoring import modeling_tasks,record_modeling_results,attach_modeled_assets
    from real2sim_builder.object_assets import register_object_asset
    from real2sim_builder.scene import value
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','attachment iteration');c=Candidate.create(p,'auto')
    scene=c.scene;scene['frames']['robot_link_gripper']={'parent':'world','transform':value(np.eye(4).tolist(),'derived',['FK'])};c.save(scene)
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='housing')
    attachment={'link':'gripper','T_link_object':np.eye(4).tolist(),'evidence':'visible rigid bracket','provenance':'estimated','physical_verified':False}
    config={'authoring_mode':'codex','objects':{'housing':{'prompt':'housing','robot_attachment':attachment}}}
    modeling_tasks(c,config,{});record_modeling_results(c,[asset]);attach_modeled_assets(c,config,{})
    pose=np.eye(4);pose[0,3]=.012;c.edit([{'op':'update_pose','id':'housing','value':pose.tolist(),'evidence':['rendered correction']}])
    attach_modeled_assets(c,config,{})
    assert c.scene['objects'][0]['frame']=='robot_link_gripper'
    assert c.scene['objects'][0]['pose']['value']==pose.tolist()
