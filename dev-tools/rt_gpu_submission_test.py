"""Physical sample/AOV invariance of bounded interactive GPU submission.

ABBA controls scheduling variation; timing is diagnostic, not a speedup claim.
The original full initial iteration count must be retained for LIGHT tasks.
"""
import argparse,importlib.util,json,os,time,hashlib
from pathlib import Path
import numpy as np

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=False)
spec=importlib.util.spec_from_file_location('submission_fixture',Path(__file__).with_name('dlss_render_frame_test.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);s=m.slc;s.Init();descs=s.GetOpenCLDeviceDescs();mask=''.join('1' if descs.Get(n+'.type').GetString()=='METAL_GPU' else '0' for n in descs.GetAllUniqueSubNames('opencl.device'));assert '1' in mask,'No CPU fallback'
outputs={'RGBA':4,'SAMPLECOUNT':1,'ALPHA':1,'ALBEDO':3,'AVG_SHADING_NORMAL':3,'DEPTH':1,'POSITION':3,'DIRECT_DIFFUSE':3,'EMISSION':3,'OBJECT_ID':1}
rows=[];report={'passed':False,'native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),'cases':rows,'performance_eligible':False,'scope':__doc__}
try:
 for spectral in (False,True):
  for light in (False,True):
   captures=[];variant=f"{'spectral' if spectral else 'rgb'}-{'light' if light else 'eye'}"
   for repeat,interactive in enumerate((False,True,True,False)):
    scene,_,_=m.fixture();config=m.props(f'''renderengine.type = RTPATHOCL
renderengine.seed = 131
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
opencl.devices.select = {mask}
film.width = 96
film.height = 64
film.hw.enable = 0
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
rtpath.denoisingframes.enable = 1
rtpath.denoisingframes.lossless = 1
rtpath.denoisingframes.haltspp = 8
rtpath.denoisingframes.tilesize = 128
rtpath.interactive.gpu = {int(interactive)}
path.pathdepth.total = 24
path.pathdepth.diffuse = 24
path.pathdepth.glossy = 24
path.pathdepth.specular = 24
path.lighttracing.auto = 0
path.lighttracing.enable = {int(light)}
path.lighttracing.taskfraction = .25
path.hybridbackforward.enable = {int(light)}
path.vertexconnection.enable = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.clamping.variance.maxvalue = 0
path.spectral.enable = {int(spectral)}
''')
    for index,name in enumerate(outputs):
     config.Set(s.Property(f'film.outputs.{index}.type',name));config.Set(s.Property(f'film.outputs.{index}.filename','unused.exr' if name!='OBJECT_ID' else 'unused.png'))
    native=s.RenderSession(s.RenderConfig(config,scene));arrays={};after=0;start=time.monotonic()
    try:
     native.Start();actual=native.GetRenderConfig().GetProperties().Get('rtpath.interactive.gpu').GetBool();assert actual==interactive
     for frame_index in range(1,9):
      deadline=time.monotonic()+60
      while True:
       frame=native.GetDenoisingFrame(after,100)
       if frame is not None:break
       assert time.monotonic()<deadline,'No complete lossless frame'
      assert frame['frame_id']==frame_index and frame['complete'] and np.all(frame['sample_count']==1)
      assert np.isfinite(frame['color']).all() and np.isfinite(frame['guides']).all()
      arrays[f'color_{frame_index}']=frame['color'].copy();arrays[f'guides_{frame_index}']=frame['guides'].copy();arrays[f'count_{frame_index}']=frame['sample_count'].copy()
      stats=native.GetFilm().GetStats();arrays[f'light_samples_{frame_index}']=np.array(stats.Get('stats.film.total.light.samplecount').GetFloat(),np.float64)
      if light:assert arrays[f'light_samples_{frame_index}']>0,'LIGHT work was not exercised'
      if frame_index==8:
       for name,channels in outputs.items():
        integer=name in ('SAMPLECOUNT','OBJECT_ID');a=np.empty((64,96,channels),np.uint32 if integer else np.float32);getter=native.GetFilm().GetOutputUInt if integer else native.GetFilm().GetOutputFloat;getter(s.FilmOutputType.names[name],a,0,False);arrays['aov_'+name]=a
      after=frame['frame_id'];native.AcknowledgeDenoisingFrame(frame);del frame
    finally:
     if native.IsStarted():native.Stop()
    elapsed=time.monotonic()-start;file=args.out/f'{variant}-{repeat}-interactive{int(interactive)}.npz';np.savez_compressed(file,**arrays);captures.append(arrays)
    print(json.dumps({'variant':variant,'repeat':repeat,'interactive':interactive,'seconds':elapsed,'frames':8}),flush=True)
   reference=captures[0];comparisons=[]
   for repeat,arrays in enumerate(captures[1:],1):
    deltas={};exact=[]
    for key,a in reference.items():
     other=arrays[key];equal=np.array_equal(a,other,equal_nan=True)
     if equal:exact.append(key)
     else:
      # GPU LIGHT splats may differ by float atomic accumulation order;
      # counts/guides and all non-LIGHT arrays still require exact equality.
      allowed=light and (key.startswith('color_') or key in ('aov_RGBA','aov_DIRECT_DIFFUSE','aov_EMISSION'))
      assert allowed and np.allclose(a,other,rtol=2e-6,atol=2e-6,equal_nan=True),(variant,repeat,key,float(np.nanmax(np.abs(a-other))))
      deltas[key]=float(np.nanmax(np.abs(a-other)))
    comparisons.append({'repeat':repeat,'exact_arrays':exact,'float_atomic_differences':deltas})
   rows.append({'variant':variant,'spectral':spectral,'light':light,'frames_per_repeat':8,'order':[0,1,1,0],'array_count':len(reference),'comparisons':comparisons,'passed':True})
 report['passed']=len(rows)==4 and all(row['passed'] for row in rows)
finally:(args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
assert report['passed']
