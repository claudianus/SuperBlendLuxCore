# Cycles Vector Displacement: verified 2.11.22 candidate

기존 Cycles Object/Tangent/World Vector Displacement와 연결 Scale·Midlevel을 원본 노드·UV·메시 수정 없이 native 변위로 렌더한다. SuperLuxCore의 OpenPBR·Spectral 기본 품질과 전송 추정기를 유지한다. 2.11.22의 공개 ZIP과 macOS CPU·Metal 사용자 설치 검증은 완료했다. Windows/Linux NVIDIA CUDA 컴파일 결함은 확인됐으며 2.11.23 수정본을 검증 중이다. 상세 범위는 [배포 기록](2026-10-10-deployment-2.11.22.md)을 따른다. 전체 제작 씬 호환 goal은 활성 상태다.

## 구현과 Blender 소스 대조

설치된 Blender 5.2.1 LTS의 정확한 소스 SHA `9e2066aef7ef7e20c142ad7bd3303138a4304c93`를 바탕화면 `code/blender-5.2` 저장소에서 대조했다. Vector Displacement는 `(Vector - Midlevel.xxx) * Scale`을 데이터 텍스처로 내보낸다. Object/World/Tangent 공간과 원래 인스턴스 좌표계는 명시적 native shape 속성으로 전달한다. 기존 native displacement의 채널 순서·UV 필수 조건은 바꾸지 않았다.

Cycles `scene/mesh_displace.cpp`처럼 원본 버텍스의 첫 삼각형 코너에서 한 번 평가하고, UV/법선으로 나뉜 모든 복제 코너를 함께 이동시킨다. 원본 ID를 두 vertex AOV에 저장하며 smoothing 비트와 POINT/CORNER 법선 도메인을 보존한다. 코너 법선은 변위 전후 원본 버텍스 법선 차이로 갱신한다. 공유 Cycles 메시의 변위는 첫 오브젝트 기준으로 평가하고 각 실제 오브젝트의 변환으로 배치한다.

UV 없는 구의 접선 경계에서 임시 Python 메시 방식은 추가 돌기를 만들었다. 이를 설치 Cycles와 같은 삼각형 Mikk 구현과 octahedral 2x16-bit 법선 정밀도로 교체했다. native `ComputeMikkTangents`는 원본 배열을 변경하지 않으며 UV가 없을 때 원본 오브젝트 위치의 spherical 좌표를 사용한다. Blender의 Apache-2.0 Mikk 헤더 네 개는 출처 SHA·원 저작권·SPDX와 함께 byte-identical로 보존한다. Native API 호출자는 원래 full-precision 기본값을 유지한다.

F12 persistent cache의 shape 서명 호출도 새 변위 좌표계 인자를 전달한다. 서명 계산 실패는 재사용을 허용하지 않는다. 변위 모드/그래프가 바뀌면 wrapper 메시를 재평가하고, 공유 변위의 형상/변환 변경은 전체 관련 좌표계를 재구축한다. 이번 좌표계 인자 추가 중 누락됐던 서명 호출을 수정했고, 계산 실패 두 개가 모두 `None`인 것을 같다고 판단하는 경로도 제거했다.

## 현재 검증

같은 native 바이너리·매니페스트·dist-info 2.11.22 및 다섯 adapter 파일 SHA-256을 고정한 격리 프로필에서 115개 native/core 검사를 통과했다.

| 범위 | CPU | Metal |
| --- | ---: | ---: |
| Vector Displacement 20개 조건 + 공유 메시 이동 | 21 | 21 |
| 기존 Normal Map, smooth, image Bump, scalar displacement | 22 | 22 |
| native displacement 속성/legacy/오류 경계 | 16 | — |
| native Mikk basis/반전/입력 경계 | 13 | — |

Vector 검사는 모두 1280×720, 16 samples, native Spectral ON, denoiser 및 noise halt OFF다. 원본 그래프·원본 메시 좌표·UV 지문 보존, finite 값, 오류 없음, 실루엣 IoU > .99, 공통 내부 Depth MAE < .006, Normal MAE < .012를 각각 검사한다. 최종 CPU 최대 Normal MAE는 .001399, Depth MAE .002092, 최저 IoU .996530이다. Metal은 .001435, .002232, .996544다. 이는 표적 기하 검사이고 전체 제작 씬 호환률이 아니다.

조건은 공간 세 종류, UV gradient, world Position, linked Midlevel/Scale gradient, mirrored/rotated UV, 음수·비균일 스케일, UV 없는 평면/구, 공유 메시의 두 변환과 이동을 포함한다. 기존 native 2.11.21의 세 legacy 위치/거부 조건은 새 바이너리와 정확히 같다. 마지막 이식용 정수형/표준 헤더 추가 후의 로컬 native 바이너리도 검사한 바이너리와 byte-identical다.

비교 시트 6개를 직접 검사했다. 실루엣 위치, UV 방향, 공유 메시 배치와 구의 접선 경계가 Cycles 기준과 일치한다. 64 samples native Spectral 조명 렌더 세 조건을 CPU와 Metal에서 모두 완료·직접 검수했다. 구의 접선 seam은 원본 Cycles에도 존재한다. Native 영상의 노이즈·경계 보정 차이와 수렴 품질을 동일하다고 주장하지 않는다.

Runtime native SHA-256:

`0c1210e5287f1fd7c21576b1b3bf0af565c6cc272bc62d54006462e4cefd30f5`

시험 코드는 `dev-tools/cycles-vector-displacement-test.py`, 기존 normal/bump/displacement scripts와 native 저장소의 `displacement-space-properties-test.py`/`mikktspace-properties-test.py`다. 원본 EXR/PNG/NPY, metrics, 실패 진단과 각 수정 단계의 지문·로그는 workspace `test-scenes/validation-2026-10-10/vector-displacement-2.11.22`에 보존한다. 공개/설치 검증 결과는 별도 배포 문서로 기록한다.

## 배포 전 0 입력 경계 검증

새 플랫폼 빌드의 pybind11 초기화 ABI는 native 저장소에서 모든 binding 파일에 같은 compile definition을 적용해 수정했다. Linux·Windows의 실제 설치 import/렌더 smoke 단계가 통과했다. 현재 macOS ARM CI 휠의 native SHA-256은 `e5198b1edc3e9f30222d54b098f91c03d097f37277db5774260dc254fa3dad7c`이며 전체 휠 출처/번들/사용자 설치 검증은 별도 게이트다.

미지원 값을 나타내던 숫자 `0` 때문에 연결되지 않은 Vector Displacement `Midlevel=0`과 scalar Displacement `Height=0`이 변위를 통째로 생략했다. 숫자 대체 동작은 유지하면서 미지원 표시의 객체 identity로 두 변위 입력 검사를 구분한다. 다른 reader 비교 동작은 바꾸지 않는다. Object/World/Tangent의 미연결 `Midlevel=0` 세 조건을 CPU와 Metal에서 1280×720, Spectral ON으로 검증했다. `Height=0`의 BUMP/DISPLACEMENT/BOTH 상수 및 기존 UV gradient 여섯 조건도 양쪽에서 검증했다. 정상 0을 오류로 세지 않으며 원본 씬 입력은 변경하지 않는다.

현재 Blender에서 전체 출력·열거·연결 입력 변환 검수 1,023조건은 예외 0, 경고 239조건, RNA에서 지정 불가인 ROTATION 1조건을 기록했다. 이는 호출 회귀 결과이며 경고를 지원 완료로 세거나 영상 합격률로 환산하지 않는다. 확대된 CI 121개, 추가 Height=0 12개, 최종 ZIP 104개, 실제 macOS 설치 104개 검사를 통과했다. 이 결과는 CUDA를 검증한 것이 아니며 확인된 CUDA 결함을 별도로 기록한다.

## 남은 acceptance 범위

- Vector BUMP/BOTH, scalar World 및 연결 Normal 입력.
- true displacement의 Geometry Incoming 방향 및 곡면 Bump 평가 미분값.
- adaptive/cage displacement, flat nonplanar polygon과 그룹 출력의 더 넓은 검사.
- 다중 재질 경계의 원본 버텍스 공유, 변위 후 Normal Map attribute 갱신.
- 제작 규모 프레임/viewport/F12, 혼합 재질·형상과 다른 플랫폼의 실제 Blender/GPU 렌더.

이 조건들은 C29를 미완료로 유지한다. OSL·베이킹은 기존 유보 범위를 유지하며, 다른 mapped transmission/SSS/박막/Principled Tangent/광선 경로 호환 작업도 계속 남아 있다.
