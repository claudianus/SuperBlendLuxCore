# SPDX-License-Identifier: Apache-2.0
"""Unchanged constant arithmetic SSS inputs preserve the local diffuse limit.

Positive, exact-threshold and dynamic conditions are export controls only.
"""
from pathlib import Path
import os
setup = Path(__file__).with_name('cycles-zero-render-test.py').read_text()
assert setup.count('for case in (') == 1
exec(compile(setup.split('for case in (')[0], '<sss-expression-scene>', 'exec'))
reader = importlib.import_module(package + '.export.cycles_node_reader')
baseline = os.environ.get('SUPERLUXCORE_AUDIT_BASELINE') == '1'
cases = [
    ('add_scale_zero', 'ADD', (0.0, 0.0), 'Scale', 'matte'),
    ('subtract_scale_zero', 'SUBTRACT', (0.25, 0.25), 'Scale', 'matte'),
    ('multiply_scale_zero', 'MULTIPLY', (0.0, 0.15), 'Scale', 'matte'),
    ('divide_scale_zero', 'DIVIDE', (0.0, 2.0), 'Scale', 'matte'),
    ('add_radius_zero', 'ADD', (0.0, 0.0), 'Radius', 'matte'),
    ('subtract_radius_zero', 'SUBTRACT', (0.25, 0.25), 'Radius', 'matte'),
    ('add_scale_positive', 'ADD', (0.1, 0.05), 'Scale', 'openpbr'),
    ('subtract_scale_positive', 'SUBTRACT', (0.25, 0.1), 'Scale', 'openpbr'),
    ('tiny_scale_math', 'MULTIPLY', (1e-09, 1.0), 'Scale', 'matte'),
    ('clamp_negative_scale', 'ADD', (-1.0, 0.0), 'Scale', 'matte'),
    ('clamp_positive_scale', 'ADD', (0.1, 0.05), 'Scale', 'openpbr'),
    ('exact_threshold_scale', 'ADD', (1.0, 0.0), 'Scale', 'openpbr'),
    ('dynamic_add_scale', 'ADD', (0.0, 0.0), 'Scale', 'openpbr'),
    ('nested_scale_zero', 'SUBTRACT', (0.5, 0.5), 'Scale', 'matte'),
    ('radius_tiny_math', 'MULTIPLY', (1e-09, 1.0), 'Radius', 'matte'),
    ('value_sub_scale_zero', 'SUBTRACT', (0.25, 0.25), 'Scale', 'matte'),
    ('rgb_sub_scale_zero', 'SUBTRACT', (0.25, 0.25), 'Scale', 'matte'),
    ('vector_sub_radius_zero', 'SUBTRACT', (0.25, 0.25), 'Radius', 'matte'),
]
rows = []
for case, operation, values, dest, expected_type in cases:
    if os.environ.get('SUPERLUXCORE_AUDIT_CASES') and case not in os.environ['SUPERLUXCORE_AUDIT_CASES'].split(','):
        continue
    nodes, links = (mat.node_tree.nodes, mat.node_tree.links)
    nodes.clear()
    target = nodes.new('ShaderNodeSubsurfaceScattering')
    target.inputs['Scale'].default_value = 0.15
    target.inputs['Color'].default_value = (0.45, 0.45, 0.45, 1.0)
    target.inputs['Roughness'].default_value = 0.0
    n = nodes.new('ShaderNodeVectorMath' if case.startswith('vector_') else 'ShaderNodeMath')
    n.operation = operation
    for j, v in enumerate(values):
        n.inputs[j].default_value = (v, v, v) if case.startswith('vector_') else v
    if case.startswith('clamp_'):
        n.use_clamp = True
    if case == 'exact_threshold_scale':
        target.inputs['Radius'].default_value = (1e-08, 1e-08, 1e-08)
    if case == 'dynamic_add_scale':
        coords = nodes.new('ShaderNodeTexCoord')
        split = nodes.new('ShaderNodeSeparateXYZ')
        links.new(coords.outputs['UV'], split.inputs[0])
        links.new(split.outputs['X'], n.inputs[0])
    if case == 'nested_scale_zero':
        inner = nodes.new('ShaderNodeMath')
        inner.operation = 'ADD'
        inner.inputs[0].default_value = 0.25
        inner.inputs[1].default_value = 0.25
        links.new(inner.outputs[0], n.inputs[0])
    if case.startswith(('value_', 'rgb_')):
        for j, v in enumerate(values):
            operand = nodes.new('ShaderNodeRGB' if case.startswith('rgb_') else 'ShaderNodeValue')
            operand.outputs[0].default_value = (v, v, v, 1.0) if case.startswith('rgb_') else v
            links.new(operand.outputs[0], n.inputs[j])
    links.new(n.outputs[0], target.inputs[dest])
    out = nodes.new('ShaderNodeOutputMaterial')
    links.new(target.outputs[0], out.inputs['Surface'])
    before = fingerprint(nodes, links)
    log.clear(False)
    properties = native.Properties()
    name = reader._node(target, target.outputs[0], properties, mat, obj.name)
    assert not log.errors and (not log.warnings), (log.errors, log.warnings)
    export_type = properties.Get('scene.materials.' + name + '.type').GetString()
    record = {
        'case': case,
        'expected_type': expected_type,
        'export_type': export_type,
        'passed': export_type == expected_type,
        'graph_unchanged': True,
        'native_version': native.Version(),
        'native_sha256': hashlib.sha256(Path(native.pysuperluxcore.__file__).read_bytes()).hexdigest(),
        'reader_sha256': hashlib.sha256(Path(reader.__file__).read_bytes()).hexdigest(),
        'errors': [],
        'render_verified': False,
        'spectral': True,
        'resolution': [1280, 720],
        'samples': 64,
    }
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
            assert np.isfinite(pixels).all() and (not log.errors)
            assert all((w.message.startswith('Light-probe-volume') for w in log.warnings)), [w.message for w in log.warnings]
            means[engine] = float(pixels.mean())
            s.render.image_settings.file_format = 'PNG'
            bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
            s.render.image_settings.file_format = 'OPEN_EXR'
            assert before == fingerprint(nodes, links)
        ratio = means['SUPERLUXCORE'] / max(means['CYCLES'], 1e-08)
        record.update(means=means, native_cycles_mean_ratio=ratio, render_verified=True)
        record['passed'] &= abs(ratio - 1) < 0.025
    assert before == fingerprint(nodes, links)
    rows.append(record)
    (folder / 'metrics.json').write_text(json.dumps(rows, indent=2) + '\n')
    print('SSS_EXPRESSION', record, flush=True)
    if not baseline:
        assert record['passed'], record
print('SSS_EXPRESSION_COMPLETE', len(rows), sum((r['passed'] for r in rows)), flush=True)
