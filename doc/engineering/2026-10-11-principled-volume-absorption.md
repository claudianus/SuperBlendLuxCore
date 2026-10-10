# Cycles Principled Volume absorption color

Cycles 5.2 computes the square root of the authored Absorption Color RGB before
converting it into the absorption complement. The adapter previously used the
raw color, making fractional input channels absorb too strongly. For example,
`(0.04, 0.25, 0.64)` at unit density and zero scattering color previously
produced sigma-a `(0.96, 0.75, 0.36)` instead of `(0.8, 0.5, 0.2)`.

The Principled Volume branch now takes the nonnegative square root per RGB
channel. Constants fold in Python. Linked colors use SplitFloat3, scalar
nonnegative power and color MakeFloat3 helpers, so the nonlinear operator runs
on authored RGB before the default spectral conversion. The existing
absorption complement and density composition then apply. Pure Volume
Absorption and Volume Scatter branches are unchanged.

`dev-tools/cycles-principled-volume-absorption-test.py` renders the same authored
graph in Cycles, SuperLuxCore CPU and Metal. It compares an eroded 1280x720 slab
body to the independent RGB law `exp(-2 * max(1 - sqrt(color), 0))`. Constant
fractional channels, a linked gradient with an explicitly authored Object
coordinate reference, and 0/1/4 limits have fixed 64-sample and 1% mean gates.
The driver also renders both native backends in their default spectral mode;
these images have a separate direct review and no RGB-equality gate.

The narrow installed-adapter candidate, without monkeypatches, completed all
15 images. All original PNGs were directly reviewed. Six native RGB conditions
passed, with maximum body error 0.08960%. Spectral CPU and Metal retain blue,
cool-to-warm gradient and cyan meaning, with grain at 64 SPP. Absorption blue
value 4 has a 67.50% red-channel mean difference from the RGB law in spectral
mode; this is an explicit HDR spectral colorimetry limitation. The test does
not establish final converged color or general volume compatibility.

The exact signed core is source `c2915a73a325bd2e5d0e2f999298051bf9af5d32`,
native SHA256 `d5443cf5022c653d5636fa4b44ec246a60e39b0b65e2078e6135410949636024`,
whole wheel SHA256 `dace137bff6799eebb099ede4e4570ad3eba07fdd1bc9d79b624ca25db1ba5d7`.
Evidence is in the parent workspace's
`test-scenes/validation-2026-10-11/principled-volume-absorption`.
The original one-thread interrupted attempt and its source are retained;
the four-thread rerun preserves sample budgets and the analytic threshold.
Actual narrow-reader registration and linked-color rendering subsequently completed as recorded below.

Named VDB attributes, Generated coordinates inside volumes, broad blackbody
radiance/unit checks, overlapping volume boundaries and production convergence
remain open. In particular, the separate Generated-coordinate failure is not
hidden by the explicitly authored reference used to isolate this color
operator. The full unchanged-Cycles-scene goal remains active.

## Actual narrow deployment and latest bundles

The implementation is on main at `d8302873b124cefc30def3cd081a42bc0e12a92f`.
The actual installed reader was updated from
`7dd35540ac9a1fcffdbd4b1aeb2684957f51164e799a30b93cc6d271fcb6a235`
to `6b87346c41135fccfc7405fcf19c4b41edfbb9f83ff6c4bdd26a2477fa957f2a`.
Only the Principled absorption block was backported into that stable reader;
all other 373 installed Python files, the full core payload, cached wheel and
user settings were verified unchanged. The whole repository reader also has
the preceding unconnected-zero-Normal cleanup and has SHA256
`ee603e49966b2c3cc05d60db88ae122fd7ce38cf3f86e554420d6667b83ffb7c`.
This narrow installation does not expose the private experimental BSSRDF path.

Fresh installed Blender 5.2.1 registration succeeded before and after rendering.
The unchanged linked-color fixture completed five actual 1280x720 images:
Cycles RGB and native CPU/Metal in RGB/default spectral modes. All five original
PNGs were directly inspected, and the graph fingerprint matches the candidate.
Native RGB maximum mean error was 0.09907% against the same independent slab
law. The spectral gradient and silhouette remain consistent; bounded grain
is visible. This verifies the installed color operator without accepting final
production convergence or fixing Generated volume-carrier context.

[Latest bundle workflow 38089660645](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38089660645)
completed bundle build, signature and publication at the exact implementation
commit. All four public ZIP digests match the signed subjects. The
[latest prerelease](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/latest)
contains Windows x64, Linux x64, macOS Intel and macOS ARM installers.
The downloaded ARM ZIP matches its release digest and has all 382 Python source
files byte-for-byte equal to that Git commit; its repository reader and bundled
whole core wheel match the hashes above. Other platform bundle payloads were
not downloaded or rendered locally; their signed publication and CI gates are
verified. The stable versioned release is a separate earlier artifact.

The candidate profile was verified and removed immediately after use
(293059213 logical bytes; physical freed space not measured). All owned render,
validation and bundle-capture processes have been reaped. Original images,
EXRs, the ARM installer, signature evidence, rollback reader, interrupted attempt
and source/hash inventories remain in durable evidence. `completion-proof.json`
and `preservation-inventory.json` record the unit. The full compatibility goal
remains active, including named VDB attributes, Generated volume context and
broader blackbody/colorimetry/production checks.
