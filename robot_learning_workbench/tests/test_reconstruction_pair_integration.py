"""Real Snapshot/Pair readers with memory buses; no physical device commands."""
from pathlib import Path
import numpy as np


def test_scene_free_pair_is_discoverable_and_candidate_reuses_captured_robot(tmp_path):
    from test_robot_lifecycle import make
    from test_precision_calibration import CURRENT
    from real2sim_builder.project import Project,Candidate
    from real2sim_builder.files import sha
    from real2sim_builder.observations import input_images
    from real2sim_builder.automation import captured_robot,refit_pairs
    from robot_learning_workbench.robot.snapshots import SnapshotStore
    from robot_learning_workbench.robot.capture import snapshot_state
    follower,_,_=make(tmp_path);follower.connect()
    try:
        native,interval=follower.read();t=interval['end']['monotonic_ns']
        history=[{'timestamp_ns':t-(6-i)*100_000_000,'native':native,'raw':dict(follower.last_raw),'feedback_interval':interval}for i in range(7)]
        packets={n:{'read_start':{'monotonic_ns':t-2_000_000},'read_end':{'monotonic_ns':t-1_000_000},'sequence':1}for n in('side','wrist')}
        state=snapshot_state(follower,history,packets,{'stable':True,'window_start_ns':t-600_000_000,'window_end_ns':t})
        p=Project.create(tmp_path/'projects','new scene pair');store=SnapshotStore(p,session_id='session',model=CURRENT,mapping=follower.precision_mapper.metadata())
        rgb={n:np.full((480,640,3),31,np.uint8)for n in('real_side','real_wrist')}
        pending=store.prepare('pair1',state,rgb,now_ns=t)
        rendered={'images':{n:rgb['real_'+n]for n in('side','wrist')},'measured_q_rad':pending['sample']['q_measured'],
            'applied_sim_joint_rad':[q+.01 for q in pending['sample']['q_measured']],
            'scene_identity':{'manifest_sha256':'a'*64},'engine':'mujoco','sim_timestamp':{'monotonic_ns':t+100_000_000},
            'sim_cameras':{},'joint_mapping':follower.precision_mapper.metadata()}
        result=store.finish(pending,rendered=rendered)
        images,layout,needs=input_images(p)
        assert len(images)==2 and layout.startswith('layout_')and not needs
        assert all(i['robot_model_sha256']==sha(CURRENT)and i['scene_state_id']==layout for i in images)
        original={str(f):sha(f)for f in Path(result['path']).rglob('*')if f.is_file()}
        c=Candidate.create(p,'bootstrap');robot=captured_robot(c,images)
        assert robot['status']=='IMPORTED_REFERENCE'and c.scene['robot_model']['mapping']==follower.precision_mapper.metadata()
        report=refit_pairs(p,candidate='bootstrap',scene_state=layout,config={'objects':{}})
        assert report['status']=='NEEDS_MORE_DATA'
        assert report['code']=='PAIR_SOURCE_UNRESOLVED'
        assert c.info.get('source_revision')is None
        assert not(p.root/'working/current_scene.yaml').exists()
        assert original=={str(f):sha(f)for f in Path(result['path']).rglob('*')if f.is_file()}
    finally:follower.close()
