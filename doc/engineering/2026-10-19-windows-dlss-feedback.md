# Windows fix1 rendered viewport: DLSS fallback and continued crash feedback

User confirmation: the affected package is **fix1**, and the DLSS complaint is
about the **rendered viewport**. Windows 10 / Blender 5.2.2 LTS / RTX 5070 Ti;
normal launch crashes ending a session, while `-d` and CPU Image Pipeline were
previously reported to avoid it. No matching crash stack is available.

## Status and scope

The actual Windows RTX viewport crash remains **open**. Do not call the prior
fix1 successful for this tester, or claim these local fixes certify that crash.
New Phase79 feature work is frozen and its unaccepted prototype is preserved.
No new Windows binary/release, default Blender change, commit or push occurred.

The exact public fix1 ZIP was inspected locally (SHA256
`46d389b56c61af180b3227cf493c939160cbeef5f268d0d5811e7f564888b373`). Its
native pyd is `51ad3eddc658e982a1744e6878d73742c3c1b01f4fbcdf91eb13396f08de82d0`.
The nested wheel contains both `superluxcore_dlss.dll` and
`dlss-runtime/nvngx_dlssd.dll`; this complete ZIP needs no extra SDK download.
Blank locators auto-discover these files. File presence/ABI is not successful
NGX execution. Current candidate RTX/NGX executions: **0**.

## Confirmed defects and bounded source fixes

1. **Shipped viewport fallback bypasses OIDN.** Choosing DLSS routes both
   interactive and paused display away from OIDN even when no DLSS result has
   been produced, so the ordinary noisy film remains visible. Fix: only an
   accepted result for the current session owns DLSS presentation; otherwise
   use the existing OIDN settings/readiness gates and display `OIDN fallback`.
   Normal active DLSS, OIDN, OptiX and disabled-denoiser cases are preserved.
   Labels explicitly identify experimental support and OIDN fallback.
   The tester's underlying NGX/guide rejection reason is still unknown.
2. **Independent native async execution abort.** `ExecuteImagePipelineThreadImpl`
   let any driver/plugin exception leave its native thread. Real host-method
   runtime/unknown failure injection aborted the old process. Capture the
   exception, publish completion, join and deliver it once to polling/Wait
   callers; cleanup joins retain no throwing failure. Starting a new worker
   retires the previous one and reports unobserved failure. Context pop now
   also occurs after execution failure. This is an independently confirmed
   F12 async/shared execution defect, **not an identified root cause of the
   tester's viewport shutdown**.
3. **F12 false success / empty Combined after denoise error.** The old handler
   assigned successful SPP before executing, caught an error, said `Denoiser
   Done`, and could replace Combined with an empty DENOISED pass. The new
   handler reports/persists the failure, keeps actual noisy Combined, fills
   DENOISED from that raw result and leaves failed SPP uncommitted for retry.
   This is additional failure-path hardening, separate from the reported UI.

Sampling, kernels, materials, AOV transport, and DLSS models were not changed
by this feedback patch. `source-preservation.json` proves reversing only the
owned delta restores the exact pre-existing file bytes. Five native execution
method bodies match primary, private macOS and frozen Windows-source candidates.

## Validation

- ASan/UBSan production-method harness: async 3 cases; context restore 5 cases.
  Old code aborts on injected failures; new code passes. Frozen fix1 Windows
  source plus the narrow patch passes the same host tests on macOS; this is
  not a Windows binary/device test.
- Real viewport presentation branches: 10 cases, including active DLSS owner,
  missing DLSS owner, OIDN, OptiX and disabled, during rendering and pause.
  The exact shipped adapter misses OIDN in 2/10; patched code passes 10/10.
- Existing checks pass: CUDA teardown11, Film teardown6, producer config2,
  OIDN readiness6, final cleanup4 and viewport visual12.
- Real native macOS CPU/Metal Film: four invalid OIDN filter errors through
  polling and Wait. Caller survives, receives the error once, recovers a normal
  pipeline and retains bit-identical raw RGB.
- Stock Blender 5.2.2 GUI without `-d`: five F12 cases (CPU/Metal OIDN fallback,
  Metal invalid-filter error, recovery, cancel), all finished with workers
  drained. The invalid-filter case preserves a nonblack noisy Combined and
  reports failure rather than success. Four actual rendered-viewport cases
  (CPU/Metal, interactive/paused) upload finite nonblack OIDN output and drain.
- F12 error/recovery EXRs and ACES2 PNGs inspected: cube orientation preserved,
  raw face noise remains on failure, successful OIDN smooths it. Unobscured
  paused Metal viewport inspected; edges remain coarse and low-SPP surfaces
  patchy. These are functional checks, not DLSS or final quality acceptance.

The macOS diagnostic native is a preserved Phase71–79 private checkout plus
this delta. It is **not** equivalent to the shipped Windows renderer. Built SO
SHA256 `3848f799941db5d590d44f55ab27339e6e828a6ec9f44703f875ebae5a0add1e`,
installed SO `5625b5295cacd0efe3945b30568e2dd9b1481f7926e132558fcb239dc16da710`,
original wheel `3884fdb7e486fb333a36e71a1e1763c3f0532dc1cf9ee2b71e5c4bd460d71fd7`.
Kernel archive remains
`bde5885b2901d408e7d723933d0d5569e06dbcf060145bf54b1371c41409de40`.

Retained failed checks: initial supervisor ps permission failure occurred
before build start; escalated bounded build passed. First viewport harness
uploaded OIDN but then accessed removed StructRNA during cleanup; it is marked
failed and retained. Capturing worker/framebuffer before teardown fixed the
harness; all four cases then passed. Initial screenshots had a startup splash;
a later unoccluded Metal capture was used for visual inspection.

## Remaining crash investigation and tester burden

Normal session-worker shutdown requests and joins the DLSS consumer before
session Stop. Consumer join timeout followed by Stop and device-error cleanup
exceptions remain potential risks, without a matching reproduction. They were
not rewritten speculatively. The captured async exception is not blanket
immunity to driver faults, access violations or throwing GPU destructors.
NVIDIA documents that context operations can also report prior asynchronous
errors: https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__CTX.html

The local `SuperLuxCore-Windows-normal-start-logs.zip` is a **logging aid**,
not a fixed renderer. Extract it and drag the installed `blender.exe` onto its
CMD file, then reproduce just the reported action once. It uses no `-d` flag;
records version/native identity, selected routes, viewport DLSS status changes,
stdout/stderr and Python fault log; changes no scene/render settings and uploads
nothing. Its Python observer is syntax/host tested. The Windows CMD launch is
not Windows-tested. Logging/redirection may affect timing or console behaviour,
so survival under this launcher does not clear the double-click crash.

Until matching evidence is available, CPU Image Pipeline plus OIDN is the
reported safe workaround; physical GPU tracing is a separate setting. Do not
advertise successful DLSS solely because the enum is selected. The intended
feature is CUDA Ray Reconstruction of independent noisy inputs, not frame
generation. A successful result requires a compatible backend/runtime/device,
valid guides and accepted presentation output.

## Evidence and cleanup

Workspace evidence: `dev-tools/reviews/2026-10-19/windows-dlss-feedback/`:
`report.json`, `baseline.json`, `source-preservation.json`, narrow patches,
`shipped-runtime-presence.json`, native/GUI receipts and results, EXR/PNGs,
failed harness evidence and diagnostic observer regression.

All10 supervised children were reaped; final read-only process audit found no
live Blender or owned receipt PIDs. Eight consumed own isolated profiles were
removed: 2,453,582,615 logical bytes. Original wheels, source snapshots, ZIPs,
images and logs remain. The current profile is retired, reinstall from its
original wheel if needed. User's Blender installation, original scenes and
unrelated WIP remain preserved.
