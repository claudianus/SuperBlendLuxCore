# e56 — PhotonGI caustic saturation-backoff bench (Blender harness).
# Renders the e52 glass-sphere scene with caustic update period = 1 spp so
# the radius refinement reaches its floor (~60 passes) mid-render; compares
# wall time and update-pass count with LUX_PGIC_SATBACKOFF off/on.
# Env: E56_SPP (default 128).
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

tag = os.environ.get("LUX_PGIC_SATBACKOFF", "default")

scene = bpy.context.scene
scene.render.resolution_x = 640
scene.render.resolution_y = 360
scene.render.resolution_percentage = 100
scene.render.use_compositing = False

cfg = scene.superluxcore.config
cfg.engine = "PATH"
cfg.device = "CPU"
cfg.use_tiles = False
cfg.photongi.caustic_mode = "on"
cfg.photongi.caustic_periodic_update = True
cfg.photongi.caustic_updatespp = 1
# Force the radius refinement to its floor from the first pass so the
# saturation backoff precondition (radius converged) is met early - the
# bench targets the skip path, not the refinement dynamics.
if os.environ.get("E56_FORCE_MINRADIUS", "1") == "1":
    cfg.photongi.caustic_updatespp_minradius = 1.0

halt = scene.superluxcore.halt
halt.enable = True
halt.use_noise_level = False
halt.use_time = False
halt.use_samples = True
halt.samples = int(os.environ.get("E56_SPP", "128"))
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
bpy.ops.render.render()
wall = time.time() - t0
print(f"E56-RESULT backoff={tag} spp={halt.samples} wall={wall:.1f}s",
      flush=True)
