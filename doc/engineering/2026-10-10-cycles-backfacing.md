# Cycles Geometry Backfacing spectrum evaluation

Geometry Backfacing를 발광 Color/Strength에 연결하면 앞면과 뒷면이 반대로 평가되던 오류를 수정했다. HitPointFieldTexture의 scalar 평가와 GPU texture 함수는 Dot(fixedDir, geometryN)<0을 사용하지만 C++ spectrum 평가는 >0이었다. Spectrum 평가도 <0으로 맞췄다. GPU kernel/ABI, 샘플링·MC 전송·품질 정책은 변경하지 않았다.

공개 2.11.23 baseline은 직접 Color/Strength 앞·뒷면 4개씩 CPU·Metal에서 모두 실패했다. 수정 후보는 직접 Color/Strength/Math Strength 및 상수 대조 8개씩, 다른 표면을 비추는 Color/Math Strength 앞·뒷면과 기본/중첩 transparent 발광 대조 6개씩 모두 통과했다. CPU 14+Metal 14=28개 표적 검사다. 초기 prototype 재실행은 중복 합산하지 않았다.

Blender 5.2.1 LTS, 1280×720, Spectral ON, denoiser/noise halt OFF. 직접 연결은 각 16 samples; irradiance는 Cycles 128/SuperLuxCore 256 samples다. 그래프를 변경하지 않고 엔진만 전환했다. 직접 출력은 MAE 0; irradiance의 앞면 조건은 두 엔진 모두 0, 뒷면 조건은 비영(非零) 조명이다. 최종 비교 시트 4개를 직접 확인했다. 샘플 수가 다른 이미지의 노이즈를 품질·성능 비교로 사용하지 않는다. 픽셀 동일성·제작 전체 씬 수렴을 주장하지 않는다.

Private native SHA-256: `0833c117bcdeb517c5d5c1eff9eb03202557e255aca23919a548e3e5896643e8`. 매 Blender 프로세스에서 native version/metadata/hash 및 exporter 5개 hash를 검증했다. Metal 로그의 실제 장치는 Apple M5 Pro다. 기록된 초기 runtime identity의 patch_sha256만 Incoming에서 상속된 값이라 actual diff hash로 정정했다. 원본 로그는 보존했다.

아래 private 후보 수정은 현재 공개2.11.24와 실제 사용자 설치에 포함된다. 타 플랫폼 실제 렌더·다른 Backfacing 소비 노드 조합 및 전체 Cycles 호환 goal은 미완료다. Incoming 변위 검사의 149개는 다른 private native hash의 별도 증거이며 같은 빌드의 검사로 합산하지 않는다.

Evidence: workspace test-scenes/validation-2026-10-10/backfacing-candidate. Regression scripts: addon dev-tools/cycles-backfacing-test.py 및 cycles-add-emitter-test.py.


## 2.11.24 공개 배포 후속 검증

이 수정은 공개2.11.24 engine와 addon ZIP에 포함되었고 실제 사용자 Blender도2.11.24로 설치했다. exact native SHA `c7439663dcbf734ce5296dee46bf3ed85d689c7381cbaa15330f4c24d0dff322`로 CI·fresh ZIP·actual 설치의591개 표적 회귀와45개 비교 시트를 확인했다. 위 private 후보 결과와 별도 빌드의 증거이며 같은 검사로 합산하지 않는다. [배포 검수 기록](2026-10-10-deployment-2.11.24.md)이 현재 상태를 설명한다. 전체 호환 goal과 각 문서의 잔여 범위는 미완료다.
