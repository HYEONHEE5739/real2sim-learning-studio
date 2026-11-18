"""Metrics remain immediate; diagnostic images derive from immutable saved RGB."""
from pathlib import Path
import numpy as np
import pytest
from PIL import Image
from robot_learning_workbench.data.native import atomic_json,file_sha256
from robot_learning_workbench.robot import pairs


def pair_fixture(tmp_path):
    root=tmp_path/'capture';root.mkdir()
    rgb=np.arange(12*16*3,dtype=np.uint8).reshape(12,16,3)
    sim=np.roll(rgb,1,axis=1)
    files={}
    for n in('side','wrist'):
        path=root/(n+'.png');Image.fromarray(rgb).save(path);files[path.name]=file_sha256(path)
    atomic_json(root/'metadata.json',dict(files=files,images=[dict(camera=n,path=n+'.png')for n in('side','wrist')]))
    pending=dict(sample=dict(q_measured=[0.]*6,timestamp_ns=1),quality=[])
    rendered=dict(images=dict.fromkeys(('side','wrist'),sim),measured_q_rad=[0.]*6,applied_sim_joint_rad=[0.]*6,scene_identity={'manifest_sha256':'a'*64})
    pairs.write_pair(root,dict(project_id='test',snapshots=[dict(path='.')]),pending,rendered,diagnostics=False)
    return root,rgb,sim


def test_deferred_comparisons_keep_metrics_and_leave_originals_unchanged(tmp_path):
    import json
    root,real,sim=pair_fixture(tmp_path)
    pair=json.loads((root/'pair.json').read_text())
    assert pair['comparison_images']['status']=='DEFERRED'
    assert all({'mae','rmse','edge_iou'}<=set(row)for row in pair['comparison'].values())
    assert len(list(root.rglob('*.png')))==4
    before={str(p.relative_to(root)):file_sha256(p)for p in root.rglob('*')if p.is_file()}
    paths=pairs.render_comparisons(root,tmp_path/'derived')
    assert len(paths)==6
    assert np.array_equal(np.asarray(Image.open(tmp_path/'derived/side/overlay.png')),np.rint((real.astype(float)+sim)/2).astype(np.uint8))
    assert before=={str(p.relative_to(root)):file_sha256(p)for p in root.rglob('*')if p.is_file()}


def test_deferred_comparisons_reject_changed_source_and_capture_destination(tmp_path):
    root,_,_=pair_fixture(tmp_path)
    with pytest.raises(ValueError,match='original|outside|immutable'):
        pairs.render_comparisons(root,root/'bad')
    path=root/'sim_side.png';path.write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed|hash'):
        pairs.render_comparisons(root,tmp_path/'derived')


def test_details_generate_comparisons_on_demand_and_release_temporary_files(tmp_path):
    from test_ui_restoration import qt
    root,_,_=pair_fixture(tmp_path)
    originals={str(p.relative_to(root)):file_sha256(p)for p in root.rglob('*')if p.is_file()}
    qt('''
import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication,QPushButton
from robot_learning_workbench.ui.session_results import ResultsDialog
app=QApplication([])
root=Path(sys.argv[1])/'capture'
dialog=ResultsDialog({'path':str(root),'id':'synthetic'})
dialog.show();app.processEvents()
button=next(b for b in dialog.findChildren(QPushButton)if b.text().startswith('비교 이미지 생성'))
initial=dialog.selection.count()
folder=Path(dialog.comparison_temporary.path())
assert not list(folder.rglob('*.png'))
button.click();app.processEvents()
assert dialog.selection.count()==initial+6 and not button.isEnabled()
assert len(list(folder.rglob('*.png')))==6
dialog.selection.setCurrentIndex(initial+1);app.processEvents()
dialog.close();app.processEvents()
assert not folder.exists()
''',tmp_path)
    assert originals=={str(p.relative_to(root)):file_sha256(p)for p in root.rglob('*')if p.is_file()}


def test_pair_is_separate_from_raw_metadata(tmp_path):
    import json
    root,_,_=pair_fixture(tmp_path)
    assert set(json.loads((root/'metadata.json').read_text())['files'])=={'side.png','wrist.png'}
    assert (root/'pair-manifest.json').is_file()
