"""Only the essential bounded new-frame encoder remains; decode via PyAV."""
import av,numpy as np,pytest
from robot_learning_workbench.data.video import AsyncVideoWriter


def test_streaming_rgb_owned_copy_and_pts(tmp_path):
    path=tmp_path/'video.mp4';writer=AsyncVideoWriter(path,width=64,height=48,fps=30,queue_size=2)
    image=np.zeros((48,64,3),np.uint8)
    for i in range(12):image[:]=i*10;writer.write(image)
    image[:]=255;writer.close();writer.close()
    with av.open(path) as container:frames=list(container.decode(video=0))
    assert len(frames)==12 and writer.queue_peak<=3
    assert [float(f.pts*f.time_base) for f in frames]==pytest.approx([i/30 for i in range(12)])
    assert frames[0].to_ndarray(format='rgb24').mean()<2 and 107<frames[-1].to_ndarray(format='rgb24').mean()<113


def test_abort_and_invalid_rgb_never_appear_as_closed_media(tmp_path):
    path=tmp_path/'video.mp4';writer=AsyncVideoWriter(path,width=64,height=48)
    with pytest.raises(ValueError):writer.write(np.zeros((48,64,3),np.float32))
    writer.abort();writer.abort();assert not path.exists()
