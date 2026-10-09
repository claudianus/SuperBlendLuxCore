"""설정 가져오기 없이 투명 필름·모션·물체 제외를 실제 720p 렌더로 확인한다."""
import importlib
import json
import os
from pathlib import Path
import bpy
import numpy as np

package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
settings = importlib.import_module(package + '.export.blender_settings')
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-scene-semantics'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
s = bpy.context.scene
bpy.ops.mesh.primitive_plane_add(size=.7)
obj = bpy.context.object
mat = bpy.data.materials.new('발광 모션 검증')
mat.use_nodes = True
mat.node_tree.nodes.clear()
emission = mat.node_tree.nodes.new('ShaderNodeEmission')
emission.inputs['Color'].default_value = (1., .1, .05, 1.)
output = mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
mat.node_tree.links.new(emission.outputs[0], output.inputs['Surface'])
obj.data.materials.append(mat)
for frame, x in ((1, -1.5), (20, 1.5)):
    obj.location.x = x
    obj.keyframe_insert('location', frame=frame)
bpy.ops.object.camera_add(location=(0, 0, 4))
s.camera = bpy.context.object
s.camera.data.lens = 45
s.frame_set(10)
s.render.resolution_x = 1280
s.render.resolution_y = 720
s.render.resolution_percentage = 100
s.render.film_transparent = True
s.render.motion_blur_shutter = 8.
s.cycles.samples = 32
s.cycles.use_denoising = False
s.view_settings.view_transform = 'Standard'
slc = s.superluxcore
slc.config.engine = 'PATH'
slc.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if slc.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
slc.config.spectral_enable = False
slc.config.path.use_clamping = False
slc.config.path.auto_clamping = False
slc.halt.enable = True
slc.halt.use_samples = True
slc.halt.samples = 32
slc.denoiser.enabled = False
# 원본 카메라와 물체에는 SuperLuxCore의 모션 플래그를 기록하지 않는다.
assert not s.camera.data.superluxcore.motion_blur.is_property_set('enable')
assert not obj.superluxcore.is_property_set('enable_motion_blur')
results = []
for tag, blur, excluded in (('static', False, False), ('blur', True, False), ('excluded', True, True)):
    s.render.use_motion_blur = blur
    obj.cycles.use_motion_blur = not excluded
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        path = folder / f'{tag}_{engine}.exr'
        s.render.image_settings.file_format = 'OPEN_EXR'
        s.render.image_settings.color_mode = 'RGBA'
        s.render.image_settings.color_depth = '32'
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path), check_existing=False)
        pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)
        bpy.data.images.remove(image)
        alpha = pixels[:, :, 3]
        visible = np.any(pixels[:, :, 0] > .02, axis=0)
        columns = np.flatnonzero(visible)
        record = {'case': tag, 'engine': engine, 'span': int(columns[-1] - columns[0]) if columns.size else 0,
                  'finite': bool(np.isfinite(pixels).all()), 'corner_alpha': float(alpha[0, 0]),
                  'max_alpha': float(alpha.max())}
        results.append(record)
        s.render.image_settings.file_format = 'PNG'
        s.render.filepath = str(folder / f'{tag}_{engine}.png')
        bpy.data.images['Render Result'].save_render(s.render.filepath, scene=s)
        print('씬 의미 검증', record, flush=True)
for engine in ('CYCLES', 'SUPERLUXCORE'):
    records = {r['case']: r for r in results if r['engine'] == engine}
    assert all(r['finite'] and r['corner_alpha'] < .001 and r['max_alpha'] > .2 for r in records.values()), engine
    assert records['blur']['span'] > records['static']['span'] + 80, records
    assert abs(records['excluded']['span'] - records['static']['span']) < 10, records
assert not s.camera.data.superluxcore.motion_blur.is_property_set('enable')
assert not obj.superluxcore.is_property_set('enable_motion_blur')
(folder / 'metrics.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print('씬 의미 검증 완료', flush=True)
