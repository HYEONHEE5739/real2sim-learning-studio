"""Existing MuJoCo/Blender rendering; engines remain lazy and unavailable is explicit.

MuJoCo3.3.7 Renderer: https://mujoco.readthedocs.io/en/3.3.7/python.html#rendering
Blender worker is invoked only through an already installed executable.
"""
import sys
if __name__ == '__main__' and '--blender-worker' in sys.argv:
    import bpy
    import json,runpy,numpy as np
    from pathlib import Path
    from mathutils import Matrix,Vector

def _blender_material(row):
    mat = bpy.data.materials.new(row['id'] + '_material')
    mat.use_nodes = True
    node = mat.node_tree.nodes.get('Principled BSDF')
    node.inputs['Base Color'].default_value = (*row['color'], 1.0)
    node.inputs['Roughness'].default_value = row['roughness']
    node.inputs['Metallic'].default_value = row['metallic']
    if row.get('texture'):
        texture = mat.node_tree.nodes.new('ShaderNodeTexImage')
        texture.image = bpy.data.images.load(row['texture'])
        texture.image.pack()
        mat.node_tree.links.new(texture.outputs['Color'], node.inputs['Base Color'])
    return mat

def _blender_build(description):
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 16
    scene.cycles.seed = 0
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.view_settings.view_transform = 'Standard'
    scene.view_settings.exposure = 0
    scene.view_settings.gamma = 1
    scene.world = bpy.data.worlds.new('CanonicalWorld')
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get('Background')
    background.inputs['Color'].default_value = (*description['ambient'], 1)
    background.inputs['Strength'].default_value = 1
    for row in description['objects']:
        meshes = []
        mat = _blender_material(row)
        for part in row['parts']:
            kind = part['type']
            dims = part['dimensions']
            if kind == 'mesh':
                mesh = bpy.data.meshes.new(row['id'])
                mesh.from_pydata(part['vertices'], [], part['faces'])
                mesh.update()
                obj = bpy.data.objects.new(row['id'], mesh)
                scene.collection.objects.link(obj)
                mesh.transform(Matrix.Diagonal((*part.get('scale', [1, 1, 1]), 1.0)))
                if part.get('uv'):
                    layer = mesh.uv_layers.new(name='UVMap')
                    for loop in mesh.loops:
                        layer.data[loop.index].uv = part['uv'][loop.vertex_index]
            else:
                if kind == 'box':
                    bpy.ops.mesh.primitive_cube_add(size=1)
                    scale = dims
                elif kind == 'sphere':
                    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=0.5)
                    scale = dims
                elif kind == 'cylinder':
                    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.5, depth=1)
                    scale = dims
                else:
                    raise ValueError('Unsupported visual part ' + kind)
                obj = bpy.context.object
                obj.data.transform(Matrix.Diagonal((*scale, 1.0)))
            obj.data.transform(Matrix(part['pose']))
            obj.data.materials.clear()
            obj.data.materials.append(mat)
            meshes.append(obj)
        bpy.ops.object.select_all(action='DESELECT')
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
        obj = bpy.context.object
        obj.name = row['id']
        obj['r2s_id'] = row['id']
        obj['r2s_role'] = row['role']
        obj.matrix_world = Matrix(row['pose'])
    for row in description['cameras']:
        data = bpy.data.cameras.new(row['id'])
        obj = bpy.data.objects.new(row['id'], data)
        scene.collection.objects.link(obj)
        obj.matrix_world = Matrix(row['pose'])
        obj['r2s_id'] = row['id']
        obj['r2s_resolution'] = row['resolution']
        obj['r2s_pixel_aspect'] = [row['intrinsics']['pixel_aspect_x'], row['intrinsics']['pixel_aspect_y']]
        data.type = 'PERSP'
        data.clip_start = description['conventions']['clip_m'][0]
        data.clip_end = description['conventions']['clip_m'][1]
        for key in ('sensor_fit', 'sensor_width', 'lens', 'shift_x', 'shift_y'):
            setattr(data, key, row['intrinsics'][key])
    for row in description.get('lights', []):
        data = bpy.data.lights.new(row['id'], {'point': 'POINT', 'area': 'AREA', 'sun': 'SUN'}[row['type']])
        obj = bpy.data.objects.new(row['id'], data)
        scene.collection.objects.link(obj)
        obj.matrix_world = Matrix(row['pose']['value'])
        obj['r2s_id'] = row['id']
        data.energy = row['energy']['value']
        data.color = row['color']['value']
        if data.type == 'AREA':
            data.size = row['size']['value']
    bpy.context.view_layer.update()

def _blender_camera_setup(camera):
    scene = bpy.context.scene
    scene.camera = camera
    w, h = camera['r2s_resolution']
    scene.render.resolution_x = w
    scene.render.resolution_y = h
    scene.render.resolution_percentage = 100
    scene.render.pixel_aspect_x, scene.render.pixel_aspect_y = camera['r2s_pixel_aspect']

def _blender_render(folder):
    scene = bpy.context.scene
    objects = [o for o in scene.objects if o.type == 'MESH' and o.get('r2s_id')]
    cameras = [o for o in scene.objects if o.type == 'CAMERA' and o.get('r2s_id')]
    projections = []
    from bpy_extras.object_utils import world_to_camera_view
    for camera in cameras:
        _blender_camera_setup(camera)
        w, h = camera['r2s_resolution']
        for obj in objects:
            ndc = world_to_camera_view(scene, camera, obj.matrix_world.translation)
            projections.append({'camera': camera['r2s_id'], 'object': obj['r2s_id'], 'uv': [float(ndc.x * w), float((1 - ndc.y) * h)]})
        scene.render.filepath = str(folder / (camera['r2s_id'] + '.png'))
        bpy.ops.render.render(write_still=True)
    old = [(o, list(o.data.materials), [p.material_index for p in o.data.polygons]) for o in objects]
    scene.view_settings.view_transform = 'Raw'
    background = scene.world.node_tree.nodes.get('Background')
    background.inputs['Color'].default_value = (0, 0, 0, 1)
    for index, obj in enumerate(objects, 1):
        rgb = [index >> shift & 255 for shift in (0, 8, 16)]
        mat = bpy.data.materials.new('id_' + str(index))
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        out = nodes.new('ShaderNodeOutputMaterial')
        emission = nodes.new('ShaderNodeEmission')
        emission.inputs['Color'].default_value = (*(v / 255 for v in rgb), 1)
        mat.node_tree.links.new(emission.outputs[0], out.inputs['Surface'])
        obj.data.materials.clear()
        obj.data.materials.append(mat)
        for polygon in obj.data.polygons:
            polygon.material_index = 0
    for camera in cameras:
        _blender_camera_setup(camera)
        path = folder / (camera['r2s_id'] + '_labels.png')
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        im = bpy.data.images.load(str(path), check_existing=False)
        im.colorspace_settings.name = 'Non-Color'
        pixels = np.asarray(im.pixels[:]).reshape(im.size[1], im.size[0], 4)[::-1, :, :3]
        rgb = np.rint(pixels * 255).astype(np.int32)
        labels = rgb[:, :, 0] + 256 * rgb[:, :, 1] + 65536 * rgb[:, :, 2]
        for index, obj in enumerate(objects, 1):
            np.save(folder / (camera['r2s_id'] + '__' + obj['r2s_id'] + '.npy'), labels == index)
    for obj, mats, indices in old:
        obj.data.materials.clear()
        for mat in mats:
            obj.data.materials.append(mat)
        for polygon, index in zip(obj.data.polygons, indices):
            polygon.material_index = index
    return {'projections': projections}

def _blender_synchronize(folder):
    assets = folder / 'assets'
    assets.mkdir(exist_ok=True)
    result = {'objects': [], 'cameras': [], 'lights': []}
    background = bpy.context.scene.world.node_tree.nodes.get('Background')
    if background.inputs['Color'].is_linked or background.inputs['Strength'].is_linked:
        raise ValueError('Bake environment lighting before canonical sync')
    result['ambient'] = [v * background.inputs['Strength'].default_value for v in background.inputs['Color'].default_value[:3]]
    graph = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.context.scene.objects:
        if not obj.get('r2s_id'):
            if obj.type in ('MESH', 'CAMERA', 'LIGHT') and (not obj.hide_render):
                raise ValueError('Tag authored objects with r2s_id and meshes with r2s_role before sync')
            continue
        name = obj['r2s_id']
        if not name.replace('_', 'a').isalnum() or not name.isascii():
            raise ValueError('Invalid canonical object ID')
        if obj.type == 'MESH':
            evaluated = obj.evaluated_get(graph)
            mesh = evaluated.to_mesh()
            mesh.calc_loop_triangles()
            try:
                translation, rotation, scale = obj.matrix_world.decompose()
                reconstructed = Matrix.LocRotScale(translation, rotation, scale)
                if not np.allclose(np.asarray(reconstructed), np.asarray(obj.matrix_world), atol=1e-06) or min(scale) <= 0:
                    raise ValueError('Bake shear/negative scale before sync')
                if len(obj.data.materials) > 1:
                    raise ValueError('One material per canonical object required; split semantic objects explicitly')
                vertices = np.array([[v.co[i] * scale[i] for i in range(3)] for v in mesh.vertices])
                path = assets / (name + '.obj')
                lines = ['v ' + ' '.join(map(str, v)) for v in vertices]
                uv = mesh.uv_layers.active
                if uv:
                    lines += ['vt ' + str(d.uv.x) + ' ' + str(d.uv.y) for d in uv.data]
                for triangle in mesh.loop_triangles:
                    tokens = [str(v + 1) + '/' + str(loop + 1) if uv else str(v + 1) for v, loop in zip(triangle.vertices, triangle.loops)]
                    lines.append('f ' + ' '.join(tokens))
                path.write_text('\n'.join(lines) + '\n')
                mat = obj.active_material
                node = mat.node_tree.nodes.get('Principled BSDF') if mat and mat.use_nodes else None
                if node is None:
                    raise ValueError('Sync supports Principled BSDF materials only')
                color = node.inputs['Base Color']
                texture = None
                if color.is_linked:
                    source = color.links[0].from_node
                    if source.type != 'TEX_IMAGE' or source.image is None:
                        raise ValueError('Bake procedural materials to an image before sync')
                    texture = assets / (name + '_texture.png')
                    image = source.image.copy()
                    image.filepath_raw = str(texture)
                    image.file_format = 'PNG'
                    image.save()
                    bpy.data.images.remove(image)
                result['objects'].append({'id': name, 'role': obj.get('r2s_role', 'fixture'), 'pose': np.asarray(Matrix.LocRotScale(translation, rotation, Vector((1, 1, 1)))).tolist(), 'dimensions': np.ptp(vertices, axis=0).tolist(), 'mesh': str(path), 'texture': str(texture) if texture else None, 'color': list(color.default_value[:3]), 'roughness': node.inputs['Roughness'].default_value, 'metallic': node.inputs['Metallic'].default_value})
            finally:
                evaluated.to_mesh_clear()
        elif obj.type == 'LIGHT':
            if obj.data.type not in ('POINT', 'AREA', 'SUN'):
                raise ValueError('Unsupported light type')
            result['lights'].append({'id': name, 'type': obj.data.type.lower(), 'pose': np.asarray(obj.matrix_world).tolist(), 'color': list(obj.data.color), 'energy': obj.data.energy, 'size': obj.data.size if obj.data.type == 'AREA' else 0.0})
        elif obj.type == 'CAMERA':
            data = obj.data
            w, h = obj['r2s_resolution']
            ax, ay = obj['r2s_pixel_aspect']
            ratio = ay / ax
            if data.type != 'PERSP' or data.sensor_fit != 'HORIZONTAL':
                raise ValueError('Use canonical horizontal-fit perspective cameras')
            fx = data.lens / data.sensor_width * w
            fy = fx / ratio
            cx = w / 2 - data.shift_x * w
            cy = h / 2 + data.shift_y * w / ratio
            result['cameras'].append({'id': name, 'pose': (np.asarray(obj.matrix_world) @ np.diag([1, -1, -1, 1])).tolist(), 'K': [[fx, 0, cx], [0, fy, cy], [0, 0, 1]], 'resolution': [w, h]})
    return result

def _blender_repose(description):
    """Keep synchronized authored meshes/materials, apply immutable observed FK poses."""
    objects = {o.get('r2s_id'): o for o in bpy.context.scene.objects if o.get('r2s_id')}
    for row in description['objects']:
        obj = objects.get(row['id'])
        if obj is None or obj.type != 'MESH':
            raise ValueError('Missing authored object: ' + row['id'])
        obj.matrix_world = Matrix(row['pose'])
    for row in description['cameras']:
        obj = objects.get(row['id'])
        if obj is None or obj.type != 'CAMERA':
            raise ValueError('Missing authored camera: ' + row['id'])
        obj.matrix_world = Matrix(row['pose'])
        obj['r2s_resolution'] = row['resolution']
        settings = row['intrinsics']
        for key in ('lens', 'sensor_width', 'shift_x', 'shift_y', 'sensor_fit'):
            setattr(obj.data, key, settings[key])
        obj['r2s_pixel_aspect'] = [settings['pixel_aspect_x'], settings['pixel_aspect_y']]

def _blender_main():
    request = json.loads(Path(sys.argv[sys.argv.index('--blender-worker') + 1]).read_text())
    folder = Path(request['output'])
    folder.mkdir(parents=True, exist_ok=True)
    action = request['action']
    if action in ('build', 'render'):
        _blender_build(request['scene'])
    else:
        bpy.ops.wm.open_mainfile(filepath=request['blend'])
    if request.get('repose'):
        _blender_repose(request['scene'])
    result = {'status': 'OK', 'action': action}
    if action == 'author':
        runpy.run_path(request['script'], run_name='__main__')
    if action in ('build', 'author'):
        bpy.ops.file.pack_all()
        bpy.ops.wm.save_as_mainfile(filepath=request['blend'])
    elif action in ('render', 'render-blend'):
        result.update(_blender_render(folder))
    elif action == 'sync':
        result.update(_blender_synchronize(folder))
    (folder / 'result.json').write_text(json.dumps(result, allow_nan=False, indent=2))

if __name__ == "__main__" and "--blender-worker" in sys.argv:
    _blender_main()
    raise SystemExit(0)

"""Lazy offscreen MuJoCo rendering; software/EGL comparisons use separate workers."""
import os
from pathlib import Path
import numpy as np
from .project import local_path


def configure(mode):
    modes={'egl':'egl','software-egl':'egl','osmesa':'osmesa'}
    if mode not in modes:raise ValueError('Unsupported renderer')
    if 'mujoco' in sys.modules:
        if os.environ.get('MUJOCO_GL')!=modes[mode] or (os.environ.get('LIBGL_ALWAYS_SOFTWARE')=='1')!=(mode=='software-egl'):
            raise RuntimeError('Change renderer in a new worker process')
        return
    os.environ['MUJOCO_GL']=modes[mode]
    if mode=='software-egl':
        os.environ['LIBGL_ALWAYS_SOFTWARE']='1'
        mesa='/usr/share/glvnd/egl_vendor.d/50_mesa.json'
        if Path(mesa).is_file():os.environ['__EGL_VENDOR_LIBRARY_FILENAMES']=mesa
    else:
        os.environ.pop('LIBGL_ALWAYS_SOFTWARE',None);os.environ.pop('__EGL_VENDOR_LIBRARY_FILENAMES',None)


class Renderer:
    def __init__(self,scene,root,scratch,mode='software-egl'):
        from .exporters.mjcf import export
        self.mode=mode
        configure(mode)
        import mujoco
        self.mj=mujoco;self.scene=scene;self.renderers={}
        scratch=Path(scratch);scratch.mkdir(parents=True,exist_ok=True)
        export(scene,root,scratch/'scene.xml')
        self.model=mujoco.MjModel.from_xml_path(str(scratch/'scene.xml'));self.data=mujoco.MjData(self.model)
        mujoco.mj_forward(self.model,self.data)

    def rgb(self,camera):
        c=next(c for c in self.scene['cameras'] if c['id']==camera);w,h=c['resolution']
        if camera not in self.renderers:self.renderers[camera]=self.mj.Renderer(self.model,height=h,width=w)
        renderer=self.renderers[camera];renderer.update_scene(self.data,camera=camera)
        rgb=renderer.render().copy()
        linear=rgb.astype(float)/255.;display=np.where(linear<=.0031308,12.92*linear,1.055*linear**(1/2.4)-.055)
        return np.rint(np.clip(display,0,1)*255).astype(np.uint8)

    def mask(self,camera,obj):
        if camera not in self.renderers:self.rgb(camera)
        renderer=self.renderers[camera];renderer.enable_segmentation_rendering()
        try:
            renderer.update_scene(self.data,camera=camera);seg=renderer.render()
            body=self.mj.mj_name2id(self.model,self.mj.mjtObj.mjOBJ_BODY,obj)
            if body<0:raise ValueError('Unknown silhouette object')
            result=np.zeros(seg.shape[:2],bool)
            for gid in np.where(self.model.geom_bodyid==body)[0]:result|=(seg[:,:,0]==gid)&(seg[:,:,1]==int(self.mj.mjtObj.mjOBJ_GEOM))
            return result
        finally:renderer.disable_segmentation_rendering()

    def close(self):
        for r in self.renderers.values():r.close()
        self.renderers.clear()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


from contextlib import contextmanager

@contextmanager
def for_observation(project,scene,image,default,folder):
    if not image.get('session_id'):
        yield default;return
    from .project import observation_scene
    from .rendering import BlenderRenderer
    posed=observation_scene(scene,image,project.root)
    factory=BlenderRenderer if getattr(default,'engine',None)=='blender' else Renderer
    with factory(posed,project.root,folder,getattr(default,'mode','software-egl')) as model:
        if factory is BlenderRenderer:
            model.blend=getattr(default,'blend',None)
            model.repose=bool(model.blend)
        yield model


"""JSON bridge to an existing Blender executable, never installs or imports bpy here."""
import copy
import json
import shutil
import subprocess
from .project import write, read, sha
from .project import validate, world_pose, frame_world, local_path, value
from .project import blender_intrinsics, render_pose, CONVENTIONS
from .project import preserve
from .calibration.geometry import parts, mesh_data, obj_data


class Unavailable(RuntimeError): pass


def worker_environment():
    """Blender ships its own Python/USD/MaterialX; isolate host binding paths."""
    environment = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME', 'LD_LIBRARY_PATH', 'LD_PRELOAD'):
        environment.pop(key, None)
    return environment


def capability():
    requested=os.environ.get('REAL2SIM_BLENDER','blender')
    executable=shutil.which(requested)
    if not executable: return {'available':False,'reason':'Blender executable not found; set REAL2SIM_BLENDER to an existing executable','requested':requested}
    try:
        result=subprocess.run([executable,'--version'],capture_output=True,text=True,timeout=15,env=worker_environment())
        if result.returncode: raise RuntimeError(result.stderr)
        return {'available':True,'executable':executable,'version':result.stdout.splitlines()[0]}
    except (OSError,subprocess.SubprocessError,RuntimeError) as exc:
        return {'available':False,'reason':str(exc),'requested':requested}


def invoke(request, folder):
    available=capability()
    if not available['available']: raise Unavailable(available['reason'])
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    write(folder/'request.json',request)
    command=[available['executable'],'--background','-noaudio','--factory-startup','--python-exit-code','1',
             '--python',str(Path(__file__).resolve()),'--','--blender-worker',str(folder/'request.json')]
    with (folder/'blender.log').open('w') as stream:
        subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,check=True,timeout=600,env=worker_environment())
    return read(folder/'result.json')


def description(scene, root):
    validate(scene,root);objects=[]
    for obj in scene['objects']:
        pieces=[]
        for part in parts(obj,'visual'):
            row={k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in part.items()}
            if part['type']=='mesh':
                path=local_path(root,scene['assets'][part['asset']]['path'])
                vertices,faces=mesh_data(path)
                row.update(vertices=vertices.tolist(),faces=faces.tolist())
                if path.suffix.lower()=='.obj': row['uv']=obj_data(path)[2].tolist()
            pieces.append(row)
        texture=obj['visual'].get('texture')
        objects.append({'id':obj['id'],'role':obj['role'],'pose':world_pose(scene,obj).tolist(),'parts':pieces,
                        'color':obj['color']['value'] or [.5]*3,
                        'roughness':obj.get('material',{}).get('roughness',{}).get('value',.6),
                        'metallic':obj.get('material',{}).get('metallic',{}).get('value',0.),
                        'texture':str(local_path(root,scene['assets'][texture]['path'])) if texture else None})
    cameras=[]
    for c in scene['cameras']:
        if any(c['distortion']['value']): raise ValueError('Undistort evidence before Blender rendering')
        cameras.append({'id':c['id'],'pose':render_pose(scene,c).tolist(),'resolution':c['resolution'],
                        'intrinsics':blender_intrinsics(c)})
    return {'objects':objects,'cameras':cameras,'ambient':scene['lights']['ambient']['value'],'lights':scene['lights'].get('sources',[]),'conventions':CONVENTIONS}


class BlenderRenderer:
    engine = 'blender'
    def __init__(self,scene,root,scratch,mode=None):
        self.scene=scene;self.root=Path(root);self.folder=Path(scratch).resolve();self.done=False;self.blend=None;self.repose=False
    def prepare(self):
        if not self.done:
            request={'action':'render','scene':description(self.scene,self.root),'output':str(self.folder)}
            if self.blend:
                request.update(action='render-blend',blend=str(self.blend))
                if self.repose:request['repose']=True
            invoke(request,self.folder)
            self.done=True
    def rgb(self,camera):
        from PIL import Image
        self.prepare();return np.asarray(Image.open(self.folder/(camera+'.png')).convert('RGB'))
    def mask(self,camera,obj):
        self.prepare();return np.load(self.folder/(camera+'__'+obj+'.npy'),allow_pickle=False)
    def close(self): pass
    def __enter__(self): return self
    def __exit__(self,*args): self.close()


def workspace(candidate, action='build', script=None):
    from .project import exclusive
    with exclusive(candidate.project):
        candidate.require_open(); folder=candidate.root/'blender';blend=candidate.root/'candidate.blend'
        request={'action':action,'output':str(folder),'blend':str(blend)}
        if action=='build':
            request['scene']=description(candidate.scene,candidate.project.root)
        else:
            record=read(folder/'canonical_signature.json')
            if record!=candidate.project.signature(candidate.scene): raise ValueError('Canonical changed since Blender build; rebuild workspace')
            if not blend.is_file(): raise ValueError('Build the Blender workspace first')
        if action=='author':
            if script is None or not Path(script).is_file(): raise ValueError('Author requires a bpy script path')
            request['script']=str(Path(script).resolve())
        result=invoke(request,folder)
        if action=='build':
            write(folder/'canonical_signature.json',candidate.project.signature(candidate.scene))
        if action in ('build','author'):
            write(folder/'authored.json',{'blend_sha256':sha(blend),'action':action})
        if action=='sync':
            synchronize(candidate,result)
            write(folder/'canonical_signature.json',candidate.project.signature(candidate.scene))
            write(folder/'sync.json',{'blend_sha256':sha(blend),'input_signature':candidate.project.signature(candidate.scene)})
        return result


def synchronize(candidate, result):
    """Explicit visual sync; preserve collision and protected measured/calibrated values."""
    scene=copy.deepcopy(candidate.scene);p=candidate.project
    original={o['id']:o for o in scene['objects']}
    if set(original)-{o['id'] for o in result['objects']}: raise ValueError('Remove canonical objects explicitly through edit, not implicit Blender deletion')
    def import_asset(path,kind):
        path=Path(path).resolve()
        if not path.is_relative_to(candidate.root): raise ValueError('Blender asset escapes candidate workspace')
        digest=sha(path);key='asset_'+digest[:16]
        scene['assets'][key]={'path':path.relative_to(p.root).as_posix(),'sha256':digest,'source':'blender_reconstruction','category':kind}
        return key
    def update(node,key,data):
        old=node.get(key)
        if old is not None and old.get('value') is not None and np.allclose(old['value'],data,atol=1e-6,rtol=1e-6): return
        node[key]=value(data,'estimated',['explicit Blender visual reconstruction synchronization'])
    for row in result['objects']:
        obj=next((o for o in scene['objects'] if o['id']==row['id']),None)
        if obj is None:
            obj={'id':row['id'],'role':row['role'],'frame':'world','pose':value(None),'dimensions':value(None),
                 'color':value(None),'visual':{'type':'unknown'},'collision':{'type':'unknown'},
                 'physics':{'mass_kg':value(None),'friction':value(None)}}
            scene['objects'].append(obj)
        old=copy.deepcopy(obj)
        update(obj,'pose',(np.linalg.inv(frame_world(scene,obj['frame']))@np.asarray(row['pose'])).tolist())
        update(obj,'dimensions',row['dimensions']);update(obj,'color',row['color'])
        obj['role']=row['role'];obj['visual']={'type':'mesh','asset':import_asset(row['mesh'],'visual'),
                                           'scale':[1,1,1],'source':'blender_reconstruction','provenance':'estimated'}
        if row.get('texture'):obj['visual']['texture']=import_asset(row['texture'],'textures')
        material=obj.setdefault('material',{})
        for key in ('roughness','metallic'):update(material,key,row[key])
        preserve(old,obj,obj['id'])
    for row in result['cameras']:
        c=next((c for c in scene['cameras'] if c['id']==row['id']),None)
        if c is None:
            c={'id':row['id'],'frame':'world','pose':value(None),'K':value(None),'distortion':value([0.]*5,'estimated'),'resolution':row['resolution']}
            scene['cameras'].append(c)
        old=copy.deepcopy(c)
        update(c,'pose',(np.linalg.inv(frame_world(scene,c['frame']))@np.asarray(row['pose'])).tolist())
        update(c,'K',row['K']);c['resolution']=row['resolution'];preserve(old,c,c['id'])
    if 'ambient' in result:
        old=copy.deepcopy(scene['lights']);update(scene['lights'],'ambient',result['ambient'])
        scene['lights']['sources']=[]
        for row in result.get('lights',[]):
            node=next((copy.deepcopy(x) for x in old.get('sources',[]) if x['id']==row['id']),{'id':row['id'],'type':row['type']})
            before=copy.deepcopy(node)
            for key in ('pose','energy','color','size'):update(node,key,row[key])
            preserve(before,node,'light.'+row['id']);scene['lights']['sources'].append(node)
        preserve(old,scene['lights'],'lights')
    candidate.save(scene)
