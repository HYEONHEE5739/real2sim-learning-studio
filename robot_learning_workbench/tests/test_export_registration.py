"""Ordinary Builder exports must become discoverable without migration or device IO."""
import copy,json,subprocess
from pathlib import Path

import numpy as np
import pytest

from real2sim_builder.project import Project,empty,value
from real2sim_builder.files import read,write
from real2sim_builder.export import export_revision
from robot_learning_workbench.ui.session_operations import execution_scenes


def export_project(tmp_path):
    workspace=tmp_path/'workspace';project=Project.create(workspace/'scenes','Export review')
    scene=empty('Export review')
    for name,role,size,z in(('table','support_surface',[1.,.8,.04],-.02),('block','manipulable_object',[.06]*3,.03)):
        pose=np.eye(4);pose[2,3]=z
        scene['objects'].append({'id':name,'role':role,'frame':'world','pose':value(pose.tolist(),'measured'),'dimensions':value(size,'measured'),
            'visual':{'type':'box'},'collision':{'type':'box'},'color':value([.5,.2,.1],'measured'),'physics':{'mass_kg':value(None),'friction':value(.1,'measured')}})
    pose=np.eye(4);pose[:3,:3]=[[1,0,0],[0,-1,0],[0,0,-1]];pose[2,3]=1
    for name in('side','wrist'):
        scene['cameras'].append({'id':name,'camera_type':name,'frame':'world','pose':value(pose.tolist(),'calibrated'),'K':value([[640.,0,320.],[0,640.,240.],[0,0,1]],'calibrated'),
            'resolution':[640,480],'distortion':value([0.]*5,'calibrated')})
    project.save_scene(scene)
    write(project.root/'working/validation/report.json',{'passed':False,'input_signature':project.signature(),'scope':'synthetic unvalidated review'})
    return workspace,project


def test_successful_builder_exports_register_distinct_scene_revisions_without_launching(tmp_path,monkeypatch):
    workspace,project=export_project(tmp_path)
    def no_launch(*args,**kwargs):raise AssertionError('Export/registration must not launch simulation or devices')
    monkeypatch.setattr(subprocess,'Popen',no_launch)
    identities=[]
    for revision in('review1','review2'):
        destination=project.root/'exports'/revision
        identities.append(export_revision(project,destination=destination,revision=revision,allow_unvalidated=True))
    records=read(project.root/'project.yaml').get('execution_packages',[])
    assert len(records)==2,'Successful Builder exports never reach the Real/Sim registry'
    for record,identity in zip(records,identities):
        assert (record['scene_id'],record['revision'],record['manifest_sha256'])==(identity.scene_id,identity.revision,identity.manifest_sha256)
        assert record['source_project_id']==project.info['id']
        assert record['engine_config']=={}
        assert record['execution_readiness']['mujoco']['pose']=='BLOCKED'
        assert any('robot' in r.lower()for r in record['execution_readiness']['mujoco']['needs'])
    scenes=execution_scenes(workspace)['scenes']
    assert {r['revision']for r in scenes}=={'review1','review2'}
    assert all(r['name']=='Export review'and r['project_id']==project.info['id']and r['scene_id']==identities[0].scene_id for r in scenes)
    assert all(r['engines']==[]and r['reason']for r in scenes)


def test_failed_builder_export_does_not_register_or_replace_previous_revision(tmp_path,monkeypatch):
    from real2sim_builder import export as exporter
    workspace,project=export_project(tmp_path)
    export_revision(project,destination=project.root/'exports/good',allow_unvalidated=True)
    before=read(project.root/'project.yaml');package_before=(project.root/'exports/good/manifest.json').read_bytes()
    def fail(*args,**kwargs):raise OSError('controlled export failure')
    monkeypatch.setattr(exporter.usd,'export',fail)
    with pytest.raises(OSError,match='controlled export failure'):
        export_revision(project,destination=project.root/'exports/broken',allow_unvalidated=True)
    assert read(project.root/'project.yaml')==before and (project.root/'exports/good/manifest.json').read_bytes()==package_before
    assert not (project.root/'exports/broken').exists()


def test_changed_registered_manifest_is_not_a_normal_selectable_scene(tmp_path):
    workspace,project=export_project(tmp_path);out=project.root/'exports/review'
    export_revision(project,destination=out,allow_unvalidated=True)
    assert execution_scenes(workspace)['scenes'],'Exported scene did not register'
    manifest=out/'manifest.json';manifest.write_text(manifest.read_text()+'\n')
    rows=execution_scenes(workspace)['scenes']
    assert not rows or all(r.get('valid')is False and r.get('reason')for r in rows),'Changed package still appears as a normal Scene'
