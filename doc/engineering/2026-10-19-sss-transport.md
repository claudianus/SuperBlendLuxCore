# CPU SSS installed delivery and matched raw comparison

The core default now enables a thickness-gated joint direction/free-flight
proposal for isotropic homogeneous SSS. The Blender spectral default and
physical material inputs are preserved. No denoising, clamping, reduced
geometry or reduced bounce budget is used in this study. See the core
`doc/engineering/2026-10-19-sss-transport.md` for the estimator contract.

## Installed artifact

Stock Blender 5.2.2 LTS (`d13f752e3b9c`) loaded the complete final wheel from
its actual user extension dependency directory, without a native override.
Native SHA256: `3b8b6b636f974b526a395e36496bb5406d801a73e4934f214681d6d1933efb4d`.
Wheel SHA256: `8a6b2c0a1df01a12db82c187043446b2eb43eaf3223295611a3e644ffd9280bf`.
The complete wheel is in workspace `dist/sss-guided-cpu-v2-20261019/`.
All 393 installed adapter Python sources remain byte-identical to the
pre-study installed snapshot. Native package, dylibs, wheel cache, LOCAL
source setting and RECORD were read back after Blender exited.

The actual-profile CPU spectral F12 test completes all 100 samples in every
320x180 pixel. Engine RGB and saved linear EXR are bit-identical. Its raw
ACES 2.0 preview still has conspicuous color grain and fireflies. This is a
local developer artifact incorporating pre-existing core WIP, not a clean
published release or a Cycles/Octane quality certification.

## Comparison boundary

Apple M5 Pro, four CPU threads; identical authored geometry, optical inputs,
area lights, resolution and BOX-equivalent filter; fixed complete sample
budgets, raw EXR, adaptive sampling and denoising off. Product spectral mode
is also tested separately; RGB is used to compare with Cycles. The native
refractive bulk and Cycles nonlocal BSSRDF transport models differ. Both
have independent finite 4096-SPP references; the native legacy reference
requested seed 181 but used sequence 131 before the tile-seed repair.

Final-binary ABBA: RGB classic64 averages 9.325 s and guided100 9.926 s;
spectral classic81 averages 13.625 s and guided100 12.377 s. These render
operator wall times include preparation and EXR writing, excluding host
startup. Shared hardware and RGB control-leg variability limit general
speed claims. Final guided RGB seeds17/53/97 reduce SSS RMSE by20.2/15.6/24.0
percent against earlier classic64 controls; exact fingerprints and both
bulk/thin masks are retained. The same-final-binary seed17 control confirms
20.2 percent. Spectral three-seed screening also reduces interseed variance.

Cycles441 at seed17 takes9.907 s with SSS relative RMSE3.21 percent versus
native guided100 at9.937 s and62.7 percent, each against its own reference.
The large convergence gap remains open. `near-time-rgb.png` retains the
native-resolution, unsmoothed common ACES2 display comparison.

## Repeat and preserve user state

`sss_blender_test.py` builds actual OpenPBR nodes and equivalent Cycles
inputs. `sss_matched_benchmark.py` records raw EXR/counts, independent
geometric masks, host/binary identities and renderer configuration.
`sss_compare_run.py` executes sequential owned children with timeouts,
process-admission checks and cleanup. `sss_compare_analyze.py` computes
model-specific errors and spectral interseed variance.

Use an isolated profile with copies of the installed adapter, config and
complete wheel. Set all three Blender roots: `BLENDER_USER_RESOURCES`,
`BLENDER_USER_CONFIG`, and `BLENDER_USER_EXTENSIONS`. Set
`SLC_SSS_NATIVE_ROOT` only when comparing an explicitly identified complete
candidate package. Never run factory-startup validation against the actual
user profile: extension reconciliation can remove inactive dependencies.
The actual-profile smoke uses a fresh unsaved scene and world, no factory
startup, and no native override. It does not save user preferences/scenes.

The comparison driver expects `EVIDENCE/isolated-profile` and a complete
candidate package directory. Temporary profiles/extractions may be retired
after the study; recreate them from the retained wheel before rerunning.
Run the analyzer on workspace
`test-scenes/validation-2026-10-19/sss-transport` for the retained study.
Source snapshots, raw images, failures, final installation receipt, fingerprints
and the machine-readable report are kept there.
