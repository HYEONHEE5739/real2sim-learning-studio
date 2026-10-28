"""Fixed DLS calculation and Best Effort command eligibility (no engine)."""
import json
from pathlib import Path
import numpy as np
import pytest
from robot_learning_workbench.generation import mimic
from robot_learning_workbench.robot.calibration import JOINTS

ROOT=Path(__file__).resolve().parents[2]

def model_input():
    from scene_contract.package import load_scene
    info=json.loads((ROOT/'docs/evidence/e01-v8-collision/runtime-inputs.json').read_text())
    scene=load_scene(Path(info['package_root'])/'scene.json')
    row=next(r for r in scene.calibration['records'].values() if r['algorithm_id']=='precision_bound_residual')
    path=next(scene.root/f.path for f in scene.files if f.sha256==row['execution_model_sha256'] and f.path.endswith('.urdf'))
    return path,row['execution_model_sha256']

def test_dls_same_pose_and_identity():
    path,sha=model_input();kin=mimic.bind_kinematics(path,model_sha256=sha,joint_order=JOINTS)
    measured=np.zeros(6);goal=kin.forward_kinematics(measured[:5])
    result=mimic.solve_dls(kin,goal,measured,measured,0.,model_sha256=sha,joint_order=JOINTS,frame='robot_base',units='m_rad')
    assert np.array_equal(result.command,measured)
    assert result.diagnostics['converged'] and not result.diagnostics['command_applied']
    assert result.diagnostics['native_result']['iterations']==1
    assert result.identity['solver']=='pinocchio_dls'

@pytest.mark.parametrize('delta,valid',[(np.nextafter(.5,0),True),(.5,True),(np.nextafter(.5,1),False)])
def test_jump_uses_previous_applied_not_measured(delta,valid):
    limits=np.tile([-2.,2.],(6,1));arm=np.array([delta,0,0,0,0.])
    command,reason=mimic.best_effort_candidate(arm,0.,np.zeros(6),limits)
    assert (command is not None)==valid
    assert reason==('' if valid else 'candidate_jump')

@pytest.mark.parametrize('candidate,reason',[(np.zeros(4),'candidate_shape'),(np.array([np.nan,0,0,0,0]),'candidate_nonfinite'),(np.array([3.,0,0,0,0]),'joint_limit_violation')])
def test_invalid_candidates_never_hold_or_clip(candidate,reason):
    command,actual=mimic.best_effort_candidate(candidate,0.,np.zeros(6),np.tile([-2.,2.],(6,1)))
    assert command is None and actual==reason

def test_model_frame_joint_units_rejected():
    path,sha=model_input()
    with pytest.raises(ValueError):mimic.bind_kinematics(path,model_sha256='0'*64,joint_order=JOINTS)
    with pytest.raises(ValueError):mimic.bind_kinematics(path,model_sha256=sha,joint_order=tuple(reversed(JOINTS)))
    kin=mimic.bind_kinematics(path,model_sha256=sha,joint_order=JOINTS)
    for override in ({'frame':'world'},{'units':'degrees'},{'model_sha256':'0'*64},{'joint_order':tuple(reversed(JOINTS))}):
        args=dict(model_sha256=sha,joint_order=JOINTS,frame='robot_base',units='m_rad');args.update(override)
        with pytest.raises(ValueError):mimic.solve_dls(kin,np.eye(4),np.zeros(6),np.zeros(6),0.,**args)

def test_solver_invalid_candidate_is_structured_attempt_failure():
    path,sha=model_input();kin=mimic.bind_kinematics(path,model_sha256=sha,joint_order=JOINTS)
    q=np.zeros(6);previous=q.copy();previous[0]=.51
    with pytest.raises(mimic.IKFailure) as error:
        mimic.solve_dls(kin,kin.forward_kinematics(q[:5]),q,previous,0.,model_sha256=sha,joint_order=JOINTS,frame='robot_base',units='m_rad')
    assert error.value.diagnostics['failure_reason']=='candidate_jump'
    assert not error.value.diagnostics['command_applied']
    assert np.array_equal(previous,np.array([.51,0,0,0,0,0]))


def test_valid_unconverged_candidate_is_eligible_not_applied(monkeypatch):
    path,sha=model_input();kin=mimic.bind_kinematics(path,model_sha256=sha,joint_order=JOINTS)
    q=np.zeros(6);goal=kin.forward_kinematics(q[:5]);goal[0,3]+=1.
    monkeypatch.setattr(kin,'inverse_kinematics',lambda *args,**kwargs:(np.zeros(5),False,{'iterations':200}))
    result=mimic.solve_dls(kin,goal,q,q,0.,model_sha256=sha,joint_order=JOINTS,frame='robot_base',units='m_rad')
    assert result.command is not None and not result.diagnostics['common_pose_passed']
    assert not result.diagnostics['command_applied'] and not result.diagnostics['converged']

@pytest.mark.parametrize('offset,valid',[(np.nextafter(1e-7,0),True),(1e-7,True),(np.nextafter(1e-7,1),False)])
def test_best_effort_limit_epsilon_is_not_engine_clipping(offset,valid):
    bounds=np.tile([0.,2.],(6,1));candidate=np.array([-offset,0,0,0,0.])
    result,reason=mimic.best_effort_candidate(candidate,0.,np.zeros(6),bounds)
    assert (result is not None)==valid
    if valid:assert result[0]==-offset
    else:assert reason=='joint_limit_violation'


def test_actual_dls_unreachable_target_keeps_valid_best_effort_candidate():
    path,sha=model_input();kin=mimic.bind_kinematics(path,model_sha256=sha,joint_order=JOINTS)
    measured=np.zeros(6);target=kin.forward_kinematics(measured[:5]);target[0,3]+=2.
    arm,converged,_=kin.inverse_kinematics(measured[:5],target,**mimic.DLS_PARAMETERS)
    assert not converged
    previous=np.r_[arm,0.]
    result=mimic.solve_dls(kin,target,measured,previous,0.,model_sha256=sha,joint_order=JOINTS,frame='robot_base',units='m_rad')
    np.testing.assert_array_equal(result.command[:5],arm)
    assert result.diagnostics['candidate_valid'] and not result.diagnostics['converged']
    assert not result.diagnostics['common_pose_passed'] and not result.diagnostics['command_applied']
    np.testing.assert_array_equal(result.diagnostics['measured_joint_rad'],measured)


def test_bound_dls_identity_is_required_unchanged_for_native_continuation(tmp_path):
    import copy
    from robot_learning_workbench.data.native import NativeRun,resume_to,DataError
    from test_native_dataset import execution
    path,sha=model_input();kin=mimic.bind_kinematics(path,model_sha256=sha,joint_order=JOINTS)
    config=execution();config['ik']=kin.identity
    with NativeRun(tmp_path/'original',config) as owner:
        segment=owner.segment('failed-attempt');claim=owner.claim_attempt(segment)
        segment.record_attempt(claim,status='ik_failure',diagnostics={'fixture':'invalid candidate; no completed Episode fabricated'});segment.commit()
    same=resume_to(tmp_path/'original',tmp_path/'same',config);same.close()
    for key,value in [('solver','scipy_ls'),('policy','strict'),('code_sha256','0'*64),('seed_reference','previous_command')]:
        changed=copy.deepcopy(config);changed['ik'][key]=value
        with pytest.raises(DataError) as error:resume_to(tmp_path/'original',tmp_path/key,changed)
        assert error.value.code=='RESUME_INCOMPATIBLE' and not (tmp_path/key).exists()


def test_nonnumeric_solver_candidate_is_diagnostic_failure_not_fk_error(monkeypatch):
    path,sha=model_input();kin=mimic.bind_kinematics(path,model_sha256=sha,joint_order=JOINTS)
    q=np.zeros(6);goal=kin.forward_kinematics(q[:5])
    monkeypatch.setattr(kin,'inverse_kinematics',lambda *a,**k:(np.array(['bad']*5),False,{'iterations':1,'position_error':float('inf')}))
    with pytest.raises(mimic.IKFailure) as error:
        mimic.solve_dls(kin,goal,q,q,0.,model_sha256=sha,joint_order=JOINTS,frame='robot_base',units='m_rad')
    assert error.value.diagnostics['failure_reason']=='candidate_nonfinite'
    json.dumps(error.value.diagnostics,allow_nan=False)


def test_native_ik_array_names_dtype_and_units_match_b02():
    path,sha=model_input();kin=mimic.bind_kinematics(path,model_sha256=sha,joint_order=JOINTS);q=np.zeros(6)
    result=mimic.solve_dls(kin,kin.forward_kinematics(q[:5]),q,q,0.,model_sha256=sha,joint_order=JOINTS,frame='robot_base',units='m_rad')
    row=mimic.ik_record(result,.01,applied=True)
    assert row['ik_duration_ms']==10. and row['ik_iterations_or_evaluations']==1
    assert row['ik_position_error_mm']==result.diagnostics['position_error_m']*1000
    assert row['ik_orientation_error_deg']==np.degrees(result.diagnostics['rotation_error_rad'])
    assert np.asarray(row['ik_iterations_or_evaluations']).dtype==np.int64
    assert np.asarray(row['ik_converged']).dtype==np.bool_
    assert np.asarray(row['candidate_joint_rad']).dtype==np.float64
    assert row['command_applied'] and not result.diagnostics['command_applied']
