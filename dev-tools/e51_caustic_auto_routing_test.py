# e51 — caustic auto-routing regression (export-level, no render).
# Verifies that caustic_mode=auto enables the PhotonGI caustic cache for
# transmissive scenes even with the PhotonGI master toggle OFF, that the
# heavy indirect pass stays gated on the master toggle, and that explicit
# on/off modes always win.
import os, sys
import bpy

_EXT_DIR = os.path.expanduser(
    "~/Library/Application Support/Blender/5.2/extensions/user_default")
if _EXT_DIR not in sys.path:
    sys.path.insert(0, _EXT_DIR)

try:
    bpy.context.scene.render.engine = "SUPERLUXCORE"
except TypeError:
    bpy.ops.preferences.addon_enable(module="bl_ext.user_default.superluxcore")
    bpy.context.scene.render.engine = "SUPERLUXCORE"

addon = sys.modules["bl_ext.user_default.superluxcore"]

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("ok " if cond else "FAIL ") + name + (f"  ({detail})" if detail else ""),
          flush=True)


def reset_scene():
    # Fresh Scene per case - read_factory_settings would unload/re-register
    # the addon mid-script and leave stale RNA pointers (segfault).
    sc = bpy.data.scenes.new("e51")
    bpy.context.window.scene = sc
    sc.render.engine = "SUPERLUXCORE"
    sc.render.resolution_x = 160
    sc.render.resolution_y = 90
    return sc


def add_glass_scene(sc):
    bpy.ops.mesh.primitive_plane_add(size=8)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=1,
                                        location=(0, 0, 1.2))
    sph = bpy.context.active_object
    m = bpy.data.materials.new("glass")
    m.use_nodes = True
    bsdf = m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Transmission Weight"].default_value = 1.0
    sph.data.materials.append(m)
    ld = bpy.data.lights.new("pt", type="POINT")
    ld.energy = 100.0
    lo = bpy.data.objects.new("pt", ld)
    lo.location = (0, 0, 2.5)
    sc.collection.objects.link(lo)
    bpy.ops.object.camera_add(location=(0, -4, 2))
    sc.camera = bpy.context.active_object


def add_opaque_scene(sc):
    bpy.ops.mesh.primitive_cube_add(size=1)
    m = bpy.data.materials.new("matte")
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    bpy.context.active_object.data.materials.append(m)
    ld = bpy.data.lights.new("pt", type="POINT")
    ld.energy = 100.0
    lo = bpy.data.objects.new("pt", ld)
    lo.location = (0, 0, 3)
    sc.collection.objects.link(lo)
    bpy.ops.object.camera_add(location=(0, -4, 2))
    sc.camera = bpy.context.active_object


class EngineStub:
    aov_imagepipelines = {}
    is_animation = False

    def test_break(self):
        return False

    def __getattr__(self, name):
        return lambda *a, **k: None


def export_defs():
    exporter = addon.export.Exporter()
    _, cfg = exporter.export_scene(
        bpy.context.evaluated_depsgraph_get(), engine=EngineStub(),
        view_layer=bpy.context.view_layer)
    return {k: cfg.Get(k).GetString(0) for k in cfg.GetAllNames()}


pg = "path.photongi."

# 1. glass + auto + master off -> caustic on, indirect off
sc = reset_scene()
add_glass_scene(sc)
d = export_defs()
check("auto: caustic on for glass (master off)",
      d.get(pg + "caustic.enabled") == "1", d.get(pg + "caustic.enabled"))
check("auto: indirect stays off when master off",
      d.get(pg + "indirect.enabled") == "0", d.get(pg + "indirect.enabled"))

# 2. opaque + auto + master off -> no photongi block at all
sc = reset_scene()
add_opaque_scene(sc)
d = export_defs()
check("auto: no caustic for opaque scene", pg + "caustic.enabled" not in d)

# 3. glass + mode=off -> nothing
sc = reset_scene()
add_glass_scene(sc)
sc.superluxcore.config.photongi.caustic_mode = "off"
d = export_defs()
check("off: caustic disabled despite glass", pg + "caustic.enabled" not in d)

# 4. opaque + mode=on + master off -> forced on
sc = reset_scene()
add_opaque_scene(sc)
sc.superluxcore.config.photongi.caustic_mode = "on"
d = export_defs()
check("on: caustic forced for opaque scene",
      d.get(pg + "caustic.enabled") == "1", d.get(pg + "caustic.enabled"))

# 5. glass + auto + master on + indirect on -> both enabled
sc = reset_scene()
add_glass_scene(sc)
sc.superluxcore.config.photongi.enabled = True
d = export_defs()
check("master on: caustic auto-still on",
      d.get(pg + "caustic.enabled") == "1")
check("master on: indirect enabled",
      d.get(pg + "indirect.enabled") == "1")

# 6. legacy caustic_enabled=True under auto -> force on (back-compat)
sc = reset_scene()
add_opaque_scene(sc)
sc.superluxcore.config.photongi.caustic_enabled = True
d = export_defs()
check("legacy bool forces caustic under auto",
      d.get(pg + "caustic.enabled") == "1", d.get(pg + "caustic.enabled"))

# 7. mode=off + legacy bool True -> off wins
sc = reset_scene()
add_glass_scene(sc)
sc.superluxcore.config.photongi.caustic_mode = "off"
sc.superluxcore.config.photongi.caustic_enabled = True
d = export_defs()
check("off beats legacy bool", pg + "caustic.enabled" not in d)

# 8. BIDIR + mode=on -> explicit opt-in is engine-agnostic (regression:
# an engine startswith gate used to swallow on/legacy for non-PATH
# engines even though BIDIRCPU owns a PhotonGI caustic pass)
sc = reset_scene()
add_opaque_scene(sc)
sc.superluxcore.config.engine = "BIDIR"
sc.superluxcore.config.photongi.caustic_mode = "on"
d = export_defs()
check("bidir: mode=on forces caustic",
      d.get(pg + "caustic.enabled") == "1", d.get(pg + "caustic.enabled"))
check("bidir: indirect stays off when master off",
      d.get(pg + "indirect.enabled") == "0", d.get(pg + "indirect.enabled"))

# 9. BIDIR + auto + glass -> transmissive scene engages the cache too
# (BIDIRCPU is a PhotonGI consumer)
sc = reset_scene()
add_glass_scene(sc)
sc.superluxcore.config.engine = "BIDIR"
d = export_defs()
check("bidir: auto engages for glass",
      d.get(pg + "caustic.enabled") == "1", d.get(pg + "caustic.enabled"))

fails = [n for n, c, _ in results if not c]
print(f"\n== e51: {len(results) - len(fails)}/{len(results)} passed" +
      (f" | FAILED: {fails}" if fails else ""), flush=True)
sys.exit(1 if fails else 0)
