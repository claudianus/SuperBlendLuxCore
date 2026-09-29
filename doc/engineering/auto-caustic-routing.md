# Auto caustic routing (scene-signature driven)

## What

`photongi.caustic_mode` = `auto | on | off` (default `auto`) replaces the
raw `caustic_enabled` bool as the artist-facing control. Under `auto` the
PhotonGI **caustic** cache engages on final renders whenever the scene
contains a transmissive caster — even with the PhotonGI master toggle
off. Opaque scenes pay nothing; viewport renders stay cache-free.

## Resolution logic (`export/config.py`)

```
mode = photongi.caustic_mode
off  -> never
on   -> always (engine must be PATH*/TILEPATH*/RTPATH*)
auto -> scene_has_transmissive(scene) OR legacy caustic_enabled=True
```

- `caustic_enabled` is kept as a hidden legacy bool: a saved `True` in an
  old .blend still forces the cache under `auto`. `off` overrides it.
- The PhotonGI block is exported when `photongi.enabled OR caustic_on`.
- **Indirect cache stays gated on the master toggle**
  (`indirect.enabled = photongi.enabled and photongi.indirect_enabled`) —
  auto-caustics must not pull in the heavy indirect preprocess.
- Engine guard: BIDIR/various non-PATH engines are skipped (PhotonGI is
  PATH-family only).
- `is_viewport_render` skips everything — viewport stays progressive
  and cache-free by design.

## Scene signature scan (`utils/scene_analysis.py`)

`scene_flags(scene)` does one pass over `scene.objects` mesh materials
(both Cycles and SuperLuxCore node trees, deduplicated by material) and
fills `{transmissive, sss, volume, emission, dispersion}`.
`scene_has_transmissive()` is the narrow accessor used by routing.

Transmissive classifiers: `SuperLuxCoreNodeMatGlass`,
`SuperLuxCoreNodeMatMatteTranslucent`, `SuperLuxCoreNodeMatGlossyTranslucent`,
Principled/OpenPBR `Transmission Weight` (linked or > 0),
Cycles `BsdfGlass/BsdfRefraction/BsdfTranslucent`, and mix/add containers
that feed any of those.

## Synergy

Auto-built caustic caches also feed the MNEE seed table (MPG-lite
Phase B): photon-traced delta vertices are injected into the seed cache,
which warm-starts ~26% of manifold solves in caustic-heavy scenes.

## Tests

- `dev-tools/e51_caustic_auto_routing_test.py` — 9 export-level checks
  (auto on glass, opaque skip, off/on overrides, legacy bool, indirect
  gating). Note: use `bpy.data.scenes.new()` per case — repeated
  `read_factory_settings` + addon re-register leaves stale RNA pointers
  and segfaults Blender.
- `dev-tools/e49_render_defaults_test.py` pins `caustic_mode == "auto"`.

## Gotcha

The export-level check `path.photongi.caustic.enabled == "1"` requires a
final-render export (`export_scene` with `context=None`). Viewport
exports (`context` set) never carry PhotonGI keys.
