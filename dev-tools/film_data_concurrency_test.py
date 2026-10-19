"""Actual progressive CPU/Metal depth-position consistency under supported sampling.

Orthographic aperture .12, focus10, hither.001. Layered stripes at z3/10
and a covering z15 plane provide the same independent interval oracle as
orthographic_film_data_test.py. Averages/stop overshoot are recorded; this
does not claim exactly64 samples per pixel or matched performance.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import numpy as np

spec=importlib.util.spec_from_file_location('cohort_fixture',Path(__file__).with_name('dlss_render_frame_test.py'))
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--large',action='store_true');p.add_argument('--observe',action='store_true');p.add_argument('--spp',type=int,default=64);p.add_argument('--cases',nargs='+');p.add_argument('--full-data',action='store_true');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
s=m.slc;s.Init();w,h=(1280,720) if a.large else (257,145)
scene=s.Scene();scene.Parse(m.props('''scene.camera.type=orthographic
scene.camera.lookat.orig=0 0 0
scene.camera.lookat.target=0 0 1
scene.camera.up=0 1 0
scene.camera.cliphither=.001
scene.camera.clipyon=30
scene.camera.lensradius=.12
scene.camera.focaldistance=10
scene.materials.dark.type=matte
scene.materials.dark.kd=0 0 0
scene.materials.dark.emission=.02 .02 .02
scene.materials.bright.type=matte
scene.materials.bright.kd=0 0 0
scene.materials.bright.emission=1 1 1
''' + ('scene.materials.dark.id=7\nscene.materials.bright.id=11\n' if a.full_data else '')))
scene.DefineMesh('back',[(-20,-20,15),(60,-20,15),(-20,60,15)],[(0,2,1)],uvs=[(-20,-20),(60,-20),(-20,60)] if a.full_data else None)
scene.Parse(m.props('scene.objects.back.shape=back\nscene.objects.back.material=dark'+ ('\nscene.objects.back.id=3' if a.full_data else '')))
for panel,(lo,hi,z) in enumerate([(-1.6,-.1,10.),(.1,1.6,3.)]):
 for stripe in range(24):
  x0=lo+(hi-lo)*stripe/24;x1=lo+(hi-lo)*(stripe+1)/24;name=f'p{panel}s{stripe}'
  scene.DefineMesh(name,[(x0,-2,z),(x1,-2,z),(x1,2,z),(x0,2,z)],[(0,2,1),(0,3,2)],uvs=[(x0,-2),(x1,-2),(x1,2),(x0,2)] if a.full_data else None)
  scene.Parse(m.props(f'scene.objects.{name}.shape={name}\nscene.objects.{name}.material={"bright" if stripe%2 else "dark"}' + (f'\nscene.objects.{name}.id={100+panel*24+stripe}' if a.full_data else '')))
cases=[('cpu-sobol','PATHCPU','SOBOL',1,0.),('metal-sobol','PATHOCL','SOBOL',1,0.),
       ('metal-sobol-overlap8','PATHOCL','SOBOL',8,0.),('metal-rt','RTPATHOCL','TILEPATHSAMPLER',1,0.),
       ('metal-rt-fovea','RTPATHOCL','TILEPATHSAMPLER',1,.95),
       ('metal-random','PATHOCL','RANDOM',1,0.),('metal-metropolis','PATHOCL','METROPOLIS',1,0.),
       ('metal-sobol-wavefront','PATHOCL','SOBOL',8,0.)]
if a.cases:
 assert set(a.cases)<={c[0] for c in cases};cases=[c for c in cases if c[0] in a.cases]
desc=s.GetOpenCLDeviceDescs();mask=''.join('1' if desc.Get(n+'.type').GetString()=='METAL_GPU' else '0' for n in desc.GetAllUniqueSubNames('opencl.device'));assert '1' in mask
records=[]
for label,engine,sampler,overlap,fovea in cases:
 cfg=m.props(f'''renderengine.type={engine}
sampler.type={sampler}
pathocl.wavefront={"on" if "wavefront" in label else "off"}
sampler.sobol.overlapping={overlap}
sampler.tilepath.fovea.strength={fovea}
sampler.tilepath.fovea.radius=.2
native.threads.count=4
opencl.native.threads.count=0
opencl.task.count=8192
opencl.devices.select={mask}
pathocl.pixelatomics.enable=1
film.width={w}
film.height={h}
film.filter.type=NONE
film.imagepipelines.0.0.type=NOP
batch.haltspp={a.spp}
rtpath.resolutionreduction=1
rtpath.resolutionreduction.preview=1
rtpath.resolutionreduction.preview.step=0
path.pathdepth.total=4
path.sampling.pixeljitter.enable=1
path.sampling.pixeljitter.x=0
path.sampling.pixeljitter.y=0
path.lighttracing.auto=0
path.lighttracing.enable=0
path.hybridbackforward.enable=0
path.vertexconnection.enable=0
path.mnee.auto=0
path.mnee.enable=0
path.guiding.enable=0
path.photongi.indirect.enabled=0
path.photongi.caustic.enabled=0
path.spectral.enable=0
''')
 channels=[('color','RGBA',4),('depth','DEPTH',1),('position','POSITION',3),('normal','SHADING_NORMAL',3),('count','SAMPLECOUNT',1)]
 if a.full_data:channels.extend([('geometry_normal','GEOMETRY_NORMAL',3),('material','MATERIAL_ID',1),('uv','UV',2),('object','OBJECT_ID',1),('motion','MOTION_VECTOR',4)])
 for j,(_,channel,_) in enumerate(channels):cfg.Set(s.Property(f'film.outputs.{j}.type',channel));cfg.Set(s.Property(f'film.outputs.{j}.filename','unused.png' if channel in ('MATERIAL_ID','OBJECT_ID') else 'unused.exr'))
 config=s.RenderConfig(cfg,scene);session=s.RenderSession(config);started=time.monotonic()
 try:
  session.Start();deadline=time.monotonic()+180
  while not session.HasDone():
   session.UpdateStats()
   if session.GetStats().Get('stats.renderengine.pass').GetFloat()>=a.spp:break
   if time.monotonic()>deadline:raise TimeoutError(label)
   time.sleep(.01)
  session.Stop();data={}
  for name,channel,n in channels:
   integer=channel in ('SAMPLECOUNT','MATERIAL_ID','OBJECT_ID')
   x=np.empty((h,w,n),np.uint32 if integer else np.float32)
   method=session.GetFilm().GetOutputUInt if integer else session.GetFilm().GetOutputFloat
   method(getattr(s.FilmOutputType,channel),x,0,False);data[name]=x
  np.savez_compressed(a.out/(label+'.npz'),**data)
  count=data['count'][:,:,0];depth=data['depth'][:,:,0];position=data['position'];covered=count>0
  delta_z=position[:,:,2].astype(np.float64)-.001;dz_min=1/np.sqrt(1+(.12/10)**2)
  bad=covered&((~np.isfinite(depth))|(~np.isfinite(position).all(2))|(depth<delta_z-2e-5)|(depth>delta_z/dz_min+2e-5))
  attributes={}
  if a.full_data:
   # Independent surface oracle: the declared object IDs select an actual
   # stripe/plane. UVs are world XY, and all front-facing normals are -Z.
   oid=data['object'][:,:,0];back=oid==3;stripe=(oid.astype(np.int64)-100)%24;panel=(oid.astype(np.int64)-100)//24
   x0=np.where(panel==0,-1.6,.1)+1.5*stripe/24
   known=back|((oid>=100)&(oid<148))
   plane_z=np.where(back,15.,np.where(panel==0,10.,3.))
   on_surface=(np.abs(position[:,:,2]-plane_z)<2e-5)&(back|((position[:,:,0]>=x0-2e-5)&(position[:,:,0]<=x0+1.5/24+2e-5)&(np.abs(position[:,:,1])<=2+2e-5)))
   expected_material=np.where(back|(stripe%2==0),7,11)
   checks={'object_surface':known&on_surface,'material':data['material'][:,:,0]==expected_material,
           'uv':np.isfinite(data['uv']).all(2)&(np.max(np.abs(data['uv']-position[:,:,:2]),axis=2)<2e-5),
           'geometry_normal':np.isfinite(data['geometry_normal']).all(2)&(np.max(np.abs(data['geometry_normal']-np.array([0,0,-1])),axis=2)<2e-5),
           'shading_normal':np.isfinite(data['normal']).all(2)&(np.max(np.abs(data['normal']-np.array([0,0,-1])),axis=2)<2e-5),
           # MOTION_VECTOR is {vx, vy, valid, objectMotion}; these panes
           # have visible static hits, so validity must be one, not zero.
           'static_motion':np.isfinite(data['motion']).all(2)&(np.max(np.abs(data['motion']-np.array([0,0,1,0])),axis=2)<1e-6)}
   attributes={name:int(np.count_nonzero(covered&~valid)) for name,valid in checks.items()}
  coords=np.argwhere(bad);record={'case':label,'engine':engine,'sampler':sampler,'wavefront':('on' if 'wavefront' in label else 'off'),'overlap':overlap,'fovea_strength':fovea,'size':[w,h],
   'actual_sample_count_min':int(count.min()),'actual_sample_count_max':int(count.max()),'actual_sample_count_mean':float(count.mean()),
   'covered_pixels':int(covered.sum()),'total_pixels':w*h,'inconsistent_pixels':len(coords),'RGB_finite':bool(np.isfinite(data['color']).all()),
   'full_data':a.full_data,'attribute_inconsistent_pixels':attributes,
   'passed':bool(np.all(covered)) and len(coords)==0 and np.isfinite(data['color']).all().item() and not any(attributes.values()),
   'examples':[{'y_x':q.tolist(),'depth':float(depth[tuple(q)]),'position':position[tuple(q)].tolist()} for q in coords[:8]],
   'elapsed_includes_prepare_stop_capture_seconds':time.monotonic()-started}
  records.append(record);(a.out/'progress.json').write_text(json.dumps(records,indent=2)+'\n');print(json.dumps({k:v for k,v in record.items() if k!='examples'}),flush=True)
 finally:
  if session.IsStarted():session.Stop()
report={'passed':all(r['passed'] for r in records),'records':records,'scope':__doc__,'observe_only':a.observe,'performance_eligible':False,'target_mean_spp':a.spp,
        'native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),'test_sha256':hashlib.file_digest(Path(__file__).open('rb'),'sha256').hexdigest()}
(a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
if not a.observe:assert report['passed'],'Progressive depth and position select different samples'
