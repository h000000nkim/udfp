---
description: 지정 외부 라이브러리의 알고리즘과 자료구조를 조사하여 docs/library-mapping.md를 갱신
argument-hint: [라이브러리명 또는 GitHub URL]
---

# 외부 라이브러리 알고리즘 조사

`library-research` 스킬을 따라 다음을 수행:

1. `$ARGUMENTS`가 라이브러리명이면 GitHub URL 검색, URL이면 직접 사용
2. README + LICENSE + 주요 소스 파일 확인
3. 핵심 자료구조와 함수 시그니처 추출
4. 알고리즘 핵심 원리를 자연어로 정리
5. `docs/library-mapping.md`에 새 항목 추가 또는 갱신
6. 라이선스에 따라 활용 방안 결정

## 보고 항목

- 라이브러리명, 버전, 라이선스, URL
- UDFP에서 활용할 수 있는 알고리즘 요약
- 활용 방안 (의존성 / 알고리즘 참조 / 사용 안 함)
- AGPL/GPL인 경우 코드 직접 인용 금지 명시
- 다음 조사 후보

## 절대 금지

- 코드 본문 그대로 복사
- README만 보고 표 갱신
- 라이선스 미확인 상태로 등록
