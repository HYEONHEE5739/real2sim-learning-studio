from pathlib import Path
import pytest


def test_empty_and_note_only_projects_do_not_require_model_or_scene(tmp_path):
    from robot_learning_workbench.scene_preparation import create_scene,save_inputs,scene_details,list_scenes
    project=create_scene(tmp_path,'notes_only')
    assert project['name']=='notes_only'and project['inputs']==[]and not project['reconstruction_ready']
    assert not(Path(project['project'])/'working/current_scene.yaml').exists()
    result=save_inputs(project['project'],[], '컵 지름 80mm, 블록 세 개. 아직 실측 보정 없음.')
    assert scene_details(project['project'])['notes']=='컵 지름 80mm, 블록 세 개. 아직 실측 보정 없음.'
    assert list_scenes(tmp_path)[0]['project']==project['project']
    assert not result['reconstruction_ready']


def test_optional_images_and_unknown_measurements_are_archived_not_invented_geometry(tmp_path):
    from robot_learning_workbench.scene_preparation import create_scene,save_inputs,scene_details
    from PIL import Image
    p=create_scene(tmp_path,'photos');image=tmp_path/'phone.png';Image.new('RGB',(30,20)).save(image);measurement=tmp_path/'distances.txt';measurement.write_text('table height about 400mm, unverified')
    result=save_inputs(p['project'],[str(image),str(measurement)],'notes')
    assert len(result['inputs'])==2 and result['notes']=='notes'
    assert all(row['path'].startswith('input/')for row in result['inputs'])
    image.unlink();measurement.unlink();assert len(scene_details(p['project'])['inputs'])==2
    assert not(Path(p['project'])/'working/current_scene.yaml').exists()


def test_saved_phone_batch_is_reconstruction_input_without_camera_or_dimensions(tmp_path):
    from robot_learning_workbench.scene_preparation import create_scene,save_inputs
    from real2sim_builder.project import Project
    from real2sim_builder.observations import input_images
    from PIL import Image
    root=create_scene(tmp_path/'workspace','photos')['project']
    paths=[]
    for index in range(2):
        path=tmp_path/f'phone{index}.jpg';Image.new('RGB',(30,20),(index,50,0)).save(path);paths.append(path)
    save_inputs(root,paths,'컵 높이는 100mm야')
    rows,state,needs=input_images(Project(root))
    assert len(rows)==2 and not needs and state
    assert all(r['camera_type']=='external' and r['split']=='train' and r['q_measured']is None for r in rows)
    assert all(r['registration_status']=='UNREGISTERED' and not r['eligible'] for r in rows)
    assert len({r['camera'] for r in rows})==2
    original=Project(root).evidence
    save_inputs(root,paths,'updated memo')
    assert Project(root).evidence==original
    third=tmp_path/'later.jpg';Image.new('RGB',(30,20),'blue').save(third)
    save_inputs(root,[third],'later capture')
    assert input_images(Project(root))[0]==[]  # Distinct uploads never imply the same layout.
    assert len(input_images(Project(root),state)[0])==2
