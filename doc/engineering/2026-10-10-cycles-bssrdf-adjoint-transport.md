# Experimental Cycles BSSRDF CPU adjoint transport

Pure `LIGHTCPU` can now reverse a standalone homogeneous Cycles random-walk
closure and connect its rough entry boundary to the camera. This is an actual
light-path transport implementation, building on the shared directional
boundary measures, rather than another eye-side render. It remains a private
diagnostic prerequisite for full Cycles scene compatibility. The release
adapter, user installation and production quality defaults are unchanged.

## Transport operator

The original eye walk samples the GGX entry direction without ordinary rough
glass attenuation, freezes its coefficients, traverses the object-local medium
and continues through a white diffuse escape. Its transpose must start with
the white diffuse operator, reverse the homogeneous medium, then evaluate or
sample the inverse GGX entry. Refracting at both ends would implement a
different operator.

The light-side start samples an inward geometry-cosine hemisphere and retains
the original escape's external shading/geometry cosine ratio. The reciprocal
homogeneous HG medium uses the same distance-channel mixture, absorption,
partial RGB local-channel split, spectral support, low-albedo compensation and
Russian roulette as the eye walk. Groups may contain several meshes when
every member shares the same root material; a different material partition is
rejected because the original entry's frozen coefficients cannot simply be
replaced by coefficients at a different light-side point.

At the other boundary, a scene-owned proxy evaluates the original entry's
`p_forward(inside | outside)` as `f*cos(theta_light)`. Its proposal samples
`p_reverse(outside | inside)` and returns `p_forward/p_reverse` before the
ordinary `BSDF` geometry-cosine adjoint correction. The shared helper retains
TIR/rejected mass and is not reciprocal rough glass. The proxy is a member of
the scene material, so no temporary BSDF material can outlive stack storage.
The collapsed closure counts as one diffuse reflection in external path-depth
and ray-context counters, as on the eye side; the internal inverse boundary's
transmission event is not exposed as another scene bounce.

BSDF material name, numeric ID and Cryptomatte ID retain the real visible
surface's identity when an internal diffuse/adjoint proxy replaces its shading
operator. Every BSDF initialisation clears that retained identity. Ordinary
materials continue to use their own identity.

## Explicit support boundary

Both `path.cyclesbssrdf.experimental.enable` and
`path.cyclesbssrdf.experimental.adjoint.enable` are required for `LIGHTCPU`.
The diagnostic accepts constant color, Radius, Scale, IOR, Roughness and HG
anisotropy, with a rough nonlocal camera boundary. All-local radii may use
zero roughness. Mixed roots, different material partitions, textured
coefficients, explicit Normal/Bump, opacity and volume kernels are rejected
before workers start. Sharp nonlocal boundaries require internal-vertex or
manifold connections and are rejected as well. Live edits run the same
preflight and can recover after an invalid edit is repaired.

Hybrid light/eye tracing, BIDIR, vertex connections, ReSTIR and photon caches
remain gated. The global CPU gate now also rejects `path.vertexconnect.enable`:
`ParseOptions` can force hybrid tracing from that option even when the authored
hybrid flag is false, which previously bypassed the eye-only preflight.

## Validation scope

The complete isolated wheel's native SHA-256 is
`407702be156d3420bf33f5c6116d7fc008f0639ca854df9a1f0cc0420ba8ca24`.
Blender is 5.2.1 LTS `9e2066aef7ef`; device regressions use actual Apple M5 Pro
Metal. The release adapter is never patched on disk by these diagnostics.

The paired transport driver checks gray/colored RGB, forward/backward HG,
low/high IOR, partial RGB radii, spectral and all-local limits, black absorption,
original material/object Cryptomatte names, ordinary-surface continuation and
live-edit preflight recovery. It retains a 3% per-channel energy gate. The
near-unity IOR case has narrow inverse-camera angular support and uses a
larger independently checked photon budget, rather than relaxing this gate.
Final paired/preflight/identity/live-edit contracts: 22 PASS; maximum furnace
per-channel mean difference is 2.4480%. Existing CPU contracts: 50 PASS; actual
Metal wavefront off/on: 51 PASS. Ordinary CPU/LIGHTCPU/Metal emission regressions:
5 PASS, no SKIP. CUDA static lint: zero problems in 181 kernel files.
Independent low-IOR seeds at 65536 light spp differ by 0.55% and 1.76%.
The metrics and logs preserve the exact budgets and completed sample counts.

There are two necessary controls for small eye/light transport comparisons:

- Pure LIGHTCPU does not own the zero-bounce environment background. A wide
  reconstruction filter spills that background into object-edge pixels in
  an eye render. Small energy fixtures use `film.filter.type=NONE`; the
  1280x720 Blender visual tests keep their ordinary filters.
- The eye tracer performs no NEE at a terminal non-primary vertex, while
  LIGHTCPU connects its last vertex. Eye total depth 4 and light total depth
  3 therefore match three physical scattering vertices in these fixtures.

The initial mismatched continuation comparison failed at 3.2-3.8%, and the
short near-unity IOR photon budget also failed the unchanged 3% gate. These
failures are retained. The independent continuation probe uses two seeds,
4096 eye spp and 32768 light spp, both with and without direct illumination of
the ordinary floor. Light linking excludes direct environment-to-floor paths,
so the second floor comparison isolates SSS-to-floor continuation. All eight
material/seed/illumination comparisons pass; maximum relative mean error is
0.3654%. This establishes the tested continuation operator, not production
convergence or a broad MIS result.

The private Blender harness additionally transposes the halt budget in
`export.halt.convert`: the ordinary UI still describes eye tracing, and its
later `[eye_spp, 0]` update would otherwise leave pure LIGHTCPU running
indefinitely. Both initial and later diagnostic halt properties use
`[0, light_spp]`. The incomplete first execution is preserved, and is excluded
from completion/performance evidence.

Two unchanged spectral Cycles graphs are rendered at 1280x720: colored and
rough-anisotropic SSS. Cycles and CPU/Metal eye rendering use 128 spp; pure
LIGHTCPU uses 512 light spp without changing the original Cycles sample
setting. Light/Cycles mean ratios are 1.02479 and 1.01197, respectively. The
opaque final images have equal alpha, but this is not a proof that LIGHTCPU
owns eye-only alpha, depth or other camera AOVs. Direct original-resolution
review confirms orientation, shape, light direction and color/scattering
meaning. The pure light estimator has substantial chromatic grain at this
budget and is not accepted as a production-quality replacement.

Evidence lives under the workspace's
`test-scenes/validation-2026-10-10/cycles-bssrdf-adjoint-transport/`: complete
wheel/runtime provenance, renderer and driver snapshots, raw paired outputs,
linear EXRs, original PNGs, reviews, initial failures and CI/delivery state.
Timing is excluded from performance claims because other project renders were
active during this validation.

## Remaining work for the existing full goal

Full/default-quality Cycles compatibility remains unfinished. GPU reverse
walks, hybrid/BIDIR and spatial/reverse-probability MIS, sharp camera boundaries,
textured frozen-entry reconstruction, different material partitions and
mixed/Normal/Bump/opacity/volume/ray contexts are still required. Principled
random-walk/Skin/Burley/legacy methods, radius/spectral limits and broader
production/interactive/platform coverage remain in the compatibility registry.
The public 2.11.27 positive-radius SSS defect is not repaired by a private
opt-in diagnostic. Production deployment must retain SuperLuxCore quality and
enable the real adapter only after those contracts are verified. The goal is
active; this implementation does not narrow or complete it.
