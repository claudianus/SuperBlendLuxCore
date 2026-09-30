# e52 — MNEE solve-cost baseline + photon-seed benefit measurement.
# Builds a delta-glass caustic scene and renders at fixed SPP; prints
# [MNEE seeds]/[MNEE solve] diagnostics at session end
# (LUX_MNEE_SEED_STATS=1).
# Env: E52_SPP (default 64), E52_CAUSTIC_MODE (auto|off),
#      E52_SELFSEED=0 disables solve-triggered seeding,
#      E52_DEVICE=OCL for GPU.
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

scene = bpy.context.scene
scene.render.resolution_x = int(os.environ.get("E52_W", "640"))
scene.render.resolution_y = int(os.environ.get("E52_H", "360"))
scene.render.resolution_percentage = 100
scene.render.use_compositing = False

cfg = scene.superluxcore.config
cfg.engine = "PATH"
cfg.device = os.environ.get("E52_DEVICE", "CPU")
cfg.use_tiles = False
cfg.photongi.caustic_mode = os.environ.get("E52_CAUSTIC_MODE", "auto")

# Fixed sample count so A/B iteration counts are comparable.
halt = scene.superluxcore.halt
halt.enable = True
halt.use_noise_level = False
halt.use_time = False
halt.use_samples = True
halt.samples = int(os.environ.get("E52_SPP", "64"))
scene.superluxcore.denoiser.enabled = False


def lux_material(name):
    mat = bpy.data.materials.new(name)
    nt = bpy.data.node_groups.new(name + "Tree",
                                  "superluxcore_material_nodes")
    mat.superluxcore.node_tree = nt
    out = nt.nodes.new("SuperLuxCoreNodeMatOutput")
    return mat, nt, out


# Scene: matte floor + pure-glass sphere + point light inside the sphere.
# Every shadow ray to the light crosses a delta interface -> MNEE territory.
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
# Off-centre inside the sphere: a centred light makes the only Fermat
# solution the degenerate on-axis root (Jacobian singular) - an unfair
# solver test.
lo.location = (0.35, 0.1, 1.55)
scene.collection.objects.link(lo)

bpy.ops.object.camera_add(location=(0, -4.5, 2.6))
cam = bpy.context.active_object
cam.rotation_euler = (math.radians(62), 0, 0)
scene.camera = cam

t0 = time.time()
bpy.ops.render.render()
wall = time.time() - t0
print(f"E52-RESULT mode={cfg.photongi.caustic_mode} "
      f"device={cfg.device} spp={halt.samples} wall={wall:.1f}s",
      flush=True)
