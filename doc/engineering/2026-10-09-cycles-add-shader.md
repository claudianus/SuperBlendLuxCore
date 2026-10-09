# Cycles Add Shader closure sums and transparent transport

The 2.11.20 development candidate exports Add Shader as a sum of closures. It
preserves the original Cycles node graph and does not change the artist's nodes
or rendering settings. Pixel identity with Cycles is not an acceptance condition.
This feature does not change the native quality defaults or switch the shadow
terminator from Chiang to Conty.

This is a bounded surface-closure implementation. The overall Cycles scene goal
and C39 remain partial. The actual user installation is the verified public
2.11.19 package; this candidate has not been packaged or deployed publicly.

## Closure and estimator contract

Native `mix` accepts `additive = true`. Ordinary Mix retains its existing amount
and normalization. Add selects each child with probability one half and evaluates
`2 * (.5 * fA + .5 * fB) = fA + fB`. The factor also applies to sampled throughput,
delta events, inherited emission, albedo and selected transparent throughput.
Mixture PDFs keep their selection weights. Nested sums therefore retain all
closure weights rather than repeatedly halving their physical contribution.

Transparent is a closure, not an empty Add input. Scene intersection uses the
same selection variable to choose and skip null closures before returning a
scattering vertex. For the returned vertex, let `P` be the non-null selection
probability. Evaluation and its direct/reverse PDFs are conditioned by `1/P`;
sample throughput `f/pdf` is unchanged and its returned PDF is conditioned by
`1/P`. A direct emission hit at that vertex has the same selection compensation.
Recursive material calls keep the original distribution; compensation happens
once at the BSDF boundary.

A BSDF records whether scene intersection actually performed this conditioning.
BSDFs initialized directly on a light or another sampled surface keep the
unconditioned distribution. CPU and the shared OpenCL/Metal kernel implement the
same boundary. This avoids applying eye-vertex conditioning to a bidirectional
light start that has not rejected a null selection.

The implemented selection complement covers native Null/Mix closure trees.
Direction-dependent ArchGlass and custom coating/opacity combinations need
separate estimator coverage; the flag must not be treated as a universal
pass-through probability.

## Emission inheritance

A standalone Emission can attach to a simple, non-emitting surface. Null and
composite materials use an additive closure. Null would skip an attached emission;
Mix, GlossyCoating and TwoSided can inherit emission without having a local
`.emission` property. Adding a local property on such a composite would override
its children. The adapter therefore avoids the attachment shortcut for these
types. It also clears provisional root properties after exporting the children
so a replaced root cannot refer to a material defined later in the property list.

## Alpha as data

A primary ray keeps an RGB transmission weight independently of spectral
radiance. At each participating surface it accumulates the local opacity
`mean(Wrgb * (1 - Trgb))`, where `Trgb` is the analytic weighted null transmission
of the closure tree. A selected transparent continuation updates `Wrgb` with its
existing probability-compensated RGB throughput. This reduces selection noise
for a single transparent surface and preserves the expectation for geometry
behind it. Spectral evaluation is paused for this data calculation; the GPU uses
a scoped raw-RGB context and restores the previous context afterwards.

Signed sample contributions remain signed until film accumulation. RGBA and Alpha
outputs clamp the normalized final value to `[0,1]`, matching the purpose of
Cycles `kernel/film/read.h::film_transparency_to_alpha`. The camera-transmission
field is reset, copied and moved with SampleResult on CPU and reset on GPU.
Volume first-hit and holdout behavior retain their existing handling.

## Evidence and current verification boundary

Blender 5.2.1 LTS, build `9e2066aef7ef`, ARM64, 1280 by 720. Raw EXRs, PNGs,
logs, harnesses and runtime hashes are retained in workspace validation phase17.
The runtime is installed with the full sync script; replacing a dylib alone is
not a valid validation cycle.

The pre-final native binary
`048d0bbf98eee42c24f05fb3673b23e2a1d78c66a1a891f961194f76a813632c`
passed 106 bounded conditions: 18 RGB energy conditions per CPU/Metal, 15
achromatic spectral energy conditions per CPU/Metal, and 10 transparent-film
RGBA conditions per backend and RGB/spectral mode. Mean white-furnace energy is
within one percent, finite samples are required, and unsupported warnings fail
the gate. Per-pixel MAE is diagnostic rather than an equality requirement.

That binary then exposed an inherited-emission defect: a nested transparent
emitter emitted half the reference energy onto another surface on both backends.
The three preceding emitter controls passed. This failure is preserved; the 106
passes do not establish complete emission or Add compatibility.

The current candidate incorporates the composite-emission fix and the explicit
BSDF conditioning boundary. Its native runtime SHA is
`36ee7ab9928edbbb0a06e5899df57a9f17d9c20379c746bb22835c7fdcb917dc`.
This binary passed 120 checks/renders in `phase17/current-36ee7ab`:

| Check | CPU | Metal | Other |
| --- | ---: | ---: | ---: |
| Achromatic spectral Add/Mix energy and graph boundaries | 16 | 16 | |
| RGB energy, colored Transparent and inherited emission | 14 | 14 | |
| Spectral transparent-film RGBA | 4 | 4 | |
| Spectral mesh emitter illuminating another surface | 5 | 5 | |
| Spectral Bump data regression | 4 | 4 | |
| Spectral Normal Map data regression | 8 | 8 | |
| CPU BIDIR shader energy / emitter receiver | | | 5 + 3 |
| Existing large-film RGBA regression (1024 by 512) | | | 9 actual renders |
| Native default spectral material scene | | 1 | |

All other checks use 1280 by 720. Add energy uses a one-percent mean-energy
gate, emitter receivers use three percent, and alpha uses an absolute .01 gate.
Maximum native energy error in current PATH RGB/spectral tests is .056 percent;
maximum emitter mean error is .0054 percent. The current-hash nested emitter no
longer loses half its energy. Runtime logs confirm PATHCPU, BIDIRCPU and Metal
PATHOCL; a Metal image-pipeline device in a CPU log does not identify the path
tracer as Metal. The nine large-film renders also check native light-group
coordinate output and normalized RGB/alpha.

Four raw-EXR comparison sheets (closure energy, alpha, emitter receivers and
colored RGB) and the material-scene PNG were directly inspected. Nested closure
brightness, linked-factor gradients, transparent alpha, colored transmission
and receiver falloff retain their intended meaning. Stochastic noise differs.
The beauty scene keeps native spectral/quality defaults and contains no mapped
Normal/Bump; it does not verify the open C31 silhouette defect. Glass caustic
noise remains visible at 128 samples. EXRs, PNGs, logs, runtime warm-up, harnesses,
comparison extraction scripts and `validation-summary.json` are preserved.

The earlier finite-sample pixel-MAE gate rejected Diffuse+Mirror despite correct
mean energy; it was replaced with the physical furnace contract. A separate
nested alpha test failed because the Cycles 64-sample reference mean was 0.01042
against a 0.01 threshold, while native alpha was 0.000055. That was a reference
convergence limitation, not a native defect. Transparent-film references now use
256 Cycles samples. These intermediate records remain in phase17.

## Regression entry points

- `dev-tools/cycles-add-shader-test.py`: energy, delta, emission, transparent
  RGBA, empty inputs, groups and a linked Mix factor. The permanent harness checks
  node input values and links before and after rendering.
- `dev-tools/cycles-add-emitter-test.py`: mesh emission illuminating another
  surface, including nested Add and Mix with Transparent; catches camera-only
  checks that miss NEE or inherited-emission losses.
- Existing NormalMap, Bump, large-film RGBA and 720p material-scene checks must be
  included after native/kernel changes. Backend names alone do not prove which
  renderer ran; preserve the runtime logs.

## Remaining coverage

C39 is not a full-production or all-platform completion claim. Important open
coverage includes HDR/animated/view-dependent closure weights, colored spectral
radiance rather than only raw alpha, layered transparent geometry, motion,
volume Add/Mix, combined light groups and caches, broad bidirectional/VCM
transport beyond the eight targeted BIDIR checks, and actual
viewport/F12 behavior. General Principled glossy/bump silhouette correction (C31)
is tracked independently and remains unresolved. User OSL and baking stay outside
the deferred goal scope.

## Verified public 2.11.20 deployment

The fixed native source `2f0304832ea144a7069718a1cf0a6dcdb13dea73` and add-on
source `6a8c14837fae8428aaec459ad26ef4423f5ec9a7` are now public and installed
in the actual user Blender profile. The ARM CI native module SHA-256 is
`79b47dca82b4692aba120aa32adaf339457bfc49c5f822ca1f0f2b7dd83b6324`,
distinct from the private module used for the implementation checks above.

The public-payload gate passed 125 CI-wheel checks, 48 final-ZIP checks and 38
actual user-profile checks on CPU/Metal. Fourteen comparison sheets and six
1280×720 spectral material images were inspected. Four platform packages passed
runtime-file, metadata, exact-source/hash and GitHub attestation checks. These
checks retain the limits above, including strongly tilted reflection/diffuse
normals and production-scene coverage. See the
[deployment report](2026-10-09-deployment-2.11.20.md) for provenance, artifact
hashes, actual installation diagnostics and release-job cleanup.
