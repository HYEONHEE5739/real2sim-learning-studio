"""Identify passive sliding friction only with measured mass/support/timing evidence."""
# Official MjModel/MjData/mj_forward/mj_step API: https://mujoco.readthedocs.io/en/3.3.7/python.html
import copy
import numpy as np
from scipy.optimize import least_squares
from ..exporters.mjcf import export
from ..project import value


def trajectory(scene,root,scratch,motion):
    import mujoco
    times=np.asarray(motion['times_s'],float);positions=np.asarray(motion['positions_world_m'],float)
    velocity=np.asarray(motion['initial_velocity_m_s'],float)
    if len(times)<3 or times.shape!=(len(times),) or positions.shape!=(len(times),3) or velocity.shape!=(3,) or not np.isfinite(np.r_[times,positions.ravel(),velocity]).all() or times[0]!=0 or np.any(np.diff(times)<=0):
        raise ValueError('Motion needs finite increasing timestamps from zero, 3D positions and initial velocity')
    obj=next(o for o in scene['objects'] if o['id']==motion['object'])
    if obj['physics']['mass_kg']['value'] is None or obj['physics']['mass_kg']['provenance'] not in ('measured','calibrated'):
        raise ValueError('Passive dynamics require a measured object mass; mass is not identifiable from motion alone')
    export(scene,root,scratch/'motion.xml');model=mujoco.MjModel.from_xml_path(str(scratch/'motion.xml'));data=mujoco.MjData(model)
    jid=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_JOINT,obj['id']+'_free')
    if jid<0:raise ValueError('Only free passive objects can identify dynamics')
    q=int(model.jnt_qposadr[jid]);v=int(model.jnt_dofadr[jid]);data.qpos[q:q+3]=positions[0];data.qvel[v:v+3]=velocity
    mujoco.mj_forward(model,data);result=[]
    for timestamp in times:
        while data.time+model.opt.timestep/2<timestamp:mujoco.mj_step(model,data)
        if not np.isfinite(data.qpos).all():raise ValueError('Nonfinite motion simulation')
        result.append(data.qpos[q:q+3].copy())
    return np.asarray(result)


def fit(scene,root,scratch,motions):
    candidate=copy.deepcopy(scene);report=[]
    for motion in motions:
        if motion.get('split','train')!='train':continue
        obj=next(o for o in candidate['objects'] if o['id']==motion['object'])
        if motion.get('fit_parameters',[]) not in ([],['friction']):raise ValueError('Only passive friction is identifiable in the current motion adapter')
        if motion.get('fit_parameters'):
            support=next(o for o in candidate['objects'] if o['id']==motion['support'])
            if support['physics']['friction']['provenance'] not in ('measured','calibrated'):raise ValueError('Known support friction required to separate contact contributions')
            initial=obj['physics']['friction']['value']
            if initial is None:obj['physics']['friction']=value(.5,'estimated',['optimizer seed, not a measurement'])
            def residual(x):
                obj['physics']['friction']['value']=float(x[0])
                return (trajectory(candidate,root,scratch,motion)-np.asarray(motion['positions_world_m'])).ravel()
            result=least_squares(residual,[obj['physics']['friction']['value']],bounds=(0,2),diff_step=.02,max_nfev=30)
            if np.linalg.norm(result.jac)<1e-7:raise ValueError('Friction is unobservable from the provided trajectory')
            obj['physics']['friction']=value(float(result.x[0]),'optimized',['measured passive motion, mass and support properties'])
        predicted=trajectory(candidate,root,scratch,motion)
        report.append({'object':obj['id'],'split':'train','rmse_m':float(np.sqrt(np.mean((predicted-np.asarray(motion['positions_world_m']))**2)))})
    for motion in motions:
        if motion.get('split')=='validation':
            predicted=trajectory(candidate,root,scratch,motion)
            report.append({'object':motion['object'],'split':'validation','rmse_m':float(np.sqrt(np.mean((predicted-np.asarray(motion['positions_world_m']))**2)))})
    if any(m.get('fit_parameters') for m in motions) and not any(r['split']=='validation' for r in report):
        raise ValueError('One held-out passive trajectory is required to validate identified friction')
    return candidate,report
