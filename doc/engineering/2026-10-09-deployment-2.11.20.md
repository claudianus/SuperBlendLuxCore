# Verified SuperLuxCore Blender 2.11.20 deployment

2.11.20 preserves existing Cycles Add Shader closure sums, nested transparent/emissive transport and transparent-film alpha on CPU and Metal. Adding two unit diffuse closures retains their summed energy; transparent/emissive material combinations retain both transmitted camera light and emitted illumination. Cycles Bump distance and linked-normal inputs are also supported without rewriting the artist graph. Native high-quality spectral defaults remain in place.

This is a bounded compatibility improvement. The overall no-edit production Cycles goal is active and incomplete.

## Fixed source and published artifacts

- Engine source `2f0304832ea144a7069718a1cf0a6dcdb13dea73`, successful [wheel CI 37927542538](https://github.com/claudianus/SuperLuxCore/actions/runs/37927542538), public [engine wheels 2.11.20](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.20).
- Add-on source `6a8c14837fae8428aaec459ad26ef4423f5ec9a7`, successful [bundle CI 37936274505](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37936274505), public [Blender extension 2.11.20](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.20).
- Four platform wheel builds/smoke tests, ZIP integrity, metadata/runtime files and exact-source GitHub attestations passed. All embedded engine wheel hashes match the attested CI wheels. Each final ZIP's 366 Python source files match the fixed add-on source. Windows/Linux packages carry the platform-matched, hash-pinned NVRTC wheel; macOS packages carry none.
- Published tag commits and release asset digests were checked after publication. Subsequent main changes record validation and guard duplicate release jobs; they do not change the installed runtime payload.

## Actual Blender validation

Installed Blender 5.2.1 LTS (`9e2066aef7ef`) on macOS ARM/M5 Pro completed 211 checks:

| Installation stage | Checks, including native material images |
| --- | ---: |
| CI engine wheel and frozen add-on | 125 |
| Final extension ZIP in an isolated profile | 48 |
| Final extension ZIP in the actual user profile | 38 |

The CI gate covers spectral/RGB closure sums, transparent alpha, spatial emitter receivers, Bump and Normal Map vector data, white-environment energy, limited CPU bidirectional transport, nine large-film RGBA renders and two spectral material images. Final-ZIP/actual-profile gates verify the installation path and repeat selected material/alpha/normal/illumination checks on both backends. These are check counts, not 211 independent production scenes.

Fourteen comparison sheets and six 1280×720 native spectral material images were inspected. Checks include brightness sums, spatial-factor orientation, alpha, emitted RGB, receiver-light falloff, signed normal vectors, contact, highlights and refraction. Actual Metal render logs confirm M5 Pro Metal intersection/path kernels. The material scenes retain native spectral defaults, disable early noise halt and use 128 samples. Metal glass caustics remain visibly noisy at that sample count; convergence and production performance are not established by these images.

The actual native module, distribution metadata and extension manifest report 2.11.20. The module SHA-256 matches the CI ARM wheel:

`79b47dca82b4692aba120aa32adaf339457bfc49c5f822ca1f0f2b7dd83b6324`

Install through Blender Preferences > Get Extensions > Install from Disk, choosing the ZIP for the platform. The macOS ARM package has already been installed in the actual profile. The prior extension, config and native module were backed up to `/tmp/slc-actual-before-v20`. Active wheel settings are `{"wheel_source": 0}`; an unused old LOCAL 2.11.12 wheel path was removed, and a fresh process again verified the exact CI module.

The in-process CLI update emitted three RNA property-registration diagnostics, also seen in the previous version's update. The update exited successfully. Fresh 2.11.20 processes registered, loaded and completed all actual-profile renders without those diagnostics. GUI hot reload remains unverified.

## Remaining compatibility work

- [Strongly tilted reflection-normal audit](2026-10-09-reflection-normal-audit.md): mapped Principled normals can lose reflection/diffuse energy. Per-material reflection correction, physical surface-facing decisions, separate Coat Normal and lobe/frame/terminator handling remain incomplete. The audit's ten conditions use a private runtime and reproduce defects; they are not compatibility passes.
- Add/Mix shader coverage still excludes broader animated/HDR/path-dependent weights, colored spectral transport edge cases, layered geometry/volumes/caches/light groups and full BIDIR/VCM production workflows.
- Displacement, geometry/volume/lighting combinations, production-scene convergence, viewport/F12 and other-platform local GPU/GUI rendering remain open in the goal status. Other platforms have CI/package validation only.
- User OSL and baking remain deferred. Pixel identity and a 99% completion claim are outside this release's evidence.

## Release-job cleanup

Publishing a manually verified draft creates the version tag and triggers a redundant tag build. The previous 2.11.19 tag build failed at release creation because `updateOnlyUnreleased` correctly rejected overwriting an already public release. The duplicate 2.11.20 tag run `37939464190`, using the same `6a8c148` source, was cancelled after the successful manual build/publication. Public asset hashes remained verified.

The main workflow now reads the release state before tag-triggered builds and skips an already public, non-prerelease version. Manual dispatch and new/unpublished tags keep the normal version/build/attestation gates. YAML/dependency structure and the exact guard script were verified against real GitHub API cases: published tag, missing tag and manual dispatch. The next new tag will provide end-to-end CI verification of that guard.

Durable evidence: workspace `test-scenes/validation-2026-10-09/public-bundle-2.11.20`, including `deployment-proof.json`, CI/final/actual metrics, logs, EXRs/PNGs, reviewed comparison sheets, final ZIPs, attestations, source/hash checks and release-state validation.

## Artifact SHA-256

| Artifact | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.20-linux_x64.zip | `281250719c907a1052aed0980d05edadf0d57605c26e235391cd97a4cb22cb71` |
| SuperLuxCore-2.11.20-macos_arm64.zip | `138b30206c313cb48020c4dd0277adc71a2d98f095a3cbbaf97a990d7d6456a0` |
| SuperLuxCore-2.11.20-macos_x64.zip | `e38872f462586c8222af617afba04292fce7e1e57aa57437bfe099c562d3fcc0` |
| SuperLuxCore-2.11.20-windows_x64.zip | `9cac547e71197f1ce99fc663ba9365fb1b0693c22bba737c18395ff638964205` |
| pysuperluxcore-2.11.20-cp313-cp313-macosx_11_0_x86_64.whl | `1fb5b97a19880987f9317bc118fd5c63a885e72ae8ea460493e766d7c147add9` |
| pysuperluxcore-2.11.20-cp313-cp313-macosx_14_0_arm64.whl | `9eba6e50f661cda77997108f1c670be3b159881c001c18507f11817e511698a4` |
| pysuperluxcore-2.11.20-cp313-cp313-manylinux_2_28_x86_64.whl | `48e4de4ac2dc122d809519af2b8f81fa597308477dfcd77ee556d7d10f24f142` |
| pysuperluxcore-2.11.20-cp313-cp313-win_amd64.whl | `d26a0bcc6cd69e173c15b6e557109e9262a744375aed211f9bb4457db00362ba` |
