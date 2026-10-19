"""Same-input raw preservation across mesh preprocessing thread schedules."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time
import numpy as np

here = Path(os.environ['SLC_DLSS_TEST_ADDON'])/'dev-tools'
spec = importlib.util.spec_from_file_location('mesh_staging_fixture', here/'geometry_staging_test.py')
m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
base_fixture = m.fixture


def fixture(case):
    if not case.startswith('grid-'):
        return base_fixture(case)
    count = int(case.split('-')[1])
    scene, unique = base_fixture('direct-first')
    x, z = np.meshgrid(np.linspace(-.7, .7, count+1, dtype=np.float32),
                       np.linspace(0, 2, count+1, dtype=np.float32))
    y = (.1*np.sin(2*x)*np.cos(3*z)).astype(np.float32)
    points = np.stack((x, y, z), axis=-1).reshape(-1, 3)
    normals = np.stack((.2*np.cos(2*x)*np.cos(3*z), -np.ones_like(x),
                        -.3*np.sin(2*x)*np.sin(3*z)), axis=-1).reshape(-1, 3)
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    q = np.arange((count+1)**2, dtype=np.uint32).reshape(count+1, count+1)[:-1, :-1].ravel()
    a = np.stack((q, q+1, q+count+2), axis=-1)
    b = np.stack((q, q+count+2, q+count+1), axis=-1)
    triangles = np.stack((a, b), axis=1).reshape(-1, 3)
    uv = np.stack(((x+.7)/1.4, z*.5), axis=-1).reshape(-1, 2)
    colors = np.column_stack((.15+.6*uv[:, 0], .1+.5*uv[:, 1], .3*np.ones(len(uv), np.float32))).astype(np.float32)
    scene.DefineMeshExt('base', points, triangles, np.ascontiguousarray(normals),
                       [uv, uv*.5], [colors], [np.ones(len(points), np.float32)],
                       generated_transformation=np.eye(4, dtype=np.float32))
    scene.SetMeshVertexAOV('base', 0, uv[:, 0].tolist())
    scene.SetMeshTriangleAOV('base', 0, np.linspace(.1, .9, len(triangles), dtype=np.float32).tolist())
    return scene, unique


m.fixture = fixture
p = argparse.ArgumentParser();p.add_argument('--out', type=Path, required=True)
p.add_argument('--engine', choices=['TILEPATHCPU', 'TILEPATHOCL'], required=True)
p.add_argument('--compare', type=Path);args = p.parse_args()
assert not args.out.exists();args.out.mkdir(parents=True);m.s.Init();rows=[]
for case in ['direct-first', 'instance-first', 'motion-first', 'distinct-same-count', 'grid-128', 'grid-384']:
    started=time.monotonic();data,_=m.render(case,args.engine,(1280,720))
    if args.compare:
        with np.load(args.compare/(case+'.npz')) as old:
            assert set(old.files)==set(data)
            for name,value in data.items():np.testing.assert_array_equal(old[name],value,err_msg=case+':'+name)
    np.savez_compressed(args.out/(case+'.npz'),**data)
    rows.append({'case':case,'raw_channels':list(data),'same_input_bit_exact':bool(args.compare),
                 'triangle_count':2*int(case.split('-')[1])**2 if case.startswith('grid-') else None,
                 'wall_seconds':time.monotonic()-started})
result={'passed':True,'engine':args.engine,'native_sha256':hashlib.file_digest(Path(m.s.pysuperluxcore.__file__).open('rb'),'sha256').hexdigest(),
        'cases':rows,'scope':__doc__+' Six720p/4SPP fixtures, independent per-triangle normals/differentials only; mesh-area reduction and kernels unchanged. No speed ratio.'}
(args.out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
