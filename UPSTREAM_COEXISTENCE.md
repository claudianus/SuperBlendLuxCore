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

Repro pipeline: `tools/upstream_coexistence/build.sh` (clone pinned upstream
-> `transform_upstream.py` tokenizer-based rename -> `post_patch.sh` ->
wheel bundling -> zip). See `tools/upstream_coexistence/README.md`.

## Installed extension is a generated artifact — do not overwrite

`~/Library/Application Support/Blender/5.2/extensions/user_default/blendluxcore_up`
contains *transformed* upstream sources, not this repo's sources. Syncing
this repo's add-on sources into it (e.g. `EXT_ID=blendluxcore_up
dev-tools/sync_dev_install.sh`, or any manual rsync/cp) destroys the
coexistence setup: both extensions then try to register engine id
`LUXCORE`, node categories `LUXCORE_*`, and the same `pyluxcore` module —
registration fails with `KeyError: Node categories list
'LUXCORE_MATERIAL_TREE' already registered` and the engine list shows
`LUXCORE` twice. This happened once (another agent deployed repo sources
over `blendluxcore_up`); fix was restoring from the build staging.

Prevention:

- `dev-tools/sync_dev_install.sh` aborts when the target extension's
  `blender_manifest.toml` `id` differs from this repo's `id`
  (`blendluxcore`) — do not bypass that check.
- The installed `blendluxcore_up/` contains `GENERATED_DO_NOT_OVERWRITE.txt`
  (emitted by `post_patch.sh` step 9). If that file is missing, the
  directory has been overwritten — rebuild via `build.sh --install`.
- To update the upstream extension, always rebuild with
  `tools/upstream_coexistence/build.sh --install`; never edit the
  installed files directly (edit `post_patch.sh`/`transform_upstream.py`
  instead so the change survives rebuilds).
