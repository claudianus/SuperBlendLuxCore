"""
Numeric comparison of /tmp/thebox4_compare/{bidir_cpu,path_cpu,path_ocl}.exr.

    Blender -b --python dev-tools/compare_thebox.py

Prints per-channel means, relative differences, spatial error maps
(wall quadrants + figure region), and writes a 2x-amplified heatmap PNG
per pair.
"""

import os

import bpy
import numpy as np

DIR = "/tmp/thebox4_compare"


def load_exr(name):
    img = bpy.data.images.load(os.path.join(DIR, name + ".exr"))
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float64).reshape(h, w, 4)
    bpy.data.images.remove(img)
    return np.flipud(px[:, :, :3])          # EXR pixels are bottom-up


def lum(a):
    return a[..., 0] * 0.2126 + a[..., 1] * 0.7152 + a[..., 2] * 0.0722


def stats(a):
    l = lum(a)
    return dict(mean=a.reshape(-1, 3).mean(0), lum_mean=l.mean(),
                lum_med=np.median(l), lum_p95=np.percentile(l, 95),
                lum_p99=np.percentile(l, 99))


def quadrant_lums(a):
    l = lum(a)
    h, w = l.shape
    # left wall | center wall | right wall | figure (bottom center)
    regions = {
        "left_red_wall":   l[int(h*0.2):int(h*0.8), int(w*0.03):int(w*0.18)],
        "right_grn_wall":  l[int(h*0.2):int(h*0.8), int(w*0.82):int(w*0.97)],
        "center_wall":     l[int(h*0.15):int(h*0.5), int(w*0.35):int(w*0.65)],
        "floor":           l[int(h*0.85):, :],
        "figure":          l[int(h*0.75):, int(w*0.35):int(w*0.65)],
    }
    return {k: v.mean() for k, v in regions.items()}


def heatmap(a, b, out):
    l1, l2 = lum(a), lum(b)
    m = (l1 > 1e-4) | (l2 > 1e-4)
    rel = np.zeros_like(l1)
    rel[m] = np.abs(l1[m] - l2[m]) / np.maximum(l1[m], l2[m])
    # 0..0.5 rel diff -> heat
    viz = np.clip(rel * 2.0, 0, 1)
    rgb = np.stack([viz, np.clip(1 - viz * 2, 0, 1), np.clip(1 - viz, 0, 1)], -1)
    save_png(rgb, out)
    print(f"  heatmap rel-diff mean={rel[m].mean():.4f} "
          f"p95={np.percentile(rel[m],95):.4f} -> {out}")


def save_png(rgb, out):
    h, w = rgb.shape[:2]
    img = bpy.data.images.new("cmp", width=w, height=h)
    rgba = np.concatenate([rgb, np.ones((h, w, 1))], -1)
    img.pixels = np.flipud(rgba).ravel()
    img.filepath_raw = out
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)


def pair(a_name, b_name, imgs):
    a, b = imgs[a_name], imgs[b_name]
    sa, sb = stats(a), stats(b)
    print(f"\n=== {a_name} vs {b_name} ===")
    print(f"  mean rgb {a_name}: {np.round(sa['mean'],4)}  "
          f"{b_name}: {np.round(sb['mean'],4)}")
    print(f"  lum mean {sa['lum_mean']:.4f} vs {sb['lum_mean']:.4f} "
          f"(ratio {sa['lum_mean']/max(sb['lum_mean'],1e-9):.4f})")
    print(f"  lum med  {sa['lum_med']:.4f} vs {sb['lum_med']:.4f}")
    print(f"  lum p95  {sa['lum_p95']:.4f} vs {sb['lum_p95']:.4f}")
    print(f"  lum p99  {sa['lum_p99']:.4f} vs {sb['lum_p99']:.4f}")
    qa, qb = quadrant_lums(a), quadrant_lums(b)
    for k in qa:
        print(f"    {k:16s}: {qa[k]:.4f} vs {qb[k]:.4f} "
              f"ratio {qa[k]/max(qb[k],1e-9):.3f}")
    heatmap(a, b, os.path.join(DIR, f"diff_{a_name}_vs_{b_name}.png"))


def main():
    imgs = {}
    for n in ("bidir_cpu", "path_cpu", "path_ocl",
              "path_cpu_ns", "path_ocl_ns"):
        if os.path.exists(os.path.join(DIR, n + ".exr")):
            imgs[n] = load_exr(n)
        else:
            print(f"missing {n}.exr")
    if "path_ocl" in imgs:
        pair("path_ocl", "bidir_cpu", imgs)
        pair("path_ocl", "path_cpu", imgs)
    if "path_cpu" in imgs and "bidir_cpu" in imgs:
        pair("path_cpu", "bidir_cpu", imgs)
    if "path_ocl_ns" in imgs and "path_cpu_ns" in imgs:
        pair("path_ocl_ns", "path_cpu_ns", imgs)
    if "path_cpu_ns" in imgs and "path_cpu" in imgs:
        pair("path_cpu_ns", "path_cpu", imgs)
    if "path_ocl_ns" in imgs and "path_ocl" in imgs:
        pair("path_ocl_ns", "path_ocl", imgs)


main()
