"""Existing atomic Builder JSON/YAML files and streaming SHA; no new format."""
import hashlib,json,os,uuid
from pathlib import Path
import yaml

def read(path):
    with Path(path).open() as stream:
        return yaml.safe_load(stream)


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('w') as stream:
            if path.suffix == '.json':
                json.dump(data, stream, indent=2, allow_nan=False)
            else:
                yaml.safe_dump(data, stream, sort_keys=False, allow_unicode=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()

