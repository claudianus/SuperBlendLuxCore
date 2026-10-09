# Normal data vectors for shader inputs

`normalvector` is a data texture with an explicit direction-vector Bump result.
It reads its child with spectral conversion paused, normalizes finite non-zero
vectors, and uses the hit-point shading normal for a zero/non-finite result.
Unlike a generic colour texture, its Bump does not differentiate components as
a scalar height. CPU and GPU carry the same texture type and unsigned input
indices.

The optional `sourcebump` input adapter exposes a legacy normal-map Bump result
as vector data. Existing native normalmap behaviour remains unchanged. Cycles
Normal Map outputs can therefore feed Vector Math and vector Mix before shader
Normal inputs without collapsing to the legacy normalmap colour value (black).
The exporter tags other linked Normal input graphs as normalvector, retaining
the direct Bump-node path. The old NormalMap/Geometry-only Mix workaround is
replaced by evaluation of the actual connected vector graph.

## Validation

Blender 5.2.1, private Release 2.11.18 build, 1280×720 Normal pass, 16 samples:
ten RGB cases and five standard spectral cases on both CPU and actual Metal.
All 30 cases passed finite-value and error checks. Maximum mean absolute
component errors were 0.00007552 CPU RGB, 0.00008765 Metal RGB, 0.00007552 CPU
spectral and 0.00010977 Metal spectral. Three comparison sheets were inspected:
constant/negative/zero/geometry vectors, UV gradients, vector Mix, direct normal
map, normal-map arithmetic, two-map Mix, and map/flat Mix have the expected
orientation and pattern. Signed data are compared in EXR; PNG display clips
negative components and is only the visual aid.

Evidence: workspace `test-scenes/validation-2026-10-09/cycles-scene-goal-phase13`.
Harness: add-on `dev-tools/cycles-normal-vector-test.py`.

## Remaining compatibility scope

The normal-map cases use an applied plane scale to isolate graph evaluation.
A nonuniform object scale reproduced a legacy tangent-space mismatch (MAE
0.1130), which is still open. These checks do not validate MikkTSpace, mirrored
or named UV normal maps, object/world spaces, out-of-range strengths, arbitrary
backfaces, specular normal guards, chained Bump nodes, Coat Normal or Tangent.
E37 settings regressions passed 22/22. The existing image-vector Bump Normal-pass
fixture also passed four standard spectral cases on both CPU and Metal.

The generic Bump output consumed through another vector node remains a separate
contract. Do not count these as completed by this data-vector change.
