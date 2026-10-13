# SPDX-License-Identifier: Apache-2.0
#
# E49: regression test — pins the render-config defaults decided by the
# rules in doc/engineering/2026-10-13-render-defaults.md (R1 unbiased,
# R2 Cycles parity for user-facing caps, R3 engine defaults for
# accelerators). A fresh scene must expose exactly these values and its
# export must leave the engine's own defaults/auto gates in charge; any
# accidental revert or property rename fails loudly.
#
# Run:
#   /Applications/Blender.app/Contents/MacOS/Blender --background \
#       --factory-startup --python dev-tools/e49_render_defaults_test.py
#
# Exits 0 on PASS, 1 on FAIL.

import math
import os
import sys

import bpy

_EXT_DIR = os.path.expanduser(
    "~/Library/Application Support/Blender/5.2/extensions/user_default")
if _EXT_DIR not in sys.path:
    sys.path.insert(0, _EXT_DIR)

RESULTS = []


def check(name, actual, expected):
    if isinstance(expected, float):
        # RNA floats are float32 — compare with tolerance
        ok = math.isclose(actual, expected, rel_tol=1e-6)
    else:
        ok = actual == expected
    RESULTS.append((name, ok))
    print(f"[E49-TEST] {'ok' if ok else 'FAIL'}: {name} "
          f"= {actual!r} (expected {expected!r})", flush=True)


def addon_key():
    for a in bpy.context.preferences.addons:
        if "superluxcore" in a.module.lower():
            return a.module
    return "bl_ext.user_default.superluxcore"


def ensure_superluxcore():
    try:
        bpy.context.scene.render.engine = "SUPERLUXCORE"
    except TypeError:
        bpy.ops.preferences.addon_enable(module=addon_key())
        bpy.context.scene.render.engine = "SUPERLUXCORE"


# (dotted path under scene.superluxcore.config, expected default)
EXPECTED = [
    # engine / device / samplers
    ("engine", "PATH"),
    ("device", "AUTO"),
    ("sampler", "SOBOL"),
    ("sampler_gpu", "SOBOL"),
    ("sampler_pattern", "PROGRESSIVE"),
    # path depths
    # path depths (R2: Cycles 12/4/4/12)
    ("path.depth_total", 12),
    ("path.depth_diffuse", 4),
    ("path.depth_glossy", 4),
    ("path.depth_specular", 12),
    ("path.depth_volume", -1),
    # hybrid light tracing
    ("path.hybridbackforward_enable", True),
    ("path.hybridbackforward_lightpartition", 20.0),
    ("path.hybridbackforward_lightpartition_opencl", 25.0),
    ("path.hybridbackforward_glossinessthresh", 0.05),
    ("path.hybridbackforward_adaptivecaustic", True),
    ("path.hybridbackforward_terminalglossiness", 0.3),
    ("path.hybridbackforward_connectprob", 0.5),
    ("path.lighttracing_only", False),
    ("path.lighttracing_focus", True),
    ("path.lighttracing_focus_ratio", 50.0),
    ("path.lighttracing_focus_radius", 0.01),
    # vertex connection
    ("path.vertex_connection", False),
    ("path.vertex_connection_connects", 4),
    ("path.vertex_connection_pool", 4),
    ("path.vertex_connection_adaptive", True),
    ("path.vertex_connection_merge_radius", 0.001),
    ("path.vertex_connection_reuse", True),
    # clamping (R1: biased, off)
    ("path.use_clamping", False),
    ("path.auto_clamping", False),
    ("path.clamping", 1000.0),
    ("path.clamp_scope", "INDIRECT"),
    ("path.clamp_adaptive", True),
    ("path.clamp_sigma", 6.0),
    # tiled path
    ("use_tiles", False),
    ("tile.path_sampling_aa_size", 3),
    ("tile.size", 128),
    ("tile.multipass_enable", True),
    ("tile.multipass_convtest_threshold", 6 / 256),
    ("tile.multipass_convtest_threshold_reduction", 0.5),
    ("tile.multipass_convtest_warmup", 32),
    # bidir
    ("bidir_light_maxdepth", 24),
    ("bidir_path_maxdepth", 24),
    # sobol
    ("sobol_adaptive_strength", 0.95),
    ("sobol_bluenoise_enable", True),
    ("sobol_owen_enable", False),
    ("sobol_owen_tile_enable", True),
    ("sobol_adaptive_moments_enable", True),
    ("sobol_adaptive_relerr", 0.02),
    # noise estimation
    ("noise_estimation.warmup", 32),
    ("noise_estimation.step", 32),
    # metropolis
    ("metropolis_largesteprate", 30.0),
    ("metropolis_maxconsecutivereject", 1024),
    ("metropolis_imagemutationrate", 5.0),
    # pixel filter (R2: Cycles Blackman-Harris 1.5 px)
    ("filter_enabled", True),
    ("filter", "BLACKMANHARRIS"),
    ("filter_width", 1.5),
    ("gaussian_alpha", 2.0),
    ("sinc_tau", 1.0),
    # light strategy + ReSTIR
    ("light_strategy", "LIGHT_BVH"),
    ("restir_temporal_enable", True),
    ("restir_candidates", 0),
    ("restir_spatial_enable", False),
    ("restir_visibility_enable", False),
    ("restir_gi_enable", False),
    ("restir_gi_candidates", 0),
    ("restir_gi_temporal_enable", True),
    ("restir_gi_spatial_enable", True),
    # MNEE (checked = engine auto gate, engine solver defaults)
    ("mnee_enable", True),
    ("mnee_maxspecular", 1),
    ("mnee_maxiterations", 12),
    ("mnee_seedcache", True),
    # path guiding (R3: engine defaults)
    ("guiding_enable", False),
    ("guiding_ris_k", 0),
    ("guiding_strength", 1.0),
    ("guiding_diffuse", False),
    ("guiding_min_depth", 2),
    ("guiding_glossy_threshold", 0.3),
    ("guiding_warmup", 256),
    ("guiding_components", 4),
    ("guiding_freeze", True),
    ("guiding_split", 0.004),
    ("guiding_max_depth", 12),
    ("guiding_max_leaves", 8192),
    ("guiding_swaprecords", 1000000),
    ("guiding_debug", False),
    ("portal_weight", 0.3),
    # spectral (R5: documented product exception)
    ("spectral_enable", True),
    # DLS cache
    ("dls_cache.enabled", False),
    ("dls_cache.entry_radius_auto", True),
    ("dls_cache.entry_radius", 0.15),
    ("dls_cache.entry_normalangle", math.radians(10)),
    ("dls_cache.entry_maxpasses", 1024),
    ("dls_cache.entry_convergencethreshold", 1.0),
    ("dls_cache.entry_warmupsamples", 12),
    ("dls_cache.entry_volumes_enable", False),
    ("dls_cache.lightthreshold", 1.0),
    ("dls_cache.targetcachehitratio", 99.5),
    ("dls_cache.maxdepth", 8),
    ("dls_cache.maxsamplescount", 10000000),
    ("dls_cache.save_or_overwrite", False),
    # PhotonGI
    ("photongi.enabled", False),
    ("photongi.photon_maxcount", 20.0),
    ("photongi.photon_maxdepth", 16),
    ("photongi.glossinessusagethreshold", 0.049),
    ("photongi.indirect_enabled", True),
    ("photongi.indirect_haltthreshold_preset", "final"),
    ("photongi.indirect_haltthreshold_custom", 5.0),
    ("photongi.indirect_lookup_radius_auto", True),
    ("photongi.indirect_lookup_radius", 0.15),
    ("photongi.indirect_normalangle", math.radians(10)),
    ("photongi.indirect_usagethresholdscale", 8.0),
    ("photongi.caustic_mode", "auto"),
    ("photongi.caustic_enabled", False),  # legacy force-on bool
    ("photongi.caustic_maxsize", 0.1),
    ("photongi.caustic_lookup_radius", 0.075),
    ("photongi.caustic_normalangle", math.radians(10)),
    ("photongi.caustic_periodic_update", True),
    ("photongi.caustic_updatespp", 16),
    ("photongi.caustic_updatespp_radiusreduction", 90.0),
    ("photongi.caustic_updatespp_minradius", 0.0),  # 0 = automatic
    ("photongi.debug", "off"),
    ("photongi.save_or_overwrite", False),
    # env light cache (R3: off like the engine, not yet measured)
    ("envlight_cache.enabled", False),
    ("envlight_cache.quality", 0.5),
    ("envlight_cache.save_or_overwrite", False),
    # image resize policy
    ("image_resize_policy.enabled", True),
    ("image_resize_policy.type", "MIPMAPMEM"),
    ("image_resize_policy.scale", 100.0),
    ("image_resize_policy.min_size", 128),
    # out of core / memory
    ("out_of_core", False),
    ("out_of_core_mode", "EVERYTHING"),
    ("out_of_core_supersampling", "16"),
    ("free_blender_image_buffers", True),
    ("external_process", False),
    ("spill_geometry", False),
    ("spill_geometry_minmb", 4),
    ("spill_images", True),
    ("proxy_auto", False),
    ("proxy_auto_mintris", 250000),
    ("proxy_cluster_stride", 16),
    # filesaver / seed / epsilon / ui
    ("use_filesaver", False),
    ("filesaver_format", "BIN"),
    ("seed", 42),
    ("use_animated_seed", False),
    ("show_min_epsilon", True),
    ("min_epsilon", 1e-5),
    ("max_epsilon", 1e-1),
]


# Defaults outside scene.superluxcore.config: the fire-and-forget stop
# and denoiser policy (Corona-parity round: renders auto-finish at 3%
# noise, samples value is only a safety backstop, and every render
# carries a DENOISED pass).
EXTRA_EXPECTED = [
    ("halt.enable", True),
    ("halt.use_samples", True),
    ("halt.samples", 4096),
    ("halt.use_noise_level", True),
    ("halt.noise_level", 3.0),
    ("denoiser.enabled", True),
    ("denoiser.type", "OIDN"),
    ("denoiser.oidn_mode", "COMPONENTS"),
    ("denoiser.periodic_refresh", True),
]


# R3: on a fresh scene the export must leave these to the engine - either
# unset (the engine's own default or auto gate decides) or equal to the
# engine default (src/slg/engines/pathtracer.cpp, sobolsampler.cpp,
# film noise estimation). None = must not be exported.
ENGINE_PARITY = [
    ("path.mnee.enable", None),
    ("path.guiding.enable", None),
    ("path.clamping.variance.maxvalue", None),
    ("sampler.sobol.owen.enable", False),
    ("sampler.sobol.bluenoise.enable", True),
    ("sampler.sobol.adaptive.strength", 0.95),
    ("sampler.sobol.adaptive.relerr", 0.02),
    ("film.noiseestimation.warmup", 32),
    ("film.noiseestimation.step", 32),
    ("path.hybridbackforward.connectprob", 0.5),
    ("path.hybridbackforward.glossinessthreshold", 0.05),
    # R2: Cycles parity (Blender's 12/4/4 bounces count vertices + 1)
    ("path.pathdepth.total", 13),
    ("path.pathdepth.diffuse", 5),
    ("path.pathdepth.glossy", 5),
    ("path.pathdepth.specular", 12),
]

# Light-pass share: the CPU split and the GPU light-task fraction
ENGINE_PARITY_DEVICE = {
    "CPU": [("path.hybridbackforward.partition", 0.8)],
    "OCL": [("path.lighttracing.taskfraction", 0.25)],
}


def check_export(scene):
    from importlib import import_module
    export_config = import_module(addon_key() + ".export.config")
    config = scene.superluxcore.config
    device = config.device
    for dev, extra in ENGINE_PARITY_DEVICE.items():
        config.device = dev
        # No exporter: the AOV pass setup logs a caught traceback, the
        # render config itself is complete
        _check_export_props(export_config.convert(None, scene), dev,
                            ENGINE_PARITY + extra)
    config.device = device


def _check_export_props(props, dev, expectations):
    names = set(props.GetAllNames())
    for key, expected in expectations:
        key_label = f"{key} [{dev}]"
        if expected is None:
            check(f"export {key_label} unset", key in names, False)
            continue
        if key not in names:
            check(f"export {key_label}", None, expected)
            continue
        prop = props.Get(key)
        if isinstance(expected, bool):
            actual = prop.GetBool()
        elif isinstance(expected, float):
            actual = prop.GetFloat()
            expected = float(expected)
            ok = math.isclose(actual, expected, rel_tol=1e-5)
            RESULTS.append((f"export {key_label}", ok))
            print(f"[E49-TEST] {'ok' if ok else 'FAIL'}: export {key_label} "
                  f"= {actual!r} (expected {expected!r})", flush=True)
            continue
        else:
            actual = prop.GetInt()
        check(f"export {key_label}", actual, expected)


def main():
    ensure_superluxcore()
    scene = bpy.context.scene
    config = scene.superluxcore.config

    for dotted, expected in EXPECTED:
        obj = config
        for part in dotted.split("."):
            obj = getattr(obj, part)
        check(dotted, obj, expected)

    for dotted, expected in EXTRA_EXPECTED:
        obj = scene.superluxcore
        for part in dotted.split("."):
            obj = getattr(obj, part)
        check(dotted, obj, expected)

    check_export(scene)

    failed = [name for name, ok in RESULTS if not ok]
    print(f"[E49-TEST] {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("[E49-TEST] FAILURES:", ", ".join(failed))
        sys.exit(1)
    print("[E49-TEST] PASS")


main()
