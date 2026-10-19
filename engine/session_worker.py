"""
Dedicated session worker thread for the viewport.

All mutating calls on the live pysuperluxcore session - Start/Stop/Parse,
BeginSceneEdit/EndSceneEdit, config restarts and kernel pre-compiles -
run here instead of on Blender's UI thread. The main thread submits
jobs; the worker executes them serially, so a slow Stop + RenderConfig +
RenderSession + Start cycle (or a 15-minute kernel compile inside it)
can no longer freeze Blender.

Job coalescing: rapid-fire edits (e.g. dragging a color picker or
resizing the viewport) produce many config/edit jobs; pending jobs of
the same kind merge so only the newest state is ever applied - the
render never plays catch-up with stale settings.

``session_lock`` is shared with the engine: the worker holds it around
mutating calls on the live session, and the framebuffer/denoiser hold it
around film reads, so a film reset in EndSceneEdit can never tear a
GetOutputFloat in half. The lock is never held across a session
construction, so readers never wait on compiles.

This module only imports pysuperluxcore (never bpy) so it stays unit-testable
and can never accidentally touch Blender state off the main thread.
"""

import threading
import time
import traceback
import weakref
from collections import deque

import pysuperluxcore



def _uses_device_type(config_props, device_type):
    """True when the renderer selects the requested device type.

    Position i of the selection string addresses opencl.device.<i> of
    pysuperluxcore.GetOpenCLDeviceDescs() (same order the render engine sees:
    OpenCL, CUDA, Metal, Vulkan).
    """
    try:
        select = config_props.Get("opencl.devices.select", [""]).GetString()
        descs = pysuperluxcore.GetOpenCLDeviceDescs()
        if not select:
            # Default selection in OCLRenderEngine prefers Metal over
            # duplicate Apple OpenCL GPUs; CUDA takes precedence if present.
            # Vulkan is explicit-only. Keep other backend fill policies.
            if device_type != "METAL_GPU" or not config_props.Get(
                    "opencl.gpu.use", [True]).GetBool():
                return False
            types = {descs.Get(name).GetString() for name in descs.GetAllNames()
                     if name.startswith("opencl.device.") and name.endswith(".type")}
            return "METAL_GPU" in types and "CUDA_GPU" not in types
        for i, flag in enumerate(select):
            if flag == "1" and descs.Get(
                    "opencl.device." + str(i) + ".type"
            ).GetString() == device_type:
                return True
    except Exception:
        pass
    return False


def precompile_kernels(config_props, renderconfig, progress_cb=None):
    """Pre-compile GPU kernels so RenderSession.Start() doesn't stall.

    Mirrors the pre-fill create_session used to do inline: RTPATHOCL and
    PATHOCL kernels are compiled up-front for OCL engines when the kernel
    cache is cold. Returns True when a fill ran.

    Pure pysuperluxcore - safe on any thread. ``progress_cb`` receives
    ``(index, count)`` per compiled kernel (0-based index).
    """
    renderengine_type = config_props.Get("renderengine.type", ["PATHCPU"]).GetString()
    if not renderengine_type.endswith("OCL"):
        return False
    # KernelCacheFill renders unrelated matte test scenes for both PATHOCL
    # and RTPATHOCL, without the actual scene's spectral/options/type set.
    # Its .ck presence check is not a Metal binary-archive lookup. Starting
    # the real session below already compiles its exact Metal program on
    # this worker, so the generic fill only adds startup work and memory.
    if _uses_device_type(config_props, "METAL_GPU"):
        return False
    # Coherent DLSS frames start one exact realtime program below. The
    # generic filler first compiles an unused PATHOCL program and cannot
    # represent this scene's guide/material feature set.
    if (renderengine_type == "RTPATHOCL" and config_props.Get(
            "rtpath.denoisingframes.enable", [False]).GetBool()):
        return False
    if renderconfig.HasCachedKernels():
        return False
    # Copy config props so we can pass scene.epsilon.min,
    # scene.epsilon.max and opencl.devices.select to the kernel filler.
    props = pysuperluxcore.Properties(config_props)
    engines = ["PATHOCL", "RTPATHOCL"]
    if renderengine_type == "TILEPATHOCL":
        # Only pre-compile for tiled path if requested, since it's rarely
        # used
        engines.append("TILEPATHOCL")
    if _uses_device_type(config_props, "VULKAN_GPU"):
        # A Vulkan cold compile is tens of minutes per engine variant
        # (clspv + MoltenVK pipeline specialization) - fill only the
        # engine the session will actually start instead of warming both.
        engines = [renderengine_type]
    props.Set(
        pysuperluxcore.Property("kernelcachefill.renderengine.types", engines)
    )
    if progress_cb is None:
        pysuperluxcore.KernelCacheFill(props)
    else:
        pysuperluxcore.KernelCacheFill(props, progress_cb)
    return True


def _film_resize_props(previous, current):
    """Return validated RT film dimensions; other config edits restart.

    Compare complete exported configs, including imagepipeline/halt fields.
    RenderSession.Parse already has a film-edit path for the RT engines,
    preserving scene acceleration structures and compiled device kernels.
    """
    if previous is None:
        return None
    engine_type = current.Get("renderengine.type", [""]).GetString()
    # Repeated CPU film edits produced NaNs in the full light-traced
    # Junk Shop probe. Retain its known-good complete restart path.
    if (engine_type != "RTPATHOCL" or
            previous.Get("renderengine.type", [""]).GetString() != engine_type):
        return None
    names = set(current.GetAllNames())
    if names != set(previous.GetAllNames()):
        return None
    changed = {name for name in names
               if str(previous.Get(name)) != str(current.Get(name))}
    film_fields = {"film.width", "film.height"}
    policy_fields = {"rtpath.resolutionreduction", "rtpath.resolutionreduction.preview",
                     "rtpath.resolutionreduction.preview.step"}
    if (not changed <= film_fields | policy_fields or
            not names & {"film.width", "film.height"}):
        return None
    # Old wheels accept unknown Parse keys without applying the policy.
    # Retain a complete restart until the matching native API is present.
    if (changed & policy_fields and
            getattr(pysuperluxcore, "RT_FILM_RESOLUTION_POLICY_VERSION", 0) < 1):
        return None
    # Coherent CUDA uses this same Parse film-edit path for interaction
    # previews. A dimensions-only UI resize need not discard its session,
    # acceleration structures and DLSS consumer with a full Stop/Start.
    coherent_cuda = (current.Get("rtpath.denoisingframes.enable", [False]).GetBool()
                     and _uses_device_type(current, "CUDA_GPU"))
    if not (_uses_device_type(current, "METAL_GPU") or coherent_cuda):
        return None
    props = pysuperluxcore.Properties()
    if not changed:
        return props
    for name in ("film.width", "film.height", "rtpath.resolutionreduction",
                 "rtpath.resolutionreduction.preview", "rtpath.resolutionreduction.preview.step"):
        if name in names:
            props.Set(current.Get(name))
    return props


class SessionWorker:
    """Single worker thread owning the live pysuperluxcore session."""

    def __init__(self, engine=None, redraw_hook=None):
        self._cond = threading.Condition()
        self._queue = deque()
        self._shutdown = False
        # Marshals a callable onto Blender's main thread
        # (bpy.app.timers.register is the only thread-safe bpy entry
        # point). Without it, _publish would call engine.tag_redraw()
        # directly from this worker - bpy/RNA methods off the main
        # thread crash Blender intermittently.
        self._redraw_hook = redraw_hook

        # Live session, owned by the worker. Mirrored to engine.session
        # on every publish so main-thread readers (stats, film fetch)
        # always see the current object.
        self.session = None
        # The exported SuperLuxCore scene the session was built on.
        # RenderConfig(props, scene) is a non-owning ctor, so the Python
        # wrapper owns the native scene and must be kept here: reaching
        # it via session.GetRenderConfig().GetScene() goes through a
        # non-owning intermediate and can hit py::smart_holder
        # "Non-owning holder" load failures.
        self.scene = None
        # Shared with the engine; guards mutating calls on the live
        # session against concurrent film reads. Never held across a
        # RenderConfig/RenderSession construction or a kernel compile.
        self.session_lock = getattr(
            engine, "session_lock", None
        ) or threading.Lock()

        # Status surfaced in the viewport stats line.
        self.phase = ""
        self.progress = None  # (index, count) while compiling kernels

        # Weak reference: engine -> worker -> engine would otherwise be a
        # reference cycle, keeping the engine (and its live session) alive
        # until cyclic GC runs after Blender drops the RenderEngine.
        try:
            self._engine = weakref.ref(engine) if engine is not None else None
        except TypeError:
            self._engine = lambda: engine
        self._error = None
        # Create/start jobs queued or executing: while >0 and no session
        # is live, the viewport shows "starting" instead of polling.
        self._starting = 0
        # A start/config/edit job is executing: edits that arrive while
        # the session object is momentarily gone requeue instead of
        # being dropped.
        self._lifecycle_busy = False
        # Latest config submitted while no session was live; folded into
        # the next start job so a config edit during startup never starts
        # a session with stale settings.
        self._pending_config = None
        self._config_props = None
        self._scene_payload = None
        self.scene_light_count = None
        # Generation counter for start jobs: a superseded start (a newer
        # export landed while it was queued) skips its build.
        self._start_seq = 0
        # Incremented after every applied mutation (edit/config/parse/
        # start): film reads record it at kickoff so the framebuffer can
        # tell post-edit pixels from pre-edit ones (hold-last-frame).
        self.mutation_seq = 0
        self._dlss_worker = None
        self._dlss_signature = (None, "")
        self.dlss_status = ""

        self._thread = threading.Thread(
            target=self._run, daemon=True, name="SuperLuxCoreSessionWorker"
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Main-thread API (job submission)
    # ------------------------------------------------------------------

    def submit_start(self, superluxcore_scene, config_props):
        """Build RenderConfig + RenderSession + Start off-thread."""
        with self._cond:
            self._start_seq += 1
            self._starting += 1
            # The export that produced this job already reflects any
            # config stashed while session-less: don't let it override.
            self._pending_config = None
            self._queue.append(
                ["start", (superluxcore_scene, config_props, self._start_seq)]
            )
            self._cond.notify()

    def submit_config(self, config_props):
        """Restart the session on the reused scene with new config props.
        Coalesces: only the newest pending config is applied."""
        with self._cond:
            for job in reversed(self._queue):
                if job[0] == "config":
                    job[1] = config_props
                    self._pending_config = None
                    break
                if job[0] == "config_edit":
                    job[1][0] = config_props
                    self._pending_config = None
                    break
            else:
                if self.session is None:
                    # No queued config owns this update: fold it into the
                    # pending start, as for ordinary startup config edits.
                    self._pending_config = config_props
                    return
                self._queue.append(["config", config_props])
            self._cond.notify()

    def submit_edit(self, ops):
        """Replay recorded scene ops inside one Begin/EndSceneEdit."""
        if not ops:
            return
        with self._cond:
            if self._queue and self._queue[-1][0] == "edit":
                self._queue[-1][1].extend(ops)
            else:
                self._queue.append(["edit", list(ops)])
            self._cond.notify()

    def submit_config_and_edit(self, config_props, ops):
        """Keep a resized raster and its camera delta in one worker job.

        Camera ops are incremental: coalescing retains all of them in order,
        while only the latest complete config is needed.
        """
        if not ops:
            self.submit_config(config_props)
            return
        with self._cond:
            if (self.session is None and not self._lifecycle_busy
                    and not any(job[0] in ("start", "config", "config_edit") for job in self._queue)):
                # A fatal, truly session-less worker needs a fresh complete
                # export, which covers these scene deltas too.
                self._pending_config = config_props
                return
            self._pending_config = None
            if self._queue and self._queue[-1][0] == "config_edit":
                self._queue[-1][1][0] = config_props
                self._queue[-1][1][1].extend(ops)
            else:
                self._queue.append(["config_edit", [config_props, list(ops)]])
            self._cond.notify()

    def submit_parse(self, props):
        """session.Parse (imagepipeline/halt props). Merges with a pending
        parse so a burst of edits costs one call."""
        with self._cond:
            if self._queue and self._queue[-1][0] == "parse":
                self._queue[-1][1].Set(props)
            else:
                self._queue.append(["parse", props])
            self._cond.notify()

    def submit_resolution_reduction(self, value):
        """Runtime RTPATHOCL/RTPATHCPU resolution-reduction override.

        ``value`` 0 restores the configured reduction. Coalesces like a
        config job: only the newest pending value matters. Applies at
        the next frame boundary without a film reset, so it is safe to
        flip per interaction burst (drag = sparse fast passes, settle =
        full-quality passes).
        """
        with self._cond:
            for job in self._queue:
                if job[0] == "res_reduction":
                    job[1] = value
                    break
            else:
                self._queue.append(["res_reduction", value])
            self._cond.notify()

    def submit_stop(self):
        """Stop the live session and drop queued jobs (they were computed
        against a scene the restart is about to discard or the engine is
        being torn down; the follow-up full export re-covers them)."""
        with self._cond:
            self._start_seq += 1
            for job in self._queue:
                if job[0] == "start":
                    self._starting -= 1
                    _discard_scene_payload(job[1][0])
            self._queue.clear()
            self._pending_config = None
            self._queue.append(("stop", None))
            self._cond.notify()

    def shutdown(self):
        """Worker teardown (engine deleted): stop the session and exit."""
        with self._cond:
            self._start_seq += 1
            self._shutdown = True
            for job in self._queue:
                if job[0] == "start":
                    self._starting -= 1
                    _discard_scene_payload(job[1][0])
            self._queue.clear()
            self._cond.notify()
        if self._dlss_worker is not None:
            self._dlss_worker.shutdown()

    def configure_dlss(self, options, reason=""):
        """Main-thread path snapshot; SDK creation never occurs here."""
        signature = (options, reason)
        with self._cond:
            if signature == self._dlss_signature:
                return
            self._dlss_signature = signature
            self.dlss_status = reason
            for job in self._queue:
                if job[0] == "dlss_config":
                    job[1] = options
                    break
            else:
                self._queue.append(["dlss_config", options])
            self._cond.notify()

    def take_dlss_result(self, session):
        """Only owned arrays cross to the main thread; no renderer calls."""
        consumer = self._dlss_worker
        if consumer is None:
            return None
        error = consumer.pop_error()
        if error:
            self.dlss_status = "DLSS fallback: " + error[1]
        result = consumer.take(session, self.mutation_seq)
        if result is not None:
            self.dlss_status = "DLSS Ray Reconstruction"
        return result

    def _stop_dlss_worker(self):
        consumer = self._dlss_worker
        if consumer is not None:
            consumer.shutdown()
            if not consumer.join(15):
                raise RuntimeError("DLSS backend has not finished teardown")
            self._dlss_worker = None

    def _do_dlss_config(self, options):
        self._stop_dlss_worker()
        if options is None:
            return
        from .dlss_stream import DLSSFrameWorker
        def notify():
            engine = self._get_engine()
            if engine is not None and self._redraw_hook is not None:
                self._redraw_hook(engine.tag_redraw)
        self._dlss_worker = DLSSFrameWorker(
            lambda: (self.session, self.mutation_seq), self.session_lock,
            options.backend, options.postprocessor, notify, output_size=getattr(options, 'output_size', None))
        self._dlss_worker.start()

    # ------------------------------------------------------------------
    # Main-thread polling
    # ------------------------------------------------------------------

    @property
    def is_starting(self):
        """True while a create/start job is queued or executing and no
        live session exists yet."""
        return self.session is None and self._starting > 0

    def pop_error(self):
        """Return and clear the last failed job as (kind, error)."""
        err, self._error = self._error, None
        return err

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _get_engine(self):
        return self._engine() if self._engine is not None else None

    def _publish(self, session):
        """Make ``session`` the engine-visible current session."""
        self.session = session
        engine = self._get_engine()
        if engine is not None:
            try:
                engine.session = session
                engine.viewport_start_time = time.time()
            except ReferenceError:
                # RenderEngine struct deleted underneath us
                return
        # tag_redraw is a bpy method - must run on the main thread.
        hook = self._redraw_hook
        if hook is not None and engine is not None:
            hook(engine.tag_redraw)

    def _run(self):
        while True:
            with self._cond:
                while not self._queue and not self._shutdown:
                    self._cond.wait()
                if self._shutdown:
                    break
                job = self._queue.popleft()
            try:
                self._execute(job)
            except Exception as error:
                traceback.print_exc()
                self._error = (job[0], error)
                self.phase = ""
                self.progress = None
                if job[0] in ("start", "config", "config_edit", "edit", "parse"):
                    # The session is unusable (stopped or half-edited):
                    # drop it so the next view_update re-exports fresh.
                    self._stop_session()
                    self._drop_scene_payload()
                    self._publish(None)
        # Shutdown: stop whatever session is still live.
        try:
            self._stop_dlss_worker()
        except Exception as error:
            self._error = ("dlss", error)
        finally:
            self._stop_session()
            self._drop_scene_payload()

    def _execute(self, job):
        kind, payload = job
        if kind == "start":
            self._do_start(*payload)
        elif kind == "config":
            self._do_config(payload)
        elif kind == "config_edit":
            self._do_config(*payload)
        elif kind == "edit":
            self._do_edit(payload)
        elif kind == "parse":
            self._do_parse(payload)
        elif kind == "res_reduction":
            self._do_res_reduction(payload)
        elif kind == "stop":
            self._do_stop()
        elif kind == "dlss_config":
            self._do_dlss_config(payload)

    def _stop_session(self):
        session, self.session = self.session, None
        self._config_props = None
        if session is not None:
            try:
                with self.session_lock:
                    session.Stop()
            except Exception:
                traceback.print_exc()

    def _do_stop(self):
        self._stop_session()
        self._drop_scene_payload()
        self._publish(None)

    def _drop_scene_payload(self):
        self.scene = None
        self.scene_light_count = None
        payload, self._scene_payload = self._scene_payload, None
        if payload is not None:
            _discard_scene_payload(payload)

    def _publish_started(self, session):
        """Publish, then schedule settings received during construction.

        A submission after publish already queues its own config job; it
        is newer than the session-less pending value and takes precedence.
        Stop/start jobs supersede the construction too.
        """
        self.mutation_seq += 1
        self._publish(session)
        with self._cond:
            pending, self._pending_config = self._pending_config, None
            if pending is not None and not self._shutdown and not any(
                job[0] in ("config", "config_edit", "start", "stop") for job in self._queue
            ):
                self._queue.appendleft(["config", pending])
                self._cond.notify()

    def _do_start(self, superluxcore_scene, config_props, seq):
        session = None
        try:
            if seq != self._start_seq:
                # A newer export landed while this job sat in the queue.
                _discard_scene_payload(superluxcore_scene)
                return
            self._lifecycle_busy = True
            # A config change that queued behind this start wins over
            # the props captured during export.
            with self._cond:
                if self._pending_config is not None:
                    config_props = self._pending_config
                    self._pending_config = None

            # A previous session must not keep rendering alongside the
            # new one (a superseded start leaves a live session behind).
            self._stop_session()
            self._drop_scene_payload()
            build = getattr(superluxcore_scene, "_build_pending_scene", None)
            if build is not None:
                self._scene_payload = superluxcore_scene
                self.phase = "Building scene"
                superluxcore_scene = build(
                    lambda: self._shutdown or seq != self._start_seq)
                if superluxcore_scene is None:
                    self._drop_scene_payload()
                    self.phase = ""
                    return
            self.scene = superluxcore_scene
            count = getattr(superluxcore_scene, "GetLightCount", None)
            self.scene_light_count = count() if count is not None else None
            self.phase = "Creating render config"
            renderconfig = pysuperluxcore.RenderConfig(config_props, superluxcore_scene)

            def progress_cb(index, count):
                self.progress = (index + 1, count)
                self.phase = f"Compiling kernels ({index + 1}/{count})"

            precompile_kernels(config_props, renderconfig, progress_cb)
            self.progress = None

            if self._shutdown or seq != self._start_seq:
                self._drop_scene_payload()
                self.phase = ""
                return

            self.phase = "Starting session"
            session = pysuperluxcore.RenderSession(renderconfig)
            session.Start()
            with self._cond:
                superseded = self._shutdown or seq != self._start_seq
                if not superseded:
                    self.phase = ""
                    self._config_props = pysuperluxcore.Properties()
                    self._config_props.Set(config_props)
                    self._publish_started(session)
            if superseded:
                session.Stop()
                self._drop_scene_payload()
                self.phase = ""
                return
        except BaseException:
            if session is not None:
                try:
                    session.Stop()
                except Exception:
                    traceback.print_exc()
            raise
        finally:
            self._lifecycle_busy = False
            with self._cond:
                self._starting -= 1

    def _do_config(self, config_props, scene_ops=()):
        """https://github.com/LuxCoreRender/BlendLuxCore/issues/577

        Metal RT dimension-only edits use the existing film-edit Parse path.
        Other edits still rebuild a complete config/session as below.
        The old code mutated the RenderConfig of the running session,
        which leaked (every stopped session kept its scene copy) and
        crashed on some SuperLuxCore versions. We build a fresh RenderConfig
        on the *same* SuperLuxCore scene instead - meshes, materials and
        lights stay defined, so no Blender re-export is needed - then
        swap in a fresh session. Everything runs on the worker so the
        Stop + rebuild + Start cycle never touches the UI thread.
        """
        old = self.session
        if old is None:
            # Session died between submit and execution: stash the props
            # so the next start uses them.
            with self._cond:
                self._pending_config = config_props
            return

        self._lifecycle_busy = True
        try:
            resize_props = _film_resize_props(self._config_props, config_props)
            if resize_props is not None:
                if not resize_props.GetAllNames():
                    # A coalesced resize may already match the live config.
                    # Do not resume/Parse or invalidate an in-flight image
                    # when no rendering state actually changes.
                    if scene_ops:
                        self._do_edit(scene_ops)
                    return
                self.phase = "Resizing film"
                with self.session_lock:
                    if old.IsInPause():
                        old.Resume()
                    if scene_ops:
                        # Do not let a film read observe the new dimensions
                        # with the previous camera. Both native boundaries
                        # belong to a single published mutation generation.
                        old.BeginSceneEdit()
                        try:
                            _replay_ops(self.scene, scene_ops)
                        except Exception:
                            try:
                                old.EndSceneEdit()
                            except Exception:
                                pass
                            raise
                        old.EndSceneEdit()
                    old.Parse(resize_props)
                    self.mutation_seq += 1
                self._config_props = pysuperluxcore.Properties()
                self._config_props.Set(config_props)
                self.phase = ""
                self._publish(old)
                return
            self.phase = "Reconfiguring session"
            # The worker keeps the exported scene alive itself (the
            # RenderConfig ctor is non-owning): do NOT fetch it via
            # old.GetRenderConfig().GetScene(), which traverses a
            # non-owning intermediate wrapper.
            scene = self.scene
            if scene is None:
                with self._cond:
                    self._pending_config = config_props
                return
            with self.session_lock:
                old.Stop()
                if scene_ops:
                    # A full restart applies the recorded camera/scene delta
                    # after stopping the old tracer and before starting its
                    # replacement on the same scene owner.
                    _replay_ops(scene, scene_ops)
            # engine.session still points at the old (stopped) session
            # until the replacement publishes: readers keep seeing its
            # last film instead of a black frame.
            self.session = None

            renderconfig = pysuperluxcore.RenderConfig(config_props, scene)

            def progress_cb(index, count):
                self.progress = (index + 1, count)
                self.phase = f"Compiling kernels ({index + 1}/{count})"

            precompile_kernels(config_props, renderconfig, progress_cb)
            self.progress = None

            self.phase = "Starting session"
            session = pysuperluxcore.RenderSession(renderconfig)
            session.Start()
            self.phase = ""
            self._config_props = pysuperluxcore.Properties()
            self._config_props.Set(config_props)
            self._publish_started(session)
        finally:
            self._lifecycle_busy = False

    def _do_edit(self, ops):
        session = self.session
        if session is None:
            # A start/config is in flight and momentarily owns no
            # session: requeue behind it so the edit lands on the new
            # session (the scene is shared, order is preserved).
            with self._cond:
                if self._lifecycle_busy or any(
                    j[0] in ("start", "config", "config_edit") for j in self._queue
                ):
                    self._queue.append(["edit", ops])
                # else: truly session-less (startup failed); the
                # follow-up full export rebuilds the state anyway.
            return
        self.phase = "Applying scene edits"
        # See _do_config: use the worker-held scene, not
        # session.GetRenderConfig().GetScene().
        scene = self.scene
        if scene is None:
            return
        with self.session_lock:
            session.BeginSceneEdit()
            try:
                _replay_ops(scene, ops)
            except Exception:
                # Partial replay leaves the scene in an unknown state;
                # bail out to a full rebuild rather than render garbage.
                try:
                    session.EndSceneEdit()
                except Exception:
                    pass
                raise
            session.EndSceneEdit()
            if session.IsInPause():
                session.Resume()
            # Bump inside the lock so a film read can never observe the
            # post-edit film while still carrying a pre-edit mut_seq.
            self.mutation_seq += 1
        # The edit restarted rendering: re-anchor the viewport halt timer
        # at the actual resume point. Without this a queued edit that runs
        # after halt_time elapsed gets re-paused instantly by view_draw
        # (resume -> pause loop = black/frozen viewport).
        engine = self._get_engine()
        if engine is not None:
            try:
                engine.viewport_start_time = time.time()
            except ReferenceError:
                pass
        self.phase = ""

    def _do_res_reduction(self, value):
        session = self.session
        if session is None:
            return
        # Atomic store into the engine - no film reset, no mutation_seq
        # bump (coverage pattern changes, accumulated samples stay valid).
        # getattr: tolerate a stale pysuperluxcore lacking the binding.
        set_reduction = getattr(
            session, "SetRuntimeResolutionReduction", None
        )
        if set_reduction is not None:
            engine_type = self._config_props.Get(
                "renderengine.type", [""]).GetString() if self._config_props is not None else ""
            if engine_type == "RTPATHOCL":
                # This native setter only stores runtimeResolutionReduction
                # atomically (or ignores it for coherent frames). The RT
                # render thread reads it at a frame boundary. This worker
                # owns session Start/Stop, so a concurrent film read cannot
                # invalidate the pinned session or require a film lock here.
                # Waiting for readback would delay every queued edit behind
                # a frame which the edit is about to invalidate anyway.
                set_reduction(value)
            else:
                # RTPATHCPU also updates sampler shared data: retain its
                # existing synchronization with film reads and scene edits.
                with self.session_lock:
                    set_reduction(value)

    def _do_parse(self, props):
        session = self.session
        if session is None:
            return
        with self.session_lock:
            session.Parse(props)
            # Interaction previews resize through a partial Parse rather
            # than a complete config job. Keep these live dimensions in
            # the comparison cache so an otherwise-identical exported
            # full-size config still restores the physical film.
            if self._config_props is not None:
                for name in ("film.width", "film.height"):
                    if props.IsDefined(name):
                        self._config_props.Set(props.Get(name))
            self.mutation_seq += 1
            resume_dlss = self._dlss_worker is not None and any(
                name.startswith(("film.imagepipeline", "film.radiancescales"))
                for name in props.GetAllNames())
            if resume_dlss and session.IsInPause():
                session.Resume()
        if resume_dlss:
            engine = self._get_engine()
            if engine is not None:
                try:
                    engine.viewport_start_time = time.time()
                except ReferenceError:
                    pass


def _replay_ops(scene, ops):
    """Apply RecordedScene ops on the real scene. Free function so tests
    can drive it without a worker."""
    for name, args, kwargs in ops:
        getattr(scene, name)(*args, **kwargs)


def _discard_scene_payload(scene):
    if getattr(scene, "_build_pending_scene", None) is not None:
        scene.close()
