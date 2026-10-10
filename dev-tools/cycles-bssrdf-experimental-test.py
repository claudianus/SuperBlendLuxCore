# SPDX-License-Identifier: Apache-2.0
"""Private CPU/Metal/adjoint diagnostic for unchanged Cycles RANDOM_WALK graphs.

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
halt = importlib.import_module(package + '.export.halt')
utils = importlib.import_module(package + '.utils')
original_node = reader._node
original_config = config.convert
original_halt = halt.convert
exported = []
exported_halts = []


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
    assert device in ('CPU', 'METAL', 'LIGHTCPU', 'CPUHYBRID'), device
    overrides = {'renderengine.type': {'CPU': 'PATHCPU', 'METAL': 'PATHOCL', 'LIGHTCPU': 'LIGHTCPU', 'CPUHYBRID': 'PATHCPU'}[device],
                 'path.cyclesbssrdf.experimental.device.enable': device == 'METAL',
                 'path.cyclesbssrdf.experimental.adjoint.enable': device in ('LIGHTCPU', 'CPUHYBRID'),
                 'opencl.cpu.use': False, 'opencl.gpu.use': True,
                 'path.cyclesbssrdf.experimental.enable': True,
                 'path.hybridbackforward.enable': device == 'CPUHYBRID',
                 'path.lighttracing.enable': False,
                 'path.lighttracing.auto': False,
                 'path.lighttracing.only': False,
                 'path.mnee.enable': False,
                 'path.mnee.auto': False,
                 'path.photongi.caustic.enabled': False,
                 'path.photongi.indirect.enabled': False}
    if device == 'LIGHTCPU' and 'SUPERLUXCORE_BSSRDF_LIGHT_SAMPLES' in os.environ:
        # The light estimator has a different variance. Keep the original
        # Cycles scene/sample settings intact and record this override.
        overrides['batch.haltspp'] = [0, int(os.environ['SUPERLUXCORE_BSSRDF_LIGHT_SAMPLES'])]
    for name, value in overrides.items():
        props.Set(pysuperluxcore.Property(name, value))
    return props


def experimental_halt(scene):
    props = original_halt(scene)
    if os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE') == 'LIGHTCPU':
        # The exporter reapplies halt conditions after config.convert. Its
        # ordinary UI still describes the eye-only diagnostic, so transpose
        # the sample budget here as well: pure LIGHTCPU produces no eye spp.
        samples = int(os.environ.get('SUPERLUXCORE_BSSRDF_LIGHT_SAMPLES',
                                     str(utils.get_halt_conditions(scene).samples)))
        props.Set(pysuperluxcore.Property('batch.haltspp', [0, samples]))
        exported_halts.append([0, samples])
        print('BSSRDF_DIAGNOSTIC_LIGHT_HALT', [0, samples], flush=True)
    elif os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE') == 'CPUHYBRID':
        samples = int(os.environ.get('SUPERLUXCORE_BSSRDF_LIGHT_SAMPLES',
                                     str(utils.get_halt_conditions(scene).samples)))
        budget = [int(utils.get_halt_conditions(scene).samples), samples]
        props.Set(pysuperluxcore.Property('batch.haltspp', budget))
        exported_halts.append(budget)
        print('BSSRDF_DIAGNOSTIC_HYBRID_HALT', budget, flush=True)
    return props


reader._node = experimental_node
config.convert = experimental_config
halt.convert = experimental_halt
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
    halt.convert = original_halt
    folder = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
    (folder / 'experimental-export.json').write_text(json.dumps({
        'experimental': True, 'production_acceptance': False,
        'cpu_eye_only': os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE', 'CPU') == 'CPU',
        'adjoint_light_only': os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE') == 'LIGHTCPU',
        'cpu_hybrid': os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE') == 'CPUHYBRID',
        'light_samples_override': os.environ.get('SUPERLUXCORE_BSSRDF_LIGHT_SAMPLES'),
        'exported_light_halts': exported_halts,
        'device': os.environ.get('SUPERLUXCORE_BSSRDF_DEVICE', 'CPU'), 'native_sha256': identity['native_sha256'],
        'exported': exported}, ensure_ascii=False, indent=2, default=str) + '\n')
