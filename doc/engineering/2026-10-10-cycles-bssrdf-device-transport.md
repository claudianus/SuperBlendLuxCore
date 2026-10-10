# Cycles BSSRDF CPU/Metal 검증 후보

기존 Cycles 씬을 변환·설정 수정 없이 대체로 올바르게 렌더한다는 전체
goal은 active이며 미완료다. 이번 후보는 standalone RANDOM_WALK의 실제
비국소 산란을 CPU와 Metal에서 검증한 단계다. 정식 2.11.27 어댑터의 양수
SSS는 기존 OpenPBR 경로를 사용하며, 알려진 Metal 어두워짐을 해결 배포했다고
계산하지 않는다. 사용자의 실제 Blender 설치도 변경하지 않았다.

`cycles-bssrdf-experimental-test.py`는 완전한 격리 패키지의 wheel RECORD,
캐시 wheel, 266개 런타임 Python 파일과 459개 프로필 항목, 네이티브 및
핵심 소스 해시를 확인한다. 프로세스 내부에서만 standalone SSS exporter를
교체하고 `SUPERLUXCORE_BSSRDF_DEVICE=CPU` 또는 `METAL`을 선택한다.
원본 노드·링크·입력·Cycles 설정은 편집하지 않는다. 미연결 영 법선의 기본값을
불필요한 상수 범프 텍스처로 만들지 않는다. 실제 연결된 법선은 내보내어
네이티브의 명시적 미지원 검사를 거치게 한다.

현재 staged native SHA256은
`4cfb861d93b8d10b8509418e5c48ae928fda30082e3260b3d1bac95ebaba835d`다.
버전 메타데이터는 2.11.27이며 공개 릴리즈 2.11.27 바이너리와 다르다.
네이티브 main은 `33ae1bd3c1ce60aee0dfc42ffeb2a0a4122755e3`다.

- CPU 계약 33개와 실제 Apple M5 Pro METAL_GPU 계약 17개를 통과했다.
  GPU 큐 모드 off/on에서 실제 비국소 산란, 검정 흡수, 타 물체 경계 무시,
  재질 분할 경계와 진입 계수 보존, 영 반경·부분 RGB 반경·Generated 기반
  영 Scale, 진입 AOV를 확인했다. 미검증 vertex connection과 진입/분할
  출구 범프는 명시적으로 거부한다.
- 현재 모듈의 일반 방출 회귀 5개가 CPU, LIGHTCPU, 실제 Metal에서 통과했다.
- 원본 그래프를 유지한 1280×720·128spp 장면 7개를 CPU와 Metal로 각각
  렌더하고 Cycles와 비교한 14쌍을 직접 검수했다. rough/aniso, 색상,
  부분 RGB 반경, 연결 Checker 색상, Generated 방출 좌표 대조군,
  재질 분할, 컬렉션 복제 경계를 포함한다. 좌표·실루엣·경계 연속성과
  색상 의미는 유지되며 작은 색/밝기 차이와 더 보이는 native Monte Carlo
  노이즈는 남아 있다. 복제 장면의 외곽 잘림은 세 렌더 모두 같은 구도다.
- 초기 CUDA gate가 벡터 인덱싱과 벡터 exp를 거부하여 wheel 배포를 차단했다.
  공통 스칼라 저장과 `Spectrum_Exp`로 수정한 최종 main은 실제 NVRTC gate를
  통과했다. Windows/Linux/macOS ARM/Intel 빌드는
  [GitHub run 38029335102](https://github.com/claudianus/SuperLuxCore/actions/runs/38029335102)에서
  진행 중이다. CUDA GPU 실행 검증을 의미하지 않는다.

| 장면 | CPU / Cycles 평균 | Metal / Cycles 평균 |
|---|---:|---:|
| rough-anisotropic | 1.011783 | 1.012324 |
| colored | 1.024873 | 1.025486 |
| partial-radius-rgb | 1.001297 | 1.001869 |
| textured-entry | 1.024510 | 1.025157 |
| generated-checker-emission | 1.019528 | 1.019505 |
| material-partitions | 1.004656 | 1.005295 |
| material-partition-instances | 1.004499 | 1.005169 |

이 평균은 해당 진단 장면의 결과이며 광범위한 호환율이나 픽셀 일치를
의미하지 않는다. 완전한 wheel, 핵심 소스, 원본 EXR/PNG, 비교 이미지와
검수 기록은 workspace의
`test-scenes/validation-2026-10-10/cycles-bssrdf-device-transport`에 보존한다.
네이티브 구조와 추정기 설명은 SuperLuxCore의 같은 이름 engineering 문서에
기록했다.

제작 기본 품질 설정은 유지한다. 실험 후보의 eye-only 제한을 제품 기본값으로
채택하지 않는다. adjoint/LT/BIDIR의 비국소 density/PDF/MIS, mixed/Add/Principled,
Skin/Burley/Legacy, 물리적 spectral Radius 및 partial/dynamic Radius, 임의의
작은 양수 반경, 출구 Normal/Bump·ray context, 명시적 Volume, 제작·애니메이션·
GUI·다른 플랫폼 GPU 실행 검증과 정식 어댑터 전환은 전체 goal의 남은 작업이다.
