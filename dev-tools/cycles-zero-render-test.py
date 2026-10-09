# SPDX-License-Identifier: Apache-2.0
"""Literal and linked zero keep the same shader meaning at 1280x720.

Each unchanged Cycles graph is rendered with both engines. Pair metrics
compare equivalent forms within an engine, not identical BSDF implementations.
DEV=OCL selects Metal. AUDIT_BASELINE=1 records known failed diagnostics.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path

import bpy
import numpy as np
import pysuperluxcore as native

package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore'))
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
folder = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=48, radius=.8)
obj = bpy.context.object
for face in obj.data.polygons:
    face.use_smooth = True
mat = bpy.data.materials.new('Existing Cycles zero-valued inputs')
mat.use_nodes = True
obj.data.materials.append(mat)
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
s.cycles.samples = 64
s.cycles.use_denoising = False
cfg = s.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.config.spectral_enable = True
cfg.config.path.use_clamping = False
cfg.config.path.auto_clamping = False
cfg.halt.enable = cfg.halt.use_samples = True
cfg.halt.samples = 64
cfg.halt.use_noise_level = cfg.halt.use_noise_thresh = False
cfg.denoiser.enabled = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False
records = []


def fingerprint(nodes, links):
    def value(socket):
        v = socket.default_value
        return tuple(v) if hasattr(v, '__iter__') else v
    return (sorted((n.name, n.bl_idname, [(i.name, value(i)) for i in n.inputs
                                        if hasattr(i, 'default_value')]) for n in nodes),
            sorted((l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name)
                   for l in links))


for case in ('sss_scale', 'sss_roughness', 'sheen_roughness', 'mix_group', 'invert_group',
             'sheen_quarter', 'sheen_half', 'sheen_one'):
    if os.environ.get('SUPERLUXCORE_AUDIT_CASES') and case not in os.environ['SUPERLUXCORE_AUDIT_CASES'].split(','):
        continue
    results = {}
    for form in ('literal', 'linked'):
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        out = nodes.new('ShaderNodeOutputMaterial')
        if case.startswith('sss_'):
            target = nodes.new('ShaderNodeSubsurfaceScattering')
            target.inputs['Color'].default_value = (.45, .45, .45, 1.)
            target.inputs['Scale'].default_value = .15
            socket = target.inputs['Scale' if case == 'sss_scale' else 'Roughness']
            surface = target.outputs[0]
        elif case.startswith('sheen_'):
            target = nodes.new('ShaderNodeBsdfSheen')
            target.inputs['Color'].default_value = (.45, .45, .45, 1.)
            socket = target.inputs['Roughness']
            surface = target.outputs[0]
        elif case == 'mix_group':
            target = nodes.new('ShaderNodeMixShader')
            socket = target.inputs['Fac']
            for i, color in ((1, .2), (2, .8)):
                emission = nodes.new('ShaderNodeEmission')
                emission.inputs['Color'].default_value = (color, color, color, 1.)
                links.new(emission.outputs[0], target.inputs[i])
            surface = target.outputs[0]
        else:
            target = nodes.new('ShaderNodeInvert')
            target.inputs['Color'].default_value = (.2, .4, .6, 1.)
            socket = target.inputs['Fac']
            emission = nodes.new('ShaderNodeEmission')
            links.new(target.outputs[0], emission.inputs['Color'])
            surface = emission.outputs[0]
        parameter = {'sheen_quarter': .25, 'sheen_half': .5, 'sheen_one': 1.0}.get(case, 0.)
        socket.default_value = parameter
        if form == 'linked':
            if case.endswith('_group'):
                group = bpy.data.node_groups.new('Existing Cycles zero output', 'ShaderNodeTree')
                group.interface.new_socket(name='Zero', in_out='OUTPUT', socket_type='NodeSocketFloat').default_value = 0.
                group.nodes.new('NodeGroupOutput')
                source = nodes.new('ShaderNodeGroup')
                source.node_tree = group
            else:
                source = nodes.new('ShaderNodeValue')
                source.outputs[0].default_value = parameter
            links.new(source.outputs[0], socket)
        links.new(surface, out.inputs['Surface'])
        before = fingerprint(nodes, links)
        for engine in ('CYCLES', 'SUPERLUXCORE'):
            s.render.engine = engine
            log.clear(False)
            path = folder / (case + '_' + form + '_' + engine + '.exr')
            s.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            image = bpy.data.images.load(str(path), check_existing=False)
            pixels = np.asarray(image.pixels[:], np.float32).reshape(720, 1280, 4)[:, :, :3].copy()
            bpy.data.images.remove(image)
            results[(engine, form)] = pixels
            s.render.image_settings.file_format = 'PNG'
            bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
            s.render.image_settings.file_format = 'OPEN_EXR'
            assert fingerprint(nodes, links) == before
            assert np.isfinite(pixels).all() and not log.errors
            assert all(w.message == 'Light-probe-volume backface culling is Eevee-only - ignored'
                       or w.message.startswith('The scene contains a lot of light sources (')
                       for w in log.warnings), [w.message for w in log.warnings]
    pair = {}
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        a, b = results[(engine, 'literal')], results[(engine, 'linked')]
        delta = float(np.abs(a - b).mean())
        mean_a, mean_b = float(a.mean()), float(b.mean())
        # A 0.01 floor bounds absolute Monte Carlo noise in dim SSS renders.
        relative = abs(mean_a - mean_b) / max(mean_a, mean_b, .01)
        pair[engine] = {'literal_mean': mean_a, 'linked_mean': mean_b,
                        'relative_mean_error': relative, 'pixel_mae': delta,
                        'passed': relative < .03 and delta < .03}
    rec = {'case': case, 'passed': all(r['passed'] for r in pair.values()),
           'pair': pair, 'graph_unchanged': True, 'spectral': True,
           'cross_engine_mean_ratio': pair['SUPERLUXCORE']['literal_mean'] / max(pair['CYCLES']['literal_mean'], 1e-8),
           'full_bsdf_parity_verified': False,
           'resolution': [1280, 720], 'samples': 64, 'device': cfg.config.device,
           'native_sha256': hashlib.sha256(Path(native.pysuperluxcore.__file__).read_bytes()).hexdigest()}
    if case == 'sss_scale' or case.startswith('sheen_'):
        cross_delta = abs(pair['CYCLES']['literal_mean'] - pair['SUPERLUXCORE']['literal_mean'])
        rec['cross_engine_condition_verified'] = cross_delta < .03 * max(pair['CYCLES']['literal_mean'], .01)
        rec['passed'] = rec['passed'] and rec['cross_engine_condition_verified']
    records.append(rec)
    (folder / 'metrics.json').write_text(json.dumps(records, indent=2) + '\n')
    print('ZERO_RENDER', rec, flush=True)
    if os.environ.get('SUPERLUXCORE_AUDIT_BASELINE') != '1':
        assert rec['passed'], rec
print('ZERO_RENDER_COMPLETE', len(records), sum(r['passed'] for r in records), flush=True)
