한국어 | [English](./README.md)

# udfp — Universal Document Format Protocol

HWP/HWPX/DOCX/PDF/MD 등 이기종 문서를 하나의 Document Model로 파싱하고, 변환하고, 렌더링합니다.

**UDF**(Universal Document Format)는 포맷입니다 — 다양한 문서 형식을 공통 블록 트리로 정규화하는 통합 문서 모델. **UDFP**(Universal Document Format Protocol)는 프로토콜 레이어입니다 — AI 에이전트가 UDF를 통해 문서를 읽고, 편집하고, 생성할 수 있게 하는 MCP 서버.

`pip install udfp`를 설치하면 두 패키지가 함께 설치됩니다:

- **`udf`** — 핵심 라이브러리. 파서, 렌더러, Document Model, 검증, CLI.
- **`udfp`** — MCP 서버. [Model Context Protocol](https://modelcontextprotocol.io/)을 통해 Claude 등 LLM 에이전트에 `udf`를 노출.

```text
pip install udfp        →  import udf       (라이브러리)
pip install udfp[mcp]   →  udfp             (MCP 서버)
```

## 주요 기능

- **다중 포맷 파싱** — HWP (바이너리), HWPX (OOXML 유사 ZIP), DOCX, PDF, Markdown, HTML, XML
- **무손실 라운드트립** — HWP/HWPX/DOCX 동일 포맷 변환 시 verbatim 레이어로 내용 보존
- **크로스 포맷 변환** — 지원 포맷 간 변환 (예: HWP → DOCX, PDF → MD)
- **프로그래밍 방식 편집** — `UdfDocument` API로 블록/인라인 추가, 수정, 삭제
- **두 가지 생성 모드** — Seed Patch (원본 기반 수정) / From Scratch (전체 재생성)
- **구조 검증** — HWP용 R-규칙 (R1–R4 구현 완료); HWPX/DOCX/PDF 규칙은 예정
- **MCP 서버** — Claude/LLM 연동으로 문서 읽기, 편집, 생성

## 설치

```bash
pip install udfp
```

MCP 서버 포함:

```bash
pip install udfp[mcp]
```

개발용:

```bash
pip install udfp[dev]
```

## `udf` — 핵심 라이브러리

### 문서 파싱

```python
import udf

doc = udf.parse("report.hwp")
print(f"{len(doc.blocks)}개 블록 파싱됨")
```

### 포맷 변환

```python
import udf

udf.convert("input.hwp", "output.docx")
udf.convert("paper.pdf", "paper.md")
```

### 프로그래밍 방식 편집

```python
import udf
from udf.core.schema import ParagraphBlock, TextInline

doc = udf.parse("template.hwp")

doc.replace_text("PLACEHOLDER", "실제 값")

new_block = ParagraphBlock(
    type="paragraph",
    id="new-1",
    inlines=[TextInline(type="text", text="새 내용")],
)
doc.add_block(new_block)

udf.render(doc, "hwp", output_path="filled.hwp")
```

### CLI

```bash
udf convert input.hwp -o output.docx
udf inspect document.hwp
udf validate document.hwp
udf diff original.hwp modified.hwp
```

## `udfp` — MCP 서버

MCP 서버를 통해 LLM이 도구 호출로 문서를 읽고, 편집하고, 생성할 수 있습니다.

### 서버 실행

```bash
udfp                                          # stdio (기본)
udfp --transport streamable-http --port 8000  # HTTP
```

### 제공 도구

| 도구 | 설명 |
| ---- | ---- |
| `read(path)` | 문서를 블록 ID가 포함된 Simplified JSON으로 파싱 |
| `edit(path, edits)` | 특정 블록+인라인 위치의 텍스트/서식 수정 |
| `render(path, format)` | 문서를 다른 포맷으로 변환 |
| `create(blocks, format)` | 블록 배열로 새 문서 생성 |
| `insert_blocks(path, blocks)` | 기존 문서에 블록 추가 |
| `remove_blocks(path, block_ids)` | ID로 블록 삭제 |
| `set_page(path, ...)` | 페이지 레이아웃 변경 (용지, 여백, 다단) |
| `describe(topic)` | 스키마 문서 조회 (`describe('overview')`부터 시작) |

### Claude Desktop 설정

```json
{
  "mcpServers": {
    "udfp": {
      "command": "udfp"
    }
  }
}
```

## Document Model

모든 포맷은 공통 블록 트리로 정규화됩니다:

| 블록 타입 | 설명 |
| --------- | ---- |
| `ParagraphBlock` | 인라인 서식이 포함된 텍스트 |
| `HeadingBlock` | 제목 레벨 1–6 |
| `TableBlock` | 행, 셀, 병합 |
| `ImageBlock` | 삽입/참조 이미지 |
| `ListBlock` | 순서/비순서 목록 |
| `EquationBlock` | 수식 |
| `CodeBlock` | 소스 코드 블록 |
| `QuoteBlock` | 인용문 |
| `PageBreakBlock` | 페이지 나누기 |
| `HorizontalRuleBlock` | 수평선 |
| `DrawingBlock` | 벡터 도형 |
| `TextBoxBlock` | 플로팅 텍스트 상자 |
| `FootnoteBlock` / `EndnoteBlock` | 각주 / 미주 |
| `HeaderBlock` / `FooterBlock` | 머리글 / 바닥글 |
| `FieldBlock` | 양식 필드, 하이퍼링크, 책갈피 |
| `BookmarkBlock` | 이름 있는 책갈피 |
| `CommentBlock` | 검토 메모 |
| `ChartBlock` | 삽입 차트 |
| `TextArtBlock` | 장식 텍스트 (WordArt) |
| `UnknownBlock` | 인식되지 않는 포맷 고유 콘텐츠 |

## 생성 모드

### Seed Patch (원본이 있을 때 기본)

원본 바이너리/ZIP을 보존하고, 변경된 스트림만 교체합니다. 미수정 영역의 비트 단위 무결성을 보장합니다.

**적합한 용도:** 양식 채우기, 텍스트 교체, 구조 변경 없는 내용 수정.

### From Scratch (자동 폴백)

Document Model에서 출력 파일 전체를 재생성합니다. 블록 추가, 삭제, 구조 변경 시 필요합니다.

**자동 감지:** `verbatim_ref`가 없는 블록(프로그래밍으로 추가된 블록)이 하나라도 있으면 자동으로 From Scratch 모드로 전환됩니다.

## 지원 포맷

| 포맷 | 파싱 | 렌더링 | 동일 포맷 라운드트립 |
| ---- | ---- | ------ | -------------------- |
| HWP | 전체 | 전체 (Seed Patch + From Scratch) | 무손실 (verbatim) |
| HWPX | 전체 | 전체 (Seed Patch + From Scratch) | 무손실 (verbatim) |
| DOCX | 전체 | 전체 (Seed Patch + From Scratch) | 무손실 (verbatim) |
| PDF | 전체 | — | 파싱 전용 |
| Markdown | 전체 | 전체 | 텍스트 수준 |
| HTML | 전체 | 전체 | 텍스트 수준 |
| XML | 전체 | — | 파싱 전용 |

### 크로스 포맷 변환 매트릭스

| 입력 \ 출력 | HWP | HWPX | DOCX | MD | HTML |
| ----------- | --- | ---- | ---- | -- | ---- |
| **HWP** | 무손실 | 시맨틱 | 시맨틱 | 텍스트 수준 | 텍스트 수준 |
| **HWPX** | 시맨틱 | 무손실 | 시맨틱 | 텍스트 수준 | 텍스트 수준 |
| **DOCX** | 시맨틱 | 시맨틱 | 무손실 | 텍스트 수준 | 텍스트 수준 |
| **PDF** | — | — | — | 텍스트 수준 | 텍스트 수준 |
| **MD** | From Scratch | — | — | — | 전체 |
| **HTML** | From Scratch | — | — | 전체 | — |

- **무손실**: Verbatim 레이어가 모든 바이너리 내용을 보존 (Seed Patch 모드)
- **시맨틱**: 블록 구조와 텍스트는 보존; 포맷 고유 스타일은 다를 수 있음 (From Scratch 모드)
- **텍스트 수준**: 텍스트 내용만 보존; 서식, 페이지 레이아웃, 이미지는 손실
- **From Scratch**: Document Model에서 새 바이너리 생성; 원본이 있으면 더 나은 결과

## 알려진 제한사항

**From Scratch 모드** (크로스 포맷 변환 및 구조 편집 시 사용):

- `DrawingBlock`, `ChartBlock`, `TextArtBlock`은 원본 파일 없이 재생성 불가 — `FORMAT_LIMIT` 손실로 보고
- 복잡한 테이블 구조 (셀 병합, 중첩 테이블)는 HWPX/DOCX → HWP 변환 시 완전히 보존되지 않을 수 있음

**검증 규칙**:

- HWP: R1–R4 구조 규칙 + I1–I3 무결성 검사 — 자동 수정기와 함께 완전 구현
- HWPX, DOCX, PDF: 포맷별 규칙은 계획 중이며 미구현; 시맨틱 diff로 검증

**텍스트 수준 포맷** (MD, HTML):

- 서식 (폰트, 색상, 여백), 이미지, 페이지 레이아웃은 보존되지 않음
- 텍스트 추출과 내용 편집에 유용, 시각적 충실도 용도에는 부적합

## 아키텍처

```text
입력 파일 ──▶ 파서 ──▶ UdfDocument ──▶ 렌더러 ──▶ 출력 파일
                            │
                            ▼
                   Document Model (블록/인라인)
                            +
                   Verbatim Layer (바이너리 보존)
                            +
                   Loss Report (손실 보고서)
```

## 개발

```bash
pytest                        # 전체 테스트
pytest tests/roundtrip/       # 라운드트립 테스트
pytest tests/validation/      # R-규칙 검증
ruff check . && ruff format . # 린트 + 포맷
mypy udf/                     # 타입 체크
```

## 라이선스

MIT
