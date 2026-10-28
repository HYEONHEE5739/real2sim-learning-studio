"""Bounded new RGB -> MP4 recording using PyAV; no Dataset reader/index/hash layer."""
import queue
import threading
import time
from fractions import Fraction
from pathlib import Path
import av
import numpy as np


_preview_sink=None  # Owned only by the current worker preview_session.


class AsyncVideoWriter:
    """Copy into a bounded queue; backpressure never drops observation frames."""
    def __init__(self, video_path, codec='libx264', fps=30, width=640, height=480,
                 crf=18, queue_size=8,env_index=0):
        self.video_path=Path(video_path);self.codec=codec;self.fps=Fraction(str(fps)).limit_denominator(1000000)
        if type(env_index) is not int or env_index<0:raise ValueError('Nonnegative video env required')
        self.env_index=env_index
        self.width=int(width);self.height=int(height);self.crf=int(crf)
        if self.fps<=0 or not 0<=self.crf<=51 or queue_size<1:
            raise ValueError('Invalid video FPS/CRF/queue size')
        self._queue=queue.Queue(maxsize=queue_size);self._error=None
        self.encoding_seconds=0.;self.queue_peak=0
        self._frame_index=0;self.frames=0;self._closed=False;self._cancel=threading.Event()
        self._thread=threading.Thread(target=self._worker,name='video-'+self.video_path.stem,daemon=True)
        self._thread.start()

    def write(self,image):
        self._raise_if_failed()
        if self._closed:raise RuntimeError('Video writer is closed: '+str(self.video_path))
        if image.dtype!=np.uint8 or image.shape!=(self.height,self.width,3):
            raise ValueError('RGB video requires uint8 [height,width,3]')
        # Observations/render buffers may be reused as soon as this call returns.
        image=np.array(image,copy=True,order='C')
        while True:
            self._raise_if_failed()
            try:
                self._queue.put(image,timeout=.05);self.frames+=1
                if _preview_sink is not None:_preview_sink(self.video_path.stem,image,self.frames-1,float((self.frames-1)/self.fps),self.env_index)
                return
            except queue.Full:continue

    def close(self):
        if not self._closed:
            self._closed=True
            while self._thread.is_alive():
                self._raise_if_failed()
                try:self._queue.put(None,timeout=.05);break
                except queue.Full:continue
            self._thread.join()
        self._raise_if_failed()
        if self._frame_index!=self.frames:raise RuntimeError('Video frame count mismatch')

    def abort(self):
        self._closed=True;self._cancel.set();self._thread.join()
        self.video_path.unlink(missing_ok=True)

    def _worker(self):
        try:
            self.video_path.parent.mkdir(parents=True,exist_ok=True)
            with av.open(str(self.video_path),'w',format='mp4') as container:
                stream=container.add_stream(self.codec,rate=self.fps,
                    options={'crf':str(self.crf),'preset':'veryfast','threads':'1'})
                stream.width=self.width;stream.height=self.height;stream.pix_fmt='yuv420p'
                stream.time_base=1/self.fps
                while not self._cancel.is_set():
                    try:image=self._queue.get(timeout=.05)
                    except queue.Empty:continue
                    if image is None:break
                    begin=time.perf_counter();self.queue_peak=max(self.queue_peak,self._queue.qsize()+1)
                    frame=av.VideoFrame.from_ndarray(image,format='rgb24')
                    frame.pts=self._frame_index;frame.time_base=1/self.fps
                    for packet in stream.encode(frame):container.mux(packet)
                    self.encoding_seconds+=time.perf_counter()-begin
                    self._frame_index+=1
                if not self._cancel.is_set():
                    begin=time.perf_counter()
                    for packet in stream.encode():container.mux(packet)
                    self.encoding_seconds+=time.perf_counter()-begin
        except Exception as exc:self._error=exc

    def _raise_if_failed(self):
        if self._error is not None:
            raise RuntimeError(f'Video encoding failed: {self.video_path}: {self._error}') from self._error
