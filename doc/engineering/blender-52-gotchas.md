# Blender 5.2 RNA/API gotchas

> Engineering note for SuperBlendLuxCore — extracted from AGENTS.md.
> Feature/user-facing docs live in `doc/features/` (SuperLuxCore) or `doc/` (SuperBlendLuxCore).

## Blender 5.2 RNA/API gotchas

- `CurveMap` lost `.evaluate()` — call
  `curve_mapping.evaluate(curve_map, position)` (helper
  `_evaluate_curve` keeps both signatures).
- RNA writes ("Writing to ID classes in this context is not allowed")
  inside render/viewport callbacks: `utils_compatibility.run()` is
  wrapped in try/RuntimeError during export (load_post already ran the
  same upgrades); `find_suggested_clamp_value` swallows the
  RuntimeError; `config._enabled_gpu_devices` falls back to reading
  `GetOpenCLDeviceDescs()` when the device collection can't be
  lazily populated.
- `get_current_view_layer()` returns None outside the final-render
  path (`State.active_view_layer` unset — direct export calls, tests);
  `aovs.convert` falls back to `view_layers[0]` instead of dropping
  all film outputs.
- Empty `config.convert()` result (export exception) is checked with
  `str(config_props) == ""` in BOTH `export_scene` (raises) and
  `get_viewport_changes` (skips the config-cache diff) — never feed an
  empty config to the session worker: `renderengine.type` would be
  undefined downstream. All `config_props.Get("renderengine.type")`
  sites use an explicit fallback.
- **Disabled sockets are excluded from `inputs[name]` key lookups** —
  use `inputs.find(name)` (index lookup, hits disabled sockets too).
  This bit the OpenPBR SSS preset seeder: subsurface sockets sit
  disabled until the lobe is enabled, so `inputs["Subsurface Radius"]`
  raised while `inputs.find()` works.
- Renaming a socket preserves `default_value` and links, so old-file
  migration can just rename — but order the renames when old and new
  names overlap (`_migrate_sss_sockets` in `nodes/materials/openpbr.py`).
  EVERY code path that looks up the new names must migrate first — an
  update callback can fire without the toggle that owns the migration
  (e.g. `update_sss_preset` on an old file, where the pre-rename float
  socket still answers to "Subsurface Radius" and rejects the RGB
  tuple's `default_value` assignment).

