from pathlib import Path
import pytest


def test_stage_output_suggestions_never_create_or_move_data(tmp_path):
    from robot_learning_workbench.ui.paths import output_path,input_directory
    for stage,group in [('source','source'),('annotation','annotation'),('datagen','datagen'),('curation','dataset'),('convert','dataset'),('train','policy'),('simulation_evaluation','evaluation'),('scene','scenes')]:
        path=output_path(tmp_path,stage,'named-run')
        assert path==tmp_path/group/'named-run' and not path.exists()
    assert input_directory(tmp_path,'annotation','dataset')==tmp_path/'source'
    assert input_directory(tmp_path,'datagen','dataset')==tmp_path/'annotation'
    assert input_directory(tmp_path,'train','dataset')==tmp_path/'dataset'
    assert input_directory(tmp_path,'simulation_evaluation','policy')==tmp_path/'policy'
    for name in ('../escape','/absolute','a/b','..'):
        with pytest.raises(ValueError):output_path(tmp_path,'source',name)
