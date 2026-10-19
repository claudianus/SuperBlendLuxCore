"""Actual RT resize-policy updates, task coverage and dense denoising frames.

The native configuration readback and pixel SAMPLECOUNT are independent checks:
storing the new policy alone cannot prove resized task buffers cover a dense film.
This is a functional regression, not an equal-sample image or performance test.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--diagnostic', action='store_true')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location(
        'resolution_fixture', Path(__file__).with_name('dlss_render_frame_test.py'))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    s = m.slc
    s.Init()
    descriptions = s.GetOpenCLDeviceDescs()
    backend = os.environ.get('SLC_DLSS_RENDER_DEVICE', 'METAL_GPU')
    mask = ''.join('1' if descriptions.Get(n+'.type').GetString() == backend else '0'
                   for n in descriptions.GetAllUniqueSubNames('opencl.device'))
    assert '1' in mask, 'Refusing a CPU fallback'
    names = ('rtpath.resolutionreduction', 'rtpath.resolutionreduction.preview',
             'rtpath.resolutionreduction.preview.step')
    rows = []
    report = dict(passed=False, cases=rows, backend=backend, diagnostic=args.diagnostic,
                  native_sha256=hashlib.file_digest(m.native_path().open('rb'), 'sha256').hexdigest(),
                  performance_eligible=False, scope=__doc__)
    try:
        for coherent, light in ((False, False), (True, False), (False, True), (True, True)):
            scene, _, _ = m.fixture(plane=True)
            config = m.props(f'''
renderengine.type = RTPATHOCL
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
film.width = 320
film.height = 180
film.hw.enable = 0
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
film.outputs.0.type = RGB
film.outputs.0.filename = unused.exr
film.outputs.1.type = SAMPLECOUNT
film.outputs.1.filename = unused-count.exr
rtpath.resolutionreduction = 8
rtpath.resolutionreduction.preview = 16
rtpath.resolutionreduction.preview.step = 2
rtpath.denoisingframes.enable = {int(coherent)}
rtpath.denoisingframes.tilesize = 128
path.lighttracing.auto = 0
path.lighttracing.enable = {int(light)}
path.hybridbackforward.enable = 0
path.vertexconnection.enable = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.clamping.variance.maxvalue = 0
path.spectral.enable = 0
''')
            config.Set(s.Property('opencl.devices.select', mask))
            session = s.RenderSession(s.RenderConfig(config, scene))
            previous_id = previous_epoch = 0
            try:
                session.Start()
                # Populate the original per-film light snapshot before growing
                # the task population; otherwise a lazy allocation hides the
                # stale-capacity bug.
                if light:
                    deadline = time.monotonic() + 10
                    while True:
                        session.WaitNewFrame()
                        initial_light = session.GetFilm().GetStats().Get(
                            'stats.film.total.light.samplecount').GetFloat()
                        if initial_light > 0:
                            break
                        if time.monotonic() > deadline:
                            raise TimeoutError('Initial LIGHT snapshot was never populated')
                # Include policy-only edits, denser task populations and a
                # return to sparse rendering. The last two keep dimensions.
                for index, (w, h, rr, preview, step) in enumerate(
                        [(400, 224, 4, 8, 1), (384, 216, 1, 1, 2),
                         (384, 216, 2, 4, 3), (384, 216, 1, 1, 1)]):
                    properties = m.props(f'film.width = {w}\nfilm.height = {h}\n')
                    requested = dict(zip(names, (rr, preview, step)))
                    for name, value in requested.items():
                        properties.Set(s.Property(name, value))
                    session.Parse(properties)
                    actual = session.GetRenderConfig().GetProperties()
                    returned = {name: actual.Get(name).GetInt() for name in names}
                    row = dict(coherent=coherent, light=light, index=index, size=[w, h],
                               requested=requested, configuration=returned,
                               config_matches=returned == requested)
                    if coherent:
                        deadline = time.monotonic() + 30
                        while True:
                            packet = session.GetDenoisingFrame(previous_id, 100)
                            if packet is not None:
                                previous_id = packet['frame_id']
                                if packet['color'].shape[:2] == (h, w):
                                    break
                            if time.monotonic() >= deadline:
                                raise TimeoutError('No resized complete frame')
                        row.update(dense=bool(np.all(packet['sample_count'] == 1)),
                                   guides_valid=bool(np.all(packet['guides'][:, :, 7] == 1)),
                                   finite=bool(np.isfinite(packet['color']).all()),
                                   epoch=int(packet['scene_epoch']),
                                   epoch_advanced=packet['scene_epoch'] > previous_epoch)
                        previous_epoch = packet['scene_epoch']
                        row['passed'] = all(row[k] for k in
                            ('config_matches', 'dense', 'guides_valid', 'finite', 'epoch_advanced'))
                    else:
                        rgb = np.empty((h, w, 3), np.float32)
                        counts = np.empty((h, w), np.uint32)
                        film = session.GetFilm()
                        # WaitNewFrame can return a synchronization boundary
                        # before the first tile is merged. Observe actual
                        # samples before pausing rather than capture an empty
                        # startup film as a policy failure.
                        deadline = time.monotonic() + 10
                        while True:
                            session.WaitNewFrame()
                            film.GetOutputUInt(s.FilmOutputType.SAMPLECOUNT, counts, 0, False)
                            if np.any(counts) and (rr != 1 or light or np.all(counts > 0)):
                                break
                            if time.monotonic() >= deadline:
                                raise TimeoutError('No sampled film with required coverage')
                            time.sleep(.005)
                        session.Pause()
                        film.GetOutputFloat(s.FilmOutputType.RGB, rgb, 0, False)
                        film.GetOutputUInt(s.FilmOutputType.SAMPLECOUNT, counts, 0, False)
                        row.update(finite=bool(np.isfinite(rgb).all()),
                                   sample_sum=int(counts.sum(dtype=np.uint64)),
                                   pixels_with_samples=int(np.count_nonzero(counts)),
                                   dense=bool(np.all(counts > 0)))
                        row['passed'] = (row['config_matches'] and row['finite'] and
                                         row['sample_sum'] > 0 and (rr != 1 or light or row['dense']))
                        session.Resume()
                    if light:
                        row['light_sample_count'] = session.GetFilm().GetStats().Get(
                            'stats.film.total.light.samplecount').GetFloat()
                        row['passed'] &= row['light_sample_count'] > 0
                    rows.append(row)
                    print(json.dumps(row), flush=True)
            finally:
                if session.IsStarted():
                    session.Stop()
        report['passed'] = len(rows) == 16 and all(row['passed'] for row in rows)
    finally:
        (args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    if not args.diagnostic and not report['passed']:
        raise SystemExit('RT policy/coverage gate failed')


if __name__ == '__main__':
    main()
