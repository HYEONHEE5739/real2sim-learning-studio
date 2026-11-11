import numpy as np
import pytest


def _source_mask_assertions():
    from real2sim_builder.calibration.decomposition import prune_redundant_masks,prune_masks_below_surface,disentangle_masks
    a=np.zeros((64,64),bool);a[10:30,10:30]=True
    b=np.zeros_like(a);b[36:56,36:56]=True
    masks,boxes,scores,names=prune_redundant_masks([a.copy(),a.copy(),b.copy()],np.array([[10,10,30,30],[10,10,30,30],[36,36,56,56]]),np.array([.9,.8,.7]),['cup','cup','cup'],boundary_proportion=.02)
    assert len(masks)==1 and scores.tolist()==[.7]  # Original removes both equal boxes.
    masks=[a.copy(),b.copy()];boxes=np.array([[10,10,30,30],[36,36,56,56]]);scores=np.array([.9,.7]);names=['cup','cup']
    pc=np.zeros((64,64,3));pc[...,2]=.1;pc[b,2]=-.1
    masks,boxes,scores,names=prune_masks_below_surface(masks,boxes,scores,names,pc,z_threshold=-.05)
    assert len(masks)==1 and np.array_equal(masks[0],a)
    large=np.zeros_like(a);large[8:32,8:32]=True
    separated=disentangle_masks([a,large],['inner','outer'])
    assert not np.any(separated[0]&separated[1])


def test_stable_instance_assignment_is_not_sam_order_or_caption_identity():
    from real2sim_builder.calibration.decomposition import associate_masks
    objs=[{'id':'cup_a','box_xyxy':[5,5,15,15]},{'id':'cup_b','box_xyxy':[35,5,45,15]}]
    order=associate_masks(objs,np.array([[35,5,45,15],[5,5,15,15]]))
    assert order=={'cup_a':1,'cup_b':0}
    with pytest.raises(ValueError,match='AMBIGUOUS'):
        associate_masks(objs,np.array([[5,5,45,15],[5,5,45,15]]))


def test_removal_annotation_retry_validator_detects_residual_green():
    from real2sim_builder.calibration.decomposition import removal_annotation,removal_is_valid
    rgb=np.full((64,64,3),100,np.uint8);mask=np.zeros((64,64),bool);mask[20:40,20:40]=True
    painted,check=removal_annotation(rgb,mask,'mask')
    assert not removal_is_valid(painted,check)
    assert removal_is_valid(rgb,check)
    for mode in ('outline','bbox'):
        annotated,check=removal_annotation(rgb,mask,mode)
        assert not removal_is_valid(annotated,check)


def test_source_mask_duplicate_pruning_and_below_support_math():
    import importlib.util
    if importlib.util.find_spec('skimage')is not None and importlib.util.find_spec('shapely')is not None:
        _source_mask_assertions()
    else:
        from real2sim_builder.calibration.decomposition import prune_redundant_masks,prune_masks_below_surface,disentangle_masks
        a=np.zeros((64,64),bool);a[10:30,10:30]=True
        with pytest.raises(ModuleNotFoundError):prune_redundant_masks([a],np.array([[10,10,30,30]]),np.array([.9]),['cup'])
        points=np.zeros((64,64,3));points[...,2]=-.1
        rows=prune_masks_below_surface([a],np.array([[10,10,30,30]]),np.array([.9]),['cup'],points,z_threshold=-.05)
        assert rows[0]==[]
        large=np.zeros_like(a);large[8:32,8:32]=True
        separated=disentangle_masks([a,large],['inner','outer'])
        assert not np.any(separated[0]&separated[1])
