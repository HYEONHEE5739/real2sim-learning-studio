"""Qt inspection plots ported from workflow/curation_ui.py:Plot.

Recorded EEF/target/XY presentation only. Robot mesh/geometry calculation stays
outside the GUI; bounded numeric rows come from the existing data reader.
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
        super().__init__();self.mode=mode;self.rows=[];self.row=None;self.excluded=set();self.selected=-1
        self.yaw=.7;self.pitch=.55;self.drag=None;self.screen=[];self.zoom=1.0
        self.frame=0;self.payload={};self.sample_frame=0;self.context_rows=[]
        self.action_lines=[];self.action_row=None;self.setMouseTracking(mode=='actions')
        self.setMinimumSize(240,200)
    def set_view(self, name):
        self.zoom=1.0
        self.yaw,self.pitch={'3D':(.7,.65),'XY':(0.,0.),'XZ':(0.,np.pi/2),'YZ':(np.pi/2,np.pi/2)}[name]
        self.update()
    def bounds(self):
        xyz=np.asarray(self.row['ee'],dtype=float);lo,hi=xyz.min(0),xyz.max(0)
        pad=np.maximum((hi-lo)*.04,.005)
        return lo-pad,hi+pad
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
        points=np.asarray([r['xy']for r in self.rows]or[[0,0]]);lo,hi=points.min(0),points.max(0)
        return np.eye(2),(lo+hi)/2,np.maximum(hi-lo,.02)*1.08
    def draw_distribution(self,painter):
        painter.setPen(QColor('#b5c5d3'))
        painter.drawText(12,self.height()-12,'기록된 선택 시작 위치 · 지정 Frame [m] · 배치 경계 추정 없음')
    def has_splits(self):
        return any(r.get('split') in SPLIT_COLORS for r in (self.context_rows or self.rows))
    def point_color(self,row,split_mode):
        if row['name'] in self.excluded:return '#66717d'
        if row.get('evaluation_outcome'):return '#55d6b0' if row['recorded_success'] else '#ff7777'
        if split_mode:return SPLIT_COLORS.get(row.get('split'),'#b5c5d3')
        return '#efb467' if row['flags'] else '#55d6b0'
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
            samples=self.row.get('sample_indices',np.arange(len(self.row.get('ee',self.row.get('actions',[])))))
            self.sample_frame=int(np.clip(np.searchsorted(samples,frame),0,len(samples)-1))
        self.update()
    def paintEvent(self,event):
        self.action_lines=[];self.action_row=None
        painter=QPainter(self);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(),QColor('#141b23'));painter.setPen(QColor('#b5c5d3'))
        robot_view=any(r.get('placement_region') for r in (self.context_rows or self.rows))
        title={'scatter':'선택 시작 Object 위치 · 지정 좌표 XY [m]','trajectory':'기록된 EEF 경로 · '+str((self.row or {}).get('display_frame',''))+' ['+str((self.row or {}).get('eef_unit','unknown'))+']','actions':'기록된 Target ['+str((self.row or {}).get('target_unit','unknown'))+'] · 선택 Frame'}[self.mode]
        painter.drawText(12,22,title)
        if self.mode=='scatter' and (self.rows or self.context_rows):
            self.draw_distribution(painter)
            self.screen=self.project([r['xy'] for r in self.rows])
            split_mode=self.has_splits()
            for i,(row,point) in enumerate(zip(self.rows,self.screen)):
                selected=getattr(self,'original_indices',list(range(len(self.rows))))[i]==self.selected
                color=self.point_color(row,split_mode)
                edge='#efb467' if row['flags'] and row['name'] not in self.excluded else color
                painter.setPen(QPen(QColor(edge),2));painter.setBrush(QColor(color));painter.drawEllipse(point,5,5)
                if selected:
                    painter.setPen(QPen(QColor('#ffffff'),2));painter.setBrush(Qt.BrushStyle.NoBrush);painter.drawEllipse(point,8,8)
        elif self.row and self.mode=='trajectory':
            self.draw_axes(painter)
            points=self.project(self.row['ee']);painter.setPen(QPen(QColor('#55d6b0'),2))
            for i,(a,b) in enumerate(zip(points,points[1:])):
                painter.setPen(QPen(QColor('#55d6b0' if i<self.sample_frame else '#4b6870'),2));painter.drawLine(a,b)
            current=self.project([self.payload['ee']])[0] if 'ee' in self.payload else points[self.sample_frame]
            painter.setPen(QColor('#ffffff'));painter.setBrush(QColor('#ffffff'));painter.drawEllipse(current,6,6)
            for point,label,color in [(points[0],'시작','#55d6b0'),(points[-1],'끝','#efb467')]:
                painter.setPen(QColor(color));painter.drawEllipse(point,5,5);painter.drawText(point+QPointF(8,18),label)
        elif self.row and self.mode=='actions':
            q=np.asarray(self.row['actions']);low=q.min();span=max(q.max()-low,1e-6)
            indices=self.row.get('sample_indices',np.arange(len(q)));total=max(self.row.get('frames',len(q))-1,1)
            times=self.row.get('timestamps')
            def phase(i):return i/total
            colors=['#55d6b0','#69b9ff','#efb467','#d196fa','#fb9292','#e5e7eb']
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
        self.drag=event.position()
        if self.mode=='scatter' and self.screen:
            d=[(p.x()-self.drag.x())**2+(p.y()-self.drag.y())**2 for p in self.screen]
            if min(d)<225:
                index=int(np.argmin(d));self.picked.emit(getattr(self,'original_indices',list(range(len(d))))[index])
    def mouseMoveEvent(self,event):
        if self.mode=='actions':
            text=self.action_tooltip(event.position())
            if text:QToolTip.showText(event.globalPosition().toPoint(),text,self)
            else:QToolTip.hideText()
            return
        if self.drag is not None and self.mode=='trajectory':
            delta=event.position()-self.drag;self.yaw+=delta.x()*.01;self.pitch+=delta.y()*.01
            self.drag=event.position();self.update()
    def mouseReleaseEvent(self,event):self.drag=None



class HistogramPlot(QWidget):
    """Draw the existing backend histogram bins/counts; no GUI statistics engine."""
    def __init__(self):
        super().__init__();self.series=[];self.field=None;self.component=0;self.setMinimumSize(240,180)

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#141b23'));painter.setPen(QColor('#b5c5d3'))
        if not self.series or self.field is None:painter.drawText(12,24,'Action / Observation 분포 · 명시 범위를 선택하세요');return
        rows=[d['fields'][self.field]for d in self.series];index=self.component
        if index>=len(rows[0]['histogram_counts']):return
        maximum=max(1,max(max(row['histogram_counts'][index])for row in rows));bins=len(rows[0]['histogram_counts'][index]);width=max(1,self.width()-60);height=max(1,self.height()-75)
        colors=('#55d6b0','#69b9ff','#efb467','#d196fa')
        for dataset,row in enumerate(rows):
            color=QColor(colors[dataset%len(colors)]);color.setAlpha(130);painter.setPen(QPen(color,1));painter.setBrush(color)
            for i,count in enumerate(row['histogram_counts'][index]):
                bar_height=count/maximum*height;painter.drawRect(QRectF(35+i*width/bins,self.height()-35-bar_height,width/bins,bar_height))
        painter.setPen(QColor('#b5c5d3'));painter.drawText(12,22,f"{self.field} · component {index+1} [{rows[0]['unit']}] · {rows[0]['phase']}")
        edges=rows[0]['histogram_edges'][index];painter.drawText(12,self.height()-10,f'{edges[0]:.5g} … {edges[-1]:.5g} · 각 Dataset의 기록 수 / 최대 {maximum}')
