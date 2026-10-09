# Cycles Vector Displacement Incoming direction

아래 private 후보 검수 이후2.11.24 공개 배포와 실제 사용자 설치를 완료했다. 후속 검증은 문서 하단과 배포 기록을 참조한다. 전체 Cycles 호환 goal은 활성·미완료다.

Blender 5.2.1 LTS 소스 9e2066aef7ef7e20c142ad7bd3303138a4304c93의 intern/cycles/kernel/geom/shader_data.h::shader_setup_from_displace는 smooth shading을 강제한 뒤 wi=N으로 변위 그래프를 평가한다. SuperLuxCore는 명시적 Object/World 공간에서도 고정 +Z를 사용했다. Geometry Incoming을 Vector Displacement에 연결하면 원래 법선 대신 +Z 오프셋이 생겼다.

명시적 Cycles 공간 경로의 fixedDir를 변환·정규화한 shadeN으로 설정했다. 기본 NATIVE_SPACE 계약은 유지한다. MC 전송·재질·품질 정책은 변경하지 않았다. Scalar/legacy native 공간의 Incoming, 곡면 Bump 미분값과 변위 후 attribute 계약은 별도 잔여다.

공개 2.11.23에서 독립 기하 12개가 모두 실패했다. 수정 후보에서 평면/변하는 smooth normal, identity/회전/비균일 transform, Object/World 12개가 모두 통과했다. 기존 NATIVE_SPACE 기하 4개는 공개 baseline과 array_equal이다. 기존 native displacement 16개와 Mikk 13개도 통과했다.

기존 Cycles 그래프의 Incoming 6개(평면/곡면/음수 스케일 × Object/World)를 표준 Vector 검사에 추가했다. 확장한 표준 회귀는 CPU 52개·Metal 52개가 통과했다: Vector 30개와 기존 Normal Map/smooth/image Bump/scalar displacement 22개다. 총 149개 표적·회귀 검사(기하 12+4, native 16+13, Blender 52+52)이며 초기 12개 렌더 smoke 재실행은 중복 합산하지 않았다. 독립 제작 씬 수나 전체 호환률을 뜻하지 않는다.

1280×720, 기본 Spectral ON, denoiser/noise halt OFF. Incoming smoke 비교 시트 2개 및 전체 Vector 비교 시트 8개를 직접 확인했다. 곡면의 UV 없는 접선 seam은 원래 Cycles에도 있다. 정확한 픽셀 일치·수렴·전체 제작 조합을 주장하지 않는다.

Private native SHA-256: `f5aa58004e4a97f228de244e2bf70a162d59085effe773188a22cb6e87461b26`. full wheel/site-packages/cached wheel과 Python metadata를 같은 후보로 맞추고 매 Blender 프로세스에서 native 및 핵심 exporter 5개 hash를 확인했다. Runtime version 2.11.23은 private build 표시이며 공개 be60dd8d native와 구분해야 한다.

원본 evidence: workspace test-scenes/validation-2026-10-10/displacement-incoming-candidate. 공개 ZIP·타 플랫폼·NVIDIA 실제 렌더·제작 GUI 검증은 아직 별도 gate다.


## 2.11.24 공개 배포 후속 검증

이 수정은 공개2.11.24 engine와 addon ZIP에 포함되었고 실제 사용자 Blender도2.11.24로 설치했다. exact native SHA `c7439663dcbf734ce5296dee46bf3ed85d689c7381cbaa15330f4c24d0dff322`로 CI·fresh ZIP·actual 설치의591개 표적 회귀와45개 비교 시트를 확인했다. 위 private 후보 결과와 별도 빌드의 증거이며 같은 검사로 합산하지 않는다. [배포 검수 기록](2026-10-10-deployment-2.11.24.md)이 현재 상태를 설명한다. 전체 호환 goal과 각 문서의 잔여 범위는 미완료다.
