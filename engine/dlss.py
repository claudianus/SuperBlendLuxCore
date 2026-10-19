"""Explicit CUDA Ray Reconstruction backend with a strict frame/guide contract.

This module never fabricates missing guides or interprets accumulated beauty as
an independent frame. A render producer must supply every plane with matching
sample intervals, jitter, orientation and backward motion conventions.
"""
from dataclasses import dataclass
import ctypes as C
import os
from pathlib import Path
import sys
import threading
import weakref

import numpy as np

DLSS_PRESETS = {'DEFAULT': 0, 'D': 4, 'E': 5, 'F': 6}


class DLSSUnavailable(RuntimeError):
    pass


class DLSSInputError(ValueError):
    pass


class _NativeFrame(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in (
        'width', 'height', 'output_width', 'output_height', 'reset', 'independent_samples')]
    _fields_ += [('frame_id', C.c_uint64), ('scene_serial', C.c_uint64),
                 ('jitter_x', C.c_float), ('jitter_y', C.c_float)]
    _fields_ += [(name, C.POINTER(C.c_float)) for name in (
        'color', 'depth', 'diffuse', 'specular', 'normal_roughness', 'motion', 'specular_motion')]


class _NativeStats(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in (
        'texture_bytes', 'host_scratch_bytes', 'sdk_private_bytes', 'frames')]
    _fields_ += [(name, C.c_uint32) for name in (
        'width', 'height', 'output_width', 'output_height')]
    _fields_ += [('evaluate_readback_seconds', C.c_double)]


@dataclass(frozen=True)
class DLSSFrame:
    color: np.ndarray
    depth: np.ndarray
    diffuse: np.ndarray
    specular: np.ndarray
    normal_roughness: np.ndarray
    motion: np.ndarray
    specular_motion: np.ndarray
    frame_id: int
    scene_serial: int
    jitter: tuple  # NGX camera compensation, opposite to traced ray displacement.
    independent_samples: bool
    reset: bool = False
    output_size: tuple = None  # (width, height), or native resolution

    @classmethod
    def from_surface_guides(cls, color, guides, *, render_position, motion, specular_motion, **metadata):
        """Accept the native host reference only when every pixel is complete.

        Background direction motion and reflected/refracted continuation must
        be supplied by a full producer before status 0/2/3 can be presented.
        Motion is explicit even in a static sequence: this function never
        silently substitutes zero for a missing plane.
        """
        status = guides.get('status')
        if (not isinstance(status, np.ndarray) or color.ndim != 3 or
                status.shape != color.shape[:2] or status.dtype != np.uint8 or
                not np.all(status == 1)):
            raise DLSSInputError('Incomplete surface guides: background, unsupported material or path continuation required')
        position = guides.get('position_depth')
        if (not isinstance(render_position, np.ndarray) or render_position.dtype != np.float32 or
                render_position.shape != (*status.shape, 3) or
                not isinstance(position, np.ndarray) or position.shape != (*status.shape, 4) or
                not np.array_equal(render_position, position[:, :, :3])):
            raise DLSSInputError('Host surface guides differ from the actual rendered hit positions; renderer-owned guides required')
        diffuse = np.array(guides['diffuse'], dtype=np.float32, order='C', copy=True)
        # Cycles applies the albedo compression at the DLSS boundary, never to
        # the renderer's material/transport values or its ordinary albedo AOV.
        diffuse[:, :, :3] /= 1 + diffuse[:, :, :3]
        depth = np.ascontiguousarray(guides['position_depth'][:, :, 3])
        frame = cls(color=color, depth=depth, diffuse=diffuse,
                    specular=guides['specular'], normal_roughness=guides['normal_roughness'],
                    motion=motion, specular_motion=specular_motion, **metadata)
        frame.native()
        return frame

    def native(self):
        if not isinstance(self.color, np.ndarray) or self.color.ndim != 3 or self.color.shape[2] != 4:
            raise DLSSInputError('Color must be a float32 H x W x 4 array')
        h, w, _ = self.color.shape
        ow, oh = self.output_size or (w, h)
        if not (0 < w <= 16384 and 0 < h <= 16384 and 32 <= ow <= 16384 and 32 <= oh <= 16384):
            raise DLSSInputError('Unsupported input/output dimensions')
        if not self.independent_samples:
            raise DLSSInputError('Fresh non-overlapping samples are required; accumulated beauty is not a frame')
        if not (0 <= self.frame_id < 2**64 and 0 <= self.scene_serial < 2**64):
            raise DLSSInputError('Frame and scene identifiers must be unsigned 64-bit values')
        jitter = np.asarray(self.jitter)
        if jitter.shape != (2,) or not np.isfinite(jitter).all() or np.any(np.abs(jitter) > .5):
            raise DLSSInputError('Jitter must match the traced frame within half a pixel')
        pointers = []
        for name, channels in [('color', 4), ('depth', 1), ('diffuse', 4), ('specular', 4),
                               ('normal_roughness', 4), ('motion', 2), ('specular_motion', 2)]:
            plane = getattr(self, name)
            shapes = ((h, w), (h, w, 1)) if channels == 1 else ((h, w, channels),)
            if (not isinstance(plane, np.ndarray) or plane.shape not in shapes or
                    plane.dtype != np.float32 or not plane.flags.c_contiguous or not plane.flags.aligned):
                raise DLSSInputError(name + ' has the wrong shape, dtype or storage layout')
            if not np.isfinite(plane).all():
                raise DLSSInputError(name + ' contains nonfinite values')
            pointers.append(plane.ctypes.data_as(C.POINTER(C.c_float)))
        if np.any(self.depth < 0) or np.any(self.normal_roughness[:, :, 3] < 0) or np.any(self.normal_roughness[:, :, 3] > 1):
            raise DLSSInputError('Depth must be nonnegative and perceptual roughness must be in [0, 1]')
        if np.any(self.color[:, :, 3] < 0) or np.any(self.color[:, :, 3] > 1):
            raise DLSSInputError('Alpha must be in [0, 1]')
        return _NativeFrame(w, h, ow, oh, self.reset, True, self.frame_id, self.scene_serial,
                            float(jitter[0]), float(jitter[1]), *pointers)


def _library_path(explicit=None):
    if explicit is None:
        explicit = os.environ.get('SUPERLUXCORE_DLSS_LIBRARY')
    if explicit:
        path = Path(explicit)
        if not path.is_absolute() or not path.is_file():
            raise DLSSUnavailable('SUPERLUXCORE_DLSS_LIBRARY must name an existing absolute library path')
        return path
    # Optional wheel payload, kept independent from the mandatory renderer ABI.
    module = sys.modules.get('pysuperluxcore')
    if module and getattr(module, '__file__', None):
        root = Path(module.__file__).parent
        for name in ('superluxcore_dlss.dll', 'libsuperluxcore_dlss.so', 'libsuperluxcore_dlss.dylib'):
            path = root / name
            if path.is_file():
                return path
    raise DLSSUnavailable('The optional CUDA DLSS backend is not installed')


class CUDADLSS:
    """Synchronous backend; call from a render worker, never Blender view_draw."""
    def __init__(self, runtime_dir, cache_dir, *, device=0, memory_limit=512*1024**2, library=None, preset='DEFAULT'):
        if not isinstance(preset, str) or preset not in DLSS_PRESETS:
            raise DLSSInputError('Unknown DLSS model preset')
        if not (0 < memory_limit < 2**64 and 0 <= device < 2**32):
            raise ValueError('A positive memory limit and nonnegative CUDA device are required')
        self._lock = threading.Lock()
        try:
            self._lib = C.CDLL(str(_library_path(library)))
        except OSError as error:
            raise DLSSUnavailable(str(error)) from error
        lib = self._lib
        lib.slc_dlss_abi.restype = C.c_uint32
        if lib.slc_dlss_abi() != 1:
            raise DLSSUnavailable('Unsupported CUDA DLSS backend ABI')
        lib.slc_dlss_create.argtypes = [C.c_uint32, C.c_char_p, C.c_char_p, C.c_uint64, C.c_char_p, C.c_uint32]
        lib.slc_dlss_create.restype = C.c_void_p
        lib.slc_dlss_process.argtypes = [C.c_void_p, C.POINTER(_NativeFrame), C.POINTER(C.c_float), C.c_uint64, C.c_char_p, C.c_uint32]
        lib.slc_dlss_process.restype = C.c_int
        lib.slc_dlss_stats.argtypes = [C.c_void_p, C.POINTER(_NativeStats)]
        lib.slc_dlss_stats.restype = None
        lib.slc_dlss_destroy.argtypes = [C.c_void_p]
        lib.slc_dlss_destroy.restype = None
        message = C.create_string_buffer(1024)
        self._handle = lib.slc_dlss_create(device, os.fsencode(runtime_dir), os.fsencode(cache_dir), memory_limit, message, len(message))
        if not self._handle:
            raise DLSSUnavailable(message.value.decode('utf8', errors='replace'))
        try:
            # Do not require the additive symbol for DEFAULT: existing ABI-1
            # installations retain their previous model and behavior.
            if preset != 'DEFAULT':
                setter = getattr(lib, 'slc_dlss_set_preset', None)
                if setter is None:
                    raise DLSSUnavailable('The selected DLSS model requires an updated optional backend')
                setter.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32]
                setter.restype = C.c_int
                if not setter(self._handle, DLSS_PRESETS[preset], message, len(message)):
                    raise DLSSUnavailable(message.value.decode('utf8', errors='replace'))
            self._preset = preset
            self._finalizer = weakref.finalize(self, lib.slc_dlss_destroy, self._handle)
        except BaseException:
            lib.slc_dlss_destroy(self._handle)
            self._handle = None
            raise

    @property
    def preset(self):
        return self._preset

    def process(self, frame):
        native = frame.native()
        output = np.empty((native.output_height, native.output_width, 4), np.float32)
        with self._lock:
            if not self._handle:
                raise RuntimeError('DLSS backend is closed')
            message = C.create_string_buffer(1024)
            ok = self._lib.slc_dlss_process(self._handle, C.byref(native), output.ctypes.data_as(C.POINTER(C.c_float)),
                                            output.size, message, len(message))
            if not ok:
                raise RuntimeError(message.value.decode('utf8', errors='replace'))
        return output

    def stats(self):
        with self._lock:
            if not self._handle:
                raise RuntimeError('DLSS backend is closed')
            stats = _NativeStats()
            self._lib.slc_dlss_stats(self._handle, C.byref(stats))
            result = {name: getattr(stats, name) for name, _ in stats._fields_}
            if result['sdk_private_bytes'] == 2**64-1:
                result['sdk_private_bytes'] = None
            return result

    def close(self):
        with self._lock:
            if self._handle:
                self._finalizer()
                self._handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class RendererDLSS:
    """Consume coherent renderer leases, with history committed after evaluation.

    The first supported producer covers static geometry with surface guides.
    Camera motion is reconstructed from the exact uploaded camera matrices.
    Moving reflective surfaces require a renderer reflection-motion guide;
    unsupported paths raise so the caller can display the untouched raw film.
    """
    def __init__(self, backend):
        self.backend = backend
        self._previous = None
        self.last_reset = True

    def reset(self):
        self._previous = None
        self.last_reset = True

    @staticmethod
    def _project(position, world_to_camera, camera_to_raster, height):
        camera = position @ world_to_camera[:3, :3].T + world_to_camera[:3, 3]
        raster = camera @ camera_to_raster[:, :3].T + camera_to_raster[:, 3]
        if not np.isfinite(raster).all() or np.any(raster[..., 3] <= 0):
            raise DLSSInputError('Motion projection is behind the camera or nonfinite')
        result = raster[..., :2] / raster[..., 3:4]
        result[..., 1] = height - result[..., 1]
        return result

    @staticmethod
    def _project_direction(direction, world_to_camera, camera_to_raster, height):
        # Homogeneous w=0 excludes camera translation for an infinite point.
        camera = direction @ world_to_camera[:3, :3].T
        raster = camera @ camera_to_raster[:, :3].T
        if not np.isfinite(raster).all() or np.any(raster[..., 3] <= 0):
            raise DLSSInputError('Environment motion projection is behind the camera or nonfinite')
        result = raster[..., :2] / raster[..., 3:4]
        result[..., 1] = height - result[..., 1]
        return result

    def _prepare(self, packet, output_size, reset):
        if (packet.get('source') != 'renderer_gpu' or packet.get('version') != 1 or
                not packet.get('complete') or not packet.get('independent_samples')):
            raise DLSSInputError('A complete renderer-owned independent frame is required')
        if not packet.get('motion_camera_compatible'):
            raise DLSSInputError('This camera needs lens, distortion or shutter-time motion guides')
        color, guides, count = packet['color'], packet['guides'], packet['sample_count']
        if (not isinstance(color, np.ndarray) or color.ndim != 3 or color.shape[2] != 4 or
                not isinstance(guides, np.ndarray) or guides.shape != (*color.shape[:2], 32) or
                guides.dtype != np.float32 or not np.isfinite(guides).all() or
                not isinstance(count, np.ndarray) or count.shape != color.shape[:2] or
                count.dtype != np.uint32 or not np.all(count == 1)):
            raise DLSSInputError('Renderer frame has an invalid guide layout or sample interval')
        holdout = guides[:, :, 7] == 5
        if not np.all((guides[:, :, 7] == 1) | holdout):
            raise DLSSInputError('Background, unsupported material or continuation needs complete renderer guides')
        if np.any(holdout) and (packet.get('guide_version', 1) != 2 or
                np.any(color[holdout] != 0)):
            raise DLSSInputError('Holdout guides require canonical zero radiance and coverage')
        guide_version = packet.get('guide_version', 1)
        if guide_version not in (1, 2):
            raise DLSSInputError('Unsupported renderer guide semantics')
        if guide_version == 2 and (not np.all(guides[:, :, 19] == 2) or
                np.any(guides[:, :, 23] != 0) or
                not np.isin(guides[:, :, 27], (0, 1, 2, 3)).all() or
                not np.isin(guides[:, :, 31], (0, 1, 2)).all()):
            raise DLSSInputError('Incomplete renderer path features or motion metadata')
        camera = {}
        for name in ('world_to_camera', 'camera_to_raster'):
            value = packet[name]
            if not isinstance(value, np.ndarray) or value.shape != (4, 4) or not np.isfinite(value).all():
                raise DLSSInputError('Renderer frame camera is invalid')
            camera[name] = np.array(value, dtype=np.float64, copy=True)
        h, w = color.shape[:2]
        identity = (packet['scene_epoch'], w, h, output_size, guide_version)
        previous = self._previous
        reset = bool(reset or previous is None or previous['identity'] != identity)
        if previous and previous['identity'] == identity and packet['frame_id'] <= previous['id']:
            raise DLSSInputError('Renderer frames must arrive in increasing order')
        motion = np.zeros((h, w, 2), np.float32)
        specular_motion = np.zeros_like(motion)
        if not reset:
            changed = any(not np.array_equal(camera[name], previous[name]) for name in camera)
            if changed and guide_version == 1 and np.any(guides[:, :, 4:7] != 0):
                raise DLSSInputError('Reflective camera motion requires renderer reflection-motion guides')
            if changed:
                position = guides[:, :, 12:15].astype(np.float64)
                try:
                    if guide_version == 1:
                        motion[:] = (self._project(position, previous['world_to_camera'], previous['camera_to_raster'], h) -
                                     self._project(position, camera['world_to_camera'], camera['camera_to_raster'], h))
                    else:
                        kind = guides[:, :, 27]
                        has_specular = np.any(guides[:, :, 4:7] != 0, axis=2)
                        for target, mask, values, project in (
                                (motion, kind != 2, position, self._project),
                                (motion, kind == 2, guides[:, :, 24:27], self._project_direction),
                                (specular_motion, (kind == 1) & has_specular, guides[:, :, 24:27], self._project),
                                (specular_motion, (kind == 3) & has_specular, guides[:, :, 24:27], self._project_direction)):
                            if np.any(mask):
                                points = values[mask].astype(np.float64)
                                target[mask] = (project(points, previous['world_to_camera'], previous['camera_to_raster'], h) -
                                                project(points, camera['world_to_camera'], camera['camera_to_raster'], h))
                except DLSSInputError:
                    # A cut that puts old projections behind the eye cannot
                    # reuse history; its first independent sample remains valid.
                    reset = True
                    motion.fill(0)
                    specular_motion.fill(0)
        diffuse = np.empty((h, w, 4), np.float32)
        diffuse[:, :, :3] = guides[:, :, :3] / (1 + guides[:, :, :3])
        diffuse[:, :, 3] = 1
        specular = np.empty_like(diffuse)
        specular[:, :, :3] = guides[:, :, 4:7]
        specular[:, :, 3] = 1
        normal = np.empty_like(diffuse)
        normal[:, :, :3] = guides[:, :, 8:11]
        normal[:, :, 3] = guides[:, :, 3]
        ray_jitter = np.asarray(packet['jitter'])
        if ray_jitter.shape != (2,):
            raise DLSSInputError('Renderer jitter must contain two ray offsets')
        # Native rays use pixel + .5 + jitter. NGX expects the compensating
        # camera offset: Cycles traces -pixel_jitter and passes +pixel_jitter.
        jitter = tuple(-float(value) for value in ray_jitter)
        frame = DLSSFrame(color, np.ascontiguousarray(guides[:, :, 15]), diffuse, specular,
                          normal, motion, specular_motion, packet['frame_id'],
                          packet['scene_epoch'], jitter, True, reset, output_size)
        frame.native()
        return frame, dict(camera, identity=identity, id=packet['frame_id'])

    def process(self, packet, *, output_size=None, reset=False):
        """Run on the owning worker. A failed evaluation invalidates history."""
        try:
            target_alpha = packet.get('target_alpha')
            target_holdout = packet.get('target_holdout')
            target_holdout_rgb = packet.get('target_holdout_rgb')
            if target_alpha is not None:
                target_size = tuple(packet.get('target_size', ()))
                if output_size is None:
                    output_size = target_size
                if (packet.get('coverage_source') != 'renderer_full_resolution' or
                        len(target_size) != 2 or tuple(output_size) != target_size or
                        not isinstance(target_alpha, np.ndarray) or target_alpha.dtype != np.float32 or
                        target_alpha.shape != target_size[::-1] or not target_alpha.flags.c_contiguous or
                        not np.isfinite(target_alpha).all() or np.any((target_alpha < 0) | (target_alpha > 1)) or
                        not isinstance(target_holdout, np.ndarray) or target_holdout.dtype != np.uint8 or
                        target_holdout.shape != target_alpha.shape or not target_holdout.flags.c_contiguous or
                        not np.isin(target_holdout, (0, 1)).all()):
                    raise DLSSInputError('Invalid canonical target coverage or reconstruction raster')
                if np.any(target_holdout) and (not isinstance(target_holdout_rgb, np.ndarray) or
                        target_holdout_rgb.dtype != np.float32 or target_holdout_rgb.shape != (*target_alpha.shape, 3) or
                        not target_holdout_rgb.flags.c_contiguous or not np.isfinite(target_holdout_rgb).all()):
                    raise DLSSInputError('Canonical holdout requires its matching accumulated radiance')
            elif np.any(packet['guides'][:, :, 7] == 5) and output_size is not None and tuple(output_size) != packet['color'].shape[1::-1]:
                raise DLSSInputError('Upscaled holdout needs renderer-owned target coverage')
            frame, state = self._prepare(packet, output_size, reset)
            result = self.backend.process(frame)
            if target_alpha is not None:
                result[:, :, 3] = target_alpha
                # A jittered edge may contain earlier background samples.
                # Preserve that exact prefix instead of blackening its RGB.
                if np.any(target_holdout):
                    mask = target_holdout != 0
                    result[:, :, :3][mask] = target_holdout_rgb[mask]
            elif np.any(packet['guides'][:, :, 7] == 5):
                result[packet['guides'][:, :, 7] == 5] = 0
        except Exception:
            self.reset()
            raise
        self._previous = state
        self.last_reset = frame.reset
        return result
