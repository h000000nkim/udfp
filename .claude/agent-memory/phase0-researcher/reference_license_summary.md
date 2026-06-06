---
name: 조사 완료 라이브러리 라이선스 분류
description: UDFP에서 사용 가능 여부 기준 라이브러리 라이선스 분류 결과 (2026-04-29 기준)
type: reference
---

## 직접 의존성 가능 (MIT / BSD / Apache)

| 라이브러리 | 라이선스 | 용도 |
|-----------|---------|------|
| olefile 0.47 | BSD-2-Clause | HWP OLE2 컨테이너 파싱 |
| compoundfiles 0.3 | MIT | OLE2 대안 (엄격 검사) |
| pdfminer.six 20260108 | MIT | PDF 레이아웃 분석 |
| pypdf 6.6.2 | BSD-3-Clause | PDF 구조 조작 |
| python-docx (latest) | MIT | DOCX 읽기·쓰기 |
| lxml 6.1.0 | BSD-3-Clause (+ MIT for libxml2) | XML 파싱·직렬화 |

## 알고리즘 학습 전용 (AGPL / GPL — 코드 인용 금지)

| 라이브러리 | 라이선스 | 참조 대상 |
|-----------|---------|---------|
| pyhwp / hwp5 | AGPL-3.0 | HWP 레코드 구조, CharShape/ParaShape 알고리즘 |
| PyMuPDF (fitz) | AGPL-3.0 | TextPage 계층 구조, get_text("dict") |
| pymupdf4llm | AGPL-3.0 | MD 변환 파이프라인 heuristic |
| python-ooxml | AGPL-3.0 | OOXML 파싱 트리 |
