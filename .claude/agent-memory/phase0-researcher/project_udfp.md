---
name: UDFP Phase 0-B 라이브러리 리서처 컨텍스트
description: Phase 0-B 에이전트의 역할과 library-mapping.md 최초 갱신 이력
type: project
---

2026-04-29 첫 조사 완료. `docs/library-mapping.md`를 트랙별 상세 알고리즘 노트 포함 형태로 전면 재작성.

조사 완료 라이브러리:
- pyhwp/hwp5 (AGPL, 알고리즘 학습) — 레코드 헤더 비트 구조, HWPTAG 목록, CharShape/ParaShape 필드 표, ctrl_id 목록 정리
- olefile (BSD-2, 직접 사용) — OLE2 컨테이너 파싱
- compoundfiles (MIT, 직접 사용) — OLE2 엄격 검사 대안
- PyMuPDF/pymupdf4llm (AGPL, 알고리즘 학습) — get_text("dict") 계층 구조
- pdfminer.six (MIT, 직접 사용) — LAParams 3단계 레이아웃 분석, LTPage 트리
- pypdf (BSD-3, 직접 사용) — 메타데이터·페이지 조작
- python-ooxml (AGPL, 알고리즘 학습) — OOXML 파싱 트리
- python-docx (MIT, 직접 사용) — Document 객체 모델, ZIP+lxml 구조
- lxml (BSD-3, 직접 사용) — XML 파싱·직렬화

**Why:** Phase 0-B 목표는 의존성 최소화 전략 수립을 위한 라이선스 분류와 알고리즘 파악.
**How to apply:** 새 라이브러리 추가 전 library-mapping.md 확인 → 이미 조사된 항목이면 재조사 불필요.
