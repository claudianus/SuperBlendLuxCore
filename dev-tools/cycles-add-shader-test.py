# SPDX-License-Identifier: Apache-2.0
"""Existing Cycles Add Shader preserves closure and emission sums."""
import importlib, importlib.metadata, json, os, math, hashlib
from pathlib import Path
import bpy, numpy as np
native = importlib.import_module('pysuperluxcore')
assert native.Version() == importlib.metadata.version('pysuperluxcore')
native_path = Path(native.pysuperluxcore.__file__).resolve()
native_sha = hashlib.sha256(native_path.read_bytes()).hexdigest()
package = next((a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore')))
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-add-shader'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
plane.scale.y = 9 / 16
mat = bpy.data.materials.new('Original Cycles Add Closure Sum')
mat.use_nodes = True
plane.data.materials.append(mat)
bpy.ops.object.camera_add(location=(0, 0, 4))
s = bpy.context.scene
s.camera = bpy.context.object
s.camera.data.type = 'ORTHO'
s.camera.data.ortho_scale = 2
s.render.resolution_x, s.render.resolution_y = (1280, 720)
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.view_settings.view_transform = 'Standard'
s.cycles.samples = 64
s.cycles.use_denoising = False
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1
s.world.node_tree.nodes['Background'].inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
s.render.film_transparent = os.environ.get('SUPERLUXCORE_AUDIT_ALPHA') == '1'
if s.render.film_transparent:
    s.cycles.samples = 256
cfg = s.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
if os.environ.get('SUPERLUXCORE_AUDIT_BIDIR') == '1':
    cfg.config.engine = 'BIDIR'
cfg.config.path.use_clamping = False
cfg.config.path.auto_clamping = False
cfg.config.spectral_enable = os.environ.get('SUPERLUXCORE_AUDIT_SPECTRAL') == '1'
cfg.halt.enable = cfg.halt.use_samples = True
cfg.halt.samples = 128
cfg.halt.use_noise_level = False
cfg.halt.use_noise_thresh = False
cfg.denoiser.enabled = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False
def graph_snapshot(nodes, links):
    values = tuple((node.bl_idname, node.name, tuple(
        (socket.name, tuple(socket.default_value) if hasattr(socket.default_value, '__len__')
         else socket.default_value)
        for socket in node.inputs if hasattr(socket, 'default_value')))
        for node in nodes)
    edges = tuple((link.from_node.name, link.from_socket.name,
                   link.to_node.name, link.to_socket.name) for link in links)
    return values, edges


records = []
for condition, expected in (('single', 1.0), ('add_diffuse', 2.0), ('mix_diffuse', 1.0), ('nested_add', 3.0), ('add_mirror', 2.0), ('add_transparent', 2.0), ('emission_surface', 1.4), ('existing_emission', 1.7), ('emission_sum', 1.0), ('mix_transparent', 1.0), ('transparent_only', 1.0), ('emission_transparent', 1.4), ('emission_mix_transparent', 1.4), ('nested_transparent', 3.0), ('add_colored_transparent', 1.6), ('mix_colored_transparent', 0.8), ('colored_transparent_only', 0.6), ('add_two_transparent', 2.0), ('one_unlinked', 1.0), ('both_unlinked', 0.0), ('group_sum', 2.3), ('textured_mix_add', 1.5)):
    if os.environ.get('SUPERLUXCORE_AUDIT_CASES') and condition not in os.environ['SUPERLUXCORE_AUDIT_CASES'].split(','):
        continue
    n, l = (mat.node_tree.nodes, mat.node_tree.links)
    n.clear()

    def diffuse():
        b = n.new('ShaderNodeBsdfDiffuse')
        b.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
        return b.outputs[0]

    def emission(strength):
        b = n.new('ShaderNodeEmission')
        b.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
        b.inputs['Strength'].default_value = strength
        return b.outputs[0]

    def add(a, b):
        node = n.new('ShaderNodeAddShader')
        l.new(a, node.inputs[0])
        l.new(b, node.inputs[1])
        return node.outputs[0]
    surface = diffuse()
    if condition in {'one_unlinked', 'both_unlinked'}:
        shader_sum = n.new('ShaderNodeAddShader')
        if condition == 'one_unlinked':
            l.new(surface, shader_sum.inputs[0])
        surface = shader_sum.outputs[0]
    if condition == 'group_sum':
        group = bpy.data.node_groups.new('Original Cycles Sum Group', 'ShaderNodeTree')
        group.interface.new_socket(name='Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
        group_output = group.nodes.new('NodeGroupOutput')
        group_diffuse = [group.nodes.new('ShaderNodeBsdfDiffuse') for _ in range(2)]
        for diffuse_node in group_diffuse:
            diffuse_node.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
        group_emission = group.nodes.new('ShaderNodeEmission')
        group_emission.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
        group_emission.inputs['Strength'].default_value = 0.3
        sums = [group.nodes.new('ShaderNodeAddShader') for _ in range(2)]
        group.links.new(group_diffuse[0].outputs[0], sums[0].inputs[0])
        group.links.new(group_diffuse[1].outputs[0], sums[0].inputs[1])
        group.links.new(sums[0].outputs[0], sums[1].inputs[0])
        group.links.new(group_emission.outputs[0], sums[1].inputs[1])
        group.links.new(sums[1].outputs[0], group_output.inputs[0])
        instance = n.new('ShaderNodeGroup')
        instance.node_tree = group
        surface = instance.outputs[0]
    if condition == 'textured_mix_add':
        shader_sum = add(surface, diffuse())
        mirror = n.new('ShaderNodeBsdfGlossy')
        mirror.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
        mirror.inputs['Roughness'].default_value = 0.0
        coord = n.new('ShaderNodeTexCoord')
        split = n.new('ShaderNodeSeparateXYZ')
        l.new(coord.outputs['UV'], split.inputs[0])
        mix = n.new('ShaderNodeMixShader')
        l.new(split.outputs['Y'], mix.inputs[0])
        l.new(shader_sum, mix.inputs[1])
        l.new(mirror.outputs[0], mix.inputs[2])
        surface = mix.outputs[0]
    if condition == 'add_diffuse':
        surface = add(surface, diffuse())
    if condition == 'mix_diffuse':
        mix = n.new('ShaderNodeMixShader')
        mix.inputs[0].default_value = 0.37
        l.new(surface, mix.inputs[1])
        l.new(diffuse(), mix.inputs[2])
        surface = mix.outputs[0]
    if condition == 'nested_add':
        surface = add(add(surface, diffuse()), diffuse())
    if condition == 'add_mirror':
        mirror = n.new('ShaderNodeBsdfGlossy')
        mirror.inputs['Color'].default_value = (1.0, 1.0, 1.0, 1.0)
        mirror.inputs['Roughness'].default_value = 0.0
        surface = add(surface, mirror.outputs[0])
    if condition in {'add_transparent', 'mix_transparent', 'transparent_only', 'emission_transparent', 'emission_mix_transparent', 'nested_transparent', 'add_colored_transparent', 'mix_colored_transparent', 'colored_transparent_only', 'add_two_transparent'}:
        transparent = n.new('ShaderNodeBsdfTransparent')
        if 'colored' in condition:
            transparent.inputs['Color'].default_value = (0.3, 0.6, 0.9, 1.0)
        if condition == 'add_two_transparent':
            surface = add(transparent.outputs[0], n.new('ShaderNodeBsdfTransparent').outputs[0])
        elif condition == 'emission_transparent':
            surface = add(transparent.outputs[0], emission(0.4))
        elif condition == 'emission_mix_transparent':
            mix = n.new('ShaderNodeMixShader')
            mix.inputs[0].default_value = 0.5
            l.new(surface, mix.inputs[1])
            l.new(transparent.outputs[0], mix.inputs[2])
            surface = add(mix.outputs[0], emission(0.4))
        elif condition == 'nested_transparent':
            surface = add(add(surface, transparent.outputs[0]), diffuse())
        elif condition in {'transparent_only', 'colored_transparent_only'}:
            surface = transparent.outputs[0]
        elif condition in {'mix_transparent', 'mix_colored_transparent'}:
            mix = n.new('ShaderNodeMixShader')
            mix.inputs[0].default_value = 0.5
            l.new(surface, mix.inputs[1])
            l.new(transparent.outputs[0], mix.inputs[2])
            surface = mix.outputs[0]
        else:
            surface = add(surface, transparent.outputs[0])
    if condition == 'emission_surface':
        surface = add(surface, emission(0.4))
    if condition == 'existing_emission':
        surface = add(add(surface, emission(0.4)), emission(0.3))
    if condition == 'emission_sum':
        surface = add(emission(0.3), emission(0.7))
    if s.render.film_transparent:
        expected = {'add_transparent': 1.0, 'mix_transparent': 0.5, 'transparent_only': 0.0, 'emission_transparent': 0.4, 'emission_mix_transparent': 0.9, 'nested_transparent': 2.0, 'add_colored_transparent': 1.0, 'mix_colored_transparent': 0.5, 'colored_transparent_only': 0.0, 'add_two_transparent': 0.0}.get(condition, expected)
    out = n.new('ShaderNodeOutputMaterial')
    l.new(surface, out.inputs['Surface'])
    pixels = {}
    alphas = {}
    original = graph_snapshot(n, l)
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        log.clear(False)
        path = folder / (condition + '_' + engine + '.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        im = bpy.data.images.load(str(path), check_existing=False)
        pixels[engine] = np.asarray(im.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[8:-8, 8:-8, :3].copy()
        alphas[engine] = float(np.asarray(im.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[8:-8, 8:-8, 3].mean())
        bpy.data.images.remove(im)
        s.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
    assert original == graph_snapshot(n, l)
    rec = {'condition': condition, 'native_version': native.Version(), 'native_sha256': native_sha, 'blender_version': bpy.app.version_string, 'blender_build_hash': bpy.app.build_hash.decode(), 'device': cfg.config.device, 'film_transparent': s.render.film_transparent, 'cycles_samples': s.cycles.samples, 'native_samples': cfg.halt.samples, 'engine': cfg.config.engine, 'spectral': bool(cfg.config.spectral_enable), 'finite': bool(np.isfinite(pixels['SUPERLUXCORE']).all()), 'expected_energy': expected, 'cycles_mean': float(pixels['CYCLES'].mean()), 'superluxcore_mean': float(pixels['SUPERLUXCORE'].mean()), 'cycles_alpha': alphas['CYCLES'], 'superluxcore_alpha': alphas['SUPERLUXCORE'], 'mae': float(np.abs(pixels['CYCLES'] - pixels['SUPERLUXCORE']).mean()), 'errors': [e.message for e in log.errors], 'warnings': [w.message for w in log.warnings]}
    # Enforce mean energy; finite-sample pixel MAE remains diagnostic.
    rec['passed'] = rec['finite'] and (not rec['errors']) and all((w == 'Light-probe-volume backface culling is Eevee-only - ignored' for w in rec['warnings'])) and (abs(rec['cycles_mean'] - expected) < 0.01 * max(1.0, expected)) and (abs(rec['superluxcore_mean'] - expected) < 0.01 * max(1.0, expected))
    if s.render.film_transparent:
        alpha_expected = {'add_transparent': 0.0, 'mix_transparent': 0.5, 'transparent_only': 0.0, 'emission_transparent': 0.0, 'emission_mix_transparent': 0.5, 'nested_transparent': 0.0, 'add_colored_transparent': 0.4, 'mix_colored_transparent': 0.7, 'colored_transparent_only': 0.4, 'add_two_transparent': 0.0}.get(condition, 1.0)
        rec['expected_alpha'] = alpha_expected
        rec['passed'] = rec['passed'] and abs(rec['cycles_alpha'] - alpha_expected) < 0.01 and (abs(rec['superluxcore_alpha'] - alpha_expected) < 0.01)
    records.append(rec)
    (folder / 'metrics.json').write_text(json.dumps(records, indent=2) + '\n')
    print(rec, flush=True)
    if os.environ.get('SUPERLUXCORE_AUDIT_BASELINE') != '1':
        assert rec['passed'], rec
print('Add Shader energy checks complete', len(records), sum((r['passed'] for r in records)), flush=True)
