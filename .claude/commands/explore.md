---
description: realworld fixture 파일을 파싱, 변환, 라운드트립 검증하고 스크린샷까지 캡처하여 결과를 직접 확인
argument-hint: "[파일명 일부 또는 인덱스 번호] (생략 시 목록 표시 후 선택/랜덤)"
---

# Realworld Fixture 탐색 및 검증

realworld 파일 하나를 선택하여 parse → convert → HTML 렌더링 → 스크린샷 캡처 → roundtrip 전체 파이프라인을 실행한다.

## 대상 파일 선택

### 인자가 있을 때

`$ARGUMENTS`가 숫자면 인덱스, 문자열이면 파일명 검색으로 대상 파일을 결정한다.

### 인자가 없을 때 (비복원 추출)

1. `output/realworld/explored.log`를 읽어서 이미 처리한 파일 목록을 확인한다.
2. 전체 realworld 파일 목록에서 처리 완료된 파일을 제외한다.
3. 사용자에게 남은 파일 목록을 보여주고 선택지를 제시한다:
   - 번호를 골라서 지정
   - "랜덤"을 선택하면 남은 파일 중 무작위 1개 선택
4. 전체 진행률을 표시한다: `[완료 N / 전체 M] (N/M × 100%)`
5. 모든 파일을 다 처리했으면 "전체 완료" 보고 후 종료.

### explored.log 형식

처리 완료 시 `output/realworld/explored.log`에 한 줄씩 추가:
```
<ISO timestamp>\t<파일 상대경로>\t<결과: OK|PARTIAL|FAIL>
```

예시:
```
2026-05-26T14:30:00	filled/감염병확산지수미분_하윤중.hwp	OK
2026-05-26T14:35:00	filled/신문 기사 쓰기.hwp	PARTIAL
```

- OK: 전 단계(parse + convert + screenshot + roundtrip) 성공
- PARTIAL: 일부 단계 실패 (어떤 단계가 실패했는지 결과 요약에 명시)
- FAIL: parse 자체 실패

파일 목록은 다음으로 확인:
```bash
python sandbox/explore_realworld.py list
```

## 실행 단계

### 1단계: Parse — 구조 분석

```python
import udf
doc = udf.parse("<파일경로>")
```

보고할 내용:
- 포맷, 블록 수
- 블록별 타입과 텍스트 미리보기 (최대 50블록)
- 특이사항 (수식, 이미지, 텍스트박스 등 비표준 블록 존재 여부)

### 2단계: Convert — 포맷 변환

원본 포맷에 따라 가능한 변환을 모두 수행하고 `output/realworld/`에 저장:

| 원본 | 변환 대상 |
|------|-----------|
| HWP  | MD, DOCX  |
| HWPX | MD, DOCX  |
| DOCX | MD        |
| PDF  | MD        |
| MD   | HWP, DOCX |

```python
udf.convert("<입력>", "output/realworld/<파일명>.<대상포맷>")
```

각 변환마다 보고:
- 출력 파일 경로와 크기
- MD 변환의 경우 처음 2000자 미리보기
- 변환 중 발생한 오류가 있으면 보고 (실패해도 다음 변환 계속)

### 3단계: HTML 렌더링 + 스크린샷 캡처

원본을 HTML로 렌더링하고 Playwright로 스크린샷을 캡처한다.

```python
from playwright.sync_api import sync_playwright
from pathlib import Path
import udf

doc = udf.parse("<파일경로>")
html = udf.render(doc, "html")

out_dir = Path("output/realworld")
html_path = out_dir / "<파일명>.html"
html_path.write_text(html)

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1200, "height": 800})
    page.goto(f"file://{html_path.resolve()}")
    page.wait_for_timeout(1500)
    page.screenshot(path=str(out_dir / "<파일명>_screenshot.png"), full_page=True)
    browser.close()
```

캡처 후:
- **Read 도구로 스크린샷 PNG를 읽어서 이 채팅에 바로 표시한다**
- 사용자가 시각적 품질을 직접 확인할 수 있도록 한다
- 시각적 판단은 하지 않는다 — 사용자에게 맡김

### 4단계: Roundtrip — 라운드트립 + diff

원본 → MD → 다시 파싱 후 원본과 시맨틱 diff 비교:

```python
doc_orig = udf.parse("<원본>")
md_text = udf.render(doc_orig, "md")
md_path = "output/realworld/<파일명>_roundtrip.md"
Path(md_path).write_text(md_text)
doc_rt = udf.parse(md_path)
lr = udf.diff(doc_orig, doc_rt)
```

보고할 내용:
- 원본 블록 수 vs 라운드트립 블록 수
- `is_roundtrip_safe` 여부
- 손실 항목 전체 목록 (lossy_blocks)
- 누락 기능 (dropped_features)
- 손실 유형별 분류: 포매팅 손실 / 텍스트 변경 / 블록 소실

### 5단계: 로그 기록 + 결과 요약

explored.log에 결과를 기록한 뒤 요약을 출력한다.

```
=== Explore 결과: <파일명> ===
[진행률: 완료 N / 전체 M (X%)]

[파일 정보]
  포맷: <hwp/hwpx/docx/pdf>
  크기: <KB>
  블록 수: <N>
  특수 블록: <수식 N개, 이미지 N개, 텍스트박스 N개, ...>

[변환 결과]
  → MD:   output/realworld/<파일명>.md (N KB) ✓/✗
  → DOCX: output/realworld/<파일명>.docx (N KB) ✓/✗
  → HTML: output/realworld/<파일명>.html (N KB) ✓

[스크린샷]
  output/realworld/<파일명>_screenshot.png (위에 표시됨)

[라운드트립]
  원본 블록: N → MD 거친 후: M 블록
  라운드트립 안전: ✓/✗
  손실 요약:
    - 포매팅 손실: N건 (폰트, 색상, 크기 등)
    - 텍스트 변경: N건
    - 블록 소실: N건

[출력 파일 전체 목록]
  - output/realworld/<파일명>.md
  - output/realworld/<파일명>.docx
  - output/realworld/<파일명>.html
  - output/realworld/<파일명>_screenshot.png
  - output/realworld/<파일명>_roundtrip.md
```

## 주의사항

- `output/realworld/`에 기존 파일이 있으면 덮어쓴다
- 변환 실패는 오류를 보고하고 다음 단계로 넘어간다
- **시각적 품질은 판단하지 않는다** — 스크린샷을 보여주고 사용자가 직접 확인
- 라운드트립에서 포매팅 손실(폰트/색상)은 MD 특성상 불가피 — 텍스트/구조 손실만 문제로 취급
- Playwright 스크린샷은 HTML 렌더링 결과이므로, 원본 HWP의 한글 뷰어 렌더링과는 차이가 있을 수 있음
- explored.log는 비복원 추출 기록이므로 삭제하면 처음부터 다시 시작
