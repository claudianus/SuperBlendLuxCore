"""Actual CPU/Metal material guide tests; no NVIDIA runtime or bpy required.

The native reference traces the scene's real hit points and textures. Primary
guides flagged for continuation are deliberately not accepted as full RR guides.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

import numpy as np

spec = importlib.util.spec_from_file_location('fixture', Path(__file__).with_name('dlss_render_frame_test.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
s = fixture.slc


def capture(material, engine, size=(64, 48), extra=''):
    scene, _, _ = fixture.fixture(plane=True)
    scene.DeleteObject('wall')
    scene.DefineMesh('wall_uv', [(-10, 3, -10), (10, 3, -10), (10, 3, 10), (-10, 3, 10)],
                     [(0, 1, 2), (0, 2, 3)], uvs=[(0, 0), (1, 0), (1, 1), (0, 1)])
    scene.Parse(fixture.props('scene.objects.wall.shape = wall_uv\nscene.objects.wall.material = white'))
    scene.Parse(fixture.props('scene.materials.white.type = ' + material + '\n' + extra))
    w, h = size
    cfg = fixture.props(f'''
renderengine.type = {engine}
native.threads.count = 4
opencl.native.threads.count = 0
opencl.task.count = 8192
tile.size = 64
tile.multipass.enable = 0
tilepath.sampling.aa.size = 1
sampler.type = TILEPATHSAMPLER
film.width = {w}
film.height = {h}
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
film.outputs.0.type = RGBA
film.outputs.0.filename = unused.exr
path.pathdepth.total = 4
path.lighttracing.auto = 0
path.hybridbackforward.enable = 0
path.vertexconnection.enable = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.sampling.pixeljitter.enable = 1
path.sampling.pixeljitter.x = 0.25
path.sampling.pixeljitter.y = -0.125
''')
    if engine.endswith('OCL'):
        desc = s.GetOpenCLDeviceDescs()
        device = os.environ.get('SLC_DLSS_RENDER_DEVICE', 'METAL_GPU')
        mask = ''.join('1' if desc.Get(n+'.type').GetString() == device else '0'
                       for n in desc.GetAllUniqueSubNames('opencl.device'))
        assert '1' in mask
        cfg.Set(s.Property('opencl.devices.select', mask))
    config = s.RenderConfig(cfg, scene)
    session = s.RenderSession(config)
    try:
        try:
            session.GetDenoisingSurfaceGuides()
        except RuntimeError:
            pass
        else:
            raise AssertionError('Unstarted session accepted')
        session.Start()
        deadline = time.monotonic() + 120
        while not session.HasDone():
            if time.monotonic() > deadline:
                raise TimeoutError(engine)
            time.sleep(.01)
        film = session.GetFilm()
        before = np.empty((h, w, 4), np.float32)
        film.GetOutputFloat(s.FilmOutputType.RGBA, before, 0, False)
        start = time.monotonic()
        guides = session.GetDenoisingSurfaceGuides(.25, -.125)
        elapsed = time.monotonic() - start
        repeat = session.GetDenoisingSurfaceGuides(.25, -.125)
        after = np.empty_like(before)
        film.GetOutputFloat(s.FilmOutputType.RGBA, after, 0, False)
        assert np.array_equal(before, after), 'Guide read changed raw beauty'
        for key in ('diffuse', 'specular', 'normal_roughness', 'position_depth', 'status'):
            assert np.array_equal(guides[key], repeat[key]), key
            assert np.isfinite(guides[key]).all(), key
        for jitter in ((float('nan'), 0), (.50001, 0)):
            try:
                session.GetDenoisingSurfaceGuides(*jitter)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Invalid jitter accepted')
        # The plane is y=3, with the camera at y=-5 looking along +Y.
        np.testing.assert_allclose(guides['position_depth'][:, :, 1], 3, atol=2e-6)
        np.testing.assert_allclose(guides['position_depth'][:, :, 3], 8, atol=3e-6)
        return guides, before, elapsed
    finally:
        if session.IsStarted():
            session.Stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--engine', default='TILEPATHCPU', choices=('TILEPATHCPU', 'TILEPATHOCL'))
    parser.add_argument('--large', action='store_true')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    s.Init()
    cases = [
        ('matte', 'matte', '', 1),
        ('matte-translucent', 'mattetranslucent', 'scene.materials.white.kr = 0.5 0.5 0.5\nscene.materials.white.kt = 0.5 0.5 0.5', 1),
        ('matte-translucent-colored', 'mattetranslucent', 'scene.materials.white.kr = 1.2 -0.1 0.25\nscene.materials.white.kt = 0.9 0.5 1.2', 1),
        ('openpbr-diffuse', 'openpbr', 'scene.materials.white.basecolor = 0.2 0.4 0.6\nscene.materials.white.specularweight = 0', 1),
        ('openpbr-metal', 'openpbr', 'scene.materials.white.basemetalness = 1\nscene.materials.white.specularroughness = 0.45', 1),
        ('openpbr-coat', 'openpbr', 'scene.materials.white.coatweight = 0.6\nscene.materials.white.coatroughness = 0.2', 1),
        ('openpbr-lobe-normals', 'openpbr', 'scene.materials.white.cyclesnormalsemantics = 1\nscene.materials.white.coatweight = 0.6', 1),
        ('metal-textured-roughness', 'metal2', '''
scene.textures.r.type = checkerboard2d
scene.textures.r.texture1 = 0.2
scene.textures.r.texture2 = 0.8
scene.textures.r.mapping.uvscale = 4 4
scene.materials.white.uroughness = r
scene.materials.white.vroughness = 0.4
scene.materials.white.distribution = ggx
''', 1),
        ('mirror-needs-continuation', 'mirror', '', 3),
        ('glass-needs-continuation', 'glass', '', 3),
        ('roughglass-needs-continuation', 'roughglass', 'scene.materials.white.distribution = ggx', 3),
        ('thinfilm-unsupported', 'openpbr', 'scene.materials.white.filmweight = 1', 2),
        ('velvet-unsupported', 'velvet', '', 2),
    ]
    records = []
    for name, material, extra, expected_status in cases:
        guides, color, elapsed = capture(material, args.engine, extra=extra)
        statuses = np.unique(guides['status']).tolist()
        assert statuses == [expected_status], (name, statuses)
        if name.startswith('matte-translucent'):
            expected = [.75, .75, .75] if name == 'matte-translucent' else [1., .5, 1.]
            np.testing.assert_allclose(guides['diffuse'][:, :, :3], np.broadcast_to(expected, (48, 64, 3)), atol=1e-6)
            assert not guides['specular'][:, :, :3].any()
            np.testing.assert_allclose(guides['normal_roughness'][:, :, 3], 1, atol=1e-7)
        if name == 'openpbr-diffuse':
            np.testing.assert_allclose(guides['diffuse'][:, :, :3], np.broadcast_to([.2, .4, .6], (48, 64, 3)), atol=1e-6)
            assert np.max(guides['specular'][:, :, :3]) < 1e-12
        if name in ('openpbr-metal', 'metal-textured-roughness'):
            assert not guides['diffuse'][:, :, :3].any()
            assert np.min(guides['specular'][:, :, :3]) > 0
        if name == 'metal-textured-roughness':
            r = guides['normal_roughness'][:, :, 3]
            assert np.min(np.abs(r[..., None] - np.sqrt([.2*.4, .8*.4])), axis=-1).max() < 2e-6
            assert np.ptp(r) > .2, 'Hit-point checker collapsed to a texture-wide mean'
        records.append({'case': name, 'status': statuses, 'guide_seconds': elapsed,
                        'raw_unchanged': True, 'repeat_bit_exact': True})
    if args.large:
        guides, color, elapsed = capture('openpbr', args.engine, (1280, 720),
            'scene.materials.white.basecolor = 0.2 0.4 0.6\nscene.materials.white.coatweight = 0.4')
        assert np.all(guides['status'] == 1)
        np.savez_compressed(args.out/'openpbr-720p.npz', color=color,
                            **{k: v for k, v in guides.items() if isinstance(v, np.ndarray)})
        records.append({'case': 'openpbr-720p', 'guide_seconds': elapsed, 'status': [1], 'raw_unchanged': True})
    module = fixture.native_path()
    report = {'native_sha256': hashlib.sha256(module.read_bytes()).hexdigest(),
              'engine': args.engine, 'cases': records,
              'scope': 'Host primary-surface estimates; not reflection continuation, GPU resident guides or live viewport.'}
    (args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
