# Experimental Cycles BSSRDF Mix/Add transport

Opaque Mix/Add graphs containing RANDOM_WALK BSSRDF now select a transport
component before direct-light evaluation on PATHCPU and PATHOCL/Metal.
Previously these graphs were rejected because a nonlocal component could not
participate in the local mixture evaluation/PDF.

The selector traverses only wrappers containing BSSRDF. Ordinary child
subtrees retain their existing BSDF evaluation and sampling. Mix selects with
its clamped entry factor and preserves throughput. Add selects each unit-weight
branch with probability 1/2 and multiplies throughput by two. Conditional NEE
and continuation use the same selected material. Entry AOVs and emission are
recorded before selection. Zero/partial-radius local branches use the selected
leaf, and the last-vertex event budget is recomputed after selection/escape.
CPU/GPU traversal is bounded to 64 levels with preflight rejection of deeper
BSSRDF paths. A compiled material flag leaves ordinary mixtures untouched.

Actual stored volume assignments are checked instead of HasAnyVolume(), which
also marks wrappers with dynamic volume delegation even without any assigned
volume. Mixed null/opacity, Normal/Bump, explicit volume and unsupported wrapper
contexts remain rejected until their conditioning/frame contracts are
implemented. All eye-only experimental opt-ins and adjoint/cache gates remain.
No production quality defaults have changed; this does not enable the release
Cycles adapter or resolve default-quality SSS compatibility.

The Blender reader omits an unconnected zero Normal's synthetic bump texture.
A linked or nonzero Normal remains exported. The existing Mix/Add reader is
used by the private diagnostic without editing the original Cycles graphs.

## Current validation

Complete isolated wheel native SHA-256:
`da25fd39c1b37147e1375f78d92edf33df47f4840222dd54790272ea0930d372`.
Blender 5.2.1 LTS `9e2066aef7ef`, Apple M5 Pro, current Release build.

- CPU: 39 native contracts, including affine Mix endpoints/interior factors,
  Add unit weights, nested two-sided selection and unsupported-null preflight.
- Actual Metal GPU: 29 contracts in wavefront off/on, including local selected
  leaf, nonlocal boundaries, entry AOVs and affine/Add weights.
- Ordinary CPU/LIGHTCPU/Metal two-sided emission regression is recorded
  separately in the evidence directory; no SKIP counts as a backend pass.
- Three unchanged Cycles graphs (Mix+Diffuse, Add+Diffuse, checker-controlled
  Mix+Diffuse), each compared to current CPU and Metal at 1280x720, 128 spp.
  Six pairs were inspected directly, including full-size Metal checker output.
  Silhouette, tint, shadow gradient and checker direction/boundaries agree.
  Native Monte Carlo noise and small intensity/hue differences remain.
- CPU mean ratios to Cycles: 1.020605, 1.018423, 1.019439.
  Metal: 1.021016, 1.019012, 1.019967 (see authoritative metrics for precision).
- CUDA static lint: zero issues across 180 kernel files. Actual NVRTC and
  platform builds must be checked on this new commit's CI; the previous
  standalone BSSRDF commit's green CI does not prove this commit.

Evidence: workspace `test-scenes/validation-2026-10-10/cycles-bssrdf-mix-transport/`.
The full wheel, RECORD/source/profile hash guard, EXR/PNG renders, logs and
visual review are retained. This is experimental transport evidence, not full
production/default-quality compatibility or public deployment acceptance.

Remaining work includes null/frame/volume conditioning, Principled, other SSS
methods, spectral radius contracts, adjoint/LT/BIDIR nonlocal PDF/MIS, production
and GUI scenes, platform runtime checks and release adapter transition. The
full Cycles scene goal remains active.
