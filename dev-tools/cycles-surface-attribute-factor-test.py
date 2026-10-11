"""Actual Blender 720p surface Attribute Factor diagnostic atlas.

Six independently authored constant attributes are each connected through
the stable Fac socket identifier to Emission Color and Emission Strength.
Expected values use the Cycles data-type contract: RGB arithmetic average,
Float2 x, or scalar identity. Native semantic failures are preserved as
failed records; they never become accepted by widening a threshold.

Run through the inventory-guarded run-render.py with a frozen profile.
The caller owns timeout, termination, reaping, and original image review.
"""

import hashlib
import importlib
import json
import os
from pathlib import Path
import time

import bpy
import numpy as np
import pysuperluxcore


resources = Path(os.environ["BLENDER_USER_RESOURCES"]).resolve()
for kind, directory in (("CONFIG", "config"), ("EXTENSIONS", "extensions")):
    path = Path(os.environ["BLENDER_USER_" + kind]).resolve()
    assert path == resources / directory
    assert Path(bpy.utils.user_resource(kind)).resolve() == path

WIDTH, HEIGHT = 1280, 720
ORTHO_WIDTH = 12.0
ORTHO_HEIGHT = ORTHO_WIDTH * HEIGHT / WIDTH
PATCH_MAX_ABS_LIMIT = 0.005
PATCH_SPREAD_LIMIT = 0.005
CASES = (
    ("red-vector", "FLOAT_VECTOR", (1., 0., 0.), 1. / 3.),
    ("green-color", "FLOAT_COLOR", (0., 1., 0., 0.25), 1. / 3.),
    ("blue-byte-color", "BYTE_COLOR", (0., 0., 1., 0.25), 1. / 3.),
    ("asymmetric-vector", "FLOAT_VECTOR", (0.1, 0.4, 0.9), (0.1 + 0.4 + 0.9) / 3.),
    ("asymmetric-float2", "FLOAT2", (0.8, 0.1), 0.8),
    ("scalar-control", "FLOAT", 0.4, 0.4),
)
DESTINATIONS = (("Color", 1.65), ("Strength", -1.65))
PATCHES = (("center", 0., 0.), ("lower-left", -0.4, -0.6),
           ("lower-right", 0.4, -0.6), ("upper-left", -0.4, 0.6),
           ("upper-right", 0.4, 0.6))
folder = Path(os.environ["SUPERLUXCORE_AUDIT_DIR"])
folder.mkdir(parents=True, exist_ok=True)
assert not (folder / "metrics.json").exists(), "Preserve original diagnostic evidence"
samples = int(os.environ.get("SLC_VDB_SAMPLES", "64"))
assert 64 <= samples <= 256
package = next(addon.module for addon in bpy.context.preferences.addons
               if addon.module.endswith(".superluxcore") or addon.module == "superluxcore")
reader = importlib.import_module(package + ".export.cycles_node_reader")
volume_export = importlib.import_module(package + ".export.volume")
named_export = importlib.import_module(package + ".export.named_attributes")
pipeline_export = importlib.import_module(package + ".export.imagepipeline")
errors = importlib.import_module(package + ".utils.errorlog").SuperLuxCoreErrorLog


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def stable_socket(sockets, identifier):
    matches = [socket for socket in sockets if socket.identifier == identifier]
    assert len(matches) == 1, (identifier, [(s.identifier, s.name) for s in sockets])
    return matches[0]


def graph_data(material):
    nodes = []
    for node in material.node_tree.nodes:
        inputs = []
        for socket in node.inputs:
            if hasattr(socket, "default_value"):
                value = socket.default_value
                if not isinstance(value, (float, int, bool, str)):
                    value = list(value)
                inputs.append([socket.identifier, value])
        nodes.append([node.name, node.bl_idname, getattr(node, "attribute_name", None),
                      getattr(node, "attribute_type", None), inputs])
    links = sorted([link.from_node.name, link.from_socket.identifier,
                    link.to_node.name, link.to_socket.identifier]
                   for link in material.node_tree.links)
    return {"nodes": sorted(nodes), "links": links}


bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
scene = bpy.context.scene
scene.world = bpy.data.worlds.new("Surface Factor black world")
scene.world.use_nodes = True
scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.
bpy.ops.object.camera_add(location=(0., 0., 8.))
scene.camera = bpy.context.object
scene.camera.rotation_euler = (0., 0., 0.)
scene.camera.data.type = "ORTHO"
scene.camera.data.sensor_fit = "HORIZONTAL"
scene.camera.data.ortho_scale = ORTHO_WIDTH
scene.render.resolution_x, scene.render.resolution_y = WIDTH, HEIGHT
scene.render.resolution_percentage = 100
scene.render.pixel_aspect_x = scene.render.pixel_aspect_y = 1.
scene.render.threads_mode, scene.render.threads = "FIXED", 4
scene.render.film_transparent = False
scene.render.image_settings.color_mode = "RGB"
scene.view_settings.view_transform = "Standard"
scene.view_settings.exposure, scene.view_settings.gamma = 0., 1.
materials, panels, socket_records = [], [], []
for column, (case, data_type, value, expected) in enumerate(CASES):
    x = -5. + 2. * column
    for destination, y in DESTINATIONS:
        label = case + "-fac-to-" + destination.lower()
        mesh = bpy.data.meshes.new(label)
        mesh.from_pydata([(-0.8, -1.2, 0.), (0.8, -1.2, 0.),
                          (0.8, 1.2, 0.), (-0.8, 1.2, 0.)], [], [(0, 1, 2, 3)])
        mesh.update()
        attribute = mesh.attributes.new(name="authored_factor", type=data_type, domain="POINT")
        assert attribute.data_type == data_type and attribute.domain == "POINT"
        prop = "color" if data_type in {"FLOAT_COLOR", "BYTE_COLOR"} else (
            "value" if data_type == "FLOAT" else "vector")
        for item in attribute.data:
            setattr(item, prop, value)
        obj = bpy.data.objects.new(label, mesh)
        scene.collection.objects.link(obj)
        obj.location = (x, y, 0.)
        material = bpy.data.materials.new(label)
        material.use_nodes = True
        material.node_tree.nodes.clear()
        output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
        attribute_node = material.node_tree.nodes.new("ShaderNodeAttribute")
        attribute_node.attribute_name = "authored_factor"
        attribute_node.attribute_type = "GEOMETRY"
        fac = stable_socket(attribute_node.outputs, "Fac")
        emission = material.node_tree.nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = (1., 1., 1., 1.)
        emission.inputs["Strength"].default_value = 1.
        material.node_tree.links.new(fac, stable_socket(emission.inputs, destination))
        material.node_tree.links.new(stable_socket(emission.outputs, "Emission"),
                                     stable_socket(output.inputs, "Surface"))
        mesh.materials.append(material)
        materials.append(material)
        panels.append({"label": label, "case": case, "destination": destination,
                       "object": obj, "attribute": attribute, "data_property": prop,
                       "data_type": data_type, "authored_value": value,
                       "center": [x, y], "expected_factor": expected})
        socket_records.append({"panel": label, "display_name": fac.name,
                               "identifier": fac.identifier, "destination": destination})

bpy.context.view_layer.update()
frame = scene.camera.data.view_frame(scene=scene)
assert abs(max(p.x for p in frame) - ORTHO_WIDTH / 2.) < 1e-6
assert abs(max(p.y for p in frame) - ORTHO_HEIGHT / 2.) < 1e-6


def authored_state():
    result = {"graphs": [graph_data(material) for material in materials], "objects": [],
              "camera_matrix": [list(row) for row in scene.camera.matrix_world],
              "camera_ortho_scale": scene.camera.data.ortho_scale}
    for panel in panels:
        obj = panel["object"]
        attr = panel["attribute"]
        values = []
        for item in attr.data:
            value = getattr(item, panel["data_property"])
            values.append(float(value) if isinstance(value, (float, int)) else list(value))
        result["objects"].append({"name": obj.name,
                                  "matrix": [list(row) for row in obj.matrix_world],
                                  "vertices": [list(v.co) for v in obj.data.vertices],
                                  "polygons": [list(face.vertices) for face in obj.data.polygons],
                                  "data_type": attr.data_type, "domain": attr.domain,
                                  "attribute_name": attr.name, "attribute_values": values})
    return result


fixture_path = folder / "atlas-fixture.json"
fixture_data = {"cases": [{"case": c, "data_type": t, "authored_value": v,
                           "expected_factor": e} for c, t, v, e in CASES],
                "destinations": [destination for destination, _ in DESTINATIONS],
                "authored_state": authored_state(), "resolution": [WIDTH, HEIGHT],
                "world_width": ORTHO_WIDTH, "world_height": ORTHO_HEIGHT,
                "expected_source": "Independent Cycles surface type contract: average RGB, Float2 x, scalar identity",
                "patch_max_absolute_error_limit": PATCH_MAX_ABS_LIMIT,
                "patch_spread_limit": PATCH_SPREAD_LIMIT}
fixture_path.write_text(json.dumps(fixture_data, indent=2) + "\n")
authored_before = authored_state()
authored_sha = hashlib.sha256(json.dumps(authored_before, sort_keys=True).encode()).hexdigest()
slc = scene.superluxcore
preferences = bpy.context.preferences.addons[package].preferences
settings = [(slc.config, "spectral_enable"), (slc.config, "engine"), (slc.config, "device"),
            (slc.config.path, "use_clamping"), (slc.config.path, "auto_clamping"),
            (slc.config.path, "hybridbackforward_enable"), (slc.devices, "use_native_cpu"),
            (slc.halt, "enable"), (slc.halt, "use_samples"), (slc.halt, "samples"),
            (slc.halt, "use_noise_level"), (slc.halt, "use_noise_thresh"),
            (slc.denoiser, "enabled"), (preferences, "gpu_backend"),
            (scene.cycles, "device"), (scene.cycles, "samples"),
            (scene.cycles, "use_denoising"), (scene.cycles, "use_adaptive_sampling"),
            (scene.cycles, "seed"),
            (scene.render, "engine"), (scene.render.image_settings, "file_format"),
            (scene.render.image_settings, "color_depth"), (scene.render, "filepath")]
before_settings = [(owner, name, getattr(owner, name)) for owner, name in settings]
spectral_before = slc.config.spectral_enable
assert spectral_before, "Preserve production spectral defaults; this atlas is an explicit RGB diagnostic"
native_module = getattr(pysuperluxcore, "pysuperluxcore", pysuperluxcore)
metrics = {"complete": False, "passed": False, "diagnostic": True, "records": [],
           "resolution": [WIDTH, HEIGHT], "samples": samples, "cpu_threads": 4,
           "fixture": str(fixture_path), "fixture_sha256": sha(fixture_path),
           "native_sha256": sha(native_module.__file__), "reader_sha256": sha(reader.__file__),
           "volume_export_sha256": sha(volume_export.__file__),
           "named_attribute_export_sha256": sha(named_export.__file__), "harness_sha256": sha(__file__),
           "blender_version": bpy.app.version_string, "blender_build_hash": bpy.app.build_hash.decode(),
           "authored_state_sha256": authored_sha, "authored_attribute_sockets": socket_records,
           "default_spectral_before": spectral_before, "default_spectral_restored": False,
           "settings_restored": False, "full_goal_complete": False,
           "production_convergence_acceptance": False,
           "scope": "Unchanged-graph surface Fac-to-Color/Strength RGB emission atlas; six types/values, twelve panels",
           "gate": {"patch_max_absolute_error": PATCH_MAX_ABS_LIMIT,
                    "patch_spread": PATCH_SPREAD_LIMIT, "patches_per_panel": len(PATCHES)}}


def save_metrics():
    (folder / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")


def patch_analysis(pixels):
    xs = ((np.arange(WIDTH) + .5) / WIDTH - .5) * ORTHO_WIDTH
    ys = ((np.arange(HEIGHT) + .5) / HEIGHT - .5) * ORTHO_HEIGHT
    results = []
    for panel in panels:
        x, y = panel["center"]
        target = np.full(3, panel["expected_factor"], dtype=np.float64)
        patches = []
        for name, dx, dy in PATCHES:
            columns = np.flatnonzero(np.abs(xs - x - dx) < .15)
            rows = np.flatnonzero(np.abs(ys - y - dy) < .20)
            assert len(columns) >= 25 and len(rows) >= 35
            values = pixels[rows[:, None], columns[None, :], :].astype(np.float64)
            mean = values.mean(axis=(0, 1))
            spread = float(np.max(np.abs(values - mean)))
            error = float(np.max(np.abs(mean - target)))
            patches.append({"name": name, "world_center": [x + dx, y + dy],
                            "pixel_count": len(rows) * len(columns), "actual_rgb": mean.tolist(),
                            "expected_rgb": target.tolist(), "max_absolute_error": error,
                            "max_spread": spread,
                            "passed": error <= PATCH_MAX_ABS_LIMIT and spread <= PATCH_SPREAD_LIMIT})
        results.append({"label": panel["label"], "case": panel["case"],
                        "data_type": panel["data_type"], "destination": panel["destination"],
                        "expected_factor": panel["expected_factor"], "patches": patches,
                        "max_absolute_error": max(p["max_absolute_error"] for p in patches),
                        "passed": all(p["passed"] for p in patches)})
    return {"panels": results, "passed": all(panel["passed"] for panel in results)}


def render_frame(engine, device):
    label = engine.lower() + "-" + device.lower() + "-attribute-factor-rgb"
    scene.render.engine = engine
    if engine == "SUPERLUXCORE":
        slc.config.device, slc.config.spectral_enable = device, False
        slc.devices.use_native_cpu = device != "OCL"
        if device == "OCL":
            preferences.gpu_backend = "METAL"
    scene.render.image_settings.file_format, scene.render.image_settings.color_depth = "OPEN_EXR", "32"
    exr, png = folder / (label + ".exr"), folder / (label + ".png")
    assert not exr.exists() and not png.exists()
    scene.render.filepath = str(exr)
    errors.clear(False)
    started = time.monotonic()
    bpy.ops.render.render(write_still=True)
    elapsed = time.monotonic() - started
    assert exr.is_file()
    image = bpy.data.images.load(str(exr), check_existing=False)
    try:
        assert tuple(image.size) == (WIDTH, HEIGHT)
        pixels = np.asarray(image.pixels[:], dtype=np.float32).reshape(HEIGHT, WIDTH, 4)[..., :3].copy()
    finally:
        bpy.data.images.remove(image)
    assert np.isfinite(pixels).all(), (label, "nonfinite raw RGB")
    scene.render.image_settings.file_format, scene.render.image_settings.color_depth = "PNG", "8"
    bpy.data.images["Render Result"].save_render(str(png), scene=scene)
    eye_spp, light_spp = None, None
    if engine == "SUPERLUXCORE":
        stats = slc.statistics.get_active()
        eye_spp, light_spp = int(stats.samples_eye.value), int(stats.samples_light_tracing.value)
        assert eye_spp >= samples, (label, eye_spp, samples)
        assert not errors.errors, (label, errors.errors)
    after = authored_state()
    assert after == authored_before, (label, "Authored Cycles graph or geometry changed")
    analysis = patch_analysis(pixels)
    record = {"label": label, "engine": engine, "device": device,
              "backend": "METAL" if device == "OCL" else "CPU", "spectral": False,
              "native_cpu_enabled": slc.devices.use_native_cpu if engine == "SUPERLUXCORE" else None,
              "actual_eye_spp": eye_spp, "actual_light_spp": light_spp,
              "configured_cycles_spp": samples if engine == "CYCLES" else None,
              "cycles_adaptive_sampling": False, "raw_rgb_exr": str(exr), "raw_rgb_exr_sha256": sha(exr),
              "png": str(png), "png_sha256": sha(png), "elapsed_seconds": elapsed,
              "finite": True, "raw_rgb_min": float(pixels.min()), "raw_rgb_max": float(pixels.max()),
              "render_engine_operator": "bpy.ops.render.render(write_still=True)",
              "authored_state_sha256": authored_sha, "authored_state_unchanged": True,
              "analytic": analysis, "passed": analysis["passed"]}
    del pixels
    return record


save_metrics()
try:
    scene.cycles.device, scene.cycles.samples = "CPU", samples
    scene.cycles.use_denoising = scene.cycles.use_adaptive_sampling = False
    scene.cycles.seed = 613
    slc.config.engine = "PATH"
    slc.config.path.use_clamping = slc.config.path.auto_clamping = False
    slc.config.path.hybridbackforward_enable = False
    slc.halt.enable = slc.halt.use_samples = True
    slc.halt.samples = samples
    slc.halt.use_noise_level = slc.halt.use_noise_thresh = False
    slc.denoiser.enabled = False
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
    metrics["native_identity_imagepipeline_plugins"] = plugins
    metrics["native_imagepipeline_properties"] = pipeline.ToString()
    scene.render.engine = "CYCLES"
    bpy.ops.wm.save_as_mainfile(filepath=str(folder / "authored-factor-atlas.blend"))
    modes = [("CYCLES", "CPU"), ("SUPERLUXCORE", "CPU")]
    if os.environ.get("SLC_SURFACE_FACTOR_GPU_ONLY") == "1":
        modes = [("CYCLES", "CPU"), ("SUPERLUXCORE", "OCL")]
    for engine, device in modes:
        record = render_frame(engine, device)
        metrics["records"].append(record)
        save_metrics()
        print("SURFACE_ATTRIBUTE_FACTOR", record["label"],
              "PASS" if record["passed"] else "FAIL", flush=True)
        if engine == "CYCLES":
            assert record["passed"], "Installed Cycles baseline contradicts the fixed independent atlas contract"
    metrics["complete"] = True
    metrics["passed"] = all(record["passed"] for record in metrics["records"])
    metrics["native_semantic_failure_reproduced"] = not metrics["records"][-1]["passed"]
except BaseException as error:
    metrics["execution_error"] = repr(error)
    raise
finally:
    for owner, name, value in reversed(before_settings):
        setattr(owner, name, value)
    metrics["settings_restored"] = all(getattr(owner, name) == value for owner, name, value in before_settings)
    metrics["default_spectral_restored"] = slc.config.spectral_enable == spectral_before
    metrics["authored_state_unchanged"] = authored_state() == authored_before
    save_metrics()

assert metrics["settings_restored"] and metrics["authored_state_unchanged"]
assert metrics["passed"], "Native surface Factor semantic failures retained in metrics.json"
print("SURFACE_ATTRIBUTE_FACTOR_COMPLETE_REQUIRES_DIRECT_REVIEW", len(metrics["records"]), flush=True)
