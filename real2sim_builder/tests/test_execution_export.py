def test_export_cannot_bypass_native_profile_validation_with_arbitrary_settings(tmp_path):
    import pytest
    from real2sim_builder.project import Project
    from real2sim_builder.export import export_revision
    from real2sim_builder.files import read,write
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path,'execution settings');p.save_scene(legacy_scene())
    write(p.root/'working/validation/report.json',{'passed':False,'input_signature':p.signature()})
    settings=p.root/'configuration/mujoco.json';write(settings,{'initial_joint_rad':[0]*6})
    before=(p.root/'project.yaml').read_bytes()
    with pytest.raises(TypeError,match='engine_config'):
        export_revision(p,destination=p.root/'exports/check',allow_unvalidated=True,engine_config={'mujoco':'configuration/mujoco.json'})
    assert (p.root/'project.yaml').read_bytes()==before
    assert not (p.root/'exports/check').exists()
    assert read(settings)=={'initial_joint_rad':[0]*6}
