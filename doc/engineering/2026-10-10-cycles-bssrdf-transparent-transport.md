# Experimental transparent Cycles BSSRDF mixtures

Mix/Add graphs containing RANDOM_WALK BSSRDF and Transparent BSDF now retain
nonlocal scattering after the transparent branch has been selected/skipped at
intersection. CPU and Metal use the same conditional branch distribution.
This extends the opaque candidate documented in
`2026-10-10-cycles-bssrdf-mix-transport.md`; it is not a release adapter switch.

For Mix weights w_i and each child's non-null probability n_i, the remaining
branch masses are w_i*n_i. The selector normalizes these masses, descends
through null-containing ordinary subtrees too, and retains Add's factor of two.
Conditioning both contribution and sampling probability cancels the common
mass. An opaque component receives a fresh uniform pass-through variate for
its internal lobe sampler. The old entry variate is restricted by transparent
selection and cannot be reused as an unconditional internal sample.
TwoSided now forwards its selected child's non-null probability on CPU and in
the compiled GPU material evaluation program. Explicit material opacity
replacements, mixed Normal/Bump and volume contexts remain gated.

The initial 720p Add+Transparent render exposed another defect: RGB mean was
only 0.5388 of Cycles. Orienting entry alone reached only 0.5574. The escape
BSDF also had to choose its scattering side from the walk direction. Previously
it always scattered towards the outer face. Both CPU/Metal now face-forward
the entry sampling frame and choose the corresponding side at escape.
Ordinary outside-to-inside walks retain their existing orientation.

Primary Blender references are the checked local 5.2 source:
`kernel/integrator/surface_shader.h` (BSSRDF closure weights),
`kernel/integrator/subsurface.h` (entry and reversed-ray escape setup), and
`kernel/closure/bssrdf.h` (radius/closure setup).

## Current verified evidence

Complete isolated wheel native SHA-256:
`df812e7c698a3010b6b79d4e4fc4934556ae5df69a321531de4d48021d1dbf20`.
Blender 5.2.1 LTS `9e2066aef7ef`; actual Apple M5 Pro Metal GPU.

- CPU 50 contracts, including zero-radius vs ordinary matte RGB/Alpha,
  transparent endpoints, Add, nested null subtrees and back-facing entry.
- Metal 51 contracts in wavefront off/on. Inside-entry means were 0.611716 /
  0.611264 against CPU 0.610639, with transparent-only contribution 0.5.
- Ordinary CPU/LIGHTCPU/Metal emission: five PASS, no SKIP.
- Four unchanged Cycles graphs at 1280x720, 128 spp: Mix+Transparent,
  Add+Transparent, checker-driven transparency and nested diffuse/transparent
  mixture. Eight CPU/Metal comparison pairs were inspected directly.
- RGB/Alpha comparisons use saved linear EXRs. Common RGB previews set only
  preview alpha to one before the same Standard display transform; alpha is
  shown separately. The actual RGBA EXR/PNG output is preserved. Comparing
  straight PNG RGB after dropping alpha would amplify Cycles' noisy near-zero
  Add alpha and create a misleading brightness difference.
- Add RGB mean ratio restored to CPU 1.024612 / Metal 1.022322. The other
  mixtures are near 1.023-1.026 (exact values in scene-metrics.json).
- Mix/checker/nested mean alpha agrees. Add's analytic native alpha is zero,
  while Cycles' 128-spp mean residual is 0.013394. A 512-spp supplementary
  pair has Cycles residual 0.006932 and stable RGB ratio 1.025002, consistent
  with a sampling residual tending towards zero. This is an inference from
  the convergence evidence and shader alpha definition, not pixel equality.
- Current CUDA static lint has zero issues across 180 kernel files. Actual
  NVRTC/platform CI must be checked for this new commit; earlier green jobs
  do not establish its compilation or runtime coverage.

Durable evidence is in workspace
`test-scenes/validation-2026-10-10/cycles-bssrdf-transparent-transport/`, including
full wheel/RECORD checks, source/profile identity, EXR/PNG, separate RGB/alpha
previews, raw logs and the failed pre-fix comparison.

These are explicit eye-only experimental diagnostics. Production defaults,
user installation and stable release have not been changed. The remaining
full-goal work includes adjoint/LT/BIDIR nonlocal PDF/MIS, Principled and other
SSS models, spectral radius contracts, mixed normal/volume/opacity overrides,
ray context, production/animation/GUI/platform runtime checks, the release
adapter transition and the other unresolved compatibility items. OSL/baking
remain deferred. Full compatibility is not claimed.
