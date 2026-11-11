"""Offline contracts for the shared Codex CLI, never a live model request."""
import json
import subprocess
from pathlib import Path
import pytest
from real2sim_builder import codex_cli


def test_image_capability_requires_selected_model_modalities(tmp_path,monkeypatch):
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path))
    (tmp_path/'models_cache.json').write_text(json.dumps({'models':[{'slug':'vision','input_modalities':['text','image']},{'slug':'text','input_modalities':['text']}]}))
    assert codex_cli.image_supported('vision',[]) is True
    assert codex_cli.image_supported('text',[]) is False
    assert codex_cli.image_supported('unknown',[]) is False


def test_shared_process_collects_quota_without_raw_account_text(tmp_path):
    program=tmp_path/'fake';program.write_text('#!/usr/bin/env python3\nimport json\nprint(json.dumps({"type":"turn.failed","error":{"code":"quota_exceeded","message":"SECRET_ACCOUNT"}}))\nraise SystemExit(2)\n');program.chmod(0o755)
    with pytest.raises(codex_cli.CodexExecutionError)as error:
        codex_cli.execute([str(program)],tmp_path,tmp_path,10,lambda:None,{'model':'test'})
    assert error.value.code=='USAGE_LIMIT' and error.value.remote_attempted
    assert 'SECRET_ACCOUNT'not in (tmp_path/'codex.log').read_text()


def test_visual_schema_rejects_incomplete_or_unexpected_answer():
    schema={'type':'object','properties':{'removed':{'enum':['yes','no']}},'required':['removed'],'additionalProperties':False}
    codex_cli.validate_answer({'removed':'yes'},schema)
    for answer in [{},{'removed':True},{'removed':'yes','invented':1}]:
        with pytest.raises(ValueError):codex_cli.validate_answer(answer,schema)


def test_visual_job_uses_shared_cli_images_and_schema_without_live_call(tmp_path,monkeypatch):
    from real2sim_builder.authoring import run_codex_vlm
    from real2sim_builder.project import Project,Candidate
    from PIL import Image
    import sys
    p=Project.create(tmp_path/'projects','visual');c=Candidate.create(p,'test')
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path/'auth'))
    monkeypatch.setenv('REAL2SIM_CODEX_MODEL','vision');monkeypatch.setenv('REAL2SIM_CODEX_EFFORT','low')
    fake=tmp_path/'fake-codex';fake.write_text('#!'+sys.executable+'\n'+'''import sys,json
from pathlib import Path
a=sys.argv
assert a.count('--image')==3
assert '--output-schema'in a and 'model_reasoning_effort="low"'in a
work=Path(a[a.index('--cd')+1]);assert (work/'BUILDER_GUIDE.md').is_file()
assert not list(work.rglob('auth.json'))
Path(a[a.index('--output-last-message')+1]).write_text('{"removed":"no"}')
''');fake.chmod(0o755)
    monkeypatch.setattr(codex_cli,'executable',lambda:str(fake))
    monkeypatch.setattr(codex_cli,'capabilities',lambda _:dict(version='fake',images=True,structured_output=True,vlm_policy=True))
    monkeypatch.setattr(codex_cli,'snapshot',lambda _:dict(logged_in=True,models=[dict(model='vision',inputModalities=['image'],supportedReasoningEfforts=[dict(reasoningEffort='low')])]))
    rgb=tmp_path/'rgb.png';Image.new('RGB',(12,8)).save(rgb)
    result=run_codex_vlm(c,{'images':[str(rgb)]*3,'prompt':'Review target','response_schema':{'type':'object','properties':{'removed':{'enum':['yes','no']}},'required':['removed'],'additionalProperties':False}},c.root/'visual')
    assert result['answer']=={'removed':'no'} and result['runtime']['model']=='vision'
    assert (c.root/'visual/status.json').is_file()
    from real2sim_builder.stage_artifacts import StageNeeds
    monkeypatch.setenv('REAL2SIM_CODEX_EFFORT','unsupported')
    with pytest.raises(StageNeeds,match='selection'):
        run_codex_vlm(c,{'images':[str(rgb)],'prompt':'Review','response_schema':{'type':'object'}},c.root/'unsupported')


def test_runtime_identity_tracks_selection_and_legacy_config_cannot_fall_back(monkeypatch,tmp_path):
    from real2sim_builder.stage_runtime import identity,invoke
    from real2sim_builder.stage_artifacts import StageNeeds
    from types import SimpleNamespace
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path/'auth'))
    monkeypatch.setenv('REAL2SIM_CODEX_MODEL','vision')
    a=identity({},'vlm');monkeypatch.setenv('REAL2SIM_CODEX_EFFORT','high');b=identity({},'vlm')
    assert a!=b and b['reasoning_effort']=='high'
    with pytest.raises(StageNeeds,match='LEGACY_VLM_CONFIG'):
        invoke(SimpleNamespace(),{'runtimes':{'vlm':{'model_options':{'model':'gemini-old'}}}},'vlm',{},tmp_path/'unused')
    assert not(tmp_path/'unused').exists()


@pytest.mark.parametrize('failure',['stop','timeout'])
def test_shared_execution_stops_owned_child_and_preserves_sanitized_record(tmp_path,failure):
    import sys
    def checkpoint():
        if failure=='stop'and (tmp_path/'ready').exists():raise InterruptedError('controlled stop')
    command=[sys.executable,'-c',"from pathlib import Path;import time;Path('ready').touch();time.sleep(20)"]
    with pytest.raises(InterruptedError if failure=='stop'else TimeoutError):
        codex_cli.execute(command,tmp_path,tmp_path,.2,checkpoint,{'model':'fake'})
    from real2sim_builder.files import read
    assert read(tmp_path/'codex.log')['returncode']is not None


def test_stored_legacy_geometry_is_readable_but_execution_fails_before_writes(tmp_path):
    from real2sim_builder import inference
    from real2sim_builder.files import write,read,sha
    path=tmp_path/'metadata.json';legacy={'backend':'mast3r_colmap','common_frame':'original','calibrated':False}
    write(path,legacy);before=sha(path)
    with pytest.raises(ValueError,match='LEGACY_GEOMETRY_UNSUPPORTED'):
        inference.run_models(None,{'geometry':legacy})
    assert read(path)==legacy and sha(path)==before


def test_front_selection_uses_codex_and_keeps_ambiguous_geometry(tmp_path):
    from real2sim_builder.stage_runtime import invoke
    from types import SimpleNamespace
    import numpy as np
    calls=[]
    def provider(op,request,folder):
        calls.append(op)
        if op=='front_views':return {'views':[{'label':'A','azimuth_deg':0,'path':'renderA.png'},{'label':'B','azimuth_deg':45,'path':'renderB.png'}]}
        assert request['task']=='semantic_front'and request['response_schema']['required']==['choice','uncertain','reason','evidence']
        return {'answer':{'choice':'NONE','uncertain':True,'reason':'symmetric','evidence':['no front']}}
    result=invoke(SimpleNamespace(),{},'canonicalize',{'mesh':'native.obj','tilt_rotation':np.eye(3).tolist(),'refine':True},tmp_path/'front',provider=provider)
    assert calls==['front_views','vlm'] and result['front']['status']=='ambiguous'
    np.testing.assert_array_equal(result['rotation'],np.eye(3))
    assert not result['semantic_front_verified']


def test_validated_stage5_analysis_skips_repeat_analysis_and_detects_changed_sources(tmp_path):
    from real2sim_builder.authoring import analysis_required,_codex_guidance
    from real2sim_builder.files import sha,write
    source=tmp_path/'photo.png';source.write_bytes(b'original observation')
    answer=tmp_path/'answer.json';write(answer,{'objects':[]})
    config={'objects':{'cup':{'prompt':'cup'}},'stage_scene_analysis':{'path':str(answer),'sha256':sha(answer),
        'stage_source_views_sha256':__import__('real2sim_builder.stage_artifacts',fromlist=['digest']).digest([]),
        'memo_sha256':'memo','guidance_sha256':_codex_guidance()[1]['sha256'],
        'source_images':[{'path':str(source),'sha256':sha(source)}]}}
    assert not analysis_required(config,'memo')
    assert analysis_required(config,'changed memo')
    source.write_bytes(b'changed observation')
    with pytest.raises(ValueError,match='source changed'):analysis_required(config,'memo')


def test_account_poll_timestamps_do_not_invalidate_visual_input_identity(tmp_path,monkeypatch):
    from real2sim_builder.stage_runtime import identity
    monkeypatch.setenv('REAL2SIM_CODEX_HOME',str(tmp_path));monkeypatch.setenv('REAL2SIM_CODEX_MODEL','vision')
    catalog=tmp_path/'models_cache.json';metadata={'models':[{'slug':'vision','input_modalities':['text','image']}],'fetched_at':'old','identity':'old account'}
    catalog.write_text(json.dumps(metadata));before=identity({},'vlm')
    metadata.update(fetched_at='new',identity='another account');catalog.write_text(json.dumps(metadata))
    assert identity({},'vlm')==before
    metadata['models'][0]['input_modalities']=['text'];catalog.write_text(json.dumps(metadata))
    assert identity({},'vlm')!=before


def test_stage5_review_receives_before_mask_after_and_blocks_uncertain_edit(tmp_path):
    from real2sim_builder.reconstruction_stages import decompose
    from real2sim_builder.stage_artifacts import StageNeeds
    from types import SimpleNamespace
    from PIL import Image
    import numpy as np
    p=SimpleNamespace(root=tmp_path/'project',evidence={'images':[]},checkpoint=lambda:None)
    candidate=SimpleNamespace(project=p,scene={'frames':{}})
    rgb=np.full((32,48,3),150,np.uint8);rgb[10:22,16:30]=[220,30,20]
    mask=np.zeros((32,48),np.uint8);mask[10:22,16:30]=255
    mask_path=tmp_path/'mask.png';Image.fromarray(mask).save(mask_path)
    pred=tmp_path/'input.npz';np.savez(pred,image=rgb[None],depth=np.ones((1,32,48)),intrinsics=np.array([[[60,0,24],[0,60,16],[0,0,1]]]))
    seen=[]
    def provider(op,request,folder):
        folder.mkdir(parents=True,exist_ok=True);seen.append(op)
        if op=='vlm'and request.get('task')=='scene_instances':
            return {'answer':{'objects':[{'id':'cube','prompt':'red cube','role':'manipulable_object','box_xyxy':[16,10,30,22]}]}}
        if op=='segments':return {'objects':[{'id':'cube','path':str(mask_path),'status':'UNIQUE_ESTIMATED'}]}
        if op=='removal':return {'order':['cube']}
        if op=='image_edit':
            result=folder/'edited.png';Image.new('RGB',(48,32),(150,150,150)).save(result)
            return {'path':str(result),'raw_path':str(result),'provider':'comfy_gguf'}
        if op=='vlm':
            assert request['task']=='removal_validity'and len(request['images'])==3
            assert Image.open(request['images'][1]).mode=='L'
            assert request['context']['pixel_evidence']
            return {'answer':dict(removed='yes',object_remaining='no',other_objects_preserved='yes',background_continuous='no',uncertain=True,reason='boundary uncertain',evidence=['synthetic boundary'])}
        pytest.fail('No depth or other model after uncertain removal')
    stage=tmp_path/'stage';stage.mkdir()
    previous={1:{'frames':[]},2:{'prediction':str(pred)},3:{'selected_index':0,'selected_frame_id':'frame'},4:{'camera_to_support':np.eye(4).tolist()}}
    with pytest.raises(StageNeeds,match='uncertain or conflicting'):decompose(candidate,{},previous,stage,provider)
    assert seen==['vlm','segments','removal','image_edit','vlm']
