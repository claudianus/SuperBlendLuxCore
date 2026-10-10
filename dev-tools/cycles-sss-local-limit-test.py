# SPDX-License-Identifier: Apache-2.0
"""Standalone SSS all-channel local diffuse limit, unchanged Cycles graphs.

Reuse the zero-input suite's fixed 720p spectral scene. Positive/partial
radii and the exact threshold are export controls, not accepted SSS renders.
"""
from pathlib import Path
import os

setup = Path(__file__).with_name('cycles-zero-render-test.py').read_text()
assert setup.count('for case in (') == 1
exec(compile(setup.split('for case in (')[0], '<sss-local-limit-scene>', 'exec'))
reader = importlib.import_module(package + '.export.cycles_node_reader')
baseline = os.environ.get('SUPERLUXCORE_AUDIT_BASELINE') == '1'
cases = [
    ('scale_tiny', 1e-9, (1.0, .2, .1), None, 'matte'),
    ('radius_zero', .15, (0.0, 0.0, 0.0), None, 'matte'),
    ('radius_tiny', .15, (1e-9, 2e-9, 3e-9), None, 'matte'),
    ('linked_scale_tiny', 1e-9, (1.0, .2, .1), 'Scale', 'matte'),
    ('linked_radius_zero', .15, (0.0, 0.0, 0.0), 'Radius', 'matte'),
    ('linked_radius_tiny', .15, (1e-9, 1e-9, 1e-9), 'Radius', 'matte'),
    ('textured_scale_radius_zero', .15, (0.0, 0.0, 0.0), 'scale_texture', 'matte'),
    ('rgb_radius_zero', .15, (0.0, 0.0, 0.0), 'radius_rgb', 'matte'),
    ('scaled_below_threshold', .5, (1e-8, 1e-8, 1e-8), None, 'matte'),
    ('radius_zero_linked_normal', .15, (0.0, 0.0, 0.0), 'normal', 'matte'),
    ('exact_threshold', 1.0, (1e-8, 1e-8, 1e-8), None, 'openpbr'),
    ('partial_zero', .15, (0.0, .2, .1), None, 'openpbr'),
    ('ordinary_positive', .15, (1.0, .2, .1), None, 'openpbr'),
]
rows = []
for case, scale, radius, linked, expected_type in cases:
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    target = nodes.new('ShaderNodeSubsurfaceScattering')
    target.inputs['Color'].default_value = (.45, .45, .45, 1.0)
    target.inputs['Scale'].default_value = scale
    target.inputs['Radius'].default_value = radius
    target.inputs['Roughness'].default_value = 0.0
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(target.outputs[0], out.inputs['Surface'])
    if linked in ('Scale', 'Radius'):
        value = nodes.new('ShaderNodeValue')
        value.outputs[0].default_value = scale if linked == 'Scale' else radius[0]
        links.new(value.outputs[0], target.inputs[linked])
    elif linked == 'scale_texture':
        coords = nodes.new('ShaderNodeTexCoord')
        split = nodes.new('ShaderNodeSeparateXYZ')
        links.new(coords.outputs['UV'], split.inputs[0])
        offset = nodes.new('ShaderNodeMath')
        offset.operation = 'ADD'
        offset.inputs[1].default_value = .15
        links.new(split.outputs['X'], offset.inputs[0])
        links.new(offset.outputs[0], target.inputs['Scale'])
    elif linked == 'radius_rgb':
        value = nodes.new('ShaderNodeRGB')
        value.outputs[0].default_value = (*radius, 1.0)
        links.new(value.outputs[0], target.inputs['Radius'])
    elif linked == 'normal':
        normal = nodes.new('ShaderNodeNormalMap')
        normal.inputs['Color'].default_value = (.65, .6, .9, 1.0)
        links.new(normal.outputs['Normal'], target.inputs['Normal'])
    before = fingerprint(nodes, links)
    log.clear(False)
    properties = native.Properties()
    name = reader._node(target, target.outputs[0], properties, mat, obj.name)
    export_type = properties.Get('scene.materials.' + name + '.type').GetString()
    record = {'case': case, 'expected_type': expected_type, 'export_type': export_type,
              'passed': export_type == expected_type, 'graph_unchanged': True,
              'native_version': native.Version(),
              'native_sha256': hashlib.sha256(Path(native.pysuperluxcore.__file__).read_bytes()).hexdigest(),
              'reader_sha256': hashlib.sha256(Path(reader.__file__).read_bytes()).hexdigest(),
              'errors': [], 'render_verified': False}
    if expected_type == 'matte':
        means = {}
        for engine in ('CYCLES', 'SUPERLUXCORE'):
            s.render.engine = engine
            log.clear(False)
            path = folder / (case + '_' + engine + '.exr')
            s.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            image = bpy.data.images.load(str(path), check_existing=False)
            pixels = np.asarray(image.pixels[:], np.float32).reshape(720, 1280, 4)[:, :, :3].copy()
            bpy.data.images.remove(image)
            assert np.isfinite(pixels).all() and not log.errors
            assert all(w.message.startswith('Light-probe-volume') for w in log.warnings), [w.message for w in log.warnings]
            means[engine] = float(pixels.mean())
            s.render.image_settings.file_format = 'PNG'
            bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
            s.render.image_settings.file_format = 'OPEN_EXR'
            assert before == fingerprint(nodes, links)
        ratio = means['SUPERLUXCORE'] / max(means['CYCLES'], 1e-8)
        record.update(means=means, native_cycles_mean_ratio=ratio, render_verified=True)
        record['passed'] &= abs(ratio - 1) < .025
    assert before == fingerprint(nodes, links)
    rows.append(record)
    (folder / 'metrics.json').write_text(json.dumps(rows, indent=2) + '\n')
    print('SSS_LOCAL_LIMIT', record, flush=True)
    if not baseline:
        assert record['passed'], record
print('SSS_LOCAL_LIMIT_COMPLETE', len(rows), sum(r['passed'] for r in rows), flush=True)
