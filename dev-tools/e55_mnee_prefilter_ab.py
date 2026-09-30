# e55 — MNEE crawl-bail A/B energy check (also the generic e52-scene A/B
# harness). Renders the e52 glass-sphere caustic scene at fixed SPP, saves
# the HDR result, and (when both images exist) reports RMSE/mean stats.
# Env: E55_SPP (default 256), E55_OUT (default /tmp/e55),
#      E55_TAG (run tag, default "on"), E55_DEVICE (default CPU).
# The engine A/B switches are LUX_MNEE_CRAWL=0|1 (crawl bail) and
# LUX_MNEE_POISON / LUX_MNEE_SELFSEED (seed cache policy).
import math, os, sys, time
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

tag = os.environ.get("E55_TAG", "on")
outdir = os.environ.get("E55_OUT", "/tmp/e55")
os.makedirs(outdir, exist_ok=True)

scene = bpy.context.scene
scene.render.resolution_x = 640
scene.render.resolution_y = 360
scene.render.resolution_percentage = 100
scene.render.use_compositing = False
scene.render.image_settings.file_format = "OPEN_EXR"
scene.render.filepath = os.path.join(outdir, f"e52_{tag}.exr")

cfg = scene.superluxcore.config
cfg.engine = "PATH"
cfg.device = os.environ.get("E55_DEVICE", "CPU")
cfg.use_tiles = False
cfg.photongi.caustic_mode = "auto"

halt = scene.superluxcore.halt
halt.enable = True
halt.use_noise_level = False
halt.use_time = False
halt.use_samples = True
halt.samples = int(os.environ.get("E55_SPP", "256"))
scene.superluxcore.denoiser.enabled = False


def lux_material(name):
    mat = bpy.data.materials.new(name)
    nt = bpy.data.node_groups.new(name + "Tree",
                                  "superluxcore_material_nodes")
    mat.superluxcore.node_tree = nt
    out = nt.nodes.new("SuperLuxCoreNodeMatOutput")
    return mat, nt, out


bpy.ops.mesh.primitive_plane_add(size=12)
pm, pnt, pout = lux_material("floor")
pd = pnt.nodes.new("SuperLuxCoreNodeMatMatte")
pd.inputs["Diffuse Color"].default_value = (0.75, 0.72, 0.68)
pnt.links.new(pd.outputs["Material"], pout.inputs["Material"])
bpy.context.active_object.data.materials.append(pm)

bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1.0,
                                    location=(0, 0, 1.3))
gm, gnt, gout = lux_material("glass")
gg = gnt.nodes.new("SuperLuxCoreNodeMatGlass")
gg.inputs["IOR"].default_value = 1.5
gnt.links.new(gg.outputs["Material"], gout.inputs["Material"])
bpy.context.active_object.data.materials.append(gm)

ld = bpy.data.lights.new("pt", type="POINT")
ld.energy = 200.0
lo = bpy.data.objects.new("pt", ld)
lo.location = (0.35, 0.1, 1.55)
scene.collection.objects.link(lo)

bpy.ops.object.camera_add(location=(0, -4.5, 2.6))
cam = bpy.context.active_object
cam.rotation_euler = (math.radians(62), 0, 0)
scene.camera = cam

t0 = time.time()
bpy.ops.render.render(write_still=True)
wall = time.time() - t0
print(f"E55-RESULT tag={tag} spp={halt.samples} wall={wall:.1f} "
      f"out={scene.render.filepath}", flush=True)
