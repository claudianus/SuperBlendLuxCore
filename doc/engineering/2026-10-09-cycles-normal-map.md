# Cycles Normal Map spaces and MikkTSpace data

Version 2.11.19 adds `cyclesnormalmap`, a direction-data texture used by the
Cycles adapter. The existing native `normalmap` texture keeps its legacy
contract. The new texture evaluates colour and linked Strength with spectral
conversion paused; raw colour is decoded without clipping. Tangent Strength
scales X/Y and blends Z toward one for the clamped zero-to-one range, preserving
negative and greater-than-one Strength semantics. Object/world spaces use the
original direction transform and nonnegative Strength blend. OpenGL/DirectX
normal convention and Blender legacy object/world axes are represented.

For tangent space the exporter reads Blender's MikkTSpace corner tangent and
bitangent sign for the original active-render or named UV layer. Object-space
corner normals and tangents are interpolated before the normal transform.
Mirrored UV handedness and nonuniform object transforms are preserved. These
arrays belong to the evaluated temporary mesh; original artist meshes and node
settings are not changed. Tangent channels participate in the existing vertex
weld and material partition. The eight colour/eight alpha data-channel budget
and missing UV/tangent failures produce explicit diagnostics.

## Backfaces and the film contract

Texture spectrum evaluation exposes camera-facing shader direction data. Bump
returns the mesh-side direction required by the native BSDF. `normalvector`
uses the same distinction so a Normal Map output may feed Vector Math/Mix and
then a shader Normal input. This changes data adapters, not the native film's
SHADING_NORMAL representation. The Cycles Normal compositor alias converts
native shading normals with GEOMETRY_NORMAL and the camera direction/position.
Orthographic plane and sphere fixtures validate this alias. Depth of field,
spherical stereo and grazing camera boundaries still need specific checks.

A backface investigation found that `np.ascontiguousarray(normals)` reused the
same allocation adopted by DefineMeshExt. Object transformation changed that
buffer in place, corrupting the supposedly original object-space normal data.
The exporter now gives these data an explicit separate owning copy. Temporary
hit-point debugging was removed before the final Release build and rerun.

## Validation

Installed Blender 5.2.1 LTS source object
`9e2066aef7ef7e20c142ad7bd3303138a4304c93` was inspected in the local Blender source
repository. Private Release 2.11.19 was built, fully synchronized into an
isolated extension profile, and warmed before tests. Native and package
versions are checked by the harnesses. All tests use 1280×720, 16 samples,
original Cycles nodes, signed EXR Normal-pass comparisons and finite/error gates.

| Fixture and mode | Cases per CPU/Metal | CPU max MAE | Metal max MAE |
| --- | ---: | ---: | ---: |
| Plane RGB | 17 | 0.00081170 | 0.00089813 |
| Plane standard spectral | 8 | 0.00080508 | 0.00086594 |
| Smooth sphere RGB | 6 | 0.00225086 | 0.00228711 |
| Smooth sphere standard spectral | 4 | 0.00225166 | 0.00225830 |

All 70 conditions passed the 0.003 component-MAE gate. Cases include tangent,
nonuniform scale, rotation, named and mirrored UV, zero/fractional/negative/
above-one and linked Strength, raw above-one colour, object/world space,
DirectX convention and a backface. Nine Cycles/CPU/Metal comparison sheets were
directly inspected for direction, handedness, gradients and smooth-surface
patterns. Display PNGs clip negative components; signed comparisons use EXR.
Small smooth-surface boundary differences remain measurable. This is a bounded
normal-data validation, not a bitwise image or full material-energy claim.

Evidence: workspace
`test-scenes/validation-2026-10-09/cycles-scene-goal-phase14`.
Harnesses: add-on `dev-tools/cycles-normal-map-test.py` and
`dev-tools/cycles-normal-map-smooth-test.py`.

## Persistent graph-edit regression

A repeated-render regression first failed when Normal Map was introduced into
an existing material after a render without tangent data (MAE 0.2438). The
persistent final scene refreshed materials but retained the original mesh
channels. Tangent UV requirements now participate in the geometry reuse
signature; adding/removing a map or changing its named UV rebuilds that data.
Viewport object updates also detect changed requirements. Requirements are
read from the original material graph. Actual GUI viewport interaction remains
unverified.

After the repair, the existing normal-vector fixtures passed ten RGB and five
standard spectral cases per CPU/Metal, including insertion into an already
rendered graph and map arithmetic/Mix. The image-vector Bump fixture passed
four standard spectral cases per backend: 38 regression conditions total.
Failure logs are preserved under phase14/regression-before-cache-fix. The final
70 Normal Map conditions were rerun after the cache repair; the table above
records this rerun. All nine comparison sheets were inspected again. E37
settings parity passed 22/22.

A separate 1280×720, 32-sample standard spectral beauty fixture exercised
normal-mapped, nonuniformly scaled Principled diffuse, metal and transmission
surfaces on CPU and Metal. Both produced finite images without renderer errors;
those images and a 32-sample Cycles reference were inspected. Placement and
normal-map direction are preserved, but metal highlights and the transmission
sphere retain visible material/radiometric differences and sampling noise.
This is a runtime/visual smoke check, not a completed material-parity claim.

## Remaining scope

No-UV/generated tangent fallback, channel-budget overflow, deformation and
animation, displaced original base, broader instancing/cache reuse, specular
normal guards, Coat Normal and Tangent still need implementation or runtime
validation. Geometry Normal data on arbitrary backfaces and generic Bump output
chains are distinct open contracts. Normal compositor conversion for depth of
field/stereo needs exact primary-ray validation. Do not count C46, C31 or C26 as
fully complete from these fixtures. Renderer quality defaults, estimators,
clamping and caustic settings are unchanged.
