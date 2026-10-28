"""Builder Project lifecycle and public authoring API; role modules own algorithms."""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import time
import uuid
from .scene import (
    WORKFLOW_SCHEMA,
    GEOMETRY_CONSTRAINT_SCHEMA,
    value,
    transform,
    empty,
    checked_value,
    cameras_audited,
    camera_calibration_signature,
    identifier,
    local_path,
    validate,
    frame_world,
    world_pose,
    uncertainties,
    validate_workflow,
    geometry_constraint_metrics,
    validate_geometry_constraints,
    validate_horizontal_layout,
    SCHEMA,
    SOURCES,
    ROLES,
)
from .files import read, write, sha
from .evidence import (
    copy_input,
    add_image,
    add_video,
    extract_videos,
    asset_importer,
    import_scene,
    import_metadata,
    import_robot,
    import_reference,
    add_brief,
    PROVENANCE,
)
from .capture import (
    mapping_contract,
    load_session,
    align,
    _import_session,
    observation_scene,
    import_session,
    validate_joint_units,
    validate_model_files,
    legacy_static_reasons,
    load_snapshots,
    import_snapshots,
    import_paired,
    CAPTURE_SCHEMA,
)
from .editing import preserve, check_scope, apply, PROTECTED
from .cameras import render_pose, blender_intrinsics, OPTICAL_TO_RENDER, CLIP, CONVENTIONS
from .candidate import exclusive, Candidate, rollback, restore_report, nonregression


STAGES = ['ANALYZE', 'CAMERA & SCALE', 'GEOMETRY', 'VISUAL', 'PHYSICS', 'VALIDATION', 'EXPORT']


STATUSES = {'DRAFT', 'RUNNING', 'PAUSED', 'STOPPED', 'ACCEPTED', 'NEEDS_MORE_DATA', 'FAILED'}


class Project:

    def __init__(self, root, *, read_only=None):
        self.root = Path(root).resolve()
        self.info = read(self.root / 'project.yaml')
        if not isinstance(self.info, dict) or self.info.get('schema') != 'real2sim.project/1':
            raise ValueError('Expected an existing real2sim.project/1 project')
        marker = self.root / 'working/owner.json'
        owned = marker.is_file() and read(marker) == {'schema':'real2sim.builder-owner/1','project_id':self.info['id']}
        if read_only is False and not owned:
            raise PermissionError('Unmarked source projects are read-only; clone_project into a new workspace first')
        self.read_only = not owned if read_only is None else bool(read_only)

    def require_writable(self):
        if self.read_only:
            raise PermissionError('Project is open for read-only inspection; create an isolated copy before editing')

    @classmethod
    def create(cls, projects, name):
        if not name.strip():
            raise ValueError('Scene name required')
        slug = re.sub('[^a-z0-9]+', '-', name.lower()).strip('-') or 'scene'
        root = Path(projects).resolve() / (slug + '-' + uuid.uuid4().hex[:8])
        root.mkdir(parents=True, exist_ok=False)
        for child in ('input', 'input/assets', 'working', 'scratch', 'exports'):
            (root / child).mkdir()
        write(root / 'project.yaml', {'schema': 'real2sim.project/1', 'id': root.name, 'name': name, 'created_at': time.time()})
        write(root / 'input/evidence.yaml', {'images': [], 'videos': [], 'landmarks': [], 'masks': [], 'motions': []})
        write(root / 'working/state.json', {'status': 'DRAFT', 'stage': None, 'iteration': 0, 'decision': 'CONTINUE', 'metrics': {}, 'needs': []})
        write(root/'working/owner.json', {'schema':'real2sim.builder-owner/1','project_id':root.name})
        return cls(root)

    @property
    def evidence(self):
        return read(self.root / 'input/evidence.yaml')

    @property
    def state(self):
        return read(self.root / 'working/state.json')

    @property
    def scene(self):
        return read(self.root / 'working/current_scene.yaml')

    def update(self, **fields):
        self.require_writable()
        state = {**self.state, **fields, 'updated_at': time.time()}
        if state['status'] not in STATUSES:
            raise ValueError('Invalid run status')
        write(self.root / 'working/state.json', state)
        with (self.root / 'history.jsonl').open('a') as stream:
            stream.write(json.dumps(state, allow_nan=False) + '\n')
        return state

    def control(self, command):
        self.require_writable()
        if command not in ('pause', 'resume', 'stop'):
            raise ValueError('Unknown command')
        write(self.root / 'working/control.json', {'command': command})

    def invalidate(self):
        self.require_writable()
        if self.state['status'] not in ('DRAFT', 'RUNNING', 'PAUSED'):
            self.update(status='DRAFT', stage=None, decision='CONTINUE', needs=[], export=None, error=None, task='Inputs changed; validation must be rerun')

    def signature(self, scene=None):
        """Bind a validation decision to the exact scene and local evidence bytes."""
        scene = scene if scene is not None else self.scene
        evidence = self.evidence
        files = {}

        def collect(node):
            if isinstance(node, dict):
                for key, item in node.items():
                    if key in ('path', 'mask') and isinstance(item, str):
                        files[item] = sha(local_path(self.root, item))
                    else:
                        collect(item)
            elif isinstance(node, list):
                for item in node:
                    collect(item)
        collect(evidence)
        collect(scene['assets'])

        def digest(data):
            return hashlib.sha256(json.dumps(data, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return {'scene_sha256': digest(scene), 'evidence_sha256': digest(evidence), 'files': files}

    def checkpoint(self):
        self.require_writable()
        command = self.root / 'working/control.json'
        if not command.exists():
            return
        instruction = read(command)['command']
        command.unlink()
        if instruction == 'stop':
            raise InterruptedError('User stopped reconstruction')
        if instruction == 'pause':
            self.update(status='PAUSED')
            while True:
                time.sleep(0.1)
                if not command.exists():
                    continue
                instruction = read(command)['command']
                command.unlink()
                if instruction == 'stop':
                    raise InterruptedError('User stopped reconstruction')
                if instruction == 'resume':
                    break
            self.update(status='RUNNING')

    def save_scene(self, scene):
        self.require_writable()
        write(self.root / 'working/current_scene.yaml', scene)
        self.invalidate()


def clone_project(source, destination):
    """Copy an existing authoring project to a new owned workspace, never edit it."""
    original=Project(source,read_only=True)
    if (original.root/'working/run.lock').exists():
        raise RuntimeError('Source project has an active or unresolved owner; cannot freeze a clone')
    destination=Path(destination).resolve()
    if destination.is_relative_to(original.root) or original.root.is_relative_to(destination):
        raise ValueError('Project clone requires a separate output directory')
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name('.'+destination.name+'.building-'+uuid.uuid4().hex)
    try:
        shutil.copytree(original.root,temporary,symlinks=False)
        write(temporary/'working/owner.json',{'schema':'real2sim.builder-owner/1','project_id':original.info['id']})
        # Working ownership locks are not copied as live process claims.
        (temporary/'working/run.lock').unlink(missing_ok=True)
        (temporary/'working/control.json').unlink(missing_ok=True)
        if (temporary/'working/current_scene.yaml').is_file():
            validate(read(temporary/'working/current_scene.yaml'),temporary)
        os.rename(temporary,destination)
        return Project(destination)
    finally:
        if temporary.exists():shutil.rmtree(temporary)

