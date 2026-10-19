"""Stopped-session ownership guard for same-export comparison and references.

Retain the real session/config/scene instead of re-exporting Blender or relying
on a serialized image's original files. No renderer/default change is made.
"""
import argparse
import gc
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import numpy as np

here = Path(os.environ['SLC_DLSS_TEST_ADDON'])/'dev-tools'
spec = importlib.util.spec_from_file_location('reuse_glt', here/'dlss_glossy_translucent_guides_test.py')
glt = importlib.util.module_from_spec(spec);sys.modules[spec.name] = glt;spec.loader.exec_module(glt)
m = glt.m;s = m.slc
p = argparse.ArgumentParser();p.add_argument('--out', type=Path, required=True)
p.add_argument('--engine', choices=['TILEPATHCPU', 'TILEPATHOCL'], required=True);a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True);s.Init()
source = a.out/'temporary-image.ppm'
source.write_bytes(b'P6\n2 2\n255\n'+bytes([255,30,10,20,220,50,50,70,255,190,110,200]))
scene, _, _ = glt.fixture(False)
scene.Parse(m.props('scene.textures.pic.type=imagemap\nscene.textures.pic.gamma=1\nscene.textures.pic.file='+str(source.resolve())+'\nscene.textures.pic2.type=imagemap\nscene.textures.pic2.gamma=2.2\nscene.textures.pic2.file='+str(source.resolve())+'\nscene.materials.white.kd=pic\nscene.materials.white.kt=pic2'))
source.unlink()
original_session, original_config = s.RenderSession, s.RenderConfig
state = {};report = {}

def remember(config):
    session = original_session(config)
    state['session'] = session
    return session

try:
    s.RenderSession = remember
    before = m.render(scene, a.engine, (96, 64), index=2, jitter=(.25, -.125), aa=2)
    s.RenderSession = original_session
    scene = None;gc.collect()
    retained = state['session'];assert not retained.IsStarted()
    config = retained.GetRenderConfig()
    retained_scene = config.GetScene()
    properties = config.GetProperties()
    s.RenderConfig = lambda *_: original_config(properties, retained_scene)
    after = m.render(None, a.engine, (96, 64), index=2, jitter=(.25, -.125), aa=2)
    np.savez_compressed(a.out/'before.npz', **before)
    np.savez_compressed(a.out/'after.npz', **after)
    for key in before:
        np.testing.assert_array_equal(before[key], after[key], err_msg=key)
    report.update(passed=True, raw_channels_bit_exact=list(before), engine=a.engine,
                  source_image_removed_before_both_renders=True,
                  dropped_original_python_scene=True, stopped_session_kept_scene_valid=True,
                  native_sha256=hashlib.file_digest(m.native_path().open('rb'), 'sha256').hexdigest(), scope=__doc__)
finally:
    s.RenderConfig = original_config;s.RenderSession = original_session
    if state.get('session') is not None and state['session'].IsStarted():state['session'].Stop()
    state.clear();source.unlink(missing_ok=True)
    report['temporary_image_removed'] = not source.exists()
    (a.out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report), flush=True)
