# Verified SuperLuxCore Blender 2.11.19 deployment

2.11.19 preserves existing Cycles Normal Map spaces, named/active UV tangent data, handedness and nonuniform object transforms without rewriting the artist graph. Existing Diffuse BSDF Roughness is translated to the native energy-preserving rough diffuse model. A native RoughMatte PDF/importance-transport repair removes the verified white-furnace energy loss.

The native high-quality spectral defaults are preserved. This release is a bounded compatibility improvement; production Cycles compatibility remains in progress.

Verified provenance:
- Engine source `cab7f75f27e18fbd524b39f559a85c9129cb4ef4`, CI [37907910137](https://github.com/claudianus/SuperLuxCore/actions/runs/37907910137).
- Add-on source `4c4307a4c8e17f089ae2d576b397112a2fd2ac5b`, bundle CI [37911862361](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37911862361), successful second attempt.
- Four-platform wheel build/smoke, exact-source attestations, ZIP structure and embedded engine wheel hashes passed.
- Actual Blender 5.2.1 macOS ARM CPU/Metal, 1280×720: 98 CI-wheel checks, 60 final-ZIP checks, 30 actual user-profile checks, plus a spectral material image on each backend at every installation stage. Signed EXRs and comparison images were reviewed. Native module SHA-256 matches the CI wheel: `9112a87f70ba270a2fb44e892347f7636f2534b2f413de778a148c22d30c36d0`.

Remaining limits:
- The material images use a 32-sample limit and retain Metal transmission noise; convergence, performance equivalence and full material parity are unverified.
- Grazing bumped/normal-mapped Principled reflection correction, coat/tangent/closure combinations, output displacement and actual viewport/F12 production workflows remain open.
- The central white-furnace energy gate passes within 1%; a separate BIDIR silhouette artifact also affects plain Matte and remains open.
- Other platforms have CI and package checks, not local Blender GPU/GUI verification.
- Dedicated Bump linked-input/direction work belongs to the next 2.11.20 candidate and is not included here.

Install the ZIP for your platform through Blender Preferences > Get Extensions > Install from Disk. The engine is bundled. The macOS ARM ZIP has also been installed and checked in the actual user profile; the previous extension and preferences were backed up before installation.

Evidence: workspace `test-scenes/validation-2026-10-09/public-bundle-2.11.19`. Actual-install backup: `/tmp/slc-actual-before-v19`. The active wheel source is bundled (`wheel_source = 0`).

## Artifact SHA-256

| Artifact | SHA-256 |
| --- | --- |
| pysuperluxcore-2.11.19-cp313-cp313-macosx_11_0_x86_64.whl | `c3aa4b460fa29b65add85c7e3a34ea48487568b4bc2aab041be22cb64b6345d3` |
| pysuperluxcore-2.11.19-cp313-cp313-win_amd64.whl | `d92708a477ef775b1460985c3f49371cc6fdf39b4e2d48685eb9f1b40b47b8e9` |
| pysuperluxcore-2.11.19-cp313-cp313-manylinux_2_28_x86_64.whl | `65fbcaa130aa3b2e82b1fd338c1c06a965ed3a80acb4dccc43b7822b4eb2f201` |
| pysuperluxcore-2.11.19-cp313-cp313-macosx_14_0_arm64.whl | `c817b23aacd9b77a3a2f6c877cf7323362fa4e746c3f2b11d8d2cd7f29b90600` |
| SuperLuxCore-2.11.19-windows_x64.zip | `7718c2beb527a49ba6d6181284e40af62d7a22a9a6997b47320f5d2680e8b420` |
| SuperLuxCore-2.11.19-macos_arm64.zip | `90627de21744857f152123ecfceef263a5cfb032df791fa37aaa2b61cdb19466` |
| SuperLuxCore-2.11.19-linux_x64.zip | `8db0c480b8184ad0509369185f0550f701c2aee4d4073b060605e68eae418f4c` |
| SuperLuxCore-2.11.19-macos_x64.zip | `f31346c830cce964cafc22cf7c9c50b002b196bae1031bc45063dd7389ff2c1a` |
