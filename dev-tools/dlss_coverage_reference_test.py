"""Canonical transport-alpha and primary-position references for SR coverage.

Use an isolated native module and bounded supervisor. This reference does not
replace the full-resolution GPU coverage producer or prove SR image quality.
Glass alpha follows the current renderer's sampled transport convention, not
an analytic optical-transmittance claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import numpy as np
sys.path.insert(0, os.environ['SLC_DLSS_RENDER_MODULE'])
import pysuperluxcore as s


def props(text):
    result = s.Properties();result.SetFromString(text);return result


def fixture(material, background=False):
    scene = s.Scene()
    scene.Parse(props('scene.camera.lookat.orig=0 -5 0\nscene.camera.lookat.target=0 0 0\nscene.camera.up=0 0 1\nscene.camera.fieldofview=45\nscene.lights.environment.type=constantinfinite\nscene.lights.environment.color=0.2 0.3 0.4\nscene.materials.opaque.type=matte\nscene.materials.opaque.kd=0.5 0.5 0.5\nscene.materials.cutout.type=matte\nscene.materials.cutout.kd=0.5 0.5 0.5\nscene.materials.cutout.transparency=0.5 0.5 0.5\nscene.materials.null.type=null\nscene.materials.glass.type=glass\nscene.materials.glass.kr=1 1 1\nscene.materials.glass.kt=1 1 1\nscene.materials.glass.exteriorior=1\nscene.materials.glass.interiorior=1.5\nscene.materials.holdout.type=matte\nscene.materials.holdout.kd=0.5 0.5 0.5\nscene.materials.holdout.holdout.enable=1\n'))
    y = -50. if background else 3.
    scene.DefineMesh('wall', [(-100., y, -100.), (100., y, -100.), (100., y, 100.), (-100., y, 100.)], [(0, 1, 2), (0, 2, 3)])
    scene.Parse(props('scene.objects.wall.shape=wall\nscene.objects.wall.material='+material))
    return scene


def render(engine, material, background=False, size=(192, 108)):
    w, h = size
    cfg = props('native.threads.count=4\nopencl.native.threads.count=0\nopencl.task.count=8192\nsampler.type=TILEPATHSAMPLER\ntile.size=64\ntilepathocl.devices.maxtiles=2\ntilepath.sampling.aa.size=2\ntile.multipass.enable=0\nfilm.filter.type=NONE\nfilm.imagepipelines.0.0.type=NOP\nfilm.hw.enable=0\nscene.epsilon.min=0.00001\nscene.epsilon.max=0.1\npath.pathdepth.total=8\npath.pathdepth.diffuse=8\npath.shadowterminator=chiang\npath.lighttracing.auto=0\npath.hybridbackforward.enable=0\npath.vertexconnection.enable=0\npath.mnee.auto=0\npath.mnee.enable=0\npath.guiding.enable=0\npath.photongi.indirect.enabled=0\npath.photongi.caustic.enabled=0\npath.spectral.enable=0\npath.sampling.pixeljitter.enable=1\npath.sampling.pixeljitter.x=0\npath.sampling.pixeljitter.y=0\npathocl.wavefront=off\n')
    for name, value in [('renderengine.type', engine), ('film.width', w), ('film.height', h)]:
        cfg.Set(s.Property(name, value))
    if engine.endswith('OCL'):
        devices = s.GetOpenCLDeviceDescs();device = os.environ.get('SLC_DLSS_RENDER_DEVICE', 'METAL_GPU')
        mask = ''.join('1' if devices.Get(n+'.type').GetString()==device else '0' for n in devices.GetAllUniqueSubNames('opencl.device'))
        assert mask.count('1')==1, mask
        cfg.Set(s.Property('opencl.devices.select', mask))
    for i, kind in enumerate(['RGBA', 'POSITION', 'SAMPLECOUNT']):
        cfg.Set(s.Property('film.outputs.%d.type'%i, kind));cfg.Set(s.Property('film.outputs.%d.filename'%i, 'unused.exr'))
    scene = fixture(material, background)
    config = s.RenderConfig(cfg, scene);session = s.RenderSession(config)
    try:
        session.Start();end = time.monotonic()+120
        while not session.HasDone():
            if time.monotonic()>end:raise TimeoutError('Coverage reference did not halt')
            time.sleep(.005)
        result = {}
        for kind, channels in [('RGBA', 4), ('POSITION', 3), ('SAMPLECOUNT', 1)]:
            integer = kind=='SAMPLECOUNT';a = np.empty((h, w, channels), np.uint32 if integer else np.float32)
            method = session.GetFilm().GetOutputUInt if integer else session.GetFilm().GetOutputFloat
            method(getattr(s.FilmOutputType, kind), a, 0, False);result[kind]=a
        assert np.all(result['SAMPLECOUNT']==4)
        assert np.isfinite(result['RGBA']).all()
        return result
    finally:
        if session.IsStarted():session.Stop()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--engine',required=True);parser.add_argument('--out',type=Path,required=True);a=parser.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    s.Init();native=Path(getattr(s,'pysuperluxcore',s).__file__)
    report={'engine':a.engine,'native_sha256':hashlib.file_digest(native.open('rb'),'sha256').hexdigest(),'scope':__doc__,'checks':[]}
    failures=[]
    for name, material, background, expected in [('opaque','opaque',False,1.),('cutout','cutout',False,.5),('null','null',False,0.),('holdout','holdout',False,0.),('background','opaque',True,0.),('glass','glass',False,None)]:
        data=render(a.engine, material, background);alpha=data['RGBA'][:,:,3]
        row={'case':name,'alpha_min':float(alpha.min()),'alpha_max':float(alpha.max()),'alpha_mean':float(alpha.mean()),'finite':True,'sample_count':4}
        np.savez_compressed(a.out/(name+'.npz'),**data)
        if expected is not None:
            row['expected_constant_alpha']=expected;row['max_alpha_error']=float(np.max(np.abs(alpha-expected)));row['passed']=row['max_alpha_error']<1e-6
        else:
            row['passed']=bool(.15<float(alpha.mean())<.35 and np.any(alpha<1.) and np.any(alpha>0.))
            row['qualification']='Current glass proposal clamps branch probabilities; sampled transport alpha is expected near0.25 here. This is a preservation reference, not Fresnel opacity validation.'
        if name in ['opaque','glass','holdout']:
            h,w=alpha.shape;yy,xx=np.meshgrid(np.arange(h)+.5,np.arange(w)+.5,indexing='ij');position=data['POSITION'];f=w/(2*np.tan(np.deg2rad(45)/2))
            px=w/2+f*position[:,:,0]/(position[:,:,1]+5);py=h/2+f*position[:,:,2]/(position[:,:,1]+5)
            row['primary_projection_max_pixels']=float(max(np.max(np.abs(px-xx)),np.max(np.abs(py-yy))))
            row['passed']=row['passed'] and row['primary_projection_max_pixels']<1e-3
        report['checks'].append(row)
        if not row['passed']:failures.append(name)
        (a.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)
    assert not failures, failures
