"""Flat two-leaf MIX auxiliary features; physical closures stay unchanged."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import numpy as np


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m

here=Path(os.environ['SLC_DLSS_TEST_ADDON'])/'dev-tools'
glt=load('mix_glt',here/'dlss_glossy_translucent_guides_test.py');m=glt.m;s=m.slc
BASE='''
scene.materials.leaf_a.type=matte
scene.materials.leaf_a.kd=0.2 0.4 0.6
scene.materials.leaf_b.type=matte
scene.materials.leaf_b.kd=0.8 0.3 0.1
scene.materials.white.type=mix
scene.materials.white.material1=leaf_a
scene.materials.white.material2=leaf_b
scene.materials.white.amount=0.25
'''
EMISSION='''
scene.materials.leaf_a.kd=0 0 0
scene.materials.leaf_a.emission=0.3 0.2 0.1
scene.materials.leaf_b.type=openpbr
scene.materials.leaf_b.basecolor=0.8 0.8 0.8
scene.materials.leaf_b.specularroughness=0.3
scene.materials.leaf_b.specularior=1.45
scene.materials.leaf_b.cyclesnormalsemantics=1
scene.materials.leaf_b.reflectionnormalcorrection=1
scene.materials.white.amount=0.6
'''
CASES=[('weighted-matte','',1),('additive','scene.materials.white.additive=1',1),
('textured-factor','''
scene.textures.factor.type=checkerboard2d
scene.textures.factor.texture1=0.2
scene.textures.factor.texture2=0.8
scene.textures.factor.mapping.uvscale=4 4
scene.materials.white.amount=factor
''',1),('endpoint-b','scene.materials.leaf_a.type=velvet\nscene.materials.white.amount=1',1),
('endpoint-a','scene.materials.leaf_b.type=velvet\nscene.materials.white.amount=0',1),
('emission-openpbr',EMISSION,1),('active-unsupported','scene.materials.leaf_b.type=velvet',2),
('child-bump','''
scene.textures.height.type=checkerboard2d
scene.textures.height.texture1=0
scene.textures.height.texture2=0.01
scene.materials.leaf_a.bumptex=height
''',2),('nested','''
scene.materials.n1.type=matte
scene.materials.n2.type=matte
scene.materials.leaf_a.type=mix
scene.materials.leaf_a.material1=n1
scene.materials.leaf_a.material2=n2
''',2)]


def fixture(extra='',glass=False):
    scene,origin,target=glt.fixture(False,glass=glass)
    if 'scene.materials.n1.type' in extra:
        scene.Parse(m.props('scene.materials.n1.type=matte\nscene.materials.n2.type=matte'))
    scene.Parse(m.props(BASE+'\n'+extra));return scene,origin,target


p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
p.add_argument('--engine',choices=['TILEPATHCPU','TILEPATHOCL'],default='TILEPATHOCL')
p.add_argument('--baseline-only',action='store_true');p.add_argument('--dlss',action='store_true')
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True);s.Init();rows=[]
report={'native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),'engine':a.engine,'device':os.environ.get('SLC_DLSS_RENDER_DEVICE'),'cases':rows,'scope':__doc__}
for name,extra,expected in CASES:
    scene,_,_=fixture(extra)
    raw=m.render(scene,a.engine,(64,48),jitter=(.25,-.125))
    np.savez_compressed(a.out/(name+'-raw.npz'),**raw)
    if a.baseline_only:continue
    actual=m.render(scene,a.engine,(64,48),jitter=(.25,-.125),surface_guides=True,gpu_guides=a.engine.endswith('OCL'))
    for key in raw:np.testing.assert_array_equal(raw[key],actual[key],err_msg=name+': '+key)
    host=actual['surface_guides'];assert np.all(host['status']==expected),(name,np.unique(host['status']))
    if name in ['weighted-matte','additive','endpoint-a','endpoint-b']:
        color={'weighted-matte':[.35,.375,.475],'additive':[1,.7,.7],'endpoint-a':[.2,.4,.6],'endpoint-b':[.8,.3,.1]}[name]
        np.testing.assert_allclose(host['diffuse'][...,:3],np.broadcast_to(color,(48,64,3)),atol=3e-6,rtol=3e-6)
    if name=='textured-factor':
        values=host['diffuse'][...,0];assert np.ptp(values)>.2
        assert np.min(np.abs(values[...,None]-[.32,.68]),axis=-1).max()<3e-6
    row={'case':name,'status':expected,'raw6_bit_exact':True}
    if 'gpu_guides' in actual:
        gpu=actual['gpu_guides'];assert np.all(gpu['status']==expected),(name,np.unique(gpu['status']))
        np.testing.assert_array_equal(gpu['position_depth'][...,:3],actual['position'])
        if expected==1:
            for key in ['diffuse','specular','normal_roughness','position_depth']:
                np.testing.assert_allclose(gpu[key],host[key],atol=4e-6,rtol=4e-6,err_msg=name+': '+key)
        row.update(actual_gpu_hit_exact=True,host_reference_4e6=expected==1)
    rows.append(row);(a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print('flat MIX passed',name,flush=True)
if a.engine.endswith('OCL') and not a.baseline_only:
    view=load('mix_view',here/'dlss_image_pipeline_test.py');d=load('mix_dlss',here.parent/'engine/dlss.py');report['rr_frames']=[]
    for glass in [False,True]:
        view.m.fixture=lambda:fixture(EMISSION,glass)
        packet,raw=view.render_frame('rtpath.denoisingframes.haltspp=1\nrtpath.denoisingframes.lossless=1\nrtpath.denoisingframes.input.reduction=2\n',capture=True,size=(384,216))
        assert np.all(packet['guides'][...,7]==1),np.unique(packet['guides'][...,7],return_counts=True)
        np.testing.assert_array_equal(packet['color'],raw[1::2,1::2])
        row={'through_glass':glass,'status':1,'source_subgrid_exact':True}
        if a.dlss:
            with d.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'],os.environ['SUPERLUXCORE_DLSS_CACHE'],library=os.environ['SLC_DLSS_TEST_LIBRARY']) as backend:
                out=d.RendererDLSS(backend).process(packet);assert np.isfinite(out).all()
                np.testing.assert_array_equal(out[...,3],raw[...,3]);assert backend.stats()['frames']==1;row['stats']=backend.stats()
        report['rr_frames'].append(row);(a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print('MIX actual RR passed',glass,flush=True)
(a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
