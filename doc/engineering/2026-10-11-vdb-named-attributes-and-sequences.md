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
Relative VDB paths belonging to linked data resolve from the owning Blender
library; resolving them from the open main file silently dropped linked media.

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
- A linked-library path contract uses the actual Blender loader and separate
  library/main directories. Both previously failing frame conditions pass;
  its temporary library, main file and VDB hard link are removed.

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

The final signed engine (`940b8916f`) and adapter feature source (`6e25c119`)
are on main. [Engine CI](https://github.com/claudianus/SuperLuxCore/actions/runs/38098862456)
passed the four platform builds, CUDA compile gate, attestations and rolling
wheel publication. [Latest bundle CI](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/38100576850)
published all four signed archives. The ARM archive's 386 Python files match
the feature commit, and its whole engine wheel matches the final signed wheel.
The other three archives have verified signed subject digests; their runtime
rendering was not exercised locally. The release remains a prerelease.

The actual Blender 5.2 profile now contains that whole 192-file engine payload,
the matching cached wheel and four reviewed adapter backports. Every other
installed Python file (370) and existing settings were preserved and checked
again after rendering. Existing unconnected-Normal and duplicate-BSSRDF source
edits remain outside this installed backport scope. The previous whole wheel
and four adapter files are retained for rollback. Exact deployed fingerprints:

- ARM wheel SHA-256: `f972a6264443887ea1e1bd5adaccd121cda612f6e6d39a52051db579a454aeb8`
- Native SHA-256: `e2a7055da33a7991e4ba8831121094a5f3913430b0ee680574c2cf2794cd8585`
- Installed volume exporter SHA-256: `1b5ad759f91463de64387dfa5282a9b853dd2ea9d2a8039245463647ed39614e`

Actual-installed gates are recorded in `actual-deployment-completed.json`:

- CPU transform/material/empty-output edits: four passing conditions at 64 eye
  SPP, after worker completion, with independent repeat seeds. Maximum relative
  mean live/fresh error is 0.000875%.
- Metal hybrid sequence missing/restored/clipped frames: four passing conditions
  under the same contract. Maximum relative mean live/fresh error is 0.005836%.
  Missing and clipped frames contain no stale carrier; restoration returns it.
- The actual Blender grid loader agrees in 85 sequence and two linked-library
  conditions, with temporary sequence/library files removed.
- Named and missing-temperature RenderEngine checks: 12 CPU and 12 pure Metal
  1280 by 720 frames, 16 configured SPP, RGB and default spectral modes. All
  authored graphs remain unchanged, raw output is finite/nonzero, and the
  authored-field/independent-control comparisons pass. The largest relative
  body error is 0.21736% CPU and 0.20948% Metal. These compare each backend's
  field to its control; they do not establish complete Cycles image parity.
- Nineteen actual-installed original PNGs were inspected directly. This is a
  recorded subset, not an assertion that every generated image was reviewed.
  The narrow/hard VDB edge remains visible against Cycles. High-radiance
  Standard previews clip and do not substitute for the raw EXR checks.
- The final CI payload also passes the film-reset contract and 6,912 exact
  blackbody float-bit comparisons. Film merges preserve moments; edit resets
  clear them, including reused native worker films in the Metal hybrid path.

All owned Blender validation workers were reaped. Obsolete local hybrid and CI
profiles were removed immediately after deployment; their file-size sum was
696,453,176 bytes (physical reclaimed space was not measured). Signed release
evidence and rollback inputs are retained. Each repository has only its primary
main worktree. Full-scene, GUI and convergence gates above remain open.
