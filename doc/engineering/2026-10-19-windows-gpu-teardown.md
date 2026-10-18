# Windows GPU Image Pipeline teardown hotfix candidate

Based on the shipped 2026-10-19 Windows DLSS experimental source, with only
CUDA/Film teardown lifetime fixes. Renderer sampling, materials, reconstruction,
GPU selection, and DLSS runtime are unchanged. This addresses independently
reproduced host context ownership defects; the tester's Windows 10 / RTX 5070 Ti
normal-launch crash has no stack and still needs a real hardware retest.

The CUDA device drains work, destroys OptiX and unloads modules under its owning
context, restores the caller context, and reports cleanup failures without
throwing from its destructor. Film replacement joins the async pipeline worker
and destroys GPU plugins under the film context. Completed workers are joined.

The separate distribution version prevents reuse of the previous native wheel.
GPU-less Windows CI is build/install/CPU fallback acceptance only, not RTX or
DLSS image-quality acceptance. The complete ZIP includes DLSS helper/runtime;
blank backend/runtime locators auto-discover the bundled files. NVIDIA display
driver and supported RTX hardware are required for actual reconstruction.
