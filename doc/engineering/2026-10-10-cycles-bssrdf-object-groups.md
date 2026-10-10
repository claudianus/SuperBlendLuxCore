# Cycles 내부 산란 물체·재질 조각 경계, 2026-10-10

전체 무변환 Cycles 씬 호환 goal은 활성·미완료다. 이 변경은
[CPU 내부 산란 후보](2026-10-10-cycles-bssrdf-transport.md)를 확장한다.
공개2.11.27의 양수 standalone SSS 실패와 실제 사용자 설치는 별도이며,
release adapter를 이 시험 구현으로 전환하지 않았다.

## 수정

한 Blender 물체는 재질별 native 메시로 나뉜다. 진입 메시 번호만으로
내부 산란의 출구를 찾으면 다른 재질 조각의 경계가 빠진다. 닫힌 상자의
native 재현 조건에서 방사량 약30%가 손실됐다. 한 물체의 재질 조각은
`.subsurfacegroup`으로 묶고, 복제 인스턴스마다 별도의 그룹을 부여한다.
사용자가 지정한 Object ID가 같아도 산란 물체를 합치지 않는다.
메시 뒤에 추가되는 머리카락·입자 조각은 따로 유지한다.

native의 `SetObjectSubsurfaceGroup`은 C++/Python에서 그룹 변경과 속성
캐시 무효화·geometry edit를 처리한다. native DuplicateObject는 정적·모션
모두 그룹을 자동 상속하지 않으며, exporter가 각 복제의 대응 재질 조각을
명시적으로 묶는다. 단일 재질 물체는 기존 메시 경계를 쓴다.

## 검수

격리 패키지의 native SHA256은
`26ea4c3aa544a14e99732b52390e1fd593890f544bb45a943e475c2b65032b00`이며
metadata는2.11.27이다. 공개27 native와 구분한다. 전체 wheel RECORD·설치
payload·캐시 wheel, addon266 Python 파일과459 payload 파일 및 핵심 소스
해시를 검수했다. 실제 사용자 프로필은 수정하지 않았다.

native33개 계약, exporter3개 계약, 일반 CPU·LIGHTCPU·실제 M5 Pro Metal
발광5개 회귀가 통과했다. exporter 계약은 재질/머리카락 분리와 같은 AOV
ID를 가진 정적·모션 복제의 독립 그룹을 검사한다. Blender 실행에는
`--python-exit-code 1`을 사용하고 완료 표식과 JSON까지 확인한다.

720p128spp CPU7쌍을 현재 native로 렌더하고 비교 이미지를 직접 확인했다.
새 재질 조각·collection instance 장면의 native/Cycles mean ratio는
각각1.004653·1.004505다. 형태·음영·색 번짐을 보존하고 재질 경계의 검은
틈이 보이지 않았다. 기존 rough/aniso·색·partial RGB Radius·textured entry·
발광 좌표 control도 다시 검수했다. 이 수치를 전체 호환률로 바꾸지 않는다.
모션 검사는 그룹 전달 계약이며 애니메이션 실렌더 완료를 뜻하지 않는다.

증거는 작업 공간
`test-scenes/validation-2026-10-10/cycles-bssrdf-object-groups`에 보존한다.
엔진 상세는 형제 저장소의 같은 이름 engineering 문서에 있다.

Metal nonlocal walk와 그룹 payload, adjoint/LT/BIDIR/PDF/MIS,
mixed/Add/Principled·Skin/Burley/Legacy, spectral Radius, 작은 양수 정밀도,
출구 Normal/Bump ray context와 Volume 조합·제작/애니메이션/GUI/플랫폼
검수가 남는다. 정식 호환 배포와 전체 goal의 완료 판정도 아직 남아 있다.
