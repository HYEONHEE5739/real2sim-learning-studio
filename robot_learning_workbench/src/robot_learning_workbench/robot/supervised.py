"""A session-local six-axis command capability; RO device APIs stay RO.

SDK: LeRobot0.4.1 SO101Follower.send_action / MotorsBus.sync_write(num_retry=0).
No configure, automatic homing, unapproved activation, or Policy control.
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
            if value is None:continue
            if type(value)not in(int,float)or not np.isfinite(value)or value<=0:raise ValueError('Explicit positive command/follow budgets required')
        self.leader=leader;self.follower=follower;self.bounds=model_bounds;self.session_id=session_id
        self.max_step=max_step_rad;self.max_follow=max_follow_error_rad;self.active=False;self.proposal=None;self.consumed=set()
        self.last_heartbeat_ns=time.monotonic_ns();self.last_tick_ns=None;self.last_target=None;self.last_raw_goal=None;self.sequence=0;self.last_attempt=None;self.last_activation=None;self.last_feedback=None;self.cancelled=lambda:False

    def heartbeat(self):self.last_heartbeat_ns=time.monotonic_ns()

    def configuration_issue(self):
        if self.max_step is None or self.max_follow is None:
            return 'Teleoperation 시작에서 목표 변화·추종 오차 제한을 설정하세요. YAML 편집이나 재연결은 필요하지 않습니다.'
        return ''

    def feedback(self):
        native,interval=self.follower.read();q=observed_positions(self.follower.precision_mapper,native,raw=self.follower.last_raw,motor_specs=self.follower.motor_specs)
        self.last_feedback={'native':dict(native),'interval':interval,'raw':dict(self.follower.last_raw),'q_measured':[q[n]for n in JOINTS]}
        return native,interval,np.array([q[n]for n in JOINTS])

    def _target(self):
        native,interval=self.leader.read()
        target,command,details=command_target(native,leader_mapper=self.leader.precision_mapper,follower=self.follower,model_bounds=self.bounds,leader_raw=self.leader.last_raw)
        return target,command,details,interval

    def _start_state(self):
        self.leader._check_identity(hardware=True);self.follower._check_identity(hardware=True)
        _,interval,q=self.feedback();bus=self.follower.bus;raw=dict(self.follower.last_raw)
        goal=bus.sync_read('Goal_Position',normalize=False);mode=bus.sync_read('Operating_Mode',normalize=False);torque=bus.sync_read('Torque_Enable',normalize=False)
        leader_torque=self.leader.bus.sync_read('Torque_Enable',normalize=False)
        if set(leader_torque)!=set(JOINTS)or any(v not in(0,1)for v in leader_torque.values()):raise ValueError('Unknown Leader Torque state')
        if any(type(raw[n])is not int or type(goal[n])is not int for n in JOINTS):raise ValueError('Invalid raw feedback/Goal registers')
        if set(mode)!=set(JOINTS)or any(mode[n]!=0 for n in JOINTS):raise DeviceError('teleop_preflight','All joints must already be in position mode',effect='not_applied')
        if set(torque)!=set(JOINTS)or any(torque[n]not in(0,1)for n in JOINTS):raise ValueError('Unknown Torque state')
        if any(torque[n] and abs(goal[n]-raw[n])>1 for n in JOINTS):raise DeviceError('teleop_preflight','Powered Goal differs from actual feedback; stop and inspect the arm',effect='not_applied')
        target,_,details,leader_interval=self._target()
        bounds=np.asarray(details['bounds_rad'])
        if np.any(q<bounds[:,0])or np.any(q>bounds[:,1]):raise DeviceError('teleop_preflight','Actual initial feedback outside approved model/motor bounds',effect='not_applied')
        if np.max(abs(target-q))>self.max_step:raise DeviceError('teleop_preflight','Leader initial target is too far from Follower feedback',effect='not_applied')
        return dict(raw=raw,goal=goal,mode=mode,torque=torque,leader_torque=leader_torque,feedback_end_ns=interval['end']['monotonic_ns'],leader_end_ns=leader_interval['end']['monotonic_ns'],measured_model_rad=q.tolist(),initial_target_rad=target.tolist(),bounds_rad=details['bounds_rad'],
                    follower_identity=self.follower.identity,leader_identity=self.leader.identity,follower_mapping=self.follower.precision_mapper.metadata()['sha256'],leader_mapping=self.leader.precision_mapper.metadata()['sha256'])

    def propose(self):
        if self.configuration_issue():raise ValueError('Explicit reviewed command/follow budget required before motion; observation needs none')
        if self.active:raise ValueError('Teleoperation already active')
        state=self._start_state();now=time.monotonic_ns()
        self.proposal={'session_id':self.session_id,'nonce':uuid.uuid4().hex,'state':state,'expires_ns':now+30_000_000_000,
                       'max_step_rad':self.max_step,'max_follow_error_rad':self.max_follow,'stop_policy':'preserve_torque_no_new_goal',
                       'authorization':'supervised_leader_teleoperation_only',
                       'initialize_goal':{n:state['raw'][n]for n in JOINTS if not state['torque'][n]},
                       'release_leader_torque':[n for n in JOINTS if state['leader_torque'][n]],
                       'physical_verified':False}
        self.proposal['sha256']=digest(self.proposal);return self.proposal.copy()

    def configure(self,max_step_rad,max_follow_error_rad):
        if self.active:raise ValueError('Stop Teleoperation before changing motion limits')
        for value in(max_step_rad,max_follow_error_rad):
            if type(value)not in(int,float)or not np.isfinite(value)or value<=0:raise ValueError('Explicit positive command/follow budgets required')
        self.max_step=max_step_rad;self.max_follow=max_follow_error_rad;self.proposal=None

    def _activation_feedback(self,approved):
        _,interval,q=self.feedback();raw=dict(self.follower.last_raw);bounds=np.asarray(approved['bounds_rad'])
        if any(abs(raw[n]-approved['raw'][n])>1 for n in JOINTS):raise ValueError('Follower moved during activation; fresh pose approval required')
        if np.any(q<bounds[:,0])or np.any(q>bounds[:,1]):raise ValueError('Activation feedback outside approved bounds')
        if interval['end']['monotonic_ns']-interval['start']['monotonic_ns']>100_000_000:raise ValueError('Activation feedback read exceeded100ms')
        return raw

    def start(self,approval):
        required={'proposal_sha256','supervised','clear','stop_ready','direction_checked','ranges_checked','preserve_torque','initialize_goal'}
        if self.active or self.proposal is None:raise ValueError('No current approval proposal, or already active')
        p=self.proposal;key=p['sha256']
        if key in self.consumed:raise ValueError('Approval already consumed')
        if set(approval)!=required or approval['proposal_sha256']!=key or any(approval[n]is not True for n in required-{'proposal_sha256'}):raise ValueError('Explicit on-site approval required')
        if time.monotonic_ns()>p['expires_ns']:raise ValueError('Approval expired; review fresh feedback')
        current=self._start_state();original=p['state']
        fixed=('goal','mode','torque','leader_torque','bounds_rad','follower_identity','leader_identity','follower_mapping','leader_mapping')
        if any(digest(current[k])!=digest(original[k])for k in fixed)or any(abs(current['raw'][n]-original['raw'][n])>1 for n in JOINTS):raise ValueError('Feedback/Goal/Calibration changed; fresh approval required')
        if np.max(abs(np.array(current['initial_target_rad'])-original['initial_target_rad']))>self.max_step:raise ValueError('Leader changed; fresh approval required')
        self.consumed.add(key);self.proposal=None
        self.last_activation={'proposal_sha256':key,'goal_initialized':False,'leader_torque_released':False,'follower_torque_enabled':False,'effect':'not_applied','state':current}
        try:
            begin=time.monotonic_ns()
            if self.cancelled():raise ValueError('Teleoperation stopped before activation')
            if any(begin-current[k]>100_000_000 for k in('feedback_end_ns','leader_end_ns')):raise ValueError('Stale activation feedback; no register writes')
            if p['release_leader_torque']:
                self.last_activation['effect']='unknown'
                self.leader.bus.sync_write('Torque_Enable',dict.fromkeys(p['release_leader_torque'],0),normalize=False,num_retry=0)
                if any(self.leader.bus.sync_read('Torque_Enable',normalize=False).values()):raise ValueError('Leader torque release readback differs')
                self.last_activation['leader_torque_released']=True
                if time.monotonic_ns()-begin>200_000_000:raise ValueError('Leader activation deadline exceeded; no Follower commands')
            # Only the approved, currently unpowered joints may be initialized.
            # Validate integer encoding/ranges through the same command path first.
            if p['initialize_goal']:
                from .control import encode_model_target
                encode_model_target(current['measured_model_rad'],follower=self.follower,model_bounds=self.bounds)
                if any(abs(self.follower.last_encoded_goal_raw[self.follower.bus.motors[n].id]-current['raw'][n])>1 for n in JOINTS):raise ValueError('Initial feedback cannot be encoded without changing the pose')
                fresh=self._activation_feedback(original)
                if self.cancelled()or time.monotonic_ns()-begin>200_000_000:raise ValueError('Initial Goal cancelled or deadline exceeded; no Follower commands')
                hold={n:fresh[n]for n in p['initialize_goal']}
                self.last_activation['effect']='unknown'
                self.follower.bus.sync_write('Goal_Position',hold,normalize=False,num_retry=0)
                readback=self.follower.bus.sync_read('Goal_Position',normalize=False)
                if any(readback[n]!=v for n,v in hold.items()):raise ValueError('Approved initial Goal readback differs; torque remains unchanged')
                self.last_activation['goal_initialized']=True
                if time.monotonic_ns()-begin>200_000_000:raise ValueError('Initial Goal deadline exceeded; torque remains unchanged')
            if any(v==0 for v in p['state']['torque'].values()):
                self._activation_feedback(original)
                if self.follower.bus.sync_read('Torque_Enable',normalize=False)!=current['torque']:raise ValueError('Follower Torque changed during activation')
                if self.cancelled()or time.monotonic_ns()-begin>200_000_000:raise ValueError('Activation cancelled or deadline exceeded; torque remains unchanged')
                self.last_activation['effect']='unknown'
                self.follower.bus.sync_write('Torque_Enable',dict.fromkeys(JOINTS,1),normalize=False,num_retry=0)
                if any(v!=1 for v in self.follower.bus.sync_read('Torque_Enable',normalize=False).values()):raise ValueError('Torque activation readback differs')
                self.last_activation['follower_torque_enabled']=True
            if time.monotonic_ns()-begin>200_000_000:raise ValueError('Torque activation deadline exceeded; no Goal commands')
            self.last_target=np.array(current['measured_model_rad']);self.last_raw_goal={self.follower.bus.motors[n].id:(current['raw'][n]if n in p['initialize_goal']else current['goal'][n])for n in JOINTS};self.last_tick_ns=time.monotonic_ns();self.heartbeat();self.active=True
            self.last_activation['effect']='sdk_returned'
        except Exception as error:
            self.last_activation['error']=str(error);self.stop();raise DeviceError('teleop_activate',str(error),effect=self.last_activation['effect'])from error

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
            if self.cancelled():raise ValueError('Teleoperation stopped before Goal transmission')
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
