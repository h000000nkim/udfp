"""UdfDocument → Simplified JSON 직렬화기.

AI가 문서 구조를 이해하고 편집할 수 있도록 compact하게 변환한다.
pipeline 메타데이터(verbatim, extensions 등)는 제거하고,
블록 구조 + 인라인 텍스트 + 서식(non-null만)을 보존한다.
"""

from __future__ import annotations

import json
from typing import Any

from udf.pipeline.document import UdfDocument
from udf.schema.blocks import (
    BlockBase,
    BookmarkBlock,
    ChartBlock,
    CodeBlock,
    CommentBlock,
    DrawingBlock,
    EndnoteBlock,
    EquationBlock,
    FieldBlock,
    FooterBlock,
    FootnoteBlock,
    HeadingBlock,
    HeaderBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableRow,
    TextArtBlock,
    TextBoxBlock,
    UnknownBlock,
)
from udf.schema.formats import BlockFormat, CellFormat
from udf.schema.inlines import (
    CodeInline,
    EndnoteRefInline,
    EquationInline,
    FootnoteRefInline,
    ImageInline,
    LinkInline,
    RubyInline,
    TextInline,
)
from udf.schema.types import Color, Ratio


def serialize_simplified(doc: UdfDocument) -> str:
    return json.dumps(_serialize_doc(doc), ensure_ascii=False)


def _serialize_doc(doc: UdfDocument) -> dict[str, Any]:
    result: dict[str, Any] = {"source_format": doc.source_format}

    meta = doc.metadata
    if meta.title or meta.author:
        md: dict[str, Any] = {}
        if meta.title:
            md["title"] = meta.title
        if meta.author:
            md["author"] = meta.author
        result["metadata"] = md

    blocks = []
    for block in doc.blocks:
        b = _serialize_block(block)
        if b is not None:
            blocks.append(b)
    result["blocks"] = blocks
    return result


def _serialize_block(block: BlockBase) -> dict[str, Any] | None:
    if isinstance(block, ParagraphBlock):
        return _serialize_paragraph(block)
    if isinstance(block, HeadingBlock):
        return _serialize_heading(block)
    if isinstance(block, TableBlock):
        return _serialize_table(block)
    if isinstance(block, ListBlock):
        return _serialize_list(block)
    if isinstance(block, FieldBlock):
        return _serialize_field(block)
    if isinstance(block, ImageBlock):
        return _serialize_image(block)
    if isinstance(block, CodeBlock):
        return _serialize_code(block)
    if isinstance(block, EquationBlock):
        return _serialize_equation(block)
    if isinstance(block, TextBoxBlock):
        return _serialize_container(block, "text_box")
    if isinstance(block, QuoteBlock):
        return _serialize_container(block, "quote")
    if isinstance(block, FootnoteBlock):
        return _serialize_footnote(block)
    if isinstance(block, EndnoteBlock):
        return _serialize_endnote(block)
    if isinstance(block, HeaderBlock):
        return _serialize_container(block, "header")
    if isinstance(block, FooterBlock):
        return _serialize_container(block, "footer")
    if isinstance(block, CommentBlock):
        return _serialize_comment(block)
    if isinstance(block, DrawingBlock):
        return _serialize_drawing(block)
    if isinstance(block, ChartBlock):
        d: dict[str, Any] = {"id": block.id, "type": "chart"}
        if block.description:
            d["description"] = block.description
        return d
    if isinstance(block, TextArtBlock):
        d = {"id": block.id, "type": "text_art"}
        if block.text:
            d["text"] = block.text
        return d
    if isinstance(block, PageBreakBlock):
        return {"id": block.id, "type": "page_break"}
    if isinstance(block, HorizontalRuleBlock):
        return {"id": block.id, "type": "horizontal_rule"}
    if isinstance(block, BookmarkBlock):
        d = {"id": block.id, "type": "bookmark", "name": block.name}
        return d
    if isinstance(block, UnknownBlock):
        return None
    return {"id": block.id, "type": getattr(block, "type", "unknown")}


# ------------------------------------------------------------------
# Block serializers
# ------------------------------------------------------------------

def _serialize_paragraph(block: ParagraphBlock) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": "paragraph"}
    fmt = _serialize_block_format(block.format)
    if fmt:
        d["fmt"] = fmt
    inlines = _serialize_inlines(block.inlines)
    if inlines:
        d["inlines"] = inlines
    return d


def _serialize_heading(block: HeadingBlock) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": block.id,
        "type": "heading",
        "level": block.level,
        "text": block.text,
    }
    fmt = _serialize_block_format(block.format)
    if fmt:
        d["fmt"] = fmt
    inlines = _serialize_inlines(block.inlines)
    if inlines:
        d["inlines"] = inlines
    return d


def _serialize_table(block: TableBlock) -> dict[str, Any]:
    grid = _compute_grid_coordinates(block.rows)
    rows_out: list[list[dict[str, Any]]] = []
    for row_idx, row in enumerate(block.rows):
        cells_out: list[dict[str, Any]] = []
        for cell_idx, cell in enumerate(row.cells):
            r, c = grid[row_idx][cell_idx]
            cd: dict[str, Any] = {"id": cell.id, "row": r, "col": c}
            if cell.row_span > 1:
                cd["row_span"] = cell.row_span
            if cell.col_span > 1:
                cd["col_span"] = cell.col_span
            cfmt = _serialize_cell_format(cell.format)
            if cfmt:
                cd["fmt"] = cfmt
            content = []
            for cb in cell.content:
                b = _serialize_block(cb)
                if b is not None:
                    content.append(b)
            if content:
                cd["content"] = content
            cells_out.append(cd)
        rows_out.append(cells_out)
    d: dict[str, Any] = {"id": block.id, "type": "table", "rows": rows_out}
    return d


def _serialize_list(block: ListBlock) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": "list"}
    if block.ordered:
        d["ordered"] = True
    items = [_serialize_list_item(item) for item in block.items]
    if items:
        d["items"] = items
    return d


def _serialize_list_item(item: ListItem) -> dict[str, Any]:
    d: dict[str, Any] = {"id": item.id}
    inlines = _serialize_inlines(item.inlines)
    if inlines:
        d["inlines"] = inlines
    if item.checked is not None:
        d["checked"] = item.checked
    if item.children:
        d["children"] = [_serialize_list_item(c) for c in item.children]
    return d


def _serialize_field(block: FieldBlock) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": block.id,
        "type": "field",
        "field_type": block.field_type,
    }
    if block.value is not None:
        d["value"] = block.value
    inlines = _serialize_inlines(block.inlines)
    if inlines:
        d["inlines"] = inlines
    if block.options:
        d["options"] = block.options
    if block.default_value is not None:
        d["default_value"] = block.default_value
    if block.required:
        d["required"] = block.required
    return d


def _serialize_image(block: ImageBlock) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": "image", "src": block.src}
    if block.alt:
        d["alt"] = block.alt
    if block.width is not None:
        d["width"] = block.width
    if block.height is not None:
        d["height"] = block.height
    return d


def _serialize_code(block: CodeBlock) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": "code", "code": block.code}
    if block.language:
        d["language"] = block.language
    return d


def _serialize_equation(block: EquationBlock) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": "equation"}
    if block.latex:
        d["latex"] = block.latex
    if block.hwp_script:
        d["hwp_script"] = block.hwp_script
    return d


def _serialize_container(block: BlockBase, block_type: str) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": block_type}
    content_list = getattr(block, "content", [])
    content = []
    for cb in content_list:
        b = _serialize_block(cb)
        if b is not None:
            content.append(b)
    if content:
        d["content"] = content
    return d


def _serialize_footnote(block: FootnoteBlock) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": "footnote", "ref": block.ref}
    content = []
    for cb in block.content:
        b = _serialize_block(cb)
        if b is not None:
            content.append(b)
    if content:
        d["content"] = content
    return d


def _serialize_endnote(block: EndnoteBlock) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": "endnote", "ref": block.ref}
    content = []
    for cb in block.content:
        b = _serialize_block(cb)
        if b is not None:
            content.append(b)
    if content:
        d["content"] = content
    return d


def _serialize_comment(block: CommentBlock) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": "comment"}
    if block.author:
        d["author"] = block.author
    if block.date:
        d["date"] = block.date
    content = []
    for cb in block.content:
        b = _serialize_block(cb)
        if b is not None:
            content.append(b)
    if content:
        d["content"] = content
    return d


def _serialize_drawing(block: DrawingBlock) -> dict[str, Any]:
    d: dict[str, Any] = {"id": block.id, "type": "drawing"}
    if block.shape_type:
        d["shape_type"] = block.shape_type
    return d


# ------------------------------------------------------------------
# Inline serializers
# ------------------------------------------------------------------

def _serialize_inlines(inlines: list) -> list[dict[str, Any]]:
    result = []
    for idx, inline in enumerate(inlines):
        result.append(_serialize_inline(inline, idx))
    return result


def _serialize_inline(inline: Any, idx: int) -> dict[str, Any]:
    if isinstance(inline, TextInline):
        d: dict[str, Any] = {"idx": idx, "text": inline.text}
        fmt = _serialize_inline_format(inline)
        if fmt:
            d["fmt"] = fmt
        return d
    if isinstance(inline, LinkInline):
        d = {"idx": idx, "type": "link", "text": inline.text, "url": inline.url}
        return d
    if isinstance(inline, ImageInline):
        d = {"idx": idx, "type": "image_inline", "src": inline.src}
        if inline.alt:
            d["alt"] = inline.alt
        return d
    if isinstance(inline, FootnoteRefInline):
        d = {"idx": idx, "type": "footnote_ref", "ref_id": inline.ref_id}
        if inline.number is not None:
            d["number"] = inline.number
        return d
    if isinstance(inline, EndnoteRefInline):
        d = {"idx": idx, "type": "endnote_ref", "ref_id": inline.ref_id}
        if inline.number is not None:
            d["number"] = inline.number
        return d
    if isinstance(inline, EquationInline):
        d = {"idx": idx, "type": "equation_inline"}
        if inline.latex:
            d["latex"] = inline.latex
        if inline.hwp_script:
            d["hwp_script"] = inline.hwp_script
        return d
    if isinstance(inline, RubyInline):
        return {
            "idx": idx,
            "type": "ruby",
            "base_text": inline.base_text,
            "ruby_text": inline.ruby_text,
        }
    if isinstance(inline, CodeInline):
        d = {"idx": idx, "type": "code_inline", "code": inline.code}
        if inline.language:
            d["language"] = inline.language
        return d
    return {"idx": idx, "type": getattr(inline, "type", "unknown")}


# ------------------------------------------------------------------
# Format serializers
# ------------------------------------------------------------------

_INLINE_FMT_FIELDS: list[tuple[str, str]] = [
    ("bold", "bold"),
    ("italic", "italic"),
    ("underline", "underline"),
    ("strikethrough", "strike"),
    ("superscript", "super"),
    ("subscript", "sub"),
    ("small_caps", "caps"),
    ("all_caps", "all_caps"),
    ("hidden", "hidden"),
    ("outline", "outline"),
    ("shadow", "shadow"),
    ("emboss", "emboss"),
    ("engrave", "engrave"),
    ("font_name", "font"),
    ("font_size", "size"),
    ("letter_spacing", "letter_spacing"),
    ("underline_type", "underline_type"),
    ("strikeout_type", "strikeout_type"),
    ("emphasis_mark", "emphasis_mark"),
]


def _serialize_inline_format(inline: TextInline) -> dict[str, Any] | None:
    fmt: dict[str, Any] = {}
    for attr, key in _INLINE_FMT_FIELDS:
        val = getattr(inline, attr, None)
        if val is not None:
            fmt[key] = val
    if inline.color is not None:
        fmt["color"] = _color_to_hex(inline.color)
    if inline.background_color is not None:
        fmt["bg"] = _color_to_hex(inline.background_color)
    if inline.highlight_color is not None:
        fmt["highlight"] = _color_to_hex(inline.highlight_color)
    if inline.underline_color is not None:
        fmt["underline_color"] = _color_to_hex(inline.underline_color)
    if inline.strikeout_color is not None:
        fmt["strikeout_color"] = _color_to_hex(inline.strikeout_color)
    if inline.char_scale is not None:
        fmt["char_scale"] = inline.char_scale.percent
    if inline.char_offset is not None:
        fmt["char_offset"] = inline.char_offset
    return fmt or None


_BLOCK_FMT_FIELDS: list[tuple[str, str]] = [
    ("bold", "bold"),
    ("italic", "italic"),
    ("font_name", "font"),
    ("font_size", "size"),
    ("alignment", "align"),
    ("line_spacing_type", "line_spacing_type"),
    ("space_before", "sp_before"),
    ("space_after", "sp_after"),
    ("indent_left", "indent_l"),
    ("indent_right", "indent_r"),
    ("indent_first", "indent_1st"),
    ("text_direction", "dir"),
    ("keep_with_next", "keep_with_next"),
    ("page_break_before", "page_break_before"),
    ("outline_level", "outline_level"),
]


def _serialize_block_format(fmt: BlockFormat | None) -> dict[str, Any] | None:
    if fmt is None:
        return None
    d: dict[str, Any] = {}
    for attr, key in _BLOCK_FMT_FIELDS:
        val = getattr(fmt, attr, None)
        if val is not None:
            d[key] = val
    if fmt.line_spacing is not None:
        if isinstance(fmt.line_spacing, Ratio):
            d["line_h"] = fmt.line_spacing.percent
        else:
            d["line_h"] = fmt.line_spacing
    if fmt.background_color is not None:
        d["bg"] = _color_to_hex(fmt.background_color)
    return d or None


_CELL_FMT_FIELDS: list[tuple[str, str]] = [
    ("vertical_align", "valign"),
    ("text_direction", "dir"),
    ("no_wrap", "no_wrap"),
    ("border_top", "border_top"),
    ("border_bottom", "border_bottom"),
    ("border_left", "border_left"),
    ("border_right", "border_right"),
]


def _serialize_cell_format(fmt: CellFormat | None) -> dict[str, Any] | None:
    if fmt is None:
        return None
    d: dict[str, Any] = {}
    for attr, key in _CELL_FMT_FIELDS:
        val = getattr(fmt, attr, None)
        if val is not None:
            d[key] = val
    if fmt.background_color is not None:
        d["bg"] = _color_to_hex(fmt.background_color)
    return d or None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _color_to_hex(c: Color | str | None) -> str | None:
    if c is None:
        return None
    if isinstance(c, Color):
        return c.to_hex()
    return str(c)


# ------------------------------------------------------------------
# Grid coordinate computation
# ------------------------------------------------------------------

def _compute_grid_coordinates(
    rows: list[TableRow],
) -> list[list[tuple[int, int]]]:
    if not rows:
        return []

    max_cols = 0
    for row in rows:
        row_cols = sum(cell.col_span for cell in row.cells)
        if row_cols > max_cols:
            max_cols = row_cols

    num_rows = len(rows)
    occupancy = [[False] * max_cols for _ in range(num_rows)]
    coords: list[list[tuple[int, int]]] = [[] for _ in range(num_rows)]

    for row_idx, row in enumerate(rows):
        col_cursor = 0
        for cell in row.cells:
            while col_cursor < max_cols and occupancy[row_idx][col_cursor]:
                col_cursor += 1
            coords[row_idx].append((row_idx, col_cursor))
            for dr in range(cell.row_span):
                for dc in range(cell.col_span):
                    r, c = row_idx + dr, col_cursor + dc
                    if r < num_rows and c < max_cols:
                        occupancy[r][c] = True
            col_cursor += cell.col_span

    return coords
