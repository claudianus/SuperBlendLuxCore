# Cycles VDB named attributes, affine grids and sequence frames

Principled Volume's Density/Color/Temperature Attribute strings previously
had no effect on imported VDB objects. A material without a Volume Info node
was skipped, strings could be truncated to three characters, and all grids
borrowed the density grid's coordinates. VDB materials now convert their
authored volume subtree, including groups, and request the exact named grids.
Missing Principled attributes are neutral (one); Volume Info uses the fixed
standard names and missing values are zero. An empty Volume output creates no
carrier. Generic geometry Attribute nodes resolve VDB fields inside this
conversion context. Node texture names include the evaluated instance context
so shared materials do not share the wrong grid mapping.

Each grid uses its own OpenVDB index-to-object affine matrix and the evaluated
instance matrix. Carrier bounds cover the requested grids with interpolation
padding. OBJECT density uses Cycles' transformed normalized diagonal direction;
WORLD density does not scale with the object. This applies to absorption,
scattering and emission. Display density is not a render coefficient.
Conversion metadata is scoped to one instance and released after conversion.
The bounds surface is null: an index-matched glass surface invented dielectric
and caustic paths, including energy exceeding one in the passive colored slab.
The null surface restores CPU/Metal agreement without changing quality defaults.

Topology comes from fields actually used by the volume shader. Principled
implicit attribute requests are retained, while an explicit Density multiplied
by zero cannot invent bounds for an otherwise topology-free emitter. Pure
emission is still valid when the temperature field requests real topology.
Native finite zero-extinction emission integration and Metal edit initialization
are required; engine source commits are `131c84733` and `48c8c6217`.

Sequence resolution now uses Blender's evaluated `VolumeGrids.frame`. Blender
applies start/duration/loop mode before the offset, and filenames retain their
numeric padding. CLIP outside the duration is empty; missing frame files remain
missing. Directory order no longer shifts frame numbers or fills missing frames
with a different file. This also fixes the actual `PING_PONG` enum. A cached
volume retains its source/frame signature, and scene-frame changes refresh
sequence volumes even when a second depsgraph evaluation has consumed update
flags. Removing a stale carrier issues native DeleteObject before re-export.

Evidence is in `../test-scenes/validation-2026-10-11/vdb-attributes/`:

- Named/missing fields, fixed Volume Info outputs, dead explicit topology and
  independent affine coordinate probes pass in Blender 5.2.1.
- 720p scalar density, missing density, shared instances and affine-grid
  diagnostics preserve the authored graphs. These are feature diagnostics,
  with separate historical profile identities.
- The null-carrier colored slab and constant-color control agree within
  0.001783% on CPU and 0.003113% on Metal hybrid. CPU/Metal brightness agrees,
  and passive output no longer exceeds one. The Cycles RGB blue comparison
  still differs by 6.78%; colored transport and edge fidelity remain open.
- Actual named-temperature and missing-temperature tests: 12 frames each on
  CPU and pure Metal, 1280 by 720 at 16 SPP, RGB and default spectral mode.
  Field/control error is at most 0.0632% CPU and 0.0278% Metal. Finite emission
  is nonzero again. These samples do not certify final convergence or absolute
  blackbody radiation units. High-radiance Standard previews clip, so numerical
  gates use the raw EXR channels.
- 85 sequence metadata conditions use the actual evaluated Blender loader as
  the oracle across CLIP/EXTEND/REPEAT/PING_PONG, offsets, gaps and zero duration.
  The old resolver fails 73 conditions; the candidate fails none. Temporary
  sequence files are removed after each run.

`dev-tools/cycles-vdb-attributes-test.py`, `cycles-vdb-sequence-test.py`,
`cycles-vdb-live-edit-test.py` and `vdb-attribute-fixture/` reproduce these
checks. Live comparisons wait for 64 **eye** SPP; total SPP includes light
paths and is not the configured eye halt. Earlier live diagnostics without
explicit eye/light counts are narrower evidence. Earlier sequence restoration
diagnostics used correlated same-seed repeats. The fresh frame's animated
seed differed from the edited session's seed, producing a different noise
pattern and a false relative-difference failure even at actual 64 eye SPP.
The corrected driver explicitly uses independent repeat seeds, retains the
original tolerances and records raw central-region noise and configuration.
Native film resets also clear the old luminance moments while preserving
them across thread-film merges. This is not a final convergence result.

Remaining gates include native dense-grid edge reconstruction, Generated
volume coordinates, more volume composition/overlapping media, larger real
simulation grids, GUI redraw and full production scenes/platforms. An earlier
thermal harness read an absent RGBA pass as zeros; those zero-radiance frames
are invalid and are not accepted. Full Cycles scene compatibility remains
active and incomplete; this document does not claim 99% compatibility.
