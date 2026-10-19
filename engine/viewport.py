from time import time
import math

_needs_reload = "bpy" in locals()

import bpy
import pysuperluxcore
from .. import export
from .. import draw
from ..draw.viewport import FrameBuffer
from .. import utils
from ..utils import render as utils_render
from ..utils import get_addon_preferences
from ..utils.log import SuperLuxCoreLog
from ..utils.errorlog import SuperLuxCoreErrorLog
from ..export.config import convert_viewport_engine
from . import session_worker
from . import dlss_viewport
from dataclasses import replace
import os

if _needs_reload:
    import importlib

    importlib.reload(session_worker)
    importlib.reload(export)
    importlib.reload(utils)
    importlib.reload(draw)


def _worker(engine, context=None):
    """Lazily create the session worker (one per RenderEngine)."""
    worker = getattr(engine, "session_worker", None)
    if worker is None:
        # Attribute access (not the stale `from`-import) so addon reload
        # picks up the reloaded class. redraw_hook keeps the worker
        # bpy-free: bpy.app.timers.register is the only thread-safe bpy
        # call, the timer itself then runs tag_redraw on the main thread
        # (calling it directly from the worker crashed Blender).
        def _marshal_redraw(fn):
            def _call():
                try:
                    fn()
                except ReferenceError:
                    pass
                return None
            bpy.app.timers.register(_call, first_interval=0.0)

        worker = session_worker.SessionWorker(
            engine, redraw_hook=_marshal_redraw
        )
        engine.session_worker = worker
    if context is not None:
        vp = context.scene.superluxcore.viewport
        requested = vp.use_denoiser and vp.denoiser == "DLSS" and not utils.in_material_shading_mode(context)
        if not requested:
            if getattr(engine, '_dlss_configuration_key', None) is not None:
                previous = worker._dlss_signature[0]
                worker.configure_dlss(None)
                engine._dlss_configuration_key = None
                if (getattr(previous, 'render_mode', 'NATIVE') != 'NATIVE' and
                        engine.session is not None and getattr(engine, 'exporter', None) is not None):
                    _submit_config_update(engine, worker, context.scene, context)
            return worker
        preferences = get_addon_preferences(context)
        transparent = bool(utils.is_valid_camera(context.scene.camera) and
                           export.blender_settings.transparent_film(context.scene))
        render_mode = getattr(vp, 'dlss_render_mode', 'NATIVE')
        output_size = utils.calc_filmsize(context.scene, context) if render_mode != 'NATIVE' else None
        key = (requested, vp.device, utils.using_bidir_in_viewport(context.scene), preferences.gpu_backend,
               preferences.dlss_library, preferences.dlss_runtime, transparent,
               getattr(vp, 'dlss_preset', 'DEFAULT'),
               render_mode, output_size,
               os.environ.get('SUPERLUXCORE_DLSS_LIBRARY'),
               os.environ.get('SUPERLUXCORE_DLSS_RUNTIME'),
               os.environ.get('SUPERLUXCORE_DLSS_CACHE'))
        if key != getattr(engine, '_dlss_configuration_key', None):
            options, reason = None, ''
            if requested:
                if vp.device != "OCL" or utils.using_bidir_in_viewport(context.scene):
                    reason = 'DLSS requires the realtime GPU path; ordinary render active'
                elif preferences.gpu_backend != "CUDA":
                    reason = 'DLSS requires the NVIDIA CUDA backend; ordinary render active'
                else:
                    options, reason = dlss_viewport.configuration(
                        bpy.path.abspath(preferences.dlss_library) if preferences.dlss_library else '',
                        bpy.path.abspath(preferences.dlss_runtime) if preferences.dlss_runtime else '',
                        getattr(vp, 'dlss_preset', 'DEFAULT'), render_mode)
                    if options is not None:
                        options = replace(options, channels=4 if transparent else 3, output_size=output_size)
            previous = worker._dlss_signature[0]
            worker.configure_dlss(options, reason)
            engine._dlss_configuration_key = key
            if (engine.session is not None and getattr(engine, 'exporter', None) is not None and
                    getattr(previous, 'render_mode', 'NATIVE') != getattr(options, 'render_mode', 'NATIVE')):
                _submit_config_update(engine, worker, context.scene, context)
        if (render_mode != 'NATIVE' and worker._dlss_signature[0] is not None and
                worker.dlss_status.startswith('DLSS fallback: ')):
            # A failed SR path must restore the user's full physical input,
            # rather than leave an ordinary render at the reduced SR size.
            reason = worker.dlss_status
            worker.configure_dlss(None, reason)
            if engine.session is not None and getattr(engine, 'exporter', None) is not None:
                _submit_config_update(engine, worker, context.scene, context)
    return worker


_LOCK_BUSY = object()

# Dynamic resolution switching: while the user interacts (scene edits
# arriving), RTPATHOCL runs sparse coverage passes - every pixel carries
# weight 1.0 regardless of reduction, so passes stay unbiased but finish
# in ~1/16 of the time. That shrinks both the frame-boundary wait before
# an edit applies and the first-post-reset-sample latency. Once edits
# stop arriving for _DYN_RES_TAIL_S the configured reduction is restored.
_DYN_RES_VALUE = 16
_DYN_RES_TAIL_S = 0.4
# Above this pixel count interaction additionally downscales the film
# itself (Parse-based BeginFilmEdit/EndFilmEdit fast path): render
# passes, the display-pipeline plugins AND the GetOutputFloat readback
# all shrink quadratically - at 4K the readback alone is ~100 MB/frame.
_INTERACTION_DOWNSCALE_PIXELS = 2_500_000
_INTERACTION_DOWNSCALE_FACTOR = 2
# Coherent DLSS frames cannot use sparse passes: every input pixel must
# contain a sample. Bound their interaction cost with the actual film size.
# This is temporary preview resolution; settled rendering always restores
# the full film and the original transport settings.
_DLSS_INTERACTION_PIXELS = 512 * 1024
_DLSS_PREVIEW_MAX_WAIT_S = 10.0
_RT_ENGINES = {"RTPATHOCL", "RTPATHCPU"}


def _dyn_res_value(pixels):
    """Sparse-pass factor while interacting, scaled to film size.

    Same budget math as the steady rr in convert_viewport_engine:
    per-pass samples stay ~constant regardless of viewport size, so a
    4K region gets 32-64 instead of the 720p-tuned 16."""
    if pixels <= 0:
        return _DYN_RES_VALUE
    steady = 1 << min(4, max(0, round(0.5 * math.log2(pixels / 65536))))
    return min(64, max(16, steady * 4))


def _dlss_interaction_active(engine):
    worker = getattr(engine, "session_worker", None)
    signature = getattr(worker, "_dlss_signature", None)
    return (getattr(engine, "_engine_type", "") == "RTPATHOCL"
            and signature is not None and signature[0] is not None)


def _dlss_render_size(engine, width, height):
    worker = getattr(engine, 'session_worker', None)
    options = getattr(worker, '_dlss_signature', (None, ''))[0]
    resolve = getattr(options, 'input_size', None)
    return resolve((width, height)) if resolve is not None else (width, height)


def _interaction_film_scale(engine):
    """Linear film divisor during interaction bursts.

    Only the RT engines get it: their BeginFilmEdit/EndFilmEdit
    suspends/resumes render threads in place, while the classic engines
    pay a full Stop/Start (kernel re-init) per transition - not worth it
    for a sub-second drag."""
    if getattr(engine, "_engine_type", "") not in _RT_ENGINES:
        return 1
    w, h = getattr(engine, "last_viewport_size", (0, 0))
    if _dlss_interaction_active(engine):
        rw, rh = _dlss_render_size(engine, w, h)
        budget = _DLSS_INTERACTION_PIXELS
        if w * h > budget:
            # Match the cost of Native's existing half-width preview. A
            # Quality SR input can be below the absolute cap yet still trace
            # more pixels than that preview, making orbit slower than Native.
            # Ceil the quarter area so odd dimensions keep Native's divisor.
            budget = min(budget, (w * h + 3) // 4)
        if rw * rh > budget:
            return min(8, 2 ** math.ceil(.5 * math.log2(rw * rh / budget)))
        return 1
    if w * h > _INTERACTION_DOWNSCALE_PIXELS:
        return _INTERACTION_DOWNSCALE_FACTOR
    return 1


def _submit_config_update(engine, worker, scene, context, depsgraph=None, changes=0):
    # Interaction-scale restoration must target the latest viewport size.
    # Keeping the startup dimensions here resized a live film back to the
    # old window after a successful config resize.
    previous_size = getattr(engine, "last_viewport_size", None)
    engine.last_viewport_size = utils.calc_filmsize(scene, context)
    props = engine.exporter.get_restart_config_props()
    if _dlss_interaction_active(engine):
        render_props = pysuperluxcore.Properties()
        render_props.Set(props)
        rw, rh = _dlss_render_size(engine, *engine.last_viewport_size)
        render_props.Set(pysuperluxcore.Property("film.width", rw))
        render_props.Set(pysuperluxcore.Property("film.height", rh))
        props = render_props
        scale = _interaction_film_scale(engine)
        engine._film_scale = scale
        engine._dyn_res_active = scale > 1
        engine._dyn_res_until = time() + _DYN_RES_TAIL_S
        worker.submit_resolution_reduction(0)
        if scale > 1:
            # Keep the exported full-size config untouched. Resize feedback
            # uses the same coherent pixel budget as orbit; the accepted
            # preview releases restoration to the latest full region size.
            preview = pysuperluxcore.Properties()
            preview.Set(props)
            w, h = _dlss_render_size(engine, *engine.last_viewport_size)
            preview.Set(pysuperluxcore.Property("film.width", max(16, w // scale)))
            preview.Set(pysuperluxcore.Property("film.height", max(16, h // scale)))
            props = preview
    elif (getattr(engine, "_engine_type", "") == "RTPATHOCL"
            and props.Get("renderengine.type", [""]).GetString() == "RTPATHOCL"
            and previous_size is not None and previous_size != engine.last_viewport_size
            and scene.superluxcore.viewport.reduce_resolution_on_edit
            and utils.get_addon_preferences(context).gpu_backend == "METAL"):
        # Ordinary Metal resize uses the same user-enabled moving preview
        # as orbit. Repeated full-size film allocation/readback otherwise
        # outruns the edit cadence at large viewport sizes. Keep the full
        # exported config intact and restore its latest dimensions on idle.
        scale = _interaction_film_scale(engine)
        if scale > 1:
            preview = pysuperluxcore.Properties()
            preview.Set(props)
            w, h = engine.last_viewport_size
            preview.Set(pysuperluxcore.Property("film.width", max(16, w // scale)))
            preview.Set(pysuperluxcore.Property("film.height", max(16, h // scale)))
            props = preview
            engine._film_scale = scale
            engine._dyn_res_active = True
            engine._dyn_res_until = time() + _DYN_RES_TAIL_S
    paired_jobs = None
    if (depsgraph is not None and changes & export.Change.CAMERA
            and getattr(engine, "_engine_type", "") == "RTPATHOCL"
            and previous_size is not None and previous_size != engine.last_viewport_size):
        try:
            paired_jobs = engine.exporter.update(
                depsgraph, context, changes & ~export.Change.CONFIG)
        except Exception as error:
            SuperLuxCoreErrorLog.add_error(error)
            import traceback
            traceback.print_exc()
            force_session_restart(engine)
            return None
        deferred = getattr(engine, "_deferred_edit_jobs", None)
        if deferred is not None:
            paired_jobs = deferred[0] + paired_jobs
            engine._deferred_edit_jobs = None
        scene_ops = []
        parses = []
        for kind, payload in paired_jobs:
            if kind == "edit":
                scene_ops.extend(payload)
            elif kind == "parse":
                parses.append(payload)
        # This camera describes the resized raster itself. Waiting for the
        # reset just submitted by that resize would pace it behind its own
        # incomplete frame. Keep ordinary orbit pacing in _submit_jobs().
        if not _dlss_interaction_active(engine):
            framebuffer = getattr(engine, "framebuffer", None)
            pixels = (framebuffer._width * framebuffer._height if framebuffer is not None
                      else engine.last_viewport_size[0] * engine.last_viewport_size[1])
            worker.submit_resolution_reduction(_dyn_res_value(pixels))
        engine._dyn_res_until = time() + _DYN_RES_TAIL_S
        engine._dyn_res_active = True
        worker.submit_config_and_edit(props, scene_ops)
        for parsed in parses:
            worker.submit_parse(parsed)
    else:
        worker.submit_config(props)
    return paired_jobs is not None


def _submit_film_scale(engine, worker, scale):
    """Ask the worker to resize the live film (Parse fast path).

    ``engine._film_scale`` records the requested factor so a redundant
    request is never re-parsed; the framebuffer itself follows the live
    film dims, so no display-side coordination is needed."""
    if getattr(engine, "_film_scale", 1) == scale:
        return
    engine._film_scale = scale
    w, h = getattr(engine, "last_viewport_size", (0, 0))
    if w <= 0 or h <= 0:
        return
    w, h = _dlss_render_size(engine, w, h)
    props = pysuperluxcore.Properties()
    props.Set(pysuperluxcore.Property(
        "film.width", max(16, w // scale)))
    props.Set(pysuperluxcore.Property(
        "film.height", max(16, h // scale)))
    worker.submit_parse(props)


def _restore_interaction(engine, worker, framebuffer):
    """Restore full resolution after a fresh preview, with a bounded wait.

    A fixed .4s tail can regrow a coherent film before its first complete
    preview is delivered, throwing away the very work needed for feedback.
    Only a DLSS upload belonging to the current session/edit and requested
    preview size releases that hold. Failure or a stalled producer still
    restores the physical film after the bounded deadline.
    """
    if not getattr(engine, "_dyn_res_active", False):
        return
    now = time()
    until = getattr(engine, "_dyn_res_until", 0)
    if now <= until:
        return
    scale = getattr(engine, "_film_scale", 1)
    if (scale > 1 and _dlss_interaction_active(engine)
            and now < until + _DLSS_PREVIEW_MAX_WAIT_S):
        w, h = _dlss_render_size(engine, *getattr(engine, "last_viewport_size", (0, 0)))
        expected = (max(16, w // scale), max(16, h // scale))
        ready = (framebuffer is not None
                 and framebuffer._dlss_owner == (id(engine.session), worker.mutation_seq)
                 and (getattr(framebuffer, '_dlss_last_source_size', None) or
                      (framebuffer._width, framebuffer._height)) == expected
                 and not worker.phase
                 and not getattr(engine, "_deferred_edit_jobs", None))
        if not ready:
            engine.tag_redraw()
            return
    engine._dyn_res_active = False
    _submit_film_scale(engine, worker, 1)
    worker.submit_resolution_reduction(0)


def _set_stats(engine, text, sub):
    """update_stats() with dedup: each call triggers a stats-region
    redraw, and alternating/identical writes every frame make the
    viewport text flicker. Only write when the text actually changed."""
    new = (text, sub)
    if new != getattr(engine, "_vp_stats_shown", None):
        engine._vp_stats_shown = new
        engine.update_stats(text, sub)


def _submit_jobs(engine, worker, framebuffer, jobs, has_camera):
    """Forward exporter jobs to the session worker, pacing scene edits.

    Every applied edit resets the film at the next frame boundary, and
    the film stays empty until the first preview pass lands (~20-80 ms).
    Submitting edits faster than that (a camera orbit or object drag
    fires one per draw, ~16 ms) leaves the film perpetually empty - the
    viewport renders black for the entire drag. While a reset is still
    waiting for content, edits are deferred (newest wins) and flushed
    once the film has a frame again, so the effective edit rate adapts
    to scene speed. Deferral is bounded by the pending deadline, so a
    starved film (paused session, empty scene) still releases the job.
    """
    # Sparse fast passes for the whole interaction burst - also while the
    # edit sits deferred behind a pending reset, so that reset resolves
    # faster and the deferred edit lands sooner.
    pixels = 0
    if framebuffer is not None:
        pixels = framebuffer._width * framebuffer._height
    elif getattr(engine, "last_viewport_size", None):
        pixels = engine.last_viewport_size[0] * engine.last_viewport_size[1]
    worker.submit_resolution_reduction(_dyn_res_value(pixels))
    _submit_film_scale(engine, worker, _interaction_film_scale(engine))
    engine._dyn_res_until = time() + _DYN_RES_TAIL_S
    engine._dyn_res_active = True
    # Exporter jobs are incremental deltas, not complete snapshots. Keep
    # independent changes in order, including when a new edit arrives on
    # the first frame after the hold expires (before view_draw flushes it).
    deferred = getattr(engine, "_deferred_edit_jobs", None)
    if deferred is not None:
        old_jobs, old_camera = deferred
        jobs = old_jobs + jobs
        has_camera = has_camera or old_camera
        engine._deferred_edit_jobs = None
    if (
        framebuffer is not None
        and framebuffer._pending_reset
        and time() < framebuffer._pending_reset_deadline
    ):
        engine._deferred_edit_jobs = (jobs, has_camera)
        return
    for kind, payload in jobs:
        if kind == "edit":
            worker.submit_edit(payload)
        elif kind == "parse":
            worker.submit_parse(payload)
    # The edit resumes a paused session on the worker: re-anchor the
    # halt timer so the resumed render isn't instantly re-paused when
    # halt_time already elapsed (paused-lockup / black viewport).
    engine.viewport_start_time = time()
    if framebuffer is not None:
        # Film was reset by the edit: hold the last frame until the new
        # render has produced visible samples (no black flash on orbit).
        # Camera moves get a shorter hold: the old viewpoint is wrong.
        framebuffer.begin_reset(
            FrameBuffer.HOLD_LAST_FRAME_CAMERA_S if has_camera else None,
            engine=engine,
        )
        framebuffer.reset_denoiser()


def _locked_session_call(engine, fn, *args):
    """Call ``fn(*args)`` while holding the worker's session_lock.

    Non-blocking: returns _LOCK_BUSY when the worker is mid-mutation
    (scene edit / Stop / Parse), so view_draw skips the call this frame
    instead of freezing the UI behind a full tile pass. Serializing every
    session call matters for correctness too: an unsynchronized read
    while the worker stops the session can crash Blender (the Solid ->
    Rendered teardown race).
    """
    worker = getattr(engine, "session_worker", None)
    lock = getattr(worker, "session_lock", None) if worker else None
    if lock is None:
        return fn(*args)
    if not lock.acquire(blocking=False):
        return _LOCK_BUSY
    try:
        return fn(*args)
    finally:
        lock.release()


def _drain_worker_error(engine):
    """Surface async worker failures to the user (error log + stats).

    Start/config failures are persistent (bad config, missing kernels):
    latch them so the viewport stops retrying and shows the error
    instead of silently looping. Edit/parse failures already caused the
    worker to drop the session - the next view_update re-exports.
    """
    worker = getattr(engine, "session_worker", None)
    if worker is None:
        return
    err = worker.pop_error()
    if err is None:
        return
    kind, error = err
    SuperLuxCoreErrorLog.add_error(error)
    engine.update_stats("Error: ", str(error))
    if kind in ("start", "config"):
        engine.viewport_fatal_error = str(error)


def force_session_restart(engine):
    """
    https://github.com/LuxCoreRender/BlendLuxCore/issues/577
    Mutating the RenderConfig of a running session leaks (every stopped
    session kept its copy of the scene) and used to crash. The worker
    stops the session off-thread; the next view_update() re-exports.
    """
    engine._deferred_edit_jobs = None
    if getattr(engine, "session_worker", None) is not None:
        engine.session_worker.submit_stop()
    elif engine.session is not None:
        # No worker (final render / preview): stop directly.
        engine.session.Stop()
    # Drop the main-thread reference so the stopped session's scene copy
    # is freed instead of accumulating until the next GC run.
    engine.session = None


def view_update(engine, context, depsgraph, changes=None):
    worker = _worker(engine, context)
    _drain_worker_error(engine)

    if worker.is_starting or engine.viewport_fatal_error:
        # Prevent deadlock: a start job is in flight (or failed
        # persistently) - depsgraph updates accumulate meanwhile and are
        # consumed by the first get_changes() after the session lands.
        return

    SuperLuxCoreErrorLog.clear(force_ui_update=False)

    if engine.session is None:
        # A fresh start clears any earlier fatal error (recovery beats a
        # permanently dead viewport; genuinely fatal errors reappear).
        engine.viewport_fatal_error = None
        engine.kernel_check_cache = None
        # A fresh session always starts at the configured film size;
        # forget any interaction downscale from the previous session
        engine._film_scale = 1
        if not engine.viewport_starting_message_shown:
            # Let one engine.view_draw() happen so it shows a message in the UI
            return

        if not engine.is_first_viewport_start:
            filmsize = utils.calc_filmsize(depsgraph.scene_eval, context)
            was_resized = engine.last_viewport_size != filmsize
            engine.last_viewport_size = filmsize

            if was_resized:
                engine.time_of_last_viewport_resize = time()
                return
            elif (
                time() - engine.time_of_last_viewport_resize
                < engine.VIEWPORT_RESIZE_TIMEOUT
            ):
                # Don't re-export the session before the timeout is done, to
                # prevent constant re-exports while resizing
                return
        else:
            display_superluxcore_logs = get_addon_preferences(
                context
            ).display_superluxcore_logs
            if display_superluxcore_logs:
                pysuperluxcore.SetLogHandler(SuperLuxCoreLog.add)
            else:
                pysuperluxcore.SetLogHandler(SuperLuxCoreLog.silent)

        try:
            print("=" * 50)
            print("[Engine/Viewport] New session")
            engine.exporter = export.Exporter()
            engine.viewport_phase = "Exporting scene"
            engine.is_first_viewport_start = False
            engine.last_viewport_size = utils.calc_filmsize(
                depsgraph.scene_eval, context
            )
            # Scene export needs the depsgraph: it has to stay on the main
            # thread. Everything from RenderConfig onward (kernel compile,
            # session start) runs on the worker so the UI never stalls.
            result = engine.exporter.export_scene(
                depsgraph, context, engine=engine
            )
            if result is not None:
                superluxcore_scene, config_props = result
                engine.viewport_phase = ""
                try:
                    engine._engine_type = config_props.Get(
                        "renderengine.type"
                    ).GetString()
                except Exception:
                    engine._engine_type = ""
                if _dlss_interaction_active(engine):
                    render_props = pysuperluxcore.Properties()
                    render_props.Set(config_props)
                    rw, rh = _dlss_render_size(engine, *engine.last_viewport_size)
                    render_props.Set(pysuperluxcore.Property('film.width', rw))
                    render_props.Set(pysuperluxcore.Property('film.height', rh))
                    config_props = render_props
                worker.submit_start(superluxcore_scene, config_props)
        except Exception as error:
            engine.session = None
            # Reset the exporter to invalidate all caches
            engine.exporter = None
            engine.viewport_fatal_error = str(error)

            engine.update_stats("Error: ", str(error))
            SuperLuxCoreErrorLog.add_error(error)

            import traceback

            traceback.print_exc()
        return

    changes = engine.exporter.get_changes(depsgraph, context, changes)

    if not changes:
        return

    # Config changes restart the session on the *reused* SuperLuxCore scene -
    # no scene re-export. Runs on the worker; the framebuffer keeps the
    # last frame until the new session produces samples (begin_reset).
    if changes & export.Change.CONFIG:
        paired = _submit_config_update(
            engine, worker, depsgraph.scene_eval, context, depsgraph, changes)
        if paired is None:
            engine.tag_redraw()
            return
        changes &= ~export.Change.CONFIG
        if paired:
            changes &= ~(export.Change.REQUIRES_SCENE_EDIT | export.Change.REQUIRES_SESSION_PARSE)
        if engine.framebuffer:
            engine.framebuffer.begin_reset(
                FrameBuffer.HOLD_LAST_FRAME_CAMERA_S if paired else None,
                engine=engine)
            engine.framebuffer.reset_denoiser()

    if changes & (
        export.Change.REQUIRES_SCENE_EDIT
        | export.Change.REQUIRES_SESSION_PARSE
    ):
        try:
            jobs = engine.exporter.update(depsgraph, context, changes)
        except Exception as error:
            # A half-recorded edit must not be replayed; rebuild the
            # scene from scratch instead.
            SuperLuxCoreErrorLog.add_error(error)
            import traceback

            traceback.print_exc()
            force_session_restart(engine)
            return
        _submit_jobs(
            engine, worker, engine.framebuffer, jobs,
            has_camera=bool(changes & export.Change.CAMERA),
        )


def _schedule_startup_redraw(engine):
    """Poll progress without repainting an unchanged preparation phase.

    A timer can observe worker progress while the window stays idle. Only a
    changed phase/progress schedules a draw; publication has its own immediate
    redraw. The weak reference lets a closed viewport retire during a build.
    """
    if getattr(engine, "_startup_redraw_pending", False):
        return
    import weakref
    try:
        engine_ref = weakref.ref(engine)
        repeat = True
    except TypeError:
        # Non-RNA test/legacy wrappers may not support weak references. Keep
        # such a wrapper for only one short callback, never a repeating loop.
        engine_ref = lambda: engine
        repeat = False
    worker = getattr(engine, "session_worker", None)
    last = [(getattr(worker, "phase", ""), getattr(worker, "progress", None))]
    engine._startup_redraw_pending = True

    def redraw():
        target = engine_ref()
        if target is None:
            return None
        try:
            worker = getattr(target, "session_worker", None)
            if worker is None or not worker.is_starting:
                target._startup_redraw_pending = False
                return None
            state = (getattr(worker, "phase", ""),
                     getattr(worker, "progress", None))
            if state != last[0]:
                last[0] = state
                target.tag_redraw()
            if repeat:
                return 0.1
            target._startup_redraw_pending = False
        except ReferenceError:
            # The RNA struct can be retired independently of this wrapper.
            pass
        return None

    bpy.app.timers.register(redraw, first_interval=0.1)


def view_draw(engine, context, depsgraph):
    scene = depsgraph.scene_eval
    worker = _worker(engine, context)
    _drain_worker_error(engine)

    if worker.is_starting:
        # Show what the worker is doing (export > config > kernels >
        # session start) instead of a frozen window.
        phase = worker.phase or getattr(engine, "viewport_phase", "")
        _set_stats(engine, "Starting viewport render", phase)
        if engine.framebuffer:
            engine.framebuffer.draw(context, scene)
        _schedule_startup_redraw(engine)
        return

    if engine.viewport_fatal_error:
        _set_stats(engine, "Error:", engine.viewport_fatal_error)
        engine.tag_redraw()
        return

    light_count = getattr(worker, "scene_light_count", None)
    if engine.session is not None and light_count is not None:
        token = (id(engine.session), light_count)
        if getattr(engine, "_reported_scene_light_count", None) != token:
            engine._reported_scene_light_count = token
            stats = getattr(getattr(engine, "exporter", None), "stats", None)
            if stats:
                stats.light_count.value = light_count
            if light_count > 1000:
                SuperLuxCoreErrorLog.add_warning(
                    f"The scene contains a lot of light sources ({light_count}), "
                    "performance might suffer "
                    "(each triangle of a meshlight counts as a separate light)")

    if engine.session is None:
        config = scene.superluxcore.config
        definitions = {}
        try:
            superluxcore_engine, _ = convert_viewport_engine(
                context, scene, definitions, config
            )
        except Exception:
            # A config failure must not take down view_draw — the real
            # export in view_update reports the error via the error log.
            superluxcore_engine = "RTPATHCPU"
        message = ""

        if superluxcore_engine.endswith("OCL"):
            # The dummy Scene/RenderConfig below costs a full kernel-config
            # build per redraw; HasCachedKernels() only changes when the
            # config does, so cache it on the engine for the sessionless
            # phase (cleared on every fresh start above).
            if engine.kernel_check_cache is None:
                # Create dummy renderconfig to check if we have to compile OpenCL kernels
                superluxcore_scene = pysuperluxcore.Scene()
                definitions = {
                    "scene.camera.type": "perspective",
                }
                superluxcore_scene.Parse(utils.luxutils.create_props("", definitions))

                devices = scene.superluxcore.devices
                definitions = {
                    "renderengine.type": "RTPATHOCL",
                    "sampler.type": "TILEPATHSAMPLER",
                    "scene.epsilon.min": config.min_epsilon,
                    "scene.epsilon.max": config.max_epsilon,
                    "opencl.devices.select": devices.devices_to_selection_string(),
                }
                config_props = utils.luxutils.create_props("", definitions)
                renderconfig = pysuperluxcore.RenderConfig(config_props, superluxcore_scene)
                engine.kernel_check_cache = (
                    renderconfig.HasCachedKernels(),
                    utils.get_addon_preferences(context).gpu_backend,
                )
            has_cached_kernels, gpu_backend = engine.kernel_check_cache
            if not has_cached_kernels:
                message = (
                    f"Compiling {gpu_backend} kernels ("
                    "((just once, usually takes 15-30 minutes)"
                )

        phase = worker.phase if worker is not None else ""
        _set_stats(
            engine,
            "Starting viewport render",
            phase or getattr(engine, "viewport_phase", "") or message,
        )
        engine.viewport_starting_message_shown = True
        # Keep showing the previous session's last frame while the new
        # session exports/starts instead of flashing black.
        if engine.framebuffer:
            engine.framebuffer.draw(context, scene)
        engine.tag_update()
        engine.tag_redraw()
        return

    if not engine.framebuffer or engine.framebuffer.needs_replacement(
        context, scene, engine
    ):
        engine.framebuffer = FrameBuffer._transition_from(
            engine.framebuffer, engine, context, scene
        )

    framebuffer = engine.framebuffer

    # Check for changes because some actions in Blender (e.g. moving the viewport
    # camera) do not trigger a view_update() call, but only a view_draw() call.
    changes = engine.exporter.get_viewport_changes(depsgraph, context)

    if changes & export.Change.CONFIG:
        # Config-only change detected during draw (e.g. viewport resize):
        # the worker rebuilds the RenderConfig on the existing scene. The
        # framebuffer keeps the last image on screen (begin_reset), so the
        # user sees the resized old frame instead of a black flash.
        paired = _submit_config_update(
            engine, worker, scene, context, depsgraph, changes)
        if paired is None:
            engine.tag_redraw()
            return
        changes &= ~export.Change.CONFIG
        if paired:
            changes &= ~(export.Change.REQUIRES_SCENE_EDIT | export.Change.REQUIRES_SESSION_PARSE)
        engine.viewport_start_time = time()
        framebuffer.begin_reset(
            FrameBuffer.HOLD_LAST_FRAME_CAMERA_S if paired else None,
            engine=engine)
        framebuffer.reset_denoiser()
        if not changes:
            engine.tag_redraw()
            framebuffer.draw(context, scene)
            return

    if changes & (export.Change.CAMERA | export.Change.MATERIAL):
        # Only update in view_draw if it is a camera/material update,
        # for everything else we call view_update(). The ops are replayed
        # by the worker inside one scene-edit block.
        try:
            jobs = engine.exporter.update(depsgraph, context, changes)
        except Exception as error:
            SuperLuxCoreErrorLog.add_error(error)
            import traceback

            traceback.print_exc()
            force_session_restart(engine)
            engine.tag_redraw()
            return
        _submit_jobs(
            engine, worker, framebuffer, jobs,
            has_camera=bool(changes & export.Change.CAMERA),
        )
    elif changes:
        # Non-camera changes noticed in draw: let view_update handle them.
        engine.tag_update()

    # Snapshot the session: the worker may publish a new one (or None
    # during a restart) at any time; a stale-but-alive object degrades
    # gracefully to RuntimeError while engine.session itself may turn
    # into None and raise AttributeError mid-draw.
    session = engine.session

    # Flush a camera edit deferred while the film was still empty. The
    # pending reset clears when post-reset content lands (or on the
    # bounded deadline), so this fires as soon as the last edit produced
    # a frame - the effective camera-edit rate adapts to scene speed.
    deferred = getattr(engine, "_deferred_edit_jobs", None)
    if deferred is not None:
        still_waiting = (
            framebuffer._pending_reset
            and time() < framebuffer._pending_reset_deadline
        )
        if still_waiting:
            # Keep draws flowing until the deferred edit can fire: while
            # paused, nothing tags a redraw and the final camera position
            # would never be submitted.
            engine.tag_redraw()
        else:
            engine._deferred_edit_jobs = None
            deferred_jobs, deferred_has_camera = deferred
            for kind, payload in deferred_jobs:
                if kind == "edit":
                    worker.submit_edit(payload)
                elif kind == "parse":
                    worker.submit_parse(payload)
            # Deferred edit finally firing: still interacting.
            _pixels = 0
            if framebuffer is not None:
                _pixels = framebuffer._width * framebuffer._height
            worker.submit_resolution_reduction(_dyn_res_value(_pixels))
            _submit_film_scale(
                engine, worker, _interaction_film_scale(engine)
            )
            engine._dyn_res_until = time() + _DYN_RES_TAIL_S
            engine._dyn_res_active = True
            engine.viewport_start_time = time()
            framebuffer.begin_reset(
                FrameBuffer.HOLD_LAST_FRAME_CAMERA_S
                if deferred_has_camera
                else None,
                engine=engine,
            )
            framebuffer.reset_denoiser()

    # Interaction settled: restore the configured (dense) reduction so
    # steady-state passes converge at full quality.
    _restore_interaction(engine, worker, framebuffer)

    if utils.in_material_shading_mode(context):
        paused = (
            session is not None
            and _locked_session_call(engine, session.IsInPause) is True
        )
        if not paused:
            # Non-blocking: draw whatever the film holds instead of waiting
            # for a full frame (avoids UI freezes on session restarts)
            try:
                if session is not None:
                    framebuffer.update_async(session, engine)
            except Exception:
                pass
            _set_stats(engine, "", "")

            samples = 0
            if session is not None:
                try:
                    stats = _locked_session_call(engine, session.GetStats)
                    # A light-only pass cannot complete a material preview.
                    samples = stats.Get("stats.renderengine.pass.eye").GetInt()
                except Exception:
                    pass

            if samples >= 5:
                _locked_session_call(engine, session.Pause)
            else:
                engine.tag_redraw()
        framebuffer.draw(context, scene)
        return

    # Check if we need to pause the viewport render
    # (note: the SuperLuxCore stat "stats.renderengine.time" is not reliable here)
    rendered_time = time() - engine.viewport_start_time
    halt_time = scene.superluxcore.viewport.halt_time
    status_message = worker.phase if worker is not None else ""
    vp = scene.superluxcore.viewport
    use_dlss = vp.use_denoiser and vp.denoiser == "DLSS"
    dlss_handled = False
    if use_dlss and worker is not None:
        dlss_handled = framebuffer.consume_dlss_result(engine, worker, session)
        status_message = worker.dlss_status or "DLSS preparing; ordinary render active"
    else:
        framebuffer._dlss_owner = None

    # Selection alone never proves a neural image was produced. Until a
    # current-session DLSS result owns the display, retain ordinary OIDN.
    use_oidn = vp.get_denoiser(context) == "OIDN" or (use_dlss and not dlss_handled)
    if use_dlss and not dlss_handled:
        status_message += "; OIDN fallback"

    if rendered_time > halt_time:
        # Put in pause... (non-blocking: if the worker is mid-edit the
        # pause is simply retried on the next draw instead of freezing)
        paused = (
            session is not None
            and _locked_session_call(engine, session.IsInPause) is True
        )
        if not paused and session is not None:
            print("[Engine/Viewport] Pausing session")
            _locked_session_call(engine, session.Pause)
        status_message = status_message or "(Paused)"

        # ...and denoise
        if use_dlss and dlss_handled:
            if not dlss_handled and session is not None:
                framebuffer.update_async(session, engine)
                reader = framebuffer._read_thread
                if reader is not None and reader.is_alive():
                    engine.tag_redraw()
            status_message = "(Paused) " + status_message
        elif use_oidn and not framebuffer.denoised:
            # The background worker computes OIDN and reads its pixels; upload/draw
            # happens here on the main thread (GL-safe).
            if framebuffer.consume_denoise_result(engine):
                pass  # fresh denoised image is already uploaded
            elif not framebuffer.is_denoiser_active():
                print("Starting OIDN denoiser...")
                framebuffer.start_denoiser(engine, session)
            status_message = "(Paused, OIDN Denoiser Working ...)"
            engine.tag_redraw()
        else:
            if use_oidn:
                status_message = "(Paused, OIDN Denoiser Done)"
            else:
                status_message = "(Paused)"

    else:
        # Not in pause yet, keep drawing.
        # WaitNewFrame() blocks the UI thread until the render session has
        # produced a full frame - after a config change or session restart
        # this can take a noticeable moment during which the viewport would
        # freeze. Instead of blocking, we render what we already have and let
        # the next view_draw() pick up the new frame (it is called again
        # because of tag_redraw() below).
        try:
            if session is not None:
                vp = scene.superluxcore.viewport
                interactive = (
                    vp.denoise_interactive
                    and use_oidn
                    and not utils.in_material_shading_mode(context)
                )
                handled = dlss_handled or (
                    framebuffer.interactive_denoise_tick(
                        engine, vp.min_samples
                    )
                    if interactive
                    else False
                )
                if not handled:
                    # Async film readback: the device-queue drain runs on a
                    # worker thread, the finished frame is consumed here.
                    framebuffer.update_async(session, engine)
        except RuntimeError:
            # Session not started yet / no film available: keep showing the
            # last framebuffer contents instead of flashing black
            pass
        engine.tag_redraw()

    framebuffer.draw(context, scene)

    # Show formatted statistics in Blender UI
    try:
        if session is None:
            raise RuntimeError("no session")
        config = _locked_session_call(engine, session.GetRenderConfig)
        stats = _locked_session_call(engine, session.GetStats)
        if config is _LOCK_BUSY or stats is _LOCK_BUSY:
            raise RuntimeError("session busy")
        pretty_stats = utils_render.get_pretty_stats(
            config, stats, scene, context
        )
        engine._vp_stats_cache = (pretty_stats, status_message)
    except Exception:
        # Session being swapped by the worker mid-draw: keep the last
        # real stats instead of flashing a phase/blank line (the stats
        # text flickers badly if it alternates every frame).
        cached = getattr(engine, "_vp_stats_cache", None)
        pretty_stats = cached[0] if cached else (
            worker.phase if worker is not None else ""
        )
    _set_stats(engine, pretty_stats, status_message)
