# Upstream BlendLuxCore coexistence (SuperLuxCore ↔ upstream comparison setup)

Goal: Blender 5.2 LTS shows **two** render engines at once —
`LUXCORE` ("SuperLuxCore", this repo's build) and `LUXCOREUP`
("LuxCoreRender Upstream", repacked upstream BlendLuxCore 2.11.1 +
pyluxcore wheel 2.11.2).

## Key finding: two pyluxcore builds cannot share one process

Loading both `pyluxcore*.so` images into one Blender process corrupts both
engines (`EXC_BAD_ACCESS / EXC_ARM_DA_ALIGN` inside `slg::Scene::Preprocess`,
reported as `BLI_mmap: Unhandled SIGBUS` -> abort).

Evidence: a scene serialized via `Scene.Save()` on the *upstream* object in a
dual-loaded session was written in the **fork's** serialization format —
dyld weak-symbol coalescing resolves identical `slg::*`/`luxrays::*` weak
symbols (template instantiations, vtables) to the first-loaded image, so the
second binary silently executes the other build's code. Not fixable without
rebuilding one binary with symbol hiding/prefixing. Bundled dylibs
(tbb 12.18 vs 12.19, embree4.4, OIDN 2.5.0/2.5.1) all have distinct install
names, so that is not the mechanism; interpose sections are absent.

## Architecture

- Upstream addon `blendluxcore_up` is installed alongside `blendluxcore`.
  Python-level names are fully namespaced (`pyluxcore_upstream`,
  `scene.luxcore_up`, `luxcore_up.*` operators, `luxcore_up_*` node trees,
  `LuxCoreUp*` classes, engine id `LUXCOREUP`).
- `luxloader.ensure_pyluxcore()` registers a **stub module** in the main
  process (`LUXCORE_UP_WORKER=1` unset). The native .so is never loaded, so
  the fork's pyluxcore is unaffected.
- Final render (`engine/base.py::_render_subprocess`): saves a copy of the
  scene (`bpy.ops.wm.save_as_mainfile(copy=True)` works inside render), then
  spawns `Blender --factory-startup -b scene.blend --python render_worker.py`
  with `LUXCORE_UP_WORKER=1`. The worker enables only `blendluxcore_up`,
  renders, writes EXR; the main process fills the `Combined` pass of the
  RenderResult (`pass.rect.foreach_set`). Esc kills the worker.
- Viewport render and material previews are disabled for the upstream
  engine in shell mode (they would need the native module in-process).
- AOVs other than Combined are not forwarded yet (empty passes).

Repro pipeline: `/tmp/transform_upstream.py` (tokenizer-based rename) +
`/tmp/post_patch.sh`; package staging: `/tmp/blc_up_pkg/blendluxcore_up_new`.
