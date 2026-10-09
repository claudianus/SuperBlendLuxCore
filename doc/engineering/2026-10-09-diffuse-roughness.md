# Existing Cycles Diffuse Roughness

The Cycles Diffuse BSDF adapter used to ignore Roughness and always emit matte.
It now reads the original constant or linked socket. Nonzero and textured
roughness uses the native `roughmatte.sigma` input. Native roughmatte already
interprets sigma as normalized EON roughness in [0,1], not an angular sigma;
no angular or squared conversion is introduced. Constant zero retains matte.
Original node RNA and links remain unchanged.

The installed Blender 5.2.1 source uses improved Oren-Nayar with an
energy-preserving multiscatter term. SuperLuxCore retains its existing EON model,
PDF/sampling and spectral quality. This preserves the artistic rough-diffuse
meaning while keeping the native renderer's model; bitwise equality is not a
requirement and model differences are not hidden by lowering quality.

Private Release 2.11.19 on Blender 5.2.1 passed four conditions (zero, quarter,
one, spatially UV-linked roughness) in RGB and standard spectral modes on CPU
and actual Metal: 16 conditions at 1280×720, sample limit 32. All outputs were finite
and free of renderer errors or conversion warnings. Maximum signed-linear-image
MAE on the lit sphere was 0.00414540 CPU RGB, 0.00414558 CPU spectral,
0.00413996 Metal RGB and 0.00414245 Metal spectral. Roughness-one versus zero
changed both renderers' images (full-frame MAE 0.00581 Cycles and 0.00554 native),
showing that the socket has visible effect instead of being ignored. Two
Cycles/CPU/Metal comparison sheets were inspected; retroreflection and the
spatial roughness pattern are preserved with measurable model differences.

Evidence: workspace `test-scenes/validation-2026-10-09/cycles-scene-goal-phase15`.
Harness: `dev-tools/cycles-diffuse-roughness-test.py`.

## White-furnace quality gate

A uniform-white environment exposed a native CPU energy defect that direct
Sun fixtures missed: roughness-one central mean was 0.91954, and 0.91956 in a
repeat with a larger sample limit. Those earlier tests had noise halt enabled;
the 32/128 values describe sample limits, not guaranteed completed sample
counts. Release 2.11.19 was held pending a native repair.

Native RoughMatte Evaluate/Pdf reversed EON's fixed/sampled PDF arguments.
The repair aligns them with Sample and lifts both directions consistently on
backfaces. Importance Sample also uses the fixed light-side cosine, matching
native Matte and Evaluate. The EON model, PDF strategy and spectral quality
are preserved.

The final harness disables noise halt and uses native sample limit 128 and
Cycles limit 32 at 1280×720. Standard spectral roughness zero/one passed the
1% central-mean energy gate, finite/error gates and original-node preservation
on PATHCPU, actual Metal, reversed faces on both, and BIDIRCPU: ten conditions.
Roughness-one means are 0.99964637 CPU, 0.99954909 Metal, 0.99961805 CPU reversed,
0.99954230 Metal reversed and 0.99809569 BIDIRCPU. The comparison sheet was
directly inspected. A dark BIDIR silhouette ring occurs for both matte and
roughmatte and remains a separate boundary limitation; central energy success
does not certify full bidirectional rendering. Four RGB front-face conditions
also passed (roughness-one means 0.99959254 CPU and 0.99956954 Metal); the RGB
comparison sheet was directly inspected.

Evidence is retained under phase15 `furnace-before-pdf-fix` and
`furnace-after-pdf-fix`; the reusable harness is
`dev-tools/cycles-diffuse-white-furnace-test.py`.
A full colour/incidence sweep and composite-closure production scenes remain
open. C35 is partial rather than globally complete. Fresh four-platform wheels
and final bundles must include the repair before publication. Public 2.11.18
does not contain this adapter or the Normal Map work.
