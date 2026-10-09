"""Unchanged Cycles Backfacing graphs, front/back and constant controls.

Run with a matching Blender development profile and DEV=OCL for Metal.
SUPERLUXCORE_AUDIT_BASELINE=1 records historical failed diagnostics.
"""
import importlib
import importlib.metadata
import hashlib
import json
import os
import math
from pathlib import Path
import bpy
import numpy as np
import pysuperluxcore as native
assert native.Version() == importlib.metadata.version('pysuperluxcore')
package = next((a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore')))
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
r = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
r.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
plane.scale.y = 9 / 16
mat = bpy.data.materials.new('Existing Cycles Backfacing consumers')
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
s.view_settings.view_transform = 'Standard'
s.cycles.samples = 16
s.cycles.use_denoising = False
cfg = s.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.config.spectral_enable = True
cfg.halt.enable = cfg.halt.use_samples = True
cfg.halt.samples = 16
cfg.halt.use_noise_level = False
cfg.halt.use_noise_thresh = False
cfg.denoiser.enabled = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False
records = []
for consumer in ('color', 'scalar', 'scalar_math', 'constant'):
    for side in ('front', 'back'):
        plane.rotation_euler.x = math.pi if side == 'back' else 0.0
        bpy.context.view_layer.update()
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        geometry = nodes.new('ShaderNodeNewGeometry')
        emission = nodes.new('ShaderNodeEmission')
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(emission.outputs[0], out.inputs['Surface'])
        if consumer == 'constant':
            emission.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0) if side == 'front' else (0.0, 0.0, 0.0, 1.0)
        elif consumer == 'scalar_math':
            math_node = nodes.new('ShaderNodeMath')
            math_node.operation = 'ADD'
            math_node.inputs[1].default_value = 0.0
            links.new(geometry.outputs['Backfacing'], math_node.inputs[0])
            links.new(math_node.outputs[0], emission.inputs['Strength'])
        else:
            links.new(geometry.outputs['Backfacing'], emission.inputs['Color' if consumer == 'color' else 'Strength'])

        def fingerprint():

            def value(socket):
                v = socket.default_value
                return tuple(v) if hasattr(v, '__iter__') else v
            return (sorted(((x.from_node.bl_idname, x.from_socket.name, x.to_node.bl_idname, x.to_socket.name) for x in links)), sorted(((n.name, n.bl_idname, getattr(n, 'operation', ''), [(i.name, value(i)) for i in n.inputs if hasattr(i, 'default_value')]) for n in nodes)), tuple((v for row in plane.matrix_world for v in row)))
        before = fingerprint()
        pixels = {}
        case = consumer + '_' + side
        for engine in ('CYCLES', 'SUPERLUXCORE'):
            s.render.engine = engine
            log.clear(False)
            f = r / (case + '_' + engine + '.exr')
            s.render.filepath = str(f)
            bpy.ops.render.render(write_still=True)
            im = bpy.data.images.load(str(f), check_existing=False)
            pixels[engine] = np.asarray(im.pixels[:], np.float32).reshape(720, 1280, 4)[100:-100, 100:-100, :3].copy()
            bpy.data.images.remove(im)
            s.render.image_settings.file_format = 'PNG'
            bpy.data.images['Render Result'].save_render(str(f.with_suffix('.png')), scene=s)
            s.render.image_settings.file_format = 'OPEN_EXR'
        assert fingerprint() == before
        mae = float(np.abs(pixels['CYCLES'] - pixels['SUPERLUXCORE']).mean())
        record = {'case': case, 'passed': mae < 0.03, 'mae': mae, 'cycles_mean': float(pixels['CYCLES'].mean()), 'native_mean': float(pixels['SUPERLUXCORE'].mean()), 'finite': bool(np.isfinite(pixels['SUPERLUXCORE']).all()), 'warnings': [w.message for w in log.warnings], 'errors': [e.message for e in log.errors], 'graph_unchanged': True, 'native_version': native.Version(), 'native_sha256': hashlib.sha256(Path(native.pysuperluxcore.__file__).read_bytes()).hexdigest(), 'device': cfg.config.device, 'spectral': True, 'resolution': [1280, 720]}
        assert record['finite'] and (not record['errors']), record
        assert all(w == 'Light-probe-volume backface culling is Eevee-only - ignored' for w in record['warnings']), record
        records.append(record)
        (r / 'metrics.json').write_text(json.dumps(records, indent=2) + '\n')
        print('BACKFACING_COLOR_DIAGNOSTIC', record, flush=True)
        if os.environ.get('SUPERLUXCORE_AUDIT_BASELINE') != '1':
            assert record['passed'], record
