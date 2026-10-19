"""Coherent RGB-only films must produce nonblack RGBA leases with opaque alpha."""
import argparse,importlib.util,sys,json,time,os,hashlib
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('rgb_frame_fixture',Path(__file__).with_name('dlss_render_frame_test.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);s=m.slc
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
s.Init();scene,_,_=m.fixture(plane=True)
device=os.environ.get('SLC_DLSS_RENDER_DEVICE','METAL_GPU');desc=s.GetOpenCLDeviceDescs();mask=''.join('1' if desc.Get(n+'.type').GetString()==device else '0' for n in desc.GetAllUniqueSubNames('opencl.device'));assert '1' in mask
cfg=m.props(f'''renderengine.type = RTPATHOCL
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
opencl.devices.select = {mask}
film.width = 64
film.height = 48
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
film.outputs.0.type = RGB_IMAGEPIPELINE
film.outputs.0.filename = unused.png
rtpath.denoisingframes.enable = 1
path.pathdepth.total = 4
path.lighttracing.auto = 0
path.lighttracing.enable = 0
path.hybridbackforward.enable = 0
path.vertexconnection.enable = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.spectral.enable = 0
''')
session=s.RenderSession(s.RenderConfig(cfg,scene))
try:
    session.Start();packet=None;end=time.monotonic()+120
    while packet is None:
        if time.monotonic()>end:raise TimeoutError('RGB-only frame')
        packet=session.GetDenoisingFrame(0,100)
    assert packet['complete']
    session.Pause();session.UpdateStats()
    canonical=np.empty((48,64,3),np.float32);session.GetFilm().GetOutputFloat(s.FilmOutputType.RGB,canonical,0,False)
    result={'native_sha256':hashlib.sha256(m.native_path().read_bytes()).hexdigest(),'canonical_rgb_max':float(canonical.max()),'frame_rgb_max':float(packet['color'][:,:,:3].max()),'frame_alpha_range':[float(packet['color'][:,:,3].min()),float(packet['color'][:,:,3].max())],'device':device}
    assert np.isfinite(canonical).all() and canonical.max()>0
    (a.out/'result.json').write_text(json.dumps(result,indent=2));print('RGB_ONLY_FRAME',result,flush=True)
    assert np.isfinite(packet['color']).all() and packet['color'][:,:,:3].max()>0
    np.testing.assert_array_equal(packet['color'][:,:,3],1)
finally:
    if session.IsStarted():session.Stop()
