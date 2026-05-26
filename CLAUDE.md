# UDF — Universal Document Format

어떤 문서 포맷(HWP/HWPX/PDF/DOCX/XLSX 등)이든 **Document Model**로 변환하고, 그 모델에서 다시 어떤 포맷으로든 재생성하는 라이브러리. 포맷 공통 기능은 블록 트리로 정규화하고, 포맷 고유 기능은 `unsupported` 메타데이터로 보존. 같은 포맷 라운드트립은 verbatim 레이어로 무손실 보장.

상세 아키텍처: `@dev/architecture.md`

**관계 프로젝트:** PE-generation (별도 저장소). UDF를 라이브러리로 import하여 양식 채우기에 활용. UDF의 HWP 처리 자산은 PE-generation에서 흡수됨.

---

## 절대 원칙 (NEVER)

1. **무손실 라운드트립 위반 금지.** 변환에서 정보가 손실되면 그 변환은 실패임. 모든 변환은 LossReport를 동반해야 함.
2. **Verbatim 계층 절대 손실 금지.** 알 수 없는 chunk는 폐기하지 않고 `unknownChunks`에 raw bytes로 보존함. controlMask, instanceId 같은 미문서화 필드도 보존.
3. **AGPL 코드 직접 인용 금지.** pyhwp, PyMuPDF, pymupdf4llm, python-ooxml 등은 알고리즘만 참조하고 코드는 직접 작성. 상세: `@dev/license-notes.md`
4. **수정 후 라운드트립 + R-규칙 + 시맨틱 diff 통과 필수.** `/roundtrip-test`로 검증. 둘 중 하나라도 실패하면 통과로 보고하지 말 것.
5. **rhwp validate rc=0을 시각 정확성의 기준으로 사용 금지.** 구조 정합성 + 파싱 가능성 검증 도구이지 시각 정확성 보장 아님 (`@dev/known-issues/rhwp-rowspan.md`).

## 우선순위

- **P0**: HWP ↔ MD ↔ HWP 무손실 라운드트립
- **P0**: PDF → MD 편집 가능 변환
- 마일스톤: `@dev/architecture.md` §10

## 생성 모드 (HWP/HWPX 트랙)

UDF는 두 가지 생성 모드를 가짐:

- **Seed Patch 모드:** 원본 컨테이너가 있을 때 변경된 스트림만 교체. 미수정 영역의 비트 단위 무결성 자연 보장. **기본 권장.**
- **From Scratch 모드:** 원본이 없을 때 Document Model에서 모든 컨테이너 재생성. fallback.

원본이 있는 경우 Seed Patch가 항상 더 안전함. 사용자가 명시적으로 강제하지 않는 한 자동으로 Seed Patch 우선.

## 검증 시스템

`udf.validation`은 1급 모듈로 운영됨. 모든 라운드트립은 다음 두 조건을 동시 통과해야 함:

- **시맨틱 diff = 0** (의미 보존)
- **트랙별 R-규칙 통과** (구조 정합성)
  - HWP: R1-R4 (charCnt, count, lineSeg, OOB charShape) — **구현 완료**
  - HWPX: HX-1~4 — 계획됨, 미구현
  - PDF: P-1~4 — 계획됨, 미구현
  - DOCX: D-1~3 — 계획됨, 미구현

Visual diff는 참고용이며 단일 렌더러 신뢰 금지 (rhwp rowspan 버그).

## 기술 스택

- Python 3.11+ (주력)
- Rust + PyO3 (병목 가속, 처음부터 인터페이스 분리)
- Pydantic v2, pytest, ruff + mypy, maturin

## 자주 쓰는 명령

```bash
pytest                                    # 전체 테스트
pytest tests/roundtrip/                   # 라운드트립 검증
pytest tests/validation/                  # R-규칙 검증
pytest tests/regression/                  # PE-generation 회귀 검증
pytest -k hwp                             # HWP 트랙만
ruff check . && ruff format .
mypy udf/
maturin develop --release                 # Rust 가속 빌드
udf diff a.hwp b.hwp --semantic           # 시맨틱 diff
udf validate file.hwp                     # 구조 정합성 검증
```

## 작업 절차

기능을 추가하거나 수정할 때:

1. 관련 라이브러리 알고리즘을 `@dev/library-mapping.md`에서 확인
2. PE-generation 자산이 있는지 `@dev/pe-generation-mapping.md` 확인
3. Python으로 구현 (정확성 우선)
4. 테스트 코퍼스에 라운드트립 케이스 추가
5. `pytest tests/roundtrip/ tests/validation/` 통과 확인
6. PE-generation 트랙 변경 시 `pytest tests/regression/`도 통과
7. 손실 보고서 검토

## 작업 완료 기준

- "실행됨"과 "목적 달성됨"은 다르다. 작업 완료 보고 전에 반드시 구분할 것.
- 검증 수단 자체가 올바르게 작동하는지 먼저 확인할 것.
  - 검증 코드가 항상 성공을 반환하도록 구현되어 있다면 그 검증은 무의미하다.
  - exit code, 반환값, 출력 문자열이 실제 실패 상황에서도 변하지 않는다면 보고하고 수정할 것.
- 성공 조건은 사전에 falsifiable한 형태로 정의할 것.
  - 나쁜 예: "오류 없이 실행됨"
  - 좋은 예: "출력에 X가 포함되고 Y가 없음", "파싱 실패 시 exit code 1"
- 검증 단계를 직접 구현한 경우, 그 구현이 실제로 실패를 감지할 수 있는지 역검증할 것.
  - 의도적으로 잘못된 입력을 넣었을 때 실패로 판정되는지 확인.
- 지시에 "확인하라", "검증하라"가 포함된 경우, 수단(도구 실행)이 아닌 목적(실제 상태 파악)을 기준으로 완료 여부를 판단할 것.
- 불확실하거나 검증이 불완전한 경우, 추정으로 완료 처리하지 말고 불확실성을 명시하여 보고할 것.

## 더 알아야 할 정보

- API 레퍼런스: `@docs/api-reference.md`
- 내부 개발 문서 (아키텍처, 스펙, known-issues 등): `dev` 브랜치에서 관리

## 사용자에 대한 주의

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

