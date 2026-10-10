# SPDX-License-Identifier: Apache-2.0
"""Read the glass-slab fixture's raw EXRs, excluding its white background.

Run in Blender after renders finish. This computes means, not visual review or
production acceptance. The authored sphere projects to radius320 at 1280x720;
the predefined interior circle has 75% of that radius.
"""
import hashlib
import json
import os
from pathlib import Path

import bpy
import numpy as np

reference = Path(os.environ['SUPERLUXCORE_BSSRDF_EYE_REFERENCE'])
folders = [Path(p) for p in os.environ['SUPERLUXCORE_BSSRDF_REVIEW_FOLDERS'].split(',')]
yy, xx = np.indices((720, 1280))
mask = (xx + .5 - 640.) ** 2 + (yy + .5 - 360.) ** 2 < 240. ** 2
reference_records = {r['case']: r for r in json.loads((reference / 'scene-metrics.json').read_text())}


def read(path):
    image = bpy.data.images.load(str(path), check_existing=False)
    try:
        assert list(image.size) == [1280, 720], path
        pixels = np.asarray(image.pixels[:], np.float32).reshape(720, 1280, 4)
        assert np.isfinite(pixels).all(), path
        return pixels[mask, :3].mean(axis=0, dtype=np.float64)
    finally:
        bpy.data.images.remove(image)


for folder in folders:
    results = []
    for source in json.loads((folder / 'scene-metrics.json').read_text()):
        case = source['case']
        assert source['graph_unchanged'] and source['graph_sha256'] == reference_records[case]['graph_sha256']
        paths = {'cycles': folder / (case + '_CYCLES.exr'),
                 'native': folder / (case + '_SUPERLUXCORE.exr'),
                 'independent_cpu_eye': reference / (case + '_SUPERLUXCORE.exr')}
        means = {name: read(path) for name, path in paths.items()}
        error = float(np.max(np.abs(means['native'] - means['independent_cpu_eye']) /
                             np.maximum(means['independent_cpu_eye'], 1e-4)))
        record = {'case': case, 'native_sha256': source['native_sha256'],
                  'graph_sha256': source['graph_sha256'], 'graph_unchanged': True,
                  'reference_native_sha256': reference_records[case]['native_sha256'],
                  'region': {'center': [640, 360], 'radius': 240, 'pixels': int(mask.sum())},
                  'means': {name: value.tolist() for name, value in means.items()},
                  'max_relative_channel_error_vs_cpu_eye': error,
                  'operator_mean_gate_passed': error < .03,
                  'production_acceptance': False, 'directly_reviewed': False,
                  'inputs': {name: {'path': str(path),
                                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                             for name, path in paths.items()}}
        results.append(record)
        print('BSSRDF_REGIONAL_REVIEW', record, flush=True)
    (folder / 'regional-metrics.json').write_text(json.dumps(results, indent=2) + '\n')
