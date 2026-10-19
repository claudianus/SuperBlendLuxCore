"""Actual-hit GLT auxiliary-guide regression; physical Schlick/GGX kept intact.

Host surface features are a reference only. RR/NGX inputs below come from the
renderer-owned GPU frame. Directional Fresnel and an NDF-peak scalar roughness
are auxiliary estimates, not the integrated BSDF, transport or a quality proof.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


HERE = Path(os.environ.get('SLC_DLSS_TEST_ADDON', Path(__file__).resolve().parents[1]))/'dev-tools'
m = load('glt_fixture', HERE/'dlss_render_frame_test.py')
s = m.slc
CASES = [
    ('schlick-front', False, '', False),
    ('schlick-back', True, '', False),
    ('ggx-front', False, 'scene.materials.white.distribution = ggx', False),
    ('ggx-back', True, 'scene.materials.white.distribution = ggx', False),
    ('colored-ior', False, 'scene.materials.white.index = 1.5\nscene.materials.white.index_bf = 1.7', False),
    ('transmission-only', False, 'scene.materials.white.kd = 0 0 0', False),
    ('textured-roughness', False, '''
scene.textures.r.type = checkerboard2d
scene.textures.r.texture1 = 0.2
scene.textures.r.texture2 = 0.8
scene.textures.r.mapping.uvscale = 4 4
scene.materials.white.uroughness = r
''', False),
    ('absorbing-rejected', False, 'scene.materials.white.d = 0.1\nscene.materials.white.ka = 0.2 0.3 0.4', True),
    ('absorbing-back-rejected', True, 'scene.materials.white.d_bf = 0.1\nscene.materials.white.ka_bf = 0.2 0.3 0.4', True),
    ('multibounce-rejected', False, 'scene.materials.white.multibounce = 1', True),
]
BASE = '''
scene.materials.white.type = glossytranslucent
scene.materials.white.kd = 0.2 0.4 0.1
scene.materials.white.kt = 0.7 0.5 0.9
scene.materials.white.ks = 0.05 0.08 0.12
scene.materials.white.ks_bf = 0.14 0.07 0.03
scene.materials.white.uroughness = 0.3
scene.materials.white.vroughness = 0.3
scene.materials.white.uroughness_bf = 0.6
scene.materials.white.vroughness_bf = 0.4
scene.materials.white.index = 0
scene.materials.white.index_bf = 0
scene.materials.white.d = 0
scene.materials.white.d_bf = 0
scene.materials.white.multibounce = 0
scene.materials.white.multibounce_bf = 0
'''


def fixture(back, extra='', glass=False):
    scene, origin, target = m.fixture(plane=True)
    scene.DeleteObject('wall')
    vertices = [(-100, 3, -100), (100, 3, -100), (100, 3, 100), (-100, 3, 100)]
    triangles = [(0, 2, 1), (0, 3, 2)] if back else [(0, 1, 2), (0, 2, 3)]
    scene.DefineMesh('leaf', vertices, triangles, uvs=[(0, 0), (1, 0), (1, 1), (0, 1)])
    scene.Parse(m.props(BASE+'\n'+extra+'\nscene.objects.wall.shape = leaf\nscene.objects.wall.material = white'))
    if glass:
        scene.DefineMesh('window', [(-100, 1, -100), (100, 1, -100), (100, 1, 100), (-100, 1, 100)], [(0, 1, 2), (0, 2, 3)])
        scene.Parse(m.props('''
scene.materials.window.type = glass
scene.materials.window.kr = 1 1 1
scene.materials.window.kt = 1 1 1
scene.materials.window.exteriorior = 1
scene.materials.window.interiorior = 1
scene.objects.window.shape = window
scene.objects.window.material = window
'''))
    return scene, origin, target


def reference_expected(guides, name, back):
    position = guides['position_depth'][..., :3]
    eye = np.array([0., -5., 1.])-position
    mu = np.abs(eye[..., 1])/np.linalg.norm(eye, axis=-1)
    a = np.array([.05, .08, .12]); b = np.array([.14, .07, .03])
    if name == 'colored-ior':
        a *= ((1.5-1)/(1.5+1))**2
        b *= ((1.7-1)/(1.7+1))**2
    F = a+(1-a)*(1-mu[..., None])**5
    B = b+(1-b)*(1-mu[..., None])**5
    side = B if back else F
    kd = np.array([0., 0., 0.]) if name == 'transmission-only' else np.array([.2, .4, .1])
    diffuse = kd*(1-side)+np.array([.7, .5, .9])*(1-kd)*np.sqrt((1-F)*(1-B))
    np.testing.assert_allclose(guides['diffuse'][..., :3], diffuse, atol=3e-6, rtol=3e-6)
    np.testing.assert_allclose(guides['specular'][..., :3], side, atol=3e-6, rtol=3e-6)
    if name != 'textured-roughness':
        uv = .6*.4 if back else .3*.3
        rough = uv**(.5 if name.startswith('ggx') else .25)
        wd, ws = diffuse.mean(axis=-1), side.mean(axis=-1)
        expected = (wd+ws*rough)/(wd+ws)
        np.testing.assert_allclose(guides['normal_roughness'][..., 3], expected, atol=3e-6, rtol=3e-6)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--engine', choices=['TILEPATHCPU', 'TILEPATHOCL'], default='TILEPATHOCL')
    p.add_argument('--baseline-only', action='store_true')
    p.add_argument('--dlss', action='store_true')
    args = p.parse_args();args.out.mkdir(parents=True, exist_ok=True);s.Init()
    report = {'native_sha256': hashlib.file_digest(m.native_path().open('rb'), 'sha256').hexdigest(),
              'engine': args.engine, 'device': os.environ.get('SLC_DLSS_RENDER_DEVICE'), 'cases': [],
              'scope': __doc__}
    for name, back, extra, rejected in CASES:
        scene, _, _ = fixture(back, extra)
        raw = m.render(scene, args.engine, (64, 48), jitter=(.25, -.125))
        np.savez_compressed(args.out/(name+'-raw.npz'), **raw)
        if args.baseline_only:
            continue
        actual = m.render(scene, args.engine, (64, 48), jitter=(.25, -.125),
                          surface_guides=True, gpu_guides=args.engine.endswith('OCL'))
        for key, value in raw.items():
            np.testing.assert_array_equal(actual[key], value, err_msg=name+': raw '+key)
        host = actual['surface_guides']
        expected_status = 2 if rejected else 1
        assert np.all(host['status'] == expected_status), (name, np.unique(host['status']))
        if not rejected:
            reference_expected(host, name, back)
        row = {'case': name, 'raw_channels_bit_exact': list(raw), 'host_status': expected_status}
        if 'gpu_guides' in actual:
            gpu = actual['gpu_guides']
            assert np.all(gpu['status'] == expected_status), (name, np.unique(gpu['status']))
            np.testing.assert_array_equal(gpu['position_depth'][..., :3], actual['position'])
            for key in ['diffuse', 'specular', 'normal_roughness', 'position_depth']:
                np.testing.assert_allclose(gpu[key], host[key], atol=4e-6, rtol=4e-6, err_msg=name+': '+key)
            row.update(gpu_status=expected_status, gpu_position_bit_exact=True, gpu_host_reference_4e6=True)
            np.savez_compressed(args.out/(name+'-guides.npz'), **{k:v for k,v in gpu.items() if isinstance(v, np.ndarray)})
        report['cases'].append(row)
        (args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
        print('GLT actual-hit reference passed', name, flush=True)
    if args.engine.endswith('OCL') and not args.baseline_only:
        view = load('glt_view', HERE/'dlss_image_pipeline_test.py')
        d = load('glt_backend', Path(os.environ['SLC_DLSS_TEST_ADDON'])/'engine/dlss.py')
        report['rr_frames'] = []
        for back, glass in [(False, False), (True, False), (False, True)]:
            view.m.fixture = lambda: fixture(back, glass=glass)
            packet, raw = view.render_frame('rtpath.denoisingframes.haltspp=1\nrtpath.denoisingframes.lossless=1\nrtpath.denoisingframes.input.reduction=2\n', capture=True, size=(384, 216))
            assert np.all(packet['guides'][..., 7] == 1), np.unique(packet['guides'][..., 7], return_counts=True)
            np.testing.assert_array_equal(packet['color'], raw[1::2, 1::2])
            np.testing.assert_array_equal(packet['target_alpha'], raw[..., 3])
            row = {'back': back, 'through_glass': glass, 'guide_status': 1, 'source_size': list(packet['color'].shape), 'raw_exact_subgrid': True}
            if args.dlss:
                with d.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'], os.environ['SUPERLUXCORE_DLSS_CACHE'], library=os.environ['SLC_DLSS_TEST_LIBRARY']) as backend:
                    output = d.RendererDLSS(backend).process(packet)
                    assert np.isfinite(output).all()
                    np.testing.assert_array_equal(output[..., 3], raw[..., 3])
                    row['stats'] = backend.stats()
            report['rr_frames'].append(row)
            (args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
            print('GLT actual GPU RR passed', back, glass, flush=True)
    (args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
