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
and actual Metal: 16 conditions at 1280×720, 32 samples. All outputs were finite
and free of renderer errors or conversion warnings. Maximum signed-linear-image
MAE on the lit sphere was 0.00414540 CPU RGB, 0.00414558 CPU spectral,
0.00413996 Metal RGB and 0.00414245 Metal spectral. Roughness-one versus zero
changed both renderers' images (full-frame MAE 0.00581 Cycles and 0.00554 native),
showing that the socket has visible effect instead of being ignored. Two
Cycles/CPU/Metal comparison sheets were inspected; retroreflection and the
spatial roughness pattern are preserved with measurable model differences.

Evidence: workspace `test-scenes/validation-2026-10-09/cycles-scene-goal-phase15`.
Harness: `dev-tools/cycles-diffuse-roughness-test.py`.

A full colour/incidence sweep, white-furnace energy checks and composite closure
production scenes remain to be validated. C35 is partial rather than globally
complete. The fix is a 2.11.19 candidate and is not in public 2.11.18.
