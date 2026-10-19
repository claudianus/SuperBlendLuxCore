# DLSS stability fix3 experimental package

No feature expansion. Windows reuses the exact accepted fix2 renderer native module after source-equivalence verification; Linux rebuilds native cleanup changes. Both include the exact init/frame-transaction helper accepted at f3449d59676ebdf8fe1e3064e9d92ae36595eee6 in CI 39202645597. ABI remains 1. Addon Python source is byte-identical to fix2. Whole ZIP upgrade gates use stock Blender 5.2.2 LTS and isolated profiles.

DLSS unavailable in rendered viewport falls back to OIDN. DLSS requires the CUDA rendering backend and a supported NVIDIA RTX driver; the OpenCL setting alone does not enable DLSS. Official helper/runtime are bundled in the renderer wheel; blank locator fields use automatic discovery. Install the complete extension ZIP and restart Blender; do not replace individual libraries.

CPU fallback and mocked error-path regression are limited evidence. No actual RTX normal-launch viewport/crash, NGX frame, quality, animation or performance acceptance is claimed. The Windows tester report has no crash stack. Stable Latest, previous experiments and unrelated WIP are preserved. Unaccepted Phase71-79 implementation is excluded.
