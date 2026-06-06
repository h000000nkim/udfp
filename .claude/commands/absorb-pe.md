---
description: PE-generation 모듈의 함수를 UDFP IR 모델 위에 흡수. 흡수 매핑표에 따라 작업하고 회귀 테스트로 검증
argument-hint: [PE-generation 함수명 또는 모듈명 (hwp_ole_patch|hwp_fill::normalize_para_headers 등)]
---

# PE-generation 자산 흡수 작업

`docs/pe-generation-mapping.md`에 따라 PE-generation의 코드를 UDFP IR 모델 위에 재구성.

## 절차

1. `docs/pe-generation-mapping.md`에서 `$ARGUMENTS`에 해당하는 매핑 확인
2. 흡수 위치(UDFP 경로)와 흡수 방식(거의 그대로 / 재작성 / 잔류) 파악
3. PE-generation 원본 코드 검토 (사용자가 코드를 제공해야 함)
4. UDFP 위치에 IR 모델 기반으로 재구성
   - 함정 회피 로직 보존 (`@.claude/rules/hwp-parsing.md`)
   - 인터페이스를 UDFP 스타일로 정리
5. 단위 테스트 작성
6. 회귀 테스트 작성: PE-generation 원본과 동일 입력에 동일 결과 산출 확인

## 검증

```bash
pytest tests/unit/test_<흡수_모듈>.py
pytest tests/regression/test_pe_generation_compat.py -k "$ARGUMENTS"
```

## 잔류 결정 시

매핑표에서 "(UDFP에 흡수 안 함)"으로 분류된 함수는 흡수하지 말고 PE-generation 측에 잔류시킬 것. 사유를 보고:

- 양식 채우기 도메인 특화
- 오케스트레이션 책임
- UDFP 라이브러리 책임 범위 초과

## 보고 형식

```
=== PE-generation 흡수 작업 결과 ===
대상: $ARGUMENTS

매핑 정보:
  - PE-generation 위치: <경로>
  - UDFP 위치: <경로>
  - 흡수 방식: 거의 그대로 / 재작성 / 잔류

작업 내용:
  - <어떤 변환을 했는지>

함정 보존 확인:
  - <어떤 함정 회피 로직이 보존되었는지>

회귀 검증:
  - 단위 테스트: <PASS/FAIL>
  - 회귀 테스트: <PASS/FAIL>

[잔류 결정의 경우]
  사유: <왜 흡수하지 않는지>
  PE-generation 측 처리 권고: <어떻게 사용해야 하는지>
```

## 절대 금지

- IR 모델로 재작성 없이 PE-generation 코드를 그대로 복사
- 함정 회피 로직 누락 (특히 controlMask 보존, OLE FAT 충돌, charCnt MSB 등)
- 회귀 테스트 없이 흡수 완료 보고
- 매핑표에 "잔류"로 분류된 함수를 강제로 흡수
