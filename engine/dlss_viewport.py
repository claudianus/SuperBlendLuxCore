"""Optional viewport backend configuration. No Blender or graphics imports."""
from dataclasses import dataclass
import os
from pathlib import Path
import sys
from time import monotonic

import pysuperluxcore
import numpy as np

from .dlss import CUDADLSS, DLSSUnavailable, DLSS_PRESETS, _library_path

DLSS_RENDER_MODES = {'NATIVE': 1., 'QUALITY': 2. / 3., 'PERFORMANCE': .5}


def render_size(size, mode='NATIVE'):
    scale = DLSS_RENDER_MODES[mode]
    return tuple(max(16, int(round(value * scale))) for value in size)


@dataclass(frozen=True)
class DLSSViewportOptions:
    library: str
    runtime: str
    cache: str
    channels: int = 4
    preset: str = 'DEFAULT'
    render_mode: str = 'NATIVE'
    output_size: tuple = None
    trace_reduction: int = 1  # Final-render policy; viewport always uses 1.

    def input_size(self, size):
        return render_size(size, self.render_mode)

    def backend(self):
        budget = 512 * 1024**2
        if self.output_size is not None:
            # Reserve enough for a same-scene full-resolution fallback too.
            width, height = (self.output_size if self.trace_reduction > 1
                             else self.input_size(self.output_size))
            budget = max(budget, width * height * 84 + self.output_size[0] * self.output_size[1] * 32)
            if budget > 1024**3:
                raise DLSSUnavailable('DLSS upscaling buffers exceed the 1 GiB budget')
        return CUDADLSS(self.runtime, self.cache, library=self.library, preset=self.preset, memory_limit=budget)

    def postprocessor(self):
        return DLSSViewportPostprocessor(self.channels)


class DLSSViewportPostprocessor:
    def __init__(self, channels):
        self.channels = channels
        self.pipeline = pysuperluxcore.DenoisingImagePipeline()

    def process(self, frame, pixels, reset=False):
        output = self.pipeline.process(frame, pixels, reset=reset)
        # Pack opaque RGB off the UI thread, just like ordinary film reads.
        return output if self.channels == 4 else np.ascontiguousarray(output[:, :, :3])


def _query_producer_available(backend):
    """Renderer capability only; SDK paths never change physical rendering."""
    try:
        if backend != 'CUDA':
            return False, 'DLSS requires the NVIDIA CUDA backend; ordinary render active'
        if not pysuperluxcore.GetPlatformDesc().Get('compile.LUXRAYS_ENABLE_CUDA').GetBool():
            return False, 'DLSS requires an available NVIDIA RTX device'
        if not hasattr(pysuperluxcore, 'DenoisingImagePipeline'):
            return False, 'DLSS requires an updated renderer installation'
        devices = pysuperluxcore.GetOpenCLDeviceDescs()
        if not any(devices.Get(name+'.type').GetString() == 'CUDA_GPU'
                   for name in devices.GetAllUniqueSubNames('opencl.device')):
            return False, 'DLSS requires an available NVIDIA RTX device'
        return True, ''
    except (RuntimeError, KeyError) as error:
        return False, str(error)


def producer_available(backend='CUDA'):
    """Reuse hardware discovery briefly across viewport config comparisons.

    Config conversion runs on every draw. Device enumeration can initialize
    backend drivers, so repeating it there blocks the UI even with a running
    render worker. Keep one result for one second, independent of SDK paths.
    A changed native module/API invalidates it immediately; failures are also
    retried after the short lifetime so device recovery remains observable.
    """
    if backend != 'CUDA':
        return False, 'DLSS requires the NVIDIA CUDA backend; ordinary render active'
    key = (pysuperluxcore, pysuperluxcore.GetPlatformDesc,
           pysuperluxcore.GetOpenCLDeviceDescs,
           getattr(pysuperluxcore, 'DenoisingImagePipeline', None))
    cached = getattr(producer_available, '_discovery', None)
    if cached is not None and cached[0] == key and monotonic() < cached[1]:
        return cached[2]
    result = _query_producer_available(backend)
    producer_available._discovery = (key, monotonic() + 1., result)
    return result


def configuration(library='', runtime='', preset='DEFAULT', render_mode='NATIVE'):
    """Resolve immutable paths without creating a CUDA/NGX context."""
    try:
        if not isinstance(preset, str) or preset not in DLSS_PRESETS:
            return None, 'Unknown DLSS model preset'
        if render_mode not in DLSS_RENDER_MODES:
            return None, 'Unknown DLSS render scale'
        available, reason = producer_available()
        if not available:
            return None, reason
        if render_mode != 'NATIVE' and not getattr(
                getattr(pysuperluxcore, 'DenoisingImagePipeline', object), 'supports_upscaling', lambda: False)():
            return None, 'DLSS upscaling requires an updated renderer installation'
        native = _library_path(library or None)
        runtime = runtime or os.environ.get('SUPERLUXCORE_DLSS_RUNTIME', '')
        if not runtime:
            # Optional packages can put the licensed runtime beside the helper.
            for folder in [native.parent/'dlss-runtime', native.parent]:
                if any(folder.glob('libnvidia-ngx-dlssd.so*')) or (folder/'nvngx_dlssd.dll').is_file():
                    runtime = str(folder)
                    break
        if not runtime or not Path(runtime).is_absolute() or not Path(runtime).is_dir():
            return None, 'The optional NVIDIA DLSS runtime is not installed'
        cache = os.environ.get('SUPERLUXCORE_DLSS_CACHE')
        if not cache:
            if sys.platform == 'win32':
                base = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))
            elif sys.platform == 'darwin':
                base = Path.home()/'Library/Caches'
            else:
                base = Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))
            cache = str(base/'SuperLuxCore/DLSS')
        return DLSSViewportOptions(str(native), runtime, cache, preset=preset, render_mode=render_mode), ''
    except (DLSSUnavailable, RuntimeError, KeyError) as error:
        return None, str(error)
