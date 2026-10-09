"""이미지·월드의 입력 색 공간과 별도 알파를 720p 실제 렌더로 확인한다."""
import importlib
import json
import os
from pathlib import Path
import struct
import zlib

import bpy
import numpy as np

package = next(a.module for a in bpy.context.preferences.addons
               if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-image-colorspace'))
folder.mkdir(parents=True, exist_ok=True)

# 뷰 변환과 저장 색 공간이 개입하지 않는 바이트 원본이다.
palette = [(4, 4, 4), (16, 16, 16), (32, 32, 32), (64, 64, 64),
           (128, 128, 128), (200, 200, 200), (90, 128, 110), (130, 100, 90)]
raw = b''.join(b'\x00' + b''.join(bytes((*palette[x // 128], 146))
                                    for x in range(1024)) for y in range(512))
def chunk(kind, data):
    return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
source = folder / 'input.png'
source.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 1024, 512, 8, 6, 0, 0, 0))
                   + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
image = bpy.data.images.load(str(source), check_existing=False)
image.alpha_mode = 'STRAIGHT'

bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
plane.scale.y = 9 / 16
mat = bpy.data.materials.new('입력 색 공간 검증')
mat.use_nodes = True
plane.data.materials.append(mat)
bpy.ops.object.camera_add(location=(0, 0, 4))
s = bpy.context.scene
s.camera = bpy.context.object
s.camera.data.type = 'ORTHO'
s.camera.data.ortho_scale = 2
s.world = bpy.data.worlds.new('입력 월드 색 공간 검증')
s.world.use_nodes = True
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
cases = [('surface', space) for space in ('sRGB', 'Non-Color', 'Linear Rec.709',
                                          'ACEScg', 'ACES2065-1', 'Linear Rec.2020')]
cases += [('surface_alpha', 'sRGB'), ('surface_alpha', 'ACEScg'), ('alpha', 'sRGB'), ('world', 'sRGB'), ('world', 'ACEScg')]
cases += [(kind, space) for kind in ('surface_premul', 'surface_none', 'surface_packed') for space in ('sRGB', 'ACEScg')]
cases += [('alpha_none', 'sRGB')]
cases += [(kind, 'sRGB') for kind in ('surface_group_unused', 'surface_group_alpha', 'surface_dead_alpha')]
selected = set(filter(None, os.environ.get('SUPERLUXCORE_AUDIT_KINDS', '').split(',')))
records = []
for index, (kind, space) in enumerate(cases):
    if selected and kind not in selected:
        continue
    if cfg.config.spectral_enable and (kind.startswith('alpha') or space not in {'sRGB', 'ACEScg'}):
        continue
    plane.hide_render = kind == 'world'
    image.alpha_mode = ('PREMUL' if kind == 'surface_premul' else 'NONE' if kind in {'surface_none', 'alpha_none'}
                        else 'CHANNEL_PACKED' if kind == 'surface_packed' else 'STRAIGHT')
    image.colorspace_settings.name = space
    tree = mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new('ShaderNodeOutputMaterial')
    emission = tree.nodes.new('ShaderNodeEmission')
    texture = tree.nodes.new('ShaderNodeTexImage')
    texture.image = image
    texture.interpolation = 'Closest'
    if kind in {'surface_group_unused', 'surface_group_alpha'}:
        group = bpy.data.node_groups.new('알파 연결 그룹 검증', 'ShaderNodeTree')
        group.interface.new_socket(name='Color', in_out='OUTPUT', socket_type='NodeSocketColor')
        group.interface.new_socket(name='Alpha', in_out='OUTPUT', socket_type='NodeSocketFloat')
        group_output = group.nodes.new('NodeGroupOutput')
        child_image = group.nodes.new('ShaderNodeTexImage')
        child_image.image = image
        child_image.interpolation = 'Closest'
        group.links.new(child_image.outputs['Color'], group_output.inputs['Color'])
        group.links.new(child_image.outputs['Alpha'], group_output.inputs['Alpha'])
        tree.nodes.remove(texture)
        texture = tree.nodes.new('ShaderNodeGroup')
        texture.node_tree = group
    if kind == 'surface_dead_alpha':
        unused = tree.nodes.new('ShaderNodeMath')
        tree.links.new(texture.outputs['Alpha'], unused.inputs[0])
    tree.links.new(texture.outputs['Alpha' if kind.startswith('alpha') else 'Color'], emission.inputs['Color'])
    if kind in {'surface_alpha', 'surface_premul', 'surface_none', 'surface_packed', 'surface_group_alpha'}:
        # 알파를 실제 최종 경로에 연결하여 Color의 비결합 분기를 활성화한다.
        amount = tree.nodes.new('ShaderNodeMath')
        amount.operation = 'ADD'
        amount.inputs[1].default_value = 1 - 146 / 255
        tree.links.new(texture.outputs['Alpha'], amount.inputs[0])
        tree.links.new(amount.outputs[0], emission.inputs['Strength'])
    tree.links.new(emission.outputs[0], out.inputs['Surface'])
    world = s.world.node_tree
    world.nodes.clear()
    background = world.nodes.new('ShaderNodeBackground')
    background.inputs['Color'].default_value = (0, 0, 0, 1)
    world_out = world.nodes.new('ShaderNodeOutputWorld')
    world.links.new(background.outputs[0], world_out.inputs['Surface'])
    if kind == 'world':
        env = world.nodes.new('ShaderNodeTexEnvironment')
        env.image = image
        env.interpolation = 'Closest'
        world.links.new(env.outputs['Color'], background.inputs['Color'])
        s.camera.data.type = 'PERSP'
        s.camera.data.lens = 12
    else:
        s.camera.data.type = 'ORTHO'
    tag = f'{index:02d}_{kind}_{space.replace(" ", "_")}'
    pixels = {}
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        log.clear(False)
        path = folder / (tag + '_' + engine + '.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        output = bpy.data.images.load(str(path), check_existing=False)
        pixels[engine] = np.asarray(output.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[8:-8, 8:-8, :3].copy()
        bpy.data.images.remove(output)
        s.render.image_settings.file_format = 'PNG'
        s.render.image_settings.color_depth = '8'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
        s.render.image_settings.color_depth = '32'
    error = np.abs(pixels['CYCLES'] - pixels['SUPERLUXCORE'])
    record = {'kind': kind, 'space': space, 'spectral': bool(cfg.config.spectral_enable),
              'finite': bool(np.isfinite(pixels['SUPERLUXCORE']).all()),
              'mae': float(error.mean()), 'p99': float(np.quantile(error, .99)),
              'cycles_mean': pixels['CYCLES'].mean(axis=(0, 1), dtype=np.float64).tolist(),
              'superluxcore_mean': pixels['SUPERLUXCORE'].mean(axis=(0, 1), dtype=np.float64).tolist(),
              'warnings': [w.message for w in log.warnings], 'errors': [e.message for e in log.errors]}
    records.append(record)
    (folder / 'metrics.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
    assert record['finite'] and not record['errors'], record
    assert not any('conversion' in w.lower() or '색 공간' in w for w in record['warnings']), record
    limit = .04 if record['spectral'] else .004
    assert record['mae'] < limit, record
    if kind.startswith('alpha'):
        expected_alpha = 1. if kind == 'alpha_none' else 146 / 255
        assert np.max(np.abs(pixels['SUPERLUXCORE'] - expected_alpha)) < .002, record
    print('이미지 색 공간 검증', record, flush=True)
print('이미지 색 공간 검증 완료', len(records), flush=True)
