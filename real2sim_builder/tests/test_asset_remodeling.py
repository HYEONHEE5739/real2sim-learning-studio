"""Replacing estimated geometry must preserve partial measurements and old assets."""
import copy
import pytest
from real2sim_builder.project import Project, Candidate
from real2sim_builder.files import sha
from real2sim_builder.object_assets import register_object_asset, instance_operation
from test_object_assets import asset_fixture


def test_new_asset_changes_only_unmeasured_dimensions(tmp_path):
    from pxr import Usd, UsdGeom
    p=Project.create(tmp_path/'projects','remodel')
    source=asset_fixture(tmp_path/'old')
    measured={'value':[None,None,.03],'provenance':'measured','evidence':['height only']}
    old=register_object_asset(p,source,asset_id='block',dimensions=measured)
    c=Candidate.create(p,'draft')
    for name in ('a','b'):c.edit([instance_operation(p,old['manifest'],name)])
    original=copy.deepcopy(c.scene);old_sha=sha(p.root/old['manifest'])
    replacement=asset_fixture(tmp_path/'replacement')
    stage=Usd.Stage.Open(str(replacement))
    for name in ('Visual','Collision'):
        attr=UsdGeom.Mesh(stage.GetPrimAtPath('/Object/'+name)).GetPointsAttr()
        attr.Set([(float(v[0])*1.5,float(v[1]),float(v[2])) for v in attr.Get()])
    stage.GetRootLayer().Save()
    new=register_object_asset(p,replacement,asset_id='block',dimensions=measured)
    op=instance_operation(p,new['manifest'],'a');op['op']='use_object_asset'
    c.edit([op])
    assert c.scene['objects'][0]['dimensions']['value'][0]>.04
    assert c.scene['objects'][0]['dimensions']['constraints']==measured
    assert c.scene['objects'][1]==original['objects'][1]
    assert old['version']!=new['version'] and sha(p.root/old['manifest'])==old_sha
    # Omitting the old partial measurement in a replacement must not discard it.
    unconstrained=register_object_asset(p,replacement,asset_id='unconstrained')
    bad=instance_operation(p,unconstrained['manifest'],'a');bad['op']='use_object_asset'
    before=copy.deepcopy(c.scene)
    with pytest.raises(ValueError,match='Protected'):
        c.edit([bad])
    assert c.scene==before
