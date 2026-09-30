# e57 — light-tracing / MNEE auto-aware export regression
# (export-level, no render).
#
# Since the engine gained caustic-scene auto-enable
# (path.lighttracing.auto / path.mnee.auto, both default on), the
# adapter must NOT pin path.lighttracing.enable /
# path.hybridbackforward.enable when the artist keeps "Add Light
# Tracing" on — leaving them unset lets the scene signature decide
# (caustic scenes get the light pass, diffuse-only scenes keep the
# full camera-path budget). Unchecked must export a hard False on BOTH
# flags (on the CPU an exported lighttracing.enable=False is what stops
# auto from re-promoting hybrid). Light-only modes and the CPU
# Light Rays=100% case still force the split. An unchecked MNEE toggle
# must export path.mnee.enable=False to beat path.mnee.auto.
#
# Run:
#   /Applications/Blender.app/Contents/MacOS/Blender --background \
#       --factory-startup --python dev-tools/e57_lighttrace_auto_export_test.py
#
# Exits 0 on PASS, 1 on FAIL.
import os
import sys

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
    results.append((name, bool(cond)))
    print(("ok " if cond else "FAIL ") + name +
          (f"  ({detail})" if detail else ""), flush=True)


def reset_scene():
    sc = bpy.data.scenes.new("e57")
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


LT = "path.lighttracing.enable"
HBF = "path.hybridbackforward.enable"
MNEE = "path.mnee.enable"

# 1. glass + defaults -> both flags unset (engine auto decides),
#    MNEE pinned on
sc = reset_scene()
add_glass_scene(sc)
d = export_defs()
check("default: lighttracing.enable left to auto", LT not in d,
      d.get(LT))
check("default: hybridbackforward.enable left to auto", HBF not in d,
      d.get(HBF))
check("default: mnee pinned on", d.get(MNEE) == "1", d.get(MNEE))

# 2. hbf off -> hard off on both flags (beats the auto signature)
sc = reset_scene()
add_glass_scene(sc)
sc.superluxcore.config.path.hybridbackforward_enable = False
d = export_defs()
check("off: lighttracing.enable=False", d.get(LT) == "0", d.get(LT))
check("off: hybridbackforward.enable=False", d.get(HBF) == "0",
      d.get(HBF))

# 3. hbf on + lighttracing_only on OCL -> forced on
sc = reset_scene()
add_glass_scene(sc)
sc.superluxcore.config.device = "OCL"
sc.superluxcore.config.path.lighttracing_only = True
d = export_defs()
check("lt.only: lighttracing.enable forced on", d.get(LT) == "1",
      d.get(LT))
check("lt.only: hbf still auto", HBF not in d, d.get(HBF))

# 4. CPU + Light Rays=100% -> hbf forced on (light-pass-only render)
sc = reset_scene()
add_glass_scene(sc)
sc.superluxcore.config.device = "CPU"
sc.superluxcore.config.path.hybridbackforward_lightpartition = 100
d = export_defs()
check("cpu light-only: hbf forced on", d.get(HBF) == "1", d.get(HBF))

# 5. mnee off -> hard off (beats path.mnee.auto)
sc = reset_scene()
add_glass_scene(sc)
sc.superluxcore.config.mnee_enable = False
d = export_defs()
check("mnee off: mnee.enable=False", d.get(MNEE) == "0", d.get(MNEE))

fails = [n for n, ok in results if not ok]
print(f"\n===== e57: {len(results) - len(fails)}/{len(results)} PASS "
      f"=====")
if fails:
    print("FAILED: " + ", ".join(fails))
    sys.exit(1)
sys.exit(0)
