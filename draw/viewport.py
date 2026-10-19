_needs_reload = "bpy" in locals()

from ..export import blender_settings
import bpy
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix

import threading
import time
import os
import numpy as np
import tempfile
from shutil import which
from os.path import dirname
import pysuperluxcore
from .. import utils
from ..utils import pfm

if _needs_reload:
    import importlib

    importlib.reload(pysuperluxcore)
    importlib.reload(utils)


def _session_lock(engine):
    """The lock the session worker holds while mutating the live session
    (scene edits, Parse, Stop). Film reads take it so a film reset in
    EndSceneEdit can never tear a GetOutputFloat in half. None without a
    worker (final render / preview paths need no guard)."""
    worker = getattr(engine, "session_worker", None)
    return getattr(worker, "session_lock", None) if worker else None


def _mutation_seq(engine):
    """Worker-side counter bumped after every applied session mutation.

    A film read records it at kickoff; if it moved by consume time the
    read predates the latest edit and must not satisfy a pending reset
    (its pixels are the previous edit's film)."""
    worker = getattr(engine, "session_worker", None)
    return getattr(worker, "mutation_seq", 0) if worker else 0


def _fetch_pixels(output_type, transparent,
                  superluxcore_session, execute_imagepipeline, lock=None,
                  seq_probe=None, snapshot_box=None):
    """Blocking film readback + imagepipeline. Runs the device-queue
    drain; with the GIL released by pysuperluxcore this is safe to call on a
    worker thread. ``lock`` (the session worker's session_lock) keeps
    the read from racing a scene edit / session stop on the worker.

    Film dimensions are read from the live film while holding the lock:
    interaction downscaling resizes the film via Parse() without a
    framebuffer rebuild, so the read must always match the live dims.

    ``seq_probe`` (optional callable) is invoked while still holding the
    lock, right after the fetch: sampling the worker's mutation_seq here
    labels the returned pixels with the exact session generation that
    produced them - a kickoff-time sample could mislabel post-edit
    pixels as pre-edit when the edit lands in the kickoff→lock window.

    Module-level (not a FrameBuffer method) so read threads never keep a
    FrameBuffer alive: GL objects must die on the main thread."""
    bufferdepth = 4 if transparent else 3

    def read():
        if execute_imagepipeline:
            # UpdateFilm can drain the device queue. Keep it beside the
            # readback on the background worker, never on view_draw().
            superluxcore_session.UpdateStats()
        film = superluxcore_session.GetFilm()
        w, h = film.GetWidth(), film.GetHeight()
        # Zeros, not np.empty: GetOutputFloat early-returns without touching
        # the buffer when the channel does not exist (e.g. a restarted film
        # without imagepipelines). Garbage here would bypass the empty-film
        # gate in _accept_pixels and upload as a white viewport.
        data = np.zeros(w * h * bufferdepth, dtype=np.float32)
        if hasattr(film, "GetOutputFloatSnapshot"):
            metadata = film.GetOutputFloatSnapshot(
                output_type, data, 0, execute_imagepipeline
            )
            w = metadata.Get("snapshot.width").GetInt()
            h = metadata.Get("snapshot.height").GetInt()
            data = data[:w * h * bufferdepth]
            if snapshot_box is not None:
                snapshot_box["snapshot"] = {
                    "ready": metadata.Get("snapshot.ready").GetBool(),
                    "copied": metadata.Get("snapshot.copied").GetBool(),
                    "camera_supported": metadata.Get("snapshot.camera.supported").GetBool(),
                    "requested": metadata.Get("snapshot.camera.requested").GetUnsignedLongLong(),
                    "applied": metadata.Get("snapshot.camera.applied").GetUnsignedLongLong(),
                    "session_token": id(superluxcore_session),
                    "metadata": metadata,
                }
        else:
            film.GetOutputFloat(output_type, data, 0, execute_imagepipeline)
        return data, w, h

    seq = None
    if lock is None:
        data, width, height = read()
        seq = seq_probe() if seq_probe else None
    else:
        with lock:
            data, width, height = read()
            seq = seq_probe() if seq_probe else None
    # The gpu buffer uses 16-bit float. Values >= 65520 get cast to
    # infinity, leading to a black viewport.
    data[data > 65519] = 65519
    return data, width, height, seq


def run_denoiser(session, lock, box, output_type, transparent, seq_probe):
    """Denoiser worker (background thread).

    OIDN and its film readback run here. Everything touching GL or Blender
    (framebuffer.update/draw, tag_redraw) must happen on the main thread,
    so the worker only raises a flag that view_draw() consumes. (Calling
    .run() instead of .start() here used to freeze the whole UI for the
    full OIDN run on every pause.)

    The FrameBuffer itself is deliberately NOT an argument: a worker
    holding it would keep its GL objects alive past engine teardown and
    free them off the main thread.
    """
    try:
        if box.get("cancelled"):
            return
        def denoise_and_read():
            if box.get("cancelled"):
                return
            session.UpdateStats()
            session.GetFilm().ApplyOIDN(0)
            if not box.get("cancelled"):
                box["data"], box["width"], box["height"], box["mut_seq"] = _fetch_pixels(
                    output_type, transparent, session, False, seq_probe=seq_probe,
                    snapshot_box=box,
                )

        if lock is None:
            denoise_and_read()
        else:
            with lock:
                denoise_and_read()
    except Exception:
        import traceback

        traceback.print_exc()
    finally:
        # Always signal completion; a cancelled/failed job has no pixels.
        box["done"] = True


class FrameBuffer:
    """FrameBuffer used for viewport render"""

    def __init__(self, engine, context, scene):
        filmsize = utils.calc_filmsize(scene, context)
        # Bootstrap from Blender dimensions. The background read supplies
        # the exact live size to _accept_pixels(), including dynamic scale.
        # Native width/height getters take filmMutex and can block the UI
        # behind a GPU drain or OIDN even though they look like cheap reads.
        self._width, self._height = filmsize
        self._border = utils.calc_blender_border(scene, context)
        self._view_rect = self._calc_view_rect(context, scene, self._border)
        self._pixel_size = int(scene.superluxcore.viewport.pixel_size)

        self._transparent = self._initialize_transparency(scene, context)
        bufferdepth = 4 if self._transparent else 3
        self._output_type = (
            pysuperluxcore.FilmOutputType.RGBA_IMAGEPIPELINE
            if self._transparent
            else pysuperluxcore.FilmOutputType.RGB_IMAGEPIPELINE
        )

        # Explicit zero init: an uninitialized FLOAT buffer reads as
        # garbage (often white) when drawn before the first film upload.
        self.buffer = gpu.types.Buffer(
            "FLOAT",
            [self._width * self._height * bufferdepth],
            np.zeros(
                self._width * self._height * bufferdepth,
                dtype=np.float32,
            ),
        )
        self._init_opengl()

        # Denoiser
        self.denoised = False  # Set to true after denoising
        self._denoiser_thread = None
        self._denoise_box = None
        self._denoise_session = None
        self._texture = None
        self._pixels_dirty = True
        self._last_update = 0.0
        self._last_pixels = None  # Last rendered pixels (h, w, depth), used for resize transitions
        self._from_transition = False  # True while showing a resampled frame from before a restart
        # Hold-last-frame: after a scene/camera edit the film is reset to
        # black; uploading that empty film flashes the viewport black. While
        # _pending_reset is set, updates only swap in once real samples exist.
        self._pending_reset = True
        self._pending_reset_deadline = 0.0
        self._pending_burst_deadline = 0.0
        # Worker mutation counter value at the moment begin_reset() ran:
        # a readback with box.mut_seq > this provably ran AFTER the edit
        # landed (session_lock makes reads/edits mutually exclusive).
        # Asynchronous RT camera application is identified separately by
        # the native snapshot epoch; submission alone is not proof of it.
        self._reset_mut_seq = 0
        self._shown_mut_seq = 0
        self._snapshot_session = None
        self._snapshot_epoch = 0
        self._last_snapshot = None
        # Async readback: GetOutputFloat (film download + imagepipeline) runs
        # on a worker thread so the device-queue drain doesn't stall the UI.
        self._read_thread = None
        self._read_box = None
        self._read_session = None
        # While recent edits are still producing fresh frames, read the
        # film at a higher cadence so the first visible frame lands fast.
        self._fast_read_until = 0.0
        # Interactive denoise: while True, denoised frames own the display and
        # raw film updates are suppressed (avoids raw/denoised alternation).
        self._interactive_denoise = False
        self._last_interactive_denoise = 0.0
        self._dlss_owner = None
        self._dlss_last_frame_id = 0
        self._dlss_last_scene_epoch = 0
        self._dlss_last_source_size = None

    @classmethod
    def _transition_from(cls, old_framebuffer, engine, context, scene):
        """Create a replacement FrameBuffer that starts out showing the
        previous framebuffer's last image, resampled to the new size.

        This keeps the viewport from flashing black during resizes: the
        previous image is stretched over the new area while the render
        session restarts, then converges normally."""
        new_fb = cls(engine, context, scene)
        if (
            old_framebuffer is not None
            and getattr(old_framebuffer, "_last_pixels", None) is not None
            and new_fb._width > 0
            and new_fb._height > 0
        ):
            try:
                old_h, old_w = old_framebuffer._last_pixels.shape[:2]
                old_depth = old_framebuffer._last_pixels.shape[2]
                new_depth = 4 if new_fb._transparent else 3
                if old_depth == new_depth and old_h > 0 and old_w > 0:
                    # Nearest-neighbor resample of the last rendered frame
                    ys = (np.arange(new_fb._height) * old_h / new_fb._height).astype(np.intp)
                    xs = (np.arange(new_fb._width) * old_w / new_fb._width).astype(np.intp)
                    resampled = old_framebuffer._last_pixels[np.ix_(ys, xs)]
                    new_fb.buffer = gpu.types.Buffer(
                        "FLOAT",
                        [new_fb._width * new_fb._height * new_depth],
                        resampled.reshape(-1).astype(np.float32, copy=False),
                    )
                    new_fb._from_transition = True
                    # A second resize can arrive before any new film read.
                    # Carry the held pixels forward through that replacement.
                    new_fb._last_pixels = resampled
            except Exception:
                # Any failure here just falls back to the default (black) buffer
                pass
        return new_fb

    def _initialize_transparency(self, scene, context):
        if utils.is_valid_camera(
            scene.camera
        ) and not utils.in_material_shading_mode(context):
            return blender_settings.transparent_film(scene)
        return False

    def _init_opengl(self):
        x, y, w, h = self._view_rect
        position = [
            (x, y),
            (x + w, y),
            (x + w, y + h),
            (x, y + h),
            (x, y),
            (x + w, y + h),
        ]

        if getattr(self, "shader", None) is None:
            self.shader = gpu.shader.from_builtin("IMAGE")
        self.batch = batch_for_shader(
            self.shader,
            "TRIS",
            {
                "pos": position,
                "texCoord": [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0), (1, 1)],
            },
        )

    def __del__(self):
        # GL objects must be freed on the main thread. Guarded: addon
        # reload / GC can call this in odd contexts, and freeing a GPU
        # buffer off the main thread crashes Blender.
        if threading.current_thread() is threading.main_thread():
            try:
                del self.buffer
                self._texture = None
            except Exception:
                pass

    def needs_replacement(self, context, scene, engine=None):
        # Film size changes are handled by _accept_pixels() without
        # replacing the framebuffer (or discarding its pending read).
        # draw() independently reanchors the quad to the current region.
        # Do not query the live film here: its getters acquire filmMutex.
        # Use the same policy as construction: material preview is opaque
        # even when the final-render film is transparent.
        if self._transparent != self._initialize_transparency(scene, context):
            return True
        if self._border != utils.calc_blender_border(scene, context):
            return True
        if self._pixel_size != int(scene.superluxcore.viewport.pixel_size):
            return True
        return False

    def _calc_view_rect(self, context, scene, border):
        """On-screen rect (region px) the film covers.

        Camera view + border: the film shows the camera image's border
        subset, drawn inside the camera frame as Blender positions it
        (view3d_camera_border) - the quad scales/pans with camzoom and
        view offset without any re-render. Everything else: the film
        covers the region's border rect exactly.
        """
        region_w = context.region.width
        region_h = context.region.height
        bmin_x, bmax_x, bmin_y, bmax_y = border

        if (
            context.region_data.view_perspective == "CAMERA"
            and scene.render.use_border
            and utils.is_valid_camera(scene.camera)
        ):
            frame_x, frame_y, frame_w, frame_h = (
                utils.calc_camera_frame_rect(scene, context)
            )
            return (
                frame_x + bmin_x * frame_w,
                frame_y + bmin_y * frame_h,
                frame_w * (bmax_x - bmin_x),
                frame_h * (bmax_y - bmin_y),
            )
        return (
            region_w * bmin_x,
            region_h * bmin_y,
            region_w * (bmax_x - bmin_x),
            region_h * (bmax_y - bmin_y),
        )

    def sync_view_transform(self, context, scene):
        """Re-anchor the draw quad to the current camera-view pan/zoom.

        Cheap: only rebuilds the 6-vertex batch when the rect moved, so
        camzoom/camdx changes track instantly with no session restart."""
        rect = self._calc_view_rect(context, scene, self._border)
        if rect != self._view_rect:
            self._view_rect = rect
            self._init_opengl()

    def start_denoiser(self, engine, session=None):
        """Kick off a background OIDN run.

        ``session`` pins the denoiser to the session the caller just
        paused - engine.session may be swapped to a new session (or None)
        by the worker while the denoiser runs."""
        if self.is_denoiser_active():
            return False
        self._denoise_box = {"done": False, "cancelled": False}
        sess = session if session is not None else engine.session
        self._denoise_session = sess
        worker = getattr(engine, "session_worker", None)
        self._denoiser_thread = threading.Thread(
            target=run_denoiser,
            args=(sess, _session_lock(engine), self._denoise_box,
                  self._output_type, self._transparent,
                  lambda: getattr(worker, "mutation_seq", 0)),
            daemon=True,
            name="SuperLuxCoreViewportDenoise",
        )
        self._denoiser_thread.start()
        return True

    def is_denoiser_active(self):
        return self._denoiser_thread and self._denoiser_thread.is_alive()

    def reset_denoiser(self):
        self.denoised = False
        if self._denoise_box is not None:
            self._denoise_box["cancelled"] = True
        # Keep tracking a running worker until it exits. New work is
        # bounded to one thread, without joining on Blender's UI thread.
        self._denoise_session = None
        self._denoise_box = None
        if not self.is_denoiser_active():
            self._denoiser_thread = None
        self._interactive_denoise = False

    # Max time to keep showing the previous frame after a film reset before
    # falling back to whatever the (possibly still-empty) film holds.
    HOLD_LAST_FRAME_MAX_S = 0.5
    # Same for camera moves: the old viewpoint is *wrong*, so bound the
    # stale display tighter (ghosting) - new samples normally land faster.
    HOLD_LAST_FRAME_CAMERA_S = 0.3
    # Absolute bound on stale-frame holding across a burst of resets.
    # Past it, whatever the film has (even nothing) is displayed - a
    # sustained orbit on a scene too heavy for the preview pass must
    # not freeze the view forever.
    PENDING_BURST_MAX_S = 1.0
    # Min interval between interactive OIDN runs during rendering.
    INTERACTIVE_DENOISE_INTERVAL = 1.0
    # Fast film readback cadence right after an edit/first start, so the
    # first recognizable frame lands early (the normal 10 Hz would add up
    # to 100 ms of dead time on top of sampling).
    FAST_READ_WINDOW_S = 1.5
    FAST_READ_INTERVAL_S = 0.033

    def begin_reset(self, hold_s=None, engine=None):
        """Mark that the film was just cleared by a scene/camera edit.

        While set, update() keeps displaying the previous frame until the
        new render has produced visible samples. The hold slides with
        every reset (each edit gets its own empty-film window covered)
        but is bounded by a per-burst deadline so a film that never
        produces content can't pin the stale frame forever.
        """
        now = time.time()
        if not self._pending_reset:
            self._pending_burst_deadline = now + self.PENDING_BURST_MAX_S
        self._pending_reset = True
        if engine is not None:
            self._reset_mut_seq = _mutation_seq(engine)
        self._fast_read_until = now + self.FAST_READ_WINDOW_S
        hold = hold_s if hold_s is not None else self.HOLD_LAST_FRAME_MAX_S
        self._pending_reset_deadline = min(
            now + hold, self._pending_burst_deadline
        )
        # The denoised frames are stale now; raw updates resume until the
        # interactive denoiser re-engages.
        self._interactive_denoise = False
        self._dlss_owner = None

    def consume_dlss_result(self, engine, worker, session):
        """Main-thread upload of worker-postprocessed pixels; no native calls."""
        result = worker.take_dlss_result(session)
        token = (id(session), worker.mutation_seq)
        if result is not None:
            depth = 4 if self._transparent else 3
            if (not result.image_pipeline_applied or result.session is not engine.session or
                    result.mutation_sequence != worker.mutation_seq or
                    result.pixels.ndim != 3 or result.pixels.shape[2] != depth):
                self._dlss_owner = None
                return False
            height, width = result.pixels.shape[:2]
            if self._accept_pixels(result.pixels.reshape(-1), width, height,
                                   force=True, mut_seq=result.mutation_sequence):
                self._pending_reset = False
                self._from_transition = False
                self._dlss_owner = token
                self._dlss_last_frame_id = result.frame_id
                self._dlss_last_scene_epoch = result.scene_epoch
                self._dlss_last_source_size = getattr(result, 'source_size', (width, height))
        if worker.dlss_status != "DLSS Ray Reconstruction":
            self._dlss_owner = None
        return self._dlss_owner == token

    def consume_denoise_result(self, engine, final=True):
        """Apply a finished background denoise on the MAIN thread.

        Returns True when a fresh denoised image was uploaded (caller
        should tag_redraw). Stale workers (session replaced since) are
        ignored. final=False for interactive (mid-render) denoise results:
        the paused-state denoiser stays armed so a fresh denoise still runs
        on the converged film once rendering pauses.
        """
        box = self._denoise_box
        if box is None or not box.get("done"):
            return False
        self._denoise_box = None
        # The worker finished (result available): drop the thread reference
        # so interactive_denoise_tick() can tell "finished" from "died".
        self._denoiser_thread = None
        denoise_session = self._denoise_session
        if (denoise_session is None or denoise_session is not engine.session
                or box.get("cancelled") or box.get("data") is None
                or box.get("mut_seq") != _mutation_seq(engine)):
            return False
        # All native work finished on the worker under the session lock.
        # Upload the owned array; never acquire a session lock on the UI.
        if not self._accept_pixels(box["data"], box["width"], box["height"],
                                   force=True, mut_seq=box["mut_seq"],
                                   snapshot=box.get("snapshot")):
            return False
        if final:
            self.denoised = True
        return True

    def _accept_pixels(self, data, width, height, force=False, mut_seq=None,
                       snapshot=None):
        """Swap newly fetched pixels into the GPU buffer (main thread).

        ``mut_seq`` fences worker mutations; the optional native snapshot
        identifies the camera actually applied to the film. An earlier
        completed camera can refresh the display during sustained orbit,
        while only a current camera satisfies the pending reset.
        """
        now = time.time()
        if mut_seq is not None and mut_seq < self._shown_mut_seq:
            return False
        camera_current = True
        if snapshot is not None:
            # Native has not copied an unsampled/reset film. Even a forced
            # denoise upload must not present that untouched caller buffer.
            if not snapshot["ready"] or not snapshot["copied"]:
                return False
            if (snapshot["session_token"] == self._snapshot_session
                    and snapshot["applied"] < self._snapshot_epoch):
                return False
            # An older completed camera remains displayable during orbit,
            # with its own transforms, until a newer camera produces pixels.
            camera_current = (not snapshot["camera_supported"] or
                              snapshot["applied"] >= snapshot["requested"])
        if force and mut_seq is not None:
            self._shown_mut_seq = mut_seq
        if not force and mut_seq is not None:
            if mut_seq > self._shown_mut_seq:
                # First read of a new generation.
                post_reset = (
                    self._pending_reset and mut_seq > self._reset_mut_seq
                )
                if (
                    post_reset
                    and snapshot is None
                    and not np.any(data > 0.0)
                    and now < self._pending_reset_deadline
                ):
                    # Post-reset film still empty inside the hold window:
                    # keep the previous frame instead of flashing black.
                    return False
                self._shown_mut_seq = mut_seq
                if post_reset and camera_current:
                    self._pending_reset = False
        elif self._pending_reset and not force:
            # No generation info (sync path): legacy gate.
            if (snapshot is not None or np.any(data > 0.0)
                    or now >= self._pending_reset_deadline):
                if camera_current:
                    self._pending_reset = False
            else:
                return False
        if (snapshot is not None and camera_current and self._pending_reset
                and (mut_seq is None or mut_seq > self._reset_mut_seq)):
            self._pending_reset = False
        if self._interactive_denoise and not force:
            # Denoised frames own the display; raw uploads would alternate
            # with them and flicker.
            return False
        bufferdepth = 4 if self._transparent else 3
        # Track the live film dims: interaction downscaling resizes the
        # film in place via Parse(), so the framebuffer follows whatever
        # the fetch actually read instead of a rebuild
        if (width, height) != (self._width, self._height):
            self._width, self._height = width, height
            self._texture = None
        # Each completed read owns a fresh array which no worker mutates
        # after publication. Retain that owner through the view for resize
        # transitions; copying it again on the UI costs ~140 MB at 4K RGBA.
        self._last_pixels = data.reshape(height, width, bufferdepth)
        self.buffer = gpu.types.Buffer(
            "FLOAT", [width * height * bufferdepth], data
        )
        self._pixels_dirty = True
        if snapshot is not None:
            self._snapshot_session = snapshot["session_token"]
            self._snapshot_epoch = snapshot["applied"]
            self._last_snapshot = snapshot
        else:
            self._last_snapshot = None
        return True

    def update(
        self,
        superluxcore_session,
        engine=None,
        execute_imagepipeline=True,
        force=False,
    ):
        # Throttle film readback: GetOutputFloat() stalls the device
        # pipeline (a full-film download + imagepipeline run per draw) and
        # view_draw() runs at display rate. 10 Hz is plenty for a progressive
        # preview and keeps the GPU rendering instead of stalling. The
        # denoise path forces an immediate upload.
        now = time.time()
        if not force and now - self._last_update < 0.1:
            return False
        self._last_update = now
        lock = _session_lock(engine) if engine is not None else None
        # Non-blocking on the UI thread: a worker mid-edit would stall
        # the whole draw behind Begin/EndSceneEdit otherwise. The forced
        # (denoise upload) path must not skip though - it is the only
        # place the denoised film gets re-read, so it may wait.
        if lock is not None and not lock.acquire(blocking=force):
            return False
        try:
            # The probe runs while we still hold the lock, so mut_seq
            # labels the fetched pixels with their exact generation.
            snapshot_box = {}
            data, width, height, mut_seq = _fetch_pixels(
                self._output_type,
                self._transparent,
                superluxcore_session,
                execute_imagepipeline,
                None,  # already holding the lock
                seq_probe=lambda: (
                    _mutation_seq(engine) if engine is not None else None
                ),
                snapshot_box=snapshot_box,
            )
        finally:
            if lock is not None:
                lock.release()
        return self._accept_pixels(
            data, width, height, force, mut_seq=mut_seq,
            snapshot=snapshot_box.get("snapshot"),
        )

    def start_async_update(
        self, superluxcore_session, engine=None, execute_imagepipeline=True
    ):
        """Kick off a background film readback; the result lands in a box
        dict consumed by consume_async_update() on the main thread. No-op
        while a read is already in flight. The thread deliberately never
        touches ``self`` so the FrameBuffer can be torn down mid-read."""
        if self._read_thread is not None and self._read_thread.is_alive():
            return False
        box = {"done": False, "data": None, "mut_seq": None}
        self._read_box = box
        self._read_session = superluxcore_session
        self._last_update = time.time()
        worker = getattr(engine, "session_worker", None)
        lock = getattr(worker, "session_lock", None) if worker else None
        output_type, transparent = self._output_type, self._transparent

        def work():
            try:
                # The probe samples mutation_seq inside session_lock right
                # after the fetch, so box.mut_seq is the exact generation
                # of these pixels (never a pre-edit label on post-edit
                # pixels from the kickoff→lock window).
                box["data"], box["width"], box["height"], box["mut_seq"] = (
                    _fetch_pixels(
                        output_type, transparent,
                        superluxcore_session, execute_imagepipeline, lock,
                        seq_probe=lambda: getattr(worker, "mutation_seq", 0),
                        snapshot_box=box,
                    )
                )
            except Exception:
                import traceback

                traceback.print_exc()
            box["done"] = True

        self._read_thread = threading.Thread(
            target=work, daemon=True, name="SuperLuxCoreViewportReadback"
        )
        self._read_thread.start()
        return True

    def consume_async_update(self, superluxcore_session, engine=None):
        """Main thread: pick up a finished async readback. Returns True when
        a fresh frame was swapped into the buffer."""
        box = self._read_box
        if box is None or not box["done"]:
            return False
        self._read_box = None
        self._read_thread = None
        if self._read_session is not superluxcore_session or box["data"] is None:
            return False
        if engine is not None and box["mut_seq"] != _mutation_seq(engine):
            # An edit landed after this read. Keep the last image until a
            # read of the current film arrives instead of flashing backwards.
            return False
        return self._accept_pixels(
            box["data"], box["width"], box["height"], mut_seq=box["mut_seq"],
            snapshot=box.get("snapshot"),
        )

    def update_async(
        self, superluxcore_session, engine=None, execute_imagepipeline=True
    ):
        """Non-blocking readback driver for view_draw: consumes a finished
        read, otherwise starts a new one. Reads run at 20 Hz for a short
        window after each edit (fast first frame), then at 10 Hz."""
        if self.consume_async_update(superluxcore_session, engine):
            return True
        now = time.time()
        interval = (
            self.FAST_READ_INTERVAL_S
            if now < self._fast_read_until
            else 0.1
        )
        if now - self._last_update < interval:
            return False
        return self.start_async_update(
            superluxcore_session, engine, execute_imagepipeline
        )

    def interactive_denoise_tick(self, engine, min_samples):
        """Periodic OIDN while the render is still running (interactive
        denoise, Octane-style). Returns True when the denoise pipeline owns
        the display this frame (worker busy or a denoised frame just landed),
        False when the caller should fall back to raw film updates."""
        if self._pending_reset:
            return False
        # A finished worker uploads its denoised frame here (main thread).
        # final=False: mid-render results don't disarm the pause denoiser.
        if self.consume_denoise_result(engine, final=False):
            self._interactive_denoise = True
            self._last_interactive_denoise = time.time()
            return True
        if self.is_denoiser_active():
            return self._interactive_denoise
        if (
            self._interactive_denoise
            and self._denoiser_thread is not None
            and (
                self._denoise_box is None
                or not self._denoise_box.get("done")
            )
        ):
            # Last worker exited without producing a result: disarm so raw
            # updates resume instead of freezing on the last denoised frame.
            self._interactive_denoise = False
        if not self._interactive_denoise:
            # Not engaged yet: start once the film has some samples.
            session = engine.session
            if session is None:
                return False
            lock = _session_lock(engine)
            try:
                # Non-blocking: this runs on the UI thread; a worker
                # mid-edit would otherwise freeze the viewport draw.
                if lock is None:
                    stats = session.GetStats()
                elif lock.acquire(blocking=False):
                    try:
                        stats = session.GetStats()
                    finally:
                        lock.release()
                else:
                    return False
                # Light paths do not establish camera coverage. The native
                # eye counter also excludes inactive coarse RT tasks.
                pass_count = stats.Get("stats.renderengine.pass.eye").GetInt()
            except RuntimeError:
                return False
            if pass_count < max(1, min_samples):
                return False
        if (
            time.time() - self._last_interactive_denoise
            < self.INTERACTIVE_DENOISE_INTERVAL
        ):
            return self._interactive_denoise
        self.start_denoiser(engine)
        # Keep the current frame up until the first denoised result lands.
        return self._interactive_denoise

    def draw(self, context=None, scene=None):
        if context is not None and scene is not None:
            self.sync_view_transform(context, scene)
        # RR output is scene-linear HDR until the display shader applies the
        # view transform. Preserve its float32 precision at upload: half-float
        # rounding was visible in the original-scene framebuffer regression.
        high_precision = self._dlss_owner is not None
        # Blender exposes RGBA32F, but not RGB32F. Opaque RR results need
        # an explicit unit alpha for that texture layout.
        format = "RGBA32F" if high_precision else ("RGBA16F" if self._transparent else "RGB16F")
        # Re-create the GPU texture only when new pixels arrived; drawing
        # the same texture every frame churns VRAM for nothing (and the old
        # texture was never explicitly freed).
        if getattr(self, "_pixels_dirty", True) or getattr(self, "_texture", None) is None:
            texture_data = self.buffer
            if high_precision and not self._transparent:
                rgba = np.empty((self._height, self._width, 4), dtype=np.float32)
                rgba[:, :, :3] = self._last_pixels
                rgba[:, :, 3] = 1.0
                texture_data = gpu.types.Buffer("FLOAT", [rgba.size], rgba)
            self._texture = gpu.types.GPUTexture(
                size=(self._width, self._height),
                layers=0,
                is_cubemap=False,
                format=format,
                data=texture_data,
            )
            self._pixels_dirty = False
        self.shader.uniform_sampler("image", self._texture)
        # Blender's inherited UI projection includes a subpixel offset. It
        # interpolates bright film edges even for a matching 1:1 texture and
        # region. Own the region-pixel transform, then restore both matrices
        # so overlays and other engines retain the host's original state.
        _, _, region_w, region_h = gpu.state.viewport_get()
        projection = gpu.matrix.get_projection_matrix().copy()
        with gpu.matrix.push_pop():
            try:
                gpu.matrix.load_matrix(Matrix.Identity(4))
                gpu.matrix.load_projection_matrix(Matrix((
                    (2 / region_w, 0, 0, -1),
                    (0, 2 / region_h, 0, -1),
                    (0, 0, -1, 0),
                    (0, 0, 0, 1),
                )))
                self.batch.draw(self.shader)
            finally:
                gpu.matrix.load_projection_matrix(projection)
