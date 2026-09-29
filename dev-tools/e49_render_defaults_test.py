# SPDX-License-Identifier: Apache-2.0
#
# E49: regression test — pins the curated render-config defaults decided
# in the 2026-09 defaults pass. A fresh scene must expose exactly these
# values; any accidental revert or property rename fails loudly.
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
    ("path.depth_total", 24),
    ("path.depth_diffuse", 8),
    ("path.depth_glossy", 8),
    ("path.depth_specular", 24),
    # hybrid light tracing
    ("path.hybridbackforward_enable", True),
    ("path.hybridbackforward_lightpartition", 25.0),
    ("path.hybridbackforward_lightpartition_opencl", 25.0),
    ("path.hybridbackforward_glossinessthresh", 0.049),
    ("path.hybridbackforward_adaptivecaustic", True),
    ("path.hybridbackforward_terminalglossiness", 0.3),
    ("path.hybridbackforward_connectprob", 0.3),
    ("path.lighttracing_only", False),
    ("path.lighttracing_focus", True),
    ("path.lighttracing_focus_ratio", 70.0),
    ("path.lighttracing_focus_radius", 0.02),
    # vertex connection
    ("path.vertex_connection", True),
    ("path.vertex_connection_connects", 4),
    ("path.vertex_connection_pool", 4),
    ("path.vertex_connection_adaptive", True),
    ("path.vertex_connection_merge_radius", 0.001),
    ("path.vertex_connection_reuse", True),
    # clamping
    ("path.use_clamping", True),
    ("path.auto_clamping", False),
    ("path.clamping", 1000.0),
    ("path.clamp_scope", "INDIRECT"),
    ("path.clamp_adaptive", True),
    ("path.clamp_sigma", 4.0),
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
    ("sobol_adaptive_strength", 0.9),
    ("sobol_bluenoise_enable", True),
    ("sobol_owen_enable", True),
    ("sobol_owen_tile_enable", True),
    ("sobol_adaptive_moments_enable", True),
    ("sobol_adaptive_relerr", 0.01),
    # noise estimation
    ("noise_estimation.warmup", 16),
    ("noise_estimation.step", 16),
    # metropolis
    ("metropolis_largesteprate", 30.0),
    ("metropolis_maxconsecutivereject", 1024),
    ("metropolis_imagemutationrate", 5.0),
    # pixel filter
    ("filter_enabled", False),
    ("filter", "BLACKMANHARRIS"),
    ("filter_width", 2.0),
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
    # MNEE (default on: caustics resolve out of the box, ~zero cost
    # without delta occluders)
    ("mnee_enable", True),
    ("mnee_maxspecular", 2),
    ("mnee_maxiterations", 64),
    ("mnee_seedcache", True),
    # path guiding
    ("guiding_enable", True),
    ("guiding_ris_k", 2),
    ("guiding_strength", 1.0),
    ("guiding_diffuse", False),
    ("guiding_min_depth", 2),
    ("guiding_glossy_threshold", 0.5),
    ("guiding_warmup", 128),
    ("guiding_components", 4),
    ("guiding_freeze", False),
    ("guiding_split", 0.004),
    ("guiding_max_depth", 10),
    ("guiding_max_leaves", 16384),
    ("guiding_swaprecords", 500000),
    ("guiding_debug", False),
    ("portal_weight", 0.7),
    # spectral
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
    ("photongi.caustic_enabled", False),
    ("photongi.caustic_maxsize", 0.1),
    ("photongi.caustic_lookup_radius", 0.075),
    ("photongi.caustic_normalangle", math.radians(10)),
    ("photongi.caustic_periodic_update", True),
    ("photongi.caustic_updatespp", 16),
    ("photongi.caustic_updatespp_radiusreduction", 90.0),
    ("photongi.caustic_updatespp_minradius", 0.0),  # 0 = automatic
    ("photongi.debug", "off"),
    ("photongi.save_or_overwrite", False),
    # env light cache (default on: learned env visibility, final renders
    # only - V-Ray Adaptive Dome parity)
    ("envlight_cache.enabled", True),
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
    ("use_animated_seed", True),
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
    ("halt.samples", 2048),
    ("halt.use_noise_level", True),
    ("halt.noise_level", 3.0),
    ("denoiser.enabled", True),
    ("denoiser.type", "OIDN"),
    ("denoiser.oidn_mode", "COMPONENTS"),
    ("denoiser.periodic_refresh", True),
]


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

    failed = [name for name, ok in RESULTS if not ok]
    print(f"[E49-TEST] {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("[E49-TEST] FAILURES:", ", ".join(failed))
        sys.exit(1)
    print("[E49-TEST] PASS")


main()
