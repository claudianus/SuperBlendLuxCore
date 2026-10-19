from ..export import blender_settings
from time import time, sleep

_needs_reload = "bpy" in locals()

import bpy

from .. import export, utils, draw, properties
from ..draw.final import FrameBufferFinal
from ..utils import render as utils_render
from ..utils import external_render
from ..utils.errorlog import SuperLuxCoreErrorLog
from ..utils import view_layer as utils_view_layer
from ..properties.denoiser import SuperLuxCoreDenoiser
from ..properties.display import SuperLuxCoreDisplaySettings

if _needs_reload:
    import importlib

    importlib.reload(export)
    importlib.reload(utils)
    importlib.reload(draw)
    importlib.reload(properties)


def render(engine, depsgraph):
    print("=" * 50)
    scene = depsgraph.scene_eval
    SuperLuxCoreErrorLog.clear()
    # Exported geometry outlives the evaluated depsgraph. Statistics must
    # belong to the original scene so they remain valid after its release.
    statistics = depsgraph.scene.superluxcore.statistics.get_active()

    if utils.is_valid_camera(scene.camera):
        tonemapper = scene.camera.data.superluxcore.imagepipeline.tonemapper
        if len(scene.view_layers) > 1 and tonemapper.is_automatic():
            msg = ("Using an automatic tonemapper with multiple "
                   "renderlayers will result in brightness differences")
            SuperLuxCoreErrorLog.add_warning(msg)

    _check_halt_conditions(engine, scene)

    layer = depsgraph.view_layer_eval
    layer_name = layer.name

    print('[Engine/Final] Rendering layer "%s"' % layer.name)

    dummy_result = engine.begin_result(0, 0, 1, 1, layer=layer.name)

    # Check if the layer is disabled. Cycles does this the same way,
    # to be honest I have no idea why they don't just check layer.use
    if layer.name not in dummy_result.layers:
        # The layer is disabled
        engine.end_result(dummy_result, cancel=True, do_merge_results=False)
        #continue

    engine.end_result(dummy_result, cancel=True, do_merge_results=False)

    # This property is used during export, e.g. to check for layer visibility
    utils_view_layer.State.active_view_layer = layer.name

    _add_passes(engine, layer, scene)
    _render_layer(engine, depsgraph, statistics, layer)

    if _stop_requested(engine):
        # Blender skips the rest of the render layers anyway
        return

    print('[Engine/Final] Finished rendering layer "%s"' % layer_name)
    

def _render_layer(engine, depsgraph, statistics, view_layer):
    engine.reset()
    engine.final_dlss = None
    engine._dlss_final_cancelled = False
    engine._dlss_fallback_reported = False
    try:
        from .dlss_final import final_options, FinalDLSS
        options, reason = final_options(depsgraph.scene_eval, engine, utils.get_addon_preferences(bpy.context))
        if options is not None:
            try:
                engine.final_dlss = FinalDLSS(options.backend(),
                                             transparent=blender_settings.transparent_film(depsgraph.scene_eval),
                                             input_reduction=(1 if getattr(options, 'trace_reduction', 1) > 1 else 2 if options.render_mode == 'PERFORMANCE' else 1),
                                             trace_reduction=getattr(options, 'trace_reduction', 1),
                                             output_size=options.output_size,
                                             native_input_reduction=int(getattr(depsgraph.scene_eval.superluxcore.denoiser, 'dlss_input_reduction', '1')))
            except (RuntimeError, OSError) as error:
                reason = 'DLSS final initialization failed: %s; using OIDN' % error
        if reason:
            SuperLuxCoreErrorLog.add_warning(reason)
        return _render_layer_impl(engine, depsgraph, statistics, view_layer)
    finally:
        final_dlss = engine.final_dlss
        if final_dlss is not None:
            print('[DLSS/Final] samples=%d evaluations=%d fallback=%s' %
                  (final_dlss.samples, final_dlss.evaluations, final_dlss.failed or 'none'))
        _close_final_resources(engine)


def _close_final_resources(engine):
    """Retire native ownership even when SDK/session cleanup raises."""
    controller = getattr(engine, 'final_dlss', None)
    try:
        if controller is not None:
            controller.close()
    finally:
        try:
            if engine.session is not None and engine.session.IsStarted():
                engine.session.Stop()
        finally:
            engine.session = None
            engine.final_dlss = None
            if controller is not None:
                controller._source_scene = None
                controller.pipeline = None
            exporter = getattr(engine, 'exporter', None)
            if exporter is not None:
                exporter.final_dlss = None


def _render_layer_impl(engine, depsgraph, statistics, view_layer):
    engine.exporter = export.Exporter(statistics)
    engine.exporter.final_dlss = engine.final_dlss
    scene = depsgraph.scene_eval

    if scene.superluxcore.config.external_process and not engine.is_preview:
        # Serialize the scene and hand it to a detached render process;
        # returning from render() releases the depsgraph and all
        # evaluated Blender-side scene memory.
        result = engine.exporter.export_scene(
            depsgraph, None, engine, view_layer
        )
        if result is None:
            return
        superluxcore_scene, config_props = result
        if not scene.superluxcore.halt.enable:
            print(
                "[BLC] WARNING: no halt condition set — the external "
                "render runs until the process is killed"
            )
        external_render.run(config_props, superluxcore_scene, scene,
                            beauty_index=engine.aov_imagepipelines.get("DENOISED", 0))
        # Drop the exporter (its caches still hold the exported numpy
        # arrays); returning releases the depsgraph too.
        engine.exporter = None
        return

    engine.session = engine.exporter.create_session(depsgraph, engine=engine, view_layer=view_layer)

    if engine.session is None:
        # session is None, but no error was thrown
        print("[Engine/Final] Export cancelled by user.")
        return

    engine.framebuffer = FrameBufferFinal(scene, depsgraph)

    # All evaluated geometry, motion and object/pass maps have been exported.
    # Keep only original-scene settings for live halt/image-pipeline changes;
    # Blender can now release its render-resolution mesh copies before the
    # native BVH and GPU staging buffers allocate another copy of the scene.
    scene = depsgraph.scene
    depsgraph = None
    if not engine.is_preview:
        _release_evaluated_scene(engine)

    # Create session
    start = time()
    engine.session.Start()
    session_init_time = time() - start
    print("Session started in %.1f s" % session_init_time)
    statistics.session_init_time.value = session_init_time

    session_config = engine.session.GetRenderConfig()

    if scene.superluxcore.config.use_filesaver:
        engine.session.Stop()

        if scene.superluxcore.config.filesaver_format == "BIN":
            output_path = session_config.GetProperty("filesaver.filename").GetString()
        else:
            output_path = session_config.GetProperty("filesaver.directory").GetString()
        engine.report({"INFO"}, 'Exported to "%s"' % output_path)

        # Clean up
        del engine.session
        engine.session = None
        return

    start = time()
    path_settings = scene.superluxcore.config.path
    last_film_refresh = 0
    last_stat_refresh = 0
    # When auto clamping already applied the suggested value at export,
    # the running render is clamped: re-measuring a suggestion from a
    # clamped film would drift, so skip it.
    checked_optimal_clamp = path_settings.use_clamping or (
        path_settings.auto_clamping
        and path_settings.suggested_clamping_value > 0
    )
    engine_type = session_config.GetProperty("renderengine.type").GetString()
    if engine_type.startswith("TILE"):
        epsilon = 0.1
        aa = scene.superluxcore.config.tile.path_sampling_aa_size
        clamp_warmup_samples = aa**2 - epsilon
    else:
        clamp_warmup_samples = 2.0
    stats = utils_render.update_stats(engine.session)
    FAST_REFRESH_DURATION = 1 if engine.is_animation else 5

    while True:
        final_dlss = engine.final_dlss
        # Wait on the native frame condition (with the GIL released), rather
        # than limiting the lossless producer/consumer handshake to 5 samples/s.
        # Bound the wait so pause, settings and cancellation remain responsive.
        dlss_active = final_dlss is not None and not final_dlss.failed
        frame_wait = 50 if dlss_active and not SuperLuxCoreDisplaySettings.paused and not engine.session.IsInPause() else 0
        dlss_updated = final_dlss.poll(engine.session, frame_wait) if dlss_active and not _stop_requested(engine) else False
        now = time()
        if final_dlss is not None and final_dlss.failed and not getattr(engine, '_dlss_fallback_reported', False):
            # A config wrapper retains its session. Drop it before rebuilding
            # the failed low-raster GPU resources to avoid a duplicate scene.
            session_config = None
            final_dlss.restore_native(engine)
            session_config = engine.session.GetRenderConfig()
            stats = utils_render.update_stats(engine.session)
            SuperLuxCoreErrorLog.add_warning('DLSS final fallback to OIDN: ' + final_dlss.failed)
            engine._dlss_fallback_reported = True
        manual_refresh_requested = SuperLuxCoreDisplaySettings.refresh or SuperLuxCoreDenoiser.refresh
        update_stats = dlss_updated or (dlss_active and engine.session.HasDone()) or (now - last_stat_refresh) > _stat_refresh_interval(start, scene)
        time_until_film_refresh = scene.superluxcore.display.interval - (now - last_film_refresh)
        fast_refresh = now - start < FAST_REFRESH_DURATION
        if dlss_active:
            # Keep all raw/AOV passes together, but avoid redrawing unchanged
            # data while waiting for the next independent input.
            fast_refresh &= dlss_updated and now - last_film_refresh >= 1 / 5

        if SuperLuxCoreDisplaySettings.paused:
            if not engine.session.IsInPause():
                engine.session.Pause()
                utils_render.update_status_msg(stats, engine, scene, session_config, time_until_film_refresh=0)
                engine.framebuffer.draw(engine, engine.session, scene, render_stopped=False)
                engine.update_stats("", "Paused")
        else:
            if engine.session.IsInPause():
                engine.session.Resume()

        # Do session update (imagepipeline, lightgroups)
        changes = engine.exporter.get_final_changes(scene)
        engine.exporter.update_session(changes, engine.session)
        if final_dlss is not None and changes & export.Change.HALT:
            final_dlss.sync_halt(engine.session, export.halt.convert(scene))
        # A halt target changes neither the traced interval nor neural history.
        # Keep reconstructing every input up to the synchronized new cap.
        if changes & ~export.Change.HALT and final_dlss is not None and not final_dlss.failed:
            final_dlss.invalidate(engine.session, 'Final render settings changed; using OIDN for the current raw film')
            if final_dlss.trace_reduction > 1:
                session_config = None
                final_dlss.restore_native(engine)
                session_config = engine.session.GetRenderConfig()

        if engine.session.IsInPause():
            if changes or manual_refresh_requested:
                engine.framebuffer.draw(engine, engine.session, scene, render_stopped=False)
        else:
            if fast_refresh or update_stats or changes or manual_refresh_requested or (time_until_film_refresh <= 0):
                # We have to check the stats often to see if a halt condition is met
                # But film drawing is expensive, so we don't do it every time we check stats
                draw_film = fast_refresh or (time_until_film_refresh <= 0)

                # Refresh quickly when user changed something or requested a refresh via button
                draw_film |= changes or manual_refresh_requested

                # poll() already updated convergence before acknowledging this
                # exact input. Do not repeat the expensive film read/merge.
                stats = (engine.session.GetStats() if dlss_updated and not final_dlss.failed and not changes
                         else utils_render.update_stats(engine.session))
                if draw_film:
                    time_until_film_refresh = 0
                utils_render.update_status_msg(stats, engine, scene, session_config, time_until_film_refresh)

                # Compute and print the optimal clamp value. Done only once after a warmup phase.
                # Only do this if clamping is disabled, otherwise the value is meaningless.
                # Must run BEFORE the HasDone break: a fast render can reach
                # the halt condition in the first stats update, and skipping
                # this check then would never record the suggestion.
                samples = stats.Get("stats.renderengine.pass").GetInt()
                if not checked_optimal_clamp and samples > clamp_warmup_samples:
                    clamp_value = utils_render.find_suggested_clamp_value(engine.session, scene)
                    print("Recommended clamp value:", clamp_value)
                    checked_optimal_clamp = True

                # Check if the user cancelled during the expensive stats update
                if _stop_requested(engine) or engine.session.HasDone():
                    break

                last_stat_refresh = now
                if draw_film:
                    # Show updated film (this operation is expensive)
                    engine.framebuffer.draw(engine, engine.session, scene, render_stopped=False)
                    last_film_refresh = time() if dlss_active else now

            utils_render.update_status_msg(stats, engine, scene, session_config, time_until_film_refresh)

        # Check before we sleep
        if _stop_requested(engine):
            break

        # Don't use up too much CPU time for this refresh loop, but stay responsive
        # Note: The engine Python code seems to be threaded by Blender,
        # so the interface would not even hang if we slept for minutes here
        if not dlss_active or final_dlss.failed or engine.session.IsInPause():
            sleep(1 / 5)

        # Check after we slept, before the next possible expensive operation
        if _stop_requested(engine):
            break

    # User wants to stop or halt condition is reached
    # Update stats to refresh film and draw the final result
    if engine.final_dlss is not None:
        engine._dlss_final_cancelled = _stop_requested(engine)
        if engine._dlss_final_cancelled and not engine.final_dlss.failed:
            engine.final_dlss.invalidate(engine.session, 'Render cancelled; keeping the traced film preview', release=False)
        if engine.session.IsInPause():
            engine.session.Resume()
        engine.session.Stop()
        stats = engine.session.GetStats()
    else:
        stats = utils_render.update_stats(engine.session)
    utils_render.update_status_msg(stats, engine, scene, session_config, time_until_film_refresh=0)
    engine.framebuffer.draw(engine, engine.session, scene, render_stopped=True)
    engine.update_stats("Render", "Stopping session...")
    if engine.session.IsInPause():
        engine.session.Resume()
    if engine.session.IsStarted():
        engine.session.Stop()
    # Clean up
    del engine.session
    engine.session = None


def _release_evaluated_scene(engine):
    """Call Blender only after evaluated scene data and maps are exported."""
    engine.free_blender_memory()


def _stop_requested(engine):
    return engine.test_break() or SuperLuxCoreDisplaySettings.stop_requested


def _stat_refresh_interval(start, scene):
    width, height = utils_render.calc_filmsize(scene)
    is_big_image = width * height > 2000 * 2000
    minimum = 4 if is_big_image else 1
    maximum = 16

    minutes = (time() - start) / 60
    if minutes < 4:
        return max(2**minutes, minimum)
    else:
        return maximum


def _check_halt_conditions(engine, scene):
    enabled_layers = [layer for layer in scene.view_layers if layer.use]
    needs_halt_condition = len(enabled_layers) > 1 or engine.is_animation
    if not needs_halt_condition:
        return
    missing = False
    for layer in enabled_layers:
        layer_halt = layer.superluxcore.halt
        halt = layer_halt if layer_halt.enable else scene.superluxcore.halt
        # Read RNA properties directly: Python convenience methods are not
        # available on every evaluated PropertyGroup in stock Blender.
        enabled = halt.enable and (halt.use_time or halt.use_samples
                                    or halt.use_noise_thresh or halt.use_noise_level)
        if not enabled:
            missing = True
            SuperLuxCoreErrorLog.add_error('Halt condition missing for render layer "%s"' % layer.name)
    if missing:
        raise Exception("Missing halt condition (check error log)")


def _add_passes(engine, layer, scene):
    """
    Add our custom passes.
    Called by engine.final.render() before the render starts.
    layer is the current render layer.
    """
    from ..export import cycles_passes
    # Depth 이미지는 Blender가 기본으로 추가하므로 중복 등록하지 않는다.
    for item in cycles_passes.enabled(layer):
        if item.name != "Depth" and not (item.name == "UV" and layer.superluxcore.aovs.uv):
            engine.add_pass(item.name, len(item.channels), item.channels, layer=layer.name)
    aovs = layer.superluxcore.aovs

    # Denoiser
    if scene.superluxcore.denoiser.enabled:
        transparent = blender_settings.transparent_film(scene)
        if transparent:
            engine.add_pass("DENOISED", 4, "RGBA", layer=layer.name)
        else:
            engine.add_pass("DENOISED", 3, "RGB", layer=layer.name)

    if aovs.rgb:
        engine.add_pass("RGB", 3, "RGB", layer=layer.name)
    if aovs.rgba:
        engine.add_pass("RGBA", 4, "RGBA", layer=layer.name)
    if aovs.alpha:
        engine.add_pass("ALPHA", 1, "A", layer=layer.name)
    # Note: If the Depth pass is already added by Blender and we add it again, it won't be
    # displayed correctly in the "Depth" view mode of the "Combined" pass in the image editor.
    if aovs.depth and not layer.use_pass_z:
        engine.add_pass("Depth", 1, "Z", layer=layer.name)
    if aovs.albedo:
        engine.add_pass("ALBEDO", 3, "RGB", layer=layer.name)
    if aovs.material_id:
        engine.add_pass("MATERIAL_ID", 1, "X", layer=layer.name)
    if aovs.material_id_color:
        engine.add_pass("MATERIAL_ID_COLOR", 3, "RGB", layer=layer.name)
    if aovs.object_id:
        engine.add_pass("OBJECT_ID", 1, "X", layer=layer.name)
    if aovs.emission:
        engine.add_pass("EMISSION", 3, "RGB", layer=layer.name)
    if aovs.caustic:
        engine.add_pass("CAUSTIC", 3, "RGB", layer=layer.name)
    if aovs.direct_diffuse:
        engine.add_pass("DIRECT_DIFFUSE", 3, "RGB", layer=layer.name)
    if aovs.direct_diffuse_reflect:
        engine.add_pass("DIRECT_DIFFUSE_REFLECT", 3, "RGB", layer=layer.name)
    if aovs.direct_diffuse_transmit:
        engine.add_pass("DIRECT_DIFFUSE_TRANSMIT", 3, "RGB", layer=layer.name)
    if aovs.direct_glossy:
        engine.add_pass("DIRECT_GLOSSY", 3, "RGB", layer=layer.name)
    if aovs.direct_glossy_reflect:
        engine.add_pass("DIRECT_GLOSSY_REFLECT", 3, "RGB", layer=layer.name)
    if aovs.direct_glossy_transmit:
        engine.add_pass("DIRECT_GLOSSY_TRANSMIT", 3, "RGB", layer=layer.name)
    if aovs.indirect_diffuse:
        engine.add_pass("INDIRECT_DIFFUSE", 3, "RGB", layer=layer.name)
    if aovs.indirect_diffuse_reflect:
        engine.add_pass("INDIRECT_DIFFUSE_REFLECT", 3, "RGB", layer=layer.name)
    if aovs.indirect_diffuse_transmit:
        engine.add_pass("INDIRECT_DIFFUSE_TRANSMIT", 3, "RGB", layer=layer.name)
    if aovs.indirect_glossy:
        engine.add_pass("INDIRECT_GLOSSY", 3, "RGB", layer=layer.name)
    if aovs.indirect_glossy_reflect:
        engine.add_pass("INDIRECT_GLOSSY_REFLECT", 3, "RGB", layer=layer.name)
    if aovs.indirect_glossy_transmit:
        engine.add_pass("INDIRECT_GLOSSY_TRANSMIT", 3, "RGB", layer=layer.name)
    if aovs.indirect_specular:
        engine.add_pass("INDIRECT_SPECULAR", 3, "RGB", layer=layer.name)
    if aovs.indirect_specular_reflect:
        engine.add_pass("INDIRECT_SPECULAR_REFLECT", 3, "RGB", layer=layer.name)
    if aovs.indirect_specular_transmit:
        engine.add_pass("INDIRECT_SPECULAR_TRANSMIT", 3, "RGB", layer=layer.name)
    if aovs.position:
        engine.add_pass("POSITION", 3, "XYZ", layer=layer.name)
    if aovs.shading_normal:
        engine.add_pass("SHADING_NORMAL", 3, "XYZ", layer=layer.name)
    if aovs.avg_shading_normal:
        engine.add_pass("AVG_SHADING_NORMAL", 3, "XYZ", layer=layer.name)
    if aovs.geometry_normal:
        engine.add_pass("GEOMETRY_NORMAL", 3, "XYZ", layer=layer.name)
    if aovs.uv:
        # We need to pad the UV pass to 3 elements (Blender can't handle 2 elements)
        engine.add_pass("UV", 3, "UVA", layer=layer.name)
    if aovs.direct_shadow_mask:
        engine.add_pass("DIRECT_SHADOW_MASK", 1, "X", layer=layer.name)
    if aovs.indirect_shadow_mask:
        engine.add_pass("INDIRECT_SHADOW_MASK", 1, "X", layer=layer.name)
    if aovs.raycount:
        engine.add_pass("RAYCOUNT", 1, "X", layer=layer.name)
    if aovs.samplecount:
        engine.add_pass("SAMPLECOUNT", 1, "X", layer=layer.name)
    if aovs.convergence:
        engine.add_pass("CONVERGENCE", 1, "X", layer=layer.name)
    if aovs.noise:
        engine.add_pass("NOISE", 1, "X", layer=layer.name)
    if aovs.irradiance:
        engine.add_pass("IRRADIANCE", 3, "RGB", layer=layer.name)

    # Light groups
    lightgroups = scene.superluxcore.lightgroups
    lightgroup_pass_names = lightgroups.get_pass_names()
    default_group_name = lightgroups.get_lightgroup_pass_name(is_default_group=True)
    # If only the default group is in the list, it doesn't make sense to show lightgroups
    # Note: this behaviour has to be the same as in the update_render_passes() method of the RenderEngine class
    if lightgroup_pass_names != [default_group_name]:
        for name in lightgroup_pass_names:
            engine.add_pass(name, 3, "RGB", layer=layer.name)
