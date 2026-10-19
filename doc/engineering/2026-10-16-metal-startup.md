# Metal session startup and real-scene viewport validation

The worker no longer calls generic `KernelCacheFill()` when the selected device
is `METAL_GPU`, including default automatic selection. Automatic detection
mirrors the core's GPU-use gate and CUDA precedence; Vulkan remains explicit-only.
The real-scene test initially exposed that an empty selection string still
triggered two filler scenes; that exact previous worker fingerprint is retained
with a failing automatic-selection regression. The filler prepares unrelated matte scenes
for both PATHOCL and RTPATHOCL, and does not copy the actual spectral/options
configuration. `RenderSession.Start()` already runs on this worker and prepares
the exact scene program. This change removes that redundant preparation without
moving any native compilation onto Blender's main thread. OpenCL and Vulkan
retain their existing fill policies.

The core change selects optional ReSTIR visibility/GI/PT PSOs using the same
conditions as their existing dispatch paths. Enabled features remain available;
no material, estimator, texture, sampling or default denoising setting changes.
See the core engineering note `2026-10-16-metal-startup.md` for per-stage evidence
and the limits of the namespaced PSO-set ABBA diagnostic.

## Regression and real UI probe

`review_metal_prefill_test.py` checks the actual worker function with selected
Metal/OpenCL/Vulkan devices. Existing async-worker, lifecycle and viewport
visual regression suites continue to cover the earlier fixes.

`review_heavy_viewport_test.py` opens the original
`/Users/modumaru/Downloads/thejunkshopsplashscreen.blend` in stock Blender and
records actual view_draw calls, timer gaps, worker mutation generations and
framebuffer uploads. It performs 30 view rotations and 14 real region-size
changes by splitting/joining an adjacent non-rendered area. It retains a full
window screenshot and the final film statistics. Split/join is used because
`screen.area_move` has a mouse-over-edge poll requirement that is unsuitable for
a timer-driven probe. `review_area_resize_test.py` independently confirms that
the actual area width changes and returns to its initial value.

The source scene contains 63 objects, 38 materials, 148 images, 456,770 source
polygons and 776,011,776 source texels. The probe does not reduce the source
geometry/textures or change quality settings. Existing viewport mip selection
and interaction scaling remain active and must not be described as full-quality
final rendering. Export/startup time is separate from orbit/resize statistics.

## Large-frame and consecutive-resize fixes

The completed readback already owns a fresh float array and no worker mutates
it after publishing. The framebuffer now retains a shaped view of that array
instead of making another full copy on the UI thread (~140 MB for the measured
4K RGBA frame). The GPU upload and pixel values are unchanged. A weak-reference
regression verifies that consuming the worker result retains the array owner
and exact pixel values without a duplicate backing store.

A replacement framebuffer also retains its resampled held image. Previously a
second resize before a new film arrived found `_last_pixels=None`, discarded
the held image and displayed the empty initial buffer. The consecutive-resize
regression fails before the change and passes after it. The viewport source
suite now has ten passing checks.

The full Junk Shop probe exposed another UI wait: native `GetWidth()` and
`GetHeight()` acquire `filmMutex`. In the otherwise asynchronous draw path,
these getters waited behind GPU draining/OIDN and produced a 2.114 s draw.
Framebuffer construction now uses Blender dimensions. The background readback
supplies exact live film dimensions to `_accept_pixels()`, which already
rebuilds the texture as needed; `draw()` reanchors the quad to the current
region. Size changes no longer discard pending readbacks or query a native
film lock from construction/replacement checks. A regression makes any such
native UI access raise, while verifying live-size acceptance.

## Resize routing and target-size correctness

The worker snapshots complete exported config properties. For selected Metal
RTPATHOCL sessions, dimension-only changes and duplicate identical configs use
the core's existing film-edit `Parse` path. The same session and acceleration
structures remain alive, a paused session resumes, and the mutation generation
is advanced for the framebuffer. Any imagepipeline, sampler/preview policy,
halt, subregion, engine or other setting change keeps the complete restart.
CPU and GPU configurations without selected Metal also keep the restart.

The broader CPU reuse candidate was conservatively rejected after nonfinite
pixels appeared in Junk Shop. Later complete-restart CPU runs also reproduced
the problem, so film reuse was not established as its cause. Paused diagnostics
showed finite raw RGB, albedo and normals while both cached and freshly executed
viewport pipelines had NaNs. A deterministic test executing the actual smoothing
body reproduced the overflow with finite signed spectral RGB: the previous
color-edge denominator `1.25 * (lC + 0.1)` becomes negative, changes the sign of
the exponential, and produces infinity followed by `inf/inf`. The display filter
now uses `1.25 * (abs(lC) + 0.1)`. It keeps signed radiance intact and keeps the
old arithmetic for nonnegative center luminance. The regression checks signed,
zero-scale-boundary and HDR inputs, bit-exact ordinary/converged output, and
untouched raw accumulation. No NaN scrubbing or RGB clamping was introduced.
CPU continues to use the conservative full-restart route in this change.

The stricter intermediate-size probe exposed a separate existing bug:
`last_viewport_size` was only initialized during startup. After a live resize,
interaction-scale restoration could therefore resize the film back to the old
window dimensions. Both UI config-submission paths now record the current
Blender film dimensions before enqueueing the complete config. A source-method
regression fails before the fix and verifies that scale restoration uses the
new dimensions in both UI paths.

The real probe performs 30 orbit actions and 14 split/join resize actions.
Twelve exercise the dimension-only route; two larger changes exercise the
sampling-policy boundary. The last two sizes are held until their actual
current-generation films arrive. Intermediate/final films must be finite,
the settled film must match the final viewport dimensions, and no session
restart may still be in flight at capture. The final native workers are drained
before Blender quits. Generation-upload latency is a proxy, not a compositor
presentation measurement.

`run_review_metal_startup_blender.py` bounds each child, checks resource admission,
records peak Blender RSS, and invalidates performance eligibility on observed
external render/indexer contention. A failed resize harness or contended run is
not a passed responsiveness measurement. Each child is reaped and its temporary
textures and recovery files are removed. The isolated profile and duplicate
wheel can be removed once validation completes; evidence is retained in the
workspace `dev-tools/reviews/2026-10-16/metal-startup/` and
`test-scenes/validation-2026-10-16/metal-startup/`.

The user's later instruction explicitly permits parallel rendering. Shared
correctness runs use `SLC_ALLOW_SHARED_VALIDATION=1`, retain process/RSS/deadline
receipts, and are **always** ineligible for performance comparisons. Only this
mode allows up to 30 seconds for a current-size checkpoint; the exclusive
four-second observation remains unchanged. RAM/time limits and process-query
failure handling remain in force. Other tasks and their processes are untouched.

## Final validation receipts

Current receipts and complete source/native/translator identities are recorded
in the workspace `metal-startup-report.json` and `candidate-identity.json`.
Validation includes actual optional Metal handlers, CPU/Metal Junk Shop orbit
and resize, CPU/Metal 720p GPU-texture checks and CPU/Metal 720p spectral ACES2
final PNG/raw EXR outputs. Failed numeric and harness attempts remain retained.

The first screenshot harness suppressed drawing during its finishing stage,
so Blender's screenshot redraw captured an empty checkerboard despite valid
pixel statistics. The harness now draws the held framebuffer while finishing;
that keeps the actual image visible without launching native reads or denoising.
Only actual captured scene images count as visual evidence.

An earlier forced quit while Start was still in flight produced an OpenMP join
crash. The bounded harness now drains read, OIDN and session workers before
quitting; successful normal exits cover that orderly test path. Arbitrary
product quit during a cold compile remains outside this probe's coverage.

Every authorized shared run is ineligible for performance comparisons.
The namespaced same-MSL ABBA result is a separate limited diagnostic; no claim
is made that historical 157-second cold startup became 23 seconds. Full-frame
read, pipeline processing and upload delays are reported independently of short
UI draw calls. This is validation of the isolated development install, not a
release ZIP certification.

## Final candidate and measured scope

- Installed native SHA256: `927269ffad2caf49a5368441d2c414a9cd054ca1547c669c96d46e41057a8c2b`.
- Worker SHA256: `b0b3ad6ffa99347cd5a0a3263724e1a3b45c6de92831c1dd1bff9819e1ddb879`.
- Framebuffer SHA256: `888d08dae84eecfb3dfa12473ee1aaa59e73e590cb4c58e26e9d61e123146911`.
- Engine viewport SHA256: `34c24baef79a06ca4e2f784d487be8a49fdb78bc72f2049877b45d6e2872e653`.
- Translator SHA256: `8fdcc4918de6b5b3b686c1c290f37aca4cd2abf308abe1662a337b2a7d298215`.

All seven final correctness cases pass on that native candidate: optional
Metal states, heavy CPU/Metal, 720p viewport CPU/Metal and 720p final CPU/Metal.
The CPU heavy scene passed twice after the signed-RGB smoothing fix. Its paused
raw radiance still includes negative values (minimum about -9.92), while raw,
guides, cached/fresh pipelines and isolated NOP/infill/smooth/temporal chains
all contain zero nonfinite values. Each successful heavy run drained its workers
and exited normally. The final optional-device receipt records `METAL_GPU` and
zero native CPU helper devices.

| Backend | Final film | Draw p95 / max | Timer gap p95 / max | Observed orbit uploads | Observed orbit p95 | Last resize to matching full-size upload |
|---|---:|---:|---:|---:|---:|---:|
| CPU | 3815 x 2292 | 5.318 / 18.201 ms | 30.075 / 315.839 ms | 22/30 | 130.752 ms | 1.873 s |
| Metal | 4218 x 2292 | 3.907 / 36.199 ms | 35.837 / 268.735 ms | 19/30 | 147.065 ms | 3.470 s |

These are authorized shared-run observations, with performance eligibility
explicitly false. Actual viewport widths differ, so this is not a CPU-versus-
Metal speed comparison. Only the observed subset of orbit actions contributes
to generation-upload latency; rapid actions may coalesce or have no observed
upload before the next action. No compositor presentation timestamp is measured.
Both final resize checkpoints use the exact current film dimensions.

UI draw calls remain short, but full-size fresh images still take seconds.
The Metal screenshot retains the existing sparse/blocky low-sample interactive
preview. Neither screenshot establishes heavy-scene convergence or equal-error
CPU/Metal quality. Geometry, textures, bounce settings, sampling and denoiser
defaults were not reduced for this measurement.

Both final 1280 x 720, 32-SPP spectral ACES2 images and saved 32-bit raw EXRs
pass. Reopening the EXRs reproduces the live RGB means exactly; HDR maxima are
about 44.74 (CPU) and 43.34 (Metal). The largest mean-channel change from the
retained prior fixture is about 0.059%. This is a stochastic regression smoke,
not an estimator or convergence-quality bound. GPU texture upload differs from
its source by at most 0.000244141; stale denoise rejection and 30 material-preview
draws with zero replacements pass. ACES2 PNGs, reopened raw-EXR previews, updated
blue-material previews and both actual Junk Shop screenshots were inspected.

Install/wheel/dependency and actual MSL/metallib/archive fingerprints are saved
in `validated-install-fingerprints.json` and `validated-program-fingerprints.json`.
The isolated profile is removed after verification; the unique validated wheel,
original prior wheel, raw EXRs, PNGs, logs and JSON evidence are retained. The
same-thread automatic follow-up is paused. No commit, push or release was made.
