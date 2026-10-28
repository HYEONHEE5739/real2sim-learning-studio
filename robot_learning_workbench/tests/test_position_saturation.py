import numpy as np
import pytest
from robot_learning_workbench.robot.control import checked_target,TargetRejected
from robot_learning_workbench.robot.calibration import JOINTS

UPPER=1.7453264625997165

def bounds():
    b=np.tile([-3.,3.],(6,1));b[3]=[-UPPER,UPPER];return b

@pytest.mark.parametrize('dtype',[np.float32,np.float64])
def test_interior_command_is_unchanged_in_native_dtype(dtype):
    raw=np.array([.1,-.2,.3,-.4,.5,.6],dtype=dtype);copy=raw.copy()
    np.testing.assert_array_equal(checked_target(raw,limits=bounds(),applied_dtype=dtype),copy)
    np.testing.assert_array_equal(raw,copy)

@pytest.mark.parametrize('sign',[-1,1])
def test_limit_saturation_is_inward_representable_and_idempotent(sign):
    raw=np.zeros(6);raw[3]=sign*100.;info={}
    q=checked_target(raw,limits=bounds(),applied_dtype=np.float32,diagnostics=info)
    assert q[3]==sign*1.7453263998031616 and np.all(q>=bounds()[:,0]) and np.all(q<=bounds()[:,1])
    assert info['saturation_mask'][3] and info['saturated_joints']==['wrist_flex']
    np.testing.assert_array_equal(checked_target(q,limits=bounds(),applied_dtype=np.float32),q)
    assert raw[3]==sign*100.

def test_rounding_overshoot_is_saturated_not_accepted_or_rejected():
    raw=np.zeros(6);raw[3]=UPPER
    q=checked_target(raw,limits=bounds(),applied_dtype=np.float32)
    assert q[3]==1.7453263998031616
    np.testing.assert_array_equal(checked_target(raw,limits=bounds(),applied_dtype=np.float64),raw)

@pytest.mark.parametrize('bad',[np.full(6,np.nan),np.full(6,np.inf),np.zeros(5),np.array(['1']*6),np.ones(6,dtype=complex)])
def test_invalid_input_cannot_be_repaired_by_saturation(bad):
    with pytest.raises(TargetRejected):checked_target(bad,limits=bounds(),applied_dtype=np.float32)

@pytest.mark.parametrize('kwargs',[{'units':'degree'},{'joint_order':JOINTS[::-1]}])
def test_units_and_mapping_remain_explicit_errors(kwargs):
    with pytest.raises(TargetRejected):checked_target(np.zeros(6),limits=bounds(),applied_dtype=np.float32,**kwargs)

def test_no_representable_value_is_rejected():
    b=bounds();b[0]=[1.+1e-10,1.+2e-10]
    with pytest.raises(TargetRejected):checked_target(np.zeros(6),limits=b,applied_dtype=np.float32)

def test_huge_finite_request_is_bounded_before_native_cast():
    q=checked_target(np.full(6,1e300),limits=bounds(),applied_dtype=np.float32)
    assert np.isfinite(q).all() and np.all(q<=bounds()[:,1])


def test_recording_uses_applied_training_target_and_preserves_requested():
    from robot_learning_workbench.engines.mujoco.source import record_frame
    from robot_learning_workbench.data.native import native_api
    raw=np.zeros(6);raw[3]=UPPER;target=checked_target(raw,limits=bounds(),applied_dtype=np.float32)
    ep=native_api()[0]();sample={'eef_pose':np.eye(4),'joint_positions':np.zeros(6),'object_poses':{}}
    record_frame(ep,sample,np.eye(4),target,time_s=0,command_requested=raw,command_limits=bounds())
    ep.pre_export()
    np.testing.assert_array_equal(ep.data['joint_targets'][0].numpy(),target)
    np.testing.assert_array_equal(ep.data['commands']['requested_joint_rad'][0].numpy(),raw)
    assert ep.data['commands']['saturation_mask'][0,3]
    assert ep.data['commands']['saturation_delta_rad'][0,3]<0


def test_applied_role_contract_is_distinct_from_historical_requested(tmp_path):
    from robot_learning_workbench.data.lerobot import control_contract
    from robot_learning_workbench.data.native import load_catalog
    from dataclasses import replace
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    old=load_catalog(root/'docs/evidence/random-placement/release/mujoco-fixed')
    recording={**old.execution['recording'],'position_target_policy':'saturation_inward_v1','joint_targets_role':'applied'}
    new=replace(old,execution={**old.execution,'recording':recording})
    contract=control_contract(new)
    assert contract['command_processing']=={'position_target_policy':'saturation_inward_v1','training_target':'applied'}
    assert 'command_processing' not in control_contract(old)


def test_summary_error_cannot_skip_real_video_cleanup(tmp_path,monkeypatch):
    from test_simulation_evaluation import prepared_evaluation
    from robot_learning_workbench.engines.mujoco import evaluation,source
    from robot_learning_workbench.data.video import AsyncVideoWriter
    from robot_learning_workbench.data.native import load_catalog
    plan=prepared_evaluation(tmp_path);closed=[];close=AsyncVideoWriter.close
    def summarize(ep):raise KeyError('partial diagnostics fixture')
    def track(writer):
        result=close(writer);closed.append(writer.video_path);return result
    monkeypatch.setattr(source,'command_summary',summarize);monkeypatch.setattr(AsyncVideoWriter,'close',track)
    result=evaluation.run(plan,events=lambda row:None,commands=lambda:())
    assert result.status=='completed' and len(closed)==2
    ep=load_catalog(plan.output_path).episodes[0]
    assert ep.metadata['saturation']['status']=='unavailable'
    assert ep.metadata['category']=='max_steps'


def test_curation_names_requested_and_delta_as_command_radians():
    from robot_learning_workbench.data.curation import _field_semantics
    from types import SimpleNamespace
    catalog=SimpleNamespace(execution={'recording':{'units':'m_rad_s','joint_order':list(JOINTS)}},metadata={},episodes=[])
    for name in ['commands/requested_joint_rad','commands/saturation_delta_rad']:
        info=_field_semantics(catalog,name)
        assert info['unit']=='rad' and info['phase']=='command_for_step_t' and info['joint_order']==list(JOINTS)


def test_teleop_saturates_only_within_approved_motor_model_intersection(tmp_path):
    from test_robot_lifecycle import make,bound
    from robot_learning_workbench.robot.control import command_target
    f,sdk,trace=make(tmp_path);f.connect();_,leader=bound('leader')
    limits={n:e['limits'] for n,e in f.profile['joints'].items()}
    requested={n:sum(pair)/2 for n,pair in leader.command_limits(limits).items()}
    native=leader.urdf_to_calibrated(requested)
    engine=np.array([limits[n] for n in JOINTS]);engine[3,1]=requested['wrist_flex']-.1
    q,goal,info=command_target(native,leader_mapper=leader,follower=f,model_bounds=limits,engine_bounds=engine)
    assert info['saturation']['saturation_mask'][3] and q[3]<=engine[3,1]
    assert 'send' not in trace and not info['hardware_measured']


def test_resume_cannot_reinterpret_historical_requested_as_applied(tmp_path):
    from pathlib import Path
    from robot_learning_workbench.data.native import load_catalog,resume_to,DataError
    old=Path(__file__).resolve().parents[2]/'docs/evidence/random-placement/release/mujoco-fixed'
    execution=load_catalog(old).execution
    changed={**execution,'recording':{**execution['recording'],'position_target_policy':'saturation_inward_v1','joint_targets_role':'applied'}}
    with pytest.raises(DataError) as error:resume_to(old,tmp_path/'changed',changed)
    assert error.value.code=='RESUME_INCOMPATIBLE' and not (tmp_path/'changed').exists()
