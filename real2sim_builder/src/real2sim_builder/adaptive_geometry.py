"""Choose geometry from structured constraints and retained original observations."""
from pathlib import Path

import numpy as np

from .files import read, sha
from .scene import local_path
from .object_assets import dimensions_match, verify_object_asset

POLICY = 'geometry-build-plan/1'
DIRECT = {'primitive', 'parametric', 'existing_asset'}


def build_plan(project, obj, spec, observation, sources):
    geometry = spec.get('geometry') or {}
    kind = geometry.get('kind', 'mesh')
    dims = geometry.get('dimensions_m') or [None]*3
    complete = len(dims)==3 and all(type(v) in (int,float) and np.isfinite(v) and v>0 for v in dims)
    with np.load(observation) as arrays:
        mask = arrays['mask'].astype(bool)
        clean = mask & (arrays['rgb_source']==0) & (arrays['depth_source']==0) & ~arrays['low_confidence'].astype(bool)
        points = arrays['camera_points'][clean[mask]]
        points = points[np.isfinite(points).all(axis=1)]
        color = np.median(arrays['image'][clean],axis=0)/255 if clean.any() else None
    route, reason = 'reconstructed_mesh', 'Detailed surface or incomplete primitive constraints'
    measured = geometry.get('provenance') in ('measured','calibrated') and bool(geometry.get('evidence'))
    manifest = spec.get('asset_manifest')
    if len(points)<10 or np.linalg.matrix_rank(points-points.mean(axis=0))<2:
        route, reason = 'needs_review','Insufficient original surface samples'
    elif manifest and spec.get('modeling_action')!='new':
        record = verify_object_asset(project,read(local_path(project.root,manifest)))
        if (spec.get('asset_group_relation') or {}).get('status') in ('AMBIGUOUS','UNRESOLVED') or any(
                r.get('status')=='AMBIGUOUS' for r in spec.get('model_references',[])):
            route, reason='needs_review','Asset identity is ambiguous'
        elif not dimensions_match(dims,record['dimensions']['value']):
            route, reason = 'needs_review','Selected asset dimensions conflict with object constraints'
        else:
            route, reason = 'existing_asset','Explicit immutable asset selection'
            sources={**sources,'asset_manifest_sha256':sha(local_path(project.root,manifest))}
    elif measured and complete and kind in ('box','sphere','cylinder','container'):
        if ((kind in ('cylinder','sphere') and not np.isclose(dims[0],dims[1]))
                or (kind=='sphere' and not np.isclose(dims[0],dims[2]))):
            route, reason = 'needs_review','Declared dimensions contradict radial symmetry'
        elif obj['role']=='receptacle' and kind!='container':
            route, reason = 'needs_review','Solid primitive cannot represent an open receptacle'
        elif kind=='container':
            wall=geometry.get('wall_m');bottom=geometry.get('bottom_diameter_m')
            if (geometry.get('round') is True and np.isclose(dims[0],dims[1])
                    and type(wall) in (float,int) and type(bottom) in (float,int)
                    and 0<bottom<=dims[0] and 0<wall<min(bottom/2,dims[2])):
                route, reason = 'parametric','Bound rim, base, height and wall dimensions'
        else:
            route, reason = 'primitive','Complete dimension constraints and observed surface'
        # An observed axis span is a lower bound on the object's 3D diameter.
        if np.max(np.ptp(points,axis=0)) > np.linalg.norm(dims):
            route, reason = 'needs_review','Observed optical-depth extent exceeds declared bounding diagonal'
    return {'schema':POLICY,'object_id':obj['id'],'role':obj['role'],'category':obj.get('category'),
            'route':route,'kind':kind,'reason':reason,'geometry':geometry,'constraints':spec.get('shape_constraints',{}),
            'sources':sources,'original_surface_samples':len(points),'color_rgb':color.tolist() if color is not None else None,
            'status':'NEEDS_REVIEW' if route=='needs_review' else 'SELECTED','uncertainty':obj.get('uncertainty'),
            'floor_thickness_assumption':({'value_m':geometry['wall_m'],'provenance':'estimated from wall thickness'} if route=='parametric' else None),
            'missing_dimension_axes':[axis for axis,v in zip('xyz',dims) if v is None],
            'required_validation':['original point cloud pose fit','collision','native export'],'accuracy':'NOT_VERIFIED'}


def create_asset(project, plan, directory):
    """Publish a native version with one convex collision per geometry part."""
    import trimesh
    from pxr import Usd,UsdGeom,UsdShade,UsdPhysics,Sdf
    from .calibration.geometry import parts
    from .object_assets import register_object_asset
    g=plan['geometry']; dims={'value':g['dimensions_m'],'provenance':g['provenance'],'evidence':g['evidence']}
    geometry={'type':plan['kind']}
    if geometry['type']=='container':
        geometry.update(round=True,wall={'value':g['wall_m']},bottom_diameter_m=g['bottom_diameter_m'])
    obj={'id':plan['object_id'],'dimensions':dims,'visual':geometry}
    path=Path(directory)/'geometry.usda';path.parent.mkdir(parents=True,exist_ok=True)
    stage=Usd.Stage.CreateInMemory();UsdGeom.SetStageMetersPerUnit(stage,1);UsdGeom.SetStageUpAxis(stage,'Z')
    stage.SetDefaultPrim(UsdGeom.Xform.Define(stage,'/Object').GetPrim())
    material=UsdShade.Material.Define(stage,'/Object/Material')
    shader=UsdShade.Shader.Define(stage,'/Object/Material/Surface');shader.CreateIdAttr('UsdPreviewSurface')
    shader.CreateInput('diffuseColor',Sdf.ValueTypeNames.Color3f).Set(tuple(plan['color_rgb']))
    material.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(),'surface')
    def native_meshes():
        if geometry['type']=='container':
            # A tapered wall is one convex wedge per sector. Stepped box rings
            # would miss the declared rim diameter on strongly tapered cups.
            top,base,height=g['dimensions_m'][0]/2,g['bottom_diameter_m']/2,g['dimensions_m'][2]
            wall=g['wall_m']
            floor=trimesh.creation.cylinder(radius=base,height=wall,sections=32)
            floor.apply_translation([0,0,(wall-height)/2])
            yield floor
            for i in range(32):
                vertices=[]
                for z,r in [(-height/2,base),(height/2,top)]:
                    for radius in (r-wall,r):
                        for angle in (i*2*np.pi/32,(i+1)*2*np.pi/32):
                            vertices.append([radius*np.cos(angle),radius*np.sin(angle),z])
                yield trimesh.convex.convex_hull(np.array(vertices))
            return
        for part in parts(obj,'visual'):
            x,y,z=part['dimensions']
            if part['type']=='box':mesh=trimesh.creation.box(extents=[x,y,z])
            elif part['type']=='cylinder':mesh=trimesh.creation.cylinder(radius=x/2,height=z,sections=32)
            else:mesh=trimesh.creation.icosphere(radius=x/2)
            mesh.apply_transform(part['pose'])
            yield mesh

    for i,mesh in enumerate(native_meshes()):
        for collision in (False,True):
            label='Collision' if collision else 'Visual'
            entry=UsdGeom.Mesh.Define(stage,f'/Object/{label}_{i}')
            entry.CreateSubdivisionSchemeAttr('none');entry.CreatePointsAttr(mesh.vertices.tolist())
            entry.CreateFaceVertexCountsAttr([3]*len(mesh.faces));entry.CreateFaceVertexIndicesAttr(mesh.faces.ravel().tolist())
            if collision:
                UsdPhysics.CollisionAPI.Apply(entry.GetPrim()).CreateCollisionEnabledAttr(True)
                entry.CreateVisibilityAttr('invisible')
            else:UsdShade.MaterialBindingAPI.Apply(entry.GetPrim()).Bind(material)
    stage.GetRootLayer().Export(str(path))
    return register_object_asset(project,path,asset_id=obj['id'],dimensions=dims,origin='centered native object in m',generation_id=POLICY)
