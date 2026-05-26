---
description: 지정 파일 또는 트랙에 대해 라운드트립 + R-규칙 + 시맨틱 diff 검증을 실행
argument-hint: [파일 경로 또는 트랙명 (hwp|pdf|hwpx|docx|md)]
---

# 라운드트립 + 검증 시스템 통합 검증

다음을 수행:

1. `$ARGUMENTS`가 파일 경로면 해당 파일에 대해, 트랙명이면 해당 트랙 전체에 대해 검증
2. 단계:
   - 원본 → IR
   - IR → 사이드카 분리 (`document.md` + `document.udfp.json`)
   - 사이드카 병합 → IR
   - IR → 원본 포맷 (Seed Patch 모드 우선, 가능하면)
   - 원본 ↔ 복원본 시맨틱 diff
   - 복원본의 R-규칙 검증
   - rhwp validate 실행 (HWP 트랙)
3. 보고:
   - 시맨틱 diff (블록 단위)
   - R-규칙 통과 여부
   - Verbatim 동등성
   - 외부 도구 검증 결과
   - 손실 보고서
4. **다음 중 하나라도 실패하면 라운드트립 실패로 보고:**
   - 시맨틱 diff != 0
   - R-규칙 위반
   - 비의도 손실

## 실행

```bash
# 파일 단위
udfp roundtrip "$ARGUMENTS"

# 트랙 단위
pytest tests/roundtrip/test_$ARGUMENTS.py -v
pytest tests/validation/test_$ARGUMENTS_rules.py -v
```

## 보고 형식

```
=== 라운드트립 + 검증 결과 ===
대상: <파일 또는 트랙>

[검증 4계층]
  시맨틱 diff:        <PASS / FAIL — N개 차이>
  R-규칙:             <PASS / FAIL — 어느 규칙 위반>
  Verbatim 동등성:    <PASS / FAIL>
  외부 도구 (rhwp):   <PASS / FAIL / 도구 없음>
  Visual diff:        <참고용, 결과>

[차이가 있는 경우]
  블록 b_0042: text 필드 변경
    원본: "..."
    복원: "..."

[규칙 위반이 있는 경우]
  R3 위반: PT 길이 50인데 PLS 엔트리 1개

[손실이 있는 경우]
  - 의도된: HWP 글자 모양 #12345 (사용자 편집 블록)
  - 비의도: ... (이게 있으면 실패)

[모드 정보]
  사용된 생성 모드: seed-patch / from-scratch
  originalContainer 사용: yes / no

[결론]
  ✅ 통과 / ❌ 실패
```

## 실패 시

1. 실패한 블록 위치 (블록 ID, 파일명)
2. 손실 종류 (시맨틱 / Verbatim / R-규칙)
3. 가능한 원인 (파서 / 제너레이터 / 사이드카 / 검증)
4. 다음 조사 명령 제안
