"""Matched deterministic renders with no guide request on old/new native wheels."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

spec=importlib.util.spec_from_file_location('fixture',Path(__file__).with_name('dlss_render_frame_test.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True)
parser.add_argument('--engine',default='TILEPATHCPU',choices=('TILEPATHCPU','TILEPATHOCL'))
args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True);m.slc.Init()
records={}
for name,extra in [('matte',''),('openpbr','''
scene.materials.white.type = openpbr
scene.materials.white.basecolor = 0.2 0.4 0.6
scene.materials.white.basemetalness = 0.3
scene.materials.white.coatweight = 0.5
scene.materials.white.coatroughness = 0.2
scene.materials.white.cyclesnormalsemantics = 1
'''),('metal','''
scene.materials.white.type = metal2
scene.materials.white.distribution = ggx
scene.materials.white.uroughness = 0.25
scene.materials.white.vroughness = 0.5
''')]:
    scene,_,_=m.fixture()
    if extra:scene.Parse(m.props(extra))
    planes=m.render(scene,args.engine,(96,64),aa=2)
    np.savez_compressed(args.out/(name+'.npz'),**planes)
    records[name]={k:hashlib.sha256(v.tobytes()).hexdigest() for k,v in planes.items()}
(args.out/'result.json').write_text(json.dumps({'engine':args.engine,'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'planes':records},indent=2)+'\n')
