# Cycles BSSRDF directional boundary measures

The eye-side random walk samples a GGX visible normal at entry and refracts
without the ordinary rough-glass attenuation, matching the standalone Cycles
random-walk closure. Reusing that sampler unchanged in light tracing would not
transpose this directional kernel. This change supplies the shared boundary
sampler, forward/reverse densities and adjoint boundary proposal needed for that
work. It does not enable adjoint/LT/BIDIR transport or relax the preflight gates.

`cyclesbssrdf_boundary.cl` compiles as both CPU C++ (through the wrapper header)
and the GPU kernel source. The existing eye walk uses its entry sampler. Its
RNG mapping, raw refraction expression, final frame transform/normalisation and
geometry-side rejection are preserved; no second Fresnel/Smith attenuation is
added. These helpers assume finite unit directions in a face-forward frame,
outside `o.z > 0`, inside `d.z < 0`, IOR in the existing 1.01-3.8 range and GGX
alpha equal to standalone SSS roughness, 0-1.

For `h = face_forward(normalize(o + ior*d))`, `co = dot(o,h)`,
`ci = dot(d,h)` and `denominator = co + ior*ci`, the continuous densities are

```
p_forward(d | o) = D(h) G1(o) co/o.z * ior^2*(-ci) / denominator^2
p_reverse(o | d) = D(h) G1(d) (-ci)/(-d.z) * co / denominator^2
adjoint boundary weight = ior^2 * G1(o)/G1(d)
```

The refractive Jacobian follows Walter et al.,
[Microfacet Models for Refraction through Rough Surfaces](https://www.graphics.cornell.edu/~bjw/microfacetbsdf.pdf),
equation 17. The visible-normal density/sampler follows Heitz,
[Sampling the GGX Distribution of Visible Normals](https://www.jcgt.org/published/0007/04/01/paper.pdf).
The adjoint weight above is our transpose of the Cycles directional-only
kernel under the cosine measure; it is not a generic reciprocal rough-glass
throughput or a nonlocal spatial BSSRDF PDF.

The inverse sampler draws a visible normal from `-d`, refracts with reciprocal
eta, and returns an invalid event for total internal reflection or an outside
direction below the macro-surface. It retains rejected probability mass instead
of resampling and normalising it away. At alpha zero, continuous PDFs are zero,
Snell event masses are one on supported pairs, the adjoint weight is `ior^2`,
and total internal reflection has zero supported mass. The GGX D/G1 evaluation
uses stable expressions near the normal and grazing directions.

## Verified package and evidence

Complete isolated wheel native SHA-256:
`e92382fdbefe3cd79f54276ae9af555fa076b48886ea4a3a02eb6d6a5793e152`.
Blender 5.2.1 LTS `9e2066aef7ef`, actual Apple M5 Pro Metal GPU.

- The Objective-C++ probe compiles the exact shared source into CPU and an
  actual Metal compute pipeline. 4,718,664 samples cover 18 directional
  distribution cases plus 72 sharp/near-sharp, grazing, IOR-limit and TIR
  endpoints. The CPU entry direction equals the previous implementation for
  every probed entry sample (maximum direction error zero).
- Independent float64 solid-angle quadrature verifies forward normalisation,
  reverse accepted mass, directional moments and the cosine-measure transpose
  weight. Gauss/trapezoid quadrature refines from order 384 up to 6144 for the
  narrow low-IOR grazing lobe. Maximum refinement difference is 0.000473;
  reverse accepted masses range 0.017629-0.875041 in these cases.
- CPU/Metal have identical supported-event masks for the sampled cases.
  Maximum PDF/weight relative p99.9 error is 0.000776. The worst reverse
  direction difference is 0.0000863 near the critical angle; the conditioned
  error `error*cos(theta_out)/ior` is at most 0.000000829 (below 16 float32
  epsilons). Forward directions have a separate 0.00002 absolute gate.
- Existing CPU random-walk contracts: 50 PASS. Actual Metal wavefront off/on:
  51 PASS. Ordinary CPU/LIGHTCPU/Metal two-sided emission: 5 PASS, no SKIP.
  CUDA static lint: zero problems in 181 source files. Exact-commit NVRTC and
  platform wheel CI must still be checked after pushing this change.
- Actual Blender exporter/render: two spectral SSS scenes on CPU and Metal,
  1280x720 at 128 spp, four Cycles/native comparison sets inspected directly,
  including original full-resolution Metal images. Shape, lighting direction,
  scattering and color meaning agree. Native/Cycles RGB mean ratios are
  1.01177-1.02546; alpha MAE is zero. Small spectral hue/intensity differences
  and Monte Carlo grain remain. Source graph fingerprints are unchanged.

Workspace evidence is preserved under
`test-scenes/validation-2026-10-10/cycles-bssrdf-boundary-measures/`: complete
wheel/RECORD/runtime identity, critical source snapshots, probe inputs and
CPU/Metal outputs, quadrature metrics, linear EXRs, PNGs, visual review and
logs. Initial quadrature/sample resolutions and angle-independent float gates
failed; those logs are retained. The validation driver was refined while the
renderer and existing render-suite sources remained frozen. These are scoped
contracts and image regressions, not full-production convergence evidence.

## Remaining production transport work

The reverse walk must begin with the transpose of the white diffuse escape
boundary and end with this inverse GGX entry boundary. Textured coefficients
frozen at the original entry need reverse reconstruction of the nonlocal kernel;
freezing them at a different light-side point is not equivalent. Smooth GGX
camera boundaries also need internal-vertex/manifold connections. The spatial
PDF, reverse path probability, MIS, LT/BIDIR/vertex-connect, sampling depth and
RR contracts are still unfinished. Principled/Skin/Burley, mixed Normal/Bump/
Volume/ray contexts, radius/spectral limits and broader interactive/production
coverage remain in the compatibility registry. The public adapter, user
installation, stable release and production quality defaults are unchanged.
Full Cycles scene compatibility and this goal remain incomplete.

## Reproduce the directional probe on macOS

```
clang++ -std=c++17 -Iinclude -Iout/build/generated/include \
  -I<Boost include directory> -framework Metal -framework Foundation \
  dev-tools/cycles_bssrdf_boundary_probe.mm -o /tmp/bssrdf-boundary-probe
python dev-tools/cycles_bssrdf_boundary_test.py /tmp/bssrdf-boundary-probe \
  /tmp/bssrdf-boundary-evidence include/slg/materials/cyclesbssrdf_boundary.cl
```

The Python driver needs NumPy. The probe requires a real Metal device and
checks successful command-buffer completion; a source translation alone is
insufficient. Runtime rendering uses the complete isolated wheel and package
identity guards in the existing experimental Blender/native harnesses.
