"""Actual 720p orthographic focus/defocus image fixture (no denoising).

Left stripes lie on the focus plane; right stripes are nearer the camera.
The no-aperture image is a control. CPU and Metal use the same 64-SPP settings;
their stochastic aperture samples are not assumed to be identical.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np

spec=importlib.util.spec_from_file_location('ortho_fixture',Path(__file__).with_name('dlss_render_frame_test.py'))
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--observe',action='store_true');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
s=m.slc;s.Init();images={};records=[]
for radius in (0.,.12):
 scene=s.Scene();scene.Parse(m.props(f'''scene.camera.type=orthographic
scene.camera.lookat.orig=0 0 0
scene.camera.lookat.target=0 0 1
scene.camera.up=0 1 0
scene.camera.cliphither=.001
scene.camera.clipyon=30
scene.camera.lensradius={radius}
scene.camera.focaldistance=10
scene.materials.dark.type=matte
scene.materials.dark.kd=0 0 0
scene.materials.dark.emission=.02 .02 .02
scene.materials.bright.type=matte
scene.materials.bright.kd=0 0 0
scene.materials.bright.emission=1 1 1
'''))
 def quad(name,x0,x1,z,mat):
  scene.DefineMesh(name,[(x0,-2,z),(x1,-2,z),(x1,2,z),(x0,2,z)],[(0,2,1),(0,3,2)])
  scene.Parse(m.props(f'scene.objects.{name}.shape={name}\nscene.objects.{name}.material={mat}'))
 # A covering dark triangle ensures finite geometry for every camera ray.
 scene.DefineMesh('back',[(-20,-20,15),(60,-20,15),(-20,60,15)],[(0,2,1)])
 scene.Parse(m.props('scene.objects.back.shape=back\nscene.objects.back.material=dark'))
 for panel,(lo,hi,z) in enumerate([(-1.6,-.1,10.),(.1,1.6,3.)]):
  for stripe in range(24):
   x0=lo+(hi-lo)*stripe/24;x1=lo+(hi-lo)*(stripe+1)/24
   quad(f'p{panel}s{stripe}',x0,x1,z,'bright' if stripe%2 else 'dark')
 for engine in ['TILEPATHCPU','TILEPATHOCL']:
  data=m.render(scene,engine,(1280,720),jitter=(0.,0.),aa=8,timeout=180)
  label=f'{"sharp" if radius==0 else "dof"}-{engine.lower()}'
  np.savez_compressed(a.out/(label+'.npz'),**data);images[label]=data['color']
  records.append({'label':label,'size':[1280,720],'samples_requested':64,
                  'sample_count_min':int(data['count'].min()),'sample_count_max':int(data['count'].max()),
                  'finite':bool(np.isfinite(data['color']).all())})
metrics={}
for engine in ['tilepathcpu','tilepathocl']:
 sharp=images['sharp-'+engine][100:620,:,:3].mean(0).mean(1)
 dof=images['dof-'+engine][100:620,:,:3].mean(0).mean(1)
 # Fixed symmetric interior ROIs; no stripe boundary pixels or panel edges.
 # Camera-to-world X is reflected, so physical left is image right.
 focus=slice(760,1180);near=slice(100,520)
 # Determine the panel through its actual world-space geometry rather than
 # relying on display orientation: X sign is read from the sharp POSITION.
 with np.load(a.out/f'sharp-{engine}.npz') as f:
  xpos=f['position'][360,:,0]
  focus_mask=(xpos>-1.45)&(xpos<-.25);near_mask=(xpos>.25)&(xpos<1.45)
 diff=np.abs(dof-sharp)
 near_variance=float(np.var(dof[near_mask]));sharp_variance=float(np.var(sharp[near_mask]))
 metrics[engine]={'focus_mean_abs_change':float(diff[focus_mask].mean()),
                  'near_mean_abs_change':float(diff[near_mask].mean()),
                  'near_variance_ratio':near_variance/sharp_variance,
                  'focus_pixels':int(focus_mask.sum()),'near_pixels':int(near_mask.sum())}
 cpu=metrics[engine]
 cpu['passed']=cpu['focus_mean_abs_change']<1e-4 and cpu['near_mean_abs_change']>.1 and cpu['near_variance_ratio']<.25
report={'passed':all(r['finite'] and r['sample_count_min']==64 and r['sample_count_max']==64 for r in records) and all(r['passed'] for r in metrics.values()),
        'records':records,'metrics':metrics,'observe_only':a.observe,'scope':__doc__,
        'native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),
        'test_sha256':hashlib.file_digest(Path(__file__).open('rb'),'sha256').hexdigest(),
        'SDK_evaluations':0,'performance_eligible':False}
(a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)
if not a.observe:assert report['passed'],'Ortho focus/defocus image contract failed'
