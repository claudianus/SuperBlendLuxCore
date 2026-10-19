"""Real pybind ownership regression: accessors must neither leak nor dangle.

Run with the candidate wheel on PYTHONPATH using Blender's bundled Python.
--observe records a baseline without accepting its known ownership failures.
"""
import argparse
import gc
import hashlib
import json
from pathlib import Path
import weakref
import tempfile

import pysuperluxcore as slc

p = argparse.ArgumentParser()
p.add_argument('--out', type=Path, required=True)
p.add_argument('--observe', action='store_true')
a = p.parse_args()
slc.Init()
records = []

def props(text):
    result = slc.Properties()
    result.SetFromString(text)
    return result

def collect():
    for _ in range(3):
        gc.collect()

def make_config(internal):
    if internal == 'serialized':
        with tempfile.TemporaryDirectory(prefix='slc-ownership-') as tmp:
            source = Path(tmp)/'scene.bcf'
            config = make_config(False)
            config.Save(str(source))
            return slc.RenderConfig(str(source))
    settings = props('renderengine.type = PATHCPU\nnative.threads.count = 1\n'
                     'film.width = 16\nfilm.height = 16\nfilm.opencl.enable = 0')
    camera = 'scene.camera.lookat.orig = 0 -5 1\nscene.camera.lookat.target = 0 0 1\nscene.camera.up = 0 0 1'
    if internal:
        with tempfile.TemporaryDirectory(prefix='slc-ownership-') as tmp:
            source = Path(tmp)/'scene.scn'
            source.write_text(camera+'\n')
            settings.Set(slc.Property('scene.file', str(source)))
            return slc.RenderConfig(settings)
    scene = slc.Scene()
    scene.Parse(props(camera))
    return slc.RenderConfig(settings, scene)

for internal in (False, True, 'serialized'):
    for accessor in ('none', 'config', 'scene', 'film', 'config-scene'):
        config = make_config(internal)
        session = slc.RenderSession(config)
        config_ref, session_ref = weakref.ref(config), weakref.ref(session)
        child = None
        same = None
        if accessor == 'config':
            child = session.GetRenderConfig()
            same = child is config
        elif accessor == 'scene':
            child = config.GetScene()
        elif accessor == 'film':
            child = session.GetFilm()
        elif accessor == 'config-scene':
            child = session.GetRenderConfig().GetScene()
        del config, session
        collect()
        # Check actual child validity after parent variables disappear.
        if accessor == 'config':
            assert child.GetFilmSize()[:2] == (16, 16)
            child.GetProperties()
        elif accessor in ('scene', 'config-scene'):
            child.ToProperties()
        elif accessor == 'film':
            assert child.GetWidth() == 16
        parent_alive_with_child = session_ref() is not None
        config_alive_with_child = config_ref() is not None
        expect_config_alive = (accessor in ('config', 'film') or
                               (bool(internal) and accessor in ('scene', 'config-scene')))
        child = None
        collect()
        released = config_ref() is None and session_ref() is None
        row = dict(internal_scene=internal, accessor=accessor,
                   returned_original_config=same,
                   session_alive_with_child=parent_alive_with_child,
                   config_alive_with_child=config_alive_with_child,
                   config_released=config_ref() is None,
                   session_released=session_ref() is None,
                   passed=(released and config_alive_with_child == expect_config_alive
                           and (parent_alive_with_child if accessor == 'film'
                                else not parent_alive_with_child)))
        records.append(row)

native = Path(slc.pysuperluxcore.__file__)
report = dict(passed=all(x['passed'] for x in records), records=records,
              test_sha256=hashlib.file_digest(Path(__file__).open('rb'), 'sha256').hexdigest(),
              native_sha256=hashlib.file_digest(native.open('rb'), 'sha256').hexdigest(),
              observe_only=a.observe)
a.out.parent.mkdir(parents=True, exist_ok=True)
a.out.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(report), flush=True)
if not a.observe:
    assert report['passed'], 'Accessor lifetime or retirement regression'
