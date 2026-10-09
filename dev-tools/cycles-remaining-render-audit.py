"""잔여 노드 의미 차이를 720p Cycles·배포본 렌더로 측정하여 실패도 보존한다."""
import json
import os
from pathlib import Path
import traceback
import importlib
import bpy
import numpy as np
package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
errorlog = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog

folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/superluxcore-remaining-render-audit'))
folder.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
s = bpy.context.scene
s.world = bpy.data.worlds.new('검수 월드')
s.world.use_nodes = True
s.world.node_tree.nodes['Background'].inputs['Strength'].default_value = 0
bpy.ops.mesh.primitive_plane_add(size=30)
plane = bpy.context.object
m = bpy.data.materials.new('잔여 호환 영상 검수')
m.use_nodes = True
plane.data.materials.append(m)
bpy.ops.object.camera_add(location=(1.2, 0, 3))
cam = bpy.context.object
cam.rotation_euler = (-cam.location).to_track_quat('-Z', 'Y').to_euler()
cam.data.lens = 65
s.camera = cam
s.render.resolution_x = 1280
s.render.resolution_y = 720
s.render.resolution_percentage = 100
s.view_settings.view_transform = 'Standard'
s.render.image_settings.file_format = 'OPEN_EXR'
s.render.image_settings.color_depth = '32'
s.cycles.samples = 16
s.cycles.use_denoising = False

cases = [("layer_fresnel", x) for x in (.2, .5, .8)] + [("layer_facing", x) for x in (.2, .5, .8)]
cases += [('hsv_fac', x) for x in (0, .25, 1)]
cases += [('ramp_alpha', .3), ('ramp_hsv', .3), ('ramp_ease', .3), ('floatcurve_fac', 0), ('floatcurve_fac', .25), ('vectorcurve', .25), ('gamma', 2), ('noise1d', 0), ('magic', 0), ('maprange_vector', 0), ('vector_sign', 0), ('vector_power', 0)]
cases += [('rgba_clamp_result', 1), ('rgba_factor_extrapolate', 1.5), ('rgba_screen', .5), ('white3d', 0)]

# 연결 입력은 GPU 테이블 분할과 스칼라 비교 경로를 실제로 통과한다.
cases += [('ramp_linked_hsv', 0), ('curve_linked', 0), ('vector_sign_mixed', 0)]
cases += [('rgba_blend', mode) for mode in ('MULTIPLY', 'DIVIDE', 'OVERLAY', 'DARKEN', 'LIGHTEN', 'DIFFERENCE', 'EXCLUSION', 'DODGE', 'BURN', 'SOFT_LIGHT', 'LINEAR_LIGHT', 'HUE', 'SATURATION', 'COLOR', 'VALUE')]
cases += [('rgb_curve', .25)]
cases += [('maprange_mode', mode) for mode in ('LINEAR', 'STEPPED', 'SMOOTHSTEP', 'SMOOTHERSTEP')]
cases += [('white_dimensions', (dim, output, w)) for dim in ('1D', '2D', '3D', '4D') for output in ('Value', 'Color') for w in (-.37, .87)]

# 셀 난수의 픽셀 일치는 요구하지 않는다. 정규 격자는 거리·출력 수치를 별도로 확인한다.
cases += [('voronoi_grid', (dim, feature, output)) for dim in ('1D', '2D', '3D', '4D')
          for feature, output in (('F1', 'Distance'), ('F2', 'Distance'), ('SMOOTH_F1', 'Distance'),
                                  ('DISTANCE_TO_EDGE', 'Distance'), ('N_SPHERE_RADIUS', 'Radius'),
                                  ('F1', 'W' if dim == '1D' else 'Position'))]
cases += [('voronoi_w', feature) for feature in ('F1', 'F2')]
cases += [('voronoi_metric', metric) for metric in ('EUCLIDEAN', 'MANHATTAN', 'CHEBYCHEV', 'MINKOWSKI')]
cases += [('voronoi_fractal', (feature, normalize)) for feature in ('F1', 'F2', 'SMOOTH_F1', 'DISTANCE_TO_EDGE') for normalize in (False, True)]
cases += [('voronoi_cells', output) for output in ('Distance', 'Color', 'Position')]

def graph(kind, arg):
    n = m.node_tree.nodes
    l = m.node_tree.links
    n.clear()
    out = n.new('ShaderNodeOutputMaterial')
    em = n.new('ShaderNodeEmission')
    l.new(em.outputs[0], out.inputs['Surface'])
    if kind in {'ramp_linked_hsv', 'curve_linked'}:
        coordinates = n.new('ShaderNodeTexCoord')
        separate = n.new('ShaderNodeSeparateXYZ')
        l.new(coordinates.outputs['UV'], separate.inputs[0])
        scale = n.new('ShaderNodeMath')
        scale.operation = 'MULTIPLY'
        scale.inputs[1].default_value = 20
        l.new(separate.outputs[0], scale.inputs[0])
        fract = n.new('ShaderNodeMath')
        fract.operation = 'FRACT'
        l.new(scale.outputs[0], fract.inputs[0])
        if kind == 'ramp_linked_hsv':
            node = n.new('ShaderNodeValToRGB')
            node.color_ramp.color_mode = 'HSV'
            node.color_ramp.elements[0].color = (1, .1, .2, 1)
            node.color_ramp.elements[1].color = (.1, 1, .2, 1)
        else:
            node = n.new('ShaderNodeFloatCurve')
            node.mapping.curves[0].points.new(.3, .8)
            node.mapping.curves[0].points.new(.7, .2)
            node.mapping.update()
        l.new(fract.outputs[0], node.inputs[0 if kind == 'ramp_linked_hsv' else 1])
        source = node.outputs[0]
    elif kind == 'rgb_curve':
        node = n.new('ShaderNodeRGBCurve')
        node.inputs['Fac'].default_value = arg
        node.inputs['Color'].default_value = (.2, .4, .7, 1)
        node.mapping.curves[0].points[1].location = (1, .8)
        node.mapping.curves[3].points[0].location = (0, .1)
        node.mapping.curves[3].points[1].location = (1, .9)
        node.mapping.update()
        source = node.outputs[0]
    elif kind == 'maprange_mode':
        node = n.new('ShaderNodeMapRange')
        node.interpolation_type = arg
        node.clamp = False
        node.inputs['Value'].default_value = 1.5
        node.inputs['From Min'].default_value = 1
        node.inputs['From Max'].default_value = -1
        node.inputs['To Min'].default_value = .2
        node.inputs['To Max'].default_value = .8
        source = node.outputs[0]
    elif kind.startswith('layer_'):
        node = n.new('ShaderNodeLayerWeight')
        node.inputs['Blend'].default_value = arg
        source = node.outputs['Fresnel' if kind == 'layer_fresnel' else 'Facing']
    elif kind == 'hsv_fac':
        node = n.new('ShaderNodeHueSaturation')
        node.inputs['Hue'].default_value = .1
        node.inputs['Fac'].default_value = arg
        node.inputs['Color'].default_value = (.8, .2, .1, 1)
        source = node.outputs[0]
    elif kind.startswith('ramp_'):
        node = n.new('ShaderNodeValToRGB')
        node.inputs[0].default_value = arg
        node.color_ramp.elements[0].color = (1, 0, 0, .1)
        node.color_ramp.elements[1].color = (0, 1, 0, .9)
        if kind == 'ramp_hsv':
            node.color_ramp.color_mode = 'HSV'
        if kind == 'ramp_ease':
            node.color_ramp.interpolation = 'EASE'
        source = node.outputs['Alpha' if kind == 'ramp_alpha' else 'Color']
    elif kind in {'floatcurve_fac', 'vectorcurve'}:
        node = n.new('ShaderNodeFloatCurve' if kind == 'floatcurve_fac' else 'ShaderNodeVectorCurve')
        node.mapping.initialize()
        for curve in node.mapping.curves:
            curve.points[0].location = (0, .2)
            curve.points[1].location = (1, .8)
        node.mapping.update()
        node.inputs[0].default_value = arg
        node.inputs[1].default_value = .7 if kind == 'floatcurve_fac' else (.2, .4, .7)
        source = node.outputs[0]
    elif kind == 'gamma':
        node = n.new('ShaderNodeGamma')
        node.inputs['Color'].default_value = (.2, .4, .7, 1)
        node.inputs['Gamma'].default_value = arg
        source = node.outputs[0]
    elif kind.startswith('voronoi_'):
        node = n.new('ShaderNodeTexVoronoi')
        if kind == 'voronoi_grid':
            dim, feature, output = arg
        elif kind == 'voronoi_w':
            dim, feature, output = '4D', arg, 'W'
        else:
            dim = '3D'
            feature = arg[0] if kind == 'voronoi_fractal' else 'F1'
            output = arg if kind == 'voronoi_cells' else 'Distance'
        node.voronoi_dimensions = dim
        node.feature = feature
        node.normalize = arg[1] if kind == 'voronoi_fractal' else False
        node.distance = arg if kind == 'voronoi_metric' else 'EUCLIDEAN'
        if node.inputs.get('Detail') and node.inputs['Detail'].enabled:
            node.inputs['Detail'].default_value = 2.3 if kind == 'voronoi_fractal' else 0.
        if node.inputs.get('Smoothness') and node.inputs['Smoothness'].enabled:
            node.inputs['Smoothness'].default_value = .4
        if node.inputs.get('Exponent') and node.inputs['Exponent'].enabled:
            node.inputs['Exponent'].default_value = 1.5
        scale = n.new('ShaderNodeValue')
        scale.outputs[0].default_value = 80. if kind == 'voronoi_cells' else 2.
        l.new(scale.outputs[0], node.inputs['Scale'])
        randomness = n.new('ShaderNodeValue')
        randomness.outputs[0].default_value = .8 if kind == 'voronoi_cells' else 0.
        l.new(randomness.outputs[0], node.inputs['Randomness'])
        if node.inputs.get('Vector'):
            if kind == 'voronoi_cells':
                texcoord = n.new('ShaderNodeTexCoord')
                l.new(texcoord.outputs['UV'], node.inputs['Vector'])
            else:
                vector = n.new('ShaderNodeCombineXYZ')
                for socket, value in zip(vector.inputs, (.13, .27, .39)):
                    socket.default_value = value
                l.new(vector.outputs[0], node.inputs['Vector'])
        if node.inputs.get('W'):
            value = n.new('ShaderNodeValue')
            value.outputs[0].default_value = .41 if kind == 'voronoi_w' else .23
            l.new(value.outputs[0], node.inputs['W'])
        source = node.outputs[output]
    elif kind == 'noise1d':
        node = n.new('ShaderNodeTexNoise')
        node.noise_dimensions = '1D'
        node.inputs['W'].default_value = .37
        source = node.outputs['Factor']
    elif kind == 'magic':
        node = n.new('ShaderNodeTexMagic')
        source = node.outputs[0]
    elif kind == 'maprange_vector':
        node = n.new('ShaderNodeMapRange')
        node.data_type = 'FLOAT_VECTOR'
        node.inputs['Vector'].default_value = (.2, .4, .7)
        source = node.outputs['Vector']
    elif kind.startswith('rgba_'):
        node = n.new('ShaderNodeMix')
        node.data_type = 'RGBA'
        node.blend_type = arg if kind == 'rgba_blend' else ('ADD' if kind == 'rgba_clamp_result' else ('SCREEN' if kind == 'rgba_screen' else 'MIX'))
        node.clamp_factor = kind != 'rgba_factor_extrapolate'
        node.clamp_result = kind == 'rgba_clamp_result'
        next(v for v in node.inputs if v.name == 'Factor' and v.enabled).default_value = .4 if kind == 'rgba_blend' else arg
        next(v for v in node.inputs if v.name == 'A' and v.enabled).default_value = (.8, .2, .4, 1)
        next(v for v in node.inputs if v.name == 'B' and v.enabled).default_value = (.1, .7, .35, 1) if kind == 'rgba_blend' else (.7, .7, .7, 1)
        source = next(v for v in node.outputs if v.enabled)
    elif kind == 'white_dimensions':
        node = n.new('ShaderNodeTexWhiteNoise')
        dim, output, w = arg
        node.noise_dimensions = dim
        vec = n.new('ShaderNodeCombineXYZ')
        for sock, val in zip(vec.inputs, (.1, -.2, .3)):
            sock.default_value = val
        if node.inputs.get('Vector'):
            l.new(vec.outputs[0], node.inputs['Vector'])
        if node.inputs.get('W'):
            value = n.new('ShaderNodeValue')
            value.outputs[0].default_value = w
            l.new(value.outputs[0], node.inputs['W'])
        source = node.outputs[output]
    elif kind == 'white3d':
        node = n.new('ShaderNodeTexWhiteNoise')
        vec = n.new('ShaderNodeCombineXYZ')
        for sock, val in zip(vec.inputs, (.1, .2, .3)):
            sock.default_value = val
        l.new(vec.outputs[0], node.inputs['Vector'])
        source = node.outputs['Color']
    else:
        node = n.new('ShaderNodeVectorMath')
        node.operation = 'SIGN' if kind in {'vector_sign', 'vector_sign_mixed'} else 'POWER'
        node.inputs[0].default_value = (-.2, 0, .7) if kind == 'vector_sign_mixed' else (.2, .4, .7)
        node.inputs[1].default_value = (2, 2, 2)
        source = node.outputs['Vector']
    if kind in {'maprange_mode', 'vector_sign_mixed'}:
        offset = n.new('ShaderNodeVectorMath')
        offset.operation = 'ADD'
        offset.inputs[1].default_value = (1, 1, 1)
        l.new(source, offset.inputs[0])
        source = offset.outputs[0]
    l.new(source, em.inputs['Color'])
    bpy.context.view_layer.update()

def render(engine, tag):
    s.render.engine = engine
    if engine == 'SUPERLUXCORE':
        cfg = s.superluxcore
        cfg.config.engine = 'PATH'
        cfg.config.device = os.environ.get('DEV', 'CPU')
        cfg.config.spectral_enable = os.environ.get('SUPERLUXCORE_AUDIT_SPECTRAL') == '1'
        cfg.halt.enable = True
        cfg.halt.use_time = False
        cfg.halt.use_noise_thresh = False
        cfg.halt.use_samples = True
        cfg.halt.samples = 16
        cfg.config.path.use_clamping = False
        cfg.config.path.auto_clamping = False
        cfg.denoiser.enabled = False
        cam.data.superluxcore.imagepipeline.tonemapper.enabled = False
    path = folder / (tag + '_' + engine + '.exr')
    path.unlink(missing_ok=True)
    errorlog.clear(False)
    s.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    if not path.exists():
        raise RuntimeError('렌더 파일이 생성되지 않았습니다')
    im = bpy.data.images.load(str(path), check_existing=False)
    pixels = np.asarray(im.pixels[:], dtype=np.float32).reshape(720, 1280, 4)[8:-8, 8:-8, :3].copy()
    bpy.data.images.remove(im)
    s.render.image_settings.file_format = 'PNG'
    s.render.image_settings.color_depth = '8'
    bpy.data.images['Render Result'].save_render(str(path.with_suffix('.png')), scene=s)
    s.render.image_settings.file_format = 'OPEN_EXR'
    s.render.image_settings.color_depth = '32'
    return pixels

records = []
selected = set(filter(None, os.environ.get('SUPERLUXCORE_AUDIT_CASES', '').split(',')))
for index, (kind, arg) in enumerate(cases):
    if selected and kind not in selected:
        continue
    tag = f'{index:02d}_{kind}_{arg}'
    record = {'case': kind, 'arg': arg, 'spectral': os.environ.get('SUPERLUXCORE_AUDIT_SPECTRAL') == '1'}
    try:
        graph(kind, arg)
        cy = render('CYCLES', tag)
        sl = render('SUPERLUXCORE', tag)
        error = np.abs(cy - sl)
        record.update(spectral=bool(s.superluxcore.config.spectral_enable), mae=float(error.mean()), p99=float(np.quantile(error, .99)), cycles_mean=cy.mean(axis=(0, 1), dtype=np.float64).tolist(), superluxcore_mean=sl.mean(axis=(0, 1), dtype=np.float64).tolist(), finite=bool(np.isfinite(sl).all()), warnings=[x.message for x in errorlog.warnings], errors=[x.message for x in errorlog.errors])
    except Exception:
        record['exception'] = traceback.format_exc()
    records.append(record)
    (folder / 'metrics.json').write_text(json.dumps(records, ensure_ascii=False, indent=2))
    print('잔여 영상 검수', record, flush=True)
print('잔여 영상 검수 완료', len(records), flush=True)
