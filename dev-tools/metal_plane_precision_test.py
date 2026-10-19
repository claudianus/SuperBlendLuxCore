"""Size-controlled diffuse furnace: separate primary shading from connection loss.

The same camera sees a kd=.65 floor under unit constant environment. Every
primary ray should hit z=0 with normal+Z and the radiance should remain.65.
Depth1 is NEE-only; depth4 also permits BSDF continuation. Extent and optional
epsilon are diagnostics, never changes to renderer/product defaults.
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

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('plane_fixture', root / 'dev-tools/dlss_render_frame_test.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
s = m.slc
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--out', type=Path, required=True)
p.add_argument('--extents', nargs='+', type=float, default=[100., 10000.])
p.add_argument('--depths', nargs='+', type=int, default=[1, 4])
p.add_argument('--aa', type=int, default=8)
p.add_argument('--epsilon-min', type=float)
p.add_argument('--tilt', type=float, default=0., help='Floor rotation about X in degrees')
p.add_argument('--instance', action='store_true', help='Apply rotation as an instance transform')
p.add_argument('--gap', type=float, help='Camera-invisible black roof above floor; guards thin contact occlusion')
p.add_argument('--engines', nargs='+', choices=['TILEPATHCPU', 'TILEPATHOCL'], default=['TILEPATHCPU', 'TILEPATHOCL'])
p.add_argument('--diagnostic', action='store_true')
a = p.parse_args()
if a.gap is not None and (a.gap <= 0 or a.tilt != 0 or a.instance):
    p.error('gap probe requires positive gap and unrotated non-instance geometry')
a.out.mkdir(parents=True, exist_ok=False)
s.Init()
desc = s.GetOpenCLDeviceDescs()
mask = ''.join('1' if desc.Get(n+'.type').GetString() == 'METAL_GPU' else '0'
               for n in desc.GetAllUniqueSubNames('opencl.device'))
assert '1' in mask
rows = []
angle = math.radians(a.tilt)
co, si = math.cos(angle), math.sin(angle)
plane_normal = np.array([0., -si, co], np.float64)
channels = {'RGB': 3, 'SAMPLECOUNT': 1, 'ALBEDO': 3,
            'GEOMETRY_NORMAL': 3, 'SHADING_NORMAL': 3,
            'POSITION': 3, 'DEPTH': 1, 'MATERIAL_ID': 1,
            'DIRECT_DIFFUSE': 3, 'INDIRECT_DIFFUSE': 3}
for extent in a.extents:
    for depth in a.depths:
        for engine in a.engines:
            label = f'e{extent:g}-d{depth}-{engine}'
            scene = s.Scene()
            scene.Parse(m.props('''
scene.camera.lookat.orig=0 -5 1.5
scene.camera.lookat.target=0 0 0
scene.camera.up=0 0 1
scene.camera.fieldofview=20
scene.materials.floor.type=matte
scene.materials.floor.kd=.65 .65 .65
scene.materials.floor.id=17
scene.lights.env.type=constantinfinite
scene.lights.env.color=1 1 1
'''))
            points = [(-extent, -extent, 0.), (extent, -extent, 0.),
                      (extent, extent, 0.), (-extent, extent, 0.)]
            if not a.instance:
                points = [(x, y*co-z*si, y*si+z*co) for x,y,z in points]
            scene.DefineMesh('floor', points, [(0, 1, 2), (0, 2, 3)])
            obj = 'scene.objects.floor.shape=floor\nscene.objects.floor.material=floor'
            if a.instance:
                obj += f'\nscene.objects.floor.transformation=1 0 0 0 0 {co} {si} 0 0 {-si} {co} 0 0 0 0 1'
            scene.Parse(m.props(obj))
            if a.gap is not None:
                scene.Parse(m.props('scene.materials.roof.type=matte\nscene.materials.roof.kd=0 0 0'))
                scene.DefineMesh('roof', [(-extent,-extent,a.gap), (extent,-extent,a.gap),
                                         (extent,extent,a.gap), (-extent,extent,a.gap)],
                                 [(0,2,1),(0,3,2)])
                scene.Parse(m.props('scene.objects.roof.shape=roof\nscene.objects.roof.material=roof\n'
                                    'scene.objects.roof.camerainvisible=1'))
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
tile.size=32
tile.multipass.enable=0
tilepath.sampling.aa.size={a.aa}
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
path.spectral.enable=0
''')
            if a.epsilon_min is not None:
                cfg.Set(s.Property('scene.epsilon.min', a.epsilon_min))
            for idx, name in enumerate(channels):
                cfg.Set(s.Property(f'film.outputs.{idx}.type', name))
                cfg.Set(s.Property(f'film.outputs.{idx}.filename', 'unused.png' if name == 'MATERIAL_ID' else 'unused.exr'))
            (a.out / (label+'-config.txt')).write_text(str(cfg))
            config = s.RenderConfig(cfg, scene)
            session = s.RenderSession(config)
            try:
                session.Start()
                deadline = time.monotonic()+90
                while not session.HasDone():
                    assert time.monotonic() < deadline, label
                    time.sleep(.01)
                session.Stop()
                film = session.GetFilm()
                arrays = {}
                for name, size in channels.items():
                    integer = name in ('SAMPLECOUNT', 'MATERIAL_ID')
                    data = np.zeros((64, 96, size), np.uint32 if integer else np.float32)
                    getter = film.GetOutputUInt if integer else film.GetOutputFloat
                    getter(s.FilmOutputType.names[name], data, 0, False)
                    if name not in ('POSITION', 'DEPTH', 'GEOMETRY_NORMAL', 'SHADING_NORMAL'):
                        assert np.isfinite(data).all(), (label, name)
                    arrays[name] = data
                assert np.all(arrays['SAMPLECOUNT'] == a.aa**2), label
                mean = float(arrays['RGB'].mean(dtype=np.float64))
                expected = .65 if a.gap is None else 0.
                error = abs(mean-expected)/expected if expected else abs(mean)
                tolerance = .025 if expected else .0001
                hit = arrays['MATERIAL_ID'][:, :, 0] == 17
                floor_gate = bool(np.all(arrays['MATERIAL_ID'] == 17))
                attribute_names = ('POSITION','DEPTH','GEOMETRY_NORMAL','SHADING_NORMAL')
                attributes_finite = all(np.isfinite(arrays[key][hit]).all() for key in attribute_names)
                def percentiles(data):
                    return np.percentile(data, [0,1,50,99,100]).tolist() if data.size else None
                def normal_stat(key, op):
                    values = arrays[key][hit]
                    return getattr(values,op)(axis=0).tolist() if values.size else None
                row = dict(case=label, engine=engine, extent=extent, depth=depth,
                           epsilon_min_override=a.epsilon_min, expected=expected,
                           tilt=a.tilt, instance=a.instance,
                           gap=a.gap, error_metric='relative' if expected else 'absolute',
                           hwrt_environment_override=os.environ.get('LUXRAYS_METAL_HWRT'),
                           error_tolerance=tolerance,
                           mean=mean, relative_error=error,
                           analytic_gate_passed=error < tolerance and floor_gate and attributes_finite,
                           primary_floor_material_gate=floor_gate,
                           primary_attributes_finite=attributes_finite,
                           nonfinite_attribute_components={key:int(np.count_nonzero(~np.isfinite(arrays[key]))) for key in attribute_names},
                           strict_sample_gate=True, primary_hit_pixels=int(hit.sum()),
                           primary_position_z_percentiles=percentiles(arrays['POSITION'][:, :, 2][hit]),
                           primary_plane_residual_percentiles=percentiles((arrays['POSITION'].astype(np.float64)@plane_normal)[hit]),
                           albedo_mean=arrays['ALBEDO'].mean((0,1), dtype=np.float64).tolist(),
                           geometry_normal_min=normal_stat('GEOMETRY_NORMAL','min'),
                           geometry_normal_max=normal_stat('GEOMETRY_NORMAL','max'),
                           shading_normal_mean=normal_stat('SHADING_NORMAL','mean'),
                           direct_mean=float(arrays['DIRECT_DIFFUSE'].mean(dtype=np.float64)),
                           indirect_mean=float(arrays['INDIRECT_DIFFUSE'].mean(dtype=np.float64)))
                rows.append(row)
                np.savez_compressed(a.out/(label+'.npz'), **arrays)
                (a.out/'progress.json').write_text(json.dumps(rows, indent=2)+'\n')
                print(json.dumps(row), flush=True)
                if not a.diagnostic:
                    assert row['analytic_gate_passed'], row
            finally:
                if session.IsStarted():
                    session.Stop()
report = dict(passed=all(row['analytic_gate_passed'] for row in rows),
              artifact_capture_complete=True, diagnostic_only=a.diagnostic,
              native_sha256=hashlib.file_digest(m.native_path().open('rb'), 'sha256').hexdigest(),
              cases=rows, scope=__doc__, performance_eligible=False)
(a.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
