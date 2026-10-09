# Existing Cycles Bump remaining contracts

The next Bump implementation is grounded in a 1280×720 signed Normal-pass
audit of existing Cycles graphs on Blender 5.2.1 and private 2.11.19. CPU and
actual Metal each ran thirteen RGB and six standard spectral conditions.
All 38 outputs were finite and renderer-error-free; only sixteen met the
combined 0.005 component-MAE and no-conversion-warning gate. This is an audit
of defects, not a compatibility pass. Both comparison sheets were inspected;
PNG display clips signed negative components, so metrics use raw EXR.

| Contract | CPU RGB MAE | Metal RGB MAE | Finding |
| --- | ---: | ---: | --- |
| Constant Distance control | 0.00005134 | 0.00005274 | Preserved in this fixture |
| Linked constant Distance | 0.00001204 | 0.00001446 | Unsupported warning; its default equals the linked value |
| Spatial Distance | 0.01052310 | 0.01053065 | Input ignored |
| Linked Normal Map base | 0.20864022 | 0.20864375 | Input ignored |
| Chained Bump | 0.02561144 | 0.02561262 | Base Normal ignored |
| Bump output through Vector Math | 0.55078137 | 0.55075127 | Height data used where direction data is required |
| Bump output through Mix | 0.20634457 | 0.20634307 | Incorrect direction data |

The standard spectral failures closely reproduce RGB. Strength above one,
negative Strength, Invert, backface and individual half/two Filter Width
controls pass in this smooth plane fixture. That does not validate general
filtering: the current adapter uses the maximum width over the material tree,
which cannot represent independent widths in a Bump chain.

Installed Cycles source (`9e2066aef7ef7e20c142ad7bd3303138a4304c93`,
`intern/cycles/kernel/svm/displace.h`) applies linked Distance after Height
differences, preserves a linked base Normal, normalizes the perturbed result,
then blends with nonnegative Strength. Multiplying a spatial Distance into
Height before differentiation would introduce a spurious Distance gradient.
The dedicated adapter must expose direction data for Math/Mix, evaluate raw
inputs with spectral conversion paused, and retain per-node filter width.

Evidence: workspace
`test-scenes/validation-2026-10-09/cycles-scene-goal-phase16`.
The baseline harness and logs are preserved there; `SUPERLUXCORE_AUDIT_BASELINE=1`
collects failures explicitly rather than claiming a strict pass. C30 remains
incomplete. These defects are not fixed by the 2.11.19 Normal Map/Diffuse work.
