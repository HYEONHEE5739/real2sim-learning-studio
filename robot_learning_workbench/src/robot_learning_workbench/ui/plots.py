"""Qt inspection plots ported from workflow/curation_ui.py:Plot.

FK and model loading stay in the Backend. Qt projects bounded display meshes
with recorded poses and draws trajectory/quality/distribution presentation.
"""
import json
import numpy as np
from PyQt6.QtCore import Qt,QPointF,QRectF,pyqtSignal
from PyQt6.QtGui import QPainter,QColor,QPen,QPolygonF
from PyQt6.QtWidgets import QWidget,QToolTip
SPLIT_COLORS={'train':'#55d6b0','val':'#69b9ff'}


class ReviewPlot(QWidget):
    picked=pyqtSignal(int)
    def __init__(self, mode):
        super().__init__();self.mode=mode;self.rows=[];self.row=None
        self.yaw=.7;self.pitch=.55;self.drag=None;self.screen=[];self.zoom=1.0
        self.frame=0;self.payload={};self.sample_frame=0;self.bounds_key=None;self.cached_bounds=None
        self.action_lines=[];self.action_row=None;self.scene={};self.parts=[];self.mesh=None;self.selected=-1;self.setMouseTracking(mode in('actions','scatter'))
        self.setMinimumSize(240,200)
    def set_view(self, name):
        self.zoom=1.0
        self.yaw,self.pitch={'3D':(.7,.65),'XY':(0.,0.),'XZ':(0.,np.pi/2),'YZ':(np.pi/2,np.pi/2)}[name]
        self.update()
    def bounds(self):
        key=(id(self.row),id(self.scene))
        if self.bounds_key==key:return self.cached_bounds
        points=list(self.row.get('ee')or[])
        if self.scene.get('bounds'):points.extend(self.scene['bounds'])
        for name,poses in self.row.get('object_paths',{}).items():
            if name in self.scene.get('objects',{}):points.extend(np.array(poses)[:,:3,3])
        if self.mesh is not None:
            vertices=self.mesh[0].reshape(-1,3);points.extend([vertices.min(0),vertices.max(0)])
        xyz=np.asarray(points or[[0.,0.,0.]],dtype=float);lo,hi=xyz.min(0),xyz.max(0)
        pad=np.maximum((hi-lo)*.04,.005)
        self.bounds_key=key;self.cached_bounds=(lo-pad,hi+pad)
        return self.cached_bounds
    def project(self, points):
        p=np.asarray(points,dtype=float)
        if not p.size:return []
        if self.mode=='trajectory':
            lo,hi=self.bounds();p=p-(lo+hi)/2
            a,b=self.yaw,self.pitch
            p=p@np.array([[np.cos(a),-np.sin(a),0],[np.sin(a),np.cos(a),0],[0,0,1]])
            p=p@np.array([[1,0,0],[0,np.cos(b),-np.sin(b)],[0,np.sin(b),np.cos(b)]])
            # Equal metric scale; fit the projected box rather than its 3D diagonal.
            a,b=self.yaw,self.pitch
            rot=np.array([[np.cos(a),-np.sin(a),0],[np.sin(a),np.cos(a),0],[0,0,1]])@np.array([[1,0,0],[0,np.cos(b),-np.sin(b)],[0,np.sin(b),np.cos(b)]])
            span=(hi-lo)@np.abs(rot)
            scale=min(max(1,self.width()-90)/max(span[0],1e-6),max(1,self.height()-80)/max(span[1],1e-6))
            p=p[:,:2]*scale*self.zoom
        else:
            basis,center,span=self.scatter_geometry()
            p=p[:,:2]@basis
            scale=min((self.width()-80)/span[0],(self.height()-110)/span[1])
            p=(p-center)*scale
        return [QPointF(x+self.width()/2,self.height()/2-y) for x,y in p]
    def scatter_geometry(self):
        points=[r['xy']for r in self.rows]
        for row in self.rows:
            region=row.get('placement_region')
            if region:points.extend(region['allowed'])
        points=np.asarray(points or[[0,0]]);lo,hi=points.min(0),points.max(0)
        return np.eye(2),(lo+hi)/2,np.maximum(hi-lo,.02)*1.08
    def draw_distribution(self,painter):
        regions={json.dumps(r['placement_region'],sort_keys=True):r['placement_region']for r in self.rows if r.get('placement_region')}
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for region in regions.values():
            for key,color,style in [('support','#65788b',Qt.PenStyle.DashLine),('allowed','#9cb6d3',Qt.PenStyle.SolidLine)]:
                painter.setPen(QPen(QColor(color),1.5,style));painter.drawPolygon(QPolygonF(self.project(region[key])))
            point=self.project([region['robot_xy']])[0]
            if self.rect().adjusted(10,35,-10,-35).contains(point.toPoint()):
                painter.setPen(QColor('#b58ce1'));painter.setBrush(QColor('#a16acf'));painter.drawRect(QRectF(point.x()-5,point.y()-5,10,10));painter.drawText(point+QPointF(9,0),'로봇')
        painter.setPen(QColor('#b5c5d3'))
        painter.drawText(12,self.height()-12,'Episode 시작 위치 [m] · 주황: 확인 필요 · 회색: 제외 · 클릭: Episode 선택')
    def has_splits(self):
        return any(r.get('split') in SPLIT_COLORS for r in self.rows)
    def point_color(self,row,split_mode):
        if not row.get('included',True):return '#66717d'
        if split_mode:return SPLIT_COLORS.get(row.get('split'),'#b5c5d3')
        return '#efb467' if row['flags'] else '#55d6b0'

    def set_scene(self,scene):
        self.scene=scene;self.parts=[];self.mesh=None
        for part in scene.get('robot',[]):self.parts.append((part['link'],np.array(part['triangles']), '#46434e'if part['dark']else'#a66bd4',True))
        for name,part in scene.get('objects',{}).items():self.parts.append((name,np.array(part['triangles']),part['color'],False))

    def draw_mesh(self,painter):
        if self.mesh is None:return
        triangles,colors=self.mesh;a,b=self.yaw,self.pitch
        rot=np.array([[np.cos(a),-np.sin(a),0],[np.sin(a),np.cos(a),0],[0,0,1]])@np.array([[1,0,0],[0,np.cos(b),-np.sin(b)],[0,np.sin(b),np.cos(b)]])
        points=self.project(triangles.reshape(-1,3));depth=(triangles.mean(1)@rot)[:,2]
        normals=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0]);light=np.abs(normals[:,2])/np.maximum(np.linalg.norm(normals,axis=1),1e-12)
        palette={};painter.setPen(Qt.PenStyle.NoPen)
        for index in np.argsort(depth):
            key=(colors[index],int(light[index]*4))
            if key not in palette:palette[key]=QColor(str(key[0])).lighter(70+key[1]*12)
            painter.setBrush(palette[key]);painter.drawPolygon(QPolygonF(points[index*3:index*3+3]))
        painter.setPen(QColor('#e3e8ef'))
        for name,pose in self.payload.get('object_poses',{}).items():
            if name in self.scene.get('objects',{}):painter.drawText(self.project([np.array(pose)[:3,3]])[0],name)
    def draw_axes(self,painter):
        lo,hi=self.bounds()
        painter.setPen(QPen(QColor('#344454'),1))
        for t in np.linspace(0,1,5):
            for axis in (0,1):
                a=lo.copy();b=lo.copy();a[axis]=b[axis]=lo[axis]+t*(hi[axis]-lo[axis])
                b[1-axis]=hi[1-axis]
                painter.drawLine(*self.project([a,b]))
        for axis,(name,color) in enumerate(zip('XYZ',('#ff8b8b','#73df9d','#75bfff'))):
            end=lo.copy();end[axis]=hi[axis]
            painter.setPen(QPen(QColor(color),2));painter.drawLine(*self.project([lo,end]))
            point=self.project([end])[0];painter.drawText(point+QPointF(5,-6),name)
    def set_frame(self,frame,payload=None):
        self.frame=frame;self.payload=payload or {}
        if self.row is not None:
            samples=self.row.get('sample_indices',np.arange(len(self.row.get('ee')or self.row.get('actions',[]))))
            self.sample_frame=int(np.clip(np.searchsorted(samples,frame),0,len(samples)-1))
        if self.mode=='trajectory':
            triangles=[];colors=[]
            for name,vertices,color,robot in self.parts:
                pose=self.payload.get('robot_poses'if robot else'object_poses',{}).get(name)
                if pose is None or not len(vertices):continue
                pose=np.asarray(pose);triangles.append(vertices@pose[:3,:3].T+pose[:3,3]);colors.extend([color]*len(vertices))
            self.mesh=(np.concatenate(triangles),colors)if triangles else None
        self.update()
    def paintEvent(self,event):
        self.action_lines=[];self.action_row=None
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(),QColor('#141b23'));painter.setPen(QColor('#b5c5d3'))
        title={'scatter':'물체 시작 위치 분포 · XY [m]','trajectory':'기록된 로봇·물체 동작 · '+str((self.row or {}).get('display_frame',''))+' [m]','actions':'기록된 Target ['+str((self.row or {}).get('target_unit','unknown'))+'] · 선택 Frame'}[self.mode]
        painter.drawText(12,22,title+(' · 실선 Target / 점선 Joint Position'if self.mode=='actions'else''))
        if self.mode=='scatter' and self.rows:
            self.draw_distribution(painter)
            self.screen=self.project([r['xy'] for r in self.rows])
            split_mode=self.has_splits()
            for i,(row,point) in enumerate(zip(self.rows,self.screen)):
                color=self.point_color(row,split_mode)
                edge='#efb467' if row['flags'] else color
                painter.setPen(QPen(QColor(edge),2));painter.setBrush(QColor(color));painter.drawEllipse(point,6,6)
                if i==self.selected:painter.setPen(QPen(QColor('#ffffff'),2));painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawEllipse(point,9,9)
        elif self.row and self.mode=='trajectory':
            self.draw_axes(painter);self.draw_mesh(painter)
            points=self.project(self.row.get('ee')or[]);painter.setPen(QPen(QColor('#55d6b0'),2))
            for i,(a,b) in enumerate(zip(points,points[1:])):
                painter.setPen(QPen(QColor('#55d6b0' if i<self.sample_frame else '#4b6870'),2));painter.drawLine(a,b)
            current=self.project([self.payload['eef']])[0]if self.payload.get('eef')is not None else points[self.sample_frame]if points else None
            if current is not None:painter.setPen(QColor('#ffffff'));painter.setBrush(QColor('#ffffff'));painter.drawEllipse(current,5,5)
            for point,label,color in ([(points[0],'시작','#55d6b0'),(points[-1],'끝','#efb467')]if points else[]):
                painter.setPen(QColor(color));painter.drawEllipse(point,5,5);painter.drawText(point+QPointF(8,18),label)
        elif self.row and self.mode=='actions':
            q=np.asarray(self.row['actions']);states=np.asarray(self.row['states'])if self.row.get('states')is not None else None
            comparable=self.row.get('state_action_comparable',False)and states is not None and states.shape==q.shape
            low=min(q.min(),states.min())if comparable else q.min();high=max(q.max(),states.max())if comparable else q.max();span=max(high-low,1e-6)
            indices=self.row.get('sample_indices',np.arange(len(q)));total=max(self.row.get('frames',len(q))-1,1)
            times=self.row.get('timestamps')
            def phase(i):return i/total
            colors=['#55d6b0','#69b9ff','#efb467','#d196fa','#fb9292','#e5e7eb']
            if comparable:
                for j,color in enumerate(colors[:q.shape[1]]):
                    painter.setPen(QPen(QColor(color),1,Qt.PenStyle.DashLine))
                    points=[QPointF(35+phase(indices[i])*(self.width()-55),self.height()-35-(v-low)/span*(self.height()-75))for i,v in enumerate(states[:,j])]
                    for a,b in zip(points,points[1:]):painter.drawLine(a,b)
            for j,color in enumerate(colors[:q.shape[1]]):
                painter.setPen(QPen(QColor(color),1))
                points=[QPointF(35+phase(indices[i])*(self.width()-55),self.height()-35-(v-low)/span*(self.height()-75)) for i,v in enumerate(q[:,j])]
                self.action_lines.append(np.array([[p.x(),p.y()] for p in points]))
                for a,b in zip(points,points[1:]):painter.drawLine(a,b)
                painter.drawText(15+j*65,40,str(j+1))
            painter.setPen(QPen(QColor('#ffffff'),1))
            x=35+phase(self.frame)*(self.width()-55);painter.drawLine(QPointF(x,45),QPointF(x,self.height()-35))
            for label,index in self.row.get('events',{}).items():
                x=35+phase(index)*(self.width()-55);painter.setPen(QPen(QColor('#efb467'),1,Qt.PenStyle.DashLine));painter.drawLine(QPointF(x,45),QPointF(x,self.height()-35));painter.drawText(QPointF(x,55),label)
            painter.drawText(12,self.height()-10,f"0 … {self.row['duration']:.2f}s / {low:.2f} … {q.max():.2f} {self.row.get('target_unit','unknown')}")
            self.action_row=self.row
        painter.end()
    def action_tooltip(self,position):
        if self.row is None or self.action_row is not self.row:return ''
        names=self.row.get('joint_order')or[str(i+1)for i in range(len(self.row['actions'][0]))]
        cursor=np.array([position.x(),position.y()]);hits=[]
        for joint,points in enumerate(self.action_lines):
            if len(points)==1:
                sample=0;distance=float(np.linalg.norm(cursor-points[0]))
            else:
                start=points[:-1];delta=np.diff(points,axis=0)
                fraction=np.clip(np.sum((cursor-start)*delta,axis=1)/np.maximum(np.sum(delta*delta,axis=1),1e-12),0,1)
                distances=np.linalg.norm(start+fraction[:,None]*delta-cursor,axis=1)
                segment=int(np.argmin(distances));distance=float(distances[segment])
                sample=segment+int(fraction[segment]>.5)
            if distance<=8:hits.append((distance,joint,sample))
        if not hits:return ''
        hits.sort();lines=['관절 목표값 · 가까운 기록']
        q=np.asarray(self.row['actions']);indices=self.row.get('sample_indices',np.arange(len(q)))
        times=self.row.get('timestamps')
        for distance,joint,sample in hits:
            if distance>hits[0][0]+1:continue
            frame=int(indices[sample]);value=float(q[sample,joint])
            elapsed=float(times[sample]-times[0]) if times is not None else frame*self.row.get('dt',self.row['duration']/max(self.row.get('frames',len(q))-1,1))
            lines.append(f'{joint+1}축 · {names[joint]}: {value:.5g} {self.row.get("target_unit","unknown")}\n'
                         f'  {elapsed:.3f}s · {frame+1} frame')
        return '\n'.join(lines)
    def leaveEvent(self,event):
        if self.mode=='actions':QToolTip.hideText()
        super().leaveEvent(event)
    def wheelEvent(self,event):
        if self.mode!='trajectory':
            event.ignore();return
        delta=event.angleDelta().y()/120
        if not delta:delta=event.pixelDelta().y()/120
        self.zoom=float(np.clip(self.zoom*1.15**np.clip(delta,-20,20),.2,8.0))
        self.update();event.accept()
    def mousePressEvent(self,event):
        if self.mode=='scatter'and self.screen:
            distances=[np.hypot(p.x()-event.position().x(),p.y()-event.position().y())for p in self.screen];index=int(np.argmin(distances))
            if distances[index]<=12:self.picked.emit(index)
        self.drag=event.position()
    def mouseMoveEvent(self,event):
        if self.mode=='scatter'and self.screen:
            distances=[np.hypot(p.x()-event.position().x(),p.y()-event.position().y())for p in self.screen];index=int(np.argmin(distances))
            if distances[index]<=12:
                row=self.rows[index];QToolTip.showText(event.globalPosition().toPoint(),row['name']+' · '+str(row.get('split')or'미분할')+'\n'+', '.join(row['flags']),self)
            else:QToolTip.hideText()
            return
        if self.mode=='actions':
            text=self.action_tooltip(event.position())
            if text:QToolTip.showText(event.globalPosition().toPoint(),text,self)
            else:QToolTip.hideText()
            return
        if self.drag is not None and self.mode=='trajectory':
            delta=event.position()-self.drag;self.yaw+=delta.x()*.01;self.pitch+=delta.y()*.01
            self.drag=event.position();self.update()
    def mouseReleaseEvent(self,event):self.drag=None
