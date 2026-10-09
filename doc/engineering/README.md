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
