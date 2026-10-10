# Private Cycles BSSRDF Metal hybrid scene verification

The unchanged-Cycles-scene goal remains active. The native uniform rough
reverse walk and inverse boundary are described in the
[core implementation record](../../../SuperLuxCore/doc/engineering/2026-10-11-cycles-bssrdf-device-adjoint.md).
Local estimator contracts completed device-adjoint42, curved-geometry8,
all-device hybrid6, CPU transport50/hybrid23/rough-adjoint22/sharp18.
These are scoped private transport checks, not production SSS acceptance.

`dev-tools/cycles-bssrdf-device-hybrid-scene-test.py` extends the existing private
Blender harness in its process, using an asserted AST transformation. It keeps
the authored Cycles fixture and its graph fingerprint. It selects PATHOCL with
explicit device/adjoint flags, enables the hybrid light pass, disables native
light threads and passes independent eye/light halt budgets. The original,
extension and generated harness sources have separate SHA256 records.
Shipping adapter source and quality defaults are unchanged.

The older PSR3 checks used GPU eye paths with a native CPU light fallback at
8192 total tasks. They validate combined transport. The corrected PSR harness
reserves a genuine GPU light tail with 16384 tasks and zero native threads,
and explicitly requires light-sample progress before accepting a hybrid run.

Existing Metal57, corrected all-device PSR3 and RANDOM/METROPOLIS sampler4
conditions completed. Guarded ordinary emission/MNEE15 and black-film3 checks
also completed. Three unchanged-graph 1280x720 comparison sets completed, and
all six original PNGs were directly inspected. Metal hybrid wavefront off/on
body-region channel means differed from independent CPU eye by 0.3209%/0.3401%.
The raw EXRs are finite. Shape, orientation and warm scattering meaning are
preserved; conspicuous spectral grain remains, particularly in the hybrid.
These fixed budgets do not establish production noise convergence. The unused
isolated local profile was verified and removed after all workers finished.
Signed exact-source wheels and installed-core verification are pending.
Sharp device camera connections, textured/mixed reverse kernels, spatial
PDF/MIS, broader Cycles closures and production adapter exposure remain open.
The full compatibility goal is not complete.
