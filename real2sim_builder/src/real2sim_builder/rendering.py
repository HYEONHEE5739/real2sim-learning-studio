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
        for index,part in enumerate(row['parts']):
            mat = _blender_material({**row,**{k:part[k]for k in('color','roughness','metallic','texture')if k in part},'id':row['id']+'_'+str(index)})
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

def _blender_object_views(objects,folder):
    """Real four-view CPU renders of the just-authored visual, not evidence placeholders."""
    scene=bpy.context.scene;bpy.context.view_layer.update()
    visual=[]
    for obj in objects:
        parent=obj;collision=False
        while parent:
            collision=collision or bool(parent.get('r2s_collision'));parent=parent.parent
        if obj.type=='MESH'and not collision:visual.append(obj)
    if not visual:raise ValueError('No visual mesh for modeling evidence')
    corners=[obj.matrix_world@Vector(corner)for obj in visual for corner in obj.bound_box]
    low=Vector([min(v[i]for v in corners)for i in range(3)]);high=Vector([max(v[i]for v in corners)for i in range(3)])
    center=(low+high)/2;span=max(max(high-low),.001)
    hidden={obj:obj.hide_render for obj in scene.objects}
    for obj in scene.objects:obj.hide_render=obj not in visual
    camera_data=bpy.data.cameras.new('EvidenceCamera');camera=bpy.data.objects.new('EvidenceCamera',camera_data);scene.collection.objects.link(camera)
    camera_data.type='ORTHO';camera_data.ortho_scale=span*1.6;camera_data.clip_start=span*.001;camera_data.clip_end=span*100;scene.camera=camera
    light_data=bpy.data.lights.new('EvidenceLight','AREA');light=bpy.data.objects.new('EvidenceLight',light_data);scene.collection.objects.link(light)
    light.location=center+Vector((3,-3,5))*span;light.rotation_euler=(center-light.location).to_track_quat('-Z','Y').to_euler();light_data.energy=100;light_data.size=span*4
    scene.render.engine='CYCLES';scene.cycles.device='CPU';scene.cycles.samples=8;scene.cycles.seed=0
    scene.render.resolution_x=320;scene.render.resolution_y=320;scene.render.resolution_percentage=100
    scene.render.image_settings.file_format='PNG';scene.render.image_settings.color_mode='RGB';scene.view_settings.view_transform='Standard'
    scene.world=bpy.data.worlds.new('EvidenceWorld');scene.world.use_nodes=True;scene.world.node_tree.nodes.get('Background').inputs['Color'].default_value=(.3,.3,.3,1)
    views={}
    for name,axis in {'front':(0,-1,.1),'side':(1,0,.1),'top':(0,0,1),'isometric':(1,-1,1)}.items():
        camera.location=center+Vector(axis).normalized()*span*3;camera.rotation_euler=(center-camera.location).to_track_quat('-Z','Y').to_euler()
        path=folder/(name+'.png');scene.render.filepath=str(path);bpy.ops.render.render(write_still=True);views[name]=str(path)
    bpy.data.objects.remove(camera,do_unlink=True);bpy.data.objects.remove(light,do_unlink=True)
    for obj,state in hidden.items():obj.hide_render=state
    return views


def _blender_main():
    request = json.loads(Path(sys.argv[sys.argv.index('--blender-worker') + 1]).read_text())
    folder = Path(request['output'])
    folder.mkdir(parents=True, exist_ok=True)
    action = request['action']
    if action=='object-author':
        bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
        runpy.run_path(request['script'],run_name='__main__')
        # Distinct data names retain each Object Xform and its custom properties
        # even when Blender default Cube/Cube.001 names would otherwise collapse.
        for obj in bpy.context.scene.objects:
            if obj.type=='MESH':obj.data.name=obj.name+'_Geometry'
            parent=obj;collision=False
            while parent:
                collision=collision or bool(parent.get('r2s_collision'));parent=parent.parent
            if collision:
                obj.hide_render=False;obj.hide_viewport=False;obj.hide_set(False)
        bpy.context.scene.unit_settings.system='METRIC';bpy.context.scene.unit_settings.scale_length=1
        bpy.ops.file.pack_all();bpy.ops.wm.save_as_mainfile(filepath=str(folder/'source.blend'))
        outputs=[]
        for name in request['object_ids']:
            roots=[o for o in bpy.context.scene.objects if o.get('r2s_id')==name and not o.parent]
            if len(roots)!=1:raise ValueError('One root with r2s_id per requested object is required: '+name)
            root=roots[0];objects=[root,*root.children_recursive];inverse=root.matrix_world.inverted()
            saved={o:o.matrix_world.copy()for o in objects}
            bpy.ops.object.select_all(action='DESELECT')
            for obj in objects:obj.select_set(True)
            # Freeze poses before mutating a parent; preserve object-local shape.
            for obj in objects:obj.matrix_world=inverse@saved[obj]
            target=folder/name;target.mkdir(exist_ok=True)
            options={'filepath':str(target/(name+'.usda')),'selected_objects_only':True,'export_animation':False,
                'export_uvmaps':True,'export_materials':True,'relative_paths':True,'root_prim_path':'/Object',
                'export_cameras':False,'export_lights':False,'export_custom_properties':True}
            supported=bpy.ops.wm.usd_export.get_rna_type().properties
            if 'export_textures_mode'in supported:options['export_textures_mode']='NEW'
            elif 'export_textures'in supported:options['export_textures']=True
            if 'convert_scene_units'in supported:options.update(convert_scene_units='METERS',meters_per_unit=1.)
            bpy.ops.wm.usd_export(**options)
            views=_blender_object_views(objects,target)
            for obj in objects:obj.matrix_world=saved[obj]
            outputs.append({'id':name,'usda':str(target/(name+'.usda')),'previews':views})
        (folder/'result.json').write_text(json.dumps({'status':'OK','objects':outputs,'blend':str(folder/'source.blend')}))
        return
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


def render_scene(scene):
    """Omit unresolved cameras only from the transient render description.

    An uninitialized sensor must not block registered photo renders. Original
    Candidate cameras and all object/geometry completeness checks remain intact.
    """
    import copy
    result=copy.deepcopy(scene)
    from .scene import value
    for camera in result['cameras']:
        if camera['pose']['value']is None:
            binding=next((r for r in result.get('view_registrations',{}).values()if r.get('camera')==camera['id']and r.get('T_world_camera')is not None and r['status']in('REGISTERED_ESTIMATED','REGISTERED_CALIBRATED')),None)
            if binding:camera.update(frame='world',pose=value(binding['T_world_camera'],'estimated',['transient external Virtual Camera; actual per-view registration overrides it']))
    result['cameras']=[c for c in result['cameras']if all(c[k]['value']is not None for k in('K','pose','distortion'))]
    return result


class Renderer:
    def __init__(self,scene,root,scratch,mode='software-egl'):
        from .exporters.mjcf import export
        scene=render_scene(scene)
        self.mode=mode
        configure(mode)
        import mujoco
        self.mj=mujoco;self.scene=scene;self.camera_views={c['id']:c for c in scene['cameras']};self.renderers={};self.resolutions={c['id']:c['resolution']for c in scene['cameras']}
        scratch=Path(scratch);scratch.mkdir(parents=True,exist_ok=True)
        self.root=root;self.scratch=scratch
        from .cameras import pinhole_scene
        export(pinhole_scene(scene),root,scratch/'scene.xml')
        self.model=mujoco.MjModel.from_xml_path(str(scratch/'scene.xml'));self.data=mujoco.MjData(self.model)
        mujoco.mj_forward(self.model,self.data)

    def update_scene(self,scene):
        """Update one posed observation; asset geometry/units remain compiled."""
        from .cameras import OPTICAL_TO_RENDER
        from .scene import world_pose
        from scipy.spatial.transform import Rotation
        from .calibration.geometry import parts
        from .exporters.mjcf import material_parameters
        scene=render_scene(scene)
        if scene['assets']!=self.scene['assets']:raise ValueError('Renderer geometry changed; recompile explicitly')
        resized=False
        for obj in scene['objects']:
            old=next(o for o in self.scene['objects']if o['id']==obj['id'])
            if any(obj[k]!=old[k]for k in('visual','collision')):raise ValueError('Renderer geometry changed; recompile explicitly')
            if obj['dimensions']['value']!=old['dimensions']['value']:
                from .calibration.geometry import dimension_axes
                axes={i for group in dimension_axes(old) for i in group}
                if not axes or any(obj['dimensions']['value'][i]!=old['dimensions']['value'][i] for i in range(3) if i not in axes):
                    raise ValueError('Renderer dimensions are protected or require a new Asset Version')
                resized=True
        if resized:
            # Compile the candidate geometry before replacing the live native model.
            # This refreshes bounding volumes/inertias too; no stale collision bounds.
            replacement=Renderer(scene,self.root,self.scratch,self.mode)
            self.close();self.__dict__.update(replacement.__dict__)
        for obj in scene['objects']:
            self._body_pose(obj['id'],world_pose(scene,obj))
            for index,part in enumerate(parts(obj,'visual')):
                gid=self.mj.mj_name2id(self.model,self.mj.mjtObj.mjOBJ_GEOM,obj['id']+'_visual_'+str(index))
                self.model.geom_rgba[gid,:3]=part.get('color',obj['color']['value']or[.5]*3)
                mid=self.model.geom_matid[gid]
                if obj.get('material')or 'roughness'in part or 'metallic'in part:
                    if mid<0:raise ValueError('Renderer material changed structurally; recompile explicitly')
                    for key,val in material_parameters(obj,part).items():getattr(self.model,'mat_'+key)[mid]=val
        self.model.vis.headlight.ambient[:]=scene['lights']['ambient']['value']
        for light in scene['lights'].get('sources',[]):
            lid=self.mj.mj_name2id(self.model,self.mj.mjtObj.mjOBJ_LIGHT,'light_'+light['id'])
            if lid<0:raise ValueError('Renderer light changed structurally; recompile explicitly')
            pose=np.asarray(light['pose']['value']);self.model.light_pos[lid]=pose[:3,3];self.model.light_dir[lid]=-pose[:3,2]
            self.model.light_diffuse[lid]=np.asarray(light['color']['value'])*float(light['energy']['value'])/1000
        for camera in scene['cameras']:
            cid=self.mj.mj_name2id(self.model,self.mj.mjtObj.mjOBJ_CAMERA,camera['id'])
            pose=world_pose(scene,camera)@OPTICAL_TO_RENDER;q=Rotation.from_matrix(pose[:3,:3]).as_quat()
            self.model.cam_pos[cid]=pose[:3,3];self.model.cam_quat[cid]=np.r_[q[3],q[:3]]
            k=np.asarray(camera['K']['value']);w,h=camera['resolution']
            if self.resolutions[camera['id']]!=[w,h]and camera['id']in self.renderers:self.renderers.pop(camera['id']).close()
            self.resolutions[camera['id']]=[w,h];self.model.cam_resolution[cid]=[w,h];self.model.cam_sensorsize[cid]=[w,h]
            self.model.vis.global_.offwidth=max(self.model.vis.global_.offwidth,w);self.model.vis.global_.offheight=max(self.model.vis.global_.offheight,h)
            self.model.cam_intrinsic[cid]=[k[0,0],k[1,1],w/2-k[0,2],k[1,2]-h/2]
        self.camera_views={c['id']:c for c in scene['cameras']}
        self.mj.mj_forward(self.model,self.data)

    def _body_pose(self,name,pose):
        from .scene import transform
        from scipy.spatial.transform import Rotation
        pose=transform(pose);body=self.mj.mj_name2id(self.model,self.mj.mjtObj.mjOBJ_BODY,name)
        if body<0 or self.model.body_parentid[body]!=0:raise ValueError('Static fitting requires a World-root object body')
        q=Rotation.from_matrix(pose[:3,:3]).as_quat();q=np.r_[q[3],q[:3]]
        joint=self.model.body_jntadr[body]
        if joint>=0 and self.model.jnt_type[joint]==self.mj.mjtJoint.mjJNT_FREE:
            address=self.model.jnt_qposadr[joint];self.data.qpos[address:address+7]=np.r_[pose[:3,3],q]
        else:self.model.body_pos[body]=pose[:3,3];self.model.body_quat[body]=q

    def set_object_pose(self,name,pose):
        """Move a World-root object for static mask refinement, without a step.

        Geometry, cameras, frames and robot kinematics stay compiled and fixed.
        This renderer-local operation never writes a Candidate or input file.
        """
        obj=next(o for o in self.scene['objects']if o['id']==name)
        if obj.get('link')or obj['role']=='reference_robot':raise ValueError('Robot pose is locked during object fitting')
        self._body_pose(name,pose);self.mj.mj_forward(self.model,self.data)

    def depth(self,camera):
        """Native optical-Z depth in Scene metres, with no physics step."""
        if camera not in self.renderers:self.rgb(camera)
        renderer=self.renderers[camera];renderer.enable_depth_rendering()
        try:
            renderer.update_scene(self.data,camera=camera)
            from .cameras import distort_render
            return distort_render(self.camera_views[camera],renderer.render().copy(),nearest=True)
        finally:renderer.disable_depth_rendering()

    def rgb(self,camera):
        w,h=self.resolutions[camera]
        if camera not in self.renderers:self.renderers[camera]=self.mj.Renderer(self.model,height=h,width=w)
        renderer=self.renderers[camera];renderer.update_scene(self.data,camera=camera)
        rgb=renderer.render().copy()
        linear=rgb.astype(float)/255.;display=np.where(linear<=.0031308,12.92*linear,1.055*linear**(1/2.4)-.055)
        from .cameras import distort_render
        return distort_render(self.camera_views[camera],np.rint(np.clip(display,0,1)*255).astype(np.uint8))

    def mask(self,camera,obj):
        if camera not in self.renderers:self.rgb(camera)
        renderer=self.renderers[camera];renderer.enable_segmentation_rendering()
        try:
            renderer.update_scene(self.data,camera=camera);seg=renderer.render()
            body=self.mj.mj_name2id(self.model,self.mj.mjtObj.mjOBJ_BODY,obj)
            if body<0:raise ValueError('Unknown silhouette object')
            result=np.zeros(seg.shape[:2],bool)
            for gid in np.where(self.model.geom_bodyid==body)[0]:result|=(seg[:,:,0]==gid)&(seg[:,:,1]==int(self.mj.mjtObj.mjOBJ_GEOM))
            from .cameras import distort_render
            return distort_render(self.camera_views[camera],result,nearest=True)
        finally:renderer.disable_segmentation_rendering()

    def close(self):
        for r in self.renderers.values():r.close()
        self.renderers.clear()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


from contextlib import contextmanager

@contextmanager
def for_observation(project,scene,image,default,folder):
    if not image.get('session_id')and image.get('id')not in scene.get('view_registrations',{}):
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


def capability(*, environment=None):
    requested=os.environ.get('REAL2SIM_BLENDER','blender')
    executable=shutil.which(requested)
    if not executable: return {'available':False,'reason':'Blender executable not found; set REAL2SIM_BLENDER to an existing executable','requested':requested}
    try:
        result=subprocess.run([executable,'--version'],capture_output=True,text=True,timeout=15,env=worker_environment()if environment is None else environment)
        if result.returncode: raise RuntimeError(result.stderr)
        return {'available':True,'executable':executable,'version':result.stdout.splitlines()[0]}
    except (OSError,subprocess.SubprocessError,RuntimeError) as exc:
        return {'available':False,'reason':str(exc),'requested':requested}


def object_worker_environment():
    """No inherited credentials, Python hooks, loader injection or user config."""
    return {'PATH':'/usr/bin:/bin','HOME':'/nonexistent','LANG':'C.UTF-8','LC_ALL':'C.UTF-8',
        'TMPDIR':'/tmp','XDG_CACHE_HOME':'/tmp/cache','XDG_CONFIG_HOME':'/tmp/config',
        'PYTHONNOUSERSITE':'1','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2'}


def object_sandbox(executable,folder):
    """Empty root, installed Blender resources/system libraries, one owned job.

    Discover the trusted installation before running generated code. No host
    home, project, authentication directories, executable search tree or GPU
    devices are mounted. A missing runtime fails closed, without a root bind.
    """
    import re
    sandbox=shutil.which('bwrap')
    if not sandbox:raise Unavailable('Object authoring requires installed bwrap')
    executable=Path(executable).resolve();folder=Path(folder).resolve()
    environment=object_worker_environment()
    probe=subprocess.run([str(executable),'--background','-noaudio','--factory-startup','--python-expr',
        'import bpy,json;print("R2S_RESOURCE="+json.dumps((bpy.utils.resource_path("SYSTEM") or bpy.utils.resource_path("LOCAL"))))'],
        capture_output=True,text=True,timeout=30,env=environment,check=True)
    found=re.search(r'^R2S_RESOURCE=(.+)$',probe.stdout,re.MULTILINE)
    if not found:raise Unavailable('Cannot discover installed Blender resources for isolated authoring')
    resource=json.loads(found.group(1))
    if not resource or not Path(resource).is_absolute():raise Unavailable('Invalid Blender runtime resource path')
    resources=Path(resource).resolve()
    if not resources.is_dir()or not(resources/'scripts').is_dir()or resources in(Path('/'),Path.home())or Path(__file__).resolve().is_relative_to(resources):
        raise Unavailable('Blender system resource directory missing or unsafe')
    dependencies=subprocess.run(['ldd',str(executable)],capture_output=True,text=True,timeout=15,check=True,env=environment)
    libraries=re.findall(r'(?:=>\s*|^\s*)(/[^\s]+)',dependencies.stdout,re.MULTILINE)
    if not libraries or 'not found'in dependencies.stdout:raise Unavailable('Blender runtime dependencies unresolved')
    mounts={str(executable):executable,str(resources):resources,str(Path(__file__).resolve()):Path(__file__).resolve()}
    for library in libraries:
        path=Path(library)
        if not path.is_file():raise Unavailable('Blender dependency missing: '+str(path))
        if 'ld-linux'in path.name:mounts[str(path)]=path.resolve()
        else:
            if path.parent in(Path('/'),Path.home()):raise Unavailable('Unsafe Blender dependency directory')
            mounts[str(path.parent)]=path.parent.resolve()
    # Optional system font/cache configuration only, never the user's config.
    for path in('/usr/share/fonts','/etc/fonts','/etc/ld.so.cache','/etc/localtime'):
        if Path(path).exists():mounts[path]=Path(path).resolve()
    command=[sandbox,'--tmpfs','/','--dev','/dev','--proc','/proc','--tmpfs','/tmp',
        '--unshare-net','--unshare-pid','--die-with-parent','--new-session']
    for target,source in sorted(mounts.items(),key=lambda item:len(item[0])):
        command.extend(['--ro-bind',str(source),target])
    command.extend(['--bind',str(folder),str(folder)])
    for name in('inputs','author.py'):
        path=folder/name
        if path.exists():command.extend(['--ro-bind',str(path),str(path)])
    command.extend(['--chdir',str(folder)])
    return command,environment


def invoke(request, folder, *, checkpoint=None, timeout_s=600):
    available=capability(environment=object_worker_environment())if request.get('sandbox')else capability()
    if not available['available']: raise Unavailable(available['reason'])
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    write(folder/'request.json',request)
    command=[available['executable'],'--background','-noaudio','--factory-startup','--python-exit-code','1',
             '--python',str(Path(__file__).resolve()),'--','--blender-worker',str(folder/'request.json')]
    environment=worker_environment()
    if request.get('sandbox'):
        prefix,environment=object_sandbox(available['executable'],folder)
        command=[*prefix,*command]
    with (folder/'blender.log').open('w') as stream:
        import signal,time
        child=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,env=environment,start_new_session=True)
        started=time.monotonic()
        try:
            while child.poll()is None:
                if checkpoint:checkpoint()
                if time.monotonic()-started>timeout_s:raise TimeoutError('Blender worker timeout')
                time.sleep(.1)
            if child.returncode:raise subprocess.CalledProcessError(child.returncode,command)
        finally:
            if child.poll()is None:
                os.killpg(child.pid,signal.SIGTERM)
                try:child.wait(timeout=3)
                except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
    return read(folder/'result.json')


def description(scene, root):
    validate(scene,root);objects=[]
    for obj in scene['objects']:
        pieces=[]
        for part in parts(obj,'visual'):
            row={k:(v.tolist() if isinstance(v,np.ndarray) else v) for k,v in part.items()}
            if row.get('texture'):row['texture']=str(local_path(root,scene['assets'][row['texture']]['path']))
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


def author_object_assets(candidate,script,object_ids,measurements=None,*,request_ids=None,on_registered=None):
    """Run the existing Blender worker for selected new assets only.

    The bpy script is authored by Codex, not generated from dimensions. Existing
    Scene objects and prior Blender workspaces remain byte-identical.
    """
    from .object_assets import register_object_asset
    from .candidate import exclusive
    from .scene import identifier
    from pxr import Usd,UsdGeom,UsdPhysics
    from scene_contract.naming import numbered_path
    import uuid
    names=[identifier(n)for n in object_ids]
    if not names or len(set(names))!=len(names):raise ValueError('Unique object IDs required')
    script=Path(script).resolve()
    if not script.is_file():raise FileNotFoundError(script)
    with exclusive(candidate.project):
        candidate.require_open();folder=numbered_path(candidate.root/'blender/objects','build')
        folder.mkdir(parents=True);owned=folder/'author.py';shutil.copyfile(script,owned)
        task=script.parent/'tasks.json'
        if task.is_file():
            if task.is_symlink()or not isinstance(read(task),dict):raise ValueError('Owned modeling tasks must be a JSON mapping')
            shutil.copyfile(task,folder/'tasks.json')
        if(script.parent/'inputs').is_dir():
            if (script.parent/'inputs').is_symlink()or any(p.is_symlink()for p in(script.parent/'inputs').rglob('*')):
                raise ValueError('Object authoring inputs may not contain symlinks')
            shutil.copytree(script.parent/'inputs',folder/'inputs')
        result=invoke({'action':'object-author','script':str(owned),'object_ids':names,'output':str(folder),'sandbox':True},folder,checkpoint=candidate.project.checkpoint)
        records=[]
        for row in result['objects']:
            path=Path(row['usda']);stage=Usd.Stage.Open(str(path))
            if not stage:raise ValueError('Blender did not produce readable USDA')
            UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z')
            for prim in stage.Traverse():
                parent=prim;collision=False
                while parent and not parent.IsPseudoRoot():
                    collision=collision or bool(parent.GetAttribute('userProperties:r2s_collision').Get());parent=parent.GetParent()
                if collision and prim.IsA(UsdGeom.Mesh):
                    UsdPhysics.CollisionAPI.Apply(prim).CreateCollisionEnabledAttr(True)
                    UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr('convexHull')
                    UsdGeom.Imageable(prim).CreateVisibilityAttr('invisible')
            stage.GetRootLayer().Save()
            records.append(register_object_asset(candidate.project,path,asset_id=row['id'],
                dimensions=(measurements or{}).get(row['id']),blend=result['blend'],generation_id=(request_ids or{}).get(row['id'])))
            write(folder/'registered.json',records)
            if on_registered:on_registered(records[-1])
        write(folder/'registered.json',records)
        return {'status':'REGISTERED_UNVALIDATED','assets':records,'build':str(folder),
            'authored_usda':{r['id']:r['usda']for r in result['objects']},
            'previews':{r['id']:r.get('previews',{})for r in result['objects']},'physical_verified':False}
