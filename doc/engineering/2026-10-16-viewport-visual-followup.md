# 2026-10-16 viewport visual follow-up

This change follows the lifecycle review and prioritizes visible material-preview
instability, stale edit results and work that can block drawing. It preserves
the prior review fixes and the existing `nodes/__init__.py` working-tree change.

## Confirmed problems and changes

1. **Material preview with a transparent final film repeatedly replaces its
   framebuffer.** Construction intentionally chooses an opaque material
   preview, but replacement compared against the transparent final-film
   setting. Both paths now use `_initialize_transparency()`. A completed film
   and any in-flight readback can survive the next draw.
2. **Completed denoise results can disappear or block drawing.** The consumer
   cleared its result before a nonblocking session-lock attempt; a busy lock
   lost the result. Once acquired, the UI still performed `UpdateStats()` and a
   forced synchronous film read. The denoise worker now pumps stats, runs OIDN
   and reads an owned float array under one session-lock hold. The main thread
   only uploads that array. Normal progressive reads also pump stats on their
   readback worker; `view_draw()` no longer calls `UpdateStats()` directly.
3. **An image from before a camera/material edit can land after the edit.**
   Async raw reads and denoise results now check the current worker mutation
   counter as well as session identity. The upload rejects generations older
   than the one already shown. A denoised upload updates the shown generation,
   so an older raw result cannot replace it.

No estimator, sample budget, material model or default denoising choice changes.
Session pause and other native calls are outside the nonblocking guarantee;
this is not a claim that every `view_draw()` path has bounded latency.

## Reproduction and validation

`dev-tools/review_viewport_visual_test.py` runs actual source methods with
deterministic locks and synthetic film/GPU objects. All seven checks fail
against the retained pre-change source and pass against the changed source.
The existing lifecycle and async-worker tests cover cancellation and shutdown.

`dev-tools/run_review_viewport_blender.py` supervises sequential stock Blender
5.2.1 runs in an isolated development profile. GUI-mode tests use an actual
1280x720 CPU/Metal film, the real framebuffer constructor, async OIDN and film
readback, and an actual GPU texture drawn into an offscreen target. They retain
the edited raw/denoised EXR and PNG output, check the device, reject a deliberately
late denoise result, test upload while the session lock is busy, and compare
GPU pixels against the source film. The material-preview context is synthetic;
this is not a manual orbit/resize interaction or a latency benchmark.

The driver additionally reruns the existing 720p final-render scene with
Voronoi diffuse, coated metal and glass on CPU and Metal. Those images use
ACES 2.0, while the viewport diagnostic uses a NOP linear pipeline and Blender
Standard for saving the displayed GPU pixels. They serve different checks.

Current outcomes, attempts, source/binary fingerprints and any limitations are
recorded in the workspace `dev-tools/reviews/2026-10-16/visual-followup/`.
Rendering evidence is under `test-scenes/validation-2026-10-16/visual-followup/`.
The isolated profile and duplicate wheel are disposable after validation;
images, result JSON and logs remain. No release or user-profile installation
is implied.

## Result

All four stock-Blender cases passed: CPU and pure Metal viewport upload, plus
CPU and Metal final render. The viewport GPU/source maximum absolute delta was
0.000244141 (half-float texture quantization). Both backends kept the same
material-preview framebuffer for 30 replacement checks, rejected the old edit's
denoise, and uploaded while the session lock was deliberately busy. Statistics
refreshes for these uploads ran on the denoise/readback threads. Seven new unit
checks, four existing lifecycle cases and 25 existing async-worker checks passed.
The 720p final images were reviewed directly for orientation, material separation,
glass, highlights and contact/caustic behavior; 32-spp residual noise remains.

The new Metal diagnostic scene required 157.940 seconds of initial kernel
compilation. Compiler services were active during the wait; the bounded GUI
case completed in 169.208 seconds. This remains a startup-cost observation,
not a repaired compiler-performance issue or a measured warm-cache improvement.
The material-preview context and 30 checks are controlled harness checks, not
30 interactive user frames. Manual heavy-scene orbit/resize and UI p95 latency
remain outside this evidence.
