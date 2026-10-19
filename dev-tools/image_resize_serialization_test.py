"""All image-cache resize policies must save/reload without losing their state.

--save-only isolates registration without GPU compilation. Render mode compares
real embedded-texture raw/AOV prefixes before and after reload on the chosen engine.
"""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,sys,time
import numpy as np
root=Path(__file__).resolve().parents[1];sp=importlib.util.spec_from_file_location('resize_serialization_fixture',root/'dev-tools/dlss_render_frame_test.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);s=m.slc
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--save-only',action='store_true');p.add_argument('--expect-unregistered',action='store_true');p.add_argument('--engine',choices=['TILEPATHCPU','TILEPATHOCL'],default='TILEPATHCPU');args=p.parse_args();args.out.mkdir(exist_ok=False,parents=True);s.Init()
records=[]
for policy in ('NONE','FIXED','MINMEM','MIPMAPMEM'):
 image=args.out/(policy+'.ppm');w,h=128,64;yy,xx=np.indices((h,w));pix=np.stack([((xx//3+yy//5)%2)*220+20,(xx*7)%256,(yy*13)%256],axis=2).astype(np.uint8);image.write_bytes(b'P6\n128 64\n255\n'+pix.tobytes())
 resize=m.props(f'scene.images.resizepolicy.type={policy}\nscene.images.resizepolicy.scale=0.75\nscene.images.resizepolicy.minsize=4')
 scene=s.Scene(s.Properties(),resize)
 scene.Parse(m.props(f'''scene.camera.lookat.orig=0 -5 0
scene.camera.lookat.target=0 0 0
scene.camera.up=0 0 1
scene.camera.fieldofview=45
scene.textures.pic.type=imagemap
scene.textures.pic.file={image.resolve()}
scene.textures.pic.gamma=1
scene.textures.pic.storage=float
scene.materials.wall.type=matte
scene.materials.wall.kd=pic
scene.lights.env.type=constantinfinite
scene.lights.env.color=1 1 1
'''))
 scene.DefineMesh('wall',[(-4,1,-3),(4,1,-3),(4,1,3),(-4,1,3)],[(0,1,2),(0,2,3)],None,[(0.,0.),(1.,0.),(1.,1.),(0.,1.)]);scene.Parse(m.props('scene.objects.wall.shape=wall\nscene.objects.wall.material=wall'))
 cfg=m.props(f'''renderengine.type={args.engine}
sampler.type=TILEPATHSAMPLER
native.threads.count=4
opencl.native.threads.count=0
film.width=96
film.height=64
film.hw.enable=0
film.filter.type=NONE
film.imagepipelines.0.0.type=NOP
tile.size=32
tile.multipass.enable=0
tilepath.sampling.aa.size=1
renderengine.seed=145
path.lighttracing.auto=0
path.lighttracing.enable=0
path.hybridbackforward.enable=0
path.vertexconnection.enable=0
path.mnee.auto=0
path.mnee.enable=0
path.guiding.enable=0
path.photongi.caustic.enabled=0
path.photongi.indirect.enabled=0
path.spectral.enable=0
path.pathdepth.total=4
''')
 if args.engine=='TILEPATHOCL':
  desc=s.GetOpenCLDeviceDescs();mask=''.join('1' if desc.Get(n+'.type').GetString()=='METAL_GPU' else '0' for n in desc.GetAllUniqueSubNames('opencl.device'));assert '1' in mask;cfg.Set(s.Property('opencl.devices.select',mask))
 channels={'RGB':3,'SAMPLECOUNT':1,'ALBEDO':3,'AVG_SHADING_NORMAL':3,'DEPTH':1,'POSITION':3}
 for i,name in enumerate(channels):cfg.Set(s.Property(f'film.outputs.{i}.type',name));cfg.Set(s.Property(f'film.outputs.{i}.filename','unused.exr'))
 config=s.RenderConfig(cfg,scene);snapshot=args.out/(policy+'.bcf');record={'policy':policy,'scale':.75,'minsize':4,'engine':args.engine}
 try:
  props_before=str(config.GetProperties())
  try:config.Save(str(snapshot))
  except RuntimeError as error:
   record.update(saved=False,error=str(error));assert args.expect_unregistered and policy in ('MINMEM','MIPMAPMEM') and 'unregistered class' in str(error);continue
  record['saved']=True;assert not(args.expect_unregistered and policy in ('MINMEM','MIPMAPMEM')),'Missing registration hypothesis disproved';assert str(config.GetProperties())==props_before
  loaded=s.RenderConfig(str(snapshot));record['reload_succeeded']=True
  if not args.save_only:
   def render(owner):
    sess=s.RenderSession(owner)
    try:
     sess.Start();deadline=time.monotonic()+90
     while not sess.HasDone():
      assert time.monotonic()<deadline,'Texture policy render deadline';time.sleep(.01)
     sess.Stop();arrays={};film=sess.GetFilm()
     for key,n in channels.items():
      a=np.zeros((64,96,n),np.uint32 if key=='SAMPLECOUNT' else np.float32);getter=film.GetOutputUInt if key=='SAMPLECOUNT' else film.GetOutputFloat;getter(s.FilmOutputType.names[key],a,0,False);arrays[key]=a
     assert np.all(arrays['SAMPLECOUNT']==1);return arrays
    finally:
     if sess.IsStarted():sess.Stop()
   before=render(config);after=render(loaded)
   for name in channels:assert np.array_equal(before[name].view(np.uint8),after[name].view(np.uint8)),(policy,name)
   np.savez_compressed(args.out/(policy+'-raw.npz'),**before);record['raw_channels_byte_exact']=list(channels)
 finally:
  snapshot.unlink(missing_ok=True);image.unlink(missing_ok=True);Path(str(image)+'.slc-raw-v1.tx').unlink(missing_ok=True);record['own_temporary_files_removed']=not snapshot.exists() and not image.exists();records.append(record);(args.out/'progress.json').write_text(json.dumps(records,indent=2)+'\n');print(json.dumps(record),flush=True)
report={'passed':True,'native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),'expect_unregistered':args.expect_unregistered,'save_only':args.save_only,'cases':records,'scope':__doc__};(args.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
