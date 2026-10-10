# Cycles SSS transport: sparse sampler startup repair

The native sampler could accumulate excessive light before a productive uniform
proposal supplied the normalization constant. This was separate from the
previously repaired forced-acceptance defect. Native main commit
`2536c51691f089ee55be6283fc5778ee71e94819` bootstraps with uniform proposals,
uses the live CPU mean before splatting, and publishes the shared warmup state
atomically. CPU and device samplers retain their quality defaults and acceptance
ratio. The production Cycles SSS adapter remains unchanged.

The complete local wheel's loaded native SHA256 is
`2147c5aaf6ebef88acb4a3eabceaccaf55c7dfa3d3b627fc25496a16a69cc807`.
The actual installed native remains
`aba55215c18290773b2772f75bdb5b78dee906de5d66b9675d9822c24b815a6a`
until a later exact-CI deployment is verified. Metadata remains2.11.27.

Local validation completed the fixed-normalizer acceptance2, full startup18,
additional concurrent warmup-exit3, actual CPU black-film halt3, CPU50/hybrid23,
rough-adjoint22, actual Metal57, ordinary PSR3 and guarded emission/MNEE15
conditions. Pure sharp-adjoint18 also completed (maximum0.7170% error). The startup contract's
maximum observed error was2.4963% with eight concurrent workers; the separate
concurrent dense warmup-exit maximum was0.6149%. The3% gates were not relaxed.
Four-million-proposal startup windows can still differ by9.22%; finite-budget
normalizer variance remains outside this specific repair's completion claim.

Twelve original1280x720 Cycles/native PNGs were directly reviewed across CPU
hybrid, CPU eye and actual Metal eye, retaining the authored graph fingerprints.
The sphere silhouette, orientation and warm scattering meaning agree. Against
the same wheel's independent CPU eye, body-region channel-mean errors were
0.3295%/1.9689% for sharp/rough hybrid and0.7203%/0.1481% for Metal eye.
Chromatic hybrid grain remains conspicuous, particularly in the rough case.
These are private diagnostic scenes with explicit transport limitations,
not accepted production convergence or a production SSS adapter switch.

The completed temporary profile was removed after all459 package files were
rechecked and the complete wheel/raw evidence was preserved.

Exact-commit [CI run38068653417](https://github.com/claudianus/SuperLuxCore/actions/runs/38068653417)
is in progress. Its four-platform wheels, CUDA compile, signed publication,
exact-artifact rendering and installed deployment are pending. Durable local
source/package identities, raw images and failed diagnostics are under parent
workspace `test-scenes/validation-2026-10-11/metropolis-startup`.

GPU adjoint transport, mixed/textured reverse reconstruction, spatial PDF/MIS,
Principled/Skin/Burley/legacy closure semantics, Normal/Bump/Volume integration,
production adapter exposure and broader production workflows remain in the full
goal. See the preceding [hybrid transport record](2026-10-10-cycles-bssrdf-hybrid-transport.md)
and the current goal registry. Full compatibility remains incomplete and active.
