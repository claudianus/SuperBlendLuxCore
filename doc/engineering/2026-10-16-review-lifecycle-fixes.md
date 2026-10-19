# 2026-10-16 review: Blender lifecycle and external output

- **F03:** deferred viewport jobs are ordered incremental deltas. A new
  edit merges with the pending batch, including when the frame-hold
  deadline expires before draw flushes it. A full scene restart drops
  deltas belonging to the discarded scene.
- **F05:** settings submitted while a session is being constructed are
  queued after publish. A newer queued config/start/stop takes precedence.
- **F06:** denoiser reset cancels the result but keeps tracking an active
  worker. A lock-waiting stale job skips OIDN and another job cannot start
  until that worker exits. Blender's UI never joins it synchronously.
- **F07:** the combined/denoised beauty is selected explicitly. AOV/light
  group/noise pipelines with higher indices are not beauty candidates.
  The child writes float EXR, and Blender saves it using the snapshotted
  image/color settings. PNG 8/16, JPEG 8 and EXR half/float are covered.
  Multilayer EXR is rejected explicitly because this detached image path
  does not construct a multilayer RenderResult.
- **F08:** the polling timer keeps ownership until the child exits and
  `poll()` reaps it. Output is saved before scratch is deleted; success,
  failure and missing-output paths remove the serialized scene/AOVs.
  Failure diagnostics retain a bounded log tail in the error log/console.

## Validation

`dev-tools/review_lifecycle_unit_test.py` covers pending settings,
independent deltas, denoiser cancellation and scratch cleanup with
deterministic gates. `dev-tools/async_worker_unit_test.py` remains the
existing worker regression suite.

`dev-tools/review_blender_test.py` runs against an isolated profile made
with `dev-tools/sync_dev_install.sh`. Its modes exercise real CPU/Metal
rendering and session workers, five image format/depth combinations
against Blender's internal save, and the serialized external child.
The candidate binary and deployed translator are hash-checked before the
test. Raw EXR and ACES 2.0 PNG images are retained with the workspace fix
report; stale profile/install scratch can be removed after verification.

The user's existing `nodes/__init__.py` change is outside this fix and is
preserved byte for byte. No release version bump or public deployment is
implied by these development artifacts.
