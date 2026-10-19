"""Run with stock Blender and an isolated, sync_dev_install test profile.

SLC_BLENDER_MODE=render|formats|worker, DEV=CPU|OCL.
The output identity pins the exact installed candidate, never the release label alone.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import time
import types

import bpy
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PROFILE = Path(os.environ["BLENDER_USER_RESOURCES"])
SITE = PROFILE / "extensions/.local/lib/python3.13/site-packages"
sys.path.insert(0, str(SITE))
package = "bl_ext.user_default.superluxcore"
bpy.ops.preferences.addon_enable(module=package)
import pysuperluxcore as slc

OUT = Path(os.environ["SUPERLUXCORE_AUDIT_DIR"])
OUT.mkdir(parents=True, exist_ok=True)
MODE = os.environ.get("SLC_BLENDER_MODE", "render")
native = Path(slc.pysuperluxcore.__file__).resolve()
identity = json.loads(Path(os.environ["SLC_CANDIDATE_IDENTITY"]).read_text())
assert native.is_relative_to(PROFILE.resolve()), native
assert hashlib.file_digest(native.open("rb"), "sha256").hexdigest() == identity["installed_native_sha256"]
assert hashlib.file_digest((native.parent / "cl2msl.py").open("rb"), "sha256").hexdigest() == identity["translator_sha256"]
record = {"mode": MODE, "blender": bpy.app.version_string, "native_version": slc.Version(),
          "native_sha256": identity["installed_native_sha256"], "translator_sha256": identity["translator_sha256"]}

if MODE == "render":
    render_utils = importlib.import_module(package + ".utils.render")
    original = render_utils.update_stats
    devices = {}
    def measured(session):
        stats = original(session)
        for name in stats.GetAllNames():
            if name.startswith("stats.renderengine.devices"):
                devices[name] = stats.Get(name).GetString()
        return stats
    render_utils.update_stats = measured
    # Save both backends through the same view transform, alongside float EXR.
    try:
        bpy.context.scene.view_settings.view_transform = "ACES 2.0"
    except (TypeError, ValueError):
        pass
    record["view_transform"] = bpy.context.scene.view_settings.view_transform
    os.environ["SUPERLUXCORE_EXPECT_VERSION"] = "2.11.34"
    runpy.run_path(str(ROOT / "dev-tools/public-bundle-render-test.py"), run_name="__main__")
    record["devices"] = devices
    if os.environ.get("DEV") == "OCL":
        assert any("Metal" in value for value in devices.values()), devices
    assert (OUT / "render.exr").is_file() and (OUT / "render.png").is_file()
elif MODE == "formats":
    ext = importlib.import_module(package + ".utils.external_render")
    errors = importlib.import_module(package + ".utils.errorlog").SuperLuxCoreErrorLog
    errors.clear()
    s = bpy.context.scene
    s.view_settings.view_transform = "Standard"
    s.view_settings.look = "None"
    image = bpy.data.images.new("float review source", width=2, height=2, alpha=True, float_buffer=True)
    image.pixels.foreach_set(np.array([4., .5, .125, .25, 2., .25, .0625, .5,
                                      .5, .125, .03125, .75, .25, .0625, .015625, 1.], dtype=np.float32))
    image.update()
    s.render.image_settings.file_format = "OPEN_EXR"
    s.render.image_settings.color_mode = "RGBA"
    s.render.image_settings.color_depth = "32"
    source = OUT / "linear-source.exr"
    image.save_render(str(source), scene=s)
    records = []
    for fmt, depth, mode, suffix, magic in (
        ("PNG", "8", "RGBA", ".png", b"\x89PNG\r\n\x1a\n"),
        ("PNG", "16", "RGBA", ".png", b"\x89PNG\r\n\x1a\n"),
        ("JPEG", "8", "RGB", ".jpg", b"\xff\xd8\xff"),
        ("OPEN_EXR", "16", "RGBA", ".exr", b"\x76\x2f\x31\x01"),
        ("OPEN_EXR", "32", "RGBA", ".exr", b"\x76\x2f\x31\x01"),
    ):
        s.render.image_settings.file_format = fmt
        s.render.image_settings.color_depth = depth
        s.render.image_settings.color_mode = mode
        settings = ext._snapshot_settings(s)
        target = OUT / (fmt.lower() + depth + suffix)
        golden = OUT / ("internal-" + target.name)
        image.save_render(str(golden), scene=s)
        with tempfile.TemporaryDirectory(prefix="slc-output-blender-") as tmp:
            work = Path(tmp) / "job"; work.mkdir()
            __import__("shutil").copyfile(source, work / "beauty.exr")
            (work / "scene.bcf").write_text("scratch fixture")
            (work / "render.log").write_text("done")
            job = ext._Job(types.SimpleNamespace(poll=lambda: 0, returncode=0), str(work),
                str(work / "render.log"), str(target), 1, settings)
            ext._finish(job)
            assert not work.exists(), work
        assert target.read_bytes().startswith(magic), target
        outputs = [bpy.data.images.load(str(f), check_existing=False) for f in (target, golden)]
        try:
            values = [np.array(o.pixels[:], np.float32) for o in outputs]
            assert np.isfinite(values[0]).all()
            delta = float(np.max(np.abs(values[0] - values[1])))
            assert delta < 1e-6, (fmt, depth, delta)
            if fmt == "OPEN_EXR":
                assert float(values[0][0]) > 3.9 and abs(float(values[0][3]) - .25) < 1e-3
            records.append({"format": fmt, "depth": depth, "max_pixel_delta_vs_internal_save": delta,
                            "hdr_first_pixel": float(values[0][0]), "magic": magic.hex()})
        finally:
            for output in outputs: bpy.data.images.remove(output)
    bpy.data.images.remove(image)
    assert not list(errors.errors), [e.message for e in errors.errors]
    # Test the serialized child process too, not just the final image writer.
    scn = slc.Scene()
    p = slc.Properties(); p.SetFromString("""
scene.camera.lookat.orig = 0 -4 1
scene.camera.lookat.target = 0 0 0
scene.camera.up = 0 0 1
scene.materials.floor.type = matte
scene.materials.floor.kd = 0.5 0.5 0.5
scene.objects.floor.material = floor
scene.objects.floor.vertices = -10 -10 0 10 -10 0 10 10 0 -10 10 0
scene.objects.floor.faces = 0 1 2 0 2 3
scene.lights.env.type = constantinfinite
scene.lights.env.color = 2 2 2
"""); scn.Parse(p)
    cfg = slc.Properties(); cfg.SetFromString("""
renderengine.type = PATHCPU
native.threads.count = 2
film.width = 32
film.height = 32
sampler.type = RANDOM
batch.haltspp = 4
film.imagepipelines.0.0.type = NOP
film.outputs.0.type = RGB_IMAGEPIPELINE
film.outputs.0.index = 0
film.outputs.0.filename = RGB_IMAGEPIPELINE_0.png
film.imagepipelines.1.0.type = GAMMA_CORRECTION
film.imagepipelines.1.0.value = 2.2
film.outputs.1.type = RGB_IMAGEPIPELINE
film.outputs.1.index = 1
film.outputs.1.filename = RGB_IMAGEPIPELINE_1.png
film.outputs.2.type = RGB_IMAGEPIPELINE
film.outputs.2.index = 0
film.outputs.2.filename = native-reference.exr
""")
    s.render.image_settings.file_format = "OPEN_EXR"
    s.render.image_settings.color_depth = "32"
    s.render.filepath = str(OUT / "external-child.exr")
    ext.run(cfg, scn, s)
    job = ext._jobs[-1]
    try:
        deadline = time.monotonic() + 30
        while job.proc.poll() is None and time.monotonic() < deadline: time.sleep(.05)
        assert job.proc.poll() == 0, (job.proc.returncode, Path(job.log_path).read_text()[-2000:])
        reference = OUT / "external-child-reference.exr"
        __import__("shutil").copyfile(Path(job.workdir) / "native-reference.exr", reference)
        ext._poll()
        assert not Path(job.workdir).exists()
        assert Path(s.render.filepath).read_bytes().startswith(b"\x76\x2f\x31\x01")
        output = bpy.data.images.load(s.render.filepath, check_existing=False)
        golden = bpy.data.images.load(str(reference), check_existing=False)
        try:
            pixels = np.array(output.pixels[:], np.float32).reshape(32, 32, 4)
            reference_pixels = np.array(golden.pixels[:], np.float32).reshape(32, 32, 4)
            # A gamma noise-estimation pipeline at index 1 must not be selected.
            child_delta = float(np.max(np.abs(pixels - reference_pixels)))
            assert child_delta < 1e-6, child_delta
        finally:
            bpy.data.images.remove(output); bpy.data.images.remove(golden)
    finally:
        if job.proc.poll() is None: job.proc.kill(); job.proc.wait()
        if job in ext._jobs: ext._jobs.remove(job)
        if Path(job.workdir).exists(): __import__("shutil").rmtree(job.workdir)
    record.update({"formats": records, "serialized_child_passed": True, "scratch_removed": True,
                   "child_delta_vs_native_linear_output": child_delta})
elif MODE == "worker":
    s = bpy.context.scene
    s.render.resolution_x = s.render.resolution_y = 64
    s.superluxcore.config.device = "OCL" if os.environ.get("DEV") == "OCL" else "CPU"
    # This engine-less exporter fixture tests lifecycle, not AOV registration.
    s.superluxcore.denoiser.enabled = False
    if os.environ.get("DEV") == "OCL":
        bpy.context.preferences.addons[package].preferences.gpu_backend = "METAL"
    exporter = importlib.import_module(package + ".export")
    export_scene = exporter.Exporter.export_scene
    def bounded_export(self, *args, **kwargs):
        result = export_scene(self, *args, **kwargs)
        if result is not None:
            result[1].Set(slc.Property("opencl.task.count", 8192))
        return result
    exporter.Exporter.export_scene = bounded_export
    try:
        runpy.run_path(str(ROOT / "dev-tools/async_session_e2e_test.py"), run_name="__main__")
    except SystemExit as e:
        assert not e.code, e.code
    record.update({"passed": True, "requested_device": s.superluxcore.config.device})
else: raise ValueError(MODE)

(OUT / ("review-" + MODE + ".json")).write_text(json.dumps(record, indent=2) + "\n")
print("REVIEW_BLENDER_PASS", json.dumps(record), flush=True)
