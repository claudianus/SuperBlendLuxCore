"""Compare Cycles Sphere/Tube image projections, including poles and zero vectors."""
import importlib
import importlib.metadata
import json
import os
from pathlib import Path

import bpy
import numpy as np

native_version = importlib.import_module('pysuperluxcore').Version()
assert native_version == importlib.metadata.version('pysuperluxcore'), 'Native/package version mismatch'

package = next(a.module for a in bpy.context.preferences.addons
               if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-image-projection'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
plane.scale.y = 9 / 16
mat = bpy.data.materials.new('Existing Cycles Image Vector')
mat.use_nodes = True
plane.data.materials.append(mat)
bpy.ops.object.camera_add(location=(0, 0, 4))
s = bpy.context.scene
s.camera = bpy.context.object
s.camera.data.type = 'ORTHO'
s.camera.data.ortho_scale = 2
s.render.resolution_x = 1280
s.render.resolution_y = 720
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.render.image_settings.color_mode = 'RGBA'
s.view_settings.view_transform = 'Standard'
s.cycles.samples = 16
s.cycles.use_denoising = False
cfg = s.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.config.spectral_enable = os.environ.get('SUPERLUXCORE_AUDIT_SPECTRAL') == '1'
cfg.halt.enable = True
cfg.halt.use_samples = True
cfg.halt.samples = 16
cfg.denoiser.enabled = False
cfg.config.path.use_clamping = False
cfg.config.path.auto_clamping = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False
records = []
# A saved non-colour EXR supplies asymmetric gradients and varying alpha.
image = bpy.data.images.new('Cycles image coordinate fixture', width=64, height=64, alpha=True, float_buffer=True)
x, y = np.meshgrid((np.arange(64) + .5) / 64, (np.arange(64) + .5) / 64)
data = np.stack((.05 + .65*x, .05 + .65*y, .15 + .3*x*y, .2 + .7*y), axis=-1)
image.pixels.foreach_set(data.astype(np.float32).ravel())
image.filepath_raw = str(folder / 'coordinate-image.exr')
image.file_format = 'OPEN_EXR'
image.save()
path = image.filepath_raw
bpy.data.images.remove(image)
image = bpy.data.images.load(path, check_existing=False)
image.colorspace_settings.name = 'Non-Color'
image.alpha_mode = 'CHANNEL_PACKED'
fixture_image = image
extra = plane.data.uv_layers.new(name='Artist UV')
for loop in extra.data:
    loop.uv = (.8*loop.uv.x + .1, .6*loop.uv.y + .2)

for projection in ('SPHERE', 'TUBE'):
  for condition in (('generated', 'POINT') if cfg.config.spectral_enable else
                    ('default_uv', 'generated', 'POINT', 'axis', 'zero')):
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    uv = nodes.new('ShaderNodeTexCoord')
    tex = nodes.new('ShaderNodeTexImage')
    tex.image = fixture_image
    tex.projection = projection
    tex.interpolation = 'Linear'
    tex.extension = 'REPEAT'
    coordinate = uv.outputs['UV']
    if condition == 'named_uv':
        named = nodes.new('ShaderNodeUVMap')
        named.uv_map = 'Artist UV'
        coordinate = named.outputs['UV']
    elif condition in {'generated', 'object'}:
        coordinate = uv.outputs[condition.title()]
    elif condition in {'constant', 'axis', 'zero'}:
        value = nodes.new('ShaderNodeCombineXYZ')
        for k, v in zip(('X', 'Y', 'Z'), ((.5, .5, 1.) if condition == 'axis' else (.5, .5, .5))):
            value.inputs[k].default_value = v
        coordinate = value.outputs[0]
    elif condition in {'math', 'alpha'}:
        math = nodes.new('ShaderNodeVectorMath')
        math.operation = 'MULTIPLY_ADD'
        math.inputs[1].default_value = (.65, .7, 1.)
        math.inputs[2].default_value = (.12, .08, 0.)
        links.new(coordinate, math.inputs[0])
        coordinate = math.outputs['Vector']
    elif condition in {'POINT', 'TEXTURE', 'VECTOR', 'NORMAL', 'chain'}:
        mapping = nodes.new('ShaderNodeMapping')
        mapping.vector_type = condition if condition != 'chain' else 'POINT'
        links.new(coordinate, mapping.inputs['Vector'])
        for key, factor, offset in (('Location', .1, (.05, .02, .1)),
                                    ('Rotation', .15, (.1, -.2, .3)),
                                    ('Scale', .2, (.7, .6, 1.))):
            if key not in mapping.inputs:
                continue
            linked = nodes.new('ShaderNodeVectorMath')
            linked.operation = 'MULTIPLY_ADD'
            linked.inputs[1].default_value = (factor, factor, factor)
            linked.inputs[2].default_value = offset
            links.new(uv.outputs['UV'], linked.inputs[0])
            links.new(linked.outputs['Vector'], mapping.inputs[key])
        coordinate = mapping.outputs['Vector']
        if condition == 'chain':
            second = nodes.new('ShaderNodeMapping')
            second.vector_type = 'TEXTURE'
            second.inputs['Location'].default_value = (.1, .12, .2)
            second.inputs['Scale'].default_value = (1.3, 1.1, 1.)
            links.new(coordinate, second.inputs['Vector'])
            coordinate = second.outputs['Vector']
    if condition != 'default_uv':
        links.new(coordinate, tex.inputs['Vector'])
    emission = nodes.new('ShaderNodeEmission')
    links.new(tex.outputs['Alpha' if condition == 'alpha' else 'Color'], emission.inputs['Color'])
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(emission.outputs[0], out.inputs['Surface'])
    tag = projection + '_' + condition
    pixels = {}
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        log.clear(False)
        path = folder / (tag + '_' + engine + '.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path), check_existing=False)
        pixels[engine] = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[8:-8, 8:-8, :3].copy()
        bpy.data.images.remove(image)
        s.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
    error = np.abs(pixels['CYCLES'] - pixels['SUPERLUXCORE'])
    record = {'projection': projection, 'condition': condition,
              'native_version': importlib.import_module('pysuperluxcore').Version(),
              'spectral': bool(cfg.config.spectral_enable),
              'finite': bool(np.isfinite(pixels['SUPERLUXCORE']).all()),
              'mae': float(error.mean()), 'p99': float(np.quantile(error, .99)),
              'errors': [e.message for e in log.errors], 'warnings': [w.message for w in log.warnings]}
    records.append(record)
    (folder / 'metrics.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
    assert record['finite'] and not record['errors'], record
    # Blender's default Eevee light-probe flag is unrelated to this material.
    assert all(w == 'Light-probe-volume backface culling is Eevee-only - ignored'
               for w in record['warnings']), record
    assert record['mae'] < (.05 if record['spectral'] else .004), record
    print('Image projection check', record, flush=True)
print('Image projection checks complete', len(records), flush=True)
