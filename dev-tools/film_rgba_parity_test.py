# SPDX-License-Identifier: Apache-2.0
"""Real large-film RGB/alpha parity; detects parallel RGBA extraction races.

Run after dev-tools/sync_dev_install.sh:
  Blender --background --python-exit-code 1 --python dev-tools/film_rgba_parity_test.py
An enabled extension and physical GPU are required.
SUPERLUXCORE_TEST_GPU_BACKEND selects METAL (default) or OPENCL.
"""
import importlib
import os
from pathlib import Path
import sys
import tempfile

import bpy
import numpy as np
import pysuperluxcore as plc

sys.path.insert(0, str(Path(__file__).resolve().parent))
from camera_raster_parity_test import build_scene

WIDTH, HEIGHT = 1024, 512


def main():
    addon_key = next(a.module for a in bpy.context.preferences.addons
                     if "superluxcore" in a.module.lower())
    bpy.context.preferences.addons[addon_key].preferences.gpu_backend = os.environ.get(
        "SUPERLUXCORE_TEST_GPU_BACKEND", "METAL")
    framebuffer = importlib.import_module(addon_key + ".draw.final").FrameBufferFinal
    original_draw = framebuffer.draw
    with tempfile.TemporaryDirectory(prefix="blender-film-rgba-") as directory:
        for label, transparent, half_plane in [("opaque full", False, False),
                                               ("transparent full", True, False),
                                               ("transparent half", True, True)]:
            scene, _ = build_scene("ORTHO", (0, 0))
            scene.render.resolution_x, scene.render.resolution_y = WIDTH, HEIGHT
            scene.render.image_settings.color_mode = "RGBA"
            scene.render.film_transparent = transparent
            scene.camera.data.superluxcore.imagepipeline.transparent_film = transparent
            scene.superluxcore.halt.samples = 512
            scene.cycles.samples = 512
            if half_plane:
                plane = next(obj for obj in scene.objects if obj.type == "MESH")
                for vertex in plane.data.vertices:
                    vertex.co.x = min(vertex.co.x, 0)
                plane.data.update()

            frame = scene.camera.data.view_frame(scene=scene)
            xmin, xmax = min(v.x for v in frame), max(v.x for v in frame)
            ymin, ymax = min(v.y for v in frame), max(v.y for v in frame)
            x = xmin + (np.arange(WIDTH) + .5) * (xmax - xmin) / WIDTH
            y = ymin + (np.arange(HEIGHT) + .5) * (ymax - ymin) / HEIGHT
            expected = np.empty((HEIGHT, WIDTH, 4), dtype=np.float32)
            expected[..., 0] = .5 + .25 * x
            expected[..., 1] = .5 + .25 * y[:, None]
            expected[..., 2] = .5
            expected[..., 3] = 1
            if half_plane:
                expected[:, x > 0, :] = 0
            # Exclude the physical edge, filter footprint and negative emission.
            regions = (np.s_[64:448, 128:480], np.s_[64:448, 544:896])

            def check_lightgroup(self, render_engine, session, render_scene, render_stopped):
                result = original_draw(self, render_engine, session, render_scene, render_stopped)
                if render_stopped:
                    group = np.empty((HEIGHT, WIDTH, 3), dtype=np.float32)
                    session.GetFilm().GetOutputFloat(plc.FilmOutputType.RADIANCE_GROUP, group)
                    for region in regions:
                        residual = (group - expected[..., :3])[region]
                        assert np.isfinite(residual).all(), (label, "light group", "non-finite")
                        error = float(np.abs(residual).max())
                        assert error < .003, (label, "light group", "RGB", error)
                    print("PASS: large-film native light-group coordinates", label, flush=True)
                return result

            for device_label, engine, device in [("Cycles", "CYCLES", None),
                                                  ("CPU", "SUPERLUXCORE", "CPU"),
                                                  ("GPU", "SUPERLUXCORE", "OCL")]:
                scene.render.engine = engine
                if device:
                    scene.superluxcore.config.device = device
                scene.render.filepath = str(Path(directory) / "film-rgba.exr")
                if device:
                    framebuffer.draw = check_lightgroup
                try:
                    bpy.ops.render.render(write_still=True)
                finally:
                    framebuffer.draw = original_draw
                image = bpy.data.images.load(scene.render.filepath, check_existing=False)
                pixels = np.empty(HEIGHT * WIDTH * 4, dtype=np.float32)
                image.pixels.foreach_get(pixels)
                actual = pixels.reshape(HEIGHT, WIDTH, 4)
                bpy.data.images.remove(image)
                for region in regions:
                    residual = (actual - expected)[region]
                    assert np.isfinite(residual).all(), (label, device_label, "non-finite film")
                    rgb_error = float(np.abs(residual[..., :3]).max())
                    alpha_error = float(np.abs(residual[..., 3]).max())
                    print("FILM_RGBA_RESIDUAL", label, device_label,
                          "RGB", rgb_error, "alpha", alpha_error, flush=True)
                    assert rgb_error < .003, (label, device_label, "RGB", rgb_error)
                    assert alpha_error < .00001, (label, device_label, "alpha", alpha_error)
                print("PASS: large film RGBA", label, device_label,
                      "1024x512 RGB and alpha against Blender camera geometry", flush=True)
    print("PASS: large-film RGBA parity, 9 actual renders", bpy.app.version_string, flush=True)


if __name__ == "__main__":
    main()
