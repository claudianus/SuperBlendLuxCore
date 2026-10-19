"""Actual renderer alpha diagnostics for explicitly requested RR model hints.

Constant coverage is a strict1e-6 contract. Finite glass/edge images and scalar
error measurements do not prove reconstruction quality or final/SR support.
No model is promoted and no canonical radiance/coverage is modified.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def sha(array):
    return hashlib.sha256(array.tobytes()).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--case', required=True,
                        choices=['opaque', 'cutout', 'null', 'holdout', 'background', 'glass', 'edge'])
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    here = Path(__file__).parent
    coverage = module('coverage_reference', here / 'dlss_coverage_reference_test.py')
    presentation = module('coverage_presentation', here / 'dlss_image_pipeline_test.py')
    backend = module('coverage_backend', Path(os.environ['SLC_DLSS_TEST_ADDON']) / 'engine/dlss.py')
    original_fixture = coverage.fixture
    material = 'opaque' if args.case == 'background' else 'cutout' if args.case == 'edge' else args.case
    background = args.case == 'background'

    def fixture(*_):
        scene = original_fixture(material, background)
        if args.case == 'edge':
            scene.Parse(coverage.props('scene.objects.wall.shape=wall\n'
                                       'scene.objects.wall.material=cutout\n'
                                       'scene.objects.wall.transformation = '
                                       '0.02 0 0 0  0 1 0 0  0 0 0.02 0  0 0 0 1'))
        return scene

    coverage.fixture = fixture
    presentation.m.fixture = lambda: (fixture(), None, None)
    coverage.s.Init()
    source_size, output_size = (192, 108), (384, 216)
    config = ('scene.epsilon.min=0.00001\nscene.epsilon.max=0.1\n'
              'path.shadowterminator=chiang\nopencl.task.count=8192\npathocl.wavefront=off\n')
    packet, raw = presentation.render_frame(config, capture=True, size=source_size)
    reference = coverage.render('TILEPATHOCL', material, background, size=output_size)
    before = {name: sha(packet[name]) for name in ('color', 'guides', 'sample_count')}
    np.savez_compressed(args.out / 'source-reference.npz', source=packet['color'],
                        source_guides=packet['guides'], reference=reference['RGBA'],
                        source_sample_count=packet['sample_count'], reference_sample_count=reference['SAMPLECOUNT'],
                        jitter=np.asarray(packet['jitter']), world_to_camera=packet['world_to_camera'],
                        camera_to_raster=packet['camera_to_raster'])
    expected = {'opaque': 1., 'cutout': .5, 'null': 0., 'holdout': 0., 'background': 0.}.get(args.case)
    report = {'case': args.case, 'native_sha256': hashlib.file_digest(presentation.m.native_path().open('rb'), 'sha256').hexdigest(),
              'source_size': source_size, 'output_size': output_size, 'source_samples': 1, 'reference_samples': 4,
              'scope': __doc__, 'requested_hint_does_not_prove_selected_model': True,
              'source_sha256': before, 'checks': []}
    failures = []
    for preset in ('D', 'E'):
        row = {'requested_preset': preset, 'quality_verified': False}
        try:
            with backend.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'], os.environ['SUPERLUXCORE_DLSS_CACHE'],
                                  library=os.environ['SLC_DLSS_TEST_LIBRARY'], preset=preset) as runtime:
                image = backend.RendererDLSS(runtime).process(packet, output_size=output_size)
                presented = presentation.s.DenoisingImagePipeline().process(packet, image)
                np.save(args.out / (preset + '-rgba.npy'), image)
                np.testing.assert_array_equal(image, presented)
                assert all(sha(packet[name]) == value for name, value in before.items())
                alpha, target = image[:, :, 3], reference['RGBA'][:, :, 3]
                assert np.isfinite(image).all() and np.all((alpha >= 0) & (alpha <= 1))
                row.update(raw_unchanged=True, presentation_bit_exact=True, stats=runtime.stats(),
                           source_alpha_range=[float(packet['color'][:, :, 3].min()), float(packet['color'][:, :, 3].max())],
                           alpha_range=[float(alpha.min()), float(alpha.max())],
                           source_alpha_mean=float(packet['color'][:, :, 3].mean()), alpha_mean=float(alpha.mean()),
                           reference_alpha_mean=float(target.mean()), reference_alpha_rmse=float(np.sqrt(np.mean((alpha-target)**2))))
                if expected is not None:
                    row['constant_alpha_max_error'] = float(np.max(np.abs(alpha-expected)))
                    row['constant_alpha_contract_passed'] = row['constant_alpha_max_error'] < 1e-6
                    assert row['constant_alpha_contract_passed'], 'Constant transport alpha changed'
                else:
                    row['qualification'] = 'Single source frame versus4spp reference; stochastic glass and edge quality remain unqualified'
                row['execution_passed'] = True
        except (RuntimeError, ValueError, AssertionError) as error:
            row.update(execution_passed=False, error=str(error))
            failures.append(preset)
        report['checks'].append(row)
        (args.out / 'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report), flush=True)
    assert not failures, failures
