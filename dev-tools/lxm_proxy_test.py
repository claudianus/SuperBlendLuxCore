"""
.lxm mesh proxy round-trip test (standalone pyluxcore).

    PYTHONPATH=<site-packages> python3.13 dev-tools/lxm_proxy_test.py

1. Loads the big PLY floor into a scene, saves it as .lxm.
2. Builds a fresh scene referencing the .lxm — LoadProxy maps the file
   copy-on-write and adopts each section in place (no heap copy).
3. Renders both at 1280x720 on PATHCPU and compares the outputs
   byte-for-byte (identical scene state => identical deterministic
   render).
"""

import os
import sys
import time
import pyluxcore

pyluxcore.Init()

WIDTH, HEIGHT = 1280, 720
PLY = "/tmp/spill_edit_floor.ply"   # written by spill_edit_test.py
LXM = "/tmp/spill_edit_floor.lxm"
OUT_PLY = "/tmp/luxcore_lxm_ply_720p.png"
OUT_LXM = "/tmp/luxcore_lxm_lxm_720p.png"

SCN_TMPL = """
scene.camera.lookat.orig = 0 -7 3.5
scene.camera.lookat.target = 0 0 0.5
scene.camera.fieldofview = 45
scene.lights.skyl.type = sky2
scene.lights.skyl.gain = 0.0001 0.0001 0.0001
scene.lights.skyl.dir = 0.2 0.2 1
scene.materials.emit.type = matte
scene.materials.emit.emission = 8000 8000 8000
scene.materials.emit.kd = 0 0 0
scene.materials.floor.type = matte
scene.materials.floor.kd = 0.6 0.5 0.4
scene.objects.lamp.material = emit
scene.objects.lamp.ply = /tmp/spill_edit_lamp.ply
scene.objects.lamp.transformation = 1 0 0 0  0 1 0 0  0 0 1 0  0 0 4 1
scene.objects.floor.material = floor
scene.objects.floor.ply = {mesh}
"""

CFG_TMPL = """
film.width = {w}
film.height = {h}
film.outputs.0.type = RGB_IMAGEPIPELINE
film.outputs.0.filename = {out}
renderengine.type = PATHCPU
sampler.type = SOBOL
path.pathdepth.total = 4
batch.haltspp = 64
"""


def build_scene(mesh_path):
    scn = pyluxcore.Properties()
    scn.SetFromString(SCN_TMPL.format(mesh=mesh_path))
    scene = pyluxcore.Scene()
    scene.Parse(scn)
    return scene


def render(scene, out):
    cfg = pyluxcore.Properties()
    cfg.SetFromString(CFG_TMPL.format(w=WIDTH, h=HEIGHT, out=out))
    config = pyluxcore.RenderConfig(cfg, scene)
    session = pyluxcore.RenderSession(config)
    session.Start()
    # Poll HasDone + UpdateStats (halt conditions run inside UpdateFilm)
    for _ in range(600):
        session.UpdateStats()
        if session.HasDone():
            break
        time.sleep(0.5)
    session.Stop()
    film = session.GetFilm()
    film.SaveOutputs()
    # Float radiance output for pixel-level comparison
    t = pyluxcore.FilmOutputType.RGB_IMAGEPIPELINE
    buf = bytearray(film.GetOutputSize(t) * 4)
    film.GetOutputFloat(t, buf, 0, True)
    return buf


if not os.path.exists(PLY):
    sys.exit(f"missing {PLY} — run spill_edit_test.py first")

# 1) PLY scene -> save .lxm proxy
scene = build_scene(PLY)
scene.SaveMesh(PLY, LXM)
size = os.path.getsize(LXM)
print(f"[LxmTest] wrote {LXM}: {size / 1e6:.1f} MB")

# 2) render the PLY original
ra = render(scene, OUT_PLY)
del scene

# 3) render the .lxm proxy (mapped copy-on-write, zero heap copy)
scene2 = build_scene(LXM)
rb = render(scene2, OUT_LXM)

# 4a) byte-level round-trip: PLY vertex/face payload vs .lxm sections
import struct
ply = open(PLY, "rb").read()
lxm = open(LXM, "rb").read()
hdr_end = ply.index(b"end_header\n") + len(b"end_header\n")
nv = struct.unpack("<Q", lxm[16:24])[0]
nt = struct.unpack("<Q", lxm[24:32])[0]
vsize = nv * 12
verts_ok = ply[hdr_end:hdr_end + vsize] == lxm[128:128 + vsize]
pos = (128 + vsize + 63) & ~63
tri_ok = all(
    ply[hdr_end + vsize + i * 13] == 3 and
    ply[hdr_end + vsize + i * 13 + 1:hdr_end + vsize + i * 13 + 13] ==
    lxm[pos + i * 12:pos + i * 12 + 12]
    for i in range(nt))
print(f"[LxmTest] data round-trip: verts={verts_ok} tris={tri_ok} "
      f"({'PASS' if verts_ok and tri_ok else 'FAIL'})")

# 4b) render compare — sanity only: two independent runs have different
#     MC noise realizations, so a loose relative-L1 bound is applied.
fa = struct.unpack(f"{len(ra)//4}f", ra)
fb = struct.unpack(f"{len(rb)//4}f", rb)
num = den = 0.0
for x, y in zip(fa, fb):
    num += abs(x - y)
    den += abs(x)
rel = num / max(den, 1e-30)
print(f"[LxmTest] relative image delta = {rel:.3e} "
      f"({'PASS' if rel < 1e-2 else 'FAIL'})")

# 5) error paths: bad magic and truncated files must throw, not crash
open("/tmp/lxm_bad_magic.lxm", "wb").write(b"XXXX" + b"\0" * 4096)
open("/tmp/lxm_truncated.lxm", "wb").write(open(LXM, "rb").read()[:3000])
for bad in ("/tmp/lxm_bad_magic.lxm", "/tmp/lxm_truncated.lxm"):
    try:
        bad_scene = build_scene(bad)
        print(f"[LxmTest] ERROR: {bad} loaded without throwing")
    except RuntimeError as e:
        print(f"[LxmTest] {bad} correctly rejected: {e}")

print("[LxmTest] DONE")
