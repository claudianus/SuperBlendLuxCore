"""Compare VDB frame selection with Blender's evaluated, loaded volume grids.

Nonzero offsets, missing files, clipping and looping are checked against the
actual Blender loader, not a duplicate sequence arithmetic implementation.
"""
from pathlib import Path
import hashlib
import importlib
import json
import os
import tempfile
import bpy

folder = Path(os.environ['SUPERLUXCORE_AUDIT_DIR'])
folder.mkdir(parents=True, exist_ok=True)
fixture = Path(os.environ['SLC_VDB_FIXTURES']) / 'named-attributes.vdb'
package = next(a.module for a in bpy.context.preferences.addons
               if a.module.endswith('.superluxcore'))
volume = importlib.import_module(package + '.export.volume')
rows = []
baseline = os.environ.get('SLC_VDB_SEQUENCE_BASELINE') == '1'
with tempfile.TemporaryDirectory(prefix='slc-vdb-sequence-') as directory:
    # Deliberately omit frame 2. Directory sorting must never fill that gap
    # with a different frame or move the sequence's starting number.
    for frame in [0, 1, 3, 100, 101, 102]:
        os.link(fixture, Path(directory) / ('smoke%04d.vdb' % frame))
    data = bpy.data.volumes.new('Sequence contract')
    data.filepath = str(Path(directory) / 'smoke0100.vdb')
    data.is_sequence = True
    data.frame_start = 10
    data.frame_duration = 3
    obj = bpy.data.objects.new('Sequence contract', data)
    bpy.context.scene.collection.objects.link(obj)
    try:
        for offset in [0, 99, -2]:
            data.frame_offset = offset
            for mode in ['CLIP', 'EXTEND', 'REPEAT', 'PING_PONG']:
                data.sequence_mode = mode
                for frame in [8, 9, 10, 11, 12, 13, 14]:
                    bpy.context.scene.frame_set(frame)
                    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
                    chosen = volume._resolve_frame_filepath(evaluated, bpy.context.scene)
                    loaded = evaluated.grids.load()
                    expected = evaluated.grids.frame_filepath
                    none = evaluated.grids.frame == 2147483647
                    exists = bool(chosen) and os.path.isfile(chosen)
                    # Failed loads can clear frame_filepath; their empty
                    # topology must still agree. Successful cached loads can
                    # return False after a previous failure, so inspect grids.
                    passed = (chosen == '' if none else
                              chosen == expected if expected else not exists)
                    rows.append({'mode': mode, 'offset': offset, 'scene_frame': frame,
                                 'blender_frame': evaluated.grids.frame,
                                 'chosen': Path(chosen).name if chosen else '',
                                 'expected': Path(expected).name if expected else '',
                                 'loaded': loaded, 'grids': len(evaluated.grids),
                                 'exists': exists, 'passed': passed})
                    if not baseline:
                        assert passed, rows[-1]
                        assert exists == bool(len(evaluated.grids)), rows[-1]
        # Zero duration is empty regardless of available files.
        data.sequence_mode = 'CLIP'
        data.frame_duration = 0
        bpy.context.scene.frame_set(10)
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
        chosen = volume._resolve_frame_filepath(evaluated, bpy.context.scene)
        rows.append({'zero_duration': True, 'chosen': chosen, 'passed': chosen == ''})
        if not baseline:
            assert chosen == ''
    finally:
        bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.volumes.remove(data)
proof = {'complete': True, 'baseline': baseline, 'records': rows,
         'failed': sum(not row['passed'] for row in rows),
         'volume_export_sha256': hashlib.sha256(Path(volume.__file__).read_bytes()).hexdigest(),
         'temporary_sequence_removed': not Path(directory).exists(),
         'actual_blender_frame_loader_oracle': True, 'full_goal_complete': False}
(folder / 'metrics.json').write_text(json.dumps(proof, indent=2) + '\n')
print('VDB_SEQUENCE_CONTRACT_COMPLETE', len(rows), proof['failed'], flush=True)
