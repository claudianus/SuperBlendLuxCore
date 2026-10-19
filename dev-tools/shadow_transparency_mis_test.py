"""NEE owns emission across the renderer's special shadow-transparency connection.

A diffuse floor sees a unit constant environment through camera-opaque ceilings.
The existing indirect-eye approximation passes through them without scattering;
the connection must neither consume bounce depth nor count an emitter twice.
The floor radiance is albedo * product(transmittance). Depth1 and an unobstructed
control protect ordinary MIS. Finite extent100 edge errors fit the2.5% MC gate.
This is an explicit artist shadow-override contract, not physical glass.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import numpy as np

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'shadow_mis_fixture', root / 'dev-tools/dlss_render_frame_test.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
s = m.slc
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, required=True)
parser.add_argument('--expect-gpu-loss', action='store_true')
parser.add_argument('--diagnostic', action='store_true', help='Capture failed analytic gates without promoting them')
parser.add_argument('--cases', nargs='+')
parser.add_argument('--aa', type=int, default=8)
parser.add_argument('--extent', type=float, default=100.)
parser.add_argument('--finite-target', action='store_true',
                    help='Exercise a real emissive landing beyond the panes')
parser.add_argument('--target-extent', type=float, default=4.,
                    help='Finite emitter half-width; environment fills the other directions')
parser.add_argument('--finite-dls', choices=['AUTO', 'ENABLED', 'DISABLED'], default='AUTO',
                    help='Emitter direct-light sampling coverage; emission itself stays enabled')
parser.add_argument('--target-grid', type=int, default=1,
                    help='Emitter grid resolution;12 gives288 triangles and exercises AUTO DLS-off')
parser.add_argument('--engines', nargs='+', choices=['TILEPATHCPU', 'TILEPATHOCL'],
                    default=['TILEPATHCPU', 'TILEPATHOCL'])
parser.add_argument('--spectral', action='store_true')
parser.add_argument('--epsilon-min', type=float)
parser.add_argument('--endpoint-gap', type=float,
                    help='Put the single shadow pane this distance below a finite emitter')
args = parser.parse_args()
assert 1 <= args.target_grid <= 32
args.out.mkdir(exist_ok=False, parents=True)
s.Init()
desc = s.GetOpenCLDeviceDescs()
mask = ''.join('1' if desc.Get(n + '.type').GetString() == 'METAL_GPU' else '0'
               for n in desc.GetAllUniqueSubNames('opencl.device'))
assert '1' in mask
records = []
cases = [('open', 0, 1., 4), ('one-white', 1, 1., 4),
         ('two-half', 2, .5, 4), ('three-half', 3, .5, 4),
         ('twenty-white', 20, 1., 4),
         ('one-white-terminal', 1, 1., 1)]
target_dls_enabled = (args.finite_dls == 'ENABLED' or
                      (args.finite_dls == 'AUTO' and 2 * args.target_grid ** 2 <= 256))
if args.finite_target and not target_dls_enabled:
    # A terminal depth1 receiver has no BSDF continuation. When this emitter
    # is excluded from NEE, unit radiance is not its bounded-depth solution.
    if args.cases and 'one-white-terminal' in args.cases:
        parser.error('depth1 analytic control requires finite emitter DLS coverage')
    cases = [case for case in cases if case[0] != 'one-white-terminal']
if args.cases:
    assert set(args.cases) <= {case[0] for case in cases}
    cases = [case for case in cases if case[0] in args.cases]
if args.endpoint_gap is not None:
    if not args.finite_target or args.endpoint_gap <= 0 or any(c[1] > 1 for c in cases):
        parser.error('endpoint-gap requires finite-target,positive gap and at most one pane')
for label, layers, transmission, depth in cases:
    for engine in args.engines:
        scene = s.Scene()
        scene.Parse(m.props(f'''
scene.camera.lookat.orig=0 -5 1.5
scene.camera.lookat.target=0 0 0
scene.camera.up=0 0 1
scene.camera.fieldofview=20
scene.materials.floor.type=matte
scene.materials.floor.kd=.65 .65 .65
scene.materials.ceiling.type=matte
scene.materials.ceiling.kd=0 0 0
scene.materials.ceiling.transparency.shadow={transmission} {transmission} {transmission}
scene.materials.ceiling.transparency.shadowoverride=1
scene.lights.env.type=constantinfinite
scene.lights.env.color=1 1 1
'''))
        def quad(name, z, ceiling, material=None, extent=None):
            extent = args.extent if extent is None else extent
            points = [(-extent, -extent, z), (extent, -extent, z),
                      (extent, extent, z), (-extent, extent, z)]
            tris = [(0, 2, 1), (0, 3, 2)] if ceiling else [(0, 1, 2), (0, 2, 3)]
            if name == 'target' and args.target_grid > 1:
                n = args.target_grid
                points = [(-extent + 2 * extent * x / n,
                           -extent + 2 * extent * y / n, z)
                          for y in range(n + 1) for x in range(n + 1)]
                tris = []
                for y in range(n):
                    for x in range(n):
                        a = y * (n + 1) + x
                        b, c, d = a + 1, a + n + 2, a + n + 1
                        tris.extend([(a, c, b), (a, d, c)] if ceiling
                                    else [(a, b, c), (a, c, d)])
            scene.DefineMesh(name, points, tris)
            scene.Parse(m.props(f'scene.objects.{name}.shape={name}\n'
                                f'scene.objects.{name}.material=' +
                                (material or ('ceiling' if ceiling else 'floor'))))
        quad('floor', 0., False)
        for layer in range(layers):
            z = (4. + layers - args.endpoint_gap if args.endpoint_gap is not None
                 else 3. + layer)
            quad('ceiling' + str(layer), z, True)
        if args.finite_target:
            # A finite emitter plus the unit environment have the same radiance
            # in every upward direction, retaining the analytic expectation.
            scene.Parse(m.props('scene.materials.target.type=matte\n'
                                'scene.materials.target.kd=0 0 0\n'
                                'scene.materials.target.emission=1 1 1\n'
                                'scene.materials.target.emission.directlightsampling.type=' + args.finite_dls))
            quad('target', 4. + layers, True, material='target',
                 extent=args.target_extent)
        (args.out / (label + '-' + engine + '-scene.txt')).write_text(str(scene.ToProperties()))
        cfg = m.props(f'''
renderengine.type={engine}
sampler.type=TILEPATHSAMPLER
native.threads.count=4
opencl.native.threads.count=0
opencl.devices.select={mask}
film.width=96
film.height=64
film.hw.enable=0
film.filter.type=NONE
film.imagepipelines.0.0.type=NOP
film.outputs.0.type=RGB
film.outputs.0.filename=unused.exr
film.outputs.1.type=SAMPLECOUNT
film.outputs.1.filename=unused.exr
film.outputs.2.type=DIRECT_DIFFUSE
film.outputs.2.filename=unused.exr
film.outputs.3.type=INDIRECT_DIFFUSE
film.outputs.3.filename=unused.exr
tile.size=32
tile.multipass.enable=0
tilepath.sampling.aa.size={args.aa}
renderengine.seed=42
path.pathdepth.total={depth}
path.pathdepth.diffuse={depth}
path.lighttracing.auto=0
path.lighttracing.enable=0
path.hybridbackforward.enable=0
path.vertexconnection.enable=0
path.mnee.auto=0
path.mnee.enable=0
path.guiding.enable=0
path.photongi.caustic.enabled=0
path.photongi.indirect.enabled=0
path.spectral.enable={int(args.spectral)}
''')
        if args.epsilon_min is not None:
            cfg.Set(s.Property('scene.epsilon.min', args.epsilon_min))
        config = s.RenderConfig(cfg, scene)
        pixel_atomics = (config.GetProperty('pathocl.pixelatomics.enable').GetBool()
                         if engine.endswith('OCL') else None)
        session = s.RenderSession(config)
        try:
            session.Start()
            deadline = time.monotonic() + 90
            while not session.HasDone():
                assert time.monotonic() < deadline, (label, engine)
                time.sleep(.01)
            session.Stop()
            film = session.GetFilm()
            rgb = np.zeros((64, 96, 3), np.float32)
            counts = np.zeros((64, 96), np.uint32)
            film.GetOutputFloat(s.FilmOutputType.RGB, rgb, 0, False)
            film.GetOutputUInt(s.FilmOutputType.SAMPLECOUNT, counts, 0, False)
            direct = np.zeros_like(rgb)
            indirect = np.zeros_like(rgb)
            film.GetOutputFloat(s.FilmOutputType.DIRECT_DIFFUSE, direct, 0, False)
            film.GetOutputFloat(s.FilmOutputType.INDIRECT_DIFFUSE, indirect, 0, False)
            assert np.all(counts == args.aa ** 2) and np.isfinite(rgb).all()
            expected = .65 * transmission ** layers
            mean = float(np.mean(rgb, dtype=np.float64))
            error = abs(mean - expected) / expected
            row = dict(case=label, engine=engine, layers=layers,
                       shadow_transmission=transmission, depth=depth,
                       expected=expected, mean=mean, relative_error=error,
                       strict_sample_gate=True, aa=args.aa, pixel_atomics=pixel_atomics,
                       extent=args.extent,
                       finite_target=args.finite_target,
                       target_extent=args.target_extent if args.finite_target else None,
                       endpoint_gap=args.endpoint_gap,
                       finite_direct_light_sampling=args.finite_dls if args.finite_target else None,
                       target_triangles=2 * args.target_grid ** 2 if args.finite_target else None,
                       expected_finite_dls_enabled=target_dls_enabled if args.finite_target else None,
                       spectral=args.spectral, epsilon_min_override=args.epsilon_min,
                       analytic_gate_passed=error < .025)
            row.update(direct_mean=float(direct.mean(dtype=np.float64)),
                       indirect_mean=float(indirect.mean(dtype=np.float64)))
            records.append(row)
            np.savez_compressed(args.out / (label + '-' + engine + '.npz'),
                                rgb=rgb, counts=counts, direct=direct, indirect=indirect)
            (args.out / 'progress.json').write_text(json.dumps(records, indent=2) + '\n')
            print(json.dumps(row), flush=True)
            loss_expected = args.expect_gpu_loss and engine.endswith('OCL') and layers and depth > 1
            if not args.diagnostic:
                assert (mean < .5 * expected) if loss_expected else (error < .025), row
        finally:
            if session.IsStarted():
                session.Stop()
report = dict(passed=all(r['analytic_gate_passed'] for r in records),
              artifact_capture_complete=True, diagnostic_only=args.diagnostic,
              expect_gpu_loss=args.expect_gpu_loss, cases=records,
              native_sha256=hashlib.file_digest(m.native_path().open('rb'), 'sha256').hexdigest(),
              scope=__doc__, performance_eligible=False)
(args.out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
