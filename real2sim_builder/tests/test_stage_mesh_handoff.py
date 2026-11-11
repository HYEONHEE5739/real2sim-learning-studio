import numpy as np
from PIL import Image
from real2sim_builder.files import read,sha
from real2sim_builder.candidate import Candidate
from real2sim_builder.project import Project


def test_prepared_crops_mask_and_depth_reach_existing_codex_handoff(tmp_path):
    from real2sim_builder.authoring import modeling_tasks
    p=Project.create(tmp_path/'projects','Prepared model evidence');c=Candidate.create(p,'test')
    folder=c.root/'prepared';folder.mkdir()
    image=folder/'rgb.png';mask=folder/'mask.png';crop=folder/'rgba.png';depth=folder/'observed.npz'
    Image.new('RGB',(32,24),'red').save(image);Image.new('L',(32,24),255).save(mask);Image.new('RGBA',(16,16),(255,0,0,255)).save(crop)
    np.savez(depth,depth=np.ones((24,32)),K=np.eye(3))
    config={'authoring_mode':'codex','objects':{'block':{'prompt':'red block'}},
            'prepared_objects':{'block':{'image':str(image),'image_id':'canonical_frame','mask':str(mask),
                 'observed':str(depth),'crops':[str(crop)],'provenance':'observed'}}}
    modeling_tasks(c,config,{})
    group=read(c.root/'modeling/tasks.json')['groups']['block']
    ref=next(r for r in group['references']if r['image_id']=='canonical_frame')
    assert ref['masks'][0]['sha256']==sha(mask)
    assert ref['crops'][0]['sha256']==sha(crop)
    assert ref['depth_batches'][0]['metadata']['sha256']==sha(depth)
    assert ref['provenance']=='observed'
