import hashlib
from pathlib import Path
import pytest


def test_fixed_smol_patch_is_scoped_and_refuses_unknown_upstream_bytes():
    from robot_learning_workbench.learning.smol_compat import patched_source,UPSTREAM_SHA256
    import importlib.util
    path=Path(importlib.util.find_spec('lerobot').origin).parent/'policies/smolvla/modeling_smolvla.py';raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==UPSTREAM_SHA256
    result=patched_source(raw);assert 'batch.get("action_is_pad")' in result and 'num_valid' in result
    assert 'masked_fill' in result and path.read_bytes()==raw
    with pytest.raises(ValueError,match='source identity'):patched_source(raw+b'\n')
