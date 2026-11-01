"""One serial owner at 30Hz; Camera/render/filesystem work stays outside this loop."""
from collections import deque
import copy,threading,time
from .devices import DeviceError


class TeleoperationLoop:
    def __init__(self,control):
        self.control=control;self.lock=threading.RLock();self.stopped=threading.Event();self.thread=None
        self.rows=deque();self.feedback_history=deque(maxlen=180);self.error=None;self.recording_error=None;self.latest=None;control.cancelled=self.stopped.is_set
    def start(self,command_id):
        if self.recording_error:raise ValueError('Control recording failed; close this session before reconnecting')
        if self.thread and self.thread.is_alive():raise ValueError('Teleoperation already active')
        with self.lock:
            self.stopped.clear()
            try:self.error=None;self.control.start(command_id=command_id)
            except Exception:self.stopped.set();raise
            self.latest=copy.deepcopy(self.control.last_feedback);self.feedback_history.append(self.latest)
        self.thread=threading.Thread(target=self._run,name='leader-follower-control',daemon=True);self.thread.start()
    def _run(self):
        try:
            while not self.stopped.is_set():
                begin=time.monotonic()
                with self.lock:
                    if self.stopped.is_set():break
                    if len(self.rows)>=300:raise DeviceError('teleoperation','Control record queue full; no further goals',effect='not_applied')
                # Only this thread owns active serial I/O. The observation lock
                # protects published data, never a potentially blocking SDK call.
                row=self.control.tick();feedback=copy.deepcopy(self.control.last_feedback)
                with self.lock:
                    self.latest=feedback;self.feedback_history.append(feedback);self.rows.append(row)
                self.stopped.wait(max(0,1/30-(time.monotonic()-begin)))
        except Exception as error:
            self.control.stop()
            with self.lock:
                if not self.stopped.is_set():self.error=str(error)
        finally:
            self.control.stop()
    def sample(self):
        with self.lock:
            running=self.thread and self.thread.is_alive()
            if running or self.error:
                if self.latest is None:raise ValueError('First control feedback is not available')
                return copy.deepcopy(self.latest)
        # A joined/dead control thread has released serial ownership. Preserve
        # read-only observations after Teleop stops; never read alongside tick.
        self.control.feedback();feedback=copy.deepcopy(self.control.last_feedback)
        with self.lock:
            self.latest=feedback;self.feedback_history.append(feedback)
        return copy.deepcopy(feedback)
    def samples(self,after_ns=0):
        latest=self.sample();end=latest['interval']['end']['monotonic_ns']
        with self.lock:
            rows=[copy.deepcopy(row)for row in self.feedback_history if after_ns<row['interval']['end']['monotonic_ns']<=end]
        return rows or[latest]
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
    def drain(self):
        """Consume live-session diagnostics without creating a recorded Dataset."""
        with self.lock:
            rows=list(self.rows);self.rows.clear();error=self.error;self.error=None
        return rows,error
    def stop(self):
        self.stopped.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1)
            if self.thread.is_alive():raise DeviceError('teleop_stop','SDK cycle did not stop; command effect unknown',effect='unknown')
        with self.lock:self.control.stop()
