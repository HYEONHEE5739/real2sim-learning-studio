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
        scene['cameras'].append({'id':name,'frame':'world','pose':value(pose.tolist(),'calibrated'),'K':value([[640.,0,320.],[0,640.,240.],[0,0,1]],'calibrated'),
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
        assert set(record['engine_config'])=={'mujoco','isaac'}
        for settings_path in record['engine_config'].values():
            settings=project.root/settings_path
            assert settings.resolve().is_relative_to(project.root)
            assert read(settings)['render_type']=='authored'
    scenes=execution_scenes(workspace)['scenes']
    assert {r['revision']for r in scenes}=={'review1','review2'}
    assert all(r['name']=='Export review'and r['project_id']==project.info['id']and r['scene_id']==identities[0].scene_id for r in scenes)
    assert all(set(r['engines'])=={'mujoco','isaac'}for r in scenes)


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


def test_authored_export_uses_verified_model_mapping_and_measured_fk_render(tmp_path):
    from real2sim_builder.evidence import import_robot
    from robot_learning_workbench.robot.scene_render import SceneView,create_renderer
    from robot_learning_workbench.robot.calibration import JOINTS,PrecisionMapper
    from test_precision_session import precision_fixture
    _,device,workspace,configuration,profile,_=precision_fixture(tmp_path)
    _,project=export_project(tmp_path)
    # Small synthetic six-axis robot with explicit primitive geometry and real
    # calibration arithmetic; no historical USD/checkpoint fixture is needed.
    import hashlib
    model=project.root/'input/robot.urdf';parts=['<robot name="synthetic"><link name="base"/>'];previous='base'
    for i,name in enumerate(JOINTS):
        link='link'+str(i);lo,hi=device.profile['joints'][name]['limits']
        parts.append(f'<link name="{link}"><visual><geometry><box size="0.03 0.03 0.08"/></geometry></visual></link><joint name="{name}" type="revolute"><parent link="{previous}"/><child link="{link}"/><origin xyz="0 0 0.08"/><axis xyz="0 1 0"/><limit lower="{lo}" upper="{hi}" effort="1" velocity="1"/></joint>');previous=link
    model.write_text(''.join(parts)+'</robot>');import_robot(project,model,joints=dict.fromkeys(JOINTS,0.),base=np.eye(4).tolist())
    scene=project.scene;scene['robot_model']={'path':'input/robot.urdf','model_sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'joint_names':list(JOINTS),'mapping_verified':False};project.save_scene(scene)
    write(project.root/'working/validation/report.json',{'passed':False,'input_signature':project.signature()})
    # Explicit synthetic auxiliary collision declarations: export/parser checks
    # remain real and the resulting Package is authoring-only, not task physics.
    collision=project.root/'input/collision';collision.mkdir();native=collision/'robot.usda';native.write_text('#usda 1.0\ndef Xform "Robot" {}\n')
    mesh=collision/'finger.bin';mesh.write_bytes(b'synthetic collision identity')
    finger=collision/'finger_convex_parts.json';pads=collision/'usd_contact_pads.json'
    write(finger,{'schema':'so101.finger-convex-parts/1','meshes':[{'mesh':mesh.name,'source_sha256':hashlib.sha256(mesh.read_bytes()).hexdigest(),'parts':[]}]})
    write(pads,{'schema':'so101.usd-contact-pads/1','source_sha256':{native.name:hashlib.sha256(native.read_bytes()).hexdigest()},'pads':[]})
    destination=project.root/'exports/fk';export_revision(project,destination=destination,allow_unvalidated=True,required_files=[finger,pads,mesh,native])
    settings=project.root/read(project.root/'project.yaml')['execution_packages'][0]['engine_config']['mujoco']
    profile_data=json.loads(profile.read_text());profile_data['urdf_sha256']=hashlib.sha256(model.read_bytes()).hexdigest()
    mapping=PrecisionMapper(profile_data).metadata();view=SceneView(destination/'scene.json','mujoco',settings,mapping)
    with create_renderer(view,tmp_path/'render')as renderer:
        result=renderer.render([0.]*6);moved=renderer.render([.2,0,0,0,0,0])
    assert moved['applied_sim_joint_rad']==[.2,0,0,0,0,0]and np.any(moved['images']['side']!=result['images']['side'])
    assert result['physics_steps']==0 and result['applied_sim_joint_rad']==[0.]*6
    assert set(result['images'])=={'side','wrist'}and all(rgb.shape==(480,640,3)for rgb in result['images'].values())
    # Production selection restores the registered engine/cameras/model and
    # builds a Prepared plan without opening serial/cameras or launching a sim.
    import yaml
    from robot_learning_workbench.robot.registration import bind_configuration
    from robot_learning_workbench.ui.session_operations import real_sim_setup
    from robot_learning_workbench.ui.operations import prepared
    profile.write_text(json.dumps(profile_data));config=yaml.safe_load(configuration.read_text());config['inputs']['robot_model']=str(model)
    for key in('leader_device_profile','leader_calibration_profile'):config['inputs'].pop(key,None)
    configuration.write_text(yaml.safe_dump(config));bind_configuration(project.root,configuration,workspace)
    setup=real_sim_setup(workspace,project.root,destination/'scene.json','mujoco')
    recipe=setup['recipe'];recipe['output']['directory']=str(workspace/'paired-output');path=workspace/'paired.yaml';path.write_text(yaml.safe_dump(recipe))
    assert prepared(str(path),str(Path(__file__).parents[1]/'task_modules.yaml'))['state']=='runtime_ready'
    damaged=copy.deepcopy(mapping);damaged['profile']['urdf_sha256']='f'*64
    from robot_learning_workbench.robot.calibration import fingerprint
    damaged['sha256']=fingerprint({k:v for k,v in damaged.items()if k!='sha256'})
    with pytest.raises(ValueError,match='[Mm]odel|[Mm]apping|[Cc]oordinate'):
        SceneView(destination/'scene.json','mujoco',settings,damaged)
