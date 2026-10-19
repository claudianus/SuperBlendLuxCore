# Windows DLSS stability fix2 candidate

Based on the published fix1. Contains only GPU Image Pipeline / OpenCL / DLSS
cleanup failure containment, ownership retirement and denoising fallback/status
fixes. No new render estimator, material, guide, quality or performance feature.
Private Phase71-79 renderer WIP is excluded. Primary checkout/index are preserved.

User reported fix1 normal-launch rendered viewport crashes on Windows 10 with
RTX 5070 Ti, and missing denoising when selecting DLSS. Source fault injection
reproduces unsafe cleanup and fallback bugs; it is not the tester's crash stack.
Until real Windows RTX reproduction/retest passes, the crash is not certified
resolved and actual DLSS reconstruction/quality/performance remain unverified.

DLSS requires the CUDA backend. On unsupported/unavailable DLSS, viewport OIDN
continues unless a current DLSS result owns the display. Backend is not silently
changed. The complete package includes helper and runtime; no SDK install is
needed. Image Pipeline Device is independent of render-device selection.

Cleanup consumes host owners despite driver errors, avoids wrong-context frees,
and reports errors after stable Film replacement ownership. A cleanup-failed
device/session must be retired. DLSS helper cleanup failure disables further NGX
use until Blender restart. Native memory whose driver release fails cannot be
certified reclaimed; no actual driver-loss recovery is claimed.

GPU-less Windows CI verifies source compilation, packaging/install/CPU fallback
and mock-driver teardown including GUI-subsystem CRT stdio without a console.
It cannot certify NVIDIA GPU execution or the reported normal-start crash.
