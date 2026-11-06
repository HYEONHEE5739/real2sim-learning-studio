def test_pair_cli_forwards_continuous_execution_options(tmp_path,monkeypatch):
    from real2sim_builder.project import Project
    from real2sim_builder.cli import main
    from real2sim_builder import automation
    p=Project.create(tmp_path,'pair cli');seen=[]
    def run(project,**kwargs):seen.append(kwargs);return {'status':'NEEDS_MORE_DATA'}
    monkeypatch.setattr(automation,'refit_pairs',run)
    assert main(['refit-pairs',str(p.root),'--candidate','pair','--scene-state','layout','--run-modeling','--max-review-calls','1'])==2
    assert seen[0]['run_modeling'] and seen[0]['max_review_calls']==1


def test_pair_mapping_allows_only_a_changed_local_port():
    import copy,hashlib,json
    from real2sim_builder.capture import mapping_coordinates_equal
    def signed(port,coefficient=1):
        m={'schema':'so101.precision-joint-mapping/1','profile':{'identity':{'port':port,'serial':'same'},'coefficient':coefficient}}
        m['sha256']=hashlib.sha256(json.dumps(m,sort_keys=True,separators=(',',':')).encode()).hexdigest();return m
    assert mapping_coordinates_equal(signed('memory'),signed('/dev/ttyACM0'))
    assert not mapping_coordinates_equal(signed('memory'),signed('memory',2))
    bad=signed('memory');bad['profile']['identity']['serial']='other'
    assert not mapping_coordinates_equal(signed('memory'),bad)
