# SPDX-License-Identifier: Apache-2.0
#
# E48: regression test — light/world interpretation resolution and
# legacy node-tree alias visibility.
#
# A) Interpretation (utils.misc.use_cycles_compat):
#    - datablocks created while the scene renders with SUPERLUXCORE are
#      pinned native (use_cycles_settings=False) by the depsgraph tagger
#    - datablocks created under a foreign engine pin Cycles
#    - a stored flag (pin or toggle) survives save/load roundtrips
#    - untouched datablocks follow the file context
#
# B) Legacy alias visibility:
#    - luxcore_*_nodes tree aliases exist for .blend compatibility but
#      must stay out of the node editor's tree-type menu unless the file
#      actually contains such a tree (presence-gated poll)
#    - alias node types are only offerable inside legacy trees
#
# Run:
#   /Applications/Blender.app/Contents/MacOS/Blender --background \
#       --factory-startup --python dev-tools/e48_datablock_mode_resolution_test.py
#
# Exits 0 on PASS, 1 on FAIL.

import os
import sys
import tempfile

import bpy

_EXT_DIR = os.path.expanduser(
    "~/Library/Application Support/Blender/5.2/extensions/user_default")
if _EXT_DIR not in sys.path:
    sys.path.insert(0, _EXT_DIR)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, ok))
    print(f"[E48-TEST] {'ok' if ok else 'FAIL'}: {name} {detail}",
          flush=True)


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


def tick():
    bpy.context.view_layer.update()


def set_engine(engine):
    bpy.context.scene.render.engine = engine
    tick()


def main():
    ensure_superluxcore()
    scene = bpy.context.scene
    misc = addon_module("utils.misc")
    nodes_mod = addon_module("nodes")
    utils_node = addon_module("utils.node")

    # register() runs in a restricted context; establish the file
    # context + uid snapshot before creating fixtures.
    misc.refresh_file_context()

    # ------------------------------------------------ A) resolution --

    # 1) Light created under SUPERLUXCORE -> pinned native
    ld = bpy.data.lights.new("L_native", type="AREA")
    obj = bpy.data.objects.new("L_native", ld)
    scene.collection.objects.link(obj)
    tick()
    check("luxcore_created_light_pinned",
          ld.superluxcore.is_property_set("use_cycles_settings")
          and ld.superluxcore.use_cycles_settings is False)
    check("luxcore_created_light_native",
          misc.use_cycles_compat(ld.superluxcore) is False)

    # 2) World created under SUPERLUXCORE -> pinned native
    world = bpy.data.worlds.new("W_native")
    world.use_fake_user = True
    tick()
    check("luxcore_created_world_native",
          misc.use_cycles_compat(world.superluxcore) is False)

    # 3) Light created under a foreign engine -> pinned cycles
    set_engine("BLENDER_EEVEE")
    ld2 = bpy.data.lights.new("L_foreign", type="POINT")
    obj2 = bpy.data.objects.new("L_foreign", ld2)
    scene.collection.objects.link(obj2)
    tick()
    check("foreign_created_light_pinned_cycles",
          ld2.superluxcore.is_property_set("use_cycles_settings")
          and ld2.superluxcore.use_cycles_settings is True)
    check("foreign_created_light_cycles",
          misc.use_cycles_compat(ld2.superluxcore) is True)
    set_engine("SUPERLUXCORE")
    check("foreign_pin_survives_engine_switch",
          misc.use_cycles_compat(ld2.superluxcore) is True)

    # 4) Manual mode toggle (what the UI operator writes) flips result
    ld2.superluxcore.use_cycles_settings = False
    check("manual_toggle_to_native",
          misc.use_cycles_compat(ld2.superluxcore) is False)
    ld2.superluxcore.use_cycles_settings = True

    # 4b) The UI operator itself (context.light override)
    with bpy.context.temp_override(light=ld2):
        bpy.ops.superluxcore.set_light_world_mode(
            target="LIGHT", use_cycles_settings=False)
    check("operator_sets_native",
          ld2.superluxcore.use_cycles_settings is False)
    with bpy.context.temp_override(light=ld2):
        bpy.ops.superluxcore.set_light_world_mode(
            target="LIGHT", use_cycles_settings=True)
    check("operator_sets_cycles",
          ld2.superluxcore.use_cycles_settings is True)

    # 5) File-context fallback for untouched load-era datablocks
    ld3 = bpy.data.lights.new("L_untouched", type="AREA")
    ld3.use_fake_user = True
    misc._known_light_world_uids.add(ld3.session_uid)  # load-era
    misc._file_authored_luxcore = True
    check("luxcore_file_untouched_native",
          misc.use_cycles_compat(ld3.superluxcore) is False)
    misc._file_authored_luxcore = False
    check("foreign_file_untouched_cycles",
          misc.use_cycles_compat(ld3.superluxcore) is True)
    misc._file_authored_luxcore = True  # restore (engine is SUPERLUXCORE)

    # 6) save/reload roundtrip: pins persist, interpretation stable
    tmp = os.path.join(tempfile.mkdtemp(), "e48_roundtrip.blend")
    res_before = {d.name: misc.use_cycles_compat(d.superluxcore)
                  for d in (*bpy.data.lights, *bpy.data.worlds)
                  if d.library is None}
    bpy.ops.wm.save_as_mainfile(filepath=tmp)
    bpy.ops.wm.open_mainfile(filepath=tmp)
    res_after = {d.name: misc.use_cycles_compat(d.superluxcore)
                 for d in (*bpy.data.lights, *bpy.data.worlds)
                 if d.library is None}
    check("roundtrip_resolution_stable", res_before == res_after,
          f"{res_before} vs {res_after}")
    check("roundtrip_flag_persisted",
          bpy.data.lights["L_foreign"].superluxcore
          .is_property_set("use_cycles_settings"))
    check("roundtrip_file_context",
          misc._file_authored_luxcore is True)

    # --------------------------------------------- B) alias polling --

    # 7) tree-type alias poll: hidden unless a legacy group exists
    tree_aliases = {c.bl_idname: c for c in nodes_mod._legacy_alias_classes
                    if c.bl_idname.endswith("_nodes")}
    check("three_tree_aliases", len(tree_aliases) == 3,
          f"{sorted(tree_aliases)}")
    ctx = bpy.context
    check("alias_poll_hidden_empty",
          not any(c.poll(ctx) for c in tree_aliases.values()))

    legacy_tree = bpy.data.node_groups.new("LegacyTree",
                                           "luxcore_material_nodes")
    check("legacy_tree_type", legacy_tree.bl_idname
          == "luxcore_material_nodes")
    check("alias_poll_visible_when_present",
          tree_aliases["luxcore_material_nodes"].poll(ctx) is True)
    check("other_alias_poll_still_hidden",
          tree_aliases["luxcore_texture_nodes"].poll(ctx) is False)

    # 8) node alias poll: only inside legacy trees
    node_aliases = {c.bl_idname: c for c in nodes_mod._legacy_alias_classes
                    if not c.bl_idname.endswith("_nodes")}
    mat_out = node_aliases.get("LuxCoreNodeMatOutput")
    check("mat_output_alias_exists", mat_out is not None)
    if mat_out:
        check("node_alias_in_legacy_tree", mat_out.poll(legacy_tree)
              is True)
        canon_tree = bpy.data.node_groups.new("CanonTree",
                                              "superluxcore_material_nodes")
        check("node_alias_not_in_canon_tree", mat_out.poll(canon_tree)
              is False)

    # 9) mixed tree: canonical output inside a legacy tree is found
    out = legacy_tree.nodes.new("SuperLuxCoreNodeMatOutput")
    out.active = True
    found = utils_node.get_active_output(legacy_tree)
    check("mixed_tree_active_output", found == out, f"{found}")

    # 10) node_groups.new for canonical + legacy stays functional
    tex_tree = bpy.data.node_groups.new("TexTree", "superluxcore_texture_nodes")
    tex_tree.nodes.new("SuperLuxCoreNodeTexOutput")
    check("canonical_tex_tree_works", True)


main()

failed = [name for name, ok in RESULTS if not ok]
print(f"[E48-TEST] {len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
if failed:
    print("[E48-TEST] FAILURES:", ", ".join(failed))
    sys.exit(1)
print("[E48-TEST] PASS")
