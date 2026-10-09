# 2.11.13 배포 검증

엔진 소스는 `bc8e30604297ed5b82207a56a727b36d2d222db9`, 확장 빌드 소스는 `4a546eea09fcc78d7cb7d347a85caba4f64980ac`이다. 확장·엔진 버전은 2.11.13, Blender Python ABI는 3.13이다.

- 엔진 빌드: https://github.com/claudianus/SuperLuxCore/actions/runs/37863618965
- 엔진 고정 릴리스: https://github.com/claudianus/SuperLuxCore/releases/tag/wheels-v2.11.13
- 확장 빌드: https://github.com/claudianus/SuperBlendLuxCore/actions/runs/37866381583
- 확장 릴리스: https://github.com/claudianus/SuperBlendLuxCore/releases/tag/v2.11.13

네 플랫폼 엔진 wheel 빌드와 엔진 산출물 증명 작업이 성공했다. Apple silicon wheel의 GitHub 산출물 증명을 엔진 소스 커밋과 대조해 검증했다. 확장 패키지 검사·최종 설치 실행 결과는 아래에 기록한다.

실행 검증 환경은 Apple M5 Pro, Blender 5.2.1이다. Windows·Linux·Intel Mac의 패키지 검사와 빌드 성공을 해당 플랫폼 GPU 실행 검증으로 세지 않는다. 제작 장면과 잔여 호환성 문제는 [720p 제작 장면 보고서](2026-10-09-production-render.md)에 기록했다. 전체 99% 호환 완료를 선언하지 않는다.

## 최종 패키지 검증

확장 빌드와 증명 작업이 모두 성공했다. CI 최종 ZIP 네 개를 내려받아 `cmake/verify_bundle.py`로 엔진 버전·Python ABI·선언한 wheel·Metal 번역 도구·Windows/Linux NVRTC 구성을 검사하여 모두 통과했다. 네 ZIP 모두 `gh attestation verify --source-digest 4a546eea09fcc78d7cb7d347a85caba4f64980ac`로 확인했다.

[GitHub 산출물 증명](https://github.com/claudianus/SuperBlendLuxCore/attestations/54150593)과 ZIP SHA-256은 다음과 같다.

| 플랫폼 | SHA-256 |
|---|---|
| Linux x64 | `861c707422eb9bda7ec1198d39cff50e1bd4aaaea7077907b260edfa60a9279c` |
| Apple silicon | `dccd7560eba995eb9b2790e2e09ae8408a25695d70a7d1fe087c6ee6462d2963` |
| Intel Mac | `7c95be3f7d16d641fee01b41bc67b7d838cda58f59bd75d0d3bd4d9db88f5718` |
| Windows x64 | `78730b5736a0aea2e39ad484129c30c7391c8b7d8681dcba4ff773e366c79b0a` |

릴리스에 첨부된 Apple silicon ZIP을 별도로 다시 받아 CI ZIP과 해시가 같음을 확인했다. 내부 엔진 wheel 해시도 이미 검증한 CI wheel의 `8c932ebd75ca4f277c0fd0cf2d41a0599f1167d67d023f6aa73c6d4ddd4446b1`과 같다. 새 `/tmp/slc-final-public-profile`에 오프라인 설치하고 실제 엔진 모듈 경로와 버전 2.11.13을 확인했다. 빈 Metal 캐시에서 기본 스펙트럼 1280×720·32샘플 렌더를 커널 준비 포함 48.25초에 완료했다. EXR의 모든 값이 유한하고 양의 신호가 있음을 검사했으며 PNG에서 방향·음영·비정상 색을 직접 확인했다.

ZIP·렌더·증명 JSON·해시 및 로그는 작업 공간 `test-scenes/validation-2026-10-09/public-bundle`에 보존한다.

최종 설치본에서 개발 빌드 경로를 제외하고 공유 텍스처 재정의 6조건, 카메라 매질 8조건, 범프 합성 12조건을 실행하여 모두 통과했다. 별도 CI wheel 설치본의 720p 좌표 4조건 및 벡터·Mix Metal 20조건도 통과했으며 최종 ZIP 내부 wheel이 이 검증본과 동일함을 해시로 확인했다.

검증 후 `v2.11.13`을 초안에서 정식 공개 릴리스로 전환했다. 빌드 소스와 이후 문서 갱신 커밋은 구분한다.
