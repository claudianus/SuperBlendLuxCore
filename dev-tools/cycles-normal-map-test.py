"""Compare existing Cycles Normal Map spaces, strengths and MikkTSpace data at 720p."""
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
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-normal-map'))
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

import math
uv_original = [tuple(item.uv) for item in plane.data.uv_layers[0].data]
named = plane.data.uv_layers.new(name='Artist rotated UV')
for item, original in zip(named.data, uv_original):
    item.uv = (original[1], 1. - original[0])
conditions = ('tangent', 'nonuniform', 'rotated', 'mirrored_uv', 'named_uv',
              'strength_zero', 'strength_quarter', 'strength_two', 'strength_negative',
              'linked_strength', 'raw_color', 'OBJECT', 'WORLD', 'object_nonuniform',
              'world_strength_two', 'directx', 'backface')
if os.environ.get('SUPERLUXCORE_AUDIT_SPECTRAL') == '1':
    conditions = ('nonuniform', 'mirrored_uv', 'named_uv', 'linked_strength',
                  'raw_color', 'object_nonuniform', 'WORLD', 'backface')
for condition in conditions:
    plane.scale = (1., 1., 1.)
    plane.rotation_euler = (0., 0., 0.)
    for item, original in zip(plane.data.uv_layers[0].data, uv_original):
        item.uv = (1. - original[0], original[1]) if condition == 'mirrored_uv' else original
    if condition in {'nonuniform', 'object_nonuniform'}:
        plane.scale = (1., .65, 1.4)
    if condition in {'rotated', 'OBJECT', 'WORLD', 'object_nonuniform'}:
        plane.rotation_euler.z = .31
    if condition == 'backface':
        plane.rotation_euler.x = math.pi
    bpy.context.view_layer.update()
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    mapping = nodes.new('ShaderNodeNormalMap')
    mapping.space = 'OBJECT' if condition == 'object_nonuniform' else 'WORLD' if condition == 'world_strength_two' else condition if condition in {'OBJECT', 'WORLD'} else 'TANGENT'
    mapping.inputs['Color'].default_value = (.65, .6, .9, 1.)
    mapping.inputs['Strength'].default_value = 1.
    if condition == 'named_uv':
        mapping.uv_map = 'Artist rotated UV'
    if condition.startswith('strength_'):
        mapping.inputs['Strength'].default_value = {'strength_zero':0., 'strength_quarter':.25, 'strength_two':2., 'strength_negative':-.5}[condition]
    if condition == 'world_strength_two':
        mapping.inputs['Strength'].default_value = 2.
    if condition == 'raw_color':
        mapping.inputs['Color'].default_value = (.35, .7, 2., 1.)
    if condition == 'directx':
        mapping.convention = 'DIRECTX'
    if condition == 'linked_strength':
        uv = nodes.new('ShaderNodeTexCoord')
        split = nodes.new('ShaderNodeSeparateXYZ')
        links.new(uv.outputs['UV'], split.inputs[0])
        strength = nodes.new('ShaderNodeMath')
        strength.operation = 'MULTIPLY_ADD'
        strength.inputs[1].default_value = 2.5
        strength.inputs[2].default_value = -.5
        links.new(split.outputs['X'], strength.inputs[0])
        links.new(strength.outputs[0], mapping.inputs['Strength'])
    surface = nodes.new('ShaderNodeBsdfDiffuse')
    links.new(mapping.outputs['Normal'], surface.inputs['Normal'])
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
    record = {'condition':condition, 'native_version':native_version,
              'spectral':bool(cfg.config.spectral_enable),
              'finite':bool(np.isfinite(pixels['SUPERLUXCORE']).all()),
              'mae':float(error.mean()), 'p99':float(np.quantile(error,.99)),
              'errors':[e.message for e in log.errors], 'warnings':[w.message for w in log.warnings]}
    records.append(record)
    (folder/'metrics.json').write_text(json.dumps(records,ensure_ascii=False,indent=2))
    assert record['finite'] and not record['errors'], record
    assert all(w == 'Light-probe-volume backface culling is Eevee-only - ignored' for w in record['warnings']), record
    assert record['mae'] < .003, record
    print('Normal Map check',record,flush=True)
print('Normal Map checks complete',len(records),flush=True)
