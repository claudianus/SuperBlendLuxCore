# Blender RNA thread-safety rules and crash fixes

> Engineering note: every bpy/RNA access is main-thread-only. This file
> records where worker threads used to touch bpy (intermittent Blender
> crashes — the "RNA dereference" signature seen in historical crash
> logs) and the marshalling pattern that fixed them.

## The rule

- `bpy.data`, `bpy.context`, `bpy.ops`, RNA property reads/writes,
  `RenderEngine.update_stats/tag_redraw` outside its own callbacks,
  `bpy.app.timers` callbacks themselves: **main thread only**.
- Legal off-main-thread: `bpy.app.timers.register()` (documented
  thread-safe — the only supported cross-thread entry point), plain
  `pysuperluxcore` calls on a worker-owned session, network/file IO.
- Holding an RNA object (PropertyGroup, Image, Object) across a
  depsgraph update or scene rebuild can dangle the underlying C
  struct: dereference it only on the main thread, inside try/except
  that catches `ReferenceError` — or better, store the name/key and
  re-resolve.

## Marshalling pattern

```python
# worker thread — never touch bpy here
_main_results.put(("kind", plain_payload))

# main thread — registered once, persistent
def _drain_main_results():
    while True:
        try:
            kind, payload = _main_results.get_nowait()
        except Exception:
            break
        # ... all bpy work here ...
    return 0.5
```

`bpy.app.timers.register(_drain_main_results, first_interval=0.5,
persistent=True)` runs the drain on the main thread.

## Fixed violations (this audit)

| Site | Was | Now |
|---|---|---|
| `utils/lol/utils.py::Downloader.run` | `bpy.context` + addon prefs from worker | prefs snapshotted into `tcom.passargs` on main |
| `utils/lol/utils.py::check_cache` | worker read/wrote `scene.superluxcoreOL` RNA while hashing | worker hashes files only; `cache_hit` results applied by drain |
| `utils/lol/utils.py::bg_download_thumbnails` | worker called `bpy.data.images.load/scale/save` + `asset['thumbnail']` | worker downloads files only; drain loads images and assigns |
| `engine/session_worker.py::_publish` | worker called `engine.tag_redraw()` | `redraw_hook` marshals through `bpy.app.timers` |
| `engine/base.py::log_listener` | LuxCore engine threads ran `self.update_stats` via the log handler | marshalled to a main-thread timer (engine may be dead → guarded) |
| `icons/__init__.py::__del__` | GC on any thread could call `bpy.utils.previews.remove` | main-thread check + try/except |

## Adjacent hardening

- `utils/log.py` listener list mutated while engine threads iterate →
  copy-on-write list ops.
- `utils/lol/timer.py::timer_update` returned `None` after the first
  finished download → unregistered itself and orphaned every other
  download (fixed to `continue`); `window_managers['WinMan'].windows[0]`
  crashed in background mode → `_tag_view3d_redraw` helper; RNA
  resolution of OL collections wrapped per-tick; `append_material` /
  `link_asset` exceptions can't kill the timer (target object may be
  deleted while the download runs — objects are re-resolved by name).
- `utils/lol/utils.py::download_file` deep-copies the asset idprop
  (`to_dict()`, plain-dict fallback) — the worker and timer must never
  hold an RNA reference; duplicate `bpy.app.timers.register(timer_update)`
  guarded with `is_registered`.
- `handlers/load_post.py` — `bpy.context.scene` is legitimately `None`
  during `load_post` (background/factory startup): early-out instead of
  AttributeError aborting the scene loop.
- `draw/viewport.py::run_denoiser` — `box["done"]` set in `finally`:
  a failed denoise used to wedge `_denoise_box` on "not done" forever.

## Verification

- `dev-tools/async_worker_unit_test.py`: 25/25 pass (no Blender).
- `dev-tools/async_session_e2e_test.py` under Blender 5.2.1: 17/17
  pass, incl. session restart burst and error-drop paths.
- Module smoke (installed addon): LoL utils/timer/log/icons import and
  drain/listener APIs exercised — OK.
