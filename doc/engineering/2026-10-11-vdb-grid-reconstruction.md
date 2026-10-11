# Cycles VDB index reconstruction and filtered RGBA attributes

Existing VDB textures resampled the leaf-node box with OpenVDB's quadratic
sampler before native trilinear evaluation. The last inclusive sample, isolated
active voxels, negative coordinates, tile-only grids and authored filter support
could therefore change. The Blender bridge now requests an explicit index-grid
mode: original integer values are read once and filtered at the shading point
with the material's Linear or positive cubic B-spline setting.

This feature unit does not complete the existing Cycles-scene compatibility
goal. Deployment and actual-profile render acceptance remain pending until the
signed build and render evidence recorded below are complete.

## Reconstruction contracts

- `GetOpenVDBGridInfo(path, name, active_bounds=True)` reports the original
  inclusive active-voxel box. The existing two-argument metadata API and legacy
  `densitygrid` OpenVDB resampling mode retain their previous interpretation.
- `openvdb.mode=index`, `openvdb.padding=N` validate the requested dimensions
  against that original box, then use integer accessor reads. Active tiles,
  inactive stored values and the grid background survive extraction.
- Float, Double, Int32, Int64, Bool, Vec3f, Vec3d, Vec3i and Blender's custom
  `Tree4<Vec4f,5,4,3>` are supported. The Vec4 tree registers before metadata and
  voxel loading. `openvdb.component=alpha` preserves authored Vec4 alpha;
  existing scalar/Vec3 attributes carry alpha one while retaining their grid
  request and carrier topology. Missing attributes remain zero.
- Lookup uses `u*N`, with no half-voxel shift. Linear reads floor and floor+1;
  cubic reads floor-1 through floor+2 with positive cardinal B-spline weights.
  Physical carrier padding is one/two voxels respectively. Cubic dense read
  padding is three, so inactive stored samples beyond the carrier remain in
  the complete stencil. The texture's exclusive endpoint is independent of
  the carrier's bounds.
- GPU textures carry the filter in their compiled descriptor. CPU and GPU
  cubic Clamp fractions stay bounded, and Repeat wraps every stencil tap.
  Existing default Linear interpolation arithmetic is preserved.
- Box bounds include every filter tap, accept the lower coordinate zero,
  include the outside value one for White-wrap minorants, and conservatively
  scan the full grid for nonfinite transformed box corners. Cubic bounds add
  a small float-roundoff margin; the native delta/residual-ratio estimator and
  default quality settings remain in use.
- Serialization preserves all RGB channels, float storage and interpolation.
  The Blender bridge unpremultiplies RGBA **after interpolation**, only when
  alpha exceeds 1e-6, using a safe divisor. Attribute Color/Vector/Fac, Volume
  Info and Principled's implicit field readers share this filtered-value path.

## Source and installed-version distinction

The supplied Blender source is `/Users/modumaru/Desktop/code/blender-5.2`,
commit `d13f752e3b9c4f8c261cda552b1021f8bcc0382c`. The installed Blender is
5.2.1 LTS build `9e2066aef7ef`. Source references include
`intern/cycles/scene/image_vdb.cpp`, `kernel/util/image_3d.h` and
`kernel/geom/volume.h`; actual operator renders independently exercise the
installed application.

Validation lives in
`test-scenes/validation-2026-10-11/vdb-grid-reconstruction` at the workspace
root. `SuperLuxCore/dev-tools/vdb_grid_contract.py/.cpp` uses a separate fixture
authoring process and an independent numeric oracle. Evaluation does not
register the Vec4 grid before the native parser, so a missing registration
cannot be hidden by the oracle.

The first installed-baseline run failed all 26 requested new index/filter
conditions. Those conditions ask for an opt-in API absent from that release;
this is a targeted regression baseline, not a global compatibility percentage.
It also reproduces concrete old behavior: the last voxel and isolated voxel
read zero, negative-coordinate last value reads 6.25 instead of 8, and a
tile-only query reads .5 instead of .375. Double/integer/bool/other vector grids
fail loading, RGB serialization loses channels, and float storage is lost.

## Acceptance status

The staged whole native payload passes 44 independent conditions, 136 point
samples, 14 active-inclusive metadata checks, 176 carrier-box checks with
22,000 independent samples, and 44 infinite-box checks. Serialization and
explicit finite-value checks pass. The per-component numeric budget is
`2e-6 + 8*FLT_EPS*abs(expected)`; the maximum observed absolute error is
3.65575e-6 at a value near eight, within 0.384 of its budget. Conservative
bounds retain their separate 2e-6 comparison tolerance. The initial generic
Clamp case used an over-strict fixed absolute budget; its failed evidence is
retained before the principled relative float allowance. A metadata-test tuple
index error was corrected independently of the native implementation.

The staged Blender adapter export probes pass on installed Blender. The first
boundary harness stopped after a successful Cycles render because `.blend`
saving changed an absolute filepath to a relative one. File identity is now
checked through its resolved path; that stopped run is retained separately.
The initial replacement candidate's unchanged-graph 1280x720 Linear/Cubic boundary renders pass on native CPU
and pure Metal, with a separate Cycles CPU reference for each case: four
records per route, eight records in total. Native eye sampling completed at
64 or more samples. Raw boundary-profile mean error against Cycles is
0.002005/0.002520 on CPU and 0.005887/0.006863 on Metal, within the fixed
0.012 mean and 0.04 maximum profile budgets. All eight original PNGs were
directly reviewed and hash-bound in `readonly-boundary-visual-review.json`.
Orientation, last-plane extent and smooth support are correct; the native
64-sample diagnostic is visibly noisier than Cycles. These RGB diagnostics
compare spatial/transport meaning and do not establish production convergence
or pixel identity. Default spectral settings were restored after both workers.

The installed Blender itself rejects the external custom-Vec4 fixture before
native import (`grids.load() == false`, `Unknown error reading VDB file`, no
grids). The known scalar/Vec3 control loads successfully. Accordingly the
first all-black Cycles RGBA render is retained as a failed reference, not
accepted as an RGBA parity result. Cycles' internal RGBA voxel path and the
native independent numeric contract do not prove that Blender's external
VDB-object loader accepts that type. Native RGBA RenderEngine acceptance
against the independent analytic oracle, signed four-platform publication
and actual-profile acceptance remain pending. The RGBA diagnostic also found
an adapter defect: Blender 5.2 displays the stable `Fac` identifier as
`Factor`. The old name-only branch returned RGB instead of an arithmetic
average. The adapter now accepts the stable identifier and both display
names; Linear CPU/Metal renders confirm Color/Vector/Fac/Alpha independently.

The initial four-point pixel-footprint oracle missed a cubic alpha-guard
transition inside one pixel and rejected the correct native image. Independent
cardinal-polynomial integration locates that crossing at
`x=0.3764308937559173`. Streaming 16,384 horizontal samples on the gated
constant-z rows and 8,192 edge samples resolve it; a separate 4,096-to-16,384
check must remain below 0.0001. The original 0.012/0.04 render gates are
unchanged. Failed metrics remain intact beside the convergence evidence and
separate reassessment. Black output, RGB substituted for Fac and constant
Alpha still fail the independent oracle. Fresh final-binary renders are
required before acceptance.


The first staged native candidate passed those CPU numeric checks but crashed
in both actual Blender CPU/Metal routes after Cycles had rendered. The native
OpenVDB registered accessor destructor reached `tbb::concurrent_hash_map`
registry erasure and `libtbbmalloc` free. That candidate was rejected before
main, publication or installation; its 404,747,460 logical bytes of temporary
profile were removed after all owned workers had terminated and been reaped.
The crash backtrace and failed metrics remain as evidence.

Extraction now uses one unregistered const cache per worker on the exclusively
owned immutable loaded tree. OpenVDB only requires registration when topology
may mutate; extraction performs no topology mutation, the owning grid survives
the OpenMP barrier, and delayed leaf loads use OpenVDB's own synchronization.
This removes the registered TBB map from the crashing path while retaining
integer value semantics. New whole-payload Blender acceptance is required;
old numeric success is not promoted to render success. The replacement
whole-payload CPU/Metal boundary workers above both finish successfully.
An additional actual Blender factory worker initializes Cycles, loads six
known scalar/Vec3 grids through Blender, explicitly preloads Blender's lazy
TBB allocator, then imports the exact candidate. All 180 native
parse/serialize/destroy operations across 14 numeric grids and the RGBA grid
complete in three rounds. dyld fingerprints record both distinct host and
packaged TBB/TBBmalloc libraries. This is a targeted regression check of the
extraction path, not proof that all allocator coexistence paths are safe.

The first verified native change is on main and GitHub at
`f683200cb982b2c3da728cfb231e3b9042c4f9be`. Its CI caught CUDA `float4`
subscripting in the cubic weight lookup: 19 of 23 programs compiled, so no
wheel publication occurred. Portable component selection is committed at
`ed9aebd4fc901bc5bb5d3787eb4303b767eca87e`; the subsequent CI CUDA gate
passes. The new local whole-payload binary
`e04d60b9011933cfd383a96219b5e774c552ea58d49ebe8c6bb97c6383590503`
passes all 44 numeric conditions again. Fresh unchanged-graph boundary
operator renders pass on CPU/pure Metal (four records each); profile mean
errors against Cycles are 0.001993/0.002480 and 0.005883/0.006857 respectively.
Fresh native-only RGBA Linear/Cubic renders pass on both routes (two records
each): maximum gated panel errors are 0.000161/0.001123 on CPU and
0.000129/0.000441 on Metal. These retain the independent analytic reference,
fixed gates and explicit unavailable Cycles external-Vec4 reference. All 12
original PNGs were directly reviewed, with SHA-bound reviews beside the
portable metrics. Default spectral/device preferences were restored.

The upgraded isolated host-first check again passes 180 conversions. Twenty
independent affine export points and three Alpha/topology export probes also
pass. Every fresh worker measures unchanged actual payload (192 files), all
374 Python files, three settings and one cached whole wheel. The isolated
load-order devtool is committed separately at `adba86f43`; compiled sources
remain those of `ed9aebd4fc901bc5bb5d3787eb4303b767eca87e`.

The installer now requires the corresponding reaped worker, measured
preservation artifact, exact driver/fixture hashes, authored-state preservation,
restored preferences and complete direct PNG review coverage. A local-only
schema diagnostic accepts those portable records and rejects seven invalid
binding/preservation/backend/review cases. It supplies no signature or
deployment approval. Exact signed-wheel and actual-profile acceptance remain
pending.

During concurrent Blender validation, all 192 actual engine-package files
were unexpectedly removed while adapter files, settings and the cached
signed wheel remained unchanged. The actual extension compatibility cache
contained SuperLux alone; Blender's wheel manager removes packages when the
required wheel list is empty. The responsible process is not conclusively
identified. Missing-only recovery verified the old signed publication,
streamed every original wheel/RECORD entry, and restored all 192 exact files
without overwriting existing data. `actual-baseline-recovery.json` records
the recovery and temporary-file cleanup. The actual profile is again on its
preceding signed native deployment.

Future workers explicitly set CONFIG, EXTENSIONS and RESOURCES, assert their
resolved Blender paths before addon activation, and hash the actual engine,
374 adapter Python files, three settings files and cached wheel before/after
every render. Older state files' `production_profile_modified=false` expressed
intent rather than a measured preservation result. New states bind the full
comparison artifact by SHA; a concurrent deletion fails acceptance.

## Remaining volume work

[The current carrier-coordinate audit](2026-10-11-volume-coordinate-carrier-audit.md)
tracks Generated/Object carrier ownership, world media, shared instances,
motion and conservative instance-aware bounds. Additional source-confirmed
limits stay explicit:

- Render clipping is active-topology processing, not zeroing stored values.
  Disconnected carrier support and overlap composition need independent work.
- The current carrier encloses transformed grids in an object-space AABB.
  A sheared/rotated internal VDB affine grid can require a parallelepiped;
  constant emission or nonzero background exposes the extra medium. An object
  or collection-instance shear test alone does not close this case.
- Material selection must eventually share Cycles' first volume-capable used
  shader, null-slot/default-volume behavior and view-layer material override.
  This unit's authored render fixtures use one volume-material slot.
- Large sparse simulations still expand to a dense reconstruction image.
  The numeric grid-type fixtures do not prove broad simulation memory use.
- GUI redraw, broad production scenes, animation combinations and runtime
  acceptance on the other three packaged platforms remain open.
