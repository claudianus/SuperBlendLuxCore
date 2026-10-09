"""배포 ZIP의 실제 모듈로 기존 Cycles 재질과 기본 스펙트럼을 720p 렌더한다."""
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import time

import bpy
from mathutils import Vector
import numpy as np
import pysuperluxcore

folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-public-bundle-render'))
folder.mkdir(parents=True, exist_ok=True)
expected = os.environ.get('SUPERLUXCORE_EXPECT_VERSION', '2.11.14')
native = Path(pysuperluxcore.pysuperluxcore.__file__).resolve()
profile = Path(os.environ['BLENDER_USER_RESOURCES']).resolve()
assert native.is_relative_to(profile), (native, profile)
assert pysuperluxcore.Version() == expected
assert importlib.metadata.version('pysuperluxcore') == expected
package = next(a.module for a in bpy.context.preferences.addons
               if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
s = bpy.context.scene
for index, (x, metallic, roughness) in enumerate(((-1.25, 0, .32), (0, .8, .2), (1.25, 0, .08))):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=32, radius=.52, location=(x, 0, .56))
    obj = bpy.context.object
    for face in obj.data.polygons:
        face.use_smooth = True
    mat = bpy.data.materials.new('기존 Cycles 재질 ' + str(index))
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    bsdf = nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = (.1, .35, .7, 1)
    bsdf.inputs['Metallic'].default_value = metallic
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Coat Weight'].default_value = .3
    if index == 0:
        texture = nodes.new('ShaderNodeTexVoronoi')
        texture.voronoi_dimensions = '4D'
        texture.inputs['W'].default_value = .41
        texture.inputs['Scale'].default_value = 7
        links.new(texture.outputs['Color'], bsdf.inputs['Base Color'])
    elif index == 2:
        bsdf.inputs['Transmission Weight'].default_value = 1
    obj.data.materials.append(mat)
bpy.ops.mesh.primitive_plane_add(size=20)
mat = bpy.data.materials.new('기존 Cycles 바닥')
mat.use_nodes = True
mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.18, .18, .18, 1)
bpy.context.object.data.materials.append(mat)
for position, power, color, size in (((-3, -4, 5), 800, (1, .85, .7), 3), ((3, 1, 4), 1000, (.65, .8, 1), 2)):
    bpy.ops.object.light_add(type='AREA', location=position)
    obj = bpy.context.object
    obj.rotation_euler = (Vector((0, 0, .5)) - obj.location).to_track_quat('-Z', 'Y').to_euler()
    obj.data.energy = power
    obj.data.color = color
    obj.data.size = size
bpy.ops.object.camera_add(location=(3.5, -6, 3.4))
s.camera = bpy.context.object
s.camera.rotation_euler = (Vector((0, 0, .5)) - s.camera.location).to_track_quat('-Z', 'Y').to_euler()
s.camera.data.lens = 45
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.12, .12, .12, 1)
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .3
s.render.resolution_x = 1280
s.render.resolution_y = 720
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.render.image_settings.color_mode = 'RGBA'
cfg = s.superluxcore
assert cfg.config.spectral_enable, '기본 스펙트럼 설정이 비활성화됨'
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.halt.enable = True
cfg.halt.use_samples = True
cfg.halt.samples = 32
s.render.engine = 'SUPERLUXCORE'
log.clear(False)
s.render.filepath = str(folder / 'render.exr')
start = time.monotonic()
bpy.ops.render.render(write_still=True)
elapsed = time.monotonic() - start
image = bpy.data.images.load(str(folder / 'render.exr'), check_existing=False)
pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)
bpy.data.images.remove(image)
s.render.image_settings.file_format = 'PNG'
s.render.image_settings.color_depth = '8'
bpy.data.images['Render Result'].save_render(str(folder / 'render.png'), scene=s)
record = {'version': pysuperluxcore.Version(), 'native_path': str(native),
          'package_version': importlib.metadata.version('pysuperluxcore'),
          'device': cfg.config.device, 'spectral': bool(cfg.config.spectral_enable),
          'resolution': [1280, 720], 'samples': 32, 'seconds': elapsed,
          'finite': bool(np.isfinite(pixels).all()), 'rgb_mean': pixels[:, :, :3].mean(axis=(0, 1)).tolist(),
          'errors': [e.message for e in log.errors], 'warnings': [w.message for w in log.warnings]}
(folder / 'metrics.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
assert record['finite'] and not record['errors'], record
assert sum(record['rgb_mean']) > .01, record
assert not any('conversion' in w.lower() for w in record['warnings']), record
print('배포 ZIP 720p 렌더 검증 완료', record, flush=True)
