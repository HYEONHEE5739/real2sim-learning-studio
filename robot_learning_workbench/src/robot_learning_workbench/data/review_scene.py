"""Read-only review geometry using recorded Scene identity and Builder FK.

Meshes are simplified for display only. No simulator, controller or physics replay.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from real2sim_builder.calibration.geometry import mesh_data,origin,link_transforms


def preview_triangles(vertices,faces):
    """Original preview's vertex clustering, never a change to stored assets."""
    triangles=np.asarray(vertices)[np.asarray(faces)]
    if len(triangles)<100:return triangles
    flat=triangles.reshape(-1,3);tolerance=.0045
    while True:
        cells=np.round(flat/tolerance).astype(int)
        _,inverse=np.unique(cells,axis=0,return_inverse=True);points=np.zeros((inverse.max()+1,3))
        np.add.at(points,inverse,flat);points/=np.bincount(inverse)[:,None]
        reduced=inverse.reshape(-1,3);reduced=reduced[(reduced[:,0]!=reduced[:,1])&(reduced[:,1]!=reduced[:,2])&(reduced[:,0]!=reduced[:,2])]
        _,indices=np.unique(np.sort(reduced,axis=1),axis=0,return_index=True)
        output=points[reduced[indices]]
        if len(output)<=300:return output
        tolerance*=1.25



def box_triangles(dimensions):
    vertices=np.array([[x,y,z]for x in(-.5,.5)for y in(-.5,.5)for z in(-.5,.5)])*dimensions
    return vertices[np.array([[0,1,3],[0,3,2],[4,6,7],[4,7,5],[0,4,5],[0,5,1],[2,3,7],[2,7,6],[0,2,6],[0,6,4],[1,5,7],[1,7,3]])]


class RobotVisual:
    def __init__(self,urdf):
        self.urdf=Path(urdf);self.parts=[];root=ET.parse(urdf).getroot()
        for link in root.findall('link'):
            for visual in link.findall('visual'):
                mesh=visual.find('geometry/mesh')
                if mesh is None:continue
                path=mesh.get('filename')
                if path.startswith('package://'):raise ValueError('Preview needs resolved package mesh paths')
                vertices,faces=mesh_data((self.urdf.parent/path).resolve());vertices=vertices*np.fromstring(mesh.get('scale','1 1 1'),sep=' ')
                triangles=preview_triangles(vertices,faces);transform=origin(visual.find('origin'))
                triangles=triangles@transform[:3,:3].T+transform[:3,3]
                material=visual.find('material');dark=material is not None and material.get('name')=='sts3215'
                self.parts.append(dict(link=link.get('name'),triangles=triangles.tolist(),dark=dark))

    def poses(self,joints):return {name:pose.tolist()for name,pose in link_transforms(self.urdf,joints).items()}

    def bounds(self,names,states):
        low=np.full(3,np.inf);high=-low
        for state in states[::max(1,len(states)//40)]:
            poses=link_transforms(self.urdf,dict(zip(names,state)))
            for part in self.parts:
                t=poses[part['link']];points=np.array(part['triangles']).reshape(-1,3)@t[:3,:3].T+t[:3,3]
                if len(points):low=np.minimum(low,points.min(0));high=np.maximum(high,points.max(0))
        return [low.tolist(),high.tolist()]if np.isfinite(low).all()else None


class ReviewScene:
    def __init__(self,catalog,workspace):
        from scene_contract.package import load_scene,SceneIdentity
        from ..engines.mujoco.model import _execution_urdf
        from .native import file_sha256
        from real2sim_builder.files import read
        identity=catalog.execution.get('scene_identity');self.package=None
        if not identity:raise ValueError('기록된 Scene identity가 없어 로봇 모델을 연결하지 않습니다.')
        recording=catalog.execution.get('recording',{})
        if recording.get('pose_frame')!='robot_base'or recording.get('units')!='m_rad_s':raise ValueError('로봇 모델 표시에는 명시된 robot_base·model rad 기록이 필요합니다.')
        for project in sorted((Path(workspace)/'scenes').glob('*/project.yaml')):
            for record in read(project).get('execution_packages',[]):
                if all(record.get(k)==identity.get(k)for k in('scene_id','revision','manifest_sha256')):
                    self.package=load_scene(project.parent/record['path']/'scene.json',expected=SceneIdentity(**identity));break
            if self.package is not None:break
        if self.package is None:raise ValueError('기록된 Scene Revision을 찾지 못했습니다. 영상/기록 수치는 그대로 검토할 수 있습니다.')
        path=_execution_urdf(self.package)
        if file_sha256(path)!=catalog.execution.get('urdf_sha256'):raise ValueError('기록된 실행 URDF와 Preview 모델이 다릅니다.')
        self.robot=RobotVisual(path);self.joints=catalog.execution['recording']['joint_order'];self.objects={}
        for name,obj in self.package.scene['objects'].items():
            if obj['role']not in('task_object','receptacle'):continue
            visual=obj['visual'];transform=np.array(visual.get('local_transform',np.eye(4)));scale=np.array(visual.get('scale',[1,1,1]))
            if visual['kind']=='mesh':
                vertices,faces=mesh_data(self.package.root/visual['asset_path']);triangles=preview_triangles(vertices*scale,faces)
            else:triangles=box_triangles(np.array(visual['dimensions_m'])*scale)
            triangles=triangles@transform[:3,:3].T+transform[:3,3]
            color='#e46b64'if 'red'in name else'#6685de'if 'blue'in name else'#55b99b'if 'green'in name else'#deb970'
            self.objects[name]=dict(triangles=triangles.tolist(),color=color)

    def info(self,states):return dict(robot=self.robot.parts,objects=self.objects,frame='robot_base',unit='m',geometry='display_simplification',bounds=self.robot.bounds(self.joints,states)if states else None)

    def region(self,execution,object_id):
        from ..tasks.placement import WorkspaceParams,validate_params
        from scene_contract.transforms import resolve_transform
        binding=execution.get('placements',{}).get('objects.'+object_id+'.placement')
        if not binding or binding['name']!='placement.random_workspace':return None
        params=WorkspaceParams(**binding['params']);validate_params(params,self.package);lo,hi=params._context['bounds'];size=params._context['workspace_dimensions_m']
        transform=resolve_transform(self.package.scene['frames'],source=params.frame,target='robot_base')
        def polygon(low,high):
            xy=np.array([[low[0],low[1]],[high[0],low[1]],[high[0],high[1]],[low[0],high[1]]]);xyz=np.c_[xy,np.zeros(4)]
            return (xyz@transform[:3,:3].T+transform[:3,3])[:,:2].tolist()
        return dict(support=polygon(-size/2,size/2),allowed=polygon(lo,hi),robot_xy=[0.,0.],mode='uniform')
