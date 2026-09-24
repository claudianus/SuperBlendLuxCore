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

# 6) layer coverage: normals + uv + color + alpha + vertAOV + triAOV
#    round-trip.

NV, NT = 64, 124
LAYERED_PLY = "/tmp/lxm_layered.ply"
LAYERED_LXM = "/tmp/lxm_layered.lxm"

verts = [(float(i), float(i * 2), float(i % 7)) for i in range(NV)]
norms = [(0.0, 0.0, 1.0)] * NV
uvs = [(i / NV, 1.0 - i / NV) for i in range(NV)]
cols = [(i * 3 % 256, i * 5 % 256, i * 7 % 256) for i in range(NV)]
alphas = [i * 2 % 256 for i in range(NV)]
tris = [(i, i + 1, i + 2) for i in range(NT)]
vert_aov = [float(i) * 0.25 for i in range(NV)]
tri_aov = [float(i) * 0.5 for i in range(NT)]

with open(LAYERED_PLY, "wb") as f:
    f.write(b"ply\nformat binary_little_endian 1.0\n")
    f.write(f"element vertex {NV}\n".encode())
    for p in ("x", "y", "z", "nx", "ny", "nz", "s", "t", "vertaov"):
        f.write(f"property float {p}\n".encode())
    for p in ("red", "green", "blue", "alpha"):
        f.write(f"property uchar {p}\n".encode())
    f.write(f"element face {NT}\n".encode())
    f.write(b"property list uchar int vertex_indices\n")
    f.write(f"element faceaov {NT}\n".encode())
    f.write(b"property float triaov\nend_header\n")
    for i in range(NV):
        f.write(struct.pack("<9f4B", *verts[i], *norms[i],
                            *uvs[i], vert_aov[i], *cols[i], alphas[i]))
    for t in tris:
        f.write(struct.pack("<B3i", 3, *t))
    for v in tri_aov:
        f.write(struct.pack("<f", v))

scn3 = pyluxcore.Scene()
p3 = pyluxcore.Properties()
p3.SetFromString(
    SCN_TMPL.format(mesh=LAYERED_PLY).replace(
        "scene.objects.floor", "scene.objects.layfloor")
)
scn3.Parse(p3)
scn3.SaveMesh(LAYERED_PLY, LAYERED_LXM)

lxm2 = open(LAYERED_LXM, "rb").read()
flags = struct.unpack("<I", lxm2[8:12])[0]
masks = struct.unpack("<5I", lxm2[32:52])
uvm, colm, alm, vam, tam = masks
print(f"[LxmTest] layered: flags={flags} masks uv={uvm} col={colm} "
      f"alpha={alm} vertaov={vam} triaov={tam}")

pos2 = 128
ok = True
# verts
exp = b"".join(struct.pack("<3f", *v) for v in verts)
ok &= lxm2[pos2:pos2 + NV * 12] == exp; pos2 += NV * 12
pos2 = (pos2 + 63) & ~63
# tris
exp = b"".join(struct.pack("<3i", *t) for t in tris)
ok &= lxm2[pos2:pos2 + NT * 12] == exp; pos2 += NT * 12
pos2 = (pos2 + 63) & ~63
# normals
exp = b"".join(struct.pack("<3f", *n) for n in norms)
ok &= lxm2[pos2:pos2 + NV * 12] == exp; pos2 += NV * 12
pos2 = (pos2 + 63) & ~63
# uv layer 0
exp = b"".join(struct.pack("<2f", *uv) for uv in uvs)
ok &= lxm2[pos2:pos2 + NV * 8] == exp; pos2 += NV * 8
pos2 = (pos2 + 63) & ~63
# color layer 0: uchar -> float/255
exp = b"".join(struct.pack("<3f", *(c / 255.0 for c in col)) for col in cols)
ok &= lxm2[pos2:pos2 + NV * 12] == exp; pos2 += NV * 12
pos2 = (pos2 + 63) & ~63
# alpha layer 0
exp = b"".join(struct.pack("<f", a / 255.0) for a in alphas)
ok &= lxm2[pos2:pos2 + NV * 4] == exp; pos2 += NV * 4
pos2 = (pos2 + 63) & ~63
# vertAOV layer 0
exp = b"".join(struct.pack("<f", v) for v in vert_aov)
ok &= lxm2[pos2:pos2 + NV * 4] == exp; pos2 += NV * 4
pos2 = (pos2 + 63) & ~63
# triAOV layer 0 — last section, no trailing pad in the file
exp = b"".join(struct.pack("<f", v) for v in tri_aov)
ok &= lxm2[pos2:pos2 + NT * 4] == exp; pos2 += NT * 4
ok &= pos2 == len(lxm2)
expected_masks = (flags == 1 and uvm == 1 and colm == 1 and
                  alm == 1 and vam == 1 and tam == 1)
print(f"[LxmTest] layer sections byte-exact: {ok}, "
      f"masks expected: {expected_masks} "
      f"({'PASS' if ok and expected_masks else 'FAIL'})")

print("[LxmTest] DONE")
