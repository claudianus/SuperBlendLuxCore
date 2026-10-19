"""Read saved CPU/Metal linear EXRs back through stock Blender, no rendering."""
from pathlib import Path
import json
import hashlib
import bpy
import numpy as np

WORK=Path(__file__).resolve().parents[2]
BASE=WORK/'test-scenes/validation-2026-10-16/metal-startup'
OUT=WORK/'dev-tools/reviews/2026-10-16/metal-startup'
scene=bpy.context.scene
scene.view_settings.view_transform='ACES 2.0'
scene.view_settings.look='None'
scene.render.image_settings.file_format='PNG'
scene.render.image_settings.color_mode='RGBA'
scene.render.image_settings.color_depth='8'
records={}
for dev in ('cpu','ocl'):
    folder=BASE/f'render-{dev}';path=folder/'render.exr'
    img=bpy.data.images.load(str(path),check_existing=False)
    try:
        values=np.empty(len(img.pixels),np.float32);img.pixels.foreach_get(values)
        pixels=values.reshape(img.size[1],img.size[0],img.channels)
        assert list(img.size)==[1280,720] and np.isfinite(pixels).all()
        rgb=pixels[:,:,:3]
        metrics=json.loads((folder/'metrics.json').read_text())
        mean=rgb.mean(axis=(0,1))
        delta=float(np.max(np.abs(mean-np.array(metrics['rgb_mean']))))
        assert delta<2e-5,(dev,delta)
        target=folder/'render-raw-reviewed.png'
        img.save_render(str(target),scene=scene)
        records[dev]={'path':str(path),'sha256':hashlib.file_digest(path.open('rb'),'sha256').hexdigest(),
            'size':list(img.size),'colorspace':img.colorspace_settings.name,'finite':True,
            'min_max':[float(rgb.min()),float(rgb.max())],'mean_rgb':mean.tolist(),
            'negative_rgb_values':int(np.count_nonzero(rgb<0)),'hdr_rgb_values':int(np.count_nonzero(rgb>1)),
            'mean_abs_delta_to_live_render_max':delta,'review_png':str(target)}
    finally:bpy.data.images.remove(img)
(OUT/'saved-exr-review.json').write_text(json.dumps(records,indent=2,allow_nan=False)+'\n')
print(json.dumps(records),flush=True)
