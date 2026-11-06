"""Historical fixture recovery is byte-exact and never repairs the Manifest."""
import hashlib
import json
from pathlib import Path
import pytest
from restore_scene_fixtures import restore


def manifest(root, rows):
    root.mkdir()
    (root/'manifest.json').write_text(json.dumps({'files':[
        {'path':name,'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
        for name,data in rows.items()]}))


def test_restore_only_missing_exact_bytes_and_preserves_existing_files(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'missing.usda').write_bytes(b'original USD bytes')
    target=tmp_path/'fixture';manifest(target,{'missing.usda':b'original USD bytes','existing.txt':b'original'})
    (target/'existing.txt').write_bytes(b'intentionally tampered')
    before=(target/'manifest.json').read_bytes()
    assert restore(source,[target])==[str(target/'missing.usda')]
    assert (target/'missing.usda').read_bytes()==b'original USD bytes'
    assert (target/'existing.txt').read_bytes()==b'intentionally tampered'
    assert (target/'manifest.json').read_bytes()==before


def test_wrong_original_hash_cannot_partially_restore_a_fixture(tmp_path):
    source=tmp_path/'source';source.mkdir();(source/'good').write_bytes(b'good');(source/'bad').write_bytes(b'changed')
    target=tmp_path/'fixture';manifest(target,{'good':b'good','bad':b'original'})
    with pytest.raises(ValueError,match='Matching original bytes'):restore(source,[target])
    assert sorted(p.name for p in target.iterdir())==['manifest.json']
