---
name: feedback-self-verify-loop
description: compare.html을 직접 캡처/파싱해서 자체 검증 루프를 돌려야 함. 사용자에게 스크린샷을 요청하지 말 것
metadata:
  type: feedback
---

렌더링 품질 검증은 사용자가 아니라 내가 직접 해야 함.
compare.html을 생성한 뒤 직접 스크린샷을 찍거나 HTML을 파싱해서 GT와 비교 검증하고, 문제를 발견하면 수정 → 재생성 → 재검증 루프를 반복해야 함.

**Why:** 사용자가 compare.html을 만들라고 한 이유는 내가 자체 검증하라는 것이지 사용자에게 보여주려는 게 아님. 사용자가 매번 캡처해서 떠먹여주는 상황이 반복됨.

**How to apply:** 렌더링 변경 후에는 반드시: (1) compare.html 재생성 (2) 직접 HTML 파싱 or 스크린샷으로 GT와 비교 (3) 불일치 발견 시 자체 수정 루프. [[feedback-no-self-validation]]
