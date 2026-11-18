"""Native settings belong to an engine/mode/revision and never overwrite inputs."""
from types import SimpleNamespace
from scene_contract.package import SceneIdentity
import pytest
from real2sim_builder.project import Project
from real2sim_builder import registration
from real2sim_builder.files import read,write


def packages(tmp_path,monkeypatch):
    project=Project.create(tmp_path,'shared settings')
    roots=[]
    for name in ('one','two'):
        root=project.root/'exports'/name;root.mkdir(parents=True)
        write(root/'execution_profiles.json',{engine:{mode:{'initial_joint_rad':[0.]*6}for mode in('pose','physics')}for engine in('mujoco','isaac')})
        write(root/'scene.json',{'validation':{'native_readiness':{'synthetic':True}}});roots.append(root)
    def verify(path):
        return SimpleNamespace(scene={'engines':{'mujoco':{},'isaac':{}}},
            identity=SceneIdentity(scene_id='scene',revision=path.name,manifest_sha256=('a'if path.name=='one'else'b')*64))
    monkeypatch.setattr(registration,'verify_package',verify)
    return project,roots


def test_native_settings_are_bound_to_each_engine_mode_and_revision(tmp_path,monkeypatch):
    project,roots=packages(tmp_path,monkeypatch)
    rows=[registration.register_export(project,path)for path in roots]
    paths={p for row in rows for p in row['engine_config'].values()}
    assert len(paths)==4  # One Pose setting per engine/revision; Physics is separate.
    assert len(list((project.root/'configuration').glob('*.json')))==8
    assert all(read(project.root/path)['simulation_mode']=='pose'for path in paths)
    assert all(read(project.root/path)['render_type']=='native'for path in paths)


def test_failed_registration_removes_only_the_new_automatic_settings(tmp_path,monkeypatch):
    project,roots=packages(tmp_path,monkeypatch)
    original=registration.write;before=(project.root/'project.yaml').read_bytes()
    def fail(path,value):
        if path==project.root/'project.yaml':raise OSError('registration commit failed')
        original(path,value)
    monkeypatch.setattr(registration,'write',fail)
    with pytest.raises(OSError,match='commit failed'):registration.register_export(project,roots[0])
    assert (project.root/'project.yaml').read_bytes()==before
    assert not list((project.root/'configuration').glob('*.json'))


def test_existing_settings_survive_later_registration_failure(tmp_path,monkeypatch):
    project,roots=packages(tmp_path,monkeypatch)
    row=registration.register_export(project,roots[0]);path=project.root/row['engine_config']['mujoco'];before=path.read_bytes()
    original=registration.write
    def fail(target,value):
        if target==project.root/'project.yaml':raise OSError('registration commit failed')
        original(target,value)
    monkeypatch.setattr(registration,'write',fail)
    with pytest.raises(OSError):registration.register_export(project,roots[1])
    assert path.read_bytes()==before
    assert len(list((project.root/'configuration').glob('*.json')))==4


def test_immutable_native_settings_are_never_overwritten_if_modified(tmp_path,monkeypatch):
    project,roots=packages(tmp_path,monkeypatch)
    row=registration.register_export(project,roots[0]);path=project.root/row['engine_config']['mujoco']
    write(path,{'render_type':'user-selected'});before=path.read_bytes()
    info=read(project.root/'project.yaml');info['execution_packages']=[];write(project.root/'project.yaml',info)
    with pytest.raises(ValueError,match='settings'):registration.register_export(project,roots[0])
    assert path.read_bytes()==before
