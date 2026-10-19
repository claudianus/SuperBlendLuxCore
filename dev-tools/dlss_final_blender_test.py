"""Exercise actual stock-Blender F12/animation and native NGX final delivery.

Run in an isolated development profile. Hooks only observe real render passes,
native film and SDK calls; the paired control selects the same coherent sampler.
This fixed opaque diffuse fixture is not general material or motion support.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import weakref

import bpy
from mathutils import Vector
import numpy as np

PROFILE = Path(os.environ['BLENDER_USER_RESOURCES']).resolve()
sys.path.insert(0, str(PROFILE / 'extensions/.local/lib/python3.13/site-packages'))
PACKAGE = 'bl_ext.user_default.superluxcore'
# Fail before enabling/downloading anything if Blender initialized another repo.
repository = next((repo for repo in bpy.context.preferences.extensions.repos if repo.module == 'user_default'), None)
assert repository is not None and Path(repository.directory).resolve().is_relative_to(PROFILE), (repository.directory if repository else None, PROFILE)
bpy.ops.preferences.addon_enable(module=PACKAGE)
addon = importlib.import_module(PACKAGE)
assert Path(addon.__file__).resolve().is_relative_to(PROFILE)
import pysuperluxcore as slc

OUT = Path(os.environ['SLC_DLSS_FINAL_OUT'])
OUT.mkdir(parents=True, exist_ok=True)
SIZE = tuple(map(int, os.environ.get('SLC_DLSS_FINAL_SIZE', '320,180').split(',')))
SAMPLES = int(os.environ.get('SLC_DLSS_FINAL_SAMPLES', '4'))
MODE = os.environ.get('SLC_DLSS_FINAL_MODE', 'still')
DEVICE = os.environ.get('SLC_DLSS_FINAL_DEVICE', 'CUDA_GPU')
native = Path(slc.pysuperluxcore.__file__).resolve()
assert native.is_relative_to(PROFILE)
preferences = bpy.context.preferences.addons[PACKAGE].preferences
preferences.gpu_backend = 'METAL' if DEVICE == 'METAL_GPU' else 'CUDA'
preferences.dlss_library = os.environ['SLC_DLSS_TEST_LIBRARY']
preferences.dlss_runtime = os.environ['SLC_DLSS_TEST_RUNTIME']
final_dlss = importlib.import_module(PACKAGE + '.engine.dlss_final')
dlss = importlib.import_module(PACKAGE + '.engine.dlss')
config = importlib.import_module(PACKAGE + '.export.config')
halt_export = importlib.import_module(PACKAGE + '.export.halt')
framebuffer = importlib.import_module(PACKAGE + '.draw.final').FrameBufferFinal
display = importlib.import_module(PACKAGE + '.properties.display').SuperLuxCoreDisplaySettings

scene = bpy.context.scene
KEEP_SCENE = os.environ.get('SLC_DLSS_KEEP_SCENE') == '1'
if KEEP_SCENE:
    assert MODE in ('still', 'raw-reference', 'dlss-only'), 'Original scene must not be animated/edited by a fixture mode'
    assert scene.camera is not None
else:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)


    def matte(name, color):
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        tree = material.node_tree
        tree.nodes.clear()
        surface = tree.nodes.new('ShaderNodeBsdfDiffuse')
        surface.inputs['Color'].default_value = (*color, 1.)
        surface.inputs['Roughness'].default_value = 0.
        output = tree.nodes.new('ShaderNodeOutputMaterial')
        tree.links.new(surface.outputs['BSDF'], output.inputs['Surface'])
        return material


    bpy.ops.mesh.primitive_plane_add(size=100)
    floor = bpy.context.object
    floor.data.materials.append(matte('Floor', (.35, .35, .35)))
    floor.pass_index = 1
    for index, (x, color) in enumerate(((-1.1, (.65, .12, .06)), (1.1, (.06, .25, .65)))):
        bpy.ops.mesh.primitive_cube_add(size=1.5, location=(x, 0, .75))
        obj = bpy.context.object
        obj.data.materials.append(matte('Diffuse ' + str(index), color))
        obj.pass_index = index + 2
        if index == 0:
            animated = obj
    bpy.ops.object.light_add(type='AREA', location=(-3, -4, 6))
    light = bpy.context.object
    light.rotation_euler = (Vector((0, 0, .5)) - light.location).to_track_quat('-Z', 'Y').to_euler()
    light.data.energy = 1500
    light.data.size = 4
    bpy.ops.object.camera_add(location=(7, -10, 7))
    scene.camera = bpy.context.object
    scene.camera.rotation_euler = (Vector((0, 0, .7)) - scene.camera.location).to_track_quat('-Z', 'Y').to_euler()
    scene.camera.data.lens = 50
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (.15, .15, .15, 1.)
    scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = .2
scene.render.engine = 'SUPERLUXCORE'
scene.render.resolution_x, scene.render.resolution_y = SIZE
scene.render.resolution_percentage = 100
scene.render.use_compositing = False
scene.render.film_transparent = False
scene.view_settings.view_transform = 'ACES 2.0'
scene.view_settings.look = 'None'
settings = scene.superluxcore
settings.config.engine = 'PATH'
settings.config.device = 'CPU' if DEVICE == 'CPU' else 'OCL'
settings.config.use_tiles = True
settings.config.tile.path_sampling_aa_size = 1
settings.config.spectral_enable = False
settings.config.seed = 131
settings.config.use_animated_seed = False
settings.config.filter_enabled = False
settings.config.path.auto_clamping = False
settings.config.path.use_clamping = False
settings.config.path.hybridbackforward_enable = False
settings.config.path.vertex_connection = False
settings.config.mnee_enable = False
settings.config.guiding_enable = False
settings.config.photongi.enabled = False
settings.config.path.depth_total = 6
settings.config.path.depth_diffuse = 6
settings.config.path.depth_glossy = 6
settings.config.path.depth_specular = 6
settings.devices.use_native_cpu = False
settings.devices.init_devices(slc.GetOpenCLDeviceDescs())
for device in settings.devices.devices:
    device.enabled = device.type == DEVICE
settings.halt.enable = True
settings.halt.use_samples = True
settings.halt.samples = SAMPLES
settings.halt.use_noise_level = False
settings.halt.use_noise_thresh = False
settings.halt.use_time = False
settings.denoiser.periodic_refresh = False
settings.denoiser.to_combined = True
settings.denoiser.temporal_enabled = False
settings.denoiser.dlss_preset = os.environ.get('SLC_DLSS_TEST_PRESET', 'DEFAULT')
settings.denoiser.dlss_input_reduction = os.environ.get('SLC_DLSS_FINAL_INPUT_REDUCTION', '1')
tonemapper = scene.camera.data.superluxcore.imagepipeline.tonemapper
tonemapper.type = 'TONEMAP_LINEAR'
tonemapper.use_autolinear = False
tonemapper.linear_scale = 1.
layer = scene.view_layers[0]
layer.superluxcore.halt.enable = False
for name in ('rgb', 'alpha', 'albedo', 'avg_shading_normal', 'depth', 'position',
             'samplecount', 'direct_diffuse', 'emission', 'object_id'):
    setattr(layer.superluxcore.aovs, name, True)
layer.use_pass_z = True
layer.use_pass_normal = True
layer.use_pass_object_index = True

state = {'label': '', 'control': False, 'stopped': False, 'captures': [], 'sdk': [], 'closed': [],
         'validation_seconds': 0., 'render_timings': [], 'pause_seen': False}
final_engine = importlib.import_module(PACKAGE + '.engine.final')
original_free_memory = final_engine._release_evaluated_scene
def current_rss():
    stat = Path('/proc/self/statm')
    return int(stat.read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE') if stat.exists() else None
def freed_blender_memory(self):
    before = current_rss()
    persistent = scene.render.use_persistent_data
    original = scene.as_pointer()
    result = original_free_memory(self)
    assert scene.as_pointer() == original and scene.camera is not None
    row = {'label': state['label'], 'blender_frame': scene.frame_current,
           'before_rss': before, 'after_rss': current_rss(),
           'persistent_data_requested': persistent, 'original_scene_valid': True}
    state.setdefault('blender_memory_release', []).append(row)
    print('BLENDER_MEMORY_RELEASE ' + json.dumps(row), flush=True)
    return result
final_engine._release_evaluated_scene = freed_blender_memory
native_channels = {'RGB': 3, 'ALPHA': 1, 'ALBEDO': 3, 'AVG_SHADING_NORMAL': 3,
                   'DEPTH': 1, 'POSITION': 3, 'SAMPLECOUNT': 1,
                   'DIRECT_DIFFUSE': 3, 'EMISSION': 3, 'OBJECT_ID': 1}


def pass_pixels(render_pass):
    values = np.empty(SIZE[0] * SIZE[1] * render_pass.channels, np.float32)
    render_pass.rect.foreach_get(values)
    return values.reshape(SIZE[1], SIZE[0], render_pass.channels)


original_convert = config.convert
def converted(*args, **kwargs):
    props = original_convert(*args, **kwargs)
    if state['control']:
        assert not final_dlss.configure_producer(props, halt_export.convert(scene))
        props.Set(slc.Property('rtpath.denoisingframes.lossless', False))
    (OUT / (state['label'] + '-config.txt')).write_text(str(props))
    return props
config.convert = converted

original_process = dlss.CUDADLSS.process
def evaluated(self, frame):
    evaluate_start = time.monotonic()
    result = original_process(self, frame)
    state['last_sdk_output'] = result.copy()
    source_size = (frame.color.shape[1], frame.color.shape[0])
    target_size = (result.shape[1], result.shape[0])
    if settings.denoiser.dlss_input_reduction == '2':
        assert source_size == (SIZE[0] // 2, SIZE[1] // 2)
        assert target_size == SIZE
    state['sdk'].append({'label': state['label'], 'blender_frame': scene.frame_current,
                         'id': frame.frame_id, 'reset': frame.reset, 'preset': self.preset,
                         'source_size': source_size, 'target_size': target_size,
                         'evaluate_readback_wall_seconds': time.monotonic() - evaluate_start})
    with (OUT / 'sdk-progress.jsonl').open('a') as log:
        log.write(json.dumps(state['sdk'][-1]) + '\n')
    if MODE == 'cancel' and len(state['sdk']) == 3:
        state['cancel_requested_at'] = time.perf_counter()
        display.stop_requested = True
    elif MODE == 'pause' and len(state['sdk']) == 2:
        display.paused = True
        def resume():
            time.sleep(.4)
            display.paused = False
        state['resume_thread'] = threading.Thread(target=resume)
        state['resume_thread'].start()
    elif MODE == 'live-halt' and len(state['sdk']) == 2:
        settings.halt.samples = SAMPLES * 2
        state['edited_halt_target'] = SAMPLES * 2
    return result
dlss.CUDADLSS.process = evaluated

original_poll = final_dlss.FinalDLSS.poll
def polled(self, *args, **kwargs):
    start = time.monotonic()
    result = original_poll(self, *args, **kwargs)
    elapsed = time.monotonic() - start
    if result or self.failed or elapsed > .5:
        row = {'label': state['label'], 'samples': self.samples, 'evaluations': self.evaluations,
               'updated': result, 'failed': self.failed, 'wall_seconds': elapsed}
        with (OUT / 'frame-progress.jsonl').open('a') as log:
            log.write(json.dumps(row) + '\n')
    return result
final_dlss.FinalDLSS.poll = polled

if MODE == 'cleanup-fault':
    original_init = final_dlss.FinalDLSS.__init__
    class FaultAfterNativePresentation:
        def __init__(self, pipeline):
            self.pipeline = pipeline
            self.calls = 0
        def process(self, *args, **kwargs):
            result = self.pipeline.process(*args, **kwargs)
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError('injected failure after native presentation')
            return result
    def initialized(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.pipeline = FaultAfterNativePresentation(self.pipeline)
    final_dlss.FinalDLSS.__init__ = initialized

original_close = final_dlss.FinalDLSS.close
def closed(self):
    state['closed'].append({'label': state['label'], 'blender_frame': scene.frame_current,
                            'samples': self.samples, 'evaluations': self.evaluations,
                            'failed': self.failed})
    if MODE == 'cleanup-fault' and self.failed and self._alpha is not None:
        assert self._raw_color is not None
        refs = [weakref.ref(self._alpha), weakref.ref(self._raw_color)]
        released_bytes = self._alpha.nbytes + self._raw_color.nbytes
        result = original_close(self)
        assert self.result is None and self._alpha is None and self._raw_color is None
        assert self.consumer._previous is None
        assert all(ref() is None for ref in refs)
        state['cleanup_fault'] = {'released_scratch_bytes': released_bytes,
                                  'weak_references_released': True,
                                  'successful_evaluations_before_failure': self.evaluations,
                                  'sdk_calls_before_failure': len(state['sdk']),
                                  'reason': self.failed}
        return result
    return original_close(self)
final_dlss.FinalDLSS.close = closed

original_draw = framebuffer.draw
def drawn(self, engine, session, current_scene, render_stopped):
    if session.IsInPause():
        state['pause_seen'] = True
    state['stopped'] = render_stopped
    state['session'] = session
    try:
        return original_draw(self, engine, session, current_scene, render_stopped)
    finally:
        state['stopped'] = False
        state.pop('session', None)
framebuffer.draw = drawn

original_refresh = framebuffer._refresh_denoiser
def refreshed(self, engine, session, current_scene, render_layer, render_stopped):
    if render_stopped:
        state['raw_display'] = pass_pixels(render_layer.passes['Combined']).copy()
    return original_refresh(self, engine, session, current_scene, render_layer, render_stopped)
framebuffer._refresh_denoiser = refreshed

original_combined = framebuffer._denoised_to_combined
def combined(self, engine, current_scene, render_layer):
    result = original_combined(self, engine, current_scene, render_layer)
    if not state['stopped']:
        return result
    capture_start = time.perf_counter()
    session = state['session']
    arrays = {'pass_' + item.name: pass_pixels(item).copy() for item in render_layer.passes}
    arrays['raw_display'] = state['raw_display']
    for name, channels in native_channels.items():
        is_uint = name in ('SAMPLECOUNT', 'OBJECT_ID')
        values = np.empty((SIZE[1], SIZE[0], channels), np.uint32 if is_uint else np.float32)
        getter = session.GetFilm().GetOutputUInt if is_uint else session.GetFilm().GetOutputFloat
        getter(slc.FilmOutputType.names[name], values, 0, False)
        arrays['native_' + name] = values
    assert np.array_equal(arrays['pass_RGB'], arrays['native_RGB'])
    controller = getattr(engine, 'final_dlss', None)
    if MODE == 'cancel' and 'cancel_requested_at' in state:
        state['cancel_to_final_capture_seconds'] = time.perf_counter() - state['cancel_requested_at']
    if controller is not None and not controller.failed:
        assert not session.IsStarted(), 'Final native film must be frozen before delivery'
        expected_samples = state.get('edited_halt_target', SAMPLES)
        assert controller.samples == controller.evaluations == expected_samples, (controller.samples, controller.evaluations, expected_samples)
        assert np.array_equal(arrays['pass_DENOISED'][:, :, :3], controller.result[:, :, :3])
        assert np.array_equal(arrays['pass_Combined'][:, :, :3], controller.result[:, :, :3])
    if current_scene.render.film_transparent:
        assert np.array_equal(arrays['pass_Combined'][:, :, 3:], arrays['native_ALPHA'])
        alpha = arrays['native_ALPHA']
        assert np.any((alpha > 0) & (alpha < 1)), 'Fixture needs actual fractional coverage'
        if controller is not None and not controller.failed:
            # Preserve the configured NOP + LINEAR(1) pipeline. Its coverage
            # pixels must keep canonical raw RGB; fully covered pixels use NN.
            expected = state['last_sdk_output'][:, :, :3].copy()
            partial = alpha[:, :, 0] < 1.
            expected[partial] = arrays['native_RGB'][partial]
            np.testing.assert_array_equal(arrays['pass_Combined'][:, :, :3], expected)
            np.testing.assert_array_equal(arrays['pass_Combined'][:, :, :3][partial], arrays['native_RGB'][partial])
    label = state['label'] + '-frame%04d' % scene.frame_current
    if MODE in ('multi-layer', 'multi-layer-unsupported'):
        label += '-layer%02d' % len(state['captures'])
    np.savez_compressed(OUT / (label + '.npz'), **arrays)
    state['captures'].append({'label': state['label'], 'frame': scene.frame_current,
                              'layer': render_layer.name,
                              'artifact': label + '.npz', 'canonical_samples': np.unique(arrays['native_SAMPLECOUNT']).tolist(),
                              'combined_rgb_mean': arrays['pass_Combined'][:, :, :3].mean(axis=(0, 1)).tolist()})
    state['last_arrays'] = arrays
    if MODE == 'live-halt':
        record = {'requested_after_edit': state.get('edited_halt_target'),
                  'actual_sample_counts': np.unique(arrays['native_SAMPLECOUNT']).tolist(),
                  'sdk_evaluations': len(state['sdk']),
                  'fallback_reason': controller.failed if controller is not None else None}
        (OUT / 'live-halt-reproduction.json').write_text(json.dumps(record, indent=2) + '\n')
    state['validation_seconds'] += time.perf_counter() - capture_start
    return result
framebuffer._denoised_to_combined = combined


def render(label, kind, animation=False):
    state.update(label=label, control=kind == 'control')
    settings.denoiser.enabled = kind != 'control'
    settings.denoiser.type = 'DLSS' if kind in ('dlss', 'alpha-fallback') else 'OIDN'
    bpy.context.view_layer.update()
    if kind == 'dlss' and MODE not in ('unsupported', 'multi-layer-unsupported', 'legacy-preset-fallback', 'capability-fallback'):
        # Fail before exporting a large scene when a saved setting selects
        # fallback. An image produced by OIDN cannot qualify as DLSS evidence.
        from types import SimpleNamespace
        options, reason = final_dlss.final_options(scene, SimpleNamespace(is_preview=False), preferences)
        assert options is not None and not reason, ('Expected actual DLSS before export', reason)
        print('DLSS_ELIGIBILITY ' + json.dumps({'label': label, 'render_mode': options.render_mode,
            'output_size': options.output_size, 'border': scene.render.use_border,
            'crop': scene.render.use_crop_to_border}), flush=True)
    before = len(state['captures'])
    start = time.monotonic()
    validation_before = state['validation_seconds']
    bpy.ops.render.render(animation=animation, write_still=False)
    render_wall = time.monotonic() - start
    validation_wall = state['validation_seconds'] - validation_before
    state['render_timings'].append({'label': label, 'render_with_validation_seconds': render_wall,
                                    'validation_seconds': validation_wall,
                                    'render_excluding_capture_seconds': render_wall - validation_wall})
    assert len(state['captures']) > before, 'Blender returned without final pass capture'
    if not animation and MODE not in ('multi-layer', 'multi-layer-unsupported'):
        image = bpy.data.images['Render Result']
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '32'
        image.save_render(str(OUT / (label + '.exr')), scene=scene)
        loaded = bpy.data.images.load(str(OUT / (label + '.exr')), check_existing=False)
        try:
            saved = np.asarray(loaded.pixels[:], np.float32).reshape(SIZE[1], SIZE[0], 4)
            assert np.max(np.abs(saved - state['last_arrays']['pass_Combined'])) < 1e-6
        finally:
            bpy.data.images.remove(loaded)
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_depth = '8'
        image.save_render(str(OUT / (label + '-aces2.png')), scene=scene)
    print(json.dumps({'render': label, 'wall_seconds': time.monotonic() - start}), flush=True)


if MODE == 'raw-reference':
    render('raw-reference', 'control')
    assert not state['sdk'] and not state['closed']
elif MODE == 'still':
    render('raw-control', 'control')
    control = state['last_arrays']
    render('dlss', 'dlss')
    exact = [name for name in native_channels if np.array_equal(control['native_' + name], state['last_arrays']['native_' + name])]
    assert exact == list(native_channels), exact
    assert state['closed'][-1]['evaluations'] == SAMPLES and not state['closed'][-1]['failed']
    assert len(state['sdk']) == SAMPLES and [item['reset'] for item in state['sdk']] == [True] + [False] * (SAMPLES - 1)
elif MODE == 'dlss-only':
    render('dlss', 'dlss')
    assert state['closed'][-1]['evaluations'] == SAMPLES and not state['closed'][-1]['failed']
    assert len(state['sdk']) == SAMPLES and [item['reset'] for item in state['sdk']] == [True] + [False] * (SAMPLES - 1)
    assert np.all(state['last_arrays']['native_SAMPLECOUNT'] == SAMPLES)
    # The actual raw Combined image was captured immediately before neural
    # delivery, from this same frozen Film/sample prefix. Preserve its native
    # image-pipeline/light-group settings rather than constructing another run.
    raw = state['last_arrays']['raw_display']
    image = bpy.data.images.new('Same-prefix raw display', width=SIZE[0], height=SIZE[1], alpha=True, float_buffer=True)
    try:
        image.colorspace_settings.name = 'Linear Rec.709'
        image.pixels.foreach_set(raw.reshape(-1));image.update()
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.color_depth = '32'
        image.save_render(str(OUT / 'raw-same-prefix.exr'), scene=scene)
        loaded = bpy.data.images.load(str(OUT / 'raw-same-prefix.exr'), check_existing=False)
        try:
            saved = np.asarray(loaded.pixels[:], np.float32).reshape(SIZE[1], SIZE[0], 4)
            assert float(np.max(np.abs(saved - raw))) < 1e-6
        finally:
            bpy.data.images.remove(loaded)
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_depth = '8'
        image.save_render(str(OUT / 'raw-same-prefix-aces2.png'), scene=scene)
    finally:
        bpy.data.images.remove(image)
elif MODE in ('multi-layer', 'multi-layer-unsupported'):
    second = scene.view_layers.new('MemoryReleaseLayer')
    second.superluxcore.halt.enable = False
    for name in ('rgb', 'alpha', 'albedo', 'avg_shading_normal', 'depth', 'position',
                 'samplecount', 'direct_diffuse', 'emission', 'object_id'):
        setattr(second.superluxcore.aovs, name, True)
    second.use_pass_z = second.use_pass_normal = second.use_pass_object_index = True
    render('multi-layer', 'dlss')
    assert len(state['captures']) == 2
    assert {item['layer'] for item in state['captures']} == {item.name for item in scene.view_layers}
    if MODE == 'multi-layer-unsupported':
        assert not state['closed'] and not state['sdk']
    else:
        assert len(state['closed']) == 2
        assert all(item['evaluations'] == SAMPLES and not item['failed'] for item in state['closed'])
        assert [item['reset'] for item in state['sdk']] == ([True] + [False] * (SAMPLES - 1)) * 2
elif MODE in ('animation', 'animation-alpha'):
    if MODE == 'animation-alpha':
        floor.scale = (.025, .025, .025)
        scene.render.film_transparent = True
    scene.frame_start, scene.frame_end = 1, 2
    for frame, x in ((1, -1.1), (2, -.65)):
        animated.location.x = x
        animated.keyframe_insert(data_path='location', frame=frame)
    scene.frame_set(1)
    scene.render.filepath = str(OUT / 'animation-')
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = '32'
    render('animation', 'dlss', animation=True)
    assert len(state['closed']) == 2 and all(item['evaluations'] == SAMPLES and not item['failed'] for item in state['closed'])
    for frame in (1, 2):
        calls = [item for item in state['sdk'] if item['blender_frame'] == frame]
        assert len(calls) == SAMPLES and [item['reset'] for item in calls] == [True] + [False] * (SAMPLES - 1)
elif MODE == 'cleanup-fault':
    floor.scale = (.025, .025, .025)
    scene.render.film_transparent = True
    render('cleanup-raw-control', 'control')
    control = state['last_arrays']
    render('cleanup-fallback', 'dlss')
    assert state['cleanup_fault']['successful_evaluations_before_failure'] == 1
    assert len(state['sdk']) == 2 and all(item['failed'] for item in state['closed'])
    assert np.all(state['last_arrays']['native_SAMPLECOUNT'] == SAMPLES), 'Fallback producer remained parked'
    for name in native_channels:
        np.testing.assert_array_equal(control['native_' + name], state['last_arrays']['native_' + name])
elif MODE in ('alpha-fallback', 'transparent-alpha'):
    floor.scale = (.025, .025, .025)
    scene.render.film_transparent = True
    render('transparent-raw-control', 'control')
    control = state['last_arrays']
    render('transparent-dlss', 'dlss')
    for name in native_channels:
        np.testing.assert_array_equal(control['native_' + name], state['last_arrays']['native_' + name])
    assert len(state['sdk']) == SAMPLES and not state['closed'][-1]['failed']
    assert np.any(state['last_arrays']['native_ALPHA'] < 1.)
elif MODE == 'opaque-alpha':
    floor.scale = (.025, .025, .025)
    scene.render.film_transparent = False
    render('opaque-raw-control', 'control')
    control = state['last_arrays']
    assert np.any(control['native_ALPHA'] < 1.)
    render('opaque-dlss', 'dlss')
    for name in native_channels:
        np.testing.assert_array_equal(control['native_' + name], state['last_arrays']['native_' + name])
    assert len(state['sdk']) == SAMPLES and not state['closed'][-1]['failed']
    assert np.all(state['last_arrays']['pass_Combined'][:, :, 3] == 1.)
elif MODE == 'oidn':
    render('oidn-default', 'oidn')
    assert not state['closed'] and not state['sdk']
elif MODE == 'unsupported':
    assert DEVICE != 'CUDA_GPU'
    render('dlss-unsupported-oidn', 'dlss')
    assert not state['closed'] and not state['sdk']
elif MODE == 'legacy-preset-fallback':
    assert DEVICE == 'CUDA_GPU' and settings.denoiser.dlss_preset != 'DEFAULT'
    render('legacy-model-oidn', 'dlss')
    assert not state['closed'] and not state['sdk']
    assert np.min(state['last_arrays']['native_SAMPLECOUNT']) >= SAMPLES
    assert 'RTPATHOCL' not in (OUT / 'legacy-model-oidn-config.txt').read_text()
elif MODE == 'capability-fallback':
    assert not hasattr(slc.RenderSession, 'SetDenoisingFrameHaltSPP')
    render('old-native-oidn', 'dlss')
    assert not state['closed'] and not state['sdk']
elif MODE == 'cancel':
    try:
        render('cancel', 'dlss')
    finally:
        display.stop_requested = False
    assert len(state['sdk']) == 3
    assert 'cancelled' in state['closed'][-1]['failed'].lower()
    np.testing.assert_array_equal(state['last_arrays']['pass_Combined'], state['last_arrays']['raw_display'])
    denoised = state['last_arrays']['pass_DENOISED']
    np.testing.assert_array_equal(denoised, state['last_arrays']['raw_display'][:, :, :denoised.shape[2]])
    assert state['cancel_to_final_capture_seconds'] < 2., state['cancel_to_final_capture_seconds']
elif MODE == 'pause':
    try:
        render('pause', 'dlss')
    finally:
        display.paused = False
        if 'resume_thread' in state:
            state['resume_thread'].join(timeout=2)
            assert not state['resume_thread'].is_alive()
    assert state['pause_seen'], 'Native session never actually paused'
    assert len(state['sdk']) == SAMPLES and not state['closed'][-1]['failed']
elif MODE == 'live-halt':
    settings.halt.samples = SAMPLES * 2
    render('live-halt-control', 'control')
    control = state['last_arrays']
    settings.halt.samples = SAMPLES
    render('live-halt', 'dlss')
    assert state['edited_halt_target'] == SAMPLES * 2
    assert np.all(state['last_arrays']['native_SAMPLECOUNT'] == SAMPLES * 2), 'Edited halt target stopped at the old native coherent cap'
    assert len(state['sdk']) == SAMPLES * 2 and not state['closed'][-1]['failed']
    assert [item['reset'] for item in state['sdk']] == [True] + [False] * (SAMPLES * 2 - 1)
    for name in native_channels:
        assert np.array_equal(control['native_' + name], state['last_arrays']['native_' + name]), name
else:
    raise ValueError(MODE)
report = {'mode': MODE, 'device': DEVICE, 'blender': bpy.app.version_string, 'native_sha256': hashlib.file_digest(native.open('rb'), 'sha256').hexdigest(),
          'preset': settings.denoiser.dlss_preset,
          'input_reduction': settings.denoiser.dlss_input_reduction,
          'fixture': 'original scene geometry/materials/lights/camera' if KEEP_SCENE else 'two diffuse cubes',
          'blender_memory_release': state.get('blender_memory_release', []),
          'render_timings': state['render_timings'],
          'pause_seen': state['pause_seen'],
          'cancel_to_final_capture_seconds': state.get('cancel_to_final_capture_seconds'),
          'size': SIZE, 'samples': SAMPLES, 'sdk_calls': state['sdk'], 'controllers': state['closed'], 'captures': state['captures'],
          'scope': 'Actual stock-Blender F12/animation, explicit RGB eye-only diagnostic settings with the recorded fixture; canonical AOV comparison, real CUDA/NGX and EXR/ACES2 export. Not general alpha/SR/material/motion support, performance or equal-error quality proof.'}
if MODE == 'still':
    report['raw_aov_control_bit_exact'] = exact
if os.environ.get('SLC_DLSS_EXPECT_MEMORY_RELEASE') == '1':
    assert len(state.get('blender_memory_release', [])) == len(state['captures'])
if MODE == 'cleanup-fault':
    report['cleanup_fault'] = state['cleanup_fault']
    report['raw_aov_control_bit_exact'] = list(native_channels)
(OUT / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report), flush=True)
