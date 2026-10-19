"""Native completed-eye statistics versus a stopped film's SAMPLECOUNT.

Ordinary coarse RT is not a DLSS packet. The coherent-frame delivery tests
separately protect raw/AOV prefixes, exact halt, guides and backpressure.
"""
import argparse,hashlib,importlib.util,json,os,time
from pathlib import Path
import numpy as np

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('eye_count_fixture',root/'dev-tools/dlss_render_frame_test.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);s=m.slc
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--expect-overcount',action='store_true');p.add_argument('--cases',nargs='+');args=p.parse_args();args.out.mkdir(parents=True,exist_ok=False)
s.Init();device=os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU');desc=s.GetOpenCLDeviceDescs()
mask=''.join('1' if desc.Get(n+'.type').GetString()==device else '0' for n in desc.GetAllUniqueSubNames('opencl.device'));assert '1' in mask
cases=[('rt-rr1','RTPATHOCL',128,96,1,1,1,False),('rt-rr2','RTPATHOCL',128,96,2,2,1,False),('rt-rr4','RTPATHOCL',128,96,4,4,1,False),('rt-odd-rr4','RTPATHOCL',97,65,4,4,1,False),('rt-preview','RTPATHOCL',97,65,1,4,1,False),('rt-adaptive-fovea','RTPATHOCL',97,65,2,2,1,True),('tile-aa1','TILEPATHOCL',97,65,1,1,1,False),('tile-aa2','TILEPATHOCL',97,65,1,1,2,False),('cpu-aa2','TILEPATHCPU',97,65,1,1,2,False),('rt-subregion','RTPATHOCL',97,65,2,2,1,False),('tile-subregion','TILEPATHOCL',97,65,1,1,2,False),('rt-lt-count','RTPATHOCL',97,65,2,2,1,False)]
if args.cases:
 assert set(args.cases)<={c[0] for c in cases}
 cases=[c for c in cases if c[0] in args.cases]
rows=[]
for label,engine,w,h,rr,preview,aa,adaptive in cases:
 scene,_,_=m.fixture(plane=True)
 cfg=m.props(f'''
renderengine.type={engine}
sampler.type=TILEPATHSAMPLER
native.threads.count=4
opencl.native.threads.count=0
opencl.devices.select={mask}
opencl.task.count=16384
film.width={w}
film.height={h}
film.hw.enable=0
film.filter.type=NONE
film.imagepipelines.0.0.type=NOP
film.outputs.0.type=RGB
film.outputs.0.filename=unused.exr
film.outputs.1.type=SAMPLECOUNT
film.outputs.1.filename=unused.exr
rtpath.resolutionreduction.preview={preview}
rtpath.resolutionreduction.preview.step=4
rtpath.resolutionreduction={rr}
tilepath.sampling.aa.size={aa}
tile.multipass.enable=0
tile.size=32
sampler.tilepath.adaptive.strength={.7 if adaptive else 0}
sampler.tilepath.fovea.strength={.7 if adaptive else 0}
renderengine.seed=143
path.pathdepth.total=4
path.mnee.auto=0
path.mnee.enable=0
path.spectral.enable=0
path.lighttracing.auto=0
path.lighttracing.enable=0
path.lighttracing.only=0
path.hybridbackforward.enable=0
path.vertexconnection.enable=0
path.photongi.caustic.enabled=0
path.photongi.indirect.enabled=0
path.guiding.enable=0
batch.halttime=0
batch.haltspp=0
''')
 if label=='rt-lt-count':cfg.Set(m.props('path.lighttracing.enable=1\npath.lighttracing.taskfraction=0.25'))
 region=(9,83,7,57) if 'subregion' in label else (0,w-1,0,h-1)
 if 'subregion' in label:cfg.Set(m.props('film.subregion=9 83 7 57'))
 session=s.RenderSession(s.RenderConfig(cfg,scene))
 try:
  session.Start();deadline=time.monotonic()+90
  while True:
   if engine=='RTPATHOCL':ready=session.GetFilm().GetStats().Get('stats.film.total.samplecount').GetFloat()>=w*h*2
   else:ready=session.HasDone()
   if ready:break
   if time.monotonic()>deadline:raise TimeoutError(label)
   time.sleep(.005)
  # Stop joins render threads. Film stats and channel now describe the same
  # immutable prefix; no stale session stats or Pause/readback race.
  session.Stop();film=session.GetFilm();counts=np.zeros((h,w),np.uint32);rgb=np.zeros((h,w,3),np.float32)
  film.GetOutputUInt(s.FilmOutputType.SAMPLECOUNT,counts,0,False);film.GetOutputFloat(s.FilmOutputType.RGB,rgb,0,False)
  actual=int(counts.sum(dtype=np.uint64));stats=film.GetStats();total=stats.Get('stats.film.total.samplecount').GetFloat();eye=stats.Get('stats.film.total.eye.samplecount').GetFloat() if stats.IsDefined('stats.film.total.eye.samplecount') else None;reported=eye if eye is not None else total;light=stats.Get('stats.film.total.light.samplecount').GetFloat() if stats.IsDefined('stats.film.total.light.samplecount') else None
  row={'case':label,'engine':engine,'size':[w,h],'reduction':rr,'preview_reduction':preview,'aa':aa,'reported_count':reported,'reported_eye_count':eye,'reported_total_count':total,'reported_light_count':light,'report_source':'exact_eye' if eye is not None else 'legacy_total' ,'retained_camera_samples':actual,'difference':reported-actual,'ratio':reported/actual if actual else None,'finite_rgb':bool(np.isfinite(rgb).all()),'count_min_max':[int(counts.min()),int(counts.max())],'subregion':region}
  rows.append(row);np.savez_compressed(args.out/(label+'.npz'),counts=counts,rgb=rgb)
  (args.out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(row),flush=True)
  assert row['finite_rgb'] and actual>0,row
  if args.expect_overcount:
   if label in ('rt-rr2','rt-rr4','rt-odd-rr4','rt-subregion'):assert reported>actual,row
   # Legacy totals may omit pending edge-tile batches; retain that evidence.
  else:
   assert eye is not None and reported==actual,row
   if engine!='TILEPATHCPU':assert light is not None and total==actual+light,row
   if label=='rt-lt-count':assert light>0,row
  if engine!='RTPATHOCL':
   x0,x1,y0,y1=region;expected=np.zeros((h,w),np.uint32);expected[y0:y1+1,x0:x1+1]=aa*aa
   np.testing.assert_array_equal(counts,expected,err_msg=label)
 finally:
  if session.IsStarted():session.Stop()
  del session,scene
report={'passed':True,'native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),'device':device,'expect_overcount':args.expect_overcount,'rows':rows,'scope':__doc__}
(args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
