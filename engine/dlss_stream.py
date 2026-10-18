"""Bounded live DLSS consumption without Blender or graphics calls.

The source returns (native_session, mutation_sequence) under session_lock.
It must refer to the session owner, never a FrameBuffer or Blender object.
Results are RGB or RGBA with an explicit image_pipeline_applied flag. An optional
native postprocessor runs on this worker before main-thread graphics upload.
"""
from dataclasses import dataclass
import threading

from .dlss import RendererDLSS, DLSSInputError


@dataclass(frozen=True)
class DLSSStreamResult:
    session: object
    mutation_sequence: int
    frame_id: int
    scene_epoch: int
    pixels: object
    image_pipeline_applied: bool = False
    source_size: tuple = None


class DLSSFrameWorker:
    """One evaluation in flight, one replaceable completed result, no backlog.

    The backend is created, used and closed on this thread. Native frame leases
    are acquired with a nonblocking read under the session owner's lock; SDK
    evaluation never holds that lock. Edits and Stop can therefore proceed
    while DLSS works. Results that predate an applied edit are discarded.
    Construction does not start a thread, so ownership is explicit.
    """
    def __init__(self, source, session_lock, backend_factory, postprocessor_factory=None, notify=None, output_size=None):
        self._source = source
        self._session_lock = session_lock
        self._backend_factory = backend_factory
        self._postprocessor_factory = postprocessor_factory
        self._notify = notify
        self._output_size = output_size
        self._stop = threading.Event()
        self._condition = threading.Condition()
        self._result = None
        self._error = None
        self._thread = None

    def start(self):
        if self._thread is not None or self._stop.is_set():
            raise RuntimeError('A DLSS frame worker can only be started once')
        self._thread = threading.Thread(target=self._run, name='SuperLuxCoreDLSS', daemon=True)
        self._thread.start()

    def shutdown(self):
        """Signal cancellation without waiting for the SDK on the UI thread."""
        self._stop.set()
        with self._condition:
            self._result = None
            self._condition.notify_all()

    def join(self, timeout=None):
        """Wait during supervised teardown; returns whether the thread exited."""
        if self._thread is not None:
            self._thread.join(timeout)
        return self._thread is None or not self._thread.is_alive()

    def take(self, session, mutation_sequence):
        """Consume the latest result only for the current session/edit."""
        with self._condition:
            result, self._result = self._result, None
        if (result is not None and result.session is session and
                result.mutation_sequence == mutation_sequence):
            return result
        return None

    def pop_error(self):
        """Return (exception type, message), retaining no failed frame traceback."""
        with self._condition:
            error, self._error = self._error, None
        return error

    def _wake_presentation(self):
        if self._notify is not None:
            try:
                self._notify()
            except Exception:
                # A closing viewport can no longer schedule redraws. Native
                # resource ownership/teardown must still run on this worker.
                pass

    def _run(self):
        backend = consumer = postprocessor = session = None
        after_id = 0
        failed_session = None
        try:
            while not self._stop.is_set():
                # A busy edit/Stop has priority; never wait holding a second
                # lock or let an SDK evaluation extend its critical section.
                if not self._session_lock.acquire(blocking=False):
                    self._stop.wait(.01)
                    continue
                try:
                    current, sequence = self._source()
                    packet = (current.GetDenoisingFrame(after_id if current is session else 0, 0)
                              if current is not None and current is not failed_session else None)
                finally:
                    self._session_lock.release()
                if current is not session:
                    if backend is not None:
                        backend.close()
                    backend = consumer = postprocessor = None
                    session, after_id, failed_session = current, 0, None
                    with self._condition:
                        self._result = None
                if packet is None:
                    self._stop.wait(.01)
                    continue
                after_id = packet['frame_id']
                try:
                    if (self._postprocessor_factory is not None and
                            packet.get('image_pipeline_available') is False):
                        raise DLSSInputError(packet.get('image_pipeline_error') or
                                             'Coherent image-pipeline capture is unavailable')
                    if backend is None:
                        if self._postprocessor_factory is not None:
                            postprocessor = self._postprocessor_factory()
                        backend = self._backend_factory()
                        consumer = RendererDLSS(backend)
                    pixels = (consumer.process(packet, output_size=self._output_size)
                              if self._output_size is not None else consumer.process(packet))
                    if postprocessor is not None:
                        pixels = postprocessor.process(packet, pixels, reset=consumer.last_reset)
                except Exception as error:
                    if consumer is not None:
                        consumer.reset()
                    with self._condition:
                        wake = self._error is None
                        self._result = None
                        self._error = (type(error).__name__, str(error))
                    # Backend creation is expensive and cannot succeed anew
                    # for every frame of the same unusable session. Guide
                    # rejection/evaluation errors may recover on a later frame.
                    if backend is None and not isinstance(error, DLSSInputError):
                        failed_session = current
                        postprocessor = None
                    packet = None
                    if wake:
                        self._wake_presentation()
                    continue
                result = DLSSStreamResult(current, sequence, packet['frame_id'],
                                          packet['scene_epoch'], pixels,
                                          postprocessor is not None,
                                          (packet['color'].shape[1], packet['color'].shape[0]))
                packet = None  # Release the large native lease immediately.
                wake = False
                # A slow producer may have no next frame for several seconds.
                # A brief ordinary film read must not discard its only finished
                # reconstruction. Retain this one result (the native lease is
                # already released), retry without holding any owner lock, and
                # let shutdown interrupt the wait even while an edit owns it.
                while not self._stop.is_set():
                    if not self._session_lock.acquire(blocking=False):
                        self._stop.wait(.01)
                        continue
                    try:
                        latest, latest_sequence = self._source()
                        if latest is current and latest_sequence == sequence:
                            with self._condition:
                                if not self._stop.is_set():
                                    wake = self._result is None
                                    self._result = result
                                    self._error = None
                                    self._condition.notify_all()
                    finally:
                        self._session_lock.release()
                    # An intervening edit/session swap makes the result stale;
                    # discard it rather than retrying under a new generation.
                    break
                if wake:
                    self._wake_presentation()
                # Never retain an obsolete session or a second finished image
                # while waiting for its next packet.
                result = pixels = None
        except Exception as error:
            with self._condition:
                self._result = None
                self._error = (type(error).__name__, str(error))
        finally:
            try:
                if backend is not None:
                    backend.close()
            finally:
                with self._condition:
                    self._result = None
                    self._condition.notify_all()
