"""Task targets are recorded independently of the Scene's object catalogue."""
from dataclasses import asdict
from types import SimpleNamespace
import pytest
from test_recipe_preparation import scene,source_doc,annotation_doc,registry
from test_native_dataset import episode,execution
from robot_learning_workbench import recipe
from robot_learning_workbench.data import native


def test_source_task_flags_are_boolean_and_recorded_separately_from_creation_list(tmp_path,scene):
    from robot_learning_workbench.engines.mujoco.source import execution_contract
    from robot_learning_workbench.engines.mujoco.model import ModelConfig
    objects={name:{'task_object':task,'placement':{'function':'placement.fixed_xy','params':{'frame':'workspace','support':'marker_top','xy_m':[.02,-.24]}}}for name,task in [('cube_red',False),('cube_blue',True)]}
    plan=recipe.prepare_recipe(source_doc(tmp_path,objects),scene=scene,tasks=registry())
    assert plan.object_order==('cube_red','cube_blue')
    assert list(plan.effective_settings['task_objects'])==['cube_blue']
    b=SimpleNamespace(model_sha256='a'*64,urdf_sha256='b'*64,dynamic_objects=plan.object_order)
    recorded=execution_contract(plan,b,ModelConfig((0,)*6,plan.object_order,{}))
    assert recorded['task_objects']==['cube_blue'] and recorded['active_objects']==['cube_red','cube_blue']
    objects['cube_red'].pop('task_object')
    only_blue=recipe.prepare_recipe(source_doc(tmp_path,objects),scene=scene,tasks=registry())
    assert list(only_blue.effective_settings['task_objects'])==['cube_blue']
    objects['cube_blue']['task_object']='true'
    with pytest.raises(recipe.RecipeError):source_doc(tmp_path,objects)


def test_annotation_inherits_recorded_task_objects(tmp_path,scene):
    with native.NativeRun(tmp_path/'data',dict(stage='source',scene_identity=asdict(scene.identity),active_objects=['cube_red','cube_blue'],task_objects=['cube_blue'])):pass
    plan=recipe.prepare_recipe(annotation_doc(tmp_path),scene=scene,tasks=registry())
    assert list(plan.effective_settings['task_objects'])==['cube_blue']


def test_initial_distribution_uses_episode_start_even_when_training_range_is_trimmed(tmp_path):
    import numpy as np,torch
    from robot_learning_workbench.data.curation import save_curation
    from robot_learning_workbench.data.quality import motion_quality
    settings=execution('source');settings.update(task_objects=['cube_blue'])
    settings['recording'].update(units='m_rad_s',pose_frame='robot_base')
    with native.NativeRun(tmp_path/'data',settings)as run:
        segment=run.segment('one');e=episode(6);poses=np.tile(np.eye(4),(6,1,1));poses[:,0,3]=np.arange(6)*.01
        e.data['obs']['datagen_info']={'object_pose':{'cube_blue':torch.from_numpy(poses)}}
        segment.write_episode(e,episode_id='e');segment.commit()
    selected=save_curation(tmp_path/'trim.json',run.root,frame_ranges={'e':(3,6)})
    assert motion_quality(selected)['e']['initial_objects']['cube_blue']==[0.,0.,0.]


def test_script_creation_list_overrides_engine_template_in_both_engines():
    from robot_learning_workbench.engines.mujoco.source import resolved_model_config
    from robot_learning_workbench.engines.isaac.source import settings_for
    objects={name:{'role':'task_object','spawn':'recipe'}for name in('red','blue','green')}
    for engine in('mujoco','isaac'):
        settings=dict(active_object_ids=['red','blue','green'],initial_joint_rad=[0.]*6,object_physics={})
        if engine=='isaac':settings['isaac']=dict(physics_timestep_s=1/300,decimation=10)
        plan=SimpleNamespace(engine=engine,stage='source',scene=SimpleNamespace(scene={'objects':objects}),object_order=('blue',),input_documents={'engine_config':settings},effective_settings={'execution':{}})
        resolved=resolved_model_config(plan)if engine=='mujoco'else settings_for(plan)
        assert list(resolved.active_object_ids if engine=='mujoco'else resolved['active_object_ids'])==['blue']
        replay=resolved_model_config(plan,settings)if engine=='mujoco'else settings_for(plan,settings)
        assert list(replay.active_object_ids if engine=='mujoco'else replay['active_object_ids'])==['red','blue','green']
        settings['active_object_ids'].append('unknown')
        with pytest.raises(ValueError):resolved_model_config(plan)if engine=='mujoco'else settings_for(plan)


def test_native_mujoco_removes_optional_bodies_instead_of_only_hiding_them(tmp_path):
    import hashlib
    import numpy as np
    import mujoco
    from robot_learning_workbench.robot.calibration import JOINTS
    from robot_learning_workbench.engines.mujoco.model import ModelConfig,build_native_model
    root=tmp_path;xml=['<mujoco><compiler angle="radian"/><worldbody><body name="base">']
    for name in JOINTS:xml.append(f'<body name="link_{name}"><joint name="{name}" type="hinge" range="-2 2"/><geom type="sphere" size=".01" mass=".1"/>')
    xml.append('<site name="tool0"/>');xml.extend('</body>'for _ in JOINTS);xml.append('</body>')
    for name in('red','blue','green'):xml.append(f'<body name="{name}" pos="0 0 .1"><freejoint/><geom name="{name}_collider" type="box" size=".01 .01 .01" mass=".02"/></body>')
    xml.append('</worldbody><actuator>')
    for name in JOINTS:xml.append(f'<position name="motor_{name}" joint="{name}" kp="10"/>')
    xml.append('</actuator></mujoco>');path=root/'native.xml';path.write_text(''.join(xml));(root/'robot.urdf').write_text('<robot name="fixture"/>')
    entries=[SimpleNamespace(path=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest())for p in root.iterdir()]
    objects={name:dict(role='task_object',spawn='recipe')for name in('red','blue','green')}
    frames={'world':dict(parent=None,state='reference',T_parent_from_frame=np.eye(4).tolist()),'robot_base':dict(parent='world',state='reference',T_parent_from_frame=np.eye(4).tolist())}
    package=SimpleNamespace(root=root,files=entries,identity=SimpleNamespace(manifest_sha256='a'*64),calibration={'records':{}},scene=dict(objects=objects,frames=frames,cameras={},robot=dict(asset_path='robot.urdf',bindings={'mujoco':dict(asset_path='native.xml',base_body='base')})))
    cfg=ModelConfig((0.,)*6,('blue',),{})
    # Native binding also needs the two named recording cameras.
    path.write_text(path.read_text().replace('</worldbody>','<camera name="side"/><camera name="wrist"/></worldbody>'))
    entries[0].sha256=hashlib.sha256(path.read_bytes()).hexdigest()if entries[0].path=='native.xml'else entries[0].sha256
    for entry in entries:
        if entry.path=='native.xml':entry.sha256=hashlib.sha256(path.read_bytes()).hexdigest()
    before=path.read_bytes();model,binding=build_native_model(package,cfg)
    assert binding.dynamic_objects==('blue',) and set(binding.object_body_ids)=={'blue'}
    assert mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'red')==-1
    assert mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_GEOM,'green_collider')==-1
    assert path.read_bytes()==before


def test_task_distribution_survives_lerobot_conversion_without_native_file_access(tmp_path):
    import numpy as np,torch,shutil
    from robot_learning_workbench.data.lerobot import materialize
    from robot_learning_workbench.data.quality import motion_quality
    from robot_learning_workbench.data.curation import save_curation
    settings=execution('source');settings.update(task_objects=['cube_blue'],single_task='Pick blue')
    settings['recording'].update(units='m_rad_s',pose_frame='robot_base')
    with native.NativeRun(tmp_path/'source',settings)as run:
        segment=run.segment('one');e=episode(6);poses=np.tile(np.eye(4),(6,1,1));poses[:,0,3]=np.arange(6)*.01
        e.data['obs']['datagen_info']={'object_pose':{'cube_blue':torch.from_numpy(poses),'cube_red':torch.from_numpy(poses)}}
        segment.write_episode(e,episode_id='e');segment.commit()
    selected=save_curation(tmp_path/'trimmed.json',run.root,frame_ranges={'e':(3,6)})
    output=materialize(selected,tmp_path/'official')
    shutil.rmtree(run.root)
    catalog=native.load_catalog(output)
    assert catalog.execution['task_objects']==['cube_blue']
    assert motion_quality(catalog)['e']['initial_objects']=={'cube_blue':[0.,0.,0.]}


def test_annotation_uses_recorded_instances_even_with_an_engine_template(tmp_path):
    from robot_learning_workbench.data.recording import replay_settings
    from robot_learning_workbench.robot.calibration import JOINTS
    settings=execution('source');settings.update(active_objects=['blue'])
    settings['recording'].update(joint_order=list(JOINTS),units='m_rad_s',pose_frame='robot_base',observation_phase='pre_step',task_phase='post_step',fps=30,resolution=[640,480])
    with native.NativeRun(tmp_path/'source',settings):pass
    catalog=native.load_catalog(tmp_path/'source')
    template={'active_object_ids':['red','blue','green'],'initial_joint_rad':[0.]*6}
    for engine in('mujoco','isaac'):
        plan=SimpleNamespace(scene_identity=settings['scene_identity'],engine=engine,input_documents={'engine_config':template})
        resolved=replay_settings(plan,catalog)
        assert resolved['active_object_ids']==['blue']
        assert template['active_object_ids']==['red','blue','green']
