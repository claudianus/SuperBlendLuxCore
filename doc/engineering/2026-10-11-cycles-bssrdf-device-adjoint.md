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
Signed exact-source wheels and installed-core verification subsequently completed as recorded below.
Sharp device camera connections, textured/mixed reverse kernels, spatial
PDF/MIS, broader Cycles closures and production adapter exposure remain open.
The full compatibility goal is not complete.

## Exact signed CI and actual core deployment

The exact native source `c2915a73a325bd2e5d0e2f999298051bf9af5d32`
completed [workflow 38081369548](https://github.com/claudianus/SuperLuxCore/actions/runs/38081369548).
All four platform builds, CUDA NVRTC, wheel attestation and rolling publication
succeeded. The signed ARM whole wheel SHA256 is
`dace137bff6799eebb099ede4e4570ad3eba07fdd1bc9d79b624ca25db1ba5d7`;
its loaded native SHA256 is
`d5443cf5022c653d5636fa4b44ec246a60e39b0b65e2078e6135410949636024`.
All four signed wheel subjects match the corresponding rolling release assets.

This wheel passed CPU50/hybrid23, CPU50/rough22/sharp18, device-adjoint42,
geometry8, hybrid6, Metal-eye57, all-device PSR3, sampler4, guarded ordinary15
and black-film3. Device adjoint, geometry and hybrid maximum channel-mean errors
were 2.1422%, 1.0104% and 1.3415%, within the retained 3% gates. One orchestration
attempt failed before ordinary rendering because the output directory did not
exist. Its logs and states were preserved; directory creation was repaired and
only the remaining suites were resumed. No passing suite was replaced.

All six unchanged-graph 1280x720 Cycles/native comparison PNGs were directly
reviewed. Metal hybrid retains conspicuous chromatic grain and a visually grayer
body at 128 eye / 512 light samples. The predeclared raw-body region differs
from independent CPU eye by 0.3110%/0.2843%. This accepts the bounded transport
operator check, not final noise convergence or production adapter promotion.

The stable installed adapter was cloned into a temporary preview profile.
All 266 runtime Python files and all 192 extracted wheel members were verified.
The preview CPU/Metal images and the actual-installed CPU/Metal images were
rendered at 1280x720 and directly reviewed. Voronoi facets, glass, reflections,
floor shadows and the transmitted blue pattern were retained; 128-SPP grain
remains visible. The actual installed core and cached whole wheel match the
signed hashes. Fresh Blender 5.2.1 LTS registration and actual PSR3 passed;
PSR maximum error was 2.0111%. All 374 installed Python files, including the
266 runtime files, and user settings remained unchanged. The preceding signed
whole wheel remains a rollback reference. An already-open GUI hot reload was
not tested.

The unused preview profile was verified again and removed immediately
(293058056 logical bytes). After the separate read-only volume prototype
finished, all owned workers were reaped, all 459 CI profile entries and 79
frozen source files were verified, and the remaining stage was removed
(293160963 logical bytes). Physical space freed is not measured. Whole wheels,
raw EXRs, original PNGs, signatures, failed diagnostics and SHA inventories
remain in durable evidence. `ci/completion-proof.json` and
`ci/preservation-inventory.json` record this completed deployment unit.
The production BSSRDF adapter remains unchanged and the full goal stays active.
