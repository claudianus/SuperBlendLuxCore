# Deployment: installed extension, wheel chain, external render

> Engineering note for SuperBlendLuxCore — extracted from AGENTS.md.
> Feature/user-facing docs live in `doc/features/` (SuperLuxCore) or `doc/` (SuperBlendLuxCore).

## Installed Blender extensions

- `extensions/user_default/superluxcore` — this repo's add-on, synced via
  `dev-tools/sync_dev_install.sh` (default `EXT_ID=superluxcore`).

## Installing a released zip (end user / unattended)

The release artifacts are one zip per platform
(`SuperLuxCore-<version>-{windows_x64,linux_x64,macos_arm64,macos_x64}.zip`),
each bundling the matching `pysuperluxcore` wheel so no download or pip is
needed. Install with the platform zip:

    blender --command extension install-file -r user_default -e \
        SuperLuxCore-<version>-<platform>.zip

`-e` (`--enable`) is required: without it Blender only unpacks the zip and
leaves the add-on disabled, so the engine never registers. From the GUI,
*Edit > Preferences > Get Extensions > Install from Disk* enables it.
The engine resolves its Metal kernel translator (`cl2msl.py`) from inside
the installed package, so a released install renders on the GPU with no
source tree, no environment variable and no network access.

## pysuperluxcore wheel install chain (verified 2026-09)

- The add-on's wheel manager runs at startup: it copies the wheel from
  `SuperLuxCore/out/install/Release/wheel/*.whl` into
  `extensions/user_default/superluxcore/wheels/`, then unpacks it into
  `extensions/.local/lib/python3.13/site-packages/pysuperluxcore`.
- It re-does this whenever `pysuperluxcore_installation_info.txt` is missing
  or mismatched — so a hand-copied .so in site-packages is silently
  replaced on the next Blender launch. Deploy via
  `dev-tools/sync_dev_install.sh` (updates both site-packages AND the
  cached wheel), never by copying the .so alone.
- `pip install --target site-packages` also works but pip may serve a
  cached stale build for a same-version wheel — use `--no-cache-dir`
  or just let sync_dev_install.sh handle it.
- macOS: any .so placed outside the pip flow needs
  `codesign --force --sign - <so>`.
- Windows: `dev-tools/sync_dev_install.ps1` is the equivalent flow —
  copies `pysuperluxcore.pyd` + the runtime DLL set from
  `SuperLuxCore/out/install/Release` into site-packages as a
  wheel-shaped package (`pysuperluxcore/` + minimal `.dist-info` so
  `pip show`/import metadata resolve), syncs the add-on sources, and
  smoke-imports under Blender's bundled Python 3.13. Because Windows
  has no rpath, the generated `pysuperluxcore/__init__.py` shim calls
  `os.add_dll_directory()` on the package's DLL dir before importing
  the extension — copying just the .pyd without the shim/DLLs will
  fail to import.

## External-process render

- `scene.superluxcore.config.external_process` serializes the scene+config to
  a .bcf (RenderConfig.Save) and renders it in a detached
  `python3 external_render_runner.py` process; render() returns
  immediately so Blender releases the depsgraph.
- The runner must poll `session.HasDone()` + `session.UpdateStats()`:
  halt conditions are evaluated inside `Film::RunTests()` which only
  runs during `UpdateFilm` — a bare `WaitForDone()` never returns.
- `opencl.devices.select` is stripped before serializing: the child
  enumerates devices itself and a mismatched-length selection aborts.

