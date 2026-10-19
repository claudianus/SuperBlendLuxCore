"""Sellmeier data images are raw coefficients, including vector/composed inputs.

Compare a red (1,0,0) coefficient texture to the identical constant coefficient
through an actual refractive interface and emissive receiver. RGB and spectral
transport must preserve this identity on each backend; no spectral RGB reference
or cross-backend path equality is inferred.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import numpy as np

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('raw_spectrum_fixture',root/'dev-tools/dlss_render_frame_test.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);s=m.slc
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--diagnostic',action='store_true');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False);s.Init()
desc=s.GetOpenCLDeviceDescs();mask=''.join('1' if desc.Get(n+'.type').GetString()=='METAL_GPU' else '0' for n in desc.GetAllUniqueSubNames('opencl.device'));assert '1' in mask
pixels=np.zeros((32,32,3),np.uint8);pixels[:,:16,0]=255;pixels[:,16:,1]=255
image=a.out/'coefficients.ppm';image.write_bytes(b'P6\n32 32\n255\n'+pixels.tobytes())
rows=[];comparisons=[]
for spectral in (False,True):
    for engine in ('TILEPATHCPU','TILEPATHOCL'):
        captures={}
        for variant,coefficient in [('constant','1 0 0'),('image','pic'),('composed','identity')]:
            label=f'{int(spectral)}-{engine}-{variant}'
            scene=s.Scene();scene.Parse(m.props(f'''
scene.camera.lookat.orig=0 -5 0
scene.camera.lookat.target=0 0 0
scene.camera.up=0 0 1
scene.camera.fieldofview=10
scene.textures.pic.type=imagemap
scene.textures.pic.file={image.resolve()}
scene.textures.pic.colorspace=nop
scene.textures.pic.storage=float
scene.textures.pic.vector=0.125 0.125 0
scene.textures.identity.type=scale
scene.textures.identity.texture1=pic
scene.textures.identity.texture2=1
scene.materials.glass.type=glass
scene.materials.glass.kr=1 1 1
scene.materials.glass.kt=1 1 1
scene.materials.glass.interiorior=1.5
scene.materials.glass.sellmeierb={coefficient}
scene.materials.glass.sellmeierc=0.01 0.02 0.03
scene.materials.receiver.type=matte
scene.materials.receiver.kd=0 0 0
scene.materials.receiver.emission=0.65 0.65 0.65
scene.materials.receiver.emission.directlightsampling.type=DISABLED
'''))
            for name,y,material in [('glass',0.,'glass'),('receiver',1.,'receiver')]:
                scene.DefineMesh(name,[(-4,y,-3),(4,y,-3),(4,y,3),(-4,y,3)],[(0,1,2),(0,2,3)],None,[(0.,0.),(1.,0.),(1.,1.),(0.,1.)])
                scene.Parse(m.props(f'scene.objects.{name}.shape={name}\nscene.objects.{name}.material={material}'))
            cfg=m.props(f'''
renderengine.type={engine}
sampler.type=TILEPATHSAMPLER
native.threads.count=4
opencl.native.threads.count=0
opencl.devices.select={mask}
film.width=48
film.height=32
film.hw.enable=0
film.filter.type=NONE
film.imagepipelines.0.0.type=NOP
tile.size=32
tile.multipass.enable=0
tilepath.sampling.aa.size=2
path.pathdepth.total=8
path.pathdepth.specular=8
path.lighttracing.auto=0
path.lighttracing.enable=0
path.hybridbackforward.enable=0
path.vertexconnection.enable=0
path.mnee.auto=0
path.mnee.enable=0
path.guiding.enable=0
path.photongi.caustic.enabled=0
path.photongi.indirect.enabled=0
path.spectral.enable={int(spectral)}
film.outputs.0.type=RGB
film.outputs.0.filename=unused.exr
film.outputs.1.type=SAMPLECOUNT
film.outputs.1.filename=unused.exr
''')
            session=s.RenderSession(s.RenderConfig(cfg,scene))
            try:
                session.Start();deadline=time.monotonic()+90
                while not session.HasDone():
                    assert time.monotonic()<deadline,label
                    time.sleep(.01)
                session.Stop();rgb=np.zeros((32,48,3),np.float32);count=np.zeros((32,48,1),np.uint32)
                session.GetFilm().GetOutputFloat(s.FilmOutputType.RGB,rgb,0,False)
                session.GetFilm().GetOutputUInt(s.FilmOutputType.SAMPLECOUNT,count,0,False)
                assert np.isfinite(rgb).all() and np.any(rgb>0) and np.all(count==4),label
                captures[variant]=rgb;np.savez_compressed(a.out/(label+'.npz'),RGB=rgb,SAMPLECOUNT=count)
                rows.append({'case':label,'spectral':spectral,'engine':engine,'variant':variant,'mean_RGB':rgb.mean((0,1),dtype=np.float64).tolist(),'finite':True,'all_pixels4':True})
            finally:
                if session.IsStarted():session.Stop()
        for variant in ('image','composed'):
            error=float(np.abs(captures[variant]-captures['constant']).max());passed=error<1e-5
            comparisons.append({'spectral':spectral,'engine':engine,'variant':variant,'max_abs_RGB_error':error,'tolerance':1e-5,'passed':passed})
report={'passed':all(r['passed'] for r in comparisons),'artifact_capture_complete':True,'diagnostic_only':a.diagnostic,'cases':rows,'comparisons':comparisons,'scope':__doc__,'native_sha256':hashlib.file_digest(m.native_path().open('rb'),'sha256').hexdigest(),'performance_eligible':False}
(a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(comparisons),flush=True)
if not a.diagnostic:assert report['passed'],report
