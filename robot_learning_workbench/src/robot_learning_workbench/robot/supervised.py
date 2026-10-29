"""A session-local six-axis command capability; RO device APIs stay RO.

SDK: LeRobot0.4.1 SO101Follower.send_action / MotorsBus.sync_write(num_retry=0).
No configure, automatic homing, target hold, torque release, or Policy control.
"""
import time,uuid
import numpy as np
from .calibration import JOINTS
from .capture import observed_positions
from .control import command_target
from .devices import DeviceError
from ..data.native import digest


class Teleoperation:
    def __init__(self,leader,follower,*,model_bounds,session_id,max_step_rad,max_follow_error_rad):
        for value in (max_step_rad,max_follow_error_rad):
            if type(value)not in(int,float)or not np.isfinite(value)or value<=0:raise ValueError('Explicit positive command/follow budgets required')
        self.leader=leader;self.follower=follower;self.bounds=model_bounds;self.session_id=session_id
        self.max_step=max_step_rad;self.max_follow=max_follow_error_rad;self.active=False;self.proposal=None;self.consumed=set()
        self.last_heartbeat_ns=time.monotonic_ns();self.last_tick_ns=None;self.last_target=None;self.last_raw_goal=None;self.sequence=0;self.last_attempt=None

    def heartbeat(self):self.last_heartbeat_ns=time.monotonic_ns()

    def feedback(self):
        native,interval=self.follower.read();q=observed_positions(self.follower.precision_mapper,native,raw=self.follower.last_raw,motor_specs=self.follower.motor_specs)
        return native,interval,np.array([q[n]for n in JOINTS])

    def _target(self):
        native,interval=self.leader.read()
        target,command,details=command_target(native,leader_mapper=self.leader.precision_mapper,follower=self.follower,model_bounds=self.bounds,leader_raw=self.leader.last_raw)
        return target,command,details,interval

    def _start_state(self):
        self.leader._check_identity(hardware=True);self.follower._check_identity(hardware=True)
        _,interval,q=self.feedback();bus=self.follower.bus;raw=dict(self.follower.last_raw)
        goal=bus.sync_read('Goal_Position',normalize=False);mode=bus.sync_read('Operating_Mode',normalize=False);torque=bus.sync_read('Torque_Enable',normalize=False)
        if any(type(raw[n])is not int or abs(goal[n]-raw[n])>1 for n in JOINTS):raise DeviceError('teleop_preflight','Initial Goal differs from actual feedback; no automatic Hold rewrite',effect='not_applied')
        if set(mode)!=set(JOINTS)or any(mode[n]!=0 for n in JOINTS):raise DeviceError('teleop_preflight','All joints must already be in position mode',effect='not_applied')
        if set(torque)!=set(JOINTS)or any(torque[n]not in(0,1)for n in JOINTS):raise ValueError('Unknown Torque state')
        target,_,details,_=self._target()
        bounds=np.asarray(details['bounds_rad'])
        if np.any(q<bounds[:,0])or np.any(q>bounds[:,1]):raise DeviceError('teleop_preflight','Actual initial feedback outside approved model/motor bounds',effect='not_applied')
        if np.max(abs(target-q))>self.max_step:raise DeviceError('teleop_preflight','Leader initial target is too far from Follower feedback',effect='not_applied')
        return dict(raw=raw,goal=goal,mode=mode,torque=torque,measured_model_rad=q.tolist(),initial_target_rad=target.tolist(),bounds_rad=details['bounds_rad'],
                    follower_identity=self.follower.identity,leader_identity=self.leader.identity,follower_mapping=self.follower.precision_mapper.metadata()['sha256'],leader_mapping=self.leader.precision_mapper.metadata()['sha256'])

    def propose(self):
        if self.active:raise ValueError('Teleoperation already active')
        state=self._start_state();now=time.monotonic_ns()
        self.proposal={'session_id':self.session_id,'nonce':uuid.uuid4().hex,'state':state,'expires_ns':now+30_000_000_000,
                       'max_step_rad':self.max_step,'max_follow_error_rad':self.max_follow,'stop_policy':'preserve_torque_no_new_goal'}
        self.proposal['sha256']=digest(self.proposal);return self.proposal.copy()

    def start(self,approval):
        required={'proposal_sha256','supervised','clear','stop_ready','direction_checked','ranges_checked','preserve_torque'}
        if self.active or self.proposal is None:raise ValueError('No current approval proposal, or already active')
        p=self.proposal;key=p['sha256']
        if key in self.consumed:raise ValueError('Approval already consumed')
        if set(approval)!=required or approval['proposal_sha256']!=key or any(approval[n]is not True for n in required-{'proposal_sha256'}):raise ValueError('Explicit on-site approval required')
        if time.monotonic_ns()>p['expires_ns']:raise ValueError('Approval expired; review fresh feedback')
        if digest(self._start_state())!=digest(p['state']):raise ValueError('Feedback/Goal/Calibration changed; fresh approval required')
        self.consumed.add(key);self.proposal=None
        try:
            begin=time.monotonic_ns()
            if any(v==0 for v in p['state']['torque'].values()):
                self.follower.bus.sync_write('Torque_Enable',dict.fromkeys(JOINTS,1),normalize=False,num_retry=0)
                if any(v!=1 for v in self.follower.bus.sync_read('Torque_Enable',normalize=False).values()):raise ValueError('Torque activation readback differs')
            if time.monotonic_ns()-begin>200_000_000:raise ValueError('Torque activation deadline exceeded; no Goal commands')
            self.last_target=np.array(p['state']['measured_model_rad']);self.last_raw_goal={self.follower.bus.motors[n].id:p['state']['goal'][n]for n in JOINTS};self.last_tick_ns=time.monotonic_ns();self.heartbeat();self.active=True
        except Exception as error:
            self.stop();raise DeviceError('teleop_activate',str(error),effect='unknown')from error

    def stop(self):
        self.active=False;self.proposal=None

    def tick(self):
        if not self.active:raise DeviceError('teleoperation','No approved active Teleoperation',effect='not_applied')
        send_attempted=False;attempt=None
        try:
            now=time.monotonic_ns()
            if now-self.last_heartbeat_ns>1_500_000_000 or now-self.last_tick_ns>200_000_000:raise ValueError('Stale session heartbeat/control cycle')
            self.leader._check_identity();self.follower._check_identity()
            _,feedback,q=self.feedback();target,command,details,leader_interval=self._target()
            if np.max(abs(target-self.last_target))>self.max_step:raise ValueError('Previous applied target jump exceeds approved budget')
            if np.max(abs(q-self.last_target))>self.max_follow:raise ValueError('Follower tracking error exceeds approved budget')
            begin=time.monotonic_ns()
            if begin-feedback['end']['monotonic_ns']>100_000_000 or begin-leader_interval['end']['monotonic_ns']>100_000_000:raise ValueError('Stale feedback/Leader command')
            raw=dict(self.follower.last_encoded_goal_raw);duplicate=raw==self.last_raw_goal
            attempt=dict(sequence=self.sequence+1,requested_model_rad=details['requested_model_rad'],target_payload_rad=target.tolist(),sdk_goal_raw=raw,
                         measured_model_rad=q.tolist(),feedback_interval=feedback,leader_interval=leader_interval,send_begin_ns=begin,command_sent=False,effect='not_applied')
            self.last_attempt=attempt
            if not duplicate:
                # Encoding already ran strict model/motor/Precision/SDK checks.
                send_attempted=True;returned=self.follower.device.send_action({n+'.pos':command[n]for n in JOINTS})
                if returned!={n+'.pos':command[n]for n in JOINTS}:raise ValueError('SDK changed the preflighted target')
            end=time.monotonic_ns();attempt.update(send_end_ns=end,send_latency_s=(end-begin)/1e9,command_sent=not duplicate,effect='sdk_returned'if not duplicate else'not_applied')
            if end-now>200_000_000:raise ValueError('Control/send deadline exceeded; no further goals')
            self.last_tick_ns=end;self.sequence+=1;self.last_target=target;self.last_raw_goal=raw
            return dict(sequence=self.sequence,timestamp_ns=feedback['end']['monotonic_ns'],measured_model_rad=q.tolist(),requested_model_rad=details['requested_model_rad'],
                        applied_model_rad=target.tolist(),saturation=details['saturation'],sdk_goal_raw=raw,command_sent=not duplicate,duplicate_suppressed=duplicate,
                        feedback_interval=feedback,leader_interval=leader_interval,send_latency_s=(end-begin)/1e9,follow_error_rad=(q-target).tolist())
        except Exception as error:
            if attempt is not None:attempt.update(command_sent='unknown'if send_attempted else False,effect='unknown'if send_attempted else'not_applied',error=str(error),send_end_ns=time.monotonic_ns())
            self.stop();raise DeviceError('teleoperation',str(error),effect='unknown'if send_attempted else'not_applied')from error
