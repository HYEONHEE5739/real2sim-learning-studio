"""A session-local six-axis command capability; RO device APIs stay RO.

SDK: LeRobot0.4.1 SO101Follower.send_action / MotorsBus.sync_write(num_retry=0).
Only an explicit session teleop_start command activates Leader control.
No configure, automatic homing, connection-time activation, or Policy control.
"""
import time
import numpy as np
from .calibration import JOINTS
from .capture import observed_positions
from .control import command_target
from .devices import DeviceError


class Teleoperation:
    def __init__(self,leader,follower,*,model_bounds,session_id):
        self.leader=leader;self.follower=follower;self.bounds=model_bounds;self.session_id=session_id
        self.active=False;self.consumed=set()
        self.last_heartbeat_ns=time.monotonic_ns();self.last_tick_ns=None;self.last_raw_goal=None;self.sequence=0;self.last_attempt=None;self.last_activation=None;self.last_feedback=None;self.cancelled=lambda:False

    def heartbeat(self):self.last_heartbeat_ns=time.monotonic_ns()

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
        target,_,details,leader_interval=self._target()
        bounds=np.asarray(details['bounds_rad'])
        target_raw={n:self.follower.last_encoded_goal_raw[self.follower.bus.motors[n].id]for n in JOINTS}
        return dict(raw=raw,initial_target_raw=target_raw,goal=goal,mode=mode,torque=torque,leader_torque=leader_torque,feedback_end_ns=interval['end']['monotonic_ns'],leader_end_ns=leader_interval['end']['monotonic_ns'],measured_model_rad=q.tolist(),initial_target_rad=target.tolist(),bounds_rad=details['bounds_rad'],
                    initial_displacement_rad=(target-q).tolist(),
                    follower_identity=self.follower.identity,leader_identity=self.leader.identity,follower_mapping=self.follower.precision_mapper.metadata()['sha256'],leader_mapping=self.leader.precision_mapper.metadata()['sha256'])

    def _activation_feedback(self):
        _,interval,_=self.feedback()
        if interval['end']['monotonic_ns']-interval['start']['monotonic_ns']>100_000_000:raise ValueError('Activation feedback read exceeded100ms')

    def start(self,*,command_id):
        if self.active:raise ValueError('Teleoperation already active')
        if not isinstance(command_id,str)or not command_id:raise ValueError('Explicit teleop_start command required')
        if command_id in self.consumed:raise ValueError('Start command already consumed')
        current=self._start_state()
        self.consumed.add(command_id)
        initialize=[n for n in JOINTS if not current['torque'][n]]
        release=[n for n in JOINTS if current['leader_torque'][n]]
        self.last_activation={'command_id':command_id,'session_id':self.session_id,'authorization':'explicit_teleop_start',
                              'goal_initialized':False,'leader_torque_released':False,'follower_torque_enabled':False,'effect':'not_applied','state':current}
        try:
            begin=time.monotonic_ns()
            if self.cancelled():raise ValueError('Teleoperation stopped before activation')
            if any(begin-current[k]>100_000_000 for k in('feedback_end_ns','leader_end_ns')):raise ValueError('Stale activation feedback; no register writes')
            if release:
                self.last_activation['effect']='unknown'
                self.leader.bus.sync_write('Torque_Enable',dict.fromkeys(release,0),normalize=False,num_retry=0)
                if any(self.leader.bus.sync_read('Torque_Enable',normalize=False).values()):raise ValueError('Leader torque release readback differs')
                self.last_activation['leader_torque_released']=True
                if time.monotonic_ns()-begin>200_000_000:raise ValueError('Leader activation deadline exceeded; no Follower commands')
            # The start button grants continuous Leader control. Recompute its
            # current encoded target; feedback is never used as a motor goal.
            target,_,details,leader_interval=self._target()
            current['initial_target_rad']=target.tolist()
            current['initial_target_raw']={n:self.follower.last_encoded_goal_raw[self.follower.bus.motors[n].id]for n in JOINTS}
            current['initial_target_saturation']=details['saturation']
            current['leader_end_ns']=leader_interval['end']['monotonic_ns']
            if initialize:
                self._activation_feedback()
                if self.cancelled()or time.monotonic_ns()-begin>200_000_000:raise ValueError('Initial Goal cancelled or deadline exceeded; no Follower commands')
                initial_goal={n:current['initial_target_raw'][n]for n in initialize}
                self.last_activation['effect']='unknown'
                self.follower.bus.sync_write('Goal_Position',initial_goal,normalize=False,num_retry=0)
                readback=self.follower.bus.sync_read('Goal_Position',normalize=False)
                if any(readback[n]!=v for n,v in initial_goal.items()):raise ValueError('Initial Goal readback differs; torque remains unchanged')
                self.last_activation['goal_initialized']=True
                if time.monotonic_ns()-begin>200_000_000:raise ValueError('Initial Goal deadline exceeded; torque remains unchanged')
            if initialize:
                self._activation_feedback()
                if self.follower.bus.sync_read('Torque_Enable',normalize=False)!=current['torque']:raise ValueError('Follower Torque changed during activation')
                if self.follower.bus.sync_read('Operating_Mode',normalize=False)!=current['mode']:raise ValueError('Follower position mode changed during activation')
                if self.cancelled()or time.monotonic_ns()-begin>200_000_000:raise ValueError('Activation cancelled or deadline exceeded; torque remains unchanged')
                self.last_activation['effect']='unknown'
                self.follower.bus.sync_write('Torque_Enable',dict.fromkeys(JOINTS,1),normalize=False,num_retry=0)
                if any(v!=1 for v in self.follower.bus.sync_read('Torque_Enable',normalize=False).values()):raise ValueError('Torque activation readback differs')
                self.last_activation['follower_torque_enabled']=True
            if time.monotonic_ns()-begin>200_000_000:raise ValueError('Torque activation deadline exceeded; no Goal commands')
            self.last_raw_goal={self.follower.bus.motors[n].id:(current['initial_target_raw'][n]if n in initialize else current['goal'][n])for n in JOINTS};self.last_tick_ns=time.monotonic_ns();self.heartbeat();self.active=True
            self.last_activation['effect']='sdk_returned'
        except Exception as error:
            self.last_activation['error']=str(error);self.stop();raise DeviceError('teleop_activate',str(error),effect=self.last_activation['effect'])from error

    def stop(self):
        self.active=False

    def tick(self):
        if not self.active:raise DeviceError('teleoperation','Teleoperation start command is required',effect='not_applied')
        send_attempted=False;attempt=None
        try:
            now=time.monotonic_ns()
            if now-self.last_heartbeat_ns>1_500_000_000 or now-self.last_tick_ns>200_000_000:raise ValueError('Stale session heartbeat/control cycle')
            self.leader._check_identity();self.follower._check_identity()
            _,feedback,q=self.feedback();target,command,details,leader_interval=self._target()
            begin=time.monotonic_ns()
            if begin-feedback['end']['monotonic_ns']>100_000_000 or begin-leader_interval['end']['monotonic_ns']>100_000_000:raise ValueError('Stale feedback/Leader command')
            raw=dict(self.follower.last_encoded_goal_raw);duplicate=raw==self.last_raw_goal
            attempt=dict(sequence=self.sequence+1,requested_model_rad=details['requested_model_rad'],target_payload_rad=target.tolist(),sdk_goal_raw=raw,
                         measured_model_rad=q.tolist(),feedback_interval=feedback,leader_interval=leader_interval,send_begin_ns=begin,command_sent=False,effect='not_applied')
            self.last_attempt=attempt
            if self.cancelled():raise ValueError('Teleoperation stopped before Goal transmission')
            if begin-now>200_000_000:raise ValueError('Control deadline exceeded before Goal transmission')
            if not duplicate:
                # Encoding already ran strict model/motor/Precision/SDK checks.
                send_attempted=True;returned=self.follower.device.send_action({n+'.pos':command[n]for n in JOINTS})
                if returned!={n+'.pos':command[n]for n in JOINTS}:raise ValueError('SDK changed the preflighted target')
            end=time.monotonic_ns();attempt.update(send_end_ns=end,send_latency_s=(end-begin)/1e9,command_sent=not duplicate,effect='sdk_returned'if not duplicate else'not_applied')
            if end-now>200_000_000:raise ValueError('Control/send deadline exceeded; no further goals')
            self.last_tick_ns=end;self.sequence+=1;self.last_raw_goal=raw
            return dict(sequence=self.sequence,timestamp_ns=feedback['end']['monotonic_ns'],measured_model_rad=q.tolist(),requested_model_rad=details['requested_model_rad'],
                        applied_model_rad=target.tolist(),saturation=details['saturation'],sdk_goal_raw=raw,command_sent=not duplicate,duplicate_suppressed=duplicate,
                        feedback_interval=feedback,leader_interval=leader_interval,send_latency_s=(end-begin)/1e9,follow_error_rad=(q-target).tolist())
        except Exception as error:
            if attempt is not None:attempt.update(command_sent='unknown'if send_attempted else False,effect='unknown'if send_attempted else'not_applied',error=str(error),send_end_ns=time.monotonic_ns())
            self.stop();raise DeviceError('teleoperation',str(error),effect='unknown'if send_attempted else'not_applied')from error
