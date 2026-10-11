# Volume Generated/Object coordinates and carrier ownership

This is a source audit, not implementation or current-render acceptance. It
inspected SuperBlendLuxCore `4549a8ee57756c20c3b63213d5f5fb6b83071520`,
SuperLuxCore `940b8916f1fa02d0972a197c09edfaa8018b8d39`, and the supplied local
`/Users/modumaru/Desktop/code/blender-5.2/intern/cycles` source at
`d13f752e3b9c4f8c261cda552b1021f8bcc0382c` on 2026-10-11. That supplied
source tree is a source reference; its HEAD is not the installed Blender build
fingerprint.
No native source was changed and no build, render or deployment was performed
for this audit. The changes described below remain proposed.

The previous [volume source and prototype audit](2026-10-11-volume-source-and-prototype-audit.md#absorption-prototype-and-the-failed-spatial-case)
retains a real 1280x720 Generated-coordinate absorption failure of 32.75% in
the largest mean channel. That result used the older diagnostic profile named
in that report; it is not a rerender of the currently installed release. This
inspection confirms that the relevant coordinate-context defect remains in
the current native source.

## Confirmed source path

Paths below are relative to the named repository; line numbers refer to the
revisions above and will move when implementation changes them.

| Behavior | Source reference | Consequence |
| --- | --- | --- |
| Explicit Texture Coordinate Generated exports `hitpoint.generated`. Object without an external object exports `hitpoint.objectspace`. | SuperBlendLuxCore `export/cycles_node_reader.py:3376-3392`. | Both depend on the native shading point retaining its carrier. |
| Default procedural coordinates also export Generated. | SuperBlendLuxCore `export/cycles_node_reader.py:491-497`; Noise and Wave at `3655-3659`, `3824-3828`. | The defect includes unchanged procedural volume shaders with no Vector connection. |
| An explicit external Object coordinate already transforms `hitpoint.worldpos`. | SuperBlendLuxCore `export/cycles_node_reader.py:3377-3380`, helper `856-865`. | That independently authored path explains why the previous control could pass while Generated failed. It does not fix implicit Object/Generated. |
| CPU Generated reads the base mesh Generated transform; without a mesh it returns the inverse-localToWorld point. | SuperLuxCore `src/slg/textures/hitpointfield.cpp:78-104`. | A fresh volume point defaults to world/object identity coordinates instead of the authored normalization. |
| HitPoint default initialization clears `mesh`. | SuperLuxCore `src/slg/bsdf/hitpoint.cpp:111-122`. | Copying only the point position cannot recover Generated context. |
| Majorant construction, march scatter, march transmittance, delta scatter and ratio transmittance create fresh coefficient HitPoints. | SuperLuxCore `src/slg/volumes/heterogenous.cpp:298`, `484`, `534`, `585`, `753`. Clear/homogeneous have corresponding fresh points. | All coefficient-evaluation paths need the same context, including shadow attenuation and finite-segment emission. |
| CPU scatter BSDF sets `sceneObject=nullptr`, `mesh=nullptr`, `triangleIndex=NULL_INDEX`; GPU uses carrierless counterparts. | SuperLuxCore `src/slg/bsdf/bsdf.cpp:220-244`, `include/slg/bsdf/bsdf_funcs.cl:145-176`. | Phase/albedo evaluation at a scatter vertex also loses context; fixing only ray attenuation is incomplete. |
| GPU temporary volume initialization resets the point and transform. | SuperLuxCore `include/slg/volumes/volume_funcs.cl:42-66`. | The shared OpenCL/Metal/CUDA implementation needs matching propagation. Preserve the spectral-state save/restore already present. |
| GPU Generated directly indexes `meshDescs[meshIndex]` without a NULL guard. | SuperLuxCore `include/slg/textures/texture_funcs_evalops.cl:2080-2105`. | Carrierless volume/world evaluation has an invalid-access risk. This is source-confirmed, not a newly reproduced GPU crash. CPU already has a carrierless fallback. |
| The current path stack contains only Volume pointers/indices and priority state. | SuperLuxCore `include/slg/utils/pathvolumeinfo.h:90-95`, `include/slg/utils/pathvolumeinfo_types.cl:24-28`; updates in `src/slg/utils/pathvolumeinfo.cpp:158-175` and `include/slg/utils/pathvolumeinfo_funcs.cl:133-155`. | Two instances sharing a material cannot retain distinct texture coordinates after crossing their boundaries. |

## Cycles meaning to preserve

Cycles `kernel/integrator/volume_shader.h:449-472` assigns the object from each
volume-stack entry and sets its transforms at the shader ray time. This is
per-path/per-instance context, not one transform stored on a shared material.
The initial volume ShaderData also retains an object in
`kernel/geom/shader_data.h:433-452`.

`kernel/svm/tex_coord.h:161-168` returns world position for a carrierless
volume Generated coordinate. For a carrier,
`kernel/geom/volume.h:30-43` first applies the inverse object transform and then
the `ATTR_STD_GENERATED_TRANSFORM` attribute, when available. It does not clamp
the resulting coordinate to [0,1].

For mesh carriers, `blender/mesh.cpp:838-849` requests that normalization from
mesh texture space, including custom texture space. The helper
`blender/util.h:532-551` defines the scale and offset. The adapter already
exports the equivalent custom normalization in
`export/mesh_converter.py:161-168`, via `generated_transformation` at line 302.
Native `src/luxrays/core/exttrianglemesh.cpp:602-607` composes it with the base
mesh's applied transform; its existing surface evaluation handles baked direct
meshes versus instance/motion wrappers. Reuse this mapping rather than replacing
it with per-part bounding boxes.

For VDB carriers, Cycles `blender/volume.cpp:412-422` uses
`BKE_volume_min_max` and the matrix
`scale(1 / (max-min)) * translate(-min)`. The current adapter's carrier box in
`export/volume.py:330-342` encloses shader-used grids, so deriving Generated
from that box can disagree with the whole Blender volume bounds. A VDB
coordinate implementation must explicitly retain the appropriate normalization
independently of the carrier box used for ray support. The precise RNA access
to the full evaluated volume bounds has not been runtime-validated by this audit.

## Recommended shared-backend implementation

1. Retain carrier identity alongside each volume-stack entry and the selected
   current volume. CPU can retain a scene object/mesh reference; GPU can retain
   an index. Full transforms need not be stored per entry: existing mesh APIs
   sample them at `ray.time` (`ExtMesh_GetLocal2World` in
   `include/luxrays/core/exttrianglemesh_funcs.cl:620-643`).
2. Capture the carrier on a boundary crossing and remove the `(volume, carrier)`
   pair on exit. Removing only the volume pointer can pop the wrong instance
   when two carriers share that pointer. Preserve the current priority rules.
3. Resolve the carrier of the selected segment in CPU `Scene::Intersect`
   (`src/slg/scene/scene.cpp:914-964`) and GPU `Scene_Intersect`
   (`include/slg/scene/scene_funcs.cl:81-163`). Handle an initial exit hit when
   the camera starts inside a carrier and has no prior stack entry; world/default
   media retain no carrier.
4. Seed coefficient HitPoints and the scatter BSDF's texture context with the
   carrier mesh and time-dependent localToWorld. Use `triangleIndex=NULL_INDEX`
   and explicitly skip surface-plane projection for volume points. Preserve
   material/isVolume, PDFs, phase functions, random draws, tracking and spectral
   state. Do not convert a volume vertex into a surface vertex.
5. Give GPU Generated a safe carrierless fallback matching CPU/Cycles world
   position. Preserve surface triangle-plane correction and custom Generated
   normalization; do not clamp Generated coordinates.
6. Carry the same context into bound construction before accepting delta
   tracking. `src/slg/scene/parsevolumes.cpp:189-197` makes delta the default;
   `src/slg/scene/scenepreprocess.cpp:297-327` currently unions all carrier world
   bounds and builds one grid per shared Volume. Fresh bound samples at
   `heterogenous.cpp:298` cannot represent distinct carrier transforms. Compute
   each world cell's support and bounds across the relevant carrier contexts,
   retaining safe minorants and existing weighted tracking. A ray-point fix with
   context-free zero-support cells can silently skip real extinction. Forcing
   global march mode is not an acceptance substitute for this requirement.

## Acceptance gates and independent limitations

- Rerender the unchanged Generated absorption slab and its explicit external
  Object-coordinate control at 1280x720 or above. Compare raw RGB columns and
  interior means with the independent analytic law, keeping the historical
  failed images. A black/nonfinite image must not pass based on file existence.
- Use one shared material on translated, rotated, nonuniformly scaled and
  sheared carriers, including mesh instances, custom mesh texture space and a
  multi-material partition. Retain authored spatial fields in all of them.
- Cover camera-inside, light-inside, shadow transmittance and repeated scattering.
  The same context must reach albedo and textured anisotropy as well as
  extinction/emission. A single eye-ray absorption render does not cover them.
- Cover explicit Generated, implicit procedural Generated, implicit Object and
  explicit external Object, including linked node groups and live transform/
  texture-space changes. Use a VDB with different whole-volume and shader-used
  bounds to expose accidental carrier-bounds normalization.
- Exercise majorant support whose extinction is zero under world-coordinate
  evaluation but nonzero under Generated evaluation; repeat with two carriers
  sharing the same Volume. Include motion-time context and a safe carrierless
  world-coordinate probe.
- Validate actual CPU and Metal RGB output, default spectral output and original
  images at 720p or above; verify installed whole-wheel/library fingerprints and
  unchanged quality defaults. Low-SPP output is scoped evidence, not final
  convergence or broad production acceptance.
- Recheck surface Generated/Object behavior so stable plane zeros, tangent bump
  offsets and custom texture-space normalization are preserved.

The existing native volume priority model selects one medium; Cycles sums
overlapping media. Carrier propagation does not itself solve that separate
compatibility scope. Cycles From Instancer Generated is also a distinct constant
coordinate path (`scene/shader_nodes.cpp:4098-4109`,
`kernel/svm/tex_coord.h:153-155`); the current adapter reader does not inspect
the corresponding flag. That behavior remains open.

Textured world volumes have a separate segment-constant limitation in adapter
`export/world.py:65-72`. Passing a carrierless coordinate probe does not close
full heterogeneous world rendering. No result of this source audit is a claim
of complete Cycles volume compatibility or approval for deployment.

## Related VDB render clipping audit

Clipping changes support topology; it is not a pointwise threshold on sampled
grid values. This distinction matters for an exact-index VDB accessor and for
the carrier used by procedural/constant volume coefficients.

The supplied Blender `source/blender/makesdna/DNA_volume_types.h:100-104`
defines VolumeRender defaults: HALF precision, OBJECT space, step size 0 and
clipping 0.001. RNA `source/blender/makesrna/intern/rna_volume.cc:562-570`
exposes clipping with range [0,1]. Cycles passes it from `b_render.clipping`
to the VDB loader in `intern/cycles/blender/volume.cpp:395-401`; the loader
itself also defaults to 0.001 (`scene/image_vdb.h:29-33`, line 65).

`intern/cycles/util/nanovdb.cpp:284-294` bypasses clipping entirely for exactly
zero. Otherwise it deep-copies the converted grid and calls
`openvdb::tools::deactivate(copy, ValueType(0), ValueType(clipping))`, then
converts that copy to NanoVDB. It never writes replacement numeric values.
The implementation was cross-checked in the existing local OpenVDB 12.1.1
and 13.0.0 headers under SuperLuxCore
`out/dependencies/full_deploy/host/openvdb/<version>/Release/armv8/include`:

| Case | Exact source behavior |
| --- | --- |
| Scalar active value/tile | Deactivate if `abs(value) <= clipping`, including negative values and equality. `tools/Activate.h:129-160` uses `math::isApproxEqual`; `math/Math.h:406-408` in 12.1.1, `431-433` in 13.0.0. |
| Vector active value/tile | Deactivate only when every component is within the absolute tolerance. This is equivalent to `max(abs(component)) <= clipping`, not average, length or minimum. `math/Vec3.h:583-587`; Vec4 has the corresponding four-component conjunction. |
| Inactive stored value/tile | Not visited by this operation. Iterators are `beginValueOn`. |
| Values and allocation | `setValueOn(false)` changes activity without setting values; no prune is called by this operation (`tools/Activate.h:203-223`). |
| Clipping zero | Cycles returns the original grid without running deactivate; it therefore preserves zero-valued active topology too. |

Cycles' kernel accessor does not gate the numeric result on the active mask:
`intern/cycles/kernel/util/nanovdb.h:330-353` returns tile or leaf stored values;
`219-221` reads the leaf value array. Thus the accessor must retain stored
inactive values and backgrounds. An exact-index dense accessor must not zero
each value below clipping or reject an interpolation corner merely because it
is inactive. The conversion library's entire NanoVDB serialization was not
independently compiled or runtime-probed in this audit; the directly confirmed
operations above already exclude interpreting clipping as a sampler threshold.

There are two separate domains. `scene/image_vdb.cpp:62-64` takes image metadata
bounds from the original OpenVDB grid after conversion setup; the clipped copy
belongs to NanoVDB, not that original pointer. The volume carrier, however, is
built from the NanoVDB active mask: `scene/volume.cpp:180-203` extracts and
unions those masks, and `654-692` adds the shader-requested voxel grids.
LINEAR interpolation pads the mask by one voxel; CUBIC pads by two
(`629-634`, `205-210`). Empty combined topology yields no carrier (`686-689`).
Changing texture mapping/normalization to a clipped active bounding box would
therefore shift surviving coordinates. Reducing carrier support to one clipped
global AABB is only partial equivalence for disconnected topology and constant
emission across gaps.

To preserve artist-authored render meaning, propagate render clipping into
support/topology construction and its cache identity separately from numeric
sampling. Useful regressions are positive/negative values just below/equal/above
0.001, a vector with one component exceeding the threshold, an all-subthreshold
grid with constant emission, inactive nonzero stored values next to retained
active values, zero-valued active topology with clipping 0, and disconnected
grids sharing an AABB. Retain ordinary inactive/background interpolation values;
compare carrier support and raw samples independently. No clipping implementation
or new render acceptance is claimed here.
