# 등록 노드별 호출 검수 목록

99개 생성 가능 노드를 포함한 RNA 이름 102개를 모두 기록한다. 예외·경고가 없는 반환은 수치·영상 호환성 합격이 아니다. 주 검수 보고서의 소스·영상 결과를 함께 본다.

| 노드 유형 | 조건 | 예외 | 경고 조건 | 판정 |
|---|---:|---:|---:|---|
| ShaderNode | 0 | 0 | 0 | 기반/추상 유형: 생성 불가 |
| ShaderNodeAddShader | 3 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeAmbientOcclusion | 12 | 0 | 12 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeAttribute | 16 | 0 | 16 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeBackground | 3 | 0 | 3 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeBevel | 3 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeBlackbody | 2 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeBrightContrast | 4 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeBsdfAnisotropic | 10 | 0 | 1 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeBsdfDiffuse | 4 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeBsdfGlass | 9 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeBsdfHair | 7 | 0 | 7 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeBsdfHairPrincipled | 18 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeBsdfMetallic | 13 | 0 | 12 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeBsdfPrincipled | 35 | 0 | 1 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeBsdfRayPortal | 4 | 0 | 4 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeBsdfRefraction | 6 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeBsdfSheen | 5 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeBsdfToon | 6 | 0 | 6 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeBsdfTranslucent | 3 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeBsdfTransparent | 2 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeBump | 7 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeCameraData | 3 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeClamp | 4 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeCombineColor | 6 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeCombineXYZ | 4 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeCustomGroup | 0 | 0 | 0 | 기반/추상 유형: 생성 불가 |
| ShaderNodeDisplacement | 6 | 0 | 6 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeEeveeSpecular | 10 | 0 | 10 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeEmission | 3 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeFloatCurve | 3 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeFresnel | 3 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeGamma | 3 | 0 | 3 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeGroup | 0 | 0 | 0 | 출력 없는 기본 구성: 호출 없음 |
| ShaderNodeHairInfo | 6 | 0 | 3 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeHoldout | 1 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeHueSaturation | 6 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeInvert | 3 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeLayerWeight | 6 | 0 | 3 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeLightFalloff | 9 | 0 | 9 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeLightPath | 15 | 0 | 1 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeMapRange | 27 | 3 | 18 | 예외 재현 |
| ShaderNodeMapping | 8 | 0 | 7 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeMath | 44 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeMix | 104 | 0 | 56 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeMixRGB | 23 | 0 | 14 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeMixShader | 4 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeNewGeometry | 9 | 0 | 3 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeNormal | 4 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeNormalMap | 7 | 0 | 4 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeObjectInfo | 6 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeOutputAOV | 0 | 0 | 0 | 출력 없는 기본 구성: 호출 없음 |
| ShaderNodeOutputLight | 0 | 0 | 0 | 출력 없는 기본 구성: 호출 없음 |
| ShaderNodeOutputLineStyle | 0 | 0 | 0 | 출력 없는 기본 구성: 호출 없음 |
| ShaderNodeOutputMaterial | 0 | 0 | 0 | 출력 없는 기본 구성: 호출 없음 |
| ShaderNodeOutputWorld | 0 | 0 | 0 | 출력 없는 기본 구성: 호출 없음 |
| ShaderNodeParticleInfo | 8 | 0 | 5 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodePointInfo | 3 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeRGB | 1 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeRGBCurve | 3 | 0 | 3 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeRGBToBW | 2 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeRadialTiling | 20 | 0 | 20 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeRaycast | 25 | 0 | 25 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeScript | 0 | 0 | 0 | 출력 없는 기본 구성: 호출 없음 |
| ShaderNodeSeparateColor | 12 | 0 | 6 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeSeparateXYZ | 6 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeShaderToRGB | 4 | 0 | 4 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeSqueeze | 4 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeSubsurfaceScattering | 8 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeTangent | 4 | 0 | 4 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeTexBrick | 22 | 0 | 22 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeTexChecker | 10 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeTexCoord | 7 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeTexEnvironment | 6 | 0 | 4 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeTexGabor | 21 | 0 | 12 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeTexGradient | 16 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeTexIES | 4 | 0 | 4 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeTexImage | 22 | 0 | 12 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeTexMagic | 8 | 8 | 0 | 예외 재현 |
| ShaderNodeTexNoise | 110 | 22 | 0 | 예외 재현 |
| ShaderNodeTexSky | 4 | 0 | 4 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeTexVoronoi | 51 | 3 | 40 | 예외 재현 |
| ShaderNodeTexWave | 34 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeTexWhiteNoise | 10 | 2 | 6 | 예외 재현 |
| ShaderNodeTree | 0 | 0 | 0 | 기반/추상 유형: 생성 불가 |
| ShaderNodeUVAlongStroke | 1 | 0 | 1 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeUVMap | 1 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeValToRGB | 4 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeValue | 1 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeVectorCurve | 3 | 0 | 3 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeVectorDisplacement | 6 | 0 | 6 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeVectorMath | 32 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeVectorRotate | 10 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeVectorTransform | 8 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeVertexColor | 2 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeVolumeAbsorption | 3 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeVolumeCoefficients | 5 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeVolumeInfo | 4 | 0 | 4 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeVolumePrincipled | 10 | 0 | 2 | 경고·대체 또는 데이터 조건 확인 필요 |
| ShaderNodeVolumeScatter | 4 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeWavelength | 2 | 0 | 0 | 변환 반환됨: 영상 동등함 별도 검증 |
| ShaderNodeWireframe | 3 | 0 | 1 | 경고·대체 또는 데이터 조건 확인 필요 |
