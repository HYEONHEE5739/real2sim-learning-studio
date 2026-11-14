"""Verified USD triangles in Qt's depth-buffered OpenGL widget.

Conversion stays in BackendJob; no proxy geometry or simulator sensors.
Lifecycle: https://doc.qt.io/qt-6.11/qopenglwidget.html
"""
import base64
import numpy as np
from PyQt6 import sip
from PyQt6.QtCore import Qt,QTimer,pyqtSignal,QPointF
from PyQt6.QtGui import QImage,QSurfaceFormat,QMatrix3x3,QColor,QPainter
from PyQt6.QtOpenGL import (QOpenGLFunctions_4_1_Core,QOpenGLBuffer,
    QOpenGLShader,QOpenGLShaderProgram,QOpenGLTexture,QOpenGLVertexArrayObject)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from .collision_wireframe import mesh_topology,collision_topology,feature_base,silhouette_mask

DEPTH_TEST=0x0B71;CULL_FACE=0x0B44;BLEND=0x0BE2
LESS=0x0201;EQUAL=0x0202;LEQUAL=0x0203;GREATER=0x0204;POLYGON_OFFSET_FILL=0x8037
TRIANGLES=0x0004;LINES=0x0001;FLOAT=0x1406

VERTEX='''#version 410 core
in vec3 position;
in vec3 normal;
in vec2 uv;
uniform mat3 rotation;
uniform vec2 scale;
uniform vec2 pan;
uniform vec2 viewport;
uniform bool wireframe;
out vec3 face_normal;
out vec2 texcoord;
noperspective out float edge_distance;
void main() {
    vec3 p=rotation*position;
    gl_Position=vec4(p.xy*scale+pan, -p.z*.25, 1.0);
    face_normal=rotation*normal;
    texcoord=uv;
    edge_distance=0.;
    if (wireframe) {
        // Edge buffers store the segment's start in the normal attribute.
        vec3 start=rotation*normal;
        edge_distance=length((p.xy-start.xy)*scale*viewport*.5);
    }
}
'''
FRAGMENT='''#version 410 core
in vec3 face_normal;
in vec2 texcoord;
uniform vec4 color;
uniform sampler2D image;
uniform bool textured;
uniform bool lit;
uniform bool dashed;
noperspective in float edge_distance;
out vec4 fragment;
void main() {
    if (dashed && mod(edge_distance,10.)>5.) discard;
    vec3 rgb=textured ? texture(image,texcoord).rgb : color.rgb;
    float shade=lit ? .35+.65*abs(dot(normalize(face_normal),normalize(vec3(.3,.4,1.)))) : 1.;
    fragment=vec4(rgb*shade,color.a);
}
'''


def view_rotation(yaw,pitch):
    """Right-handed camera basis; positive pitch looks down onto +Z assets."""
    yaw,pitch=np.radians([yaw,pitch]);cy,sy=np.cos(yaw),np.sin(yaw);cp,sp=np.cos(pitch),np.sin(pitch)
    right=np.array([cy,-sy,0.]);up=np.array([sy*sp,cy*sp,cp])
    return np.array([right,up,np.cross(right,up)])


def triangle_edges(vertices,faces):
    """Unique undirected triangle edges within ONE part, including UV seams.

    Exact coordinate welding handles the Converter's triangle soup. No spatial
    tolerance or cross-part merge can erase thin/internal collision geometry.
    """
    return mesh_topology(vertices,faces)['segments']


class AssetViewport(QOpenGLWidget):
    rendered=pyqtSignal(object)
    error=pyqtSignal(str)

    def __init__(self,parent=None):
        super().__init__(parent)
        fmt=QSurfaceFormat();fmt.setVersion(4,1);fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        fmt.setDepthBufferSize(24);fmt.setSamples(4);self.setFormat(fmt)
        self.setMinimumSize(360,300)
        self.payload=None;self.image=None;self.running=False;self.pending=False;self.closed=False
        self.parts=[];self.lines=[];self.edges=[];self.program=None;self.vao=None;self.functions=None
        self.topology=None;self.feature=None;self.feature_key=None;self.feature_angle=None;self.feature_base=None;self.feature_selection=None
        self.dirty=True;self.capture_pending=False;self.capturing=False;self.generation=0;self.gl_info={};self.gl_error=None
        self.state={'show_visual':True,'show_collision':False,'collision_mode':'xray','visual_opacity':1.,
            'edge_mode':'feature','feature_angle':25.,'visible_opacity':1.,'hidden_opacity':.2}
        self.reset_view()

    def reset_view(self):
        self.state.update(yaw=35.,pitch=30.,zoom=1.,pan=[0.,0.])
        self.request_render()

    def load(self,payload):
        self.payload=payload;self.image=None;self.dirty=True;self.reset_view()

    def request_render(self):
        self.generation+=1
        self.running=self.payload is not None and not self.closed and self.gl_error is None
        self.update()

    def showEvent(self,event):
        super().showEvent(event);QTimer.singleShot(0,self.check_context)

    def check_context(self):
        if not self.closed and not self.isValid():self.fail('No desktop OpenGL context; use an X11/Wayland display, not offscreen QPA')

    def resizeGL(self,width,height):
        self.running=self.payload is not None and not self.closed and self.gl_error is None

    def initializeGL(self):
        try:
            self.functions=QOpenGLFunctions_4_1_Core()
            if not self.functions.initializeOpenGLFunctions():raise RuntimeError('Desktop OpenGL 4.1 required')
            f=self.functions
            self.gl_info={'vendor':f.glGetString(0x1F00),'renderer':f.glGetString(0x1F01),
                'version':f.glGetString(0x1F02),'depth_bits':self.context().format().depthBufferSize()}
            self.program=QOpenGLShaderProgram()
            for kind,source in [(QOpenGLShader.ShaderTypeBit.Vertex,VERTEX),(QOpenGLShader.ShaderTypeBit.Fragment,FRAGMENT)]:
                if not self.program.addShaderFromSourceCode(kind,source):raise RuntimeError(self.program.log())
            if not self.program.link():raise RuntimeError(self.program.log())
            self.vao=QOpenGLVertexArrayObject();self.vao.create()
            self.context().aboutToBeDestroyed.connect(self.cleanup)
            self.dirty=True
        except Exception as error:self.fail(error)

    def fail(self,error):
        self.gl_error=str(error);self.running=False;self.image=None
        self.error.emit('3D OpenGL Viewer: '+str(error))

    def buffer(self,data):
        buf=QOpenGLBuffer();buf.create();buf.bind();raw=np.asarray(data,dtype=np.float32).tobytes();buf.allocate(raw,len(raw));buf.release()
        return buf

    def release_meshes(self):
        for part in self.parts+self.lines+self.edges+([self.feature]if self.feature else[]):
            part['buffer'].destroy()
            if part.get('texture'):part['texture'].destroy()
        self.parts=[];self.lines=[];self.edges=[]
        self.topology=None;self.feature=None;self.feature_key=None;self.feature_angle=None;self.feature_base=None;self.feature_selection=None

    def upload(self):
        self.release_meshes();self.dirty=False
        if self.payload is None:return
        meshes=self.payload['meshes'];points=np.concatenate([np.asarray(m['vertices'],float)for m in meshes])
        lo,hi=points.min(0),points.max(0);self.center=(lo+hi)/2;self.extent=max(np.linalg.norm(hi-lo),1e-9)
        self.topology=collision_topology(meshes)
        edge_parts={p['part_index']:p for p in self.topology['parts']}
        for part_index,mesh in enumerate(meshes):
            points=np.asarray(mesh['vertices'],float);faces=np.asarray(mesh['faces'],int)
            triangles=points[faces];normal=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
            normal/=np.maximum(np.linalg.norm(normal,axis=1,keepdims=True),1e-12)
            uv=np.asarray(mesh.get('uv',[]),float);uv=uv[faces].reshape(-1,2)if uv.size else np.zeros((faces.size,2))
            vertices=(triangles.reshape(-1,3)-self.center)/self.extent
            data=np.c_[vertices,np.repeat(normal,3,axis=0),uv]
            texture=None
            if mesh.get('texture_png'):
                image=QImage.fromData(base64.b64decode(mesh['texture_png']))
                if image.isNull():raise ValueError('Invalid USD preview Texture')
                # USD v=0 is the bottom row; QImage storage starts at the top.
                texture=QOpenGLTexture(image.flipped(Qt.Orientation.Vertical))
                texture.setMinificationFilter(QOpenGLTexture.Filter.LinearMipMapLinear)
                texture.setMagnificationFilter(QOpenGLTexture.Filter.Linear)
                texture.setWrapMode(QOpenGLTexture.WrapMode.Repeat)
            self.parts.append({'buffer':self.buffer(data),'count':len(data),'kind':mesh['kind'],
                'color':mesh.get('color',[.5]*3),'texture':texture})
            if mesh['kind']=='collision':
                segments=(edge_parts[part_index]['segments']-self.center)/self.extent
                starts=np.repeat(segments[:,0],2,axis=0)
                data=np.c_[segments.reshape(-1,3),starts,np.zeros((len(starts),2))]
                self.edges.append({'buffer':self.buffer(data),'count':len(data),'part_index':part_index})
        def lines(vertices,color):
            positions=(np.asarray(vertices)-self.center)/self.extent
            self.lines.append({'buffer':self.buffer(np.c_[positions,np.zeros((len(positions),5))]),'count':len(positions),'color':color})
        grid=[]
        for t in np.linspace(-self.extent,self.extent,11):
            grid.extend([[-self.extent,t,0],[self.extent,t,0],[t,-self.extent,0],[t,self.extent,0]])
        lines(grid,[.22,.27,.33])
        for axis,color in zip(np.eye(3),[[1.,.4,.4],[.4,.9,.5],[.4,.6,1.]]):lines([[0,0,0],axis*self.extent*.4],color)

    def feature_buffer(self,rotation):
        """Reuse topology/All buffers; update only selected contour lines."""
        angle=float(self.state['feature_angle']);direction=tuple(rotation[2]);key=(angle,direction)
        if key==self.feature_key:return self.feature
        if angle!=self.feature_angle:
            self.feature_base=feature_base(self.topology,angle);self.feature_angle=angle
        mask=self.feature_base|silhouette_mask(self.topology,direction)
        if self.feature is not None and np.array_equal(mask,self.feature_selection):
            self.feature_key=key;return self.feature
        segments=(self.topology['segments'][mask]-self.center)/self.extent
        starts=np.repeat(segments[:,0],2,axis=0)
        data=np.c_[segments.reshape(-1,3),starts,np.zeros((len(starts),2))]
        if self.feature is None:self.feature={'buffer':self.buffer(data),'count':len(data)}
        else:
            buf=self.feature['buffer'];buf.bind();raw=np.asarray(data,np.float32).tobytes();buf.allocate(raw,len(raw));buf.release();self.feature['count']=len(data)
        self.feature_key=key;self.feature_selection=mask
        return self.feature

    def draw(self,part,color,*,primitive=TRIANGLES,lit=True,textured=False,wireframe=False,dashed=False):
        p=self.program;part['buffer'].bind()
        for name,offset,size in [('position',0,3),('normal',12,3),('uv',24,2)]:
            p.enableAttributeArray(name);p.setAttributeBuffer(name,FLOAT,offset,size,32)
        p.setUniformValue('color',*map(float,color));p.setUniformValue('lit',lit);p.setUniformValue('textured',textured)
        p.setUniformValue('wireframe',wireframe);p.setUniformValue('dashed',dashed)
        if textured:part['texture'].bind(0)
        self.functions.glDrawArrays(primitive,0,part['count'])
        if textured:part['texture'].release(0)
        part['buffer'].release()

    def paintGL(self):
        if not self.functions or self.gl_error:return
        try:
            f=self.functions;f.glDepthMask(True);f.glColorMask(True,True,True,True)
            f.glClearColor(32/255,39/255,51/255,1.);f.glClear(0x4000|0x0100)
            if self.closed:return
            if self.dirty:self.upload()
            if self.payload is None:return
            f.glEnable(DEPTH_TEST);f.glDepthFunc(LESS);f.glDisable(BLEND)
            if self.state.get('cull_backfaces',False):f.glEnable(CULL_FACE)
            else:f.glDisable(CULL_FACE)
            self.vao.bind();p=self.program;p.bind()
            R=view_rotation(self.state['yaw'],self.state['pitch'])
            p.setUniformValue('rotation',QMatrix3x3(R.ravel().tolist()))
            scale=min(self.width(),self.height())*.75*self.state['zoom']
            p.setUniformValue('scale',float(2*scale/self.width()),float(2*scale/self.height()))
            p.setUniformValue('pan',float(2*self.state['pan'][0]/self.width()),float(-2*self.state['pan'][1]/self.height()))
            p.setUniformValue('image',0)
            p.setUniformValue('viewport',float(self.width()*self.devicePixelRatioF()),float(self.height()*self.devicePixelRatioF()))
            show_visual=self.state['show_visual'];show_collision=self.state['show_collision']
            opacity=float(np.clip(self.state['visual_opacity'],0.,1.))
            visuals=[part for part in self.parts if part['kind']=='visual']
            collisions=[part for part in self.parts if part['kind']=='collision']
            if show_collision:
                # Raster-only offset: keep coplanar edges stable without moving
                # any mesh or changing the common Camera/Scale/Transform.
                f.glEnable(POLYGON_OFFSET_FILL);f.glPolygonOffset(1.,1.)
            if show_visual:
                # Even opacity=0 retains surface depth for honest visibility.
                f.glColorMask(False,False,False,False)
                for part in visuals:self.draw(part,[*part['color'],1.],lit=False)
                f.glColorMask(True,True,True,True);f.glDepthMask(False);f.glDepthFunc(EQUAL)
                if opacity>0:
                    if opacity<1.:f.glEnable(BLEND);f.glBlendFunc(0x0302,0x0303)
                    for part in visuals:
                        self.draw(part,[*part['color'],opacity],lit=self.state.get('lighting',True),
                            textured=bool(part['texture'])and self.state.get('textures',True))
                f.glDisable(BLEND);f.glDepthMask(True);f.glDepthFunc(LESS)
            if show_collision:
                # Union depth includes all Collision parts, so rear/internal
                # edges remain hidden even when the Visual is toggled off.
                f.glColorMask(not show_visual,not show_visual,not show_visual,not show_visual)
                for part in collisions:self.draw(part,[.28,.86,.96,1.],lit=self.state.get('lighting',True))
                f.glColorMask(True,True,True,True);f.glDisable(POLYGON_OFFSET_FILL)
                f.glDepthMask(False);f.glEnable(BLEND);f.glBlendFunc(0x0302,0x0303)
                edges=[self.feature_buffer(R)]if self.state['edge_mode']=='feature'else self.edges
                hidden=float(np.clip(self.state['hidden_opacity'],0.,1.));visible=float(np.clip(self.state['visible_opacity'],0.,1.))
                if self.state['collision_mode']=='xray'and hidden>0:
                    f.glDepthFunc(GREATER)
                    for edge in edges:self.draw(edge,[1.,.5,.12,hidden],primitive=LINES,lit=False,wireframe=True,dashed=True)
                f.glDepthFunc(LEQUAL)
                if visible>0:
                    for edge in edges:self.draw(edge,[.15,.9,1.,visible],primitive=LINES,lit=False,wireframe=True)
                f.glDisable(BLEND);f.glDepthFunc(LESS)
            f.glDepthMask(False)
            if self.state.get('grid',True):
                for part in self.lines:self.draw(part,[*part['color'],1.],primitive=LINES,lit=False)
            f.glDepthMask(True);p.release();self.vao.release();f.glDisable(DEPTH_TEST)
            painter=QPainter(self);painter.setPen(QColor('#dce3ed'))
            if self.state.get('grid',True):
                for axis,label in zip(np.eye(3),'XYZ'):
                    point=R@((axis*self.extent*.4-self.center)/self.extent)
                    painter.drawText(QPointF(self.width()/2+point[0]*scale+self.state['pan'][0],
                        self.height()/2-point[1]*scale+self.state['pan'][1]),label)
            painter.end()
            if self.running and not self.capture_pending and not self.capturing:
                self.capture_pending=True;QTimer.singleShot(0,self.capture)
        except Exception as error:self.fail(error)

    def capture(self):
        self.capture_pending=False
        if self.closed or self.payload is None:return
        generation=self.generation;self.capturing=True
        try:self.image=self.grabFramebuffer()
        finally:self.capturing=False
        if generation==self.generation:self.running=False;self.rendered.emit(self.image)

    def cleanup(self):
        if self.context()and self.context().isValid():
            self.makeCurrent();self.release_meshes()
            if self.vao:self.vao.destroy();self.vao=None
            if self.program:sip.delete(self.program);self.program=None
            self.doneCurrent()
        self.dirty=True

    def mousePressEvent(self,event):self.last=event.position()
    def mouseMoveEvent(self,event):
        if not hasattr(self,'last'):return
        delta=event.position()-self.last;self.last=event.position()
        if event.buttons()&Qt.MouseButton.RightButton:
            self.state['yaw']+=delta.x()*.5;self.state['pitch']=float(np.clip(self.state['pitch']+delta.y()*.5,-89,89))
        elif event.buttons()&Qt.MouseButton.MiddleButton:self.state['pan']=[self.state['pan'][0]+delta.x(),self.state['pan'][1]+delta.y()]
        else:return
        self.request_render()
    def wheelEvent(self,event):self.state['zoom']=float(np.clip(self.state['zoom']*1.15**(event.angleDelta().y()/120),.05,30));self.request_render()
    def closeEvent(self,event):
        self.closed=True;self.running=False;self.pending=False;self.payload=None;self.image=None;self.cleanup();super().closeEvent(event)
