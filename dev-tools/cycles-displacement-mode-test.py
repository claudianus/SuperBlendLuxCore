"""기존 변위 모드·연결 Scale/Midlevel의 표면과 메시 의미를 720p로 검사한다."""
import importlib
import importlib.metadata
import json
import os
from pathlib import Path

import bpy
import numpy as np

package = next(a.module for a in bpy.context.preferences.addons
               if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
final = importlib.import_module(package + '.draw.final')
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-displacement-modes'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
mat = bpy.data.materials.new('기존 변위 모드 검증')
mat.use_nodes = True
plane.data.materials.append(mat)
bpy.ops.object.camera_add(location=(0, 0, 4))
s = bpy.context.scene
s.camera = bpy.context.object
s.camera.data.type = 'ORTHO'
s.camera.data.ortho_scale = 3
s.render.resolution_x = 1280
s.render.resolution_y = 720
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.render.image_settings.color_mode = 'RGBA'
s.view_settings.view_transform = 'Standard'
s.cycles.samples = 16
s.cycles.use_denoising = False
layer = s.view_layers[0]
layer.use_pass_normal = True
layer.use_pass_z = True
cfg = s.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.halt.enable = True
cfg.halt.use_samples = True
cfg.halt.samples = 16
cfg.denoiser.enabled = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False
tree = bpy.data.node_groups.new('기존 변위 컴포지터', 'CompositorNodeTree')
tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
rl = tree.nodes.new('CompositorNodeRLayers')
rl.layer = layer.name
output = tree.nodes.new('NodeGroupOutput')
s.compositing_node_group = tree
s.render.use_compositing = True
captured = {}
original = final.FrameBufferFinal._import_cycles_passes

def inspect(self, source_layer, render_layer, session, engine, scene):
    original(self, source_layer, render_layer, session, engine, scene)
    for name in ('Normal', 'Depth'):
        render_pass = render_layer.passes[name]
        data = np.empty(1280 * 720 * render_pass.channels, dtype=np.float32)
        render_pass.rect.foreach_get(data)
        captured[name] = data.reshape(720, 1280, render_pass.channels).copy()

final.FrameBufferFinal._import_cycles_passes = inspect
records = []
for mode in ('BUMP', 'DISPLACEMENT', 'BOTH'):
    for gradient in (False, True):
        mat.displacement_method = mode
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        material_out = nodes.new('ShaderNodeOutputMaterial')
        diffuse = nodes.new('ShaderNodeBsdfDiffuse')
        links.new(diffuse.outputs[0], material_out.inputs['Surface'])
        displacement = nodes.new('ShaderNodeDisplacement')
        links.new(displacement.outputs[0], material_out.inputs['Displacement'])
        displacement.inputs['Height'].default_value = .8
        for name, value in (('Midlevel', .5), ('Scale', .4)):
            source = nodes.new('ShaderNodeValue')
            source.outputs[0].default_value = value
            links.new(source.outputs[0], displacement.inputs[name])
        if gradient:
            uv = nodes.new('ShaderNodeTexCoord')
            separate = nodes.new('ShaderNodeSeparateXYZ')
            links.new(uv.outputs['UV'], separate.inputs[0])
            links.new(separate.outputs['X'], displacement.inputs['Height'])
        tag = mode + ('_gradient' if gradient else '_constant')
        refs = {}
        s.render.engine = 'CYCLES'
        for name in ('Normal', 'Depth'):
            tree.links.new(rl.outputs[name], output.inputs['Image'])
            path = folder / (tag + '_' + name + '_CYCLES.exr')
            s.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            image = bpy.data.images.load(str(path), check_existing=False)
            refs[name] = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4).copy()
            bpy.data.images.remove(image)
            if name == 'Normal':
                s.render.image_settings.file_format = 'PNG'
                bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
                s.render.image_settings.file_format = 'OPEN_EXR'
        tree.links.new(rl.outputs['Normal'], output.inputs['Image'])
        s.render.engine = 'SUPERLUXCORE'
        log.clear(False)
        path = folder / (tag + '_Normal_SUPERLUXCORE.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        s.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
        # 경계와 배경의 필터 차이를 피하고 중앙의 동일한 표면을 검사한다.
        roi = (slice(260, 460), slice(480, 800))
        record = {'mode': mode, 'gradient': gradient,
                  'spectral': bool(cfg.config.spectral_enable),
                  'native_version': importlib.import_module('pysuperluxcore').Version(),
                  'package_version': importlib.metadata.version('pysuperluxcore'),
                  'warnings': [w.message for w in log.warnings],
                  'errors': [e.message for e in log.errors]}
        for name in ('Normal', 'Depth'):
            data = captured[name]
            np.save(folder / (tag + '_' + name + '_SUPERLUXCORE.npy'), data)
            ref = refs[name][:, :, :data.shape[2]]
            record[name] = {'finite': bool(np.isfinite(data).all()),
                            'mae': float(np.abs(data[roi] - ref[roi]).mean()),
                            'cycles_mean': ref[roi].mean(axis=(0, 1), dtype=np.float64).tolist(),
                            'superluxcore_mean': data[roi].mean(axis=(0, 1), dtype=np.float64).tolist()}
        records.append(record)
        (folder / 'metrics.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
        assert not record['errors'], record
        assert record['Normal']['finite'] and record['Depth']['finite'], record
        assert record['Normal']['mae'] < .012 and record['Depth']['mae'] < .006, record
        assert not any('conversion' in w.lower() for w in record['warnings']), record
        print('변위 모드 검증', record, flush=True)
print('변위 모드 검증 완료', len(records), flush=True)
