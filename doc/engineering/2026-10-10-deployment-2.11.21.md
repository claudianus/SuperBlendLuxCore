# SuperLuxCore 2.11.21 공개 ZIP 및 실제 Blender 배포

기존 Cycles Principled의 독립 기저·코트 법선과 재질별 반사 보정 설정을 원본 노드 그래프를 수정하지 않고 렌더한다. 강한 Normal에서 반사·확산이 검게 사라지던 경로, Coat Normal 무시, 뒤면 누수 및 영벡터 fallback을 다룬다. Native OpenPBR BRDF·분광 기본값과 품질 정책은 유지한다. 전체 Cycles 제작 씬 호환 goal은 활성 상태이며 미완료다.

## 공개 소스와 패키지

- 엔진 `00a3afb7205d856327b0f16f76f94dbad1967105`: [wheel CI 37955453896](https://github.com/claudianus/SuperLuxCore/actions/runs/37955453896), [공개 wheels-v2.11.21](https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.21).
- 확장 `84f93cce73087062c73708249097a1c3fe14d5f1`: [bundle CI 37961431687](https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37961431687), [공개 v2.11.21](https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.21).
- 두 공개 태그는 각각 위 커밋을 가리킨다. 모든 공개 자산의 서버 SHA-256을 다운로드한 최종 파일과 대조했다.
- 네 플랫폼의 wheel 빌드·메타데이터·런타임 파일·서명과 최종 ZIP 구조·의존성·소스·서명을 통과했다. 각 ZIP의 367개 Python 파일은 확장 소스와 같다. 포함된 엔진 wheel은 서명된 CI wheel과 바이트 해시가 같다. Windows/Linux의 NVRTC wheel은 플랫폼·고정 해시를 검사했다.
- Windows wheel에는 CRLF와 delvewheel의 정해진 DLL 초기화 블록 3개가 추가된다. 이 블록을 정확히 검사한 뒤 원본 Python과 대조했다. 최종 wheel 해시와 서명은 수정하지 않은 실제 파일로 검증했다.
- Intel Mac 빌드는 성공했지만 GPU 없는 CI runner의 runtime smoke는 생략된다. Windows/Linux/ARM smoke는 통과했다. 다른 플랫폼의 로컬 Blender/GPU 렌더 검증을 뜻하지 않는다.

## 실제 설치와 렌더

Blender 5.2.1 LTS (`9e2066aef7ef`)와 macOS ARM/M5 Pro에서 다음 192개 native/core 검사를 통과했다.

| 검증 단계 | 검사 수 |
| --- | ---: |
| 실제 CI wheel + 고정 확장 소스 | 112 |
| 최종 ZIP의 새 격리 설치, CPU·Metal | 40 |
| 실제 사용자 설치본, CPU·Metal | 40 |

112개는 720p 법선 조건 50개, Add Shader·알파·방사광·Normal Map·Bump·표적 CPU BIDIR 회귀 49개, native 720p 장면 2개, 속성 export/reparse 3개, 작은 거친 유리 백색로 8개다. 설치 단계의 40개씩은 고정 wheel/소스가 그대로 로드되는지와 핵심 법선·투명도·방사광·Normal Map·Bump 및 720p 재질 장면을 검사한다. 192개 독립 제작 씬을 의미하지 않는다.

CI의 선택한 평균 에너지 조건은 CPU·Metal 각각 11개이며 최대 차이는 1.031%다. 이 수치를 전체 제작 씬이나 투과 호환률로 해석하지 않는다. 비교 시트 6개, 1280×720 native 분광 재질 이미지 6개와 Cycles 기준 이미지 1개를 직접 검수했다. 기저·코트의 다른 반사와 형상은 반영되며 유리 색·caustic 노이즈 차이는 남아 있다. 기본 분광·128 samples·noise halt 비활성화 조건이고 제작 성능이나 수렴을 주장하지 않는다.

실제 설치의 native 버전·dist-info·확장 manifest는 2.11.21이다. 다음 모듈 SHA-256은 CI ARM wheel과 같다.

`0f61daf90d3ad2cb6082d59f837e73fea657133fce39983f82d303b4d985d295`

실제 CPU와 Metal 검사에서 로그의 backend 및 `Apple M5 Pro MetalIntersect (Type: METAL_GPU)`를 확인했다. 실제 확장의 367개 Python 파일과 매니페스트도 최종 ZIP과 같다. 실제 프로필은 `/Users/modumaru/Library/Application Support/Blender/5.2`, wheel 설정은 `{"wheel_source": 0}`이며 번들 소스를 사용한다. 이전 확장·native 패키지·설정·userpref는 workspace `test-scenes/validation-2026-10-09/public-bundle-2.11.21/previous-install-2.11.20`에 백업했다.

실제 CLI 업그레이드 과정에서 기존 버전과 같은 RNA 등록 진단 3개가 발생했지만 종료 코드는 0이었다. 새 프로세스는 정확한 2.11.21 모듈을 등록·로드하고 40개 렌더 검사를 진단 없이 완료했다. 열려 있던 GUI의 핫리로드는 검증하지 않았다.

## 남은 범위와 다음 결함

- [로브 법선](2026-10-10-cycles-lobe-normals.md): mapped transmission의 밝기, Principled Tangent, 커브 전용 보정, 넓은 SSS/코트/박막/legacy 혼합과 모든 광선 방향·BIDIR/VCM 조합이 남아 있다.
- Vector Displacement의 Object/Tangent/World와 연결 Scale·Midlevel 진단 3개는 현재 실패한다. 공통 표면 깊이 차이 0.669–0.805, 형상 intersection/union 0.338–0.370으로 실제 형상 의미 차이를 재현했다. Midlevel 누락·공간 혼동·연결 Scale 무시, BUMP/BOTH 벡터 범프 미지원도 원본 Blender 소스와 대조했다. 이 결과는 호환 통과 수에 포함하지 않는다.
- 전체 제작 씬·viewport/F12 및 타 플랫폼 실제 실행은 추가 검수 범위다. User OSL·베이킹은 유보된 범위를 유지한다. 픽셀 일치와 99% 완료를 주장하지 않는다.
- Legacy nested engine releaser는 작업 생성 전 startup_failure였다. 성공한 standalone wheel-builder와 고정 버전 ZIP 경로로 배포했다. Legacy caller 권한과 새 호출의 end-to-end 확인은 별도 파이프라인 정리 항목이다.

원본 EXR/PNG·metrics·로그·CI/설치 provenance·서명·공개 자산 기록·검수 시트는 workspace `test-scenes/validation-2026-10-09/public-bundle-2.11.21`에 보존한다.

## 최종 ZIP SHA-256

| 파일 | SHA-256 |
| --- | --- |
| SuperLuxCore-2.11.21-linux_x64.zip | `294dbf210a25902f4a7f2cb7b9261484185fd0e2764f20223a06dd17f8ffeefd` |
| SuperLuxCore-2.11.21-macos_arm64.zip | `b4babb67d63087f6003ff65a2a46270e2415e1706b5144f8ea9627123ee760b1` |
| SuperLuxCore-2.11.21-macos_x64.zip | `48bf3b6688fd4028857b091ebc784b6dcfeda7903fac99a4213bff2843dadd1a` |
| SuperLuxCore-2.11.21-windows_x64.zip | `d10420abd934a25f594afaf47ce8d4dab98c1283309b387f031ad0056efc4932` |
