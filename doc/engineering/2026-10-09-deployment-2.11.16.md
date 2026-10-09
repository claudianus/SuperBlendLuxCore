# Verified SuperLuxCore Blender 2.11.16 deployment

The public release and actual Blender user profile were upgraded to 2.11.16 after final ZIP validation. Full Cycles production compatibility remains in progress.

- Engine main: `00e96a78ad7be788b3c2e1f76560eb255b0fbf10`; [CI 37890503790](https://github.com/claudianus/SuperLuxCore/actions/runs/37890503790).
- Add-on build source: `42dc17b832eca363d3ca205e88019f0582cfeb06`; [CI 37892886586](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37892886586).
- [Fixed engine wheels](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.16) and [public Blender ZIPs](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.16).

All four engine builds/smoke checks, four ZIP structural/ABI packaging checks, source-bound wheel/ZIP attestations and embedded engine hashes passed. Actual Blender 5.2.1 rendering was verified on macOS ARM CPU and Metal. Windows/Linux/Intel passed CI build/smoke/package checks; their Blender GUI and GPU rendering remain unverified locally.

The final ARM ZIP was installed through Blender's extension CLI into a clean isolated profile. Mapping and Vector Divide standard spectral conditions plus a material scene were rendered at 1280×720 and inspected. The actual user profile `/Users/modumaru/Library/Application Support/Blender/5.2` then received the same complete ZIP, with the prior extension/config/preferences backed up to `/tmp/slc-actual-before-v16`. Its default wheel source is 0; the loader recognises matching bundled versions and skips download. Both CPU and actual Metal user-profile renders passed. The installed native module SHA-256 matches the CI wheel and final ZIP: `9422ec76b327e9aa248245f57658a5e1d12e8dd3a3eb3b50ab9727180ff417ac`.

| Final ZIP / actual user check | Conditions | Result |
|---|---|---|
| mapping-cpu | 4 | 0.009060085 |
| mapping-metal | 4 | 0.011165215 |
| divide-cpu | 3 | 0.006916548 |
| divide-metal | 3 | 0.007962551 |
| render-cpu | 1 scene, 32 samples | Finite, no render errors, native/package 2.11.16 |
| render-metal | 1 scene, 32 samples | Finite, no render errors, native/package 2.11.16 |
| actual-cpu | 1 scene, 32 samples | Finite, no render errors, native/package 2.11.16 |
| actual-metal | 1 scene, 32 samples | Finite, no render errors, native/package 2.11.16 |

The 32-sample Metal material render retains visible spectral grain, especially in the transmission object. This validation confirms functioning materials, image layout and finite rendering; it does not claim noise equivalence, production convergence or performance ratios. No spectral/quality defaults were disabled for this scene.

Artifacts, raw EXRs, PNGs, logs and attestation data are in workspace `test-scenes/validation-2026-10-09/public-bundle-2.11.16/`. Feature-level private RGB/spectral evidence is in phases 9 (Mapping) and 10 (Vector Divide). E37 passed 22/22 after Vector Divide.

## Artifact SHA-256

| Artifact | SHA-256 |
|---|---|
| pysuperluxcore-2.11.16-cp313-cp313-macosx_14_0_arm64.whl | `bc0bf6772957a7feb85b1c39d2daf521c1bb2760f82c6f358e3b6cac5b7361a6` |
| pysuperluxcore-2.11.16-cp313-cp313-macosx_11_0_x86_64.whl | `1e0dee162705830a1f9c7105e1c3334847e96e6a111d92ff9f4a6cabe5fdf9fd` |
| pysuperluxcore-2.11.16-cp313-cp313-manylinux_2_28_x86_64.whl | `6178350eb311db09f8dae6dc0b5e4abeda2c6b73f16cfd7a92422089d5a0d886` |
| pysuperluxcore-2.11.16-cp313-cp313-win_amd64.whl | `c175d286e8d1b6c152fed823fd3353989948c712b4ed262776057e8fa9375466` |
| SuperLuxCore-2.11.16-windows_x64.zip | `37a2ad24167bfc813dbffb797ea1190e001734c6217db31559236e5664e452b2` |
| SuperLuxCore-2.11.16-macos_x64.zip | `018ea5f1187cfb3abd368f0357c0377027dcf76d048d3d2c24f22a7c856f1175` |
| SuperLuxCore-2.11.16-linux_x64.zip | `d00abe5239f4d88517b613c3641bd62eb4227d3203425c8190f0aa445836a265` |
| SuperLuxCore-2.11.16-macos_arm64.zip | `10a79c19420224ac0789327fd42f95fe6ccb0126a40f7cd795ad9ed954f4b051` |
