"""Existing Cycles Diffuse roughness reaches the native EON model at 720p."""
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import bpy
import numpy as np
from mathutils import Vector

native = importlib.import_module('pysuperluxcore')
assert native.Version() == importlib.metadata.version('pysuperluxcore')
package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore'))
reader = importlib.import_module(package + '.export.cycles_node_reader')
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-diffuse-roughness'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=48, radius=.8)
obj = bpy.context.object
for face in obj.data.polygons:
    face.use_smooth = True
mat = bpy.data.materials.new('Existing Cycles rough diffuse')
mat.use_nodes = True
obj.data.materials.append(mat)
nodes, links = mat.node_tree.nodes, mat.node_tree.links
nodes.clear()
bsdf = nodes.new('ShaderNodeBsdfDiffuse')
bsdf.inputs['Color'].default_value = (.45, .45, .45, 1.)
out = nodes.new('ShaderNodeOutputMaterial')
links.new(bsdf.outputs[0], out.inputs['Surface'])
bpy.ops.object.camera_add(location=(0, -4, 1.4))
s = bpy.context.scene
s.camera = bpy.context.object
s.camera.rotation_euler = (-s.camera.location).to_track_quat('-Z', 'Y').to_euler()
s.camera.data.type = 'ORTHO'
s.camera.data.ortho_scale = 3.2
bpy.ops.object.light_add(type='SUN', location=(-2, -3, 4))
sun = bpy.context.object
sun.rotation_euler = (-sun.location).to_track_quat('-Z', 'Y').to_euler()
sun.data.energy = 1.
sun.data.angle = .01
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.
s.render.resolution_x, s.render.resolution_y = 1280, 720
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.render.image_settings.color_mode = 'RGBA'
s.view_settings.view_transform = 'Standard'
s.cycles.samples = 32
s.cycles.use_denoising = False
cfg = s.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.config.spectral_enable = os.environ.get('SUPERLUXCORE_AUDIT_SPECTRAL') == '1'
cfg.config.path.use_clamping = False
cfg.config.path.auto_clamping = False
cfg.halt.enable = cfg.halt.use_samples = True
cfg.halt.samples = 32
cfg.denoiser.enabled = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False
records, rendered = [], {}
for condition, value in (('zero', 0.), ('quarter', .25), ('one', 1.), ('linked', None)):
    if value is not None:
        bsdf.inputs['Roughness'].default_value = value
    else:
        uv = nodes.new('ShaderNodeTexCoord')
        split = nodes.new('ShaderNodeSeparateXYZ')
        links.new(uv.outputs['UV'], split.inputs[0])
        links.new(split.outputs['X'], bsdf.inputs['Roughness'])
    props = native.Properties()
    name, props = reader.convert(mat, props, 'audit_diffuse', obj.name)
    kind = props.Get('scene.materials.' + name + '.type').GetString()
    assert kind == ('matte' if condition == 'zero' else 'roughmatte'), (condition, str(props))
    if kind == 'roughmatte':
        assert props.IsDefined('scene.materials.' + name + '.sigma')
    original = (bsdf.inputs['Roughness'].default_value, bsdf.inputs['Roughness'].is_linked)
    pixels = {}
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        log.clear(False)
        path = folder / (condition + '_' + engine + '.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path), check_existing=False)
        pixels[engine] = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[:, :, :3].copy()
        bpy.data.images.remove(image)
        s.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
    assert original == (bsdf.inputs['Roughness'].default_value, bsdf.inputs['Roughness'].is_linked)
    mask = pixels['CYCLES'].mean(axis=2) > .02
    delta = np.abs(pixels['CYCLES'][mask] - pixels['SUPERLUXCORE'][mask])
    record = {'condition':condition, 'native_version':native.Version(),
              'spectral':cfg.config.spectral_enable, 'finite':bool(np.isfinite(pixels['SUPERLUXCORE']).all()),
              'mae':float(delta.mean()), 'max':float(delta.max()),
              'cycles_mean':float(pixels['CYCLES'][mask].mean()),
              'superluxcore_mean':float(pixels['SUPERLUXCORE'][mask].mean()),
              'errors':[e.message for e in log.errors], 'warnings':[w.message for w in log.warnings]}
    records.append(record)
    (folder / 'metrics.json').write_text(json.dumps(records, indent=2))
    assert record['finite'] and not record['errors'] and record['superluxcore_mean'] > .01, record
    assert all(w == 'Light-probe-volume backface culling is Eevee-only - ignored' for w in record['warnings']), record
    assert record['mae'] < .03, record
    rendered[condition] = pixels
    print('Diffuse roughness check',record,flush=True)
for engine in ('CYCLES','SUPERLUXCORE'):
    impact = float(np.abs(rendered['one'][engine] - rendered['zero'][engine]).mean())
    assert impact > .002, (engine, impact)
    print('Roughness image impact', engine, impact, flush=True)
print('Diffuse roughness checks complete',len(records),flush=True)
