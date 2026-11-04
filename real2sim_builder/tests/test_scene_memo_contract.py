"""Literal prompt transport and typed Codex output; no real model calls."""
import copy,json,sys
import pytest
from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import read,write,sha
from real2sim_builder.evidence import save_scene_memo,scene_memo
from real2sim_builder.automation import modeling_tasks,run_codex_modeling,parse_scene_analysis
from test_modeling_handoff import semantic_reply


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
    from real2sim_builder.automation import analysis_required
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
