# e55 — EXR A/B comparison (run inside Blender: --background --python <this>).
# Loads the render-result EXRs saved by e55_mnee_prefilter_ab.py and reports
# global/regional radiance stats + pairwise RMSE. No external deps: decodes
# Radiance-style RGBE through Blender's image API instead — actually simpler:
# bpy.data.images.load can read EXR and pixels come out as RGBA floats.
import bpy, sys, os
import numpy as np

OUT = os.environ.get("E55_OUT", "/tmp/e55")
TAGS = (os.environ.get("E55_TAGS") or "base,crawl,both").split(",")
REF = os.environ.get("E55_REF", "base")

imgs = {}
for tag in TAGS:
    path = os.path.join(OUT, f"e52_{tag}.exr")
    img = bpy.data.images.load(path)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)
    imgs[tag] = px[::-1, :, :3]  # flip y (OpenGL order), drop alpha
    bpy.data.images.remove(img)
    rgb = imgs[tag]
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    hi = lum > np.percentile(lum, 99.0)  # bright region: sphere + caustics
    print(f"E55-IMG {tag} mean={rgb.mean(axis=(0,1)).tolist()} "
          f"lumMean={lum.mean():.5f} hiMean={lum[hi].mean():.5f} "
          f"hiFrac={hi.mean():.4f}", flush=True)

ref = imgs[REF]
for tag in TAGS:
    if tag == REF:
        continue
    d = imgs[tag] - ref
    rmse = float(np.sqrt((d * d).mean()))
    lum_r = ref @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    lum_t = imgs[tag] @ np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    hi = lum_r > np.percentile(lum_r, 99.0)
    print(f"E55-RMSE {REF}vs{tag} global={rmse:.6f} "
          f"relLum={lum_t.mean() / lum_r.mean() - 1.0:+.4%} "
          f"hiMeanRef={lum_r[hi].mean():.5f} hiMeanTest={lum_t[hi].mean():.5f} "
          f"hiRel={(lum_t[hi].mean() / lum_r[hi].mean() - 1.0):+.4%}",
          flush=True)
