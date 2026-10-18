"""Final-render consumption of lossless native independent frames.

Native mode preserves canonical raw RGB, alpha and AOV accumulation. The
opt-in physical Half mode traces a smaller beauty film, retaining native
resolution whenever canonical target channels or coverage are requested.
"""
from dataclasses import replace
import numpy as np
import pysuperluxcore

from .dlss import RendererDLSS, DLSSInputError
from .dlss_viewport import configuration
from ..export import blender_settings


def final_options(scene, engine, preferences):
    """Resolve support without altering the scene or its physical settings."""
    if engine.is_preview or not scene.superluxcore.denoiser.enabled or scene.superluxcore.denoiser.type != 'DLSS':
        return None, ''
    config = scene.superluxcore.config
    if config.external_process or config.use_filesaver:
        return None, 'DLSS final rendering currently requires an in-process render; using OIDN'
    if config.engine != 'PATH' or config.effective_device() != 'OCL' or preferences.gpu_backend != 'CUDA':
        return None, 'DLSS final rendering requires CUDA path tracing; using OIDN'
    if scene.superluxcore.denoiser.temporal_enabled:
        return None, 'DLSS and file-based temporal accumulation are separate reconstruction modes; using OIDN'
    if not all(hasattr(pysuperluxcore.RenderSession, name) for name in
               ('AcknowledgeDenoisingFrame', 'ReleaseDenoisingFrameDelivery', 'SetDenoisingFrameHaltSPP')):
        return None, 'The renderer needs updated final-frame delivery and halt support; using OIDN'
    options, reason = configuration(preferences.dlss_library, preferences.dlss_runtime,
                                    getattr(scene.superluxcore.denoiser, 'dlss_preset', 'DEFAULT'))
    reduction = int(getattr(scene.superluxcore.denoiser, 'dlss_input_reduction', '1'))
    trace = int(getattr(scene.superluxcore.denoiser, 'dlss_trace_reduction', '1'))
    if options is not None and trace == 2:
        why = native_trace_reason(scene)
        if not why:
            size = tuple(int(value * scene.render.resolution_percentage / 100)
                         for value in (scene.render.resolution_x, scene.render.resolution_y))
            return replace(options, render_mode='PERFORMANCE', output_size=size, trace_reduction=2), ''
        reason = 'Full-resolution ray tracing retained: ' + why
    elif trace not in (1, 2):
        return None, 'Unknown DLSS physical trace reduction; using OIDN'
    if options is not None and reduction > 1:
        if not getattr(pysuperluxcore.DenoisingImagePipeline, 'supports_canonical_coverage', lambda: False)():
            return None, 'Reduced final input requires renderer-owned target coverage; using OIDN'
        # A saved full-frame border (including Crop enabled) still exports
        # the complete raster. Reject actual crops without changing the
        # artist's border settings or the camera's projection.
        if scene.render.use_border and (
                scene.render.border_min_x != 0 or scene.render.border_min_y != 0 or
                scene.render.border_max_x != 1 or scene.render.border_max_y != 1):
            return None, 'Reduced final input requires the complete output raster; using OIDN'
        size = tuple(int(value * scene.render.resolution_percentage / 100)
                     for value in (scene.render.resolution_x, scene.render.resolution_y))
        options = replace(options, render_mode='PERFORMANCE', output_size=size)
    return options, reason


def native_trace_reason(scene):
    """A reduced beauty film cannot stand in for canonical target AOVs."""
    render, denoiser = scene.render, scene.superluxcore.denoiser
    if not getattr(denoiser, 'to_combined', True):
        return 'the original Combined pass is requested'
    if blender_settings.transparent_film(scene):
        return 'transparent film needs canonical target coverage'
    # A saved full-frame Border/Crop has the same film and projection as
    # Border disabled. Preserve those settings; only actual crops need their
    # original raster. Match the reduced neural-input contract above exactly.
    if render.use_border and (
            render.border_min_x != 0 or render.border_min_y != 0 or
            render.border_max_x != 1 or render.border_max_y != 1):
        return 'render borders need their original raster'
    size = tuple(int(v * render.resolution_percentage / 100)
                 for v in (render.resolution_x, render.resolution_y))
    if any(v < 64 or v % 2 for v in size):
        return 'physical Half requires even output dimensions of at least 64'
    if not getattr(pysuperluxcore.DenoisingImagePipeline, 'supports_upscaling', lambda: False)():
        return 'the installed renderer cannot scale presentation'
    for layer in scene.view_layers:
        if not layer.use:
            continue
        for name in dir(layer):
            # Accurate Cryptomatte is a quality setting, not a requested pass.
            if name.startswith('use_pass_') and name not in {
                    'use_pass_combined', 'use_pass_cryptomatte_accurate'} and getattr(layer, name, False):
                return 'Blender data passes need canonical full-resolution samples'
        aovs = layer.superluxcore.aovs
        if any(getattr(aovs, name.lower(), False) for name in pysuperluxcore.FilmOutputType.names):
            return 'raw AOVs need canonical full-resolution samples'
        if any(item.expression.strip() for item in aovs.lpe_list):
            return 'light-path expressions need canonical full-resolution samples'
    if len(scene.superluxcore.lightgroups.custom):
        return 'light groups need canonical full-resolution samples'
    return ''


def scaled_pipeline_reason(props):
    # These plugins consume RGB only. Geometry/coverage-dependent presentation
    # must keep its real target channels, rather than nearest-resampling them.
    rgb_only = {'NOP', 'TONEMAP_LINEAR', 'TONEMAP_REINHARD02', 'TONEMAP_AUTOLINEAR',
                'TONEMAP_LUXLINEAR', 'GAMMA_CORRECTION', 'GAUSSIANFILTER_3x3',
                'CAMERA_RESPONSE_FUNC', 'BLOOM', 'VIGNETTING', 'COLOR_ABERRATION',
                'WHITE_BALANCE', 'COLOR_LUT', 'TONEMAP_OPENCOLORIO'}
    for name in props.GetAllNames():
        parts = name.split('.')
        if len(parts) == 5 and parts[:2] == ['film', 'imagepipelines'] and int(parts[2]) == 0 and parts[4] == 'type':
            kind = props.Get(name).GetString()
            if kind not in rgb_only:
                return 'image-pipeline plugin ' + kind + ' needs its original target channels'
    return ''


def configure_producer(props, halt_props=None, input_reduction=1, trace_reduction=1):
    """Select coherent sampling while preserving the exported transport/AOVs."""
    if props.Get('renderengine.type').GetString() not in ('PATHOCL', 'TILEPATHOCL'):
        return 'This render engine does not provide coherent CUDA frames; using OIDN'
    # These engines' exported contracts explicitly exclude RTPATHOCL today.
    for name in ('path.restir.gi.enable', 'path.restir.pt.enable'):
        if props.IsDefined(name) and props.Get(name).GetBool():
            return 'The selected indirect-lighting mode needs its original engine; using OIDN'
    if props.IsDefined('path.lighttracing.only') and props.Get('path.lighttracing.only').GetBool():
        return 'DLSS needs camera samples; using OIDN for light-only rendering'
    if input_reduction != 1:
        if input_reduction != 2 or any(props.Get(name).GetInt() < 32 or props.Get(name).GetInt() % 2
                                       for name in ('film.width', 'film.height')):
            return 'Reduced final input requires even output dimensions of at least 32 pixels; using OIDN'
    if trace_reduction != 1:
        if trace_reduction != 2 or input_reduction != 1 or any(
                props.Get(name).GetInt() < 64 or props.Get(name).GetInt() % 2
                for name in ('film.width', 'film.height')):
            return 'Invalid physical Super Resolution raster; using OIDN'
        for name in ('film.width', 'film.height'):
            props.Set(pysuperluxcore.Property(name, props.Get(name).GetInt() // 2))
    for name, value in {
        'renderengine.type': 'RTPATHOCL', 'sampler.type': 'TILEPATHSAMPLER',
        'rtpath.denoisingframes.enable': True,
        'rtpath.denoisingframes.lossless': True,
        'rtpath.denoisingframes.imagepipeline.enable': True,
        'rtpath.denoisingframes.imagepipeline.accumulated': True,
        'rtpath.denoisingframes.input.reduction': input_reduction,
    }.items():
        props.Set(pysuperluxcore.Property(name, value))
    # Config export precedes the separate halt-property merge. Use that
    # actual exported halt contract rather than an absent/default value.
    halt = (halt_props if halt_props is not None else props).Get('batch.haltspp', [0])
    props.Set(pysuperluxcore.Property('rtpath.denoisingframes.haltspp', _coherent_halt_spp(halt)))
    return ''


def _coherent_halt_spp(halt):
    return halt.GetInt(0) if halt.GetSize() == 1 or (halt.GetSize() == 2 and halt.GetInt(1) == 0) else 0


class FinalDLSS:
    """One backend per Blender frame/layer; no stale cross-frame history."""
    def __init__(self, backend, *, transparent=True, input_reduction=1, trace_reduction=1, output_size=None, native_input_reduction=1):
        self.backend = backend
        self.transparent = transparent
        self.input_reduction = input_reduction
        self.trace_reduction = trace_reduction
        self.output_size = output_size
        self.native_input_reduction = native_input_reduction
        self.plan_note = ''
        self.native_restored = False
        self._source_scene = None
        self.consumer = RendererDLSS(backend)
        self.pipeline = pysuperluxcore.DenoisingImagePipeline()
        self.result = None
        self.samples = 0
        self.frame_id = 0
        self.failed = ''
        self.evaluations = 0
        self._epoch = None
        self._alpha = None
        self._raw_color = None

    def retain_native(self, props, reason):
        self.plan_note = 'Full-resolution ray tracing retained: ' + reason
        self.trace_reduction = 1
        self.input_reduction = self.native_input_reduction
        for name, value in zip(('film.width', 'film.height'), self.output_size):
            props.Set(pysuperluxcore.Property(name, value))
        props.Set(pysuperluxcore.Property('rtpath.denoisingframes.input.reduction', self.input_reduction))

    def configure(self, props, halt_props):
        if self.trace_reduction > 1:
            why = scaled_pipeline_reason(props)
            if why:
                self.retain_native(props, why)
        if self.trace_reduction > 1:
            # Configuration may be requested twice while exporting; derive
            # the source raster from the immutable target, never halve twice.
            for name, value in zip(('film.width', 'film.height'), self.output_size):
                props.Set(pysuperluxcore.Property(name, value))
        reason = configure_producer(props, halt_props, self.input_reduction, self.trace_reduction)
        if reason:
            # Admission failed before the producer changed its full raster.
            # The ordinary engine needs no recovery or retained scene owner.
            self.trace_reduction = 1
        return reason

    def prepare_scene(self, scene, props):
        # Retain the real owning wrapper, never reconstruct a non-owning Scene.
        self._source_scene = scene
        if self.trace_reduction == 1:
            return
        # The exporter appends the primary camera pipeline after config.convert.
        # Check the complete contract before allocating the reduced session.
        why = scaled_pipeline_reason(props)
        if why:
            self.retain_native(props, why)
            return
        # Read only: never serialize/reload the scene or its image-map cache.
        try:
            values = scene.ToProperties()
            holdout = any(name.endswith('.holdout.enable') and values.Get(name).GetBool()
                          for name in values.GetAllNames())
        except (RuntimeError, ValueError) as error:
            self.retain_native(props, 'holdout coverage could not be checked: ' + str(error))
        else:
            if holdout:
                self.retain_native(props, 'holdout needs canonical target coverage')

    def restore_native(self, engine):
        """Rebuild GPU resources after failure, retaining the owning scene.

        Callers must drop non-owning RenderConfig wrappers before entering:
        they keep the old session alive and otherwise duplicate its GPU/RAM.
        The in-place RTPATH film resize is unsafe after a captured SR prefix;
        a fresh session avoids reusing stale film/task buffers.
        """
        if self.trace_reduction == 1:
            return False
        if self._source_scene is None:
            raise RuntimeError('Physical SR recovery lost the owning scene')
        old = engine.session
        was_paused = old.IsInPause()
        old.ReleaseDenoisingFrameDelivery()
        if was_paused:
            old.Resume()
        props = old.GetRenderConfig().GetProperties()
        for name, value in zip(('film.width', 'film.height'), self.output_size):
            props.Set(pysuperluxcore.Property(name, value))
        # No consumer remains after fallback; still use coherent sampling and
        # its exact halt contract, without parking a newly started producer.
        props.Set(pysuperluxcore.Property('rtpath.denoisingframes.lossless', False))
        old.Stop()
        engine.session = None
        del old
        config = pysuperluxcore.RenderConfig(props, self._source_scene)
        engine.session = pysuperluxcore.RenderSession(config)
        engine.session.Start()
        if was_paused:
            engine.session.Pause()
        self.trace_reduction = 1
        self.native_restored = True
        return True

    def poll(self, session, timeout_ms=0):
        if self.failed:
            return False
        packet = session.GetDenoisingFrame(self.frame_id, timeout_ms)
        if packet is None:
            return False
        try:
            if not packet.get('lossless_delivery') or not packet.get('image_pipeline_accumulated'):
                raise DLSSInputError('Final rendering requires lossless frames and accumulated AOV context')
            if not packet.get('image_pipeline_available', True):
                raise DLSSInputError(packet.get('image_pipeline_error') or 'Native image-pipeline capture is unavailable')
            count = packet.get('accumulated_eye_samples', 0.)
            if not np.isfinite(count) or count < 1 or count != int(count):
                raise DLSSInputError('The final raw film has an incomplete sample interval')
            changed = self._epoch is not None and packet['scene_epoch'] != self._epoch
            if self.samples and count == 1:
                self.consumer.reset();self.pipeline = pysuperluxcore.DenoisingImagePipeline()
                self.result = None;self.samples = 0
            elif changed:
                raise DLSSInputError('Final reconstruction settings changed without a fresh raw prefix')
            if count != self.samples + 1 or (self.frame_id and packet['frame_id'] != self.frame_id + 1):
                raise DLSSInputError('A final-render frame or accumulated sample interval was skipped/reset')
            film = session.GetFilm()
            has_alpha = film.HasOutput(pysuperluxcore.FilmOutputType.ALPHA)
            if self.transparent and not has_alpha and not np.all(packet['color'][:, :, 3] == 1):
                raise DLSSInputError('Transparent reconstruction needs the canonical accumulated alpha')
            if self.trace_reduction > 1:
                expected = tuple(v // self.trace_reduction for v in self.output_size)
                if tuple(packet['color'].shape[1::-1]) != expected or packet.get('input_reduction', 1) != 1:
                    raise DLSSInputError('Physical SR packet differs from the traced raster')
                image = self.consumer.process(packet, output_size=self.output_size)
                image[:, :, 3] = 1.
            elif self.input_reduction > 1:
                if packet.get('input_reduction') != self.input_reduction or 'target_alpha' not in packet:
                    raise DLSSInputError('Reduced final reconstruction needs its canonical target coverage')
                image = self.consumer.process(packet, output_size=tuple(packet['target_size']))
            else:
                image = self.consumer.process(packet)
            # Reconstruct RGB only. Coverage belongs to the exact accumulated
            # raw prefix, rather than the last input or the neural output.
            # The image pipeline applies its configured alpha/compositing
            # operations once, with the same alpha as ordinary final and AOVs.
            if has_alpha and self.trace_reduction == 1:
                shape = image.shape[:2]
                if self._alpha is None or self._alpha.shape != shape:
                    self._alpha = np.empty(shape, np.float32)
                film.GetOutputFloat(pysuperluxcore.FilmOutputType.ALPHA, self._alpha, 0, False)
                image[:, :, 3] = self._alpha
                if self.transparent:
                    # Neural RGB and sampled coverage use different filters.
                    # Preserve the actual raw radiance at partial/background
                    # pixels until a joint RGB/coverage reconstruction exists;
                    # otherwise an alpha-zero pixel can retain a bright halo.
                    partial = self._alpha < 1.
                    if np.any(partial):
                        rgb_shape = (*shape, 3)
                        if self._raw_color is None or self._raw_color.shape != rgb_shape:
                            self._raw_color = np.empty(rgb_shape, np.float32)
                        film.GetOutputFloat(pysuperluxcore.FilmOutputType.RGB, self._raw_color, 0, False)
                        image[:, :, :3][partial] = self._raw_color[partial]
            result = self.pipeline.process(packet, image, reset=self.consumer.last_reset)
            if not self.transparent:
                # Match FrameBufferFinal's RGB -> opaque Combined conversion.
                # Canonical raw alpha and all AOVs remain renderer-owned.
                result[:, :, 3] = 1.
            if not np.isfinite(result).all():
                raise DLSSInputError('Nonfinite DLSS final output')
            self.result = result
            self.samples = int(count)
            self.evaluations += 1
            self._epoch = packet['scene_epoch']
        except (RuntimeError, ValueError, KeyError) as error:
            self.failed = str(error)
            self.close()
        finally:
            # Update convergence before releasing the producer, so sample/time
            # halt tests can park at this exact fully consumed raw prefix.
            session.UpdateStats()
            session.AcknowledgeDenoisingFrame(packet, keep_lossless=not bool(self.failed))
            self.frame_id = packet['frame_id']
        return True

    def close(self):
        try:
            self.backend.close()
        finally:
            # Failure can hand a long render back to its raw/OIDN path.
            # Release coverage/RGB scratch immediately, including when SDK
            # teardown raises, rather than retaining it until frame end.
            self.result = None
            self._alpha = None
            self._raw_color = None
            self.pipeline = None
            self.consumer.reset()

    def sync_halt(self, session, halt_props):
        config = session.GetRenderConfig()
        if config.GetProperty('renderengine.type').GetString() == 'RTPATHOCL':
            # RenderConfig retains the startup batch properties; use the same
            # current export that was parsed into the running film.
            session.SetDenoisingFrameHaltSPP(_coherent_halt_spp(halt_props.Get('batch.haltspp', [0])))

    def invalidate(self, session, reason, release=True):
        self.failed = reason
        try:
            self.close()
        finally:
            if release:
                session.ReleaseDenoisingFrameDelivery()
