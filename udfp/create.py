"""JSON 블록 스키마 → UdfDocument 변환.

AI가 전달하는 blocks JSON을 Document Model로 변환한다.
create tool과 insert_blocks tool에서 공통 사용.
"""

from __future__ import annotations

import itertools
from typing import Any

from udf.pipeline.document import UdfDocument
from udf.schema.blocks import (
    Block,
    CodeBlock,
    EquationBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TableColumnDef,
    TableRow,
)
from udf.schema.formats import BlockFormat, CellFormat
from udf.schema.inlines import LinkInline, TextInline
from udf.schema.metadata import (
    ColumnDef,
    DocumentMetadata,
    PageMargins,
)
from udf.schema.types import Color

import base64
import tempfile
import urllib.request

_PAPER_SIZES: dict[str, tuple[float, float]] = {
    "a4": (595.28, 841.89),
    "a3": (841.89, 1190.55),
    "a5": (419.53, 595.28),
    "b5": (498.90, 708.66),
    "letter": (612.0, 792.0),
    "legal": (612.0, 1008.0),
}

_counter = itertools.count(1)


def _reset_counter() -> None:
    global _counter
    _counter = itertools.count(1)


def _next_id() -> str:
    return f"b_{next(_counter):04d}"


def _resolve_image_src(src: str) -> str:
    """이미지 소스를 로컬 파일 경로로 변환.

    지원 형식:
    - 로컬 파일 경로 → 그대로 반환
    - data:image/...;base64,... → 임시 파일에 디코드하여 저장
    - https://... or http://... → 다운로드하여 임시 파일에 저장
    """
    if not src:
        return src

    if src.startswith("data:"):
        try:
            header, data = src.split(",", 1)
            ext = ".png"
            if "image/jpeg" in header or "image/jpg" in header:
                ext = ".jpg"
            elif "image/gif" in header:
                ext = ".gif"
            elif "image/svg" in header:
                ext = ".svg"
            decoded = base64.b64decode(data)
            tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            tmp.write(decoded)
            tmp.close()
            return tmp.name
        except Exception:
            return src

    if src.startswith("http://") or src.startswith("https://"):
        try:
            ext = ".png"
            if ".jpg" in src or ".jpeg" in src:
                ext = ".jpg"
            elif ".gif" in src:
                ext = ".gif"
            elif ".svg" in src:
                ext = ".svg"
            tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
            urllib.request.urlretrieve(src, tmp.name)
            tmp.close()
            return tmp.name
        except Exception:
            return src

    return src


def _parse_color(value: str | None) -> Color | None:
    if value is None:
        return None
    return Color.from_hex(value)


def _make_inline(spec: dict[str, Any]) -> TextInline | LinkInline:
    """인라인 JSON → Inline 인스턴스."""
    fmt = spec.get("fmt", {})
    if "url" in spec:
        return LinkInline(
            text=spec.get("text", ""),
            url=spec["url"],
            title=spec.get("title"),
        )
    kwargs: dict[str, Any] = {"text": spec.get("text", "")}
    if fmt.get("bold"):
        kwargs["bold"] = True
    if fmt.get("italic"):
        kwargs["italic"] = True
    if fmt.get("underline"):
        kwargs["underline"] = True
    if fmt.get("strikethrough") or fmt.get("strike"):
        kwargs["strikethrough"] = True
    if fmt.get("superscript") or fmt.get("super"):
        kwargs["superscript"] = True
    if fmt.get("subscript") or fmt.get("sub"):
        kwargs["subscript"] = True
    if "size" in fmt or "font_size" in fmt:
        kwargs["font_size"] = fmt.get("size") or fmt.get("font_size")
    if "font" in fmt or "font_name" in fmt:
        kwargs["font_name"] = fmt.get("font") or fmt.get("font_name")
    if "color" in fmt:
        kwargs["color"] = _parse_color(fmt["color"])
    if "bg" in fmt or "background_color" in fmt:
        kwargs["background_color"] = _parse_color(fmt.get("bg") or fmt.get("background_color"))
    return TextInline(**kwargs)


def _make_inlines(spec: dict[str, Any]) -> list:
    """블록 spec에서 inlines 리스트 생성.

    두 가지 형태 지원:
    - {"text": "..."} → 단일 TextInline
    - {"inlines": [{...}, ...]} → 여러 Inline
    """
    if "inlines" in spec:
        return [_make_inline(i) for i in spec["inlines"]]
    text = spec.get("text", "")
    if not text:
        return []
    fmt = spec.get("fmt", {})
    return [_make_inline({"text": text, "fmt": fmt})]


def _make_block_format(fmt: dict[str, Any]) -> BlockFormat | None:
    """fmt dict → BlockFormat."""
    if not fmt:
        return None
    kwargs: dict[str, Any] = {}
    if "align" in fmt or "alignment" in fmt:
        kwargs["alignment"] = fmt.get("align") or fmt.get("alignment")
    if "line_spacing" in fmt or "line_h" in fmt:
        kwargs["line_spacing"] = fmt.get("line_spacing") or fmt.get("line_h")
    if "space_before" in fmt or "sp_before" in fmt:
        kwargs["space_before"] = fmt.get("space_before") or fmt.get("sp_before")
    if "space_after" in fmt or "sp_after" in fmt:
        kwargs["space_after"] = fmt.get("space_after") or fmt.get("sp_after")
    if "indent_left" in fmt or "indent_l" in fmt:
        kwargs["indent_left"] = fmt.get("indent_left") or fmt.get("indent_l")
    if "indent_right" in fmt or "indent_r" in fmt:
        kwargs["indent_right"] = fmt.get("indent_right") or fmt.get("indent_r")
    if "indent_first" in fmt or "indent_1st" in fmt:
        kwargs["indent_first"] = fmt.get("indent_first") or fmt.get("indent_1st")
    if "keep_with_next" in fmt:
        kwargs["keep_with_next"] = fmt["keep_with_next"]
    if "page_break_before" in fmt:
        kwargs["page_break_before"] = fmt["page_break_before"]
    if "bg" in fmt or "background_color" in fmt:
        kwargs["background_color"] = _parse_color(fmt.get("bg") or fmt.get("background_color"))
    if not kwargs:
        return None
    return BlockFormat(**kwargs)


def _make_cell_format(spec: dict[str, Any]) -> CellFormat | None:
    """셀 spec에서 CellFormat 생성."""
    kwargs: dict[str, Any] = {}
    if "bg" in spec or "background_color" in spec:
        kwargs["background_color"] = _parse_color(spec.get("bg") or spec.get("background_color"))
    if "valign" in spec or "vertical_align" in spec:
        kwargs["vertical_align"] = spec.get("valign") or spec.get("vertical_align")
    if not kwargs:
        return None
    return CellFormat(**kwargs)


def _build_block(spec: dict[str, Any]) -> Block:
    """단일 블록 JSON → Block 인스턴스."""
    block_type = spec.get("type", "paragraph")

    if block_type == "heading":
        level = spec.get("level", 1)
        inlines = _make_inlines(spec)
        text = spec.get("text", "")
        if not text and inlines:
            text = "".join(i.text for i in inlines if hasattr(i, "text"))
        return HeadingBlock(
            id=_next_id(),
            level=max(1, min(6, level)),
            text=text,
            inlines=inlines,
            format=_make_block_format(spec.get("fmt", {})),
        )

    elif block_type == "paragraph":
        return ParagraphBlock(
            id=_next_id(),
            inlines=_make_inlines(spec),
            format=_make_block_format(spec.get("fmt", {})),
        )

    elif block_type == "table":
        return _build_table(spec)

    elif block_type == "image":
        src = _resolve_image_src(spec.get("src", ""))
        return ImageBlock(
            id=_next_id(),
            src=src,
            alt=spec.get("alt", ""),
            width=spec.get("width"),
            height=spec.get("height"),
        )

    elif block_type == "list":
        return _build_list(spec)

    elif block_type == "code":
        return CodeBlock(
            id=_next_id(),
            code=spec.get("code", ""),
            language=spec.get("language"),
        )

    elif block_type == "quote":
        content: list[Block] = []
        if "text" in spec:
            content.append(ParagraphBlock(
                id=_next_id(),
                inlines=[TextInline(text=spec["text"])],
            ))
        elif "blocks" in spec:
            content = [_build_block(b) for b in spec["blocks"]]
        return QuoteBlock(id=_next_id(), content=content)

    elif block_type == "equation":
        return EquationBlock(
            id=_next_id(),
            latex=spec.get("latex"),
            hwp_script=spec.get("hwp_script"),
        )

    elif block_type == "page_break":
        return PageBreakBlock(id=_next_id())

    elif block_type == "horizontal_rule":
        return HorizontalRuleBlock(id=_next_id())

    else:
        return ParagraphBlock(
            id=_next_id(),
            inlines=[TextInline(text=spec.get("text", ""))],
        )


def _build_table(spec: dict[str, Any]) -> TableBlock:
    """테이블 블록 생성."""
    rows_data = spec.get("rows", [])
    col_widths_mm = spec.get("col_widths", [])
    header_rows = spec.get("header_rows", 0)
    border = spec.get("border", "single")

    rows: list[TableRow] = []
    for ri, row_data in enumerate(rows_data):
        cells: list[TableCell] = []
        for ci, cell_spec in enumerate(row_data):
            if cell_spec is None:
                continue
            if isinstance(cell_spec, str):
                cell_spec = {"text": cell_spec}

            cell_inlines = _make_inlines(cell_spec)
            content = [ParagraphBlock(
                id=_next_id(),
                inlines=cell_inlines,
                format=_make_block_format(cell_spec.get("fmt", {})),
            )]
            cell_fmt = _make_cell_format(cell_spec)
            is_header = ri < header_rows if header_rows else None
            width = col_widths_mm[ci] if ci < len(col_widths_mm) else None

            cells.append(TableCell(
                id=_next_id(),
                content=content,
                format=cell_fmt,
                is_header=is_header,
                width=width,
                col_span=cell_spec.get("colspan", 1) if isinstance(cell_spec, dict) else 1,
                row_span=cell_spec.get("rowspan", 1) if isinstance(cell_spec, dict) else 1,
            ))
        rows.append(TableRow(cells=cells))

    col_defs = [TableColumnDef(width=w) for w in col_widths_mm] if col_widths_mm else []
    border_str = "0.5pt solid #000000" if border == "single" else (
        "1.0pt double #000000" if border == "double" else None
    )

    return TableBlock(
        id=_next_id(),
        rows=rows,
        col_widths=col_defs,
        repeat_header=header_rows > 0 if header_rows else None,
        border_top=border_str,
        border_bottom=border_str,
        border_left=border_str,
        border_right=border_str,
        border_inside_h=border_str,
        border_inside_v=border_str,
    )


def _build_list(spec: dict[str, Any]) -> ListBlock:
    """리스트 블록 생성."""
    items_data = spec.get("items", [])
    ordered = spec.get("ordered", False)
    items: list[ListItem] = []
    for item in items_data:
        if isinstance(item, str):
            items.append(ListItem(
                id=_next_id(),
                inlines=[TextInline(text=item)],
            ))
        elif isinstance(item, dict):
            items.append(ListItem(
                id=_next_id(),
                inlines=_make_inlines(item),
            ))
    return ListBlock(
        id=_next_id(),
        ordered=ordered,
        items=items,
    )


def _build_metadata(meta: dict[str, Any] | None) -> DocumentMetadata:
    """metadata JSON → DocumentMetadata."""
    if not meta:
        return DocumentMetadata()
    return DocumentMetadata(
        title=meta.get("title"),
        author=meta.get("author"),
        subject=meta.get("subject"),
        keywords=meta.get("keywords", []),
        language=meta.get("language"),
    )


def _build_page_settings(
    page: dict[str, Any] | None,
    metadata: DocumentMetadata,
) -> None:
    """page JSON → metadata에 페이지 설정 반영."""
    if not page:
        return
    paper = page.get("paper", "A4").lower()
    orientation = page.get("orientation", "portrait")

    size = _PAPER_SIZES.get(paper, _PAPER_SIZES["a4"])
    if orientation == "landscape":
        size = (size[1], size[0])

    metadata.page_width = size[0]
    metadata.page_height = size[1]
    metadata.page_size = paper.upper()

    margin_top = page.get("margin_top", 20.0)
    margin_bottom = page.get("margin_bottom", 20.0)
    margin_left = page.get("margin_left", 30.0)
    margin_right = page.get("margin_right", 30.0)
    metadata.margins = PageMargins(
        top=margin_top * 2.8346,  # mm → pt
        bottom=margin_bottom * 2.8346,
        left=margin_left * 2.8346,
        right=margin_right * 2.8346,
    )

    if "gutter" in page:
        metadata.gutter = page["gutter"] * 2.8346

    columns = page.get("columns", 1)
    if columns > 1:
        gutter = page.get("column_gap", page.get("gutter", 10.0))
        metadata.columns = ColumnDef(count=columns, gap=gutter * 2.8346)


def blocks_from_json(block_specs: list[dict[str, Any]]) -> list[Block]:
    """블록 JSON 배열 → Block 인스턴스 리스트."""
    _reset_counter()
    return [_build_block(spec) for spec in block_specs]


def document_from_json(
    blocks: list[dict[str, Any]],
    *,
    format: str = "hwp",
    page: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> UdfDocument:
    """전체 create 파라미터 → UdfDocument."""
    _reset_counter()
    block_list = [_build_block(spec) for spec in blocks]
    meta = _build_metadata(metadata)
    _build_page_settings(page, meta)
    return UdfDocument(
        source_format=format,
        blocks=block_list,
        metadata=meta,
    )
