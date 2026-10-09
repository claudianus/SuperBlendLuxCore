# Verified SuperLuxCore Blender 2.11.17 deployment

The public release and actual Blender user profile were upgraded to 2.11.17 after final ZIP validation. Production Cycles compatibility remains in progress.

- Engine source: `839f1c6fe955947db1662f39accf7d62c5e0a9c0`; [CI 37894698719](https://github.com/claudianus/SuperLuxCore/actions/runs/37894698719).
- Add-on source: `6ed9d458c21540fbc767eff4aed85e35d38341af`; [CI 37898081366](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37898081366).
- [Fixed engine wheels](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.17) and [public Blender ZIPs](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.17).

All four engine builds/smoke checks, four ZIP packaging checks, source-bound wheel/ZIP attestations and embedded engine hashes passed. Actual Blender 5.2.1 CPU and Metal rendering was verified on macOS ARM. Other platforms have CI build/smoke/package checks; local Blender GPU/GUI rendering on them remains unverified.

Final ARM ZIP and actual user profile both completed 1280×720 standard spectral material scenes at 32 samples, with finite pixels, no renderer errors, matching native/package 2.11.17 and the same native module SHA-256: `fbc312af418a7b2425c9e115de22c544bd4253d17aff7b87e1d653d3bded283e`. Images were inspected. The Metal transmission sphere retains spectral grain at 32 samples; convergence and performance equivalence are not claimed.

Final ZIP additionally passed four spectral Flat-image Vector and four Sphere/Tube cases per backend. Private phase 11 includes 13 RGB/four spectral image Vector cases and four Bump Normal-pass cases per backend; phase 12 includes ten RGB/four spectral projection cases. The real HALL_BENCH legacy settings bridge test passed after the RNA descriptor lifetime fix. No quality defaults were reduced to match Cycles.

The user extension, add-on config and user preferences were backed up to `/tmp/slc-actual-before-v17` before installation through Blender's extension CLI. Wheel source is 0; the loader recognises the matching bundled wheel. No Blender GUI was running. The separately isolated old SuperLux test process was left running.

Evidence: workspace `test-scenes/validation-2026-10-09/public-bundle-2.11.17/` contains logs, metrics, raw EXRs, PNGs, hashes and attestation records. Feature evidence is in phases 11 and 12.

## Artifact SHA-256

| Artifact | SHA-256 |
|---|---|
| pysuperluxcore-2.11.17-cp313-cp313-macosx_14_0_arm64.whl | `72a609b75ea5a509be42fa743f738e4c5e6d660cd0c5499c9c99d1a6837b12e3` |
| pysuperluxcore-2.11.17-cp313-cp313-macosx_11_0_x86_64.whl | `24ab6e220431685239b47b5c1f7143139ec8fa5fadf22e623ac78b639bfd7d9a` |
| pysuperluxcore-2.11.17-cp313-cp313-manylinux_2_28_x86_64.whl | `4d4bb8e913dac025165750d8765eb2109ff133d7d33dc6f4393bc44c792c7e1c` |
| pysuperluxcore-2.11.17-cp313-cp313-win_amd64.whl | `3fc081dc218ef81a5716722e0eb370453347b04932bdd1ada31e281a773fffca` |
| SuperLuxCore-2.11.17-windows_x64.zip | `fd136725e2dd7c99ae40cdb191ab2703bd793e77518be9e7f1f945df9495f842` |
| SuperLuxCore-2.11.17-macos_x64.zip | `c97b7768422ab5269b6d4d575da4b6caa9736ed0900fd18a494ee2047e04e062` |
| SuperLuxCore-2.11.17-linux_x64.zip | `38d28034b6e2feb2b7f83eb9303e58d05f90fff8ba297853da944af3185c23b5` |
| SuperLuxCore-2.11.17-macos_arm64.zip | `f037d6609d802f60045712a96ae8f8a04e4679444ea0b5abf8f8b039407f36a7` |
