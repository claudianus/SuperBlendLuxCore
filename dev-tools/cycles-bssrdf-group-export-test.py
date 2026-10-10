# SPDX-License-Identifier: Apache-2.0
"""Blender exporter grouping contracts against the complete private package.

Material partitions join one boundary; hair and copies retain independent
identities even when every AOV Object ID is deliberately identical.
"""
from array import array
import hashlib
import importlib
import json
import os
from pathlib import Path

import bpy
import pysuperluxcore as slc

identity = json.loads(Path(os.environ['SUPERLUXCORE_BSSRDF_IDENTITY']).read_text())
profile = Path(os.environ['BLENDER_USER_RESOURCES'])
for relative, digest in identity['profile_files'].items():
    assert hashlib.sha256((profile / relative).read_bytes()).hexdigest() == digest, relative
for filename, digest in identity['source_files'].items():
    assert hashlib.sha256(Path(filename).read_bytes()).hexdigest() == digest, filename
assert hashlib.sha256(Path(slc.pysuperluxcore.__file__).read_bytes()).hexdigest() == identity['native_sha256']
package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore'))
data = importlib.import_module(package + '.export.caches.exported_data')
utils = importlib.import_module(package + '.utils')
exported = data.ExportedObject('unique-object-key', [('front', 0), ('back', 1)],
                             ['surface', 'surface'], None, True, 432)
# Hair and particle geometry are appended after the material mesh partitions.
exported.parts.append(data.ExportedPart('separate-hair', 'hair', 'surface'))
props = utils.luxutils.create_props('', {
    'scene.materials.surface.type': 'matte', 'scene.materials.surface.kd': .45,
    **{'scene.shapes.' + name + '.' + key: value
       for name in ('front', 'back', 'hair')
       for key, value in (('type', 'inlinedmesh'), ('vertices', [0., 0., 0., 1., 0., 0., 0., 1., 0.]),
                          ('faces', [0, 1, 2]))}})
props.Set(exported.get_props())
scene = slc.Scene()
scene.Parse(props)
records = []


def check_sources():
    serialized = scene.ToProperties()
    for part in exported.parts[:2]:
        assert serialized.Get('scene.objects.' + part.lux_obj + '.subsurfacegroup').GetString() == 'unique-object-key'
        assert serialized.Get('scene.objects.' + part.lux_obj + '.id').GetInt() == 432
    assert not serialized.IsDefined('scene.objects.separate-hair.subsurfacegroup')


check_sources()
records.append('material-partitions-share-explicit-group-hair-remains-separate')
matrix = [1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 4., 0., 0., 1.]
for moving in (False, True):
    for part in exported.parts:
        if moving:
            scene.DuplicateObject(part.lux_obj, part.lux_obj + 'dupli', 2, 2,
                                  array('f', [0., 1.]), array('f', matrix * 4), array('I', [432, 432]))
        else:
            scene.DuplicateObject(part.lux_obj, part.lux_obj + 'dupli', 2,
                                  array('f', matrix * 2), array('I', [432, 432]))
    # Native APIs cannot infer cross-partition copy identity on their own.
    assert all(not scene.ToProperties().IsDefined('scene.objects.' + part.lux_obj + 'dupli0.subsurfacegroup')
               for part in exported.parts)
    exported.set_duplicate_subsurface_groups(scene, 2)
    serialized = scene.ToProperties()
    groups = []
    for index in range(2):
        joined = [serialized.Get('scene.objects.' + part.lux_obj + 'dupli' + str(index) + '.subsurfacegroup').GetString()
                  for part in exported.parts[:2]]
        assert joined[0] == joined[1] and joined[0] != 'unique-object-key'
        groups.append(joined[0])
        assert not serialized.IsDefined('scene.objects.separate-hairdupli' + str(index) + '.subsurfacegroup')
    assert len(set(groups)) == 2
    check_sources()
    records.append(('motion' if moving else 'static') + '-copies-with-shared-aov-id-have-distinct-boundaries')
    for part in exported.parts:
        for index in range(2):
            scene.DeleteObject(part.lux_obj + 'dupli' + str(index))

folder = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
folder.mkdir(parents=True, exist_ok=True)
(folder / 'group-export-metrics.json').write_text(json.dumps({
    'native_sha256': identity['native_sha256'], 'contracts': records,
    'passed': len(records), 'production_acceptance': False}, indent=2) + '\n')
print('BSSRDF_GROUP_EXPORT_COMPLETE', len(records), flush=True)
