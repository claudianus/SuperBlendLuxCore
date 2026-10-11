"""Resolve VDB files relative to the owning linked Blender library.

Use the actual Blender VDB loader as the oracle. Temporary linked libraries,
main files and hard-linked fixtures are removed on success and failure.
"""
from pathlib import Path
import hashlib, importlib, json, os, tempfile
import bpy

root = Path(os.environ['SUPERLUXCORE_AUDIT_DIR']); root.mkdir(parents=True, exist_ok=True)
fixture = Path(os.environ['SLC_VDB_FIXTURES'])/'named-attributes.vdb'
package = next(a.module for a in bpy.context.preferences.addons if a.module.endswith('.superluxcore'))
export = importlib.import_module(package+'.export.volume')
rows=[]
with tempfile.TemporaryDirectory(prefix='slc-vdb-linked-') as directory:
    temp=Path(directory); library=temp/'library'; library.mkdir()
    (library/'cache').mkdir(); main=temp/'main';main.mkdir()
    os.link(fixture,library/'cache/smoke0100.vdb')
    data=bpy.data.volumes.new('Linked VDB contract');data.filepath='//cache/smoke0100.vdb'
    path=library/'asset.blend'
    bpy.data.libraries.write(str(path),{data},fake_user=True)
    bpy.data.volumes.remove(data)
    bpy.ops.wm.save_as_mainfile(filepath=str(main/'scene.blend'))
    with bpy.data.libraries.load(str(path),link=True) as (available,requested):
        requested.volumes=['Linked VDB contract']
    data=requested.volumes[0];assert data.library is not None
    obj=bpy.data.objects.new('Linked VDB contract',data);bpy.context.scene.collection.objects.link(obj)
    try:
        for frame in [1,10]:
            bpy.context.scene.frame_set(frame)
            evaluated=obj.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
            chosen=export._resolve_frame_filepath(evaluated,bpy.context.scene)
            evaluated.grids.load();expected=evaluated.grids.frame_filepath
            rows.append({'frame':frame,'chosen':chosen,'expected':expected,
                         'grids':len(evaluated.grids),'passed':chosen==expected})
    finally:
        bpy.data.objects.remove(obj,do_unlink=True);bpy.data.volumes.remove(data)
proof={'complete':True,'records':rows,'failed':sum(not r['passed'] for r in rows),
       'actual_blender_loader_oracle':True,'temporary_library_removed':not Path(directory).exists(),
       'volume_export_sha256':hashlib.sha256(Path(export.__file__).read_bytes()).hexdigest()}
(root/'metrics.json').write_text(json.dumps(proof,indent=2)+'\n')
assert proof['failed']==0,rows
print('LINKED_VDB_PATH_CONTRACT_COMPLETE',len(rows),flush=True)
