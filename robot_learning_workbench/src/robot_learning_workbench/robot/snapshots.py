"""User-command snapshots in existing real2sim.snapshot/1, transactional Builder import."""
import copy,os,time
from pathlib import Path
from PIL import Image
from .capture import prepare_snapshot,share_model
from .calibration import JOINTS
from ..data.native import atomic_json,file_sha256


def snapshot_writer(store):
    """One session-owned save process; never inherit an open serial device.

    Threads still share the control interpreter's GIL. Keep PNG/NumPy/native
    imports, hashing and Builder registration in a spawned interpreter instead.
    The process remains in the existing R03 process group and is joined after
    devices stop. Only paths, immutable mapping data and frozen observations
    cross this boundary, never a Device, Renderer or Project instance.
    """
    from concurrent.futures import ProcessPoolExecutor
    from multiprocessing import get_context
    return ProcessPoolExecutor(max_workers=1,mp_context=get_context('spawn'),
        initializer=_initialize_writer,initargs=(str(store.project.root),store.session_id,str(store.model),store.mapping))


def _initialize_writer(project_root,session_id,model,mapping):
    import cv2
    from real2sim_builder.project import Project
    global _writer_store,_writer_pending
    # Canny/Laplacian on two camera frames must not reserve all host cores while
    # the motor owner and live renderer run. This setting is child-local.
    cv2.setNumThreads(1)
    _writer_store=SnapshotStore(Project(project_root),session_id=session_id,model=model,mapping=mapping)
    _writer_pending={}


def writer_ready():
    """Warm imports and validate the save owner before device connection."""
    from real2sim_builder.capture import load_session
    return os.getpid()


def save_snapshot(operation,*args,**kwargs):
    """Run the existing transaction in its persistent, single save owner."""
    if operation=='prepare':
        try:result=_writer_store.prepare(*args,**kwargs)
        except Exception as error:
            folder=_writer_store.directory/('pending_'+args[0])
            if folder.is_dir():error.snapshot_pending=dict(id=args[0],staging=str(folder),sealed=(folder/'COMPLETE').is_file())
            raise
        _writer_pending[result['id']]=result
        return result
    if operation=='finish':
        pending=args[0]
        # finish may rename before import fails. Preserve that mutation in this
        # owner so an explicit retry cannot lose the sealed observation path.
        pending=_writer_pending.setdefault(pending['id'],pending)
        try:
            result=_writer_store.finish(pending,**kwargs);_writer_pending.pop(pending['id'],None)
            return result
        except Exception as error:
            # Builtin exception state crosses ProcessPool IPC. Keep the real
            # renamed path in the parent report as well, even if the session
            # closes instead of explicitly retrying in this save owner.
            error.snapshot_pending=copy.deepcopy(pending)
            raise
    raise ValueError('Unknown snapshot save operation')


class CaptureQueue:
    """At most four frozen observations; reuse the existing save/render owners."""
    capacity=4

    def __init__(self,session,*,paired=False):
        self.session=session;self.paired=paired;self.jobs={};self.failed={};self.last_sequences={}
        self.rendering=None;self.render_error=None

    def progress(self):
        first=next(iter(self.jobs.values()),None)
        return dict(capture_pending=bool(self.jobs),capture_queue_size=len(self.jobs),capture_queue_capacity=self.capacity,
            capture_request_allowed=not self.session.closing and not self.session.terminal and self.session.state in('OBSERVING','TELEOP_ACTIVE')and len(self.jobs)<self.capacity and not self.render_error,
            capture_phase=first['phase'].lower()if first else None,
            capture_elapsed_s=(time.monotonic_ns()-first['request']['requested_ns'])/1e9 if first else None)

    def _publish(self,job,phase,**extra):
        job['phase']=phase;job.setdefault('times',{})[phase]=time.monotonic_ns()
        pending=job.get('pending')or{};sample=pending.get('sample')or job['sample']
        folder=pending.get('path')or pending.get('staging')
        row=dict(id=job['id'],command_id=job['command']['command_id'],phase=phase,path=folder,
            timestamp_ns=sample['timestamp_ns'],unix_ns=sample.get('unix_ns'),q_measured=sample['q_measured'],
            paired=self.paired,request=job['request'],phase_times_ns=dict(job['times']),**extra)
        row.setdefault('error',job.get('error'))
        if folder:row['images']={r['camera']:str(Path(folder)/r['path'])for r in pending.get('observed',[])}
        self.session.emit(capture_update=row,**({'error':row['error']}if phase=='FAILED'else{}))

    def request(self,command):
        if len(self.jobs)>=self.capacity:raise ValueError('Capture queue full (4); wait for a saved observation')
        if self.render_error:raise ValueError('Sim renderer unavailable; raw observations already saved are retained')
        from .capture import freeze_capture
        state,images,sequences=freeze_capture(self.session,command,self.last_sequences)
        identifier=('pair_'if self.paired else'snapshot_')+command['command_id']
        job=dict(id=identifier,command=command,request=state['capture_request'],
            sample=dict(timestamp_ns=state['timestamps']['follower']['end']['monotonic_ns'],
                unix_ns=state['timestamps']['follower']['end'].get('unix_ns'),q_measured=state['physical_q_measured']),
            pending=None,future=None)
        self.jobs[identifier]=job
        self._publish(job,'OBSERVED')
        try:job['future']=self.session.writer.submit(save_snapshot,'prepare',identifier,state,images)
        except Exception:
            self.jobs.pop(identifier);raise
        self.last_sequences.update(sequences)
        self.session.ack(command,'accepted');self._publish(job,'QUEUED')

    def _finish(self,job,rendered=None):
        job['future']=self.session.writer.submit(save_snapshot,'finish',job['pending'],rendered=rendered)
        self._publish(job,'REGISTERING')

    def rendered(self,result):
        if self.rendering is None or result.get('id')!=self.rendering:raise ValueError('Pair render ID differs from the frozen Capture request')
        job=self.jobs[self.rendering];self.rendering=None
        try:self._finish(job,result)
        except Exception as error:self._fail(job,error)

    def renderer_failed(self,error):
        self.render_error=str(error)
        if self.rendering is not None:
            job=self.jobs.get(self.rendering);self.rendering=None
            if job:self._fail(job,error)

    def _fail(self,job,error):
        pending=getattr(error,'snapshot_pending',None)
        if isinstance(pending,dict):job['pending']=pending
        job['future']=None;job['error']=str(error);job['failed_phase']=job['phase']
        self.jobs.pop(job['id'],None);self.failed[job['id']]=job
        if self.rendering==job['id']:self.rendering=None
        self.session.ack(job['command'],'rejected',str(error))
        from .devices import DeviceError
        if isinstance(error,DeviceError)and self.session.control:
            self.session.control.stop()
            if self.session.state=='TELEOP_ACTIVE':self.session.state='OBSERVING'
        self._publish(job,'FAILED',error=str(error))

    def poll(self,*,closing=False):
        for job in list(self.jobs.values()):
            future=job['future']
            if future is None or not future.done():continue
            job['future']=None
            try:
                result=future.result()
                if job['phase']=='QUEUED':
                    job['pending']=result;self._publish(job,'RAW_SAVED')
                    if closing:continue
                    if not self.paired:self._finish(job)
                else:
                    result.update(capture_elapsed_s=(time.monotonic_ns()-job['request']['requested_ns'])/1e9,
                        request=job['request'],phase_times_ns=dict(job['times']))
                    self.jobs.pop(job['id']);self.session.snapshots.append(result)
                    job['pending']['path']=result['path']
                    if self.paired:
                        try:warnings=self.session.renderer.release_capture(job['id'])
                        except Exception as error:warnings=[str(error)]
                        if warnings:self.session.events({'kind':'log','payload':{'level':'warning','message':'Render cleanup: '+str(warnings)}})
                    self.session.ack(job['command']);self._publish(job,'REGISTERED',result=result)
                    result['phase_times_ns']=dict(job['times'])
                    self.session.emit(snapshot=result)
            except Exception as error:
                if job['id']not in self.jobs:raise  # Publication/event I/O failure must not rewrite a successful capture ACK.
                self._fail(job,error)
        if closing:return
        if self.render_error:
            for job in list(self.jobs.values()):
                if job['phase']=='RAW_SAVED':self._fail(job,RuntimeError('Raw observation retained; Sim failed: '+self.render_error))
        elif self.paired and self.rendering is None:
            job=next((j for j in self.jobs.values()if j['phase']=='RAW_SAVED'),None)
            if job:
                try:
                    self.session.renderer.capture(job['pending']);self.rendering=job['id'];job['render_deadline']=time.monotonic()+180
                    self._publish(job,'SIM_PAIR')
                except Exception as error:
                    self.renderer_failed(error)
                    if job['id']in self.jobs:self._fail(job,error)
        if self.rendering and time.monotonic()>self.jobs[self.rendering]['render_deadline']:
            self.renderer_failed(TimeoutError('Frozen Pair render timed out; raw observation retained'))

    def retry(self,command):
        identifier=command['payload']['snapshot_id'];job=self.failed.get(identifier)
        if len(self.jobs)>=self.capacity:raise ValueError('Capture queue full')
        if job is None or not job.get('pending'):raise ValueError('No sealed original observation is available to retry')
        if self.paired and self.render_error:raise ValueError('Reconnect the failed renderer before retrying this sealed observation')
        folder=Path(job['pending'].get('path')or job['pending']['staging'])
        if not(folder/'COMPLETE').is_file():
            raise ValueError('Original observation was not sealed; partial files retained, no registration retry possible')
        self.failed.pop(identifier);job.update(command=command,error=None);self.jobs[identifier]=job
        self.session.ack(command,'accepted')
        try:
            if self.paired and not(folder/'pair.json').is_file():self._publish(job,'RAW_SAVED')
            else:self._finish(job)
        except Exception as error:self._fail(job,error)

    def pending_records(self):
        return [dict(id=j['id'],phase=j['phase'],request=j['request'],pending=j.get('pending'),error=j.get('error'))for j in [*self.jobs.values(),*self.failed.values()]]

    def close(self):
        # The caller has already stopped serial control/devices. Complete only
        # already-owned filesystem work; never acquire later substitute frames.
        while any(j['future']is not None for j in self.jobs.values()):
            for job in list(self.jobs.values()):
                if job['future']is not None:
                    try:job['future'].result()
                    except Exception:pass
            self.poll(closing=True)
        for job in list(self.jobs.values()):self._fail(job,RuntimeError('Stopped before registration/Pair completion; sealed observation retained'))


class SnapshotStore:
    def __init__(self,project,*,session_id,model,mapping):
        project.require_writable();self.project=project;self.project_id=project.info['id'];self.session_id=session_id;self.model=Path(model)
        self.directory=project.root/'input/captures'/session_id
        self.mapping=copy.deepcopy(mapping);self.last_sequences={};self.completed={}
        if mapping.get('profile',{}).get('urdf_sha256')!=file_sha256(self.model):raise ValueError('Explicit model differs from measured Precision mapping')

    @classmethod
    def recover(cls,project,folder):
        """Explicit offline registration of a sealed owned observation, no recapture.

        Existing Pair bytes are reused if fully sealed. Raw-only observations
        stay raw-only; this operation never launches a renderer or motion.
        """
        from real2sim_builder.capture import load_session
        from real2sim_builder.files import read
        from real2sim_builder.candidate import exclusive
        folder=Path(folder).resolve()
        if not folder.is_relative_to((project.root/'input/captures').resolve()):raise ValueError('Recovery requires an owned Capture path')
        with exclusive(project):
            manifest,_,_=load_session(folder)
            if manifest.get('project_id')!=project.info['id']or len(manifest.get('snapshots',[]))!=1:raise ValueError('Recovery requires one Snapshot from this Project')
            if any(r.get('dataset_id')==manifest['source_dataset_id']for r in project.read_evidence(resolve=False).get('capture_sessions',[])):
                raise ValueError('Capture already registered; original archive retained')
            row=manifest['snapshots'][0];shot=folder/row['path'];metadata=read(shot/'metadata.json');state=read(shot/'state.json')
            store=cls(project,session_id=manifest.get('session_identity',folder.parent.name),model=folder/manifest['robot']['path'],mapping=manifest['joint_mapping'])
            pending=dict(id=row['id'],staging=str(folder)if folder.name.startswith('pending_')else None,
                path=str(folder),sample=dict(timestamp_ns=state['timestamp_ns'],unix_ns=state['timestamps']['follower']['end'].get('unix_ns'),q_measured=state['q_measured']),
                observed=metadata['images'],quality=metadata.get('quality_warnings',[]))
            return store.finish(pending)

    def prepare(self,identifier,state,images,*,now_ns=None):
        begin=time.monotonic()
        from real2sim_builder.scene import identifier as validate_id
        from real2sim_builder.capture import load_session
        validate_id(identifier)
        if self.project.info['id']!=self.project_id:raise ValueError('Project identity changed')
        if state['sim_joint_mapping']!=self.mapping:raise ValueError('Snapshot mapping changed')
        # Local reservation is atomic below; the locked import checks global
        # dataset uniqueness. Do not parse the entire Project before raw save.
        if identifier in self.completed:raise ValueError('Snapshot ID already exists')
        measured,observed,warnings=prepare_snapshot(state,images,{'cameras':{n:{'resolution':[640,480]}for n in('side','wrist')}},now_ns=now_ns)
        sequences={r['camera']:r['sequence']for r in observed}
        if any(sequences[n]<=self.last_sequences.get(n,-1)for n in sequences):raise ValueError('Camera frame reused; wait for new Side/Wrist frames')
        validated=time.monotonic()
        staging=self.directory/('pending_'+identifier);staging.mkdir(parents=True,exist_ok=False)
        model_relative,files=share_model(staging,self.model);shot=staging
        model_shared=time.monotonic()
        measured.update(hardware_identity=state['hardware']['follower']['identity'],camera_metadata=state.get('camera_metadata',{}),device_source=state.get('device_source','unspecified'))
        atomic_json(shot/'state.json',measured);shot_files={'state.json':file_sha256(shot/'state.json')}
        for row in observed:
            Image.fromarray(images['real_'+row['camera']]).save(shot/row['path'],compress_level=1);shot_files[row['path']]=file_sha256(shot/row['path'])
        layout_id='layout_'+self.project_id.replace('-','_')
        metadata=dict(id=identifier,scene_state_id=layout_id,files=shot_files,images=observed,quality_warnings=warnings)
        atomic_json(shot/'metadata.json',metadata);(shot/'COMPLETE').write_text('complete\n')
        manifest=dict(schema='real2sim.snapshot/1',dataset_id=identifier,session_id=identifier,clock={'domain':'host_monotonic_ns','hardware_synchronized':False,'timestamp_kind':'host_receipt_not_exposure'},
            joint_names=list(JOINTS),joint_units=['rad']*6,q_measured_source='physical_follower_feedback_converted_to_model',joint_mapping=self.mapping,
            source_robot_sha256=file_sha256(self.model),robot={'path':model_relative,'mapping_verified':False},cameras=[{'id':n,'camera_type':n,'resolution':[640,480]}for n in('side','wrist')],
            files=files,snapshots=[{'id':identifier,'scene_state_id':layout_id,'path':str(shot.relative_to(staging)),'metadata_sha256':file_sha256(shot/'metadata.json')}],
            project_id=self.project_id,session_identity=self.session_id,command_source='measured_observation_no_training_action',device_source=state.get('device_source','unspecified'),
            capture_policy=measured['capture_policy'],static_layout_verified=False,physical_verified=False)
        atomic_json(staging/'capture_manifest.yaml',manifest);(staging/'COMPLETE').write_text('complete\n');sealed=time.monotonic();load_session(staging)
        end=time.monotonic()
        self.last_sequences=sequences
        return dict(id=identifier,staging=str(staging),sample={'timestamp_ns':measured['timestamp_ns'],'unix_ns':measured['timestamps']['follower']['end'].get('unix_ns'),'q_measured':measured['q_measured']},quality=warnings,observed=observed,capture_request=measured.get('capture_request'),
            processing_times_ns={'raw_saved_ns':time.monotonic_ns()},
            save_timing_ms={'observation':(validated-begin)*1000,'model':(model_shared-validated)*1000,'encode_seal':(sealed-model_shared)*1000,'closure_check':(end-sealed)*1000,'prepare':(end-begin)*1000})

    def finish(self,pending,*,rendered=None):
        begin=time.monotonic();pair_ms=0.
        processing=dict(pending.get('processing_times_ns',{}))
        from real2sim_builder.files import read
        from real2sim_builder.capture import load_session,import_snapshots
        from real2sim_builder.candidate import exclusive
        identifier=pending['id']
        if identifier in self.completed:return self.completed[identifier]
        staging=Path(pending['staging'])if pending.get('staging')else None
        with exclusive(self.project):
            if staging is not None and staging.exists():
                manifest=read(staging/'capture_manifest.yaml')
                if rendered is not None:
                    from .pairs import write_pair
                    pair_begin=time.monotonic()
                    write_pair(staging,manifest,pending,rendered)
                    pair_ms=(time.monotonic()-pair_begin)*1000
                    processing['pair_completed_ns']=time.monotonic_ns()
                    atomic_json(staging/'capture_manifest.yaml',manifest)
                load_session(staging)
                from scene_contract.naming import numbered_path
                final=numbered_path(self.directory,'capture');os.rename(staging,final);pending['path']=str(final)
            else:final=Path(pending['path'])
            manifest=read(final/'capture_manifest.yaml');metadata=read(final/manifest['snapshots'][0]['path']/'metadata.json')
            paired='pair.json'in metadata['files']
            processing['registration_started_ns']=time.monotonic_ns()
            report=import_snapshots(self.project,final,paired=paired)
            processing['registration_completed_ns']=time.monotonic_ns()
        shot=final/manifest['snapshots'][0]['path'];images={i['camera']:str(shot/i['path'])for i in metadata['images']}
        if paired:
            pair=read(shot/'pair.json');images.update({'sim_'+n:str(shot/file)for n,file in pair['sim_images'].items()})
        result=dict(images=images,id=identifier,path=str(final),project_id=self.project_id,session_id=self.session_id,status='SAVED',registration=report,
            quality=pending['quality'],timestamp_ns=pending['sample']['timestamp_ns'],unix_ns=pending['sample'].get('unix_ns'),q_measured=pending['sample']['q_measured'],calibration_approved=False,paired=paired)
        timing={**pending.get('save_timing_ms',{}),'pair':pair_ms,'finish':(time.monotonic()-begin)*1000}
        timing['total']=timing.get('prepare',0.)+timing['finish'];result['save_timing_ms']=timing;result['processing_times_ns']=processing
        self.completed[identifier]=result;return result
