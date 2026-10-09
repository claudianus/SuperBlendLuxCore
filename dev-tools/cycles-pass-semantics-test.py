"""기존 Render Layers 연결과 데이터 패스의 단위·인덱스를 720p에서 검사한다."""
import importlib
import json
import os
from pathlib import Path
import bpy
import numpy as np

package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
module = importlib.import_module(package + '.draw.final')
passes = importlib.import_module(package + '.export.cycles_passes')
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-pass-semantics'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
s = bpy.context.scene
bpy.ops.mesh.primitive_plane_add(size=2.5, rotation=(.2, .4, .1))
obj = bpy.context.object
obj.pass_index = 7
mat = bpy.data.materials.new('패스 의미 검증')
mat.use_nodes = True
mat.pass_index = 13
mat.node_tree.nodes.clear()
e = mat.node_tree.nodes.new('ShaderNodeEmission')
e.inputs['Color'].default_value = (.2, .4, .8, 1.)
out = mat.node_tree.nodes.new('ShaderNodeOutputMaterial')
mat.node_tree.links.new(e.outputs[0], out.inputs['Surface'])
obj.data.materials.append(mat)
bpy.ops.object.camera_add(location=(0, 0, 4))
s.camera = bpy.context.object
s.camera.data.lens = 35
if os.environ.get("SUPERLUXCORE_AUDIT_CAMERA") == "ORTHO":
    s.camera.data.type = "ORTHO"
    s.camera.data.ortho_scale = 5.
s.render.resolution_x = 1280
s.render.resolution_y = 720
s.render.resolution_percentage = 100
s.cycles.samples = 16
s.cycles.use_denoising = False
s.view_settings.view_transform = 'Standard'
s.world.mist_settings.start = 3
s.world.mist_settings.depth = 2
s.world.mist_settings.falloff = 'LINEAR'
layer = s.view_layers[0]
for item in passes.PASSES:
    setattr(layer, item.flag, True)
slc = s.superluxcore
slc.config.engine = 'PATH'
slc.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if slc.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
slc.config.spectral_enable = False
slc.config.path.use_clamping = False
slc.config.path.auto_clamping = False
slc.config.sobol_adaptive_strength = 0
slc.halt.enable = True
slc.halt.use_samples = True
slc.halt.samples = 16
slc.denoiser.enabled = False
# Blender 5.2의 기존 컴포지터 그룹을 한 번 만들고 엔진 교체 후에도 유지한다.
tree = bpy.data.node_groups.new('기존 패스 컴포지터', 'CompositorNodeTree')
tree.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
rl = tree.nodes.new('CompositorNodeRLayers')
rl.layer = layer.name
output = tree.nodes.new('NodeGroupOutput')
s.compositing_node_group = tree
s.render.use_compositing = True
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.render.image_settings.color_mode = 'RGBA'

captured = {}
original = module.FrameBufferFinal._import_cycles_passes

def inspect(self, source_layer, render_layer, session, engine, scene):
    original(self, source_layer, render_layer, session, engine, scene)
    for item in passes.enabled(source_layer):
        render_pass = render_layer.passes[item.name]
        buf = np.empty(1280 * 720 * render_pass.channels, dtype=np.float32)
        render_pass.rect.foreach_get(buf)
        captured[item.name] = buf.reshape(720, 1280, render_pass.channels).copy()
module.FrameBufferFinal._import_cycles_passes = inspect

# 컴포지터 출력에서 Cycles의 원본 패스 데이터를 읽는다.
references = {}
s.render.engine = 'CYCLES'
for item in passes.enabled(layer):
    socket = rl.outputs.get({"IndexOB": "Object Index", "IndexMA": "Material Index", "Emit": "Emission"}.get(item.name, item.name))
    assert socket is not None, (item.name, [x.name for x in rl.outputs])
    tree.links.new(socket, output.inputs['Image'])
    path = folder / f'{item.name}_CYCLES.exr'
    s.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if item.name == "Normal":
        s.render.image_settings.file_format = "PNG"
        bpy.data.images["Render Result"].save_render(str(folder / "Normal_CYCLES.png"), scene=s)
        s.render.image_settings.file_format = "OPEN_EXR"
    image = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)
    bpy.data.images.remove(image)
    references[item.name] = pixels
# 컴포지터의 Normal 연결을 유지한 채 엔진만 교체한다.
tree.links.new(rl.outputs['Normal'], output.inputs['Image'])
s.render.engine = 'SUPERLUXCORE'
path = folder / 'Normal_SUPERLUXCORE.exr'
s.render.filepath = str(path)
bpy.ops.render.render(write_still=True)
s.render.image_settings.file_format = 'PNG'
bpy.data.images['Render Result'].save_render(str(folder / 'Normal_SUPERLUXCORE.png'), scene=s)
s.render.image_settings.file_format = 'OPEN_EXR'
image = bpy.data.images.load(str(path), check_existing=False)
composite = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)
bpy.data.images.remove(image)
assert set(captured) == {p.name for p in passes.enabled(layer)}, captured.keys()
mask = (captured['IndexOB'][:, :, 0] == 7)
# 안쪽 픽셀에서 기하·데이터의 의미를 비교하며 경계의 필터 차이는 분리한다.
inside = mask.copy()
for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
    for step in range(1, 6):
        inside &= np.roll(mask, (dy * step, dx * step), (0, 1))
inside &= references["Depth"][:, :, 0] < 100.
metrics = []
for name, buf in captured.items():
    np.save(folder / f'{name}_SUPERLUXCORE.npy', buf)
    ref = references[name][:, :, :buf.shape[2]]
    # 단일 값 패스는 컴포지터에서 RGB로 확장되므로 첫 채널로 비교한다.
    error = np.abs(buf[inside] - ref[inside])
    metrics.append({'pass': name, 'finite': bool(np.isfinite(buf).all()),
                    'inside_mean': buf[inside].mean(axis=0).tolist(),
                    'cycles_inside_mean': ref[inside].mean(axis=0).tolist(),
                    'mae': float(error.mean()), 'p99': float(np.quantile(error, .99))})
    assert np.isfinite(buf).all(), name
assert captured['Depth'][inside].mean() > 3.5
assert np.all(captured['IndexOB'][inside] == 7)
assert np.all(captured['IndexMA'][inside] == 13)
assert np.all(captured['UV'][inside, 2] == 1)
assert np.mean(np.abs(composite[inside, :3] - captured['Normal'][inside])) < .002
(folder / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
for entry in metrics:
    assert entry['mae'] < .03, entry
assert not layer.superluxcore.aovs.is_property_set('depth')
assert not layer.superluxcore.aovs.is_property_set('object_id')
(folder / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
print('패스 의미 검증 완료', json.dumps(metrics, ensure_ascii=False), flush=True)
