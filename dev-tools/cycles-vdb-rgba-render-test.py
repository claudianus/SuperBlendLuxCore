"""Actual Blender 720p RGBA volume-attribute postfilter diagnostics.

The separately authored rgba-postfilter.vdb has zero RGBA background and
active integer samples [0,31]^3 at voxel size 1/16, translation (-1,-1,-1).
Four known x strips exercise positive, zero, and sub-threshold alpha. Four
unchanged Cycles materials read Color, Vector, Fac, and Alpha into volume
emission. The oracle samples the known cardinal kernels before applying the
Cycles alpha guard; neither exported densitygrid definitions nor bboxes are
used to obtain expected values. The caller owns process bounds and cleanup.

SLC_VDB_RGBA_NATIVE_ONLY=1 explicitly tests the native extension against the
independent oracle when Blender's external VDB loader rejects custom Vec4f.
That mode records the unavailable Cycles reference and proves no Cycles parity.
"""

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import time

import bpy
import numpy as np
import pysuperluxcore


# The caller must set all three paths before Blender starts: a factory
# profile with production EXTENSIONS can cause its wheel manager to purge
# disabled extensions' dependencies. This check cannot repair startup paths.
isolated_resources = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
for resource_kind, directory in (("CONFIG", "config"), ("EXTENSIONS", "extensions")):
    isolated_path = Path(os.environ["BLENDER_USER_" + resource_kind]).resolve()
    assert isolated_path == isolated_resources / directory
    assert Path(bpy.utils.user_resource(resource_kind)).resolve() == isolated_path


WIDTH, HEIGHT = 1280, 720
ORTHO_WIDTH = 10.0
ORTHO_HEIGHT = ORTHO_WIDTH * HEIGHT / WIDTH
VOXEL_SIZE = 0.0625
EMISSION_SCALE = 0.25
ALPHA_GUARD = float(np.float32(1.e-6))
STRIP_RGBA = np.array([
    [0.125, 0.25, 0.5, 0.5],
    [0.0, 0.0, 0.0, 0.0],
    [1.e-7, 2.e-7, 4.e-7, 5.e-7],
    [0.125, 0.25, 0.5, 0.25],
], dtype=np.float32).astype(np.float64)
PANELS = [("Color", -3.75), ("Vector", -1.25), ("Fac", 1.25), ("Alpha", 3.75)]
PROFILE_MAE_LIMIT = 0.012
PROFILE_MAX_LIMIT = 0.04
CYCLES_PROFILE_MAE_LIMIT = 0.018
CYCLES_PROFILE_MAX_LIMIT = 0.05
GUARD_PATCH_ABS_LIMIT = 0.006
PROFILE_MIN_ROWS = 80
Y_EDGE_STEPS_PER_VOXEL = 8192
PROFILE_PIXEL_STEPS = 16384
PROFILE_CONVERGENCE_STEPS = 4096
PROFILE_QUADRATURE_ERROR_LIMIT = 0.0001

folder = Path(os.environ["SUPERLUXCORE_AUDIT_DIR"])
folder.mkdir(parents=True, exist_ok=True)
fixture = Path(os.environ["SLC_VDB_FIXTURES"]) / "rgba-postfilter.vdb"
assert fixture.is_file(), fixture
samples = int(os.environ.get("SLC_VDB_SAMPLES", "64"))
assert 32 <= samples <= 256
native_only = os.environ.get("SLC_VDB_RGBA_NATIVE_ONLY") == "1"
package = next(addon.module for addon in bpy.context.preferences.addons
               if addon.module.endswith(".superluxcore") or addon.module == "superluxcore")
reader = importlib.import_module(package + ".export.cycles_node_reader")
volume_export = importlib.import_module(package + ".export.volume")
pipeline_export = importlib.import_module(package + ".export.imagepipeline")
errors = importlib.import_module(package + ".utils.errorlog").SuperLuxCoreErrorLog


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def graph_hash(material):
    nodes = []
    for node in material.node_tree.nodes:
        inputs = []
        for socket in node.inputs:
            if not hasattr(socket, "default_value"):
                continue
            value = socket.default_value
            if not isinstance(value, (float, int, bool, str)):
                value = list(value)
            inputs.append([socket.identifier, value])
        nodes.append([node.name, node.bl_idname, getattr(node, "attribute_name", None),
                      getattr(node, "operation", None), inputs])
    links = sorted([link.from_node.name, link.from_socket.identifier,
                    link.to_node.name, link.to_socket.identifier]
                   for link in material.node_tree.links)
    return hashlib.sha256(json.dumps({
        "nodes": sorted(nodes), "links": links,
        "interpolation": material.cycles.volume_interpolation,
    }, sort_keys=True).encode()).hexdigest()


def kernel(distance, interpolation):
    distance = np.abs(np.asarray(distance, dtype=np.float64))
    if interpolation == "LINEAR":
        return np.maximum(1. - distance, 0.)
    return np.where(distance < 1., (4. - 6. * distance ** 2 + 3. * distance ** 3) / 6.,
                    np.where(distance < 2., (2. - distance) ** 3 / 6., 0.))


def sample_axis(index_coordinate, interpolation, rgba=False):
    coordinate = np.asarray(index_coordinate, dtype=np.float64)
    base = np.floor(coordinate)
    result = np.zeros((*coordinate.shape, 4), dtype=np.float64) if rgba else np.zeros_like(coordinate)
    for offset in ((0, 1) if interpolation == "LINEAR" else (-1, 0, 1, 2)):
        voxel = base + offset
        active = (voxel >= 0) & (voxel <= 31)
        weight = kernel(coordinate - voxel, interpolation) * active
        if rgba:
            # Inactive samples remain zero; clamping only makes array indexing
            # safe and does not alter their zero interpolation weight.
            strip = np.clip(voxel.astype(np.int64), 0, 31) // 8
            result += weight[..., None] * STRIP_RGBA[strip]
        else:
            result += weight
    return result


def y_integrator(interpolation):
    # A constant 32-sample field has a plateau and two mirrored kernel edges.
    # Midpoint integration resolves only the independent lower edge. This
    # permits evaluating the alpha guard exactly per sampled edge value while
    # avoiding a per-pixel 3D temporary array.
    pad, plateau_start, plateau_length = (1, 0, 31) if interpolation == "LINEAR" else (2, 1, 29)
    edge_length = pad + plateau_start
    count = edge_length * Y_EDGE_STEPS_PER_VOXEL
    edge_positions = -pad + (np.arange(count, dtype=np.float64) + .5) * edge_length / count
    factors = sample_axis(edge_positions, interpolation)
    assert np.all(np.diff(factors) >= -1e-14)
    prefix = np.concatenate([[0.], np.cumsum(factors, dtype=np.float64)])
    edge_step_world = edge_length / count * VOXEL_SIZE
    plateau_world = plateau_length * VOXEL_SIZE
    integral = plateau_world + 2. * prefix[-1] * edge_step_world
    assert abs(integral - 32. * VOXEL_SIZE) < 1e-7

    def integrate(raw_rgba):
        alpha = raw_rgba[..., 3]
        rgb = raw_rgba[..., :3]
        positive = alpha > 0.
        threshold = np.divide(ALPHA_GUARD, alpha, out=np.full_like(alpha, np.inf), where=positive)
        invalid_count = np.searchsorted(factors, threshold, side="right")
        plateau_valid = alpha > ALPHA_GUARD
        valid_measure = (plateau_valid * plateau_world
                         + 2. * (count - invalid_count) * edge_step_world)
        invalid_integral = ((~plateau_valid) * plateau_world
                            + 2. * prefix[invalid_count] * edge_step_world)
        unpremultiplied = np.divide(rgb, alpha[..., None], out=np.zeros_like(rgb), where=positive[..., None])
        color = unpremultiplied * valid_measure[..., None] + rgb * invalid_integral[..., None]
        return color, alpha * integral

    return integrate, {"edge_midpoint_steps_per_voxel": Y_EDGE_STEPS_PER_VOXEL,
                       "y_kernel_world_integral": float(integral),
                       "plateau_world_length": plateau_world,
                       "carrier_source": "Cycles cardinal support: min-pad, inclusive-max+pad"}


def oracle_checks(interpolation, integrate):
    # Pure strip interiors independently fix each output's meaning and guard.
    centers = np.array([3., 11., 19., 27.])
    raw = sample_axis(centers, interpolation, rgba=True)
    assert np.allclose(raw, STRIP_RGBA, rtol=1e-12, atol=1e-15)
    color, alpha = integrate(raw)
    assert np.allclose(color[1], STRIP_RGBA[1, :3] * 2., atol=1e-12)
    assert np.allclose(color[2], STRIP_RGBA[2, :3] * 2., atol=1e-12)
    assert np.allclose(alpha, STRIP_RGBA[:, 3] * 2., atol=1e-7)
    # Divide-first produces an observably different result across adjacent
    # positive/zero and positive/small-alpha strips. This is a rejection
    # witness fixed before any render, not an implementation-derived oracle.
    positions = np.array([7.5, 23.5])
    filtered = sample_axis(positions, interpolation, rgba=True)
    actual_color, _ = integrate(filtered)
    divided_voxels = STRIP_RGBA[:, :3].copy()
    mask = STRIP_RGBA[:, 3] > ALPHA_GUARD
    divided_voxels[mask] /= STRIP_RGBA[mask, 3, None]
    wrong = np.zeros((2, 3), dtype=np.float64)
    base = np.floor(positions)
    for offset in ((0, 1) if interpolation == "LINEAR" else (-1, 0, 1, 2)):
        voxel = base + offset
        wrong += kernel(positions - voxel, interpolation)[:, None] * divided_voxels[voxel.astype(int) // 8]
    wrong *= 2.
    gap = float(np.abs(actual_color - wrong).max())
    assert gap > .25, (interpolation, "oracle cannot reject divide-before-filter", gap)
    result = {"strip_center_raw_rgba": raw.tolist(), "strip_center_color_y_integrals": color.tolist(),
              "strip_center_alpha_y_integrals": alpha.tolist(), "divide_before_filter_rejection_gap": gap}
    if interpolation == "CUBIC":
        # At index x in [22,23], the first positive-alpha voxel contributes
        # (x-22)^3/6. The authored alpha guard therefore crosses inside a
        # camera pixel. Its finite plateau jump requires converged footprint
        # integration; four midpoint samples can alias it by more than .04.
        small_alpha, positive_alpha = STRIP_RGBA[2, 3], STRIP_RGBA[3, 3]
        crossing = 22. + ((ALPHA_GUARD - small_alpha) * 6.
                          / (positive_alpha - small_alpha)) ** (1. / 3.)
        at_crossing = sample_axis(crossing, interpolation, rgba=True)
        assert abs(at_crossing[3] - ALPHA_GUARD) < 1e-15
        result["analytic_alpha_guard_crossing_index_x"] = float(crossing)
        result["analytic_alpha_guard_crossing_world_x"] = float(crossing * VOXEL_SIZE - 1.)
    return result


def footprint_profile(local_x, interpolation, integrate, steps):
    # Stream a small 1D quadrature buffer. Constant-z interior profiles need
    # no 2D supersampled image, and retain exact independent y integration.
    color = np.zeros((len(local_x), 3), dtype=np.float64)
    alpha = np.zeros(len(local_x), dtype=np.float64)
    for first in range(0, steps, 64):
        offsets = ((np.arange(first, min(first + 64, steps), dtype=np.float64) + .5)
                   / steps - .5) * ORTHO_WIDTH / WIDTH
        raw = sample_axis((local_x[:, None] + offsets[None, :] + 1.) / VOXEL_SIZE,
                          interpolation, rgba=True)
        rgb, a = integrate(raw)
        color += rgb.sum(axis=1) * EMISSION_SCALE / steps
        alpha += a.sum(axis=1) * EMISSION_SCALE / steps
    return color, alpha


def expected_image(interpolation):
    integrate, check = y_integrator(interpolation)
    check.update(oracle_checks(interpolation, integrate))
    xs = ((np.arange(WIDTH, dtype=np.float64) + .5) / WIDTH - .5) * ORTHO_WIDTH
    zs = ((np.arange(HEIGHT, dtype=np.float64) + .5) / HEIGHT - .5) * ORTHO_HEIGHT
    result = np.zeros((HEIGHT, WIDTH, 3), dtype=np.float64)
    offsets = (-.375, -.125, .125, .375)
    for dz in offsets:
        z_factor = sample_axis((zs + dz * ORTHO_HEIGHT / HEIGHT + 1.) / VOXEL_SIZE, interpolation)
        for dx in offsets:
            for socket, center in PANELS:
                raw_x = sample_axis((xs + dx * ORTHO_WIDTH / WIDTH - center + 1.) / VOXEL_SIZE,
                                    interpolation, rgba=True)
                raw = z_factor[:, None, None] * raw_x[None, :, :]
                color, alpha = integrate(raw)
                if socket in {"Color", "Vector"}:
                    value = color
                elif socket == "Fac":
                    value = np.repeat(color.mean(axis=2, keepdims=True), 3, axis=2)
                else:
                    value = np.repeat(alpha[..., None], 3, axis=2)
                result += EMISSION_SCALE * value / 16.
    rows = np.flatnonzero(np.abs(zs + .03125) < .4)
    # Every pixel footprint in these rows stays within the constant-z
    # plateau. Thus a 1D converged x integral is the exact profile oracle.
    for edge in (-.5, .5):
        z_factor = sample_axis((zs[rows] + edge * ORTHO_HEIGHT / HEIGHT + 1.) / VOXEL_SIZE,
                               interpolation)
        assert np.allclose(z_factor, 1., rtol=0., atol=1e-14)
    convergence = []
    for socket, center in PANELS:
        selection = np.flatnonzero(np.abs(xs - center + .03125) < 1.14)
        local_x = xs[selection] - center
        color, alpha = footprint_profile(local_x, interpolation, integrate, PROFILE_PIXEL_STEPS)
        coarse_color, coarse_alpha = footprint_profile(local_x, interpolation, integrate,
                                                       PROFILE_CONVERGENCE_STEPS)
        error = max(float(np.abs(color - coarse_color).max()),
                    float(np.abs(alpha - coarse_alpha).max()))
        assert error <= PROFILE_QUADRATURE_ERROR_LIMIT, (interpolation, socket, error)
        value = (color if socket in {"Color", "Vector"}
                 else np.repeat(color.mean(axis=1, keepdims=True), 3, axis=1) if socket == "Fac"
                 else np.repeat(alpha[:, None], 3, axis=1))
        result[rows[:, None], selection[None, :], :] = value[None, :, :]
        convergence.append({"socket": socket, "max_absolute_difference": error,
                            "limit": PROFILE_QUADRATURE_ERROR_LIMIT})
    check["full_frame_pixel_midpoint_grid"] = [4, 4]
    check["full_frame_error_is_diagnostic_only"] = True
    check["gated_profile_pixel_midpoint_steps"] = PROFILE_PIXEL_STEPS
    check["profile_comparison_midpoint_steps"] = PROFILE_CONVERGENCE_STEPS
    check["profile_z_footprint_is_constant_one"] = True
    check["profile_quadrature_convergence"] = convergence
    return xs, zs, result, check


def profile_comparison(pixels, expected, xs, zs, label, compare_cycles=False):
    rows = np.flatnonzero(np.abs(zs + .03125) < .4)
    assert len(rows) >= PROFILE_MIN_ROWS
    profiles = []
    for socket, center in PANELS:
        selection = np.flatnonzero(np.abs(xs - center + .03125) < 1.14)
        actual = pixels[rows][:, selection].mean(axis=0, dtype=np.float64)
        target = expected[rows][:, selection].mean(axis=0, dtype=np.float64)
        error = np.abs(actual - target)
        local_x = xs[selection] - center
        patches = []
        for name, lower, upper in (("positive-alpha", -.88, -.63),
                                   ("zero-alpha-guard", -.38, -.13),
                                   ("small-alpha-guard", .12, .37),
                                   ("small-positive-transition", .43, .49),
                                   ("positive-alpha-quarter", .62, .87)):
            patch = (local_x >= lower) & (local_x <= upper)
            assert patch.any(), (name, local_x)
            got, want = actual[patch].mean(axis=0), target[patch].mean(axis=0)
            absolute = float(np.abs(got - want).max())
            patch_limit = GUARD_PATCH_ABS_LIMIT if name.endswith("guard") else PROFILE_MAX_LIMIT
            if compare_cycles:
                patch_limit *= 1.5
            patches.append({"name": name, "actual_rgb": got.tolist(), "target_rgb": want.tolist(),
                            "max_absolute_error": absolute, "limit": patch_limit,
                            "passed": absolute <= patch_limit})
        item = {"socket": socket, "panel_center_world_x": center, "rows": len(rows),
                "profile_mae": float(error.mean()), "profile_max_error": float(error.max()),
                "mae_limit": CYCLES_PROFILE_MAE_LIMIT if compare_cycles else PROFILE_MAE_LIMIT,
                "max_limit": CYCLES_PROFILE_MAX_LIMIT if compare_cycles else PROFILE_MAX_LIMIT,
                "guard_and_transition_patches": patches}
        item["passed"] = (item["profile_mae"] <= item["mae_limit"]
                          and item["profile_max_error"] <= item["max_limit"]
                          and all(patch["passed"] for patch in patches))
        profiles.append({**item, "local_x_world": local_x.tolist(),
                         "actual_profile_rgb": actual.tolist(), "target_profile_rgb": target.tolist()})
    path = folder / (label + "-profiles.json")
    path.write_text(json.dumps(profiles, indent=2) + "\n")
    return {"kind": "unchanged-cycles-raw-rgba-profiles" if compare_cycles else "independent-postfilter-emission-integral",
            "panels": [{key: value for key, value in item.items()
                        if key not in {"local_x_world", "actual_profile_rgb", "target_profile_rgb"}}
                       for item in profiles], "profile_path": str(path),
            "full_frame_mae_diagnostic": float(np.abs(pixels - expected).mean()),
            "passed": all(item["passed"] for item in profiles)}


bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.world = bpy.data.worlds.new("RGBA emission black world")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0
bpy.ops.object.camera_add(location=(0, -7, 0))
scene.camera = bpy.context.object
scene.camera.rotation_euler = (math.pi / 2, 0, 0)
scene.camera.data.type = "ORTHO"
scene.camera.data.sensor_fit = "HORIZONTAL"
scene.camera.data.ortho_scale = ORTHO_WIDTH
scene.render.resolution_x, scene.render.resolution_y = WIDTH, HEIGHT
scene.render.resolution_percentage = 100
scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
scene.render.threads_mode, scene.render.threads = "FIXED", 4
scene.render.film_transparent = False
scene.render.image_settings.color_mode = "RGB"
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure, scene.view_settings.gamma = 0, 1
scene.cycles.device, scene.cycles.samples = "CPU", samples
scene.cycles.use_denoising = scene.cycles.use_adaptive_sampling = False
bpy.context.preferences.filepaths.save_version = 0
materials, volumes, host_loader_records, attribute_socket_records = [], [], [], []
for socket, center in PANELS:
    material = bpy.data.materials.new("Authored RGBA " + socket)
    material.use_nodes = True
    material.node_tree.nodes.clear()
    output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
    attribute = material.node_tree.nodes.new("ShaderNodeAttribute")
    attribute.attribute_name = "rgba"
    attribute_socket_records.append({"requested_socket": socket,
                                     "display_name": attribute.outputs[socket].name,
                                     "identifier": attribute.outputs[socket].identifier})
    emission = material.node_tree.nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = EMISSION_SCALE
    if socket in {"Color", "Vector"}:
        material.node_tree.links.new(attribute.outputs[socket], emission.inputs["Color"])
    else:
        multiply = material.node_tree.nodes.new("ShaderNodeMath")
        multiply.operation = "MULTIPLY"
        multiply.inputs[1].default_value = EMISSION_SCALE
        material.node_tree.links.new(attribute.outputs[socket], multiply.inputs[0])
        material.node_tree.links.new(multiply.outputs[0], emission.inputs["Strength"])
        emission.inputs["Color"].default_value = (1, 1, 1, 1)
    material.node_tree.links.new(emission.outputs[0], output.inputs["Volume"])
    data = bpy.data.volumes.new("Known RGBA " + socket)
    data.filepath = str(fixture)
    load_result = data.grids.load()
    host_loader_records.append({"socket": socket, "load_result": bool(load_result),
                                "is_loaded": data.grids.is_loaded,
                                "error_message": data.grids.error_message,
                                "grids": [{"name": grid.name, "data_type": grid.data_type,
                                           "channels": grid.channels} for grid in data.grids]})
    data.materials.append(material)
    data.render.space, data.render.precision, data.render.clipping = "WORLD", "FULL", 0
    volume = bpy.data.objects.new("RGBA " + socket, data)
    volume.location.x = center
    scene.collection.objects.link(volume)
    materials.append(material)
    volumes.append(volume)

slc = scene.superluxcore
spectral_before = slc.config.spectral_enable
assert spectral_before, "Load the production spectral default before RGB diagnostics"
native_cpu_before = slc.devices.use_native_cpu
gpu_backend_before = bpy.context.preferences.addons[package].preferences.gpu_backend
slc.config.engine = "PATH"
slc.config.path.use_clamping = slc.config.path.auto_clamping = False
slc.halt.enable = slc.halt.use_samples = True
slc.halt.samples = samples
slc.halt.use_noise_level = slc.halt.use_noise_thresh = False
slc.denoiser.enabled = False
bpy.context.view_layer.update()
frame = scene.camera.data.view_frame(scene=scene)
assert abs(max(p.x for p in frame) - ORTHO_WIDTH / 2.) < 1e-6
assert abs(min(p.x for p in frame) + ORTHO_WIDTH / 2.) < 1e-6
assert abs(max(p.y for p in frame) - ORTHO_HEIGHT / 2.) < 1e-6
assert abs(min(p.y for p in frame) + ORTHO_HEIGHT / 2.) < 1e-6
pipeline = pipeline_export.convert(scene)
plugins = []
for name in pipeline.GetAllNames("film.imagepipelines.000."):
    if name.endswith(".type"):
        kind = pipeline.Get(name).GetString()
        assert kind in {"NOP", "TONEMAP_LINEAR"}, (name, kind)
        if kind == "TONEMAP_LINEAR":
            assert pipeline.Get(name[:-4] + "scale").GetFloat() == 1.
        plugins.append(kind)
assert plugins
native_module = getattr(pysuperluxcore, "pysuperluxcore", pysuperluxcore)
metrics = {"complete": False, "passed": False, "records": [], "comparisons": [],
           "resolution": [WIDTH, HEIGHT], "samples": samples, "cpu_threads": 4,
           "fixture": str(fixture), "fixture_sha256": sha(fixture),
           "native_sha256": sha(native_module.__file__), "reader_sha256": sha(reader.__file__),
           "volume_export_sha256": sha(volume_export.__file__), "harness_sha256": sha(__file__),
           "blender_version": bpy.app.version_string, "blender_build_hash": bpy.app.build_hash.decode(),
           "default_spectral_before": spectral_before, "default_spectral_restored": False,
           "native_pixel_filter": {"enabled": slc.config.filter_enabled,
                                   "type": slc.config.filter, "width": slc.config.filter_width},
           "cycles_volume_biased": getattr(scene.cycles, "volume_biased", None),
           "native_identity_imagepipeline_plugins": plugins,
           "native_imagepipeline_properties": pipeline.ToString(),
           "combined_exr_is_scene_linear_rgb": True,
           "oracle": {"active_indices_inclusive": [[0, 0, 0], [31, 31, 31]],
                      "rgba_x_strips_float32": STRIP_RGBA.tolist(), "background_rgba": [0, 0, 0, 0],
                      "voxel_size": VOXEL_SIZE, "translation": [-1, -1, -1],
                      "alpha_guard": ALPHA_GUARD, "emission_scale": EMISSION_SCALE,
                      "exported_bbox_used": False, "pixel_quadrature": [4, 4]},
           "scope": "RGBA Color/Vector/Fac/Alpha RGB diagnostic via actual RenderEngine",
           "native_only_requested": native_only,
           "authored_attribute_sockets": attribute_socket_records,
           "cycles_reference": {"requested": not native_only,
                                "reference_unavailable": any(not record["load_result"] for record in host_loader_records),
                                "reason": "Blender external VDB loader rejects custom Vec4f" if
                                          any(not record["load_result"] for record in host_loader_records) else None,
                                "host_loader_records": host_loader_records},
           "full_cycles_parity_verified": False,
           "production_convergence_acceptance": False, "full_goal_complete": False}


def save_metrics():
    (folder / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")


def state_dict():
    return {
        "graphs": [graph_hash(material) for material in materials],
        "volume_matrices": [[list(row) for row in volume.matrix_world] for volume in volumes],
        "volume_filepaths": [str(Path(bpy.path.abspath(volume.data.filepath,
                                                       library=volume.data.library)).resolve())
                             for volume in volumes],
        "volume_render_settings": [[volume.data.render.space, volume.data.render.precision,
                                    volume.data.render.clipping] for volume in volumes],
        "camera_matrix": [list(row) for row in scene.camera.matrix_world],
        "camera_ortho_scale": scene.camera.data.ortho_scale,
    }


def state_hash():
    return hashlib.sha256(json.dumps(state_dict(), sort_keys=True).encode()).hexdigest()


def render_frame(label, engine, device):
    scene.render.engine = engine
    if engine == "SUPERLUXCORE":
        slc.config.device, slc.config.spectral_enable = device, False
        slc.devices.use_native_cpu = False if device == "OCL" else native_cpu_before
        if device == "OCL":
            bpy.context.preferences.addons[package].preferences.gpu_backend = "METAL"
    errors.clear(False)
    scene.render.image_settings.file_format, scene.render.image_settings.color_depth = "OPEN_EXR", "32"
    exr = folder / (label + ".exr")
    scene.render.filepath = str(exr)
    start = time.monotonic()
    bpy.ops.render.render(write_still=True)
    elapsed = time.monotonic() - start
    assert exr.is_file(), label
    image = bpy.data.images.load(str(exr), check_existing=False)
    try:
        assert tuple(image.size) == (WIDTH, HEIGHT)
        pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(HEIGHT, WIDTH, 4)[..., :3].copy()
    finally:
        bpy.data.images.remove(image)
    assert np.isfinite(pixels).all(), (label, "nonfinite raw RGB")
    scene.render.image_settings.file_format, scene.render.image_settings.color_depth = "PNG", "8"
    png = folder / (label + ".png")
    bpy.data.images["Render Result"].save_render(str(png), scene=scene)
    eye_spp = light_spp = None
    if engine == "SUPERLUXCORE":
        stats = slc.statistics.get_active()
        eye_spp, light_spp = int(stats.samples_eye.value), int(stats.samples_light_tracing.value)
        assert eye_spp >= samples, (label, eye_spp, samples)
        assert not errors.errors, (label, errors.errors)
    return pixels, {"label": label, "engine": engine, "device": device,
                    "backend": "METAL" if device == "OCL" else "CPU", "spectral": False,
                    "native_cpu_enabled": slc.devices.use_native_cpu if engine == "SUPERLUXCORE" else None,
                    "actual_eye_spp": eye_spp, "actual_light_spp": light_spp,
                    "raw_rgb_exr": str(exr), "raw_rgb_exr_sha256": sha(exr),
                    "png": str(png), "png_sha256": sha(png), "elapsed_seconds": elapsed,
                    "finite": True, "raw_rgb_min": float(pixels.min()), "raw_rgb_max": float(pixels.max()),
                    "render_engine_operator": "bpy.ops.render.render(write_still=True)"}


save_metrics()
cases = os.environ.get("SLC_VDB_RGBA_CASES", "linear,cubic").split(",")
assert cases and all(case in {"linear", "cubic"} for case in cases)
modes = ([("SUPERLUXCORE", "CPU"), ("SUPERLUXCORE", "OCL")] if native_only else
         [("CYCLES", "CPU"), ("SUPERLUXCORE", "CPU"), ("SUPERLUXCORE", "OCL")])
if os.environ.get("SLC_VDB_CPU_ONLY") == "1":
    modes = [mode for mode in modes if mode[1] == "CPU"]
if os.environ.get("SLC_VDB_GPU_ONLY") == "1":
    modes = [mode for mode in modes if mode[0] == "CYCLES" or mode[1] == "OCL"]
try:
    assert native_only or not metrics["cycles_reference"]["reference_unavailable"], (
        "Cycles reference unavailable: Blender cannot load the authored external Vec4f VDB; "
        "use explicit SLC_VDB_RGBA_NATIVE_ONLY=1 for independent native diagnostics",
        metrics["cycles_reference"])
    for case in cases:
        interpolation = case.upper()
        for material in materials:
            material.cycles.volume_interpolation = interpolation
        bpy.context.view_layer.update()
        state_before = state_dict()
        authored = state_hash()
        xs, zs, expected, check = expected_image(interpolation)
        metrics.setdefault("oracle_checks", {})[case] = check
        scene.render.engine, slc.config.spectral_enable = "CYCLES", spectral_before
        bpy.ops.wm.save_as_mainfile(filepath=str(folder / (case + ".blend")))
        cycles_pixels = None
        for engine, device in modes:
            label = case + "-" + engine.lower() + "-" + device.lower() + "-rgba-rgb"
            pixels, record = render_frame(label, engine, device)
            state_after = state_dict()
            if state_after != state_before:
                failure = {"label": label, "before": state_before, "after": state_after,
                           "changed_fields": [key for key in state_before if state_before[key] != state_after[key]]}
                metrics.setdefault("authored_state_failures", []).append(failure)
                save_metrics()
                raise AssertionError((label, "authored state or field file changed", failure))
            assert state_hash() == authored
            record.update({"case": case, "interpolation": interpolation,
                           "authored_state_sha256": authored, "authored_state_unchanged": True,
                           "analytic": profile_comparison(pixels, expected, xs, zs, label)})
            if engine == "CYCLES":
                cycles_pixels = pixels
            elif not native_only:
                assert cycles_pixels is not None
                comparison = profile_comparison(pixels, cycles_pixels, xs, zs,
                                                label + "-vs-cycles", compare_cycles=True)
                metrics["comparisons"].append({"case": case, "device": device, **comparison})
            record["passed"] = record["analytic"]["passed"] and (
                native_only or engine == "CYCLES" or metrics["comparisons"][-1]["passed"])
            record["cycles_reference_available"] = not metrics["cycles_reference"]["reference_unavailable"]
            record["cycles_parity_verified"] = not native_only and engine != "CYCLES" and record["passed"]
            metrics["records"].append(record)
            save_metrics()
            print("VDB_RGBA_RENDER", label, "PASS" if record["passed"] else "FAIL", flush=True)
            assert record["passed"], (label, record["analytic"])
            if engine != "CYCLES":
                del pixels
        del expected, cycles_pixels
    metrics["complete"] = True
    metrics["passed"] = all(record["passed"] for record in metrics["records"])
    metrics["full_cycles_parity_verified"] = not native_only and metrics["passed"]
finally:
    slc.config.spectral_enable = spectral_before
    slc.devices.use_native_cpu = native_cpu_before
    bpy.context.preferences.addons[package].preferences.gpu_backend = gpu_backend_before
    metrics["default_spectral_restored"] = slc.config.spectral_enable == spectral_before
    metrics["native_cpu_preference_restored"] = slc.devices.use_native_cpu == native_cpu_before
    metrics["gpu_backend_restored"] = bpy.context.preferences.addons[package].preferences.gpu_backend == gpu_backend_before
    save_metrics()

print("VDB_RGBA_RENDER_COMPLETE_REQUIRES_DIRECT_REVIEW", len(metrics["records"]), flush=True)
