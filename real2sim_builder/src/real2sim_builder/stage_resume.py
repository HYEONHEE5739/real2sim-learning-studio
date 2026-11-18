"""Match saved Stage/Worker inputs across presentation-only updates."""
from pathlib import Path

from .files import read


# These orchestration revisions differ only in progress reporting and cache lookup
# for stages 1–5. Any other automation change must invalidate the old signature.
CURRENT_AUTOMATION = '0f84aaa6af22b785486e8d21be9b65459268016320cb2a45c40962595ad03433'
PROGRESS_REVISIONS = (
    ('49320148ab72b6c04135b345d956864d92cf2fb4a2ea678c4c2b959a811e33a1',
     '74ff4e46d1a573937facb83d8c109a64d8dd6d406264d7f8d81105b35f0abac8'),
    ('e19506370ce1585cc32951fac2da94da4d33d0f8e12c0d7702d30f16c27cd345',
     '0e22cc4bff1a8d7d89493b3da3f7378e1ba7f2739b1333d6674bb124a9a0d466'),
)


def checkpoint_identities(stage, runtime):
    sources = runtime['stage_implementation_sha256']
    backend = {name: value for name, value in sources.items() if name not in {'ui_reconstruction.py','visual_evidence.py','evidence_dashboard.py'}}
    yield {**runtime, 'stage_implementation_sha256': backend}
    yield runtime
    if stage <= 5 and sources.get('automation.py') == CURRENT_AUTOMATION:
        for automation, ui in PROGRESS_REVISIONS:
            legacy = {**sources, 'automation.py': automation, 'ui_reconstruction.py': ui}
            legacy.pop('stage_resume.py', None)
            yield {**runtime, 'stage_implementation_sha256': legacy}


def checkpoint_lineage(root, index):
    """Prefer ancestors of the furthest completed stage over shorter retries."""
    paths = {}
    for stage in range(14, 0, -1):
        entry = index.get(str(stage), {}).get('artifact')
        if not entry or stage in paths:
            continue
        path = Path(entry)
        for n in range(stage, 0, -1):
            if path.resolve().parent.parent != (root / f'stage_{n:02d}').resolve() or path.name != 'artifact.json':
                raise ValueError('Stage artifact outside expected Candidate stage')
            if not path.is_file():
                break
            paths[n] = path
            if n == 1:
                break
            files = read(path)['input_manifest']['files']
            if len(files) != 1:
                break
            path = Path(files[0]['path'])
    return paths
