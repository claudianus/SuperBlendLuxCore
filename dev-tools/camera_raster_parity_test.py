# SPDX-License-Identifier: Apache-2.0
"""Real Blender 5.2 camera pixel centers against Cycles, CPU and GPU renders.

Run after dev-tools/sync_dev_install.sh:
  Blender --background --python-exit-code 1 --python dev-tools/camera_raster_parity_test.py
An enabled SuperLuxCore extension and a physical GPU are required.
SUPERLUXCORE_TEST_GPU_BACKEND selects METAL (default) or OPENCL.
"""
import math
import os
from pathlib import Path
import tempfile

import bmesh
import bpy
import numpy as np

WIDTH, HEIGHT = 64, 32


def build_scene(camera_model, shift):
    scene = bpy.data.scenes.new("CameraRaster_" + camera_model)
    bpy.context.window.scene = scene
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.image_settings.color_depth = "32"
    scene.world = bpy.data.worlds.new("CameraRasterBlackWorld")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get("Background").inputs["Color"].default_value = (0, 0, 0, 1)

    material = bpy.data.materials.new("IndependentCoordinateRamp")
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    geometry = nodes.new("ShaderNodeNewGeometry")
    scale = nodes.new("ShaderNodeVectorMath")
    scale.operation = "SCALE"
    scale.inputs["Scale"].default_value = .25
    bias = nodes.new("ShaderNodeVectorMath")
    bias.operation = "ADD"
    bias.inputs[1].default_value = (.5, .5, .5)
    emission = nodes.new("ShaderNodeEmission")
    output = nodes.new("ShaderNodeOutputMaterial")
    links = material.node_tree.links
    links.new(geometry.outputs["Incoming" if camera_model == "PANO" else "Position"], scale.inputs[0])
    links.new(scale.outputs["Vector"], bias.inputs[0])
    links.new(bias.outputs["Vector"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    camera_data = bpy.data.cameras.new("IndependentBlenderCamera")
    camera = bpy.data.objects.new("IndependentBlenderCamera", camera_data)
    scene.collection.objects.link(camera)
    camera_data.type = camera_model
    camera_data.ortho_scale = 4.8
    camera_data.shift_x, camera_data.shift_y = shift
    camera.location = (0, 0, 3)
    scene.camera = camera
    camera_data.superluxcore.imagepipeline.tonemapper.enabled = False
    if camera_model == "PANO":
        camera.location = (0, 0, 0)
        camera_data.panorama_type = "EQUIRECTANGULAR"
        bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=64, radius=10)
        obj = bpy.context.object
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        for face in bm.faces:
            face.normal_flip()
        bm.to_mesh(obj.data)
        bm.free()
    else:
        mesh = bpy.data.meshes.new("IndependentPositionPlane")
        mesh.from_pydata([(-4, -3, 0), (4, -3, 0), (4, 3, 0), (-4, 3, 0)], [], [(0, 1, 2, 3)])
        mesh.update()
        obj = bpy.data.objects.new("IndependentPositionPlane", mesh)
        scene.collection.objects.link(obj)
    obj.data.materials.append(material)

    cfg = scene.superluxcore
    cfg.config.engine = "PATH"
    cfg.config.spectral_enable = False
    cfg.config.mnee_enable = False
    cfg.config.path.vertex_connection = False
    cfg.config.path.use_clamping = False
    cfg.config.path.auto_clamping = False
    cfg.config.path.suggested_clamping_value = -1
    cfg.devices.use_native_cpu = False
    cfg.halt.enable = True
    cfg.halt.use_time = False
    cfg.halt.use_samples = True
    cfg.halt.samples = 512
    cfg.halt.use_noise_thresh = False
    cfg.halt.use_light_samples = False
    cfg.denoiser.enabled = False
    scene.cycles.device = "CPU"
    scene.cycles.samples = 512
    scene.cycles.use_denoising = False

    frame = camera_data.view_frame(scene=scene)
    xmin, xmax = min(v.x for v in frame), max(v.x for v in frame)
    ymin, ymax = min(v.y for v in frame), max(v.y for v in frame)
    if camera_model == "PERSP":
        depth = camera.location.z / -frame[0].z
        xmin, xmax = xmin * depth, xmax * depth
        ymin, ymax = ymin * depth, ymax * depth
    expected = np.empty((HEIGHT, WIDTH, 3), dtype=np.float32)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if camera_model == "PANO":
                latitude = math.pi * ((y + .5) / HEIGHT - .5)
                longitude = 2 * math.pi * ((x + .5) / WIDTH - .5)
                direction = (math.cos(latitude) * math.sin(longitude), math.sin(latitude),
                             -math.cos(latitude) * math.cos(longitude))
                expected[y, x] = tuple(.5 - .25 * value for value in direction)
            else:
                expected[y, x] = (.5 + .25 * (xmin + (x + .5) * (xmax - xmin) / WIDTH),
                                  .5 + .25 * (ymin + (y + .5) * (ymax - ymin) / HEIGHT), .5)
    return scene, expected


def main():
    addon_key = next(a.module for a in bpy.context.preferences.addons if "superluxcore" in a.module.lower())
    bpy.context.preferences.addons[addon_key].preferences.gpu_backend = os.environ.get(
        "SUPERLUXCORE_TEST_GPU_BACKEND", "METAL")
    with tempfile.TemporaryDirectory(prefix="blender-camera-raster-") as directory:
        for model, shift in [("ORTHO", (0, 0)), ("PERSP", (0, 0)),
                             ("ORTHO", (.11, -.07)), ("PERSP", (.11, -.07)), ("PANO", (0, 0))]:
            scene, expected = build_scene(model, shift)
            roi = np.s_[4:28, 8:56]
            y_gradient = np.gradient(expected[:, :, 1], axis=0)[roi]
            for label, engine, device in [("Cycles", "CYCLES", None),
                                          ("CPU", "SUPERLUXCORE", "CPU"),
                                          ("GPU", "SUPERLUXCORE", "OCL")]:
                scene.render.engine = engine
                if device:
                    scene.superluxcore.config.device = device
                scene.render.filepath = str(Path(directory) / "coordinate-ramp.exr")
                bpy.ops.render.render(write_still=True)
                image = bpy.data.images.load(scene.render.filepath, check_existing=False)
                pixels = np.empty(HEIGHT * WIDTH * 4, dtype=np.float32)
                image.pixels.foreach_get(pixels)
                actual = pixels.reshape(HEIGHT, WIDTH, 4)[:, :, :3].copy()
                bpy.data.images.remove(image)
                residual = (actual - expected)[roi]
                assert np.isfinite(residual).all(), (model, shift, label, "non-finite film")
                max_rgb_error = float(np.abs(residual).max())
                row_y_offsets = (residual[:, :, 1] / y_gradient).mean(axis=1)
                max_row_offset = float(np.abs(row_y_offsets).max())
                assert max_rgb_error < .003, (model, shift, label, "RGB", max_rgb_error)
                assert max_row_offset < .05, (model, shift, label, "pixel Y", max_row_offset)
                print("PASS: camera raster", model, shift, label,
                      "max RGB", max_rgb_error, "max row Y pixels", max_row_offset, flush=True)
    print("PASS: Blender camera pixel-center parity, 15 actual renders", bpy.app.version_string, flush=True)


if __name__ == "__main__":
    main()
