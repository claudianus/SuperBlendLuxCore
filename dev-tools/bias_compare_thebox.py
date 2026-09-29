"""
Engine-consistency comparison on a real artist scene (thebox4/Untitled.blend).

    Blender -b Untitled.blend --python dev-tools/bias_compare_thebox.py

Renders the loaded scene with BIDIRCPU / PATHCPU / PATHOCL at 720p,
writes one PNG + one EXR per engine into /tmp/thebox4_compare/ and
prints a scene summary. Compare output with compare_thebox.py.
"""

import os
import time

import bpy

OUT_DIR = "/tmp/thebox4_compare"
RES = (1280, 720)
HALT_SAMPLES = 256
HALT_TIME = 600          # per-engine wall budget (seconds)
SEED = 11

VARIANTS = [
    # (name, engine, device)
    ("bidir_cpu", "BIDIR", "CPU"),
    ("path_cpu", "PATH", "CPU"),
    ("path_ocl", "PATH", "OCL"),
]


def scene_summary(scene):
    lights = [o for o in scene.objects if o.type == "LIGHT"]
    mats = [m for m in bpy.data.materials]
    meshes = [o for o in scene.objects if o.type == "MESH"]
    n_tris = sum(len(m.data.polygons) for m in meshes)
    print(f"[Summary] objects={len(scene.objects)} meshes={len(meshes)} "
          f"polys={n_tris} materials={len(mats)} lights={len(lights)}")
    for l in lights:
        print(f"  light {l.name}: type={l.data.type} energy={l.data.energy} "
              f"color={tuple(round(c, 3) for c in l.data.color)}")
    for m in mats:
        kinds = []
        if m.use_nodes and m.node_tree:
            kinds = sorted({n.bl_idname for n in m.node_tree.nodes
                            if n.bl_idname.startswith("ShaderNodeBsdf")})
        print(f"  mat {m.name}: {kinds}")
    w = scene.world
    if w and w.use_nodes and w.node_tree:
        print("  world nodes:", sorted({n.bl_idname for n in w.node_tree.nodes}))


def configure(scene, engine, device):
    cfg = scene.superluxcore.config
    cfg.engine = engine
    if engine == "PATH":
        cfg.device = device
        cfg.sampler = "SOBOL"
    else:
        cfg.bidir_device = "CPU"

    halt = scene.superluxcore.halt
    halt.enable = True
    halt.use_samples = True
    halt.samples = HALT_SAMPLES
    halt.use_time = True
    halt.time = HALT_TIME
    halt.use_noise_thresh = False

    scene.render.engine = "SUPERLUXCORE"
    scene.render.resolution_x, scene.render.resolution_y = RES
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    cfg.seed = SEED


def render_to(scene, name):
    png = os.path.join(OUT_DIR, f"{name}.png")
    scene.render.filepath = png
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    dt = time.time() - t0
    print(f"[{name}] rendered in {dt:.1f}s -> {png}")

    # linear EXR for numeric comparison (bypass tonemapper output)
    img = bpy.data.images.get("Render Result")
    if img:
        exr = os.path.join(OUT_DIR, f"{name}.exr")
        scene.render.image_settings.file_format = "OPEN_EXR"
        scene.render.image_settings.exr_codec = "ZIP"
        scene.render.image_settings.color_depth = "32"
        img.save_render(exr, scene=scene)
        scene.render.image_settings.file_format = "PNG"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    scene = bpy.context.scene
    scene_summary(scene)

    for name, engine, device in VARIANTS:
        print(f"\n===== {name}: engine={engine} device={device} =====")
        configure(scene, engine, device)
        try:
            render_to(scene, name)
        except Exception as e:
            print(f"[{name}] FAILED: {e}")

    print("\nDone. Compare with: compare_thebox.py")


main()
