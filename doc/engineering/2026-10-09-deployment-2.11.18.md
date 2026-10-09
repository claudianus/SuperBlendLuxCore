# Verified SuperLuxCore Blender 2.11.18 deployment

2.11.18 is public and installed in the actual Blender user profile. Production
Cycles scene compatibility remains in progress; 2.11.19 Normal Map work is a
separate candidate.

- Engine source: `751e8dfafbb91f63fc8bb67659e693faed6ee4db`; [CI 37898310834](https://github.com/claudianus/SuperLuxCore/actions/runs/37898310834).
- Add-on source: `eab1753d565a1db107d2505f1084f35e870d8d67`; [bundle CI 37902268082](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37902268082).
- [Fixed engine wheels](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.18) and [public Blender ZIPs](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.18).

All four engine build/smoke jobs, exact-source wheel/ZIP attestations, four ZIP
structure checks and embedded wheel hashes passed. macOS ARM was tested in
actual Blender 5.2.1 on CPU and Metal. Other platforms have CI build/smoke/package
verification; local Blender GPU/GUI rendering remains unverified.

The CI wheel passed ten RGB and five standard spectral Normal-vector cases per
backend. A clean profile installed the final ZIP through Blender's extension
CLI, then passed five standard spectral Normal-vector cases per backend.
CI wheel, final ZIP and actual user profile each rendered a 1280×720 standard
spectral material scene at 32 samples on CPU and Metal with finite pixels and
no renderer errors. Final ZIP and actual images were inspected. The native and
package versions match 2.11.18, and the installed native module matches the CI
wheel SHA-256: `35efc51f2ef7047c203e75b58785723a4825a3761ce277d497ab7240934e408b`.

Metal transmission retains spectral grain at 32 samples; convergence,
performance equivalence and full material parity are not claimed. No quality
defaults were reduced. The actual extension/config/user preferences were backed
up to `/tmp/slc-actual-before-v18`; no Blender GUI or render was running during
installation. The bundled wheel is the active source.

Evidence: workspace `test-scenes/validation-2026-10-09/public-bundle-2.11.18`
contains metrics, EXRs, PNGs, logs, source attestations and artifact hashes.

## Artifact SHA-256

| Artifact | SHA-256 |
| --- | --- |
| pysuperluxcore-2.11.18-cp313-cp313-macosx_14_0_arm64.whl | `a63ecc4bf448ad09ca24e5c7cd386b9ee0b18903ab553c23484cad9a6847c926` |
| pysuperluxcore-2.11.18-cp313-cp313-macosx_11_0_x86_64.whl | `5ded6f36cfa9aeac6329051e221d71393475cc6be600492dc434ac8803800e4f` |
| pysuperluxcore-2.11.18-cp313-cp313-manylinux_2_28_x86_64.whl | `8b82befe5462e3e3744a3f05ba4cd7825d7a4b60ab451b7d79c4964b10040993` |
| pysuperluxcore-2.11.18-cp313-cp313-win_amd64.whl | `a587682ee7ae40715dc9558dadb8b3da89e34512322320d517b290c555c4409b` |
| SuperLuxCore-2.11.18-linux_x64.zip | `b4c1b0cf3c184a6d24c40cfe82bdfc05a0b3f07daf28176d18fb44ffe08e5da2` |
| SuperLuxCore-2.11.18-macos_x64.zip | `0d3cfda0c9325c46b0aeac5497fae379260d5adc80bc5f927b3e0cae7d3c9e12` |
| SuperLuxCore-2.11.18-windows_x64.zip | `51401c75503e9887d3fa358758d077e2dd31f75dce7064a9decd2aaa4587361d` |
| SuperLuxCore-2.11.18-macos_arm64.zip | `12230fe82d95163d16ce41b0bbd761b853ded11e6b47c186707efe10a01dfa75` |
