import importlib
from pathlib import Path
import tomllib
import pytest
from test_robot_offline_stages import plan
from robot_learning_workbench import recipe
from robot_learning_workbench.robot import offline
ROOT=Path(__file__).resolve().parents[2]


def test_offline_extra_declares_builder_and_pinned_device_sdk():
    cfg=tomllib.loads((ROOT/'robot_learning_workbench/pyproject.toml').read_text())
    dependencies=cfg['project']['optional-dependencies']['offline']
    assert any(x.startswith('real2sim-builder>=')for x in dependencies)
    assert 'lerobot==0.4.1'in dependencies


def test_missing_capture_dependency_is_explicit_before_output(tmp_path,monkeypatch):
    p=plan(tmp_path,'precision_calibration')
    from dataclasses import replace
    p=replace(p,stage='capture')
    original=importlib.import_module
    def missing(name,package=None):
        if name=='real2sim_builder.capture':raise ModuleNotFoundError("No module named 'real2sim_builder'",name='real2sim_builder')
        return original(name,package=package)
    monkeypatch.setattr(importlib,'import_module',missing)
    with pytest.raises(ValueError,match='offline.*extra')as error:
        offline.run(p,events=lambda _:None,commands=lambda:())
    assert error.value.code=='STAGE_DEPENDENCY_MISSING'
    assert not p.output_path.exists()
