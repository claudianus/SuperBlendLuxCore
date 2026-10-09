"""Cycles 설정 가져오기·카메라·컴포지터 패스의 배포본 연결을 검수한다."""
import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import bpy
import pysuperluxcore as lux

package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore') or a.module == 'superluxcore')
base = importlib.import_module(package + '.engine.base')
final = importlib.import_module(package + '.engine.final')
aovs = importlib.import_module(package + '.export.aovs')
compat = importlib.import_module(package + '.export.cycles_compat')
camera = importlib.import_module(package + '.export.camera')
reader = importlib.import_module(package + '.export.cycles_node_reader')
vlutils = importlib.import_module(package + '.utils.view_layer')
log = importlib.import_module(package + '.utils.errorlog').SuperLuxCoreErrorLog
s = bpy.context.scene
s.render.engine = 'SUPERLUXCORE'
cam = s.camera
layer = s.view_layers[0]
results = {}

class Recorder:
    is_preview = False
    aov_imagepipelines = {}
    def __init__(self):
        self.registered = []
        self.added = []
        self.lightgroup_cache = {0}
    def register_pass(self, scene, renderlayer, name, *args):
        self.registered.append(name)
    def add_pass(self, name, *args, **kwargs):
        self.added.append(name)

for flag, names in compat._PASS_OUTPUTS:
    if hasattr(layer, flag):
        setattr(layer, flag, True)
s.superluxcore.denoiser.enabled = False
s.superluxcore.config.sobol_adaptive_strength = 0
vlutils.State.active_view_layer = layer.name
rec = Recorder()
log.clear(False)
base.SuperLuxCoreRenderEngine.update_render_passes(rec, s, layer)
final._add_passes(rec, layer, s)
props = aovs.convert(rec, s, engine=rec)
results['passes'] = {'requested': sorted(compat.cycles_pass_outputs(layer, set())),
                     'registered': rec.registered, 'added': rec.added,
                     'film_props': str(props), 'warnings': [x.message for x in log.warnings]}

s.render.film_transparent = True
s.render.use_motion_blur = True
s.render.motion_blur_shutter = .75
s.cycles.max_bounces = 0
s.cycles.diffuse_bounces = 0
s.cycles.glossy_bounces = 0
s.cycles.transparent_max_bounces = 3
s.cycles.transmission_bounces = 7
before = {'film': cam.data.superluxcore.imagepipeline.transparent_film,
          'motion': cam.data.superluxcore.motion_blur.enable,
          'shutter': cam.data.superluxcore.motion_blur.shutter}
bpy.ops.superluxcore.import_cycles_settings()
path = s.superluxcore.config.path
results['settings_import'] = {'cycles_film_location': 'scene.render.film_transparent',
                             'cycles_has_film_transparent': hasattr(s.cycles, 'film_transparent'),
                             'cycles_has_transparent_bounces': hasattr(s.cycles, 'transparent_bounces'),
                             'cycles_transparent_max_bounces': s.cycles.transparent_max_bounces,
                             'before': before, 'after': {'film': cam.data.superluxcore.imagepipeline.transparent_film,
                             'motion': cam.data.superluxcore.motion_blur.enable,
                             'shutter': cam.data.superluxcore.motion_blur.shutter,
                             'depth_total': path.depth_total, 'depth_diffuse': path.depth_diffuse,
                             'depth_glossy': path.depth_glossy, 'depth_specular': path.depth_specular}}

cam.data.dof.use_dof = True
cam.data.dof.aperture_blades = 7
cam.data.dof.aperture_ratio = 2
cam.data.dof.aperture_rotation = .3
defs = {}
camera._depth_of_field(s, defs)
results['dof'] = {'requested': {'blades': 7, 'ratio': 2, 'rotation': .3}, 'exported': defs}
cam.data.type = 'PANO'
cam.data.panorama_type = 'EQUIRECTANGULAR'
cam.data.longitude_min = -.5
cam.data.longitude_max = 1.5
defs = {}
camera._pano_compat(cam.data, defs, cam.name)
results['panorama'] = {'longitude_min': -.5, 'longitude_max': 1.5, 'exported': defs}

mat = bpy.data.materials.new('볼륨 조합 검수')
mat.use_nodes = True
tree = mat.node_tree
tree.nodes.clear()
absorb = tree.nodes.new('ShaderNodeVolumeAbsorption')
absorb.inputs['Color'].default_value = (.2, .4, .6, 1)
scatter = tree.nodes.new('ShaderNodeVolumeScatter')
mix = tree.nodes.new('ShaderNodeMixShader')
mix.inputs[0].default_value = .25
add = tree.nodes.new('ShaderNodeAddShader')
tree.links.new(absorb.outputs[0], add.inputs[0])
tree.links.new(scatter.outputs[0], add.inputs[1])
tree.links.new(absorb.outputs[0], mix.inputs[1])
tree.links.new(scatter.outputs[0], mix.inputs[2])
results['volume_combinations'] = {}
for node in (add, mix):
    props = lux.Properties()
    log.clear(False)
    defs = reader._volume(node, node.outputs[0], props, mat, 'volume_audit', '')
    results['volume_combinations'][node.bl_idname] = {'definitions': defs, 'props': str(props), 'warnings': [x.message for x in log.warnings]}
tree.links.remove(mix.inputs[1].links[0])
results['volume_combinations']['mix_single_child'] = reader._volume(mix, mix.outputs[0], lux.Properties(), mat, 'single', '')
pv = tree.nodes.new('ShaderNodeVolumePrincipled')
pv.inputs['Blackbody Intensity'].default_value = 1
pv.inputs['Temperature'].default_value = 1500
log.clear(False)
props = lux.Properties()
results['principled_volume_blackbody'] = {'definitions': reader._volume(pv, pv.outputs[0], props, mat, 'blackbody', ''), 'props': str(props), 'warnings': [x.message for x in log.warnings]}

# 같은 표시 이름을 가진 그룹 출력도 식별자로 구분되어야 한다.
group_tree = bpy.data.node_groups.new('중복 이름 검수', 'ShaderNodeTree')
for _ in range(2):
    group_tree.interface.new_socket(name='같은 이름', in_out='OUTPUT', socket_type='NodeSocketFloat')
group_output = group_tree.nodes.new('NodeGroupOutput')
for index, value in enumerate((.1, .8)):
    source = group_tree.nodes.new('ShaderNodeValue')
    source.outputs[0].default_value = value
    group_tree.links.new(source.outputs[0], group_output.inputs[index])
group_node = tree.nodes.new('ShaderNodeGroup')
group_node.node_tree = group_tree
group_props = lux.Properties()
results['duplicate_group_outputs'] = {'requested_output_index': 1, 'expected': .8,
    'output_names': [socket.name for socket in group_node.outputs],
    'exported': reader._node(group_node, group_node.outputs[1], group_props, mat, 'group_audit', '')}
results['duplicate_group_outputs']['props'] = str(group_props)

folder = Path(os.environ.get('SUPERLUXCORE_AUDIT_DIR', '/tmp/superluxcore-remaining-audit'))
folder.mkdir(parents=True, exist_ok=True)
(folder / 'workflow-audit.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
print('워크플로 검수', json.dumps(results, ensure_ascii=False), flush=True)
