"""Independent-frame LightMix and native external-HDR presentation contracts."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import time

import numpy as np

spec = importlib.util.spec_from_file_location(
    'presentation_fixture', Path(__file__).with_name('dlss_render_frame_test.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
s = m.slc


def render_frame(extra='', capture=False, size=(96, 64), inspect_running=None):
    scene, _, _ = m.fixture()
    cfg = m.props('''
renderengine.type = RTPATHOCL
sampler.type = TILEPATHSAMPLER
opencl.native.threads.count = 0
film.width = 96
film.height = 64
film.filter.type = NONE
film.hw.enable = 0
film.imagepipelines.0.0.type = NOP
rtpath.denoisingframes.enable = 1
rtpath.denoisingframes.tilesize = 64
batch.haltspp = 1
path.pathdepth.total = 8
path.lighttracing.auto = 0
path.hybridbackforward.enable = 0
path.vertexconnection.enable = 0
path.mnee.auto = 0
path.mnee.enable = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
path.spectral.enable = 0
film.outputs.0.type = RGBA
film.outputs.0.filename = unused.exr
''' + extra)
    if capture:
        cfg.Set(s.Property('rtpath.denoisingframes.imagepipeline.enable', True))
    cfg.Set(s.Property('film.width', size[0]))
    cfg.Set(s.Property('film.height', size[1]))
    descriptions = s.GetOpenCLDeviceDescs()
    device = os.environ.get('SLC_DLSS_RENDER_DEVICE', 'METAL_GPU')
    mask = ''.join('1' if descriptions.Get(name+'.type').GetString() == device else '0'
                   for name in descriptions.GetAllUniqueSubNames('opencl.device'))
    assert mask.count('1') == 1
    cfg.Set(s.Property('opencl.devices.select', mask))
    config = s.RenderConfig(cfg, scene)
    session = s.RenderSession(config)
    try:
        session.Start()
        if inspect_running is not None:
            return inspect_running(session)
        end = time.monotonic()+30
        while not session.HasDone():
            if time.monotonic() > end:
                raise TimeoutError('One-frame presentation fixture did not halt')
            time.sleep(.005)
        packet = session.GetDenoisingFrame(0, 0)
        assert packet is not None, 'No completed frame after natural halt'
        print('halted frame', packet['frame_id'], flush=True)
        raw = np.empty((size[1], size[0], 4), np.float32)
        session.GetFilm().GetOutputFloat(s.FilmOutputType.RGBA, raw.reshape(-1), 0, False)
        return packet, raw
    finally:
        if session.IsStarted():
            session.Stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--lightmix-only', action='store_true')
    parser.add_argument('--large', action='store_true')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    s.Init()
    packet, raw = render_frame('''
film.imagepipelines.0.radiancescales.0.enabled = 0
''')
    error = float(np.abs(packet['color']-raw).max())
    report = {'native_sha256': hashlib.sha256(m.native_path().read_bytes()).hexdigest(),
              'lightmix_all_groups_disabled_max_abs': error,
              'canonical_disabled_rgb_zero': bool(np.all(raw[:, :, :3] == 0)),
              'lightmix_bit_exact': bool(np.array_equal(packet['color'], raw))}
    (args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    assert np.array_equal(packet['color'], raw), ('Independent frame lost LightMix scale', error)
    assert np.all(raw[:, :, :3] == 0)
    if args.lightmix_only:
        raise SystemExit(0)

    report['presentation'] = []
    for name, chain in [
        ('linear_gamma', '''
film.imagepipelines.0.0.type = TONEMAP_LINEAR
film.imagepipelines.0.0.scale = 0.25
film.imagepipelines.0.1.type = GAMMA_CORRECTION
film.imagepipelines.0.1.value = 2.2
'''),
        ('reinhard', 'film.imagepipelines.0.0.type = TONEMAP_REINHARD02'),
        ('mist_depth', '''
film.outputs.1.type = DEPTH
film.outputs.1.filename = unused-depth.exr
film.imagepipelines.0.0.type = MIST
film.imagepipelines.0.0.color = 0.1 0.4 0.8
film.imagepipelines.0.0.amount = 0.5
film.imagepipelines.0.0.startdistance = 0
film.imagepipelines.0.0.enddistance = 20
'''),
        ('depth_switch', '''
film.outputs.1.type = DEPTH
film.outputs.1.filename = unused-depth.exr
film.imagepipelines.0.0.type = OUTPUT_SWITCHER
film.imagepipelines.0.0.channel = DEPTH
''')]:
        size = (1280, 720) if args.large and name == 'linear_gamma' else (96, 64)
        packet, _ = render_frame(chain+'''
film.imagepipelines.0.radiancescales.0.globalscale = 2
film.imagepipelines.0.radiancescales.0.rgbscale = 0.75 0.5 1
''', capture=True, size=size)
        assert packet['image_pipeline_available'], packet['image_pipeline_error']
        original = hashlib.sha256(packet['color'].tobytes()).hexdigest()
        reference = s.DenoisingImagePipeline().process(packet)
        processor = s.DenoisingImagePipeline()
        output = processor.process(packet, packet['color'])
        np.testing.assert_allclose(output, reference, atol=5e-6, rtol=5e-6)
        assert original == hashlib.sha256(packet['color'].tobytes()).hexdigest()
        try:
            processor.process(packet, packet['color'])
        except RuntimeError as e:
            assert 'increasing order' in str(e)
        else:
            raise AssertionError('Duplicate presentation frame accepted')
        for bad in [packet['color'].astype(np.float64), packet['color'][:, ::-1],
                    np.full_like(packet['color'], np.nan)]:
            try:
                s.DenoisingImagePipeline().process(packet, bad)
            except RuntimeError:
                pass
            else:
                raise AssertionError('Invalid presentation input accepted')
        report['presentation'].append({'case': name, 'size': size,
            'raw_merge_reference_max_abs': float(np.abs(output-reference).max()),
            'raw_inputs_unchanged': True, 'processed_after_session_stop': True,
            'channel_bytes': packet['image_pipeline_channel_bytes']})
        (args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')

    packet, _ = render_frame('film.imagepipelines.0.0.type = PREMULTIPLY_ALPHA', capture=True)
    rgba = packet['color'].copy()
    rgba[:, :, 3] = np.linspace(0, 1, rgba.shape[1], dtype=np.float32)
    output = s.DenoisingImagePipeline().process(packet, rgba)
    np.testing.assert_allclose(output[:, :, :3], rgba[:, :, :3]*rgba[:, :, 3:4], atol=1e-7)
    assert np.array_equal(output[:, :, 3], rgba[:, :, 3])
    reference_after = s.DenoisingImagePipeline().process(packet)
    np.testing.assert_array_equal(reference_after, packet['color'])
    report['external_alpha_applied_and_raw_alpha_restored'] = True

    packet, raw = render_frame('rtpath.denoisingframes.imagepipeline.maxbytes = 1', capture=True)
    assert not packet['image_pipeline_available'] and 'maxbytes' in packet['image_pipeline_error']
    assert np.isfinite(raw).all() and packet['complete']
    try:
        s.DenoisingImagePipeline().process(packet, packet['color'])
    except RuntimeError as e:
        assert 'maxbytes' in str(e)
    else:
        raise AssertionError('Over-budget presentation was processed')
    report['budget_rejection_preserves_canonical_rendering'] = True

    def hot_settings(session):
        def receive(after=0):
            end = time.monotonic()+15
            while time.monotonic() < end:
                frame = session.GetDenoisingFrame(after, 100)
                if frame is not None and frame['complete']:
                    return frame
            raise TimeoutError('No frame after image-pipeline edit')
        first = receive()
        original = s.DenoisingImagePipeline().process(first)
        session.Pause()
        session.Parse(m.props('''
film.imagepipelines.0.0.type = NOP
film.imagepipelines.0.radiancescales.0.enabled = 0
'''))
        immediate = session.GetDenoisingFrame(0, 0)
        if immediate is not None:
            assert immediate['image_pipeline_revision'] > first['image_pipeline_revision']
        np.testing.assert_array_equal(s.DenoisingImagePipeline().process(first), original)
        session.Resume()
        latest = receive(first['frame_id'])
        assert latest['scene_epoch'] > first['scene_epoch']
        assert latest['image_pipeline_revision'] > first['image_pipeline_revision']
        assert np.all(latest['color'][:, :, :3] == 0)
        assert np.all(s.DenoisingImagePipeline().process(latest)[:, :, :3] == 0)
        return {'old_publisher_invalidated': True, 'previous_lease_preserved': True,
                'new_lightmix_input_zero': True, 'history_epoch_advanced': True}
    report['hot_settings'] = render_frame('batch.haltspp = 0', capture=True, inspect_running=hot_settings)
    (args.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
