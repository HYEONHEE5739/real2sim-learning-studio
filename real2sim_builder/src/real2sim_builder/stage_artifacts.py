"""Typed, byte-verified stage records within the existing Candidate lifecycle.

This module only owns artifact validation and identities. Execution remains in
automation.py; model runtimes remain child processes.
"""
from dataclasses import asdict, dataclass, field
from pathlib import Path
import hashlib
import json
from .files import sha


STAGE_NAMES = (
    'RGB preparation', 'DA3 Nested depth', 'Canonical frame / SAM3 support',
    'World frame / metric QA', 'Scene decomposition', 'Object RGBA preparation',
    'Codex / Blender meshes', 'Mesh pose matching', 'Optional articulation',
    'Scene compilation', 'Collision / properties', 'Physics stabilization',
    'USD package', 'Simulator / sensor integration',
)
STATUSES = {'COMPLETE', 'NEEDS_RUNTIME', 'NEEDS_MORE_DATA', 'NEEDS_REVIEW',
            'FAILED', 'STOPPED', 'NOT_SUPPORTED'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode()).hexdigest()


def cache_key(stage_id, inputs, config, runtime):
    return digest([stage_id, inputs, config, runtime])


def _plain_file(path):
    path = Path(path).absolute()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('Artifact symlink is forbidden')
    if not path.is_file():
        raise ValueError('Artifact integrity: missing file ' + str(path))
    return path.resolve()


def manifest(paths, data=None):
    files = []
    seen = set()
    for path in paths:
        path = _plain_file(path)
        if str(path) in seen:
            continue
        seen.add(str(path))
        files.append({'path': str(path), 'sha256': sha(path)})
    result = {'files': files, 'data': data or {}}
    digest(result)  # Reject NaN/non-serializable metadata before publishing.
    return result


def verify_manifest(record, *, output_root=None):
    if not isinstance(record, dict) or set(record) != {'files', 'data'}:
        raise ValueError('Expected an explicit file/data manifest')
    seen = set()
    for row in record['files']:
        path = _plain_file(row['path'])
        if output_root is not None and not path.is_relative_to(Path(output_root).resolve()):
            raise ValueError('Artifact output outside stage attempt')
        if str(path) in seen or sha(path) != row['sha256']:
            raise ValueError('Artifact integrity mismatch: ' + str(path))
        seen.add(str(path))
    digest(record)


@dataclass
class StageArtifact:
    stage_id: int
    status: str
    input_manifest: dict
    input_sha256: str
    output_manifest: dict
    output_sha256: str
    runtime_identity: dict
    config_identity: str
    coordinate_frame: str
    units: dict
    provenance: dict
    warnings: list = field(default_factory=list)
    needs: list = field(default_factory=list)
    error: dict | None = None
    schema: str = 'real2sim.stage-artifact/1'

    @classmethod
    def create(cls, stage_id, status, inputs, outputs, *, runtime_identity,
               config, coordinate_frame='not_applicable', warnings=(), needs=(), error=None):
        return cls(stage_id, status, inputs, digest(inputs), outputs, digest(outputs),
                   runtime_identity, digest(config), coordinate_frame,
                   {'length': 'm', 'angle': 'rad'},
                   {'execution': 'mock' if runtime_identity.get('kind') == 'mock' else 'real',
                    'physical_verified': False}, list(warnings), list(needs), error)

    def validate(self, output_root):
        if type(self.stage_id) is not int or not 1 <= self.stage_id <= 14:
            raise ValueError('Invalid stage ID')
        if self.schema != 'real2sim.stage-artifact/1' or self.status not in STATUSES:
            raise ValueError('Invalid stage artifact schema/status')
        if not self.runtime_identity or not self.coordinate_frame:
            raise ValueError('Runtime and coordinate provenance required')
        verify_manifest(self.input_manifest)
        verify_manifest(self.output_manifest, output_root=output_root)
        if digest(self.input_manifest) != self.input_sha256 or digest(self.output_manifest) != self.output_sha256:
            raise ValueError('Artifact integrity digest mismatch')
        if self.status == 'COMPLETE' and not self.output_manifest['files']:
            raise ValueError('A complete stage must retain an actual output artifact')
        if self.provenance.get('execution') not in ('real', 'mock'):
            raise ValueError('Actual/mock execution provenance required')
        return self

    def to_dict(self):
        return asdict(self)


class StageNeeds(RuntimeError):
    def __init__(self, status, message, *, code=None):
        if status not in STATUSES - {'COMPLETE'}:
            raise ValueError('Invalid stage stop status')
        self.status = status
        self.code = code
        super().__init__(message)
