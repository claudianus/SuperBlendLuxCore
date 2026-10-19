"""Actual coherent presentation with many raw AOVs and display pipelines.

The unavailable baseline is retained and compared with the new native capture.
No renderer budget is raised and no canonical channel is disabled.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(os.environ.get('SLC_DLSS_TEST_ADDON', str(Path(__file__).resolve().parents[1])))
def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

m = load('presentation_budget_fixture', ROOT/'dev-tools/dlss_render_frame_test.py')
s = m.slc
d = load('presentation_budget_backend', ROOT/'engine/dlss.py')
parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--expect', choices=['available', 'unavailable'], default='available')
parser.add_argument('--dlss', action='store_true')
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
s.Init()
device = os.environ.get('SLC_DLSS_RENDER_DEVICE', 'METAL_GPU')
descs = s.GetOpenCLDeviceDescs()
mask = ''.join('1' if descs.Get(n+'.type').GetString() == device else '0'
               for n in descs.GetAllUniqueSubNames('opencl.device'))
assert '1' in mask
channels = {'RGB': 3, 'ALPHA': 1, 'ALBEDO': 3, 'AVG_SHADING_NORMAL': 3,
            'DEPTH': 1, 'POSITION': 3, 'SAMPLECOUNT': 1, 'OBJECT_ID': 1,
            'GEOMETRY_NORMAL': 3, 'SHADING_NORMAL': 3, 'DIRECT_DIFFUSE': 3,
            'DIRECT_DIFFUSE_REFLECT': 3, 'DIRECT_DIFFUSE_TRANSMIT': 3,
            'DIRECT_GLOSSY': 3, 'DIRECT_GLOSSY_REFLECT': 3, 'DIRECT_GLOSSY_TRANSMIT': 3,
            'EMISSION': 3, 'INDIRECT_DIFFUSE': 3, 'INDIRECT_DIFFUSE_REFLECT': 3,
            'INDIRECT_DIFFUSE_TRANSMIT': 3, 'INDIRECT_GLOSSY': 3,
            'INDIRECT_GLOSSY_REFLECT': 3, 'INDIRECT_GLOSSY_TRANSMIT': 3,
            'INDIRECT_SPECULAR': 3, 'INDIRECT_SPECULAR_REFLECT': 3,
            'INDIRECT_SPECULAR_TRANSMIT': 3}

def outputs(native, w, h):
    result = {}
    for name, count in channels.items():
        uint = name in ('SAMPLECOUNT', 'OBJECT_ID')
        pixels = np.empty((h, w, count), np.uint32 if uint else np.float32)
        getter = native.GetFilm().GetOutputUInt if uint else native.GetFilm().GetOutputFloat
        getter(s.FilmOutputType.names[name], pixels, 0, False)
        result[name] = pixels
    return result

cases = [('many-aovs', 1280, 720, 'NOP'), ('alpha', 160, 96, 'PREMULTIPLY_ALPHA'),
         ('cpu-only-aov', 160, 96, 'OUTPUT_SWITCHER')]
if args.expect == 'unavailable':
    cases = cases[:1]
records = []
for name, w, h, plugin in cases:
    scene, _, _ = m.fixture()
    for obj in ('back', 'left', 'right', 'ceiling'):
        scene.DeleteObject(obj)
    cfg = m.props(f'''renderengine.type = RTPATHOCL
renderengine.seed = 131
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
opencl.devices.select = {mask}
film.width = {w}
film.height = {h}
film.filter.type = NONE
film.denoisingguides.enable = 1
rtpath.denoisingframes.enable = 1
rtpath.denoisingframes.lossless = 1
rtpath.denoisingframes.haltspp = 2
rtpath.denoisingframes.imagepipeline.enable = 1
rtpath.denoisingframes.imagepipeline.accumulated = 1
rtpath.denoisingframes.input.reduction = 2
batch.haltspp = 2
path.pathdepth.total = 6
path.pathdepth.diffuse = 6
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
    for i, output in enumerate(channels):
        cfg.Set(s.Property(f'film.outputs.{i}.type', output))
        cfg.Set(s.Property(f'film.outputs.{i}.filename', 'unused.png' if output == 'OBJECT_ID' else 'unused.exr'))
    for index in range(20):
        cfg.Set(s.Property(f'film.imagepipelines.{index}.0.type', plugin if index == 0 else 'NOP'))
        cfg.Set(s.Property(f'film.imagepipelines.{index}.1.type', 'TONEMAP_LINEAR'))
        cfg.Set(s.Property(f'film.imagepipelines.{index}.1.scale', 1.))
        i = len(channels) + index
        cfg.Set(s.Property(f'film.outputs.{i}.type', 'RGBA_IMAGEPIPELINE'))
        cfg.Set(s.Property(f'film.outputs.{i}.index', index))
        cfg.Set(s.Property(f'film.outputs.{i}.filename', f'pipeline-{index}.exr'))
    if plugin == 'OUTPUT_SWITCHER':
        cfg.Set(s.Property('film.imagepipelines.0.0.channel', 'DIRECT_DIFFUSE'))
    native = s.RenderSession(s.RenderConfig(cfg, scene))
    backend = consumer = None
    frames = []
    try:
        if args.dlss:
            backend = d.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'], os.environ['SUPERLUXCORE_DLSS_CACHE'],
                                 library=os.environ['SLC_DLSS_TEST_LIBRARY'])
            consumer = d.RendererDLSS(backend)
        native.Start()
        after = 0
        for sample in (1, 2):
            end = time.monotonic() + 120
            packet = native.GetDenoisingFrame(after, 100)
            while packet is None and time.monotonic() < end:
                packet = native.GetDenoisingFrame(after, 100)
            assert packet is not None, name
            assert packet['complete'] and packet['accumulated_eye_samples'] == sample
            before = outputs(native, w, h)
            assert np.all(before['SAMPLECOUNT'] == sample)
            np.savez_compressed(args.out/f'{name}-frame{sample}.npz', **before)
            available = packet['image_pipeline_available']
            if args.expect == 'unavailable':
                assert not available
                assert 'exceed rtpath.denoisingframes.imagepipeline.maxbytes' in packet['image_pipeline_error']
            else:
                assert available, packet['image_pipeline_error']
                assert packet['image_pipeline_channel_bytes'] <= 256*1024**2
                assert packet['target_alpha'].shape == (h, w)
                raw = s.DenoisingImagePipeline().process(packet)
                reference = np.empty((h, w, 4), np.float32)
                native.GetFilm().GetOutputFloat(s.FilmOutputType.RGBA_IMAGEPIPELINE, reference, 0, True)
                np.testing.assert_allclose(raw, reference, atol=1e-6, rtol=0)
                if consumer is not None:
                    image = consumer.process(packet, output_size=(w, h))
                    result = s.DenoisingImagePipeline().process(packet, image, reset=True)
                    assert result.shape == (h, w, 4) and np.isfinite(result).all()
                    np.save(args.out/f'{name}-dlss-frame{sample}.npy', result)
            actual = outputs(native, w, h)
            for key in channels:
                np.testing.assert_array_equal(before[key], actual[key], err_msg=key)
            frames.append({'sample': sample, 'available': available,
                'channel_bytes': packet['image_pipeline_channel_bytes'], 'error': packet['image_pipeline_error'],
                'source_size': list(packet['color'].shape[:2][::-1]), 'target_size': [w, h],
                'raw_channels_bit_exact_during_processing': list(channels)})
            after = packet['frame_id']
            native.UpdateStats()
            native.AcknowledgeDenoisingFrame(packet)
        records.append({'case': name, 'frames': frames, 'sdk_evaluations': backend.stats()['frames'] if backend else 0})
    finally:
        if native.IsStarted():
            native.Stop()
        if backend is not None:
            backend.close()
report = {'native_sha256': hashlib.sha256(m.native_path().read_bytes()).hexdigest(), 'device': device,
          'expected': args.expect, 'image_pipeline_budget_bytes': 256*1024**2,
          'canonical_channels': list(channels), 'cases': records,
          'scope': 'Actual GPU 2SPP lossless frames, 26 raw AOVs and 20 display pipelines; primary/alpha/CPU-only channel semantics. No performance or general quality claim.'}
(args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report), flush=True)
