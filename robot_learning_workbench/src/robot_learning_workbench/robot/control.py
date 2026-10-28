"""Native SDK encoding and explicit model/Teleop targets; no engine or bus writes."""
import math
import numpy as np
from collections.abc import Mapping,Sequence
from typing import TYPE_CHECKING
from .calibration import JOINTS,values,LEGACY_MAPPER
if TYPE_CHECKING:
    from .devices import Follower


class TargetRejected(ValueError):
    code='COMMAND_TARGET_REJECTED'
    effect='not_applied'
    def __init__(self,reason,diagnostics):
        super().__init__(reason);self.diagnostics=diagnostics
        self.issues=({'field':'joint_target','reason':reason,'source':diagnostics},)


def checked_target(target,*,limits,applied_dtype,joint_order=JOINTS,units='model_rad',diagnostics=None):
    """Finite position targets saturate to dtype-representable INWARD limits.

    NumPy1.26 nextafter: https://numpy.org/doc/1.26/reference/generated/numpy.nextafter.html
    Saturation never extends model limits or repairs invalid units/identity/input.
    """
    original=np.asarray(target);bounds=np.asarray(limits,dtype=np.float64);dtype=np.dtype(applied_dtype)
    info={'original_action':original.tolist() if original.dtype.kind in 'fiu' and np.isfinite(original).all() else repr(target),
          'original_dtype':str(original.dtype),'applied_dtype':str(dtype),'joint_order':list(JOINTS),
          'units':'model_rad','command_applied':False,'violations':[]}
    if tuple(joint_order)!=JOINTS or units!='model_rad':raise TargetRejected('Expected declared SO101 order and model_rad units',info)
    if original.shape!=(6,) or original.dtype.kind not in 'fiu' or not np.isfinite(original).all():
        raise TargetRejected('Expected finite six-joint model-radian command',info)
    if bounds.shape!=(6,2) or not np.isfinite(bounds).all() or np.any(bounds[:,0]>bounds[:,1]) or dtype not in (np.dtype('float32'),np.dtype('float64')):
        raise TargetRejected('Invalid finite model/engine/motor command bounds or payload dtype',info)
    with np.errstate(over='ignore'):
        low=bounds[:,0].astype(dtype);high=bounds[:,1].astype(dtype)
    low=np.where(low.astype(np.float64)<bounds[:,0],np.nextafter(low,dtype.type(np.inf)),low)
    high=np.where(high.astype(np.float64)>bounds[:,1],np.nextafter(high,dtype.type(-np.inf)),high)
    if not np.isfinite(low).all() or not np.isfinite(high).all() or np.any(low>high):
        raise TargetRejected('No finite native payload inside approved limits',info)
    request=original.astype(np.float64)
    mask=(request<low.astype(np.float64))|(request>high.astype(np.float64))
    payload=np.minimum(np.maximum(request,low.astype(np.float64)),high.astype(np.float64)).astype(dtype)
    if not np.isfinite(payload).all() or np.any(payload.astype(np.float64)<bounds[:,0]) or np.any(payload.astype(np.float64)>bounds[:,1]):
        raise TargetRejected('Final payload outside original limits',info)
    info.update(policy='position_saturation_inward_v1',safe_limits_rad=np.stack([low,high],axis=1).astype(np.float64).tolist(),
                applied_target=payload.tolist(),saturation_mask=mask.tolist(),saturated_joints=[JOINTS[i] for i in np.flatnonzero(mask)],
                delta_rad=(payload.astype(np.float64)-request).tolist())
    if diagnostics is not None:diagnostics.update(info)
    return payload.copy()


def command_target(leader_native, *, leader_mapper, follower, model_bounds, engine_bounds=None, leader_raw=None):
    """Saturate to approved Teleop common limits and use the same SDK-quantized target.

    Does not send to hardware or step Sim. Policy/replay must use strict inverse,
    never infer hardware command approval from this pure calculation.
    """
    requested=values(leader_mapper.calibrated_to_observation(leader_native,raw=leader_raw))
    if leader_mapper.profile['urdf_sha256'] != follower.precision_mapper.profile['urdf_sha256']: raise ValueError('Leader/Follower model mismatch')
    return encode_model_target([requested[n] for n in JOINTS],follower=follower,model_bounds=model_bounds,engine_bounds=engine_bounds)


def encode_model_target(requested: Sequence[float]|np.ndarray, *, follower: 'Follower', model_bounds: Mapping[str,Sequence[float]], engine_bounds: np.ndarray|None=None, joint_order: Sequence[str]=JOINTS, units: str='model_rad') -> tuple[np.ndarray,dict,dict]:
    """Shared pure preflight for model targets; never connect, activate or send."""
    mapper=follower.precision_mapper
    bounds=np.array([model_bounds[n] for n in JOINTS],dtype=float)
    if bounds.shape!=(6,2) or not np.isfinite(bounds).all(): raise ValueError('Expected finite model bounds')
    if engine_bounds is not None:
        engine=np.asarray(engine_bounds,dtype=float)
        if engine.shape!=(6,2) or not np.isfinite(engine).all(): raise ValueError('Expected finite engine bounds')
        bounds[:,0]=np.maximum(bounds[:,0],engine[:,0]);bounds[:,1]=np.minimum(bounds[:,1],engine[:,1])
    calibrated=mapper.profile['joints']
    for i,n in enumerate(JOINTS):
        if n in calibrated: continue
        ends=sorted(LEGACY_MAPPER.calibrated_to_urdf({**dict.fromkeys(JOINTS,0.),n:v})[n] for v in follower.limits[n])
        bounds[i]=max(bounds[i,0],ends[0]),min(bounds[i,1],ends[1])
    if np.any(bounds[:,0]>bounds[:,1]): raise ValueError('No common model/engine/motor range')
    motor_bounds=mapper.command_limits(dict(zip(JOINTS,bounds.tolist())))
    bounds=np.array([motor_bounds[n] for n in JOINTS])
    saturation={};goal=checked_target(requested,limits=bounds,applied_dtype=np.float64,joint_order=joint_order,units=units,diagnostics=saturation)
    diagnostics={'requested_model_rad':dict(zip(JOINTS,np.asarray(requested).tolist())),'bounds_rad':bounds.tolist(),'hardware_measured':False,'saturation':saturation}
    try:
        native=mapper.urdf_to_calibrated(dict(zip(JOINTS,goal.tolist())))
        command,encoded=follower.encode_goal(native)
        actual=values(mapper.calibrated_to_urdf(encoded));q=np.array([actual[n] for n in JOINTS])
        if np.any(q<bounds[:,0]) or np.any(q>bounds[:,1]):raise ValueError('Encoded motor target outside approved bounds')
    except Exception as error:
        error.command_preflight={**diagnostics,'encoding_possible':False,'reason':str(error)}
        raise
    return q,command,{**diagnostics,'encoded_model_rad':actual,'encoding_possible':True}

def encode_goal(self, target, *, joints=JOINTS):
    """Read-only SDK encoding preflight, including integer truncation."""
    from .calibration import raw_from_native, native_from_raw
    if tuple(joints) not in (JOINTS,('gripper',)):raise ValueError('Only full Fake encoding or gripper encoding is supported')
    if tuple(joints)==JOINTS:target=values(target).copy()
    elif set(target)!= {'gripper'} or not math.isfinite(target['gripper']):raise ValueError('Finite gripper target required')
    else:target=dict(target)
    bus=self.device.bus
    if any(target[n] < self.limits[n][0]-1e-6 or target[n] > self.limits[n][1]+1e-6 for n in joints):
        raise ValueError("Follower native goal outside calibrated motor range")
    entries=getattr(getattr(self,'precision_mapper',None),'profile',{}).get('joints',{})
    def encode(): return bus._unnormalize({bus.motors[n].id:target[n] for n in joints})
    raw=encode()
    for name in joints:
        spec=entries[name]['motor'] if name in entries else self.motor_specs[name]
        identifier=bus.motors[name].id
        expected=round(raw_from_native(target[name],spec))
        if name not in entries:
            target[name]=native_from_raw(expected,spec);raw=encode()
        # The strict Precision inverse has already selected this integer goal.
        # Move only a few floating point ULPs so SDK int() encodes that goal.
        direction=-math.inf if spec['mode']=='RANGE_0_100' and spec['apply_drive_mode'] and spec['calibration']['drive_mode'] else math.inf
        for _ in range(16):
            if raw[identifier]==expected: break
            if raw[identifier]!=expected-1: raise ValueError(name+': SDK encoder disagrees with Precision inverse')
            target[name]=math.nextafter(target[name],direction);raw=encode()
        if raw[identifier]!=expected: raise ValueError(name+': SDK encoder cannot roundtrip calibrated goal')
    for n in joints:
        cal=bus.calibration[n]; goal=raw[bus.motors[n].id]
        if not cal.range_min <= goal <= cal.range_max:
            raise ValueError(n+": SDK goal outside calibrated motor range")
    normalized=bus._normalize(raw)
    self.last_encoded_goal_raw=dict(raw)
    packet={n:normalized[bus.motors[n].id] for n in joints}
    return target,values(packet) if tuple(joints)==JOINTS else packet
