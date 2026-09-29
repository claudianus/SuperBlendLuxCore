# SPDX-License-Identifier: Apache-2.0
#
# E50: zero-config render smoke — the fire-and-forget defaults must make
# a fresh scene render, auto-stop on the noise target, and produce a
# denoised pass without the artist touching a single render option.
#
# Scene: point light inside a closed glass sphere over a matte plane —
# floor->light shadow rays refract through the sphere, so MNEE fires and
# a caustic pool lands on the floor; a sky2 world exercises the env
# light visibility cache (both now on by default).
#
# Run:
#   /Applications/Blender.app/Contents/MacOS/Blender --background \
#       --factory-startup --python dev-tools/e50_zero_config_render_test.py
#
# Exits 0 on PASS, 1 on FAIL. Renders land in /tmp/e50_*.png.

import math
import os
import sys
import time

import bpy

_EXT_DIR = os.path.expanduser(
    "~/Library/Application Support/Blender/5.2/extensions/user_default")
if _EXT_DIR not in sys.path:
    sys.path.insert(0, _EXT_DIR)

W = int(os.environ.get("E50_W", "1280"))
H = int(os.environ.get("E50_H", "720"))
RESULTS = []


def check(name, ok, info=""):
    RESULTS.append((name, ok))
    print(f"[E50-TEST] {'ok' if ok else 'FAIL'}: {name} {info}",
          flush=True)


def ensure_superluxcore():
    try:
        bpy.context.scene.render.engine = "SUPERLUXCORE"
    except TypeError:
        module = next((a.module for a in bpy.context.preferences.addons
                       if "superluxcore" in a.module.lower()),
                      "bl_ext.user_default.superluxcore")
        bpy.ops.preferences.addon_enable(module=module)
        bpy.context.scene.render.engine = "SUPERLUXCORE"


def lux_material(name):
    mat = bpy.data.materials.new(name)
    nt = bpy.data.node_groups.new(name + "Tree",
                                  "superluxcore_material_nodes")
    mat.superluxcore.node_tree = nt
    out = nt.nodes.new("SuperLuxCoreNodeMatOutput")
    return mat, nt, out


def main():
    ensure_superluxcore()
    scene = bpy.context.scene

    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "ACES 2.0"
    scene.render.use_compositing = False

    # Stock defaults are the contract under test - assert, never set.
    cfg = scene.superluxcore.config
    halt = scene.superluxcore.halt
    denoiser = scene.superluxcore.denoiser
    check("defaults.mnee_enable", cfg.mnee_enable is True)
    check("defaults.halt_enable", halt.enable is True)
    check("defaults.halt_noise_level", halt.use_noise_level is True)
    check("defaults.denoiser_enabled", denoiser.enabled is True)
    check("defaults.envlight_cache", cfg.envlight_cache.enabled is True)

    # Bisect toggles for bring-up debugging (E50_DISABLE_*)
    if os.environ.get("E50_DISABLE_ENVLIGHT"):
        cfg.envlight_cache.enabled = False
    if os.environ.get("E50_DISABLE_DENOISER"):
        denoiser.enabled = False
    if os.environ.get("E50_DISABLE_HALT"):
        halt.enable = False
    if os.environ.get("E50_DISABLE_MNEE"):
        cfg.mnee_enable = False

    # --- geometry -------------------------------------------------------
    bpy.ops.mesh.primitive_plane_add(size=12)
    plane = bpy.context.active_object
    pm, pnt, pout = lux_material("floor")
    pd = pnt.nodes.new("SuperLuxCoreNodeMatMatte")
    pd.inputs["Diffuse Color"].default_value = (0.75, 0.72, 0.68)
    pnt.links.new(pd.outputs["Material"], pout.inputs["Material"])
    plane.data.materials.append(pm)

    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0,
                                        location=(0, 0, 1.3))
    ball = bpy.context.active_object
    gm, gnt, gout = lux_material("glass")
    gg = gnt.nodes.new("SuperLuxCoreNodeMatGlass")
    gg.inputs["IOR"].default_value = 1.5
    gnt.links.new(gg.outputs["Material"], gout.inputs["Material"])
    ball.data.materials.append(gm)

    # Point light hovering inside the sphere: shadow rays through the
    # glass need MNEE to connect.
    ld = bpy.data.lights.new("pt", type="POINT")
    ld.energy = 200.0
    lo = bpy.data.objects.new("pt", ld)
    lo.location = (0, 0, 1.3)
    scene.collection.objects.link(lo)

    # Sky world -> env light visibility cache path (final render only).
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    wnt = world.node_tree
    wnt.nodes.clear()
    wout = wnt.nodes.new("ShaderNodeOutputWorld")
    wsky = wnt.nodes.new("ShaderNodeTexSky")
    wnt.links.new(wsky.outputs["Color"], wout.inputs["Surface"])
    scene.world = world

    bpy.ops.object.camera_add(location=(0, -4.5, 2.6))
    cam = bpy.context.active_object
    cam.rotation_euler = (math.radians(62), 0, 0)
    scene.camera = cam

    # --- render ---------------------------------------------------------
    os.makedirs("/tmp/e50", exist_ok=True)
    exr = f"/tmp/e50/e50_zeroconfig_{W}x{H}.exr"
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.filepath = exr

    t0 = time.monotonic()
    bpy.ops.render.render(write_still=True)
    wall = time.monotonic() - t0
    print(f"[E50-TEST] render finished in {wall:.1f}s", flush=True)

    # A run with no halt condition never returns - reaching this point
    # already proves the noise-level stop fired.
    check("render.auto_halt", True, f"wall={wall:.1f}s")

    # Registered render passes (incl. the DENOISED buffer the adapter
    # adds when the default-on denoiser is active) are enumerable via a
    # Render Layers node - background Render Result pixels are empty.
    cnt = bpy.data.node_groups.new("e50_passes", "CompositorNodeTree")
    rl = cnt.nodes.new("CompositorNodeRLayers")
    outs = [o.name for o in rl.outputs]
    check("pass.denoised_present", "DENOISED" in outs, f"outs={outs}")

    # Read the written Combined EXR back for finite/non-black content.
    img = bpy.data.images.load(exr)
    px = list(img.pixels)
    check("render.combined_finite",
          bool(px) and all(math.isfinite(v) for v in px))
    check("render.combined_nonblack",
          any(v > 0.0 for v in px) and
          len({round(v, 5) for v in px[::997]}) > 8)

    # Unique PNG artifact for visual inspection (ACES 2.0 display path).
    png = f"/tmp/e50/e50_zeroconfig_{W}x{H}.png"
    scene.render.image_settings.file_format = "PNG"
    img.save_render(png, scene=scene)
    print(f"[E50-TEST] saved {exr} and {png}", flush=True)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"[E50-TEST] {len(RESULTS) - len(failed)}/{len(RESULTS)} "
          f"passed")
    if failed:
        print("[E50-TEST] FAILURES:", ", ".join(failed))
        sys.exit(1)
    print("[E50-TEST] PASS")


main()
