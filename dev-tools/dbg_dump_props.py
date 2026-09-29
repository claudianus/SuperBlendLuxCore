# Debug helper: build the e50 scene, run the exporter, then bisect which
# feature flag makes RenderSession raise "bad lexical cast".
#   DBG_NOENV=1 / DBG_NODEN=1 / DBG_NOHALT=1 disable individual features.
import math, os, sys
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

scene = bpy.context.scene
scene.render.resolution_x = 320
scene.render.resolution_y = 180
scene.render.resolution_percentage = 100

if os.environ.get("DBG_NOENV"):
    scene.superluxcore.config.envlight_cache.enabled = False
if os.environ.get("DBG_NODEN"):
    scene.superluxcore.denoiser.enabled = False
if os.environ.get("DBG_NOHALT"):
    scene.superluxcore.halt.enable = False
if os.environ.get("DBG_NOMNEE"):
    scene.superluxcore.config.mnee_enable = False

bpy.ops.mesh.primitive_plane_add(size=12)
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0, location=(0,0,1.3))
ld = bpy.data.lights.new("pt", type="POINT"); ld.energy = 200.0
lo = bpy.data.objects.new("pt", ld); lo.location = (0,0,1.3)
scene.collection.objects.link(lo)
world = bpy.data.worlds.new("w"); world.use_nodes = True
scene.world = world
bpy.ops.object.camera_add(location=(0,-4.5,2.6))
cam = bpy.context.active_object
cam.rotation_euler = (math.radians(62),0,0)
scene.camera = cam

depsgraph = bpy.context.evaluated_depsgraph_get()
addon = sys.modules["bl_ext.user_default.superluxcore"]
import pysuperluxcore

exporter = addon.export.Exporter()
view_layer = bpy.context.view_layer
class EngineStub:
    aov_imagepipelines = {}
    is_animation = False

    def test_break(self):
        return False

    def __getattr__(self, name):
        return lambda *a, **k: None

result = exporter.export_scene(depsgraph, engine=EngineStub(),
                               view_layer=view_layer)
lux_scene, config_props = result

with open("/tmp/e50_config_props.txt", "w") as f:
    for k in config_props.GetAllNames():
        vals = [config_props.Get(k).GetString(i)
                for i in range(config_props.Get(k).GetSize())]
        f.write(f"{k} = {' | '.join(vals)}\n")


try:
    lux_scene.Save("/tmp/e50_scene.scn")
except Exception as e:
    print("scene save failed (partial):", e, flush=True)


def try_session(cfg, tag):
    try:
        pysuperluxcore.RenderSession(
            pysuperluxcore.RenderConfig(cfg, lux_scene))
        print(f"SESSION-OK {tag}", flush=True)
        return True
    except Exception as e:
        print(f"SESSION-FAIL {tag}: {e}", flush=True)
        return False


def strip(cfg, prefixes):
    out = pysuperluxcore.Properties()
    out.Set(cfg)
    for k in [n for n in out.GetAllNames()
              if any(n.startswith(p) for p in prefixes)]:
        out.Delete(k)
    return out


if not try_session(config_props, "full"):
    cfg0 = strip(config_props, [])
    cfg0.Set(pysuperluxcore.Property("film.adaptiveerror.target", "0"))
    try_session(cfg0, "adaptiveerror.target=0")

    # Hypothesis: python float -> DOUBLE_VAL -> Get<float> uses
    # lexical_cast<float>(double) which requires exact roundtrip and
    # throws for non-representable values (e.g. 0.03). A string value
    # takes the FromString (istringstream) path and should work.
    cfgS = strip(config_props, [])
    cfgS.Set(pysuperluxcore.Property("film.adaptiveerror.target", "0.03"))
    try_session(cfgS, "adaptiveerror.target='0.03' (str)")

    # adaptive kept, other groups stripped one at a time
    for g in ["film.noiseestimation", "film.imagepipelines",
              "film.outputs", "film.adaptiveerror"]:
        try_session(strip(config_props, [g]), f"without {g}")

