"""Compare Cycles vector displacement geometry and pass data without graph edits.

This covers DISPLACEMENT only. Vector BUMP/BOTH remain explicit acceptance work.
Use SUPERLUXCORE_AUDIT_CASES to select diagnostic cases and DEV=OCL for Metal.
"""
import hashlib
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
errorlog = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
native = importlib.import_module('pysuperluxcore')
expected = os.environ.get('SUPERLUXCORE_EXPECT_VERSION', '2.11.22')
assert native.Version() == importlib.metadata.version('pysuperluxcore') == expected
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/slc-vector-displacement'))
folder.mkdir(parents=True, exist_ok=True)
width, height = 1280, 720
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
plane = bpy.context.object
plane.name = 'Vector displacement source'
plane.rotation_euler = (.3, .4, .2)
plane.scale = (1.4, .8, 1.2)
# A regular, explicit mesh tests deformation without adaptive tessellation.
bpy.ops.object.mode_set(mode='EDIT')
bpy.ops.mesh.subdivide(number_cuts=12)
bpy.ops.object.mode_set(mode='OBJECT')
uv_original = np.empty((len(plane.data.uv_layers.active.data), 2), np.float32)
plane.data.uv_layers.active.data.foreach_get('uv', uv_original.ravel())
original_mesh = plane.data.copy()
material = bpy.data.materials.new('Existing Cycles vector displacement')
material.use_nodes = True
material.displacement_method = 'DISPLACEMENT'
plane.data.materials.append(material)
bpy.ops.object.camera_add(location=(0, 0, 4))
scene = bpy.context.scene
scene.camera = bpy.context.object
scene.camera.data.type = 'ORTHO'
scene.camera.data.ortho_scale = 3
scene.render.resolution_x = width
scene.render.resolution_y = height
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'OPEN_EXR'
scene.render.image_settings.color_depth = '32'
scene.render.image_settings.color_mode = 'RGBA'
scene.view_settings.view_transform = 'Standard'
scene.cycles.samples = 16
scene.cycles.use_denoising = False
if os.environ.get('SUPERLUXCORE_AUDIT_BEAUTY') == '1':
    bpy.ops.object.light_add(type='AREA', location=(2, -3, 4))
    light = bpy.context.object
    light.data.energy = 250
    light.data.size = 4
    light.rotation_euler = (-light.location).to_track_quat('-Z', 'Y').to_euler()
layer = scene.view_layers[0]
layer.use_pass_normal = True
layer.use_pass_z = True
cfg = scene.superluxcore
cfg.config.device = 'OCL' if os.environ.get('DEV') == 'OCL' else 'CPU'
if cfg.config.device == 'OCL':
    bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
cfg.halt.enable = True
cfg.halt.use_samples = True
cfg.halt.samples = 16
cfg.halt.use_noise_level = False
cfg.halt.use_noise_thresh = False
cfg.denoiser.enabled = False
scene.camera.data.superluxcore.imagepipeline.tonemapper.enabled = False
compositor = bpy.data.node_groups.new('Displacement pass inspection', 'CompositorNodeTree')
compositor.interface.new_socket(name='Image', in_out='OUTPUT', socket_type='NodeSocketColor')
render_layers = compositor.nodes.new('CompositorNodeRLayers')
render_layers.layer = layer.name
output = compositor.nodes.new('NodeGroupOutput')
scene.compositing_node_group = compositor
scene.render.use_compositing = True
captured = {}
original_import = final.FrameBufferFinal._import_cycles_passes


def inspect(self, source_layer, render_layer, session, engine, scene):
    original_import(self, source_layer, render_layer, session, engine, scene)
    for name in ('Normal', 'Depth'):
        p = render_layer.passes[name]
        data = np.empty(width * height * p.channels, np.float32)
        p.rect.foreach_get(data)
        captured[name] = data.reshape(height, width, p.channels).copy()


final.FrameBufferFinal._import_cycles_passes = inspect
cases = [('object_linked', 'OBJECT', ''), ('tangent_linked', 'TANGENT', ''),
         ('world_linked', 'WORLD', ''), ('object_uv_gradient', 'OBJECT', 'uv'),
         ('world_position', 'WORLD', 'position'), ('linked_midlevel_gradient', 'OBJECT', 'midlevel'),
         ('tangent_mirrored_uv', 'TANGENT', 'mirror_uv'), ('tangent_rotated_uv', 'TANGENT', 'rotate_uv'),
         ('object_negative_scale', 'OBJECT', 'negative_scale'), ('world_negative_scale', 'WORLD', 'negative_scale'),
         ('object_no_uv', 'OBJECT', 'no_uv'), ('world_no_uv', 'WORLD', 'no_uv'),
         ('tangent_no_uv', 'TANGENT', 'no_uv'), ('object_shared_instances', 'OBJECT', 'instances'),
         ('world_shared_instances', 'WORLD', 'instances'),
         ('linked_scale_gradient', 'OBJECT', 'scale'), ('tangent_negative_scale', 'TANGENT', 'negative_scale'),
         ('object_curved_no_uv', 'OBJECT', 'curved_no_uv'), ('tangent_curved_no_uv', 'TANGENT', 'curved_no_uv'),
         ('world_curved_no_uv', 'WORLD', 'curved_no_uv')]
selected = set(filter(None, os.environ.get('SUPERLUXCORE_AUDIT_CASES', '').split(',')))
if selected:
    assert selected <= {case[0] for case in cases}, selected
    cases = [case for case in cases if case[0] in selected]
records = []
instances = []
for tag, space, feature in cases:
    for obj in instances:
        bpy.data.objects.remove(obj, do_unlink=True)
    instances.clear()
    old_mesh = plane.data
    plane.data = original_mesh.copy()
    plane.data.materials.append(material)
    if old_mesh != original_mesh and old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    plane.location = (0, 0, 0)
    plane.rotation_euler = (.3, .4, .2)
    plane.scale = (-1.4 if feature == 'negative_scale' else 1.4, .8, 1.2)
    if feature == 'curved_no_uv':
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=1)
        sphere = bpy.context.object
        plane.data = sphere.data
        bpy.data.objects.remove(sphere, do_unlink=True)
        plane.data.materials.append(material)
        for polygon in plane.data.polygons:
            polygon.use_smooth = True
        plane.scale = (.9, .9, .9) if os.environ.get('SUPERLUXCORE_AUDIT_UNIFORM_SCALE') == '1' else (.9, .7, 1.1)
    if feature in ('no_uv', 'curved_no_uv'):
        for uv in list(plane.data.uv_layers):
            plane.data.uv_layers.remove(uv)
    elif feature in ('mirror_uv', 'rotate_uv'):
        values = uv_original.copy()
        if feature == 'mirror_uv':
            values[:, 0] = 1 - values[:, 0]
        else:
            values = np.column_stack((values[:, 1], 1 - values[:, 0]))
        plane.data.uv_layers.active.data.foreach_set('uv', values.ravel())
    if feature == 'instances':
        plane.location = (-1.1, -.1, 0)
        plane.scale = (.65, .5, 1.2)
        other = plane.copy()
        other.data = plane.data
        other.location = (1.1, .1, .2)
        other.rotation_euler = (-.15, -.35, -.3)
        other.scale = (.8, .55, .7)
        scene.collection.objects.link(other)
        instances.append(other)
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial')
    diffuse = nodes.new('ShaderNodeBsdfDiffuse')
    links.new(diffuse.outputs[0], out.inputs['Surface'])
    displacement = nodes.new('ShaderNodeVectorDisplacement')
    displacement.space = space
    displacement.inputs['Vector'].default_value = (.8, .65, .9, 1)
    links.new(displacement.outputs[0], out.inputs['Displacement'])
    for name, value in [('Scale', .4), ('Midlevel', .5)]:
        source = nodes.new('ShaderNodeValue')
        source.outputs[0].default_value = value
        links.new(source.outputs[0], displacement.inputs[name])
    if feature in ('uv', 'midlevel', 'scale'):
        coord = nodes.new('ShaderNodeTexCoord')
        separate = nodes.new('ShaderNodeSeparateXYZ')
        links.new(coord.outputs['UV'], separate.inputs[0])
        if feature == 'midlevel':
            links.new(separate.outputs['X'], displacement.inputs['Midlevel'])
        elif feature == 'scale':
            links.new(separate.outputs['Y'], displacement.inputs['Scale'])
        else:
            combined = nodes.new('ShaderNodeCombineXYZ')
            combined.inputs['Y'].default_value = .65
            combined.inputs['Z'].default_value = .9
            links.new(separate.outputs['X'], combined.inputs['X'])
            links.new(combined.outputs[0], displacement.inputs['Vector'])
    elif feature == 'position':
        geometry = nodes.new('ShaderNodeNewGeometry')
        links.new(geometry.outputs['Position'], displacement.inputs['Vector'])
        for node in nodes:
            if node.bl_idname == 'ShaderNodeValue':
                node.outputs[0].default_value = .04 if any(link.to_socket.name == 'Scale' for link in node.outputs[0].links) else 0
    def fingerprint():
        def value(socket):
            v = socket.default_value
            return list(v) if hasattr(v, '__iter__') else v
        points = np.empty(len(plane.data.vertices) * 3, np.float32)
        plane.data.vertices.foreach_get('co', points)
        uv_layers = []
        for uv_layer in plane.data.uv_layers:
            values = np.empty(len(uv_layer.data) * 2, np.float32)
            uv_layer.data.foreach_get('uv', values)
            uv_layers.append((uv_layer.name, hashlib.sha256(values.tobytes()).hexdigest()))
        return {'links': sorted((link.from_node.name, link.from_socket.name, link.to_node.name, link.to_socket.name) for link in links),
                'nodes': sorted((node.name, node.bl_idname, getattr(node, 'space', ''),
                                 [(socket.name, value(socket)) for socket in (*node.inputs, *node.outputs)
                                  if hasattr(socket, 'default_value')]) for node in nodes),
                'mode': material.displacement_method, 'mesh_sha256': hashlib.sha256(points.tobytes()).hexdigest(),
                'uv_layers': uv_layers}
    def compare_render(tag):
        original_graph = fingerprint()
        refs = {}
        scene.render.engine = 'CYCLES'
        for name in ('Normal', 'Depth'):
            compositor.links.new(render_layers.outputs[name], output.inputs['Image'])
            path = folder / (tag + '_' + name + '_CYCLES.exr')
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            image = bpy.data.images.load(str(path), check_existing=False)
            refs[name] = np.asarray(image.pixels[:], np.float32).reshape(height, width, 4).copy()
            bpy.data.images.remove(image)
            if name == 'Normal':
                scene.render.image_settings.file_format = 'PNG'
                bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=scene)
                scene.render.image_settings.file_format = 'OPEN_EXR'
        compositor.links.new(render_layers.outputs['Normal'], output.inputs['Image'])
        scene.render.engine = 'SUPERLUXCORE'
        errorlog.clear(False)
        scene.render.filepath = str(folder / (tag + '_Normal_SUPERLUXCORE.exr'))
        bpy.ops.render.render(write_still=True)
        scene.render.image_settings.file_format = 'PNG'
        bpy.data.images['Render Result'].save_render(str(folder / (tag + '_Normal_SUPERLUXCORE.png')), scene=scene)
        scene.render.image_settings.file_format = 'OPEN_EXR'
        ref_depth = refs['Depth'][:, :, 0]
        depth = captured['Depth'][:, :, 0]
        a = (ref_depth > 0) & (ref_depth < 100)
        b = (depth > 0) & (depth < 100)
        common = a & b
        # Exclude boundaries from pass error; silhouette is tested separately.
        interior = common.copy()
        for dy, dx in [(0, 2), (0, -2), (2, 0), (-2, 0)]:
            interior &= np.roll(common, (dy, dx), (0, 1))
        assert interior.sum() > 1000, (tag, interior.sum())
        record = {'case': tag, 'space': space, 'mode': material.displacement_method,
                  'finite': bool(all(np.isfinite(v).all() for v in captured.values())),
                  'normal_mae': float(np.abs(captured['Normal'][interior] - refs['Normal'][:, :, :3][interior]).mean()),
                  'depth_mae': float(np.abs(depth[interior] - ref_depth[interior]).mean()),
                  'silhouette_iou': float(common.sum() / (a | b).sum()),
                  'cycles_coverage': float(a.mean()), 'native_coverage': float(b.mean()),
                  'warnings': [w.message for w in errorlog.warnings],
                  'errors': [e.message for e in errorlog.errors], 'graph_unchanged': original_graph == fingerprint(),
                  'spectral': bool(cfg.config.spectral_enable), 'native_version': native.Version(),
                  'native_sha256': hashlib.sha256(Path(native.pysuperluxcore.__file__).read_bytes()).hexdigest()}
        for name, value in captured.items():
            np.save(folder / (tag + '_' + name + '_SUPERLUXCORE.npy'), value)
        # A different pixel filter may affect a thin boundary, but cannot hide wrong geometry.
        record['passed'] = (record['finite'] and record['graph_unchanged'] and not record['errors']
                            and record['silhouette_iou'] > .99 and record['depth_mae'] < .006
                            and record['normal_mae'] < .012)
        records.append(record)
        (folder / 'metrics.json').write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n')
        print('VECTOR_DISPLACEMENT_CHECK', json.dumps(record, ensure_ascii=False), flush=True)
        assert record['passed'], record
        if os.environ.get('SUPERLUXCORE_AUDIT_BEAUTY') == '1':
            compositor.links.new(render_layers.outputs['Image'], output.inputs['Image'])
            scene.render.image_settings.file_format = 'PNG'
            scene.cycles.samples = cfg.halt.samples = 64
            for renderer in ('CYCLES', 'SUPERLUXCORE'):
                scene.render.engine = renderer
                errorlog.clear(False)
                scene.render.filepath = str(folder / (tag + '_Beauty_' + renderer + '.png'))
                bpy.ops.render.render(write_still=True)
                assert not errorlog.errors, (tag, renderer, errorlog.errors)
            assert original_graph == fingerprint(), tag
            scene.cycles.samples = cfg.halt.samples = 16
            scene.render.image_settings.file_format = 'OPEN_EXR'
    compare_render(tag)
    if tag == 'world_shared_instances' and os.environ.get('SUPERLUXCORE_AUDIT_MOVED') == '1':
        # Preserve graph and mesh data between F12 renders. A transform-only
        # cache patch must not leave shared geometry in an old world context.
        scene.frame_set(2)
        plane.location.x += .17
        plane.rotation_euler.z += .11
        plane.scale.z *= .8
        compare_render(tag + '_moved')
print('VECTOR_DISPLACEMENT_PASS', len(records), flush=True)
