from pathlib import Path
import pytest


def test_manifest_rejects_changed_bytes_and_output_escape(tmp_path):
    from real2sim_builder.stage_artifacts import manifest, verify_manifest
    path = tmp_path / 'depth.npz'
    path.write_bytes(b'original')
    record = manifest([path], {'coordinates': 'optical'})
    verify_manifest(record, output_root=tmp_path)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='integrity'):
        verify_manifest(record, output_root=tmp_path)
    with pytest.raises(ValueError, match='outside'):
        verify_manifest(manifest([path]), output_root=tmp_path / 'elsewhere')


def test_complete_artifact_requires_real_output_and_execution_provenance(tmp_path):
    from real2sim_builder.stage_artifacts import StageArtifact, manifest
    path = tmp_path / 'result.json'
    path.write_text('{}')
    a = StageArtifact.create(2, 'COMPLETE', manifest([]), manifest([path]),
                             runtime_identity={'kind': 'mock', 'worker': 'fixture'}, config={})
    a.validate(tmp_path)
    assert a.provenance['execution'] == 'mock'
    assert a.units == {'length': 'm', 'angle': 'rad'}
    path.unlink()
    with pytest.raises(ValueError, match='integrity'):
        a.validate(tmp_path)


def test_nonfinite_values_are_never_hashable_artifact_data():
    from real2sim_builder.stage_artifacts import digest
    with pytest.raises(ValueError):
        digest({'depth': float('nan')})


def test_stage_cache_identity_includes_runtime_config_and_upstream():
    from real2sim_builder.stage_artifacts import cache_key
    key = cache_key(2, {'input': 'a'}, {'resolution': 336}, {'model': 'one'})
    assert key != cache_key(2, {'input': 'b'}, {'resolution': 336}, {'model': 'one'})
    assert key != cache_key(2, {'input': 'a'}, {'resolution': 448}, {'model': 'one'})
    assert key != cache_key(2, {'input': 'a'}, {'resolution': 336}, {'model': 'two'})


def test_manifest_does_not_accept_symlinks(tmp_path):
    from real2sim_builder.stage_artifacts import manifest
    p = tmp_path / 'file'
    p.write_text('x')
    link = tmp_path / 'link'
    link.symlink_to(p)
    with pytest.raises(ValueError, match='symlink'):
        manifest([link])
