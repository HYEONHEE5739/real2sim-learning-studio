import pytest
from real2sim_builder.authoring import review_decision


def test_review_action_is_typed_and_never_promotes_missing_camera_evidence():
    review={'objects':[{'id':'cup'}],'views':[{'image_id':'w'}],
            'camera_quality':{'status':'NOT_VERIFIED'}}
    answer={'action':'complete','objects':[],'evidence':['w'],'reason':'looks aligned'}
    assert review_decision(answer,review)['action']=='needs_data'
    answer.update(action='remodel',objects=['cup'])
    assert review_decision(answer,review)['objects']==['cup']
    answer['objects']=['missing']
    with pytest.raises(ValueError):review_decision(answer,review)


def test_review_runner_passes_comparisons_to_codex_and_does_not_run_blender(tmp_path):
    import sys
    from PIL import Image
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.authoring import modeling_tasks,run_codex_modeling
    from real2sim_builder.files import write,read
    p=Project.create(tmp_path/'projects','review');c=Candidate.create(p,'draft')
    modeling_tasks(c,{}, {'segments':[],'depth_batches':[]})
    folder=c.root/'fitting/final/previews/w';folder.mkdir(parents=True)
    for i,kind in enumerate(('real','sim','overlay','difference')):
        Image.new('RGB',(8,8),(i*50,0,0)).save(folder/(kind+'.png'))
    write(c.root/'metrics.json',{'input_signature':p.signature(c.scene),
        'images':[{'image_id':'w','camera_type':'wrist'}]})
    executable=tmp_path/'codex_fake'
    executable.write_text('#!'+sys.executable+'\n'+'''import json,sys
from pathlib import Path
args=sys.argv;root=Path(args[args.index('--cd')+1])
payload=json.loads((root/'tasks.json').read_text())
view=payload['fitting_review']['views'][0]
assert view['camera_type']=='wrist'
assert len(view['references'])==4
assert all((root/ref['path']).is_file() for ref in view['references'])
assert args.count('--image')==4
Path(args[args.index('--output-last-message')+1]).write_text(json.dumps(
    {'action':'numeric','objects':[],'evidence':['w'],'reason':'Shared mount pose needs refinement'}))
''');executable.chmod(0o700)
    before=c.scene
    result=run_codex_modeling(c,executable=executable,review_fitting=True)
    assert result['status']=='REVIEWED' and result['decision']['action']=='numeric'
    assert c.scene==before
    assert not (c.root/'modeling/results.json').exists()
    assert read(c.root/'fitting/decision.json')==result


def test_visual_completion_does_not_require_invented_numeric_tolerances():
    review={'objects':[],'views':[{'image_id':'w'},{'image_id':'s'}],
        'camera_quality':{'status':'NOT_VERIFIED','cameras':{'wrist':{'count':2},'side':{'count':1}},'distinct_wrist_q':2}}
    answer={'action':'complete','objects':[],'evidence':['w','s'],'reason':'Consistent across supplied poses'}
    assert review_decision(answer,review)['action']=='complete'
    review['camera_quality']['status']='NOT_MET'
    assert review_decision(answer,review)['action']=='needs_data'
