"""Measured-state Builder Candidate rendering and immutable paired evidence."""
import copy,time,os,json
from pathlib import Path
import numpy as np
from PIL import Image
from ..data.native import digest,file_sha256,atomic_json
from .calibration import JOINTS


class CandidateView:
    def __init__(self,project,candidate,model,mapping):
        from real2sim_builder.project import Project
        from real2sim_builder.files import read
        from real2sim_builder.scene import validate
        self.project=Project(project);self.path=Path(candidate).resolve();self.model=Path(model).resolve();self.mapping=copy.deepcopy(mapping)
        if not self.path.is_relative_to(self.project.root):raise ValueError('Candidate must belong to selected Project')
        self.scene=read(self.path);validate(self.scene,self.project.root,complete=True)
        robot=self.scene.get('robot_model',{})
        if robot.get('model_sha256')!=file_sha256(self.model):raise ValueError('Candidate robot model differs from measured model')
        if robot.get('mapping')!=mapping or robot.get('joint_names')!=list(JOINTS):raise ValueError('Candidate joint mapping/order differs from measured feedback')
        cameras={c['id']:c for c in self.scene['cameras']}
        if set(cameras)!={'side','wrist'}or any(c['resolution']!=[640,480]for c in cameras.values()):raise ValueError('Explicit Candidate Side/Wrist640x480 required')
        from real2sim_builder.scene import local_path
        self.candidate_model=local_path(self.project.root,robot['path'])
        if file_sha256(self.candidate_model)!=file_sha256(self.model):raise ValueError('Candidate FK URDF differs from measured model')
        self.identity=self._identity()
        self.watched=[self.path,self.model,self.candidate_model,*[local_path(self.project.root,r['path'])for r in self.scene['assets'].values()]]
        self.stats=self._stats()

    def _stats(self):
        return [(str(p),p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns,p.stat().st_ctime_ns,p.stat().st_nlink)for p in self.watched]

    def verify(self):
        if self._identity()!=self.identity:raise ValueError('Candidate/model/asset identity changed during session')

    def _identity(self):
        from real2sim_builder.scene import local_path
        return dict(project_id=self.project.info['id'],candidate_path=str(self.path.relative_to(self.project.root)),candidate_sha256=file_sha256(self.path),
            model_sha256=file_sha256(self.model),candidate_model_sha256=file_sha256(self.candidate_model),camera_calibration_sha256=digest(self.scene['cameras']),
            assets={key:file_sha256(local_path(self.project.root,row['path']))for key,row in self.scene['assets'].items()})

    def pose(self,q):
        from real2sim_builder.capture import observation_scene
        from real2sim_builder.calibration.geometry import simulation_offsets
        q=np.asarray(q,dtype=float)
        if q.shape!=(6,)or not np.isfinite(q).all():raise ValueError('Six finite measured joints required')
        if self._stats()!=self.stats:
            self.verify();self.stats=self._stats()
        binding=self.scene['robot_model'].get('simulation_joint_offsets_rad',{}).get('precision_mapping_sha256')
        if binding and binding!=self.mapping.get('sha256'):raise ValueError('Candidate simulation residual mapping differs')
        return observation_scene(self.scene,dict(session_id='measured_session',eligible=True,q_measured=q.tolist(),joint_names=list(JOINTS)),self.project.root)


class CandidateRenderer:
    def __init__(self,view,engine,directory):
        self.view=view;self.engine=engine;self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True);self.isaac=None
    def render(self,q,*,source_capture=None):
        from real2sim_builder.scene import world_pose
        from real2sim_builder.calibration.geometry import simulation_offsets
        begin=time.monotonic_ns();posed=self.view.pose(q);observations=[];geometry={}
        if source_capture is not None:
            from real2sim_builder.capture import load_session
            source_capture=Path(source_capture).resolve()
            if not source_capture.is_relative_to(self.view.project.root):raise ValueError('Source observation must belong to Project')
            manifest,samples,_=load_session(source_capture)
            if samples[0]['q_measured']!=list(q) or manifest['joint_mapping']!=self.view.mapping:raise ValueError('Source measured pose/mapping differs')
            observations=[r for r in self.view.project.evidence['images']if (self.view.project.root/r['path']).resolve().is_relative_to(source_capture)]
        if self.engine=='mujoco':
            from real2sim_builder.rendering import Renderer
            mode='software-egl'if os.environ.get('LIBGL_ALWAYS_SOFTWARE')=='1'else'egl'
            with Renderer(posed,self.view.project.root,self.directory/'mjcf',mode)as renderer:
                images={n:renderer.rgb(n)for n in('side','wrist')}
                from real2sim_builder.validation import object_metrics
                for observation in observations:
                    wanted={r['object']for r in self.view.project.evidence.get('masks',[])if r['image']==observation['path']}
                    masks={object_id:renderer.mask(observation['camera'],object_id)for object_id in wanted}
                    geometry[observation['camera']]=object_metrics(self.view.project,posed,observation,masks)
        elif self.engine in('isaac','isaaclab'):
            from .candidate_isaac import StaticRenderer
            if self.isaac is None:self.isaac=StaticRenderer(posed,self.view.project.root,self.directory)
            images=self.isaac.render(posed)
        else:raise ValueError('Actual MuJoCo or Isaac engine required')
        return dict(images=images,measured_q_rad=np.asarray(q,dtype=float).tolist(),applied_sim_joint_rad=(np.asarray(q)+simulation_offsets(posed['robot_model'])).tolist(),
            geometry=geometry,geometry_status='PROVIDED_EVIDENCE_DIAGNOSTICS'if geometry else'UNMEASURED',sim_joint_delta_rad=simulation_offsets(posed['robot_model']).tolist(),candidate_identity=self.view.identity,engine=self.engine,physics_steps=0,state_application='builder_measured_joint_fk',
            sim_timestamp={'monotonic_ns':time.monotonic_ns(),'timestamp_kind':'render_completion_not_camera_exposure'},render_ms=(time.monotonic_ns()-begin)/1e6,
            sim_cameras={c['id']:{'resolution':c['resolution'],'K':c['K']['value'],'T_world_optical':world_pose(posed,c).tolist()}for c in posed['cameras']},joint_mapping=self.view.mapping)
    def close(self):
        if self.isaac is not None:self.isaac.close()
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


def write_pair(root,manifest,pending,rendered):
    """Fill the existing snapshot paired-observation/1 before it is published."""
    from real2sim_builder.files import read
    from real2sim_builder.validation import compare
    root=Path(root);row=manifest['snapshots'][0];shot=root/row['path'];metadata=read(shot/'metadata.json')
    if rendered['measured_q_rad']!=pending['sample']['q_measured']:raise ValueError('Renderer result does not match frozen measured q')
    context={'workspace_id':manifest['project_id'],'content_sha256':rendered['candidate_identity']['candidate_sha256'],'builder':{'manifest_sha256':digest(rendered['candidate_identity'])}}
    metrics={};sim_files={}
    for image in metadata['images']:
        name=image['camera'];rgb=rendered['images'][name];real=np.asarray(Image.open(shot/image['path']).convert('RGB'));sim='sim_'+name+'.png'
        Image.fromarray(rgb).save(shot/sim);metadata['files'][sim]=file_sha256(shot/sim);sim_files[name]=sim
        # Existing Builder diagnostics emit normalized RGB metrics and visual comparisons.
        metrics[name]={**compare(real,rgb,shot/'comparison'/name,save_inputs=False),'objects':rendered.get('geometry',{}).get(name,[]),'landmark_rmse_px':None,'mask_iou':None,'geometry_status':'UNMEASURED'}
    for path in (shot/'comparison').rglob('*.png'):metadata['files'][path.relative_to(shot).as_posix()]=file_sha256(path)
    pair={k:v for k,v in rendered.items()if k!='images'};pair.update(schema='real2sim.paired-observation/1',meaning='historical_runtime_baseline_not_ground_truth',
        measurement_basis='follower_feedback',workspace_context=context,sim_q_measured_rad=rendered['applied_sim_joint_rad'],quality={'eligible':not pending['quality'],'warnings':pending['quality'],'physical_verified':False},
        sim_images=sim_files,comparison=metrics,hardware_synchronized=False,source_capture_timestamp_ns=pending['sample']['timestamp_ns'])
    atomic_json(shot/'pair.json',pair);metadata['files']['pair.json']=file_sha256(shot/'pair.json');atomic_json(shot/'metadata.json',metadata)
    row['metadata_sha256']=file_sha256(shot/'metadata.json');pending['comparison']=metrics


class RenderProcess:
    """A concrete read-only render child; serial control remains in Session."""
    def __init__(self,plan,mapping):
        import subprocess,sys
        self.root=plan.output_path/'renderer';self.root.mkdir();self.engine=plan.engine;self.capture_id=None;self.last_live=None;self.last_request=0;self.number=0
        view=CandidateView(plan.resolved_inputs['project']['root'],plan.resolved_inputs['candidate']['path'],plan.resolved_inputs['robot_model']['path'],mapping)
        atomic_json(self.root/'config.json',dict(project=str(view.project.root),candidate=str(view.path),model=str(view.model),mapping=mapping,identity=view.identity,engine=plan.engine))
        self.log=(self.root/'stdout.log').open('wb');self.process=subprocess.Popen([sys.executable,'-B','-m','robot_learning_workbench.robot.render_worker',str(self.root)],stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True)

    def observe(self,q):
        now=time.monotonic_ns()
        if now-self.last_request<100_000_000:return
        self.number+=1;self.last_request=now;atomic_json(self.root/'latest.json',{'id':'live_'+str(self.number),'q':list(q),'requested_ns':now})

    def capture(self,pending):
        if self.capture_id is not None:raise ValueError('One Pair render at a time')
        self.capture_id=pending['id'];atomic_json(self.root/'capture.json',{'id':self.capture_id,'q':pending['sample']['q_measured'],'requested_ns':time.monotonic_ns(),**({'source_capture':pending['source_capture']}if pending.get('source_capture')else{})})

    def _read(self,name):
        path=self.root/name
        if not path.is_file():return None
        before=path.read_bytes();result=json.loads(before);images={}
        for camera,row in result['files'].items():
            image=Path(row['path'])
            if not image.resolve().is_relative_to(self.root.resolve()):raise ValueError('Render result escaped owned storage')
            try:
                if file_sha256(image)!=row['sha256']:return None
                images[camera]=np.asarray(Image.open(image).convert('RGB'))
            except(FileNotFoundError,OSError):return None
        if path.read_bytes()!=before:return None
        return {**result,'images':images,'result_latency_ms':(time.monotonic_ns()-result['requested_ns'])/1e6}

    def poll(self):
        if(self.root/'error.json').is_file():raise ValueError('Candidate render failed: '+json.loads((self.root/'error.json').read_text())['error'])
        if self.process.poll()is not None:raise ValueError('Candidate render child exited: '+str(self.process.returncode))
        live=self._read('live-result.json')
        if live is not None and (self.last_live is None or live['id']!=self.last_live['id']):
            self.last_live={k:v for k,v in live.items()if k!='images'}
            from ..data import video
            if video._preview_sink is not None:
                for n,image in live['images'].items():video._preview_sink('sim_'+n,image,live['generation'],live['sim_timestamp']['monotonic_ns']/1e9,0)
        result=self._read('capture-result.json')if self.capture_id is not None else None
        if result is not None and result['id']==self.capture_id:self.capture_id=None;return result

    def close(self):
        import signal,subprocess
        (self.root/'stop').touch()
        try:
            if self.process.poll()is None:
                try:self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid,signal.SIGTERM)
                    try:self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:os.killpg(self.process.pid,signal.SIGKILL);self.process.wait(timeout=5)
        finally:self.log.close()


def derive_snapshot(project,source,identifier):
    """Hardlink immutable measured files, replacing only owned derived metadata."""
    import shutil
    from real2sim_builder.capture import load_session
    from real2sim_builder.files import read
    manifest,samples,_=load_session(source);source=Path(source)
    if manifest.get('project_id')!=project.info['id']:raise ValueError('Source Capture belongs to another Project')
    if len(samples)!=1:raise ValueError('Select one Snapshot for rerender')
    staging=project.root/'input/captures'/('pending_'+identifier)
    shutil.copytree(source,staging,copy_function=os.link)
    row=manifest['snapshots'][0];shot=staging/row['path'];metadata=read(shot/'metadata.json')
    real_files={'state.json',*[i['path']for i in metadata['images']]}
    for relative in list(metadata['files']):
        if relative not in real_files:(shot/relative).unlink();del metadata['files'][relative]
    atomic_json(shot/'metadata.json',metadata);row['metadata_sha256']=file_sha256(shot/'metadata.json')
    manifest.update(dataset_id=identifier,derived_from={'path':str(source),'manifest_sha256':file_sha256(source/'capture_manifest.yaml')})
    atomic_json(staging/'capture_manifest.yaml',manifest)
    return dict(id=identifier,staging=str(staging),source_capture=str(source),sample={'timestamp_ns':samples[0]['timestamp_ns'],'q_measured':samples[0]['q_measured']},quality=metadata.get('quality_warnings',[]))


def rerender(plan,*,events,commands):
    from ..recipe import verify_prepared_inputs
    from ..run import StageResult
    from .snapshots import SnapshotStore
    from real2sim_builder.project import Project
    from real2sim_builder.capture import load_session
    from types import SimpleNamespace
    verify_prepared_inputs(plan);plan.output_path.mkdir();source=Path(plan.resolved_inputs['capture_session']['path']);manifest,_,_=load_session(source)
    project=Project(plan.resolved_inputs['project']['root']);model=source/manifest['robot']['path'];mapping=manifest['joint_mapping']
    pending=derive_snapshot(project,source,plan.output_path.name.replace('-','_'))
    render_plan=SimpleNamespace(output_path=plan.output_path,engine=plan.engine,resolved_inputs={**plan.resolved_inputs,'robot_model':{'path':str(model)}})
    worker=RenderProcess(render_plan,mapping);deadline=time.monotonic()+180
    try:
        worker.capture(pending);result=None
        while result is None:
            if any(c['kind']=='cancel'for c in commands()):return StageResult('cancelled',(str(plan.output_path),),0,{'pending_snapshot':pending['staging']})
            if time.monotonic()>deadline:raise TimeoutError('Candidate render did not finish within180s; measured input preserved')
            result=worker.poll();time.sleep(.05)
        store=SnapshotStore(project,session_id=plan.output_path.name.replace('-','_'),model=model,mapping=mapping)
        saved=store.finish(pending,rendered=result);atomic_json(plan.output_path/'session-report.json',{'snapshots':[saved],'derived_from':str(source),'hardware_connected':False})
        events({'kind':'status','payload':{'progress':{'snapshot':saved}}})
        return StageResult('completed',(str(plan.output_path),),0,{'snapshots':1,'hardware_connected':False})
    finally:worker.close()
