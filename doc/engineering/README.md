# Engineering notes

Deep implementation notes, debugging findings and platform gotchas
extracted from the old monolithic `AGENTS.md`. Feature/user-facing
docs live alongside in `doc/`.

| File | Contents |
|---|---|
| [legacy-compat.md](legacy-compat.md) | Legacy upstream file compatibility |
| [deployment.md](deployment.md) | Deployment: installed extension, wheel chain, external render |
| [windows-extension-packaging.md](windows-extension-packaging.md) | Windows extension zip: local build, CI auto-release, bundled NVRTC for RTX/CUDA |
| [render-session.md](render-session.md) | Render session lifecycle: halt, callbacks, viewport restart |
| [cycles-compat.md](cycles-compat.md) | Cycles compatibility findings |
| [blender-52-gotchas.md](blender-52-gotchas.md) | Blender 5.2 RNA/API gotchas |
| [pysuperluxcore-notes.md](pysuperluxcore-notes.md) | Standalone pysuperluxcore API notes |
| [out-of-core.md](out-of-core.md) | Out-of-core memory: spilling, .lxm proxies, streaming |
| [diffraction-node.md](diffraction-node.md) | Diffraction material node |
| [thread-safety.md](thread-safety.md) | bpy/RNA main-thread rules, worker marshalling, crash fixes |
| [auto-caustic-routing.md](auto-caustic-routing.md) | Scene-signature caustic auto-enable (auto/on/off), legacy bool folding |

## 2026-10-09 잔여 호환성 검수

[현재 배포본의 전수 검수](2026-10-09-remaining-compatibility-audit.md)는 Blender 5.2.1 원본과 1,023개 변환 조건, CPU·Metal 720p 비교를 대조한다. [노드별 목록](2026-10-09-node-audit-catalog.md)과 [문제 60개 묶음](2026-10-09-remaining-issues.json)은 확정 결함·제한·미검증 범위를 구분한다. 런타임 수정이나 새 배포 완료 기록이 아니다.

## 기존 Cycles 씬의 무변환 렌더 목표

[목표와 현재 소스 검증](2026-10-09-cycles-scene-goal.md)은 픽셀 일치 대신 시각적·논리적 의미를 보존하는 사용자 기준과 검증된 첫 수정 묶음을 기록한다. 목표는 활성 상태이며 전체 제작 씬 호환·정식 배포 완료를 뜻하지 않는다.

[Verified 2.11.16 deployment](2026-10-09-deployment-2.11.16.md) records final ZIP and actual user Blender validation, source commits and artifact hashes.

- [RNA descriptor lifetime during render-engine changes](2026-10-09-rna-descriptor-lifetime.md)

- [Normal data vectors for shader inputs](2026-10-09-normal-data-vectors.md)

- [Verified Blender 2.11.17 deployment](2026-10-09-deployment-2.11.17.md)

- [Cycles Normal Map spaces and MikkTSpace data](2026-10-09-cycles-normal-map.md)

- [Verified Blender 2.11.18 deployment](2026-10-09-deployment-2.11.18.md)

- [Existing Cycles Diffuse Roughness](2026-10-09-diffuse-roughness.md)

- [Existing Cycles Bump remaining contracts](2026-10-09-cycles-bump-audit.md)

- [Cycles Bump direction and linked-input semantics](2026-10-09-cycles-bump-direction.md)

- [Verified 2.11.19 public ZIP and actual Blender deployment](2026-10-09-deployment-2.11.19.md)

- [Cycles Add Shader closure sums and transparent transport](2026-10-09-cycles-add-shader.md)

- [Strongly tilted reflection and diffuse normal audit](2026-10-09-reflection-normal-audit.md)

- [Verified 2.11.20 public ZIP and actual Blender deployment](2026-10-09-deployment-2.11.20.md)

- [Cycles Principled lobe normals and independent Coat Normal](2026-10-10-cycles-lobe-normals.md)

- [Verified 2.11.21 public ZIP and actual Blender deployment](2026-10-10-deployment-2.11.21.md)

- [Cycles Vector Displacement spaces, shared geometry and Mikk data](2026-10-10-cycles-vector-displacement.md)

- [Verified 2.11.22 public ZIP and macOS Blender deployment, with confirmed CUDA limitation](2026-10-10-deployment-2.11.22.md)

- [Verified 2.11.23 CUDA compile fix, four-platform ZIP and macOS deployment](2026-10-10-deployment-2.11.23.md)

- [Verified private Cycles Vector Displacement Incoming direction](2026-10-10-cycles-displacement-incoming.md)

- [Cycles Backfacing spectrum](2026-10-10-cycles-backfacing.md): front/back emission color/strength fix; 28 private CPU/Metal checks; the scoped fix is included in verified 2.11.24 deployment.

- [Valid zero, zero SSS and Microfiber sheen](2026-10-10-cycles-zero-subsurface-microfiber.md): 23 private acceptance checks, source-grounded local SSS limit and native fuzz mapping; positive SSS/Ashikhmin gaps remain.

- [Current 2.11.26 standalone positive SSS boundary diagnostic](2026-10-10-cycles-positive-sss-diagnostic.md): confirmed remaining defect; auxiliary models excluded from production acceptance.

- [Verified 2.11.24 Incoming, Backfacing, valid-zero and Microfiber deployment](2026-10-10-deployment-2.11.24.md): 591 guarded CI/fresh/actual CPU and Metal checks; full-scene goal remains active.

- [Cycles Bump zero Filter Width](2026-10-10-cycles-bump-zero-filter.md): 78 private CPU/Metal, spectral and smooth geometry checks; scoped fix included in verified 2.11.25 deployment.

- [Cycles standalone SSS all-channel local diffuse limit](2026-10-10-cycles-sss-local-limit.md): 58 private adapter checks and 5 reviewed sheets; scoped fix included in2.11.25; ordinary positive SSS remains open.

- [Verified 2.11.25 Bump zero-width and SSS local diffuse deployment](2026-10-10-deployment-2.11.25.md): 627 guarded CI/fresh/actual checks; goal remains active and incomplete.

- [Cycles SSS constant RGB/Vector Scale coercion](2026-10-10-cycles-sss-scale-coercion.md): 46 private CPU/Metal checks and6 reviewed sheets; verified public2.11.26 deployment with86 guarded checks and9 sheets.

- [Verified 2.11.26 SSS RGB/Vector Scale coercion deployment](2026-10-10-deployment-2.11.26.md):86 guarded CI/fresh/actual checks; full goal remains active and incomplete.
