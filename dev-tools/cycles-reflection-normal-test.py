"""No-edit Principled lobe normals and per-material reflection guard, 720p."""
import bpy, importlib, importlib.metadata, os, json, hashlib
from pathlib import Path
from mathutils import Vector
import numpy as np
import pysuperluxcore as native
assert native.Version() == os.environ.get('SUPERLUXCORE_EXPECT_VERSION', '2.11.21')
assert native.Version() == importlib.metadata.version('pysuperluxcore')
assert Path(native.pysuperluxcore.__file__).resolve().is_relative_to(Path(os.environ['BLENDER_USER_RESOURCES']).resolve())
folder = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
folder.mkdir(parents=True, exist_ok=True)
package = next((a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore')))
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=12)
plane = bpy.context.object
material = bpy.data.materials.new('Original Cycles per-material reflection correction')
material.use_nodes = True
plane.data.materials.append(material)
if hasattr(material, 'use_backface_culling_lightprobe_volume'):
    material.use_backface_culling_lightprobe_volume = False
bpy.ops.object.camera_add(location=(-3, 0, 1.5))
s = bpy.context.scene
s.camera = bpy.context.object
s.camera.rotation_euler = (-s.camera.location).to_track_quat('-Z', 'Y').to_euler()
s.camera.data.type = 'ORTHO'
s.camera.data.ortho_scale = 2
s.render.resolution_x, s.render.resolution_y = (1280, 720)
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.render.image_settings.color_mode = 'RGBA'
s.view_settings.view_transform = 'Standard'
s.cycles.samples = 64
s.cycles.use_denoising = False
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Color'].default_value = (1, 1, 1, 1)
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1
cfg = s.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.config.sampler = 'SOBOL'
cfg.config.sampler_gpu = 'SOBOL'
cfg.config.spectral_enable = True
cfg.halt.enable = cfg.halt.use_samples = True
cfg.halt.samples = 128
cfg.halt.use_noise_level = False
cfg.halt.use_noise_thresh = False
if os.environ.get('SUPERLUXCORE_AUDIT_BIDIR') == '1':
    cfg.config.engine = 'BIDIR'
cfg.config.shadow_terminator = os.environ.get('SUPERLUXCORE_AUDIT_TERMINATOR', 'CHIANG')
cfg.denoiser.enabled = False
cfg.config.path.use_clamping = False
cfg.config.path.auto_clamping = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False
assert hasattr(material.cycles, 'use_bump_map_correction')
records = []
cases = {
    'metal_corrected': dict(metal=1),
    'metal_uncorrected': dict(metal=1, guard=False),
    'principled_diffuse': dict(spec=0),
    'diffuse_uncorrected': dict(spec=0, guard=False),
    'rough_diffuse': dict(spec=0, diffuse_roughness=0.7),
    'mixed_corrected': dict(),
    'metal_flat': dict(metal=1, mapped=False),
    'grazing_shading_normal': dict(metal=1, normal=(0.8, 0, 0.6), camera=(-3, 0, 4)),
    'coat_flat_on_tilted': dict(spec=0, color=0, coat=(0, 0, 1)),
    'coat_tilted_on_flat': dict(spec=0, color=0, mapped=False, coat=(0.97, 0, 0.243)),
    'coat_tilted_uncorrected': dict(spec=0, color=0, mapped=False, coat=(0.97, 0, 0.243), guard=False),
    'coat_bump': dict(spec=0, color=0, mapped=False, coat='BUMP'),
    'backface_metal': dict(metal=1, backface=True),
    'backface_diffuse': dict(spec=0, backface=True),
    'backface_diffuse_uncorrected': dict(spec=0, backface=True, guard=False),
    'anisotropic_metal': dict(metal=1, mapped=False, aniso=0.8),
    'mixed_transmission': dict(transmission=0.5),
    'mix_independent_normals': dict(metal=1, mix=True),
    'backface_flat_metal': dict(metal=1, mapped=False, backface=True),
    'backface_flat_diffuse': dict(spec=0, mapped=False, backface=True),
    'backface_flat_dielectric': dict(mapped=False, backface=True),
    'zero_normal': dict(metal=1, normal=(0, 0, 0)),
    'zero_coat_normal': dict(spec=0, color=0, mapped=False, coat=(0, 0, 0)),
    'flat_transmission': dict(mapped=False, transmission=1),
    'mapped_transmission': dict(transmission=1),
}
selected = os.environ.get('SUPERLUXCORE_AUDIT_CASES')
if selected:
    cases = {key: cases[key] for key in selected.split(',')}
for condition, case in cases.items():
    metal = case.get('metal', 0)
    spec = case.get('spec', 0.5)
    guard = case.get('guard', True)
    mapped = case.get('mapped', True)
    s.camera.location = case.get('camera', (-3, 0, -1.5 if case.get('backface') else 1.5))
    s.camera.rotation_euler = (-s.camera.location).to_track_quat('-Z', 'Y').to_euler()
    n, l = (material.node_tree.nodes, material.node_tree.links)
    n.clear()
    bsdf = n.new('ShaderNodeBsdfPrincipled')
    color = case.get('color', 1)
    bsdf.inputs['Base Color'].default_value = (color, color, color, 1)
    bsdf.inputs['Metallic'].default_value = metal
    bsdf.inputs['Specular IOR Level'].default_value = spec
    bsdf.inputs['Roughness'].default_value = 0.2
    bsdf.inputs['Coat Weight'].default_value = 0
    bsdf.inputs['Diffuse Roughness'].default_value = case.get('diffuse_roughness', 0)
    bsdf.inputs['Anisotropic'].default_value = case.get('aniso', 0)
    bsdf.inputs['Transmission Weight'].default_value = case.get('transmission', 0)
    if mapped:
        normal = n.new('ShaderNodeCombineXYZ')
        direction = case.get('normal', (0.97, 0, 0.243))
        for axis, value in zip(('X', 'Y', 'Z'), direction):
            normal.inputs[axis].default_value = value
        l.new(normal.outputs[0], bsdf.inputs['Normal'])
    if 'coat' in case:
        bsdf.inputs['Coat Weight'].default_value = 1
        bsdf.inputs['Coat Roughness'].default_value = 0.2
        if case['coat'] == 'BUMP':
            tex = n.new('ShaderNodeTexNoise')
            tex.inputs['Scale'].default_value = 3
            normal = n.new('ShaderNodeBump')
            normal.inputs['Distance'].default_value = 0.02
            l.new(tex.outputs['Fac'], normal.inputs['Height'])
            coat_output = normal.outputs['Normal']
        else:
            normal = n.new('ShaderNodeCombineXYZ')
            for axis, value in zip(('X', 'Y', 'Z'), case['coat']):
                normal.inputs[axis].default_value = value
            coat_output = normal.outputs[0]
        l.new(coat_output, bsdf.inputs['Coat Normal'])
    shader_output = bsdf.outputs[0]
    if case.get('mix'):
        second = n.new('ShaderNodeBsdfPrincipled')
        second.inputs['Base Color'].default_value = (1, 1, 1, 1)
        second.inputs['Specular IOR Level'].default_value = 0
        mix = n.new('ShaderNodeMixShader')
        mix.inputs[0].default_value = 0.3
        l.new(shader_output, mix.inputs[1])
        l.new(second.outputs[0], mix.inputs[2])
        shader_output = mix.outputs[0]
    out = n.new('ShaderNodeOutputMaterial')
    l.new(shader_output, out.inputs['Surface'])
    material.cycles.use_bump_map_correction = guard
    signature = [(link.from_node.name, link.from_socket.name, link.to_node.name, link.to_socket.name) for link in l]
    pixels = {}
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        log.clear(False)
        path = folder / (condition + '_' + engine + '.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path), check_existing=False)
        pixels[engine] = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[16:-16, 16:-16, :3].copy()
        bpy.data.images.remove(image)
        s.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
    assert signature == [(link.from_node.name, link.from_socket.name, link.to_node.name, link.to_socket.name) for link in l]
    assert material.cycles.use_bump_map_correction == guard
    record = {'condition': condition, 'version': native.Version(), 'native_sha256': hashlib.sha256(Path(native.pysuperluxcore.__file__).read_bytes()).hexdigest(), 'device': cfg.config.device, 'spectral': True, 'cycles_samples': s.cycles.samples, 'native_samples': cfg.halt.samples, 'native_engine': cfg.config.engine, 'terminator': cfg.config.shadow_terminator, 'blender_build_hash': bpy.app.build_hash.decode(), 'cycles_mean': float(pixels['CYCLES'].mean()), 'native_mean': float(pixels['SUPERLUXCORE'].mean()), 'cycles_black_fraction': float((pixels['CYCLES'].mean(axis=2) < 0.001).mean()), 'native_black_fraction': float((pixels['SUPERLUXCORE'].mean(axis=2) < 0.001).mean()), 'finite': bool(np.isfinite(pixels['SUPERLUXCORE']).all()), 'errors': [e.message for e in log.errors], 'warnings': [e.message for e in log.warnings]}
    # Normal behavior plus scoped mean-energy gates. Transmission remains a separate open audit.
    record['passed'] = record['finite'] and (not record['errors']) and (not record['warnings'])
    if condition in {'metal_uncorrected', 'coat_tilted_uncorrected'}:
        record['passed'] &= record['cycles_mean'] < 0.001 and record['native_mean'] < 0.001
    elif condition in {'backface_diffuse', 'backface_metal', 'backface_diffuse_uncorrected'} and record['cycles_mean'] < 0.001:
        record['passed'] &= record['native_mean'] < 0.001
    elif condition not in {'metal_flat', 'anisotropic_metal', 'mixed_transmission'}:
        record['passed'] &= record['cycles_mean'] > 0.01 and record['native_mean'] > 0.01 and (record['native_black_fraction'] < 0.1)
    elif condition in {'metal_flat', 'anisotropic_metal'}:
        record['passed'] &= abs(record['native_mean'] - record['cycles_mean']) < 0.025
    else:
        record['passed'] &= 0.01 < record['native_mean'] < 1.5
    energy_conditions = {'metal_corrected', 'principled_diffuse', 'rough_diffuse',
                         'mixed_corrected', 'grazing_shading_normal',
                         'coat_flat_on_tilted', 'coat_tilted_on_flat', 'coat_bump',
                         'mix_independent_normals', 'zero_normal', 'zero_coat_normal'}
    record['mean_energy_checked'] = condition in energy_conditions
    if record['mean_energy_checked']:
        record['relative_mean_error'] = abs(record['native_mean'] / record['cycles_mean'] - 1)
        record['mean_energy_tolerance'] = 0.025
        record['passed'] &= record['relative_mean_error'] < record['mean_energy_tolerance']
    records.append(record)
    (folder / 'metrics.json').write_text(json.dumps(records, indent=2) + '\n')
    print('REFLECTION_NORMAL_AUDIT', record, flush=True)
    assert record['passed'], record
print('Reflection-normal conditions passed', len(records), flush=True)
