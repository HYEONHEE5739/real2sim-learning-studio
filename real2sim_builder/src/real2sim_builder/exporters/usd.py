# Algorithms ported from the original Builder; source SHA/AST in BU evidence.
# Official formats: https://mujoco.readthedocs.io/en/3.3.7/XMLreference.html
# https://openusd.org/release/api/class_usd_geom_camera.html
"""Portable USDA syntax in scene.usd, directly from the same canonical geometry."""
import json
import os
from pathlib import Path
import numpy as np
from real2sim_builder.scene import validate, world_pose, local_path
from ..calibration.geometry import parts,mesh_data
from real2sim_builder.cameras import CLIP


def tuple_string(x):return '('+', '.join(format(float(v),'.12g') for v in x)+')'
def matrix(t):return '('+', '.join(tuple_string(row) for row in t.T)+')'


def export(scene,root,path):
    validate(scene,root,complete=True);lines=['#usda 1.0','(\n    defaultPrim = "Scene"\n    metersPerUnit = 1\n    upAxis = "Z"\n)','def Xform "Scene" {']
    lines.append('  custom string canonical_frames = '+json.dumps(json.dumps(scene['frames'],sort_keys=True)))
    def xform(t,indent='    '):
        lines.extend([indent+'matrix4d xformOp:transform = '+matrix(t),indent+'uniform token[] xformOpOrder = ["xformOp:transform"]'])
    for obj in scene['objects']:
        material='/Scene/material_'+obj['id']
        friction=obj['physics']['friction']['value']
        mat_api=' (prepend apiSchemas = ["PhysicsMaterialAPI"])' if friction is not None else ''
        lines.append('  def Material '+json.dumps('material_'+obj['id'])+mat_api+' {')
        if friction is not None:lines.extend(['    float physics:staticFriction = '+str(friction),'    float physics:dynamicFriction = '+str(friction)])
        texture=obj['visual'].get('texture')
        lines.extend(['    token outputs:surface.connect = <'+material+'/Surface.outputs:surface>',
            '    def Shader "Surface" {','      uniform token info:id = "UsdPreviewSurface"',
            '      color3f inputs:diffuseColor = '+tuple_string(obj['color']['value'] or [.5]*3),
            '      float inputs:roughness = '+str(obj.get('material',{}).get('roughness',{}).get('value',.6)), '      float inputs:metallic = '+str(obj.get('material',{}).get('metallic',{}).get('value',0.)),'      token outputs:surface'])
        if texture:
            lines.append('      color3f inputs:diffuseColor.connect = <'+material+'/Image.outputs:rgb>')
        lines.append('    }')
        if texture:
            relative=os.path.relpath(local_path(root,scene['assets'][texture]['path']),Path(path).parent)
            lines.extend(['    def Shader "Image" {','      uniform token info:id = "UsdUVTexture"',
                '      asset inputs:file = @'+relative+'@','      token inputs:sourceColorSpace = "sRGB"',
                '      float2 inputs:st.connect = <'+material+'/UV.outputs:result>','      float3 outputs:rgb','    }',
                '    def Shader "UV" {','      uniform token info:id = "UsdPrimvarReader_float2"',
                '      token inputs:varname = "st"','      float2 outputs:result','    }'])
        lines.append('  }')
        mass=obj['physics']['mass_kg']['value'];dynamic=obj['role']=='manipulable_object' and mass is not None and mass>0
        api=' (prepend apiSchemas = ["PhysicsRigidBodyAPI", "PhysicsMassAPI"])' if dynamic else ''
        lines.append('  def Xform '+json.dumps(obj['id'])+api+' {');xform(world_pose(scene,obj))
        lines.append('    custom string semantic_role = '+json.dumps(obj['role']))
        if dynamic:lines.extend(['    bool physics:rigidBodyEnabled = true','    float physics:mass = '+str(mass)])
        for field in ('visual','collision'):
            for i,part in enumerate(parts(obj,field)):
                kind=part['type'];dtype={'box':'Cube','sphere':'Sphere','cylinder':'Cylinder','mesh':'Mesh'}[kind]
                api=' (prepend apiSchemas = ["PhysicsCollisionAPI", "MaterialBindingAPI"])' if field=='collision' else ' (prepend apiSchemas = ["MaterialBindingAPI"])'
                lines.append('    def '+dtype+' '+json.dumps(field+'_'+str(i))+api+' {')
                t=part['pose'].copy();dims=part['dimensions']
                if kind=='box':t[:3,:3]=t[:3,:3]@np.diag(dims/2)
                xform(t,'      ')
                if kind=='box':lines.append('      double size = 2')
                elif kind=='sphere':lines.append('      double radius = '+str(dims[0]/2))
                elif kind=='cylinder':lines.extend(['      double radius = '+str(dims[0]/2),'      double height = '+str(dims[2]),'      uniform token axis = "Z"'])
                elif kind=='mesh':
                    vertices,faces=mesh_data(local_path(root,scene['assets'][part['asset']]['path']))
                    vertices=vertices*np.asarray(part.get('scale',[1,1,1]))
                    lines.extend(['      point3f[] points = ['+', '.join(tuple_string(v) for v in vertices)+']',
                        '      int[] faceVertexCounts = ['+', '.join('3' for _ in faces)+']',
                        '      int[] faceVertexIndices = ['+', '.join(str(int(v)) for v in faces.ravel())+']',
                        '      uniform token subdivisionScheme = "none"'])
                    if texture:
                        axes=np.argsort(np.ptp(vertices,axis=0))[-2:]
                        st=(vertices[:,axes]-vertices[:,axes].min(0))/np.maximum(np.ptp(vertices[:,axes],axis=0),1e-9)
                        if local_path(root,scene['assets'][part['asset']]['path']).suffix.lower()=='.obj':
                            from ..calibration.geometry import obj_data
                            _,_,st=obj_data(local_path(root,scene['assets'][part['asset']]['path']))
                        lines.append('      texCoord2f[] primvars:st = ['+', '.join(tuple_string(v) for v in st)+'] (interpolation = "vertex")')
                lines.append('      rel material:binding'+(':physics' if field=='collision' else '')+' = <'+material+'>')
                if field=='visual':lines.append('      color3f[] primvars:displayColor = ['+tuple_string(obj['color']['value'] or [.5]*3)+']')
                else:lines.extend(['      token visibility = "invisible"','      bool physics:collisionEnabled = true'])
                lines.append('    }')
        lines.append('  }')
    from real2sim_builder.cameras import OPTICAL_TO_RENDER
    conversion=OPTICAL_TO_RENDER
    for camera in scene['cameras']:
        k=np.asarray(camera['K']['value']);w,h=camera['resolution'];focal=10.
        lines.append('  def Camera '+json.dumps(camera['id'])+' {');xform(world_pose(scene,camera)@conversion)
        lines.extend(['    float focalLength = '+str(focal),'    float horizontalAperture = '+str(w/k[0,0]*focal),
            '    float verticalAperture = '+str(h/k[1,1]*focal),
            '    float horizontalApertureOffset = '+str((w/2-k[0,2])/k[0,0]*focal),
            '    float verticalApertureOffset = '+str((k[1,2]-h/2)/k[1,1]*focal),
            '    float2 clippingRange = '+tuple_string(CLIP),'  }'])
    for light in scene['lights'].get('sources',[]):
        kind={'point':'SphereLight','area':'RectLight','sun':'DistantLight'}[light['type']]
        lines.append('  def '+kind+' '+json.dumps('light_'+light['id'])+' {');xform(np.asarray(light['pose']['value']))
        lines.extend(['    float inputs:intensity = '+str(light['energy']['value']), '    color3f inputs:color = '+tuple_string(light['color']['value'])])
        if kind=='RectLight':lines.extend(['    float inputs:width = '+str(light['size']['value']), '    float inputs:height = '+str(light['size']['value'])])
        lines.append('  }')
    lines.extend(['  def DistantLight "KeyLight" {','    float inputs:intensity = 1000','  }','}'])
    Path(path).write_text('\n'.join(lines)+'\n')
    return {o['id']:'/Scene/'+o['id'] for o in scene['objects']}
