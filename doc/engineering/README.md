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
