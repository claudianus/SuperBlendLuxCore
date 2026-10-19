"""Actual OpenPBR grazing-light / near-normal-eye transport parity fixture.

No external assets. A narrow spotlight puts almost all emitted rays on a flat
receiver. Its centre has light cosine .1 and eye cosine .9. The integrated ROI
is smooth, positive and avoids per-pixel photon-splat noise comparisons. Two
scrambles check stability; the 5% energy gate is a regression tolerance, not a
confidence interval or proof of general OpenPBR correctness. LIGHTCPU/PATHOCL
light-only and PATHCPU/PATHOCL eye-only are independent transport controls.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import time

import numpy as np


def load_native():
    path = Path(__file__).with_name('dlss_render_frame_test.py')
    spec = importlib.util.spec_from_file_location('lightpath_frame_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(m):
    s = m.slc
    scene = s.Scene()
    # Spotlight coneangle is the half-angle in this engine (spotlight.cpp).
    scene.Parse(m.props(f'''
scene.camera.type = perspective
scene.camera.lookat.orig = {10 * math.sqrt(1 / .9 ** 2 - 1)} 0 10
scene.camera.lookat.target = 0 0 0
scene.camera.up = 0 1 0
scene.camera.fieldofview = 8
scene.materials.receiver.type = openpbr
scene.materials.receiver.basecolor = .65 .65 .65
scene.materials.receiver.baseweight = 1
scene.materials.receiver.basemetalness = 0
scene.materials.receiver.basediffuseroughness = 0
scene.materials.receiver.specularweight = 1
scene.materials.receiver.specularcolor = 1 1 1
scene.materials.receiver.specularroughness = .5
scene.materials.receiver.specularior = 1.5
scene.materials.receiver.transmissionweight = 0
scene.materials.receiver.subsurfaceweight = 0
scene.materials.receiver.coatweight = 0
scene.materials.receiver.fuzzweight = 0
scene.materials.receiver.filmweight = 0
scene.lights.key.type = spot
scene.lights.key.position = {math.sqrt(99)} 0 1
scene.lights.key.target = 0 0 0
scene.lights.key.color = 1 1 1
scene.lights.key.gain = 1000 1000 1000
scene.lights.key.coneangle = .3
scene.lights.key.conedeltaangle = .03
scene.lights.key.cosinecompensation = 0
'''))
    scene.DefineMesh('receiver', [(-4., -4., 0.), (4., -4., 0.),
                                  (4., 4., 0.), (-4., 4., 0.)],
                     [(0, 1, 2), (0, 2, 3)])
    scene.Parse(m.props('scene.objects.receiver.shape = receiver\n'
                        'scene.objects.receiver.material = receiver'))
    return scene


def render(m, engine, mode, spp, seed, out, mask, stop_mode='halt'):
    s = m.slc
    w, h = 96, 64
    cfg = m.props(f'''
renderengine.type = {engine}
renderengine.seed = {seed}
sampler.type = SOBOL
native.threads.count = 4
opencl.native.threads.count = 0
opencl.task.count = 8192
film.width = {w}
film.height = {h}
film.hw.enable = 0
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
film.outputs.0.type = RGB
film.outputs.0.filename = unused.exr
film.outputs.1.type = SAMPLECOUNT
film.outputs.1.filename = unused.exr
batch.haltspp = {spp if stop_mode == 'halt' else 0}
path.pathdepth.total = 3
path.pathdepth.diffuse = 3
path.pathdepth.glossy = 3
path.pathdepth.specular = 3
path.lighttracing.auto = 0
path.lighttracing.enable = {int(mode == 'light')}
path.lighttracing.only = {int(mode == 'light')}
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
    if engine.endswith('OCL'):
        cfg.Set(s.Property('opencl.devices.select', mask))
    session = s.RenderSession(s.RenderConfig(cfg, fixture(m)))
    label = f'{mode}-{engine}-seed{seed}'
    try:
        session.Start()
        deadline = time.monotonic() + 90
        while not session.HasDone():
            if stop_mode == 'manual':
                session.UpdateStats()
                if session.GetStats().Get('stats.renderengine.pass').GetInt() >= spp:
                    break
            if time.monotonic() >= deadline:
                raise TimeoutError(label + ' did not finish within 90s')
            time.sleep(.02)
        session.UpdateStats()
        pass_before_stop = session.GetStats().Get('stats.renderengine.pass').GetInt()
        stats_before = session.GetFilm().GetStats()
        sample_keys = ('stats.film.total.samplecount',
                       'stats.film.total.eye.samplecount',
                       'stats.film.total.light.samplecount')
        counters_before_stop = {key: stats_before.Get(key).GetFloat() for key in sample_keys}
        session.Stop()
        # Read only after worker shutdown, including the final merged splats.
        film = session.GetFilm()
        rgb = np.empty((h, w, 3), np.float32)
        counts = np.empty((h, w, 1), np.uint32)
        film.GetOutputFloat(s.FilmOutputType.RGB, rgb, 0, False)
        film.GetOutputUInt(s.FilmOutputType.SAMPLECOUNT, counts, 0, False)
        # The Python Film binding exposes this through GetStats(), rather
        # than the C++-only GetTotalSampleCount() method. Read after Stop so
        # the count includes the same final merge as the captured RGB.
        final_stats = film.GetStats()
        final_counters = {key: final_stats.Get(key).GetFloat() for key in sample_keys}
        total = float(final_counters['stats.film.total.samplecount'])
        roi = rgb[8:56, 8:88]
        mean = float(np.mean(roi, dtype=np.float64))
        finite = bool(np.isfinite(rgb).all())
        count_sum = int(counts.sum(dtype=np.uint64))
        eye_counts_match = (count_sum == final_counters['stats.film.total.eye.samplecount'])
        # This fixture produces one SAMPLECOUNT increment per eye sample.
        # The per-pixel channel is independent of the host task-stat readback.
        valid = (finite and mean > 1e-8 and total >= spp*w*h and pass_before_stop >= spp
                 and (engine != 'PATHOCL' or mode != 'eye' or eye_counts_match))
        np.savez_compressed(out / (label + '.npz'), RGB=rgb, SAMPLECOUNT=counts)
        row = dict(case=label, engine=engine, mode=mode, seed=seed, stop_mode=stop_mode,
                   requested_spp=spp, pass_before_stop=pass_before_stop,
                   actual_total_samples=total, actual_samples_per_pixel=total/(w*h),
                   counters_before_stop=counters_before_stop,
                   final_counters=final_counters,
                   samplecount_min=int(counts.min()), samplecount_max=int(counts.max()),
                   samplecount_sum=count_sum,
                   eye_samplecount_matches_final_counter=eye_counts_match,
                   samplecount_scope='Splat/hit counts; not uniform SPP for light tracing',
                   finite=finite, roi_mean=mean, passed=valid,
                   roi_xyxy=[8, 8, 88, 56], rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest())
        print(json.dumps(row), flush=True)
        return row
    finally:
        if session.IsStarted():
            session.Stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--engines', nargs='+', default=['LIGHTCPU', 'PATHCPU', 'PATHOCL'])
    parser.add_argument('--spp', type=int, default=1024)
    parser.add_argument('--seeds', nargs='+', type=int, default=[42, 1337])
    parser.add_argument('--stop-mode', choices=['halt', 'manual'], default='halt')
    parser.add_argument('--diagnostic', action='store_true')
    args = parser.parse_args()
    if args.spp < 1 or any(e not in ('LIGHTCPU', 'PATHCPU', 'PATHOCL') for e in args.engines):
        parser.error('Positive spp and engines LIGHTCPU / PATHCPU / PATHOCL required')
    args.out.mkdir(parents=True, exist_ok=False)
    m = load_native()
    s = m.slc
    s.Init()
    device_type = os.environ.get('SLC_DLSS_RENDER_DEVICE', 'METAL_GPU')
    desc = s.GetOpenCLDeviceDescs()
    names = desc.GetAllUniqueSubNames('opencl.device')
    devices = [dict(name=n, type=desc.Get(n+'.type').GetString()) for n in names]
    mask = ''.join('1' if d['type'] == device_type else '0' for d in devices)
    if 'PATHOCL' in args.engines and '1' not in mask:
        raise RuntimeError(device_type + ' unavailable; refusing CPU fallback')
    rows, comparisons, stability = [], [], []
    report = dict(artifact_capture_complete=False, passed=False, diagnostic_only=args.diagnostic,
                  native_sha256=hashlib.file_digest(m.native_path().open('rb'), 'sha256').hexdigest(),
                  devices=devices, selected_device_type=device_type, width=96, height=64,
                  centre_cosines=dict(light=.1, eye=.9), scope=__doc__,
                  stop_mode=args.stop_mode,
                  performance_eligible=False, cases=rows, comparisons=comparisons, stability=stability)
    try:
        for engine in args.engines:
            modes = ['light', 'eye'] if engine == 'PATHOCL' else ['light' if engine == 'LIGHTCPU' else 'eye']
            for mode in modes:
                for seed in args.seeds:
                    rows.append(render(m, engine, mode, args.spp, seed, args.out, mask,
                                       args.stop_mode))
        for mode, cpu in [('light', 'LIGHTCPU'), ('eye', 'PATHCPU')]:
            for seed in args.seeds:
                selected = [r for r in rows if r['mode'] == mode and r['seed'] == seed]
                by_engine = {r['engine']: r for r in selected}
                if cpu in by_engine and 'PATHOCL' in by_engine:
                    a, b = by_engine[cpu]['roi_mean'], by_engine['PATHOCL']['roi_mean']
                    error = abs(b/a-1)
                    comparisons.append(dict(mode=mode, seed=seed, cpu=cpu,
                                            relative_mean_error=error, tolerance=.05, passed=error <= .05))
        for engine, mode in sorted({(r['engine'], r['mode']) for r in rows}):
            selected = [r for r in rows if r['engine'] == engine and r['mode'] == mode]
            means = [r['roi_mean'] for r in selected]
            relative_range = (max(means)-min(means))/max(float(np.mean(means)), 1e-30)
            distinct = len({r['rgb_sha256'] for r in selected}) == len(selected)
            stability.append(dict(engine=engine, mode=mode, replicates=len(selected),
                                  relative_mean_range=relative_range, tolerance=.02,
                                  scramble_outputs_distinct=distinct,
                                  passed=len(selected) >= 2 and distinct and relative_range <= .02))
        report['artifact_capture_complete'] = True
        report['passed'] = (len(comparisons) == 2*len(args.seeds)
                            and args.spp >= 1024 and all(r['passed'] for r in rows)
                            and all(r['passed'] for r in comparisons+stability))
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        (args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    if not args.diagnostic and not report['passed']:
        raise SystemExit('OpenPBR transport parity/stability gate failed; inspect result.json')


if __name__ == '__main__':
    main()
