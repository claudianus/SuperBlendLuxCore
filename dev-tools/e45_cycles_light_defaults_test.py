# SPDX-License-Identifier: Apache-2.0
#
# E45: regression test — Cycles-authored lights/worlds must export through
# the Cycles conversion path.
#
# Resolution semantics (utils.misc.use_cycles_compat):
#   1. An explicitly stored use_cycles_settings flag wins. It is written
#      once per datablock: at creation the depsgraph tagger pins it to
#      the authoring engine, at save the save_pre handler freezes the
#      resolved mode, and the UI mode toggle writes it directly.
#   2. Authored LuxCore settings force the native path.
#   3. Untouched datablocks follow the file context (LuxCore-authored
#      file -> native, foreign file -> Cycles fallback).
#
# To simulate a foreign (Cycles-authored) datablock, fixtures are
# created while scene.render.engine is a foreign engine so the runtime
# pin lands as use_cycles_settings=True — the same state a real
# Cycles-authored file produces.
#
# Run:
#   /Applications/Blender.app/Contents/MacOS/Blender --background \
#       --factory-startup --python dev-tools/e45_cycles_light_defaults_test.py
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


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"[E45-TEST] {'ok' if ok else 'FAIL'}: {name} {detail}", flush=True)


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


def addon_module(name):
    import importlib
    key = next(a.module for a in bpy.context.preferences.addons
               if "superluxcore" in a.module.lower())
    return importlib.import_module(key + "." + name)


def convert(obj, is_world=False):
    """Run the real light/world converter, return its Properties."""
    import pysuperluxcore
    export = addon_module("export")
    light_mod = addon_module("export.light")
    exporter = export.Exporter()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    scene = depsgraph.scene_eval
    if is_world:
        return light_mod.convert_world(exporter, obj, scene, False)
    slc_scene = pysuperluxcore.Scene()
    return light_mod.convert_light(
        exporter, obj, obj.name, depsgraph, slc_scene,
        obj.matrix_world, False)[0]


def get(props, name, idx=0):
    if name not in props.GetAllNames():
        return None
    p = props.Get(name)
    if name.endswith((".type", ".file")):
        return p.GetString(idx)
    try:
        return p.GetFloat(idx)
    except Exception:
        return p.GetString(idx)


def tick():
    """Force a depsgraph evaluation so depsgraph_update_post runs and
    pins newly created lights/worlds to the authoring engine."""
    bpy.context.view_layer.update()


def new_light(name, light_type, foreign=False, pinned=True, **kwargs):
    """Create a light and object. `foreign` pins it via a non-LuxCore
    authoring engine; `pinned=False` simulates a file-loaded datablock
    (no runtime pin - the uid is seeded so the tagger skips it)."""
    scene = bpy.context.scene
    if foreign:
        prev = scene.render.engine
        scene.render.engine = "BLENDER_EEVEE"
    ld = bpy.data.lights.new(name, type=light_type)
    for key, value in kwargs.items():
        setattr(ld, key, value)
    obj = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(obj)
    if pinned:
        tick()
        if foreign:
            scene.render.engine = prev
            tick()
    else:
        assert not foreign
        _misc()._known_light_world_uids.add(ld.session_uid)
    return obj, ld


def new_world(name, foreign=False, pinned=True):
    scene = bpy.context.scene
    if foreign:
        prev = scene.render.engine
        scene.render.engine = "BLENDER_EEVEE"
    world = bpy.data.worlds.new(name)
    if pinned:
        tick()
        if foreign:
            scene.render.engine = prev
            tick()
    else:
        assert not foreign
        _misc()._known_light_world_uids.add(world.session_uid)
    return world


def _misc():
    return addon_module("utils.misc")


def distant_norm_factor(energy, angle):
    half_angle = math.degrees(angle) / 2
    cos_t = min(math.cos(math.radians(half_angle)), 1 - 1e-9)
    return energy / (2 * math.pi * (1 - cos_t))


def main():
    ensure_superluxcore()
    scene = bpy.context.scene
    misc = addon_module("utils.misc")

    # --- 1) Foreign-authored untouched sun -> distant light, gain =
    #        energy * normalization ---
    sun_obj, sun = new_light("sun_cycles", "SUN", foreign=True)
    sun.energy = 1000.0
    sun.angle = 0.00918
    check("foreign_sun_resolves_cycles",
          misc.use_cycles_compat(sun.superluxcore) is True)
    props = convert(sun_obj)
    ltype = get(props, "scene.lights.sun_cycles.type")
    gain = get(props, "scene.lights.sun_cycles.gain")
    expect = distant_norm_factor(1000.0, sun.angle)
    check("sun_cycles_type_distant", ltype == "distant", f"type={ltype}")
    check("sun_cycles_gain_energy", gain is not None
          and abs(gain - expect) / expect < 0.01,
          f"gain={gain} expect={expect:.0f}")

    # --- 2) Stored legacy dict flag (older files) -> honored, native
    #        path. A load-era datablock carries no RNA pin, so the
    #        stored dict member is the authoritative signal. ---
    obj2, sun2 = new_light("sun_native", "SUN", pinned=False)
    sun2["superluxcore"] = {"use_cycles_settings": 0}
    check("explicit_false_resolves_native",
          misc.use_cycles_compat(sun2.superluxcore) is False)
    props = convert(obj2)
    ltype = get(props, "scene.lights.sun_native.type")
    gain = get(props, "scene.lights.sun_native.gain")
    check("sun_native_type_sun", ltype == "sun", f"type={ltype}")
    check("sun_native_gain_skysun", gain is not None and gain < 1e-3,
          f"gain={gain}")

    # --- 3) Flag unset but native prop authored -> native path ---
    obj3, sun3 = new_light("sun_authored", "SUN", pinned=False)
    sun3.superluxcore.turbidity = 7.0
    check("authored_native_resolves_native",
          misc.use_cycles_compat(sun3.superluxcore) is False)
    props = convert(obj3)
    ltype = get(props, "scene.lights.sun_authored.type")
    turb = get(props, "scene.lights.sun_authored.turbidity")
    check("authored_native_type_sun", ltype == "sun", f"type={ltype}")
    check("authored_native_turbidity", turb == 7.0, f"turbidity={turb}")

    # --- 4) Shared prop alone (importance) must NOT pin native ---
    obj4, pt = new_light("pt_imp", "POINT", foreign=True)
    pt.energy = 42.0
    pt.superluxcore.importance = 2.0
    check("importance_keeps_cycles",
          misc.use_cycles_compat(pt.superluxcore) is True)
    props = convert(obj4)
    ltype = get(props, "scene.lights.pt_imp.type")
    gain = get(props, "scene.lights.pt_imp.gain")
    check("point_cycles_type", ltype == "point", f"type={ltype}")
    check("point_cycles_gain", gain == 42.0, f"gain={gain}")

    # --- 5) Cycles world with unlinked output -> no world light ---
    world = new_world("w_unlinked", foreign=True)
    out5 = world.node_tree.nodes.get("World Output")
    for link in list(out5.inputs["Surface"].links):
        world.node_tree.links.remove(link)
    props = convert(world, is_world=True)
    check("world_unlinked_no_light", props is None,
          f"props={props}")

    # --- 6) Cycles world Background -> constantinfinite w/ strength ---
    world6 = new_world("w_bg", foreign=True)
    world6.use_nodes = True
    out = world6.node_tree.nodes.get("World Output")
    bg = world6.node_tree.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.4, 0.6, 1.0, 1.0)
    bg.inputs["Strength"].default_value = 2.0
    world6.node_tree.links.new(bg.outputs["Background"], out.inputs["Surface"])
    props = convert(world6, is_world=True)
    ltype = get(props, "scene.lights.__WORLD_BACKGROUND_LIGHT__.type")
    gain = get(props, "scene.lights.__WORLD_BACKGROUND_LIGHT__.gain")
    check("world_cycles_type", ltype == "constantinfinite",
          f"type={ltype}")
    check("world_cycles_gain", gain == 2.0, f"gain={gain}")

    # --- 7) Stored legacy flag on a world -> native sky2 ---
    world7 = new_world("w_native", pinned=False)
    world7["superluxcore"] = {"use_cycles_settings": 0}
    props = convert(world7, is_world=True)
    ltype = get(props, "scene.lights.__WORLD_BACKGROUND_LIGHT__.type")
    check("world_native_sky2", ltype == "sky2", f"type={ltype}")

    failed = [name for name, ok in RESULTS if not ok]
    print(f"[E45-TEST] {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    if failed:
        print("[E45-TEST] FAILURES:", ", ".join(failed))
        sys.exit(1)
    print("[E45-TEST] PASS")


main()
