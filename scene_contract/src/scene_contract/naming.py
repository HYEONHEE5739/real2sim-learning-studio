"""Readable owned paths; integrity digests and protocol identities stay metadata."""
from pathlib import Path
import hashlib
import os
import re
import shutil
import tempfile


def readable_name(name):
    if not isinstance(name,str)or not name.strip():raise ValueError('A nonempty display name is required')
    return re.sub(r'[\W_]+','-',name.casefold(),flags=re.UNICODE).strip('-')or'item'


def available_path(parent,name,*,separator='-',start=2,digits=0):
    parent=Path(parent);path=Path(name)
    if path.name!=name or name in('.','..')or'\\'in name:raise ValueError('One non-path name is required')
    result=parent/name;index=start
    while result.exists()or result.is_symlink():
        result=parent/(path.stem+separator+str(index).zfill(digits)+path.suffix);index+=1
    return result


def reserve_directory(parent,name):
    parent=Path(parent);parent.mkdir(parents=True,exist_ok=True);name=readable_name(name)
    while True:
        result=available_path(parent,name)
        try:result.mkdir();return result
        except FileExistsError:continue


def copy_named(source,parent):
    source=Path(source);parent=Path(parent);parent.mkdir(parents=True,exist_ok=True)
    def digest(path):
        h=hashlib.sha256()
        with path.open('rb')as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
        return h.digest()
    expected=digest(source)
    for file in parent.iterdir():
        if file.is_file()and not file.is_symlink()and file.stat().st_size==source.stat().st_size and digest(file)==expected:return file
    with tempfile.NamedTemporaryFile(dir=parent,prefix='.copy-',delete=False)as temporary:
        pending=Path(temporary.name)
    try:
        shutil.copy2(source,pending)
        while True:
            target=available_path(parent,source.name,separator='_')
            try:os.link(pending,target);return target
            except FileExistsError:continue
    finally:pending.unlink(missing_ok=True)


def numbered_path(parent,prefix,*,digits=3,suffix=''):
    parent=Path(parent);index=1
    while True:
        path=parent/(prefix+'_'+str(index).zfill(digits)+suffix)
        if not path.exists()and not path.with_suffix('.yaml').exists()and not path.with_suffix('').exists():return path
        index+=1


def check_storage_available(workspace):
    marker=Path(workspace)/'.storage-migration-in-progress'
    if marker.exists():
        import json
        try:owner=json.loads(marker.read_text()).get('pid')
        except (ValueError,OSError):owner=None
        if owner==os.getpid():return
        raise RuntimeError('Storage migration in progress; wait for verification or restore before opening this Workspace')
