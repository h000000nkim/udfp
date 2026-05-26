---
paths:
  - "udf/validation/**"
  - "tests/validation/**"
  - "tests/roundtrip/**"
---

# 검증 시스템 정책 (1급 모듈)

`udf.validation`은 UDF의 1급 모듈임. 모든 라운드트립과 변환의 정확성은 이 모듈을 통해 자동 검증됨.

## 검증 4계층

| 계층 | 역할 | 자동 실행 |
|------|------|----------|
| **구조 정합성 (Format Rules)** | 포맷별 R-규칙으로 파일 무결성 검증 | 모든 변환 후 자동 |
| **시맨틱 동등성 (Semantic Diff)** | 두 문서의 의미 단위 일치 | 라운드트립 자동 |
| **Verbatim 동등성** | 같은 포맷끼리 raw bytes 또는 논리 동등성 | 라운드트립 자동 |
| **시각 동등성 (Visual Diff)** | 렌더링 후 픽셀/레이아웃 비교 | 수동, 참고용 |

## R-규칙 시스템

각 포맷은 자체 R-규칙 집합을 가짐. 새 트랙 추가 시 R-규칙도 함께 정의.

### 규칙 클래스 패턴

```python
class ValidationRule(Protocol):
    rule_id: str          # "R1", "HX-1", "P-1", ...
    severity: Literal["warning", "error"]
    description: str

    def check(self, doc: ParsedDocument) -> RuleResult: ...
    def fix(self, doc: ParsedDocument) -> ParsedDocument | None: ...
```

### 트랙별 R-규칙

- **HWP**: R1-R4 (`udf/validation/hwp/rules.py`) + I1-I3 (`integrity.py`) — **구현 완료**
- **HWPX**: HX-1~4 — 계획됨, 미구현 (현재 시맨틱 diff만으로 검증)
- **PDF**: P-1~4 — 계획됨, 미구현 (PDF는 읽기 전용이므로 생성 시점까지 불필요)
- **DOCX**: D-1~3 — 계획됨, 미구현 (현재 시맨틱 diff만으로 검증)

상세: `dev/architecture.md` §8.3

## 통과 기준

라운드트립 통과 조건 (모두 만족해야 함):

1. **시맨틱 diff = 0**
2. **R-규칙 모두 통과** (warning_count = 0, error_count = 0)
3. **외부 도구 검증 (예: rhwp validate)** rc = 0 또는 도구 없음

```python
def is_passing(report):
    return (
        report.semantic_diff.is_empty()
        and report.warning_count == 0
        and report.error_count == 0
        and report.external_check.rc != "fail"  # 도구 없음은 통과로 간주
    )
```

## Visual Diff 정책

- Visual diff는 **참고용**이며 통과 기준이 아님
- **단일 렌더러 신뢰 금지** (rhwp rowspan 버그 — `dev/known-issues/rhwp-rowspan.md`)
- 가능한 경우 다중 렌더러 비교

## 자동 수정 (Auto Fix)

`validation_loop()`는 검증 실패 시 자동 수정자를 적용 후 재검증:

```python
def validate_and_fix(path, format, max_iter=5):
    for _ in range(max_iter):
        report = validate(path, format)
        if report.is_passing():
            return report
        if not report.has_fixable_issues():
            break
        path = apply_auto_fixes(path, report)
    return report
```

자동 수정 가능한 규칙은 `Fix` 메서드를 구현. 자동 수정 불가한 위반은 사용자에게 보고하고 진행 중단.

## 의도된 손실 vs 비의도 손실

```python
class LossCategory(Enum):
    USER_EDITED = "user_edited"      # 의도됨, 통과
    FORMAT_LIMIT = "format_limit"     # MD 표현 한계, 통과 (사이드카 보존)
    UNINTENDED = "unintended"          # 통과 불가
```

비의도 손실이 하나라도 있으면 **검증 실패**. 사용자에게 어느 블록의 어느 필드가 손실되었는지 보고.

## 절대 금지

- 검증 실패를 사용자에게 "통과"로 보고
- 라운드트립 테스트를 `@pytest.mark.skip`으로 비활성화하여 통과 표시
- R-규칙 통과를 "거의 같으니 OK"라고 처리
- Visual diff 단독 통과를 라운드트립 통과로 인정
- 자동 수정 후 재검증 없이 종료

## 검증 도구 추가 시 주의

새로운 외부 검증 도구(예: 다른 HWP 렌더러)를 추가할 때:

1. **rc=0이 시각 정확성을 보장하지 않을 수 있음을 명시** (rhwp 사례)
2. 도구의 알려진 버그를 `dev/known-issues/`에 기록
3. 다중 렌더러 비교 정책에 통합

## PE-generation 회귀 검증

PE-generation에서 흡수한 검증 코드는 동일 입력에 대해 동일 결과를 산출해야 함:

```bash
pytest tests/regression/test_pe_generation_compat.py -v
```

이 테스트가 깨지면 흡수 작업 회귀이므로 즉시 보고.
