---
name: HWP 단락 삭제 금지 — 한컴이 손상으로 판정
description: HWP Section0에서 단락을 추가/삭제하면 한컴이 "파일 손상"으로 판정. 내용 수정만 허용됨. Seed Patch 핵심 제약.
type: feedback
---

## HWP Section 스트림에서 단락(PARA_HEADER L0)을 추가하거나 삭제하면 한컴이 "파일 손상"으로 판정한다.

**Why:** 2026-05-02 f15_equations.hwp 생성 과정에서 발견. 격리 테스트 결과:

| 테스트 | 내용 | 결과 |
|--------|------|------|
| testA | 원본 compressed 그대로 패치 (no-op) | ✅ 열림 |
| testB | decompress → recompress (데이터 동일) | ✅ 열림 |
| testC | 전체 레코드 decode → re-encode → recompress (바이트 동일 확인) | ✅ 열림 |
| testD | L0 단락 115개 → 114개 (마지막 1개만 제거) | ❌ 손상 |
| testG | 단락 제거 + null padding으로 원본 크기 맞춤 | ❌ 손상 |
| testH | 전체 단락 유지 + EQEDIT 스크립트만 변경 (크기 달라짐) | ✅ 열림 |

- 압축 방식/크기 변경 → OK
- 레코드 재인코딩 → OK (바이트 동일 확인됨)
- 내용(스크립트 등) 수정 → OK
- **단락 삭제 → 무조건 손상**

원인 추정: 한컴 내부적으로 Section 스트림의 단락 구조를 DocInfo나 다른 메타데이터와 교차 검증하는 것으로 보임. 정확한 메커니즘은 미확인이나 DOCUMENT_PROPERTIES, DOC_DATA, PrvText 등이 후보.

**How to apply:**

1. **Seed Patch 모드에서 단락 추가/삭제 절대 금지.** 기존 단락의 내용(PT, PCS, EQEDIT 등)만 수정할 것.
2. **합성 fixture(f15 등) 생성 시:** 원본 파일 전체를 보존하고 필요한 레코드의 payload만 교체. 단락을 잘라내거나 새로 삽입하지 말 것.
3. **From Scratch 모드에서만** 단락 수를 자유롭게 결정 가능 (전체 파일을 새로 생성하므로).
4. 이 제약은 EQEDIT뿐 아니라 모든 종류의 단락(텍스트, 표, 수식 등)에 적용됨.
