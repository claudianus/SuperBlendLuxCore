# Cycles Bump direction texture

A dedicated `cyclesbump` texture preserves the meaning of existing Cycles
Bump graphs. The adapter exports Height, linked Distance, linked Strength,
linked base Normal, Invert and each node's own Filter Width. It leaves the
Blender graph untouched. Distance multiplies the height derivative after
finite differences; differentiating Height × spatial Distance would add a
spurious gradient. Nonnegative Strength blends with the normalized perturbed
normal after differentiation.

CPU and the GPU texture VM evaluate data with spectral conversion paused.
The data result is a facing world-space normal, so Vector Math and Mix can
consume Bump output. The material Bump entry returns a mesh-side normal.
Backface gradients follow the Cycles facing partials. GPU offsets save and
restore the original position, normal and UV before evaluating Distance,
Strength and Normal, including nested Bump inputs.

Private Blender 5.2.1 validation at 1280×720 passed all 48 strict plane
conditions: eighteen RGB and six standard spectral conditions per CPU/Metal.
They include linked/spatial Distance, Normal Map base, chaining, Math/Mix,
Strength above one and negative Strength, Invert, backfaces and independent
Filter Widths. Maximum RGB component MAE was 0.00042807 against signed Cycles
Normal-pass EXRs (gate 0.005). Five smooth-sphere conditions per backend also
passed (maximum MAE 0.00145648). Eight existing Normal Map spectral cases per
backend passed regression (maximum MAE 0.00086994). Comparison sheets were
inspected; signed EXRs provide metrics because display PNG clips negatives.

This is bounded normal-data validation. A 128-sample-limit spectral material
scene exposed black silhouettes on bumped Principled materials with the
native default Chiang terminator. The same graph on pure Diffuse did not
show that band; selecting Conty also removed it. Native reflection-normal
correction is currently coupled to the Conty choice. Cycles instead controls
it with Material `use_bump_map_correction` and applies it to glossy closures.
That per-material/per-lobe behavior remains open; changing the default
terminator to conceal it would not preserve native quality or closure
semantics. No default was changed. Glass convergence, arbitrary closures,
output-displacement composition and production/GUI scenes remain unverified.

The private prototype used 2.11.19 metadata but a different native hash from
the frozen public 2.11.19 CI wheel. Public 2.11.19 contains Normal Map and
RoughMatte fixes, not this new Bump type. Do not equate the prototype's version
string with a public-package validation result.

Evidence: workspace
`test-scenes/validation-2026-10-09/cycles-scene-goal-phase16`, especially
`candidate-after-facing-fix`. It retains raw images, logs, harnesses and
pre-fix failures as well as the final passes and closure-isolation images.

The final 2.11.20 Release build was installed with the full dev sync into a
separate profile, including cached wheel and metadata. All six spectral Bump
conditions per backend passed again (twelve total); the loaded module SHA-256
is `cb90c5b7a5b382c5ff4ae31d4b018e4d6780449ba0084c3fb2d148ed2ae03f7e`.
Evidence is under `phase16/final-v20`. This candidate is not the actual user
installation, which remains on the verified public 2.11.19 bundle.
