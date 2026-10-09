"""Compare existing Cycles normal-vector graphs through the 720p Normal pass."""
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
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-normal-vector'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
plane.scale.y = 9 / 16
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
mat = bpy.data.materials.new('Existing Cycles Normal Vectors')
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
layer = s.view_layers[0]
layer.use_pass_normal = True
tree = bpy.data.node_groups.new('Existing Cycles Normal compositor', 'CompositorNodeTree')
tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
rl = tree.nodes.new('CompositorNodeRLayers')
rl.layer = layer.name
out = tree.nodes.new('NodeGroupOutput')
tree.links.new(rl.outputs['Normal'], out.inputs['Image'])
s.compositing_node_group = tree
s.render.use_compositing = True

conditions = ('constant', 'negative', 'zero', 'geometry', 'uv_vector',
              'vector_mix', 'normalmap', 'normalmap_math', 'normalmap_mix', 'flat_mix')
if os.environ.get('SUPERLUXCORE_AUDIT_SPECTRAL') == '1':
    conditions = ('negative', 'uv_vector', 'normalmap_math', 'normalmap_mix', 'flat_mix')

for condition in conditions:
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    geometry = nodes.new('ShaderNodeNewGeometry')
    uv = nodes.new('ShaderNodeTexCoord')
    vector = nodes.new('ShaderNodeCombineXYZ')
    for key, value in zip(('X', 'Y', 'Z'), (.3, .4, 1.)):
        vector.inputs[key].default_value = value
    normal = vector.outputs[0]
    if condition == 'negative':
        vector.inputs['X'].default_value = -.3
    elif condition == 'zero':
        for socket in vector.inputs:
            socket.default_value = 0.
    elif condition == 'geometry':
        normal = geometry.outputs['Normal']
    elif condition in {'uv_vector', 'vector_mix'}:
        math = nodes.new('ShaderNodeVectorMath')
        math.operation = 'MULTIPLY_ADD'
        math.inputs[1].default_value = (.35, .4, 0.)
        math.inputs[2].default_value = (-.2, -.15, 1.)
        links.new(uv.outputs['UV'], math.inputs[0])
        normal = math.outputs['Vector']
        if condition == 'vector_mix':
            mix = nodes.new('ShaderNodeMix')
            mix.data_type = 'VECTOR'
            mix.factor_mode = 'UNIFORM'
            links.new(uv.outputs['UV'], mix.inputs[0])
            links.new(normal, mix.inputs[4])
            links.new(geometry.outputs['Normal'], mix.inputs[5])
            normal = mix.outputs[1]
    elif condition.startswith('normalmap') or condition == 'flat_mix':
        mapping = nodes.new('ShaderNodeNormalMap')
        mapping.inputs['Color'].default_value = (.65, .7, 1., 1.)
        mapping.inputs['Strength'].default_value = 1.
        normal = mapping.outputs['Normal']
        if condition == 'normalmap_math':
            math = nodes.new('ShaderNodeVectorMath')
            math.operation = 'ADD'
            math.inputs[1].default_value = (-.1, .05, 0.)
            links.new(normal, math.inputs[0])
            normal = math.outputs['Vector']
        elif condition in {'normalmap_mix', 'flat_mix'}:
            other = nodes.new('ShaderNodeNormalMap')
            other.inputs['Color'].default_value = (.35, .55, 1., 1.)
            mix = nodes.new('ShaderNodeMix')
            mix.data_type = 'VECTOR'
            mix.factor_mode = 'UNIFORM'
            links.new(uv.outputs['UV'], mix.inputs[0])
            links.new(normal, mix.inputs[4])
            links.new(other.outputs['Normal'] if condition == 'normalmap_mix' else geometry.outputs['Normal'], mix.inputs[5])
            normal = mix.outputs[1]
    surface = nodes.new('ShaderNodeBsdfDiffuse')
    links.new(normal, surface.inputs['Normal'])
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(surface.outputs[0], out.inputs['Surface'])
    pixels = {}
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        log.clear(False)
        path = folder / (condition + '_' + engine + '.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path), check_existing=False)
        pixels[engine] = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[8:-8, 8:-8, :3].copy()
        bpy.data.images.remove(image)
        s.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
    error = np.abs(pixels['CYCLES'] - pixels['SUPERLUXCORE'])
    record = {'condition': condition, 'native_version': native_version,
              'spectral': bool(cfg.config.spectral_enable),
              'finite': bool(np.isfinite(pixels['SUPERLUXCORE']).all()),
              'mae': float(error.mean()), 'p99': float(np.quantile(error, .99)),
              'errors': [e.message for e in log.errors], 'warnings': [w.message for w in log.warnings]}
    records.append(record)
    (folder / 'metrics.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
    assert record['finite'] and not record['errors'], record
    assert all(w == 'Light-probe-volume backface culling is Eevee-only - ignored' for w in record['warnings']), record
    assert record['mae'] < .003, record
    print('Normal vector check', record, flush=True)
print('Normal vector checks complete', len(records), flush=True)
