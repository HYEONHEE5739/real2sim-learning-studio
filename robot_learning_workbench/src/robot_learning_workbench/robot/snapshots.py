"""User-command snapshots in existing real2sim.snapshot/1, transactional Builder import."""
import copy,os
from pathlib import Path
from PIL import Image
from .capture import prepare_snapshot,share_model
from .calibration import JOINTS
from ..data.native import atomic_json,file_sha256


class SnapshotStore:
    def __init__(self,project,*,session_id,model,mapping):
        project.require_writable();self.project=project;self.project_id=project.info['id'];self.session_id=session_id;self.model=Path(model)
        self.mapping=copy.deepcopy(mapping);self.last_sequences={};self.completed={}
        if mapping.get('profile',{}).get('urdf_sha256')!=file_sha256(self.model):raise ValueError('Explicit model differs from measured Precision mapping')

    def prepare(self,identifier,state,images,*,now_ns=None):
        from real2sim_builder.scene import identifier as validate_id
        from real2sim_builder.capture import load_session
        validate_id(identifier)
        if self.project.info['id']!=self.project_id:raise ValueError('Project identity changed')
        if state['sim_joint_mapping']!=self.mapping:raise ValueError('Snapshot mapping changed')
        if identifier in self.completed or any(s.get('dataset_id')==identifier for s in self.project.evidence.get('capture_sessions',[])):raise ValueError('Snapshot ID already exists')
        measured,observed,warnings=prepare_snapshot(state,images,{'cameras':{n:{'resolution':[640,480]}for n in('side','wrist')}},now_ns=now_ns)
        sequences={r['camera']:r['sequence']for r in observed}
        if any(sequences[n]<=self.last_sequences.get(n,-1)for n in sequences):raise ValueError('Camera frame reused; wait for new Side/Wrist frames')
        staging=self.project.root/'input/captures'/('pending_'+identifier);staging.mkdir(parents=True,exist_ok=False)
        model_relative,files=share_model(staging,self.model);shot=staging/'shots'/identifier;shot.mkdir(parents=True)
        measured.update(hardware_identity=state['hardware']['follower']['identity'],camera_metadata=state.get('camera_metadata',{}),device_source=state.get('device_source','unspecified'))
        atomic_json(shot/'state.json',measured);shot_files={'state.json':file_sha256(shot/'state.json')}
        for row in observed:
            Image.fromarray(images['real_'+row['camera']]).save(shot/row['path']);shot_files[row['path']]=file_sha256(shot/row['path'])
        layout_id='layout_'+self.project_id.replace('-','_')
        metadata=dict(id=identifier,scene_state_id=layout_id,files=shot_files,images=observed,quality_warnings=warnings)
        atomic_json(shot/'metadata.json',metadata);(shot/'COMPLETE').write_text('complete\n')
        manifest=dict(schema='real2sim.snapshot/1',dataset_id=identifier,clock={'domain':'host_monotonic_ns','hardware_synchronized':False,'timestamp_kind':'host_receipt_not_exposure'},
            joint_names=list(JOINTS),joint_units=['rad']*6,q_measured_source='physical_follower_feedback_converted_to_model',joint_mapping=self.mapping,
            source_robot_sha256=file_sha256(self.model),robot={'path':model_relative,'mapping_verified':False},cameras=[{'id':n,'resolution':[640,480]}for n in('side','wrist')],
            files=files,snapshots=[{'id':identifier,'scene_state_id':layout_id,'path':str(shot.relative_to(staging)),'metadata_sha256':file_sha256(shot/'metadata.json')}],
            project_id=self.project_id,session_identity=self.session_id,command_source='measured_observation_no_training_action',device_source=state.get('device_source','unspecified'),
            static_layout_verified=False,physical_verified=False)
        atomic_json(staging/'capture_manifest.yaml',manifest);(staging/'COMPLETE').write_text('complete\n');load_session(staging)
        self.last_sequences=sequences
        return dict(id=identifier,staging=str(staging),sample={'timestamp_ns':measured['timestamp_ns'],'unix_ns':measured['timestamps']['follower']['end'].get('unix_ns'),'q_measured':measured['q_measured']},quality=warnings,observed=observed)

    def finish(self,pending,*,rendered=None):
        from real2sim_builder.files import read,write
        from real2sim_builder.capture import load_session,import_snapshots
        from real2sim_builder.candidate import exclusive
        identifier=pending['id']
        if identifier in self.completed:return self.completed[identifier]
        staging=Path(pending['staging'])
        with exclusive(self.project):
            if staging.exists():
                manifest=read(staging/'capture_manifest.yaml')
                if rendered is not None:
                    from .real_sim import write_pair
                    write_pair(staging,manifest,pending,rendered)
                write(staging/'capture_manifest.yaml',manifest);normalized,_,_=load_session(staging)
                final=self.project.root/'input/captures'/normalized['session_id'];os.rename(staging,final);pending['path']=str(final)
            else:final=Path(pending['path'])
            report=import_snapshots(self.project,final,paired=rendered is not None)
        result=dict(id=identifier,path=str(final),project_id=self.project_id,session_id=self.session_id,status='SAVED',registration=report,
            quality=pending['quality'],timestamp_ns=pending['sample']['timestamp_ns'],unix_ns=pending['sample'].get('unix_ns'),q_measured=pending['sample']['q_measured'],calibration_approved=False,paired=rendered is not None)
        self.completed[identifier]=result;return result
