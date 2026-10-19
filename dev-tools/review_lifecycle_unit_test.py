"""Regression tests for deferred edits, worker configs, denoise and external cleanup.

Source methods execute with deterministic gates/fakes; no Blender import required.
Real output format/color validation is covered by review_blender_test.py.
"""
import ast
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


fake = load("review_worker_fakes", ROOT / "dev-tools/async_worker_unit_test.py")


def methods(path, names, env, cls=None):
    nodes = ast.parse(path.read_text()).body
    if cls: nodes = next(n for n in nodes if isinstance(n, ast.ClassDef) and n.name == cls).body
    selected = [n for n in nodes if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), env)


class Regressions(unittest.TestCase):
    def test_configs_arriving_during_start_and_restart(self):
        for initial in (True, False):
            with self.subTest(initial=initial):
                entered, release = threading.Event(), threading.Event()
                original = fake.fake_pysuperluxcore.RenderConfig
                class Blocking(original):
                    def __init__(self, props, *args):
                        if props.Get("film.width").Get() == 64:
                            entered.set(); assert release.wait(3)
                        super().__init__(props, *args)
                def props(width):
                    return fake.FakeProperties("renderengine.type", "film.width") << ("PATHCPU", width)
                w = fake.SessionWorker()
                try:
                    if not initial:
                        w.submit_start(fake.FakeScene(), props(32))
                        self.assertTrue(fake.wait_until(lambda: w.session is not None))
                    fake.fake_pysuperluxcore.RenderConfig = Blocking
                    if initial: w.submit_start(fake.FakeScene(), props(64))
                    else: w.submit_config(props(64))
                    self.assertTrue(entered.wait(3))
                    w.submit_config(props(96)); w.submit_config(props(128))
                    release.set()
                    self.assertTrue(fake.wait_until(lambda: w.session is not None and
                        w.session.config.props.Get("film.width").Get() == 128 and not w._lifecycle_busy))
                    self.assertIsNone(w._pending_config)
                finally:
                    release.set(); w.shutdown(); w._thread.join(3)
                    self.assertFalse(w._thread.is_alive())
                    fake.fake_pysuperluxcore.RenderConfig = original

    def test_deferred_independent_edits_keep_order_when_hold_expires(self):
        submitted = []
        now = [1]
        env = {"time": lambda: now[0], "_dyn_res_value": lambda x: 16,
            "_submit_film_scale": lambda *a: None, "_interaction_film_scale": lambda e: 1,
            "_DYN_RES_TAIL_S": .4, "FrameBuffer": types.SimpleNamespace(HOLD_LAST_FRAME_CAMERA_S=.3)}
        methods(ROOT / "engine/viewport.py", {"_submit_jobs"}, env)
        e = types.SimpleNamespace()
        w = types.SimpleNamespace(submit_resolution_reduction=lambda x: None,
            submit_edit=lambda ops: submitted.extend(ops), submit_parse=lambda p: submitted.append(p))
        fb = types.SimpleNamespace(_width=32, _height=32, _pending_reset=True,
            _pending_reset_deadline=100, begin_reset=lambda *a, **kw: None, reset_denoiser=lambda: None)
        env["_submit_jobs"](e, w, fb, [("edit", ["materialA"])], False)
        env["_submit_jobs"](e, w, fb, [("edit", ["cameraB"])], True)
        now[0] = 101
        env["_submit_jobs"](e, w, fb, [("edit", ["objectC"]), ("parse", "pipelineD")], False)
        self.assertEqual(submitted, ["materialA", "cameraB", "objectC", "pipelineD"])
        self.assertIsNone(e._deferred_edit_jobs)

    def test_denoiser_reset_bounds_workers_and_cancels_lock_waiter(self):
        env = {"threading": threading, "_session_lock": lambda e: e.lock}
        names = {"start_denoiser", "reset_denoiser", "is_denoiser_active", "run_denoiser"}
        methods(ROOT / "draw/viewport.py", {"run_denoiser"}, env)
        methods(ROOT / "draw/viewport.py", names, env, "FrameBuffer")
        cls = type("FrameBufferStub", (), {n: env[n] for n in names if n != "run_denoiser"})
        fb = cls(); fb._denoiser_thread = None; fb._denoise_box = None
        fb._output_type = "RGB"; fb._transparent = False
        called = []
        session = types.SimpleNamespace(GetFilm=lambda: types.SimpleNamespace(ApplyOIDN=lambda i: called.append(i)))
        engine = types.SimpleNamespace(session=session, lock=threading.Lock())
        engine.lock.acquire()
        thread = None
        try:
            self.assertTrue(fb.start_denoiser(engine)); thread = fb._denoiser_thread
            for i in range(8):
                fb.reset_denoiser()
                self.assertTrue(fb.is_denoiser_active())
                self.assertFalse(fb.start_denoiser(engine))
                self.assertIs(fb._denoiser_thread, thread)
        finally:
            engine.lock.release()
            if thread: thread.join(3)
        self.assertEqual(called, [])
        self.assertFalse(fb.is_denoiser_active())

    def test_external_cleanup_success_failure_and_missing_beauty(self):
        package = types.ModuleType("review_external_utils"); package.__path__ = []
        sys.modules[package.__name__] = package
        errors = []
        err = types.ModuleType("review_external_utils.errorlog")
        err.SuperLuxCoreErrorLog = types.SimpleNamespace(add_error=errors.append)
        sys.modules[err.__name__] = err
        env = {"__package__": package.__name__, "os": __import__("os"), "glob": __import__("glob"),
            "re": __import__("re"), "shutil": shutil, "deque": __import__("collections").deque,
            "bpy": types.SimpleNamespace(data=types.SimpleNamespace(images=types.SimpleNamespace(load=lambda *a, **kw: object())),
                context=types.SimpleNamespace(window_manager=types.SimpleNamespace(windows=[])))}
        methods(ROOT / "utils/external_render.py", {"_finish", "_find_beauty", "_resolve_target"}, env)
        env["_save_beauty"] = lambda job, source, dest: shutil.copyfile(source, dest)
        with tempfile.TemporaryDirectory(prefix="slc-external-unit-") as tmp:
            for case in ("ok", "failed", "missing"):
                work = Path(tmp) / case; work.mkdir()
                (work / "scene.bcf").write_text("temporary serialized scene")
                (work / "render.log").write_text("bounded error tail")
                if case != "missing": (work / "beauty.exr").write_bytes(b"\x76\x2f\x31\x01float-placeholder")
                code = 1 if case == "failed" else 0
                job = types.SimpleNamespace(workdir=str(work), log_path=str(work / "render.log"),
                    proc=types.SimpleNamespace(poll=lambda: code, returncode=code),
                    target_path=str(Path(tmp) / (case + ".exr")), frame=1)
                env["_finish"](job)
                self.assertFalse(work.exists())
                if case == "ok": self.assertTrue(Path(job.target_path).is_file())
            self.assertEqual(len(errors), 2)


if __name__ == "__main__": unittest.main(verbosity=2)
