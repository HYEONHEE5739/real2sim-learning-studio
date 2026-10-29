"""Bounded control records in the existing Native HDF5 contract, without fake RGB."""
import numpy as np
from .calibration import JOINTS


class Recorder:
    def __init__(self,plan,follower):
        from ..data.native import NativeRun,native_api
        self.Episode=native_api()[0];self.pending=None;self.rows=[];self.index=0;self.origin=None
        self.owner=NativeRun(plan.output_path/'teleoperation',dict(stage='teleoperation',engine=plan.effective_settings['execution']['device_source'],seed=0,
            recording_only=True,joint_order=list(JOINTS),model_sha256=follower.profile['urdf_sha256'],hardware_connected=plan.effective_settings['execution']['device_source']=='hardware',
            training_ready=False,scope='actual requested/applied targets with next measured feedback; no synchronized control video'))

    def append(self,row):
        if self.pending is not None:
            self.rows.append({**self.pending,'post_measured_model_rad':row['measured_model_rad']})
            if len(self.rows)>=300:self.flush()
        self.pending=row

    def flush(self):
        if not self.rows:return
        import torch
        self.index+=1;segment=self.owner.segment('control-'+str(self.index));claim=self.owner.claim_attempt(segment);ep=self.Episode();ep.seed=0;ep.success=True
        if self.origin is None:self.origin=self.rows[0]['timestamp_ns']
        for r in self.rows:
            values={'actions':r['applied_model_rad'],'joint_targets':r['applied_model_rad'],'obs/policy/joint_pos':r['measured_model_rad'],'states/joint_pos':r['post_measured_model_rad'],
                'commands/requested_joint_rad':[r['requested_model_rad'][n]for n in JOINTS],'commands/applied_joint_rad':r['applied_model_rad'],'commands/saturation_delta_rad':r['saturation']['delta_rad'],
                'obs/timestamp':[(r['timestamp_ns']-self.origin)/1e9],'timing/send_duration_s':[r['send_latency_s']],'control/follow_error_rad':r['follow_error_rad']}
            for key,value in values.items():ep.add(key,torch.tensor(value,dtype=torch.float64))
            ep.add('commands/saturation_mask',torch.tensor(r['saturation']['saturation_mask'],dtype=torch.bool))
        eid='control-'+str(self.index);segment.write_episode(ep,episode_id=eid,metadata={'recording_only':True,'training_ready':False});segment.record_attempt(claim,status='success',episode_id=eid);segment.commit();self.rows=[]

    def close(self):
        try:self.flush()
        finally:self.owner.close()
