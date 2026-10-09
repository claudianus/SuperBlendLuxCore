"""흡수·산란 합성과 흑체 발광의 실제 720p 영상을 보존한다."""
import importlib
import json
import os
from pathlib import Path
import bpy
import numpy as np

package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-volume-semantics'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
s = bpy.context.scene
s.world = bpy.data.worlds.new('검은 월드')
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
mat = bpy.data.materials.new('볼륨 의미 검증')
mat.use_nodes = True
obj.data.materials.append(mat)
bpy.ops.object.camera_add(location=(0, -5, 1))
s.camera = bpy.context.object
s.camera.rotation_euler = (-s.camera.location).to_track_quat('-Z', 'Y').to_euler()
bpy.ops.object.light_add(type='AREA', location=(0, -2, 3))
light = bpy.context.object
light.rotation_euler = (-light.location).to_track_quat('-Z', 'Y').to_euler()
light.data.energy = 1000
light.data.shape = 'DISK'
light.data.size = 2
s.render.resolution_x = 1280
s.render.resolution_y = 720
s.render.resolution_percentage = 100
s.cycles.samples = 32
s.cycles.use_denoising = False
s.view_settings.view_transform = 'Standard'
slc = s.superluxcore
slc.config.engine = 'PATH'
slc.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if slc.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
# 제품의 기본 스펙트럼 모드에서 동작한다.
assert slc.config.spectral_enable
slc.halt.enable = True
slc.halt.use_samples = True
slc.halt.samples = 32
slc.denoiser.enabled = False
slc.config.path.use_clamping = False
slc.config.path.auto_clamping = False
results = []
for kind in ('absorb_scatter_add', 'principled_blackbody'):
    tree = mat.node_tree
    tree.nodes.clear()
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    if kind == 'absorb_scatter_add':
        absorption = tree.nodes.new('ShaderNodeVolumeAbsorption')
        absorption.inputs['Color'].default_value = (.3, .7, .4, 1)
        absorption.inputs['Density'].default_value = .8
        scatter = tree.nodes.new('ShaderNodeVolumeScatter')
        scatter.inputs['Density'].default_value = .8
        add = tree.nodes.new('ShaderNodeAddShader')
        tree.links.new(absorption.outputs[0], add.inputs[0])
        tree.links.new(scatter.outputs[0], add.inputs[1])
        source = add.outputs[0]
    else:
        volume = tree.nodes.new('ShaderNodeVolumePrincipled')
        volume.inputs['Density'].default_value = .1
        volume.inputs['Blackbody Intensity'].default_value = 1
        volume.inputs['Temperature'].default_value = 2500
        source = volume.outputs[0]
        light.data.energy = 0
    tree.links.new(source, output.inputs['Volume'])
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        s.render.image_settings.file_format = 'OPEN_EXR'
        s.render.image_settings.color_depth = '32'
        s.render.filepath = str(folder / f'{kind}_{engine}.exr')
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(s.render.filepath, check_existing=False)
        pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[:, :, :3]
        bpy.data.images.remove(image)
        assert np.isfinite(pixels).all() and pixels.max() > .01, (kind, engine)
        results.append({'case': kind, 'engine': engine, 'finite': True, 'mean': pixels.mean(axis=(0, 1), dtype=np.float64).tolist(), 'max': float(pixels.max()), 'spectral': slc.config.spectral_enable if engine == 'SUPERLUXCORE' else False})
        s.render.image_settings.file_format = 'PNG'
        s.render.filepath = str(folder / f'{kind}_{engine}.png')
        bpy.data.images['Render Result'].save_render(s.render.filepath, scene=s)
(folder / 'metrics.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print('볼륨 의미 검증 완료', results, flush=True)
