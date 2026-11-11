from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import read,write,sha


def test_empty_inputs_keep_a_measured_draft_without_launching_models_or_export(tmp_path):
    from real2sim_builder.automation import reconstruct
    p=Project.create(tmp_path,'empty auto')
    config={'measurements':[{'id':'block','kind':'box','dimensions_m':[.03]*3,'evidence':['caliper']}],
            'objects':{'block':{'prompt':'red cube'}}}
    result=reconstruct(p,candidate='auto_1',config=config)
    assert result['status']=='NEEDS_MORE_DATA' and result['needs']
    c=Candidate(p,'auto_1');assert not c.scene['objects']  # No synthetic measured Object before Scene input preparation
    assert not(p.root/'working/current_scene.yaml').exists() and not list((p.root/'exports').iterdir())
    assert not(c.root/'.cache/inference/sam-job').exists()
    assert p.state['status']=='NEEDS_MORE_DATA'


def test_cli_reconstruction_uses_candidate_configuration_and_retains_original(tmp_path,capsys):
    from real2sim_builder.cli import main
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'cli auto');p.save_scene(legacy_scene());before=sha(p.root/'working/current_scene.yaml')
    config=tmp_path/'configuration.yaml';write(config,{'objects':{'block':{'prompt':'cube'}}})
    assert main(['reconstruct',str(p.root),'--candidate','cli_auto','--config',str(config)])==2
    assert not(p.root/'input/reconstruction.yaml').exists()
    assert read(p.root/'scratch/agent/cli_auto/reconstruction-config.yaml')['objects']['block']['prompt']=='cube'
    assert sha(p.root/'working/current_scene.yaml')==before
    assert read(p.root/'scratch/agent/cli_auto/reconstruction.json')['physical_verified']is False


def test_board_pixel_binding_uses_existing_measured_world_geometry():
    from real2sim_builder.automation import board_binding
    from test_builder_export import legacy_scene
    import numpy as np
    scene=legacy_scene();uv=[[10,10],[100,10],[100,80],[10,80]]
    binding=board_binding(scene,'table',uv)
    np.testing.assert_allclose(binding['world_points_m'],[[-.5,-.4,0],[.5,-.4,0],[.5,.4,0],[-.5,.4,0]])
    assert binding['uv_px']==uv and binding['source']=='measured'


def test_pipeline_lock_can_nest_existing_candidate_operations_but_not_other_threads(tmp_path):
    from real2sim_builder.candidate import exclusive
    from concurrent.futures import ThreadPoolExecutor
    import pytest
    p=Project.create(tmp_path,'nested lock')
    with exclusive(p):
        c=Candidate.create(p,'nested')
        assert c.info['status']=='OPEN'and(p.root/'working/run.lock').exists()
        with ThreadPoolExecutor(1)as pool:
            future=pool.submit(Candidate.create,p,'concurrent')
            with pytest.raises(RuntimeError,match='busy'):future.result()
    assert not(p.root/'working/run.lock').exists()


def test_review_export_owns_cloud_and_mask_and_cannot_promote_the_draft(tmp_path):
    import numpy as np
    from PIL import Image
    import pytest
    from real2sim_builder.export import export_revision
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'review');p.save_scene(legacy_scene());c=Candidate.create(p,'draft')
    points=c.root/'points.npz';np.savez(points,points_world_m=np.ones((2,3)))
    mask=c.root/'mask.png';Image.new('L',(160,120),255).save(mask)
    scene=c.scene;scene['reconstruction_observations']={'clouds':[{
        'path':points.relative_to(p.root).as_posix(),'sha256':sha(points),
        'mask':mask.relative_to(p.root).as_posix(),'mask_sha256':sha(mask)}]}
    frozen=c.root/'configuration.yaml';write(frozen,{'objects':{'block':{'prompt':'cube'}}})
    scene['reconstruction_configuration']={'path':frozen.relative_to(p.root).as_posix(),'sha256':sha(frozen),'provenance':'derived'};c.save(scene)
    write(c.root/'metrics.json',{'scope':'train render only','images':[{}],'passed':False,'input_signature':p.signature(scene)})
    with pytest.raises(ValueError,match='Evaluate'):c.promote()
    destination=p.root/'exports/review';export_revision(p,destination=destination,candidate='draft',allow_unvalidated=True)
    exported=read(destination/'authored_scene.json')['reconstruction_observations']['clouds'][0]
    assert sha(destination/exported['path'])==sha(points)and sha(destination/exported['mask'])==sha(mask)
    frozen_export=read(destination/'authored_scene.json')['reconstruction_configuration']
    assert sha(destination/frozen_export['path'])==sha(frozen)


def test_mask_selection_preferences_do_not_rebase_the_current_scene_evidence(tmp_path):
    from real2sim_builder.authoring import save_configuration
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'preferences');p.save_scene(legacy_scene());before=p.signature()
    save_configuration(p,{'objects':{'block':{'prompt':'cube'}}})
    c=Candidate.create(p,'correction')
    save_configuration(p,{'objects':{'block':{'prompt':'cube'}},'selections':{'photo':{'block':1}}})
    assert p.signature()==before==c.info['base_signature']


def test_pair_refit_uses_manifest_source_instead_of_current_and_rejects_mixed_revisions(tmp_path,monkeypatch):
    from real2sim_builder.project import Project
    from real2sim_builder import automation
    from real2sim_builder.export import export_revision
    from real2sim_builder.files import write,sha,read
    from dataclasses import asdict
    import copy
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'projects','revision source');source=legacy_scene();p.save_scene(source)
    write(p.root/'working/validation/report.json',{'passed':False,'input_signature':p.signature()})
    package=p.root/'exports/first';identity=export_revision(p,destination=package,allow_unvalidated=True)
    from real2sim_builder.evidence import save_scene_memo,save_reconstruction_memo
    save_scene_memo(p,'original scene description')
    memo_before=sha(p.root/'input/scene_memo.txt')
    memo=save_reconstruction_memo(p,'The simulated gripper looks too small.',package/'scene.json')
    current=copy.deepcopy(source);current['objects'][1]['color']['value']=[.1,.9,.2]
    # Current changed independently after capture. The Pair must keep the first material.
    write(p.root/'working/current_scene.yaml',current);before=sha(p.root/'working/current_scene.yaml')
    pair={'id':'real1','scene_state_id':'layout','runtime_baseline':{'scene_identity':asdict(identity),
        'workspace_context':{'content_sha256':identity.manifest_sha256}},'q_measured':[0]*6}
    monkeypatch.setattr(automation,'_reconstruct',lambda project,**kw:{'status':'NEEDS_MORE_DATA','needs':[]})
    monkeypatch.setattr('real2sim_builder.observations.input_images',lambda *args:([pair],'layout',[]))
    result=automation.refit_pairs(p,candidate='refit',scene_state='layout',config={})
    assert result['source_revision']['identity']==asdict(identity)
    assert read(p.root/'scratch/agent/refit/candidate_scene.yaml')['objects'][1]['color']==source['objects'][1]['color']
    assert sha(p.root/'working/current_scene.yaml')==before
    again=automation.refit_pairs(p,candidate='refit',scene_state='layout',config={})
    assert again['source_revision']==result['source_revision']
    seen=[]
    def connected(project,**kwargs):
        seen.append(kwargs);return {'status':'NEEDS_MORE_DATA','needs':[]}
    monkeypatch.setattr(automation,'reconstruct',connected)
    automation.refit_pairs(p,candidate='refit',scene_state='layout',config={},run_modeling=True)
    assert seen[0]['run_modeling'] and seen[0]['refit_only']
    assert seen[0]['config']['image_ids']==['real1']
    assert seen[0]['config']['reconstruction_memo']==memo
    assert read(p.root/'scratch/agent/refit/reconstruction_memo.json')==memo
    assert sha(p.root/'input/scene_memo.txt')==memo_before
    assert sha(p.root/'working/current_scene.yaml')==before
    import json
    archived=p.root/'input/pair.json';write(archived,{'scene_identity':asdict(identity),'joint_mapping':{}})
    legacy=copy.deepcopy(pair);legacy['runtime_baseline'].pop('scene_identity')
    legacy['runtime_baseline'].update(pair_path='input/pair.json',pair_sha256=sha(archived))
    assert automation.pair_source(p,[legacy])[1]['identity']==asdict(identity)
    write(archived,{'scene_identity':{**asdict(identity),'revision':'changed'}})
    assert automation.pair_source(p,[legacy])[2]=='PAIR_SOURCE_MISMATCH'
    wrong=copy.deepcopy(pair);wrong['scene_state_id']='different_layout'
    monkeypatch.setattr('real2sim_builder.observations.input_images',lambda *args:([wrong],'layout',[]))
    assert automation.refit_pairs(p,candidate='wrong',scene_state='layout',config={})['code']=='PAIR_LAYOUT_MISMATCH'
    other=copy.deepcopy(pair);other['id']='real2';other['runtime_baseline']['scene_identity']['manifest_sha256']='a'*64
    monkeypatch.setattr('real2sim_builder.observations.input_images',lambda *args:([pair,other],'layout',[]))
    report=automation.refit_pairs(p,candidate='mixed',scene_state='layout',config={})
    assert report['status']=='NEEDS_MORE_DATA'and report['code']=='PAIR_SOURCE_MISMATCH'
    assert not(p.root/'scratch/agent/mixed').exists()
    selected=automation.refit_pairs(p,candidate='refit',scene_state='layout',config={'refit_source_identity':asdict(identity)})
    assert selected['source_revision']['identity']==asdict(identity)
    assert seen[-1]['config']['image_ids']==['real1']


def test_scene_memo_is_one_exact_text_with_legacy_read_only_restore(tmp_path):
    from real2sim_builder.evidence import scene_memo,save_scene_memo
    from real2sim_builder.project import Project
    from real2sim_builder.files import read,write,sha
    a=Project.create(tmp_path/'scenes','A');b=Project.create(tmp_path/'scenes','B')
    legacy=a.root/'input/notes/old.txt';legacy.parent.mkdir();legacy.write_bytes('과거 메모\r\n그대로'.encode())
    evidence=a.evidence;evidence['briefs']=[{'path':'input/notes/old.txt','sha256':sha(legacy)}];write(a.root/'input/evidence.yaml',evidence)
    before=sha(a.root/'input/evidence.yaml');assert scene_memo(a)['text']=='과거 메모\r\n그대로'
    assert sha(a.root/'input/evidence.yaml')==before
    text='두 컵은 같은 종이컵이야.\r\n  свободный текст 🙂\n'
    save_scene_memo(a,text);memo=scene_memo(a)
    assert memo['text']==text and memo['path']=='input/scene_memo.txt'
    assert (a.root/memo['path']).read_bytes()==text.encode('utf-8')
    stamp=(a.root/memo['path']).stat().st_mtime_ns;save_scene_memo(a,text)
    assert (a.root/memo['path']).stat().st_mtime_ns==stamp
    assert scene_memo(b)['text']==''and not scene_memo(b)['saved']
    save_scene_memo(a,'');assert scene_memo(a)['text']==''and scene_memo(a)['saved']
    assert legacy.read_bytes()=='과거 메모\r\n그대로'.encode()and sha(a.root/'input/evidence.yaml')==before


def test_missing_scene_photos_stops_before_models_and_preserves_changed_memo(tmp_path,monkeypatch):
    from real2sim_builder import automation
    from real2sim_builder.evidence import save_scene_memo
    p=Project.create(tmp_path,'memo first');save_scene_memo(p,'配置だけ変更。 Different cups now.')
    def forbidden(*a,**kw):raise AssertionError('Models must wait for current memo interpretation')
    monkeypatch.setattr('real2sim_builder.inference.run_models',forbidden)
    result=automation.reconstruct(p,candidate='fresh',config={'scene_analysis':{'memo_sha256':'old'},'objects':{'cup':{'prompt':'cup'}}})
    assert result['status']=='NEEDS_MORE_DATA'and result['failed_stage']==1
    c=Candidate(p,'fresh')
    assert (p.root/'input/scene_memo.txt').read_text()=='配置だけ変更。 Different cups now.'
    assert 'inference'not in result['stages']and not(c.root/'.cache/inference').exists()


def test_pair_refit_disables_dimension_changes_even_when_requested(tmp_path):
    from real2sim_builder.automation import _reconstruct
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'pair geometry');p.save_scene(legacy_scene())
    before=sha(p.root/'working/current_scene.yaml')
    _reconstruct(p,candidate='pair',config={'fitting':{'optimize_dimensions':True}},refit_only=True)
    frozen=read(p.root/'scratch/agent/pair/reconstruction-config.yaml')
    assert frozen['fitting']['optimize_dimensions'] is False
    assert sha(p.root/'working/current_scene.yaml')==before
