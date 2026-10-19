"""Actual CPU/Metal camera near-surface visibility regression.

Translated pinhole cameras must see a representable emitting surface just beyond
cliphither. The far blue plane keeps all geometric outputs covered and finite.
A single covering triangle isolates clipping bounds from shared-edge precision;
--quad preserves a separate shared-diagonal stress case.
--observe records the old visibility failure without accepting it.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import numpy as np

spec=importlib.util.spec_from_file_location('camera_fixture',Path(__file__).with_name('dlss_render_frame_test.py'))
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--observe',action='store_true');p.add_argument('--large',action='store_true');p.add_argument('--guides',action='store_true');p.add_argument('--quad',action='store_true');p.add_argument('--motion-scale',action='store_true');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);s=m.slc;s.Init();records=[]
for offset in (0.,10.,1000.):
    scene=s.Scene()
    scene.Parse(m.props(f'''scene.camera.lookat.orig = {offset} 0 0
scene.camera.lookat.target = {offset} 0 1
scene.camera.up = 0 1 0
scene.camera.cliphither = .001
scene.camera.clipyon = 100
scene.camera.lensradius = 0
scene.materials.near.type = matte
scene.materials.near.kd = 0 0 0
scene.materials.near.emission = 1 0 0
scene.materials.far.type = matte
scene.materials.far.kd = 0 0 0
scene.materials.far.emission = 0 0 1
'''))
    if a.motion_scale:
        scene.Parse(m.props('scene.camera.lookat.orig = '+str(offset)+' 0 0\nscene.camera.lookat.target = '+str(offset)+' 0 1\nscene.camera.up = 0 1 0\nscene.camera.cliphither = .001\nscene.camera.clipyon = 100\nscene.camera.motion.0.time = 0\nscene.camera.motion.0.transformation = 2 0 0 0 0 .5 0 0 0 0 1.5 0 0 0 0 1\nscene.camera.motion.1.time = 1\nscene.camera.motion.1.transformation = 2 0 0 0 0 .5 0 0 0 0 1.5 0 0 0 0 1'))
    for name,z,extent in [('near',.00105,.1),('far',1.,10.)]:
        if a.quad:
            vertices=[(offset-extent,-extent,z),(offset+extent,-extent,z),
                      (offset+extent,extent,z),(offset-extent,extent,z)]
            triangles=[(0,2,1),(0,3,2)]
        else:
            vertices=[(offset-extent,-extent,z),(offset+3*extent,-extent,z),
                      (offset-extent,3*extent,z)]
            triangles=[(0,2,1)]
        if a.motion_scale:
            vertices=[(2*x,.5*y,1.5*z) for x,y,z in vertices]
        scene.DefineMesh(name,vertices,triangles)
        scene.Parse(m.props(f'scene.objects.{name}.shape={name}\nscene.objects.{name}.material={name}'))
    for engine in ['TILEPATHCPU','TILEPATHOCL']:
        data=m.render(scene,engine,(1280,720) if a.large else (96,64),jitter=(0.,0.),
                      gpu_guides=a.guides and engine.endswith('OCL'))
        guides=data.pop('gpu_guides',None)
        guide_exact=None
        if guides is not None:
            guide_exact=np.array_equal(guides['position_depth'][:,:,:3],data['position'])
            assert guide_exact and np.all(guides['status']==1), 'Renderer-owned guides lost the primary surface'
            for key,value in guides.items():
                if isinstance(value,np.ndarray):data['gpu_'+key]=value
        close=np.abs(data['position'][:,:,2]-(.001575 if a.motion_scale else .00105))<1e-6
        label=f'{int(offset)}-{engine.lower()}'
        np.savez_compressed(a.out/(label+'.npz'),**data)
        row={'offset':offset,'engine':engine,'near_surface_fraction':float(close.mean()),
             'median_hit_z':float(np.median(data['position'][:,:,2])),
             'mean_RGB':data['color'][:,:,:3].mean((0,1),dtype=np.float64).tolist(),
             'passed':bool(np.all(close)),'size':list(data['position'].shape[:2][::-1]),
             'renderer_owned_GPU_guide_positions_exact':guide_exact}
        records.append(row)
report={'passed':all(r['passed'] for r in records),'records':records,'observe_only':a.observe,
        'scope':__doc__,'motion_scale':a.motion_scale,'topology':'shared-diagonal-quad' if a.quad else 'single-covering-triangle','native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),
        'test_sha256':hashlib.file_digest(Path(__file__).open('rb'),'sha256').hexdigest()}
(a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
if not a.observe:assert report['passed'],'Visible surface lost after translating camera'
