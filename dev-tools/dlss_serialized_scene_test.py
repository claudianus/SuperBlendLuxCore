"""Same-scene binary RenderConfig replay guard for bounded comparison work.

Save must retain the original scene's ownership. Replaying a full config must
preserve the deterministic raw channels, not merely load without a crash.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

here = Path(os.environ.get('SLC_DLSS_TEST_ADDON', Path(__file__).resolve().parents[1]))/'dev-tools'
spec = importlib.util.spec_from_file_location('serialized_glt', here/'dlss_glossy_translucent_guides_test.py')
glt = importlib.util.module_from_spec(spec);sys.modules[spec.name] = glt;spec.loader.exec_module(glt)
m = glt.m;s = m.slc
p = argparse.ArgumentParser();p.add_argument('--out', type=Path, required=True)
p.add_argument('--image', action='store_true')
p.add_argument('--save-legacy', type=Path)
p.add_argument('--legacy', type=Path)
p.add_argument('--engine', choices=['TILEPATHCPU', 'TILEPATHOCL'], required=True)
a = p.parse_args();a.out.mkdir(parents=True, exist_ok=True);s.Init()
scene, _, _ = glt.fixture(False, 'scene.materials.white.index = 1.5\nscene.materials.white.index_bf = 1.7')
original_constructor = s.RenderConfig
snapshot = a.out/'temporary-config.bcf'
state = {}
source_image = a.out/'temporary-image.ppm'
if a.image:
    source_image.write_bytes(b'P6\n2 2\n255\n'+bytes([255,30,10,20,220,50,50,70,255,190,110,200]))
    scene.Parse(m.props('scene.textures.pic.type = imagemap\nscene.textures.pic.gamma = 1\nscene.textures.pic.file = '+str(source_image.resolve())+'\nscene.textures.pic2.type = imagemap\nscene.textures.pic2.gamma = 2.2\nscene.textures.pic2.file = '+str(source_image.resolve())+'\nscene.materials.white.kd = pic\nscene.materials.white.kt = pic2'))

def saved(cfg, source_scene):
    config = original_constructor(cfg, source_scene)
    before = str(config.GetProperties())
    config.Save(str(snapshot))
    if a.save_legacy:
        a.save_legacy.write_bytes(snapshot.read_bytes())
    if a.image:
        source_image.unlink()
        state['image_source_removed_before_both_renders'] = True
    assert before == str(config.GetProperties()), 'Save mutated config properties'
    state['snapshot_bytes'] = snapshot.stat().st_size
    state['snapshot_sha256'] = hashlib.file_digest(snapshot.open('rb'), 'sha256').hexdigest()
    return config

try:
    s.RenderConfig = saved
    before = m.render(scene, a.engine, (96, 64), index=2, jitter=(.25, -.125), aa=2)
    s.RenderConfig = original_constructor
    loaded = original_constructor(str(snapshot))
    assert loaded.GetScene() is not None
    s.RenderConfig = lambda *_: loaded
    after = m.render(scene, a.engine, (96, 64), index=2, jitter=(.25, -.125), aa=2)
    np.savez_compressed(a.out/'before.npz', **before)
    np.savez_compressed(a.out/'after.npz', **after)
    for key in before:
        np.testing.assert_array_equal(before[key], after[key], err_msg=key)
    if a.legacy:
        legacy = original_constructor(str(a.legacy))
        s.RenderConfig = lambda *_: legacy
        legacy_raw = m.render(scene, a.engine, (96, 64), index=2, jitter=(.25, -.125), aa=2)
        for key in before:
            np.testing.assert_array_equal(before[key], legacy_raw[key], err_msg='legacy '+key)
        state['legacy_v2_raw_channels_bit_exact'] = list(before)
    state.update(passed=True, raw_channels_bit_exact=list(before), engine=a.engine,
                 native_sha256=hashlib.file_digest(m.native_path().open('rb'), 'sha256').hexdigest(),
                 device=os.environ.get('SLC_DLSS_RENDER_DEVICE'), scope=__doc__)
finally:
    s.RenderConfig = original_constructor
    snapshot.unlink(missing_ok=True)
    source_image.unlink(missing_ok=True)
    state['temporary_snapshot_removed'] = not snapshot.exists()
    state['temporary_image_removed'] = not source_image.exists()
    (a.out/'result.json').write_text(json.dumps(state, indent=2)+'\n')
print(json.dumps(state), flush=True)
