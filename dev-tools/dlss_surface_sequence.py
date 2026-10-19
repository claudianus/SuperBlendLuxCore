"""Static procedural textured OpenPBR/metal captures using native surface guides.

Only this generated geometry/colors are read. No external assets or .blend.
This deliberately excludes motion, background, transmission and sharp lobes;
the strict guide gate rejects any pixel still needing path continuation.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = load('surface_fixture', ROOT/'dev-tools/dlss_render_frame_test.py')
dlss = load('surface_dlss', ROOT/'engine/dlss.py')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--engine', choices=('TILEPATHCPU', 'TILEPATHOCL'), default='TILEPATHCPU')
    parser.add_argument('--frames', type=int, default=16)
    parser.add_argument('--reference', action='store_true')
    args = parser.parse_args()
    assert 1 <= args.frames <= 32
    args.out.mkdir(parents=True, exist_ok=True)
    fixture.slc.Init()
    scene, _, _ = fixture.fixture()
    scene.Parse(fixture.props('''
scene.textures.copper_tiles.type = checkerboard3d
scene.textures.copper_tiles.mapping.type = globalmapping3d
scene.textures.copper_tiles.texture1 = 0.8 0.36 0.14
scene.textures.copper_tiles.texture2 = 0.08 0.22 0.45
scene.textures.rough_tiles.type = checkerboard3d
scene.textures.rough_tiles.mapping.type = globalmapping3d
scene.textures.rough_tiles.texture1 = 0.5
scene.textures.rough_tiles.texture2 = 0.8
scene.materials.copper.type = openpbr
scene.materials.copper.basecolor = copper_tiles
scene.materials.copper.basemetalness = 1
scene.materials.copper.specularroughness = rough_tiles
scene.materials.copper.specularanisotropy = 0.25
scene.materials.copper.cyclesnormalsemantics = 1
scene.materials.coated.type = openpbr
scene.materials.coated.basecolor = 0.06 0.28 0.65
scene.materials.coated.specularroughness = 0.5
scene.materials.coated.coatweight = 0.6
scene.materials.coated.coatroughness = 0.45
scene.materials.coated.cyclesnormalsemantics = 1
scene.objects.ball_a.shape = ball_a
scene.objects.ball_a.material = copper
scene.objects.ball_b.shape = ball_b
scene.objects.ball_b.material = coated
'''))
    report = {'native_sha256': hashlib.sha256(Path(fixture.slc.pysuperluxcore.__file__).read_bytes()).hexdigest(),
              'engine': args.engine, 'scope': 'procedural opaque textured OpenPBR metal and coated plastic; static pinhole camera and geometry',
              'guide_producer': 'native host scene intersection and per-hit closure estimates',
              'gpu_resident_guides': False, 'frames': []}
    hashes = set()
    for i in range(args.frames):
        jitter = (float((i*.7548776662466927+.5) % 1 - .5),
                  float((i*.5698402909980532+.5) % 1 - .5))
        render = fixture.render(scene, args.engine, (1280, 720), index=i, jitter=jitter, surface_guides=True)
        guides = render['surface_guides']
        motion = np.zeros((720, 1280, 2), np.float32)  # explicit static camera/geometry contract
        frame = dlss.DLSSFrame.from_surface_guides(render['color'], guides,
                    render_position=render['position'], motion=motion, specular_motion=motion.copy(), frame_id=i, scene_serial=1,
                    jitter=jitter, independent_samples=True)
        position_error = float(np.max(np.abs(guides['position_depth'][:, :, :3]-render['position'])))
        if args.engine == 'TILEPATHCPU':
            assert position_error < .002, position_error
        raw_hash = hashlib.sha256(frame.color.tobytes()).hexdigest()
        assert raw_hash not in hashes
        hashes.add(raw_hash)
        filename = f'frame-{i:03}.npz'
        np.savez_compressed(args.out/filename, **{n: getattr(frame, n) for n in (
            'color', 'depth', 'diffuse', 'specular', 'normal_roughness', 'motion', 'specular_motion')},
            jitter=np.array(jitter, np.float32))
        report['frames'].append({'id': i, 'file': filename, 'jitter': jitter, 'samples_per_pixel': 1,
                                  'raw_sha256': raw_hash, 'surface_status': [1],
                                  'host_to_render_position_max_abs': position_error})
        (args.out/'capture.json').write_text(json.dumps(report, indent=2)+'\n')
        print('captured material frame', i, 'position error', position_error, flush=True)
    if args.reference:
        reference = fixture.render(scene, args.engine, (1280, 720), index=97, aa=16, timeout=240)
        np.save(args.out/'reference-rgba.npy', reference['color'])
        report['reference_spp'] = 256
        (args.out/'capture.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
