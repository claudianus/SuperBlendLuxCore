"""Real Blender RenderEngine VDB boundary tests with an independent oracle.

The fixture has density .2 at integer indices [0, 31]^3, background zero,
voxel size 1/16 and translation (-1, -1, -1). Neither the exported bbox nor
the engine's normalized texture definition participates in the oracle.
These RGB, 720p, finite-sample diagnostics do not prove final convergence.
The caller owns the bounded Blender process and its cleanup.
"""

import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import time

import bpy
from mathutils import Matrix
import numpy as np
import pysuperluxcore


# All paths must be set by the caller before Blender starts, including
# EXTENSIONS so factory startup cannot purge production wheel dependencies.
isolated_resources = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
for resource_kind, directory in (("CONFIG", "config"), ("EXTENSIONS", "extensions")):
    isolated_path = Path(os.environ["BLENDER_USER_" + resource_kind]).resolve()
    assert isolated_path == isolated_resources / directory
    assert Path(bpy.utils.user_resource(resource_kind)).resolve() == isolated_path


WIDTH, HEIGHT = 1280, 720
ORTHO_WIDTH = 4.0
ORTHO_HEIGHT = ORTHO_WIDTH * HEIGHT / WIDTH
VOXEL_SIZE = 0.0625
GRID_VALUE = float(np.float32(0.2))
DENSITY_MULTIPLIER = 5.0
SIGMA = DENSITY_MULTIPLIER * GRID_VALUE
Y_INTEGRAL = 32 * VOXEL_SIZE
PROFILE_MAE_LIMIT = 0.008
PROFILE_MAX_LIMIT = 0.03
CONTOUR_WORLD_LIMIT = 0.0125
FULL_FRAME_MAE_SYSTEMATIC_ALLOWANCE = 0.004
FULL_FRAME_MAE_NOISE_MULTIPLIER = 1.5
CYCLES_PROFILE_MAE_LIMIT = 0.012
CYCLES_PROFILE_MAX_LIMIT = 0.04
PROFILE_MIN_ROWS = 160
RGB_CHANNEL_SPREAD_LIMIT = 1e-5

folder = Path(os.environ["SUPERLUXCORE_AUDIT_DIR"])
folder.mkdir(parents=True, exist_ok=True)
fixture = Path(os.environ["SLC_VDB_FIXTURES"]) / "named-attributes.vdb"
assert fixture.is_file(), fixture
samples = int(os.environ.get("SLC_VDB_SAMPLES", "64"))
assert 32 <= samples <= 256, "Boundary profile gates require 32–256 eye samples"
package = next(
    addon.module for addon in bpy.context.preferences.addons
    if addon.module.endswith(".superluxcore") or addon.module == "superluxcore"
)
reader = importlib.import_module(package + ".export.cycles_node_reader")
volume_export = importlib.import_module(package + ".export.volume")
imagepipeline_export = importlib.import_module(package + ".export.imagepipeline")
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
        nodes.append([node.name, node.bl_idname, inputs])
    links = sorted([
        link.from_node.name, link.from_socket.identifier,
        link.to_node.name, link.to_socket.identifier
    ] for link in material.node_tree.links)
    return hashlib.sha256(json.dumps({
        "nodes": sorted(nodes), "links": links,
        "cycles_volume_interpolation": material.cycles.volume_interpolation,
    }, sort_keys=True).encode()).hexdigest()


def cardinal_kernel(distance, interpolation):
    distance = np.abs(np.asarray(distance, dtype=np.float64))
    if interpolation == "LINEAR":
        return np.maximum(1.0 - distance, 0.0)
    # The cardinal cubic B-spline whose four weights are used by Cycles.
    return np.where(
        distance < 1.0,
        (4.0 - 6.0 * distance ** 2 + 3.0 * distance ** 3) / 6.0,
        np.where(distance < 2.0, (2.0 - distance) ** 3 / 6.0, 0.0),
    )


def axis_factor(index_coordinate, interpolation):
    coordinate = np.asarray(index_coordinate, dtype=np.float64)
    # Compact support avoids a 32-by-frame temporary allocation.
    base = np.floor(coordinate)
    result = np.zeros_like(coordinate)
    offsets = (0, 1) if interpolation == "LINEAR" else (-1, 0, 1, 2)
    for offset in offsets:
        voxel = base + offset
        active = (voxel >= 0) & (voxel <= 31)
        result += cardinal_kernel(coordinate - voxel, interpolation) * active
    return result


def verify_oracle():
    checks = []
    for interpolation in ("LINEAR", "CUBIC"):
        # Independent trapezoidal integration spans the known kernel support.
        # Every interval endpoint lies on an integer; the piecewise cubic is
        # integrated at 1/1024 voxel intervals without consulting engine data.
        positions = np.linspace(-3.0, 34.0, 37 * 1024 + 1)
        integral = float(np.trapezoid(axis_factor(positions, interpolation), positions))
        assert abs(integral - 32.0) < 1e-10, (interpolation, integral)
        assert axis_factor(np.array([-3.0, 34.0]), interpolation).max() == 0
        checks.append({"interpolation": interpolation, "index_integral": integral,
                       "world_y_integral": integral * VOXEL_SIZE})
    assert axis_factor(np.array([0.0, 31.0]), "LINEAR").tolist() == [1.0, 1.0]
    assert np.allclose(axis_factor(np.array([0.0, 31.0]), "CUBIC"), 5.0 / 6.0)
    return checks


def expected_image(interpolation, shear):
    xs = ((np.arange(WIDTH, dtype=np.float64) + 0.5) / WIDTH - 0.5) * ORTHO_WIDTH
    zs = ((np.arange(HEIGHT, dtype=np.float64) + 0.5) / HEIGHT - 0.5) * ORTHO_HEIGHT
    expected = np.zeros((HEIGHT, WIDTH), dtype=np.float64)
    # Pixel footprint integration, independent of either engine's samples.
    # The default native filter is NONE; Cycles' reconstruction filter may
    # give small subpixel differences covered by the fixed profile gates.
    offsets = (-0.375, -0.125, 0.125, 0.375)
    for dz in offsets:
        world_z = zs + dz * ORTHO_HEIGHT / HEIGHT
        z_factor = axis_factor((world_z + 1.0) / VOXEL_SIZE, interpolation)
        for dx in offsets:
            world_x = xs[None, :] + dx * ORTHO_WIDTH / WIDTH
            object_x = world_x - shear * world_z[:, None]
            x_factor = axis_factor((object_x + 1.0) / VOXEL_SIZE, interpolation)
            expected += np.exp(-SIGMA * Y_INTEGRAL * x_factor * z_factor[:, None]) / 16.0
    return xs, zs, expected


def profiles(image, xs, zs, shear):
    luminance = image if image.ndim == 2 else image.mean(axis=2, dtype=np.float64)
    # Undo the authored x-from-z shear for comparison in fixture coordinates.
    rows = np.flatnonzero(np.abs(zs + 0.03125) < 0.45)
    assert len(rows) >= PROFILE_MIN_ROWS
    aligned = np.asarray([
        np.interp(xs + shear * zs[row], xs, luminance[row], left=1.0, right=1.0)
        for row in rows
    ])
    horizontal = aligned.mean(axis=0, dtype=np.float64)
    horizontal_sem = aligned.std(axis=0, ddof=1, dtype=np.float64) / math.sqrt(len(rows))
    # For sheared cases, align x coordinates before averaging interior columns.
    columns = np.flatnonzero(np.abs(xs + 0.03125) < 0.45)
    vertical = np.asarray([
        np.interp(xs[columns] + shear * zs[row], xs, luminance[row], left=1.0, right=1.0).mean()
        for row in range(HEIGHT)
    ])
    return horizontal, vertical, horizontal_sem, len(rows), len(columns)


def crossing(coordinates, profile, side, contrast):
    # A threshold crossing near a known active edge, not a detected bbox.
    center = -1.0 if side == "lower" else 31 * VOXEL_SIZE - 1.0
    selection = np.flatnonzero(np.abs(coordinates - center) < 0.19)
    values = 1.0 - profile
    for lower, upper in zip(selection[:-1], selection[1:]):
        a, b = values[lower] - contrast, values[upper] - contrast
        increasing = side == "lower" and a <= 0 < b
        decreasing = side == "upper" and a >= 0 > b
        if increasing or decreasing:
            fraction = -a / (b - a)
            return float(coordinates[lower] + fraction * (coordinates[upper] - coordinates[lower]))
    return None


def comparison(image, expected, xs, zs, shear, label):
    horizontal, vertical, sem, rows, columns = profiles(image, xs, zs, shear)
    eh, ev, _, _, _ = profiles(expected, xs, zs, shear)
    radius = 0.1875
    x_band = (np.abs(xs + 1.0) < radius) | (np.abs(xs - 0.9375) < radius)
    z_band = (np.abs(zs + 1.0) < radius) | (np.abs(zs - 0.9375) < radius)
    edge_error = np.concatenate([np.abs(horizontal - eh)[x_band], np.abs(vertical - ev)[z_band]])
    contour_checks = []
    for axis, coordinates, actual, oracle in (("x", xs, horizontal, eh), ("z", zs, vertical, ev)):
        for side in ("lower", "upper"):
            for contrast in (0.1, 0.5):
                got = crossing(coordinates, actual, side, contrast)
                target = crossing(coordinates, oracle, side, contrast)
                error = None if got is None or target is None else abs(got - target)
                contour_checks.append({"axis": axis, "side": side, "contrast": contrast,
                                       "world": got, "expected_world": target, "world_error": error,
                                       "limit": CONTOUR_WORLD_LIMIT,
                                       "passed": error is not None and error <= CONTOUR_WORLD_LIMIT})
    mean_image = image if image.ndim == 2 else image.mean(axis=2, dtype=np.float64)
    full_mae = float(np.abs(mean_image - expected).mean(dtype=np.float64))
    # Pure absorption samples survival of white background rays. For N eye
    # samples, Bernoulli standard deviation is sqrt(T*(1-T)/N). Aggregate
    # edge profiles use many independent rows, but full-frame raw MAE still
    # contains this per-pixel noise. Set its allowance before any render.
    expected_pixel_mae = math.sqrt(2.0 / math.pi) * float(
        np.sqrt(expected * (1.0 - expected) / samples).mean())
    full_mae_limit = (FULL_FRAME_MAE_SYSTEMATIC_ALLOWANCE
                      + FULL_FRAME_MAE_NOISE_MULTIPLIER * expected_pixel_mae)
    # The large row/column aggregates reduce finite-sample transport noise;
    # raw per-pixel maximum would conflate that noise with a boundary defect.
    edge_mae = float(edge_error.mean())
    edge_max = float(edge_error.max())
    passed = (edge_mae <= PROFILE_MAE_LIMIT and edge_max <= PROFILE_MAX_LIMIT
              and full_mae <= full_mae_limit and all(c["passed"] for c in contour_checks))
    profile_path = folder / (label + "-profiles.json")
    profile_path.write_text(json.dumps({
        "x_world": xs.tolist(), "z_world": zs.tolist(),
        "horizontal": horizontal.tolist(), "expected_horizontal": eh.tolist(),
        "vertical": vertical.tolist(), "expected_vertical": ev.tolist(),
        "horizontal_standard_error": sem.tolist(), "horizontal_rows": rows,
        "vertical_columns": columns,
    }, indent=2) + "\n")
    return {"kind": "independent-original-voxel-kernel-optical-depth",
            "edge_profile_mae": edge_mae, "edge_profile_max_error": edge_max,
            "mae_limit": PROFILE_MAE_LIMIT, "max_limit": PROFILE_MAX_LIMIT,
            "full_frame_mae": full_mae, "full_frame_mae_limit": full_mae_limit,
            "expected_bernoulli_pixel_mae": expected_pixel_mae,
            "full_frame_systematic_allowance": FULL_FRAME_MAE_SYSTEMATIC_ALLOWANCE,
            "full_frame_noise_multiplier": FULL_FRAME_MAE_NOISE_MULTIPLIER,
            "maximum_horizontal_profile_sem": float(sem.max()),
            "horizontal_rows": rows, "vertical_columns": columns,
            "contours": contour_checks, "profile_path": str(profile_path), "passed": passed}


bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.world = bpy.data.worlds.new("Original voxel boundary white world")
scene.world.use_nodes = True
background = scene.world.node_tree.nodes["Background"]
background.inputs["Color"].default_value = (1, 1, 1, 1)
background.inputs["Strength"].default_value = 1
bpy.ops.object.camera_add(location=(0, -7, 0))
scene.camera = bpy.context.object
scene.camera.rotation_euler = (math.pi / 2, 0, 0)
scene.camera.data.type = "ORTHO"
scene.camera.data.sensor_fit = "HORIZONTAL"
scene.camera.data.ortho_scale = ORTHO_WIDTH
scene.render.resolution_x = WIDTH
scene.render.resolution_y = HEIGHT
scene.render.resolution_percentage = 100
scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1
scene.render.threads_mode = "FIXED"
scene.render.threads = 4
scene.render.film_transparent = False
scene.render.image_settings.color_mode = "RGB"
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure = 0
scene.view_settings.gamma = 1
scene.cycles.samples = samples
scene.cycles.device = "CPU"
scene.cycles.use_denoising = False
scene.cycles.use_adaptive_sampling = False
bpy.context.preferences.filepaths.save_version = 0

material = bpy.data.materials.new("Unchanged authored Cycles voxel boundary")
material.use_nodes = True
material.node_tree.nodes.clear()
output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
principled = material.node_tree.nodes.new("ShaderNodeVolumePrincipled")
principled.inputs["Density"].default_value = DENSITY_MULTIPLIER
principled.inputs["Color"].default_value = (0, 0, 0, 1)
principled.inputs["Density Attribute"].default_value = "density"
principled.inputs["Color Attribute"].default_value = ""
principled.inputs["Emission Strength"].default_value = 0
principled.inputs["Blackbody Intensity"].default_value = 0
material.node_tree.links.new(principled.outputs[0], output.inputs["Volume"])
data = bpy.data.volumes.new("Original 32 cubed density grid")
data.filepath = str(fixture)
data.grids.load()
data.materials.append(material)
data.render.space = "WORLD"
data.render.precision = "FULL"
data.render.clipping = 0
volume = bpy.data.objects.new("Original density voxels", data)
scene.collection.objects.link(volume)
collection_instance = None

slc = scene.superluxcore
spectral_before = slc.config.spectral_enable
assert spectral_before, "Load the production high-quality spectral default"
native_cpu_before = slc.devices.use_native_cpu
gpu_backend_before = bpy.context.preferences.addons[package].preferences.gpu_backend
slc.config.engine = "PATH"
slc.config.path.use_clamping = False
slc.config.path.auto_clamping = False
slc.halt.enable = True
slc.halt.use_samples = True
slc.halt.samples = samples
slc.halt.use_noise_level = False
slc.halt.use_noise_thresh = False
slc.denoiser.enabled = False

# A camera-space oracle confirms the requested horizontal field of view.
bpy.context.view_layer.update()
frame = scene.camera.data.view_frame(scene=scene)
assert abs(max(p.x for p in frame) - ORTHO_WIDTH / 2) < 1e-6
assert abs(min(p.x for p in frame) + ORTHO_WIDTH / 2) < 1e-6
assert abs(max(p.y for p in frame) - ORTHO_HEIGHT / 2) < 1e-6
assert abs(min(p.y for p in frame) + ORTHO_HEIGHT / 2) < 1e-6

# The RenderEngine Combined pass uses RGB_IMAGEPIPELINE. A freshly authored
# camera's identity pipeline makes its EXR numerically raw scene-linear RGB.
# Prove that condition instead of labeling a nonlinear Combined pass "raw".
pipeline_properties = imagepipeline_export.convert(scene)
pipeline_plugins = []
for name in pipeline_properties.GetAllNames("film.imagepipelines.000."):
    if not name.endswith(".type"):
        continue
    kind = pipeline_properties.Get(name).GetString()
    assert kind in {"NOP", "TONEMAP_LINEAR"}, (name, kind)
    if kind == "TONEMAP_LINEAR":
        scale = pipeline_properties.Get(name[:-len("type")] + "scale").GetFloat()
        assert scale == 1, (name, scale)
    pipeline_plugins.append(kind)
assert pipeline_plugins, "Missing identity image pipeline"

native_module = getattr(pysuperluxcore, "pysuperluxcore", pysuperluxcore)
metrics = {
    "complete": False, "passed": False, "records": [], "comparisons": [],
    "resolution": [WIDTH, HEIGHT], "samples": samples, "cpu_threads": 4,
    "native_sha256": sha(native_module.__file__), "reader_sha256": sha(reader.__file__),
    "volume_export_sha256": sha(volume_export.__file__), "harness_sha256": sha(__file__),
    "fixture": str(fixture), "fixture_sha256": sha(fixture),
    "blender_version": bpy.app.version_string,
    "blender_build_hash": bpy.app.build_hash.decode(),
    "oracle": {"active_indices_inclusive": [[0, 0, 0], [31, 31, 31]],
               "voxel_size": VOXEL_SIZE, "translation": [-1, -1, -1],
               "grid_value": GRID_VALUE, "density_multiplier": DENSITY_MULTIPLIER,
               "sigma": SIGMA, "y_integral": Y_INTEGRAL,
               "source": "known fixture coefficients and cardinal kernel integral",
               "exported_bbox_used": False, "pixel_footprint_quadrature": [4, 4],
               "checks": verify_oracle()},
    "default_spectral_before": spectral_before, "default_spectral_restored": False,
    "native_pixel_filter": {"enabled": slc.config.filter_enabled,
                            "type": slc.config.filter, "width": slc.config.filter_width},
    "combined_exr_is_scene_linear_rgb": True,
    "native_identity_imagepipeline_plugins": pipeline_plugins,
    "native_imagepipeline_properties": pipeline_properties.ToString(),
    "scope": "RGB boundary transport via bpy.ops.render.render",
    "production_convergence_acceptance": False, "full_goal_complete": False,
}


def save_metrics():
    (folder / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")


def authored_state_dict():
    # Saving a .blend may remap the RNA filepath to //relative form. The
    # actual field file, rather than that serialization spelling, is authored.
    return {
        "graph": graph_hash(material),
        "volume_filepath": str(Path(bpy.path.abspath(data.filepath, library=data.library)).resolve()),
        "volume_space": data.render.space,
        "object_matrix": [list(row) for row in volume.matrix_world],
        "instance_matrix": [list(row) for row in collection_instance.matrix_world]
                           if collection_instance is not None else None,
        "camera_matrix": [list(row) for row in scene.camera.matrix_world],
        "camera_ortho_scale": scene.camera.data.ortho_scale,
    }


def authored_state_hash():
    return hashlib.sha256(json.dumps(authored_state_dict(), sort_keys=True).encode()).hexdigest()


def render_frame(label, engine, device):
    scene.render.engine = engine
    if engine == "SUPERLUXCORE":
        slc.config.device = device
        slc.config.spectral_enable = False
        if device == "OCL":
            slc.devices.use_native_cpu = False
            bpy.context.preferences.addons[package].preferences.gpu_backend = "METAL"
        else:
            slc.devices.use_native_cpu = native_cpu_before
    errors.clear(False)
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    exr = folder / (label + ".exr")
    scene.render.filepath = str(exr)
    start = time.monotonic()
    bpy.ops.render.render(write_still=True)
    elapsed = time.monotonic() - start
    assert exr.is_file(), (label, "RenderEngine did not produce EXR")
    image = bpy.data.images.load(str(exr), check_existing=False)
    try:
        assert tuple(image.size) == (WIDTH, HEIGHT)
        pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(HEIGHT, WIDTH, 4)[..., :3].copy()
    finally:
        bpy.data.images.remove(image)
    assert np.isfinite(pixels).all(), (label, "nonfinite raw RGB")
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_depth = "8"
    png = folder / (label + ".png")
    bpy.data.images["Render Result"].save_render(str(png), scene=scene)
    actual_eye_spp = actual_light_spp = None
    if engine == "SUPERLUXCORE":
        stats = slc.statistics.get_active()
        actual_eye_spp = int(stats.samples_eye.value)
        actual_light_spp = int(stats.samples_light_tracing.value)
        assert actual_eye_spp >= samples, (label, "eye sample halt incomplete", actual_eye_spp, samples)
        assert not errors.errors, (label, errors.errors)
    return pixels, {
        "label": label, "engine": engine, "device": device,
        "backend": "METAL" if device == "OCL" else "CPU", "spectral": False,
        "native_cpu_enabled": slc.devices.use_native_cpu if engine == "SUPERLUXCORE" else None,
        "actual_eye_spp": actual_eye_spp, "actual_light_spp": actual_light_spp,
        "cycles_requested_spp": samples if engine == "CYCLES" else None,
        "render_engine_operator": "bpy.ops.render.render(write_still=True)",
        "raw_rgb_exr": str(exr), "raw_rgb_exr_sha256": sha(exr),
        "png": str(png), "png_sha256": sha(png), "elapsed_seconds": elapsed,
        "finite": True, "raw_rgb_min": float(pixels.min()), "raw_rgb_max": float(pixels.max()),
        "maximum_rgb_channel_spread": float(np.ptp(pixels, axis=2).max()),
        "rgb_channel_spread_limit": RGB_CHANNEL_SPREAD_LIMIT,
    }


save_metrics()
cases = os.environ.get("SLC_VDB_GRID_CASES", "linear,cubic").split(",")
assert cases and all(case in {"linear", "cubic", "linear-shear", "cubic-shear"} for case in cases)
modes = [("CYCLES", "CPU"), ("SUPERLUXCORE", "CPU"), ("SUPERLUXCORE", "OCL")]
if os.environ.get("SLC_VDB_CPU_ONLY") == "1":
    modes = [mode for mode in modes if mode[1] == "CPU"]
if os.environ.get("SLC_VDB_GPU_ONLY") == "1":
    modes = [mode for mode in modes if mode[0] == "CYCLES" or mode[1] == "OCL"]

try:
    for case in cases:
        interpolation = "CUBIC" if case.startswith("cubic") else "LINEAR"
        shear = 0.35 if case.endswith("-shear") else 0.0
        material.cycles.volume_interpolation = interpolation
        if shear and collection_instance is None:
            source = bpy.data.collections.new("Authored shear instance source")
            scene.collection.objects.unlink(volume)
            source.objects.link(volume)
            collection_instance = bpy.data.objects.new("Authored shear collection instance", None)
            collection_instance.instance_type = "COLLECTION"
            collection_instance.instance_collection = source
            scene.collection.objects.link(collection_instance)
        if collection_instance is not None:
            matrix = Matrix.Identity(4)
            matrix[0][2] = shear
            collection_instance.matrix_world = matrix
        bpy.context.view_layer.update()
        authored = graph_hash(material)
        state_before = authored_state_dict()
        authored_state = authored_state_hash()
        xs, zs, expected = expected_image(interpolation, shear)
        scene.render.engine = "CYCLES"
        slc.config.spectral_enable = spectral_before
        bpy.ops.wm.save_as_mainfile(filepath=str(folder / (case + ".blend")))
        cycles_pixels = None
        for engine, device in modes:
            label = case + "-" + engine.lower() + "-" + device.lower() + "-rgb"
            pixels, record = render_frame(label, engine, device)
            assert graph_hash(material) == authored, (label, "authored graph changed")
            state_after = authored_state_dict()
            if state_after != state_before:
                failure = {"label": label, "before": state_before, "after": state_after,
                           "changed_fields": [key for key in state_before if state_before[key] != state_after[key]]}
                metrics.setdefault("authored_state_failures", []).append(failure)
                save_metrics()
                raise AssertionError((label, "authored instance, camera, or field file changed", failure))
            assert authored_state_hash() == authored_state
            record.update({"case": case, "interpolation": interpolation, "shear_x_from_z": shear,
                           "graph_sha256": authored, "authored_graph_unchanged": True,
                           "authored_state_sha256": authored_state, "authored_state_unchanged": True,
                           "analytic": comparison(pixels, expected, xs, zs, shear, label)})
            if engine == "CYCLES":
                cycles_pixels = pixels
            else:
                assert cycles_pixels is not None
                ph, pv, _, _, _ = profiles(pixels, xs, zs, shear)
                ch, cv, _, _, _ = profiles(cycles_pixels, xs, zs, shear)
                x_band = (np.abs(xs + 1) < 0.1875) | (np.abs(xs - 0.9375) < 0.1875)
                z_band = (np.abs(zs + 1) < 0.1875) | (np.abs(zs - 0.9375) < 0.1875)
                differences = np.concatenate([np.abs(ph - ch)[x_band], np.abs(pv - cv)[z_band]])
                item = {"case": case, "device": device, "kind": "unchanged-cycles-raw-boundary-profile",
                        "mae": float(differences.mean()), "max_error": float(differences.max()),
                        "mae_limit": CYCLES_PROFILE_MAE_LIMIT, "max_limit": CYCLES_PROFILE_MAX_LIMIT}
                item["passed"] = item["mae"] <= item["mae_limit"] and item["max_error"] <= item["max_limit"]
                metrics["comparisons"].append(item)
            record["passed"] = (record["analytic"]["passed"]
                and record["maximum_rgb_channel_spread"] <= RGB_CHANNEL_SPREAD_LIMIT) and (
                engine == "CYCLES" or metrics["comparisons"][-1]["passed"])
            metrics["records"].append(record)
            save_metrics()
            print("VDB_GRID_RENDER", label, "PASS" if record["passed"] else "FAIL",
                  record["analytic"]["edge_profile_mae"], record["analytic"]["edge_profile_max_error"], flush=True)
            assert record["passed"], (label, record["analytic"], metrics["comparisons"][-1:] if engine != "CYCLES" else [])
            if engine != "CYCLES":
                del pixels
        del expected, cycles_pixels
    metrics["complete"] = True
    metrics["passed"] = all(record["passed"] for record in metrics["records"])
finally:
    slc.config.spectral_enable = spectral_before
    slc.devices.use_native_cpu = native_cpu_before
    bpy.context.preferences.addons[package].preferences.gpu_backend = gpu_backend_before
    metrics["default_spectral_restored"] = slc.config.spectral_enable == spectral_before
    metrics["native_cpu_preference_restored"] = slc.devices.use_native_cpu == native_cpu_before
    metrics["gpu_backend_restored"] = bpy.context.preferences.addons[package].preferences.gpu_backend == gpu_backend_before
    save_metrics()

print("VDB_GRID_RENDER_COMPLETE_REQUIRES_DIRECT_REVIEW", len(metrics["records"]), flush=True)
