"""SIGKILL only our disposable children; published official files stay readable."""
import os,subprocess,sys,time
from pathlib import Path
import pytest
from robot_learning_workbench.data import native as n,lerobot as l
from test_native_dataset import episode,execution


def kill_at_marker(code,root):
    marker=root/'ready'
    child=subprocess.Popen([sys.executable,'-B','-c',code,str(root)],env=os.environ.copy(),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        deadline=time.monotonic()+30
        while not marker.exists():
            if child.poll() is not None:raise AssertionError(child.communicate())
            if time.monotonic()>deadline:raise AssertionError('child did not reach controlled boundary')
            time.sleep(.02)
        child.kill();child.communicate(timeout=10)
        assert child.returncode==-9
    finally:
        if child.poll() is None:child.kill();child.wait(timeout=10)


def test_killed_hdf5_child_only_exposes_prior_sealed_segment(tmp_path):
    code='''
import sys,time,json,torch
from pathlib import Path
from robot_learning_workbench.data import native as n
root=Path(sys.argv[1]);cfg=json.loads((root/'execution.json').read_text())
r=n.NativeRun(root/'run',cfg)
def episode():
 e=n.native_api()[0]();e.data={'actions':torch.zeros((3,7))};e.success=True;return e
s=r.segment('sealed');a=r.claim_attempt(s);s.write_episode(episode(),episode_id='first');s.record_attempt(a,status='success',episode_id='first');s.commit()
s=r.segment('unfinished');r.claim_attempt(s);s.write_episode(episode(),episode_id='partial');s.handler.flush()
(root/'ready').write_text('ready');time.sleep(300)
'''
    import json
    (tmp_path/'execution.json').write_text(json.dumps(execution()))
    kill_at_marker(code,tmp_path)
    catalog=n.load_catalog(tmp_path/'run');assert [e.episode_id for e in catalog.episodes]==['first']
    handler=n.open_native(catalog.episodes[0]);assert len(handler.load_episode('demo_0','cpu').data['actions'])==3;handler.close()
    before=n.file_sha256(catalog.episodes[0].file)
    with pytest.raises(n.DataError):n.resume_to(tmp_path/'run',tmp_path/'blocked',execution())
    report=n.recover(tmp_path/'run',acknowledge_interrupted=True)
    assert report['interrupted_attempts']==[2] and not report['staging_promoted']
    with n.resume_to(tmp_path/'run',tmp_path/'resumed',execution()) as run:
        s=run.segment('next');assert run.claim_attempt(s)['attempt']==3
    assert n.file_sha256(catalog.episodes[0].file)==before


def test_killed_lerobot_child_cannot_invalidate_prior_finalized_dataset(tmp_path):
    import json
    with n.NativeRun(tmp_path/'source',execution()) as run:
        s=run.segment('one');s.write_episode(episode(),episode_id='first');s.commit()
    good=l.materialize(run.root,tmp_path/'good')
    before={str(p.relative_to(good)):n.file_sha256(p) for p in good.rglob('*') if p.is_file()}
    code='''
import sys,time,numpy as np
from pathlib import Path
from robot_learning_workbench.data import lerobot as l
root=Path(sys.argv[1]);d=l.create_staging(root/'pending',features={'action':{'dtype':'float64','shape':(6,),'names':None}},fps=30)
for i in range(3):d.add_frame({'action':np.zeros(6,dtype=np.float64),'task':'hold'})
d.save_episode();(root/'ready').write_text('ready');time.sleep(300)
'''
    kill_at_marker(code,tmp_path)
    assert not (tmp_path/'pending').exists()
    with pytest.raises(n.DataError):l.create_staging(tmp_path/'pending',features={},fps=30)
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    assert len(LeRobotDataset('workbench/native',root=good,video_backend='pyav'))==3
    assert before=={str(p.relative_to(good)):n.file_sha256(p) for p in good.rglob('*') if p.is_file()}
