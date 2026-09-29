"""Dump the adapter-exported scene/config via FILESAVER (TXT).

    Blender -b Untitled.blend --python dev-tools/dump_thebox_scene.py
"""
import bpy

scene = bpy.context.scene
scene.render.engine = "SUPERLUXCORE"
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100

cfg = scene.superluxcore.config
cfg.engine = "PATH"
cfg.device = "OCL"          # reproduce the user's GPU-render path
cfg.spectral_enable = False # FILESAVER rejects spectral; toggle in .cfg after
cfg.use_filesaver = True
cfg.filesaver_format = "TXT"
cfg.filesaver_path = "/tmp/thebox4_fsaver/"

halt = scene.superluxcore.halt
halt.enable = True
halt.use_samples = True
halt.samples = 256

scene.render.filepath = "/tmp/thebox4_fsaver/out.png"
bpy.ops.render.render(write_still=True)
print("[Dump] filesaver done")
