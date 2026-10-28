"""v8 Task calculations. No simulation, device, writer or UI ownership."""
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import ClassVar, Literal

import numpy as np

from .registry import FunctionSpec, TaskError

# Existing engineering thresholds; not newly measured physical constants.
HOLD_SECONDS = 0.20
RELATIVE_DRIFT_M = 0.006


class StableGrasp:
    def __init__(self, dt, size):
        self.dt = dt
        self.size = size
        self.samples = []
        self.completed = False
        self.last_tick = None
        self.details = {}

    def update(self, sample):
        """One post-step observation. Pre-step recording reads completed separately."""
        if sample.get('phase')!='post_step':_invalid('phase','grasp updates require post_step')
        tick=sample.get('tick')
        if type(tick) is not int or tick<0:_invalid('tick','expected nonnegative integer tick')
        if (sample.get('episode_id'),sample.get('env_index'),sample.get('dt_s'))!=(self.episode_id,self.env_index,self.dt):
            _invalid('episode','tracker belongs to a different episode/env/control period')
        values=sample.get('grasp_inputs',{});contacts=sample.get('contacts',{})
        if values.get('object_id')!=self.object_id:_invalid('grasp_inputs.object_id','wrong tracked object')
        order=values.get('quaternion_order')
        source=contacts.get('source_definition')
        if order not in ('wxyz','xyzw') or source not in (
            'mujoco_body_pair_dist_le_0','isaac_contact_sensor_gt_1e_4_n','isaac_direct_contact_view_gt_0_01_n'):
            _invalid('contacts/grasp_inputs','explicit contact definition and quaternion order required')
        convention=(order,source)
        if self.input_convention is not None and convention!=self.input_convention:
            _invalid('contacts/grasp_inputs','input convention changed within an episode')
        arrays=[]
        for name,shape in (('relative',(3,)),('relative_quat',(4,)),('ee_position',(3,)),('object_position',(3,))):
            try:
                value=np.asarray(values[name])
                valid=value.shape==shape and value.dtype.kind in 'fiu' and np.isfinite(value).all()
            except (KeyError,TypeError,ValueError):valid=False
            if not valid:_invalid('grasp_inputs.'+name,'expected finite numeric array '+str(shape))
            arrays.append(value)
        if any(type(contacts.get(k)) not in (bool,np.bool_) for k in ('left','right')):
            _invalid('contacts','left/right must be measured booleans')
        self.input_convention=convention
        value=self.observe(tick,*arrays,contacts['left'],contacts['right'])
        return SignalValue(bool(value),tick,'post_step',MappingProxyType({**self.details,
            'object_id':self.object_id,'source_definition':source,'quaternion_order':order}))

    def observe(self, tick, relative, relative_quat, ee_position, object_position, left, right):
        if tick == self.last_tick:
            return self.completed
        if self.last_tick is not None and tick != self.last_tick + 1:
            self.samples.clear()
        self.last_tick = tick
        sample = tuple(np.asarray(v, dtype=float).copy() for v in
                       (relative, relative_quat, ee_position, object_position))
        if left and right:
            self.samples.append(sample)
            while self.samples:
                origin = self.samples[0]
                drift = max(np.linalg.norm(p[0] - origin[0]) for p in self.samples)
                angle = max(2*np.arccos(np.clip(abs(np.dot(p[1], origin[1])) /
                            max(np.linalg.norm(p[1])*np.linalg.norm(origin[1]), 1e-12), 0, 1))
                            for p in self.samples)
                if drift <= RELATIVE_DRIFT_M and angle <= np.deg2rad(10):
                    break
                self.samples.pop(0)
        else:
            self.samples.clear()
        duration = max(0, len(self.samples)-1)*self.dt
        ee_motion = object_motion = 0.
        if self.samples:
            ee_motion = np.linalg.norm(sample[2]-self.samples[0][2])
            object_motion = np.linalg.norm(sample[3]-self.samples[0][3])
        moving = ee_motion >= .005 and object_motion >= .005
        stable = bool(left and right and moving and duration + 1e-9 >= HOLD_SECONDS)
        self.completed |= stable
        self.details = dict(left_contact=bool(left), right_contact=bool(right), moving=bool(moving),
                            ee_motion_m=float(ee_motion), object_motion_m=float(object_motion),
                            stable=stable, hold_seconds=duration, required_seconds=HOLD_SECONDS,
                            relative_drift_limit_m=RELATIVE_DRIFT_M)
        # Rolling window; confirmation requires motion inside the sustained-contact window.
        if len(self.samples) > int(np.ceil(HOLD_SECONDS/self.dt))+1:
            self.samples.pop(0)
        return self.completed




@dataclass(frozen=True)
class PlacementGeometry:
    """Historical task dimensions, not collision mesh/support geometry."""
    object_dimensions_m: tuple[float, float, float]
    target_dimensions_m: tuple[float, float, float]
    wall_m: float
    bottom_diameter_m: float | None = None


def numpy_corners(object_pose, target_pose, dimensions_m):
    """Original NumPy order; engine bindings retain their own native pose arithmetic."""
    relative = np.linalg.inv(target_pose) @ object_pose
    size = np.asarray(dimensions_m)
    corners = np.array([[a,b,c] for a in (-1,1) for b in (-1,1) for c in (-1,1)]) * size / 2
    return corners @ relative[:3,:3].T + relative[:3,3]


def placement_details(points, linear_velocity, geometry, *, relation='contained_and_settled',
                      max_speed_m_s=.03, bounds_m=None):
    """Eight target-local corners and world linear velocity, retaining array dtype.

    Tensor inputs use the historical Torch reductions; NumPy uses the MuJoCo math.
    No engine state/contacts are queried and no orientation or release gate is added.
    """
    tensor = type(points).__module__.startswith('torch')
    if tensor:
        import torch
        norm = lambda x: torch.linalg.vector_norm(x,dim=-1)
        all_true = lambda x: bool(x.all())
    else:
        points = np.asarray(points)
        linear_velocity = np.asarray(linear_velocity)
        norm = lambda x: np.linalg.norm(x,axis=-1)
        all_true = lambda x: bool(np.all(x))
    if relation not in ('contained_and_settled','inside_region_and_settled'):
        _invalid('relation','unknown placement relation')
    if tensor:
        valid=(isinstance(linear_velocity,torch.Tensor) and tuple(points.shape)==(8,3)
            and tuple(linear_velocity.shape)==(3,) and points.dtype==linear_velocity.dtype
            and points.device==linear_velocity.device and points.is_floating_point()
            and bool(torch.isfinite(points).all()) and bool(torch.isfinite(linear_velocity).all()))
    else:
        valid=(points.shape==(8,3) and linear_velocity.shape==(3,) and points.dtype.kind in 'fiu'
            and linear_velocity.dtype.kind in 'fiu' and np.isfinite(points).all() and np.isfinite(linear_velocity).all())
    if not valid:_invalid('placement_points/linear_velocities','expected finite 8x3 corners and 3-vector velocity, retaining native dtype')
    speed_raw=norm(linear_velocity)
    speed = float(speed_raw)
    speed_ok = bool(speed_raw < max_speed_m_s) if tensor else speed < max_speed_m_s
    if relation == 'inside_region_and_settled':
        if tensor:
            bounds = torch.tensor(bounds_m,device=points.device)
        else:
            bounds = np.asarray(bounds_m)
        inside = all_true((points >= bounds[0]) & (points <= bounds[1]))
        return dict(height_ok=inside,wall_ok=inside,speed_ok=speed_ok,success=inside and speed_ok,speed_m_s=speed)
    h=geometry.target_dimensions_m[2];top=geometry.target_dimensions_m[0]/2
    bottom=(geometry.bottom_diameter_m if geometry.bottom_diameter_m is not None else top*2)/2
    radius=bottom+(top-bottom)*(points[:,2]+h/2)/h-geometry.wall_m
    excess=norm(points[:,:2])-radius
    height_ok=bool(points[:,2].min() > -h/2+geometry.wall_m-.002 and points[:,2].max() < h/2)
    wall_ok=all_true(excess <= .001)
    return dict(height_ok=height_ok,wall_ok=wall_ok,speed_ok=speed_ok,
                success=height_ok and wall_ok and speed_ok,speed_m_s=speed,
                radial_excess_m=float(excess.max()))




@dataclass(frozen=True)
class GraspParams:
    object: str = field(metadata={'reference':'object'})


@dataclass(frozen=True)
class SignalValue:
    value: bool
    tick: int
    phase: str
    diagnostics: object


def _invalid(field,reason):
    raise TaskError('TASK_SAMPLE_INVALID',field,reason)


def create_stable_grasp(*,params,episode):
    dt=episode['control_dt_s']
    if type(dt) not in (int,float) or not np.isfinite(dt) or dt<=0:_invalid('control_dt_s','expected positive finite control period')
    tracker=StableGrasp(dt,None)  # Historical size was unused; no new size/grip gate.
    tracker.episode_id=episode['episode_id'];tracker.env_index=episode['env_index']
    tracker.object_id=params.object
    tracker.input_convention=None
    return tracker




@dataclass(frozen=True)
class PickPlaceParams:
    object: str = field(metadata={'reference':'object'})
    target: str = field(metadata={'reference':'object'})
    relation: Literal['contained_and_settled','inside_region_and_settled'] = 'contained_and_settled'
    max_speed_m_s: float = .03
    bounds_m: tuple[tuple[float,float,float],tuple[float,float,float]] | None = None
    _geometry: ClassVar[PlacementGeometry | None] = None


def validate_params(params,scene):
    """Bind immutable task geometry from the already validated Scene; no file I/O."""
    if isinstance(params,GraspParams):return
    if scene is None:raise ValueError('placement requires Scene task_geometry')
    objects=scene.scene['objects']
    pick=objects[params.object].get('task_geometry',{})
    target=objects[params.target].get('task_geometry',{})
    dimensions=tuple(pick.get('dimensions_m',()))
    cup_dimensions=tuple(target.get('dimensions_m',()))
    if len(dimensions)!=3 or not all(np.isfinite(v) and v>0 for v in dimensions):
        raise ValueError('object task_geometry.dimensions_m must be positive finite XYZ')
    if not np.isfinite(params.max_speed_m_s) or params.max_speed_m_s<0:raise ValueError('invalid speed limit')
    if params.relation=='contained_and_settled':
        if len(cup_dimensions)!=3 or not all(np.isfinite(v) and v>0 for v in cup_dimensions):
            raise ValueError('target task_geometry.dimensions_m must be positive finite XYZ')
        wall=target.get('wall_m');bottom=target.get('bottom_diameter_m',cup_dimensions[0])
        if wall is None or not np.isfinite(wall) or wall<0 or not np.isfinite(bottom) or bottom<=0:
            raise ValueError('target task_geometry wall/bottom data required')
    elif params.relation=='inside_region_and_settled':
        bounds=np.asarray(params.bounds_m)
        if bounds.shape!=(2,3) or bounds.dtype.kind not in 'fiu' or not np.isfinite(bounds).all() or (bounds[0]>bounds[1]).any():
            raise ValueError('explicit target-local region bounds required')
        wall=0.;bottom=None
    else:raise ValueError('unknown placement relation')
    # Private derived cache: it is not a dataclass input field or a Recipe option.
    object.__setattr__(params,'_geometry',PlacementGeometry(dimensions,cup_dimensions,wall,bottom))


def v8_metrics(sample,*,params):
    if params._geometry is None:_invalid('params','validate parameters with a Scene before use')
    try:
        entry=sample['placement_points'][params.object]
        if entry['target_id']!=params.target:_invalid('placement_points.target_id','wrong target-local geometry input')
        points=entry['points'];velocity=sample['linear_velocities'][params.object]
    except (KeyError,TypeError,IndexError):_invalid('placement_points/linear_velocities','explicit selected object/target input required')
    return placement_details(points,velocity,params._geometry,relation=params.relation,
                             max_speed_m_s=params.max_speed_m_s,bounds_m=params.bounds_m)


def v8_placement(sample,*,params):
    return v8_metrics(sample,params=params)['success']


def grasp_and_placement(final,*,params):
    if final.get('phase')!='episode_end':_invalid('phase','physical acceptance requires episode_end')
    signal=final.get('signals',{}).get('grasp')
    if not isinstance(signal,SignalValue) or type(signal.value) is not bool or type(signal.tick) is not int or signal.phase!='post_step' or signal.tick>final['tick'] or signal.diagnostics.get('object_id')!=params.object:
        _invalid('signals.grasp','completed post-step tracker snapshot for this object required')
    return bool(v8_placement(final,params=params) and signal.value)


_TASK_STAGES={'annotation','datagen','simulation_evaluation'}
FUNCTIONS={
    'pick_place.stable_grasp': FunctionSpec(kind='tracker',stages=_TASK_STAGES,engines={'independent'},
        params_type=GraspParams,callable=create_stable_grasp,requires=('grasp_inputs','contacts'),
        bindings={stage:{'phase':'post_step'} for stage in _TASK_STAGES}),
    'pick_place.placement': FunctionSpec(kind='predicate',stages=_TASK_STAGES,engines={'independent'},
        params_type=PickPlaceParams,callable=v8_placement,requires=('placement_points','linear_velocities')),
    'pick_place.v8_evaluation': FunctionSpec(kind='predicate',stages={'simulation_evaluation'},engines={'independent'},
        params_type=PickPlaceParams,callable=v8_placement,requires=('placement_points','linear_velocities'),
        bindings={'simulation_evaluation':{'phase':'post_step'}}),
    'pick_place.v8_metrics': FunctionSpec(kind='metrics',stages=_TASK_STAGES,engines={'independent'},
        params_type=PickPlaceParams,callable=v8_metrics,requires=('placement_points','linear_velocities'),
        bindings={stage:{'phase':'post_step' if stage=='simulation_evaluation' else 'pre_step'} for stage in _TASK_STAGES}),
}
for _stage in ('annotation','datagen'):
    FUNCTIONS['pick_place.v8_'+_stage]=FunctionSpec(kind='acceptance',stages={_stage},engines={'independent'},
        params_type=PickPlaceParams,callable=grasp_and_placement,
        requires=('placement_points','linear_velocities','signals.grasp'),
        bindings={_stage:{'phase':'episode_end','signals':{'grasp':{'function':'pick_place.stable_grasp','params':{}}}}})


def release_evidence(tracker,relative,contacts,command,tick,hz,reference,grip,released,loss_steps,drop_step):
    """Original diagnostic latch; never modifies grasp/placement acceptance."""
    if tracker.completed:
        if reference is None:reference=np.asarray(relative).copy();grip=float(command[5])
        if float(command[5])>grip+1e-4:released=True
        separated=not any(contacts) and np.linalg.norm(relative-reference)>RELATIVE_DRIFT_M
        loss_steps=loss_steps+1 if separated and not released else 0
        if loss_steps/hz>=HOLD_SECONDS and drop_step is None:drop_step=tick
    return reference,grip,released,loss_steps,drop_step


def object_metrics(active, target, positions, eef, state, grasp=False, place=False, initial_positions=None):
    """Approach identity proxy; single-object selection accuracy is N/A, never automatic success."""
    import numpy as np
    distance = {name:float(np.linalg.norm(np.asarray(pos)-eef)) for name,pos in positions.items() if name in active}
    if set(distance)!=set(active):raise ValueError('Evaluation object states differ from active scene')
    if 'selected_object_id' not in state:state['selected_object_id']='UNKNOWN'
    if not state.get('grasp_success') and state['selected_object_id']=='UNKNOWN' and distance:
        closest=min(distance,key=distance.get)
        if distance[closest] < .04:state['selected_object_id']=closest
    state['grasp_success']=bool(state.get('grasp_success') or grasp)
    if initial_positions and state['grasp_success']:
        state['transport_success']=bool(state.get('transport_success') or np.linalg.norm(
            np.asarray(positions[target])-initial_positions[target])>.04)
    state['place_success']=bool(state.get('place_success') or place)
    minimum = state.setdefault('object_min_distances_m', {})
    for name,value in distance.items():minimum[name]=min(value,minimum.get(name,float('inf')))
    choice = state['selected_object_id']
    discriminable = len(active)>1 and choice!='UNKNOWN'
    return {'scene_active_object_count':len(active),'active_object_ids':list(active),'target_object_id':target,
        'distractor_ids':[n for n in active if n!=target], 'selected_object_id':choice,
        'target_selection_accuracy':(choice==target if discriminable else None),
        'wrong_object_approach':(choice!=target if discriminable else None),
        'object_distances_m':distance, 'object_min_distances_m':dict(minimum),
        'object_approached':{n:v<.04 for n,v in minimum.items()}, 'grasp_success':state['grasp_success'],
        'transport_success':bool(state.get('transport_success')), 'place_success':state['place_success'],
        'full_task_success':bool(state['grasp_success'] and state.get('transport_success') and state['place_success']),
        'selection_measurement':'closest object within 40mm before grasp; geometric proxy, not verified semantic recognition'}
