"""Camera observations and previews exclude debug sites.

MuJoCo3.3.7 Renderer.update_scene / mjvOption.sitegroup:
https://mujoco.readthedocs.io/en/3.3.7/programming/visualization.html
Only visualization options change; the model, tool0 and physics state stay intact.
"""


def camera_rgb(renderer,data,camera):
    import mujoco
    option=mujoco.MjvOption()
    option.sitegroup[:]=0
    renderer.update_scene(data,camera=camera,scene_option=option)
    return renderer.render()
