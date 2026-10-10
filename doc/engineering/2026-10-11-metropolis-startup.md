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
The signed exact-CI rolling wheel is now installed in the actual Blender
site-packages and complete wheel cache. The installed native SHA256 is
`8c05e75cf59e5c2577a55b5d2426531731ac924e40af983836a405f120ea96a2`,
and whole wheel SHA256 is
`7a5d8e3f45e83291b4a3543270fd033a7581f1192766699ec275eee9880ab62a`.
Metadata remains 2.11.27. All 266 runtime Python files, 374 Python files including
developer tools, and user settings were preserved. The production Cycles reader
remains SHA `7dd35540ac9a1fcffdbd4b1aeb2684957f51164e799a30b93cc6d271fcb6a235`.

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
completed all four-platform wheels, CUDA NVRTC compilation, attestations and
[rolling publication](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-latest).
The signed statement identifies native source commit2536c5169 and all four
published wheel digests. The complete unmodified ARM CI artifact independently
passed CPU50/hybrid23, CPU50/rough22/sharp18, actual Metal57, ordinary PSR3,
guarded emission/MNEE15 and CPU black-film halt3. Maximum channel-mean errors
were1.1821% hybrid,2.5111% rough adjoint and0.7177% sharp adjoint. Declared3%
gates and sample budgets were unchanged; no transport reruns or threshold
relaxation were used.

Twelve original1280x720 CI Cycles/native PNGs were directly reviewed with the
authored graph fingerprints unchanged. Against this wheel's independent CPU
eye, body-region errors were0.8944%/0.4744% for sharp/rough hybrid and
0.9204%/0.0864% for Metal eye. Chromatic hybrid grain remains conspicuous. These
private diagnostics retain unsupported-transport limits and do not promote
production SSS quality or exposure.

Before installation, the actual stable adapter with the complete new CI core
passed an ordinary-material CPU/Metal1280x720/128-sample preview, directly
reviewed as two original PNGs. After installation, fresh Blender5.2.1 LTS/build
9e2066aef7ef loaded the exact CI native; complete wheel payload/cache and
adapter/settings identities were rechecked. Actual CPU/Metal1280x720/128-sample
spectral renders of Principled,4D Voronoi,coat,sheen,blue glass and area lights
completed with finite raw pixels and no exporter errors. Both original images
were directly reviewed; their maximum relative channel-mean difference was
0.1246%. The known Eevee-only probe flags are reported as ignored warnings.
The installed PSR3 regression also passed, and fresh registration was checked
again afterward. Residual grain remains at this denoiser-off budget; no general
convergence or performance improvement is claimed. GUI hot reload is unverified.

The previous complete CI wheel with native SHAaba55215/wheel SHA814210ce is
preserved and verified as a rollback reference without another duplicate.
An initial preflight inventory diagnostic stopped before writes because runtime
files and installed developer tools were compared as one inventory; its failure
record is preserved, the scope was corrected, and all374 Python files were
subsequently checked unchanged. It is excluded from product render evidence.

Completed CI and preview temporary profiles were removed after full-payload
and source checks; all owned render children completed and were reaped. Durable
whole wheels, source/package identities, original raw images, signatures,
metrics and failed diagnostics are under parent workspace
`test-scenes/validation-2026-10-11/metropolis-startup`. This deploys the common
sampler repair; it does not replace the existing artist stable ZIP or switch
the positive-radius production SSS adapter.

GPU adjoint transport, mixed/textured reverse reconstruction, spatial PDF/MIS,
Principled/Skin/Burley/legacy closure semantics, Normal/Bump/Volume integration,
production adapter exposure and broader production workflows remain in the full
goal. See the preceding [hybrid transport record](2026-10-10-cycles-bssrdf-hybrid-transport.md)
and the current goal registry. Full compatibility remains incomplete and active.
