# SPDX-License-Identifier: Apache-2.0
"""Constant RGB/Vector to SSS Scale keeps the local diffuse meaning.

Six paired 720p spectral conditions and four export-only controls. Positive
SSS and dynamic inputs are routing controls, not visual acceptance.
"""
from pathlib import Path
import os

setup = Path(__file__).with_name('cycles-zero-render-test.py').read_text()
assert setup.count('for case in (') == 1
exec(compile(setup.split('for case in (')[0], '<sss-local-limit-scene>', 'exec'))
reader = importlib.import_module(package + '.export.cycles_node_reader')
baseline = os.environ.get('SUPERLUXCORE_AUDIT_BASELINE') == '1'
cases = [
    ('rgb_scale_zero', .15, (1.0, .2, .1), 'scale_rgb_zero', 'matte'),
    ('rgb_scale_tiny', 1e-9, (1.0, .2, .1), 'scale_rgb', 'matte'),
    ('rgb_green_scale_tiny', 1e-9, (1.0, .2, .1), 'scale_rgb_green', 'matte'),
    ('vector_scale_zero', 0., (1.0, .2, .1), 'scale_vector', 'matte'),
    ('vector_scale_tiny', 1e-9, (1.0, .2, .1), 'scale_vector', 'matte'),
    ('rgb_scale_zero_normal', .15, (1.0, .2, .1), 'scale_rgb_zero_normal', 'matte'),
    ('rgb_scale_exact_threshold', 1., (1e-8, 1e-8, 1e-8), 'scale_rgb', 'openpbr'),
    ('rgb_scale_positive', .15, (1.0, .2, .1), 'scale_rgb', 'openpbr'),
    ('vector_scale_positive', .15, (1.0, .2, .1), 'scale_vector', 'openpbr'),
    ('dynamic_vector_scale', .15, (1.0, .2, .1), 'scale_dynamic_vector', 'openpbr'),
]
rows = []
for case, scale, radius, linked, expected_type in cases:
    if os.environ.get('SUPERLUXCORE_AUDIT_CASES') and case not in os.environ['SUPERLUXCORE_AUDIT_CASES'].split(','):
        continue
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    target = nodes.new('ShaderNodeSubsurfaceScattering')
    target.inputs['Color'].default_value = (.45, .45, .45, 1.0)
    target.inputs['Scale'].default_value = scale
    target.inputs['Radius'].default_value = radius
    target.inputs['Roughness'].default_value = 0.0
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(target.outputs[0], out.inputs['Surface'])
    if linked.startswith('scale_rgb'):
        value = nodes.new('ShaderNodeRGB')
        rgb = (0., 0., 0.) if 'zero' in linked else (scale, scale, scale)
        if linked == 'scale_rgb_green':
            rgb = (0., scale, 0.)
        value.outputs[0].default_value = (*rgb, 1.)
        links.new(value.outputs[0], target.inputs['Scale'])
        if linked.endswith('_normal'):
            normal = nodes.new('ShaderNodeNormalMap')
            normal.inputs['Color'].default_value = (.65, .6, .9, 1.)
            links.new(normal.outputs['Normal'], target.inputs['Normal'])
    elif linked == 'scale_vector':
        value = nodes.new('ShaderNodeCombineXYZ')
        for axis in ('X', 'Y', 'Z'):
            value.inputs[axis].default_value = scale
        links.new(value.outputs[0], target.inputs['Scale'])
    elif linked == 'scale_dynamic_vector':
        value = nodes.new('ShaderNodeTexCoord')
        links.new(value.outputs['UV'], target.inputs['Scale'])
    before = fingerprint(nodes, links)
    log.clear(False)
    properties = native.Properties()
    name = reader._node(target, target.outputs[0], properties, mat, obj.name)
    assert not log.errors, log.errors
    export_type = properties.Get('scene.materials.' + name + '.type').GetString()
    record = {'case': case, 'expected_type': expected_type, 'export_type': export_type,
              'passed': export_type == expected_type, 'graph_unchanged': True,
              'native_version': native.Version(),
              'native_sha256': hashlib.sha256(Path(native.pysuperluxcore.__file__).read_bytes()).hexdigest(),
              'reader_sha256': hashlib.sha256(Path(reader.__file__).read_bytes()).hexdigest(),
              'errors': [], 'render_verified': False, 'spectral': True,
              'resolution': [1280, 720], 'samples': 64}
    if expected_type == 'matte' and os.environ.get('SUPERLUXCORE_AUDIT_EXPORT_ONLY') != '1':
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
