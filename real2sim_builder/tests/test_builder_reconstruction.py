"""Image-only drafts keep unresolved geometry explicit; no retired Scan route."""
from PIL import Image
from real2sim_builder.project import Project
from real2sim_builder.reconstruction import run


def test_image_only_pipeline_requests_metric_evidence_without_export(tmp_path):
    from real2sim_builder.project import add_image
    p=Project.create(tmp_path/'projects','unknown');image=tmp_path/'real.png';Image.new('RGB',(64,48),'red').save(image);add_image(p,image)
    state=run(p);assert state['status']=='NEEDS_MORE_DATA' and len(state['needs'])>=2
    assert p.scene['cameras'][0]['K']['value'] is None and not list((p.root/'exports').glob('*'))


def test_validation_report_completes_with_no_images_and_no_fake_pass(tmp_path):
    from real2sim_builder.reconstruction import validate_scene
    from test_builder_export import legacy_scene
    p=Project.create(tmp_path/'projects','validation');p.save_scene(legacy_scene())
    report,rendered=validate_scene(p,p.scene,None,tmp_path/'review',{'mae':.1,'silhouette_iou':.8,'reprojection_px':3.})
    assert report['passed'] is False and report['physics_status']=='PHYSICS_NOT_VALIDATED'
    assert report['input_signature']==p.signature() and 'diagnosis' in report and 'coverage' in report
    assert rendered=={}
