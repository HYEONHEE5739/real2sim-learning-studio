"""Preview association keeps different categories separate and ambiguity explicit."""
import numpy as np
from real2sim_builder import stage_workers


def test_preview_masks_keep_boundary_robot_without_erasing_ambiguous_target(tmp_path,monkeypatch):
    from real2sim_builder.calibration import decomposition
    # The original optional skimage cleanup is outside this dispatch contract;
    # all unique-assignment math and returned masks are the real implementation.
    def prune(masks,boxes,scores,phrases,**options):
        assert options['boundary_proportion']is None and options['text_encoder']is None
        return masks,boxes,scores,phrases
    monkeypatch.setattr(decomposition,'prune_redundant_masks',prune)
    monkeypatch.setattr(stage_workers,'_module',lambda *args:decomposition)
    masks=np.zeros((3,32,32),bool);masks[0,5:30,:9]=True;masks[1,10:20,15:25]=True;masks[2]=masks[1]
    path=tmp_path/'raw.npz';np.savez(path,masks=masks,boxes=[[0,5,9,30],[15,10,25,20],[15,10,25,20]],scores=[.9,.8,.7])
    request={'output':str(tmp_path),'objects':[
        {'id':'robot','category':'robot','prompt':'robot','box_xyxy':[0,5,9,30]},
        {'id':'block','category':'block','prompt':'block','box_xyxy':[15,10,25,20]}],
        'sam_result':{'path':str(path),'phrases':['robot','block','block'],'provenance':{'execution':'mock'},'point_fallback':[]}}
    result=stage_workers.preview_segments(request);rows={r['id']:r for r in result['objects']}
    assert rows['robot']['status']=='UNIQUE_ESTIMATED'and rows['robot']['confidence']==.9
    assert rows['block']['status']=='AMBIGUOUS'and 'path'not in rows['block']
    assert (tmp_path/'robot_mask.png').is_file()


def test_workspace_preview_mask_excludes_contained_target_pixels(tmp_path,monkeypatch):
    from real2sim_builder.calibration import decomposition
    monkeypatch.setattr(decomposition,'prune_redundant_masks',lambda m,b,s,p,**kw:(m,b,s,p))
    monkeypatch.setattr(stage_workers,'_module',lambda *args:decomposition)
    masks=np.zeros((2,32,32),bool);masks[0,5:28,5:28]=True;masks[1,10:18,10:18]=True
    path=tmp_path/'raw.npz';np.savez(path,masks=masks,boxes=[[5,5,28,28],[10,10,18,18]],scores=[.9,.95])
    request={'output':str(tmp_path),'objects':[
        {'id':'paper','category':'paper','prompt':'paper','box_xyxy':[5,5,28,28]},
        {'id':'block','category':'block','prompt':'block','box_xyxy':[10,10,18,18]}],
        'sam_result':{'path':str(path),'phrases':['paper','block'],'provenance':{},'point_fallback':[]}}
    result=stage_workers.preview_segments(request);rows={r['id']:r for r in result['objects']}
    from PIL import Image
    paper=np.asarray(Image.open(rows['paper']['path']))>0;block=np.asarray(Image.open(rows['block']['path']))>0
    assert block.sum()==64 and not(paper&block).any()
