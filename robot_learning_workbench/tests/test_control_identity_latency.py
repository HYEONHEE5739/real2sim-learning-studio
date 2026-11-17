"""Fresh USB identity checks must inspect the connected port, not all devices.

Memory SDK objects only: fake PySerial sysfs metadata never opens a real port.
Discovery remains the explicit selection-time uniqueness check.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_robot_lifecycle import make
from robot_learning_workbench.robot import registration


def metadata_reader(monkeypatch,follower):
    from serial.tools import list_ports_linux
    follower.usb_identity={'serial':'memory-serial','vid':0x1234,'pid':0x5678}
    actual=SimpleNamespace(device=follower.bus.port,serial_number='memory-serial',vid=0x1234,pid=0x5678)
    calls=[]
    def selected(port):
        calls.append(str(port))
        return actual
    def inventory():
        pytest.fail('A control-cycle identity check enumerated unrelated serial devices and cameras')
    monkeypatch.setattr(list_ports_linux,'SysFS',selected)
    monkeypatch.setattr(registration,'discover',inventory)
    return actual,calls


def test_control_identity_reads_only_the_selected_port_without_connecting(tmp_path,monkeypatch):
    follower,_,trace=make(tmp_path)
    _,calls=metadata_reader(monkeypatch,follower)
    follower._check_identity()
    assert calls==[str(Path(follower.bus.port).resolve())]
    assert not trace and not follower.bus.is_connected


@pytest.mark.parametrize('field,replacement',[
    ('serial_number','changed-device'),('vid',0x9999),('pid',0x9999),('serial_number',None),
])
def test_selected_port_identity_is_fresh_and_fail_closed(tmp_path,monkeypatch,field,replacement):
    follower,_,trace=make(tmp_path)
    actual,calls=metadata_reader(monkeypatch,follower)
    follower._check_identity()
    setattr(actual,field,replacement)
    with pytest.raises(ValueError,match='USB identity'):
        follower._check_identity()
    assert len(calls)==2, 'Identity changes must not be hidden by a time-based cache'
    assert not trace and not follower.bus.is_connected


def test_selection_still_rejects_ambiguous_usb_identity():
    identity={'serial':'same','vid':1,'pid':2}
    rows=[dict(path=port,**identity)for port in('/memory/a','/memory/b')]
    with pytest.raises(ValueError,match='not unique'):
        registration.resolve_serial(identity,inventory=rows)


def test_unrelated_device_inventory_latency_cannot_stall_an_active_control_cycle(tmp_path,monkeypatch):
    """Replay a 220ms inventory stall with a deterministic clock, never sleeping.

    The currently connected ports stay unchanged. A fresh selected-port check
    still works while unrelated global device discovery is expensive.
    """
    import time
    from serial.tools import list_ports_linux
    from test_supervised_session import controller
    control,leader,follower,_,_,_=controller(tmp_path)
    try:
        control.start(command_id='explicit_start')
        clock=[time.monotonic_ns()];inventories=[];ports={}
        for number,device in enumerate((leader,follower)):
            device.usb_identity={'serial':'memory-'+str(number),'vid':1,'pid':2}
            ports[str(Path(device.bus.port).resolve())]=SimpleNamespace(
                device=device.bus.port,serial_number=device.usb_identity['serial'],vid=1,pid=2)
        def expensive_inventory():
            if not inventories:clock[0]+=220_000_000
            inventories.append(True)
            return {'serial':[dict(path=p.device,serial=p.serial_number,vid=p.vid,pid=p.pid)for p in ports.values()],
                    'cameras':[]}
        monkeypatch.setattr(registration,'discover',expensive_inventory)
        monkeypatch.setattr(list_ports_linux,'SysFS',lambda port:ports[str(port)])
        monkeypatch.setattr(time,'monotonic_ns',lambda:clock[0])
        row=control.tick()
        assert row['sequence']==1 and control.active
        assert not inventories,'An already-selected device must not enumerate unrelated hardware during control'
    finally:
        control.stop();leader.close();follower.close()
