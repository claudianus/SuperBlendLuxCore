"""Actual renderer leases: full-resolution HDR presentation and optional CUDA RR SR.

The supervisor supplies an isolated site-packages/PYTHONPATH, device selection,
time/RAM/disk bounds and cleanup. These are contract tests, not convergence or
equal-error performance evidence.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

spec = importlib.util.spec_from_file_location('upscale_fixture', Path(__file__).with_name('dlss_image_pipeline_test.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
s = m.s


def digest(value):
    return hashlib.sha256(value.tobytes()).hexdigest()


def nearest(values, size):
    width, height = size
    xs = ((2 * np.arange(width) + 1) * values.shape[1] // (2 * width)).astype(int)
    ys = ((2 * np.arange(height) + 1) * values.shape[0] // (2 * height)).astype(int)
    return values[ys[:, None], xs[None, :]]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--case', choices=['pipeline', 'sr720', 'sr4k'], default='pipeline')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    s.Init()
    assert s.DenoisingImagePipeline.supports_upscaling()
    config = '''scene.epsilon.min = 0.00001
scene.epsilon.max = 0.1
path.shadowterminator = chiang
opencl.task.count = 8192
pathocl.wavefront = off
'''
    report = {'case': args.case, 'native_sha256': hashlib.file_digest(m.m.native_path().open('rb'), 'sha256').hexdigest(),
              'scope': 'Actual native frame/pipeline and CUDA SR contracts only; no general image-quality or speed claim.', 'checks': []}

    if args.case == 'pipeline':
        for name, chain in [
            ('nop', 'film.imagepipelines.0.0.type = NOP'),
            ('linear', 'film.imagepipelines.0.0.type = TONEMAP_LINEAR\nfilm.imagepipelines.0.0.scale = 0.25'),
            ('alpha', 'film.imagepipelines.0.0.type = PREMULTIPLY_ALPHA'),
            ('depth', 'film.outputs.1.type = DEPTH\nfilm.outputs.1.filename = unused.exr\nfilm.imagepipelines.0.0.type = OUTPUT_SWITCHER\nfilm.imagepipelines.0.0.channel = DEPTH'),
            ('mist', 'film.outputs.1.type = DEPTH\nfilm.outputs.1.filename = unused.exr\nfilm.imagepipelines.0.0.type = MIST\nfilm.imagepipelines.0.0.amount = 0.5\nfilm.imagepipelines.0.0.startdistance = 0\nfilm.imagepipelines.0.0.enddistance = 20'),
        ]:
            packet, _ = m.render_frame(config + chain, capture=True)
            raw_hash = digest(packet['color'])
            reference = s.DenoisingImagePipeline().process(packet)
            for size in [(193, 129), (1280, 720)]:
                rgba = np.ascontiguousarray(nearest(packet['color'], size))
                processor = s.DenoisingImagePipeline()
                output = processor.process(packet, rgba)
                expected = nearest(reference, size)
                np.testing.assert_allclose(output, expected, atol=5e-6, rtol=5e-6)
                assert digest(packet['color']) == raw_hash
                if name == 'nop':
                    # Preserve high-frequency reconstruction detail that was
                    # never present at source resolution.
                    detail = rgba.copy();detail[:, ::2, 0] = .123;detail[:, 1::2, 0] = .789
                    actual = s.DenoisingImagePipeline().process(packet, detail)
                    np.testing.assert_array_equal(actual, detail)
                if name == 'alpha':
                    detail = rgba.copy();detail[:, :, 3] = np.linspace(0, 1, size[0], dtype=np.float32)
                    actual = s.DenoisingImagePipeline().process(packet, detail)
                    np.testing.assert_allclose(actual[:, :, :3], detail[:, :, :3]*detail[:, :, 3:4], atol=1e-7)
                    np.testing.assert_array_equal(actual[:, :, 3], detail[:, :, 3])
                    np.testing.assert_array_equal(s.DenoisingImagePipeline().process(packet), reference)
                try:
                    processor.process(packet, rgba)
                except RuntimeError as error:
                    assert 'increasing order' in str(error)
                else:
                    raise AssertionError('Duplicate SR presentation frame accepted')
                report['checks'].append({'pipeline': name, 'output_size': size,
                    'max_abs': float(np.abs(output - expected).max()), 'raw_unchanged': True})
        # Reject before allocating a huge presentation context/output.
        oversized = np.empty((4096, 4096, 4), np.float32)
        try:
            s.DenoisingImagePipeline().process(packet, oversized)
        except RuntimeError as error:
            assert '1 GiB budget' in str(error)
        else:
            raise AssertionError('Invalid oversized storage accepted')
        del oversized
    else:
        size = (1280, 720) if args.case == 'sr720' else (3840, 2160)
        source_size = (size[0] // 2, size[1] // 2)
        packet, _ = m.render_frame(config, capture=True, size=source_size)
        assert packet['image_pipeline_available'], packet['image_pipeline_error']
        before = {name: digest(packet[name]) for name in ['color', 'guides', 'sample_count']}
        addon = Path(os.environ['SLC_DLSS_TEST_ADDON'])
        spec = importlib.util.spec_from_file_location('actual_sr_backend', addon / 'engine/dlss.py')
        backend_module = importlib.util.module_from_spec(spec);sys.modules[spec.name] = backend_module;spec.loader.exec_module(backend_module)
        with backend_module.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'], os.environ['SUPERLUXCORE_DLSS_CACHE'],
                                    library=os.environ['SLC_DLSS_TEST_LIBRARY'], memory_limit=1024**3) as backend:
            consumer = backend_module.RendererDLSS(backend)
            reconstructed = consumer.process(packet, output_size=size)
            output = s.DenoisingImagePipeline().process(packet, reconstructed)
            # Preserve failed SDK/presentation evidence before any quality
            # assertion. A tiny alpha clamp difference must not hide an
            # unrelated coverage or RGB error in the same evaluation.
            diagnostic = {
                'source_size': source_size, 'output_size': size,
                'actual_ngx_evaluations': 1, 'stats': backend.stats(),
                'raw_unchanged': all(digest(packet[name]) == value for name, value in before.items()),
                'source_alpha_range': [float(packet['color'][:, :, 3].min()), float(packet['color'][:, :, 3].max())],
                'reconstructed_alpha_range': [float(reconstructed[:, :, 3].min()), float(reconstructed[:, :, 3].max())],
                'presentation_alpha_range': [float(output[:, :, 3].min()), float(output[:, :, 3].max())],
                'presentation_difference_max_by_channel': np.abs(output - reconstructed).max(axis=(0, 1)).tolist(),
                'presentation_difference_count_by_channel': np.count_nonzero(output != reconstructed, axis=(0, 1)).tolist(),
                'presentation_rgb_bit_exact': bool(np.array_equal(output[:, :, :3], reconstructed[:, :, :3])),
                'alpha_max_abs_from_one': float(np.abs(output[:, :, 3] - 1).max()),
                'quality_gate_passed': False,
            }
            np.save(args.out / 'sr-reconstructed.npy', reconstructed)
            np.save(args.out / 'sr-presentation.npy', output)
            np.save(args.out / 'physical-source.npy', packet['color'])
            (args.out / 'diagnostic.json').write_text(json.dumps(diagnostic, indent=2) + '\n')
            np.testing.assert_array_equal(output, reconstructed)
            assert np.isfinite(output).all() and output.shape == (size[1], size[0], 4)
            assert np.max(np.abs(output[:, :, 3]-1)) < 1e-6, 'Opaque SR coverage changed'
            assert all(digest(packet[name]) == value for name, value in before.items())
            diagnostic['quality_gate_passed'] = True
            (args.out / 'diagnostic.json').write_text(json.dumps(diagnostic, indent=2) + '\n')
            report['checks'].append(diagnostic)
    (args.out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
