"""Single Native publisher helpers; engine loops own step/reset/resources."""
from dataclasses import asdict
from pathlib import Path
import numpy as np
from .native import load_catalog,history,atomic_json


def publish_event(output,episode_id,events):
    catalog=load_catalog(output)
    events({'kind':'episode_committed','payload':{'episode_id':episode_id,'dataset_path':str(catalog.root),'dataset_identity':asdict(catalog.identity)}})



def publish_annotation(owner,seg,claim,ep,media,report,catalog,original,events):
    from ..recipe import _plain
    summary={k:v for k,v in report.items() if k not in ('trace','source_initial_snapshot','replay_initial_snapshot')}
    if ep is not None:
        eid='annotation-'+str(claim['attempt']-1)
        seg.write_episode(ep,episode_id=eid,metadata={**report,'source_lineage':{'dataset':_plain(catalog.identity),'episode_id':original.episode_id,'key':original.key},'source_metadata':original.metadata},media=media)
        for path in media.values():Path(path).unlink()
        seg.record_attempt(claim,status='success',episode_id=eid,diagnostics=summary);seg.commit();publish_event(owner.root,eid,events)
    else:
        seg.record_attempt(claim,status='cancelled' if report['status']=='cancelled' else 'failure',diagnostics=summary);seg.commit()
    return ep is not None,{k:v for k,v in report.items() if k not in ('trace','source_initial_snapshot','replay_initial_snapshot')}



def publish_generation(owner,segment,claim,ep,media,report,catalog,kin,events):
    """One Native publisher for single and concurrent MuJoCo attempts."""
    from ..recipe import _plain
    summary={k:v for k,v in report.items() if k!='ik_diagnostics'}
    rows=report['ik_diagnostics'];summary['ik_summary']={'applied_steps':len(rows),'native_nonconverged_steps':sum(not r['converged'] for r in rows),'pose_diagnostic_failed_steps':sum(not r['common_pose_passed'] for r in rows)}
    summary['last_applied_ik']=rows[-1] if rows else None
    if ep is not None:
        eid='datagen-'+str(claim['attempt'])
        lineage=[{'dataset':_plain(catalog.identity),**selection,'source_lineage':catalog.episodes[selection['source_index']].metadata.get('source_lineage')} for selection in report['selected_sources']]
        segment.write_episode(ep,episode_id=eid,metadata={**summary,'non_tensor_arrays':{'ik/failure_reason':np.asarray([r['failure_reason'].encode() for r in report['ik_diagnostics']],dtype='S64')},'ik_identity':kin.identity,'source_lineage':lineage,'success_source':'stable_grasp_and_placement'},media=media)
        for p in media.values():Path(p).unlink()
        segment.record_attempt(claim,status='success',episode_id=eid,diagnostics=summary);segment.commit();publish_event(owner.root,eid,events)
    else:
        for p in segment.folder.glob('*.mp4'):p.unlink()
        status='cancelled' if report['status']=='cancelled' else 'ik_failure' if report['category']=='ik_failure' else 'failure'
        segment.record_attempt(claim,status=status,diagnostics=summary);segment.commit()
    return ep is not None



def publish_attempt(owner,segment,claim,ep,media,report,events):
    eid='evaluation-'+str(claim['attempt']);saved=None
    if ep is not None:
        ep.success=report['success'];segment.write_episode(ep,episode_id=eid,metadata={**report,'success_source':'simulation_place_condition'},media=media)
        for path in media.values():Path(path).unlink()
        saved=eid
    status='cancelled' if report['category']=='cancelled' else 'success' if report['success'] else 'failure'
    summary_report={k:v for k,v in report.items() if k!='initial_snapshot'}
    segment.record_attempt(claim,status=status,episode_id=saved,diagnostics=summary_report);segment.commit()
    if saved:publish_event(owner.root,eid,events)
    rows=history(owner.root);successes=sum(row['status']=='success' for row in rows)
    summary=dict(attempts=len(rows),successes=successes,failures=sum(row['status']=='failure' for row in rows),cancelled=sum(row['status']=='cancelled' for row in rows),
        safety_rejections=sum(row.get('diagnostics',{}).get('category')=='action_safety_rejection' for row in rows),success_rate=successes/len(rows) if rows else None,
        denominator='all recorded attempts, including rejection/errors/cancellation',completed_episodes=len(load_catalog(owner.root).episodes),latest=summary_report)
    atomic_json(owner.root/'evaluation-summary.json',summary)
    return summary

