"""Real CUDA session construction with an explicitly expected OptiX loader state.

Run in separate processes with and without libnvoptix on the library path.
This does not start tracing, compile a kernel, or assert render performance.
"""
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'cuda_availability_fixture', Path(__file__).with_name('dlss_render_frame_test.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
s = fixture.slc
s.Init()
platform = s.GetPlatformDesc()
assert platform.Get('compile.LUXRAYS_ENABLE_CUDA').GetBool(), 'CUDA is unavailable'
expected = os.environ['SLC_EXPECT_OPTIX'] == '1'
available = platform.Get('compile.LUXRAYS_ENABLE_OPTIX').GetBool()
assert available == expected, (available, expected)

descriptions = s.GetOpenCLDeviceDescs()
mask = ''.join('1' if descriptions.Get(name+'.type').GetString() == 'CUDA_GPU' else '0'
               for name in descriptions.GetAllUniqueSubNames('opencl.device'))
assert mask.count('1') == 1, 'The bounded test requires one CUDA GPU'
scene, _, _ = fixture.fixture()
props = fixture.props('''
renderengine.type = TILEPATHOCL
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
film.width = 32
film.height = 32
film.hw.enable = 0
film.imagepipelines.0.0.type = NOP
''')
props.Set(s.Property('opencl.devices.select', mask))
config = s.RenderConfig(props, scene)
session = s.RenderSession(config)
assert not session.IsStarted()
del session, config, scene
gc.collect()
print(json.dumps({'native_sha256': hashlib.sha256(fixture.native_path().read_bytes()).hexdigest(),
                  'cuda_available': True, 'optix_available': available,
                  'session_constructed_and_released': True,
                  'scope': 'Real CUDA context creation and loader failure fallback, no tracing/JIT/quality or speed claim.'}, indent=2))
