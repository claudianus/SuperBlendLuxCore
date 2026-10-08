"""좌표 출력의 실제 영상 일치와 유한값을 검사한다."""
import bpy, os, numpy as np
from pathlib import Path
from mathutils import Matrix
try:
    bpy.context.scene.render.engine='SUPERLUXCORE'
except TypeError:
    bpy.ops.preferences.addon_enable(module='superluxcore')
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
s=bpy.context.scene
s.world=bpy.data.worlds.new('검증 월드'); s.world.use_nodes=True
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value=0
bpy.ops.mesh.primitive_plane_add(size=30)
plane=bpy.context.object
m=bpy.data.materials.new('좌표 검증'); m.use_nodes=True; plane.data.materials.append(m)
n=m.node_tree.nodes; l=m.node_tree.links
n.clear(); out=n.new('ShaderNodeOutputMaterial'); emission=n.new('ShaderNodeEmission'); coords=n.new('ShaderNodeTexCoord')
scale=n.new('ShaderNodeVectorMath'); scale.operation='SCALE'; scale.inputs['Scale'].default_value=.1
add=n.new('ShaderNodeVectorMath'); add.operation='ADD'; add.inputs[1].default_value=(.5,.5,.5)
l.new(scale.outputs[0],add.inputs[0]); l.new(add.outputs[0],emission.inputs['Color']); l.new(emission.outputs[0],out.inputs['Surface'])
bpy.ops.object.camera_add(location=(.7,-.4,4)); cam=bpy.context.object; cam.data.lens=40; cam.data.shift_x=.12; cam.data.shift_y=-.08; s.camera=cam
reference=bpy.data.objects.new('참조 공간',None); s.collection.objects.link(reference); reference.location=(.3,-.2,.6); reference.scale=(2,3,.5); reference.rotation_euler.z=.4; coords.object=reference
s.render.resolution_percentage=100; s.render.resolution_x=int(os.environ.get('RX','192')); s.render.resolution_y=s.render.resolution_x*9//16
s.view_settings.view_transform='Standard'; s.render.image_settings.file_format='OPEN_EXR'; s.render.image_settings.color_depth='32'
s.render.film_transparent=False
s.cycles.samples=32; s.cycles.use_denoising=False
folder=str(Path(os.environ.get('SUPERLUXCORE_VALIDATION_DIR', '/tmp/superluxcore-coordinate-regression'))); os.makedirs(folder,exist_ok=True)
def render(engine,case):
    s.render.engine=engine
    if engine=='SUPERLUXCORE':
        cfg=s.superluxcore; cfg.config.engine='PATH'; cfg.config.device=os.environ.get('DEV','OCL'); cfg.config.spectral_enable=False
        cfg.halt.enable=True; cfg.halt.use_time=False; cfg.halt.use_noise_thresh=False; cfg.halt.use_samples=True; cfg.halt.samples=32
        cfg.config.path.use_clamping=False; cfg.config.path.auto_clamping=False; cfg.denoiser.enabled=False
        cam.data.superluxcore.imagepipeline.tonemapper.enabled=False
    path=folder+'/'+case+'_'+os.environ.get('DEV','OCL')+'_'+engine+'.exr'; s.render.filepath=path
    bpy.ops.render.render(write_still=True)
    im=bpy.data.images.load(path,check_existing=False); a=np.array(im.pixels[:],dtype=np.float32).reshape(s.render.resolution_y,s.render.resolution_x,4)[...,:3]; bpy.data.images.remove(im); return a
for camera_type,coord in (('PERSP','Camera'),('PERSP','Window'),('ORTHO','Window'),('PERSP','Object')):
    cam.data.type=camera_type; cam.data.ortho_scale=5
    for link in list(scale.inputs[0].links): l.remove(link)
    l.new(coords.outputs[coord],scale.inputs[0])
    bpy.context.view_layer.update()
    name=camera_type+'_'+coord
    cy=render('CYCLES',name); lx=render('SUPERLUXCORE',name)
    cy=cy[4:-4,4:-4]; lx=lx[4:-4,4:-4]
    error=np.abs(lx-cy); print('COORD',name,'MAE',error.mean(),'MAX',error.max(),flush=True)
    assert np.isfinite(lx).all() and error.mean()<.001 and np.quantile(error,.99)<.003, (name,error.mean(),np.quantile(error,.99))
print('좌표 영상 검사 4개 통과',flush=True)
