"""Actual invalid-path metadata must remain rejected before neural inference."""
from contextlib import nullcontext
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
    m = importlib.util.module_from_spec(spec);sys.modules[name] = m;spec.loader.exec_module(m)
    return m


here = Path(os.environ['SLC_DLSS_TEST_ADDON'])/'dev-tools'
glt = load('trace_glt', here/'dlss_glossy_translucent_guides_test.py')
view = load('trace_view', here/'dlss_image_pipeline_test.py')
d = load('trace_dlss', here.parent/'engine/dlss.py')
p = argparse.ArgumentParser();p.add_argument('--out', type=Path, required=True)
p.add_argument('--baseline', action='store_true');p.add_argument('--dlss', action='store_true');a = p.parse_args();a.out.mkdir(parents=True, exist_ok=True)
view.s.Init();rows = []
class NoInference:
    calls = 0
    def process(self, *_):
        self.calls += 1
        raise AssertionError('Invalid path reached the neural backend')

for name, glass, invalid in [('accepted', False, False), ('primary-velvet', False, True), ('secondary-velvet', True, True)]:
    extra = 'scene.materials.white.type = velvet' if invalid else ''
    view.m.fixture = lambda: glt.fixture(False, extra, glass=glass)
    packet, raw = view.render_frame('rtpath.denoisingframes.haltspp=1\nrtpath.denoisingframes.lossless=1\nrtpath.denoisingframes.input.reduction=2\n', capture=True, size=(192, 108))
    guides = packet['guides']
    np.savez_compressed(a.out/(name+'.npz'), raw=raw, source=packet['color'], guides=guides)
    rejected = guides[..., 7] == 2
    if invalid:
        assert rejected.any() and np.isin(guides[..., 7], [1, 2]).all()
        if not glass:assert rejected.all()
    else:
        assert np.all(guides[..., 7] == 1)
    failure = guides[rejected]
    row = {'case': name, 'status_histogram': {str(v):int(n) for v,n in zip(*np.unique(guides[...,7],return_counts=True))}, 'rejected_pixels':int(rejected.sum())}
    if invalid:
        manager = d.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'], os.environ['SUPERLUXCORE_DLSS_CACHE'], library=os.environ['SLC_DLSS_TEST_LIBRARY']) if a.dlss else nullcontext(NoInference())
        with manager as backend:
            consumer = d.RendererDLSS(backend)
            try:
                consumer.process(packet)
            except d.DLSSInputError:
                pass
            else:
                raise AssertionError('Unsupported material packet accepted')
            assert (backend.stats()['frames'] if a.dlss else backend.calls) == 0
        row['neural_calls'] = 0
        if not a.baseline:
            # Glass paths may physically terminate before hitting velvet. Only the
            # actually rejected vertices carry failure metadata; no status is repaired.
            # MaterialType::VELVET is10 in the shared material_types.cl enum.
            assert np.all(failure[:, 24] == 10), np.unique(failure[:, 24])
            assert np.all(failure[:, 25] >= 0) and np.all(failure[:, 25] == np.floor(failure[:, 25]))
            assert np.all(failure[:, 26] == int(glass)), np.unique(failure[:, 26])
            assert np.all(failure[:, 27] == -1)
            row.update(material_type=10, vertex_depth=int(glass), rejection_tag=-1)
    if not invalid and a.dlss:
        with d.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'], os.environ['SUPERLUXCORE_DLSS_CACHE'], library=os.environ['SLC_DLSS_TEST_LIBRARY']) as backend:
            output = d.RendererDLSS(backend).process(packet)
            assert np.isfinite(output).all()
            np.testing.assert_array_equal(output[..., 3], raw[..., 3])
            assert backend.stats()['frames'] == 1
            row['neural_calls'] = 1
    rows.append(row)
    (a.out/'result.json').write_text(json.dumps({'native_sha256':hashlib.file_digest(view.m.native_path().open('rb'),'sha256').hexdigest(),'cases':rows,'baseline':a.baseline,'scope':__doc__},indent=2)+'\n')
    print('actual rejection metadata passed', name, flush=True)
