"""Page-breaking engine.

Takes a list of document blocks, computes exact heights using the
line-breaking engine, and splits into pages at precise boundaries.
"""

from __future__ import annotations

from udf.layout import LayoutBlock, LayoutLine, LayoutPage
from udf.layout.line_break import break_into_lines, inlines_to_runs, InlineRun
from udf.layout.font_metrics import measure_string
from udf.schema.blocks import (
    Block, HeadingBlock, ParagraphBlock, TableBlock, TableCell,
    ImageBlock, EquationBlock, CodeBlock, QuoteBlock, ListBlock,
    TextBoxBlock, DrawingBlock, HorizontalRuleBlock, PageBreakBlock,
    HeaderBlock, FooterBlock, EndnoteBlock,
)
from udf.schema.formats import BlockFormat
from udf.schema.types import Ratio


def _parse_ls(ls) -> float:
    if isinstance(ls, Ratio):
        return ls.factor
    if isinstance(ls, (int, float)):
        v = float(ls)
        return v / 100 if v > 5 else v
    return 1.6


def _spacing(fmt: BlockFormat | None) -> tuple[float, float]:
    sb = 0.0
    sa = 0.0
    if fmt:
        if fmt.space_before is not None:
            sb = float(fmt.space_before) if isinstance(fmt.space_before, (int, float)) else 0.0
        if fmt.space_after is not None:
            sa = float(fmt.space_after) if isinstance(fmt.space_after, (int, float)) else 0.0
    return sb, sa


def measure_block_height(
    block: Block,
    container_width: float,
    default_font: str = "맑은 고딕",
    default_size: float = 10.0,
) -> tuple[float, list[LayoutLine]]:
    fmt = getattr(block, "format", None)
    sb, sa = _spacing(fmt)
    ls_ratio = _parse_ls(fmt.line_spacing if fmt and fmt.line_spacing else None)

    fn = (fmt.font_name if fmt and fmt.font_name else None) or default_font
    fs = (fmt.font_size if fmt and fmt.font_size else None) or default_size

    indent_first = float(fmt.indent_first) if fmt and fmt.indent_first else 0.0
    indent_left = float(fmt.indent_left) if fmt and fmt.indent_left else 0.0
    indent_right = float(fmt.indent_right) if fmt and fmt.indent_right else 0.0
    effective_width = container_width - indent_left - indent_right

    if isinstance(block, PageBreakBlock):
        return 0.0, []

    if isinstance(block, (HeaderBlock, FooterBlock, EndnoteBlock)):
        return 0.0, []

    if isinstance(block, EquationBlock):
        h = block.height if block.height and block.height > 0 else (40.0 if block.latex and "\\frac" in block.latex else 20.0)
        display_margin = 16.0 if block.display else 0.0
        return h + display_margin + sb + sa, []

    if isinstance(block, ImageBlock):
        pos = getattr(block, "position", None)
        if pos and pos.flow in ("front", "back") and not getattr(pos, "like_char", False):
            return 0.0, []
        h = (pos.height if pos and pos.height else None) or block.height or 0.0
        return float(h) + sb + sa, []

    if isinstance(block, HorizontalRuleBlock):
        return 12.0 + sb + sa, []

    if isinstance(block, CodeBlock):
        line_count = (block.code or "").count("\n") + 1
        return max(line_count * 14.0, 28.0) + sb + sa, []

    if isinstance(block, (HeadingBlock, ParagraphBlock)):
        inlines = getattr(block, "inlines", None) or []
        if not inlines:
            if isinstance(block, HeadingBlock) and block.text:
                inlines_text = block.text
                runs = [InlineRun(text=inlines_text, font_name=fn, font_size=fs)]
            else:
                return fs * ls_ratio + sb + sa, []
        else:
            runs = inlines_to_runs(inlines, default_font=fn, default_size=fs)

        if not runs:
            return fs * ls_ratio + sb + sa, []

        lines = break_into_lines(runs, effective_width, ls_ratio, indent_first)
        total_h = sum(line.height for line in lines)
        return total_h + sb + sa, lines

    if isinstance(block, QuoteBlock):
        total = 16.0
        for cb in (block.content or []):
            h, _ = measure_block_height(cb, effective_width - 20.0, fn, fs)
            total += h
        return total + sb + sa, []

    if isinstance(block, ListBlock):
        total = 0.0
        for item in (block.items or []):
            item_inlines = getattr(item, "inlines", None) or []
            if item_inlines:
                runs = inlines_to_runs(item_inlines, fn, fs)
                lines = break_into_lines(runs, effective_width - 20.0, ls_ratio)
                total += sum(l.height for l in lines)
            else:
                total += fs * ls_ratio
            for child in (getattr(item, "children", None) or []):
                child_inlines = getattr(child, "inlines", None) or []
                if child_inlines:
                    runs = inlines_to_runs(child_inlines, fn, fs)
                    lines = break_into_lines(runs, effective_width - 40.0, ls_ratio)
                    total += sum(l.height for l in lines)
                else:
                    total += fs * ls_ratio
        return total + sb + sa, []

    if isinstance(block, TableBlock):
        total = 0.0
        for row in (block.rows or []):
            row_h = 0.0
            for cell in row.cells:
                if cell.height and cell.height > 0:
                    row_h = max(row_h, float(cell.height) / max(cell.row_span, 1))
                elif cell.content:
                    cell_w = float(cell.width) if cell.width else (effective_width / max(len(row.cells), 1))
                    content_h_val = sum(
                        measure_block_height(cb, max(cell_w - 10.0, 20.0), fn, fs)[0]
                        for cb in cell.content
                    )
                    row_h = max(row_h, content_h_val)
                else:
                    row_h = max(row_h, fs * ls_ratio)
            total += row_h
        return total + sb + sa, []

    if isinstance(block, (TextBoxBlock, DrawingBlock)):
        pos = getattr(block, "position", None)
        if pos and pos.flow in ("front", "back") and not getattr(pos, "like_char", False):
            return 0.0, []
        h = (pos.height if pos and pos.height else None) or getattr(block, "height", None) or 0.0
        return float(h) + sb + sa, []

    return 20.0 + sb + sa, []


def split_into_pages(
    blocks: list[Block],
    page_width: float,
    page_height: float,
    margin_top: float,
    margin_bottom: float,
    margin_left: float,
    margin_right: float,
    default_font: str = "맑은 고딕",
    default_size: float = 10.0,
) -> list[LayoutPage]:
    content_w = page_width - margin_left - margin_right
    content_h = page_height - margin_top - margin_bottom

    body_blocks = [b for b in blocks if not isinstance(b, (HeaderBlock, FooterBlock, EndnoteBlock))]

    if not body_blocks:
        return [LayoutPage(
            page_index=0, width=page_width, height=page_height,
            margin_top=margin_top, margin_bottom=margin_bottom,
            margin_left=margin_left, margin_right=margin_right,
        )]

    pages: list[LayoutPage] = []
    current_page = LayoutPage(
        page_index=0, width=page_width, height=page_height,
        margin_top=margin_top, margin_bottom=margin_bottom,
        margin_left=margin_left, margin_right=margin_right,
    )
    cursor_y = 0.0

    for block in body_blocks:
        if isinstance(block, PageBreakBlock):
            if current_page.blocks:
                pages.append(current_page)
                current_page = LayoutPage(
                    page_index=len(pages), width=page_width, height=page_height,
                    margin_top=margin_top, margin_bottom=margin_bottom,
                    margin_left=margin_left, margin_right=margin_right,
                )
                cursor_y = 0.0
            continue

        fmt = getattr(block, "format", None)
        if fmt and getattr(fmt, "page_break_before", False):
            if current_page.blocks:
                pages.append(current_page)
                current_page = LayoutPage(
                    page_index=len(pages), width=page_width, height=page_height,
                    margin_top=margin_top, margin_bottom=margin_bottom,
                    margin_left=margin_left, margin_right=margin_right,
                )
                cursor_y = 0.0

        h, lines = measure_block_height(block, content_w, default_font, default_size)

        if cursor_y > 0 and cursor_y + h > content_h:
            if cursor_y >= content_h * 0.15:
                pages.append(current_page)
                current_page = LayoutPage(
                    page_index=len(pages), width=page_width, height=page_height,
                    margin_top=margin_top, margin_bottom=margin_bottom,
                    margin_left=margin_left, margin_right=margin_right,
                )
                cursor_y = 0.0

        layout_block = LayoutBlock(
            block_id=getattr(block, "id", ""),
            block_type=getattr(block, "type", "unknown"),
            x=margin_left,
            y=margin_top + cursor_y,
            width=content_w,
            height=h,
            lines=lines,
            page=current_page.page_index,
        )
        current_page.blocks.append(layout_block)
        cursor_y += h

    if current_page.blocks:
        pages.append(current_page)

    return pages
