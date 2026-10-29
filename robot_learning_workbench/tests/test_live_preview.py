"""Real RGB producer/consumer contract; synthetic pixels are unit fixtures only."""
from pathlib import Path
import numpy as np
import pytest
from robot_learning_workbench import run
from robot_learning_workbench.data import video


def test_real_video_writer_publishes_bounded_current_rgb_and_cleans(tmp_path):
    root=tmp_path/'run-a';root.mkdir();events=[];image=np.zeros((480,640,3),np.uint8);image[:,:,1]=177
    with run.preview_session(root,events.append,interval_s=0):
        with_writer=video.AsyncVideoWriter(tmp_path/'side.mp4')
        for _ in range(7):with_writer.write(image)
        with_writer.close()
        meta,ppm=run.read_preview_frame(root,'side')
        assert meta['run_id']=='run-a' and meta['generation']==7 and meta['frame_index']==6
        assert ppm.endswith(image.tobytes())
        assert len(list((root/'preview').glob('side-*.ppm')))==2
        assert len(events)==7
    assert not (root/'preview').exists()
    assert run.read_preview_frame(root,'side') is None


def test_preview_generation_and_run_identity_prevent_stale_mixing(tmp_path):
    root=tmp_path/'one';root.mkdir();image=np.zeros((480,640,3),np.uint8)
    with run.preview_session(root,lambda _:None,interval_s=0):
        with_writer=video.AsyncVideoWriter(tmp_path/'wrist.mp4');with_writer.write(image);with_writer.close()
        meta,ppm=run.read_preview_frame(root,'wrist');path=root/'preview'/('wrist-'+str(meta['slot'])+'.ppm')
        path.write_bytes(ppm.replace(b'one ',b'old ',1))
        assert run.read_preview_frame(root,'wrist') is None


def test_display_failure_does_not_drop_recording(tmp_path):
    root=tmp_path/'test';root.mkdir();events=[]
    with run.preview_session(root,events.append,interval_s=0):
        (root/'preview').rmdir();(root/'preview').write_text('controlled IO failure')
        writer=video.AsyncVideoWriter(tmp_path/'side.mp4');writer.write(np.zeros((480,640,3),np.uint8));writer.close()
        assert writer.frames==1 and any(e['kind']=='log' for e in events)
    assert (tmp_path/'side.mp4').is_file()


def test_preview_setup_failure_never_prevents_stage(tmp_path):
    root=tmp_path/'test';root.mkdir();(root/'preview').write_text('existing path')
    events=[];ran=False
    with run.preview_session(root,events.append):ran=True
    assert ran and (root/'preview').read_text()=='existing path'
    assert any(e['kind']=='log' for e in events)


def test_preview_selected_env_has_full_resolution_and_bounded_storage(tmp_path):
    root=tmp_path/'run';root.mkdir();events=[];image=np.zeros((480,640,3),np.uint8)
    with run.preview_session(root,events.append,interval_s=0):
        run.select_preview_env(root,3)
        a=video.AsyncVideoWriter(tmp_path/'a/side.mp4',env_index=0);b=video.AsyncVideoWriter(tmp_path/'b/side.mp4',env_index=3)
        a.write(image);assert run.read_preview_frame(root,'side') is None
        image[:,:,2]=200;b.write(image);b.close();a.close()
        meta,raw=run.read_preview_frame(root,'side');assert meta['env_index']==3 and meta['shape']==[480,640,3]
        assert raw.endswith(image.tobytes()) and meta['published_monotonic_ns']>0
    assert not (root/'preview').exists()


def test_pair_preview_has_four_bounded_channels(tmp_path):
    root=tmp_path/'pair';root.mkdir();rgb=np.full((480,640,3),77,np.uint8)
    with run.preview_session(root,lambda _:None,interval_s=0):
        for name in('side','wrist','sim_side','sim_wrist'):
            video._preview_sink(name,rgb,1,0,0)
            assert run.read_preview_frame(root,name)[0]['camera']==name
        assert len(list((root/'preview').glob('*.ppm')))==4
