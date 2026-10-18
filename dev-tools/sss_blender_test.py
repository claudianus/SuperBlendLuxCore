"""Actual OpenPBR nodes, default depth export and stock-Blender SSS render.

Run in an isolated sync_dev_install profile. SLC_SSS_LEGACY=1 selects the
authored legacy depth limit for a before/after control; no exposure changes.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import time

import bpy
from mathutils import Vector
import numpy as np

PROFILE = Path(os.environ['BLENDER_USER_RESOURCES']).resolve()
if os.environ.get('BLENDER_USER_EXTENSIONS'):
    assert Path(bpy.utils.user_resource('EXTENSIONS')).resolve()==PROFILE/'extensions'
sys.path.insert(0, os.environ.get('SLC_SSS_NATIVE_ROOT', str(PROFILE/'extensions/.local/lib/python3.13/site-packages')))
PACKAGE = 'bl_ext.user_default.superluxcore'
bpy.ops.preferences.addon_enable(module=PACKAGE)
import pysuperluxcore as slc

OUT = Path(os.environ['SLC_SSS_OUT']).resolve()
OUT.mkdir(parents=True,exist_ok=True)
native = Path(slc.pysuperluxcore.__file__).resolve()
if os.environ.get('SLC_SSS_NATIVE_ROOT'):
    expected=Path(os.environ['SLC_SSS_NATIVE_ROOT'])/'pysuperluxcore'/native.name
    assert native==expected.resolve(),(native,expected.resolve())
else:
    assert native.is_relative_to(PROFILE)
config_export = importlib.import_module(PACKAGE+'.export.config')
errors = importlib.import_module(PACKAGE+'.utils.errorlog').SuperLuxCoreErrorLog
s = bpy.context.scene
if os.environ.get('SLC_SSS_FRESH_SCENE')=='1':
    assert bpy.context.window is not None
    s=bpy.data.scenes.new('SSS installed validation')
    s.world=bpy.data.worlds.new('SSS validation world')
    bpy.context.window.scene=s
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
cfg = s.superluxcore
cfg.config.device = 'CPU'
cfg.config.spectral_enable = os.environ.get('SLC_SSS_SPECTRAL','1') == '1'
cfg.config.path.use_clamping = False
cfg.config.path.auto_clamping = False
if os.environ.get('SLC_SSS_EYE_ONLY') == '1':
    cfg.config.path.hybridbackforward_enable = False
cfg.halt.enable = cfg.halt.use_samples = True
cfg.halt.samples = int(os.environ.get('SLC_SSS_SAMPLES','16'))
cfg.halt.use_noise_level = cfg.halt.use_noise_thresh = False
cfg.denoiser.enabled = False
s.render.threads_mode = 'FIXED'
s.render.threads = int(os.environ.get('SLC_SSS_THREADS','4'))
s.render.resolution_x,s.render.resolution_y = map(int,os.environ.get('SLC_SSS_SIZE','320,180').split(','))
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.render.image_settings.color_mode = 'RGBA'
s.view_settings.view_transform = 'ACES 2.0'
s.view_settings.look = 'None'
s.view_settings.exposure = 0
s.view_settings.gamma = 1

materials = []
for index,(preset,ior) in enumerate((('skin_light',1.4),('skin_dark',1.4),('marble',1.5))):
    mat = bpy.data.materials.new(preset)
    nt = bpy.data.node_groups.new(preset,'superluxcore_material_nodes')
    mat.superluxcore.node_tree = nt
    output = nt.nodes.new('SuperLuxCoreNodeMatOutput')
    node = nt.nodes.new('SuperLuxCoreNodeMatOpenPBR')
    nt.links.new(node.outputs['Material'],output.inputs[0])
    node.use_subsurface = True
    node.sss_preset = preset
    node.inputs['Specular IOR'].default_value = ior
    node.inputs['Specular Roughness'].default_value = .4
    # Independent Cycles control, with the same authored optical parameters.
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get('Principled BSDF')
    principled.inputs['Base Color'].default_value = (*node.inputs['Subsurface Color'].default_value,1)
    principled.inputs['IOR'].default_value = ior
    if 'Subsurface IOR' in principled.inputs:
        principled.inputs['Subsurface IOR'].default_value = ior
    principled.inputs['Roughness'].default_value = .4
    principled.inputs['Subsurface Weight'].default_value = 1
    principled.inputs['Subsurface Radius'].default_value = node.inputs['Subsurface Radius'].default_value
    principled.inputs['Subsurface Scale'].default_value = node.inputs['Subsurface Scale'].default_value
    principled.inputs['Subsurface Anisotropy'].default_value = node.inputs['Subsurface Anisotropy'].default_value
    materials.append(mat)
    x = (index-1)*.23
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48,ring_count=32,radius=.09,location=(x,0,.105))
    ball = bpy.context.object
    ball.data.materials.append(mat)
    for face in ball.data.polygons: face.use_smooth=True
    # Closed thin ellipsoid under the same material, to inspect transmission.
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32,ring_count=24,radius=1,location=(x+.075,0,.13))
    ear = bpy.context.object
    ear.scale = (.035,.0015,.045)
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    ear.data.materials.append(mat)
    for face in ear.data.polygons: face.use_smooth=True

bpy.ops.mesh.primitive_plane_add(size=20)
floor = bpy.data.materials.new('floor')
floor.use_nodes=True
floor.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.15,.15,.15,1)
floor.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.6
bpy.context.object.data.materials.append(floor)
for location,power,color,size in (((-.3,-.35,.5),20,(1,.9,.8),.3),
                                ((.15,.2,.3),30,(1,.65,.35),.2)):
    bpy.ops.object.light_add(type='AREA',location=location)
    light=bpy.context.object
    light.rotation_euler=(Vector((0,0,.12))-light.location).to_track_quat('-Z','Y').to_euler()
    light.data.energy=power
    light.data.color=color
    light.data.size=size
bpy.ops.object.camera_add(location=(.25,-.95,.4))
s.camera=bpy.context.object
s.camera.rotation_euler=(Vector((0,0,.11))-s.camera.location).to_track_quat('-Z','Y').to_euler()
s.camera.data.type='ORTHO'
s.camera.data.ortho_scale=.8
s.world.use_nodes=True
s.world.node_tree.nodes['Background'].inputs['Color'].default_value=(.1,.1,.1,1)
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value=.15
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled=False

# Verify the real Blender RNA state and production export, including explicit
# author choices. The unit test also covers Cycles override precedence.
path = cfg.config.path
assert not path.is_property_set('depth_volume')
rows=[]
for authored,expected in ((None,None),(-1,0),(0,1),(8,9)):
    if authored is None: path.property_unset('depth_volume')
    else: path.depth_volume=authored
    definitions={}
    config_export._convert_path(cfg.config,definitions,False,'CPU',False,s)
    actual=definitions.get('path.pathdepth.volume')
    assert actual==expected,(authored,actual,expected)
    rows.append(dict(authored=authored,exported=actual))
path.property_unset('depth_volume')
legacy=os.environ.get('SLC_SSS_LEGACY')=='1'
if legacy: path.depth_volume=-1

# Observe the complete exporter, without changing the produced configuration.
original=config_export.convert
exports=[]
def observed(*args,**kwargs):
    result=original(*args,**kwargs)
    if result:
        names=result.GetAllNames()
        exports.append({n:result.Get(n).GetString() for n in names if n.startswith('path.pathdepth.')})
    return result
config_export.convert=observed
s.render.engine=os.environ.get('SLC_SSS_ENGINE','SUPERLUXCORE')
s.cycles.samples=cfg.halt.samples
s.cycles.use_denoising=False
s.cycles.use_adaptive_sampling=False
errors.clear(False)
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'scene.blend'))
s.render.filepath=str(OUT/'render.exr')
start=time.monotonic()
bpy.ops.render.render(write_still=True)
elapsed=time.monotonic()-start
image=bpy.data.images.load(str(OUT/'render.exr'),check_existing=False)
pixels=np.array(image.pixels[:],np.float32).reshape(s.render.resolution_y,s.render.resolution_x,4)
bpy.data.images.remove(image)
s.render.image_settings.file_format='PNG'
s.render.image_settings.color_depth='8'
bpy.data.images['Render Result'].save_render(str(OUT/'render.png'),scene=s)
record=dict(native_sha256=hashlib.sha256(native.read_bytes()).hexdigest(),engine=s.render.engine,
            blender=bpy.app.version_string,legacy=legacy,
            spectral=bool(cfg.config.spectral_enable and s.render.engine=='SUPERLUXCORE'),
            size=[s.render.resolution_x,s.render.resolution_y],samples=cfg.halt.samples,
            seconds=elapsed,threads=s.render.threads,finite=bool(np.isfinite(pixels).all()),
            mean_rgb=pixels[:,:,:3].mean(axis=(0,1),dtype=np.float64).tolist(),
            max_rgb=float(pixels[:,:,:3].max()),depth_contracts=rows,exports=exports,
            errors=[e.message for e in errors.errors])
(OUT/'result.json').write_text(json.dumps(record,indent=2))
assert record['finite'] and not record['errors'],record
if s.render.engine=='SUPERLUXCORE':
    assert exports and all(('path.pathdepth.volume' in e)==legacy for e in exports),exports
print('SSS_BLENDER_RESULT',json.dumps(record),flush=True)
