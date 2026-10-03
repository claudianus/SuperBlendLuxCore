# Cycles shader-node coverage (Blender 5.2 LTS)

Audit of `export/cycles_node_reader.py` against the 102 `ShaderNode*`
types registered by Blender 5.2.1.

Unsupported nodes never silently black out: the reader logs a warning
(node name + reason) and emits a neutral fallback — grey `matte` for
shader outputs, mid-grey/identity for value/vector sockets, or passes
through the first input where that is semantically closest. Node types
with no SuperLuxCore equivalent additionally carry a specific reason via
`_UNSUPPORTED_NODE_NOTES`.

## Legend

- **mapped** — the primary path converts; uncommon sockets/modes may warn + fall back
- **approx** — mapped with a documented approximation (warning emitted)
- **const-only** — works when key inputs are constant; textured inputs warn + passthrough
- **warn** — no SuperLuxCore equivalent; warning + neutral fallback
- **n/a** — not reachable through material trees (handled elsewhere or engine-internal)

## BSDF / shader nodes

| Node | Status | Notes |
|---|---|---|
| ShaderNodeBsdfPrincipled | approx | Disney mapping: base/metallic/roughness/IOR/alpha/normal, specular level+tint (tint = luminance of free color, warns when colored), subsurface weight (diffuse-profile approx — radius/scale/IOR/anisotropy and random-walk methods warn), anisotropic (rotation/tangent warn), sheen weight+tint (sheen roughness warns), coat weight/roughness → clearcoat/gloss; non-default coat IOR/tint/normal → real `glossycoating` layer (ks=weight, index=IOR, ka/d=tint absorption matching `pow(tint, w/cosNT)`, bumptex=coat normal); coat also wraps the glass path; transmission weight/roughness → integrated lobe or glass/roughglass; Thin Wall + sharp full transmission → archglass (else warn); thin film → film params (disney + glass families); emission = color×strength; diffuse roughness warns |
| ShaderNodeBsdfDiffuse | mapped | matte |
| ShaderNodeBsdfGlossy | mapped | glossy2 |
| ShaderNodeBsdfAnisotropic | mapped | glossy2 anisotropic |
| ShaderNodeBsdfMetallic | mapped | metal2; F82 tint warns |
| ShaderNodeBsdfGlass | mapped | glass/roughglass; thin-film warns |
| ShaderNodeBsdfRefraction | mapped | |
| ShaderNodeBsdfTransparent | mapped | transparent |
| ShaderNodeBsdfTranslucent | mapped | mattetranslucent |
| ShaderNodeBsdfVelvet | mapped | Charlie sheen (velvet `model=charlie`) - Color→kd, Sigma→sheenroughness; Normal→bumptex (node removed in Blender 5.2, still resolves for legacy .blend files) |
| ShaderNodeBsdfSheen | mapped | Charlie sheen (velvet `model=charlie`) - Color→kd, Roughness→sheenroughness; Normal→bumptex |
| ShaderNodeBsdfToon | approx | |
| ShaderNodeBsdfHairPrincipled | mapped | hairmat: CHIANG→beta_m/beta_n, HUANG→model=huang + roughness/aspectratio; melanin/color/absorption parametrizations; textured melanin → const approx |
| ShaderNodeBsdfHair | approx | legacy hair → hairmat; Reflection/Transmission lobe split not separable |
| ShaderNodeBsdfRayPortal | approx | → transparent (rays pass through) |
| ShaderNodeEeveeSpecular | approx | legacy Eevee specular → glossy2 |
| ShaderNodeEmission | mapped | |
| ShaderNodeBackground | warn | world shader only; warns inside material trees |
| ShaderNodeHoldout | mapped | matte + holdout.enable |
| ShaderNodeSubsurfaceScattering | mapped | openpbr subsurface lobes - Weight/Color/Scale/Radius/IOR/Anisotropy all carried (CB15 profile); Normal→bumptex |
| ShaderNodeAddShader | mapped | |
| ShaderNodeMixShader | mapped | |
| ShaderNodeShaderToRGB | warn | Eevee-only concept |

## Texture nodes

| Node | Status | Notes |
|---|---|---|
| ShaderNodeTexImage | mapped | incl. UV/Generated/Object vector mapping |
| ShaderNodeTexEnvironment | mapped | |
| ShaderNodeTexNoise | approx | blender_noise; feature subset warns |
| ShaderNodeTexVoronoi | approx | distance/feature subset warns |
| ShaderNodeTexBrick | mapped | brick |
| ShaderNodeTexChecker | mapped | checkerboard |
| ShaderNodeTexGradient | approx | gradient-type subset |
| ShaderNodeTexMagic | approx | blender_magic |
| ShaderNodeTexWave | approx | wave-type subset |
| ShaderNodeTexWhiteNoise | mapped | whitenoise |
| ShaderNodeTexGabor | mapped | `gabornoise` (native; 2D only, 3D mode warns+approximates) |
| ShaderNodeTexIES | mapped | light Emission strength -> mappoint/mapsphere iesblob (point lights) |
| ShaderNodeTexSky | warn | sky2/sun are lights, not material textures |

## Input / geometry nodes

| Node | Status | Notes |
|---|---|---|
| ShaderNodeTexCoord | approx | UV->uv, Normal->shadingnormal, Object->hitpoint.objectspace, Generated->hitpoint.generated (transformed base-mesh bbox; flat axes 0.5), Reflection->hitpoint.reflection; full undeformed ORCO/custom texspace/material-submesh bounds are not mapped; Window/Camera warn |
| ShaderNodeNewGeometry | mapped | Position->`position`, Normal->`shadingnormal`, TrueNormal/Backfacing/Incoming/Parametric->`hitpoint` channels; Pointiness unwired (needs vertex-AOV export) |
| ShaderNodeUVMap | mapped | incl. named-layer index lookup |
| ShaderNodeAttribute | mapped | color attrs, UV layers (Vector out), generic named attrs — float/int/bool→`hitpointvertexaov`/`hitpointtriangleaov`, vector/float2→extra color layer; edge-domain/string warn |
| ShaderNodeVertexColor | approx | |
| ShaderNodeObjectInfo | approx | Random→objectidnormalized; per-field subset warns |
| ShaderNodeParticleInfo | approx | per-field subset warns |
| ShaderNodeHairInfo | approx | per-output subset warns |
| ShaderNodePointInfo | approx | Random→objectidnormalized (per-point instance id); Position→hit position approx; Radius→warn 1.0 |
| ShaderNodeCameraData | mapped | View Vector->hitpoint.incoming×-1 (scale), View Distance->rayinfo.raylength, View Z Depth->rayinfo.viewdepth (camera-fwd projection, base pose on motion blur) |
| ShaderNodeLightPath | mapped | all outputs via `rayinfo` texture (HitPoint ray context): Is Camera/Shadow/Diffuse/Glossy/Singular/Reflection/Transmission/Volume Scatter Ray, Ray Length/Depth, Diffuse/Glossy/Transparent/Transmission Depth |
| ShaderNodeLayerWeight | mapped | Fresnel→`fresnelior` (dielectric at incident angle, IOR 1.45); Facing→`facing` (pow(1-|cos|,blend), Blend input carried) |
| ShaderNodeFresnel | mapped | `fresnelior` dielectric at the hit incident angle; textured IOR falls back to Schlick F0 chain (eta is scalar) |
| ShaderNodeVolumeInfo | approx | per-output subset warns |
| ShaderNodeRaycast | warn | no scene-query textures |
| ShaderNodeTangent | approx | |
| ShaderNodeUVAlongStroke | warn | Freestyle |

## Color / math / vector nodes

| Node | Status | Notes |
|---|---|---|
| ShaderNodeMath | mapped | SINE/COSINE/TANGENT/ARC*/ARCTAN2/SINH/COSH/TANH/INVERSE_SQRT/FLOORED_MODULO/SNAP/FLOOR/CEIL/TRUNC/FRACT/ROUND/EXPONENT/LOGARITHM/MINIMUM/MAXIMUM via SuperLuxCore `mathfunc` texture (log_b(x)=ln(x)/ln(b)); SNAP floors to the increment, including negative/zero increments; ROUND uses Blender's float32 floor(x+0.5), not ties-away; supported results share the post-operation Clamp stage; SQRT via native power; SMOOTH_MIN/SMOOTH_MAX via polynomial composition; PINGPONG/SIGN/COMPARE/WRAP/MULTIPLY_ADD/RADIANS/DEGREES composed from existing textures; remaining ops warn + passthrough |
| ShaderNodeVectorMath | approx | ADD/SUBTRACT/MULTIPLY/DIVIDE/DOT/CROSS/REFLECT/PROJECT/FACEFORWARD/MULTIPLY_ADD/LENGTH/DISTANCE/NORMALIZE/SCALE/ABSOLUTE/MODULO mapped; MINIMUM/MAXIMUM→native componentwise `mathfunc.min/max`, including folded constants; SNAP→native componentwise floored `mathfunc.snap`, including negative/zero increments; FLOOR/CEIL/FRACTION→native componentwise unary `mathfunc`; SINE/COSINE/TANGENT→elementwise `mathfunc`; WRAP/FLOORMOD/REFRACT→warn passthrough |
| ShaderNodeVectorRotate | const-only | rotation composed as constant 3x3 matrix over texture channels; textured axis/angle/euler → warn passthrough |
| ShaderNodeVectorTransform | approx | world/object/camera matrices composed per object; per-instance object space not expressible (base object matrix used); unresolvable → warn passthrough |
| ShaderNodeMixRGB / Mix | approx | direct blend modes; exotic blends → mix + warn |
| ShaderNodeValToRGB (ColorRamp) | mapped | band |
| ShaderNodeRGBCurve / FloatCurve / VectorCurve | mapped | curve LUT evaluation |
| ShaderNodeHueSaturation | mapped | hsv |
| ShaderNodeInvert | mapped | |
| ShaderNodeBrightContrast | mapped | brightcontrast |
| ShaderNodeGamma | mapped | power |
| ShaderNodeRGBToBW | mapped | Rec.709 dot product |
| ShaderNodeMapRange | mapped | remap |
| ShaderNodeClamp | mapped | legacy node |
| ShaderNodeCombine*/Separate* | mapped | makefloat3/splitfloat3; non-RGB modes warn |
| ShaderNodeRGB / Value | mapped | constfloat3/constfloat1 |
| ShaderNodeBlackbody | mapped | blackbody |
| ShaderNodeWavelength | mapped | lampspectrum |
| ShaderNodeSqueeze | mapped | sigmoid 1/(1+exp(-(v-c)*w)) via `mathfunc` exp + arithmetic |

## Shading-graph utility nodes

| Node | Status | Notes |
|---|---|---|
| ShaderNodeMapping | mapped | UV/global mapping transforms |
| ShaderNodeNormal | approx | direction output subset warns |
| ShaderNodeNormalMap | mapped | tangent-space normal maps |
| ShaderNodeBump | mapped | bump mapping |
| ShaderNodeBevel | mapped | SuperLuxCore bevel texture (bump-only round edges; Radius constant only, Normal input unsupported) |
| ShaderNodeAmbientOcclusion | approx | AO texture |
| ShaderNodeWireframe | mapped | wireframe |
| ShaderNodeDisplacement / VectorDisplacement | approx | object space only; exported as displacement shape |
| ShaderNodeGroup / CustomGroup | mapped | recursive expansion |
| ShaderNodeOutputMaterial | n/a | entry point, not evaluated as a node |
| ShaderNodeOutputWorld / OutputLight | n/a | world/light trees (see below) |
| ShaderNodeOutputAOV | warn | SuperLuxCore AOVs via film outputs, not material nodes |
| ShaderNodeScript | warn | no OSL |

## World & light trees

Handled outside `_node` (`export/light.py::_convert_cycles_world` /
`_convert_cycles_light`): Background, TexSky, TexEnvironment, Emission,
portal lights. `ShaderNodeLightFalloff` warns (falloff lives on SuperLuxCore
light definitions).

## Regression test

`dev-tools/cycles_node_coverage_test.py` (headless Blender, non-render):
constant-fold checks for the composed vector ops, material-type checks
for the new BSDF mappings, warning-content checks for the warn-tier
nodes, and Principled coverage: disney/glossycoating coat wrap
(`base`/`ks`/`index`/`ka`/`d`/coat `bumptex`), archglass thin-wall path,
thin-film on glass, and per-feature warning assertions.

## E2E render corpus

`dev-tools/e23_cycles_compat_e2e_test.py` (headless Blender, renders):

```sh
/Applications/Blender.app/Contents/MacOS/Blender --background \
    --factory-startup --python dev-tools/e23_cycles_compat_e2e_test.py
```

Builds 14 small scenes (128×128, ~32 samples) that use only native
Cycles node trees, renders each with SuperLuxCore (PATH, CPU) and asserts the
output is finite, non-black and plausibly bright. Where the result is
physically comparable the same scene is also rendered with Cycles (CPU)
and the mean luminance factor plus mean-normalised luminance RMSE are
compared with loose tolerances. Renders are written as EXR and read back
via `bpy.data.images.load()`, so all checks run on scene-linear radiance
(the Render Result buffer is not readable in background mode).

Scene coverage:

| Scene | Nodes exercised | Parity vs Cycles |
|---|---|---|
| s01_diffuse_point | BsdfDiffuse + point light | asserted |
| s02_principled_area | BsdfPrincipled + area light | asserted (disney approx) |
| s03_glass_sun | BsdfGlass + sun light | asserted, loose (caustics) |
| s04_emission | Emission shader | asserted |
| s05_noise_ramp | TexNoise -> ValToRGB | asserted, loose (approx noise) |
| s06_image_texture | TexImage (packed generated) | asserted + quadrant hues |
| s07_bump_noise | TexNoise -> Bump | asserted, loose |
| s08_mix_transparent | TexChecker -> MixShader(Transparent, Diffuse) | asserted |
| s09_world_background | world Background flat color | asserted |
| s10_world_sky | world TexSky(Hosek-Wilkie) -> sky2 | asserted, loose |
| s11_volume_principled | VolumePrincipled interior volume | asserted, loose |
| s12_lightpath | LightPath Is Camera Ray -> MixShader | asserted |
| s13_shadertorgb_fallback | ShaderToRGB warn-tier fallback | SuperLuxCore-only + warning check |
| s14_lightpath_mirror | LightPath Is Camera Ray across a mirror bounce | asserted + quadrant hues |

Notes:

- Lights and worlds must opt in via `superluxcore.use_cycles_settings`;
  materials with a Blender node tree are converted automatically.
- The test disables `path.auto_clamping` / `use_clamping` and resets
  `suggested_clamping_value` for deterministic parity measurements.
  `check_stale_clamp()` additionally verifies the stale-suggestion fix:
  the suggested clamp is stamped with a lighting-content signature
  (`suggested_clamping_sig`), so a value measured on one scene is ignored
  once the emitters change — before the fix, a previous scene's clamp
  silently crushed bright emitters (~13x observed on s04).
- Measured luminance factors on this suite are ~1.0–1.6 for mapped nodes
  and ~2.0 for the approx-tier noise texture; the warn-tier scenes render
  non-black via the documented fallbacks.
- `ShaderNodeLightPath` is backed by the `rayinfo` texture:
  `Scene::Intersect()` records the incoming ray's flags (camera/shadow/
  indirect), the generating BSDF event and the path depth counters on the
  shaded `HitPoint` (`rayFlags`, `rayEvent`, `rayDepth`, `rayDiffuseDepth`,
  `rayGlossyDepth`, `raySpecularDepth`, `rayTransmissionDepth`,
  `rayTransparentDepth`, `rayLength`). Camera and shadow rays mask the
  event-based outputs to 0 (they have no generating bounce), matching
  Cycles where `is_*_ray` flags other than camera/shadow are 0 on the
  first path vertex. Works on PATHCPU and PATHOCL; BiDir/light-tracing
  hits carry the corresponding light-path context.


## Snap / vector dispatch regression gate

- Blender 5.2 reference: `gpu_shader_common_math.glsl::math_snap` and
  `gpu_shader_material_vector_math.glsl::vector_math_snap` both evaluate
  `floor(safe_divide(a,b))*b`.
- Math and Vector Math SNAP now emit one native binary `mathfunc.snap`
  texture, replacing nearest-multiple rounding. Scalar Clamp follows the
  common Math output path; vector increments remain componentwise.
- A missing `ShaderNodeTexCoord` branch header had placed coordinate
  dispatch inside Vector Math. Actual Blender export reproduced
  `NameError: coord is not defined` for Vector Math SNAP and a neutral
  fallback for Generated coordinates. Restoring the branch separates
  these supported node families without a fallback shim.
- `dev-tools/snap_node_e2e_test.py` runs real Blender nodes through the
  repository reader and renders their exported graphs using the rebuilt
  renderer. 26 CPU/isolated Metal checks passed: five native cases plus
  eight Blender-export cases (positive/negative/zero increments, Clamp,
  linked Combine XYZ inputs, Vector Add, Generated coordinates, and
  Generated→Scale→Add→Snap procedural input).
- Texture SDL round-trip is included. Rendered radiance tolerance is
  `0.05`, not a claim of bitwise texture precision: a preliminary strict
  gate observed GPU radiance residuals around `0.01` even for constant
  emission. The nearest-rounding regression changes the fixtures by
  `0.5` or more and fails this gate.
- Installed Blender 5.2.1 extension/runtime bundle was synchronized using
  `sync_dev_install.sh`; actual SUPERLUXCORE rendering of the linked
  Vector Snap material completed and produced a readable EXR.

## Math output Clamp regression gate

- Actual Blender export/render reproduced `EXPONENT(1)` with Clamp
  enabled producing biased radiance `6.71837` rather than `5`. Helper
  Math branches returned before the existing post-operation Clamp stage.
- Supported helper branches now carry their output to the same final
  stage as direct native definitions. No identity texture is inserted:
  an unclamped folded result stays a constant, and a linked helper result
  keeps its existing texture graph. Clamp adds one native wrapper.
- The real-Blender E2E gate now passes 78 CPU/isolated Metal renders,
  including Clamp enabled/disabled for Square Root (interior and upper
  values), Exponent, Minimum, Maximum, Sine, Radians, Degrees, Logarithm,
  Multiply Add, Smooth Minimum, Smooth Maximum and Sign. Constant and
  linked inputs are included, along with the earlier Snap/vector/Generated
  coordinate gates. Radiance tolerance remains `0.05`.
- Invocation:
  `Blender --background --python-exit-code 1 --python dev-tools/snap_node_e2e_test.py`.
  The explicit exit code makes a failed Python assertion fail the command.
- Synchronized installed-extension smoke also rendered clamped Exponent
  and Sine graphs successfully on CPU and isolated Metal (four checks).

## Linked Square Root regression gate

- Actual Blender `Value(0.25)→Math.SQRT` export/render reproduced biased
  radiance `5` instead of `4.5`. `_tex_binary("power", ...)` emitted
  `texture1/texture2`, while native power SDL reads `base/exponent` and
  defaulted both operands to one.
- The binary helper now emits power's correct operand names, after its
  existing constant-folding stage. Direct Math POWER already used the
  correct SDL keys and remains unchanged.
- 84 CPU/isolated Metal renders passed. Added consumer gates exercise
  linked `Sqrt(0.25)` with Clamp off/on and linked `Sqrt(9)` without Clamp;
  earlier constant-folded Square Root, Math Clamp, Snap and coordinate
  cases remain in the same actual-Blender graph/render run.
- Synchronized installed-extension `Value(0.25)→Square Root` graphs also
  rendered the expected biased radiance `4.5` on CPU and isolated Metal.

## Signed integer / fractional Math regression gate

- Blender 5.2 `gpu_shader_common_math.glsl` defines Floor/Ceil/Truncate
  natively, Fraction as `a-floor(a)`, and Round as `floor(a+0.5f)`.
  `gpu_shader_material_vector_math.glsl` applies Floor/Ceil/Fraction
  componentwise.
- Actual exported CPU emission renders reproduced five discrepancies:
  Floor(-1)→-2, Ceil(1)→2, Truncate(1.75)→-1, Fraction(-1)→1,
  Round(-1.5)→-2. Vector Floor/Ceil/Fraction warned and passed through.
- Added native unary `mathfunc.floor/ceil/trunc/fract/round` operations on
  CPU and the shared GPU kernel path, appending enum IDs without shifting
  existing operations. Scalar Floor/Ceil/Truncate/Fraction keep constant
  folding; Round retains native float32 half-add semantics rather than
  using Python double arithmetic. Typed scalar socket conversion is
  handled at the input boundary; vector operations stay componentwise.
- Removed the composed round/shift/sign approximations. Vector rounding
  uses one native unary texture rather than channel splitting/recombining.
  No measured end-to-end speedup is claimed.
- 206 actual CPU/isolated Metal renders passed, covering constant/linked
  signed integers, negative half-ties, fractions, vector components and
  positive/negative float32 unit-spacing boundaries. A real Blender
  `Round(8388609)→Subtract(8388610)` graph also yields zero on both paths.
  SDL round-trip and previous Math/Clamp/Snap/coordinate cases are included;
  radiance tolerance remains `0.05`, not a bitwise-parity claim.
- Installed Blender 5.2.1 SUPERLUXCORE rendering of
  Generated→Scale(4)→Add(-2)→Vector Floor→Add(3)→Scale(0.15)→Emission
  produced the actual `docs/assets/ex_math_floor.png` example. Four
  distinct colour bands and flat interior plateaus passed checks.
  Display-managed RGB is not used as a raw math oracle; the SDL emission
  gate above checks numeric semantics independently.

## Typed scalar socket regression gate

- Blender's `gpu_shader_codegen_lib.glsl` converts Vector→Float by the
  mean of RGB components and Color→Float by luminance, not the mean.
  Colour coefficients come from the active OpenColorIO configuration;
  [upstream colour management](https://github.com/blender/blender/blob/main/source/blender/imbuf/intern/colormanagement.cc)
  loads `get_default_luma_coefs()`.
- Actual CPU rendering of Combine XYZ(0,1.5,0)→Math.Sine produced
  biased RGB `[4,4.99753,4]` rather than scalar `[4.47943]*3`.
  RGB(0,1.5,0)→Math.Sine had the same channelwise defect; the expected
  biased luminance result is `[4.87854]*3` with Blender's default config.
- Float inputs now convert linked Vector/Color outputs with the existing
  native `dotproduct` texture. This averages the evaluated vector, not
  the product of its component means. Scalar links pass through unchanged.
  The same boundary applies to Math's third input and group interfaces.
  RGB to BW uses the same active-config luminance coefficients.
- Removed the `power(x,1)` conversion workaround and its callers.
  Linked scalar Floor/Ceil/Truncate/Fraction graphs drop from three
  explicit textures to two, including their Value input. The large
  Round→Subtract graph also drops from three to two. Vector/Color→Sine
  gains one necessary conversion texture; no native type/layout changes
  or separate GPU buffers are introduced. No render-speedup claim.
- 222 actual CPU/isolated Metal render checks passed: native SDL
  round-trip, previous Math/Clamp/Snap/coordinate coverage, vector/colour
  Sine, colour Add, RGB to BW, derived vector multiplication, third
  operands, and scalar group input/output boundaries. Tolerance `0.05`
  remains a radiance gate, not proof of bitwise mathematical parity.

## Compare boundary and numeric SDL regression gate

- Blender 5.2 `math_compare` evaluates
  `abs(a-b) <= max(epsilon,1e-5f)`. Actual CPU Compare(1,1,0) returned
  biased radiance 4 instead of 5 because the adapter used strict `<`
  without a minimum epsilon.
- Compare now uses native absolute difference, `mathfunc.max` for the
  epsilon floor, and `mathfunc.lessequal`. Constant subtraction rounds
  to float32, so 16777216−(-1) rounds to 16777216 while
  16777218−(-1) rounds to 16777220. NaN differences compare false.
- These linked boundary fixtures also exposed SDL precision loss:
  Python double properties serialized 16777216 as 16777200, while the
  native float formatter could round it to 16777220. The engine's
  float/double formatting preserves shortest round-trip values using
  compile-time fmt in a stack buffer; no identity textures or input
  special cases. This also preserves the macOS 11 Intel deployment target.
- With two linked operands and constant epsilon, Compare keeps three
  operation textures. Linked epsilon adds one native maximum operation
  to enforce its minimum. No native texture/layout changes; no measured
  render-speedup claim.
- 268 actual CPU/isolated Metal renders passed, including the full
  previous corpus, native scalar/spectrum maximum and inclusive compare,
  epsilon equality, zero/negative epsilon, both float32 spacing ties,
  NaN differences, and SDL round-trip. Installed-extension Compare
  graphs also passed. Installed numeric Property SDL round-tripped 5004
  finite double values exactly, including signed zero and subnormals.
  Radiance tolerance stays `0.05`, not a bitwise shader-parity claim.

## Native Minimum/Maximum and quotient boundaries

- Math and Vector Math Minimum/Maximum now use one native `mathfunc`
  operation instead of four composed operations. Two linked operands
  need three explicit textures instead of six, measured on actual
  Blender graphs for all four node/operation combinations.
- Direct extrema avoid overflowing an intermediate subtraction with
  finite opposite-sign values near float32's maximum. Constant vector
  inputs fold componentwise, rather than selecting their first channel.
- Full-range fixtures remain at `±3e38`; their normalization divides by
  the selected extreme and must return one on CPU and isolated Metal.
  This also exposed and repaired Metal reciprocal underflow.
- Divide texture spectrum evaluation now avoids CPU reciprocal overflow.
  The Metal translator preserves subnormal input significands and exact
  zero-divisor guards locally, without disabling global fast math or
  changing texture storage. Native scalar/spectrum probes include
  `1e-45/1e-45`, signed tiny inputs and zero divisors.
- Development installs synchronize the Metal translator into both the
  installed package and cached wheel. Installed exporter and native
  package rendering passed these boundaries plus linked/folded extrema.
- This is a graph-cost reduction and numerical correctness fix, not a
  measured render-speedup or bitwise GPU-parity claim.
- The final full corpus passed 302 actual CPU/isolated Metal checks;
  70 installed-package checks also passed. All graphs go through SDL
  round-trip, with radiance tolerance `0.05` and no native CPU workers
  enabled on the Metal gate.

## Transformed Generated coordinates

- Generated previously mixed inverse-transformed hit positions with baked
  mesh bounds. An actual translated-plane Min/Max render lost its ramps.
  CPU/GPU now use a cached baked-to-normalized authoring map; no per-hit
  geometry scan, per-vertex coordinate array or new texture layout.
- Translation and rotation/nonuniform scale are covered for direct meshes
  and instances. Flat axes use Blender's 0.5 texture-space center.
  Blender 5.2 mesh texspace independently supplies reference vertex colours;
  Generated minus the interpolated reference is amplified 1000× before
  checking every pixel in the original 4×4 region. Radiance tolerance
  remains 0.05, not a claim of bitwise parity.
- The full Blender export → SDL round-trip → CPU/isolated Metal corpus
  passed 308 checks. The installed extension's actual 384×192 RGB emission
  render is `docs/assets/ex_vector_extrema.png`: raw EXR pixels verified
  upper/lower clipping plateaus and distinct blue components.
- Generated remains a base-mesh bbox approximation. Full undeformed ORCO,
  custom texspace and whole-object bounds shared across material submeshes
  are not established by these transform checks.

