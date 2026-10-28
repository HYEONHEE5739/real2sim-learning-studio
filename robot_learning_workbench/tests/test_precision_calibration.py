"""B03 read-only profiles and arithmetic only: no device or model export."""
import copy
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import pytest
from robot_learning_workbench.robot import calibration as c

ROOT=Path(__file__).resolve().parents[2]
B03=ROOT/'docs/evidence/b03'
INV=json.loads((B03/'inventory.json').read_text())
OLD=ROOT/'docs/evidence/b01/runspace/soarm101_lab/outputs/b01_historical_models/3b676464eb11410752707021f9d07b988439b46e37d5605cdbfe9508de14e5dd.urdf'
CURRENT=Path('/home/hyeonhee/soarm_isaaclab/soarm101_lab/outputs/real2sim/environments/scene2_builder/v8/assets/SO101/urdf/so101_isaaclab.urdf')

def bound(role):
    saved=json.loads(Path(INV['roles'][role]['profile_path']).read_text())
    effective=c.profile_for_model(saved,INV['roles'][role]['effective_model_sha256'],source_model=OLD.read_bytes(),execution_model=CURRENT.read_bytes())
    return saved,c.PrecisionMapper(effective)

@pytest.mark.parametrize('role',['leader','follower'])
def test_b03_sixty_samples_and_mapping_identity_exact(role):
    saved,mapper=bound(role); before=copy.deepcopy(saved)
    rows=json.loads((B03/'calibration-probes.json').read_text())['roles'][role]
    for fraction in (.05,.25,.5,.75,.95):
        selected=[s for s in rows['samples'] if s['fraction']==fraction]
        q={s['joint']:s['requested_rad'] for s in selected}
        native=mapper.urdf_to_calibrated(q); measured=mapper.calibrated_to_urdf(native)
        assert list(measured)==list(c.JOINTS)
        for s in selected:
            assert measured[s['joint']]==s['actual_rad']
            assert c.raw_from_native(native[s['joint']],mapper.profile['joints'][s['joint']]['motor'])==s['raw']
    assert saved==before
    assert mapper.metadata()['sha256']==INV['roles'][role]['mapping_sha256']

@pytest.mark.parametrize('mode',['DEGREES','RANGE_0_100'])
@pytest.mark.parametrize('drive',[0,1])
def test_raw_native_homing_not_applied_twice(mode,drive):
    spec={'calibration':{'range_min':200,'range_max':3800,'drive_mode':drive,'homing_offset':1133},'resolution':4096,'mode':mode,'apply_drive_mode':True}
    for raw in (200,2050,3800):
        native=c.native_from_raw(raw,spec)
        assert c.raw_from_native(native,spec)==pytest.approx(raw,abs=1e-12)
        if mode=='DEGREES': assert native==(raw-2000)*360/4095


def test_half_turn_branch_and_invalid_normalization():
    with pytest.raises(ValueError,match='half-turn'):c.unwrap(2048,0,4096)
    with pytest.raises(ValueError):c.native_from_raw(1,{'calibration':{'range_min':0,'range_max':100},'resolution':4096,'mode':'UNKNOWN','apply_drive_mode':False})

@pytest.mark.parametrize('role',['leader','follower'])
def test_observation_outside_limits_is_retained_but_command_rejected(role):
    _,mapper=bound(role); native=mapper.urdf_to_calibrated({n:sum(v)/2 for n,v in mapper.command_limits({n:e['limits'] for n,e in mapper.profile['joints'].items()}).items()})
    entry=mapper.profile['joints']['shoulder_pan']; raw={n:round(c.raw_from_native(native[n],e['motor'])) for n,e in mapper.profile['joints'].items()}
    raw['shoulder_pan']=round(entry['anchor_raw']+(entry['limits'][1]+.01-entry['reference_angle_rad'])/entry['rad_per_count'])
    native['shoulder_pan']=c.native_from_raw(raw['shoulder_pan'],entry['motor'])
    observed=mapper.calibrated_to_observation(native,raw=raw)
    assert observed['shoulder_pan']>entry['limits'][1]
    with pytest.raises(ValueError):mapper.urdf_to_calibrated(observed)
    with pytest.raises(ValueError,match='mismatch'):mapper.calibrated_to_observation({**native,'shoulder_pan':native['shoulder_pan']+1},raw=raw)

@pytest.mark.parametrize('bad',['schema','joint_order','profile','hash'])
def test_tampered_mapping_is_never_defaulted(bad):
    _,m=bound('follower'); meta=m.metadata()
    if bad=='schema':meta['schema']='future/2'
    elif bad=='joint_order':meta['joint_order'].reverse();meta['sha256']=c.fingerprint({k:v for k,v in meta.items() if k!='sha256'})
    elif bad=='profile':meta['profile']['joints']['gripper']['rad_per_count']+=.1;meta['sha256']=c.fingerprint({k:v for k,v in meta.items() if k!='sha256'})
    else:meta['sha256']='0'*64
    with pytest.raises(ValueError):c.mapper_from_metadata(meta)

@pytest.mark.parametrize('bad',['missing','hash','axis','limits'])
def test_model_binding_needs_full_correct_evidence(bad):
    saved,_=bound('follower');old=OLD.read_bytes();new=CURRENT.read_bytes();h=hashlib.sha256(new).hexdigest()
    if bad=='missing':old=None
    if bad=='hash':h='0'*64
    if bad=='axis':new=new.replace(b'axis xyz="0 0 1"',b'axis xyz="0 1 0"',1);h=hashlib.sha256(new).hexdigest()
    if bad=='limits':saved['joints']['gripper']['limits'][0]-=.1
    with pytest.raises(ValueError):c.profile_for_model(saved,h,source_model=old,execution_model=new)

@pytest.mark.parametrize('bad',[math.nan,math.inf,True,'1'])
def test_external_joint_packets_reject_non_numeric_values(bad):
    _,mapper=bound('follower');q=dict.fromkeys(c.JOINTS,0.);q['elbow_flex']=bad
    with pytest.raises(ValueError):mapper.calibrated_to_observation(q)
    with pytest.raises(ValueError):mapper.urdf_to_calibrated(q)


def test_profile_load_identity_and_no_implicit_active_pointer(tmp_path):
    saved,_=bound('follower');path=tmp_path/'profile.json';path.write_text(json.dumps(saved))
    loaded=c.load_profile(path,expected_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),role='follower',identity=saved['identity'])
    assert loaded==saved
    with pytest.raises(ValueError):c.load_profile(path,role='leader')
    with pytest.raises(ValueError):c.load_profile(path,expected_sha256='0'*64)
    with pytest.raises(ValueError):c.load_profile(path,identity={**saved['identity'],'port':'other'})
    path.write_text('{"schema":1,"schema":2}')
    with pytest.raises(ValueError):c.load_profile(path)


def test_scene_encoder_binding_uses_registered_evidence_and_rejects_baked(tmp_path):
    from dataclasses import asdict
    from scene_contract.package import load_scene,FileEntry
    saved,m=bound('follower')
    for name,raw in [('old.urdf',OLD.read_bytes()),('current.urdf',CURRENT.read_bytes()),('follower.json',json.dumps(m.metadata()).encode())]:(tmp_path/name).write_bytes(raw)
    record={'kind':'encoder_mapping','target':'robot','algorithm_id':'so101_precision_v1','joint_order':list(c.JOINTS),
      'source_model_sha256':saved['urdf_sha256'],'execution_model_sha256':m.profile['urdf_sha256'],'parameters_file':'follower.json',
      'application':{'mode':'runtime','phase':'device_observation','input_space':'follower_homed_count','output_space':'model_rad','order_index':0},
      'validation':{'physical_verified':False},'evidence_ids':[]}
    scene={'schema_version':1,'scene_id':'ro_fixture','revision':'test','units':{'length':'m','angle':'rad','time':'s','mass':'kg'},
      'frames':{'world':{'parent':None,'state':'reference','T_parent_from_frame':np.eye(4).tolist()}},'objects':{},'robot':{'frame_id':'world','joint_order':list(c.JOINTS)},
      'cameras':{},'supports':{},'engines':{},'validation':{},'calibration':'calibration.json','manifest':'manifest.json'}
    (tmp_path/'scene.json').write_text(json.dumps(scene));(tmp_path/'calibration.json').write_text(json.dumps({'schema_version':1,'records':{'encoder':record},'evidence':{}}))
    entries=[asdict(FileEntry(p.name,p.stat().st_size,hashlib.sha256(p.read_bytes()).hexdigest())) for p in sorted(tmp_path.iterdir())]
    (tmp_path/'manifest.json').write_text(json.dumps({'schema_version':1,'files':entries}))
    package=load_scene(tmp_path/'scene.json')
    new=c.mapper_from_scene(package,'encoder',role='follower',phase='device_observation')
    assert new.metadata()==m.metadata()
    with pytest.raises(ValueError):c.mapper_from_scene(package,'encoder',role='leader',phase='device_observation')
    with pytest.raises(ValueError):c.mapper_from_scene(package,'encoder',role='follower',phase='device_command')
    (tmp_path/'current.urdf').write_bytes(b'changed')
    with pytest.raises(ValueError):c.mapper_from_scene(package,'encoder',role='follower',phase='device_observation')

@pytest.mark.parametrize('slope_sign',[1,-1])
def test_fit_review_validation_are_separate_and_coefficients_checked(slope_sign):
    _,m=bound('follower');spec=m.profile['joints']['shoulder_pan']['motor']
    refs=[{'joint':'shoulder_pan','raw':raw,'angle_rad':math.radians(angle*slope_sign),'split':split,'calibration_hash':spec['calibration_hash']} for raw,angle,split in [(1500,0,'train'),(2500,90,'train'),(2000,45,'validation')]]
    fitted=c.fit_joint(refs,spec,'shoulder_pan',[-2,2]);assert fitted['status']=='CANDIDATE_NEEDS_VALIDATION'
    reviewed=c.review_joint(fitted);assert reviewed['status']=='REVIEWED_MANUAL' and not reviewed['physical_verified']
    validated=c.validate_joint(fitted);assert validated['status']=='VALIDATED_MANUAL'
    assert not validated['physical_verified']
    one=c.fit_joint(refs[:1],spec,'shoulder_pan',[-2,2]);assert one['status']=='OFFSET_ONLY_NEEDS_MORE_DATA'
    assert c.validate_joint(one)['status']=='NEEDS_MORE_DATA'
    meta={**m.profile,'joints':{'shoulder_pan':reviewed}}
    c.PrecisionMapper(meta)
    meta=copy.deepcopy(meta);meta['joints']['shoulder_pan']['anchor_raw']+=1
    with pytest.raises(ValueError):c.PrecisionMapper(meta)


def test_review_revision_preserves_original_and_never_claims_physical_accuracy(tmp_path):
    profile=Path(INV['roles']['follower']['profile_path']);original=profile.read_bytes()
    target=tmp_path/'reviewed.json'
    result=c.review_revision(profile,target)
    saved=c.load_profile(target)
    assert result['physical_verified'] is False and saved['physical_verified'] is False
    assert saved['parent_sha256']==hashlib.sha256(original).hexdigest()
    assert profile.read_bytes()==original and all(e['status']=='REVIEWED_MANUAL'for e in saved['joints'].values())
    assert result['new_independent_reference'] is False
    with pytest.raises(FileExistsError):c.review_revision(profile,target)
