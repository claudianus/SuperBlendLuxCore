# Principled Volume attributes, absorption and spatial coordinates

The volume compatibility goal remains open. Current Blender 5.2.1 LTS
(`9e2066aef7ef`) reproduces two independent defects: Principled Volume attribute
names do not drive the OpenVDB material, and Generated coordinates lose their
object context inside native heterogeneous volume evaluation. A separate
absorption-color prototype corrects the missing square root, with scoped CPU
evidence. That prototype has not been applied to repository runtime code or the
installed production adapter.

## Source and real Blender evidence

The adapter source for this audit is runtime revision `1db7211`, with
`cycles_node_reader.py` SHA-256
`943bec9e4a2d9f1c445677f3dcf2acc03def5d28defb649fe8e9ff95282cfb22`.
The diagnostic native is the signed ARM CI wheel built from `c2915a7`, native
SHA-256 `d5443cf5022c653d5636fa4b44ec246a60e39b0b65e2078e6135410949636024`.
The native source and active release-validation profile remain unchanged.

The reference source is the supplied `blender-5.2/intern/cycles` tree, specifically
`kernel/svm/closure.h::svm_node_principled_volume`,
`scene/shader_nodes.cpp::VolumeInfoNode::expand`, and
`scene/object.cpp::object_volume_density`. The installed Blender RNA was also
queried, rather than assuming the old attribute-name properties still exist.

| Input or behavior | Current observation | Required meaning |
| --- | --- | --- |
| Principled Volume Density/Color/Temperature Attribute | These are STRING inputs in current RNA. Standard, artist and absent names all export the same constant coefficients, without OpenVDB textures. | Multiply by the requested available field. A missing Principled attribute keeps the neutral multiplier used by Cycles. |
| Volume object material | `_material_volume_defs` accepts a subtree only when it contains Volume Info, so a plain authored Principled Volume is ignored. | Honor the authored volume material, including its ordinary coefficients and attribute names. |
| Generic STRING input | `_socket` converts an unlinked string into its first three characters as a list. | Preserve the whole string when adding attribute input handling. Current ShaderNodeTree group interfaces do not expose NodeSocketString in this Blender build. |
| Volume Info | Current code uses fallback grids and RNA properties absent from the queried node. | Cycles expands the four outputs to the fixed names `color`, `density`, `flame`, `temperature`; these differ from Principled's optional named multipliers. |
| Absorption Color | The adapter complements the raw color. | Cycles complements `max(sqrt(Absorption Color), 0)`; retain RGB channels before nonlinear math and spectral conversion. |
| Volume render space | RNA render properties have `space`, `step_size`, `clipping`, `precision`; display has `density`, without `density_scale`. | Cycles applies inverse instance scale in OBJECT space using the transformed normalized `(1,1,1)` vector. Display density is not part of Cycles volume source synchronization. |

## Absorption prototype and the failed spatial case

The test is an unchanged volume-only cube of depth 2 against a unit white world,
1280×720, 64 SPP, denoising and radiance clamping disabled for the numerical
measurement. A fixed eroded interior region excludes filtered silhouettes.
For RGB transport, the independent slab law is
`T = exp(-2 * max(1 - sqrt(Absorption Color), 0))` with Color=0 and Density=1.
The expected vector at `(0.04, 0.25, 0.64)` is approximately
`(0.2018965, 0.3678794, 0.6703200)`.

The prototype changes only the Principled absorption computation in its own
Blender process. Constant RGB mean-channel error is 0.0026%; a linked linear
color field with authored external Object coordinates has 0.0485% error; the
0/1/4 limits have 0.0032% error. Their original CPU PNGs were directly reviewed
at 1280×720. The linked native field retains visible heterogeneous-medium grain
at this fixed budget. The default spectral constant case also retained its
transmitted color and boundary in direct review; its difference from the RGB
slab formula is not treated as a spectral equality test or convergence proof.
Metal and broader production acceptance for this prototype remain unfinished.

The equivalent field using Generated coordinates fails by **32.75%** in the
largest mean channel. This result is retained, and the prototype is not accepted
for deployment. The authored field expects body mean
`(0.5032850, 0.4084698, 0.4549916)`; the native result is
`(0.3384663, 0.3863440, 0.5728420)`.

Native `HeterogeneousVolume` creates a fresh `HitPoint` for internal coefficient
evaluation. `HitPoint::Init()` clears the mesh; `HITPOINT_GENERATED` then falls
back to the object-space point. In this identity cube that is world X, instead
of the expected normalized `(worldX + 1) / 2`. The wrong-coordinate prediction
has mean absolute column error 0.00183, compared with 0.10160 against authored
Generated coordinates. This explains the spatial defect independently of the
absorption square root. A complete fix must preserve carrier context across
eye, light and shadow paths, shared materials, instances, transforms and volume
boundaries, without changing surface Generated evaluation.

## Reproduction artifacts and next validation

Local durable evidence is under workspace
`test-scenes/validation-2026-10-11/volume-attribute-audit`: real RNA and attribute
probes, failed source snapshots and EXR/PNG, independent column diagnosis,
prototype CPU metrics and direct image reviews. No result from these probes is
a claim of complete Cycles volume or scene compatibility.

Three small VDB fixtures cover named fields, a missing standard density grid,
and different grid transforms. Blender and native grid loading and metadata
agree after the native public `Init()` call. The standalone fixture build used
existing local dependencies; its owned children were reaped and the temporary
build folder was removed immediately. Retained VDBs and source are reusable
test inputs, rather than temporary build output.

Next work must implement named material fields and missing-field defaults,
per-grid mapping and carrier bounds, OBJECT/WORLD scale, the Generated volume
context defect, and CPU/Metal unchanged-scene acceptance. Current CPU prototype
successes do not close those scopes or switch the production SSS adapter.

## Completed Metal prototype follow-up

The same read-only CI profile subsequently completed nine 1280x720 images:
Cycles RGB references plus Metal RGB and default spectral renders for constant
absorption, the explicitly authored Object-coordinate gradient, and the
absorption limit case. All nine original PNGs were directly reviewed. The
three Metal RGB body errors against the analytic slab were 0.0025%, 0.1142%
and 0.0031%, within the fixed 1% operator gate. The cool-to-warm gradient,
cyan limit color and silhouettes remain visible in spectral mode, with grain
at 64 SPP. Spectral values are not gated against the RGB slab law: the HDR
Absorption Color blue value 4 differs by 67.5151% in the red channel mean.
This remains an explicit spectral colorimetry limitation, not an acceptance
of exact RGB equality or final converged color. No runtime reader was changed
or deployed. The Generated-volume context and named-grid defects remain open.
All prototype processes were reaped and the shared CI stage was removed after
its independent deployment and preservation checks.
