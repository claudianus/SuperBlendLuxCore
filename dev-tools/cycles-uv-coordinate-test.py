"""UV 좌표의 정수 타일·음수·경계 값이 절차 그래프에서 보존되는지 검사한다."""
import importlib
import json
import os
from pathlib import Path

import bpy
import numpy as np

package = next(a.module for a in bpy.context.preferences.addons
               if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-uv-coordinates'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
plane.scale.y = 9 / 16
mat = bpy.data.materials.new('UV 원본 좌표 검증')
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
uv_layer = plane.data.uv_layers.active
original_uv = [tuple(item.uv) for item in uv_layer.data]
records = []
checker = os.environ.get('SUPERLUXCORE_AUDIT_CHECKER') == '1'
for source_type in ('ShaderNodeTexCoord', 'ShaderNodeUVMap'):
    for kind in (('tile', 'negative', 'boundary', 'generated', 'object', 'mapping') if checker else ('tile', 'negative', 'boundary')):
        for item, uv in zip(uv_layer.data, original_uv):
            item.uv = ((uv[0] + 2, uv[1] + 3) if kind == 'tile' else
                       (uv[0] - 2, uv[1] - 1) if kind == 'negative' else (1, 1) if kind == 'boundary' else uv)
        plane.data.update()
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        nodes.clear()
        source = nodes.new(source_type)
        if source_type == 'ShaderNodeUVMap':
            source.uv_map = uv_layer.name
        positive = nodes.new('ShaderNodeVectorMath')
        positive.operation = 'ADD'
        positive.inputs[1].default_value = (2, 2, 0)
        links.new(source.outputs['UV'], positive.inputs[0])
        scale = nodes.new('ShaderNodeVectorMath')
        scale.operation = 'SCALE'
        scale.inputs['Scale'].default_value = .125
        links.new(positive.outputs['Vector'], scale.inputs[0])
        emission = nodes.new('ShaderNodeEmission')
        if checker:
            texture = nodes.new('ShaderNodeTexChecker')
            texture.inputs['Color1'].default_value = (.8, .1, .2, 1)
            texture.inputs['Color2'].default_value = (.1, .5, .8, 1)
            coordinate = source.outputs['UV']
            if kind == 'object':
                coordinate = nodes.new('ShaderNodeTexCoord').outputs['Object']
            elif kind == 'mapping':
                for angle, translation in ((.35, (-1.2, .3, .2)), (-.17, (.1, -.2, .3))):
                    mapping = nodes.new('ShaderNodeMapping')
                    mapping.inputs['Location'].default_value = translation
                    mapping.inputs['Rotation'].default_value = (0, 0, angle)
                    mapping.inputs['Scale'].default_value = (1.3, .8, 1)
                    links.new(coordinate, mapping.inputs['Vector'])
                    coordinate = mapping.outputs['Vector']
            if kind != 'generated':
                links.new(coordinate, texture.inputs['Vector'])
            separate = nodes.new('ShaderNodeSeparateXYZ')
            links.new(source.outputs['UV'], separate.inputs[0])
            amount = nodes.new('ShaderNodeMath')
            amount.operation = 'MULTIPLY_ADD'
            amount.inputs[1].default_value = 3
            amount.inputs[2].default_value = 8
            links.new(separate.outputs['X'], amount.inputs[0])
            links.new(amount.outputs[0], texture.inputs['Scale'])
            links.new(texture.outputs[os.environ.get('SUPERLUXCORE_AUDIT_OUTPUT', 'Color')], emission.inputs['Color'])
        else:
            links.new(scale.outputs['Vector'], emission.inputs['Color'])
        out = nodes.new('ShaderNodeOutputMaterial')
        links.new(emission.outputs[0], out.inputs['Surface'])
        tag = source_type + '_' + kind
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
        record = {'source': source_type, 'kind': kind, 'checker': checker,
                  'output': os.environ.get('SUPERLUXCORE_AUDIT_OUTPUT', 'Color'),
                  'native_version': importlib.import_module('pysuperluxcore').Version(),
                  'spectral': bool(cfg.config.spectral_enable),
                  'finite': bool(np.isfinite(pixels['SUPERLUXCORE']).all()),
                  'mae': float(error.mean()), 'p99': float(np.quantile(error, .99)),
                  'errors': [e.message for e in log.errors], 'warnings': [w.message for w in log.warnings]}
        records.append(record)
        (folder / 'metrics.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
        assert record['finite'] and not record['errors'], record
        assert record['mae'] < (.04 if record['spectral'] else .02 if checker else .0015), record
        print('UV 좌표 검증', record, flush=True)
print('UV 좌표 검증 완료', len(records), flush=True)
