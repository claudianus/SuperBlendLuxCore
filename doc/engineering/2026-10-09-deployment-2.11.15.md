# 2.11.15 공개 ZIP과 사용자 Blender 설치 검증

엔진 빌드 소스는 `5953e309e0ea3ad6e50636818728c094b7395f6c`, 확장 빌드 소스는 `0d067d9d79cf200bfc338d527208cc80de41dba1`이다. 네 플랫폼 엔진 wheel 및 확장 ZIP 빌드·증명 작업이 통과했다. ZIP 네 개의 구조·Python 3.13 ABI·엔진 버전·도구를 검사했고, 내부 wheel SHA-256이 증명된 동일 CI wheel과 같음을 확인했다. 네 wheel과 네 ZIP의 산출물 증명을 각각 해당 소스 SHA로 검증했다.

- 엔진 CI: https://github.com/claudianus/SuperLuxCore/actions/runs/37887168215
- 확장 CI: https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37889585320
- 엔진 고정 릴리스: https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.15
- 확장 공개 릴리스: https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.15

| ZIP | SHA-256 |
|---|---|
| SuperLuxCore-2.11.15-linux_x64.zip | `901d83e358c6c49bc226e86ae53a3e7108ac1d08676b315967c5150159438665` |
| SuperLuxCore-2.11.15-macos_arm64.zip | `44f4bdc3813305e0e541b0b9c10e8f03ca309d5e6cbf2407f0078bbe831968ba` |
| SuperLuxCore-2.11.15-macos_x64.zip | `97e11f1c50546d6f281b312b952393a714ed3b17e9b8ce15bfb623dc9c46b674` |
| SuperLuxCore-2.11.15-windows_x64.zip | `921e2f384569a569f2cd4a911ed0d6e056ce0a8a22aa419519ca2b8ecd3341f5` |

Apple M5 Pro·Blender 5.2.1에서 내려받은 공개 ZIP을 격리 프로필에 오프라인 설치했다. 실제 로드한 네이티브·배포 메타데이터 버전은 2.11.15이고 모듈 경로는 해당 프로필 안이다. 기존 Cycles Principled·금속·유리·4D Voronoi 장면을 기본 스펙트럼 1280×720·32샘플로 CPU·Metal 렌더하여 유한 출력·양의 신호·변환 오류 없음과 이미지를 확인했다. 실제 CI wheel의 기본 스펙트럼 Checker 좌표 12조건도 장치별로 통과했다. 32샘플의 잔여 노이즈와 CPU/Metal 노이즈 제거 차이는 전체 품질 완료로 판단하지 않는다.

사용자 Blender 프로필은 이전 2.11.12 개발 wheel을 가리키고 있었다. 기존 확장·환경설정·wheel 소스 설정을 `/tmp/slc-actual-before-v15`에 백업한 뒤 기본 wheel 소스로 복원하고 공개 ZIP을 설치했다. 실제 사용자 프로필에서 2.11.15 모듈 경로와 기본 스펙트럼 CPU 720p 렌더를 확인했으며 설치된 네이티브 바이너리 SHA-256이 증명된 CI wheel과 동일했다. 실제 사용자 설치본의 Metal 기본 스펙트럼 720p 렌더도 통과했으며 로그·수치·이미지를 증거 폴더에 보존했다.

증거는 작업 공간 `test-scenes/validation-2026-10-09/public-bundle-2.11.15/`다. Windows/Linux/Intel GPU의 현장 실행 검증을 뜻하지 않는다. 전체 의미 호환 목표는 미완료이며, 남은 항목과 후속 main 2.11.16의 Mapping은 [목표 기록](2026-10-09-cycles-scene-goal.md)에서 구분한다. 실제 Metal 실행이 실패한 2.11.14 후보는 초안으로 회수했고 공개하지 않았다.
