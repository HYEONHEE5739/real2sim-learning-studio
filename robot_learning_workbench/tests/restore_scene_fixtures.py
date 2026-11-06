"""Restore deleted historical test assets from an identical local Scene revision.

Explicit maintenance command; no downloads, Manifest rewrites or replacements.
Run: python restore_scene_fixtures.py --source PACKAGE --fixture PACKAGE [...]
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil


def restore(source, fixtures):
    source=Path(source).resolve();pending=[]
    for root in map(Path,fixtures):
        root=root.resolve()
        for row in json.loads((root/'manifest.json').read_text())['files']:
            target=root/row['path']
            if target.exists():continue
            original=source/row['path']
            if not target.resolve().is_relative_to(root) or not original.resolve().is_relative_to(source):
                raise ValueError('Manifest path escapes package')
            if not original.is_file() or original.stat().st_size!=row['size_bytes'] or hashlib.sha256(original.read_bytes()).hexdigest()!=row['sha256']:
                raise ValueError('Matching original bytes required: '+row['path'])
            pending.append((original,target))
    for original,target in pending:
        target.parent.mkdir(parents=True,exist_ok=True)
        try:os.link(original,target)
        except OSError:shutil.copyfile(original,target)
    return [str(target) for _,target in pending]


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',required=True,type=Path)
    parser.add_argument('--fixture',required=True,type=Path,action='append')
    args=parser.parse_args()
    print(json.dumps({'restored':restore(args.source,args.fixture)},indent=2))
