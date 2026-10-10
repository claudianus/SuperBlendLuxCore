# Cycles BSSRDF native CPU candidate, 2026-10-10

전체 무변환 Cycles 씬 호환 goal은 활성·미완료다. 공개2.11.27의 양수
standalone SSS는 여전히 OpenPBR/bulk-volume 경로이고 알려진 어두운 영상
결함이 남는다. 이번 변경은 main의 native CPU 시험 구현과 검수 도구이며
release adapter나 실제 사용자 설치를 교체하지 않는다.

Native `cyclesbssrdf`는 진입에서 Color·Radius·Scale·IOR·Roughness·Anisotropy를
평가하고 보존한다. standalone의 직접 GGX alpha로 진입 방향을 샘플링하고,
동일 native mesh 내부의 random walk, 원본 Van de Hulst 및 저알베도 보정,
HG 위상함수, 채널 거리 PDF 혼합과 roulette 보상을 사용한다. 출구는
weight1 diffuse다. 일반 OpenPBR·볼륨·렌더 품질 기본값은 유지한다.

카메라에 보이는 진입 표면의 AOV와 자체 발광을 기록한 다음 산란 위치를
옮기며, 흡수된 경로는 종료한다. 완전 검정의 safe-divide 가중치와 all-local
Radius 한계, RGB 부분채널의 확률 보상, 동적 RGB Scale0도 검수했다.

## 격리 검수

`cycles-bssrdf-experimental-test.py`는 새 프로세스 안에서만 exporter를
교체하며 기존 Cycles 그래프를 수정하지 않는다. 전체 staged package,
캐시 wheel, addon runtime266 Python 파일, native/test source 해시를
확인한다. 시험 설정은 CPU eye-only이며 Metal·LT·PhotonGI·ReSTIR GI/PT를
사용하지 않는다. 이 제한을 제작용 품질 기본값으로 배포하지 않는다.

최종 native SHA는
`cb99bcb66d07c0c49e01e442b0eec518846e2602c6cd66937b117b4ba3cc21f6`이며
metadata는 기존2.11.27이다. 공개 wheel의 native SHA와 혼동하면 안 된다.
Native26 contract 조건이 통과했고 일반 양면 발광5개 회귀도 current-build
CPU·LIGHTCPU·실제 M5 Pro Metal에서 통과했다. 이는 Metal BSSRDF의 통과를
뜻하지 않는다.

개발 설치 스크립트는 repack 후 최종 wheel의 RECORD 해시·길이를 다시
작성하고 기존 RECORD 서명을 제거한다. 이전에는 새 native를 넣은 뒤에도
원래 공개 wheel의 파일 목록 해시를 유지했다. 전체 wheel entry와 설치
payload·캐시의 일치를 검사했으며 이 패키지 수정으로 native 바이트는
변하지 않았다. 마지막 새 Blender 프로세스에서 전체 패키지를 재확인했다.

720p128spp CPU 비교에는 roughness/aniso, colored, partial Radius RGB,
textured entry와 별도 generated checker emission control을 사용했다.
native/Cycles mean ratio는 각각 대략1.012·1.025·1.001·1.025이고 발광
control은1.019다. 그래프 지문과 저장 EXR을 보존한다. 평균과 영상 검토는
분리하며 프로젝트 호환률로 환산하지 않는다. 텍스처 경계의 초기 미리보기
판정은 독립 EXR·PNG 픽셀 검사와 비교 이미지에서 재현되지 않아 철회했다.
좌표 변환 코드는 이 판정 때문에 변경하지 않았다.

## 여전히 필요한 구현

Metal nonlocal walk, LT/BIDIR adjoint 및 위치 PDF/MIS, mixed/Add/Principled
closures, Skin/Burley/Legacy, spectral partial/dynamic/unbounded radius,
작은 양수 Radius의 정밀도, 한 Blender 물체의 material partition 묶기,
출구 Normal/Bump의 ray context, 명시적 Volume 조합, 제작·애니메이션·GUI
검수가 남는다. spectral partial와 동적 Radius/Scale은 material context를
포함해 worker 시작 전에 차단한다. OSL·베이킹은 기존 별도 단계다.

Native 구현 상세는 형제 엔진 저장소
`doc/engineering/2026-10-10-cycles-bssrdf-transport.md`에 있다. 검수 증거는
작업 공간 `test-scenes/validation-2026-10-10/cycles-bssrdf-cpu-transport`에
보존한다. 공개2.11.27의 과거 실패 증거와 private candidate의 결과를
합치지 않는다. 정식 adapter 전환과 배포는 이 잔여 구현을 계속 처리한다.

Follow-up: [CPU material partition and instance boundary verification](2026-10-10-cycles-bssrdf-object-groups.md). The original candidate evidence above remains preserved separately.
