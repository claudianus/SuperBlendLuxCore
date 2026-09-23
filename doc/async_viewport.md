# Async viewport session (SessionWorker)

## Why

`view_update`/`view_draw` run on Blender's UI thread. Session creation
(RenderConfig + kernel pre-compile + RenderSession.Start) can take
minutes on a cold kernel cache, and every synchronous call froze the
whole window. All live-session work now runs on a dedicated worker
thread; the main thread only does what it must — depsgraph access.

## Threads and ownership

```
main thread (bpy/depsgraph)          worker thread (pyluxcore only)
--------------------------           -----------------------------
Exporter.export_scene()        ->    RenderConfig + KernelCacheFill
  produces (scene, config_props)     + RenderSession.Start
Exporter.update()              ->    BeginSceneEdit + replay ops +
  produces [("edit", ops),           EndSceneEdit, session.Parse,
            ("parse", props)]        Stop, config rebuilds
```

- `engine.session_worker` owns the live `pyluxcore.RenderSession`.
  `_publish()` mirrors it into `engine.session` so readers (stats, film
  readback) always see the current object.
- `session_lock` (created in `engine.reset()`, shared with the worker)
  guards live-session mutations vs. film reads. It is never held across
  RenderConfig/RenderSession construction or kernel compiles, so readers
  never stall behind a rebuild.
- The worker holds `weakref(engine)` — `engine -> worker -> engine`
  would otherwise be a reference cycle delaying `__del__` cleanup.

## Job coalescing

- `submit_config` merges pending config jobs (newest wins) or stashes
  into `_pending_config` when no session is live (folded into the next
  start — a config change during startup never boots stale settings).
- `submit_edit` appends/merges op lists; edits arriving mid-restart are
  requeued so they land on the new session (the scene is shared).
- `submit_start` carries a seq counter: a superseded start skips its
  build. Before building, the old session is stopped.
- `submit_stop` clears the queue and stops the session; the follow-up
  full export re-covers any dropped edits.

## Errors

- `_error` latches `(kind, error)`; `view_update`/`view_draw` drain it
  via `pop_error()` -> `LuxCoreErrorLog` + stats line.
- `start`/`config` failures set `engine.viewport_fatal_error` so the
  viewport stops retrying (persistent errors like a bad engine name).
- `edit`/`parse` failures drop the session (`_publish(None)`) — the next
  `view_update` sees `engine.session is None` and re-exports fresh.
- `engine.reset()` clears `viewport_fatal_error` on every fresh start —
  recovery beats a permanently dead viewport.

## RecordedScene contract

`Exporter.update()` never touches the live scene. It runs the normal
conversion code against `export/recorded_scene.RecordedScene`, which
records `(name, args, kwargs)` and answers `Is*Defined` queries from a
conservative shadow state (unknown -> False -> caller re-defines, which
is safe; a false positive would corrupt the scene). The worker replays
the ops inside one `BeginSceneEdit`/`EndSceneEdit`. When adding a scene
call to the update path, it must be in `RecordedScene._MUTATORS` (or a
shadow query) — otherwise it raises AttributeError on the proxy.

## Framebuffer (draw/viewport.py)

- Film readback (`GetOutputFloat` = device drain + imagepipeline) runs
  on a readback thread (`update_async`); results are consumed on the
  main thread and stale results (session swapped meanwhile) are dropped.
- `begin_reset()` holds the last visible frame while the new render has
  no samples yet (bounded by `HOLD_LAST_FRAME_MAX_S`) — no black flash
  on camera orbit, resize, or session restart.
- OIDN denoise runs off-thread (`run_denoiser`); GL upload stays on the
  main thread (`consume_denoise_result`). Results pinned to the paused
  session are ignored if the session was replaced.
- `view_draw` snapshots `engine.session` once per draw: the worker may
  publish None mid-draw, and a stale-but-alive session degrades to a
  caught RuntimeError instead of AttributeError.

## Status line

`worker.phase` carries "Exporting scene" / "Creating render config" /
"Compiling kernels (i/n)" / "Starting session" / "Applying scene edits"
/ "Reconfiguring session" into `update_stats`, so a long compile shows
progress instead of a frozen frame.

## Tests

- `dev-tools/async_worker_unit_test.py` — worker + RecordedScene, plain
  python3 (no Blender), fake pyluxcore.
- `dev-tools/async_session_e2e_test.py` — real Blender -b + real
  pyluxcore: start/edit/config/burst/bad-config/stop.
