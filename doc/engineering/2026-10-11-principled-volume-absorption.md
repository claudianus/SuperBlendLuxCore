# Cycles Principled Volume absorption color

Cycles 5.2 computes the square root of the authored Absorption Color RGB before
converting it into the absorption complement. The adapter previously used the
raw color, making fractional input channels absorb too strongly. For example,
`(0.04, 0.25, 0.64)` at unit density and zero scattering color previously
produced sigma-a `(0.96, 0.75, 0.36)` instead of `(0.8, 0.5, 0.2)`.

The Principled Volume branch now takes the nonnegative square root per RGB
channel. Constants fold in Python. Linked colors use SplitFloat3, scalar
nonnegative power and color MakeFloat3 helpers, so the nonlinear operator runs
on authored RGB before the default spectral conversion. The existing
absorption complement and density composition then apply. Pure Volume
Absorption and Volume Scatter branches are unchanged.

`dev-tools/cycles-principled-volume-absorption-test.py` renders the same authored
graph in Cycles, SuperLuxCore CPU and Metal. It compares an eroded 1280x720 slab
body to the independent RGB law `exp(-2 * max(1 - sqrt(color), 0))`. Constant
fractional channels, a linked gradient with an explicitly authored Object
coordinate reference, and 0/1/4 limits have fixed 64-sample and 1% mean gates.
The driver also renders both native backends in their default spectral mode;
these images have a separate direct review and no RGB-equality gate.

The narrow installed-adapter candidate, without monkeypatches, completed all
15 images. All original PNGs were directly reviewed. Six native RGB conditions
passed, with maximum body error 0.08960%. Spectral CPU and Metal retain blue,
cool-to-warm gradient and cyan meaning, with grain at 64 SPP. Absorption blue
value 4 has a 67.50% red-channel mean difference from the RGB law in spectral
mode; this is an explicit HDR spectral colorimetry limitation. The test does
not establish final converged color or general volume compatibility.

The exact signed core is source `c2915a73a325bd2e5d0e2f999298051bf9af5d32`,
native SHA256 `d5443cf5022c653d5636fa4b44ec246a60e39b0b65e2078e6135410949636024`,
whole wheel SHA256 `dace137bff6799eebb099ede4e4570ad3eba07fdd1bc9d79b624ca25db1ba5d7`.
Evidence is in the parent workspace's
`test-scenes/validation-2026-10-11/principled-volume-absorption`.
The original one-thread interrupted attempt and its source are retained;
the four-thread rerun preserves sample budgets and the analytic threshold.
Actual narrow-reader registration and linked-color rendering are underway.

Named VDB attributes, Generated coordinates inside volumes, broad blackbody
radiance/unit checks, overlapping volume boundaries and production convergence
remain open. In particular, the separate Generated-coordinate failure is not
hidden by the explicitly authored reference used to isolate this color
operator. The full unchanged-Cycles-scene goal remains active.
