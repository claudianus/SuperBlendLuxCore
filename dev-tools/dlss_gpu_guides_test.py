"""Renderer-owned GPU guide/readback tests, including the Metal silhouette case."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m)
    return m


root=Path(__file__).resolve().parents[1]
m=load('gpu_guide_fixture',root/'dev-tools/dlss_render_frame_test.py')
dlss=load('gpu_guide_dlss',root/'engine/dlss.py')
parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--large',action='store_true');args=parser.parse_args()
args.out.mkdir(parents=True,exist_ok=True);m.slc.Init();records=[]
cases=[('matte',''),('openpbr','''
scene.materials.white.type = openpbr
scene.materials.white.basemetalness = 0.35
scene.materials.white.coatweight = 0.4
scene.materials.white.specularroughness = 0.5
scene.materials.white.coatroughness = 0.45
scene.materials.white.cyclesnormalsemantics = 1
'''),('metal2','''
scene.materials.white.type = metal2
scene.materials.white.distribution = ggx
scene.materials.white.uroughness = 0.5
scene.materials.white.vroughness = 0.7
''')]
for name,extra in cases:
    scene,_,_=m.fixture()
    if extra:scene.Parse(m.props(extra))
    size=(1280,720) if args.large and name=='matte' else (96,64)
    # The second sequence jitter previously produced different CPU/Metal hits.
    jitter=(.2548776662466927,.0698402909980532)
    raw=m.render(scene,'TILEPATHOCL',size,index=1,jitter=jitter)
    actual=m.render(scene,'TILEPATHOCL',size,index=1,jitter=jitter,gpu_guides=True)
    guides=actual['gpu_guides']
    assert guides['source']=='renderer_gpu'
    assert np.all(guides['status']==1), (name,np.unique(guides['status'],return_counts=True))
    assert np.array_equal(guides['position_depth'][:,:,:3],actual['position']), name+' actual-hit mismatch'
    for k in ('diffuse','specular','normal_roughness','position_depth'):
        assert np.isfinite(guides[k]).all(), k
    assert np.all((guides['normal_roughness'][:,:,3]>=0)&(guides['normal_roughness'][:,:,3]<=1))
    w,h=size;motion=np.zeros((h,w,2),np.float32)
    frame=dlss.DLSSFrame.from_surface_guides(actual['color'],guides,render_position=actual['position'],
        motion=motion,specular_motion=motion.copy(),frame_id=1,scene_serial=1,
        jitter=tuple(-value for value in jitter),independent_samples=True)
    preservation={}
    for k in raw:
        a,z=raw[k],actual[k]
        preservation[k]={'bit_exact':bool(np.array_equal(a,z)),'max_abs':float(np.max(np.abs(a.astype(float)-z.astype(float))))}
        np.testing.assert_allclose(a,z,atol=5e-6,rtol=5e-6,err_msg=name+': '+k)
    if size==(1280,720):
        np.savez_compressed(args.out/'gpu-guides-720p.npz',**{n:getattr(frame,n) for n in
            ('color','depth','diffuse','specular','normal_roughness','motion','specular_motion')},
            jitter=np.array(frame.jitter,np.float32),ray_jitter=np.array(jitter,np.float32))
    records.append({'case':name,'size':size,'status':[1],'gpu_positions_bit_exact_to_render':True,
                    'default_preservation_5e6':True,'preservation':preservation})
    (args.out/'result.json').write_text(json.dumps({'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'device_type':os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU'),'cases':records,'scope':'Actual GPU primary-hit guides; static scenes. Continuation and final/animation integration still in progress.'},indent=2)+'\n')
    print('GPU guides passed',name,size,flush=True)
