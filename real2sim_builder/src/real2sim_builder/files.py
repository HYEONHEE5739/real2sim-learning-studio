"""Existing atomic Builder JSON/YAML files and streaming SHA; no new format."""
import hashlib,json,os,uuid
from pathlib import Path
import yaml

def read(path):
    with Path(path).open() as stream:
        if Path(path).suffix=='.json':return json.load(stream)
        text=stream.read()
    # Capture's atomic JSON writer intentionally uses its existing .yaml name.
    # JSON is YAML-compatible; avoid parsing large Mapping records a second way.
    if text.lstrip().startswith(('{','[')):
        try:return json.loads(text)
        except json.JSONDecodeError:pass  # Ordinary flow-style YAML remains valid.
    return yaml.load(text,Loader=getattr(yaml,'CSafeLoader',yaml.SafeLoader))


def write(path, data, *, json_format=False):
    path = Path(path)
    compact=None
    if json_format:
        try:compact=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        except (TypeError,ValueError):pass  # Preserve legacy YAML-only scalar types without coercion.
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('w') as stream:
            if compact is not None:stream.write(compact+'\n')
            elif path.suffix == '.json':
                json.dump(data, stream, indent=2, allow_nan=False)
            else:
                yaml.dump(data, stream, Dumper=getattr(yaml,'CSafeDumper',yaml.SafeDumper), sort_keys=False, allow_unicode=True)
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

