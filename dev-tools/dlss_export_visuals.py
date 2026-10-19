"""Stock Blender export/reopen of raw float captures and ACES 2.0 previews."""
import hashlib
import json
import os
from pathlib import Path

import bpy
import numpy as np

files = json.loads(os.environ['SLC_DLSS_VISUAL_FILES'])
out = Path(os.environ['SLC_DLSS_VISUAL_OUT'])
out.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
scene.view_settings.look = 'None'
scene.view_settings.exposure = 0
scene.view_settings.gamma = 1
records = {}
for label, filename in files.items():
    values = np.load(filename, allow_pickle=False)
    h, w, c = values.shape
    assert c == 4 and values.dtype == np.float32 and np.isfinite(values).all()
    img = bpy.data.images.new(label, width=w, height=h, alpha=True, float_buffer=True)
    try:
        img.colorspace_settings.name = 'Linear Rec.709'
        img.pixels.foreach_set(values.ravel())
        img.update()
        exr, png = out/(label+'.exr'), out/(label+'.png')
        scene.render.image_settings.file_format = 'OPEN_EXR'
        scene.render.image_settings.color_depth = '32'
        scene.render.image_settings.color_mode = 'RGBA'
        scene.render.image_settings.exr_codec = 'ZIP'
        scene.view_settings.view_transform = 'Raw'
        img.save_render(str(exr), scene=scene)
        scene.render.image_settings.file_format = 'PNG'
        scene.render.image_settings.color_depth = '8'
        scene.view_settings.view_transform = 'ACES 2.0'
        img.save_render(str(png), scene=scene)
        check = bpy.data.images.load(str(exr), check_existing=False)
        try:
            reopened = np.empty(values.size, np.float32)
            check.pixels.foreach_get(reopened)
            reopened = reopened.reshape(values.shape)
            error = float(np.abs(reopened-values).max())
            assert error < 1e-6, (label, error)
            records[label] = {'source': filename, 'size': [w, h], 'finite': True,
                              'exr_reopen_max_abs': error, 'view_transform': 'ACES 2.0',
                              'exr': str(exr), 'png': str(png),
                              'mean_rgb': values[:, :, :3].mean(axis=(0, 1), dtype=np.float64).tolist(),
                              'exr_sha256': hashlib.file_digest(exr.open('rb'), 'sha256').hexdigest()}
        finally:
            bpy.data.images.remove(check)
    finally:
        bpy.data.images.remove(img)
(out/'visuals.json').write_text(json.dumps(records, indent=2)+'\n')
print(json.dumps(records), flush=True)
