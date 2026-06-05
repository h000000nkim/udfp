"""Complete HTML renderer — renders any UdfDocument to semantic, styled HTML5.

Supports all 22 block types, 8 inline types, and full CSS mapping for
TextInline (27 fields), BlockFormat (31 fields), and CellFormat (13 fields).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from udf.core.schema import UdfDocument
from udf.schema.blocks import (
    Block,
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
    HeaderBlock,
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
    TextArtBlock,
    TextBoxBlock,
    UnknownBlock,
)
from udf.renderers.font_map import lookup as _font_lookup
from udf.schema.formats import BlockFormat, CellFormat, PositionInfo
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
from udf.schema.types import Ratio

import re as _re

_SERIF_FONTS = ("바탕", "Batang", "명조", "Myungjo", "신명조", "HYSMyeongJo", "궁서", "Gungsuh")
_MONO_FONTS = ("고정폭", "Courier", "Consolas", "D2Coding", "나눔고딕코딩")

_HANGUL_SYLLABLES = "가나다라마바사아자차카타파하"


class _NumberingState:
    def __init__(self, patterns: list[str | None]) -> None:
        self.patterns = patterns
        self.counters = [0] * 7

    def advance(self, level: int) -> str | None:
        idx = level - 1
        if idx < 0 or idx >= len(self.patterns) or not self.patterns[idx]:
            return None
        self.counters[idx] += 1
        for j in range(idx + 1, 7):
            self.counters[j] = 0
        return self._apply_pattern(self.patterns[idx])

    def _apply_pattern(self, pattern: str) -> str:
        result = pattern
        for lvl in range(7, 0, -1):
            token = f"^{lvl}"
            if token in result:
                result = result.replace(token, self._format_counter(lvl - 1))
        return result

    def _format_counter(self, idx: int) -> str:
        val = self.counters[idx]
        if val <= 0:
            return ""
        if idx == 0:
            return str(val)
        if idx == 1 and val <= len(_HANGUL_SYLLABLES):
            return _HANGUL_SYLLABLES[val - 1]
        if idx == 2:
            return f"({val})"
        return str(val)


# ---------------------------------------------------------------------------
# Page layout helpers
# ---------------------------------------------------------------------------


def _extract_page_dims(doc: UdfDocument) -> tuple[float, float, float, float, float, float]:
    pw, ph = 595.0, 842.0
    mt, mb, ml, mr = 57.0, 43.0, 57.0, 57.0
    if doc.metadata and doc.metadata.sections:
        sec = doc.metadata.sections[0]
        try:
            if sec.page_width:
                pw = _to_float(sec.page_width)
            if sec.page_height:
                ph = _to_float(sec.page_height)
            if sec.margins:
                mt = _to_float(sec.margins.top)
                mb = _to_float(sec.margins.bottom)
                ml = _to_float(sec.margins.left)
                mr = _to_float(sec.margins.right)
        except (ValueError, AttributeError):
            pass
    return pw, ph, mt, mb, ml, mr


def _to_float(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return float(v.replace("pt", "").replace("mm", "").replace("%", "").strip())
    if hasattr(v, "percent"):
        return float(v.percent)
    return 0.0


def _parse_spacing_pt(val: Any) -> float:
    if not val:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if hasattr(val, "percent"):
        return float(val.percent)
    if not isinstance(val, str):
        return 0.0
    v = val.strip()
    try:
        if v.endswith("mm"):
            return float(v[:-2]) * 2.8346
        if v.endswith("cm"):
            return float(v[:-2]) * 28.346
        if v.endswith("pt"):
            return float(v[:-2])
    except ValueError:
        pass
    return 0.0


def _build_pls_line_counts(doc: UdfDocument) -> dict[str, int]:
    """Extract exact line counts from PLS data for paragraph blocks."""
    import base64

    if not doc.verbatim or not doc.verbatim.blocks:
        return {}
    line_counts: dict[str, int] = {}
    vblocks = doc.verbatim.blocks
    for block in doc.blocks:
        vref = getattr(block, "verbatim_ref", None)
        if not vref or vref not in vblocks:
            continue
        vb = vblocks[vref]
        decoded = vb.decoded if hasattr(vb, "decoded") and vb.decoded else None
        if not decoded or not isinstance(decoded, dict):
            continue
        pls_b64 = decoded.get("pls_bytes")
        if not pls_b64:
            continue
        try:
            pls_data = base64.b64decode(pls_b64)
        except Exception:
            continue
        if len(pls_data) < 24:
            continue
        entry_size = 36
        for esz in (36, 32, 28, 24):
            if len(pls_data) % esz == 0:
                entry_size = esz
                break
        n_lines = len(pls_data) // entry_size
        if n_lines > 0:
            line_counts[block.id] = n_lines
    return line_counts


def _estimate_block_height(
    b: Block, cw: float, pls_map: dict[str, int],
) -> float:
    fmt = getattr(b, "format", None)
    spacing = 0.0
    if fmt:
        spacing += _parse_spacing_pt(getattr(fmt, "space_before", None))
        spacing += _parse_spacing_pt(getattr(fmt, "space_after", None))

    if isinstance(b, TableBlock):
        total = 0.0
        for row in (b.rows or []):
            max_h = 0.0
            for cell in row.cells:
                ch_spec = (cell.height / max(cell.row_span, 1)) if (cell.height and cell.height > 0) else 0.0
                ch_content = (sum(
                    _estimate_block_height(cb, cw, pls_map) for cb in cell.content
                ) if cell.content else 16.0)
                max_h = max(max_h, ch_spec, ch_content)
            pad = 6.0 if max_h < 20.0 else 0.0
            total += max(max_h, 16.0) + pad
        return max(total, 16.0)

    if isinstance(b, HeadingBlock):
        fs = 10.0
        if b.inlines:
            for il in b.inlines:
                if hasattr(il, "font_size") and il.font_size:
                    fs = _to_float(il.font_size)
                    break
        return fs * 2.0 + spacing

    if isinstance(b, ParagraphBlock):
        if not b.inlines:
            return 16.0 + spacing
        text = "".join(il.text for il in b.inlines if hasattr(il, "text"))
        if not text.strip() and not any(isinstance(il, (ImageInline, EquationInline)) for il in b.inlines):
            return 16.0 + spacing
        fs = 10.0
        has_cjk = any(ord(c) > 0x2E80 for c in text[:100])
        max_inline_h = 0.0
        for il in b.inlines:
            if hasattr(il, "font_size") and il.font_size:
                fs = _to_float(il.font_size)
                break
        for il in b.inlines:
            if isinstance(il, ImageInline):
                ih = _to_float(il.height) if il.height else 0.0
                max_inline_h = max(max_inline_h, ih)
            elif isinstance(il, EquationInline):
                expr = il.latex or getattr(il, "hwp_script", "") or ""
                has_frac = any(k in expr for k in ("\\frac", "\\int", "\\sum", "over"))
                max_inline_h = max(max_inline_h, 60.0 if has_frac else 30.0)
        ls = 1.6
        if fmt and fmt.line_spacing:
            try:
                ls = _parse_line_spacing(fmt.line_spacing)
            except (ValueError, TypeError):
                pass
        char_width_factor = 1.2 if has_cjk else 0.55
        chars_per_line = max(10, cw / (fs * char_width_factor))
        heur_lines = max(1, len(text) / chars_per_line)
        pls_n = pls_map.get(b.id, 0)
        if pls_n > 0 and heur_lines >= 2.0:
            lines = max(heur_lines, float(pls_n))
        else:
            lines = heur_lines
        line_height = fs * ls
        text_h = lines * line_height
        return max(text_h, max_inline_h) + spacing

    if isinstance(b, ImageBlock):
        if b.position and not getattr(b.position, "like_char", False):
            flow = getattr(b.position, "flow", None)
            if flow in ("front", "back"):
                return 0.0
        if b.position and b.position.height:
            return b.position.height + spacing
        if b.height:
            return b.height + spacing
        return 200.0 + spacing

    if isinstance(b, (DrawingBlock, TextBoxBlock)):
        if b.position and not getattr(b.position, "like_char", False):
            flow = getattr(b.position, "flow", None)
            if flow in ("front", "back"):
                return 0.0
        if b.position and b.position.height:
            return b.position.height + spacing
        return 40.0 + spacing

    if isinstance(b, PageBreakBlock):
        return 0.0

    if isinstance(b, EquationBlock):
        expr = b.latex or b.hwp_script or ""
        has_frac = any(k in expr for k in ("\\frac", "\\int", "\\sum", "\\prod", "over"))
        return (60.0 if has_frac else 30.0) + spacing

    if isinstance(b, CodeBlock):
        lines = (b.code or "").count("\n") + 1
        return max(lines * 16.0, 32.0) + spacing

    if isinstance(b, QuoteBlock):
        inner = sum(_estimate_block_height(cb, cw, pls_map) for cb in (b.content or []))
        return max(inner, 20.0) + 16.0 + spacing

    if isinstance(b, (ListBlock,)):
        item_h = sum(20.0 for _ in (b.items or []))
        return max(item_h, 20.0) + spacing

    if isinstance(b, HorizontalRuleBlock):
        return 24.0 + spacing

    return 20.0 + spacing


def _split_table_across_pages(
    table: TableBlock, remaining: float, page_h: float, cw: float,
    pls_map: dict[str, int],
) -> list[TableBlock]:
    if not table.rows or len(table.rows) <= 1:
        return [table]
    from udf.schema.blocks import TableRow

    n_rows = len(table.rows)
    row_heights: list[float] = []
    for row in table.rows:
        max_h = 0.0
        for cell in row.cells:
            ch_spec = (cell.height / max(cell.row_span, 1)) if (cell.height and cell.height > 0) else 0.0
            ch_content = (sum(
                _estimate_block_height(cb, cw, pls_map) for cb in cell.content
            ) if cell.content else 16.0)
            max_h = max(max_h, ch_spec, ch_content)
        pad = 6.0 if max_h < 20.0 else 0.0
        row_heights.append(max(max_h, 16.0) + pad)

    rowspan_end = [0] * n_rows
    for ri, row in enumerate(table.rows):
        for cell in row.cells:
            if cell.row_span > 1:
                span_end = ri + cell.row_span - 1
                for k in range(ri, min(span_end + 1, n_rows)):
                    rowspan_end[k] = max(rowspan_end[k], span_end)

    def _can_split_before(ri: int) -> bool:
        if ri <= 0:
            return False
        if rowspan_end[ri - 1] < ri:
            return True
        if ri >= 3 and all(rowspan_end[k] >= ri for k in range(max(0, ri - 3), ri)):
            return True
        return False

    parts: list[TableBlock] = []
    current_rows: list[TableRow] = []
    cursor = 0.0

    for ri, row in enumerate(table.rows):
        rh = row_heights[ri]
        limit = remaining if not parts else page_h
        if cursor > 0 and cursor + rh > limit and _can_split_before(ri):
            orphan_h = sum(row_heights[r] for r in range(ri - len(current_rows), ri)) if current_rows else 0
            if rh > page_h and parts and current_rows and orphan_h < page_h * 0.10:
                parts[-1] = TableBlock(
                    type="table", id=table.id,
                    rows=list(parts[-1].rows) + current_rows,
                    caption=parts[-1].caption,
                )
            elif current_rows:
                parts.append(TableBlock(
                    type="table", id=table.id, rows=current_rows,
                    caption=table.caption if not parts else None,
                ))
            current_rows = []
            cursor = 0.0
        current_rows.append(row)
        cursor += rh

    if current_rows:
        parts.append(TableBlock(
            type="table", id=table.id, rows=current_rows,
        ))
    if len(parts) > 1:
        for i, part in enumerate(parts):
            part._split_source_id = table.id  # type: ignore[attr-defined]
            part._split_index = i  # type: ignore[attr-defined]
    return parts if parts else [table]


def _reassign_positioned_blocks(
    pages: list[list[Block]], page_height: float, margin_top: float,
) -> list[list[Block]]:
    """Adjust y coordinates for absolutely-positioned blocks within their page.

    Objects with vrelto=paper/page have y relative to their anchor page, not
    document-absolute. They stay on the page assigned by _split_into_pages
    (which tracks their anchor paragraph's flow position).

    Only objects with y > page_height are reassigned — this handles rare cases
    where the y value exceeds a single page height.
    """
    if len(pages) <= 1:
        return pages

    positioned: list[tuple[Block, int, int]] = []
    new_pages: list[list[Block]] = [[] for _ in pages]

    for pi, page in enumerate(pages):
        for b in page:
            pos = getattr(b, "position", None)
            if (pos and not getattr(pos, "like_char", False)
                    and pos.y is not None
                    and getattr(pos, "vrelto", None) in ("paper", "page", None)):
                if pos.y > page_height and page_height > 0:
                    target_page = int(pos.y / page_height)
                    target_page = max(0, min(target_page, len(pages) - 1))
                    page_y = pos.y - target_page * page_height
                    adjusted = pos.model_copy(update={"y": page_y})
                    b_copy = b.model_copy(update={"position": adjusted})
                    positioned.append((b_copy, target_page, pi))
                else:
                    new_pages[pi].append(b)
            else:
                new_pages[pi].append(b)

    for b, target, _orig in positioned:
        new_pages[target].append(b)

    return [p for p in new_pages if p] or [[]]



def _detect_pls_page_breaks(doc: UdfDocument) -> dict[str, int]:
    """Detect page breaks from PLS Y-coordinate resets."""
    import base64
    import struct as _st

    if not doc.verbatim or not doc.verbatim.blocks:
        return {}
    vblocks = doc.verbatim.blocks
    break_counts: dict[str, int] = {}
    prev_bottom = -1
    for block in doc.blocks:
        vref = getattr(block, "verbatim_ref", None)
        if not vref or vref not in vblocks:
            continue
        vb = vblocks[vref]
        decoded = vb.decoded if hasattr(vb, "decoded") and vb.decoded else None
        if not decoded or not isinstance(decoded, dict):
            continue
        pls_b64 = decoded.get("pls_bytes")
        if not pls_b64:
            continue
        try:
            pls_data = base64.b64decode(pls_b64)
        except Exception:
            continue
        if len(pls_data) < 24:
            continue
        entry_size = 36
        for esz in (36, 32, 28, 24):
            if len(pls_data) % esz == 0:
                entry_size = esz
                break
        n_lines = len(pls_data) // entry_size
        if n_lines == 0:
            continue
        first_y = _st.unpack_from("<I", pls_data, 4)[0]
        last_y = _st.unpack_from("<I", pls_data, (n_lines - 1) * entry_size + 4)[0]
        last_h = _st.unpack_from("<I", pls_data, (n_lines - 1) * entry_size + 8)[0]
        breaks = 0
        if first_y < prev_bottom and prev_bottom > 0:
            drop = prev_bottom - first_y
            if drop > 10000:
                breaks += 1
        if breaks > 0:
            break_counts[block.id] = breaks
        prev_bottom = last_y + last_h
    return break_counts

def _split_into_pages(
    blocks: list[Block], content_h: float, cw: float,
    pls_map: dict[str, int],
    pls_page_breaks: dict[str, int] | None = None,
) -> list[list[Block]]:
    if not blocks or content_h <= 0:
        return [blocks] if blocks else []

    safe_h = content_h

    pages: list[list[Block]] = [[]]
    cursor = 0.0

    for b in blocks:
        if isinstance(b, PageBreakBlock):
            if pages[-1]:
                pages.append([])
                cursor = 0.0
            continue

        pls_broke = False
        if pls_page_breaks and b.id in pls_page_breaks:
            n_breaks = pls_page_breaks[b.id]
            for _ in range(n_breaks):
                if pages[-1] and cursor > safe_h * 0.8:
                    pages.append([])
                    cursor = 0.0
                    pls_broke = True

        h = _estimate_block_height(b, cw, pls_map)

        _tbl_lc = getattr(b, "position", None) and getattr(b.position, "like_char", False)
        if isinstance(b, TableBlock) and len(b.rows) > 1 and cursor + h > safe_h and not _tbl_lc:
            remaining = safe_h - cursor
            parts = _split_table_across_pages(b, remaining, safe_h, cw, pls_map)
            if len(parts) > 1:
                first_part_h = _estimate_block_height(parts[0], cw, pls_map)
                if cursor > 0 and cursor + first_part_h > safe_h and cursor < safe_h * 0.2:
                    prev_blocks = pages[-1][:]
                    pages[-1] = []
                    pages.append(prev_blocks)
                    cursor = sum(_estimate_block_height(pb, cw, pls_map) for pb in prev_blocks)
                    remaining = safe_h - cursor
                    parts = _split_table_across_pages(b, remaining, safe_h, cw, pls_map)
                for j, part in enumerate(parts):
                    part_h = _estimate_block_height(part, cw, pls_map)
                    if j > 0 or (cursor > 0 and cursor + part_h > safe_h):
                        pages.append([])
                        cursor = 0.0
                    pages[-1].append(part)
                    cursor += part_h
                continue

        is_like_char = getattr(b, "position", None) and getattr(b.position, "like_char", False)
        if cursor > 0 and cursor + h > safe_h and not pls_broke:
            skip = is_like_char
            if cursor >= safe_h * 0.15 and not skip:
                pages.append([])
                cursor = 0.0

        pages[-1].append(b)
        cursor += h

    result = [p for p in pages if p]
    if len(result) > 1:
        last_h = sum(_estimate_block_height(b, cw, pls_map) for b in result[-1])
        if last_h < content_h * 0.03:
            result[-2].extend(result[-1])
            result.pop()
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_html(
    doc: UdfDocument,
    *,
    mode: str | None = None,
    image_dir: str = "images",
    embed_images: bool = True,
    embed_ids: bool = False,
    title: str = "",
) -> str:
    """Render a UdfDocument to a complete standalone HTML5 document.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    mode : str or None
        ``"paginated"`` for page-layout output, ``"flow"`` for continuous
        layout.  ``None`` auto-detects from *doc.source_format*.
    image_dir : str
        Directory path for ``bindata:`` image references (when
        *embed_images* is False).
    embed_images : bool
        Embed images as base64 data URIs.
    embed_ids : bool
        Emit ``data-bid`` attributes for roundtrip block-ID tracking.
    title : str
        Explicit document title. Falls back to metadata title.

    Returns
    -------
    str
        Complete HTML5 document string.
    """
    bindata = (doc.verbatim.bindata_streams if doc.verbatim else {}) or {}

    numbering_state: _NumberingState | None = None
    if doc.verbatim and doc.verbatim.global_resources:
        ndef = doc.verbatim.global_resources.numberings.get("0")
        if ndef and ndef.levels:
            patterns = [lvl.prefix for lvl in ndef.levels]
            if any(p for p in patterns):
                headings_have_inline_num = any(
                    _re.match(r"^\d|^[가-힣]\s*\.", "".join(
                        il.text for il in b.inlines if hasattr(il, "text")
                    ).strip())
                    for b in doc.blocks
                    if b.type == "heading"
                    and hasattr(b, "inlines") and b.inlines
                )
                if not headings_have_inline_num:
                    numbering_state = _NumberingState(patterns)

    ctx = _Ctx(
        embed_ids=embed_ids,
        embed_images=embed_images,
        image_dir=image_dir,
        bindata=bindata,
        numbering=numbering_state,
    )

    doc_title = title or _meta_title(doc) or "Document"
    lang = (doc.metadata.language if doc.metadata and doc.metadata.language else None)
    if not lang:
        fmt = getattr(doc, "source_format", None)
        lang = "ko" if fmt in ("hwp", "hwpx") else "en"

    if mode is None:
        fmt = getattr(doc, "source_format", None)
        has_page_meta = (doc.metadata and doc.metadata.sections
                         and doc.metadata.sections[0].page_height)
        use_pages = fmt in ("hwp", "hwpx", "pdf") and has_page_meta
    else:
        use_pages = mode == "paginated"

    endnotes: list[EndnoteBlock] = []
    headers: list[HeaderBlock] = []
    footers: list[FooterBlock] = []
    body_blocks: list[Block] = []
    for b in doc.blocks:
        if isinstance(b, EndnoteBlock):
            endnotes.append(b)
        elif isinstance(b, HeaderBlock):
            headers.append(b)
        elif isinstance(b, FooterBlock):
            footers.append(b)
        else:
            body_blocks.append(b)

    if use_pages:
        pw, ph, mt, mb, ml, mr = _extract_page_dims(doc)
        ctx.page_margins = (mt, mr, mb, ml)
        ctx.paginated = True
        cw = pw - ml - mr
        real_content_h = ph - mt - mb
        content_h = real_content_h
        _col_count = 1
        if doc.metadata and doc.metadata.sections:
            _sec0 = doc.metadata.sections[0]
            _col = getattr(_sec0, "columns", None)
            if _col and _col.count > 1:
                _col_count = _col.count
        pls_map: dict[str, int] = _build_pls_line_counts(doc) if _col_count == 1 else {}
        _pls_pb: dict[str, int] = _detect_pls_page_breaks(doc) if _col_count == 1 else {}
        effective_h = content_h
        pages = _split_into_pages(body_blocks, effective_h, cw, pls_map, _pls_pb)
        pages = _reassign_positioned_blocks(pages, ph, mt)

        def _pick_hf(hf_list, page_idx):
            for hf in hf_list:
                at = getattr(hf, "apply_to", "all") or "all"
                if at == "all":
                    return hf
                if at == "first" and page_idx == 0:
                    return hf
                if at == "odd" and page_idx % 2 == 0:
                    return hf
                if at == "even" and page_idx % 2 == 1:
                    return hf
            return hf_list[0] if hf_list else None

        all_headers = headers
        all_footers = footers

        def _px(pt: float) -> str:
            return f"{pt * 1.333:.2f}"

        col_css = ""
        sec_bg_css = ""
        if doc.metadata and doc.metadata.sections:
            sec0 = doc.metadata.sections[0]
            col = sec0.columns
            if col and col.count > 1:
                col_css = f";column-count:{col.count}"
                if col.gap:
                    col_css += f";column-gap:{_px(col.gap)}px"
            bg = getattr(sec0, "background_color", None)
            if bg:
                sec_bg_css = f";background-color:{bg}"

        parts: list[str] = []
        for page_idx, page_blocks in enumerate(pages):
            parts.append(
                f'<section class="page" style="'
                f"width:{_px(pw)}px;"
                f"height:{_px(ph)}px;"
                f"padding:{_px(mt)}px {_px(mr)}px {_px(mb)}px {_px(ml)}px"
                f"{sec_bg_css}"
                f'">'
            )
            hdr = _pick_hf(all_headers, page_idx)
            if hdr:
                parts.append(f'<div class="page-header">{_render_blocks(hdr.content, ctx)}</div>')
            positioned_parts: list[str] = []
            flow_parts: list[str] = []
            anchor_y = 0.0
            for block in page_blocks:
                pos = getattr(block, "position", None)
                if pos and pos.flow in ("front", "back") and not getattr(pos, "like_char", False):
                    if pos.vrelto == "paper":
                        adj_y = pos.y or 0.0
                        adj_x = pos.x or 0.0
                    else:
                        adj_y = (pos.y or 0.0) + anchor_y + mt
                        adj_x = (pos.x or 0.0) + ml
                    old_pos = block.position
                    block = block.model_copy(update={
                        "position": old_pos.model_copy(update={"x": adj_x, "y": adj_y, "hrelto": "paper", "vrelto": "paper"})
                    })
                    html = _render_block(block, ctx)
                    if html:
                        positioned_parts.append(html)
                else:
                    h = _estimate_block_height(block, cw, pls_map)
                    anchor_y += h
                    html = _render_block(block, ctx)
                    if html:
                        flow_parts.append(html)
            parts.append(
                f'<div class="page-flow" style="max-height:{_px(content_h)}px;overflow:hidden{col_css}">'
            )
            parts.extend(flow_parts)
            parts.append("</div>")
            parts.extend(positioned_parts)
            ftr = _pick_hf(all_footers, page_idx)
            if ftr:
                parts.append(f'<div class="page-footer">{_render_blocks(ftr.content, ctx)}</div>')
            parts.append("</section>")

        if endnotes:
            parts.append(
                f'<section class="page" style="'
                f"width:{_px(pw)}px;"
                f"min-height:{_px(ph)}px;"
                f"padding:{_px(mt)}px {_px(mr)}px {_px(mb)}px {_px(ml)}px"
                f'">'
            )
            parts.append('<div class="endnotes" role="doc-endnotes"><hr>')
            for en in endnotes:
                bid = _bid(en.id, ctx)
                parts.append(f'<aside class="endnote" id="en-{_esc(en.ref)}"{bid}>')
                parts.append(_render_blocks(en.content, ctx))
                parts.append("</aside>")
            parts.append("</div></section>")

        body = "\n".join(parts)
        return _TEMPLATE_PAGINATED.format(
            title=_esc(doc_title), lang=lang, body=body,
            meta_tags=_meta_tags(doc),
        )

    # --- flow mode ---
    pw_f, _ph_f, mt_f, _mb_f, ml_f, mr_f = _extract_page_dims(doc)
    ctx.page_margins = (mt_f, mr_f, _mb_f, ml_f)
    parts_f: list[str] = []

    if headers:
        parts_f.append('<header class="doc-header" role="banner">')
        for h in headers:
            parts_f.append(_render_blocks(h.content, ctx))
        parts_f.append("</header>")

    for block in body_blocks:
        html = _render_block(block, ctx)
        if html:
            parts_f.append(html)

    if endnotes:
        parts_f.append('<section class="endnotes" role="doc-endnotes">')
        parts_f.append("<hr>")
        for en in endnotes:
            bid = _bid(en.id, ctx)
            parts_f.append(f'<aside class="endnote" id="en-{_esc(en.ref)}"{bid}>')
            parts_f.append(_render_blocks(en.content, ctx))
            parts_f.append("</aside>")
        parts_f.append("</section>")

    if footers:
        parts_f.append('<footer class="doc-footer" role="contentinfo">')
        for f in footers:
            parts_f.append(_render_blocks(f.content, ctx))
        parts_f.append("</footer>")

    body = "\n".join(parts_f)
    return _TEMPLATE.format(title=_esc(doc_title), lang=lang, body=body, meta_tags=_meta_tags(doc))


# ---------------------------------------------------------------------------
# Internal context
# ---------------------------------------------------------------------------


class _Ctx:
    __slots__ = ("embed_ids", "embed_images", "image_dir", "bindata",
                 "numbering", "page_margins", "paginated")

    def __init__(
        self,
        embed_ids: bool,
        embed_images: bool,
        image_dir: str,
        bindata: dict[str, str],
        numbering: _NumberingState | None = None,
        page_margins: tuple[float, float, float, float] | None = None,
        paginated: bool = False,
    ) -> None:
        self.embed_ids = embed_ids
        self.embed_images = embed_images
        self.image_dir = image_dir
        self.bindata = bindata
        self.numbering = numbering
        self.page_margins = page_margins
        self.paginated = paginated


# ---------------------------------------------------------------------------
# Position helpers
# ---------------------------------------------------------------------------


_MAX_COORD_PT = 5000.0


def _like_char_align_wrap(html: str, pos: PositionInfo | None) -> str:
    if not pos or not pos.like_char or not pos.halign:
        return html
    align = pos.halign
    if align in ("inside", "outside"):
        align = "left"
    if align == "left":
        return html
    return f'<div style="text-align:{align}">{html}</div>'


@dataclass
class PositionStrategy:
    mode: str  # "inline" | "block" | "float" | "anchored"
    wrapper_style: str | None = None
    element_parts: list[str] = field(default_factory=list)
    use_span: bool = False


def _apply_size_extras(
    parts: list[str], pos: PositionInfo,
    page_margins: tuple[float, float, float, float] | None,
) -> None:
    w = pos.width
    h = pos.height
    if (w is not None and page_margins
            and (pos.restrict_in_page or pos.hrelto == "paper"
                 or pos.flow == "back")):
        page_pw = 595.0
        page_cw = page_pw - page_margins[1] - page_margins[3]
        limit = page_pw if pos.hrelto == "paper" else page_cw
        if w > limit:
            if h is not None and w > 0:
                h = h * (limit / w)
            w = limit
    if w is not None:
        parts.append(f"width:{w}pt")
    if h is not None:
        parts.append(f"height:{h}pt")
    if pos.rotation:
        parts.append(f"transform:rotate({pos.rotation}deg)")
    if pos.opacity is not None and pos.opacity < 1.0:
        parts.append(f"opacity:{pos.opacity}")


def _apply_non_float_margins(parts: list[str], pos: PositionInfo) -> None:
    if pos.margin_top is not None or pos.margin_right is not None:
        mt = f"{pos.margin_top}pt" if pos.margin_top else "0"
        mr = f"{pos.margin_right}pt" if pos.margin_right else "0"
        mb = f"{pos.margin_bottom}pt" if pos.margin_bottom else "0"
        ml = f"{pos.margin_left}pt" if pos.margin_left else "0"
        parts.append(f"margin:{mt} {mr} {mb} {ml}")


def _position_strategy(
    pos: PositionInfo | None,
    page_margins: tuple[float, float, float, float] | None = None,
    paginated: bool = False,
) -> PositionStrategy:
    if not pos:
        return PositionStrategy(mode="block")

    parts: list[str] = []

    if pos.like_char:
        parts.append("display:inline-block")
        va = pos.valign or "middle"
        parts.append(f"vertical-align:{va}")
        _apply_size_extras(parts, pos, page_margins)
        _apply_non_float_margins(parts, pos)
        return PositionStrategy(mode="inline", element_parts=parts, use_span=True)

    if pos.flow in ("float", "tight", "through"):
        align = pos.halign or "left"
        if align in ("right", "outside"):
            parts.append("float:right")
        else:
            parts.append("float:left")
        side = pos.text_side or "both"
        if side == "left":
            parts.append("clear:right")
        elif side == "right":
            parts.append("clear:left")
        mt = f"{pos.margin_top}pt" if pos.margin_top else "4pt"
        mr = f"{pos.margin_right}pt" if pos.margin_right else "8pt"
        mb = f"{pos.margin_bottom}pt" if pos.margin_bottom else "4pt"
        ml = f"{pos.margin_left}pt" if pos.margin_left else "8pt"
        parts.append(f"margin:{mt} {mr} {mb} {ml}")
        _apply_size_extras(parts, pos, page_margins)
        return PositionStrategy(mode="float", element_parts=parts)

    is_block_flow = (
        pos.flow == "block"
        and pos.vrelto == "paragraph"
        and (pos.x is None or pos.x == 0)
        and (pos.y is None or pos.y == 0)
    )
    if is_block_flow:
        halign = pos.halign
        if halign == "center":
            parts.append("margin-left:auto")
            parts.append("margin-right:auto")
        elif halign == "right":
            parts.append("margin-left:auto")
            parts.append("margin-right:0")
        _apply_size_extras(parts, pos, page_margins)
        _apply_non_float_margins(parts, pos)
        return PositionStrategy(mode="block", element_parts=parts)

    # anchored: back/front, paper-relative, or any object with coordinates
    if pos.content_x is not None:
        x = pos.content_x
    else:
        x = pos.x
    if pos.content_y is not None:
        y = pos.content_y
    else:
        y = pos.y
    if x is not None and abs(x) > _MAX_COORD_PT:
        x = None
    if y is not None and abs(y) > _MAX_COORD_PT:
        y = None

    if not paginated and pos.content_x is None and pos.content_y is None:
        if page_margins and pos.hrelto == "paper" and x is not None:
            x -= page_margins[3]
        if page_margins and pos.vrelto == "paper" and y is not None:
            y -= page_margins[0]

    parts.append("position:absolute")
    if x is not None:
        parts.append(f"left:{x}pt")
    if y is not None:
        parts.append(f"top:{y}pt")

    z: int | None = None
    if pos.flow == "back":
        z = -1
        parts.append("pointer-events:none")
    elif pos.flow == "front":
        is_fullpage = (pos.width and pos.width > 400) or (pos.height and pos.height > 400)
        if is_fullpage:
            z = -1
            parts.append("pointer-events:none")
        else:
            z = 10
    elif pos.z_order is not None:
        z = pos.z_order

    _apply_size_extras(parts, pos, page_margins)

    wrapper_style: str | None = None
    if not paginated:
        wrapper_style = f"z-index:{z}" if z is not None else ""
    else:
        if z is not None:
            parts.append(f"z-index:{z}")

    return PositionStrategy(
        mode="anchored", wrapper_style=wrapper_style, element_parts=parts,
    )


# ---------------------------------------------------------------------------
# Block rendering
# ---------------------------------------------------------------------------


def _render_blocks(blocks: list[Block], ctx: _Ctx) -> str:
    parts = [_render_block(b, ctx) for b in blocks]
    return "\n".join(p for p in parts if p)


def _render_block(block: Block, ctx: _Ctx) -> str | None:
    t = block.type

    if t == "heading":
        return _render_heading(block, ctx)  # type: ignore[arg-type]
    if t == "paragraph":
        return _render_paragraph(block, ctx)  # type: ignore[arg-type]
    if t == "table":
        return _render_table(block, ctx)  # type: ignore[arg-type]
    if t == "list":
        return _render_list(block, ctx)  # type: ignore[arg-type]
    if t == "image":
        return _render_image(block, ctx)  # type: ignore[arg-type]
    if t == "code":
        return _render_code(block, ctx)  # type: ignore[arg-type]
    if t == "quote":
        return _render_quote(block, ctx)  # type: ignore[arg-type]
    if t == "horizontal_rule":
        return _render_hr(block, ctx)  # type: ignore[arg-type]
    if t == "equation":
        return _render_equation(block, ctx)  # type: ignore[arg-type]
    if t == "footnote":
        return _render_footnote(block, ctx)  # type: ignore[arg-type]
    if t == "endnote":
        return None  # collected at top level
    if t == "header":
        return None  # collected at top level
    if t == "footer":
        return None  # collected at top level
    if t == "field":
        return _render_field(block, ctx)  # type: ignore[arg-type]
    if t == "text_box":
        return _render_textbox(block, ctx)  # type: ignore[arg-type]
    if t == "drawing":
        return _render_drawing(block, ctx)  # type: ignore[arg-type]
    if t == "chart":
        return _render_chart(block, ctx)  # type: ignore[arg-type]
    if t == "text_art":
        return _render_textart(block, ctx)  # type: ignore[arg-type]
    if t == "page_break":
        return _render_pagebreak(block, ctx)  # type: ignore[arg-type]
    if t == "bookmark":
        return _render_bookmark(block, ctx)  # type: ignore[arg-type]
    if t == "comment":
        return _render_comment(block, ctx)  # type: ignore[arg-type]
    if t == "unknown":
        return _render_unknown(block, ctx)  # type: ignore[arg-type]
    return None


# -- Heading ----------------------------------------------------------------

def _render_heading(b: HeadingBlock, ctx: _Ctx) -> str:
    lvl = max(1, min(6, b.level))
    bid = _bid(b.id, ctx)
    style = _block_format_css(b.format)
    content = _render_inlines(b.inlines, ctx) if b.inlines else _esc(b.text)
    prefix = ""
    if ctx.numbering and content.strip():
        pfx = ctx.numbering.advance(lvl)
        if pfx:
            prefix = f"<strong>{_esc(pfx)}</strong> "
    return f"<h{lvl}{bid}{style}>{prefix}{content}</h{lvl}>"


def _infer_para_bg(
    inlines: list[Any] | None, fmt: BlockFormat | None,
) -> BlockFormat | None:
    if not inlines:
        return fmt
    total_len = 0
    bg_len = 0
    dominant_bg = None
    bg_counts: dict[str, int] = {}
    for il in inlines:
        t = getattr(il, "text", "") or ""
        tl = len(t)
        total_len += tl
        bg = getattr(il, "background_color", None) or getattr(il, "highlight_color", None)
        if bg and tl > 0:
            key = bg.to_hex() if hasattr(bg, "to_hex") else str(bg)
            bg_counts[key] = bg_counts.get(key, 0) + tl
            bg_len += tl
    if total_len > 0 and bg_len / total_len >= 0.4 and bg_counts:
        dominant_bg = max(bg_counts, key=bg_counts.get)  # type: ignore[arg-type]
        if fmt:
            return fmt.model_copy(update={"background_color": dominant_bg})
        return BlockFormat(background_color=dominant_bg)
    return fmt


# -- Paragraph --------------------------------------------------------------

def _render_paragraph(b: ParagraphBlock, ctx: _Ctx) -> str:
    content = _render_inlines(b.inlines, ctx)
    bid = _bid(b.id, ctx)
    fmt = b.format
    inferred_bg = False
    if not fmt or not getattr(fmt, "background_color", None):
        new_fmt = _infer_para_bg(b.inlines, fmt)
        if new_fmt is not fmt:
            fmt = new_fmt
            inferred_bg = True
    style = _block_format_css(fmt)
    if inferred_bg and fmt and getattr(fmt, "background_color", None):
        style = style.rstrip('"') + ';padding:2pt 7pt"' if style.endswith('"') else ' style="padding:2pt 7pt"'
    if not content.strip():
        return f"<p{bid}{style}>&nbsp;</p>"
    return f"<p{bid}{style}>{content}</p>"


# -- Table ------------------------------------------------------------------

def _render_table(b: TableBlock, ctx: _Ctx) -> str:
    if not b.rows:
        return ""
    bid = _bid(b.id, ctx)
    split_attr = ""
    split_src = getattr(b, "_split_source_id", None)
    if split_src is not None:
        split_idx = getattr(b, "_split_index", 0)
        split_attr = f' data-udf-split-id="{_esc_attr(split_src)}" data-udf-split-index="{split_idx}"'
    style_parts: list[str] = []
    if b.width:
        style_parts.append(f"width:{b.width}pt")
    tbl_style = f' style="{";".join(style_parts)}"' if style_parts else ""

    lines: list[str] = [f"<table{bid}{split_attr}{tbl_style}>"]
    if b.caption:
        lines.append(f"<caption>{_render_inlines(b.caption, ctx)}</caption>")

    for ri, row in enumerate(b.rows):
        lines.append("<tr>")
        for cell in row.cells:
            tag = "th" if (ri == 0 or cell.is_header) else "td"
            attrs = ""
            if cell.row_span > 1:
                attrs += f' rowspan="{cell.row_span}"'
            if cell.col_span > 1:
                attrs += f' colspan="{cell.col_span}"'
            if tag == "th":
                attrs += f' scope="{"col" if ri == 0 else "row"}"'
            cs = _cell_style_css(cell)
            cell_html = _render_blocks(cell.content, ctx)
            lines.append(f"<{tag}{attrs}{cs}>{cell_html}</{tag}>")
        lines.append("</tr>")
    lines.append("</table>")
    html = "\n".join(lines)
    return _like_char_align_wrap(html, b.position)


# -- List -------------------------------------------------------------------

def _render_list(b: ListBlock, ctx: _Ctx) -> str:
    tag = "ol" if b.ordered else "ul"
    bid = _bid(b.id, ctx)
    start = f' start="{b.start}"' if b.start and b.start != 1 else ""
    lst = getattr(b, "list_style", None)
    style = f' style="list-style-type:{lst}"' if lst else ""
    items = "\n".join(_render_list_item(it, ctx) for it in b.items)
    return f"<{tag}{bid}{start}{style}>\n{items}\n</{tag}>"


def _render_list_item(item: ListItem, ctx: _Ctx) -> str:
    text = _render_inlines(item.inlines, ctx)
    children = ""
    if item.children:
        sub = "\n".join(_render_list_item(c, ctx) for c in item.children)
        children = f"\n<ul>\n{sub}\n</ul>"
    checked = ""
    if item.checked is not None:
        chk = "checked " if item.checked else ""
        checked = f'<input type="checkbox" {chk}disabled> '
    return f"<li>{checked}{text}{children}</li>"


# -- Image ------------------------------------------------------------------

def _render_image(b: ImageBlock, ctx: _Ctx) -> str:
    src = _resolve_src(b.src, ctx)
    if not src:
        return ""
    alt = _esc_attr(b.alt or "")
    bid = _bid(b.id, ctx)
    strategy = _position_strategy(b.position, ctx.page_margins, ctx.paginated)
    fig_style_parts = list(strategy.element_parts)
    if b.position and not strategy.use_span:
        fig_style_parts.append("max-width:100%")
    fig_style = f' style="{";".join(fig_style_parts)}"' if fig_style_parts else ""
    img_style_parts: list[str] = ["max-width:100%"]
    has_pos_size = b.position and (b.position.width is not None or b.position.height is not None)
    if b.width and not has_pos_size:
        img_style_parts.append(f"width:{b.width}pt")
    if b.height and not has_pos_size:
        img_style_parts.append(f"height:{b.height}pt")
    if any(getattr(b, f"crop_{s}", None) for s in ("top", "right", "bottom", "left")):
        ct = b.crop_top or 0
        cr = b.crop_right or 0
        cb = b.crop_bottom or 0
        cl = b.crop_left or 0
        if all(v <= 100 for v in (ct, cr, cb, cl)) and any(v > 0 for v in (ct, cr, cb, cl)):
            img_style_parts.append(f"clip-path:inset({ct}% {cr}% {cb}% {cl}%)")
    if b.brightness and b.brightness != 0:
        img_style_parts.append(f"filter:brightness({100 + b.brightness}%)")
    if b.contrast and b.contrast != 0:
        c = 100 + b.contrast
        img_style_parts.append(f"filter:contrast({c}%)")
    img_style = f' style="{";".join(img_style_parts)}"'
    cap = f"<figcaption>{_render_inlines(b.caption, ctx)}</figcaption>" if b.caption else ""
    if strategy.use_span:
        html = f'<span class="inline-image"{bid}{fig_style}><img src="{_esc_attr(src)}" alt="{alt}"{img_style}>{cap}</span>'
        return _like_char_align_wrap(html, b.position)
    inner = f'<figure{bid}{fig_style}><img src="{_esc_attr(src)}" alt="{alt}"{img_style}>{cap}</figure>'
    if strategy.wrapper_style is not None:
        wrap_attr = f' style="{strategy.wrapper_style}"' if strategy.wrapper_style else ""
        return f'<div class="anchor-wrap"{wrap_attr}>{inner}</div>'
    return _like_char_align_wrap(inner, b.position)


# -- Code -------------------------------------------------------------------

def _render_code(b: CodeBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    lang_cls = f' class="language-{_esc_attr(b.language)}"' if b.language else ""
    return f"<pre{bid}><code{lang_cls}>{_esc(b.code)}</code></pre>"


# -- Quote ------------------------------------------------------------------

def _render_quote(b: QuoteBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    content = _render_blocks(b.content, ctx)
    return f"<blockquote{bid}>{content}</blockquote>"


# -- Horizontal rule --------------------------------------------------------

def _render_hr(b: HorizontalRuleBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    return f"<hr{bid}>"


# -- Equation ---------------------------------------------------------------

def _render_equation(b: EquationBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    expr = b.latex or b.hwp_script or ""
    if not expr:
        return ""
    return f'<div class="equation"{bid}>$${expr}$$</div>'


# -- Footnote ---------------------------------------------------------------

def _render_footnote(b: FootnoteBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    content = _render_blocks(b.content, ctx)
    return f'<aside class="footnote" id="fn-{_esc_attr(b.ref)}" role="doc-footnote"{bid}>{content}</aside>'


# -- Field ------------------------------------------------------------------

def _render_field(b: FieldBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    if b.inlines:
        content = _render_inlines(b.inlines, ctx)
        return f'<span class="field" data-field-type="{_esc_attr(b.field_type)}"{bid}>{content}</span>'
    val = _esc(b.value or "")
    return f'<span class="field" data-field-type="{_esc_attr(b.field_type)}"{bid}>{val}</span>'


# -- TextBox ----------------------------------------------------------------

def _render_textbox(b: TextBoxBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    strategy = _position_strategy(b.position, ctx.page_margins, ctx.paginated)
    style_parts = list(strategy.element_parts)
    has_pos_size = b.position and (b.position.width is not None or b.position.height is not None)
    if b.width and not has_pos_size:
        style_parts.append(f"width:{b.width}pt")
    if b.height and not has_pos_size:
        style_parts.append(f"height:{b.height}pt")
    if b.background_color:
        style_parts.append(f"background-color:{b.background_color}")
    if b.line_color:
        style_parts.append(f"border-color:{b.line_color}")
    if b.line_width:
        style_parts.append(f"border-width:{b.line_width}pt")
        style_parts.append("border-style:solid")
    if b.border_radius:
        style_parts.append(f"border-radius:{b.border_radius}pt")
    if b.vertical_align:
        style_parts.append(f"vertical-align:{b.vertical_align}")
    _add_padding(style_parts, b.padding_top, b.padding_right, b.padding_bottom, b.padding_left)
    style_parts.append("overflow:hidden")
    style_parts.append("box-sizing:border-box")
    style = f' style="{";".join(style_parts)}"' if style_parts else ""
    content = _render_blocks(b.content, ctx)
    if strategy.use_span:
        html = f'<span class="text-box"{bid}{style}>{content}</span>'
        return _like_char_align_wrap(html, b.position)
    inner = f'<aside class="text-box"{bid}{style}>{content}</aside>'
    if strategy.wrapper_style is not None:
        wrap_attr = f' style="{strategy.wrapper_style}"' if strategy.wrapper_style else ""
        return f'<div class="anchor-wrap"{wrap_attr}>{inner}</div>'
    return _like_char_align_wrap(inner, b.position)


# -- Drawing ----------------------------------------------------------------

def _render_drawing(b: DrawingBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    label = _esc(b.shape_type or "drawing")
    strategy = _position_strategy(b.position, ctx.page_margins, ctx.paginated)
    style_parts = list(strategy.element_parts)
    if b.background_color:
        style_parts.append(f"background-color:{b.background_color}")
    if b.line_color:
        style_parts.append(f"border-color:{b.line_color}")
    if b.line_width:
        style_parts.append(f"border-width:{b.line_width}pt")
        style_parts.append("border-style:solid")
    style = f' style="{";".join(style_parts)}"' if style_parts else ""
    svg = ""
    if b.vertices and len(b.vertices) >= 3:
        w = b.position.width if b.position and b.position.width else 100
        h = b.position.height if b.position and b.position.height else 100
        pts = " ".join(f"{v.x},{v.y}" for v in b.vertices)
        fill = b.background_color or "none"
        stroke = b.line_color or "#000"
        sw = b.line_width or 1
        svg = f'<svg viewBox="0 0 {w} {h}" style="width:{w}pt;height:{h}pt"><polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/></svg>'
    if b.content:
        inner_content = _render_blocks(b.content, ctx)
        inner = f'<div class="drawing" aria-label="{label}"{bid}{style}>{svg}{inner_content}</div>'
    elif svg:
        inner = f'<div class="drawing" aria-label="{label}"{bid}{style}>{svg}</div>'
    else:
        inner = f'<div class="drawing" aria-label="{label}"{bid}{style}>[{label}]</div>'
    if strategy.wrapper_style is not None:
        wrap_attr = f' style="{strategy.wrapper_style}"' if strategy.wrapper_style else ""
        return f'<div class="anchor-wrap"{wrap_attr}>{inner}</div>'
    return _like_char_align_wrap(inner, b.position)


# -- Chart ------------------------------------------------------------------

def _render_chart(b: ChartBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    desc = _esc(b.description or "chart")
    return f'<figure class="chart" aria-label="{desc}"{bid}><div class="chart-placeholder">[{desc}]</div></figure>'


# -- TextArt ----------------------------------------------------------------

def _render_textart(b: TextArtBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    text = _esc(b.text or "")
    return f'<div class="text-art"{bid}>{text}</div>'


# -- PageBreak --------------------------------------------------------------

def _render_pagebreak(b: PageBreakBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    return f'<div class="page-break"{bid}></div>'


# -- Bookmark ---------------------------------------------------------------

def _render_bookmark(b: BookmarkBlock, ctx: _Ctx) -> str:
    return f'<a id="bm-{_esc_attr(b.name)}" class="bookmark"></a>'


# -- Comment ----------------------------------------------------------------

def _render_comment(b: CommentBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    author = _esc(b.author or "")
    content = _render_blocks(b.content, ctx)
    return f'<aside class="comment" role="note" data-author="{author}" hidden{bid}>{content}</aside>'


# -- Unknown ----------------------------------------------------------------

def _render_unknown(b: UnknownBlock, ctx: _Ctx) -> str:
    bid = _bid(b.id, ctx)
    desc = _esc(b.description or "")
    return f'<div class="unknown" data-description="{desc}"{bid}></div>'


# ---------------------------------------------------------------------------
# Inline rendering
# ---------------------------------------------------------------------------


def _render_inlines(inlines: list[Any], ctx: _Ctx) -> str:
    parts: list[str] = []
    for il in inlines:
        t = getattr(il, "type", None)
        if t == "text":
            parts.append(_render_text_inline(il, ctx))
        elif t == "link":
            parts.append(_render_link_inline(il))
        elif t == "image_inline":
            parts.append(_render_image_inline(il, ctx))
        elif t == "footnote_ref":
            parts.append(_render_footnote_ref(il))
        elif t == "endnote_ref":
            parts.append(_render_endnote_ref(il))
        elif t == "equation_inline":
            parts.append(_render_equation_inline(il))
        elif t == "ruby":
            parts.append(_render_ruby_inline(il))
        elif t == "code_inline":
            parts.append(_render_code_inline(il))
        else:
            text = getattr(il, "text", "")
            if text:
                parts.append(_esc(text))
    return "".join(parts)


def _render_text_inline(il: TextInline, ctx: _Ctx) -> str:
    text = _esc(il.text)
    if not text:
        return ""

    style = _text_inline_css(il, ctx)
    if style:
        text = f'<span style="{style}">{text}</span>'

    if il.bold:
        text = f"<strong>{text}</strong>"
    if il.italic:
        text = f"<em>{text}</em>"
    if il.underline:
        text = f"<u>{text}</u>"
    if il.strikethrough:
        text = f"<del>{text}</del>"
    if il.superscript:
        text = f"<sup>{text}</sup>"
    if il.subscript:
        text = f"<sub>{text}</sub>"
    if il.hidden:
        text = f'<span class="hidden" style="display:none">{text}</span>'
    rev = getattr(il, "revision", None)
    if rev:
        rt = rev.revision_type
        if rt == "insert":
            text = f"<ins>{text}</ins>"
        elif rt == "delete":
            text = f"<del>{text}</del>"
    return text


def _render_link_inline(il: LinkInline) -> str:
    title = f' title="{_esc_attr(il.title)}"' if il.title else ""
    return f'<a href="{_esc_attr(il.url)}"{title}>{_esc(il.text)}</a>'


def _render_image_inline(il: ImageInline, ctx: _Ctx) -> str:
    src = _resolve_src(il.src, ctx)
    alt = _esc(il.alt or "")
    style_parts: list[str] = []
    if il.width:
        style_parts.append(f"width:{il.width}pt")
    if il.height:
        style_parts.append(f"height:{il.height}pt")
    style = f' style="{";".join(style_parts)}"' if style_parts else ""
    return f'<img src="{_esc_attr(src)}" alt="{alt}"{style}>'


def _render_footnote_ref(il: FootnoteRefInline) -> str:
    num = il.number or ""
    return f'<sup><a href="#fn-{_esc_attr(il.ref_id)}" class="footnote-ref">{num}</a></sup>'


def _render_endnote_ref(il: EndnoteRefInline) -> str:
    num = il.number or ""
    return f'<sup><a href="#en-{_esc_attr(il.ref_id)}" class="endnote-ref">{num}</a></sup>'


def _render_equation_inline(il: EquationInline) -> str:
    expr = il.latex or il.hwp_script or ""
    if not expr:
        return ""
    return f"\\({expr}\\)"


def _render_ruby_inline(il: RubyInline) -> str:
    return f"<ruby>{_esc(il.base_text)}<rp>(</rp><rt>{_esc(il.ruby_text)}</rt><rp>)</rp></ruby>"


def _render_code_inline(il: CodeInline) -> str:
    return f"<code>{_esc(il.code)}</code>"


# ---------------------------------------------------------------------------
# CSS generation — TextInline (27 fields)
# ---------------------------------------------------------------------------


def _text_inline_css(il: TextInline, ctx: _Ctx | None = None) -> str:
    """Build CSS style string from TextInline format fields.

    Semantic tags (bold/italic/underline/strikethrough/superscript/subscript/hidden)
    are handled via HTML elements, not CSS. This function handles the remaining
    visual properties.
    """
    parts: list[str] = []

    if il.color:
        parts.append(f"color:{il.color.to_hex()}")
    bg = il.highlight_color or il.background_color
    if bg:
        parts.append(f"background-color:{bg.to_hex()}")
    if il.font_name:
        fb = _font_fallback(il.font_name)
        parts.append(f"font-family:'{il.font_name}'{fb}")
        if not il.letter_spacing:
            ls_em = _font_letter_spacing(il.font_name)
            if ls_em > 0.001:
                parts.append(f"letter-spacing:{ls_em}em")
    if il.font_size:
        parts.append(f"font-size:{il.font_size}pt")
    if il.letter_spacing:
        parts.append(f"letter-spacing:{il.letter_spacing / 100}em")
    if il.char_scale:
        factor = il.char_scale.factor if isinstance(il.char_scale, Ratio) else il.char_scale / 100
        if abs(factor - 1.0) > 0.01:
            parts.append("display:inline-block")
            parts.append(f"transform:scaleX({factor:.2f})")
    if il.char_offset:
        parts.append(f"vertical-align:{il.char_offset / 100}em")
    if il.small_caps:
        parts.append("font-variant:small-caps")
    if il.all_caps:
        parts.append("text-transform:uppercase")
    if il.outline:
        parts.append("-webkit-text-stroke:1px currentColor")
        parts.append("color:transparent")
    if il.shadow:
        parts.append("text-shadow:1px 1px 2px rgba(0,0,0,0.3)")
    if il.emboss:
        parts.append("text-shadow:1px 1px 0 #fff,-1px -1px 0 #888")
    if il.engrave:
        parts.append("text-shadow:-1px -1px 0 #fff,1px 1px 0 #888")
    if il.emphasis_mark and il.emphasis_mark != "none":
        mark_map = {"dot": "dot", "circle": "circle", "comma": "'\\2018'", "under_dot": "dot"}
        em_val = mark_map.get(il.emphasis_mark, "dot")
        parts.append(f"text-emphasis:{em_val}")
    if il.rtl:
        parts.append("direction:rtl")

    deco_parts: list[str] = []
    deco_style: str | None = None
    deco_color: str | None = None
    if il.underline and il.underline_type:
        _style_map = {
            "solid": "solid", "dash": "dashed", "dashed": "dashed",
            "dotted": "dotted", "double": "double", "wavy": "wavy",
            "thick": "solid",
        }
        deco_parts.append("underline")
        deco_style = _style_map.get(il.underline_type, "solid")
    if il.underline_color:
        deco_color = il.underline_color.to_hex()
    if il.strikethrough and il.strikeout_type:
        deco_parts.append("line-through")
    if il.strikeout_color:
        deco_color = il.strikeout_color.to_hex()
    if deco_style:
        parts.append(f"text-decoration-style:{deco_style}")
    if deco_color:
        parts.append(f"text-decoration-color:{deco_color}")

    return ";".join(parts)


# ---------------------------------------------------------------------------
# CSS generation — BlockFormat (31 fields)
# ---------------------------------------------------------------------------


def _block_format_css(fmt: BlockFormat | None) -> str:
    if not fmt:
        return ""
    parts: list[str] = []

    if fmt.font_name:
        fb = _font_fallback(fmt.font_name)
        parts.append(f"font-family:'{fmt.font_name}'{fb}")
    if fmt.font_size:
        parts.append(f"font-size:{fmt.font_size}pt")
    if fmt.bold:
        parts.append("font-weight:700")
    if fmt.italic:
        parts.append("font-style:italic")
    if fmt.alignment:
        parts.append(f"text-align:{fmt.alignment}")
    if fmt.line_spacing is not None:
        lh = _parse_line_spacing(
            fmt.line_spacing, for_css=True,
            font_name=fmt.font_name, line_spacing_type=fmt.line_spacing_type,
        )
        if isinstance(lh, str):
            parts.append(f"line-height:{lh}")
        else:
            parts.append(f"line-height:{lh:.2f}")
    if fmt.space_before is not None:
        parts.append(f"margin-top:{fmt.space_before}pt")
    else:
        parts.append("margin-top:0")
    if fmt.space_after is not None:
        parts.append(f"margin-bottom:{fmt.space_after}pt")
    else:
        parts.append("margin-bottom:0")
    if fmt.indent_left:
        parts.append(f"margin-left:{fmt.indent_left}pt")
    if fmt.indent_right:
        parts.append(f"margin-right:{fmt.indent_right}pt")
    if fmt.indent_first:
        parts.append(f"text-indent:{fmt.indent_first}pt")
    if fmt.text_direction == "vertical":
        parts.append("writing-mode:vertical-rl")
    if fmt.keep_with_next:
        parts.append("page-break-after:avoid")
    if fmt.widow_orphan:
        parts.append("orphans:2")
        parts.append("widows:2")
    if fmt.page_break_before:
        parts.append("page-break-before:always")
    if fmt.background_color:
        parts.append(f"background-color:{_color_css(fmt.background_color)}")
    for side in ("top", "bottom", "left", "right"):
        val = getattr(fmt, f"border_{side}", None)
        if val:
            parts.append(f"border-{side}:{val}")
    if fmt.bidi:
        parts.append("direction:rtl")
    if fmt.column_break_before:
        parts.append("break-before:column")
    if fmt.drop_cap_lines and fmt.drop_cap_lines > 1:
        parts.append(f"initial-letter:{fmt.drop_cap_lines}")
    if fmt.tab_stops:
        " ".join(f"{ts.position}pt" for ts in fmt.tab_stops)
        parts.append("tab-size:8ch")

    if not parts:
        return ""
    return f' style="{";".join(parts)}"'


# ---------------------------------------------------------------------------
# CSS generation — CellFormat (13 fields)
# ---------------------------------------------------------------------------


def _cell_style_css(cell: TableCell) -> str:
    parts: list[str] = []
    if cell.width:
        parts.append(f"width:{cell.width:.2f}pt")
    if cell.height:
        h = cell.height / max(cell.row_span, 1)
        parts.append(f"height:{h:.2f}pt")
    fmt = cell.format
    if fmt:
        if fmt.background_color:
            parts.append(f"background-color:{_color_css(fmt.background_color)}")
        for side in ("top", "bottom", "left", "right"):
            val = getattr(fmt, f"border_{side}", None)
            if val:
                parts.append(f"border-{side}:{val}")
        _add_padding(parts, fmt.padding_top, fmt.padding_right, fmt.padding_bottom, fmt.padding_left)
        if fmt.padding and not any(getattr(fmt, f"padding_{s}", None) for s in ("top", "right", "bottom", "left")):
            parts.append(f"padding:{fmt.padding}pt")
        if fmt.vertical_align:
            parts.append(f"vertical-align:{fmt.vertical_align}")
        if fmt.text_direction == "vertical":
            parts.append("writing-mode:vertical-rl")
        if fmt.no_wrap:
            parts.append("white-space:nowrap")
    if not parts:
        return ""
    return f' style="{";".join(parts)}"'


def _cell_format_css(fmt: CellFormat | None) -> str:
    if not fmt:
        return ""
    parts: list[str] = []

    if fmt.background_color:
        parts.append(f"background-color:{_color_css(fmt.background_color)}")
    for side in ("top", "bottom", "left", "right"):
        val = getattr(fmt, f"border_{side}", None)
        if val:
            parts.append(f"border-{side}:{val}")
    _add_padding(parts, fmt.padding_top, fmt.padding_right, fmt.padding_bottom, fmt.padding_left)
    if fmt.padding and not any(getattr(fmt, f"padding_{s}", None) for s in ("top", "right", "bottom", "left")):
        parts.append(f"padding:{fmt.padding}pt")
    if fmt.vertical_align:
        parts.append(f"vertical-align:{fmt.vertical_align}")
    if fmt.text_direction == "vertical":
        parts.append("writing-mode:vertical-rl")
    if fmt.no_wrap:
        parts.append("white-space:nowrap")

    if not parts:
        return ""
    return f' style="{";".join(parts)}"'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _meta_title(doc: UdfDocument) -> str | None:
    if doc.metadata and doc.metadata.title:
        return doc.metadata.title
    return None


def _meta_tags(doc: UdfDocument) -> str:
    if not doc.metadata:
        return ""
    m = doc.metadata
    parts: list[str] = []
    author = getattr(m, "author", None)
    if author:
        parts.append(f'<meta name="author" content="{_esc_attr(str(author))}">')
    subject = getattr(m, "subject", None)
    if subject:
        parts.append(f'<meta name="description" content="{_esc_attr(str(subject))}">')
    keywords = getattr(m, "keywords", None)
    if keywords:
        kw = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
        parts.append(f'<meta name="keywords" content="{_esc_attr(kw)}">')
    created = getattr(m, "created", None) or getattr(m, "creation_date", None)
    if created:
        parts.append(f'<meta name="dcterms.created" content="{created}">')
    return "\n".join(parts)


def _color_css(c: Any) -> str:
    if hasattr(c, "to_hex"):
        return c.to_hex()
    return str(c)


def _esc(text: str) -> str:
    s = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if "  " in s:
        s = _re.sub(r"  ", " &nbsp;", s)
    return s


def _esc_attr(text: str) -> str:
    return _esc(text).replace('"', "&quot;")


def _bid(block_id: str, ctx: _Ctx) -> str:
    if ctx.embed_ids:
        return f' data-bid="{_esc_attr(block_id)}"'
    return ""


def _resolve_src(src: str, ctx: _Ctx) -> str:
    if not src:
        return ""
    if not src.startswith("bindata:"):
        return src
    name = src[len("bindata:"):]
    if ctx.embed_images and name in ctx.bindata:
        ext = name.rsplit(".", 1)[-1].lower()
        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "gif": "image/gif", "bmp": "image/bmp"}.get(ext, "image/jpeg")
        return f"data:{mime};base64,{ctx.bindata[name]}"
    return f"{ctx.image_dir}/{name}"


def _font_fallback(name: str) -> str:
    m = _font_lookup(name)
    if m.category == "western":
        return ",sans-serif"
    if m.category == "mono":
        return f",'{m.fallback}',monospace"
    if m.category == "serif":
        return f",'{m.fallback}',serif"
    return f",'{m.fallback}',sans-serif"


def _font_letter_spacing(name: str) -> float:
    return _font_lookup(name).letter_spacing_em


def _parse_line_spacing(
    ls: Any,
    *,
    for_css: bool = False,
    font_name: str | None = None,
    line_spacing_type: str | None = None,
) -> float | str:
    if for_css and line_spacing_type == "fixed" and isinstance(ls, (int, float)):
        return f"{float(ls)}pt"

    if isinstance(ls, Ratio):
        raw = ls.factor
    elif isinstance(ls, (int, float)):
        v = float(ls)
        raw = v / 100 if v > 5 else v
    else:
        raw = 1.6
    if for_css and raw > 1.0:
        from udf.renderers._font_utils import compute_css_line_height_correction
        correction = compute_css_line_height_correction(font_name or "")
        return raw * correction
    return raw


def _add_padding(
    parts: list[str],
    top: float | None,
    right: float | None,
    bottom: float | None,
    left: float | None,
) -> None:
    if top:
        parts.append(f"padding-top:{top}pt")
    if right:
        parts.append(f"padding-right:{right}pt")
    if bottom:
        parts.append(f"padding-bottom:{bottom}pt")
    if left:
        parts.append(f"padding-left:{left}pt")


# ---------------------------------------------------------------------------
# HTML templates
# ---------------------------------------------------------------------------

_TEMPLATE = """\
<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{meta_tags}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700&family=Nanum+Myeongjo:wght@400;700&family=Nanum+Gothic+Coding&family=Noto+Sans+KR:wght@400;700&family=Noto+Serif+KR:wght@400;700&display=swap" rel="stylesheet">
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    padding: 32px 16px 64px;
    background: #f0f0f0;
    font-family: 'Noto Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
    color: #1a1a1a;
    line-height: 1.7;
  }}

  article {{
    max-width: 820px;
    margin: 0 auto;
    background: #fff;
    padding: 56px 72px;
    box-shadow: 0 4px 24px rgba(0,0,0,.10);
    border-radius: 6px;
    position: relative;
  }}

  h1 {{ font-size: 1.9em; margin: 1.6em 0 0.4em; }}
  h2 {{ font-size: 1.5em; margin: 1.4em 0 0.35em; }}
  h3 {{ font-size: 1.25em; margin: 1.2em 0 0.3em; }}
  h4, h5, h6 {{ font-size: 1.08em; margin: 1em 0 0.25em; }}

  p {{ margin: 0.45em 0; }}

  ul, ol {{ padding-left: 1.6em; margin: 0.6em 0; }}
  li {{ margin: 0.25em 0; }}

  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 1.2em 0;
    font-size: 0.92em;
  }}
  th, td {{
    border: 1px solid #bbb;
    padding: 7px 11px;
    text-align: left;
    vertical-align: top;
  }}
  th {{ background: #f5f5f5; font-weight: 600; }}
  tr:nth-child(even) td {{ background: #fafafa; }}

  figure {{
    margin: 1.4em 0;
    text-align: center;
  }}
  figure img {{
    max-width: 100%;
    height: auto;
    border-radius: 3px;
  }}
  figcaption {{
    margin-top: 6px;
    font-size: 0.82em;
    color: #666;
  }}

  .anchor-wrap {{
    position: relative;
    height: 0;
    overflow: visible;
    pointer-events: none;
  }}
  .anchor-wrap > * {{
    pointer-events: auto;
  }}

  blockquote {{
    margin: 1em 0;
    padding: 0.8em 1.2em;
    border-left: 4px solid #ccc;
    background: #f9f9f9;
    color: #333;
  }}

  pre {{
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 12px 16px;
    overflow-x: auto;
    font-family: 'D2Coding', Consolas, monospace;
    font-size: 0.88em;
    line-height: 1.5;
  }}
  code {{
    font-family: 'D2Coding', Consolas, monospace;
    font-size: 0.92em;
  }}
  pre code {{ font-size: 1em; }}

  hr {{
    border: none;
    border-top: 1px solid #ddd;
    margin: 2em 0;
  }}

  .equation {{
    text-align: center;
    margin: 1em 0;
    font-size: 1.1em;
  }}

  .footnote {{
    font-size: 0.85em;
    color: #555;
    margin-top: 0.4em;
    padding-left: 1em;
    border-left: 2px solid #ddd;
  }}

  .endnotes {{
    margin-top: 3em;
  }}
  .endnote {{
    font-size: 0.85em;
    color: #555;
    margin: 0.4em 0;
    padding-left: 1em;
  }}

  .footnote-ref, .endnote-ref {{
    text-decoration: none;
    color: #0066cc;
  }}

  .inline-image {{
    display: inline-block;
    vertical-align: middle;
  }}
  .inline-image img {{
    max-width: 100%;
    height: auto;
  }}

  span.text-box {{
    display: inline-block;
    vertical-align: middle;
  }}

  .text-box {{
    border: 1px solid #999;
    padding: 8px 12px;
    margin: 1em 0;
    border-radius: 4px;
    box-sizing: border-box;
    overflow: hidden;
  }}

  .drawing {{
    background: #f8f8f8;
    border: 1px dashed #bbb;
    border-radius: 4px;
    padding: 24px;
    text-align: center;
    color: #888;
    font-size: 0.88em;
    margin: 1em 0;
  }}

  .chart-placeholder {{
    background: #f8f8f8;
    border: 1px dashed #bbb;
    border-radius: 4px;
    padding: 24px;
    text-align: center;
    color: #888;
  }}

  .text-art {{
    font-size: 1.5em;
    font-weight: bold;
    text-align: center;
    margin: 1em 0;
  }}

  .page-break {{
    page-break-after: always;
    break-after: page;
    height: 0;
    margin: 0;
  }}

  .bookmark {{ display: inline; }}

  .comment {{
    background: #fffbcc;
    border: 1px solid #e6d600;
    border-radius: 4px;
    padding: 8px 12px;
    font-size: 0.85em;
    margin: 0.5em 0;
  }}
  .comment[hidden] {{ display: none; }}

  .unknown {{ display: none; }}

  .field {{
    border-bottom: 1px dotted #999;
  }}

  .doc-header {{
    border-bottom: 2px solid #222;
    margin-bottom: 2em;
    padding-bottom: 1em;
  }}

  .doc-footer {{
    margin-top: 3em;
    padding-top: 1em;
    border-top: 1px solid #ddd;
    font-size: 0.85em;
    color: #666;
  }}

  .hidden {{ display: none; }}

  strong {{ font-weight: 700; }}
  em {{ font-style: italic; }}

  ruby rt {{
    font-size: 0.6em;
  }}

  @media print {{
    body {{ background: none; padding: 0; }}
    article {{ box-shadow: none; padding: 20mm 25mm; max-width: none; }}
    .page-break {{ page-break-after: always; break-after: page; }}
    .comment {{ display: none !important; }}
  }}
</style>
</head>
<body>
<article>
{body}
</article>
</body>
</html>
"""

_TEMPLATE_PAGINATED = """\
<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{meta_tags}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Nanum+Gothic:wght@400;700&family=Nanum+Myeongjo:wght@400;700&family=Nanum+Gothic+Coding&family=Noto+Sans+KR:wght@400;700&family=Noto+Serif+KR:wght@400;700&display=swap" rel="stylesheet">
<script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}

  body {{
    margin: 0;
    padding: 32px 16px 64px;
    background: #e0e0e0;
    font-family: 'Malgun Gothic', 'Noto Sans KR', 'Apple SD Gothic Neo', sans-serif;
    font-size: 10pt;
    color: #1a1a1a;
    line-height: 1.6;
    letter-spacing: 0.06em;
  }}

  .page {{
    background: #fff;
    margin: 0 auto 24px;
    box-shadow: 0 2px 12px rgba(0,0,0,.15);
    position: relative;
    overflow: visible;
  }}
  .page-flow {{
    overflow: hidden;
  }}

  .page-header {{
    border-bottom: 1px solid #ddd;
    margin-bottom: 0.8em;
    padding-bottom: 0.4em;
    font-size: 0.85em;
    color: #666;
  }}

  .page-footer {{
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    padding: 0.4em 1em;
    border-top: 1px solid #ddd;
    font-size: 0.85em;
    color: #666;
  }}

  h1 {{ font-size: 1.9em; margin: 0; }}
  h2 {{ font-size: 1.5em; margin: 0; }}
  h3 {{ font-size: 1.25em; margin: 0; }}
  h4, h5, h6 {{ font-size: 1.08em; margin: 0; }}

  p {{ margin: 0; }}

  ul, ol {{ padding-left: 1.6em; margin: 0; }}
  li {{ margin: 0; }}

  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 0;
    font-size: inherit;
  }}
  th, td {{
    border: 1px solid #bbb;
    padding: 4px 7px;
    text-align: left;
    vertical-align: top;
  }}
  th {{ background: #f5f5f5; font-weight: 600; }}

  figure {{
    margin: 0;
    text-align: center;
  }}
  figure img {{
    max-width: 100%;
    height: auto;
  }}
  figcaption {{
    margin-top: 4px;
    font-size: 0.82em;
    color: #666;
  }}

  .anchor-wrap {{
    position: relative;
    height: 0;
    overflow: visible;
    pointer-events: none;
  }}
  .anchor-wrap > * {{
    pointer-events: auto;
  }}

  blockquote {{
    margin: 0.8em 0;
    padding: 0.6em 1em;
    border-left: 4px solid #ccc;
    background: #f9f9f9;
    color: #333;
  }}

  pre {{
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 10px 14px;
    overflow-x: auto;
    font-family: 'D2Coding', Consolas, monospace;
    font-size: 0.88em;
    line-height: 1.5;
  }}
  code {{
    font-family: 'D2Coding', Consolas, monospace;
    font-size: 0.92em;
  }}
  pre code {{ font-size: 1em; }}

  hr {{
    border: none;
    border-top: 1px solid #ddd;
    margin: 1.5em 0;
  }}

  .equation {{
    text-align: center;
    margin: 0.8em 0;
    font-size: 1.1em;
  }}

  .footnote {{
    font-size: 0.85em;
    color: #555;
    margin-top: 0.4em;
    padding-left: 1em;
    border-left: 2px solid #ddd;
  }}

  .endnotes {{ margin-top: 2em; }}
  .endnote {{
    font-size: 0.85em;
    color: #555;
    margin: 0.4em 0;
    padding-left: 1em;
  }}

  .footnote-ref, .endnote-ref {{
    text-decoration: none;
    color: #0066cc;
  }}

  .text-box {{
    border: 1px solid #999;
    padding: 8px 12px;
    margin: 0.8em 0;
    border-radius: 4px;
    box-sizing: border-box;
    overflow: hidden;
  }}

  .drawing {{
    background: #f8f8f8;
    border: 1px dashed #bbb;
    border-radius: 4px;
    padding: 16px;
    text-align: center;
    color: #888;
    font-size: 0.88em;
    margin: 0.8em 0;
    box-sizing: border-box;
    overflow: hidden;
  }}

  .chart-placeholder {{
    background: #f8f8f8;
    border: 1px dashed #bbb;
    border-radius: 4px;
    padding: 16px;
    text-align: center;
    color: #888;
  }}

  .text-art {{
    font-size: 1.5em;
    font-weight: bold;
    text-align: center;
    margin: 0.8em 0;
  }}

  .bookmark {{ display: inline; }}
  .comment {{ background: #fffbcc; border: 1px solid #e6d600; border-radius: 4px; padding: 8px 12px; font-size: 0.85em; margin: 0.5em 0; }}
  .comment[hidden] {{ display: none; }}
  .unknown {{ display: none; }}
  .field {{ border-bottom: 1px dotted #999; }}
  .hidden {{ display: none; }}
  strong {{ font-weight: 700; }}
  em {{ font-style: italic; }}
  ruby rt {{ font-size: 0.6em; }}

  @media print {{
    body {{ background: none; padding: 0; }}
    .page {{
      box-shadow: none;
      margin: 0;
      page-break-after: always;
      break-after: page;
    }}
    .page:last-child {{
      page-break-after: auto;
      break-after: auto;
    }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""
