# Private Cycles BSSRDF hybrid fixture and raw-region review

The private experimental wrapper supports CPUHYBRID alongside CPU eye, Metal
eye and LIGHTCPU. It selects the native experimental/adjoint opt-ins in process
and records separate eye/light halt budgets. The public reader is unchanged;
this is not positive-radius production SSS deployment.

Two authored Cycles graphs place sharp/rough Subsurface Scattering beneath a
closed sharp Glass slab. The fixture keeps its graphs/settings unchanged across
engines and fingerprints all materials, world graph, light values, transforms
and Cycles filter settings. The closed slab preserves an exterior medium.
1280x720 comparisons use Cycles128, eye128 and hybrid eye128/light512; actual
hybrid eye work is higher because of the partition. These are quality checks,
not matched-budget timing comparisons.

`cycles-bssrdf-regional-review.py` reads raw EXRs after rendering and removes
loaded images on exit. Its predefined radius240 interior circle excludes the
white background. It records exact input hashes, means and the unchanged 3%
per-channel gate against an independent CPU eye reference. It explicitly
records production_acceptance and directly_reviewed as false; image review
must be recorded separately. Failed diagnostic outputs can be measured without
being silently promoted to acceptance.

The initial hybrid's body was 36.4%/38.0% brighter, despite far smaller whole-frame
errors. The native PSR partition fix reduces the same region's sharp/rough
errors to 0.661%/1.030%. Direct review of the four corrected Cycles/hybrid PNGs
confirms shape, orientation, warm hue and scattering meaning. Strong chromatic
grain, especially in the rough hybrid, remains a production-quality issue.

The native unit also fixes forced Metropolis acceptance and a missing return in
Metal mirror PSR sampling. Exact native fingerprints and detailed scope are in
SuperLuxCore's matching engineering note. Exact new CI-wheel checks and broader
production adapter integration remain necessary; full Cycles compatibility is
an active goal, not a result of these private fixtures.

## Exact CI wheel, images and installed common core

Native code commit `ce7195b66ddf828353f13186b44e4086cff5417c` passes all four
platform wheels, CUDA NVRTC, attestations and rolling publication in
[the exact workflow](https://github.com/claudianus/SuperLuxCore/actions/runs/38062029454).
All four public asset digests match the signed subjects and invocation.
[The rolling release](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-latest)
points to that exact native commit. ARM wheel/native SHA-256 are respectively
`814210cedebff3cbd8a9d68127de8b234685624aaf1461ca48ac0b18d98921e6` and
`aba55215c18290773b2772f75bdb5b78dee906de5d66b9675d9822c24b815a6a`.

The exact whole CI wheel passes CPU50/rough22/sharp18, Metal55, ordinary PSR3,
emission5 and MNEE7+3. Initial low-budget hybrid executions fail spectral at
3.1359% and rough PSR at3.0113%; neither is accepted. The declared higher-budget
spectral diagnostic passes three independent seeds at0.5965%/0.4764%/0.8172%.
The permanent native driver now uses eye65536/light81920 for every paired
condition, keeps the3% gate and adds three independent seeds for both spectral
and rough-PSR transport. Its complete CPU50/hybrid23 verification passes, maximum raw-channel mean
error1.7592%, inside the unchanged3% gate.
No rendering defaults or native implementation changed for this fixture revision.

All12 original-resolution PNGs from six CI720p comparison sets were directly
reviewed. Shape, orientation and warm scattering meaning agree. The hybrid
retains strong chromatic grain, especially rough SSS, and is not production
convergence acceptance. The predefined body region gives hybrid sharp/rough
errors0.5103%/1.2076% and Metal-eye errors0.3216%/0.1043% versus independent CPU
eye. Material/world/light graph fingerprints remain equal across engines.

The common core is installed in the actual Blender5.2 profile; complete payload
and cached wheel bytes match the signed CI wheel. The old production adapter's
266 runtime Python files are preserved, including Cycles reader SHA-256
`7dd35540ac9a1fcffdbd4b1aeb2684957f51164e799a30b93cc6d271fcb6a235`.
This is rolling core2.11.27, not a new stable artist ZIP or a production SSS
adapter switch. Actual installed PSR3 passes (maximum1.2796%). Production-preview
and actual installed CPU/Metal spectral128spp720p images, four PNGs total, were
directly reviewed. Diffuse colors, metal/glass highlights, silhouettes and floor
shadows agree; denoiser-off noise remains. Fresh processes load the new native
fingerprint; GUI hot reload is not assumed. The prior public ZIP retains the
exact rollback wheel. Positive-radius production SSS remains an open defect.

A separate actual-Release startup diagnostic still has23.86% cumulative error
at32million samples even though its last4million window has1.15% error and its
uniform normalizer is about1.46% high. It preserves the initial contribution
problem as failed evidence. This is separate from the repaired rejection rule.

Raw/failed outputs, frozen sources, whole wheels, PNG/EXR, publication signatures
and installed-runtime proof are in workspace
`test-scenes/validation-2026-10-11/cycles-bssrdf-hybrid-transport/`.
Completed temporary executables and profiles are removed. Full compatibility,
production SSS and convergence remain active work.
