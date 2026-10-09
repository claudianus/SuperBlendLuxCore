# Cycles reflection-normal compatibility audit

Strongly tilted shading normals are a remaining visible compatibility defect. Normal Map/Bump vector-data agreement does not establish that those normals produce the right material reflection or diffuse lighting.

## Reproduction and evidence

Installed Blender 5.2.1 LTS, build `9e2066aef7ef`, was compared against the matching Blender source commit `9e2066aef7ef7e20c142ad7bd3303138a4304c93` in the local `blender-5.2` repository. The test uses an existing Cycles Principled graph on a plane, an orthographic grazing camera, a white environment and a linked world-space normal `(0.97, 0, 0.243)`. It preserves graph links and `material.cycles.use_bump_map_correction` during engine switching. All images are 1280×720, native spectral 128 samples, Cycles 64 samples, with noise halt disabled.

The diagnostic runtime is the private 2.11.20 native module `36ee7ab9928edbbb0a06e5899df57a9f17d9c20379c746bb22835c7fdcb917dc`, engine source `2f0304832ea144a7069718a1cf0a6dcdb13dea73`, add-on source `6a8c14837fae8428aaec459ad26ef4423f5ec9a7`. These results are not final-public-package measurements.

| Condition | Cycles mean | Native CPU mean | Native Metal mean |
| --- | ---: | ---: | ---: |
| Metal, reflection correction enabled | 0.644003 | 0 | 0.00001697 |
| Metal, reflection correction disabled | 0 | 0 | 0.00001611 |
| Principled diffuse, specular level 0 | 0.372478 | 0 | 0.00001980 |
| Mixed dielectric, correction enabled | 0.425020 | 0 | 0.00001937 |
| Metal, geometric normal | 1.000197 | 1.010404 | 1.010361 |

Ten diagnostic conditions completed with finite pixels and no renderer errors. The comparison sheet was inspected: the corrected metal, diffuse and mixed native planes lose essentially all light. The uncorrected Cycles metal is also black, demonstrating that the per-material correction flag matters. The flat-normal baseline retains light but has approximately 1% excess mean energy; it needs a separate statistical GGX/furnace investigation. Finite rendering is not a compatibility pass for these cases.

Durable evidence, including the harness, EXRs, PNGs, metrics, logs and reviewed sheet: workspace `test-scenes/validation-2026-10-09/phase18/reflection-normal-baseline`.

## Current-source findings

- Cycles `intern/cycles/kernel/svm/closure.h` creates a corrected reflection normal for metal, specular, transmission and thick subsurface closures. Coat uses its separate Coat Normal input and its own correction. Diffuse keeps the artist's raw normal.
- The installed source's RNA property `use_bump_map_correction` defaults to true (`intern/cycles/blender/addon/properties.py`) and is copied onto the shader by `intern/cycles/blender/shader.cpp`. `maybe_ensure_valid_specular_reflection` in `kernel/closure/bsdf_util.h` leaves the normal unchanged when that flag is off, for curves, or when the shading normal equals the geometric normal. These boundaries belong in the repair rather than an unconditional global normal replacement.
- Cycles `intern/cycles/kernel/closure/bsdf_diffuse.h` samples the hemisphere around the diffuse normal and rejects directions below the geometric surface. Its Lambert evaluation does not flip the entire shading frame merely because the view points below the shading-normal hemisphere.
- The add-on OpenPBR exporter currently warns and ignores Coat Normal. It also does not translate the material's `use_bump_map_correction` setting.
- Native OpenPBR currently shares one shading frame between all lobes. Its opaque backface decision uses the local shading-normal view dot product. A physically front-facing plane with a strongly tilted normal can therefore be treated as the backface and sample the wrong hemisphere.
- Native reflection correction in `Material::Bump` is tied to the global Conty terminator choice and changes the common shading normal. Native defaults use Chiang. Switching the global mode would change diffuse/data semantics and is not an adequate per-material compatibility repair.
- BSDF-level shadow-terminator attenuation uses the common shading normal after the material returns a lobe mixture. Correcting a reflective lobe internally without addressing that attenuation can still discard the recovered energy.

## Required repair boundaries

The repair must distinguish physical surface facing from shading-normal hemisphere, support reflection and Coat Normal frames per lobe, and preserve raw diffuse/normal-data intent. The per-material Cycles correction flag must control the imported closure semantics while native material defaults and high-quality shadow-terminator policy remain intact. CPU and shared GPU paths need matching evaluation, sampling, forward/reverse PDFs and frame transforms, including anisotropy, transmission, mixed closures and bidirectional transport.

No repair is claimed by this audit. C31 remains incomplete; the 2.11.20 release gates cover vector-data, Bump distance/links, additive closures and transparent transport rather than strongly tilted mapped-normal material parity.
