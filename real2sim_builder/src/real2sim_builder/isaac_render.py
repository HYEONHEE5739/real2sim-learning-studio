"""Native static USD RGB/mask/optical depth, shared by fitting and Real/Sim.

Kit is initialized only by the owning child, never by importing this module.
The optimizer remains calibration.hybrid.fit_scene for both engines.
"""
from pathlib import Path
import copy
import numpy as np


class IsaacRenderer:
    def __init__(self,scene,root,scratch,mode=None,*,data_types=('rgb','distance_to_image_plane','semantic_segmentation')):
        from .rendering import render_scene
        scene=render_scene(scene)
        import isaaclab.sim as sim
        from isaacsim.core.utils.semantics import add_labels
        import omni.usd
        from .exporters.usd import export
        self.scene=copy.deepcopy(scene);self.cameras={};self.frames={};self.sim=None;self.stage=None;self.products=[];self.camera_product_paths={}
        self.resolutions={c['id']:c['resolution']for c in scene['cameras']}
        self.data_types=tuple(data_types)
        try:
            self.sim=sim.SimulationContext(sim.SimulationCfg(dt=1/30,device='cuda:0'))
            scratch=Path(scratch);scratch.mkdir(parents=True,exist_ok=True)
            path=scratch/'authored.usda';export(scene,root,path)
            cfg=sim.UsdFileCfg(usd_path=str(path));cfg.func('/World/Authored',cfg)
            self.stage=omni.usd.get_context().get_stage()
            if 'semantic_segmentation'in data_types:
                for obj in scene['objects']:
                    add_labels(self.stage.GetPrimAtPath('/World/Authored/'+obj['id']),[obj['id']],instance_name='class')
            self.sim.reset()
            self.update_scene(scene)
        except BaseException:
            self.close();raise

    def update_scene(self,scene):
        from .rendering import render_scene
        scene=render_scene(scene)
        from pxr import Gf,UsdGeom
        from .scene import world_pose
        from .cameras import OPTICAL_TO_RENDER
        if scene['assets']!=self.scene['assets']:raise ValueError('Renderer geometry changed; recompile explicitly')
        old={o['id']:o for o in self.scene['objects']}
        if set(old)!={o['id']for o in scene['objects']}:raise ValueError('Renderer object set changed')
        def set_attr(path,name,val):
            attribute=self.stage.GetPrimAtPath('/World/Authored/'+path).GetAttribute(name)
            if not attribute:raise ValueError('Native USD attribute missing: '+path+'/'+name)
            attribute.Set(val)
        for obj in scene['objects']:
            previous=old[obj['id']]
            if any(obj[k]!=previous[k]for k in('visual','collision')):
                raise ValueError('Renderer geometry changed; recompile explicitly')
            from .calibration.geometry import dimension_axes,parts
            axes={i for group in dimension_axes(previous) for i in group}
            if obj['dimensions']['value']!=previous['dimensions']['value'] and (not axes or
                    any(obj['dimensions']['value'][i]!=previous['dimensions']['value'][i] for i in range(3) if i not in axes)):
                raise ValueError('Renderer dimensions are protected or require a new Asset Version')
            if axes:
                for field in ('visual','collision'):
                    for index,part in enumerate(parts(obj,field)):
                        path=obj['id']+'/'+field+'_'+str(index);dims=part['dimensions'];kind=part['type']
                        if kind=='box':
                            transform=part['pose'].copy();transform[:3,:3]=transform[:3,:3]@np.diag(dims/2)
                            set_attr(path,'xformOp:transform',Gf.Matrix4d(*transform.T.ravel().tolist()))
                        else:
                            set_attr(path,'radius',float(dims[0]/2))
                            if kind=='cylinder':set_attr(path,'height',float(dims[2]))
            set_attr(obj['id'],'xformOp:transform',Gf.Matrix4d(*world_pose(scene,obj).T.ravel().tolist()))
            if not obj.get('object_asset'):
                shader='material_'+obj['id']+'/Surface'
                set_attr(shader,'inputs:diffuseColor',Gf.Vec3f(*(obj['color']['value']or[.5]*3)))
                for field,default in(('roughness',.6),('metallic',0.)):
                    set_attr(shader,'inputs:'+field,float(obj.get('material',{}).get(field,{}).get('value',default)))
        for camera in scene['cameras']:
            name=camera['id'];w,h=camera['resolution']
            if name in self.resolutions and self.resolutions[name]!=[w,h]:raise ValueError('Isaac camera resolution changed; recompile explicitly')
            self.resolutions[name]=[w,h]
            path='/World/Authored/'+name
            self.stage.DefinePrim(path,'Camera').SetActive(True)
            native=UsdGeom.Camera(self.stage.GetPrimAtPath(path))
            if not UsdGeom.Xformable(native).GetOrderedXformOps():UsdGeom.Xformable(native).AddTransformOp()
            from .cameras import CLIP
            native.CreateClippingRangeAttr(Gf.Vec2f(*CLIP))
            for attr in('FocalLength','HorizontalAperture','VerticalAperture','HorizontalApertureOffset','VerticalApertureOffset'):
                getattr(native,'Create'+attr+'Attr')()
            pose=world_pose(scene,camera)@OPTICAL_TO_RENDER;k=np.asarray(camera['K']['value']);focal=10.
            set_attr(name,'xformOp:transform',Gf.Matrix4d(*pose.T.ravel().tolist()))
            # Same USD pinhole convention as the exporter, including principal
            # point offsets and unequal fx/fy. No centered-lens approximation.
            for attr,val in {'focalLength':focal,'horizontalAperture':w/k[0,0]*focal,
                    'verticalAperture':h/k[1,1]*focal,'horizontalApertureOffset':(w/2-k[0,2])/k[0,0]*focal,
                    'verticalApertureOffset':(k[1,2]-h/2)/k[1,1]*focal}.items():set_attr(name,attr,float(val))
        set_attr('AmbientLight','inputs:color',Gf.Vec3f(*scene['lights']['ambient']['value']))
        for light in scene['lights'].get('sources',[]):
            name='light_'+light['id']
            set_attr(name,'xformOp:transform',Gf.Matrix4d(*np.asarray(light['pose']['value']).T.ravel().tolist()))
            set_attr(name,'inputs:intensity',float(light['energy']['value']))
            set_attr(name,'inputs:color',Gf.Vec3f(*light['color']['value']))
        self.camera_views={c['id']:c for c in scene['cameras']}
        if set(self.cameras)!=set(self.camera_views):
            self.release_cameras()
            import omni.replicator.core as rep
            for camera in scene['cameras']:
                name=camera['id'];w,h=camera['resolution']
                self.stage.GetPrimAtPath('/World/Authored/'+name).SetActive(True)
                product=rep.create.render_product('/World/Authored/'+name,(w,h),force_new=True)
                self.products.append(product);self.camera_product_paths[name]=product.path;self.cameras[name]={}
                for kind in self.data_types:
                    params={'colorize':False}if kind=='semantic_segmentation'else None
                    annotator=rep.AnnotatorRegistry.get_annotator(kind,init_params=params,device='cpu')
                    self.cameras[name][kind]=annotator;annotator.attach([product.path])
        self.frames.clear()
        # Rendering only: no physics step and no articulation command.
        for _ in range(3):self.sim.render()

    def _frame(self,camera):
        if camera not in self.frames:
            output={};info=None;w,h=self.resolutions[camera]
            for kind,annotator in self.cameras[camera].items():
                packet=annotator.get_data()
                if isinstance(packet,dict):
                    pixels=packet['data']
                    if kind=='semantic_segmentation':info=copy.deepcopy(packet.get('info'))
                else:pixels=packet
                pixels=np.asarray(pixels).copy()
                if pixels.shape[:2]!=(h,w):raise RuntimeError('Isaac render buffer not ready or wrong resolution: '+camera+'/'+kind)
                if pixels.ndim==2:pixels=pixels[...,None]
                output[kind]=pixels
            self.frames[camera]=(output,info)
        return self.frames[camera]

    def rgb(self,camera):
        from .cameras import distort_render
        return distort_render(self.camera_views[camera],self._frame(camera)[0]['rgb'][...,:3])
    def depth(self,camera):
        from .cameras import distort_render
        return distort_render(self.camera_views[camera],self._frame(camera)[0]['distance_to_image_plane'][...,0],nearest=True)
    def mask(self,camera,obj):
        if obj not in{o['id']for o in self.scene['objects']}:raise ValueError('Unknown silhouette object')
        data,info=self._frame(camera);labels=(info or{}).get('idToLabels',{})
        ids=[int(key)for key,row in labels.items()if obj in str(row.get('class','')).split(',')]
        from .cameras import distort_render
        return distort_render(self.camera_views[camera],np.isin(data['semantic_segmentation'][...,0],ids),nearest=True)
    def render(self,scene):
        self.update_scene(scene);return {name:self.rgb(name)for name in self.cameras}
    def release_cameras(self):
        """Release requested view products, retaining compiled geometry/context."""
        from contextlib import ExitStack
        self.frames.clear()
        cameras,self.cameras=self.cameras,{};products,self.products=self.products,[]
        paths,self.camera_product_paths=self.camera_product_paths,{}
        with ExitStack()as cleanup:
            if self.stage is not None:
                for name in cameras:cleanup.callback(self.stage.GetPrimAtPath('/World/Authored/'+name).SetActive,False)
            for product in reversed(products):cleanup.callback(product.destroy)
            for name,annotators in reversed(list(cameras.items())):
                for annotator in reversed(list(annotators.values())):cleanup.callback(annotator.detach,[paths[name]])

    def close(self):
        from contextlib import ExitStack
        stage,self.stage=self.stage,None;sim,self.sim=self.sim,None
        # Finish every release even if a native annotator detach raises.
        with ExitStack()as cleanup:
            if sim is not None:
                # Unsubscribe the standalone STOP handler before stopping the
                # live timeline; otherwise a subsequent context can keep rendering.
                cleanup.callback(sim.stop);cleanup.callback(sim.clear_instance);cleanup.callback(sim.clear_all_callbacks)
            if stage is not None:cleanup.callback(stage.RemovePrim,'/World/Authored')
            cleanup.callback(self.release_cameras)
    def __enter__(self):return self
    def __exit__(self,*_):self.close()


def run_job(project,scene,folder,options,operation):
    """One owned Kit process per solve/comparison, with bounded stop/cleanup."""
    import os,signal,subprocess,sys,time,uuid
    from .files import read,write
    job=Path(folder)/('isaac-'+uuid.uuid4().hex);job.mkdir(parents=True)
    timeout=float(options.get('native_timeout_s',900))
    if not np.isfinite(timeout)or timeout<=0:raise ValueError('Positive native timeout required')
    write(job/'request.json',{'project':str(project.root),'scene':scene,'options':options,'operation':operation})
    child=None
    try:
        with(job/'worker.log').open('w')as log:
            child=subprocess.Popen([sys.executable,'-B','-m','real2sim_builder.isaac_render',str(job)],
                stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            previous=time.monotonic();elapsed=0.;stop_at=None
            while child.poll()is None:
                # Only the worker consumes pause/resume/stop. The parent observes
                # stop to bound cleanup even when Kit is stuck inside native code.
                control=project.root/'working/control.json'
                try:command=read(control).get('command')
                except FileNotFoundError:command=None
                now=time.monotonic()
                if command=='stop'and stop_at is None:stop_at=now
                if stop_at is not None and now-stop_at>=3:raise InterruptedError('User stopped Isaac fitting')
                paused=command=='pause'or project.state['status']=='PAUSED'
                if not paused:elapsed+=now-previous
                previous=now
                if elapsed>timeout:raise TimeoutError('Isaac fitting timed out: '+str(job/'worker.log'))
                time.sleep(.05)
        if child.returncode or(job/'error.json').exists():
            error=read(job/'error.json')if(job/'error.json').exists()else{}
            message=error.get('error','Native worker failed; inspect '+str(job/'worker.log'))
            if error.get('stopped'):raise InterruptedError(message)
            raise RuntimeError(message)
        if not(job/'report.json').exists():raise RuntimeError('Native worker exited without a report: '+str(job/'worker.log'))
        report=read(job/'report.json')
        return (read(job/'best-scene.yaml'),report)if operation=='fit'else report
    except (InterruptedError,RuntimeError,TimeoutError)as error:
        if(job/'best-scene.yaml').exists():error.best_scene=read(job/'best-scene.yaml')
        raise
    finally:
        if child is not None and child.poll()is None:
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=3)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()


def worker(folder):
    from isaaclab.app import AppLauncher
    from .files import read,write
    folder=Path(folder);request=read(folder/'request.json');launcher=None
    try:
        # Use SimulationApp's documented standalone default. All result files
        # are closed before close(); extension-by-extension USD shutdown can
        # deadlock with native semantic annotators in the installed runtime.
        launcher=AppLauncher(headless=True,enable_cameras=True,device='cuda:0',fast_shutdown=True)
        from .project import Project
        from .calibration.hybrid import fit_scene,alignment_metrics
        project=Project(request['project']);options={**request['options'],'renderer_factory':IsaacRenderer}
        if request['operation']=='fit':
            scene,report=fit_scene(project,request['scene'],folder,options);write(folder/'best-scene.yaml',scene)
        else:
            from functools import partial
            from .calibration.hybrid import cloud_inputs
            # RGB comparison needs no depth buffers. Only observations with
            # object masks require semantic output; full-resolution photo AOVs
            # otherwise consume GPU memory without contributing to this loss.
            outputs=('rgb','semantic_segmentation')if cloud_inputs(project,request['scene'])else('rgb',)
            options['renderer_factory']=partial(IsaacRenderer,data_types=outputs)
            report=alignment_metrics(project,request['scene'],folder,options)
        write(folder/'report.json',report)
    except BaseException as error:
        write(folder/'error.json',{'error':str(error),'stopped':isinstance(error,InterruptedError)});raise
    finally:
        # Sensor arrays are copied synchronously; no Replicator writer is queued.
        if launcher:launcher.app.close(wait_for_replicator=False)


if __name__=='__main__':
    import sys
    worker(sys.argv[1])
