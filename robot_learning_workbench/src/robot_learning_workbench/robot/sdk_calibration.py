"""User-supervised official SDK setup, separate from read-only Capture Sessions."""
from pathlib import Path
import time,uuid,builtins
from .devices import serial_lease


def validate_spec(spec,config_root,approved):
    if approved is not True:raise ValueError('Explicit on-site calibration approval required')
    root=Path(config_root).resolve();cal=Path(spec['calibration_path']).resolve()
    if root.parent.name!='devices'or not cal.is_relative_to(root/'calibration'):raise ValueError('Calibration must belong to the selected local device configuration')
    if cal.exists():raise ValueError('Preserve existing SDK Calibration; select a new device configuration to create a new revision')
    if spec.get('role')not in('leader','follower')or not spec.get('usb_identity',{}).get('serial'):raise ValueError('SO101 role and stable USB identity required')
    sdk=spec['sdk']
    if Path(sdk['calibration_dir']).resolve()!=cal.parent or cal.name!=sdk['id']+'.json':raise ValueError('SDK calibration location mismatch')


def validate(plan):
    from ..recipe import _plain
    file=Path(plan.resolved_inputs['device_profile']['path']);spec=_plain(plan.input_documents['device_profile'])
    validate_spec(spec,file.parent,plan.effective_settings['execution']['confirm_on_site']);return spec


def calibrate(device,prompt,range_enter):
    """Adapt official interactive prompts to R03; SDK procedure itself stays unchanged."""
    from unittest.mock import patch
    try:
        device.bus.connect()  # Do not call official connect/configure.
        import lerobot.motors.motors_bus as official_bus
        with patch.object(builtins,'input',prompt),patch.object(official_bus,'enter_pressed',range_enter):device.calibrate()
    finally:
        device.bus.disconnect(disable_torque=False)


def run(plan,*,events,commands):
    from ..recipe import verify_prepared_inputs
    from ..run import StageResult
    from ..data.native import atomic_json,file_sha256
    from .offline import sdk_configuration
    from .registration import resolve_serial
    verify_prepared_inputs(plan);spec=validate(plan);spec['sdk']['port']=resolve_serial(spec['usb_identity']);cfg=sdk_configuration(spec)
    if spec['role']=='follower':
        from lerobot.robots.so101_follower.so101_follower import SO101Follower
        device=SO101Follower(cfg)
    else:
        from lerobot.teleoperators.so101_leader.so101_leader import SO101Leader
        device=SO101Leader(cfg)
    plan.output_path.mkdir();deadline=time.monotonic()+plan.effective_settings['execution'].get('timeout_s',600);cancelled=False;error=None
    def ack(c,status,reason=None):events({'kind':'command_ack','payload':{'command_id':c['command_id'],'status':status,**({'reason':reason}if reason else{})}})
    current=None
    def poll(text):
        nonlocal current
        if current is None:
            current=uuid.uuid4().hex;events({'kind':'status','payload':{'progress':{'calibration_prompt':{'id':current,'text':text,'role':spec['role']}}}})
        if time.monotonic()>=deadline:raise TimeoutError('On-site calibration prompt timed out')
        batch=list(commands())
        if any(c['kind']=='cancel'for c in batch):
            for c in batch:ack(c,'completed'if c['kind']=='cancel'else'rejected','Calibration cancelled')
            raise InterruptedError('User cancelled calibration; inspect hardware before retry')
        result=None
        for c in batch:
            if c['kind']=='calibration_response'and c['payload']['prompt_id']==current and result is None:
                result=c['payload']['response'];ack(c,'completed')
            else:ack(c,'rejected','Respond to the current calibration prompt')
        if result is not None:current=None
        return result
    def prompt(text):
        while True:
            response=poll(text)
            if response is not None:return response
            time.sleep(.05)
    def range_enter():return poll('Torque is disabled. Move each joint manually through its safe range. Finish recording only after all ranges have been observed; press Continue to finish.')is not None
    try:
        with serial_lease(cfg.port):
            prompt('직접 감독하며 공식 SDK Calibration을 시작할 준비가 됐으면 계속하세요. Torque Disable 및 Homing/Range 레지스터 쓰기가 이어집니다.')
            calibrate(device,prompt,range_enter)
        cal=Path(spec['calibration_path'])
        if not cal.is_file():raise ValueError('Official SDK did not save its Calibration file')
        digest=file_sha256(cal)
    except InterruptedError as exc:cancelled=True;error=str(exc);digest=None
    except Exception as exc:error=str(exc);raise
    finally:atomic_json(plan.output_path/'sdk-calibration-report.json',{'role':spec['role'],'error':error,'calibration_path':spec['calibration_path'],'calibration_sha256':file_sha256(spec['calibration_path'])if Path(spec['calibration_path']).is_file()else None,'physical_verified':False,'procedure':'official SDK calibrate; manually supervised; torque may be disabled and calibration registers written'})
    return StageResult('cancelled'if cancelled else'completed',(str(plan.output_path),),0,{'sdk_calibration_created':not cancelled,'sha256':digest,'physical_verified':False})
