"""Renderer-owned, independent DLSS frame fixture (opaque matte surfaces only).

This is a bounded producer integration test, not the general viewport producer.
Each tiled render completes once with a new scramble, explicit pixel jitter and
no reused film. The matte BSDF has exactly zero specular albedo, unit perceptual
roughness and, in this static fixture, exactly zero backward/reflection motion.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, os.environ['SLC_DLSS_RENDER_MODULE'])
import pysuperluxcore as slc


def native_path():
    """Wheel package or direct native build import; neither installs a module."""
    return Path(getattr(slc, 'pysuperluxcore', slc).__file__)


def props(text):
    result = slc.Properties()
    result.SetFromString(text)
    return result


def fixture(plane=False):
    scene = slc.Scene()
    camera = '0 -5 2.2' if not plane else '0 -5 1'
    target = '0 0.5 1.5' if not plane else '0 0 1'
    scene.Parse(props(f'''
scene.camera.lookat.orig = {camera}
scene.camera.lookat.target = {target}
scene.camera.up = 0 0 1
scene.camera.fieldofview = 45
scene.materials.white.type = matte
scene.materials.white.kd = 0.65 0.65 0.65
scene.materials.red.type = matte
scene.materials.red.kd = 0.65 0.06 0.04
scene.materials.green.type = matte
scene.materials.green.kd = 0.06 0.45 0.1
scene.materials.blue.type = matte
scene.materials.blue.kd = 0.08 0.18 0.6
scene.materials.light.type = matte
scene.materials.light.kd = 0 0 0
scene.materials.light.emission = 9 8 6
scene.lights.env.type = constantinfinite
scene.lights.env.color = 0.02 0.02 0.02
'''))

    def quad(name, material, vertices):
        scene.DefineMesh(name, vertices, [(0, 1, 2), (0, 2, 3)])
        scene.Parse(props(f'scene.objects.{name}.shape = {name}\nscene.objects.{name}.material = {material}'))

    if plane:
        quad('wall', 'white', [(-100, 3, -100), (100, 3, -100), (100, 3, 100), (-100, 3, 100)])
        return scene, np.array([0., -5., 1.]), np.array([0., 0., 1.])
    quad('floor', 'white', [(-3, -7, 0), (3, -7, 0), (3, 3, 0), (-3, 3, 0)])
    quad('back', 'white', [(-3, 3, 0), (3, 3, 0), (3, 3, 4), (-3, 3, 4)])
    quad('left', 'red', [(-3, -7, 0), (-3, 3, 0), (-3, 3, 4), (-3, -7, 4)])
    quad('right', 'green', [(3, 3, 0), (3, -7, 0), (3, -7, 4), (3, 3, 4)])
    quad('ceiling', 'white', [(-3, 3, 4), (3, 3, 4), (3, -7, 4), (-3, -7, 4)])
    quad('key', 'light', [(-.85, .8, 3.98), (.85, .8, 3.98), (.85, -.6, 3.98), (-.85, -.6, 3.98)])
    for name, center, radius, material in [('ball_a', (-1.1, .4, .85), .85, 'white'),
                                           ('ball_b', (.9, 1., 1.1), 1.1, 'blue')]:
        points, normals, triangles = [], [], []
        for y in range(33):
            theta = math.pi*y/32
            for x in range(65):
                phi = 2*math.pi*x/64
                n = (math.sin(theta)*math.cos(phi), math.sin(theta)*math.sin(phi), math.cos(theta))
                normals.append(n)
                points.append(tuple(center[i]+radius*n[i] for i in range(3)))
        for y in range(32):
            for x in range(64):
                a = y*65+x
                triangles.extend([(a, a+65, a+1), (a+1, a+65, a+66)])
        scene.DefineMesh(name, points, triangles, normals)
        scene.Parse(props(f'scene.objects.{name}.shape = {name}\nscene.objects.{name}.material = {material}'))
    return scene, np.array([0., -5., 2.2]), np.array([0., .5, 1.5])


def render(scene, engine, size, *, index=0, jitter=None, aa=1, timeout=120, surface_guides=False, gpu_guides=False):
    w, h = size
    cfg = props(f'''
renderengine.type = {engine}
native.threads.count = 4
opencl.native.threads.count = 0
opencl.task.count = 8192
tile.size = 64
tilepathocl.devices.maxtiles = 2
sampler.type = TILEPATHSAMPLER
tilepath.sampling.aa.size = {aa}
tile.multipass.enable = 0
tile.multipass.startindex = {index}
film.width = {w}
film.height = {h}
film.filter.type = NONE
film.imagepipelines.0.0.type = NOP
path.pathdepth.total = 8
path.pathdepth.diffuse = 8
path.lighttracing.auto = 0
path.hybridbackforward.enable = 0
path.vertexconnection.enable = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.spectral.enable = 0
''')
    if engine.endswith('OCL'):
        desc = slc.GetOpenCLDeviceDescs()
        selected = os.environ.get('SLC_DLSS_RENDER_DEVICE', 'METAL_GPU')
        mask = ''.join('1' if desc.Get(n+'.type').GetString() == selected else '0'
                       for n in desc.GetAllUniqueSubNames('opencl.device'))
        assert '1' in mask, selected + ' unavailable'
        cfg.Set(slc.Property('opencl.devices.select', mask))
    if jitter is not None:
        cfg.Set(slc.Property('path.sampling.pixeljitter.enable', True))
        for axis, value in zip('xy', jitter):
            cfg.Set(slc.Property('path.sampling.pixeljitter.'+axis, float(value)))
    if gpu_guides:
        cfg.Set(slc.Property('film.denoisingguides.enable', True))
    channels = [('color', 'RGBA', 4), ('albedo', 'ALBEDO', 3),
                ('normal', 'SHADING_NORMAL', 3), ('depth', 'DEPTH', 1),
                ('position', 'POSITION', 3), ('count', 'SAMPLECOUNT', 1)]
    for i, (_, output, _) in enumerate(channels):
        cfg.Set(slc.Property(f'film.outputs.{i}.type', output))
        cfg.Set(slc.Property(f'film.outputs.{i}.filename', 'unused.exr'))
    config = slc.RenderConfig(cfg, scene)
    session = slc.RenderSession(config)
    try:
        session.Start()
        end = time.monotonic()+timeout
        while not session.HasDone():
            if time.monotonic() > end:
                raise TimeoutError(engine + ' frame incomplete')
            time.sleep(.01)
        session.UpdateStats()
        result = {}
        for name, output, channels_count in channels:
            dtype = np.uint32 if name == 'count' else np.float32
            data = np.empty((h, w, channels_count), dtype)
            method = session.GetFilm().GetOutputUInt if name == 'count' else session.GetFilm().GetOutputFloat
            method(getattr(slc.FilmOutputType, output), data, 0, False)
            result[name] = data
        assert np.all(result['count'] == aa*aa), np.unique(result['count'], return_counts=True)
        assert all(np.isfinite(x).all() for x in result.values()), 'Uncovered/background pixel in closed fixture'
        if surface_guides:
            result['surface_guides'] = session.GetDenoisingSurfaceGuides(*(jitter or (0., 0.)))
        if gpu_guides:
            result['gpu_guides'] = session.GetDenoisingGuides()
        return result
    finally:
        if session.IsStarted():
            session.Stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--engine', default='TILEPATHCPU')
    parser.add_argument('--frames', type=int, default=16)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--baseline-only', action='store_true')
    parser.add_argument('--contract-only', action='store_true')
    parser.add_argument('--reference', action='store_true')
    parser.add_argument('--orbit', type=float, default=0., help='Total static-geometry camera arc in degrees')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    slc.Init()
    sha = hashlib.file_digest(native_path().open('rb'), 'sha256').hexdigest()
    records = {'native_sha256': sha, 'engine': args.engine, 'scope': 'opaque matte static fixture', 'frames': []}
    scene, origin, target = fixture(plane=True)
    baseline = render(scene, args.engine, (96, 64), aa=2)
    np.savez_compressed(args.out/'default.npz', **baseline)
    room, _, _ = fixture()
    np.savez_compressed(args.out/'default-room.npz', **render(room, args.engine, (96, 64), aa=2))
    if args.baseline_only:
        return
    j = (.25, -.125)
    first = render(scene, args.engine, (96, 64), jitter=j)
    second = render(scene, args.engine, (96, 64), index=1, jitter=j)
    assert np.array_equal(first['position'], second['position']), 'Frame jitter changed with sample scramble'
    v = first['position'] - origin
    # SuperLuxCore specifies FOV on the longer image dimension.
    f = 96/(2*math.tan(math.radians(45)/2))
    xx, yy = np.meshgrid(np.arange(96)+.5+j[0], np.arange(64)+.5+j[1])
    projected_x, projected_y = 48+f*v[:, :, 0]/v[:, :, 1], 32+f*v[:, :, 2]/v[:, :, 1]
    error = max(float(np.max(np.abs(projected_x-xx))), float(np.max(np.abs(projected_y-yy))))
    assert error < 1e-3, ('traced jitter mismatch', error)
    records['jitter_projection_max_pixels'] = error
    scene, origin, target = fixture()
    a = render(scene, args.engine, (96, 64), index=0, jitter=j)
    b = render(scene, args.engine, (96, 64), index=1, jitter=j)
    assert not np.array_equal(a['color'], b['color']), 'Changing frame scramble did not change actual path samples'
    for name in ['albedo', 'normal', 'depth', 'position', 'count']:
        assert np.array_equal(a[name], b[name]), ('Scramble changed fixed-jitter geometric guide', name)
    records['fixed_jitter_independent_scrambles'] = True
    for kwargs in [{'jitter': (.6, 0.)}, {'jitter': (0., -.6)}, {'index': 2**32-1}]:
        try:
            render(scene, args.engine, (32, 32), **kwargs)
        except RuntimeError as e:
            assert 'jitter' in str(e) or 'startindex' in str(e), str(e)
        else:
            raise AssertionError('Invalid producer options accepted: '+str(kwargs))
    records['invalid_options_rejected'] = True
    if args.contract_only:
        (args.out/'capture.json').write_text(json.dumps(records, indent=2)+'\n')
        return
    def basis(eye):
        forward = target-eye
        forward /= np.linalg.norm(forward)
        right = np.cross(forward, [0., 0., 1.]); right /= np.linalg.norm(right)
        up = np.cross(right, forward)
        return np.array([right, up, forward], np.float64)

    def project(position, eye, camera_basis):
        view = (position-eye) @ camera_basis.T
        focal = max(args.width, args.height)/(2*math.tan(math.radians(45)/2))
        return np.stack((args.width/2+focal*view[:, :, 0]/view[:, :, 2],
                         args.height/2+focal*view[:, :, 1]/view[:, :, 2]), axis=2)

    previous_eye = previous_basis = None
    records['camera_orbit_degrees'] = args.orbit
    hashes = set()
    for i in range(args.frames):
        if args.orbit:
            angle = math.radians(args.orbit)*(i/max(args.frames-1, 1)-.5)
            origin = target+np.array([5.5*math.sin(angle), -5.5*math.cos(angle), .7])
            # Scene.Parse reconstructs a camera from the supplied properties;
            # partial camera props would reset omitted target/FOV/up defaults.
            scene.Parse(props('scene.camera.lookat.orig = '+' '.join(map(str, origin))+
                              '\nscene.camera.lookat.target = '+' '.join(map(str, target))+
                              '\nscene.camera.up = 0 0 1\nscene.camera.fieldofview = 45'))
        world_to_camera = basis(origin)
        forward = world_to_camera[2]
        # Known global jitter, with new per-pixel/path RNG scramble every frame.
        j = (float(((i*.7548776662466927+.5) % 1)-.5),
             float(((i*.5698402909980532+.5) % 1)-.5))
        planes = render(scene, args.engine, (args.width, args.height), index=i, jitter=j)
        px, py = np.meshgrid(np.arange(args.width)+.5+j[0], np.arange(args.height)+.5+j[1])
        expected = np.stack((px, py), axis=2)
        projection_error = float(np.abs(project(planes['position'], origin, world_to_camera)-expected).max())
        assert projection_error < 1e-3, ('Actual camera differs from guide camera', i, projection_error)
        color = planes['color']
        diffuse = np.ones_like(color); diffuse[:, :, :3] = planes['albedo']/(1+planes['albedo'])
        specular = np.zeros_like(color)
        normal = np.ones_like(color); normal[:, :, :3] = planes['normal'] @ world_to_camera.T
        depth = np.ascontiguousarray((planes['position']-origin) @ forward, dtype=np.float32)
        motion = np.zeros((args.height, args.width, 2), np.float32)
        if previous_eye is not None and args.orbit:
            # Static geometry: project the same world-space shading point
            # through both unjittered cameras. Current-to-previous sign;
            # changes to frame jitter are not mistaken for scene motion.
            motion[:] = project(planes['position'], previous_eye, previous_basis)-project(planes['position'], origin, world_to_camera)
        previous_eye, previous_basis = origin.copy(), world_to_camera.copy()
        path = args.out/f'frame-{i:03}.npz'
        np.savez_compressed(path, color=color, depth=depth, diffuse=diffuse,
                            specular=specular, normal_roughness=normal,
                            motion=motion, specular_motion=np.zeros_like(motion),
                            jitter=-np.array(j, np.float32), ray_jitter=np.array(j, np.float32))
        digest = hashlib.sha256(color.tobytes()).hexdigest()
        assert digest not in hashes, 'Repeated frame, not independent samples'
        hashes.add(digest)
        records['frames'].append({'id': i, 'jitter': tuple(-value for value in j),
                                 'ray_jitter': j, 'jitter_semantics': 'ngx-compensation', 'raw_sha256': digest,
                                   'samples_per_pixel': 1, 'file': path.name,
                                   'camera_origin': origin.tolist(),
                                   'camera_target': target.tolist(),
                                   'projection_max_error_pixels': projection_error,
                                   'max_motion_pixels': float(np.abs(motion).max())})
        (args.out/'capture.json').write_text(json.dumps(records, indent=2)+'\n')
        print('captured', i, 'mean', float(color[:, :, :3].mean()), flush=True)
    if args.reference:
        if args.orbit:
            matched = render(scene, args.engine, (args.width, args.height), index=71, aa=4)
            np.save(args.out/'last-camera-16spp-rgba.npy', matched['color'])
            records['last_camera_reference_spp'] = 16
        reference = render(scene, args.engine, (args.width, args.height), index=97, aa=12, timeout=240)
        np.save(args.out/'reference-rgba.npy', reference['color'])
        records['reference_spp'] = 144
        (args.out/'capture.json').write_text(json.dumps(records, indent=2)+'\n')


if __name__ == '__main__':
    main()
