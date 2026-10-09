"""Compare Cycles Vector Math division, including per-component safe zeros."""
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
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-vector-divide'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
plane.scale.y = 9 / 16
mat = bpy.data.materials.new('Existing Cycles Vector Divide')
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
for condition in (('first_zero', 'linked_zero', 'linked') if cfg.config.spectral_enable else
                  ('first_zero', 'middle_zero', 'last_zero', 'all_zero', 'nonzero', 'constant', 'linked_zero', 'linked')):
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    uv = nodes.new('ShaderNodeTexCoord')
    divide = nodes.new('ShaderNodeVectorMath')
    divide.operation = 'DIVIDE'
    divide.inputs[0].default_value = (.3, -.2, .4)
    if condition != 'constant':
        source = nodes.new('ShaderNodeVectorMath')
        source.operation = 'ADD'
        source.inputs[1].default_value = (.3, -.2, .4)
        links.new(uv.outputs['UV'], source.inputs[0])
        links.new(source.outputs['Vector'], divide.inputs[0])
    divisors = {'first_zero': (0, 3, -.5), 'middle_zero': (-2, 0, -.5),
                'last_zero': (-2, 3, 0), 'all_zero': (0, 0, 0)}
    divide.inputs[1].default_value = divisors.get(condition, (-2, 3, -.5))
    if condition in {'linked', 'linked_zero'}:
        divisor = nodes.new('ShaderNodeVectorMath')
        divisor.operation = 'MULTIPLY_ADD'
        divisor.inputs[1].default_value = (.3, .4, .5) if condition == 'linked' else (0, .4, 0)
        divisor.inputs[2].default_value = (-2, 3, -.5) if condition == 'linked' else (0, 3, -.5)
        links.new(uv.outputs['UV'], divisor.inputs[0])
        links.new(divisor.outputs['Vector'], divide.inputs[1])
    visible = nodes.new('ShaderNodeVectorMath')
    visible.operation = 'MULTIPLY_ADD'
    visible.inputs[1].default_value = (.2, .2, .2)
    visible.inputs[2].default_value = (.5, .5, .5)
    links.new(divide.outputs['Vector'], visible.inputs[0])
    emission = nodes.new('ShaderNodeEmission')
    links.new(visible.outputs['Vector'], emission.inputs['Color'])
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(emission.outputs[0], out.inputs['Surface'])
    tag = condition
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
    record = {'condition': condition,
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
    assert record['mae'] < (.05 if record['spectral'] else .0015), record
    print('Vector divide check', record, flush=True)
print('Vector divide checks complete', len(records), flush=True)
