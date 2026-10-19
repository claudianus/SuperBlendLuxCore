"""Deterministic regressions for material preview, stale frames and UI readback.

SLC_VIEWPORT_SOURCE can select a retained pre-fix source for reproduction.
Native CPU/Metal and GL upload are checked separately in stock Blender.
"""
import ast
import os
from pathlib import Path
import threading
import time
import types
import unittest
import weakref

import numpy as np

SOURCE = Path(os.environ.get("SLC_VIEWPORT_SOURCE", str(Path(__file__).resolve().parents[1] / "draw/viewport.py")))


def load():
    fake_gpu = types.SimpleNamespace(types=types.SimpleNamespace(Buffer=lambda kind, size, data: np.array(data)))
    env = {"np": np, "gpu": fake_gpu, "threading": threading, "time": time,
           "_session_lock": lambda e: e.session_worker.session_lock,
           "_mutation_seq": lambda e: e.session_worker.mutation_seq,
           "utils": types.SimpleNamespace(is_valid_camera=lambda cam: True,
               in_material_shading_mode=lambda ctx: ctx.material,
               calc_filmsize=lambda *a: (2,2),
               calc_blender_border=lambda *a: (0, 1, 0, 1)),
           "pysuperluxcore": types.SimpleNamespace(FilmOutputType=types.SimpleNamespace(
               RGB_IMAGEPIPELINE="RGB",RGBA_IMAGEPIPELINE="RGBA")),
           "blender_settings": types.SimpleNamespace(transparent_film=lambda s: True)}
    nodes = [n for n in ast.parse(SOURCE.read_text()).body if isinstance(n, (ast.FunctionDef, ast.ClassDef))
             and n.name in ("FrameBuffer", "run_denoiser", "_fetch_pixels")]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), "exec"), env)
    return env


class VisualRegressions(unittest.TestCase):
    def setUp(self):
        self.env = load(); self.cls = self.env["FrameBuffer"]
        self.fb = self.cls.__new__(self.cls)
        self.fb._width = self.fb._height = 2
        self.fb._transparent = False
        self.fb._border = (0, 1, 0, 1); self.fb._pixel_size = 1
        self.fb._pending_reset = False; self.fb._shown_mut_seq = 0
        self.fb._interactive_denoise = False; self.fb._output_type = "RGB"
        self.fb._last_update = 0; self.fb._denoiser_thread = None
        self.fb._read_thread = None
        self.fb._denoise_box = None; self.fb._denoise_session = None
        self.worker = types.SimpleNamespace(session_lock=threading.Lock(), mutation_seq=3)
        self.engine = types.SimpleNamespace(session=None, session_worker=self.worker)

    def test_region_and_border_cover_exact_pixel_bounds(self):
        context = types.SimpleNamespace(region=types.SimpleNamespace(width=1920, height=1080),
                                        region_data=types.SimpleNamespace(view_perspective="PERSP"))
        scene = types.SimpleNamespace(camera=object(), render=types.SimpleNamespace(use_border=True))
        self.assertEqual(self.fb._calc_view_rect(context, scene, (0, 1, 0, 1)),
                         (0, 0, 1920, 1080))
        self.assertEqual(self.fb._calc_view_rect(context, scene, (.25, .75, .1, .9)),
                         (480, 108, 960, 864))

    def test_camera_border_keeps_camera_pan_and_zoom(self):
        context = types.SimpleNamespace(region=types.SimpleNamespace(width=1920, height=1080),
                                        region_data=types.SimpleNamespace(view_perspective="CAMERA"))
        scene = types.SimpleNamespace(camera=object(), render=types.SimpleNamespace(use_border=True))
        self.env["utils"].calc_camera_frame_rect = lambda *args: (-40, 30, 2000, 1000)
        self.assertEqual(self.fb._calc_view_rect(context, scene, (.25, .75, .1, .9)),
                         (460, 130, 1000, 800))

    def test_material_preview_transparent_film_keeps_framebuffer(self):
        film = types.SimpleNamespace(GetWidth=lambda: 2, GetHeight=lambda: 2)
        self.engine.session = types.SimpleNamespace(GetFilm=lambda: film)
        scene = types.SimpleNamespace(camera=object(), superluxcore=types.SimpleNamespace(
            viewport=types.SimpleNamespace(pixel_size=1)))
        context = types.SimpleNamespace(material=True)
        self.fb._transparent = self.fb._initialize_transparency(scene, context)
        self.assertFalse(self.fb.needs_replacement(context, scene, self.engine))

    def test_older_read_cannot_replace_new_edit(self):
        self.fb._shown_mut_seq = 3
        self.fb._last_pixels = np.ones((2, 2, 3), np.float32)
        self.fb._read_session = self.engine.session = object()
        self.fb._read_thread = None
        self.fb._read_box = {"done": True, "data": np.zeros(12, np.float32), "width": 2, "height": 2, "mut_seq": 2}
        self.assertFalse(self.fb.consume_async_update(self.engine.session, self.engine))
        self.assertTrue(np.all(self.fb._last_pixels == 1))

    def test_completed_denoise_upload_never_waits_for_session(self):
        self.engine.session = self.fb._denoise_session = object()
        self.fb._denoise_box = {"done": True, "data": np.ones(12, np.float32),
            "width": 2, "height": 2, "mut_seq": 3}
        self.worker.session_lock.acquire()
        try:
            self.assertTrue(self.fb.consume_denoise_result(self.engine))
            self.assertTrue(self.fb.denoised)
            self.assertEqual(self.fb._shown_mut_seq, 3)
        finally:
            self.worker.session_lock.release()

    def test_read_completed_before_edit_does_not_satisfy_reset(self):
        self.fb._shown_mut_seq = 1
        self.fb._last_pixels = np.ones((2, 2, 3), np.float32)
        self.fb._read_session = self.engine.session = object()
        self.fb._read_thread = None
        self.fb._read_box = {"done": True, "data": np.zeros(12, np.float32),
            "width": 2, "height": 2, "mut_seq": 2}
        self.assertFalse(self.fb.consume_async_update(self.engine.session, self.engine))
        self.assertTrue(np.all(self.fb._last_pixels == 1))

    def test_denoise_from_old_edit_is_discarded(self):
        self.engine.session = self.fb._denoise_session = types.SimpleNamespace(UpdateStats=lambda: None)
        self.fb.update = lambda *a, **kw: self.fail("stale denoise must not re-read or upload the current film")
        self.fb._denoise_box = {"done": True, "data": np.ones(12, np.float32),
            "width": 2, "height": 2, "mut_seq": 2}
        self.assertFalse(self.fb.consume_denoise_result(self.engine))

    def test_native_read_and_stats_stay_on_background_thread(self):
        native_threads = []
        def call(): native_threads.append(threading.current_thread().name)
        def output(kind, data, index, execute): call(); data[:] = .5
        film = types.SimpleNamespace(ApplyOIDN=lambda i: call(), GetWidth=lambda: 2, GetHeight=lambda: 2,
            GetOutputFloat=output)
        self.engine.session = types.SimpleNamespace(GetFilm=lambda: film, UpdateStats=call)
        self.assertTrue(self.fb.start_denoiser(self.engine))
        self.fb._denoiser_thread.join(3)
        self.assertFalse(self.fb.is_denoiser_active())
        self.assertIn("data", self.fb._denoise_box)
        self.assertTrue(self.fb.consume_denoise_result(self.engine))
        self.assertEqual(native_threads, ["SuperLuxCoreViewportDenoise"] * 3)

    def test_progressive_read_pumps_stats_on_readback_worker(self):
        calls = []
        def output(kind, data, index, execute):
            calls.append(("pixels", threading.current_thread().name)); data[:] = .5
        film = types.SimpleNamespace(GetWidth=lambda: 2, GetHeight=lambda: 2, GetOutputFloat=output)
        self.engine.session = types.SimpleNamespace(GetFilm=lambda: film,
            UpdateStats=lambda: calls.append(("stats", threading.current_thread().name)))
        self.fb.start_async_update(self.engine.session, self.engine)
        self.fb._read_thread.join(3)
        self.assertFalse(self.fb._read_thread.is_alive())
        self.assertTrue(self.fb.consume_async_update(self.engine.session, self.engine))
        self.assertEqual(calls, [("stats", "SuperLuxCoreViewportReadback"),
                                 ("pixels", "SuperLuxCoreViewportReadback")])

    def test_completed_read_owner_survives_result_consumption_without_duplicate(self):
        pixels=np.arange(12,dtype=np.float32)
        owner=weakref.ref(pixels)
        self.engine.session=self.fb._read_session=object()
        self.fb._read_box={"done":True,"data":pixels,"width":2,"height":2,"mut_seq":3}
        self.assertTrue(self.fb.consume_async_update(self.engine.session,self.engine))
        del pixels
        self.assertIsNotNone(owner())
        self.assertTrue(np.shares_memory(owner(),self.fb._last_pixels))
        np.testing.assert_array_equal(self.fb._last_pixels.ravel(),np.arange(12,dtype=np.float32))

    def test_second_resize_keeps_held_frame_before_new_render_arrives(self):
        class Transition(self.cls):
            def __init__(self,engine,context,scene):
                self._width,self._height=context
                self._transparent=False;self._last_pixels=None;self._from_transition=False
                self.buffer=None
        old=types.SimpleNamespace(_last_pixels=np.arange(12,dtype=np.float32).reshape(2,2,3))
        first=Transition._transition_from(old,None,(4,3),None)
        self.assertIsNotNone(first.buffer)
        second=Transition._transition_from(first,None,(5,3),None)
        self.assertIsNotNone(second.buffer)
        self.assertTrue(np.any(second.buffer>0))

    def test_ui_construction_and_replacement_never_query_locked_film(self):
        calls=[]
        film=types.SimpleNamespace(GetWidth=lambda:2,GetHeight=lambda:2)
        def get_film():calls.append("native film access");return film
        self.engine.session=types.SimpleNamespace(GetFilm=get_film)
        scene=types.SimpleNamespace(camera=object(),superluxcore=types.SimpleNamespace(
            viewport=types.SimpleNamespace(pixel_size=1)))
        context=types.SimpleNamespace(material=True)
        class LocalFrame(self.cls):
            def _init_opengl(self):pass
            def _calc_view_rect(self,*a):return (0,0,2,2)
        fb=LocalFrame(self.engine,context,scene)
        self.assertFalse(fb.needs_replacement(context,scene,self.engine))
        self.assertEqual(calls,[])
        # A dynamically scaled read owns its dimensions; it must not
        # trigger a rebuild toward the configured (2,2) dimensions.
        self.assertTrue(fb._accept_pixels(np.ones(24,np.float32),4,2,mut_seq=3))
        self.assertFalse(fb.needs_replacement(context,scene,self.engine))
        self.assertEqual(calls,[])


if __name__ == "__main__": unittest.main(verbosity=2)
