def test_export_can_register_explicit_owned_engine_settings(tmp_path):
    from real2sim_builder.project import Project
    from real2sim_builder.export import export_revision
    from real2sim_builder.files import read,write
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'execution settings');p.save_scene(legacy_scene())
    write(p.root/'working/validation/report.json',{'passed':False,'input_signature':p.signature()})
    settings=p.root/'configuration/mujoco.json';write(settings,{'initial_joint_rad':[0]*6})
    export_revision(p,destination=p.root/'exports/check',allow_unvalidated=True,engine_config={'mujoco':'configuration/mujoco.json'})
    record=read(p.root/'project.yaml')['execution_packages'][-1]
    assert record['engine_config']=={'mujoco':'configuration/mujoco.json'}
    assert read(settings)=={'initial_joint_rad':[0]*6}
