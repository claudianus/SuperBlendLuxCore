"""Actual CPU/Metal stereo primary-ray render in a closed emitting room.

Static and non-uniform-scale motion are compared with identical fixed pixel
jitter, no denoiser and one sample. This tests primary geometry, not stereo
DLSS reprojection, light tracing, or converged material quality.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import numpy as np

spec=importlib.util.spec_from_file_location('stereo_fixture',Path(__file__).with_name('dlss_render_frame_test.py'))
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--observe',action='store_true');p.add_argument('--large',action='store_true');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);s=m.slc;s.Init();records=[]
for kind in ['perspective','environment_180','environment_360']:
    for motion in (False,True):
        scene=s.Scene()
        text=f'''scene.camera.type = stereo
scene.camera.stereo.type = {kind}
scene.camera.lookat.orig = 0 0 0
scene.camera.lookat.target = 0 0 1
scene.camera.up = 0 1 0
scene.camera.cliphither = .001
scene.camera.clipyon = 50
scene.camera.lensradius = 0
'''
        if motion:
            for key in (0,1):
                text+=f'scene.camera.motion.{key}.time = {key}\nscene.camera.motion.{key}.transformation = 2 0 0 0 0 .5 0 0 0 0 1.5 0 0 0 0 1\n'
        scene.Parse(m.props(text))
        for face in range(6):
            axis=face//2;sign=-1 if face%2==0 else 1
            other=[k for k in range(3) if k!=axis]
            vertices=[]
            for u,v in [(-8,-8),(8,-8),(8,8),(-8,8)]:
                point=[0.,0.,0.];point[axis]=8*sign;point[other[0]]=u;point[other[1]]=v;vertices.append(tuple(point))
            normal=np.cross(np.array(vertices[1])-vertices[0],np.array(vertices[2])-vertices[0])
            triangles=[(0,1,2),(0,2,3)] if normal[axis]*sign<0 else [(0,2,1),(0,3,2)]
            color=['1 .1 .1','.1 1 1','.1 1 .1','1 .1 1','.1 .1 1','1 1 .1'][face]
            name=f'wall{face}';scene.DefineMesh(name,vertices,triangles)
            scene.Parse(m.props(f'scene.materials.{name}.type=matte\nscene.materials.{name}.kd=0 0 0\nscene.materials.{name}.emission={color}\nscene.objects.{name}.shape={name}\nscene.objects.{name}.material={name}'))
        images={}
        for engine in ['TILEPATHCPU','TILEPATHOCL']:
            data=m.render(scene,engine,(1280,720) if a.large else (96,64),jitter=(0.,0.))
            images[engine]=data
            np.savez_compressed(a.out/f'{kind}-{int(motion)}-{engine.lower()}.npz',**data)
        cpu,gpu=images['TILEPATHCPU'],images['TILEPATHOCL']
        position_error=float(np.max(np.abs(cpu['position'].astype(np.float64)-gpu['position'])))
        depth_error=float(np.max(np.abs(cpu['depth'].astype(np.float64)-gpu['depth'])))
        records.append({'kind':kind,'motion_scale':motion,'position_max_abs':position_error,
                        'depth_max_abs':depth_error,'geometry_tolerance':1e-4,
                        'RGB_exact':bool(np.array_equal(cpu['color'],gpu['color'])),
                        'passed':position_error<1e-4 and depth_error<1e-4,
                        'size':list(cpu['position'].shape[:2][::-1])})
report={'passed':all(r['passed'] for r in records),'records':records,'observe_only':a.observe,
        'scope':__doc__,'native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),
        'test_sha256':hashlib.file_digest(Path(__file__).open('rb'),'sha256').hexdigest()}
(a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
if not a.observe:assert report['passed'],'Stereo CPU/Metal primary geometry differs'
