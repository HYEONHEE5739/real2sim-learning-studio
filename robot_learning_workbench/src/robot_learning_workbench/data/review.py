"""One read-only Episode, persistent MP4 decoders and its recorded time index."""
from dataclasses import replace
import math
import numpy as np
from .native import load_catalog,DataError
from .curation import _episode,_chunks,_video_frames


class EpisodeReview:
    def __init__(self,source,selection_id,*,workspace=None,scene_cache=None):
        self.catalog=load_catalog(source);self.episode=_episode(self.catalog,selection_id)
        self.official={};self.decoders={};self.current={};self.file=None
        ep=self.episode;self.stop=ep.num_frames if ep.stop is None else ep.stop
        self.fields=('observation.state','action')if ep.format=='lerobot'else('obs/policy/joint_pos','joint_targets')
        clock='timestamp'if ep.format=='lerobot'else'obs/timestamp'
        self.timestamps=np.concatenate(list(_chunks((ep,),clock,2048,self.official))).reshape(-1)
        if not len(self.timestamps)or not np.isfinite(self.timestamps).all()or np.any(np.diff(self.timestamps)<=0):
            raise DataError('CURATION_INVALID','timestamp','Recorded playback times must be finite and increasing')
        if ep.format=='isaac_hdf5':
            import h5py
            self.file=h5py.File(ep.file,'r');self.group=self.file['data/'+ep.key]
        self.scene=None;self.scene_note=''
        if workspace is not None:
            from .review_scene import ReviewScene
            from .native import digest
            try:
                key=digest({'scene':self.catalog.execution.get('scene_identity'),'urdf':self.catalog.execution.get('urdf_sha256'),'recording':self.catalog.execution.get('recording')})
                cache=scene_cache if scene_cache is not None else{}
                if key not in cache:cache[key]=ReviewScene(self.catalog,workspace)
                self.scene=cache[key]
            except (ValueError,OSError,KeyError,ImportError)as error:self.scene_note=str(error)

    def info(self):
        plot=episode_plot(self.catalog,self.episode.selection_id or self.episode.episode_id)
        return dict(timestamps=self.timestamps.tolist(),plot=plot,
                    scene=self.scene.info(plot.get('states'))if self.scene is not None else{},scene_note=self.scene_note,
                    regions={name:self.scene.region(self.catalog.execution,name)for name in self.scene.objects}if self.scene is not None else{})

    def frame(self,frame):
        ep=self.episode
        if type(frame)is not int or not 0<=frame<len(self.timestamps):raise DataError('CURATION_INVALID','frame','Frame outside current selection')
        index=ep.start+frame;images={};pts={}
        for camera,media in ep.media.items():
            previous=self.current.get(camera)
            if previous is None or index<previous[0]or index-previous[0]>max(1,math.ceil(float(media['fps']))):
                if camera in self.decoders:self.decoders[camera].close()
                self.decoders[camera]=_video_frames(ep,camera,index,self.stop);previous=next(self.decoders[camera])
            while previous[0]<index:previous=next(self.decoders[camera])
            self.current[camera]=previous;_,pts[camera],images[camera]=previous
        if self.file is not None:values={field:self.group[field][index].tolist()for field in self.fields}
        else:
            single=replace(ep,start=index,stop=index+1)
            values={field:next(_chunks((single,),field,1,self.official))[0].tolist()for field in self.fields}
        objects={};eef=None
        if self.file is not None:
            for name,field in self.group.get('obs/datagen_info/object_pose',{}).items():objects[name]=field[index].tolist()
            if 'obs/datagen_info/eef_pose/tool0'in self.group:eef=self.group['obs/datagen_info/eef_pose/tool0'][index,:3,3].tolist()
        return dict(selection_id=ep.selection_id or ep.episode_id,selection_frame=frame,original_frame=index,
                    timestamp_s=float(self.timestamps[frame]),values=values,rgb=images,video_pts_s=pts,object_poses=objects,eef=eef,
                    robot_poses=self.scene.robot.poses(dict(zip(self.scene.joints,values[self.fields[0]])))if self.scene is not None else{})

    def close(self):
        for decoder in self.decoders.values():decoder.close()
        self.decoders.clear();self.current.clear()
        if self.file is not None:self.file.close();self.file=None


def episode_plot(source: str, selection_id: str) -> dict:
    """Bounded read-only plot projection of existing selected numeric rows."""
    import numpy as np
    from . import curation
    catalog=curation._catalog(source);ep=curation._episode(catalog,selection_id)
    total=(ep.stop if ep.stop is not None else ep.num_frames)-ep.start
    indices=np.unique(np.r_[np.arange(0,total,max(1,int(np.ceil(total/511)))),total-1]).astype(int)
    def samples(name):
        selected=[];offset=0
        for block in curation._chunks((ep,),name,2048,{}):
            take=indices[(indices>=offset)&(indices<offset+len(block))]-offset
            if len(take):selected.append(block[take])
            offset+=len(block)
        return np.concatenate(selected)
    target='action'if ep.format=='lerobot'else'joint_targets'
    values=curation._numeric(samples(target),target)
    semantics=curation._field_semantics(catalog,target)
    clock='timestamp'if ep.format=='lerobot'else'obs/timestamp'
    times=samples(clock).reshape(-1)
    eef=None;events={};event_times={};states=None;object_paths={}
    state_field='observation.state'if ep.format=='lerobot'else'obs/policy/joint_pos'
    if ep.format=='isaac_hdf5':
        import h5py
        with h5py.File(ep.file,'r')as file:
            group=file['data/'+ep.key]
            name='obs/datagen_info/eef_pose/tool0'
            if name in group:eef=samples(name)[:,:3,3].tolist()
            for obj in group.get('obs/datagen_info/object_pose',{}):object_paths[obj]=samples('obs/datagen_info/object_pose/'+obj).tolist()
            if state_field in group:states=samples(state_field).tolist()
            for prefix in('obs/events','obs/datagen_info/subtask_term_signals'):
                if prefix not in group:continue
                for event in group[prefix]:
                    name=prefix+'/'+event
                    if event in events:continue
                    offset=0
                    for block in curation._chunks((ep,),name,2048,{}):
                        array=curation._numeric(block,name);first=np.flatnonzero(array.reshape(len(array),-1).any(1))
                        if len(first):
                            events[event]=int(offset+first[0]);event_times[event]=float(np.asarray(group['obs/timestamp'][ep.start+events[event]]).reshape(-1)[0]-np.asarray(group['obs/timestamp'][ep.start]).reshape(-1)[0]);break
                        offset+=len(block)
    elif ep.format=='lerobot':states=samples(state_field).tolist()
    state_semantics=curation._field_semantics(catalog,state_field)
    comparable=semantics['unit']=='rad'and state_semantics['unit']=='rad'and bool(semantics['joint_order'])and semantics['joint_order']==state_semantics['joint_order']
    return dict(selection_id=selection_id,frames=total,original_range=[ep.start,ep.start+total],indices=indices.tolist(),
                targets=values.tolist(),states=states,state_unit=state_semantics['unit'],state_joint_order=state_semantics['joint_order'],state_action_comparable=comparable,timestamps=times.tolist(),target_unit=semantics['unit'],joint_order=semantics['joint_order'],
                eef=eef,object_paths=object_paths,eef_frame=catalog.execution.get('recording',{}).get('pose_frame','unknown'),eef_unit='m'if catalog.execution.get('recording',{}).get('units')=='m_rad_s'else'unknown',events=events,event_times_s=event_times,event_phase='recorded pre-step latch; not new Task evaluation',sampled=len(indices)<total)

