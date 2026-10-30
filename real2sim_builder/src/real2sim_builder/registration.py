"""Publish verified export references in their owning Project; no engine startup."""
from pathlib import Path
from .files import read,write
from .candidate import exclusive
from .export import verify_package


def register_export(project,package_path,*,engine_config=None,source_project_id=None):
    project.require_writable();root=Path(package_path).resolve();package=verify_package(root)
    with exclusive(project):
        info=read(project.root/'project.yaml');rows=info.get('execution_packages',[])
        if any((project.root/r['path']).resolve()==root for r in rows):raise ValueError('Export already registered; revisions are immutable')
        settings={}
        for engine in package.scene['engines']:
            if engine_config is None:
                if not (root/'authored_scene.json').is_file():raise ValueError('Authored export scene required for default render settings')
                path=project.root/'configuration'/('export-'+package.identity.manifest_sha256[:16]+'-'+engine+'.json')
                write(path,{'render_type':'authored'});settings[engine]=path.relative_to(project.root).as_posix()
            elif engine in engine_config:settings[engine]=engine_config[engine]
        row={'path':root.relative_to(project.root).as_posix()if root.is_relative_to(project.root)else str(root),'scene_id':package.identity.scene_id,'revision':package.identity.revision,
             'manifest_sha256':package.identity.manifest_sha256,'source_project_id':source_project_id or project.info['id'],'engine_config':settings}
        write(project.root/'project.yaml',{**info,'execution_packages':[*rows,row]});project.info=read(project.root/'project.yaml')
    return row
