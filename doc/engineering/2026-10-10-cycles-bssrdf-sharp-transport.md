# Experimental sharp Cycles BSSRDF CPU adjoint transport

A homogeneous standalone Cycles BSSRDF with Roughness 0 can connect a pure
`LIGHTCPU` random walk to the camera through its sharp entry boundary. The
original eye walk and SuperLuxCore quality defaults remain intact. This is an
experimental prerequisite for the existing full no-edit Cycles scene goal;
production compatibility and stable adapter deployment remain unfinished.

## Operator and camera measure

The eye closure consists of unit-weight entry refraction, a frozen-coefficient
object-local HG random walk and a white diffuse escape. Its transpose starts
with the diffuse escape, reverses the medium and ends with the inverse entry.
An escaped sharp delta BSDF cannot evaluate a finite camera connection. The
new connection callback therefore visits the initial diffuse escape and every
internal HG collision before sampling its continuation direction.

Each connection uses an independent RNG stream, a first-boundary trace confined
to the same physical object/group, and a refractive single-vertex manifold
solve. Perspective cameras use the sampled lens position; orthographic cameras
use the fixed camera direction and project the solved boundary to the film.
The receiver factor is the original diffuse geometry-cosine density or the HG
phase density. The segment includes its actual Beer attenuation, the unit entry
kernel's ior-squared transpose and the ordinary shade/geometry cosine correction.
It introduces no glass Fresnel attenuation. The solved boundary retains the
real material/object Cryptomatte identity; the collapsed SSS closure still
counts as one diffuse reflection in external path counters.

Independent uniform direction seeds can select multiple Newton roots. Repeated
independent solves estimate the reciprocal probability of selecting the same
root. A weighted roulette tail preserves that estimator's expectation rather
than truncating rare basins without compensation. This follows the probability
correction in [Specular Manifold Sampling](https://rgl.epfl.ch/publications/Zeltner2020Specular)
by Zeltner, Georgiev and Jakob (2020). This design does not establish a general
finite-budget variance or production convergence result. Small basins and
chromatic light-path grain remain quality concerns.

## Precision and smooth surfaces

The local solver differentiates the actual normalized barycentric shading
normal on the geometric triangle, independently of UV coordinates. For a
nonuniform instance it transforms raw corner normals before interpolation and
normalization, matching the mesh's normal field. Geometric position tangents
and shading constraint tangents remain separate. Ordinary glass/mirror MNEE
continues to use its existing parameterization and tolerances.

An internal collision close to a boundary cannot attain an angular residual
below the float world-position error divided by the segment length. Local
convergence and inverse-direction validation account for that attainable
precision. The initial diffuse vertex and every re-projection start at the
same exact receiver point. Its initial triangle is excluded from the first
boundary trace rather than offsetting the origin and solving a different
constraint. Opt-in `SUPERLUXCORE_BSSRDF_SHARP_JACOBIAN` diagnostics compare the
analytic measure with four independently perturbed, re-solved paths.

Initial strict-tolerance, missing-curvature and offset-origin failures are
preserved with raw outputs, source snapshots and exact package fingerprints.
The nonuniform instance's missing unscattered contribution was recovered by
the exact-origin trace. Light sample-result storage grows only when internal
connections exceed the original external-path allocation and is retained for
later samples; the used count bounds splatting.

## Backend option preflight

The backend consumes `path.vertexconnection.enable`. The previous diagnostic
preflight checked only `path.vertexconnect.enable`, which cannot guard the
actual promotion to hybrid tracing. Both CPU and device validation now reject
the consumed canonical option; the prior diagnostic spelling also remains
rejected. The CPU, LIGHTCPU and actual Metal contract fixtures use the canonical
option. Unsupported vertex connections cannot bypass the BSSRDF transport gate.

## Verification and remaining scope

The final release module and complete isolated wheel use native SHA-256
`44d9314de884015bfdb88305dd2057e3e477132205682f271e912c64cee10524`.
Final validation after the canonical-option fix is complete. The connection
implementation was first verified with native SHA-256
`e460a834a4db73187c6afb6b08355c28b6374b8e22a20165c84a9c6b64be95fa`.
The complete corrected permanent driver passes in one final execution: CPU 50,
rough-adjoint 22 and sharp 18 conditions. The sharp maximum raw channel mean
error is 0.7176%; isolated floor continuation is 0.4759%. The existing ordinary
CPU/LIGHTCPU/Metal emission driver also passes all five conditions without SKIP.
CUDA static lint reports zero problems in 181 kernel files. Runtime/native and
whole-wheel RECORD/payload fingerprints identify the actual tested package.

The last floor fixture initially excluded every light path because the body
was missing its source link group. Its correction preserves the original
mesh/material/ID. The intermediate 16-plus-two execution, tested-prefix AST
proof and failed dark outputs are retained; final acceptance uses the full
corrected driver, without a skipped or resumed condition.

Actual Apple M5 Pro Metal wavefront off/on 51 contracts and three directly
reviewed 1280x720 Cycles comparison sets pass with the final native library.
The initial connection implementation's perspective nonuniform-instance derivative probe independently re-solves
four neighboring paths for each accepted sample: 125 probes, including six
initial diffuse vertices, have maximum relative Jacobian difference 0.5443%.
These are scoped derivative/mean checks, not per-pixel convergence proof.

The sharp fixture uses an independent eye random walk and a 3% per raw RGB
channel mean gate over the whole eroded material-ID region, including smooth
curved meshes, UV/no-UV normals, nonuniform instances, an independent seed,
anisotropy, low/high IOR, partial RGB radii, spectral color, a no-scatter-heavy
case, a concave torus and continuation to an ordinary surface. Eye/light
external path depths match the same physical scattering vertices.

Pure LIGHTCPU has no primary environment-background path. Even filter NONE
and an eroded material-ID mask can contain partially covered silhouette pixels.
The sharp energy fixture therefore sets `path.forceblackbackground.enable` on
both estimators, preserving all lighting and secondary environment hits. The
same 460-pixel smooth orthographic region initially failed with 8.1481% blue
mean difference; with this physically matched primary-path set the independent
probe's maximum channel difference is 0.7149%. The ROI and 3% gate are unchanged.
This control does not alter the original Cycles graphs or 720p visual fixtures.

The original colored sharp Cycles graph is unchanged across CPU/Metal eye
128 spp and pure LIGHTCPU 512 light spp. Image review confirms orientation,
shape, light direction, color/scattering meaning and alpha. Pure LIGHTCPU has
substantially stronger chromatic grain and a few bright samples and is not
accepted as production quality. No speed claim is made during concurrent
project activity.

Both existing experimental enable flags are still required. Mixed/textured
adjoint kernels, different material partitions, Normal/Bump/opacity/volume,
GPU reverse walks, hybrid/BIDIR and spatial/reverse-probability MIS remain
gated. This unit does not switch the public 2.11.27 SSS adapter, repair its
positive-radius defect in the installed package, lower quality defaults, or
complete the full goal. Principled/Skin/Burley/legacy methods and the broader
compatibility registry remain part of that active goal.

Evidence is preserved under the workspace's
`test-scenes/validation-2026-10-10/cycles-bssrdf-sharp-transport/`, including
source-frozen fixture builders, package RECORD/payload fingerprints, raw paired
outputs, initially failed configurations, original PNG/EXR images and reviews.
`Scene::ToProperties()` alone does not include inline mesh buffers; reproducing
the geometry requires the frozen builders in addition to the serialized
camera/material settings. Completed temporary profiles and duplicate wheels
are removed after the required package tests finish.

The legacy directional-glass MNEE test initially failed on both the previous
main CI wheel and the candidate. Auto PSR makes the CPU glass non-delta during
its early sample budget, outside the MNEE gate. The regression now explicitly
selects the intended unregularized delta operator, without changing production
defaults: CPU/Metal interior luminance 0.0895/0.0898; CPU MNEE-off is zero. All
seven directional-chain gates pass. A trial of broader common-normal changes
had no measured benefit and was reverted. The dispersive light-side regression
also passes its existing broader bounds (upper/lower ratios 0.71/0.78); it is a
regression smoke check, not a 3% physical parity or convergence result.


## Exact main CI wheel verification

Native main commit `447159b8cd1634fcf43aca579071f430a04fd062` was pushed
and verified on GitHub. Its [exact-commit workflow](https://github.com/claudianus/SuperLuxCore/actions/runs/38053140005)
was manually dispatched after the push had not registered an automatic run.
The macOS ARM artifact metadata identifies that exact SHA and workflow ID.
The complete wheel RECORD, extracted payload, cached wheel and 266 runtime
Python files were checked before tests and rechecked after all children exited.

The CI wheel SHA-256 is
`8573f89b5411654ccb7c5bc6ce458eda384348312981726bc893c3eee46ffe17`;
its actually loaded native module SHA-256 is
`a0ae02bd47cc49186f1f236b431e7836ff3eff7fedbbb9e1a797bfdf4c3e1e9d`.
The full corrected driver passes CPU50, rough-adjoint22 and sharp18 in one
execution. The CI sharp maximum raw-channel mean error is 0.7150%; continuation
to the ordinary floor is 0.5284%. Actual M5 Pro Metal51, ordinary5 (zero SKIP),
directional MNEE7 and the broader light-side MNEE smoke3 also pass.
The latter has upper/lower/all ratios 0.91/1.12/0.99 under its existing wider
regression bounds, not the sharp driver's 3% operator-parity criterion.

Three CI-wheel 1280x720 comparison sets preserve the original graph. All six
original-resolution PNGs were directly reviewed. CPU/Metal128 and LIGHTCPU512
mean brightness ratios against Cycles are 1.02389/1.02447/1.02392; alpha error
is zero. Geometry, light direction and warm scattering meaning agree, while
LIGHTCPU retains stronger chromatic grain and sparse bright samples. These
images do not accept production convergence or arbitrary Cycles SSS behavior.
The actual public installation remains version2.11.27, native module SHA-256
`d29c2387496c2bb94700b7cbe09a4bb9cdde5c6f225056c6309e8dd3d752b2bf` and
Cycles reader SHA-256
`7dd35540ac9a1fcffdbd4b1aeb2684957f51164e799a30b93cc6d271fcb6a235`.
Its positive-radius SSS production defect remains open.

Final local and CI evidence, complete wheels, source snapshots and raw outputs
are preserved in `cycles-bssrdf-sharp-transport/local/` and `ci/` beneath the
workspace validation directory. Both completed temporary test profiles and
the staging directory were removed; all owned test children were reaped.
The dev installation sync now excludes generated `out/`, which had copied
354MiB of unused build outputs. Bash syntax and the exact rsync source copy
were checked; all 266 runtime Python files remain identical. No user runtime
or quality defaults changed as part of that cleanup.


All four platform wheel jobs, CUDA NVRTC, wheel attestations and rolling
publication completed successfully. The [public wheels-latest release](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-latest)
points to exact native commit `447159b8cd1634fcf43aca579071f430a04fd062`.
All four wheel assets are uploaded. The public ARM asset digest is exactly
`sha256:8573f89b5411654ccb7c5bc6ce458eda384348312981726bc893c3eee46ffe17`,
matching the whole wheel tested in actual Blender. Platform compile success
does not establish Windows/Linux/Intel GPU execution or production SSS quality.
The workflow, tag and release metadata are preserved with publication-proof.json.
