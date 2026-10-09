"""Blender 등록 노드의 출력·열거 모드·연결 입력을 실제 변환기로 검수한다."""
import importlib
import json
import os
from pathlib import Path
import traceback
import itertools

import bpy
import pysuperluxcore as lux

package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
reader = importlib.import_module(package + '.export.cycles_node_reader')
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/superluxcore-remaining-audit'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.object
obj.name = '호환 검수 물체'
bpy.ops.object.camera_add(location=(0, 0, 5))
bpy.context.scene.camera = bpy.context.object
mat = bpy.data.materials.new('호환 검수 재질')
mat.use_nodes = True
obj.data.materials.append(mat)
tree = mat.node_tree
inventory = []
records = []
image = bpy.data.images.new('검수 이미지', width=4, height=4)
image.pixels[:] = [.2, .4, .7, .6] * 16
image.pack()
enum_fields = {'operation', 'data_type', 'blend_type', 'factor_mode', 'distribution',
               'subsurface_method', 'component', 'parametrization', 'model', 'space',
               'rotation_type', 'convert_from', 'convert_to', 'vector_type',
               'gradient_type', 'wave_type', 'bands_direction', 'rings_direction',
               'wave_profile', 'noise_dimensions', 'noise_type', 'normalize',
               'voronoi_dimensions', 'feature', 'distance', 'gabor_type',
               'interpolation', 'interpolation_type', 'mode', 'extension',
               'projection', 'attribute_type', 'direction_type', 'axis', 'fresnel_type', 'sky_type'}

def value(socket):
    v = getattr(socket, 'default_value', None)
    try:
        return list(v)
    except TypeError:
        return v if isinstance(v, (str, float, int, bool, type(None))) else str(v)

def state(node):
    return {'inputs': [{'name': s.name, 'identifier': s.identifier, 'type': s.bl_idname,
                        'enabled': s.enabled, 'default': value(s)} for s in node.inputs],
            'outputs': [{'name': s.name, 'type': s.bl_idname, 'enabled': s.enabled} for s in node.outputs]}

def make(kind, setting):
    tree.nodes.clear()
    n = tree.nodes.new(kind)
    if kind in {'ShaderNodeTexImage', 'ShaderNodeTexEnvironment'}:
        n.image = image
    for key, val in setting.items():
        setattr(n, key, val)
    return n

def linked(node, index):
    s = node.inputs[index]
    if s.type == 'SHADER':
        source = tree.nodes.new('ShaderNodeBsdfDiffuse').outputs[0]
    elif s.type in {'VECTOR', 'RGBA'}:
        source = tree.nodes.new('ShaderNodeRGB').outputs[0]
    else:
        v = tree.nodes.new('ShaderNodeValue')
        v.outputs[0].default_value = 0.37
        source = v.outputs[0]
    tree.links.new(source, s)

for kind in sorted(n for n in dir(bpy.types) if n.startswith('ShaderNode')):
    try:
        n = make(kind, {})
    except Exception as e:
        inventory.append({'node': kind, 'creation_error': str(e)})
        continue
    enums = {}
    for p in n.bl_rna.properties:
        if p.identifier in enum_fields and p.type == 'ENUM':
            enums[p.identifier] = [v.identifier for v in p.enum_items if v.identifier]
    inventory.append({'node': kind, **state(n), 'enum': enums})
    settings = [{}] + [{k: v} for k, vals in enums.items() for v in vals if v != getattr(n, k)]
    for key in ('use_clamp', 'clamp_factor', 'clamp_result', 'clamp', 'invert', 'use_pixel_size', 'normalize', 'inside', 'only_local'):
        if hasattr(n, key):
            settings.append({key: not getattr(n, key)})
    grids = {
        'ShaderNodeMix': {'data_type': ['RGBA'], 'blend_type': enums.get('blend_type', []), 'clamp_factor': [False, True], 'clamp_result': [False, True]},
        'ShaderNodeTexNoise': {'noise_dimensions': enums.get('noise_dimensions', []), 'noise_type': enums.get('noise_type', []), 'normalize': [False, True]},
        'ShaderNodeBsdfHairPrincipled': {'model': enums.get('model', []), 'parametrization': enums.get('parametrization', [])},
        'ShaderNodeMapRange': {'data_type': enums.get('data_type', []), 'interpolation_type': enums.get('interpolation_type', []), 'clamp': [False, True]},
    }
    grid = grids.get(kind)
    if grid:
        settings += [dict(zip(grid, v)) for v in itertools.product(*grid.values())]
    settings = list({json.dumps(s, sort_keys=True): s for s in settings}.values())
    for setting in settings:
        try:
            n = make(kind, setting)
        except (TypeError, ValueError) as e:
            records.append({'node': kind, 'setting': setting, 'unavailable_mode': str(e), 'warnings': []})
            continue
        outputs = [i for i, s in enumerate(n.outputs) if s.enabled and s.type != 'CUSTOM']
        variants = [None] + ([i for i, s in enumerate(n.inputs) if s.enabled and s.type not in {'CUSTOM', 'STRING'}] if not setting else [])
        for linked_index in variants:
            for oi in outputs:
                n = make(kind, setting)
                if linked_index is not None:
                    linked(n, linked_index)
                out = n.outputs[oi]
                log.clear(False)
                props = lux.Properties()
                record = {'node': kind, 'setting': setting, 'output': out.name,
                          'linked_input': n.inputs[linked_index].name if linked_index is not None else None,
                          'linked_identifier': n.inputs[linked_index].identifier if linked_index is not None else None}
                try:
                    if out.type == 'SHADER' and kind.startswith('ShaderNodeVolume'):
                        result = reader._volume(n, out, props, mat, 'audit', obj.name)
                    else:
                        result = reader._node(n, out, props, mat, 'audit', obj.name)
                    record['result'] = str(result)
                    record['props'] = str(props)
                except Exception:
                    record['exception'] = traceback.format_exc()
                record['warnings'] = [e.message for e in log.warnings]
                records.append(record)
    print('검수', kind, '누적', len(records), flush=True)

(folder / 'node-inventory.json').write_text(json.dumps({'blender': bpy.app.version_string, 'engine': lux.Version(), 'reader': reader.__file__, 'nodes': inventory}, ensure_ascii=False, indent=2))
(folder / 'node-export-audit.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
exceptions = [r for r in records if 'exception' in r]
warnings = [r for r in records if r['warnings']]
print('전체 검수', len(inventory), '개 유형', len(records), '조건', '예외', len(exceptions), '경고', len(warnings), flush=True)
