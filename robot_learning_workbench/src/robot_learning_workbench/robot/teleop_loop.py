"""One serial owner at 30Hz; Camera/render/filesystem work stays outside this loop."""
from collections import deque
import copy,threading,time
from .devices import DeviceError


class TeleoperationLoop:
    def __init__(self,control):
        self.control=control;self.lock=threading.RLock();self.stopped=threading.Event();self.thread=None
        self.rows=deque();self.error=None;self.recording_error=None;self.latest=None;control.cancelled=self.stopped.is_set
    def prepare(self,limits):
        if self.recording_error:raise ValueError('Control recording failed; close this session before reconnecting')
        if self.control.active:raise ValueError('Stop Teleoperation before preparing another approval')
        self.stop()
        with self.lock:
            if limits:self.control.configure(limits['max_command_step_rad'],limits['max_follow_error_rad'])
            self.error=None;return self.control.propose()
    def start(self,approval):
        if self.thread and self.thread.is_alive():raise ValueError('Teleoperation already active')
        with self.lock:
            self.stopped.clear()
            try:self.control.start(approval)
            except Exception:self.stopped.set();raise
            self.latest=copy.deepcopy(self.control.last_feedback)
        self.thread=threading.Thread(target=self._run,name='leader-follower-control',daemon=True);self.thread.start()
    def _run(self):
        try:
            while not self.stopped.is_set():
                begin=time.monotonic()
                with self.lock:
                    if self.stopped.is_set():break
                    if len(self.rows)>=300:raise DeviceError('teleoperation','Control record queue full; no further goals',effect='not_applied')
                    row=self.control.tick();self.latest=copy.deepcopy(self.control.last_feedback);self.rows.append(row)
                self.stopped.wait(max(0,1/30-(time.monotonic()-begin)))
        except Exception as error:
            with self.lock:
                if not self.stopped.is_set():self.error=str(error)
                self.control.stop()
        finally:
            with self.lock:self.control.stop()
    def sample(self):
        if not self.lock.acquire(timeout=.25):
            self.stopped.set();raise DeviceError('teleoperation','SDK feedback deadline exceeded; no further goals',effect='unknown')
        try:
            if self.thread and self.thread.is_alive():
                if self.latest is None:raise ValueError('First control feedback is not available')
                return copy.deepcopy(self.latest)
            self.control.feedback();return copy.deepcopy(self.control.last_feedback)
        finally:self.lock.release()
    def record_to(self,recorder):
        if self.recording_error:return None
        with self.lock:
            rows=list(self.rows);error=self.error;self.error=None
        written=0
        try:
            for row in rows:recorder.append(row);written+=1
        except Exception as failure:
            self.recording_error=str(failure);self.stop();raise
        finally:
            with self.lock:
                for _ in range(written):self.rows.popleft()
        return error
    def stop(self):
        self.stopped.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
            if self.thread.is_alive():raise DeviceError('teleop_stop','SDK cycle did not stop; command effect unknown',effect='unknown')
        with self.lock:self.control.stop()
