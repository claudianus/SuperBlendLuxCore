# SPDX-License-Identifier: Apache-2.0
"""720p visual diagnostics through cycles-bssrdf-experimental-test.py.

Construct ordinary Cycles graphs; rendering must not edit their node inputs,
links, method or original Cycles settings. These private eye-only or pure
LIGHTCPU results are never counted as production/default-quality acceptance.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path

import bpy
import numpy as np
import pysuperluxcore

folder = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
folder.mkdir(parents=True, exist_ok=True)
package = next(a.module for a in bpy.context.preferences.addons
               if a.module.endswith('.superluxcore'))
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=48, radius=.8)
obj = bpy.context.object
for face in obj.data.polygons:
    face.use_smooth = True
mat = bpy.data.materials.new('Unchanged Cycles BSSRDF diagnostic')
mat.use_nodes = True
obj.data.materials.append(mat)
bpy.ops.object.camera_add(location=(0., -4., 1.4))
s = bpy.context.scene
s.camera = bpy.context.object
s.camera.rotation_euler = (-s.camera.location).to_track_quat('-Z', 'Y').to_euler()
s.camera.data.type = 'ORTHO'
s.camera.data.ortho_scale = 3.2
bpy.ops.object.light_add(type='SUN', location=(-2., -3., 4.))
sun = bpy.context.object
sun.rotation_euler = (-sun.location).to_track_quat('-Z', 'Y').to_euler()
sun.data.energy, sun.data.angle = 1., .01
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.
s.render.resolution_x, s.render.resolution_y = 1280, 720
s.render.resolution_percentage = 100
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.render.image_settings.color_mode = 'RGBA'
s.view_settings.view_transform = 'Standard'
s.cycles.samples = int(os.environ.get('SUPERLUXCORE_BSSRDF_SAMPLES', '128'))
s.cycles.use_denoising = False
cfg = s.superluxcore
cfg.config.device = 'CPU'
cfg.config.path.use_clamping = cfg.config.path.auto_clamping = False
cfg.halt.enable = cfg.halt.use_samples = True
cfg.halt.samples = s.cycles.samples
cfg.halt.use_noise_level = cfg.halt.use_noise_thresh = False
cfg.denoiser.enabled = False
s.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False


def fingerprint():
    def value(socket):
        data = socket.default_value
        return list(data) if hasattr(data, '__iter__') else data
    def graph(material):
        nodes = material.node_tree.nodes
        return {'nodes': sorted((n.name, n.bl_idname,
                               [(i.name, value(i)) for i in n.inputs if hasattr(i, 'default_value')],
                               getattr(n, 'falloff', ''), getattr(n, 'operation', '')) for n in nodes),
               'links': sorted((l.from_node.name, l.from_socket.name,
                                l.to_node.name, l.to_socket.name) for l in material.node_tree.links)}
    payload = {'materials': sorted((material.name, graph(material))
                                  for material in bpy.data.materials if material.use_nodes),
               'world': graph(s.world),
               'lights': sorted((o.name, o.data.type, o.data.energy, list(o.data.color),
                                 getattr(o.data, 'angle', 0.))
                                for o in s.objects if o.type == 'LIGHT'),
               'material_indices': [p.material_index for p in obj.data.polygons],
               'objects': sorted((o.name, o.type, list(o.matrix_world),
                                   o.instance_type, o.instance_collection.name if o.instance_collection else '')
                                  for o in s.objects),
               'cycles_samples': s.cycles.samples, 'cycles_filter_glossy': s.cycles.blur_glossy,
               'film_transparent': s.render.film_transparent}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode()).hexdigest()


variants = {
    'hybrid-glass-sharp': {'color': (.55, .2, .08, 1.), 'radius': (1., .3, .2),
                          'scale': .8, 'roughness': 0., 'anisotropy': 0.,
                          'spectral': True, 'glass_caster': True},
    'hybrid-glass-rough': {'color': (.45, .45, .45, 1.), 'radius': (1., .3, .2),
                          'scale': .8, 'roughness': .4, 'anisotropy': 0.,
                          'spectral': True, 'glass_caster': True},
    'sharp-colored': {'color': (.55, .2, .08, 1.), 'radius': (1., .3, .2),
                      'scale': .2, 'roughness': 0., 'anisotropy': 0., 'spectral': True},
    'rough-anisotropic': {'color': (.45, .45, .45, 1.), 'radius': (1., .2, .1),
                         'scale': .15, 'roughness': .6, 'anisotropy': .5, 'spectral': True},
    'colored': {'color': (.55, .2, .08, 1.), 'radius': (1., .3, .2),
                'scale': .2, 'roughness': .25, 'anisotropy': 0., 'spectral': True},
    'partial-radius-rgb': {'color': (.45, .45, .45, 1.), 'radius': (0., .2, .1),
                          'scale': .15, 'roughness': 0., 'anisotropy': 0., 'spectral': False},
    'textured-entry': {'color': (.45, .45, .45, 1.), 'radius': (1., .2, .1),
                       'scale': .15, 'roughness': .25, 'anisotropy': 0.,
                       'spectral': True, 'textured': True},
    'generated-checker-emission': {'spectral': True, 'textured': True, 'emission': True},
    'material-partitions': {'color': (.45, .45, .45, 1.), 'radius': (1., .2, .1),
                            'scale': .15, 'roughness': .25, 'anisotropy': 0.,
                            'spectral': True, 'partitioned': True},
    'material-partition-instances': {'color': (.45, .45, .45, 1.), 'radius': (1., .2, .1),
                                    'scale': .15, 'roughness': .25, 'anisotropy': 0.,
                                    'spectral': True, 'partitioned': True, 'instances': True},
}
# Exercise the existing Cycles Mix/Add exporter with a nonlocal branch.
for name, mode in (('mix-diffuse', 'mix'), ('add-diffuse', 'add'),
                   ('textured-mix-diffuse', 'textured')):
    variants[name] = dict(variants['colored'], mixed=mode)
for name, mode, nested in (('mix-transparent', 'mix', False), ('add-transparent', 'add', False),
                           ('checker-transparent', 'textured', False), ('nested-transparent', 'mix', True)):
    variants[name] = dict(variants['colored'], mixed=mode, transparent=True, nested_null=nested)
records = []
original_filter_glossy = s.cycles.blur_glossy
for case in os.environ.get('SUPERLUXCORE_BSSRDF_VARIANTS', ','.join(variants)).split(','):
    variant = variants[case]
    caster = None
    if variant.get('glass_caster'):
        # A closed slab, rather than an open dielectric interface, keeps the
        # authored Cycles scene's exterior medium and energy well defined.
        sun.data.energy = 0.
        s.world.node_tree.nodes['Background'].inputs['Color'].default_value = (1., 1., 1., 1.)
        s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1.
        s.cycles.blur_glossy = 0.
        bpy.ops.mesh.primitive_cube_add(size=2., location=(0., 1.3, 0.))
        caster = bpy.context.object
        caster.name = 'Unchanged Cycles sharp glass slab'
        caster.scale = (3., .05, 3.)
        caster_material = bpy.data.materials.new('Unchanged Cycles Glass BSDF')
        caster_material.use_nodes = True
        caster_material.node_tree.nodes.clear()
        glass = caster_material.node_tree.nodes.new('ShaderNodeBsdfGlass')
        glass.inputs['Color'].default_value = (1., 1., 1., 1.)
        glass.inputs['Roughness'].default_value = 0.
        glass.inputs['IOR'].default_value = 1.5
        glass_output = caster_material.node_tree.nodes.new('ShaderNodeOutputMaterial')
        caster_material.node_tree.links.new(glass.outputs[0], glass_output.inputs['Surface'])
        caster.data.materials.append(caster_material)
    cfg.config.spectral_enable = variant['spectral']
    s.render.film_transparent = bool(variant.get('transparent'))
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new('ShaderNodeOutputMaterial')
    if variant.get('emission'):
        target = nodes.new('ShaderNodeEmission')
    else:
        target = nodes.new('ShaderNodeSubsurfaceScattering')
        target.falloff = 'RANDOM_WALK'
        for name, key in (('Color', 'color'), ('Radius', 'radius'), ('Scale', 'scale'),
                          ('Roughness', 'roughness'), ('Anisotropy', 'anisotropy')):
            target.inputs[name].default_value = variant[key]
    if variant.get('textured'):
        checker = nodes.new('ShaderNodeTexChecker')
        checker.inputs['Color1'].default_value = (.65, .16, .08, 1.)
        checker.inputs['Color2'].default_value = (.08, .18, .55, 1.)
        checker.inputs['Scale'].default_value = 5.
        links.new(checker.outputs['Color'], target.inputs['Color'])
    if variant.get('mixed'):
        diffuse = nodes.new('ShaderNodeBsdfTransparent' if variant.get('transparent') and not variant.get('nested_null') else 'ShaderNodeBsdfDiffuse')
        diffuse.inputs['Color'].default_value = (1., 1., 1., 1.) if diffuse.bl_idname == 'ShaderNodeBsdfTransparent' else (.08, .18, .55, 1.)
        if variant.get('nested_null'):
            clear = nodes.new('ShaderNodeBsdfTransparent')
            inner = nodes.new('ShaderNodeMixShader')
            inner.inputs[0].default_value = .7
            links.new(diffuse.outputs[0], inner.inputs[1])
            links.new(clear.outputs[0], inner.inputs[2])
            diffuse = inner
        mode = variant['mixed']
        blend = nodes.new('ShaderNodeAddShader' if mode == 'add' else 'ShaderNodeMixShader')
        offset = 0 if mode == 'add' else 1
        if mode != 'add':
            blend.inputs[0].default_value = .35
        if mode == 'textured':
            factor = nodes.new('ShaderNodeTexChecker')
            factor.inputs['Scale'].default_value = 5.
            links.new(factor.outputs['Fac'], blend.inputs[0])
        links.new(target.outputs[0], blend.inputs[offset])
        links.new(diffuse.outputs[0], blend.inputs[offset + 1])
        target = blend
    links.new(target.outputs[0], output.inputs['Surface'])
    second_material, source_collection, instances = None, None, []
    if variant.get('partitioned'):
        second_material = mat.copy()
        obj.data.materials.append(second_material)
        for face in obj.data.polygons:
            face.material_index = face.index % 2
    if variant.get('instances'):
        # The source collection is not directly linked into the scene: only
        # its copies render. This exercises the native DuplicateObject path.
        source_collection = bpy.data.collections.new('BSSRDF partitioned source')
        source_collection.objects.link(obj)
        for collection in list(obj.users_collection):
            if collection != source_collection:
                collection.objects.unlink(obj)
        for index, x in enumerate((-.9, .9)):
            instance = bpy.data.objects.new('Partitioned BSSRDF instance ' + str(index), None)
            instance.instance_type = 'COLLECTION'
            instance.instance_collection = source_collection
            instance.location.x = x
            s.collection.objects.link(instance)
            instances.append(instance)
    bpy.context.view_layer.update()
    before = fingerprint()
    images = {}
    for engine in ('CYCLES', 'SUPERLUXCORE'):
        s.render.engine = engine
        log.clear(False)
        path = folder / (case + '_' + engine + '.exr')
        s.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        loaded = bpy.data.images.load(str(path), check_existing=False)
        pixels = np.asarray(loaded.pixels[:], np.float32).reshape(720, 1280, 4)
        images[engine] = pixels.copy()
        bpy.data.images.remove(loaded)
        s.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
        s.render.image_settings.file_format = 'OPEN_EXR'
        assert fingerprint() == before, (case, engine)
        assert np.isfinite(pixels).all() and not log.errors, (case, engine)
        assert all(w.message == 'Light-probe-volume backface culling is Eevee-only - ignored'
                   or w.message.startswith('The scene contains a lot of light sources (')
                   for w in log.warnings), [w.message for w in log.warnings]
    a, b = images['CYCLES'][:, :, :3], images['SUPERLUXCORE'][:, :, :3]
    record = {'case': case, 'experimental': True, 'production_acceptance': False,
              'graph_sha256': before, 'graph_unchanged': True,
              'spectral': variant['spectral'], 'device': os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE', 'CPU'),
              'resolution': [1280, 720], 'samples': s.cycles.samples,
              'light_samples_override': os.environ.get('SUPERLUXCORE_BSSRDF_LIGHT_SAMPLES'),
              'cycles_rgb_mean': a.mean(axis=(0, 1)).tolist(),
              'native_rgb_mean': b.mean(axis=(0, 1)).tolist(),
              'native_cycles_mean_ratio': float(b.mean() / max(a.mean(), 1e-8)),
              'pixel_mae': float(np.abs(a - b).mean()),
              'cycles_alpha_mean': float(images['CYCLES'][:, :, 3].mean()),
              'native_alpha_mean': float(images['SUPERLUXCORE'][:, :, 3].mean()),
              'alpha_mae': float(np.abs(images['CYCLES'][:, :, 3] - images['SUPERLUXCORE'][:, :, 3]).mean()),
              'native_sha256': hashlib.sha256(Path(pysuperluxcore.pysuperluxcore.__file__).read_bytes()).hexdigest(),
              'directly_reviewed': False, 'full_compatibility_verified': False}
    records.append(record)
    (folder / 'scene-metrics.json').write_text(json.dumps(records, indent=2) + '\n')
    print('BSSRDF_SCENE_DIAGNOSTIC', record, flush=True)
    for instance in instances:
        bpy.data.objects.remove(instance, do_unlink=True)
    if source_collection:
        s.collection.objects.link(obj)
        source_collection.objects.unlink(obj)
        bpy.data.collections.remove(source_collection)
    if second_material:
        obj.data.materials.pop(index=1)
        bpy.data.materials.remove(second_material)
        for face in obj.data.polygons:
            face.material_index = 0
    if caster:
        bpy.data.objects.remove(caster, do_unlink=True)
        bpy.data.materials.remove(caster_material)
        sun.data.energy = 1.
        s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0.
        s.cycles.blur_glossy = original_filter_glossy
print('BSSRDF_SCENE_COMPLETE', len(records), flush=True)
