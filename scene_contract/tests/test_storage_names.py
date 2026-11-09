from pathlib import Path


def test_readable_collisions_and_content_deduplication(tmp_path):
    from scene_contract.naming import reserve_directory,copy_named
    assert reserve_directory(tmp_path,'Auto Version').name=='auto-version'
    assert reserve_directory(tmp_path,'Auto Version').name=='auto-version-2'
    first=tmp_path/'source1';second=tmp_path/'source2';first.mkdir();second.mkdir()
    (first/'scene_img1.jpg').write_bytes(b'original');(second/'scene_img1.jpg').write_bytes(b'different')
    store=tmp_path/'photos'
    assert copy_named(first/'scene_img1.jpg',store).name=='scene_img1.jpg'
    assert copy_named(first/'scene_img1.jpg',store).name=='scene_img1.jpg'
    assert copy_named(second/'scene_img1.jpg',store).name=='scene_img1_2.jpg'
    assert (store/'scene_img1.jpg').read_bytes()==b'original'


def test_new_projects_have_readable_folders_and_independent_identity(tmp_path):
    from real2sim_builder.project import Project
    a=Project.create(tmp_path,'Auto Version');b=Project.create(tmp_path,'Auto Version')
    assert a.root.name=='auto-version'and b.root.name=='auto-version-2'
    assert a.info['id']!=b.info['id']and a.info['id']!=a.root.name
