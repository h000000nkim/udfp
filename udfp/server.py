"""FastMCP 서버 — read/edit/render/create MCP tool."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

import udf
from udf.pipeline.document import UdfDocument, _get_inlines as _core_get_inlines
from udf.schema.blocks import (
    BlockBase,
    HeadingBlock,
)
from udf.schema.formats import BlockFormat
from udf.schema.inlines import TextInline
from udf.schema.types import Color

from udfp.create import blocks_from_json, document_from_json
from udfp.serialize import serialize_simplified


def create_server() -> FastMCP:
    mcp = FastMCP(
        "udfp",
        instructions=(
            "UDF (Universal Document Format) MCP server for reading, editing, "
            "and generating documents across formats (HWP, HWPX, DOCX, PDF, MD, HTML).\n\n"
            "Tools:\n"
            "- read(path): Parse a document into simplified JSON with block IDs and inline text\n"
            "- edit(path, edits): Modify text/formatting at specific block+inline positions\n"
            "- render(path, format): Convert a document to another format\n"
            "- create(blocks, format): Build a new document from a block array\n"
            "- insert_blocks(path, blocks): Add blocks to an existing document\n"
            "- remove_blocks(path, block_ids): Delete blocks by ID\n"
            "- set_page(path, ...): Change page layout (paper size, margins, columns)\n"
            "- export_md(path): Export document as editable Markdown with block IDs\n"
            "- import_md(path, edited_md): Apply edited Markdown back, preserving original formatting\n"
            "- describe(topic): Get schema docs — call describe('overview') first\n\n"
            "Workflow: read → understand block IDs → edit/insert/remove → render.\n"
            "MD editing workflow: export_md → edit the returned MD → import_md → done.\n"
            "Format keys use short aliases (size, bold, align, bg, sp_before, indent_l, etc.).\n"
            "Call describe('fmt') for the full alias mapping table."
        ),
    )

    @mcp.tool()
    async def read(path: str) -> str:
        """문서를 읽어서 Simplified JSON으로 반환합니다.

        지원 포맷: HWP, HWPX, DOCX, PDF, MD, HTML, XML
        반환: 블록 ID, 인라인 텍스트(idx 포함), 서식, 표 grid 좌표를 포함한 compact JSON
        """
        try:
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            doc = udf.parse(path)
            return serialize_simplified(doc)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}\nTip: Use describe('overview') for guidance."

    @mcp.tool()
    async def edit(
        path: str,
        edits: list[dict[str, Any]],
        output_path: str | None = None,
    ) -> str:
        """문서의 지정 위치에 텍스트/서식을 변경하고 저장합니다.

        각 edit는 block_id로 대상 블록을 지정합니다.

        edit 형식:
        - 텍스트 변경: {"block_id": "b_XXXX", "inline_idx": 0, "text": "새 텍스트"}
        - 텍스트+서식: {"block_id": "b_XXXX", "inline_idx": 0, "text": "...", "fmt": {"bold": true, "size": 14.0}}
        - 블록 서식만: {"block_id": "b_XXXX", "block_fmt": {"align": "center"}}
        - 빈 블록에 삽입: {"block_id": "b_XXXX", "inline_idx": null, "text": "새 내용"}
        """
        try:
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            doc = udf.parse(path)
            _apply_edits(doc, edits)
            out = output_path or path
            _save_doc(doc, out)
            return serialize_simplified(doc)
        except ValueError as e:
            return f"Error: {e}\nTip: Use describe('edit') for edit patterns."
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}\nTip: Use describe('edit') for edit patterns."

    @mcp.tool()
    async def render(
        path: str,
        format: str,
        output_path: str | None = None,
    ) -> str:
        """문서를 원하는 포맷으로 렌더링합니다.

        지원 출력 포맷: hwp, hwpx, docx, md, html
        output_path 미지정 시 입력 파일의 확장자를 변경하여 저장합니다.
        """
        try:
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            fmt = format.lower().strip().lstrip(".")
            doc = udf.parse(path)
            if output_path is None:
                output_path = str(Path(path).with_suffix(f".{fmt}"))
            result = udf.render(doc, fmt, output_path=output_path)
            if result is not None:
                Path(output_path).write_text(result, encoding="utf-8")
            return f"Rendered: {output_path}"
        except ValueError as e:
            return f"Error: {e}\nTip: Supported formats: hwp, hwpx, docx, md, html"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}\nTip: Use describe('workflow') for guidance."

    @mcp.tool()
    async def create(
        blocks: list[dict[str, Any]],
        format: str = "hwp",
        output_path: str | None = None,
        page: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """새 문서를 처음부터 생성합니다.

        blocks: 블록 배열. 각 블록은 type 필드로 종류를 지정합니다.
        지원 블록 타입:
        - heading: {"type": "heading", "level": 1, "text": "제목", "fmt": {"bold": true, "size": 18}}
        - paragraph: {"type": "paragraph", "text": "본문", "fmt": {"size": 12, "align": "center"}}
          또는 여러 인라인: {"type": "paragraph", "inlines": [{"text": "볼드", "fmt": {"bold": true}}, {"text": " 일반"}]}
        - table: {"type": "table", "rows": [[셀, ...], ...], "col_widths": [mm, ...], "header_rows": 1}
          셀은 문자열("텍스트") 또는 객체({"text": "...", "fmt": {...}, "bg": "#EEE", "colspan": 2})
        - image: {"type": "image", "src": "경로", "width": 200, "height": 150}
        - list: {"type": "list", "ordered": true, "items": ["항목1", "항목2"]}
        - code: {"type": "code", "code": "print('hello')", "language": "python"}
        - quote: {"type": "quote", "text": "인용문"}
        - equation: {"type": "equation", "latex": "E=mc^2"}
        - page_break: {"type": "page_break"}
        - horizontal_rule: {"type": "horizontal_rule"}

        format: 출력 포맷 (hwp, hwpx, docx, md, html)
        page: 페이지 설정 {"paper": "A4", "orientation": "portrait",
              "margin_top": 20, "margin_bottom": 20, "margin_left": 30, "margin_right": 30,
              "columns": 1}  (여백 단위: mm)
        metadata: {"title": "...", "author": "...", "subject": "...", "keywords": [...]}
        output_path: 저장 경로 (미지정 시 /tmp/udf_created.{format})
        """
        try:
            fmt = format.lower().strip().lstrip(".")
            doc = document_from_json(blocks, format=fmt, page=page, metadata=metadata)
            if output_path is None:
                output_path = f"/tmp/udf_created.{fmt}"
            _save_doc(doc, output_path)
            return f"Created: {output_path}\n\n" + serialize_simplified(doc)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}\nTip: Use describe('create') for block schema."

    @mcp.tool()
    async def insert_blocks(
        path: str,
        blocks: list[dict[str, Any]],
        after: str | None = None,
        parent_id: str | None = None,
        output_path: str | None = None,
    ) -> str:
        """기존 문서에 블록을 추가합니다.

        path: 원본 문서 경로
        blocks: 추가할 블록 배열 (create와 동일 스키마)
        after: 이 block_id 뒤에 삽입 (미지정 시 끝에 추가)
        parent_id: 컨테이너 블록 내부에 삽입할 경우 해당 컨테이너 ID
        output_path: 저장 경로 (미지정 시 원본 파일 덮어쓰기)
        """
        try:
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            doc = udf.parse(path)
            new_blocks = blocks_from_json(blocks)
            for block in new_blocks:
                doc.add_block(block, parent_id=parent_id, after=after)
                if after is None and parent_id is None:
                    pass
                elif after is not None:
                    after = block.id
            _force_from_scratch(doc)
            out = output_path or path
            _save_doc(doc, out)
            return f"Inserted {len(new_blocks)} block(s): {out}\n\n" + serialize_simplified(doc)
        except ValueError as e:
            return f"Error: {e}\nTip: Use describe('create') for block schema."
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}\nTip: Use describe('create') for block schema."

    @mcp.tool()
    async def remove_blocks(
        path: str,
        block_ids: list[str],
        output_path: str | None = None,
    ) -> str:
        """문서에서 지정된 블록을 삭제합니다.

        path: 문서 경로
        block_ids: 삭제할 블록 ID 배열
        output_path: 저장 경로 (미지정 시 원본 파일 덮어쓰기)
        """
        try:
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            doc = udf.parse(path)
            removed = 0
            for bid in block_ids:
                if doc.remove_block(bid) is not None:
                    removed += 1
            _force_from_scratch(doc)
            out = output_path or path
            _save_doc(doc, out)
            return f"Removed {removed} block(s): {out}\n\n" + serialize_simplified(doc)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}\nTip: Use read(path) first to get block IDs."

    @mcp.tool()
    async def set_page(
        path: str,
        paper: str | None = None,
        orientation: str | None = None,
        margin_top: float | None = None,
        margin_bottom: float | None = None,
        margin_left: float | None = None,
        margin_right: float | None = None,
        columns: int | None = None,
        gutter: float | None = None,
        output_path: str | None = None,
    ) -> str:
        """문서의 페이지 레이아웃을 변경합니다.

        path: 문서 경로
        paper: 용지 크기 (A4, A3, A5, B5, Letter, Legal)
        orientation: portrait 또는 landscape
        margin_top/bottom/left/right: 여백 (mm)
        columns: 다단 수 (1=단단, 2=2단, ...)
        gutter: 다단 간격 (mm)
        output_path: 저장 경로 (미지정 시 원본 파일 덮어쓰기)
        """
        from udfp.create import _build_page_settings
        try:
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            doc = udf.parse(path)
            page_spec: dict[str, Any] = {}
            if paper:
                page_spec["paper"] = paper
            if orientation:
                page_spec["orientation"] = orientation
            if margin_top is not None:
                page_spec["margin_top"] = margin_top
            if margin_bottom is not None:
                page_spec["margin_bottom"] = margin_bottom
            if margin_left is not None:
                page_spec["margin_left"] = margin_left
            if margin_right is not None:
                page_spec["margin_right"] = margin_right
            if columns is not None:
                page_spec["columns"] = columns
            if gutter is not None:
                page_spec["gutter"] = gutter
            if page_spec:
                _build_page_settings(page_spec, doc.metadata)
            out = output_path or path
            _save_doc(doc, out)
            return f"Page layout updated: {out}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}\nTip: Paper sizes: A4, A3, A5, B5, Letter, Legal"

    @mcp.tool()
    async def export_md(path: str) -> str:
        """문서를 편집 가능한 Markdown으로 변환합니다.

        블록 ID가 HTML 주석(<!-- id: b_XXXX -->)으로 삽입되어
        import_md에서 원본 서식과 매칭할 수 있습니다.

        지원 입력: HWP, HWPX, DOCX, PDF, MD, HTML
        반환: 블록 ID가 포함된 Markdown 텍스트

        사용법:
        1. export_md(path) → Markdown 텍스트 수령
        2. Markdown 텍스트를 편집 (블록 ID 주석은 유지할 것)
        3. import_md(path, edited_md) → 원본 서식 보존 + 편집 반영된 문서 저장
        """
        try:
            if not os.path.exists(path):
                return f"Error: File not found: {path}"
            doc = udf.parse(path)
            from udf.renderers.md import render_md
            md = render_md(doc, embed_ids=True)
            header = _build_source_header(path, doc)
            return header + md
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"

    @mcp.tool()
    async def import_md(
        path: str,
        edited_md: str,
        output_path: str | None = None,
    ) -> str:
        """편집된 Markdown을 원본 문서에 반영하여 저장합니다.

        export_md로 내보낸 Markdown을 편집한 후, 이 도구로 적용하면
        원본 문서의 서식·레이아웃·양식을 보존하면서 텍스트 변경만 반영됩니다.

        path: 원본 문서 경로 (서식 소스)
        edited_md: 편집된 Markdown 텍스트 (export_md 결과를 수정한 것)
        output_path: 저장 경로 (미지정 시 원본 파일 덮어쓰기)

        반환: 변경 요약 (변경 건수, 보존된 블록 수)
        """
        try:
            if not os.path.exists(path):
                return f"Error: File not found: {path}"

            from udf.core.ids import max_block_index
            from udf.merge_diff import merge_diff as _merge_diff
            from udf.parsers.md.parse import parse_md

            original = udf.parse(path)

            warning = ""
            source_meta = _parse_source_header(edited_md)
            if source_meta:
                expected_fp = source_meta.get("fingerprint", "")
                actual_fp = _fingerprint(original)
                if expected_fp and expected_fp != actual_fp:
                    warning = (
                        f"Warning: fingerprint mismatch — "
                        f"MD was exported from a different version of this document "
                        f"(expected {expected_fp}, got {actual_fp}). "
                        f"Proceeding, but some edits may not align correctly.\n"
                    )

            clean_md = _strip_source_header(edited_md)
            start = max_block_index(original.blocks) + 1
            edited_doc = parse_md(clean_md, start_id=start)
            result = _merge_diff(original, edited_doc)

            out = output_path or path
            _save_doc(result.document, out)

            lines = []
            if warning:
                lines.append(warning)
            lines.append(f"Saved: {out}")
            lines.append(f"Changes: {len(result.changes)}")
            for c in result.changes:
                lines.append(f"  - [{c.change_type}] {c.description}")
            if result.preserved_ids:
                lines.append(f"Preserved (MD-unrepresentable): {len(result.preserved_ids)} blocks")
            return "\n".join(lines)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}\nTip: Use export_md(path) first to get editable Markdown."

    @mcp.tool()
    async def describe(topic: str = "overview") -> str:
        """Get documentation about UDF document structure and tool usage.

        Topics: overview, blocks, edit, create, fmt, workflow, api, metadata, loss
        Start with describe('overview') to understand the document model.
        """
        topic = topic.lower().strip()
        info = _DESCRIBE_TOPICS.get(topic)
        if info is None:
            available = ", ".join(sorted(_DESCRIBE_TOPICS.keys()))
            return f"Unknown topic '{topic}'. Available: {available}"
        return info

    return mcp


# ------------------------------------------------------------------
# describe topic content
# ------------------------------------------------------------------

_DESCRIBE_TOPICS: dict[str, str] = {
    "overview": """\
# UDF Document Model

A document is a tree of **blocks** (paragraphs, headings, tables, images, etc.).
Each block has a unique `id` (e.g. "b_0001") and may contain **inlines** (text runs
with formatting). Tables contain cells, each cell contains its own blocks.

```
UdfDocument
├── metadata (title, author, page settings)
└── blocks[]
    ├── HeadingBlock  (level, text, inlines[])
    ├── ParagraphBlock (inlines[])
    ├── TableBlock (rows × cols, cells with nested blocks)
    ├── ImageBlock (src, width, height)
    ├── CodeBlock (code, language)
    ├── ListBlock (ordered, items with nested blocks)
    └── ... (22 block types total)
```

## Quick Start
1. `read(path)` → get block IDs and text content
2. `edit(path, edits)` → modify text/formatting by block_id + inline_idx
3. `render(path, format)` → export to hwp/hwpx/docx/md/html
4. `create(blocks, format)` → build new document from scratch

## Topics
- `describe('blocks')` — all 22 block types with JSON examples
- `describe('edit')` — edit tool patterns and examples
- `describe('create')` — create tool block schema
- `describe('fmt')` — format key alias table (inline, block, cell)
- `describe('workflow')` — common task recipes
- `describe('api')` — UdfDocument properties and methods
- `describe('metadata')` — page layout and document properties
- `describe('loss')` — loss report structure and meaning""",

    "blocks": """\
# Block Types (22 total)

## Content Blocks
| Type | Key Fields | Has Inlines |
|------|-----------|-------------|
| ParagraphBlock | inlines[] | yes |
| HeadingBlock | level (1-6), text, inlines[] | yes |
| CodeBlock | code, language | no |
| QuoteBlock | inlines[] | yes |
| EquationBlock | latex | no |
| ListBlock | ordered, items[{inlines, children}] | yes (per item) |

## Structure Blocks
| Type | Key Fields |
|------|-----------|
| TableBlock | rows, cols, col_widths, cells[{row,col,blocks}] |
| ImageBlock | src, width, height, alt |
| DrawingBlock | shapes[], position |
| TextBoxBlock | blocks[], position |
| ChartBlock | data, chart_type |

## Reference Blocks
| Type | Key Fields |
|------|-----------|
| FootnoteBlock | marker, blocks[] |
| EndnoteBlock | marker, blocks[] |
| CommentBlock | author, blocks[] |
| BookmarkBlock | name |
| FieldBlock | field_type, code |

## Layout Blocks
| Type | Key Fields |
|------|-----------|
| PageBreakBlock | — |
| HorizontalRuleBlock | — |
| HeaderBlock | blocks[] |
| FooterBlock | blocks[] |

## Special
| Type | Key Fields |
|------|-----------|
| TextArtBlock | text, shape |
| UnknownBlock | raw data preservation |

## JSON Example (from read output)
```json
{"id": "b_0001", "type": "heading", "level": 1, "text": "Title",
 "inlines": [{"idx": 0, "text": "Title", "bold": true, "size": 18.0}]}
{"id": "b_0002", "type": "paragraph",
 "inlines": [{"idx": 0, "text": "Hello "}, {"idx": 1, "text": "world", "bold": true}]}
{"id": "b_0003", "type": "table", "rows": 2, "cols": 3,
 "cells": [{"r": 0, "c": 0, "text": "Header 1"}, ...]}
```""",

    "edit": """\
# Edit Tool Patterns

The `edit` tool takes a list of edit operations. Each targets a block by `block_id`.

## Pattern 1: Change text
```json
{"block_id": "b_0002", "inline_idx": 0, "text": "New text"}
```

## Pattern 2: Change text + formatting
```json
{"block_id": "b_0002", "inline_idx": 0, "text": "Bold red",
 "fmt": {"bold": true, "color": "#FF0000", "size": 14.0}}
```

## Pattern 3: Change block-level formatting only
```json
{"block_id": "b_0002", "block_fmt": {"align": "center", "sp_before": 10.0}}
```

## Pattern 4: Add text to empty block
```json
{"block_id": "b_0005", "inline_idx": null, "text": "Inserted text"}
```

## Pattern 5: Multiple edits at once
```json
[
  {"block_id": "b_0001", "inline_idx": 0, "text": "New Title"},
  {"block_id": "b_0002", "block_fmt": {"align": "center"}},
  {"block_id": "b_0003", "inline_idx": 1, "fmt": {"bold": true}}
]
```

## Tips
- `inline_idx` is 0-based, visible in read output as `"idx": N`
- Use `block_fmt` for paragraph-level styles (alignment, spacing, indent)
- Use `fmt` for character-level styles (bold, font, color)
- Format keys accept both short and full names (see describe('fmt'))
- `output_path` saves to a different file; omit to overwrite original""",

    "create": """\
# Create Tool — Block Schema

## Heading
```json
{"type": "heading", "level": 1, "text": "Title", "fmt": {"bold": true, "size": 18}}
```

## Paragraph (simple)
```json
{"type": "paragraph", "text": "Plain text", "fmt": {"size": 12}}
```

## Paragraph (mixed formatting)
```json
{"type": "paragraph", "inlines": [
  {"text": "Bold part", "fmt": {"bold": true}},
  {"text": " normal part"},
  {"text": " red part", "fmt": {"color": "#FF0000"}}
]}
```

## Table
```json
{"type": "table", "rows": [
  ["Header 1", "Header 2", "Header 3"],
  ["Cell A", {"text": "Bold cell", "fmt": {"bold": true}}, "Cell C"],
  [{"text": "Merged", "colspan": 2}, "Cell C"]
], "col_widths": [60, 60, 60], "header_rows": 1}
```
- Cells: plain string or object with text/fmt/bg/colspan/rowspan
- `col_widths` in mm (optional, auto-calculated if omitted)

## Image
```json
{"type": "image", "src": "/path/to/image.png", "width": 200, "height": 150}
```

## List
```json
{"type": "list", "ordered": true, "items": ["First", "Second", "Third"]}
```

## Code
```json
{"type": "code", "code": "print('hello')", "language": "python"}
```

## Others
```json
{"type": "quote", "text": "Quoted text"}
{"type": "equation", "latex": "E = mc^2"}
{"type": "page_break"}
{"type": "horizontal_rule"}
```

## Page Settings
```json
{"page": {"paper": "A4", "orientation": "portrait",
  "margin_top": 20, "margin_bottom": 20,
  "margin_left": 30, "margin_right": 30}}
```

## Output Formats
hwp, hwpx, docx, md, html""",

    "fmt": """\
# Format Key Aliases

Short aliases are accepted in both `fmt` (inline) and `block_fmt` (block) fields.

## Inline Format (character-level)
| Alias | Full Name | Type | Example |
|-------|-----------|------|---------|
| bold | bold | bool | true |
| italic | italic | bool | true |
| underline | underline | bool | true |
| strike | strikethrough | bool | true |
| size | font_size | float | 14.0 |
| font | font_name | str | "Arial" |
| color | color | str | "#FF0000" |
| bg | background_color | str | "#FFFF00" |
| super | superscript | bool | true |
| sub | subscript | bool | true |
| caps | small_caps | bool | true |
| all_caps | all_caps | bool | true |
| hidden | hidden | bool | true |
| letter_spacing | letter_spacing | float | 2.0 |

## Block Format (paragraph-level)
| Alias | Full Name | Type | Example |
|-------|-----------|------|---------|
| align | alignment | str | "center" / "left" / "right" / "justify" |
| size | font_size | float | 12.0 |
| font | font_name | str | "Arial" |
| bold | bold | bool | true |
| line_h | line_spacing | float | 160.0 |
| sp_before | space_before | float | 10.0 |
| sp_after | space_after | float | 10.0 |
| indent_l | indent_left | float | 20.0 |
| indent_r | indent_right | float | 20.0 |
| indent_1st | indent_first | float | 10.0 |
| bg | background_color | str | "#F0F0F0" |
| dir | text_direction | str | "ltr" / "rtl" |

## Cell Format (table cell)
| Field | Type | Example |
|-------|------|---------|
| bg | str | "#EEEEEE" |
| border_top/bottom/left/right | object | — |
| padding | float | 2.0 |
| vertical_align | str | "top" / "middle" / "bottom" |""",

    "workflow": """\
# Common Workflows

## 1. Read and Edit Text
```
read("/path/doc.hwp")          → get block IDs
edit("/path/doc.hwp", [
  {"block_id": "b_0003", "inline_idx": 0, "text": "Updated text"}
])
```

## 2. Change Document Formatting
```
edit("/path/doc.hwp", [
  {"block_id": "b_0001", "block_fmt": {"align": "center", "size": 20}},
  {"block_id": "b_0002", "block_fmt": {"sp_before": 12, "indent_l": 20}}
])
```

## 3. Convert Between Formats
```
render("/path/doc.hwp", "docx")               → doc.docx
render("/path/doc.hwp", "md")                  → doc.md
render("/path/doc.pdf", "md", "/out/notes.md") → custom path
```

## 4. Create a New Document
```
create([
  {"type": "heading", "level": 1, "text": "Report Title"},
  {"type": "paragraph", "text": "Introduction paragraph."},
  {"type": "table", "rows": [["A","B"],["1","2"]]},
  {"type": "paragraph", "text": "Conclusion."}
], format="docx", output_path="/tmp/report.docx")
```

## 5. Add Content to Existing Document
```
read("/path/doc.hwp")
insert_blocks("/path/doc.hwp", [
  {"type": "heading", "level": 2, "text": "New Section"},
  {"type": "paragraph", "text": "Added content."}
], after="b_0005")
```

## 6. Modify Page Layout
```
set_page("/path/doc.hwp", paper="A4", orientation="landscape",
         margin_top=15, margin_bottom=15)
```

## 7. Edit Document via Markdown (preserves formatting)
```
export_md("/path/doc.hwp")
→ returns Markdown with block IDs (<!-- id: b_0000 -->)
→ AI edits the Markdown text
import_md("/path/doc.hwp", edited_md, "/path/doc_edited.hwp")
→ merges edits back, preserving original HWP formatting
```

## Tips
- Always `read` first to discover block IDs before editing
- Use `output_path` to save changes to a new file (non-destructive)
- HWP/HWPX editing uses Seed Patch (preserves original binary fidelity)
- Block structure changes (insert/remove) switch to From Scratch mode
- For bulk text editing, prefer `export_md` + `import_md` over multiple `edit` calls
- Call `describe('fmt')` for the full format alias table""",

    "api": """\
# UdfDocument API Reference

`UdfDocument` is the central object returned by `udf.parse()`. It provides deep
CRUD operations on the document tree.

## Properties (shortcuts)
| Property | Returns | Description |
|----------|---------|-------------|
| `.blocks` | list[Block] | Top-level block list |
| `.metadata` | DocumentMetadata | Title, author, page settings |
| `.page_boundaries` | list[PageBoundary] | Page break positions |
| `.headings` | list[HeadingBlock] | All headings (deep search) |
| `.paragraphs` | list[ParagraphBlock] | All paragraphs (deep search) |
| `.tables` | list[TableBlock] | All tables (deep search) |
| `.images` | list[ImageBlock] | All images (deep search) |
| `.outline` | list[OutlineItem] | Table of contents structure |

## Block Operations
| Method | Description |
|--------|-------------|
| `get_block(id)` → Block | Find block anywhere in tree |
| `find_blocks(type, **filters)` → list | Filter by type/attributes |
| `find_text(pattern)` → list[dict] | Regex search across all text |
| `replace_text(old, new)` → int | Global find-and-replace |
| `add_block(block, parent_id, after)` | Insert block at position |
| `move_block(id, parent_id, after)` | Reorder block in tree |
| `remove_block(id)` → Block | Delete and return block |

## Inline Operations
| Method | Description |
|--------|-------------|
| `get_inline(block_id, idx)` → Inline | Get inline by index |
| `add_inline(block_id, inline, at)` | Append/insert inline |
| `remove_inline(block_id, idx)` → Inline | Delete inline |
| `set_inline_text(block_id, idx, text)` | Change text content |
| `set_inline_format(block_id, idx, **fmt)` | Update char formatting |
| `split_inline(block_id, idx, offset)` | Split at character position |

## Format Operations
| Method | Description |
|--------|-------------|
| `get_block_format(id)` → BlockFormat | Get paragraph formatting |
| `set_block_format(id, **fmt)` | Update paragraph formatting |
| `set_metadata(**kwargs)` | Update title/author/page |

## Table Operations
| Method | Description |
|--------|-------------|
| `get_cell(table_id, row, col)` → Cell | Access cell by position |
| `add_table_row(table_id, at)` | Insert row |
| `remove_table_row(table_id, idx)` | Delete row |
| `add_table_column(table_id, at)` | Insert column |
| `remove_table_column(table_id, idx)` | Delete column |
| `merge_cells(table_id, r1, c1, r2, c2)` | Merge cell range |
| `split_cell(table_id, row, col)` | Unmerge cell |

## Export
| Method | Description |
|--------|-------------|
| `to(fmt, output_path)` | Render to format (hwp/docx/md/html) |
| `to_json()` → str | Serialize to JSON |
| `to_dict()` → dict | Serialize to dict |
| `save(path)` | Save as JSON file |

## Top-level Fields
| Field | Type | Description |
|-------|------|-------------|
| `udf` | str | Schema version ("1.0") |
| `source_format` | str | Original format (hwp/hwpx/docx/pdf/md) |
| `verbatim` | VerbatimLayer? | Lossless round-trip data |
| `original_container` | OriginalContainer? | Original file ref (enables Seed Patch) |
| `loss_report` | LossReport? | What was lost in conversion |
| `extensions` | dict | Format-specific extra data |

See also: describe('metadata'), describe('loss')""",

    "metadata": """\
# DocumentMetadata

Accessible via `doc.metadata`. Controls page layout and document properties.

## Document Properties
| Field | Type | Example |
|-------|------|---------|
| title | str? | "Monthly Report" |
| author | str? | "John Doe" |
| subject | str? | "Q1 Summary" |
| keywords | list[str] | ["report", "Q1"] |
| language | str? | "ko" / "en" |
| created_at | str? | "2026-05-26T10:00:00" |
| modified_at | str? | "2026-05-26T15:30:00" |

## Page Layout
| Field | Type | Unit | Example |
|-------|------|------|---------|
| page_size | str? | — | "A4" / "Letter" |
| page_width | float? | pt | 595.28 (A4) |
| page_height | float? | pt | 841.89 (A4) |
| margins | PageMargins? | — | see below |
| header_margin | float? | pt | 42.52 |
| footer_margin | float? | pt | 42.52 |
| gutter | float? | pt | 0.0 |

## PageMargins
| Field | Type | Unit |
|-------|------|------|
| top | float | pt |
| bottom | float | pt |
| left | float | pt |
| right | float | pt |

## Multi-column
| Field | Type | Description |
|-------|------|-------------|
| columns | ColumnDef? | Column count + gap |
| sections | list[SectionDef] | Per-section overrides |

## Numbering
| Field | Type | Default |
|-------|------|---------|
| start_page_number | int? | 1 |
| start_footnote_number | int? | 1 |
| start_endnote_number | int? | 1 |
| footnote_numbering_format | str? | "decimal" |
| endnote_numbering_format | str? | "decimal" |

## Via MCP
Use `set_page(path, paper="A4", margin_top=20, ...)` to modify page settings.
Use `set_metadata(title="...", author="...")` via the edit API.""",

    "loss": """\
# LossReport

When converting between formats, information may be lost. The `loss_report`
field on UdfDocument tracks exactly what was lost and whether round-trip is safe.

## Structure
```
doc.loss_report
├── total_blocks: int        — Total blocks in document
├── lossless_blocks: int     — Blocks with zero information loss
├── lossy_blocks: list[BlockLoss]
│   ├── block_id: str        — Which block had loss
│   ├── loss_type: str       — "user_edited" / "format_limit" / "unintended"
│   └── description: str     — What was lost
├── dropped_features: list[str]  — Document-level features lost
└── is_roundtrip_safe: bool  — Can this round-trip without loss?
```

## Loss Types
- `user_edited` — User intentionally changed content (expected, passes validation)
- `format_limit` — Target format cannot represent feature (e.g. DrawingBlock in MD)
- `unintended` — Unexpected loss, likely a bug (fails validation)

## Example
```json
{
  "total_blocks": 15,
  "lossless_blocks": 13,
  "lossy_blocks": [
    {"block_id": "b_0007", "loss_type": "format_limit",
     "description": "Table cell shading not supported in target format"},
    {"block_id": "b_0012", "loss_type": "format_limit",
     "description": "DrawingBlock cannot be regenerated without original file"}
  ],
  "dropped_features": ["macros", "vba_project"],
  "is_roundtrip_safe": false
}
```

## When is it present?
- After `udf.parse()`: reports what the parser couldn't fully represent
- After cross-format `udf.render()`: reports format-specific loss
- Same-format round-trip with Seed Patch: typically `is_roundtrip_safe = true`

## Using in MCP
The `read` tool does not surface loss_report directly in simplified JSON.
To check, use the Python API:
```python
doc = udf.parse("file.hwp")
if doc.loss_report and not doc.loss_report.is_roundtrip_safe:
    print(doc.loss_report.dropped_features)
```""",
}


# ------------------------------------------------------------------
# Document fingerprint
# ------------------------------------------------------------------

_SOURCE_HEADER_RE = re.compile(
    r"^<!--\s*udf-source:.*?-->\s*\n?", re.MULTILINE
)


def _fingerprint(doc: UdfDocument) -> str:
    """Content-based fingerprint (first 12 chars of sha256 over block texts)."""
    h = hashlib.sha256()
    for b in doc.blocks:
        bid = getattr(b, "id", "")
        text = b.text_content() if hasattr(b, "text_content") else ""
        h.update(f"{bid}:{text}\n".encode())
    return h.hexdigest()[:12]


def _build_source_header(path: str, doc: UdfDocument) -> str:
    fp = _fingerprint(doc)
    fmt = doc.source_format or "unknown"
    n = len(doc.blocks)
    abs_path = str(Path(path).resolve())
    return f"<!-- udf-source: path={abs_path} format={fmt} fingerprint={fp} blocks={n} -->\n"


def _parse_source_header(md: str) -> dict[str, str] | None:
    m = _SOURCE_HEADER_RE.match(md)
    if not m:
        return None
    header = m.group(0)
    result: dict[str, str] = {}
    for key in ("path", "format", "fingerprint", "blocks"):
        km = re.search(rf"{key}=(\S+)", header)
        if km:
            result[key] = km.group(1)
    return result


def _strip_source_header(md: str) -> str:
    return _SOURCE_HEADER_RE.sub("", md, count=1)


# ------------------------------------------------------------------
# Structure-change helper
# ------------------------------------------------------------------


def _force_from_scratch(doc: UdfDocument) -> None:
    """블록 추가/삭제 후 From Scratch 모드 강제 (Seed Patch 무효화)."""
    doc.original_container = None
    doc.verbatim = None


# ------------------------------------------------------------------
# Edit helpers
# ------------------------------------------------------------------

_FMT_KEY_MAP: dict[str, str] = {
    "bold": "bold",
    "italic": "italic",
    "underline": "underline",
    "strike": "strikethrough",
    "strikethrough": "strikethrough",
    "size": "font_size",
    "font_size": "font_size",
    "font": "font_name",
    "font_name": "font_name",
    "color": "color",
    "bg": "background_color",
    "background_color": "background_color",
    "super": "superscript",
    "superscript": "superscript",
    "sub": "subscript",
    "subscript": "subscript",
    "caps": "small_caps",
    "small_caps": "small_caps",
    "all_caps": "all_caps",
    "hidden": "hidden",
    "outline": "outline",
    "shadow": "shadow",
    "emboss": "emboss",
    "engrave": "engrave",
    "letter_spacing": "letter_spacing",
    "underline_type": "underline_type",
    "strikeout_type": "strikeout_type",
    "emphasis_mark": "emphasis_mark",
}

_BLOCK_FMT_KEY_MAP: dict[str, str] = {
    "align": "alignment",
    "alignment": "alignment",
    "bold": "bold",
    "italic": "italic",
    "font": "font_name",
    "font_name": "font_name",
    "size": "font_size",
    "font_size": "font_size",
    "line_h": "line_spacing",
    "line_spacing": "line_spacing",
    "line_spacing_type": "line_spacing_type",
    "sp_before": "space_before",
    "space_before": "space_before",
    "sp_after": "space_after",
    "space_after": "space_after",
    "indent_l": "indent_left",
    "indent_left": "indent_left",
    "indent_r": "indent_right",
    "indent_right": "indent_right",
    "indent_1st": "indent_first",
    "indent_first": "indent_first",
    "dir": "text_direction",
    "text_direction": "text_direction",
    "bg": "background_color",
    "background_color": "background_color",
    "keep_with_next": "keep_with_next",
    "page_break_before": "page_break_before",
    "outline_level": "outline_level",
}


def _apply_edits(doc: UdfDocument, edits: list[dict[str, Any]]) -> int:
    count = 0
    for ed in edits:
        block_id = ed.get("block_id")
        if not block_id:
            raise ValueError("edit에 block_id가 필요합니다")

        block = doc.get_block(block_id)
        if block is None:
            raise ValueError(f"블록을 찾을 수 없습니다: {block_id}")

        if "block_fmt" in ed:
            _apply_block_fmt(block, ed["block_fmt"])
            count += 1

        inline_idx = ed.get("inline_idx", -1)
        text = ed.get("text")
        fmt = ed.get("fmt")

        if inline_idx == -1 and text is None and fmt is None:
            continue

        inlines = _core_get_inlines(block)
        if inlines is None:
            raise ValueError(f"블록 {block_id}은 인라인을 가질 수 없는 타입입니다")

        if inline_idx is None:
            if text is not None:
                new_inline = TextInline(text=text)
                if fmt:
                    new_inline = _apply_inline_fmt(new_inline, fmt)
                inlines.append(new_inline)
                _sync_heading_text(block)
                count += 1
        elif isinstance(inline_idx, int) and inline_idx >= 0:
            if inline_idx >= len(inlines):
                raise ValueError(
                    f"inline_idx {inline_idx}이 범위를 벗어났습니다 "
                    f"(블록 {block_id}의 인라인 수: {len(inlines)})"
                )
            inline = inlines[inline_idx]
            updates: dict[str, Any] = {}
            if text is not None:
                updates["text"] = text
            if fmt:
                inline = _apply_inline_fmt(inline, fmt)
                if text is not None:
                    inline = inline.model_copy(update={"text": text})
                inlines[inline_idx] = inline
            elif updates:
                inlines[inline_idx] = inline.model_copy(update=updates)
            _sync_heading_text(block)
            count += 1

    return count




def _apply_inline_fmt(inline: Any, fmt: dict[str, Any]) -> Any:
    updates: dict[str, Any] = {}
    for key, value in fmt.items():
        attr = _FMT_KEY_MAP.get(key)
        if attr is None:
            continue
        if attr in ("color", "background_color") and isinstance(value, str):
            value = Color.from_hex(value)
        updates[attr] = value
    return inline.model_copy(update=updates) if updates else inline


def _apply_block_fmt(block: BlockBase, fmt_dict: dict[str, Any]) -> None:
    updates: dict[str, Any] = {}
    for key, value in fmt_dict.items():
        attr = _BLOCK_FMT_KEY_MAP.get(key)
        if attr is None:
            continue
        if attr == "background_color" and isinstance(value, str):
            value = Color.from_hex(value)
        updates[attr] = value
    if not updates:
        return
    if hasattr(block, "format") and block.format is not None:
        block.format = block.format.model_copy(update=updates)  # type: ignore[union-attr]
    else:
        block.format = BlockFormat(**updates)  # type: ignore[attr-defined]


def _sync_heading_text(block: Any) -> None:
    if isinstance(block, HeadingBlock):
        block.text = "".join(
            i.text for i in block.inlines if hasattr(i, "text")
        )


def _save_doc(doc: UdfDocument, output_path: str) -> None:
    import tempfile

    fmt = doc.source_format
    out_path = Path(output_path)

    from udf.formats import get_registry
    spec = get_registry().get(fmt)
    if spec and spec.is_binary:
        with tempfile.NamedTemporaryFile(
            dir=out_path.parent, suffix=out_path.suffix, delete=False,
        ) as tmp:
            tmp_name = tmp.name
        try:
            udf.render(doc, fmt, output_path=tmp_name)
            Path(tmp_name).replace(out_path)
        except Exception:
            Path(tmp_name).unlink(missing_ok=True)
            raise
    else:
        result = udf.render(doc, fmt, output_path=output_path)
        if result is not None:
            out_path.write_text(result, encoding="utf-8")
