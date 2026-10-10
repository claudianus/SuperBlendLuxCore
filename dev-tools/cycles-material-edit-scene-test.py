# SPDX-License-Identifier: Apache-2.0
"""720p headless Blender material edits through the real recorded update path.

Run through cycles-bssrdf-experimental-test.py. Compare one live native scene
with a fresh export and Cycles after each intentional graph edit. This checks
the exporter/replay contract, not GUI redraw or production BSSRDF acceptance.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import time

import bpy
import numpy as np
import pysuperluxcore as slc

folder = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
folder.mkdir(parents=True, exist_ok=True)
package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore'))
export = importlib.import_module(package + '.export')
recorded = importlib.import_module(package + '.export.recorded_scene').RecordedScene
persistent = importlib.import_module(package + '.export.caches.persistent_scene')
errors = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=48, radius=.8)
obj = bpy.context.object
for face in obj.data.polygons:
    face.use_smooth = True
mat = bpy.data.materials.new('Cycles material edited in place')
mat.use_nodes = True
obj.data.materials.append(mat)
nodes, links = mat.node_tree.nodes, mat.node_tree.links
nodes.clear()
output = nodes.new('ShaderNodeOutputMaterial')
old = nodes.new('ShaderNodeBsdfDiffuse')
old.inputs['Color'].default_value = (.45, .45, .45, 1.)
black = nodes.new('ShaderNodeBsdfDiffuse')
black.inputs['Color'].default_value = (0., 0., 0., 1.)
root = nodes.new('ShaderNodeMixShader')
root.inputs[0].default_value = 0.
links.new(old.outputs[0], root.inputs[1])
links.new(black.outputs[0], root.inputs[2])
links.new(root.outputs[0], output.inputs['Surface'])
bpy.ops.object.camera_add(location=(0., -4., 1.4))
s = bpy.context.scene
s.camera = bpy.context.object
s.camera.rotation_euler = (-s.camera.location).to_track_quat('-Z', 'Y').to_euler()
s.camera.data.type, s.camera.data.ortho_scale = 'ORTHO', 3.2
bpy.ops.object.light_add(type='SUN', location=(-2., -3., 4.))
sun = bpy.context.object
sun.rotation_euler = (-sun.location).to_track_quat('-Z', 'Y').to_euler()
sun.data.energy, sun.data.angle = 1., .01
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.
s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = 1280, 720, 100
s.render.film_transparent = True
s.render.image_settings.file_format, s.render.image_settings.color_mode = 'OPEN_EXR', 'RGBA'
s.render.image_settings.color_depth = '32'
s.view_settings.view_transform = 'Standard'
s.cycles.samples, s.cycles.use_denoising = 128, False
cfg = s.superluxcore
cfg.config.device = 'CPU'
cfg.config.path.use_clamping = cfg.config.path.auto_clamping = False
cfg.halt.enable = cfg.halt.use_samples = True
cfg.halt.samples = 128
cfg.halt.use_noise_level = cfg.halt.use_noise_thresh = False
cfg.denoiser.enabled = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False


def fingerprint():
    def value(socket):
        v = socket.default_value
        return list(v) if hasattr(v, '__iter__') else v
    payload = {'nodes': sorted((n.name, n.bl_idname, getattr(n, 'falloff', ''),
                               [(i.identifier, value(i)) for i in n.inputs if hasattr(i, 'default_value')])
                              for n in nodes),
               'links': sorted((l.from_node.name, l.from_socket.identifier,
                                l.to_node.name, l.to_socket.identifier) for l in links),
               'samples': s.cycles.samples, 'film_transparent': s.render.film_transparent}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def wait(ses):
    start = time.monotonic()
    while True:
        ses.UpdateStats()
        if ses.GetStats().Get('stats.renderengine.pass').GetInt() >= 128:
            break
        assert time.monotonic() - start < 180, '720p live edit timed out'
        time.sleep(.1)


def native_pixels(ses, name):
    wait(ses)
    rgba = np.empty((720, 1280, 4), np.float32)
    for kind, channels in (('RGB', 3), ('ALPHA', 1)):
        data = np.empty(720 * 1280 * channels, np.float32)
        ses.GetFilm().GetOutputFloat(getattr(slc.FilmOutputType, kind), data, 0, True)
        rgba[:, :, :3] = data.reshape(720, 1280, 3) if kind == 'RGB' else rgba[:, :, :3]
        if kind == 'ALPHA':
            rgba[:, :, 3] = data.reshape(720, 1280)
    assert np.isfinite(rgba).all()
    # Native film and Blender image pixels share bottom-up raster ordering.
    image = bpy.data.images.new(name, width=1280, height=720, float_buffer=True)
    image.pixels.foreach_set(rgba.ravel())
    image.save_render(str(folder / (name + '.exr')), scene=s)
    preview = rgba.copy()
    preview[:, :, 3] = 1.
    image.pixels.foreach_set(preview.ravel())
    s.render.image_settings.file_format = 'PNG'
    image.save_render(str(folder / (name + '_rgb.png')), scene=s)
    s.render.image_settings.file_format = 'OPEN_EXR'
    bpy.data.images.remove(image)
    return rgba


def fresh_session():
    persistent.clear_all()
    ex = export.Exporter()
    scn, config = ex.export_scene(bpy.context.evaluated_depsgraph_get(), None)
    config.Set(slc.Property('film.outputs.91.type', 'ALPHA'))
    config.Set(slc.Property('film.outputs.91.filename', 'unused-alpha.exr'))
    return ex, scn, slc.RenderSession(slc.RenderConfig(config, scn))


s.render.engine = 'SUPERLUXCORE'
exporter, live_scene, live = fresh_session()
records = []
try:
    live.Start()
    wait(live)
    # Create this subtree only after the existing root has rendered.
    subsurface = nodes.new('ShaderNodeSubsurfaceScattering')
    subsurface.falloff = 'RANDOM_WALK'
    for name, value in (('Color', (.55, .2, .08, 1.)), ('Radius', (1., .3, .2)),
                        ('Scale', .2), ('Roughness', .25)):
        subsurface.inputs[name].default_value = value
    other = nodes.new('ShaderNodeBsdfDiffuse')
    other.inputs['Color'].default_value = (.08, .18, .55, 1.)
    late = nodes.new('ShaderNodeMixShader')
    late.inputs[0].default_value = .35
    links.new(subsurface.outputs[0], late.inputs[1])
    links.new(other.outputs[0], late.inputs[2])
    links.new(late.outputs[0], root.inputs[1])
    for case in ('late-sss', 'late-transparent', 'late-emission'):
        if case != 'late-sss':
            other = nodes.new('ShaderNodeBsdfTransparent' if case == 'late-transparent' else 'ShaderNodeEmission')
            other.inputs['Color'].default_value = (1., 1., 1., 1.) if case == 'late-transparent' else (.08, .18, .55, 1.)
            links.new(other.outputs[0], late.inputs[2])
        mat.update_tag()
        bpy.context.view_layer.update()
        before = fingerprint()
        errors.clear(False)
        exporter.material_cache.changed_materials.add(mat)
        jobs = exporter.update(bpy.context.evaluated_depsgraph_get(), None, export.Change.MATERIAL)
        assert jobs and all(kind == 'edit' for kind, _ in jobs), jobs
        live.BeginSceneEdit()
        for kind, ops in jobs:
            recorded.replay(live_scene, ops)
        live.EndSceneEdit()
        a = native_pixels(live, case + '_LIVE')
        _, _, fresh = fresh_session()
        try:
            fresh.Start()
            b = native_pixels(fresh, case + '_FRESH')
        finally:
            fresh.Stop()
        s.render.engine = 'CYCLES'
        path = folder / (case + '_CYCLES.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        image = bpy.data.images.load(str(path), check_existing=False)
        c = np.asarray(image.pixels[:], np.float32).reshape(720, 1280, 4)
        rgb = c.copy()
        rgb[:, :, 3] = 1.
        image.pixels.foreach_set(rgb.ravel())
        s.render.image_settings.file_format = 'PNG'
        image.save_render(str(path.with_name(path.stem + '_rgb.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
        bpy.data.images.remove(image)
        s.render.engine = 'SUPERLUXCORE'
        assert fingerprint() == before and np.isfinite(c).all() and not errors.errors
        ratio = float(a[:, :, :3].mean() / b[:, :, :3].mean())
        alpha_error = float(abs(a[:, :, 3].mean() - b[:, :, 3].mean()))
        assert abs(ratio - 1.) < .02 and alpha_error < .003, (case, ratio, alpha_error)
        row = {'case': case, 'device': os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE', 'CPU'),
               'resolution': [1280, 720], 'samples': 128, 'graph_sha256': before,
               'graph_unchanged_by_render': True, 'recorded_material_edit': True,
               'live_fresh_rgb_mean_ratio': ratio, 'live_fresh_alpha_mean_error': alpha_error,
               'native_cycles_mean_ratio': float(a[:, :, :3].mean() / c[:, :, :3].mean()),
               'pixel_mae_live_fresh': float(np.abs(a[:, :, :3] - b[:, :, :3]).mean()),
               'native_sha256': hashlib.sha256(Path(slc.pysuperluxcore.__file__).read_bytes()).hexdigest(),
               'directly_reviewed': False, 'gui_redraw_verified': False,
               'production_acceptance': False}
        records.append(row)
        (folder / 'material-scene-metrics.json').write_text(json.dumps(records, indent=2) + '\n')
        print('CYCLES_MATERIAL_EDIT_SCENE', row, flush=True)
finally:
    live.Stop()
    persistent.clear_all()
print('CYCLES_MATERIAL_EDIT_SCENE_COMPLETE', len(records), flush=True)
