"""Literal prompt transport and typed Codex output; no real model calls."""
import copy,json,sys
import pytest
from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import read,write,sha
from real2sim_builder.evidence import save_scene_memo,scene_memo
from real2sim_builder.authoring import modeling_tasks,run_codex_modeling,parse_scene_analysis
from test_modeling_handoff import semantic_reply


def test_other_saved_photo_layouts_reach_codex_as_context_without_relabelling(tmp_path):
    from PIL import Image
    from real2sim_builder.observations import register_image
    project=Project.create(tmp_path,'all saved inputs');rows=[]
    for index,state in enumerate(('capture_layout','phone_reference')):
        file=tmp_path/f'{index}.png';Image.new('RGB',(20,20),(index,0,0)).save(file)
        rows.append(register_image(project,file,camera=f'camera{index}',camera_type='external',scene_state=state))
    original=sha(project.root/'input/evidence.yaml');candidate=Candidate.create(project,'analysis')
    modeling_tasks(candidate,{'scene_state_id':'capture_layout'}, {})
    task=read(candidate.root/'modeling/tasks.json')
    assert {r['image_id']for r in task['source_images']}=={r['id']for r in rows}
    reference=next(r for r in task['source_images']if r['image_id']==rows[1]['id'])
    assert reference['observation']['context_only']is True
    assert reference['observation']['scene_state_id']=='phone_reference'
    assert sha(project.root/'input/evidence.yaml')==original


def test_memo_dimensions_flow_through_codex_plan_without_measurement_form(tmp_path):
    from real2sim_builder.authoring import geometry_specs
    from real2sim_builder.initialization import measured_geometry
    p=Project.create(tmp_path,'memo sizes');text='cup height 100mm. board x 200mm. board y 150mm. board z 5mm.'
    memo=save_scene_memo(p,text);c=Candidate.create(p,'plan')
    geometry={'kind':'container','dimensions_m':[None,None,.1],'source':'user_memo',
              'evidence_quote':'cup height 100mm.','evidence':[],'wall_m':None,'support':'board',
              'measurement_claims':[{'field':'z','object_id':'cup','subject_quote':'cup','axis_quote':'height','statement_quote':'cup height 100mm.',
                  'value_quote':'100mm','value':'100','unit':'mm'}]}
    board={**geometry,'kind':'box','dimensions_m':[.2,.15,.005],'evidence_quote':text,'support':None,
        'measurement_claims':[{'field':axis,'object_id':'board','subject_quote':'board','axis_quote':axis,'statement_quote':f'board {axis} {n}mm.',
            'value_quote':f'{n}mm','value':str(n),'unit':'mm'}for axis,n in zip('xyz',[200,150,5])]}
    answer=semantic_reply([{'id':'cup','prompt':'cup','role':'receptacle','geometry':geometry},
                           {'id':'board','prompt':'board','role':'support_surface','geometry':board}],text)
    modeling_tasks(c,{},{});fake=tmp_path/'codex';fake_cli(fake,text,json.dumps(answer))
    run_codex_modeling(c,executable=fake,timeout_s=10)
    config=read(p.root/'input/reconstruction.yaml')
    assert 'measurements'not in config
    specs=geometry_specs(config,c.scene)
    assert specs[0]['dimensions_m']==[None,None,.1] and specs[0]['provenance']=='measured'
    scene=measured_geometry(c.scene,specs)
    assert next(o for o in scene['objects']if o['id']=='board')['dimensions']['value']==[.2,.15,.005]
    assert next(o for o in scene['objects']if o['id']=='cup')['dimensions']['value']is None
    assert config['fitting']['supports']['cup']['support']=='board'
    assert config['fitting']['supports']['cup']['status']=='PROPOSED'
    job=modeling_tasks(c,config,{})
    task=read(c.root/'modeling/tasks.json')
    assert next(g for g in task['objects']if g['object_id']=='cup')['measurements']['dimensions_m']==[None,None,.1]
    assert scene_memo(p)==memo


@pytest.mark.parametrize('bad',('quote','negative','nan','boolean','support'))
def test_invalid_dimension_plan_is_rejected_without_natural_language_guessing(tmp_path,bad):
    p=Project.create(tmp_path,'invalid size');memo=save_scene_memo(p,'height 100mm')
    geometry={'kind':'container','dimensions_m':[None,None,.1],'source':'user_memo',
              'evidence_quote':'height 100mm','evidence':[],'wall_m':None,'support':None}
    if bad=='quote':geometry['evidence_quote']='different sentence'
    elif bad=='negative':geometry['dimensions_m'][2]=-.1
    elif bad=='nan':geometry['dimensions_m'][2]=float('nan')
    elif bad=='boolean':geometry['dimensions_m'][2]=True
    else:geometry['support']='absent'
    answer=semantic_reply([{'id':'cup','prompt':'cup','role':'receptacle','geometry':geometry}],memo['text'])
    with pytest.raises(ValueError):parse_scene_analysis(answer,memo)


def test_estimates_cannot_replace_preserved_dimensions(tmp_path):
    from real2sim_builder.authoring import geometry_specs
    from real2sim_builder.initialization import measured_geometry
    p=Project.create(tmp_path,'protected');c=Candidate.create(p,'plan')
    measured={'id':'cube','kind':'box','dimensions_m':[.03]*3,'evidence':['caliper']}
    scene=measured_geometry(c.scene,[measured])
    config={'objects':{'cube':{'geometry':{**measured,'dimensions_m':[.05]*3,'provenance':'estimated'}}}}
    with pytest.raises(ValueError,match='locked|conflict'):geometry_specs(config,scene)
    assert scene['objects'][0]['dimensions']['value']==[.03]*3


def reply_for(text):
    rows=[{'id':name,'prompt':'paper cup','role':'receptacle','asset_group':'cups',
           'group_sources':[{'quote':text}]}for name in('cup_left','cup_right')]
    return semantic_reply(rows,text)


@pytest.mark.parametrize('bad',('duplicate','unknown_group','missing_member','quote','sha','box','duplicate_view'))
def test_invalid_structured_analysis_cannot_modify_saved_objects(tmp_path,bad):
    p=Project.create(tmp_path,'bad answer');memo=save_scene_memo(p,'同じカップ。')
    answer=reply_for(memo['text'])
    if bad=='duplicate':answer['objects'].append(copy.deepcopy(answer['objects'][0]))
    elif bad=='unknown_group':answer['objects'][0]['asset_group']='missing'
    elif bad=='missing_member':answer['asset_groups'][0]['members'].pop()
    elif bad=='quote':answer['asset_groups'][0]['evidence_quote']='not in current text'
    elif bad=='sha':answer['scene_memo_sha256']='a'*64
    elif bad=='box':answer['objects'][0]['observations']=[{'image_id':'photo','box_xyxy':[20,10,1,2],'evidence':'image'}]
    else:answer['objects'][0]['observations']=[{'image_id':'photo','box_xyxy':None,'evidence':'image'}]*2
    before=scene_memo(p)
    with pytest.raises(ValueError):parse_scene_analysis(answer,memo,['photo'])
    assert scene_memo(p)==before


def fake_cli(path,expected,answer):
    path.write_text('#!'+sys.executable+'\n'+'''import json,sys
from pathlib import Path
args=sys.argv;root=Path(args[args.index('--cd')+1]);task=json.loads((root/'tasks.json').read_text())
assert task['scene_memo']['text']==EXPECTED
assert not any(p.suffix=='.json' for p in (root/'inputs').iterdir())
Path(args[args.index('--output-last-message')+1]).write_text(ANSWER)
'''.replace('EXPECTED',repr(expected)).replace('ANSWER',repr(answer)))
    path.chmod(0o700)


def test_fake_cli_receives_only_own_raw_memo_and_reuses_authenticated_response(tmp_path):
    from real2sim_builder.evidence import add_image
    from PIL import Image
    private=tmp_path/'private.json';private.write_text('{"not":"a modeling input"}')
    image=tmp_path/'rgb.png';Image.new('RGB',(32,24),'white').save(image)
    texts=['두 컵은 똑같고 위치만 달라.\r\n💜 '+str(private),'The paper cups have identical shapes.\n日本語もそのまま。']
    for index,text in enumerate(texts):
        p=Project.create(tmp_path/'scenes','scene'+str(index));save_scene_memo(p,text)
        add_image(p,image,'side','train');c=Candidate.create(p,'analysis')
        modeling_tasks(c,{},{});task=read(c.root/'modeling/tasks.json')
        fake=tmp_path/('fake'+str(index));fake_cli(fake,text,json.dumps(reply_for(text)))
        result=run_codex_modeling(c,executable=fake,timeout_s=10)
        assert result['status']=='ANALYZED_OBJECT_PROPOSALS'
        config=read(p.root/'input/reconstruction.yaml');response=p.root/config['scene_analysis']['path']
        assert sha(response)==config['scene_analysis']['sha256']
        assert config['objects']['cup_left']['asset_group_relation']['semantics_verified']is False
        # A repeated old handoff must reuse its response, not launch another child.
        fake.write_text('#!'+sys.executable+'\nraise AssertionError("duplicate remote request")\n')
        again=run_codex_modeling(c,executable=fake,timeout_s=10)
        assert again['reused']and again['objects']==config['objects']
        assert len(list((c.root/'modeling/codex').glob('*/answer.json')))==1
        response.write_bytes(b'{}')
        with pytest.raises(ValueError,match='response'):run_codex_modeling(c,executable=fake)
    assert private.read_text()=='{"not":"a modeling input"}'


def test_invalid_json_keeps_last_configuration_and_response_for_diagnosis(tmp_path):
    p=Project.create(tmp_path,'invalid JSON');save_scene_memo(p,'one cup')
    c=Candidate.create(p,'analysis');modeling_tasks(c,{},{});fake=tmp_path/'bad'
    fake_cli(fake,'one cup','{broken')
    with pytest.raises(ValueError):run_codex_modeling(c,executable=fake,timeout_s=10)
    assert not(p.root/'input/reconstruction.yaml').exists()
    assert next((c.root/'modeling/codex').glob('*/answer.json')).read_text()=='{broken'
    assert not c.scene['objects']


def test_manual_asset_choices_do_not_skip_a_new_uninterpreted_memo(tmp_path):
    from real2sim_builder.authoring import analysis_required
    memo=save_scene_memo(Project.create(tmp_path,'manual'),'Keep the asset; move the cups.')
    config={'objects':{'cup':{'prompt':'cup','asset_group':'cups','asset_manifest':'chosen/manifest.json'}}}
    assert analysis_required(config,memo['sha256'])


def test_handoff_text_cannot_disagree_with_frozen_memo_bytes(tmp_path):
    p=Project.create(tmp_path,'frozen text');save_scene_memo(p,'one real prompt')
    c=Candidate.create(p,'analysis');modeling_tasks(c,{},{});path=c.root/'modeling/tasks.json'
    task=read(path);task['scene_memo']['text']='a substituted prompt';write(path,task)
    fake=tmp_path/'must_not_run';fake_cli(fake,'a substituted prompt',json.dumps(semantic_reply([],'one real prompt')))
    with pytest.raises(ValueError,match='memo'):run_codex_modeling(c,executable=fake,timeout_s=10)
    assert not(c.root/'modeling/codex').exists()


def test_codex_child_receives_only_runtime_and_existing_login_environment(tmp_path,monkeypatch):
    from real2sim_builder.authoring import modeling_tasks,run_codex_modeling
    p=Project.create(tmp_path,'minimal child');save_scene_memo(p,'one cup')
    c=Candidate.create(p,'analysis');modeling_tasks(c,{},{})
    monkeypatch.setenv('PRIVATE_UNUSED_TOKEN','never-forward-this')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY','never-forward-that')
    fake=tmp_path/'check_env'
    fake.write_text('#!'+sys.executable+'\nimport os,sys,json\nfrom pathlib import Path\nassert "PRIVATE_UNUSED_TOKEN"not in os.environ and "AWS_SECRET_ACCESS_KEY"not in os.environ\nPath(sys.argv[sys.argv.index("--output-last-message")+1]).write_text('+repr(json.dumps(semantic_reply([],'one cup')))+')\n')
    fake.chmod(0o700);run_codex_modeling(c,executable=fake,timeout_s=10)


def test_analysis_can_reference_existing_robot_support_but_not_unknown_or_self(tmp_path):
    p=Project.create(tmp_path,'existing support');memo=save_scene_memo(p,'camera on robot')
    answer=semantic_reply([{'id':'camera','prompt':'camera','role':'fixture'}],memo['text'])
    answer['objects'][0]['support_relation']={'support':'robot_gripper_0','source':'visual_inference',
        'evidence_quote':'','evidence':['visible bracket on existing gripper'],'parallel':False}
    parsed=parse_scene_analysis(answer,memo,existing_objects=['robot_gripper_0'])
    assert parsed['camera']['support']['support']=='robot_gripper_0'
    assert parsed['camera']['support']['status']=='PROPOSED'
    for bad in ('absent','camera'):
        answer['objects'][0]['support_relation']['support']=bad
        with pytest.raises(ValueError,match='Unknown/self support'):
            parse_scene_analysis(answer,memo,existing_objects=['robot_gripper_0'])


def test_model_references_reach_blender_handoff_without_geometry_observations(tmp_path):
    from PIL import Image
    from real2sim_builder.authoring import modeling_groups
    from real2sim_builder.observations import register_image,input_images
    p=Project.create(tmp_path/'scenes','model reference');file=tmp_path/'wrist_camera_img1.jpg'
    Image.new('RGB',(40,30),'blue').save(file)
    row=register_image(p,file,camera='unassigned_view_001',camera_type='external',scene_state='reference',role='model_reference')
    c=Candidate.create(p,'same');groups,_=modeling_groups(c,{'objects':{'camera':{'prompt':'camera',
        'model_references':[{'image_id':row['id'],'evidence':'same camera housing visible','status':'LINKED'}]}}},{})
    reference=groups['camera']['references'][0]
    assert reference['image_id']==row['id']and reference['role']=='model_reference'
    assert reference['depth_batches']==[]and groups['camera']['geometry_observations']==[]
    assert input_images(p,'reference')[0]==[]


def test_model_reference_links_are_object_scoped_and_ambiguity_does_not_become_identity(tmp_path):
    from PIL import Image
    from real2sim_builder.authoring import modeling_groups
    from real2sim_builder.observations import register_image
    p=Project.create(tmp_path/'scenes','links');file=tmp_path/'unrelated_name.jpg'
    Image.new('RGB',(40,30),'blue').save(file)
    row=register_image(p,file,camera='ref',camera_type='external',scene_state='refs',role='model_reference')
    specs={'camera':{'prompt':'camera','model_references':[{'image_id':row['id'],'evidence':'visible housing','status':'LINKED'}]},
           'cup':{'prompt':'cup','model_references':[]}}
    groups,_=modeling_groups(Candidate.create(p,'same'),{'objects':specs},{})
    assert [r['image_id']for r in groups['camera']['references']]==[row['id']]
    assert groups['cup']['references']==[]
    specs['camera']['model_references'][0]['image_id']='missing'
    with pytest.raises(ValueError,match='reference'):modeling_groups(Candidate(p,'same'),{'objects':specs},{})


def test_changed_trusted_guidance_invalidates_analysis_not_existing_asset_bytes(tmp_path,monkeypatch):
    from real2sim_builder import authoring
    p=Project.create(tmp_path,'policy');memo=save_scene_memo(p,'camera')
    c=Candidate.create(p,'same');modeling_tasks(c,{},{});fake=tmp_path/'codex'
    fake_cli(fake,'camera',json.dumps(semantic_reply([{'id':'camera','prompt':'camera','role':'fixture'}],'camera')))
    run_codex_modeling(c,executable=fake,timeout_s=10)
    config=read(p.root/'input/reconstruction.yaml')
    assert not authoring.analysis_required(config,memo['sha256'],project=p)
    original=authoring._codex_guidance
    def changed():
        content,record=original();return content+b'\nnew policy',dict(record,sha256='f'*64)
    monkeypatch.setattr(authoring,'_codex_guidance',changed)
    assert authoring.analysis_required(config,memo['sha256'],project=p)


def test_refit_without_a_saved_plan_analyzes_source_ids_into_candidate_only(tmp_path):
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'scenes','old package');p.save_scene(legacy_scene());c=Candidate.create(p,'refined')
    config={'refit_mode':True,'scene_state_id':'layout','reconstruction_memo':{'text':'gripper too small'}}
    write(c.root/'reconstruction-config.yaml',config)
    task=modeling_tasks(c,config,{})
    assert task['status']=='WAITING_FOR_CODEX_ANALYSIS'
    fake=tmp_path/'codex';fake_cli(fake,'',json.dumps(semantic_reply([{'id':'block','prompt':'red block','role':'manipulable_object'}])))
    result=run_codex_modeling(c,executable=fake,timeout_s=10)
    assert read(result['configuration'])['objects']['block']['prompt']=='red block'
    assert not(p.root/'input/reconstruction.yaml').exists()
    assert c.scene==p.scene


def test_codex_first_does_not_copy_another_projects_inference_installation(tmp_path):
    from real2sim_builder.automation import _fitting_configuration
    config={'sam':{'python':'old','model':'old'},'geometry':{'backend':'mast3r_colmap'},'da3':{'python':'old'},'objects':{'block':{'prompt':'block'}}}
    result=_fitting_configuration(config,False)
    assert not set(result)&{'sam','geometry','da3','selections'}
    assert result['authoring_mode']=='codex'and result['objects']==config['objects']
    assert 'sam'in config
