# Windows fix1 OpenCL cleanup follow-up

The user confirms **fix1 / rendered viewport**. This continues the stability
priority from `2026-10-19-windows-dlss-feedback.md`; Phase79 feature work remains
frozen. The prior turn made progress through reproduced fallback/error fixes.

The actual shipped Windows default GPU Backend is **OPENCL**, while DLSS
configuration explicitly requires **CUDA**. The tester's actual preference is
unknown; do not infer it from RTX hardware. The DLSS viewport panel now exposes
the existing GPU Backend choice inline and explains non-CUDA unavailability.
No backend is changed automatically and no default/render math is changed.
Actual production-panel branch tests pass5, including OIDN/OptiX controls and
unchanged preference values. Frozen fix1 preference source is retained.

OpenCL kernel, program, buffer and device destructors used CHECK_OCL_ERROR,
which throws on a failed C API return code. In a noexcept destructor that aborts
the host. Actual production-method ASan/UBSan harness: normal control passes,
five release error injections abort before the patch; all6 pass after it. The
patch reports errors and still attempts remaining releases, including context
release after queue-release failure. It does not guarantee that a failed driver
release really freed a GPU object. The same four bodies match primary/private
and frozen Windows-source candidates. No Windows device execution is claimed.

Only `include/luxrays/devices/ocldevice.h`,
`src/luxrays/devices/ocldevice.cpp` and the viewport panel changed in this follow-up.
Reversing the owned delta restores their exact earlier bytes. Combined source
patches also include the prior bounded fallback/async error fixes over frozen
Windows fix1. They exclude unrelated source WIP and are **not a built fix2**.

Private Release build passed141.29s, peak observed RSS1,996,652,544B. Complete
SO/wheel/adapter synchronization used an isolated profile. Built SO SHA256
`c8d853adc1967887bf3cc02cc895118614811a0507055e63a1c65f9976dcc63e`,
installed SO `67cf0ea17aa306df2c2d9886a556844cbb71a4e4f2458f2d55fefb8c14900451`,
original wheel `aea10b7bf606268dd1854089e9ec5d1d7f37de33e91a214237a9ad243bfc874b`.
Kernel archive stays
`bde5885b2901d408e7d723933d0d5569e06dbcf060145bf54b1371c41409de40`.
This macOS diagnostic native includes preserved Phase71–79 private work; it is
not equivalent to the shipped Windows build or RTX acceptance.

Actual macOS image-pipeline lifecycle checks pass12 sessions: CPU6 controls,
required OpenCL GPU3 and Metal GPU3. Each exercises worker execution, replacement,
explicit deletion, recreation, caller-thread session destruction and bit-exact
raw RGB preservation. Existing producer2, viewport presentation10 and Film
teardown6 regressions pass. No hardware-plugin fallback was silently accepted.

Stock Blender5.2.2 GUI (no `-d`, not background), GPU Backend OPENCL and GPU Image
Pipeline device0: **cold first viewport run fails** its unchanged90-second
functional deadline. Warm-up PATHOCL12s, RTPATHOCL61s and actual-scene preparation
16s occupied the allowance before a first OIDN result. The failure/result/log and
receipt remain. This is an unresolved startup issue, not a passing performance
measurement. The same interactive/paused cases then pass with prepared cache,
with actual finite/nonblack OIDN uploads and worker drain. Deadline was not
increased and no cold-to-warm speed ratio was made. The actual upload screenshot
was inspected: cube orientation is correct, but low-SPP smear/spots and coarse
edges remain. No full visual quality acceptance or NGX evaluation (current0).

**A further confirmed failure remains:** actual Film destructor/DeleteImagePipeline/
Wait methods abort when context push, FinishQueue or pop throw. The remaining
probe records control pass1 / abort3. This is independently reproduced with a
simulated driver; it is not yet a matching Windows RTX crash root cause. Simply
catching outside delete is insufficient because plugin destruction is noexcept
and partially deleted pointer ownership can be lost. Next local work is a bounded
exception-safe cleanup design with no leaks/double deletion/wrong-context use,
using this probe before adopting changes. FreeBuffer/GetSize and driver faults
remain relevant; do not call the current candidate crash-free.

Console-less Windows stdio can report descriptor-2, per
[Microsoft _fileno](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/fileno?view=msvc-170).
Console redirection may alter timing/availability. This is a diagnostic caveat,
not an identified cause of the user's `-d` difference.

Evidence: workspace `dev-tools/reviews/2026-10-19/windows-opencl-followup/`:
`report.json`, `backend-default-evidence.json`, ASan/UBSan baseline/fixed results,
native/GUI results and receipts, preserved cold failure, source preservation,
combined Windows source candidates and `remaining-film-cleanup-failures.json`.
No commit/push/release/default install change occurred.

Final inclusive receipt audit covers8 current supervised children and12 prior
ones, all reaped/PIDs absent, no live Blender. This corrects earlier filename
suffix enumeration that omitted archived receipts; no test outcomes were changed.
Short subsequent host probe children were waited/reaped by subprocess.run and
compiler temp files removed. Consumed isolated profile306,700,450 logical bytes
removed. Original wheel, source snapshots, images/logs/JSON remain. Original scenes
and unrelated WIP are preserved. Full goal remains active and unachieved.
