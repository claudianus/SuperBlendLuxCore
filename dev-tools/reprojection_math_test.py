# Reprojection warp math regression test.
#
# Replicates the GPU warp shader's math (draw/viewport.py _WARP_FRAG_SRC +
# the CPU-side u_vpNewInv @ uv_to_ndc fold) with numpy and verifies:
#   1. Identity: same view in/out reproduces the same UV (no drift).
#   2. Orbit: a world point on the pivot plane keeps its projected
#      position - warping the old frame lands it under the new view.
#   3. Pan/dolly/ortho sanity: finite UVs, monotonic directions.
#
# Run: blender -b --factory-startup --python dev-tools/reprojection_math_test.py
# (needs mathutils + numpy from Blender's bundled python; no GPU needed)

import sys
import math
import numpy as np
from mathutils import Matrix, Vector

PASS = 0
FAIL = 0


def check(name, ok):
    global PASS, FAIL
    if ok:
        PASS += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name)


def np_m(m):
    return np.array([[m[r][c] for c in range(4)] for r in range(4)])


def perspective(fov_deg, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    m = np.zeros((4, 4))
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye, target, up=(0, 0, 1)):
    eye = np.array(eye, float)
    fwd = np.array(target, float) - eye
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, np.array(up, float))
    right /= np.linalg.norm(right)
    up2 = np.cross(right, fwd)
    view = np.eye(4)
    view[0, :3] = right
    view[1, :3] = up2
    view[2, :3] = -fwd
    view[:3, 3] = -view[:3, :3] @ eye
    return view


def rect_ndc(rect, rw, rh):
    x, y, w, h = rect
    return np.array(
        [x / rw * 2 - 1, y / rh * 2 - 1, (x + w) / rw * 2 - 1, (y + h) / rh * 2 - 1]
    )


def warp_uv(uv, vp_old, vp_new, rect_old, rect_new, pivot):
    """Faithful replica of _WARP_FRAG_SRC + the CPU uv_to_ndc fold."""
    nx0, ny0, nx1, ny1 = rect_new
    sx, sy = nx1 - nx0, ny1 - ny0
    uv_to_ndc = np.array(
        [
            [sx, 0, 0, nx0],
            [0, sy, 0, ny0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ]
    )
    m = np.linalg.inv(vp_new) @ uv_to_ndc
    u, v = uv
    pn = m @ np.array([u, v, -1.0, 1.0])
    pf = m @ np.array([u, v, 1.0, 1.0])
    org = pn[:3] / pn[3]
    dirv = pf[:3] / pf[3] - org
    dirv /= np.linalg.norm(dirv)
    # Focus plane through the pivot, perpendicular to the view forward.
    oc = m @ np.array([0.5, 0.5, -1.0, 1.0])
    fc = m @ np.array([0.5, 0.5, 1.0, 1.0])
    fwd = fc[:3] / fc[3] - oc[:3] / oc[3]
    fwd /= np.linalg.norm(fwd)
    denom = float(np.dot(dirv, fwd))
    t = 1e6
    if abs(denom) > 1e-4:
        tp = float(np.dot(np.asarray(pivot) - org, fwd)) / denom
        if tp > 1e-3:
            t = tp
    pw = org + dirv * t
    co = vp_old @ np.array([*pw, 1.0])
    ndc_old = co[:2] / co[3]
    return (ndc_old - rect_old[:2]) / (rect_old[2:] - rect_old[:2])


def project(vp, p):
    co = vp @ np.array([*p, 1.0])
    return co[:3] / co[3]


RW, RH = 1280, 720
RECT = rect_ndc((0, 0, RW, RH), RW, RH)
PIVOT = np.array([0.0, 0.0, 0.0])
FOV, NEAR, FAR = 50.0, 0.1, 1000.0

# --- Test 1: identity ---------------------------------------------------
eye = np.array([4.0, -4.0, 3.0])
vp = perspective(FOV, RW / RH, NEAR, FAR) @ look_at(eye, PIVOT)
errs = []
for u in (0.0, 0.25, 0.5, 0.75, 1.0):
    for v in (0.0, 0.33, 0.66, 1.0):
        tuv = warp_uv((u, v), vp, vp, RECT, RECT, PIVOT)
        errs.append(max(abs(tuv[0] - u), abs(tuv[1] - v)))
check("identity round-trip max err < 1e-5", max(errs) < 1e-5)

# --- Test 2: orbit keeps pivot-plane content locked ---------------------
# Orbit the camera 10 degrees around the pivot; the pivot itself must map
# back to its old UV for the pixel that newly covers it.
theta = math.radians(10)
rot = np.array(
    [
        [math.cos(theta), -math.sin(theta), 0],
        [math.sin(theta), math.cos(theta), 0],
        [0, 0, 1],
    ]
)
eye2 = rot @ eye
vp_new = perspective(FOV, RW / RH, NEAR, FAR) @ look_at(eye2, PIVOT)
vp_old = vp

# Where does the pivot sit in each view (in film-UV terms)?
ndc_old_p = project(vp_old, PIVOT)[:2]
ndc_new_p = project(vp_new, PIVOT)[:2]
uv_old_p = (ndc_old_p - RECT[:2]) / (RECT[2:] - RECT[:2])
uv_new_p = (ndc_new_p - RECT[:2]) / (RECT[2:] - RECT[:2])
# The current pixel covering the pivot should sample the pivot's old UV.
tuv = warp_uv(tuple(uv_new_p), vp_old, vp_new, RECT, RECT, PIVOT)
check(
    "orbit: pivot stays locked (err < 1e-4)",
    np.linalg.norm(tuv - uv_old_p) < 1e-4,
)

# Points ON the focus plane (through the pivot, perpendicular to the NEW
# view's forward) must track exactly - the warp approximates content as
# lying on that plane.
fwd2 = PIVOT - eye2
fwd2 /= np.linalg.norm(fwd2)
worst = 0.0
for dx in (-2.0, -0.5, 0.7, 2.0):
    for dy in (-2.0, 0.0, 1.5):
        # Point on the plane through PIVOT with normal fwd2.
        side = np.cross(fwd2, np.array([0.0, 0.0, 1.0]))
        side /= np.linalg.norm(side)
        upv = np.cross(side, fwd2)
        p = PIVOT + dx * side + dy * upv
        n_o = project(vp_old, p)[:2]
        n_n = project(vp_new, p)[:2]
        uo = (n_o - RECT[:2]) / (RECT[2:] - RECT[:2])
        un = (n_n - RECT[:2]) / (RECT[2:] - RECT[:2])
        if not (0 <= un[0] <= 1 and 0 <= un[1] <= 1):
            continue
        if not (0 <= uo[0] <= 1 and 0 <= uo[1] <= 1):
            continue
        tuv = warp_uv(tuple(un), vp_old, vp_new, RECT, RECT, PIVOT)
        worst = max(worst, np.linalg.norm(tuv - uo))
check("orbit: focus-plane points track (worst uv err < 2e-3)", worst < 2e-3)

# --- Test 3: pan + dolly stay sane --------------------------------------
eye3 = eye + np.array([0.0, 0.0, 0.0])
piv3 = PIVOT + np.array([0.3, 0.0, 0.0])  # panned pivot
vp_pan = perspective(FOV, RW / RH, NEAR, FAR) @ look_at(eye, piv3)
uvs = [
    warp_uv((u, v), vp_old, vp_pan, RECT, RECT, piv3)
    for u in (0.1, 0.5, 0.9)
    for v in (0.1, 0.5, 0.9)
]
check("pan: all UVs finite", all(np.all(np.isfinite(t)) for t in uvs))

eye4 = eye * 0.7  # dolly in
vp_dolly = perspective(FOV, RW / RH, NEAR, FAR) @ look_at(eye4, PIVOT)
center = warp_uv((0.5, 0.5), vp_old, vp_dolly, RECT, RECT, PIVOT)
check("dolly: center stays near center", np.linalg.norm(center - 0.5) < 0.05)

# --- Test 4: film rect inside a region (camera-view quad) ---------------
small = rect_ndc((320, 180, 640, 360), RW, RH)
tuv = warp_uv((0.5, 0.5), vp, vp_new, small, small, PIVOT)
check("sub-rect: finite", np.all(np.isfinite(tuv)))
err = 0.0
for d in (0.0, 0.5, -0.4):
    p = PIVOT + d * side + 0.3 * upv
    n_o = project(vp_old, p)[:2]
    n_n = project(vp_new, p)[:2]
    uo = (n_o - small[:2]) / (small[2:] - small[:2])
    un = (n_n - small[:2]) / (small[2:] - small[:2])
    if not (0 <= un[0] <= 1 and 0 <= un[1] <= 1):
        continue
    if not (0 <= uo[0] <= 1 and 0 <= uo[1] <= 1):
        continue
    tuv = warp_uv(tuple(un), vp_old, vp_new, small, small, PIVOT)
    err = max(err, np.linalg.norm(tuv - uo))
check("sub-rect: focus-plane tracking (err < 2e-3)", err < 2e-3)

# --- Test 5: ortho view --------------------------------------------------
def ortho(scale, aspect, near, far):
    m = np.eye(4)
    m[0, 0] = 1.0 / (scale * aspect)
    m[1, 1] = 1.0 / scale
    m[2, 2] = -2.0 / (far - near)
    m[2, 3] = -(far + near) / (far - near)
    return m

vp_ortho = ortho(4.0, RW / RH, NEAR, FAR) @ look_at(eye, PIVOT)
errs = [
    warp_uv((u, v), vp_ortho, vp_ortho, RECT, RECT, PIVOT)
    for u in (0.2, 0.5, 0.8)
    for v in (0.2, 0.8)
]
worst_id = max(
    max(abs(t[0] - u), abs(t[1] - v))
    for t, (u, v) in zip(
        errs, [(u, v) for u in (0.2, 0.5, 0.8) for v in (0.2, 0.8)]
    )
)
check("ortho: identity round-trip (err < 1e-5)", worst_id < 1e-5)

print(f"\n{PASS + FAIL} checks, {FAIL} failed")
sys.exit(1 if FAIL else 0)
