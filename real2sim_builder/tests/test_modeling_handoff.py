from real2sim_builder.project import Project,Candidate
from real2sim_builder.files import read,write,sha


def semantic_reply(rows,memo=''):
    import hashlib,copy
    objects=[];groups={}
    for row in rows:
        obj={k:copy.deepcopy(row.get(k,''))for k in('id','prompt','role','category','asset_group','material_variant','modeling_notes')}
        obj['observations']=copy.deepcopy(row.get('observations',[]));objects.append(obj)
        if obj['asset_group']:
            group=groups.setdefault(obj['asset_group'],{'id':obj['asset_group'],'members':[],'relation_source':'visual_inference','evidence_quote':'','change_kind':'none','evidence':['controlled Codex interpretation']})
            group['members'].append(obj['id'])
            if row.get('group_sources'):
                group.update(relation_source='user_memo',evidence_quote=row['group_sources'][0]['quote'])
    return {'scene_memo_sha256':hashlib.sha256(memo.encode()).hexdigest(),'objects':objects,'asset_groups':list(groups.values()),'needs':[]}


def test_modeling_handoff_contains_notes_references_measurements_and_keeps_other_objects(tmp_path):
    from real2sim_builder.automation import modeling_tasks,attach_modeled_assets,record_modeling_results
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    from test_builder_export import legacy_scene
    from real2sim_builder.evidence import save_scene_memo
    p=Project.create(tmp_path/'projects','modeling');p.save_scene(legacy_scene());c=Candidate.create(p,'one_new')
    notes=tmp_path/'notes.md';notes.write_text('빨간 블록 한 개 추가. 기존 테이블과 로봇은 유지.');save_scene_memo(p,notes.read_bytes().decode('utf-8'))
    config={'objects':{'new_block':{'prompt':'red cube'}},'measurements':[{'id':'new_block','kind':'box','dimensions_m':[.03]*3,'evidence':['caliper']}]}
    result=modeling_tasks(c,config,{'segments':[],'depth_batches':[]})
    job=read(c.root/'modeling/tasks.json')
    assert result['pending']==['new_block']
    assert job['scene_memo']['sha256']==sha(notes)and job['scene_memo']['text']==notes.read_text()
    assert job['objects'][0]['measurements']['evidence']==['caliper']
    assert job['protected_objects']==['table','block']
    assert (c.root/'modeling/CODEX_MODELING.md').is_file()
    record=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='new_block')
    record_modeling_results(c,[record])
    before=c.scene;applied=attach_modeled_assets(c,config)
    assert applied['attached']==['new_block']
    assert c.scene['objects'][:2]==before['objects']
    assert modeling_tasks(c,config,{'segments':[],'depth_batches':[]})['pending']==[]


def test_blender_selective_authoring_creates_real_usda_and_separate_collision(tmp_path,monkeypatch):
    from real2sim_builder.rendering import author_object_assets
    from real2sim_builder.object_assets import inspect_usda
    from pathlib import Path
    import os
    blender=Path(os.environ.get('REAL2SIM_BLENDER','/home/hyeonhee/apps/blender/blender'))
    assert blender.is_file(),'Use installed Blender; never download a test runtime'
    monkeypatch.setenv('REAL2SIM_BLENDER',str(blender))
    p=Project.create(tmp_path/'projects','blender');c=Candidate.create(p,'model')
    script=tmp_path/'author.py';script.write_text('''import bpy
bpy.ops.mesh.primitive_cube_add(size=.03)
obj=bpy.context.object;obj.name="block";obj["r2s_id"]="block"
mat=bpy.data.materials.new("red");mat.use_nodes=True
mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value=(.8,.1,.1,1)
obj.data.materials.append(mat)
bpy.ops.mesh.primitive_cube_add(size=.03)
col=bpy.context.object;col.name="collision";col["r2s_collision"]=True;col.parent=obj;col.hide_render=True
''')
    original=sha(c.root/'candidate_scene.yaml')
    result=author_object_assets(c,script,['block'])
    record=result['assets'][0];entry=p.root/record['manifest'];entry=entry.parent/record['entry']
    inspect_usda(entry)
    assert record['collision_status']=='AUTHORED_UNVALIDATED' and len(record['visual'])==1 and len(record['collision'])==1
    assert sha(c.root/'candidate_scene.yaml')==original
    assert record['source_blend']=='source.blend'


def test_object_authoring_cannot_write_other_project_files(tmp_path,monkeypatch):
    from real2sim_builder.rendering import author_object_assets
    from pathlib import Path
    import os,subprocess,pytest
    monkeypatch.setenv('REAL2SIM_BLENDER',os.environ['REAL2SIM_BLENDER'])
    p=Project.create(tmp_path/'projects','protected');c=Candidate.create(p,'only_new')
    protected=p.root/'input/protected.txt';protected.write_text('original')
    script=tmp_path/'bad.py';script.write_text('from pathlib import Path\nPath('+repr(str(protected))+').write_text("overwritten")\n')
    with pytest.raises(subprocess.CalledProcessError):author_object_assets(c,script,['new_object'])
    assert protected.read_text()=='original'and c.info['status']=='OPEN'
    assert not list((p.workspace/'object_assets').glob('*/*/manifest.json'))


def test_opt_in_codegen_uses_nonrepo_sandbox_and_imports_validated_result(tmp_path,monkeypatch):
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling
    from pathlib import Path
    import os,sys
    monkeypatch.setenv('REAL2SIM_BLENDER',os.environ['REAL2SIM_BLENDER'])
    p=Project.create(tmp_path/'projects','explicit codegen');c=Candidate.create(p,'one_new')
    modeling_tasks(c,{'objects':{'block':{'prompt':'red cube'}}},{'segments':[],'depth_batches':[]})
    executable=tmp_path/'fake_codex'
    # Only the CLI boundary is simulated. Blender/USD validation below is real.
    executable.write_text('#!'+sys.executable+'\n'+'''import json,sys
from pathlib import Path
args=sys.argv;root=Path(args[args.index('--cd')+1]);assert not (root/'.git').exists()
assert args[args.index('--sandbox')+1]=='workspace-write'
assert 'sandbox_workspace_write.writable_roots=[]' in args
(root/'author.py').write_text('import bpy\\nbpy.ops.mesh.primitive_cube_add(size=.03)\\nobj=bpy.context.object;obj["r2s_id"]="block"\\nbpy.ops.mesh.primitive_cube_add(size=.03)\\ncol=bpy.context.object;col.parent=obj;col["r2s_collision"]=True\\n')
Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({'script':'author.py'}))
''');executable.chmod(0o700)
    result=run_codex_modeling(c,executable=executable,timeout_s=15)
    assert result['status']=='REGISTERED_UNVALIDATED'
    assert read(c.root/'modeling/results.json')['assets']['block']
    assert not(p.root/'working/current_scene.yaml').exists()


def test_empty_object_list_has_a_semantic_analysis_handoff_and_no_fake_dimensions(tmp_path):
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling
    import sys
    p=Project.create(tmp_path/'projects','notes');c=Candidate.create(p,'analysis')
    result=modeling_tasks(c,{}, {'segments':[],'depth_batches':[]})
    assert result['status']=='WAITING_FOR_CODEX_ANALYSIS'
    import json
    reply=semantic_reply([{'id':'banana','prompt':'banana','role':'manipulable_object'}])
    executable=tmp_path/'fake_codex';executable.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index("--output-last-message")+1]).write_text('+repr(json.dumps(reply))+')\n');executable.chmod(0o700)
    result=run_codex_modeling(c,executable=executable)
    assert result['status']=='ANALYZED_OBJECT_PROPOSALS'
    config=read(p.root/'input/reconstruction.yaml')
    assert config['objects']['banana']['provenance']=='estimated'and 'measurements'not in config
    assert not list((p.workspace/'object_assets').glob('*/*/manifest.json'))


def open_cup_script():
    return '''import bpy,math
from mathutils import Matrix
root=bpy.data.objects.new("cup",None);bpy.context.scene.collection.objects.link(root);root["r2s_id"]="cup"
vertices=[];faces=[];count=48
# Four rings: outer bottom/top, inner bottom/top. Known synthetic dimensions.
for radius,z in [(.04,-.05),(.04,.05),(.037,-.047),(.037,.05)]:
    vertices += [(radius*math.cos(2*math.pi*i/count),radius*math.sin(2*math.pi*i/count),z) for i in range(count)]
for i in range(count):
    j=(i+1)%count
    faces += [(i,j,count+j,count+i),(2*count+i,3*count+i,3*count+j,2*count+j),
              (count+i,count+j,3*count+j,3*count+i)]
faces += [tuple(reversed(range(count))),tuple(range(2*count,3*count))]
mesh=bpy.data.meshes.new("cup_visual");mesh.from_pydata(vertices,[],faces);mesh.update()
visual=bpy.data.objects.new("Visual",mesh);bpy.context.scene.collection.objects.link(visual);visual.parent=root
mat=bpy.data.materials.new("white");mat.use_nodes=True;visual.data.materials.append(mat)
bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.04,depth=.003,location=(0,0,-.0485))
bottom=bpy.context.object;bottom.name="CollisionBottom";bottom.parent=root;bottom["r2s_collision"]=True
for i in range(16):
    angle=i*2*math.pi/16
    bpy.ops.mesh.primitive_cube_add(size=1,location=(.0385*math.cos(angle),.0385*math.sin(angle),0))
    obj=bpy.context.object;obj.name="CollisionWall";obj.parent=root;obj["r2s_collision"]=True
    obj.data.transform(Matrix.Diagonal((.003,2*.0385*math.tan(math.pi/16)*1.03,.1,1)))
    obj.rotation_euler.z=angle
'''


def test_open_cup_keeps_visual_and_convex_collision_separate_and_block_reaches_bottom(tmp_path,monkeypatch):
    from real2sim_builder.rendering import author_object_assets
    from real2sim_builder.object_assets import instance_operation
    from real2sim_builder.scene import value
    from real2sim_builder.exporters import mjcf
    from test_builder_export import legacy_scene
    import numpy as np,os,mujoco
    monkeypatch.setenv('REAL2SIM_BLENDER',os.environ['REAL2SIM_BLENDER'])
    p=Project.create(tmp_path/'projects','open cup');p.save_scene(legacy_scene());c=Candidate.create(p,'cup_drop')
    script=tmp_path/'cup.py';script.write_text(open_cup_script())
    record=author_object_assets(c,script,['cup'])['assets'][0]
    assert len(record['visual'])==1 and len(record['collision'])==17
    pose=np.eye(4);pose[:3,3]=[.2,0,.05]
    c.edit([instance_operation(p,record['manifest'],'cup',pose=pose.tolist(),role='receptacle')])
    c.edit([{'op':'add_object','id':'drop','dimensions':[.02]*3,'pose':np.array([[1,0,0,.2],[0,1,0,0],[0,0,1,.16],[0,0,0,1]]).tolist(),
        'role':'manipulable_object','visual':{'type':'box'},'collision':{'type':'box'}}])
    scene=c.scene;scene['objects'][-1]['physics']={'mass_kg':value(.03,'estimated'),'friction':value(.5,'estimated')}
    path=tmp_path/'cup.xml';mjcf.export(scene,p.root,path);model=mujoco.MjModel.from_xml_path(str(path));data=mujoco.MjData(model)
    for _ in range(600):mujoco.mj_step(model,data)
    body=mujoco.mj_name2id(model,mujoco.mjtObj.mjOBJ_BODY,'drop')
    assert .01<data.xpos[body,2]<.02,'Cup interior was blocked or the block fell through the floor'


def test_same_asset_name_is_an_unresolved_match_until_explicitly_selected(tmp_path):
    from real2sim_builder.automation import modeling_tasks,attach_modeled_assets
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','different cup');c=Candidate.create(p,'new_photo')
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='cup')
    original={str(f):sha(f)for f in (p.workspace/'object_assets').rglob('*')if f.is_file()}
    config={'objects':{'cup':{'prompt':'a different cup','role':'receptacle'}},
        'measurements':[{'id':'cup','kind':'cylinder','dimensions_m':[.08,.08,.12],'evidence':['new cup caliper']}]}
    report=modeling_tasks(c,config,{'segments':[]})
    assert report['pending']==['cup']and not c.scene['objects']
    task=read(c.root/'modeling/tasks.json')['objects'][0]
    assert task['asset_match_status']=='ASSET_MATCH_UNRESOLVED'
    assert task['asset_candidates'][0]['manifest']==asset['manifest']
    assert task['asset_candidates'][0]['dimensions']==asset['dimensions']
    config['objects']['cup']['asset_manifest']=asset['manifest']
    assert attach_modeled_assets(c,config)['attached']==[]  # Size conflict is still enforced.
    config['measurements']=[]
    attach_modeled_assets(c,config)
    assert modeling_tasks(c,config,{'segments':[]})['pending']==[]
    c.edit([{'op':'update_pose','id':'cup','value':[[1,0,0,.1],[0,1,0,0],[0,0,1,.1],[0,0,0,1]]}])
    assert modeling_tasks(c,config,{'segments':[]})['pending']==[]
    assert original=={str(f):sha(f)for f in (p.workspace/'object_assets').rglob('*')if f.is_file()}


def test_codegen_attaches_visual_images_and_preserves_depth_camera_correspondence(tmp_path):
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling
    from PIL import Image
    import sys,json,numpy as np
    p=Project.create(tmp_path/'projects','visual input');c=Candidate.create(p,'model')
    image=p.root/'input/photo.png';Image.new('RGB',(32,24),'red').save(image)
    mask=p.root/'input/mask.png';Image.new('L',(32,24),255).save(mask)
    depth=p.root/'input/depth.npz';np.savez(depth,depth=np.ones((24,32)),confidence=np.ones((24,32)))
    inferred={'images':[{'id':'photo','path':'input/photo.png','sha256':sha(image),'resolution':[32,24],'split':'train'}],
        'segments':[{'image_id':'photo','object_id':'cube','status':'UNIQUE_ESTIMATED','masks':[{'path':str(mask),'sha256':sha(mask)}]}],
        'depth_batches':[{'path':str(depth),'image_ids':['photo'],'metadata':{'sha256':sha(depth)}}]}
    modeling_tasks(c,{'objects':{'cube':{'prompt':'red cube'}}},inferred)
    task=read(c.root/'modeling/tasks.json');task['camera_predictions']={'status':'UNRESOLVED','units':'relative'};write(c.root/'modeling/tasks.json',task)
    executable=tmp_path/'fake_codex';executable.write_text('#!'+sys.executable+'\n'+'''import sys,json
from pathlib import Path
args=sys.argv;root=Path(args[args.index('--cd')+1]);task=json.loads((root/'tasks.json').read_text())
assert '--image' in args
assert task['camera_predictions']['status']=='UNRESOLVED'
ref=task['objects'][0]['references'][0]
assert (root/ref['original']).is_file()and(root/ref['crops'][0]['path']).is_file()
assert(root/ref['depth_batches'][0]['path']).is_file()
assert task['measurements_provenance']=='Only explicitly supplied measurements are measured'
Path(args[args.index('--output-last-message')+1]).write_text(json.dumps({'script':'../outside.py'}))
''');executable.chmod(0o700)
    import pytest
    with pytest.raises(ValueError,match='escapes'):run_codex_modeling(c,executable=executable)
    assert read(next((c.root/'modeling/codex').glob('*/status.json')))['status']=='FAILED'


def test_codex_failures_retain_candidate_tasks_and_do_not_publish_assets(tmp_path):
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling
    import sys,pytest
    p=Project.create(tmp_path/'projects','failure handling');c=Candidate.create(p,'retry')
    modeling_tasks(c,{'objects':{'new':{'prompt':'new object'}}},{'segments':[]})
    before=sha(c.root/'candidate_scene.yaml');executable=tmp_path/'fake_codex'
    for message,code in [('authentication failed','AUTHENTICATION_FAILED'),('usage limit reached','USAGE_LIMIT'),('unexpected argument --bad','INVALID_CLI_OPTIONS')]:
        executable.write_text('#!'+sys.executable+'\nimport sys\nprint('+repr(message)+')\nsys.exit(1)\n');executable.chmod(0o700)
        with pytest.raises(RuntimeError):run_codex_modeling(c,executable=executable)
        latest=max((c.root/'modeling/codex').glob('*/status.json'),key=lambda f:f.stat().st_mtime_ns)
        assert read(latest)['code']==code
    executable.write_text('#!'+sys.executable+'\n');executable.chmod(0o700)
    with pytest.raises(ValueError,match='response'):run_codex_modeling(c,executable=executable)
    assert sha(c.root/'candidate_scene.yaml')==before and not list((p.workspace/'object_assets').glob('*/*/manifest.json'))


def test_codegen_timeout_stop_and_reuse_do_not_repeat_remote_work(tmp_path,monkeypatch):
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling,record_modeling_results
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    import sys,pytest
    p=Project.create(tmp_path/'projects','stop');c=Candidate.create(p,'only')
    modeling_tasks(c,{'objects':{'new':{'prompt':'object'}}},{'segments':[]})
    executable=tmp_path/'fake_codex';executable.write_text('#!'+sys.executable+'\nimport time\ntime.sleep(20)\n');executable.chmod(0o700)
    with pytest.raises(TimeoutError):run_codex_modeling(c,executable=executable,timeout_s=.1)
    def stopped():raise InterruptedError('requested stop')
    monkeypatch.setattr(p,'checkpoint',stopped)
    with pytest.raises(InterruptedError):run_codex_modeling(c,executable=executable)
    assert c.info['status']=='OPEN'
    monkeypatch.undo()
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='new')
    record_modeling_results(c,[asset])
    # The executable would sleep if called. Valid published output is reused.
    assert run_codex_modeling(c,executable=executable,timeout_s=.1)['reused']is True


def test_blender_child_timeout_and_stop_reap_only_owned_process(tmp_path,monkeypatch):
    from real2sim_builder import rendering
    import sys,os,pytest
    executable=tmp_path/'blender_boundary'
    executable.write_text('#!'+sys.executable+'\n'+'''import os,sys,time
from pathlib import Path
folder=Path(sys.argv[-1]).parent
(folder/'pid').write_text(str(os.getpid()))
time.sleep(20)
''');executable.chmod(0o700)
    monkeypatch.setattr(rendering,'capability',lambda:{'available':True,'executable':str(executable)})
    for mode in ['timeout','stop']:
        folder=tmp_path/mode
        def checkpoint():
            if (folder/'pid').exists():raise InterruptedError('stop requested')
        expected=TimeoutError if mode=='timeout'else InterruptedError
        with pytest.raises(expected):rendering.invoke({},folder,timeout_s=.4,checkpoint=checkpoint if mode=='stop'else None)
        pid=int((folder/'pid').read_text())
        with pytest.raises(ProcessLookupError):os.kill(pid,0)


def test_object_sandbox_hides_unrelated_files_credentials_and_host_network(tmp_path,monkeypatch):
    from real2sim_builder.rendering import author_object_assets
    import os,socket
    monkeypatch.setenv('REAL2SIM_BLENDER',os.environ['REAL2SIM_BLENDER'])
    monkeypatch.setenv('FAKE_AUTH_ACCESS_TOKEN','never-forward-this-test-value')
    private=tmp_path/'fake-private';private.mkdir();(private/'auth.json').write_text('fake secret')
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen();port=listener.getsockname()[1]
    p=Project.create(tmp_path/'projects','sandbox allowlist');c=Candidate.create(p,'isolated')
    script=tmp_path/'author.py';script.write_text('''import bpy,os,socket
from pathlib import Path
assert not Path('''+repr(str(private/'auth.json'))+''').exists(), 'unrelated host file readable'
assert 'FAKE_AUTH_ACCESS_TOKEN'not in os.environ, 'credential environment leaked'
assert os.environ['HOME']=='/nonexistent'
connection=socket.socket();connection.settimeout(.3)
assert connection.connect_ex(('127.0.0.1','''+str(port)+'''))!=0, 'host network reachable'
connection.close()
bpy.ops.mesh.primitive_cube_add(size=.03)
obj=bpy.context.object;obj['r2s_id']='block'
bpy.ops.mesh.primitive_cube_add(size=.03)
col=bpy.context.object;col.parent=obj;col['r2s_collision']=True;col.hide_render=True
''')
    try:
        result=author_object_assets(c,script,['block'])
        assert result['assets'][0]['collision']and result['assets'][0]['visual']
    finally:listener.close()


def test_group_models_once_and_cache_requires_content_fingerprint(tmp_path):
    from real2sim_builder.automation import modeling_tasks,attach_modeled_assets,record_modeling_results
    from real2sim_builder.object_assets import register_object_asset,list_object_assets
    from test_object_assets import asset_fixture
    import copy
    from PIL import Image
    p=Project.create(tmp_path/'projects','two identical cups');c=Candidate.create(p,'grouped')
    config={'objects':{'cup1':{'prompt':'paper cup','category':'cup','role':'receptacle','asset_group':'cups'},
                       'cup2':{'prompt':'paper cup','category':'cup','role':'receptacle','asset_group':'cups'},
                       'mug':{'prompt':'mug','category':'cup','role':'receptacle'}}}
    inferred={'segments':[]};result=modeling_tasks(c,config,inferred);task=read(c.root/'modeling/tasks.json')
    cups=next(t for t in task['objects']if t['asset_group']=='cups')
    assert len(task['objects'])==2 and cups['members']==['cup1','cup2']
    record=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='cups')
    record_modeling_results(c,[record]);applied=attach_modeled_assets(c,config,inferred)
    assert applied['attached']==['cup1','cup2']
    assert c.scene['objects'][0]['object_asset']==c.scene['objects'][1]['object_asset']
    original={str(f):sha(f)for f in (p.workspace/'object_assets').rglob('*')if f.is_file()}
    # Pose-only edits and an additional confirmed instance do not change the shape fingerprint.
    c.edit([{'op':'update_pose','id':'cup1','value':[[1,0,0,.2],[0,1,0,0],[0,0,1,.1],[0,0,0,1]]}])
    config['objects']['cup3']=copy.deepcopy(config['objects']['cup2'])
    assert attach_modeled_assets(c,config,inferred)['attached']==['cup3']
    assert modeling_tasks(c,config,inferred)['pending']==['mug']
    # Changing only this group's measurements invalidates only this group's result.
    changed=copy.deepcopy(config);changed['measurements']=[{'id':'cup1','kind':'cylinder','dimensions_m':[.1,.1,.2],'evidence':['new measurement']}]
    assert not attach_modeled_assets(c,changed,inferred)['attached']
    result=modeling_tasks(c,changed,inferred);job=read(c.root/'modeling/tasks.json')
    assert next(t for t in job['objects']if t['asset_group']=='cups')['asset_match_status']=='ASSET_DIMENSION_CONFLICT'
    assert original=={str(f):sha(f)for f in (p.workspace/'object_assets').rglob('*')if f.is_file()}
    assert len(list_object_assets(p))==1


def test_legacy_results_do_not_silently_attach_by_object_id(tmp_path):
    from real2sim_builder.automation import modeling_tasks,attach_modeled_assets
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','legacy');c=Candidate.create(p,'review')
    record=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='cup')
    write(c.root/'modeling/results.json',{'assets':{'cup':record['manifest']}})
    config={'objects':{'cup':{'prompt':'different cup'}}}
    assert attach_modeled_assets(c,config,{'segments':[]})['attached']==[]
    assert not c.scene['objects']
    modeling_tasks(c,config,{'segments':[]})
    assert read(c.root/'modeling/tasks.json')['objects'][0]['requires_review']is True
    config['objects']['cup']['asset_manifest']=record['manifest']
    assert attach_modeled_assets(c,config,{'segments':[]})['attached']==['cup']


def test_semantic_groups_and_two_cup_instances_use_one_real_blender_asset(tmp_path,monkeypatch):
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling,attach_modeled_assets
    from real2sim_builder.object_assets import list_object_assets
    from real2sim_builder.rendering import Renderer
    from real2sim_builder.inference import associate_instances
    from test_builder_export import legacy_scene
    from PIL import Image
    import numpy as np,os,sys,json,copy
    monkeypatch.setenv('REAL2SIM_BLENDER',os.environ['REAL2SIM_BLENDER'])
    p=Project.create(tmp_path/'projects','identical paper cups');scene=legacy_scene()
    scene['cameras'][0]['resolution']=[640,480];scene['cameras'][0]['K']['value']=[[640.,0,320.],[0,640.,240.],[0,0,1.]]
    p.save_scene(scene);c=Candidate.create(p,'one_model')
    from real2sim_builder.evidence import save_scene_memo
    note=tmp_path/'scene.md';note.write_text('오른쪽 종이컵 두 개는 같은 제품, 크기와 무늬가 같습니다. 각각 별도 물체이고 3D 모델은 공유합니다.')
    save_scene_memo(p,note.read_bytes().decode('utf-8'))
    config={'objects':{name:{'prompt':'paper cup','category':'paper_cup','role':'receptacle','asset_group':'paper_cup_A',
        'asset_group_relation':{'status':'PROPOSED','provenance':'estimated','evidence':['Scene memo declares same product']},
        'images':{'side':{'box_xyxy':box}}}for name,box in [('cup1',[0,0,300,480]),('cup2',[320,0,640,480])]}}
    from real2sim_builder.automation import parse_scene_analysis
    from real2sim_builder.evidence import scene_memo
    reply=semantic_reply([{'id':n,**spec}for n,spec in config['objects'].items()],note.read_text())
    reply['asset_groups'][0].update(relation_source='user_memo',evidence_quote=note.read_text())
    relation=parse_scene_analysis(reply,scene_memo(p))['cup1']['asset_group_relation']
    assert relation['provenance']=='user_declared'
    for spec in config['objects'].values():spec['asset_group_relation']=relation
    rgb=p.root/'input/photo.png';Image.new('RGB',(640,480),'white').save(rgb);masks=[]
    for index,left in enumerate([50,400]):
        a=np.zeros((480,640),np.uint8);a[100:300,left:left+100]=255;path=p.root/f'input/mask{index}.png';Image.fromarray(a).save(path);masks.append({'path':str(path),'sha256':sha(path)})
    inferred={'images':[{'id':'side','path':'input/photo.png','sha256':sha(rgb),'resolution':[640,480],'split':'train'}],
        'segments':[{'object_id':name,'image_id':'side','masks':masks,'status':'AMBIGUOUS'}for name in config['objects']]}
    associated=associate_instances(inferred,config['objects']);assert [s['association']['mask_index']for s in associated['segments']]==[0,1]
    modeling_tasks(c,config,inferred)
    script=open_cup_script().replace('root["r2s_id"]="cup"','root["r2s_id"]="paper_cup_A"')
    # Image texture loading is inside the new filesystem allowlist too.
    script+='\nvisual=bpy.data.objects["Visual"];bpy.ops.object.select_all(action="DESELECT");visual.select_set(True);bpy.context.view_layer.objects.active=visual\nbpy.ops.object.mode_set(mode="EDIT");bpy.ops.mesh.select_all(action="SELECT");bpy.ops.uv.smart_project();bpy.ops.object.mode_set(mode="OBJECT")\nfrom pathlib import Path\nimage=bpy.data.images.load(str(next((Path(__file__).parent/"inputs").glob("*.png"))))\nmat=bpy.data.materials["white"];node=mat.node_tree.nodes.new("ShaderNodeTexImage");node.image=image\nmat.node_tree.links.new(node.outputs["Color"],mat.node_tree.nodes.get("Principled BSDF").inputs["Base Color"])\n'
    script=script.replace('next((Path(__file__).parent/"inputs").glob("*.png"))', 'Path(__file__).parent/"inputs"/'+repr(sha(rgb)+'.png'))
    executable=tmp_path/'fake_codex';executable.write_text('#!'+sys.executable+'\nimport sys,json\nfrom pathlib import Path\na=sys.argv;r=Path(a[a.index("--cd")+1]);t=json.loads((r/"tasks.json").read_text());assert len(t["objects"])==1;assert t["objects"][0]["members"]==["cup1","cup2"]\n(r/"author.py").write_text('+repr(script)+')\nPath(a[a.index("--output-last-message")+1]).write_text(json.dumps({"script":"author.py"}))\n');executable.chmod(0o700)
    result=run_codex_modeling(c,executable=executable);assert len(result['assets'])==1
    assert len(list_object_assets(p))==1
    attach_modeled_assets(c,config,inferred)
    for name,x in [('cup1',-.15),('cup2',.15)]:
        pose=np.eye(4);pose[:3,3]=[x,0,.05];c.edit([{'op':'update_pose','id':name,'value':pose.tolist()}])
    cups=[o for o in c.scene['objects']if o['id'].startswith('cup')]
    assert cups[0]['object_asset']==cups[1]['object_asset']and cups[0]['pose']!=cups[1]['pose']
    with Renderer(c.scene,p.root,c.root/'renders/grouped')as renderer:render=renderer.rgb('side')
    assert render.shape==(480,640,3)
    Image.fromarray(render).save(c.root/'renders/grouped/side.png')
    write(c.root/'renders/grouped/render_scene.yaml',c.scene)
    before={str(f):sha(f)for f in (p.workspace/'object_assets').rglob('*')if f.is_file()}
    c.edit([{'op':'remove_object','id':'cup2'}])
    assert len(list_object_assets(p))==1 and before=={str(f):sha(f)for f in (p.workspace/'object_assets').rglob('*')if f.is_file()}


def test_semantic_analysis_preserves_groups_provenance_and_multiview_ids(tmp_path):
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling
    from real2sim_builder.observations import register_image
    from PIL import Image
    import sys,json
    p=Project.create(tmp_path/'projects','memo groups');c=Candidate.create(p,'analyze')
    image=tmp_path/'photo.png';Image.new('RGB',(640,480),'white').save(image)
    record=register_image(p,image,camera='side',camera_type='side',scene_state='layout')
    modeling_tasks(c,{'scene_state_id':'layout'},{})
    objects=[{'id':name,'prompt':'paper cup','role':'receptacle','category':'paper_cup','asset_group':'cups',
        'group_status':'PROPOSED','group_evidence':['memo says identical products'],'observations':[{'image_id':record['id'],'box_xyxy':box,'evidence':'visible cup'}]}
        for name,box in [('cup1',[10,20,100,200]),('cup2',[300,20,400,200])]]
    executable=tmp_path/'fake_codex';executable.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index("--output-last-message")+1]).write_text('+repr(json.dumps(semantic_reply(objects)))+')\n');executable.chmod(0o700)
    run_codex_modeling(c,executable=executable)
    config=read(p.root/'input/reconstruction.yaml');assert len(config['objects'])==2
    assert config['objects']['cup1']['asset_group']==config['objects']['cup2']['asset_group']=='cups'
    assert config['objects']['cup1']['asset_group_relation']['provenance']=='estimated'
    assert 'measurements'not in config and 'robot_model'not in c.scene


def test_rgb_mask_and_notes_change_group_fingerprints_without_path_or_pose_dependence(tmp_path):
    from real2sim_builder.automation import modeling_groups
    from PIL import Image
    import copy
    p=Project.create(tmp_path/'projects','fingerprints');c=Candidate.create(p,'shape')
    config={'objects':{'a':{'prompt':'red cube'},'b':{'prompt':'green cube'}}};inferred={'images':[],'segments':[]}
    for name,color in [('a','red'),('b','green')]:
        rgb=p.root/f'input/{name}.png';Image.new('RGB',(40,30),color).save(rgb)
        mask=p.root/f'input/{name}_mask.png';Image.new('L',(40,30),255).save(mask)
        inferred['images'].append({'id':name,'path':f'input/{name}.png','sha256':sha(rgb),'resolution':[40,30],'split':'train'})
        inferred['segments'].append({'object_id':name,'image_id':name,'status':'UNIQUE_ESTIMATED','masks':[{'path':str(mask),'sha256':sha(mask)}]})
    before,_=modeling_groups(c,config,inferred)
    rgb=p.root/'input/a.png';Image.new('RGB',(40,30),'blue').save(rgb);inferred['images'][0]['sha256']=sha(rgb)
    after,_=modeling_groups(c,config,inferred)
    assert before['a']['fingerprint']!=after['a']['fingerprint']and before['b']['fingerprint']==after['b']['fingerprint']
    mask=p.root/'input/a_mask.png';Image.new('L',(40,30),0).save(mask);inferred['segments'][0]['masks'][0]['sha256']=sha(mask)
    after_mask,_=modeling_groups(c,config,inferred);assert after_mask['a']['fingerprint']!=after['a']['fingerprint']
    # Same byte content at a different path does not change the group cache key.
    moved=p.root/'input/renamed.png';moved.write_bytes(rgb.read_bytes());inferred['images'][0]['path']='input/renamed.png'
    relocated,_=modeling_groups(c,config,inferred);assert relocated['a']['fingerprint']==after_mask['a']['fingerprint']


def test_group_split_and_material_variants_preserve_the_original_asset(tmp_path):
    from real2sim_builder.automation import modeling_tasks,attach_modeled_assets,record_modeling_results,modeling_groups
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    import copy
    p=Project.create(tmp_path/'projects','group split');c=Candidate.create(p,'split')
    config={'objects':{'cup1':{'prompt':'cup','asset_group':'cups'},'cup2':{'prompt':'cup','asset_group':'cups'}}}
    modeling_tasks(c,config,{})
    source=asset_fixture(tmp_path/'asset');asset=register_object_asset(p,source,asset_id='cups')
    record_modeling_results(c,[asset]);attach_modeled_assets(c,config,{})
    original={str(f):sha(f)for f in (p.workspace/'object_assets').rglob('*')if f.is_file()}
    changed=copy.deepcopy(config);changed['objects']['cup2']['asset_group']='other_cup'
    modeling_tasks(c,changed,{});tasks=read(c.root/'modeling/tasks.json')['objects']
    assert len(tasks)==1 and tasks[0]['members']==['cup2']and tasks[0]['requires_review']
    changed['objects']['cup2']['modeling_action']='new';modeling_tasks(c,changed,{})
    assert read(c.root/'modeling/tasks.json')['objects'][0]['requires_review']is False
    new=register_object_asset(p,source,asset_id='other_cup',generation_id=read(c.root/'modeling/tasks.json')['groups']['other_cup']['request_id']);record_modeling_results(c,[new])
    attach_modeled_assets(c,changed,{})
    assert c.scene['objects'][0]['object_asset']['asset_id']=='cups'
    assert c.scene['objects'][1]['object_asset']['asset_id']=='other_cup'
    assert original=={f:sha(f)for f in original}
    variants=copy.deepcopy(config);variants['objects']['cup1']['material_variant']='red';variants['objects']['cup2']['material_variant']='blue'
    groups,_=modeling_groups(c,variants,{})
    assert set(groups)=={'cups__red','cups__blue'}


def test_ambiguous_group_needs_review_and_input_symlinks_are_rejected(tmp_path,monkeypatch):
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling
    from real2sim_builder.rendering import author_object_assets
    import os,sys,pytest
    p=Project.create(tmp_path/'projects','uncertain');c=Candidate.create(p,'review')
    config={'objects':{'cup1':{'prompt':'cup','asset_group':'cups','asset_group_relation':{'status':'UNRESOLVED','provenance':'estimated','evidence':[]}}}}
    modeling_tasks(c,config,{})
    executable=tmp_path/'not_called';executable.write_text('#!'+sys.executable+'\nraise AssertionError("must not invoke")\n');executable.chmod(0o700)
    assert run_codex_modeling(c,executable=executable)['status']=='ASSET_REUSE_REVIEW_REQUIRED'
    private=tmp_path/'test-secret.txt';private.write_text('fake secret')
    folder=tmp_path/'author';folder.mkdir();(folder/'inputs').mkdir();(folder/'inputs/link').symlink_to(private)
    script=folder/'author.py';script.write_text('raise AssertionError("must not run")')
    monkeypatch.setenv('REAL2SIM_BLENDER',os.environ['REAL2SIM_BLENDER'])
    with pytest.raises(ValueError,match='symlinks'):author_object_assets(c,script,['cup'])
    assert private.read_text()=='fake secret'


def test_changed_frozen_mask_cannot_reuse_a_matching_but_stale_result(tmp_path):
    from real2sim_builder.automation import modeling_tasks,record_modeling_results,run_codex_modeling
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    from PIL import Image
    import pytest,sys
    p=Project.create(tmp_path/'projects','frozen content');c=Candidate.create(p,'one')
    rgb=p.root/'input/photo.png';Image.new('RGB',(40,30),'white').save(rgb)
    mask=p.root/'input/mask.png';Image.new('L',(40,30),255).save(mask)
    inferred={'images':[{'id':'view','path':'input/photo.png','sha256':sha(rgb),'resolution':[40,30],'split':'train'}],
        'segments':[{'image_id':'view','object_id':'block','status':'UNIQUE_ESTIMATED','masks':[{'path':str(mask),'sha256':sha(mask)}]}]}
    modeling_tasks(c,{'objects':{'block':{'prompt':'cube'}}},inferred)
    record=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='block');record_modeling_results(c,[record])
    Image.new('L',(40,30),0).save(mask)
    executable=tmp_path/'not_called';executable.write_text('#!'+sys.executable+'\nraise AssertionError("remote must not run")\n');executable.chmod(0o700)
    with pytest.raises(ValueError,match='Frozen modeling input changed'):run_codex_modeling(c,executable=executable)


def test_new_request_beats_same_fingerprint_and_completes_once(tmp_path):
    from real2sim_builder.automation import modeling_tasks,record_modeling_results,attach_modeled_assets,group_asset,modeling_groups
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    import copy
    p=Project.create(tmp_path/'projects','new priority');c=Candidate.create(p,'one')
    config={'objects':{'cup':{'prompt':'cup','asset_group':'cups'}}}
    modeling_tasks(c,config,{});source=asset_fixture(tmp_path/'asset');old=register_object_asset(p,source,asset_id='cups')
    record_modeling_results(c,[old]);attach_modeled_assets(c,config,{})
    old_sha=sha(p.root/old['manifest']);new=copy.deepcopy(config);new['objects']['cup']['modeling_action']='new'
    report=modeling_tasks(c,new,{});task=read(c.root/'modeling/tasks.json');assert report['pending']==['cups']
    request=task['groups']['cups']['request_id'];assert request
    assert modeling_tasks(c,new,{})['pending']==['cups']
    assert read(c.root/'modeling/tasks.json')['groups']['cups']['request_id']==request
    created=register_object_asset(p,source,asset_id='cups',generation_id=request)
    assert created['version']!=old['version']
    record_modeling_results(c,[created]);assert attach_modeled_assets(c,new,{})['attached']==['cup']
    assert modeling_tasks(c,new,{})['pending']==[]
    assert read(c.root/'modeling/results.json')['groups']['cups']['request_status']=='REGISTERED'
    assert sha(p.root/old['manifest'])==old_sha


def test_explicit_asset_resolves_only_relation_uncertainty_not_geometry_conflict(tmp_path):
    from real2sim_builder.automation import modeling_groups,group_asset
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','manifest priority');c=Candidate.create(p,'one')
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='cups')
    config={'objects':{name:{'prompt':'cup','asset_group':'cups','asset_manifest':asset['manifest'],
        'asset_group_relation':{'status':'UNRESOLVED','provenance':'estimated','evidence':[]}}for name in('cup1','cup2')}}
    group=modeling_groups(c,config,{})[0]['cups']
    assert group_asset(c,group,{})[0]['manifest']==asset['manifest']
    config['measurements']=[{'id':'cup1','kind':'box','dimensions_m':[.1]*3,'evidence':['caliper']},
                            {'id':'cup2','kind':'box','dimensions_m':[.2]*3,'evidence':['caliper']}]
    group=modeling_groups(c,config,{})[0]['cups'];assert group_asset(c,group,{})[0]is None


def test_new_observations_reuse_identity_but_keep_generation_fingerprint(tmp_path):
    from real2sim_builder.automation import modeling_tasks,record_modeling_results,attach_modeled_assets
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    from PIL import Image
    import copy
    p=Project.create(tmp_path/'projects','moving cups');c=Candidate.create(p,'one')
    config={'objects':{'cup1':{'prompt':'paper cup','category':'paper_cup','asset_group':'cups'},'cup2':{'prompt':'paper cup','category':'paper_cup','asset_group':'cups'}}}
    modeling_tasks(c,config,{});asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='cups');record_modeling_results(c,[asset]);attach_modeled_assets(c,config,{})
    original=read(c.root/'modeling/results.json')['groups']['cups'];before=sha(p.root/asset['manifest'])
    rgb=p.root/'input/new_side.png';Image.new('RGB',(40,30),'white').save(rgb)
    # New views/background, independent raw observation identity. No new shape claim.
    inferred={'images':[{'id':'new_side','path':'input/new_side.png','sha256':sha(rgb),'resolution':[40,30],'split':'train'}],
        'segments':[{'image_id':'new_side','object_id':'cup1','status':'NOT_FOUND','masks':[]}]}
    assert modeling_tasks(c,config,inferred)['pending']==[]
    attach_modeled_assets(c,config,inferred)
    current=read(c.root/'modeling/results.json')['groups']['cups']
    assert current['fingerprint']==original['fingerprint']and current['fingerprint_inputs']==original['fingerprint_inputs']
    assert current['reuse_observations'][0]['fingerprint']!=original['fingerprint']
    config['objects']['cup3']={'prompt':'cup','category':'paper_cup','asset_group':'cups'}
    assert attach_modeled_assets(c,config,inferred)['attached']==['cup3']
    changed=copy.deepcopy(config);changed['objects']['cup1']['shape_constraints']={'rim':'new geometry'}
    assert 'cups'in modeling_tasks(c,changed,inferred)['pending']
    assert sha(p.root/asset['manifest'])==before


def test_memo_quotes_authenticate_source_without_reinterpreting_their_meaning(tmp_path):
    from real2sim_builder.automation import parse_scene_analysis
    from real2sim_builder.evidence import save_scene_memo,scene_memo
    import copy,pytest
    p=Project.create(tmp_path/'projects','memo proof');save_scene_memo(p,'종이컵 두 개는 동일한 제품이다. 위치와 회전만 다르다.')
    memo=scene_memo(p);reply=semantic_reply([{'id':n,'role':'receptacle','prompt':'cup','asset_group':'cups'}for n in('cup1','cup2')],memo['text'])
    reply['asset_groups'][0].update(relation_source='user_memo',evidence_quote='위치와 회전만 다르다.')
    relation=parse_scene_analysis(reply,memo)['cup1']['asset_group_relation']
    assert relation['provenance']=='user_declared'and not relation['semantics_verified']
    invalid=copy.deepcopy(reply);invalid['asset_groups'][0]['evidence_quote']='메모에 없는 문장'
    with pytest.raises(ValueError,match='quote'):parse_scene_analysis(invalid,memo)
    invalid=copy.deepcopy(reply);invalid['scene_memo_sha256']='stale'
    with pytest.raises(ValueError,match='stale'):parse_scene_analysis(invalid,memo)
    reply['asset_groups'][0].update(relation_source='visual_inference',evidence_quote='')
    assert parse_scene_analysis(reply,memo)['cup1']['asset_group_relation']['provenance']=='estimated'


def test_new_request_runs_real_blender_once_and_preserves_other_group(tmp_path,monkeypatch):
    from real2sim_builder.automation import modeling_tasks,record_modeling_results,attach_modeled_assets,run_codex_modeling
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    import copy,os,sys
    monkeypatch.setenv('REAL2SIM_BLENDER',os.environ['REAL2SIM_BLENDER'])
    p=Project.create(tmp_path/'projects','request integration');c=Candidate.create(p,'one')
    config={'objects':{'cup':{'prompt':'cup','asset_group':'cups'},'block':{'prompt':'block'}}}
    modeling_tasks(c,config,{})
    source=asset_fixture(tmp_path/'asset');old=register_object_asset(p,source,asset_id='cups');block=register_object_asset(p,source,asset_id='block')
    record_modeling_results(c,[old,block]);attach_modeled_assets(c,config,{})
    original={str(f):sha(f)for f in (p.workspace/'object_assets').rglob('*')if f.is_file()};untouched=c.scene['objects'][1]
    changed=copy.deepcopy(config);changed['objects']['cup']['modeling_action']='new';modeling_tasks(c,changed,{})
    counter=tmp_path/'calls.txt';executable=tmp_path/'fake_codex'
    script='import bpy\nbpy.ops.mesh.primitive_cube_add(size=.03)\nobj=bpy.context.object;obj["r2s_id"]="cups"\nbpy.ops.mesh.primitive_cube_add(size=.03)\ncol=bpy.context.object;col.parent=obj;col["r2s_collision"]=True\n'
    executable.write_text('#!'+sys.executable+'\nimport sys,json\nfrom pathlib import Path\na=sys.argv;r=Path(a[a.index("--cd")+1]);p=Path('+repr(str(counter))+');p.write_text(p.read_text()+"x"if p.exists()else"x")\n(r/"author.py").write_text('+repr(script)+')\nPath(a[a.index("--output-last-message")+1]).write_text(json.dumps({"script":"author.py"}))\n');executable.chmod(0o700)
    result=run_codex_modeling(c,executable=executable)
    assert result['assets'][0]['manifest']!=old['manifest']
    assert run_codex_modeling(c,executable=executable)['reused']is True and counter.read_text()=='x'
    attach_modeled_assets(c,changed,{})
    assert c.scene['objects'][1]==untouched
    assert original=={f:sha(f)for f in original}
    assert modeling_tasks(c,changed,{})['pending']==[]


def test_semantic_memo_facts_and_count_conflicts_stay_separate(tmp_path):
    from real2sim_builder.automation import modeling_tasks,run_codex_modeling,modeling_groups,group_asset
    from real2sim_builder.evidence import save_scene_memo
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    from PIL import Image
    import sys,json,copy
    p=Project.create(tmp_path/'projects','memo integration');c=Candidate.create(p,'one')
    note=tmp_path/'notes.md';note.write_text('종이컵 두 개는 동일한 제품이다.');save_scene_memo(p,note.read_bytes().decode('utf-8'))
    modeling_tasks(c,{},{});members=['cup1','cup2']
    proposals=[{'id':name,'prompt':'paper cup','category':'paper_cup','role':'receptacle','asset_group':'cups','group_status':'PROPOSED',
        'group_evidence':['memo'],'group_sources':[{'note_sha256':sha(note),'quote':note.read_text(),'subject':'종이컵','members':members}]if i==0 else[]}
        for i,name in enumerate(members)]
    executable=tmp_path/'fake_codex';executable.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index("--output-last-message")+1]).write_text('+repr(json.dumps(semantic_reply(proposals,note.read_text())))+')\n');executable.chmod(0o700)
    result=run_codex_modeling(c,executable=executable);config=read(p.root/'input/reconstruction.yaml')
    assert all(s['asset_group_relation']['provenance']=='user_declared'for s in config['objects'].values())
    assert len(modeling_groups(c,config,{})[0])==1
    rgb=p.root/'input/photo.png';Image.new('RGB',(40,30),'white').save(rgb)
    mask=p.root/'input/mask.png';Image.new('L',(40,30),255).save(mask)
    inferred={'images':[{'id':'view','path':'input/photo.png','sha256':sha(rgb),'resolution':[40,30],'split':'train'}],
        'segments':[{'object_id':name,'image_id':'view','status':'UNIQUE_ESTIMATED','masks':[{'path':str(mask),'sha256':sha(mask)}]}for name in members]}
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='cups')
    for s in config['objects'].values():s['asset_manifest']=asset['manifest']
    group=modeling_groups(c,config,inferred)[0]['cups']
    assert any('OBSERVED_INSTANCE_COUNT_MISMATCH'in n for n in group['blocked'])
    assert group_asset(c,group,{})[0]is None
    assert all(r['provenance']=='user_declared'for r in group['relations'])


def test_only_codex_structured_shape_changes_review_the_affected_group(tmp_path):
    from real2sim_builder.automation import modeling_tasks,record_modeling_results,attach_modeled_assets,parse_scene_analysis
    from real2sim_builder.object_assets import register_object_asset
    from real2sim_builder.evidence import save_scene_memo,scene_memo
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','memo changes');c=Candidate.create(p,'two')
    config={'objects':{'cup':{'prompt':'paper cup','category':'paper_cup','asset_group':'cups'},'block':{'prompt':'red cube','category':'cube'}}}
    modeling_tasks(c,config,{})
    source=asset_fixture(tmp_path/'asset');assets=[register_object_asset(p,source,asset_id=n)for n in('cups','block')]
    record_modeling_results(c,assets);attach_modeled_assets(c,config,{})
    before={str(f):sha(f)for f in(p.workspace/'object_assets').rglob('*')if f.is_file()}
    for text,change,pending in [('位置を変えて撮り直した。','none',[]),('Change the cup geometry.','geometry',['cups'])]:
        save_scene_memo(p,text);memo=scene_memo(p)
        reply=semantic_reply([{'id':n,'role':'manipulable_object',**spec}for n,spec in config['objects'].items()],text)
        reply['asset_groups'][0]['change_kind']=change
        config['objects']=parse_scene_analysis(reply,memo)
        assert modeling_tasks(c,config,{})['pending']==pending
    assert before=={f:sha(f)for f in before}


def test_partial_new_request_retries_only_the_unfinished_group(tmp_path,monkeypatch):
    from real2sim_builder.automation import modeling_tasks,record_modeling_results,attach_modeled_assets,run_codex_modeling
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    import os,sys,copy,pytest
    monkeypatch.setenv('REAL2SIM_BLENDER',os.environ['REAL2SIM_BLENDER'])
    p=Project.create(tmp_path/'projects','partial requests');c=Candidate.create(p,'two')
    config={'objects':{name:{'prompt':'cube'}for name in('a','b')}};modeling_tasks(c,config,{})
    source=asset_fixture(tmp_path/'asset');old=[register_object_asset(p,source,asset_id=n)for n in('a','b')]
    record_modeling_results(c,old);attach_modeled_assets(c,config,{})
    original={str(f):sha(f)for f in (p.workspace/'object_assets').rglob('*')if f.is_file()}
    changed=copy.deepcopy(config)
    for spec in changed['objects'].values():spec['modeling_action']='new'
    modeling_tasks(c,changed,{})
    executable=tmp_path/'fake_codex';log=tmp_path/'requested.json'
    executable.write_text('#!'+sys.executable+'\n'+'''import sys,json
from pathlib import Path
a=sys.argv;r=Path(a[a.index('--cd')+1]);task=json.loads((r/'tasks.json').read_text());names=[x['asset_group']for x in task['objects']]
log=Path('''+repr(str(log))+''');history=json.loads(log.read_text())if log.exists()else[];history.append(names);log.write_text(json.dumps(history))
code=['import bpy']
for name in names:
 code += ['bpy.ops.mesh.primitive_cube_add(size=.03)', 'obj=bpy.context.object;obj["r2s_id"]='+repr(name)]
 code += ['bpy.ops.mesh.primitive_torus_add(major_radius=.02,minor_radius=.01)'if name=='b'and len(names)==2 else'bpy.ops.mesh.primitive_cube_add(size=.03)', 'col=bpy.context.object;col.parent=obj;col["r2s_collision"]=True']
(r/'author.py').write_text('\\n'.join(code))
Path(a[a.index('--output-last-message')+1]).write_text(json.dumps({'script':'author.py'}))
''');executable.chmod(0o700)
    with pytest.raises(ValueError):run_codex_modeling(c,executable=executable)
    after=read(c.root/'modeling/results.json')['groups'];completed_a=after['a']['manifest']
    assert completed_a!=old[0]['manifest']and after['b']['manifest']==old[1]['manifest']
    assert original=={f:sha(f)for f in original}
    result=run_codex_modeling(c,executable=executable)
    assert len(result['assets'])==2 and read(log)==[['a','b'],['b']]
    assert read(c.root/'modeling/results.json')['groups']['a']['manifest']==completed_a


def test_valid_scene_binding_precedes_an_unconfirmed_legacy_output(tmp_path):
    from real2sim_builder.automation import modeling_tasks,attach_modeled_assets
    from real2sim_builder.object_assets import register_object_asset,instance_operation
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','existing Scene');c=Candidate.create(p,'known')
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='actual_cup')
    c.edit([instance_operation(p,asset['manifest'],'cup',role='receptacle')])
    write(c.root/'modeling/results.json',{'assets':{'cup':asset['manifest']}})
    config={'objects':{'cup':{'prompt':'cup'}}}
    assert modeling_tasks(c,config,{})['pending']==[]
    assert attach_modeled_assets(c,config,{})['attached']==[]


def test_scene_asset_selection_precedes_an_older_automatic_cache(tmp_path):
    from real2sim_builder.automation import modeling_tasks,record_modeling_results,attach_modeled_assets
    from real2sim_builder.object_assets import register_object_asset,instance_operation
    from test_object_assets import asset_fixture
    p=Project.create(tmp_path/'projects','Scene selection');c=Candidate.create(p,'one')
    config={'objects':{'cup':{'prompt':'cup'}}}
    modeling_tasks(c,config,{})
    old=register_object_asset(p,asset_fixture(tmp_path/'old'),asset_id='cup');record_modeling_results(c,[old])
    selected=register_object_asset(p,asset_fixture(tmp_path/'selected'),asset_id='selected_cup')
    c.edit([instance_operation(p,selected['manifest'],'cup',role='receptacle')])
    before=c.scene
    assert modeling_tasks(c,config,{})['pending']==[]
    assert attach_modeled_assets(c,config,{})['attached']==[]
    assert c.scene==before


def test_recaptured_crop_does_not_overwrite_original_generation_input(tmp_path):
    from real2sim_builder.automation import modeling_tasks,record_modeling_results
    from real2sim_builder.object_assets import register_object_asset
    from test_object_assets import asset_fixture
    from PIL import Image
    p=Project.create(tmp_path/'projects','immutable crops');c=Candidate.create(p,'one')
    config={'objects':{'cup':{'prompt':'cup'}}}
    rgb=p.root/'input/photo.png';mask=p.root/'input/mask.png'
    Image.new('RGB',(40,30),'white').save(rgb);Image.new('L',(40,30),255).save(mask)
    def observation():
        return {'images':[{'id':'view','path':'input/photo.png','sha256':sha(rgb),'resolution':[40,30],'split':'train'}],
            'segments':[{'image_id':'view','object_id':'cup','status':'UNIQUE_ESTIMATED','masks':[{'path':str(mask),'sha256':sha(mask)}]}]}
    modeling_tasks(c,config,observation())
    asset=register_object_asset(p,asset_fixture(tmp_path/'asset'),asset_id='cup');record_modeling_results(c,[asset])
    original=read(c.root/'modeling/results.json')['groups']['cup']['references'][0]['crops'][0]
    Image.new('RGB',(40,30),'blue').save(rgb)
    modeling_tasks(c,config,observation())
    assert sha(original['path'])==original['sha256']
    current=read(c.root/'modeling/tasks.json')['groups']['cup']['references'][0]['crops'][0]
    assert current['path']!=original['path']


def test_semantic_refresh_preserves_explicit_config_group_without_provenance_field(tmp_path):
    from real2sim_builder.automation import modeling_tasks,save_configuration,run_codex_modeling
    import sys,json
    p=Project.create(tmp_path/'projects','manual Group');c=Candidate.create(p,'one')
    modeling_tasks(c,{}, {})
    saved={'objects':{name:{'prompt':'cup','asset_group':'chosen_cups'}for name in('cup1','cup2')}}
    save_configuration(p,saved)
    proposals=[{'id':name,'prompt':'cup','category':'cup','role':'receptacle','asset_group':'inferred_cups',
                'group_status':'PROPOSED','group_evidence':['similar appearance']}for name in saved['objects']]
    executable=tmp_path/'fake_codex';executable.write_text('#!'+sys.executable+'\nimport sys\nfrom pathlib import Path\nPath(sys.argv[sys.argv.index("--output-last-message")+1]).write_text('+repr(json.dumps(semantic_reply(proposals)))+')\n');executable.chmod(0o700)
    run_codex_modeling(c,executable=executable)
    config=read(p.root/'input/reconstruction.yaml')
    assert {r['asset_group']for r in config['objects'].values()}=={'chosen_cups'}


def test_changed_memo_keeps_prior_execution_snapshot_but_rejects_old_response(tmp_path):
    from real2sim_builder.evidence import save_scene_memo,scene_memo
    from real2sim_builder.automation import parse_scene_analysis,modeling_tasks
    import pytest
    p=Project.create(tmp_path/'projects','current memo');c=Candidate.create(p,'one')
    save_scene_memo(p,'같은 컵 두 개')
    old=scene_memo(p);reply=semantic_reply([{'id':n,'role':'receptacle','prompt':'cup','asset_group':'cups'}for n in('cup1','cup2')],old['text'])
    reply['asset_groups'][0].update(relation_source='user_memo',evidence_quote=old['text'])
    config={'objects':parse_scene_analysis(reply,old)};modeling_tasks(c,config,{})
    frozen=read(c.root/'modeling/tasks.json')['scene_memo']
    save_scene_memo(p,'서로 다른 컵 두 개')
    with pytest.raises(ValueError,match='stale'):parse_scene_analysis(reply,scene_memo(p))
    modeling_tasks(c,config,{})
    task=read(c.root/'modeling/tasks.json')
    assert task['scene_memo']['text']=='서로 다른 컵 두 개'and task['status']=='WAITING_FOR_CODEX_ANALYSIS'
    assert __import__('pathlib').Path(frozen['path']).read_text()==old['text']
    assert 'briefs'not in p.evidence


def test_scene_memos_are_independent_and_require_new_codex_interpretation(tmp_path):
    from real2sim_builder.evidence import save_scene_memo,scene_memo
    from real2sim_builder.automation import parse_scene_analysis,modeling_groups
    import pytest
    a=Project.create(tmp_path/'scenes','A');b=Project.create(tmp_path/'scenes','B');c=Candidate.create(a,'one')
    save_scene_memo(a,'두 컵은 같은 종이컵이야.');save_scene_memo(b,'파란 상자 하나')
    reply=semantic_reply([{'id':n,'role':'receptacle','prompt':'cup','asset_group':'cups'}for n in('cup1','cup2')],scene_memo(a)['text'])
    reply['asset_groups'][0].update(relation_source='user_memo',evidence_quote=scene_memo(a)['text'])
    config={'objects':parse_scene_analysis(reply,scene_memo(a))};config['objects']['block']={'prompt':'cube'}
    with pytest.raises(ValueError,match='stale'):parse_scene_analysis(reply,scene_memo(b))
    save_scene_memo(a,scene_memo(a)['text']+'\n블록 위치 이동.')
    groups,_=modeling_groups(c,config,{})
    assert groups['cups']['memo_relation_stale']and not groups['block'].get('memo_relation_stale')
    reply=semantic_reply([{'id':n,'role':'receptacle','prompt':'cup','asset_group':'cups'}for n in('cup1','cup2')],scene_memo(a)['text'])
    reply['asset_groups'][0].update(relation_source='user_memo',evidence_quote='두 컵은 같은 종이컵이야.')
    config['objects'].update(parse_scene_analysis(reply,scene_memo(a)))
    assert not modeling_groups(c,config,{})[0]['cups'].get('memo_relation_stale')


def test_free_memo_expressions_are_not_classified_again_by_python():
    from real2sim_builder.automation import parse_scene_analysis
    import hashlib
    expressions=['두 컵은 같은 종이컵이야.','두 컵은 동일한 제품이다.','오른쪽 컵 둘은 똑같고 위치만 달라.',
        '두 종이컵의 형상과 무늬는 동일해.','The two paper cups are identical products.','完全に同じカップだよ。']
    for text in expressions:
        memo={'text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
        answer=semantic_reply([{'id':n,'prompt':'paper cup','role':'receptacle','asset_group':'cups'}for n in('cup1','cup2')],text)
        answer['asset_groups'][0].update(relation_source='user_memo',evidence_quote=text)
        parsed=parse_scene_analysis(answer,memo)
        assert all(s['asset_group_relation']['provenance']=='user_declared'for s in parsed.values())
        assert all(s['asset_group_relation']['semantics_verified']is False for s in parsed.values())
