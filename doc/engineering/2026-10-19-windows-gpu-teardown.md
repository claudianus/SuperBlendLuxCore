# Windows GPU Image Pipeline session retirement fix candidate

The report is from Windows 10, Blender 5.2.2 LTS, RTX 5070 Ti / Threadripper 1950X: normal launch crashes at render-session exit, `-d` launch does not, and CPU Image Pipeline avoids it. No crash log is available. The exact hardware incident remains unconfirmed; this work fixes independently reproduced native lifetime defects.

## Confirmed source defects and correction

`CUDADevice::~CUDADevice()` previously pushed its context only for OptiX destruction, popped it, then unloaded CUDA modules using whichever context belonged to the caller. The film can first initialize its GPU context on the async pipeline worker, so the teardown caller need not own it. `cuModuleUnload` operates on the current context; a checked CUDA error thrown from this destructor terminates the process. The fix binds the owning context through queue synchronization, OptiX destruction and all module unloads, restores the caller context and reports cleanup errors without throwing from the CUDA destructor.

Film pipeline setters previously deleted GPU plugins without selecting the film hardware context or retiring an active async pipeline. They now join active or completed workers, finish queued GPU work and delete resources under their owning film device. The same helper covers final Film destruction and dynamic-settings pipeline replacement.

NVIDIA references: [context management](https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__CTX.html), [module management](https://docs.nvidia.com/cuda/cuda-driver-api/cuda_driver_api/group__CUDA__MODULE.html).

## Bounded validation

- Extracted production methods with deterministic context-stack/driver and owning-plugin fixtures: baseline failed expected conditions; candidate passed 11 CUDA teardown conditions and 6 Film retirement conditions. This is host lifetime proof, not GPU driver certification.
- Actual local native: Two matrices (24 CPU controls, 12 Metal and 12 explicitly selected OpenCL Image Pipeline lifecycle sessions) completed; raw RGB stayed bit-exact through pipeline replacement and deletion. Each GPU matrix has 12 matching provider-initialization messages and no hardware-plugin CPU fallback. Fifteen pybind accessor ownership cases passed.
- Stock Blender 5.2.2 normal GUI (`background=false`, `debug=false`): CPU/Metal/Metal/CPU four full renders ended cleanly. A separate CPU Stop request, Metal Stop request, then completed Metal rerender passed with no owned workers remaining. Synthetic Esc input failed to produce a cancel within its 30-second subcase limit and is not accepted as an Esc test. That run was terminated and both own PIDs were confirmed absent; it has a separate manual cleanup record, not a forged supervisor receipt.
- Four generated raw EXRs were finite. CPU/Metal ACES2 previews were directly inspected: matching upright grey-blue cube. This low-SPP fixture is lifecycle smoke only.
- Local native kernel archive is unchanged (`bde5885b...09de40`); Windows candidate changes only four native lifetime files relative to the public Phase70 snapshot. Estimator, material, quality, GPU-selection and DLSS runtime sources are unchanged.

Release candidate native source: `5469737765d78c7604732d36cba9488bdc9c4b42`; adapter `a4819ba6ac76c25139c0be8e11c80ef8b481e3df`; distribution `2.11.34+dlss.exp20261019.fix1`. Windows CI: https://github.com/claudianus/SuperLuxCore/actions/runs/39175695533 (GPU-less, current status recorded in the workspace report).

The local validation native is a separate Phase72-plus-teardown build, not the Windows release binary. Seven production method bodies were compared byte-for-byte across local private, primary WIP and frozen Windows source. The existing WIP in the four modified native files was verified exactly by reversing only our patch in a temporary Git index. Default Blender was not modified. All primary checkout heads and staging were left alone; narrow release branches carry the public candidate sources.

## Remaining acceptance and evidence

Actual Windows 10 / RTX 5070 Ti normal-launch completion, cancellation and repeated-session retest is required before declaring the reported crash resolved. Windows CI has no RTX GPU; it verifies Release build/import, kernel compilation, whole-ZIP upgrade/install and CPU fallback, not actual NGX or reconstruction quality/performance. The existing Linux package and stable Latest are separate and preserved.

Workspace evidence: `dev-tools/reviews/2026-10-19/windows-gpu-teardown/report.json`, source/method identity and preservation JSON, before/after regression JSON, local native/GUI receipts, visual review, Windows CI and publication receipts. The diagnostic `windows-gpu-pipeline-check.py` records the current operation and native log on Windows in `%TEMP%/SuperLuxCore-GPU-pipeline-fix1/`; it requires the complete fix1 package and an actual GPU of the selected backend. The tester did not specify CUDA versus OpenCL; the diagnostic records preferences and explicitly selects that backend rather than silently testing another one.


## Final Windows publication (2026-10-19)

All five required Windows CI jobs passed in run 39175695533: host teardown regression, wheel metadata/cache regression, 23/23 NVRTC kernel compiles, native Windows Release build/import/CPU smoke, and whole-ZIP upgrade/install plus stock Blender 5.2.2 CPU fallback. The previous experimental native `82723a...9fcc` was actually replaced by `51ad3eddc658e982a1744e6878d73742c3c1b01f4fbcdf91eb13396f08de82d0`; the staged ZIP native matched the raw tested wheel byte-for-byte. Bundled DLL/helper/RECORD/NVRTC identities were verified.

The fix1 experimental candidate is published at https://github.com/claudianus/SuperBlendLuxCore/releases/tag/experimental-windows-dlss-20261019-fix1 . Full ZIP is 199,279,789 bytes, SHA256 `46d389b56c61af180b3227cf493c939160cbeef5f268d0d5811e7f564888b373`; anonymous download HEAD is HTTP 200 with exact length. All five release asset digests match. Stable Latest remains v2.11.34. All eight preexisting Windows/Linux release asset IDs, sizes and digests are preserved; the old release body links the fix candidate with the actual-RTX-retest limitation.

The Windows CPU fallback EXR was downloaded, reopened and directly reviewed through ACES2. It is an upright nonblack default-scene cube and remains a smoke, not RTX/NGX acceptance. A premature zero-image observation is preserved separately and was not accepted; the final visual harness requires exactly one source EXR after download completion.

The separate `windows-gpu-pipeline-check.py` release asset records the chosen CUDA/OpenCL backend and per-step progress/native log under the Windows temporary directory. The user should install the whole fix1 ZIP with the old extension disabled, restart Blender, and retest normal launch / GPU Image Pipeline / render end and cancellation. Actual Windows 10 / RTX 5070 Ti acceptance is still pending. Local kernel tracing, quality settings and original .blend assets were not modified by this teardown change.
