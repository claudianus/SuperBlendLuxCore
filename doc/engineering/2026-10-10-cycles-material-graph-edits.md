# Material graph replacement and live rendering

Rewiring an existing material to a subtree created later made container order
different from dependency order. Replacing a leaf refreshed some parents before
their children, leaving cached BSSRDF/null/event/emission flags stale. The
pre-fix CPU fixture rendered 0.362508 instead of the fresh scene's 0.414426
(12.53% lower), because the nonlocal branch was evaluated as local diffuse.

MaterialDefinitions now sorts the old acyclic dependency graph before replacing
the material and updates references from children to parents. This preserves
the existing render-time caches without adding recursive per-hit queries.

Emission also needs object-owned light updates. Correcting the cached emission
flag exposed a missing parent TriangleLight and an undefined-LightSource abort.
Scene::ParseMaterials now captures affected object roots and their old emission
state, then removes/rebuilds their triangle lights after updating references.
This covers direct and nested Mix/Add/TwoSided owners, including removal of
emission on subsequent edits.

RenderConfig's existing Cycles BSSRDF preflight is shared by engine allocation
and RenderSession::EndSceneEdit. A live edit cannot bypass the eye-only opt-in,
backend, nonlocal PDF/MIS or context restrictions. Validation happens before
film reset and worker restart. A rejected edit remains in edit mode and can be
repaired before retrying EndSceneEdit; this recovery is tested.

## Verified current package

Complete isolated wheel native SHA-256:
`4d413643935ffb275689071874ff41782558d906ebe9840adb550dca1f145d42`.
Blender 5.2.1 LTS `9e2066aef7ef`, actual Apple M5 Pro Metal GPU.

- Material replacement: 24 CPU and 48 Metal contracts, wavefront off/on.
  Mix/Add/TwoSided graphs are rewired to later-created subtrees and their leaves
  switch between BSSRDF, Transparent, Matte and emission. Live edits and
  rejected-edit recovery are compared with freshly constructed scenes.
- Existing nonlocal transport: 50 CPU and 51 Metal contracts pass on this
  package. Ordinary CPU/LIGHTCPU/Metal two-sided emission: 5 PASS, no SKIP.
- Headless Blender's actual material cache/exporter/RecordedScene replay:
  1280x720, 128 spp, three graph edits on CPU and Metal. Each live result is
  compared with a separate fresh export and Cycles; six three-way image sets
  were inspected directly. The graph and sampled source-setting fingerprint
  remains unchanged by rendering/export.
- Live/fresh RGB mean ratios range from 0.999960 to 1.000850; maximum alpha
  mean difference is 0.0000479. Compared with Cycles, RGB mean ratios are
  1.0143-1.0262. Silhouette, lighting direction, scattering, transparency and
  emission agree in the inspected images. Small spectral hue/intensity and
  Monte Carlo noise differences remain. These numbers are scoped image
  evidence, not production convergence or bit-identical output.
- RGB previews use common Standard display settings and alpha one only for
  the preview. The original linear RGBA EXRs are preserved. Transparent alpha
  previews were inspected separately at full 720p resolution.

The failed baseline and intermediate undefined-LightSource abort are retained
alongside successful results in workspace
`test-scenes/validation-2026-10-10/cycles-material-graph-edits/`. The evidence
includes complete wheels, RECORD/runtime/source identity, logs, metrics and
images. Platform CI must be checked for the final commit; previous green CI
does not establish this C++ change's cross-platform build.

## Remaining scope

This fixes native graph-update contracts and verifies a headless Blender replay
path. It does not establish interactive GUI redraw, every animated/linked graph,
topology changes or all platform runtimes. The private BSSRDF adapter remains
an explicit eye-only diagnostic. The public adapter, user installation, stable
release and production quality defaults are unchanged. Adjoint/LT/BIDIR,
Principled/Skin/Burley, mixed Normal/Bump/Volume/ray contexts, spectral radius
limits, other compatibility registry issues and the release transition remain
unfinished. Full Cycles scene compatibility is not claimed; the goal is active.
