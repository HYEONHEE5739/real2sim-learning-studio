"""Real Qt/OpenGL regression for overlapping preview resource lifetimes."""

from test_asset_view import viewport_check


TEXTURED_VIEWERS = '''
import base64
from PyQt6.QtCore import QBuffer,QByteArray,QIODevice,qInstallMessageHandler
from PyQt6.QtGui import QColor,QImage,QOpenGLContext
from robot_learning_workbench.ui.asset_viewport import AssetViewport
messages=[]
qInstallMessageHandler(lambda kind,context,message:messages.append(message))
image=QImage(8,8,QImage.Format.Format_RGB32);image.fill(QColor('red'))
encoded=QByteArray();stream=QBuffer(encoded)
stream.open(QIODevice.OpenModeFlag.WriteOnly);image.save(stream,'PNG')
payload={'meshes':[{'kind':'visual','vertices':[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]],
 'faces':[[0,1,2],[0,2,3]],'uv':[[0,0],[1,0],[1,1],[0,1]],
 'texture_png':base64.b64encode(bytes(encoded)).decode(),'color':[0.,1.,0.]}]}
def render(view):
 view.request_render();deadline=time.monotonic()+5
 while view.running or view.image is None:
  app.processEvents();time.sleep(.002)
  assert view.gl_error is None,view.gl_error
  assert time.monotonic()<deadline,'Textured preview did not finish'
 assert view.isValid()
 assert view.image.pixelColor(view.width()//2,view.height()//2).red()>250
def make_view():
 view=AssetViewport();view.resize(500,400);view.show();view.load(payload)
 view.state.update(yaw=0.,pitch=0.,grid=False,lighting=False)
 render(view);return view
def assert_no_context_warnings():
 errors=[message for message in messages if any(fragment in message for fragment in
  ['requires a valid current context','Requires a valid current OpenGL context',
   'Texture has not been created','called without a current context'])]
 assert not errors,errors
'''


def test_closing_old_preview_preserves_current_context_of_other_viewer(tmp_path):
    viewport_check(tmp_path,TEXTURED_VIEWERS+'''
old=make_view();current=make_view()
current.makeCurrent();owner=QOpenGLContext.currentContext()
assert owner is current.context()
old.close()
# Deleting one preview must not invalidate a different preview's GL work.
assert QOpenGLContext.currentContext() is owner,'Closing old preview cleared the active Viewer context'
assert not old.parts and old.program is None
assert current.parts[0]['texture'].isCreated()
current.doneCurrent();render(current)
assert_no_context_warnings();current.close();app.processEvents()
''')


def test_reentrant_preview_close_does_not_break_texture_reload(tmp_path):
    viewport_check(tmp_path,TEXTURED_VIEWERS+'''
old=make_view();current=make_view()
upload=current.upload;closed=[]
def upload_with_old_preview_close():
 if not closed:
  closed.append(True)
  assert QOpenGLContext.currentContext() is current.context()
  old.close()
  # Check before texture allocation. The outer helper isolates this native
  # lifecycle path in a child: Qt framebuffer unwinding may itself segfault.
  assert QOpenGLContext.currentContext() is current.context(),'Old preview cleanup stole the upload context'
 return upload()
current.upload=upload_with_old_preview_close
current.load(payload);current.state.update(yaw=0.,pitch=0.,grid=False,lighting=False)
render(current)
assert closed and current.parts[0]['texture'].isCreated()
assert_no_context_warnings();current.close();app.processEvents()
''')


def test_viewer_cleanup_without_prior_current_context_releases_resources(tmp_path):
    viewport_check(tmp_path,TEXTURED_VIEWERS+'''
view=make_view();view.doneCurrent()
assert QOpenGLContext.currentContext() is None
view.cleanup()
assert QOpenGLContext.currentContext() is None
assert not view.parts and view.program is None
view.close();app.processEvents();assert_no_context_warnings()
''')
