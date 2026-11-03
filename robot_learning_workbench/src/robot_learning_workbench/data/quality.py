"""Recorded motion hints ported from the original Curation scan/outlier rules.

Idle: EEF speed <2mm/s; command idle: every joint <1 degree/s.
Jitter: RMS commanded angular acceleration. Relative flags use median+3*MAD
with the original spread floor and at least five comparable Episodes.
Revision thresholds use the original Dataset so excluding peers does not relabel
unchanged Episodes. Trimmed metrics are still measured over the selected range.
These hints never change recorded success, include/exclude, or split assignments.
"""
from contextlib import ExitStack
import numpy as np
from .curation import _chunks,_field_semantics,_parent
from .native import task_object_ids


def initial_positions(catalog,ep):
    """Task-object positions at the original Episode start, never the Trim start."""
    if ep.format!='isaac_hdf5':return ep.metadata.get('initial_objects',{})
    recording=catalog.execution.get('recording',{})
    if recording.get('pose_frame')!='robot_base'or recording.get('units')!='m_rad_s':return{}
    import h5py
    result={};names=task_object_ids(catalog.execution)
    with h5py.File(ep.file,'r')as file:
        objects=file['data/'+ep.key].get('obs/datagen_info/object_pose',{})
        for name in names:
            if name not in objects:continue
            pose=np.asarray(objects[name][0])
            if pose.shape==(4,4)and np.isfinite(pose).all():result[name]=pose[:3,3].tolist()
    return result


def episode_quality(catalog,ep,official):
    native=ep.format=='isaac_hdf5';clock='obs/timestamp'if native else'timestamp';target='joint_targets'if native else'action'
    result=dict(flags=[],flag_details=[],duration=None,stop_fraction=None,command_stop_fraction=None,jitter=None,gripper_jitter=None,initial_objects=initial_positions(catalog,ep),target_movement_m=None,lift_height_m=None)
    with ExitStack()as stack:
        group=None
        if native:
            import h5py
            group=stack.enter_context(h5py.File(ep.file,'r'))['data/'+ep.key]
            recording=catalog.execution.get('recording',{});metric_poses=recording.get('pose_frame')=='robot_base'and recording.get('units')=='m_rad_s'
        if _field_semantics(catalog,target)['unit']!='rad':result['reason']='관절 단위 근거 없음';return result
        eef_key='obs/datagen_info/eef_pose/tool0'
        eef=_chunks((ep,),eef_key,2048,official)if group is not None and metric_poses and eef_key in group else None
        pick=next(iter(catalog.execution.get('active_objects',())),None);object_key='obs/datagen_info/object_pose/'+str(pick)
        objects=_chunks((ep,),object_key,2048,official)if group is not None and metric_poses and object_key in group else None
        last_t=last_q=last_v=last_ee=last_obj=None;first=None;last=None;idle=cmd_idle=count=acc_count=0;accsum=np.zeros(6);movement=0.;initial_z=top_z=None
        for values,times in zip(_chunks((ep,),target,2048,official),_chunks((ep,),clock,2048,official)):
            times=np.asarray(times).reshape(-1);values=np.asarray(values)
            if values.shape!=(len(times),6)or not np.isfinite(times).all()or not np.isfinite(values).all():raise ValueError('Invalid aligned motion quality data')
            ee=next(eef)[:,:3,3]if eef is not None else None;obj=next(objects)[:,:3,3]if objects is not None else None
            for i,(t,q)in enumerate(zip(times,values)):
                if first is None:first=float(t)
                if last_t is not None:
                    dt=float(t-last_t)
                    if dt<=0:raise ValueError('Non-increasing recorded timestamps')
                    v=(q-last_q)/dt;cmd_idle+=np.max(np.abs(v))<np.deg2rad(1);count+=1
                    if last_v is not None:accsum+=((v-last_v)/dt)**2;acc_count+=1
                    if ee is not None:idle+=np.linalg.norm(ee[i]-last_ee)/dt<.002
                    last_v=v
                if obj is not None:
                    if initial_z is None:initial_z=top_z=float(obj[i,2])
                    top_z=max(top_z,float(obj[i,2]))
                    if last_obj is not None:movement+=float(np.linalg.norm(obj[i]-last_obj))
                    last_obj=obj[i]
                last_t=last=float(t);last_q=q;last_ee=ee[i]if ee is not None else None
        step=(last-first)/count if count else 0.
        result.update(duration=(last-first+step)if first is not None else 0.,command_stop_fraction=float(cmd_idle/count)if count else None,
                      stop_fraction=float(idle/count)if eef is not None and count else None,
                      jitter=float(np.sqrt(accsum[:5].mean()/acc_count))if acc_count else None,gripper_jitter=float(np.sqrt(accsum[5]/acc_count))if acc_count else None,
                      target_movement_m=movement if obj is not None else None,lift_height_m=top_z-initial_z if initial_z is not None else None)
    return result


def _quality_row(catalog,ep,official):
    try:return episode_quality(catalog,ep,official)
    except (ValueError,KeyError,OSError)as error:return dict(flags=[],flag_details=[],initial_objects={},reason=str(error))


def motion_quality(catalog):
    original=catalog
    while original.kind=='curated':original=_parent(original)
    official={};by_id={ep.selection_id or ep.episode_id:ep for ep in original.episodes}
    reference={name:_quality_row(original,ep,official)for name,ep in by_id.items()}
    rows={}
    for ep in catalog.episodes:
        name=ep.selection_id or ep.episode_id;full=by_id[name]
        same_range=ep.start==full.start and (ep.stop or ep.num_frames)==(full.stop or full.num_frames)
        rows[name]=reference[name]if same_range else _quality_row(catalog,ep,official)
    for metric,low,high in [('duration','짧은 시간','긴 시간'),('stop_fraction',None,'EE 정지 비율 높음'),('command_stop_fraction',None,'정지 명령 많음'),('jitter',None,'명령 Jitter 높음')]:
        valid=[r for r in reference.values()if r.get(metric)is not None and np.isfinite(r[metric])]
        if len(valid)<5:continue
        values=np.array([r[metric]for r in valid]);median=float(np.median(values));spread=max(float(1.4826*np.median(abs(values-median))),abs(median)*.1,1e-6)
        for row in rows.values():
            value=row.get(metric)
            if value is None or not np.isfinite(value):continue
            label=high if value>median+3*spread else low if low and value<median-3*spread else None
            if label:
                row['flags'].append(label);row['flag_details'].append(dict(label=label,metric=metric,value=value,median=median,threshold=median+3*spread if label==high else median-3*spread,group_size=len(valid)))
    return rows
