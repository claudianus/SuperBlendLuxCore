"""Existing CPU/Metal path engines still compile/render after task layout edits."""
from pathlib import Path
import importlib.util
import os
import json
import time
import hashlib
import numpy as np

source = Path(__file__).with_name('dlss_render_frame_test.py')
spec = importlib.util.spec_from_file_location('frame_fixture', source)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
s = m.slc; s.Init()
desc = s.GetOpenCLDeviceDescs()
mask = ''.join('1' if desc.Get(n+'.type').GetString() == 'METAL_GPU' else '0'
               for n in desc.GetAllUniqueSubNames('opencl.device'))
assert '1' in mask
records = []
for engine, sampler, fixed in [('PATHCPU', 'SOBOL', False), ('RTPATHCPU', 'RTPATHCPUSAMPLER', False),
                                ('PATHOCL', 'SOBOL', False), ('RTPATHOCL', 'TILEPATHSAMPLER', False),
                                ('RTPATHOCL', 'TILEPATHSAMPLER', True)]:
    scene, _, _ = m.fixture()
    cfg = m.props(f'''
renderengine.type = {engine}
sampler.type = {sampler}
opencl.devices.select = {mask}
native.threads.count = 4
opencl.native.threads.count = 0
opencl.task.count = 8192
film.width = 64
film.height = 64
film.imagepipelines.0.0.type = NOP
batch.haltspp = 8
rtpath.resolutionreduction = 1
rtpath.resolutionreduction.preview = 1
path.lighttracing.auto = 0
path.hybridbackforward.enable = 0
path.vertexconnection.enable = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.sampling.pixeljitter.enable = {int(fixed)}
path.sampling.pixeljitter.x = 0.25
path.sampling.pixeljitter.y = -0.125
''')
    session = s.RenderSession(s.RenderConfig(cfg, scene))
    try:
        session.Start(); end = time.monotonic()+30
        while not session.HasDone():
            session.UpdateStats()
            if session.GetStats().Get('stats.renderengine.pass').GetFloat() >= 8: break
            if time.monotonic() > end: raise TimeoutError(engine)
            time.sleep(.01)
        rgb = np.empty((64, 64, 3), np.float32)
        session.GetFilm().GetOutputFloat(s.FilmOutputType.RGB, rgb, 0, False)
        assert np.isfinite(rgb).all() and .001 < rgb.mean() < 10
        records.append({'engine': engine, 'fixed_jitter': fixed, 'finite': True, 'mean': float(rgb.mean())})
    finally:
        if session.IsStarted(): session.Stop()
record = {'native_sha256': hashlib.file_digest(Path(s.pysuperluxcore.__file__).open('rb'), 'sha256').hexdigest(), 'cases': records}
Path(os.environ['SLC_DLSS_ENGINE_SMOKE_OUT']).write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record), flush=True)
