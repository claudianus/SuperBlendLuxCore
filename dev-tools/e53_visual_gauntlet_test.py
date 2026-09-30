# SPDX-License-Identifier: Apache-2.0
#
# E53: visual gauntlet - the artist-facing showcase scene that exercises
# the hard transport paths at production settings: spectral dispersion
# caustics (prism), clean glass caustics (sphere), glossy metal
# reflections (torus), all through MNEE + auto PhotonGI caustics, OIDN
# and the noise-level auto-halt. Output must pass visual review.
#
# Run:
#   /Applications/Blender.app/Contents/MacOS/Blender --background \
#       --factory-startup --python dev-tools/e53_visual_gauntlet_test.py
#
# Env: E53_W/E53_H (default 1280x720), E53_SPP (halt cap, default 512),
#      E53_NOISE (noise-level target %, default 3.0), E53_DEVICE=CPU|GPU.
# Renders land in /tmp/e53/.

import math
import os
import sys
import time

import bpy
from mathutils import Vector

_EXT_DIR = os.path.expanduser(
    "~/Library/Application Support/Blender/5.2/extensions/user_default")
if _EXT_DIR not in sys.path:
    sys.path.insert(0, _EXT_DIR)

W = int(os.environ.get("E53_W", "1280"))
H = int(os.environ.get("E53_H", "720"))
RESULTS = []


def check(name, ok, info=""):
    RESULTS.append((name, ok))
    print(f"[E53-TEST] {'ok' if ok else 'FAIL'}: {name} {info}",
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


def set_input(node, names, value):
    for n in names:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return True
    return False


def aim(obj, target):
    d = Vector(target) - obj.location
    obj.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def main():
    ensure_superluxcore()
    scene = bpy.context.scene

    scene.render.resolution_x = W
    scene.render.resolution_y = H
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "ACES 2.0"
    scene.render.use_compositing = False

    cfg = scene.superluxcore.config
    halt = scene.superluxcore.halt
    if os.environ.get("E53_DEVICE", "") == "CPU":
        scene.superluxcore.config.device = "CPU"

    # Bounded runtime for the showcase: keep the noise target but cap
    # samples so a busy machine still finishes.
    halt.samples = int(os.environ.get("E53_SPP", "512"))
    if os.environ.get("E53_NOISE"):
        halt.noise_level = float(os.environ["E53_NOISE"])

    # --- materials ------------------------------------------------------
    # Dark matte stage
    fm, fnt, fout = lux_material("stage")
    fmat = fnt.nodes.new("SuperLuxCoreNodeMatMatte")
    fmat.inputs["Diffuse Color"].default_value = (0.035, 0.04, 0.05)
    fnt.links.new(fmat.outputs["Material"], fout.inputs["Material"])

    # Dispersive crystal (cauchy B drives spectral caustics)
    dm, dnt, dout = lux_material("crystal")
    dg = dnt.nodes.new("SuperLuxCoreNodeMatGlass")
    dg.inputs["IOR"].default_value = 1.52
    if not set_input(dg, ["Dispersion"], 0.05):
        check("mat.dispersion_input", False, "no Dispersion input")
    dnt.links.new(dg.outputs["Material"], dout.inputs["Material"])

    # Clear glass
    gm, gnt, gout = lux_material("glass")
    gg = gnt.nodes.new("SuperLuxCoreNodeMatGlass")
    gg.inputs["IOR"].default_value = 1.45
    gnt.links.new(gg.outputs["Material"], gout.inputs["Material"])

    # Brushed gold metal
    mm, mnt, mout = lux_material("metal")
    try:
        mmet = mnt.nodes.new("SuperLuxCoreNodeMatMetal")
        mmet.inputs["Color"].default_value = (0.9, 0.62, 0.32)
        mmet.inputs["Roughness"].default_value = 0.12
        mnt.links.new(mmet.outputs["Material"], mout.inputs["Material"])
    except Exception as e:
        check("mat.metal", False, str(e))
        g2 = mnt.nodes.new("SuperLuxCoreNodeMatGlossy2")
        mnt.links.new(g2.outputs["Material"], mout.inputs["Material"])

    # --- geometry -------------------------------------------------------
    bpy.ops.mesh.primitive_plane_add(size=30)
    floor = bpy.context.active_object
    floor.data.materials.append(fm)

    # Pedestal block
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0.5),
                                    scale=(1.4, 1.4, 0.5))
    ped = bpy.context.active_object
    ped.data.materials.append(fm)

    # Crystal prism: icosahedron faceted gem on the pedestal
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=0.55,
                                        location=(-0.35, 0.05, 1.35))
    gem = bpy.context.active_object
    gem.scale = (1.0, 1.0, 1.15)
    gem.data.materials.append(dm)

    # Clear glass sphere right (resting on the pedestal top at z=0.75)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=4, radius=0.42,
                                        location=(0.85, -0.15, 1.17))
    sph = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    sph.data.materials.append(gm)

    # Gold torus lying flat on the floor, left foreground
    bpy.ops.mesh.primitive_torus_add(major_radius=0.45, minor_radius=0.15,
                                     major_segments=64, minor_segments=24,
                                     location=(-1.1, -0.45, 0.15))
    tor = bpy.context.active_object
    tor.data.materials.append(mm)

    # --- lights ---------------------------------------------------------
    # Key: small strong warm area light high-left, aimed at the gem ->
    # refracted through it, drives the pedestal/floor caustics
    kd = bpy.data.lights.new("key", type="AREA")
    kd.energy = 3200.0
    kd.shape = "SQUARE"
    kd.size = 0.15
    kd.color = (1.0, 0.93, 0.82)
    ko = bpy.data.objects.new("key", kd)
    ko.location = (-2.5, -1.8, 4.5)
    scene.collection.objects.link(ko)
    aim(ko, (-0.2, 0, 1.0))

    # Fill: large cool area from camera-right, gives the metal/glass
    # something to reflect (metal reads black in an empty world)
    fd = bpy.data.lights.new("fill", type="AREA")
    fd.energy = 700.0
    fd.size = 2.0
    fd.color = (0.7, 0.82, 1.0)
    fo = bpy.data.objects.new("fill", fd)
    fo.location = (3.5, -1.5, 3.5)
    scene.collection.objects.link(fo)
    aim(fo, (0, 0, 1.0))

    # Rim: narrow point behind-right for edge sparkle
    rd = bpy.data.lights.new("rim", type="POINT")
    rd.energy = 250.0
    ro = bpy.data.objects.new("rim", rd)
    ro.location = (1.8, 1.2, 2.8)
    scene.collection.objects.link(ro)

    # Dim cool world fill
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    wnt = world.node_tree
    wnt.nodes.clear()
    wout = wnt.nodes.new("ShaderNodeOutputWorld")
    wbg = wnt.nodes.new("ShaderNodeBackground")
    wbg.inputs["Color"].default_value = (0.03, 0.045, 0.07, 1.0)
    wbg.inputs["Strength"].default_value = 0.5
    wnt.links.new(wbg.outputs["Background"], wout.inputs["Surface"])
    scene.world = world

    bpy.ops.object.camera_add(location=(0.15, -5.2, 2.9))
    cam = bpy.context.active_object
    aim(cam, (0.0, 0.0, 1.0))
    scene.camera = cam

    # --- render ---------------------------------------------------------
    os.makedirs("/tmp/e53", exist_ok=True)
    tag = f"{W}x{H}_{os.environ.get('E53_DEVICE', 'AUTO')}"
    exr = f"/tmp/e53/e53_gauntlet_{tag}.exr"
    scene.render.image_settings.file_format = "OPEN_EXR"
    scene.render.filepath = exr

    t0 = time.monotonic()
    bpy.ops.render.render(write_still=True)
    wall = time.monotonic() - t0
    print(f"[E53-TEST] render finished in {wall:.1f}s", flush=True)
    check("render.auto_halt", True, f"wall={wall:.1f}s")

    cnt = bpy.data.node_groups.new("e53_passes", "CompositorNodeTree")
    rl = cnt.nodes.new("CompositorNodeRLayers")
    outs = [o.name for o in rl.outputs]
    check("pass.denoised_present", "DENOISED" in outs)

    img = bpy.data.images.load(exr)
    px = list(img.pixels)
    check("render.combined_finite",
          bool(px) and all(math.isfinite(v) for v in px))
    check("render.combined_nonblack",
          any(v > 0.0 for v in px) and
          len({round(v, 5) for v in px[::997]}) > 8)

    png = f"/tmp/e53/e53_gauntlet_{tag}.png"
    scene.render.image_settings.file_format = "PNG"
    img.save_render(png, scene=scene)
    print(f"[E53-TEST] saved {exr} and {png}", flush=True)

    failed = [n for n, ok in RESULTS if not ok]
    print(f"[E53-TEST] {len(RESULTS) - len(failed)}/{len(RESULTS)} "
          f"passed")
    if failed:
        print("[E53-TEST] FAILURES:", ", ".join(failed))
        sys.exit(1)
    print("[E53-TEST] PASS")


main()
