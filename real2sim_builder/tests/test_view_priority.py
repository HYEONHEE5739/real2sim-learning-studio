import pytest


def test_phone_count_does_not_dilute_wrist_priority():
    from real2sim_builder.calibration.hybrid import view_priority, view_loss
    images=[{'id':'w','camera':'external','camera_type':'wrist'},{'id':'s','camera':'external','camera_type':'side'}]
    images += [{'id':f'p{i}','camera':'external','camera_type':'external'}for i in range(20)]
    priority=view_priority(images,{})
    score=view_loss([{'image_id':r['id'],'loss':1. if r['id']=='w'else 0.}for r in images],priority)
    assert score==pytest.approx(4/6.5)
    assert priority['roles']['w']=='wrist'


def test_phone_only_is_usable_without_claiming_wrist_validation():
    from real2sim_builder.calibration.hybrid import view_priority, view_loss
    p=view_priority([{'id':'p','camera':'external','camera_type':'external'}],{})
    assert view_loss([{'image_id':'p','loss':2.}],p)==2.
    assert not p['wrist_observed']
    with pytest.raises(ValueError):view_priority([] ,{'wrist':-1})


def test_codex_review_handoff_contains_real_sim_images_and_role_order(tmp_path):
    from PIL import Image
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.authoring import fitting_review
    from real2sim_builder.files import write,sha
    p=Project.create(tmp_path,'review');c=Candidate.create(p,'draft')
    rows=[]
    for name,role in [('phone','external'),('side','side'),('hand','wrist')]:
        folder=c.root/'fitting/final/previews'/name;folder.mkdir(parents=True)
        for file in ('real','sim','overlay','difference'):
            Image.new('RGB',(8,8)).save(folder/(file+'.png'))
        rows.append({'image_id':name,'camera_type':role,'split':'train','objects':[]})
    write(c.root/'metrics.json',{'images':rows,'input_signature':p.signature(c.scene)})
    result=fitting_review(c)
    assert [r['camera_type']for r in result['views']]==['wrist','side','external']
    assert all(sha(f['path'])==f['sha256']for r in result['views']for f in r['references'])
    assert result['wrist_observed'] and result['status']=='WAITING_FOR_CODEX_REVIEW'
    assert not result['physical_verified']


def test_review_rejects_stale_scene_and_missing_comparison(tmp_path):
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.authoring import fitting_review
    from real2sim_builder.files import write
    p=Project.create(tmp_path,'stale');c=Candidate.create(p,'draft')
    write(c.root/'metrics.json',{'images':[],'input_signature':{}})
    with pytest.raises(ValueError,match='inputs changed'):fitting_review(c)
    write(c.root/'metrics.json',{'images':[{'image_id':'w','camera_type':'wrist'}],
                                'input_signature':p.signature(c.scene)})
    with pytest.raises(ValueError,match='Missing fitting comparison'):fitting_review(c)


def test_heldout_comparisons_are_not_sent_to_correction_agent(tmp_path):
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.authoring import fitting_review
    from real2sim_builder.files import write
    p=Project.create(tmp_path,'heldout');c=Candidate.create(p,'draft')
    write(c.root/'metrics.json',{'input_signature':p.signature(c.scene),
        'images':[{'image_id':'validation_view','camera_type':'wrist','split':'validation'}]})
    result=fitting_review(c)
    assert result['views']==[] and not result['wrist_observed']
