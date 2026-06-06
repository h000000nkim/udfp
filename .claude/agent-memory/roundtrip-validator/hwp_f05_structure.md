---
name: f05_table_cell_text.hwp 블록 구조
description: 최상위에 빈 ParagraphBlock(id=b_0000)과 TableBlock만 존재 — 텍스트 편집 라운드트립 SKIP 사유
type: project
---

f05_table_cell_text.hwp의 최상위 블록 구성:
- ParagraphBlock (id=b_0000): 텍스트 없음 (빈 단락)
- TableBlock (2행 × 3열): 셀 내부에 "이름", "나이", "직업", "홍길동", "30세", "개발자" 포함

**Why:** 최상위에 텍스트가 있는 ParagraphBlock이 없어서 편집 라운드트립 대상 블록을 찾을 수 없음. 셀 내부 텍스트는 TableBlock → TableRow → TableCell → ParagraphBlock 경로로 접근해야 함.

**How to apply:** 이 파일에 대한 편집 라운드트립 테스트를 작성할 때는 TableBlock 내부 셀의 ParagraphBlock을 대상으로 해야 함. 최상위 블록만 탐색하는 로직에서는 스킵 처리가 정상.
