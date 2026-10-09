"""월드를 카메라에서 숨겨도 조명과 원래 필름 알파를 보존하는지 검사한다."""
import bpy
import importlib
import json
import os
from pathlib import Path
import numpy as np
package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-world-visibility'))
folder.mkdir(parents=True, exist_ok=True)
s = bpy.context.scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=.75)
obj = bpy.context.object
mat = bpy.data.materials.new('월드 조명 검증')
mat.use_nodes = True
mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (.8, .8, .8, 1.)
mat.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value = 1.
obj.data.materials.append(mat)
bpy.ops.object.camera_add(location=(0, 0, 4))
s.camera = bpy.context.object
s.world = bpy.data.worlds.new('카메라 가시성과 조명')
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.1, .4, .05, 1.)
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.
s.render.resolution_x = 1280
s.render.resolution_y = 720
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_mode = 'RGBA'
s.render.image_settings.color_depth = '32'
s.view_settings.view_transform = 'Standard'
s.cycles.samples = 32
s.cycles.use_denoising = False
cfg = s.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.config.spectral_enable = False
cfg.halt.enable = True
cfg.halt.use_samples = True
cfg.halt.samples = 32
cfg.denoiser.enabled = False
records = []
for tag, visible, film in (('visible', True, False), ('hidden', False, False), ('transparent', True, True)):
    s.world.cycles_visibility.camera = visible
    s.render.film_transparent = film
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        path = folder / (tag + '_' + engine + '.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path), check_existing=False)
        pix = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)
        bpy.data.images.remove(image)
        background = pix[5:30, 5:30].mean(axis=(0, 1), dtype=np.float64)
        center = pix[320:400, 600:680, :3].mean(axis=(0, 1), dtype=np.float64)
        record = {'case': tag, 'engine': engine, 'finite': bool(np.isfinite(pix).all()),
                  'background': background.tolist(), 'illuminated_center': center.tolist()}
        records.append(record)
        expected = (.1, .4, .05, 1.) if tag == 'visible' else (0., 0., 0., 1. if tag == 'hidden' else 0.)
        assert record['finite'] and np.max(np.abs(background - expected)) < .002, record
        assert center.max() > .05, record
        s.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
for engine in ('CYCLES', 'SUPERLUXCORE'):
    values = {r['case']: np.asarray(r['illuminated_center']) for r in records if r['engine'] == engine}
    assert np.max(np.abs(values['hidden'] - values['visible'])) < .03, values
assert not s.camera.data.superluxcore.imagepipeline.is_property_set('transparent_film')
(folder / 'metrics.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
print('월드 가시성 검증 완료', json.dumps(records, ensure_ascii=False), flush=True)
