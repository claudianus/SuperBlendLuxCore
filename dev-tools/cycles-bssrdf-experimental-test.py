# SPDX-License-Identifier: Apache-2.0
"""Private CPU/Metal diagnostic for unchanged Cycles RANDOM_WALK graphs.

The release adapter is deliberately left unchanged: default-quality/adjoint
transport and mixed closures still need implementation. This harness patches
only the in-process exporter, verifies the full staged package identity, then
runs the existing 720p literal/linked fixture without editing its Cycles graph.
"""
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import runpy

import bpy
import pysuperluxcore

identity_path = Path(os.environ['SUPERLUXCORE_BSSRDF_IDENTITY'])
identity = json.loads(identity_path.read_text())
for filename, digest in identity.get('source_files', {}).items():
    assert hashlib.sha256(Path(filename).read_bytes()).hexdigest() == digest, filename
profile = Path(os.environ['BLENDER_USER_RESOURCES']).resolve()
for relative, digest in identity['profile_files'].items():
    path = profile / relative
    assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest, path
native_path = Path(pysuperluxcore.pysuperluxcore.__file__).resolve()
assert native_path.is_relative_to(profile)
assert hashlib.sha256(native_path.read_bytes()).hexdigest() == identity['native_sha256']
assert pysuperluxcore.Version() == importlib.metadata.version('pysuperluxcore') == identity['version']
assert bpy.app.build_hash.decode() == identity['blender_build_hash']
package = next(a.module for a in bpy.context.preferences.addons
               if a.module.endswith('.superluxcore'))
reader = importlib.import_module(package + '.export.cycles_node_reader')
config = importlib.import_module(package + '.export.config')
utils = importlib.import_module(package + '.utils')
original_node = reader._node
original_config = config.convert
exported = []


def experimental_node(node, output_socket, props, material, superluxcore_name=None,
                      obj_name='', group_node_stack=None):
    if node.bl_idname != 'ShaderNodeSubsurfaceScattering':
        return original_node(node, output_socket, props, material,
                             superluxcore_name, obj_name, group_node_stack)
    if node.falloff != 'RANDOM_WALK':
        raise RuntimeError('Experimental BSSRDF currently implements RANDOM_WALK only')
    if superluxcore_name is None:
        superluxcore_name = str(node.as_pointer()) + output_socket.name
        for group in group_node_stack or ():
            superluxcore_name += str(group.as_pointer())
        superluxcore_name = utils.sanitize_superluxcore_name(superluxcore_name)
    definitions = {'type': 'cyclesbssrdf'}
    for name, key in (('Color', 'kd'), ('Radius', 'radius'), ('Scale', 'scale'),
                      ('IOR', 'ior'), ('Roughness', 'roughness'),
                      ('Anisotropy', 'anisotropy')):
        value = reader._socket(node.inputs[name], props, material, obj_name,
                               group_node_stack)
        if value is reader.ERROR_VALUE:
            raise RuntimeError('BSSRDF input could not be exported: ' + name)
        definitions[key] = value
    normal_socket = node.inputs['Normal']
    normal = reader._normal_input(normal_socket, props, material, obj_name, group_node_stack)
    # The unlinked zero is the ordinary shading-normal default. Serializing
    # it as a constant bump texture creates a false unsupported-bump context.
    if normal_socket.is_linked or not reader._is_zero(normal):
        definitions['bumptex'] = normal
    props.Set(utils.luxutils.create_props('scene.materials.' + superluxcore_name + '.',
                                         definitions))
    exported.append({'object': obj_name, 'material': material.name,
                     'node': node.name, 'method': node.falloff,
                     'definitions': definitions})
    return superluxcore_name


def experimental_config(*args, **kwargs):
    props = original_config(*args, **kwargs)
    # These are explicit limitations of a private diagnostic, not shipping
    # quality defaults and not production compatibility acceptance.
    device = os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE', 'CPU')
    assert device in ('CPU', 'METAL'), device
    overrides = {'renderengine.type': 'PATHCPU' if device == 'CPU' else 'PATHOCL',
                 'path.cyclesbssrdf.experimental.device.enable': device == 'METAL',
                 'opencl.cpu.use': False, 'opencl.gpu.use': True,
                 'path.cyclesbssrdf.experimental.enable': True,
                 'path.hybridbackforward.enable': False,
                 'path.lighttracing.enable': False,
                 'path.lighttracing.auto': False,
                 'path.lighttracing.only': False,
                 'path.mnee.enable': False,
                 'path.mnee.auto': False,
                 'path.photongi.caustic.enabled': False,
                 'path.photongi.indirect.enabled': False}
    for name, value in overrides.items():
        props.Set(pysuperluxcore.Property(name, value))
    return props


reader._node = experimental_node
config.convert = experimental_config
os.environ.setdefault('SUPERLUXCORE_AUDIT_CASES', 'sss_roughness')
os.environ.setdefault('SUPERLUXCORE_AUDIT_BASELINE', '1')
print('BSSRDF_EXPERIMENTAL_IDENTITY', identity['native_sha256'], flush=True)
try:
    fixture = Path(os.environ.get('SUPERLUXCORE_BSSRDF_FIXTURE_SCRIPT',
                                   str(Path(__file__).with_name('cycles-zero-render-test.py'))))
    assert fixture.resolve().parent == Path(__file__).resolve().parent
    runpy.run_path(str(fixture), run_name='__main__')
finally:
    reader._node = original_node
    config.convert = original_config
    folder = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
    (folder / 'experimental-export.json').write_text(json.dumps({
        'experimental': True, 'production_acceptance': False,
        'cpu_eye_only': os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE', 'CPU') == 'CPU',
        'device': os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE', 'CPU'), 'native_sha256': identity['native_sha256'],
        'exported': exported}, ensure_ascii=False, indent=2, default=str) + '\n')
