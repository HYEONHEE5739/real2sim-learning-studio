from pathlib import Path
import json
import pytest


def test_usb_resolution_requires_unique_serial_identity_not_tty_number(tmp_path):
    from robot_learning_workbench.robot.registration import resolve_serial
    inventory=[{'path':'/dev/ttyACM7','serial':'leader123','vid':6790,'pid':21972},{'path':'/dev/ttyACM3','serial':'follower456','vid':6790,'pid':21972}]
    assert resolve_serial({'serial':'leader123','vid':6790,'pid':21972},inventory)=='/dev/ttyACM7'
    with pytest.raises(ValueError,match='identity|Identity'):resolve_serial({'serial':'missing'},inventory)
    with pytest.raises(ValueError,match='ambiguous|unique'):resolve_serial({'serial':'leader123'},inventory+[inventory[0]])


def test_scene_device_binding_is_owned_and_reloads_without_old_profile_locations(tmp_path):
    from robot_learning_workbench.robot.registration import save_configuration,bind_configuration,bound_configuration
    from robot_learning_workbench.scene_preparation import create_scene
    spec={'schema_version':1,'stage':'capture_session','inputs':{},'execution':{'device_source':'hardware','max_command_step_rad':.01,'max_follow_error_rad':.1},'output':{'directory':'new-session'}}
    file=save_configuration(tmp_path,'my SO101',spec);p=create_scene(tmp_path,'new Scene');bind_configuration(p['project'],file,tmp_path)
    assert bound_configuration(p['project'],tmp_path)==file
    file.unlink()
    with pytest.raises(ValueError,match='missing|changed'):bound_configuration(p['project'],tmp_path)


def test_registration_never_reuses_a_different_units_or_geometry_precision_mapping():
    from robot_learning_workbench.robot.registration import mapping_coordinates_equal
    from test_precision_calibration import bound
    _,mapper=bound('follower');a=mapper.metadata();import copy
    b=copy.deepcopy(a);b['profile']['identity']['port']='/dev/ttyACM8'
    from robot_learning_workbench.robot.calibration import PrecisionMapper
    b=PrecisionMapper(b['profile']).metadata();assert mapping_coordinates_equal(a,b)
    b['profile']['joints']['wrist_flex']['rad_per_count']*=1.01
    with pytest.raises(ValueError,match='coefficients|review'):PrecisionMapper(b['profile'])
    b=copy.deepcopy(a);b['profile']['urdf_sha256']='0'*64;b=PrecisionMapper(b['profile']).metadata();assert not mapping_coordinates_equal(a,b)


def test_registered_geometry_accepts_only_its_exact_measured_model_and_mapping():
    from robot_learning_workbench.robot.real_sim import checked_geometry_binding
    from scene_contract.package import load_scene
    from robot_learning_workbench.robot.calibration import mapper_from_scene
    root=Path(__file__).resolve().parents[2]/'docs/evidence/e01-v8-collision/runspace/relocated/scene-v8-native';package=load_scene(root/'scene.json');record=package.calibration['records']['residual']
    measured=next(root/f.path for f in package.files if f.sha256==record['source_model_sha256']);geometry=next(root/f.path for f in package.files if f.sha256==record['execution_model_sha256']);mapping=mapper_from_scene(package,'follower',role='follower',phase='device_observation').metadata()
    assert checked_geometry_binding(root/'scene.json','residual',measured,geometry,mapping)['manifest_sha256']==package.identity.manifest_sha256
    with pytest.raises(ValueError,match='model'):checked_geometry_binding(root/'scene.json','residual',geometry,geometry,mapping)
    wrong=dict(mapping);wrong['sha256']='0'*64
    with pytest.raises(ValueError,match='mapping|hash'):checked_geometry_binding(root/'scene.json','residual',measured,geometry,wrong)


def test_new_so101_setup_needs_device_choices_not_handwritten_profiles(tmp_path):
    from robot_learning_workbench.robot.registration import configure_selected
    from real2sim_builder.files import read
    choices={'robot':'so101','leader':{'path':'/dev/ttyACM9','serial':'newleader','vid':6790,'pid':21972},'follower':{'path':'/dev/ttyACM8','serial':'newfollower','vid':6790,'pid':21972},'side':'/dev/v4l/by-id/side','wrist':'/dev/v4l/by-id/wrist'}
    file=configure_selected(tmp_path,'new pair',choices)
    recipe=read(file);assert recipe['stage']=='scene_capture'and 'calibration_profile'not in recipe['inputs']
    assert 'max_command_step_rad'not in recipe['execution']
    spec=read(recipe['inputs']['device_profile']);assert spec['usb_identity']['serial']=='newfollower'
    assert not Path(spec['calibration_path']).exists()  # User must perform official calibration, never invented.


def test_camera_only_setup_does_not_require_robot_or_urdf(tmp_path):
    from robot_learning_workbench.robot.registration import configure_selected
    from real2sim_builder.files import read
    file=configure_selected(tmp_path,'cameras',{'robot':'cameras','side':'/fixture/side','wrist':'/fixture/wrist'})
    data=read(file);assert set(data['inputs'])=={'camera_config'}and data['stage']=='scene_capture'


def test_edit_camera_keeps_same_usb_pair_calibration_and_precision(tmp_path):
    from robot_learning_workbench.robot.registration import configure_selected
    from real2sim_builder.files import read,write
    choices={'robot':'so101','leader':{'path':'/dev/ttyACM9','serial':'sameleader'},'follower':{'path':'/dev/ttyACM8','serial':'samefollower'},'side':'/fixture/side','wrist':'/fixture/wrist'}
    file=configure_selected(tmp_path,'original',choices);data=read(file)
    profile=tmp_path/'verified-profile.json';write(profile,{'source':'verified fixture'});data['inputs'].update(calibration_profile=str(profile),robot_model='/owned/model.urdf');data['stage']='capture_session';write(file,data)
    for key in('device_profile','leader_device_profile'):write(read(data['inputs'][key])['calibration_path'],{'verified_sdk':'fixture'})
    choices['side']='/fixture/new-side';changed=configure_selected(tmp_path,'camera edit',choices,existing=file);new=read(changed)
    assert new['stage']=='capture_session'and new['inputs']['calibration_profile']==str(profile)and new['inputs']['device_profile']==data['inputs']['device_profile']
    assert read(new['inputs']['camera_config'])['cameras']['side']['index_or_path']=='/fixture/new-side'
    choices['follower']['serial']='different-unit';fresh=read(configure_selected(tmp_path,'different hardware',choices,existing=file))
    assert fresh['stage']=='scene_capture'and 'calibration_profile'not in fresh['inputs']
    assert not Path(read(fresh['inputs']['device_profile'])['calibration_path']).exists()


def test_geometry_binding_rechecks_exact_package_manifest_identity(monkeypatch,tmp_path):
    import robot_learning_workbench.robot.real_sim as module
    from types import SimpleNamespace
    view=module.CandidateView.__new__(module.CandidateView)
    view.geometry_binding={'manifest_sha256':'a'*64,'files':[]};view.project=SimpleNamespace(root=tmp_path);view.model=tmp_path/'measurement.urdf';view.candidate_model=tmp_path/'geometry.urdf';view.mapping={}
    view.scene={'robot_model':{'geometry_binding':{'package':'package/scene.json','calibration_id':'geometry'}}};view.identity={'unchanged':'cached'};view._identity=lambda:view.identity
    monkeypatch.setattr(module,'checked_geometry_binding',lambda *a:{'manifest_sha256':'b'*64,'files':[]})
    with pytest.raises(ValueError,match='Manifest|manifest|revision'):view.verify()
