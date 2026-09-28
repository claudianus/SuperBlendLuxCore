# Cycles compatibility findings

> Engineering note for SuperBlendLuxCore — extracted from AGENTS.md.
> Feature/user-facing docs live in `doc/features/` (SuperLuxCore) or `doc/` (SuperBlendLuxCore).

## Phantom mesh lights (Cycles emission compat)

- Blender 5.x defaults Principled to Emission Strength=1.0 + black
  Emission Color. Emitting `scale(strength, color)` for that makes a
  NON-constant texture — SuperLuxCore nulls only literal constant
  zero/black emissions (`parsematerials.cpp`), so the material stayed
  `IsLightSource()` and every triangle became a mesh light (546,123
  fake lights on the ASiO scene: multi-GB task buffers + light BVH).
- Fix: `cycles_node_reader` folds/skips provably-zero emission
  (`_is_zero`, `_tex_binary` constant folding) in the Principled,
  standalone-Emission and AddShader paths — emits constant `0.0`
  instead. Linked/textured emission is untouched.
- Regression: `dev-tools/e44_black_emission_test.py` (7 cases:
  black/zero/real emission on Principled, Emission node, Add Shader).

## Cycles light/world resolution (use_cycles_settings)

`use_cycles_compat()` (utils/misc.py) decides per light/world whether
export/UI uses the Cycles translation layer or native SuperLuxCore
settings. Resolution order:

1. `use_cycles_settings` set on the RNA group (is_property_set) — the
   persisted pin written at creation, at save, or by the mode toggle.
2. `use_cycles_settings` member inside `id["superluxcore"]` /
   `id["luxcore"]` — files where the flag persisted as unregistered
   ID-prop storage (old versions, upstream).
3. Any authored LuxCore setting — legacy `luxcore` storage or
   registered `superluxcore` props — pins native. Shared props
   (`importance`, `link_groups`, `lightgroup`, `use_cycles_settings`
   itself, `rna_type`/`name`) never count as authored.
4. Untouched datablocks follow the file context: datablocks of a file
   containing a SUPERLUXCORE scene resolve native (`_file_authored_luxcore`),
   foreign-authored datablocks fall back to Cycles.

Pin lifecycle (the flag records the *authoring* engine, survives save):

- `depsgraph_update_post` → `misc.tag_new_light_world(engine)` writes
  `use_cycles_settings = (engine != SUPERLUXCORE)` on every newly
  appearing light/world — but only when the flag is still unset (an
  explicit write between creation and the tick wins; overwriting it
  regressed e23's scripted `= True` assignments → black renders).
- `refresh_file_context()` runs at register() and load_post: recomputes
  `_file_authored_luxcore` and seeds all existing session_uids as
  load-era, so loaded datablocks are never tagged as runtime-created.
  register() runs in a restricted context (no bpy.data); the first
  depsgraph tick then performs the deferred refresh.
- `save_pre` (handlers/save_pre.py) freezes the *resolved* mode into
  the flag on every untouched datablock, so reopening the file
  reproduces the same interpretation regardless of engine history
  (e.g. a Cycles file switched to SUPERLUXCORE and saved keeps its
  Cycles-authored lights on the compat path).
- UI: light/world panels carry a `SuperLuxCore | Cycles` mode toggle
  (`superluxcore.set_light_world_mode`) — the explicit escape hatch.
- Materials keep the explicit opt-in ("Use SuperLuxCore Material
  Nodes" button); `material_use_cycles_nodes` is unchanged.

The ASiO regression that motivated the fallback: a Cycles sun at
energy=1000 exported through the native path used the `sun_sky_gain`
default 2e-5 (~500x too dark). Cycles sun → `distant`/`sharpdistant`
with `gain = energy / (2π(1-cos θ))`; Cycles world with unlinked
Surface emits nothing.

Regression: `dev-tools/e45_cycles_light_defaults_test.py`,
`dev-tools/e48_datablock_mode_resolution_test.py` (pin lifecycle,
file context, save/reload roundtrip, mode toggle operator).

