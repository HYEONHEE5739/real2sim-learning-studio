"""Separate v8 bbox and planar collision-contact placement; no engine execution."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from ..recipe import PreparedRun
    from scene_contract.package import ScenePackage

import numpy as np

from scene_contract.transforms import resolve_transform

from .registry import FunctionSpec, TaskError, _freeze


MAX_ATTEMPTS = 1000
RULES_ID = 'v8_preserved'


def _fail(code, object_id, reason, **diagnostics):
    error=TaskError(code,f'objects.{object_id}.placement',reason)
    error.diagnostics=MappingProxyType({'object_id':object_id,**diagnostics})
    raise error


def sample_uniform_xy(support_pose,support_dimensions,object_dimensions,rng,occupied_positions,occupied_sizes,
                      *,margin_m,separation_m,clearance_m,object_id):
    """Original uniform draw/order, axis separation and unrotated 3mm height."""
    center=np.array(support_pose)[:3,3];half=np.array(support_dimensions)/2
    size=np.array(object_dimensions);limit=half[:2]-size[:2]/2-margin_m
    if np.any(limit<=0):
        _fail('INVALID_PLACEMENT',object_id,'Object does not fit reset support',attempts=0,limit_m=tuple(limit))
    for attempt in range(1,MAX_ATTEMPTS+1):
        draw=np.asarray(rng.uniform(-limit,limit))
        if (draw.shape!=(2,) or draw.dtype.kind not in 'fiu' or not np.isfinite(draw).all()
                or np.any(draw < -limit) or np.any(draw > limit)):
            _fail('INVALID_PLACEMENT',object_id,'RNG must return a finite two-vector inside its requested bounds',attempts=attempt)
        xy=center[:2]+draw
        if all(np.any(np.abs(xy-np.array(pos[:2]))>(size[:2]+occupied_sizes[n][:2])/2+separation_m)
               for n,pos in occupied_positions.items()):
            return np.array([*xy,float(center[2]+half[2]+size[2]/2+clearance_m)]),attempt
    _fail('PLACEMENT_EXHAUSTED',object_id,'Unable to place non-overlapping objects in workspace',
          attempts=MAX_ATTEMPTS,max_attempts=MAX_ATTEMPTS,margin_m=margin_m,separation_m=separation_m,
          clearance_m=clearance_m,limit_m=tuple(limit),last_xy_m=tuple(xy),occupied_object_ids=tuple(occupied_positions))


def _se3(pose,object_id):
    pose=np.asarray(pose)
    if (pose.shape!=(4,4) or pose.dtype.kind not in 'fiu' or not np.isfinite(pose).all() or not np.allclose(pose[3],[0,0,0,1])
        or not np.allclose(pose[:3,:3].T@pose[:3,:3],np.eye(3),atol=1e-6) or np.linalg.det(pose[:3,:3])<.999999):
        _fail('INVALID_PLACEMENT',object_id,'Reset must return finite placement-frame SE(3)')
    return pose


def validate_v8_pose(pose,object_dimensions,support_pose,support_dimensions,*,object_id):
    """Original SE(3)/rotated bbox footprint check, distinct from sampling/physics."""
    pose=_se3(pose,object_id)
    local=np.linalg.inv(np.asarray(support_pose))@pose
    half=np.asarray(object_dimensions)/2
    corners=np.array([[x,y,z] for x in (-half[0],half[0]) for y in (-half[1],half[1]) for z in (-half[2],half[2])])@local[:3,:3].T+local[:3,3]
    limits=np.asarray(support_dimensions)/2
    if np.any(np.abs(corners[:,:2])>limits[:2]+1e-7) or corners[:,2].min()<limits[2]-1e-6:
        _fail('INVALID_PLACEMENT',object_id,'Reset pose outside/inside support')




@dataclass(frozen=True)
class PlacementRequest:
    object_id: str
    frame_id: str
    support_id: str
    occupied_poses: Mapping = field(default_factory=dict)
    rng: object = None
    xy_m: tuple[float,float] | None = None
    orientation: object = None  # Resolved rotation matrix in frame_id, or Metadata default.
    rules_id: str = RULES_ID


@dataclass(frozen=True)
class PlacementResult:
    object_id: str
    frame_id: str
    pose: np.ndarray
    attempts: int
    rules_id: str
    diagnostics: Mapping


@dataclass(frozen=True)
class PlacementParams:
    object: str = field(metadata={'reference':'object'})
    frame: str = field(metadata={'reference':'frame'})
    support: str = field(metadata={'reference':'support'})
    rules: Literal['v8_preserved'] = RULES_ID
    margin_m: float = .01
    separation_m: float = .005
    clearance_m: Literal[.003] = .003
    _context: ClassVar[Mapping | None] = None


def _bbox(spec):
    raw=spec.get('task_geometry',{}).get('dimensions_m',())
    if len(raw)!=3 or any(type(v) not in (int,float) or not np.isfinite(v) or v<=0 for v in raw):
        raise ValueError('v8 bbox placement requires positive finite task_geometry.dimensions_m')
    return np.array(raw)


def _reference_pose(scene,source,target):
    node=scene.scene['frames'][source]
    # The recorded parent-relative matrix is authoritative: do not round-trip via world.
    if source==target:return np.eye(4)
    if node['parent']==target:return np.array(node['T_parent_from_frame'])
    return resolve_transform(scene.scene['frames'],source=source,target=target)


def validate_params(params,scene):
    if isinstance(params,WorkspaceParams):return _validate_workspace_params(params,scene)
    if isinstance(params,ContactParams):return _validate_contact_params(params,scene)
    if scene is None:raise ValueError('ScenePackage required for v8 placement')
    objects=scene.scene['objects'];support=scene.scene['supports'][params.support]
    if support.get('placement_frame_id')!=params.frame:
        raise ValueError('v8_preserved requires the Metadata placement_frame_id; other input frames require a separately supported rule')
    object_spec=objects[params.object]
    if object_spec.get('role')!='task_object':raise ValueError('placement requires a selected task_object')
    support_id=support.get('object_id')
    if support_id not in objects:raise ValueError('support.object_id must name its reference support body')
    if params.rules!=RULES_ID or params.clearance_m!=.003:raise ValueError('v8_preserved requires the existing 3mm clearance')
    if any(type(v) not in (int,float) or not np.isfinite(v) or v<0 for v in (params.margin_m,params.separation_m)):
        raise ValueError('margin and separation must be nonnegative finite metres')
    context=dict(object_pose=_reference_pose(scene,object_spec['frame_id'],params.frame),
        object_dimensions=_bbox(object_spec),support_pose=_reference_pose(scene,objects[support_id]['frame_id'],params.frame),
        support_dimensions=_bbox(objects[support_id]),objects=objects)
    for value in context.values():
        if isinstance(value,np.ndarray):value.setflags(write=False)
    object.__setattr__(params,'_context',MappingProxyType(context))


def _inputs(request,params):
    if params._context is None:_fail('INVALID_PLACEMENT',params.object,'validate parameters with a Scene first',attempts=0)
    if (request.object_id,request.frame_id,request.support_id,request.rules_id)!=(params.object,params.frame,params.support,params.rules):
        _fail('INVALID_PLACEMENT',params.object,'request IDs/frame/rules differ from validated parameters',attempts=0)
    context=params._context;pose=context['object_pose'].copy();positions={};sizes={}
    if request.orientation is not None:
        orientation=np.asarray(request.orientation)
        if orientation.shape!=(3,3) or orientation.dtype.kind not in 'fiu' or not np.isfinite(orientation).all():
            _fail('INVALID_PLACEMENT',params.object,'orientation must be a resolved finite 3x3 rotation',attempts=0)
        pose[:3,:3]=orientation
    # Validate only SE(3) here. Support/physics checks must not become sampler retries.
    _se3(pose,params.object)
    if not isinstance(request.occupied_poses,Mapping):_fail('INVALID_PLACEMENT',params.object,'occupied_poses must be a mapping',attempts=0)
    for name,other in request.occupied_poses.items():
        spec=context['objects'].get(name)
        if name==params.object or spec is None or spec.get('role')!='task_object':
            _fail('INVALID_PLACEMENT',params.object,'occupied IDs must be other task objects',attempts=0)
        other=_se3(other,name)
        positions[name]=other[:3,3].copy()
        try:sizes[name]=_bbox(spec)
        except ValueError as exc:_fail('INVALID_PLACEMENT',params.object,str(exc),attempts=0)
    return context,pose,positions,sizes


def _result(request,pose,attempts,params):
    pose.setflags(write=False)
    return PlacementResult(request.object_id,request.frame_id,pose,attempts,RULES_ID,
        MappingProxyType(dict(support_id=request.support_id,margin_m=params.margin_m,separation_m=params.separation_m,
            clearance_m=params.clearance_m,attempts=attempts,rules_version=1,
            support_pose_checked=request.xy_m is not None,geometry_rule='legacy_bbox',physical_collision_checked=False)))


def fixed_xy(request,*,params):
    context,pose,placed,sizes=_inputs(request,params)
    xy=np.asarray(request.xy_m)
    if xy.shape!=(2,) or xy.dtype.kind not in 'fiu' or not np.isfinite(xy).all():
        _fail('INVALID_PLACEMENT',params.object,'Fixed XY requires two finite metres',attempts=0)
    pose[:2,3]=xy
    pose[2,3]=context['support_pose'][2,3]+context['support_dimensions'][2]/2+context['object_dimensions'][2]/2+params.clearance_m
    validate_v8_pose(pose,context['object_dimensions'],context['support_pose'],context['support_dimensions'],object_id=params.object)
    if not all(np.any(np.abs(xy-np.array(pos[:2]))>(context['object_dimensions'][:2]+sizes[n][:2])/2+params.separation_m) for n,pos in placed.items()):
        _fail('INVALID_PLACEMENT',params.object,'Fixed pose overlaps or violates declared bbox separation',attempts=0,occupied_object_ids=tuple(placed))
    return _result(request,pose,0,params)


def random_xy(request,*,params):
    context,pose,placed,sizes=_inputs(request,params)
    if request.xy_m is not None or not callable(getattr(request.rng,'uniform',None)):
        _fail('INVALID_PLACEMENT',params.object,'Random XY requires explicit RNG and no fixed xy_m',attempts=0)
    try:
        xyz,attempts=sample_uniform_xy(context['support_pose'],context['support_dimensions'],context['object_dimensions'],request.rng,
            placed,sizes,margin_m=params.margin_m,separation_m=params.separation_m,clearance_m=params.clearance_m,object_id=params.object)
    except TaskError as error:
        error.diagnostics=MappingProxyType({**error.diagnostics,'support_id':params.support,'frame_id':params.frame,'rules_id':params.rules,'rules_version':1})
        raise
    pose[:3,3]=xyz
    return _result(request,pose,attempts,params)


_STAGES={'source','datagen','simulation_evaluation'}
FUNCTIONS={name:FunctionSpec(kind='placement',stages=_STAGES,engines={'independent'},params_type=PlacementParams,callable=fn)
    for name,fn in [('placement.fixed_xy',fixed_xy),('placement.random_xy',random_xy)]}


def environment_seed(seed,env_index,*,num_envs):
    """Original reset_workspace seed derivation; caller owns RNG lifetime."""
    if (type(seed) is not int or seed<0 or type(num_envs) is not int or num_envs<1
            or type(env_index) is not int or not 0<=env_index<num_envs):
        _fail('INVALID_PLACEMENT','seed','invalid base seed/environment index/count',attempts=0)
    return seed if num_envs==1 else int(np.random.SeedSequence([seed,env_index]).generate_state(1)[0])


# General planar contact is intentionally separate from every v8 calculation above.
CONTACT_RULE = 'collision_contact'
GEOMETRY_TOL_M = 1e-9
MIN_NORMAL_Z = 1e-8


def contact_pose(parts, rotation, xy, support_pose):
    """Solve along input +Z; return input pose and actual vertices in support frame."""
    support_pose=_se3(support_pose,'support')
    inverse=np.linalg.inv(support_pose)
    direction=inverse[:3,2]
    if direction[2]<=MIN_NORMAL_Z:
        _fail('INVALID_PLACEMENT','support','Input +Z must point out of support plane',attempts=0)
    pose=np.eye(4);pose[:3,:3]=rotation;pose[:2,3]=xy
    _se3(pose,'contact')
    projected=tuple((v@pose[:3,:3].T+pose[:3,3])@inverse[:3,:3].T+inverse[:3,3] for v in parts)
    pose[2,3]=-min(v[:,2].min() for v in projected)/direction[2]
    _se3(pose,'contact')
    placed=tuple(v+pose[2,3]*direction for v in projected)
    if not all(np.isfinite(v).all() for v in placed):
        _fail('INVALID_PLACEMENT','contact','Nonfinite transformed collision geometry',attempts=0)
    return pose,placed


def _hull(points):
    points=sorted(set(map(tuple,points)))
    def half(seq):
        out=[]
        for v in seq:
            while len(out)>1 and np.cross(np.subtract(out[-1],out[-2]),np.subtract(v,out[-1]))<=0:out.pop()
            out.append(v)
        return out
    if len(points)<3:return np.array(points)
    return np.array(half(points)[:-1]+half(points[::-1])[:-1])


def polygon_distance(a,b):
    """Euclidean distance between convex projected parts, zero for touch/overlap."""
    a=_hull(a);b=_hull(b)
    separated=False
    for poly in (a,b):
        for edge in np.roll(poly,-1,axis=0)-poly:
            axis=np.array([-edge[1],edge[0]])
            if np.linalg.norm(axis)==0:continue
            av=a@axis;bv=b@axis
            if av.max()<bv.min() or bv.max()<av.min():separated=True
    if not separated:return 0.
    distances=[]
    for points,poly in ((a,b),(b,a)):
        for start,end in zip(poly,np.roll(poly,-1,axis=0)):
            edge=end-start;length=edge@edge
            alpha=np.clip((points-start)@edge/length,0,1) if length else np.zeros(len(points))
            distances.extend(np.linalg.norm(points-start-alpha[:,None]*edge,axis=1))
    return float(min(distances))


def _convex_mesh(scene, path):
    import hashlib
    import json
    from scene_contract.package import verify_files
    entry=next((f for f in scene.files if f.path==path),None)
    if entry is None:raise ValueError('Collision mesh must be registered in Manifest')
    verify_files(scene.root,(entry,))
    raw=(scene.root/path).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=entry.sha256:raise ValueError('Collision mesh changed after verification')
    def unique(pairs):
        out={}
        for key,value in pairs:
            if key in out:raise ValueError('Duplicate collision mesh JSON key')
            out[key]=value
        return out
    mesh=json.loads(raw,object_pairs_hook=unique)
    if set(mesh)!={'schema_version','vertices_m','triangles'} or type(mesh['schema_version']) is not int or mesh['schema_version']!=1:
        raise ValueError('Unsupported collision mesh JSON schema')
    vertices=np.asarray(mesh['vertices_m']);faces=np.asarray(mesh['triangles'])
    if (vertices.ndim!=2 or vertices.shape[1]!=3 or len(vertices)<4 or vertices.dtype.kind not in 'fiu'
            or not np.isfinite(vertices).all() or len(np.unique(vertices,axis=0))!=len(vertices) or np.linalg.matrix_rank(vertices-vertices[0])!=3):
        raise ValueError('Collision vertices must define a finite 3D solid')
    if faces.ndim!=2 or faces.shape[1]!=3 or faces.dtype.kind not in 'iu' or np.any(faces<0) or np.any(faces>=len(vertices)):
        raise ValueError('Invalid triangle indices')
    directed=[]
    for face in faces:
        a,b,c=vertices[face];normal=np.cross(b-a,c-a);length=np.linalg.norm(normal)
        if length==0:raise ValueError('Degenerate collision triangle')
        distances=(vertices-a)@(normal/length)
        if distances.max()>GEOMETRY_TOL_M and distances.min()<-GEOMETRY_TOL_M:
            raise ValueError('Each mesh part must be convex; export actual convex parts, not an inferred hull')
        directed.extend((int(face[i]),int(face[(i+1)%3])) for i in range(3))
    if (set(faces.flat)!=set(range(len(vertices))) or len(set(directed))!=len(directed)
            or any((b,a) not in directed for a,b in directed)):
        raise ValueError('Mesh must have closed consistently oriented two-manifold edges')
    return vertices.astype(float)


def _collision_parts(scene, object_id):
    spec=scene.scene['objects'][object_id];parts=spec.get('collision')
    if not isinstance(parts,(list,tuple)) or not parts:raise ValueError('Explicit collision parts are required; visual/task bbox is not a fallback')
    if any('collision' in b for b in spec.get('bindings',{}).values()):
        raise ValueError('Engine-specific collision representations need an explicitly selected common geometry before placement')
    result=[]
    for part in parts:
        if not isinstance(part,Mapping):raise ValueError('Collision part must be a mapping')
        common={'kind','scale','frame_id','local_transform'}
        allowed=common|({'primitive','dimensions_m'} if part.get('kind')=='primitive' else {'asset_path'})
        if set(part)-allowed:raise ValueError('Unknown or ambiguous collision part fields')
        if part.get('kind')=='primitive' and part.get('primitive')=='box':
            dims=np.asarray(part.get('dimensions_m'))
            if dims.shape!=(3,) or dims.dtype.kind not in 'fiu' or not np.isfinite(dims).all() or np.any(dims<=0):raise ValueError('Invalid collision box dimensions')
            vertices=np.array([[x,y,z] for x in (-.5,.5) for y in (-.5,.5) for z in (-.5,.5)])*dims
        elif part.get('kind')=='mesh':vertices=_convex_mesh(scene,part['asset_path'])
        else:raise ValueError('Unsupported collision representation: expected box or convex triangle mesh JSON')
        scale=np.asarray(part.get('scale',[1,1,1]))
        if scale.shape!=(3,) or scale.dtype.kind not in 'fiu' or not np.isfinite(scale).all() or np.any(scale<=0):raise ValueError('Collision scale must be positive finite XYZ')
        if ('frame_id' in part)==('local_transform' in part):raise ValueError('Collision needs frame_id XOR local_transform')
        local=_reference_pose(scene,part['frame_id'],spec['frame_id']) if 'frame_id' in part else _se3(part['local_transform'],object_id)
        vertices=(vertices*scale)@local[:3,:3].T+local[:3,3]
        if not np.isfinite(vertices).all():raise ValueError('Nonfinite transformed collision vertices')
        vertices.setflags(write=False);result.append(vertices)
    return tuple(result)


@dataclass(frozen=True)
class ContactParams:
    object: str = field(metadata={'reference':'object'})
    frame: str = field(metadata={'reference':'frame'})
    support: str = field(metadata={'reference':'support'})
    rules: Literal['collision_contact'] = CONTACT_RULE
    margin_m: float = 0.
    separation_m: float = 0.
    _context: ClassVar[Mapping | None] = None


def _validate_contact_params(params,scene):
    if scene is None:raise ValueError('ScenePackage required for collision contact')
    if any(type(v) not in (int,float) or not np.isfinite(v) or v<0 for v in (params.margin_m,params.separation_m)):
        raise ValueError('Margin/separation must be nonnegative finite metres')
    spec=scene.scene['objects'][params.object];support=scene.scene['supports'][params.support]
    if spec.get('role')!='task_object':raise ValueError('Placement requires a task_object')
    if set(support)!={'frame_id','region_xy_m'}:raise ValueError('Contact support needs plane frame_id and convex region_xy_m only')
    region=np.asarray(support['region_xy_m'])
    if (region.ndim!=2 or region.shape[1]!=2 or len(region)<3 or region.dtype.kind not in 'fiu'
            or not np.isfinite(region).all() or len(_hull(region))!=len(region)):
        raise ValueError('Support region must be a finite strictly convex polygon')
    hull=_hull(region)
    start=next(i for i,v in enumerate(region) if np.array_equal(v,hull[0]))
    if not np.array_equal(np.roll(region,-start,axis=0),hull):raise ValueError('Support boundary must follow convex hull order')
    edges=np.roll(region,-1,axis=0)-region
    if np.any(np.cross(edges,np.roll(edges,-1,axis=0))<=0):raise ValueError('Support polygon must be counterclockwise with no collinear edges')
    support_pose=_reference_pose(scene,support['frame_id'],params.frame)
    if support_pose[2,2]<=MIN_NORMAL_Z:raise ValueError('Input +Z must point out of support plane')
    parts=_collision_parts(scene,params.object);others={};errors={}
    # Geometry is bound once here; calls below perform no file access.
    for name,obj in scene.scene['objects'].items():
        if name==params.object or obj.get('role')!='task_object':continue
        try:others[name]=_collision_parts(scene,name)
        except (ValueError,KeyError,TypeError,OSError) as exc:errors[name]=str(exc)
    context=dict(parts=parts,other_parts=MappingProxyType(others),other_errors=MappingProxyType(errors),
        object_pose=_reference_pose(scene,spec['frame_id'],params.frame),support_pose=support_pose,region=region.astype(float))
    for value in context.values():
        if isinstance(value,np.ndarray):value.setflags(write=False)
    object.__setattr__(params,'_context',MappingProxyType(context))


def contact_fixed_xy(request,*,params):
    context,rotation,occupied=_contact_inputs(request,params)
    xy=_contact_xy(request.xy_m,params)
    pose,parts=contact_pose(context['parts'],rotation,xy,context['support_pose'])
    reason=_contact_rejection(parts,context['region'],occupied,params)
    if reason:_fail('INVALID_PLACEMENT',params.object,reason,attempts=0,support_id=params.support,frame_id=params.frame,rules_id=CONTACT_RULE)
    return _contact_result(pose,0,params)


def contact_random_xy(request,*,params):
    context,rotation,occupied=_contact_inputs(request,params)
    if request.xy_m is not None or not callable(getattr(request.rng,'uniform',None)):
        _fail('INVALID_PLACEMENT',params.object,'Random contact needs explicit RNG and no fixed XY',attempts=0)
    low,high=_contact_bounds(context,rotation,params)
    for attempt in range(1,MAX_ATTEMPTS+1):
        xy=_contact_xy(request.rng.uniform(low,high),params,attempts=attempt)
        if np.any(xy<low) or np.any(xy>high):
            _fail('INVALID_PLACEMENT',params.object,'RNG response outside requested bounds',attempts=attempt)
        pose,parts=contact_pose(context['parts'],rotation,xy,context['support_pose'])
        reason=_contact_rejection(parts,context['region'],occupied,params)
        if reason is None:return _contact_result(pose,attempt,params)
    _fail('PLACEMENT_EXHAUSTED',params.object,'No valid collision contact placement',attempts=MAX_ATTEMPTS,
        max_attempts=MAX_ATTEMPTS,support_id=params.support,frame_id=params.frame,rules_id=CONTACT_RULE,rules_version=1,
        margin_m=params.margin_m,separation_m=params.separation_m,last_reason=reason,last_xy_m=tuple(xy),
        bounds_m=(tuple(low),tuple(high)),occupied_object_ids=tuple(request.occupied_poses))


FUNCTIONS.update({name:FunctionSpec(kind='placement',stages=_STAGES,engines={'independent'},params_type=ContactParams,callable=fn)
    for name,fn in [('placement.contact_fixed_xy',contact_fixed_xy),('placement.contact_random_xy',contact_random_xy)]})


def _contact_xy(value,params,*,attempts=0):
    xy=np.asarray(value)
    if xy.shape!=(2,) or xy.dtype.kind not in 'fiu' or not np.isfinite(xy).all():
        _fail('INVALID_PLACEMENT',params.object,'Expected finite input-frame XY metres',attempts=attempts)
    return xy


def _contact_inputs(request,params):
    if (params._context is None or (request.object_id,request.frame_id,request.support_id,request.rules_id)
            !=(params.object,params.frame,params.support,CONTACT_RULE)):
        _fail('INVALID_PLACEMENT',params.object,'Request IDs/frame/rules must match prepared collision parameters',attempts=0)
    context=params._context;pose=context['object_pose'].copy()
    if request.orientation is not None:
        rotation=np.asarray(request.orientation)
        if rotation.shape!=(3,3) or rotation.dtype.kind not in 'fiu':
            _fail('INVALID_PLACEMENT',params.object,'Expected input-frame rotation matrix',attempts=0)
        pose[:3,:3]=rotation
    _se3(pose,params.object)
    if not isinstance(request.occupied_poses,Mapping):_fail('INVALID_PLACEMENT',params.object,'occupied_poses must be a mapping',attempts=0)
    inverse=np.linalg.inv(context['support_pose']);occupied=[]
    for name,value in request.occupied_poses.items():
        if name not in context['other_parts']:
            _fail('INVALID_PLACEMENT',params.object,context['other_errors'].get(name,'Unknown/non-task/self occupied object'),attempts=0,occupied_object_id=name)
        local=inverse@_se3(value,name)
        occupied.extend(_hull((v@local[:3,:3].T+local[:3,3])[:,:2]) for v in context['other_parts'][name])
    return context,pose[:3,:3],tuple(occupied)


def _region_planes(region):
    for start,end in zip(region,np.roll(region,-1,axis=0)):
        edge=end-start;normal=np.array([-edge[1],edge[0]])/np.linalg.norm(edge)
        yield normal,float(start@normal)


def _contact_rejection(parts,region,occupied,params):
    for normal,bound in _region_planes(region):
        if min((v[:,:2]@normal).min() for v in parts)<bound+params.margin_m-GEOMETRY_TOL_M:
            return 'footprint_outside_support'
    for part in parts:
        for other in occupied:
            if polygon_distance(part[:,:2],other)<=params.separation_m+GEOMETRY_TOL_M:
                return 'projected_overlap_or_separation'
    return None


def _contact_result(pose,attempts,params):
    pose.setflags(write=False)
    return PlacementResult(params.object,params.frame,pose,attempts,CONTACT_RULE,MappingProxyType(dict(
        support_id=params.support,attempts=attempts,rules_version=1,geometry_rule='convex_parts_planar_contact',
        clearance_m=0.,margin_m=params.margin_m,separation_m=params.separation_m,geometry_tolerance_m=GEOMETRY_TOL_M,
        support_pose_checked=True,physical_collision_checked=False,overlap_rule='projected_parts_conservative_3d')))


def _clip_polygon(polygon,normal,bound):
    out=[]
    for start,end in zip(polygon,np.roll(polygon,-1,axis=0)):
        a=float(start@normal-bound);b=float(end@normal-bound)
        if a>=0:out.append(start)
        if (a>=0)!=(b>=0):out.append(start+(end-start)*(a/(a-b)))
    return np.array(out)


def _contact_bounds(context,rotation,params):
    """Erode convex support by all part footprints; draw uniformly in input XY bbox."""
    pose,parts=contact_pose(context['parts'],rotation,[0,0],context['support_pose'])
    # Every feasible translation must keep this actual vertex in the support polygon.
    translations=context['region']-parts[0][0,:2]
    for normal,bound in _region_planes(context['region']):
        limit=bound+params.margin_m-min((v[:,:2]@normal).min() for v in parts)
        translations=_clip_polygon(translations,normal,limit)
        if len(translations)<3:
            _fail('INVALID_PLACEMENT',params.object,'No positive-area placement region for this geometry/orientation',attempts=0)
    cross=np.cross(translations,np.roll(translations,-1,axis=0))
    if abs(cross.sum())<=GEOMETRY_TOL_M**2:
        _fail('INVALID_PLACEMENT',params.object,'Degenerate placement region',attempts=0)
    input_points=translations@context['support_pose'][:2,:2].T+pose[:2,3]
    return input_points.min(axis=0),input_points.max(axis=0)


WORKSPACE_RULE = 'workspace_entropy_v1'


@dataclass(frozen=True)
class WorkspaceParams:
    object: str = field(metadata={'reference':'object'})
    frame: str = field(metadata={'reference':'frame'})
    support: str = field(metadata={'reference':'support'})
    workspace: str = field(metadata={'reference':'object'})
    rules: Literal['workspace_entropy_v1'] = WORKSPACE_RULE
    separation_m: float = .024
    yaw_rad: float = 0.
    _context: ClassVar[Mapping | None] = None


def _workspace_parts(scene: "ScenePackage", name: str) -> tuple[np.ndarray, ...]:
    """Builder box/compound collision; cylinders use a conservative outer prism.

    This is a footprint preflight, not native collision cooking or a physics query.
    """
    collision=scene.scene['objects'][name].get('collision')
    def vertices(part):
        if part.get('kind')=='compound':
            values=[v for child in part['parts'] for v in vertices(child)]
        elif part.get('kind')=='primitive' and part.get('primitive')=='box':
            dims=np.asarray(part['dimensions_m'],float)
            if dims.shape!=(3,) or not np.isfinite(dims).all() or np.any(dims<=0):raise ValueError('Invalid collision dimensions')
            values=[np.array([[x,y,z] for x in (-.5,.5) for y in (-.5,.5) for z in (-.5,.5)])*dims]
        elif part.get('kind')=='primitive' and part.get('primitive')=='cylinder':
            dims=np.asarray(part['dimensions_m'],float)
            if dims.shape!=(3,) or not np.isfinite(dims).all() or np.any(dims<=0) or dims[0]!=dims[1]:raise ValueError('Cylinder needs positive equal XY diameters and height')
            diameter,_,height=dims;angles=np.arange(64)*2*np.pi/64
            radius=diameter/2/np.cos(np.pi/64)
            values=[np.array([[radius*np.cos(a),radius*np.sin(a),z] for a in angles for z in (-height/2,height/2)])]
        else:raise ValueError('Workspace placement needs box/compound primitives; unsupported collision: '+name)
        scale=np.asarray(part.get('scale',[1,1,1]),float)
        local=_se3(part.get('local_transform',np.eye(4)),name)
        if scale.shape!=(3,) or not np.isfinite(scale).all() or np.any(scale<=0):raise ValueError('Invalid collision scale')
        result=tuple((v*scale)@local[:3,:3].T+local[:3,3] for v in values)
        if any(not np.isfinite(v).all() for v in result):raise ValueError('Nonfinite collision geometry')
        return result
    return vertices(collision)


def _validate_workspace_params(params,scene):
    if scene is None:raise ValueError('ScenePackage required')
    if type(params.separation_m) not in (int,float) or not np.isfinite(params.separation_m) or params.separation_m<.024:
        raise ValueError('Workspace surface gap must be finite and at least .024m')
    if type(params.yaw_rad) not in (int,float) or not np.isfinite(params.yaw_rad):raise ValueError('Finite yaw required')
    objects=scene.scene['objects'];workspace=objects[params.workspace];spec=objects[params.object]
    if workspace['role']!='workspace' or workspace['frame_id']!=params.frame:raise ValueError('Explicit workspace Object and its local Frame required')
    if spec['role']!='task_object':raise ValueError('Random placement requires a task_object')
    support_id=scene.scene['supports'][params.support]['object_id']
    top=objects[support_id]['collision'];area=workspace['collision']
    if any(c.get('kind')!='primitive' or c.get('primitive')!='box' for c in (top,area)):
        raise ValueError('Workspace/support must have explicit box surfaces')
    support_pose=_reference_pose(scene,objects[support_id]['frame_id'],params.frame)@_se3(top.get('local_transform',np.eye(4)),support_id)
    if not np.allclose(support_pose[:3,2],[0,0,1],atol=1e-10,rtol=0):raise ValueError('Workspace local XY must be parallel to actual support surface')
    dims=np.asarray(area['dimensions_m'],float)*np.asarray(area.get('scale',[1,1,1]))
    if not np.array_equal(_se3(area.get('local_transform',np.eye(4)),params.workspace),np.eye(4)):
        raise ValueError('Workspace box must be centered on its declared Frame')
    support_pose[:3,3]+=support_pose[:3,2]*(top['dimensions_m'][2]*top.get('scale',[1,1,1])[2]/2)
    c,s=np.cos(params.yaw_rad),np.sin(params.yaw_rad);rotation=np.array([[c,-s,0],[s,c,0],[0,0,1.]])
    parts=_workspace_parts(scene,params.object);rotated=np.concatenate(parts)@rotation.T
    low=-dims[:2]/2-rotated[:,:2].min(axis=0);high=dims[:2]/2-rotated[:,:2].max(axis=0)
    if np.any(low>=high):raise ValueError('No positive-area workspace remaining for object footprint')
    others={};errors={}
    for name,obj in objects.items():
        if name==params.object or name==support_id or obj['role'] in ('reference_robot','background','workspace'):continue
        try:others[name]=_workspace_parts(scene,name)
        except (ValueError,KeyError,TypeError) as error:errors[name]=str(error)
    context=dict(parts=parts,rotation=rotation,bounds=(low,high),support_pose=support_pose,other_parts=others,other_errors=errors,
                 support_id=support_id,support_parts=_workspace_parts(scene,support_id),
                 support_body_pose=_reference_pose(scene,objects[support_id]['frame_id'],params.frame),
                 workspace_dimensions_m=dims[:2],roles={n:o['role'] for n,o in objects.items()})
    object.__setattr__(params,'_context',MappingProxyType(context))


def random_workspace(request: PlacementRequest,*,params: WorkspaceParams) -> PlacementResult:
    """Fresh OS entropy per call. The Recipe/Mimic attempt seed is unrelated.

    https://numpy.org/doc/1.26/reference/random/generator.html#numpy.random.default_rng
    """
    if (params._context is None or (request.object_id,request.frame_id,request.support_id,request.rules_id)
            !=(params.object,params.frame,params.support,WORKSPACE_RULE)):
        _fail('INVALID_PLACEMENT',params.object,'Workspace request differs from prepared parameters',attempts=0)
    if request.rng is not None or request.orientation is not None or request.xy_m is not None:
        _fail('INVALID_PLACEMENT',params.object,'Seed/RNG, orientation and XY overrides are not Random Workspace inputs',attempts=0)
    context=params._context;occupied=[]
    for name,pose in request.occupied_poses.items():
        if name not in context['other_parts']:
            _fail('INVALID_PLACEMENT',params.object,context['other_errors'].get(name,'Unknown occupied collision geometry'),attempts=0,occupied_object_id=name)
        pose=_se3(pose,name)
        vertices=np.concatenate(context['other_parts'][name])@pose[:3,:3].T+pose[:3,3]
        occupied.append((name,_hull(vertices[:,:2]),vertices[:,2].min(),vertices[:,2].max()))
    rng=np.random.default_rng();low,high=context['bounds'];reason=None
    inverse=np.linalg.inv(context['support_body_pose'])
    support_vertices=np.concatenate(context['support_parts']);support_low=support_vertices[:,:2].min(axis=0);support_high=support_vertices[:,:2].max(axis=0)
    for attempt in range(1,MAX_ATTEMPTS+1):
        xy=np.asarray(rng.uniform(low,high))
        if xy.shape!=(2,) or not np.isfinite(xy).all() or np.any(xy<low) or np.any(xy>high):
            _fail('INVALID_PLACEMENT',params.object,'RNG returned invalid workspace XY',attempts=attempt)
        pose,_=contact_pose(context['parts'],context['rotation'],xy,context['support_pose'])
        vertices=np.concatenate(context['parts'])@pose[:3,:3].T+pose[:3,3]
        support_local=vertices@inverse[:3,:3].T+inverse[:3,3]
        if np.any(support_local[:,:2]<support_low) or np.any(support_local[:,:2]>support_high):
            reason='outside_actual_support';continue
        footprint=_hull(vertices[:,:2]);distances={};reason=None
        for name,other,zlo,zhi in occupied:
            if zlo>vertices[:,2].max() or zhi<vertices[:,2].min():continue
            distance=polygon_distance(footprint,other);distances[name]=distance
            gap=params.separation_m if context['roles'][name]=='task_object' else 0.
            if distance<gap or distance==0:reason='surface_gap_or_obstacle_overlap';break
        if reason is None:
            pose.setflags(write=False)
            return PlacementResult(params.object,params.frame,pose,attempt,WORKSPACE_RULE,_freeze(dict(
                valid=True,workspace_id=params.workspace,workspace_dimensions_m=context['workspace_dimensions_m'].tolist(),
                bounds_m=[low.tolist(),high.tolist()],surface_gap_m=params.separation_m,surface_distances_m=distances,
                support_id=params.support,physical_collision_checked=False,geometry_rule='convex_footprints_conservative_obstacles',
                attempts=attempt,pose=pose.tolist())))
    _fail('INVALID_PLACEMENT',params.object,'Finite workspace candidate budget exhausted',attempts=MAX_ATTEMPTS,
          max_attempts=MAX_ATTEMPTS,frame_id=params.frame,workspace_id=params.workspace,support_id=params.support,
          bounds_m=[low.tolist(),high.tolist()],surface_gap_m=params.separation_m,last_reason=reason,command_applied=False)


FUNCTIONS['placement.random_workspace']=FunctionSpec(kind='placement',stages={'datagen','simulation_evaluation'},engines={'independent'},
    params_type=WorkspaceParams,callable=random_workspace)


def uses_workspace_random(plan: "PreparedRun") -> bool:
    return any(b.kind=='placement' and b.name=='placement.random_workspace' for b in plan.function_bindings.values())


def workspace_reset_poses(plan: "PreparedRun",occupied_world: Mapping[str,np.ndarray]) -> tuple[list[tuple[str,np.ndarray]],dict]:
    """Plan a complete batch without engine effects; old moving poses are excluded.

    occupied_world must include actual fixed collision objects, excluding the support,
    noncolliding visuals and robot links (which require native collision checking).
    """
    occupied={n:pose for n,pose in occupied_world.items() if n not in plan.object_order}
    results=[];records={}
    for name in plan.object_order:
        binding=plan.function_bindings['objects.'+name+'.placement'];params=binding.params
        if binding.name!='placement.random_workspace':
            _fail('INVALID_PLACEMENT',name,'One workspace reset batch requires explicit random_workspace bindings; fixed obstacles belong in occupied state',attempts=0)
        if binding.request_fields:_fail('INVALID_PLACEMENT',name,'Random workspace does not accept pose overrides',attempts=0)
        world=_reference_pose(plan.scene,params.frame,'world');inverse=np.linalg.inv(world)
        local_occupied={n:inverse@pose for n,pose in occupied.items() if n!=params._context['support_id']}
        try:result=random_workspace(PlacementRequest(name,params.frame,params.support,occupied_poses=local_occupied,rules_id=params.rules),params=params)
        except TaskError as error:
            error.diagnostics=_freeze({**error.diagnostics,'planned_not_applied':records});raise
        pose=world@result.pose;occupied[name]=pose;results.append((name,pose))
        records[name]={'object_id':name,'frame_id':params.frame,'local_pose':result.pose.tolist(),'requested_world_pose':pose.tolist(),
                       'validation':dict(result.diagnostics),'applied':False}
    return results,records


def validate_workspace_payload(plan: "PreparedRun",poses_world: list[tuple[str,np.ndarray]],occupied_world: Mapping[str,np.ndarray]) -> None:
    """Strict footprint preflight of native pose payloads before any state write.

    Quaternion serialization / float32 conversion can shrink a 24mm gap. Reject
    the batch; never move a pose, expand a bound or relabel it as physical PASS.
    """
    actual=dict(occupied_world);actual.update(poses_world)
    for name,world in poses_world:
        params=plan.function_bindings['objects.'+name+'.placement'].params;context=params._context
        inverse=np.linalg.inv(_reference_pose(plan.scene,params.frame,'world'));pose=inverse@world
        vertices=np.concatenate(context['parts'])@pose[:3,:3].T+pose[:3,3]
        if np.any(abs(vertices[:,:2])>context['workspace_dimensions_m']/2):
            _fail('INVALID_PLACEMENT',name,'Native pose payload footprint outside workspace',stage='native_payload',applied=False)
        support_inverse=np.linalg.inv(context['support_body_pose']);local=vertices@support_inverse[:3,:3].T+support_inverse[:3,3]
        support_vertices=np.concatenate(context['support_parts'])
        if np.any(local[:,:2]<support_vertices[:,:2].min(axis=0)) or np.any(local[:,:2]>support_vertices[:,:2].max(axis=0)):
            _fail('INVALID_PLACEMENT',name,'Native pose payload outside actual support',stage='native_payload',applied=False)
        footprint=_hull(vertices[:,:2])
        for other,value in actual.items():
            if other in (name,context['support_id']):continue
            if other not in context['other_parts']:
                _fail('INVALID_PLACEMENT',name,'Unverified native payload obstacle',occupied_object_id=other,applied=False)
            local=inverse@value;v=np.concatenate(context['other_parts'][other])@local[:3,:3].T+local[:3,3]
            if v[:,2].min()>vertices[:,2].max() or v[:,2].max()<vertices[:,2].min():continue
            distance=polygon_distance(footprint,_hull(v[:,:2]));gap=params.separation_m if context['roles'][other]=='task_object' else 0.
            if distance<gap or distance==0:
                _fail('INVALID_PLACEMENT',name,'Native pose payload violates surface gap/obstacle constraint',stage='native_payload',
                      occupied_object_id=other,surface_distance_m=distance,required_surface_gap_m=gap,applied=False)
