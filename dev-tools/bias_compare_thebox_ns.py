"""Spectral on/off x CPU/GPU isolation on thebox4.

    Blender -b Untitled.blend --python dev-tools/bias_compare_thebox_ns.py
"""
import os
import time

import bpy

OUT_DIR = "/tmp/thebox4_compare"
RES = (1280, 720)
HALT_SAMPLES = 256

VARIANTS = [
    ("path_cpu_ns", "PATH", "CPU", False),
    ("path_ocl_ns", "PATH", "OCL", False),
]


def main():
    scene = bpy.context.scene
    for name, engine, device, spectral in VARIANTS:
        cfg = scene.superluxcore.config
        cfg.engine = engine
        cfg.device = device
        cfg.sampler = "SOBOL"
        cfg.spectral_enable = spectral
        cfg.seed = 11

        halt = scene.superluxcore.halt
        halt.enable = True
        halt.use_samples = True
        halt.samples = HALT_SAMPLES
        halt.use_time = True
        halt.time = 600
        halt.use_noise_thresh = False

        scene.render.engine = "SUPERLUXCORE"
        scene.render.resolution_x, scene.render.resolution_y = RES
        scene.render.resolution_percentage = 100
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = os.path.join(OUT_DIR, name + ".png")

        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"[{name}] rendered in {time.time()-t0:.1f}s")

        img = bpy.data.images.get("Render Result")
        if img:
            scene.render.image_settings.file_format = "OPEN_EXR"
            scene.render.image_settings.exr_codec = "ZIP"
            scene.render.image_settings.color_depth = "32"
            img.save_render(os.path.join(OUT_DIR, name + ".exr"), scene=scene)
            scene.render.image_settings.file_format = "PNG"


main()
