"""
e15: automatic configuration defaults (B-UX roadmap item).

Validates, without rendering:

* light_strategy == "AUTO" resolves to LOG_POWER on a sparse scene and to
  RESTIR_DI once the emitter count exceeds
  AUTO_LIGHT_STRATEGY_EMITTER_THRESHOLD.
* AUTO never selects RESTIR_DI on engines that do not support it (the
  engine throws a hard error for that combination).
* An explicit light_strategy choice always wins over AUTO.
* The DLS-cache checkbox still overrides everything.
* auto_clamping applies the suggested clamp value of a previous render,
  and manual clamping takes precedence.
* Sensible production defaults on a fresh scene: denoiser on, halt
  conditions on with a convergence stop and a sample cap.

Run:
  Blender -b --python dev-tools/e15_auto_config_test.py
"""

import bpy
import sys

from bl_ext.user_default.blendluxcore.export import (
    config as export_config,
)
from bl_ext.user_default.blendluxcore.export.config import (
    AUTO_LIGHT_STRATEGY_EMITTER_THRESHOLD,
    _auto_light_strategy,
    _count_emitters,
)


results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), name, detail)


def fresh_scene():
    bpy.ops.scene.new(type="EMPTY")
    scene = bpy.context.scene
    scene.render.engine = "LUXCORE"
    return scene


def add_point_light(scene, name):
    data = bpy.data.lights.new(name, type="POINT")
    obj = bpy.data.objects.new(name, data)
    scene.collection.objects.link(obj)


def light_strategy_of(scene):
    props = export_config.convert(None, scene)
    return props.Get("lightstrategy.type").GetString()


# --- emitter counting -------------------------------------------------

scene = fresh_scene()
check("emitters.empty", _count_emitters(scene) == 0)

for i in range(3):
    add_point_light(scene, f"L{i}")
check("emitters.lights", _count_emitters(scene) == 3)

# lit world counts as one emitter
world = bpy.data.worlds.new("W")
world.use_nodes = True
scene.world = world
check("emitters.world", _count_emitters(scene) == 4)

# emissive mesh weighted by polygon count
mesh = bpy.data.meshes.new("emitmesh")
mesh.from_pydata(
    [(0, 0, 0)] * 4, [], [(0, 1, 2, 3)]
)
mat = bpy.data.materials.new("emitmat")
mat.use_nodes = True
em = mat.node_tree.nodes.new("ShaderNodeEmission")
emit_obj = bpy.data.objects.new("emitobj", mesh)
emit_obj.data.materials.append(mat)
scene.collection.objects.link(emit_obj)
check("emitters.meshlight", _count_emitters(scene) == 5)

# --- AUTO resolution --------------------------------------------------

sparse = _auto_light_strategy(scene, "PATHCPU")
check("auto.sparse", sparse == "LOG_POWER", sparse)

for i in range(AUTO_LIGHT_STRATEGY_EMITTER_THRESHOLD):
    add_point_light(scene, f"extra{i}")
dense = _auto_light_strategy(scene, "PATHCPU")
check("auto.dense", dense == "RESTIR_DI", dense)

check(
    "auto.unsupported-engine",
    _auto_light_strategy(scene, "BIDIRCPU") == "LOG_POWER",
)

# --- end-to-end through config.convert --------------------------------

scene2 = fresh_scene()
scene2.luxcore.config.engine = "PATH"
scene2.luxcore.config.device = "CPU"
check(
    "convert.sparse-logpower",
    light_strategy_of(scene2) == "LOG_POWER",
)

for i in range(AUTO_LIGHT_STRATEGY_EMITTER_THRESHOLD + 1):
    add_point_light(scene2, f"M{i}")
check(
    "convert.dense-restir",
    light_strategy_of(scene2) == "RESTIR_DI",
)

# explicit user choice wins
scene2.luxcore.config.light_strategy = "POWER"
check(
    "convert.explicit-wins",
    light_strategy_of(scene2) == "POWER",
)
scene2.luxcore.config.light_strategy = "AUTO"

# DLS cache overrides AUTO
scene2.luxcore.config.dls_cache.enabled = True
check(
    "convert.dlsc-override",
    light_strategy_of(scene2) == "DLS_CACHE",
)
scene2.luxcore.config.dls_cache.enabled = False

# --- auto clamping ----------------------------------------------------

props = export_config.convert(None, scene2)
check(
    "clamp.off-no-suggestion",
    not props.IsDefined("path.clamping.variance.maxvalue"),
)

scene2.luxcore.config.path.suggested_clamping_value = 42.0
props = export_config.convert(None, scene2)
check(
    "clamp.auto-applied",
    props.IsDefined("path.clamping.variance.maxvalue")
    and abs(props.Get("path.clamping.variance.maxvalue").GetFloat() - 42.0)
    < 1e-6,
)

scene2.luxcore.config.path.use_clamping = True
scene2.luxcore.config.path.clamping = 7.0
props = export_config.convert(None, scene2)
check(
    "clamp.manual-wins",
    abs(props.Get("path.clamping.variance.maxvalue").GetFloat() - 7.0)
    < 1e-6,
)
scene2.luxcore.config.path.use_clamping = False

scene2.luxcore.config.path.auto_clamping = False
props = export_config.convert(None, scene2)
check(
    "clamp.auto-off",
    not props.IsDefined("path.clamping.variance.maxvalue"),
)
scene2.luxcore.config.path.auto_clamping = True

# --- production defaults on a fresh scene -----------------------------

scene3 = fresh_scene()
halt = scene3.luxcore.halt
check("defaults.denoiser", scene3.luxcore.denoiser.enabled)
check("defaults.halt-enabled", halt.enable)
check("defaults.halt-noise", halt.use_noise_thresh)
check("defaults.halt-samples-cap", halt.use_samples and halt.samples >= 256)
check("defaults.auto-clamp", scene3.luxcore.config.path.auto_clamping)
check("defaults.strategy-auto", scene3.luxcore.config.light_strategy == "AUTO")

print()
n_pass = sum(1 for _, ok in results if ok)
print(f"===== auto config: {n_pass}/{len(results)} PASS =====")
sys.exit(0 if n_pass == len(results) else 1)
