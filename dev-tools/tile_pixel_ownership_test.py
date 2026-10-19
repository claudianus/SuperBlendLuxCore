"""Every tiled camera sample must remain owned by its selected pixel.

Use ordinary Sobol subpixel sampling, not fixed DLSS frame jitter. Large rasters
exercise rare float rounding that small coverage fixtures can miss. The stopped
film must contain exactly AA^2 samples in every active pixel. Baseline defect
mode records the failure as reproduction evidence, never as a quality pass.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

import numpy as np

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'pixel_ownership_fixture', root / 'dev-tools/dlss_render_frame_test.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
s = m.slc
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--cases', nargs='+')
parser.add_argument('--expect-defect', action='store_true')
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=False)
s.Init()
cases = [
    ('metal-720-aa2', 'TILEPATHOCL', 1280, 720, 2, 32, 42),
    ('cpu-720-aa2', 'TILEPATHCPU', 1280, 720, 2, 32, 42),
    ('metal-odd-aa1', 'TILEPATHOCL', 1365, 769, 1, 32, 143),
    ('metal-odd-aa4', 'TILEPATHOCL', 257, 145, 4, 64, 907),
    ('cpu-odd-aa4', 'TILEPATHCPU', 257, 145, 4, 64, 907),
]
if args.cases:
    assert set(args.cases) <= {case[0] for case in cases}
    cases = [case for case in cases if case[0] in args.cases]
records = []
for label, engine, width, height, aa, tile, seed in cases:
    scene, _, _ = m.fixture(plane=True)
    cfg = m.props(f'''
renderengine.type={engine}
sampler.type=TILEPATHSAMPLER
native.threads.count=4
opencl.native.threads.count=0
film.width={width}
film.height={height}
film.hw.enable=0
film.filter.type=NONE
film.imagepipelines.0.0.type=NOP
film.outputs.0.type=RGB
film.outputs.0.filename=unused.exr
film.outputs.1.type=SAMPLECOUNT
film.outputs.1.filename=unused.exr
tile.size={tile}
tile.multipass.enable=0
tilepath.sampling.aa.size={aa}
renderengine.seed={seed}
path.pathdepth.total=4
path.sampling.pixeljitter.enable=0
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
''')
    if engine.endswith('OCL'):
        desc = s.GetOpenCLDeviceDescs()
        device = os.environ.get('SLC_DLSS_RENDER_DEVICE', 'METAL_GPU')
        mask = ''.join('1' if desc.Get(name + '.type').GetString() == device else '0'
                       for name in desc.GetAllUniqueSubNames('opencl.device'))
        assert '1' in mask
        cfg.Set(s.Property('opencl.devices.select', mask))
    session = s.RenderSession(s.RenderConfig(cfg, scene))
    try:
        session.Start()
        deadline = time.monotonic() + 120
        while not session.HasDone():
            assert time.monotonic() < deadline, label
            time.sleep(.01)
        session.Stop()
        film = session.GetFilm()
        counts = np.zeros((height, width), np.uint32)
        rgb = np.zeros((height, width, 3), np.float32)
        film.GetOutputUInt(s.FilmOutputType.SAMPLECOUNT, counts, 0, False)
        film.GetOutputFloat(s.FilmOutputType.RGB, rgb, 0, False)
        values, pixels = np.unique(counts, return_counts=True)
        bad = np.argwhere(counts != aa * aa)
        row = {
            'case': label, 'engine': engine, 'size': [width, height],
            'aa': aa, 'tile': tile, 'seed': seed,
            'fixed_frame_jitter': False,
            'sample_distribution': dict(zip(map(str, values.tolist()), pixels.tolist())),
            'bad_pixels': [dict(x=int(x), y_bottom_up=int(y), count=int(counts[y, x]))
                           for y, x in bad],
            'strict_pixel_ownership_passed': len(bad) == 0,
            'total': int(counts.sum(dtype=np.uint64)),
            'expected_total': width * height * aa * aa,
            'finite_rgb': bool(np.isfinite(rgb).all()),
            'mean_rgb': rgb.mean((0, 1), dtype=np.float64).tolist(),
        }
        records.append(row)
        np.savez_compressed(args.out / (label + '.npz'), counts=counts, rgb=rgb)
        (args.out / 'progress.json').write_text(json.dumps(records, indent=2) + '\n')
        print(json.dumps({k: v for k, v in row.items() if k != 'bad_pixels'}), flush=True)
        assert row['finite_rgb'] and np.any(rgb > 0)
        assert row['total'] == row['expected_total']
        assert bool(len(bad)) == args.expect_defect, row
    finally:
        if session.IsStarted():
            session.Stop()

report = dict(passed=True, expect_defect=args.expect_defect, cases=records,
              native_sha256=hashlib.file_digest(m.native_path().open('rb'), 'sha256').hexdigest(),
              scope=__doc__, performance_eligible=False)
(args.out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
