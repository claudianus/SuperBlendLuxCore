# Windows extension zip: local build, CI auto-release, RTX/CUDA requirements

> Engineering note for SuperBlendLuxCore. Deployment of the *installed*
> extension for development is in [deployment.md](deployment.md).

## What ships

One Blender extension zip per platform (`SuperLuxCore-<ver>-windows_x64.zip`,
`-linux_x64`, `-macos_arm64`, `-macos_x64`). Each bundles the matching
`pysuperluxcore` wheel, so install is offline (no pip, no PyPI — the engine
wheel is **not on PyPI**, so a zip without bundled wheels cannot start).

The Windows and Linux zips additionally bundle `nvidia_cuda_nvrtc_cu12-12.8.93`
(hash-pinned in `cmake/bundled-wheels-win.txt` /
`cmake/bundled-wheels-linux.txt`):

- `pysuperluxcore` declares `Requires-Dist: nvidia-cuda-nvrtc-cu12`, but
  Blender's extension installer does **not** resolve wheel dependencies.
- CI-built wheels (delvewheel) do not contain NVRTC (cuew loads it at run
  time). Without it `cuewInit` fails and CUDA/OptiX is unavailable; older
  engine builds even threw `CUDA_ERROR_NOT_INITIALIZED` from device
  enumeration (fixed by `ccf5506c1`).
- 12.8+ is required for Blackwell (RTX 50xx, sm_120).

## Local build (no CI)

Prerequisite: Release install of the engine (`dev-tools\build-win.bat`).

    powershell -File dev-tools\package-win-extension.ps1 [-OutDir <dir>]

Packs the local `pysuperluxcore.pyd` + runtime DLLs into a `win_amd64` wheel
(`SuperLuxCore/dev-tools/make_dev_wheel_win.py`, delvewheel-style `.libs`
layout + `add_dll_directory` shim), fetches the pinned NVRTC wheel, then runs
the same CMake/`verify_bundle.py` flow as CI. Output defaults to
`<workspace>\dist\`.

## CI auto-release

1. **Engine** (`SuperLuxCore/.github/workflows/wheel-builder.yml`): after the
   wheel matrix succeeds on `main` (Release build, direct run — not
   `workflow_call` from the releaser), job `publish-latest` moves the tag
   `wheels-latest` and refreshes the rolling prerelease with the four cp313
   wheels.
2. **Addon** (`release_bundle.yml`): pushing a tag `vX.Y.Z[-pre]` (must equal
   `version` in `blender_manifest.toml`) builds the zips via
   `build_bundle.yml` and publishes a release. `workflow_dispatch` creates a
   *draft* instead. `bundle_latest.yml` (manual) refreshes the `latest`
   prerelease.
3. `build_bundle.yml`: `gh release download <wheels_tag>` → pinned NVRTC via
   `pip download --require-hashes` (`cmake/bundled-wheels-{win,linux}.txt`) →
   `cmake -DBLC_BUNDLE_WHEELS=ON` → `blender --command extension build
   --split-platforms` → `cmake/verify_bundle.py` (exactly one cp313 engine
   wheel per zip, version == manifest, platform-matched NVRTC in the Windows
   and Linux zips, none in the macOS zips).

    git tag v2.11.3 && git push origin v2.11.3

`BLC_BUNDLE_WHEELS=OFF` (default) keeps the upstream behaviour (empty
`wheels/`, `wheels = []`).

## Gotchas

- `--split-platforms` keeps the full top-level `wheels = [...]` and appends
  the platform-filtered list under `[build.generated]`; Blender installs from
  the latter. Verify that one, not the top-level list.
- `wheels-latest` must be built from an engine commit that contains the
  CUDA/NVRTC fixes (`ccf5506c1`, `ddbf303ff`). The v2.11.2 release wheel
  (`aef6e845e`) predates both: device enumeration throws without NVRTC
  (observed), and per the engine SESSION_LOG the PATHOCL kernels still carry
  OpenCL-only syntax that NVRTC rejects (not re-tested with that wheel).
- The configure step rewrites `blender_manifest.toml` and deletes `wheels/`
  in the source tree — run it on a throw-away copy locally.
- Blender extension builds need the wheel name to carry a platform tag
  Blender understands (`win_amd64`, `manylinux_2_28_x86_64`,
  `macosx_*_arm64|x86_64`); `py3-none-win_amd64` (NVRTC) is fine.

## Verified (2026-09, Windows 11, RTX 5060, Blender 5.2.2)

- Zip installs into a clean `BLENDER_USER_RESOURCES` profile via
  `extension install-file --enable`; add-on registers, Blender unpacks both
  wheels into `extensions/.local/.../site-packages`.
- From that install: `OPENCL_GPU` + `CUDA_GPU` = RTX 5060, NVRTC 12.8, and a
  PATHOCL render on the CUDA device (8.05M samples/s, valid image).
- Same CI-style zip built from the *v2.11.2 CI wheel* + pinned NVRTC also
  enumerates CUDA; the untouched v2.11.2 release zip (no NVRTC) throws
  `CUDA_ERROR_NOT_INITIALIZED` during enumeration.
- Workflows pass `actionlint` 1.7.12.
- GitHub runners (2026-09-29): engine wheel-builder run 36583842150 (20/20
  wheels + `publish-latest` → `wheels-latest` = 2.11.3 @ `62d76e587`), addon
  release run 36588418708 (4 zips, `verify_bundle.py` OK, attestation OK) →
  release `v2.11.3`. The CI windows_x64 zip was then re-validated on the
  RTX 5060: bundled-wheel fast path, CUDA + NVRTC 12.8, CUDA PATHOCL render
  9.15M samples/s (cold NVRTC kernel compile ~21 min on first render).

## Known limits

- Engine → addon is not chained automatically (a cross-repo dispatch needs a
  PAT secret). Sequence: engine `wheels-latest` refresh, then tag the addon.
- Push events (branch and tag) start no workflow in either fork: Actions is
  enabled (`actions/permissions`), GitHub records the PushEvent, but no
  `github-actions` check suite is created — only `workflow_dispatch` runs.
  Likely the fork-level "enable workflows" gate on the repo's Actions tab
  (UI only). Until push runs appear, release manually:

      gh workflow run wheel-builder.yml -R claudianus/SuperLuxCore --ref main
      git tag vX.Y.Z && git push origin vX.Y.Z
      gh workflow run release_bundle.yml -R claudianus/SuperBlendLuxCore \
        --ref vX.Y.Z -f release-version=X.Y.Z -f allow-updates=false
      gh release edit vX.Y.Z -R claudianus/SuperBlendLuxCore --draft=false --latest
- Engine `wheel-releaser.yml` / `wheel-publisher.yml` / `sample-releaser.yml`
  now target `${{ github.repository }}` (were upstream `LuxCoreRender/LuxCore`,
  engine `62d76e587`).
