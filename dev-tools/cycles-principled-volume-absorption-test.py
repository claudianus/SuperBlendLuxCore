"""Compare unchanged Principled Volume absorption to RGB slab transport.

Default spectral images remain separate color/quality review evidence.
Generated-volume coordinates have an independent unresolved context defect.
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
               if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
reader = importlib.import_module(package + '.export.cycles_node_reader')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def graph(tree):
    nodes = []
    for node in tree.nodes:
        inputs = []
        for socket in node.inputs:
            if not hasattr(socket, 'default_value'):
                continue
            value = socket.default_value
            if not isinstance(value, (float, int, str, bool)):
                value = list(value)
            inputs.append([socket.identifier, value])
        details = {}
        if node.bl_idname == 'ShaderNodeValToRGB':
            details['ramp'] = {'interpolation': node.color_ramp.interpolation,
                               'elements': [[item.position, list(item.color)] for item in node.color_ramp.elements]}
        if node.bl_idname == 'ShaderNodeTexCoord':
            details['object'] = node.object.name if node.object else None
            if node.object:
                details['object_matrix'] = [list(row) for row in node.object.matrix_world]
        nodes.append([node.name, node.bl_idname, inputs, details])
    links = sorted([link.from_node.name, link.from_socket.identifier,
                    link.to_node.name, link.to_socket.identifier] for link in tree.links)
    return hashlib.sha256(json.dumps([sorted(nodes), links], sort_keys=True).encode()).hexdigest()


bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.world = bpy.data.worlds.new('Unit white background')
scene.world.use_nodes = True
scene.world.node_tree.nodes['Background'].inputs['Color'].default_value = (1, 1, 1, 1)
scene.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
material = bpy.data.materials.new('Authored Principled Volume')
material.use_nodes = True
obj.data.materials.append(material)
bpy.ops.object.camera_add(location=(0, -5, 0))
scene.camera = bpy.context.object
scene.camera.rotation_euler = (1.5707963267948966, 0, 0)
scene.camera.data.type = 'ORTHO'
scene.camera.data.ortho_scale = 4
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.render.threads_mode = 'FIXED'
scene.render.threads = int(os.environ.get('SLC_ABSORPTION_THREADS', '4'))
assert 1 <= scene.render.threads <= 8
bpy.context.preferences.filepaths.save_version = 0
scene.cycles.samples = 64
scene.cycles.use_denoising = False
scene.view_settings.view_transform = 'Standard'
slc = scene.superluxcore
slc.config.engine = 'PATH'
slc.config.path.use_clamping = False
slc.config.path.auto_clamping = False
slc.halt.enable = True
slc.halt.use_samples = True
slc.halt.samples = 64
slc.denoiser.enabled = False
assert slc.config.spectral_enable

# Erode the known slab interior so camera filtering does not mix silhouettes.
x0, x1, y0, y1 = 350, 930, 75, 645
pixel_x = np.arange(x0, x1, dtype=np.float64) + .5
generated_x = ((-2 + 4 * pixel_x / 1280) + 1) / 2
records = []
native = Path(pysuperluxcore.pysuperluxcore.__file__).resolve()
identity = {'native_path': str(native),
            'native_sha256': sha(native),
            'reader_path': reader.__file__, 'reader_sha256': sha(reader.__file__),
            'harness_sha256': sha(__file__), 'resolution': [1280, 720],
            'analytic_rgb_only': True, 'cpu_threads': scene.render.threads, 'complete': False,
            'production_acceptance': False, 'records': records}

cases = os.environ.get('SLC_ABSORPTION_CASES',
    'fractional-constant,fractional-linked-object-gradient,limits-constant').split(',')
assert all(case in ['fractional-constant', 'fractional-linked-gradient',
                    'fractional-linked-object-gradient', 'limits-constant'] for case in cases)
for case in cases:
    tree = material.node_tree
    tree.nodes.clear()
    output = tree.nodes.new('ShaderNodeOutputMaterial')
    volume = tree.nodes.new('ShaderNodeVolumePrincipled')
    volume.inputs['Color'].default_value = (0, 0, 0, 1)
    volume.inputs['Density'].default_value = 1
    volume.inputs['Density Attribute'].default_value = ''
    volume.inputs['Color Attribute'].default_value = ''
    volume.inputs['Temperature Attribute'].default_value = ''
    low = np.array([.04, .25, .64])
    if case in ['fractional-linked-gradient', 'fractional-linked-object-gradient']:
        high = np.array([.81, .36, .09])
        coord = tree.nodes.new('ShaderNodeTexCoord')
        separate = tree.nodes.new('ShaderNodeSeparateXYZ')
        ramp = tree.nodes.new('ShaderNodeValToRGB')
        ramp.color_ramp.interpolation = 'LINEAR'
        ramp.color_ramp.elements[0].color = (*low, 1)
        ramp.color_ramp.elements[1].color = (*high, 1)
        if case == 'fractional-linked-object-gradient':
            # Independent authored coordinates expose the color operator.
            # The Generated volume-context failure has its own retained proof.
            reference = bpy.data.objects.new('Authored volume coordinate reference', None)
            scene.collection.objects.link(reference)
            reference.location = (-1, 0, 0)
            reference.scale = (2, 2, 2)
            bpy.context.view_layer.update()
            coord.object = reference
            tree.links.new(coord.outputs['Object'], separate.inputs[0])
        else:
            tree.links.new(coord.outputs['Generated'], separate.inputs[0])
        tree.links.new(separate.outputs['X'], ramp.inputs['Fac'])
        tree.links.new(ramp.outputs['Color'], volume.inputs['Absorption Color'])
        authored = low[None, :] * (1 - generated_x[:, None]) + high[None, :] * generated_x[:, None]
    else:
        if case == 'limits-constant':
            low = np.array([0, 1, 4.])
        volume.inputs['Absorption Color'].default_value = (*low, 1)
        authored = np.repeat(low[None, :], len(pixel_x), axis=0)
    tree.links.new(volume.outputs[0], output.inputs['Volume'])
    before = graph(tree)
    expected = np.exp(-2 * np.maximum(1 - np.sqrt(np.maximum(authored, 0)), 0))
    scene.render.engine = 'CYCLES'
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / (case + '.blend')))
    if os.environ.get('SLC_ABSORPTION_NATIVE_DEVICES'):
        devices = os.environ['SLC_ABSORPTION_NATIVE_DEVICES'].split(',')
        assert devices and all(device in ['CPU', 'OCL'] for device in devices)
    else:
        devices = ['CPU'] if os.environ.get('SLC_ABSORPTION_CPU_ONLY') == '1' else ['CPU', 'OCL']
    modes = [('CYCLES', 'CPU', False)] + [('SUPERLUXCORE', device, False) for device in devices]
    if case == 'fractional-constant' or os.environ.get('SLC_ABSORPTION_SPECTRAL_ALL', '1') == '1':
        modes.extend([('SUPERLUXCORE', device, True) for device in devices])
    for engine, device, spectral in modes:
        scene.render.engine = engine
        if engine == 'SUPERLUXCORE':
            slc.config.device = device
            slc.config.spectral_enable = spectral
            if device == 'OCL':
                bpy.context.preferences.addons[package].preferences.gpu_backend = 'METAL'
        label = case + '-' + engine.lower() + '-' + device.lower() + ('-spectral' if spectral else '-rgb')
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_depth = '32'
        scene.render.filepath = str(folder / (label + '.exr'))
        bpy.ops.render.render(write_still=True)
        assert graph(tree) == before, (case, engine, 'authored graph changed')
        image = bpy.data.images.load(scene.render.filepath, check_existing=False)
        pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[..., :3]
        bpy.data.images.remove(image)
        assert np.isfinite(pixels).all(), label
        body = pixels[y0:y1, x0:x1]
        mean = body.mean(axis=(0, 1), dtype=np.float64)
        ref = expected.mean(axis=0)
        error = float(np.max(np.abs(mean - ref) / np.maximum(ref, 1e-8)))
        # Wavelength transport has a separate meaning/quality review. The
        # exact RGB slab law establishes the authored absorption mapping.
        if not spectral:
            assert error < .01, (label, mean, ref, error)
        scene.render.image_settings.file_format = 'PNG'
        png = folder / (label + '.png')
        bpy.data.images['Render Result'].save_render(str(png), scene=scene)
        records.append({'case': case, 'engine': engine, 'device': device,
                        'spectral': spectral, 'graph_unchanged': True,
                        'graph_sha256': before, 'finite': True,
                        'body_mean': mean.tolist(), 'analytic_rgb_body_mean': ref.tolist(),
                        'relative_mean_error': error, 'analytic_gate_applied': not spectral,
                        'passed': True, 'png': str(png), 'png_sha256': sha(png)})
        (folder / 'metrics.json').write_text(json.dumps(identity, indent=2) + '\n')
        print('ABSORPTION_SLAB_PASS', label, error, flush=True)
        del pixels, body

identity['complete'] = True
(folder / 'metrics.json').write_text(json.dumps(identity, indent=2) + '\n')
print('ABSORPTION_SLAB_COMPLETE_REQUIRES_DIRECT_REVIEW', len(records), flush=True)
