_needs_reload = "bpy" in locals()

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

import threading
import time
import os
import numpy as np
import tempfile
from shutil import which
from os.path import dirname
import pyluxcore
from .. import utils
from ..utils import pfm

if _needs_reload:
    import importlib

    importlib.reload(pyluxcore)
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


def _fetch_pixels(output_type, width, height, transparent,
                  luxcore_session, execute_imagepipeline, lock=None):
    """Blocking film readback + imagepipeline. Runs the device-queue
    drain; with the GIL released by pyluxcore this is safe to call on a
    worker thread. ``lock`` (the session worker's session_lock) keeps
    the read from racing a scene edit / session stop on the worker.

    Module-level (not a FrameBuffer method) so read threads never keep a
    FrameBuffer alive: GL objects must die on the main thread."""
    bufferdepth = 4 if transparent else 3
    size = width * height * bufferdepth
    data = np.empty(size, dtype=np.float32)
    if lock is None:
        luxcore_session.GetFilm().GetOutputFloat(
            output_type, data, 0, execute_imagepipeline
        )
    else:
        with lock:
            luxcore_session.GetFilm().GetOutputFloat(
                output_type, data, 0, execute_imagepipeline
            )
    # The gpu buffer uses 16-bit float. Values >= 65520 get cast to
    # infinity, leading to a black viewport.
    data[data > 65519] = 65519
    return data


def run_denoiser(session, lock, box):
    """Denoiser worker (background thread).

    Only the OIDN compute runs here. Everything touching GL or Blender
    (framebuffer.update/draw, tag_redraw) must happen on the main thread,
    so the worker only raises a flag that view_draw() consumes. (Calling
    .run() instead of .start() here used to freeze the whole UI for the
    full OIDN run on every pause.)

    The FrameBuffer itself is deliberately NOT an argument: a worker
    holding it would keep its GL objects alive past engine teardown and
    free them off the main thread.
    """
    try:
        film = session.GetFilm()
        if lock is None:
            film.ApplyOIDN(0)  # Apply on first stage in pipeline
        else:
            with lock:
                film.ApplyOIDN(0)
    except Exception:
        import traceback

        traceback.print_exc()
        return
    box["done"] = True


class FrameBuffer:
    """FrameBuffer used for viewport render"""

    def __init__(self, engine, context, scene):
        filmsize = utils.calc_filmsize(scene, context)
        self._width, self._height = filmsize
        self._border = utils.calc_blender_border(scene, context)
        self._view_rect = self._calc_view_rect(context, scene, self._border)
        self._pixel_size = int(scene.luxcore.viewport.pixel_size)

        self._transparent = self._initialize_transparency(scene, context)
        bufferdepth = 4 if self._transparent else 3
        self._output_type = (
            pyluxcore.FilmOutputType.RGBA_IMAGEPIPELINE
            if self._transparent
            else pyluxcore.FilmOutputType.RGB_IMAGEPIPELINE
        )

        self.buffer = gpu.types.Buffer(
            "FLOAT", [self._width * self._height * bufferdepth]
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
        # Readback generation: bumped on every reset so a read that started
        # before the reset cannot satisfy it with pre-edit pixels.
        self._reset_seq = 0
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
                        resampled.reshape(-1).astype(np.float32),
                    )
                    new_fb._from_transition = True
            except Exception:
                # Any failure here just falls back to the default (black) buffer
                pass
        return new_fb

    def _initialize_transparency(self, scene, context):
        if utils.is_valid_camera(
            scene.camera
        ) and not utils.in_material_shading_mode(context):
            return scene.camera.data.luxcore.imagepipeline.transparent_film
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

    def needs_replacement(self, context, scene):
        if (self._width, self._height) != utils.calc_filmsize(scene, context):
            return True
        valid_cam = utils.is_valid_camera(scene.camera)
        if valid_cam:
            if (
                self._transparent
                != scene.camera.data.luxcore.imagepipeline.transparent_film
            ):
                return True
        elif self._transparent:
            # By default (if no camera is available), the film is not transparent
            return True
        if self._border != utils.calc_blender_border(scene, context):
            return True
        if self._pixel_size != int(scene.luxcore.viewport.pixel_size):
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
            region_w * bmin_x + 1,
            region_h * bmin_y + 1,
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
        self._denoise_box = {"done": False}
        sess = session if session is not None else engine.session
        self._denoise_session = sess
        self._denoiser_thread = threading.Thread(
            target=run_denoiser,
            args=(sess, _session_lock(engine), self._denoise_box),
            daemon=True,
            name="LuxCoreViewportDenoise",
        )
        self._denoiser_thread.start()

    def is_denoiser_active(self):
        return self._denoiser_thread and self._denoiser_thread.is_alive()

    def reset_denoiser(self):
        self.denoised = False
        # No join: a stale worker only flips its private box, which
        # consume_denoise_result() ignores because _denoise_box moved on.
        self._denoise_session = None
        self._denoise_box = None
        self._denoiser_thread = None
        self._interactive_denoise = False

    # Max time to keep showing the previous frame after a film reset before
    # falling back to whatever the (possibly still-empty) film holds.
    HOLD_LAST_FRAME_MAX_S = 0.5
    # Same for camera moves: the old viewpoint is *wrong*, so bound the
    # stale display tighter (ghosting) - new samples normally land faster.
    HOLD_LAST_FRAME_CAMERA_S = 0.15
    # Min interval between interactive OIDN runs during rendering.
    INTERACTIVE_DENOISE_INTERVAL = 1.0
    # Fast film readback cadence right after an edit/first start, so the
    # first recognizable frame lands early (the normal 10 Hz would add up
    # to 100 ms of dead time on top of sampling).
    FAST_READ_WINDOW_S = 1.5
    FAST_READ_INTERVAL_S = 0.05

    def begin_reset(self, hold_s=None):
        """Mark that the film was just cleared by a scene/camera edit.

        While set, update() keeps displaying the previous frame until the
        new render has produced visible samples (bounded by the deadline
        so genuinely black scenes still display). ``hold_s`` bounds the
        stale-frame hold - pass a short value when the previous frame is
        known to be wrong (camera moves) to avoid visible ghosting.
        """
        self._pending_reset = True
        self._reset_seq += 1
        self._fast_read_until = time.time() + self.FAST_READ_WINDOW_S
        hold = hold_s if hold_s is not None else self.HOLD_LAST_FRAME_MAX_S
        if self._pending_reset_deadline < time.time():
            # Deadline anchored at the FIRST reset of a burst: during a
            # sustained orbit (resets every draw) a sliding deadline would
            # pin a stale view forever if the film stays empty - after the
            # window, live (low-sample) frames take over instead.
            self._pending_reset_deadline = time.time() + hold
        # The denoised frames are stale now; raw updates resume until the
        # interactive denoiser re-engages.
        self._interactive_denoise = False

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
        if denoise_session is None or denoise_session is not engine.session:
            return False
        lock = _session_lock(engine)
        try:
            # Non-blocking on the UI thread: skip this draw rather than
            # stall behind a worker edit.
            if lock is None:
                denoise_session.UpdateStats()
            elif lock.acquire(blocking=False):
                try:
                    denoise_session.UpdateStats()
                finally:
                    lock.release()
            else:
                return False
        except RuntimeError:
            return False
        self.update(
            denoise_session, engine, execute_imagepipeline=False, force=True
        )
        if final:
            self.denoised = True
        return True

    def _accept_pixels(self, data, force=False, seq=None, fresh=True):
        """Swap newly fetched pixels into the GPU buffer (main thread)."""
        now = time.time()
        if self._pending_reset and not force:
            # Reject reads that can't contain post-edit pixels: either the
            # read was kicked off before the reset call itself, or the
            # worker applied another session mutation after the read
            # started. Accepting one would clear the pending state and let
            # the *next* (post-reset, still empty) read flash black.
            if seq is not None and (
                seq != self._reset_seq or not fresh
            ):
                return False
            if np.any(data > 0.0) or now >= self._pending_reset_deadline:
                self._pending_reset = False
            else:
                # Film still empty after the reset: keep the previous frame.
                return False
        if self._interactive_denoise and not force:
            # Denoised frames own the display; raw uploads would alternate
            # with them and flicker.
            return False
        bufferdepth = 4 if self._transparent else 3
        # Keep a copy of the last rendered pixels so a replacement framebuffer
        # can show them (resampled) while the new session starts up
        self._last_pixels = data.reshape(self._height, self._width, bufferdepth).copy()
        self.buffer = gpu.types.Buffer(
            "FLOAT", [self._width * self._height * bufferdepth], data
        )
        self._pixels_dirty = True
        return True

    def update(
        self,
        luxcore_session,
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
            data = _fetch_pixels(
                self._output_type,
                self._width,
                self._height,
                self._transparent,
                luxcore_session,
                execute_imagepipeline,
                None,  # already holding the lock
            )
        finally:
            if lock is not None:
                lock.release()
        return self._accept_pixels(data, force)

    def start_async_update(
        self, luxcore_session, engine=None, execute_imagepipeline=True
    ):
        """Kick off a background film readback; the result lands in a box
        dict consumed by consume_async_update() on the main thread. No-op
        while a read is already in flight. The thread deliberately never
        touches ``self`` so the FrameBuffer can be torn down mid-read."""
        if self._read_thread is not None and self._read_thread.is_alive():
            return False
        box = {
            "done": False,
            "data": None,
            "seq": self._reset_seq,
            "mut_seq": _mutation_seq(engine),
        }
        self._read_box = box
        self._read_session = luxcore_session
        self._last_update = time.time()
        lock = _session_lock(engine) if engine is not None else None
        output_type, width, height, transparent = (
            self._output_type,
            self._width,
            self._height,
            self._transparent,
        )

        def work():
            try:
                box["data"] = _fetch_pixels(
                    output_type, width, height, transparent,
                    luxcore_session, execute_imagepipeline, lock,
                )
            except Exception:
                import traceback

                traceback.print_exc()
            box["done"] = True

        self._read_thread = threading.Thread(
            target=work, daemon=True, name="LuxCoreViewportReadback"
        )
        self._read_thread.start()
        return True

    def consume_async_update(self, luxcore_session, engine=None):
        """Main thread: pick up a finished async readback. Returns True when
        a fresh frame was swapped into the buffer."""
        box = self._read_box
        if box is None or not box["done"]:
            return False
        self._read_box = None
        self._read_thread = None
        if self._read_session is not luxcore_session or box["data"] is None:
            return False
        fresh = (
            engine is None or box["mut_seq"] >= _mutation_seq(engine)
        )
        return self._accept_pixels(
            box["data"], seq=box["seq"], fresh=fresh
        )

    def update_async(
        self, luxcore_session, engine=None, execute_imagepipeline=True
    ):
        """Non-blocking readback driver for view_draw: consumes a finished
        read, otherwise starts a new one. Reads run at 20 Hz for a short
        window after each edit (fast first frame), then at 10 Hz."""
        if self.consume_async_update(luxcore_session, engine):
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
            luxcore_session, engine, execute_imagepipeline
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
                pass_count = stats.Get("stats.renderengine.pass").GetInt()
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
        format = "RGBA16F" if self._transparent else "RGB16F"
        # Re-create the GPU texture only when new pixels arrived; drawing
        # the same texture every frame churns VRAM for nothing (and the old
        # texture was never explicitly freed).
        if getattr(self, "_pixels_dirty", True) or getattr(self, "_texture", None) is None:
            self._texture = gpu.types.GPUTexture(
                size=(self._width, self._height),
                layers=0,
                is_cubemap=False,
                format=format,
                data=self.buffer,
            )
            self._pixels_dirty = False
        self.shader.uniform_sampler("image", self._texture)
        self.batch.draw(self.shader)
