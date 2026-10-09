# SPDX-License-Identifier: Apache-2.0
"""Cycles Add/Mix emission lights another surface; verifies NEE and BSDF-hit MIS.

Use an enabled, matching development profile and SUPERLUXCORE_AUDIT_DIR.
DEV=OCL selects Metal. SUPERLUXCORE_AUDIT_SPECTRAL=1 selects spectral transport.
"""
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path

import bpy
import numpy as np
import pysuperluxcore as native

assert native.Version() == importlib.metadata.version('pysuperluxcore')
package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore'))
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-add-emitter'))
folder.mkdir(parents=True, exist_ok=True)
native_path = Path(native.pysuperluxcore.__file__).resolve()
native_sha = hashlib.sha256(native_path.read_bytes()).hexdigest()
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=8)
receiver = bpy.context.object
floor = bpy.data.materials.new('Original Cycles receiver')
floor.use_nodes = True
floor.node_tree.nodes.clear()
diffuse = floor.node_tree.nodes.new('ShaderNodeBsdfDiffuse')
diffuse.inputs['Color'].default_value = (1., 1., 1., 1.)
out = floor.node_tree.nodes.new('ShaderNodeOutputMaterial')
floor.node_tree.links.new(diffuse.outputs[0], out.inputs['Surface'])
receiver.data.materials.append(floor)
bpy.ops.mesh.primitive_plane_add(size=1, location=(1.5, 0, 2))
emitter = bpy.context.object
emitter.rotation_euler.y = math.pi
material = bpy.data.materials.new('Original Cycles emitter')
material.use_nodes = True
emitter.data.materials.append(material)
bpy.ops.object.camera_add(location=(0, 0, 5))
s = bpy.context.scene
s.camera = bpy.context.object
s.camera.data.type = 'ORTHO'
s.camera.data.ortho_scale = 2
s.render.resolution_x, s.render.resolution_y = 1280, 720
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.render.image_settings.color_mode = 'RGBA'
s.view_settings.view_transform = 'Standard'
s.cycles.samples = 128
s.cycles.use_denoising = False
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
cfg = s.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.config.spectral_enable = os.environ.get('SUPERLUXCORE_AUDIT_SPECTRAL') == '1'
if os.environ.get('SUPERLUXCORE_AUDIT_BIDIR') == '1':
    cfg.config.engine = 'BIDIR'
cfg.config.path.use_clamping = False
cfg.config.path.auto_clamping = False
cfg.halt.enable = cfg.halt.use_samples = True
cfg.halt.samples = 256
cfg.halt.use_noise_level = cfg.halt.use_noise_thresh = False
cfg.denoiser.enabled = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False
records = []
for condition in ('emission', 'add_emission_sum', 'add_transparent_emission',
                  'nested_transparent_emission', 'mix_transparent_emission',
                  'frontface_color', 'backface_color',
                  'frontface_strength', 'backface_strength'):
    if os.environ.get('SUPERLUXCORE_AUDIT_CASES') and condition not in os.environ['SUPERLUXCORE_AUDIT_CASES'].split(','):
        continue
    emitter.rotation_euler.y = 0.0 if condition.startswith('backface_') else math.pi
    bpy.context.view_layer.update()
    nodes, links = material.node_tree.nodes, material.node_tree.links
    nodes.clear()

    def emission(strength):
        node = nodes.new('ShaderNodeEmission')
        node.inputs['Color'].default_value = (1., 1., 1., 1.)
        node.inputs['Strength'].default_value = strength
        return node.outputs[0]

    def add(a, b):
        node = nodes.new('ShaderNodeAddShader')
        links.new(a, node.inputs[0])
        links.new(b, node.inputs[1])
        return node.outputs[0]

    surface = emission(.4)
    if condition.startswith(('frontface_', 'backface_')):
        geometry = nodes.new('ShaderNodeNewGeometry')
        target = next(node for node in nodes if node.bl_idname == 'ShaderNodeEmission')
        if condition.endswith('_color'):
            links.new(geometry.outputs['Backfacing'], target.inputs['Color'])
        else:
            multiply = nodes.new('ShaderNodeMath')
            multiply.operation = 'MULTIPLY'
            multiply.inputs[1].default_value = .4
            links.new(geometry.outputs['Backfacing'], multiply.inputs[0])
            links.new(multiply.outputs[0], target.inputs['Strength'])
    if condition == 'add_emission_sum':
        surface = add(emission(.2), emission(.2))
    if condition in {'add_transparent_emission', 'nested_transparent_emission'}:
        transparent = nodes.new('ShaderNodeBsdfTransparent')
        surface = add(transparent.outputs[0], emission(.4 if condition == 'add_transparent_emission' else .2))
        if condition == 'nested_transparent_emission':
            surface = add(surface, emission(.2))
    if condition == 'mix_transparent_emission':
        transparent = nodes.new('ShaderNodeBsdfTransparent')
        mix = nodes.new('ShaderNodeMixShader')
        mix.inputs[0].default_value = .5
        links.new(transparent.outputs[0], mix.inputs[1])
        links.new(emission(.8), mix.inputs[2])
        surface = mix.outputs[0]
    output = nodes.new('ShaderNodeOutputMaterial')
    links.new(surface, output.inputs['Surface'])
    snapshot = tuple((n.bl_idname, n.name, tuple(
        (i.name, tuple(i.default_value) if hasattr(i.default_value, '__len__') else i.default_value)
        for i in n.inputs if hasattr(i, 'default_value'))) for n in nodes)
    pixels = {}
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        log.clear(False)
        path = folder / (condition + '_' + engine + '.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path), check_existing=False)
        pixels[engine] = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[32:-32, 32:-32, :3].copy()
        bpy.data.images.remove(image)
        s.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
    assert snapshot == tuple((n.bl_idname, n.name, tuple(
        (i.name, tuple(i.default_value) if hasattr(i.default_value, '__len__') else i.default_value)
        for i in n.inputs if hasattr(i, 'default_value'))) for n in nodes)
    reference = float(pixels['CYCLES'].mean())
    actual = float(pixels['SUPERLUXCORE'].mean())
    rec = {'condition': condition, 'version': native.Version(), 'native_sha256': native_sha,
           'device': cfg.config.device, 'engine': cfg.config.engine,
           'spectral': bool(cfg.config.spectral_enable), 'resolution': [1280, 720],
           'cycles_samples': s.cycles.samples, 'native_samples': cfg.halt.samples,
           'finite': bool(np.isfinite(pixels['SUPERLUXCORE']).all()),
           'cycles_mean': reference, 'superluxcore_mean': actual,
           'relative_mean_error': abs(actual - reference) / max(reference, 1e-8),
           'pixel_mae': float(np.abs(pixels['CYCLES'] - pixels['SUPERLUXCORE']).mean()),
           'errors': [e.message for e in log.errors], 'warnings': [w.message for w in log.warnings]}
    energy_passed = (reference < 1e-4 and actual < 1e-4) if condition.startswith('frontface_') else (
        reference > 1e-4 and rec['relative_mean_error'] < .03)
    rec['passed'] = rec['finite'] and not rec['errors'] and energy_passed and all(
        w == 'Light-probe-volume backface culling is Eevee-only - ignored' for w in rec['warnings'])
    records.append(rec)
    (folder / 'metrics.json').write_text(json.dumps(records, indent=2) + '\n')
    print('Add emitter MIS check', rec, flush=True)
    if os.environ.get('SUPERLUXCORE_AUDIT_BASELINE') != '1':
        assert rec['passed'], rec
print('Add emitter MIS checks complete', len(records), sum(r['passed'] for r in records), flush=True)
