"""Owned GUI Blender: real CPU/Metal film -> async OIDN -> GPU texture -> image.

Run with --factory-startup --python (no -b: GPU upload requires a context).
The supervising driver bounds and reaps the Blender process.
"""
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import types

import bpy
import gpu
from mathutils import Matrix
import numpy as np

PROFILE = Path(os.environ["BLENDER_USER_RESOURCES"])
sys.path.insert(0, str(PROFILE / "extensions/.local/lib/python3.13/site-packages"))
PACKAGE = "bl_ext.user_default.superluxcore"
bpy.context.preferences.filepaths.temporary_directory = os.environ["TMPDIR"]
bpy.ops.preferences.addon_enable(module=PACKAGE)
import pysuperluxcore as slc
viewport = importlib.import_module(PACKAGE + ".draw.viewport")
OUT = Path(os.environ["SUPERLUXCORE_AUDIT_DIR"]); OUT.mkdir(parents=True, exist_ok=True)
W, H = 1280, 720


def props(text):
    p = slc.Properties(); p.SetFromString(text); return p


def wait_thread(thread):
    thread.join(45)
    assert not thread.is_alive(), thread.name


def main():
    session = None; fb = None; off = None
    record = {"blender": bpy.app.version_string, "device": os.environ.get("DEV", "CPU")}
    try:
        native = Path(slc.pysuperluxcore.__file__).resolve()
        record["native_sha256"] = hashlib.file_digest(native.open("rb"), "sha256").hexdigest()
        record["adapter_sha256"] = hashlib.file_digest(Path(viewport.__file__).open("rb"), "sha256").hexdigest()
        identity = json.loads(Path(os.environ["SLC_CANDIDATE_IDENTITY"]).read_text())
        assert record["native_sha256"] == identity["installed_native_sha256"]
        assert record["adapter_sha256"] == identity["viewport_sha256"]
        scn = slc.Scene(); scn.Parse(props("""
scene.camera.lookat.orig = 0 -4 2
scene.camera.lookat.target = 0 0 0.6
scene.camera.up = 0 0 1
scene.materials.floor.type = matte
scene.materials.floor.kd = 0.4 0.4 0.4
scene.objects.floor.material = floor
scene.objects.floor.vertices = -10 -10 0 10 -10 0 10 10 0 -10 10 0
scene.objects.floor.faces = 0 1 2 0 2 3
scene.materials.panel.type = matte
scene.materials.panel.kd = 0.2 0.02 0.02
scene.materials.panel.emission = 0.6 0.025 0.01
scene.objects.panel.material = panel
scene.objects.panel.vertices = -1.5 0 0 1.5 0 0 1.5 0 1.8 -1.5 0 1.8
scene.objects.panel.faces = 0 1 2 0 2 3
scene.lights.env.type = constantinfinite
scene.lights.env.color = 0.05 0.07 0.1
"""))
        settings = f"""
renderengine.type = PATHCPU
native.threads.count = 2
film.width = {W}
film.height = {H}
film.imagepipelines.0.0.type = NOP
sampler.type = RANDOM
batch.haltspp = 16
path.lighttracing.auto = 0
path.hybridbackforward.enable = 0
path.mnee.enable = 0
path.mnee.auto = 0
path.guiding.enable = 0
path.photongi.indirect.enabled = 0
path.photongi.caustic.enabled = 0
"""
        if record["device"] == "OCL":
            desc = slc.GetOpenCLDeviceDescs()
            mask = "".join("1" if desc.Get(n + ".type").GetString() == "METAL_GPU" else "0"
                           for n in desc.GetAllUniqueSubNames("opencl.device"))
            assert "1" in mask
            settings += f"\nrenderengine.type = PATHOCL\nopencl.task.count = 8192\nopencl.native.threads.count = 0\nopencl.devices.select = {mask}\n"
        session = slc.RenderSession(slc.RenderConfig(props(settings), scn)); session.Start()
        def converge():
            end = time.monotonic() + 35
            while time.monotonic() < end:
                session.UpdateStats()
                if session.GetStats().Get("stats.renderengine.pass").GetInt() >= 16: break
                time.sleep(.02)
            else: raise AssertionError("film failed to reach 16 samples")
            session.Pause(); session.UpdateStats()
        converge()
        stats = session.GetStats()
        record["devices"] = {n: stats.Get(n).GetString() for n in stats.GetAllNames()
                             if n.startswith("stats.renderengine.devices")}
        if record["device"] == "OCL": assert any("Metal" in v for v in record["devices"].values())
        native_calls = []
        class Observed:
            def GetFilm(self): return session.GetFilm()
            def UpdateStats(self):
                native_calls.append(threading.current_thread().name); session.UpdateStats()
        worker = types.SimpleNamespace(session_lock=threading.Lock(), mutation_seq=1)
        engine = types.SimpleNamespace(session=Observed(), session_worker=worker)
        scene = bpy.context.scene
        scene.render.film_transparent = True
        scene.superluxcore.viewport.pixel_size = "1"
        context = types.SimpleNamespace(region=types.SimpleNamespace(width=W, height=H),
            region_data=types.SimpleNamespace(view_perspective="PERSP"),
            space_data=types.SimpleNamespace(shading=types.SimpleNamespace(type="MATERIAL"), use_render_border=False,
                render_border_min_x=0., render_border_max_x=1., render_border_min_y=0., render_border_max_y=1.))
        fb = viewport.FrameBuffer(engine, context, scene)
        assert not fb._transparent
        for _ in range(30): assert not fb.needs_replacement(context, scene, engine)
        record["material_preview_replacements_30_draws"] = 0
        off = gpu.types.GPUOffScreen(W, H, format="RGBA32F")
        def save(name):
            with off.bind():
                gpu.state.viewport_set(0, 0, W, H)
                gpu.state.blend_set("NONE")
                gpu.state.depth_test_set("NONE")
                gpu.state.active_framebuffer_get().clear(color=(0, 0, 0, 1))
                with gpu.matrix.push_pop():
                    gpu.matrix.load_matrix(Matrix.Identity(4))
                    gpu.matrix.load_projection_matrix(Matrix(((2/W,0,0,-1),(0,2/H,0,-1),(0,0,-1,0),(0,0,0,1))))
                    fb.draw()
                pixels = np.array(gpu.state.active_framebuffer_get().read_color(0, 0, W, H, 4, 0, "FLOAT")).reshape(H, W, 4)
            assert np.isfinite(pixels).all()
            expected = fb._last_pixels
            delta = float(np.max(np.abs(pixels[1:, 1:, :3] - expected[:-1, :-1])))
            assert delta < .002, (name, delta)
            image = bpy.data.images.new(name, width=W, height=H, alpha=True, float_buffer=True)
            try:
                image.pixels.foreach_set(pixels.ravel()); image.update()
                scene.view_settings.view_transform = "Standard"; scene.view_settings.look = "None"
                scene.render.image_settings.file_format = "OPEN_EXR"; scene.render.image_settings.color_depth = "32"
                image.save_render(str(OUT / (name + ".exr")), scene=scene)
                scene.render.image_settings.file_format = "PNG"; scene.render.image_settings.color_depth = "8"
                image.save_render(str(OUT / (name + ".png")), scene=scene)
            finally: bpy.data.images.remove(image)
            return {"gpu_upload_max_abs_delta": delta, "rgb_mean": pixels[:, :, :3].mean(axis=(0,1)).tolist()}
        fb.start_denoiser(engine); wait_thread(fb._denoiser_thread)
        old_box = fb._denoise_box
        worker.session_lock.acquire()
        try: assert fb.consume_denoise_result(engine)
        finally: worker.session_lock.release()
        record["before_edit"] = save("before-edit-denoised")
        with worker.session_lock:
            session.Resume(); session.BeginSceneEdit()
            scn.Parse(props("scene.materials.panel.kd = 0.01 0.05 0.3\nscene.materials.panel.emission = 0.01 0.08 0.65"))
            session.EndSceneEdit(); worker.mutation_seq += 1
        converge()
        fb._denoise_box = old_box
        assert not fb.consume_denoise_result(engine)
        record["stale_denoise_rejected"] = True
        fb.reset_denoiser()
        fb.start_async_update(engine.session, engine); wait_thread(fb._read_thread)
        assert fb.consume_async_update(engine.session, engine)
        record["after_edit_raw"] = save("after-edit-raw")
        fb.start_denoiser(engine); wait_thread(fb._denoiser_thread)
        assert fb.consume_denoise_result(engine)
        record["after_edit_denoised"] = save("after-edit-denoised")
        assert record["before_edit"]["rgb_mean"][0] > record["after_edit_denoised"]["rgb_mean"][0]
        assert record["before_edit"]["rgb_mean"][2] < record["after_edit_denoised"]["rgb_mean"][2]
        record["native_stats_threads"] = native_calls
        assert native_calls and all(n != "MainThread" for n in native_calls)
        record["status"] = "passed"
    except BaseException:
        record["status"] = "failed"; record["error"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        if fb:
            fb.reset_denoiser()
            for thread in (fb._denoiser_thread, fb._read_thread):
                if thread: wait_thread(thread)
        if session: session.Stop()
        if off: off.free()
        (OUT / "viewport-result.json").write_text(json.dumps(record, indent=2) + "\n")
        bpy.ops.wm.quit_blender()


bpy.app.timers.register(main, first_interval=.5)
