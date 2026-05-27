"""Markdown and HTML renderers.

Convert a UdfDocument into GFM Markdown or a paginated HTML document.
The Markdown output supports optional block ID embedding for round-trip
workflows. The HTML output renders pages with absolute positioning for
images, table splitting, and styling from the document model.
"""

from __future__ import annotations

import re
from typing import Any

from udf.core.schema import (
    Block,
    ChartBlock,
    DrawingBlock,
    EquationBlock,
    EquationInline,
    FieldBlock,
    FootnoteBlock,
    FootnoteRefInline,
    HeaderBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ImageInline,
    LinkInline,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextArtBlock,
    TextBoxBlock,
    TextInline,
    UdfDocument,
    UnknownBlock,
)

_SERIF_FONTS = {"함초롬바탕", "한컴바탕", "바탕", "바탕체", "HYSMyeongJo", "명조"}
_SANS_FONTS = {"함초롬돋움", "한컴돋움", "돋움", "돋움체", "굴림", "굴림체", "HYGothic"}
_MONO_FONTS = {"D2Coding", "나눔고딕코딩", "Courier New"}


def _to_float(v: Any) -> float:
    """문자열('10pt', '5mm') 또는 숫자(int/float) 모두 처리."""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return float(v.replace("pt", "").replace("mm", "").replace("%", "").strip())
    if hasattr(v, "percent"):
        return float(v.percent)
    return 0.0


def _to_css_val(v: Any, default_unit: str = "pt") -> str:
    """문자열은 그대로, 숫자는 단위를 붙여서 CSS 값으로 반환."""
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return f"{v}{default_unit}"
    if hasattr(v, "percent"):
        return f"{v.percent}{default_unit}"
    return f"0{default_unit}"


def _parse_line_spacing(ls: Any) -> float:
    """line_spacing을 비율(1.6 = 160%)로 반환. 문자열('160%') / float / Ratio 모두 처리."""
    if hasattr(ls, "percent"):
        return float(ls.percent) / 100
    if isinstance(ls, (int, float)):
        return float(ls) / 100  # assume percentage number e.g. 160 → 1.6
    if isinstance(ls, str):
        s = ls.strip()
        if s.endswith("%"):
            return float(s.rstrip("%")) / 100
        return float(s) / 100
    return 1.6


def _font_fallback(name: str) -> str:
    """Return a CSS font-family fallback suffix based on Korean font name."""
    for kw in _SERIF_FONTS:
        if kw in name:
            return ",'Noto Serif KR',serif"
    for kw in _MONO_FONTS:
        if kw in name:
            return ",monospace"
    return ",'Noto Sans KR',sans-serif"


def _extract_page_dims(doc: UdfDocument) -> tuple[float, float, float, float, float, float]:
    """Extract page dimensions (width, height, margins) from document metadata."""
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


# ---------------------------------------------------------------------------
# HTML: 페이지 분리 + 절대 좌표 이미지 + 서식 적용
# ---------------------------------------------------------------------------

def _split_into_pages(
    blocks: list[Block], pw: float, content_height: float = 0, cw: float = 0,
) -> list[list[Block]]:
    """블록 리스트를 페이지별로 분리.

    감지 기준 (우선순위 순):
    1. 이미지 y좌표 리셋: 배너 이미지 또는 상단 이미지 클러스터 감지
    2. 높이 기반: 블록 누적 높이가 콘텐츠 영역을 초과하면 새 페이지
    """
    if not blocks:
        return []

    has_positioned_images = any(
        isinstance(b, ImageBlock) and b.position and b.position.y is not None
        for b in blocks
    )

    if has_positioned_images:
        pages = _split_by_image_coords(blocks, pw)
        if len(pages) > 1 and content_height > 0:
            refined: list[list[Block]] = []
            for page in pages:
                ph = sum(_estimate_block_height(b, cw) for b in page)
                if ph > content_height * 1.2:
                    refined.extend(_split_by_height(page, content_height, cw))
                else:
                    refined.append(page)
            return refined
        if len(pages) > 1:
            return pages

    if content_height > 0:
        return _split_by_height(blocks, content_height, cw)

    return [blocks]


def _split_by_image_coords(blocks: list[Block], pw: float) -> list[list[Block]]:
    """이미지 y좌표 기반 페이지 분리."""
    pages: list[list[Block]] = [[]]
    max_y = 0.0

    i = 0
    while i < len(blocks):
        b = blocks[i]
        new_page = False

        if isinstance(b, ImageBlock) and b.position:
            y = (b.position.y or 0)
            w = (b.position.width or 0)
            if y < 50 and w > pw * 0.8 and max_y > 300:
                new_page = True

        elif b.type in ("paragraph", "heading") and max_y > 500:
            text = ""
            if hasattr(b, "text"):
                text = b.text
            elif hasattr(b, "inlines") and b.inlines:
                text = "".join(
                    il.text for il in b.inlines if hasattr(il, "text")
                )
            if text.strip():
                low_count = 0
                for j in range(i + 1, min(i + 8, len(blocks))):
                    bj = blocks[j]
                    if isinstance(bj, ImageBlock) and bj.position:
                        yj = (bj.position.y or 0)
                        if yj < 150:
                            low_count += 1
                        else:
                            break
                    elif bj.type in ("paragraph", "heading", "table"):
                        break
                if low_count >= 2:
                    new_page = True

        if new_page and pages[-1]:
            pages.append([])
            max_y = 0.0

        pages[-1].append(b)

        if isinstance(b, ImageBlock) and b.position and b.position.y is not None:
            max_y = max(max_y, (b.position.y or 0))

        i += 1

    return [p for p in pages if p]


def _estimate_row_height(row: TableRow, cw: float) -> float:
    """Estimate a table row's height in points based on cell content."""
    max_h = 0.0
    for cell in row.cells:
        if cell.height and cell.height > 0:
            ch = cell.height
            if cell.row_span > 1:
                ch = ch / cell.row_span
        else:
            ch = sum(
                _estimate_block_height(cb, cw) for cb in cell.content
            ) if cell.content else 16.0
        if ch > max_h:
            max_h = ch
    return max(max_h, 16.0)


def _split_table_rows(
    table: TableBlock,
    remaining_height: float,
    content_height: float,
    cw: float,
) -> list[TableBlock]:
    """Split a table across pages by distributing rows to fit content height."""
    if not table.rows or len(table.rows) <= 1:
        return [table]

    header_row = table.rows[0] if table.repeat_header else None
    header_h = _estimate_row_height(header_row, cw) if header_row else 0.0

    row_heights = [_estimate_row_height(r, cw) for r in table.rows]

    parts: list[list[int]] = [[]]
    cursor = 0.0
    page_h = remaining_height

    tolerance = content_height * 0.03
    for ri, rh in enumerate(row_heights):
        if cursor > 0 and cursor + rh > page_h + tolerance:
            parts.append([])
            cursor = header_h
            page_h = content_height
        parts[-1].append(ri)
        cursor += rh

    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return [table]

    result: list[TableBlock] = []
    for pi, row_indices in enumerate(parts):
        rows = []
        if pi > 0 and header_row and 0 not in row_indices:
            rows.append(header_row)
        for ri in row_indices:
            rows.append(table.rows[ri])
        part = TableBlock(
            type="table",
            id=table.id if pi == 0 else f"{table.id}_p{pi}",
            rows=rows,
            format=table.format,
            position=table.position,
            cell_spacing=table.cell_spacing,
            default_padding=table.default_padding,
            repeat_header=table.repeat_header,
            border_fill_id=table.border_fill_id,
            verbatim_ref=table.verbatim_ref if pi == 0 else None,
        )
        result.append(part)
    return result


def _split_by_height(
    blocks: list[Block], content_height: float, cw: float,
) -> list[list[Block]]:
    """블록 누적 높이 기반 페이지 분리."""
    pages: list[list[Block]] = [[]]
    cursor = 0.0

    for b in blocks:
        h = _estimate_block_height(b, cw)
        if isinstance(b, TableBlock) and len(b.rows) > 1 and cursor + h > content_height:
            remaining = content_height - cursor
            parts = _split_table_rows(b, remaining, content_height, cw)
            for j, part in enumerate(parts):
                if j > 0:
                    pages.append([])
                    cursor = 0.0
                pages[-1].append(part)
                cursor += _estimate_block_height(part, cw)
            continue
        if cursor > 0 and cursor + h > content_height:
            if cursor < content_height * 0.15:
                pass
            else:
                pages.append([])
                cursor = 0.0
        pages[-1].append(b)
        cursor += h

    result = [p for p in pages if p]
    if len(result) > 1:
        last_h = sum(_estimate_block_height(b, cw) for b in result[-1])
        if last_h < content_height * 0.05:
            result[-2].extend(result[-1])
            result.pop()
    return result


def render_html(
    doc: UdfDocument,
    *,
    image_dir: str = "images",
    embed_images: bool = False,
    embed_ids: bool = False,
) -> str:
    """Render a UdfDocument to a paginated HTML string.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    image_dir : str, default "images"
        Directory path used in ``<img src>`` for BinData references.
    embed_images : bool, default False
        If True, embed images as base64 data URIs instead of file paths.
    embed_ids : bool, default False
        If True, emit ``data-bid`` attributes on elements for block ID
        tracking.

    Returns
    -------
    str
        Complete HTML document string with page layout and styling.
    """
    bindata = (doc.verbatim.bindata_streams if doc.verbatim else {}) or {}

    def resolve_src(src: str) -> str:
        """Resolve bindata: URIs to file paths or data URIs."""
        if not src.startswith("bindata:"):
            return src
        name = src[len("bindata:"):]
        if embed_images and name in bindata:
            ext = name.rsplit(".", 1)[-1].lower()
            mime = {
                "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "gif": "image/gif",
                "bmp": "image/bmp",
            }.get(ext, "image/jpeg")
            return f"data:{mime};base64,{bindata[name]}"
        return f"{image_dir}/{name}"

    pw, ph, mt, mb, ml, mr = _extract_page_dims(doc)
    cw = pw - ml - mr

    numbering_state: _NumberingState | None = None
    if doc.verbatim and doc.verbatim.global_resources:
        ndef = doc.verbatim.global_resources.numberings.get("0")
        if ndef and ndef.levels:
            patterns = [
                lvl.prefix for lvl in ndef.levels
            ]
            if any(p for p in patterns):
                headings_have_inline_num = any(
                    re.match(r"^\d|^[가-힣]\s*\.", "".join(
                        il.text for il in b.inlines if hasattr(il, "text")
                    ).strip())
                    for b in doc.blocks
                    if b.type == "heading"
                    and hasattr(b, "inlines") and b.inlines
                )
                if not headings_have_inline_num:
                    numbering_state = _NumberingState(patterns)

    ctx = _HtmlCtx(
        resolve_src=resolve_src, content_width=cw,
        margin_left=ml, margin_right=mr, paper_width=pw,
        margin_top=mt,
        numbering=numbering_state,
        embed_ids=embed_ids,
    )

    content_height = ph - mt - mb

    global _pls_height_map
    _pls_height_map = _build_pls_height_map(doc)

    pages = _split_into_pages(list(doc.blocks), pw, content_height, cw)

    page_htmls: list[str] = []
    show_page_num = len(pages) > 1
    for pi, page_blocks in enumerate(pages, 1):
        page_htmls.append(_render_page(
            page_blocks, ctx,
            page_num=pi if show_page_num else None,
        ))

    body = "\n".join(page_htmls)
    return _HTML_TEMPLATE.format(
        body=body,
        pw=int(pw), ph=int(ph),
        mt=int(mt), mb=int(mb), ml=int(ml), mr=int(mr),
    )


def _render_page(
    blocks: list[Block], ctx: _HtmlCtx,
    page_num: int | None = None,
) -> str:
    """Render a single page to HTML with image placement and text flow."""
    ml = ctx.margin_left
    mr = ctx.margin_right
    pw = ctx.paper_width
    cw = ctx.content_width
    mt = ctx.margin_top

    # 1단계: 블록 전처리 — 여백 장식, 챕터번호, 헤더 이미지, 드롭캡 감지
    margin_bg_parts: list[str] = []
    chapter_num_idx: int | None = None
    header_img_indices: set[int] = set()
    dropcap_idx: int | None = None
    dropcap_target_idx: int | None = None
    skip_indices: set[int] = set()

    for i, b in enumerate(blocks):
        if isinstance(b, ImageBlock) and b.position:
            p = b.position
            x = (p.x or 0)
            w = (p.width or 0)
            center_x = x + w / 2
            if center_x < ml * 0.7 or center_x > pw - mr * 0.7:
                src = ctx.resolve_src(b.src) if ctx.resolve_src else b.src
                if src:
                    y = (p.y or 0)
                    h = (p.height or 0)
                    margin_bg_parts.append(
                        f"url('{src}') {x:.0f}pt {y:.0f}pt / {w:.0f}pt {h:.0f}pt no-repeat"
                    )
                skip_indices.add(i)

    for i, b in enumerate(blocks):
        if i in skip_indices:
            continue
        if isinstance(b, ParagraphBlock) and b.inlines:
            raw = "".join(il.text for il in b.inlines if hasattr(il, "text")).strip()
            if raw and len(raw) <= 2:
                fs = _get_font_size(b)
                if fs >= 50:
                    chapter_num_idx = i
                    skip_indices.add(i)
                    break

    if chapter_num_idx is not None:
        for i, b in enumerate(blocks):
            if i in skip_indices or not isinstance(b, ImageBlock) or not b.position:
                continue
            p = b.position
            x = (p.x or 0)
            y = (p.y or 0)
            w = (p.width or 0)
            h = (p.height or 0)
            rel_x = x - ml
            if y < 150 and h > 40 and rel_x + w / 2 > cw / 2 and w <= cw * 0.7:
                header_img_indices.add(i)
                skip_indices.add(i)

    for i, b in enumerate(blocks):
        if i in skip_indices:
            continue
        if not isinstance(b, ParagraphBlock) or not b.inlines:
            continue
        raw = "".join(il.text for il in b.inlines if hasattr(il, "text")).strip()
        if not raw or len(raw) > 2:
            continue
        fs = _get_font_size(b)
        if 20 <= fs < 50:
            for j in range(max(0, i - 5), min(len(blocks), i + 5)):
                if j == i or j in skip_indices:
                    continue
                if isinstance(blocks[j], TableBlock) and blocks[j].rows:
                    dropcap_idx = i
                    dropcap_target_idx = j
                    skip_indices.add(i)
                    break
            break

    # 2단계: 텍스트와 이미지를 y좌표 기준으로 정렬하여 올바른 위치에 배치
    # 텍스트 블록: 누적 높이로 y 추정 (이미지 y를 앵커로 보정)
    # 이미지 블록: HWP의 페이지 y좌표 사용
    text_blocks: list[tuple[int, Block]] = []
    img_queue: list[tuple[float, int, ImageBlock]] = []

    for i, b in enumerate(blocks):
        if i in skip_indices:
            continue
        if isinstance(b, ImageBlock) and b.position:
            y = (b.position.y or 0) - mt
            img_queue.append((max(0, y), i, b))
        else:
            text_blocks.append((i, b))

    img_queue.sort(key=lambda t: t[0])

    # 텍스트 y 추정: 누적 높이, 이미지 y를 앵커로 보정
    cursor_y = 0.0
    text_with_y: list[tuple[float, int, Block]] = []
    img_anchors = [y for y, _, _ in img_queue]

    for idx, (i, b) in enumerate(text_blocks):
        # 이 텍스트 블록의 스트림 위치(i) 이전에 있는 이미지들의 y로 보정
        for ay, ai, _ in img_queue:
            if ai < i and ay > cursor_y:
                cursor_y = max(cursor_y, ay)
        text_with_y.append((cursor_y, i, b))
        cursor_y += _estimate_block_height(b, cw)

    # 모든 블록을 y 기준 통합 정렬 (같은 y면 텍스트 우선)
    all_items: list[tuple[float, int, Block, bool]] = []
    for y, i, b in text_with_y:
        all_items.append((y, i, b, False))
    for y, i, b in img_queue:
        all_items.append((y, i, b, True))
    all_items.sort(key=lambda t: (t[0], 0 if not t[3] else 1))

    # 3단계: 페이지 조립
    parts: list[str] = []
    has_float = False

    # 헤더
    if chapter_num_idx is not None:
        for i, b in enumerate(blocks):
            if i in skip_indices or not isinstance(b, ImageBlock) or not b.position:
                continue
            p = b.position
            y = (p.y or 0)
            w = (p.width or 0)
            if y < 50 and w > cw * 0.7:
                src = ctx.resolve_src(b.src) if ctx.resolve_src else b.src
                alt = _escape_html(b.alt or "")
                h = (p.height or 0)
                parts.append(
                    f'<div style="text-align:center;margin:0 0 8pt 0">'
                    f'<img src="{src}" alt="{alt}" '
                    f'style="width:{w:.0f}pt;height:{h:.0f}pt;max-width:100%">'
                    f'</div>'
                )
                skip_indices.add(i)

        chap_b = blocks[chapter_num_idx]
        raw = "".join(il.text for il in chap_b.inlines if hasattr(il, "text")).strip()
        display_fs = min(_get_font_size(chap_b), 72)
        header_parts: list[str] = [
            f'<div style="font-size:{display_fs:.0f}pt;line-height:0.85;'
            f'padding:5pt 15pt 0 0;font-weight:bold">'
            f'{_escape_html(raw)}</div>',
            '<div style="flex:1"></div>',
        ]
        if header_img_indices:
            header_parts.append('<div>')
            for i in sorted(header_img_indices):
                b = blocks[i]
                src = ctx.resolve_src(b.src) if ctx.resolve_src else b.src
                alt = _escape_html(b.alt or "")
                w = (b.position.width or 0)
                h = (b.position.height or 0)
                dw = min(w, 160)
                scale = dw / w if dw < w else 1
                dh = h * scale
                header_parts.append(
                    f'<img src="{src}" alt="{alt}" '
                    f'style="width:{dw:.0f}pt;height:{dh:.0f}pt;'
                    f'display:block;margin-bottom:2pt">'
                )
            header_parts.append('</div>')
        parts.append(
            '<div style="display:flex;align-items:flex-start;'
            'margin-bottom:8pt;overflow:hidden">\n'
            + "\n".join(header_parts) + "\n</div>"
        )

    # 본문: y 정렬된 순서로 렌더링
    ctx.flow_cursor_y = 0.0
    emitted: set[int] = set()
    for y, block_idx, b, is_img in all_items:
        if block_idx in skip_indices or block_idx in emitted:
            continue
        emitted.add(block_idx)

        if is_img:
            w = (b.position.width or 0)
            if has_float and w > cw * 0.7:
                parts.append('<div style="clear:both"></div>')
                has_float = False
            rendered = _render_single_image(b, ctx, cw, ml)
            parts.append(rendered)
            if w <= cw * 0.7:
                has_float = True
        else:
            if has_float and isinstance(b, (TableBlock, HeadingBlock)):
                parts.append('<div style="clear:both"></div>')
                has_float = False

            if isinstance(b, TableBlock):
                dc = None
                if dropcap_target_idx is not None and block_idx == dropcap_target_idx and dropcap_idx is not None:
                    dc_b = blocks[dropcap_idx]
                    dc_raw = "".join(il.text for il in dc_b.inlines if hasattr(il, "text")).strip()
                    dc_fs = _get_font_size(dc_b)
                    dc = (dc_raw, dc_fs)
                parts.append(_render_table_html(b, ctx, dropcap=dc))
            else:
                rendered = _render_primary_html(b, ctx)
                if rendered:
                    parts.append(rendered)
            ctx.flow_cursor_y += _estimate_block_height(b, cw)

    parts.append('<div style="clear:both"></div>')
    content = "\n".join(parts)
    if margin_bg_parts:
        bg_imgs = []
        bg_positions = []
        bg_sizes = []
        _bg_re = re.compile(r"(url\([^)]+\))\s+([\d.]+pt)\s+([\d.]+pt)\s*/\s*([\d.]+pt)\s+([\d.]+pt)\s+no-repeat")
        for part in margin_bg_parts:
            m = _bg_re.match(part)
            if m:
                bg_imgs.append(m.group(1))
                bg_positions.append(f"{m.group(2)} {m.group(3)}")
                bg_sizes.append(f"{m.group(4)} {m.group(5)}")
        if bg_imgs:
            style_parts = [
                f"background-image:{','.join(bg_imgs)}",
                f"background-position:{','.join(bg_positions)}",
                f"background-size:{','.join(bg_sizes)}",
                f"background-repeat:{','.join(['no-repeat']*len(bg_imgs))}",
                "background-color:#fff",
            ]
            style = ";".join(style_parts)
            footer = _page_footer(page_num)
            return (
                f'<div class="page" style="{style}">\n'
                f'<div class="content">\n{content}\n</div>{footer}\n</div>'
            )
    footer = _page_footer(page_num)
    return f'<div class="page">\n<div class="content">\n{content}\n</div>{footer}\n</div>'


def _page_footer(page_num: int | None) -> str:
    """Generate a centered page number footer div."""
    if page_num is None:
        return ""
    return (
        f'\n<div style="text-align:center;font-size:9pt;'
        f'padding:8pt 0;color:#333">- {page_num} -</div>'
    )


def _get_font_size(block: Block) -> float:
    """ParagraphBlock의 첫 인라인 font_size를 pt 단위로 반환."""
    if hasattr(block, "inlines") and block.inlines:
        for il in block.inlines:
            if hasattr(il, "font_size") and il.font_size:
                try:
                    return _to_float(il.font_size)
                except (ValueError, TypeError):
                    pass
    return 10.0


def _render_single_image(b: ImageBlock, ctx: _HtmlCtx, cw: float, ml: float) -> str:
    """단일 이미지를 x좌표 기반으로 float 또는 block 렌더링."""
    p = b.position
    x = (p.x or 0)
    w = (p.width or 0)
    h = (p.height or 0)
    src = ctx.resolve_src(b.src) if ctx.resolve_src else b.src
    alt = _escape_html(b.alt or "")
    bid = _bid_attr(b, ctx)
    rel_x = x - ml

    if w > cw * 0.7:
        return (
            f'<div{bid} style="text-align:center;margin:8pt 0">'
            f'<img src="{src}" alt="{alt}" '
            f'style="width:{w:.0f}pt;height:{h:.0f}pt;max-width:100%">'
            f'</div>'
        )
    elif rel_x + w / 2 > cw / 2:
        return (
            f'<img{bid} src="{src}" alt="{alt}" '
            f'style="float:right;margin:4pt 0 4pt 10pt;'
            f'width:{w:.0f}pt;height:{h:.0f}pt">'
        )
    else:
        lm = max(0, rel_x)
        return (
            f'<img{bid} src="{src}" alt="{alt}" '
            f'style="float:left;margin:4pt 10pt 4pt {lm:.0f}pt;'
            f'width:{w:.0f}pt;height:{h:.0f}pt">'
        )


def _render_image_group(
    grp: list[tuple[float, float, float, float, ImageBlock]],
    ctx: _HtmlCtx,
    has_float: bool,
) -> str:
    """이미지 그룹 렌더링. x좌표 겹침 감지 → 겹치는 이미지는 하나의 float 컨테이너."""
    ml = ctx.margin_left
    cw = ctx.content_width
    parts: list[str] = []

    full_width: list[tuple[float, float, float, float, ImageBlock]] = []
    right_side: list[tuple[float, float, float, float, ImageBlock]] = []
    left_side: list[tuple[float, float, float, float, ImageBlock]] = []

    for item in grp:
        cy, x, w, h, b = item
        rel_x = x - ml
        if w > cw * 0.7:
            full_width.append(item)
        elif rel_x + w / 2 > cw / 2:
            right_side.append(item)
        else:
            left_side.append(item)

    for cy, x, w, h, b in full_width:
        src = ctx.resolve_src(b.src) if ctx.resolve_src else b.src
        alt = _escape_html(b.alt or "")
        if has_float:
            parts.append('<div style="clear:both"></div>')
            has_float = False
        parts.append(
            f'<div style="text-align:center;margin:8pt 0">'
            f'<img src="{src}" alt="{alt}" '
            f'style="width:{w:.0f}pt;height:{h:.0f}pt;max-width:100%">'
            f'</div>'
        )

    if right_side:
        right_side.sort(key=lambda g: g[1])
        max_w = max(w for _, _, w, _, _ in right_side)
        if len(right_side) == 1:
            cy, x, w, h, b = right_side[0]
            src = ctx.resolve_src(b.src) if ctx.resolve_src else b.src
            alt = _escape_html(b.alt or "")
            parts.append(
                f'<img src="{src}" alt="{alt}" '
                f'style="float:right;margin:4pt 0 4pt 10pt;'
                f'width:{w:.0f}pt;height:{h:.0f}pt">'
            )
        else:
            imgs_html: list[str] = []
            for cy, x, w, h, b in right_side:
                src = ctx.resolve_src(b.src) if ctx.resolve_src else b.src
                alt = _escape_html(b.alt or "")
                imgs_html.append(
                    f'<img src="{src}" alt="{alt}" '
                    f'style="width:{w:.0f}pt;height:{h:.0f}pt;display:block;'
                    f'margin-bottom:2pt">'
                )
            parts.append(
                f'<div style="float:right;margin:4pt 0 4pt 10pt;'
                f'max-width:{max_w:.0f}pt">\n'
                + "\n".join(imgs_html)
                + "\n</div>"
            )

    for cy, x, w, h, b in sorted(left_side, key=lambda g: g[1]):
        src = ctx.resolve_src(b.src) if ctx.resolve_src else b.src
        alt = _escape_html(b.alt or "")
        lm = max(0, x - ml)
        parts.append(
            f'<img src="{src}" alt="{alt}" '
            f'style="float:left;margin:4pt 10pt 4pt {lm:.0f}pt;'
            f'width:{w:.0f}pt;height:{h:.0f}pt">'
        )
    return "\n".join(parts)


def _build_pls_height_map(doc: UdfDocument) -> dict[str, float]:
    """verbatim PLS 데이터에서 블록별 정확한 높이를 추출."""
    import base64
    import struct as _st

    if not doc.verbatim or not doc.verbatim.blocks:
        return {}

    height_map: dict[str, float] = {}
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
        # PLS entry size: try 36, 32, 28, 24
        for esz in (36, 32, 28, 24):
            if len(pls_data) % esz == 0:
                entry_size = esz
                break
        else:
            continue
        n_lines = len(pls_data) // entry_size
        if n_lines == 0:
            continue
        # offset 4 = vpos (Y), offset 8 = lineHeight
        last_y = _st.unpack_from("<I", pls_data, (n_lines - 1) * entry_size + 4)[0]
        last_h = _st.unpack_from("<I", pls_data, (n_lines - 1) * entry_size + 8)[0]
        first_y = _st.unpack_from("<I", pls_data, 4)[0]
        total_hu = (last_y - first_y) + last_h
        height_map[block.id] = total_hu / 100.0  # HWPUNIT → pt

    return height_map


_pls_height_map: dict[str, float] = {}


def _parse_spacing_pt(val: Any) -> float:
    """Parse a spacing value (pt/mm/cm string or numeric) to points."""
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


def _estimate_block_height(b: Block, content_width: float = 481.0) -> float:
    """Estimate a block's rendered height in points for page splitting."""
    fmt = getattr(b, "format", None)
    para_spacing = 0.0
    if fmt:
        para_spacing += _parse_spacing_pt(getattr(fmt, "space_before", None))
        para_spacing += _parse_spacing_pt(getattr(fmt, "space_after", None))

    if b.id in _pls_height_map:
        h = _pls_height_map[b.id]
        if h > 0:
            return h + para_spacing
    if isinstance(b, TableBlock):
        total = 0.0
        seen_rows: set[int] = set()
        for row in (b.rows or []):
            max_h = 0.0
            for cell in row.cells:
                if cell.height and cell.height > 0:
                    ch = cell.height
                    r0 = cell.row_span
                    if r0 > 1:
                        ch = ch / r0
                else:
                    ch = sum(
                        _estimate_block_height(cb, content_width)
                        for cb in cell.content
                    ) if cell.content else 16.0
                if ch > max_h:
                    max_h = ch
            total += max(max_h, 16.0)
        return max(total, 16.0)
    if isinstance(b, HeadingBlock):
        fs = 10.0
        if hasattr(b, "inlines") and b.inlines:
            for il in b.inlines:
                if hasattr(il, "font_size") and il.font_size:
                    try:
                        fs = _to_float(il.font_size)
                    except (ValueError, TypeError):
                        pass
                    break
        return fs * 2.0 + para_spacing
    if isinstance(b, ParagraphBlock):
        if not b.inlines:
            return 16.0 + para_spacing
        text = "".join(il.text for il in b.inlines if hasattr(il, "text"))
        if not text.strip():
            return 16.0 + para_spacing
        fs = 10.0
        for il in b.inlines:
            if hasattr(il, "font_size") and il.font_size:
                try:
                    fs = _to_float(il.font_size)
                    break
                except (ValueError, TypeError):
                    pass
        ls = 1.6
        if b.format and b.format.line_spacing:
            try:
                ls = _parse_line_spacing(b.format.line_spacing)
            except (ValueError, TypeError):
                pass
        chars_per_line = max(10, content_width / (fs * 0.55))
        lines = max(1, len(text) / chars_per_line)
        return lines * fs * ls + para_spacing
    if isinstance(b, (DrawingBlock, TextBoxBlock)):
        if b.position and b.position.like_char is False:
            return 0.0
        if b.position and b.position.height and getattr(b.position, "like_char", False):
            return b.position.height
    return 20.0


_HANGUL_SYLLABLES = "가나다라마바사아자차카타파하"
_HANGUL_JAMO = "ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ"


class _NumberingState:
    """개요 번호 카운터. HeadingBlock 렌더링 시 자동 번호 적용."""

    def __init__(self, patterns: list[str | None]) -> None:
        """Initialize numbering state with per-level format patterns."""
        self.patterns = patterns
        self.counters = [0] * 7

    def advance(self, level: int) -> str | None:
        """Advance the counter for the given level and return formatted string."""
        idx = level - 1
        if idx < 0 or idx >= len(self.patterns) or not self.patterns[idx]:
            return None
        self.counters[idx] += 1
        for j in range(idx + 1, 7):
            self.counters[j] = 0
        return self._apply_pattern(self.patterns[idx])

    def _apply_pattern(self, pattern: str) -> str:
        """Substitute level tokens in the pattern with formatted counters."""
        result = pattern
        for lvl in range(7, 0, -1):
            token = f"^{lvl}"
            if token in result:
                result = result.replace(token, self._format_counter(lvl - 1))
        return result

    def _format_counter(self, idx: int) -> str:
        """Format a counter value based on its level (digit, hangul, etc.)."""
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


class _HtmlCtx:
    def __init__(
        self, *, resolve_src: Any, content_width: float,
        margin_left: float, margin_right: float = 57.0, paper_width: float = 595.0,
        margin_top: float = 57.0,
        numbering: _NumberingState | None = None,
        embed_ids: bool = False,
    ):
        """Initialize HTML rendering context with page layout parameters."""
        self.resolve_src = resolve_src
        self.content_width = content_width
        self.margin_left = margin_left
        self.margin_right = margin_right
        self.paper_width = paper_width
        self.margin_top = margin_top
        self.numbering = numbering
        self.embed_ids = embed_ids
        self.flow_cursor_y: float = 0.0


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;700&family=Noto+Sans+KR:wght@400;700&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async></script>
<style>
@font-face {{ font-family: '함초롬바탕'; src: local('함초롬바탕'); }}
@font-face {{ font-family: '함초롬돋움'; src: local('함초롬돋움'); }}
@font-face {{ font-family: '한컴돋움'; src: local('한컴돋움'); }}
@font-face {{ font-family: '한컴바탕'; src: local('한컴바탕'); }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; padding: 20px; background: #e0e0e0; font-family: 'Noto Sans KR', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif; }}
.page {{
  width: {pw}pt;
  height: {ph}pt;
  margin: 0 auto 40px auto;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.18);
  overflow: hidden;
  position: relative;
  page-break-after: always;
}}
.page .content {{
  padding: {mt}pt {mr}pt {mb}pt {ml}pt;
  line-height: 1.6;
  font-size: 10pt;
  overflow: hidden;
}}
.page .content p {{ margin: 0.15em 0; white-space: pre-wrap; }}
.page .content h1,.page .content h2,.page .content h3,
.page .content h4,.page .content h5,.page .content h6 {{ margin: 0.15em 0; font-size: inherit; }}
table {{ border-collapse: collapse; table-layout: fixed; margin: 0.4em 0; }}
td, th {{ border: none; padding: 1pt 2pt; vertical-align: top; font-size: 10pt; }}
.fn {{ font-size: 8pt; color: #555; margin-top: 0.4em; }}
.img-left {{ float: left; margin: 4pt 10pt 4pt 0; }}
.img-right {{ float: right; margin: 4pt 0 4pt 10pt; }}
.img-center {{ display: block; margin: 8pt auto; }}
.img-full {{ display: block; width: 100% !important; height: auto !important; margin: 8pt 0; }}
.clear {{ clear: both; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


# ---------------------------------------------------------------------------
# 주 블록 HTML (서식 적용)
# ---------------------------------------------------------------------------


def _abs_position_styles(pos: Any, ctx: _HtmlCtx) -> list[str]:
    """like_char=False인 개체의 position:absolute CSS 조각 반환."""
    if not pos or pos.like_char is not False:
        return []
    x_pt = (pos.x or 0)
    y_pt = (pos.y or 0)
    hrel = pos.hrelto or "column"
    vrel = pos.vrelto or "paragraph"
    left = x_pt if hrel == "paper" else ctx.margin_left + x_pt
    if vrel == "paper":
        top = y_pt
    elif vrel == "page":
        top = ctx.margin_top + y_pt
    else:
        top = ctx.margin_top + ctx.flow_cursor_y + y_pt
    sty = [f"position:absolute", f"left:{left:.1f}pt", f"top:{top:.1f}pt"]
    if pos.flow == "front":
        sty.append("z-index:10")
    elif pos.flow == "back":
        sty.append("z-index:-1")
    else:
        sty.append("z-index:5")
    return sty


def _render_drawing_container(block: DrawingBlock, ctx: _HtmlCtx | None = None) -> str:
    """children이 있는 DrawingBlock → position:relative 컨테이너 + absolute 자식."""
    abs_sty = _abs_position_styles(block.position, ctx) if ctx else []
    if abs_sty:
        psty = abs_sty
    else:
        psty = ["position:relative"]
    if block.position:
        if block.position.width:
            psty.append(f"width:{block.position.width:.0f}pt")
        if block.position.height:
            psty.append(f"height:{block.position.height:.0f}pt")
    if block.background_color:
        psty.append(f"background:{block.background_color}")
    if block.line_color and block.line_width and block.line_width > 0:
        psty.append(f"border:{block.line_width:.1f}pt solid {block.line_color}")
    if not abs_sty:
        psty.append("margin:2pt 0")
    parts = [f'<div style="{";".join(psty)}">']
    for child in block.children:
        csty: list[str] = ["position:absolute"]
        if child.position:
            csty.append(f"left:{(child.position.x or 0):.0f}pt")
            csty.append(f"top:{(child.position.y or 0):.0f}pt")
            if child.position.width:
                csty.append(f"width:{child.position.width:.0f}pt")
            if child.position.height:
                csty.append(f"height:{child.position.height:.0f}pt")
        if child.background_color:
            csty.append(f"background:{child.background_color}")
        if child.line_color and child.line_width and child.line_width > 0:
            csty.append(f"border:{child.line_width:.1f}pt solid {child.line_color}")
        parts.append(f'<div style="{";".join(csty)}"></div>')
    parts.append("</div>")
    return "\n".join(parts)


def _bid_attr(block: Block, ctx: _HtmlCtx) -> str:
    """Return a data-bid HTML attribute string if embed_ids is enabled."""
    if ctx.embed_ids and hasattr(block, "id") and block.id:
        return f' data-bid="{block.id}"'
    return ""


def _render_primary_html(block: Block, ctx: _HtmlCtx) -> str | None:
    """Render a block to its primary HTML representation."""
    if isinstance(block, ParagraphBlock):
        bid = _bid_attr(block, ctx)
        text = _render_inlines_html(block.inlines, ctx)
        if not text:
            pstyle = _para_style(block)
            attr = f' style="{pstyle}"' if pstyle else ""
            return f"<p{bid}{attr}>&nbsp;</p>"
        raw = "".join(
            il.text for il in block.inlines if hasattr(il, "text")
        ).strip()
        if raw and len(raw) <= 2:
            fs = 10.0
            for il in block.inlines:
                if hasattr(il, "font_size") and il.font_size:
                    try:
                        fs = _to_float(il.font_size)
                    except (ValueError, TypeError):
                        pass
                    break
            if fs >= 50:
                return (
                    f'<p{bid} style="font-size:{min(fs, 72):.0f}pt;'
                    f'line-height:0.85;margin:0 0 5pt 0;font-weight:bold">'
                    f'{_escape_html(raw)}</p>'
                )
        pstyle = _para_style(block)
        attr = f' style="{pstyle}"' if pstyle else ""
        return f"<p{bid}{attr}>{text}</p>"

    if isinstance(block, HeadingBlock):
        bid = _bid_attr(block, ctx)
        level = max(1, min(6, block.level))
        pstyle = _para_style(block)
        attr = f' style="{pstyle}"' if pstyle else ""
        text = _render_inlines_html(block.inlines, ctx) if hasattr(block, "inlines") and block.inlines else _escape_html(block.text)
        prefix = ""
        if ctx and ctx.numbering and text.strip():
            pfx = ctx.numbering.advance(level)
            if pfx:
                prefix = f"<strong>{_escape_html(pfx)}</strong> "
        return f"<h{level}{bid}{attr}>{prefix}{text}</h{level}>"

    if isinstance(block, TableBlock):
        return _render_table_html(block, ctx)

    if isinstance(block, EquationBlock):
        bid = _bid_attr(block, ctx)
        if block.latex:
            return f"<p{bid}>$${block.latex}$$</p>"
        if block.hwp_script:
            return f"<!-- hwp-equation: {_escape_html(block.hwp_script)} -->"
        return None

    if isinstance(block, DrawingBlock):
        if block.children:
            return _render_drawing_container(block, ctx)
        has_border = block.line_color and block.line_width and block.line_width > 0
        abs_sty = _abs_position_styles(block.position, ctx)
        if abs_sty or block.background_color or has_border:
            sty: list[str] = list(abs_sty)
            if block.background_color:
                sty.append(f"background:{block.background_color}")
            if has_border:
                sty.append(f"border:{block.line_width:.1f}pt solid {block.line_color}")
            if block.position:
                if block.position.width:
                    sty.append(f"width:{block.position.width:.0f}pt")
                if block.position.height:
                    h_pt = block.position.height
                    sty.append(f"height:{max(h_pt, 2):.0f}pt")
                elif not abs_sty:
                    sty.append("height:2pt")
            elif not abs_sty:
                sty.append("height:2pt;width:100%")
            if not abs_sty:
                sty.append("margin:2pt 0")
            return f'<div style="{";".join(sty)}"></div>'
        return None

    if isinstance(block, TextBoxBlock):
        inner_parts = []
        for b in block.content:
            rendered = _render_primary_html(b, ctx)
            if rendered:
                inner_parts.append(rendered)
        abs_sty = _abs_position_styles(block.position, ctx)
        style_parts: list[str] = list(abs_sty)
        if block.background_color:
            style_parts.append(f"background:{block.background_color}")
        if block.background_image and ctx:
            src = ctx.resolve_src(block.background_image)
            style_parts.append(
                f"background-image:url('{src}');background-size:cover;"
                "background-position:center"
            )
        if block.line_color and block.line_width and block.line_width > 0:
            style_parts.append(f"border:{block.line_width:.1f}pt solid {block.line_color}")
        if block.border_radius:
            style_parts.append(f"border-radius:{block.border_radius:.0f}pt")
        if block.position and block.position.width:
            w = block.position.width
            style_parts.append(f"width:{w:.0f}pt")
        if block.position and block.position.height:
            h = block.position.height
            style_parts.append(f"min-height:{h:.0f}pt")
        style_parts.append("padding:6pt 8pt")
        if not abs_sty:
            style_parts.append("margin:4pt 0")
        style = ";".join(style_parts)
        inner = "".join(inner_parts)
        if not inner and not block.background_image and not block.background_color and not abs_sty:
            return None
        return f'<div style="{style}">{inner}</div>'

    if isinstance(block, ListBlock):
        bid = _bid_attr(block, ctx)
        tag = "ol" if block.ordered else "ul"
        start_attr = f' start="{block.start}"' if block.ordered and block.start and block.start != 1 else ""
        items_html: list[str] = []
        for item in block.items:
            text = _render_inlines_html(item.inlines, ctx)
            sub = ""
            if item.children:
                sub_items = "\n".join(
                    f"<li>{_render_inlines_html(c.inlines, ctx)}</li>" for c in item.children
                )
                sub = f"\n<ul>\n{sub_items}\n</ul>"
            items_html.append(f"<li>{text}{sub}</li>")
        return f"<{tag}{bid}{start_attr}>\n" + "\n".join(items_html) + f"\n</{tag}>"

    if isinstance(block, FootnoteBlock):
        bid = _bid_attr(block, ctx)
        inner = " ".join(
            _render_primary_html(b, ctx) or "" for b in block.content
        ).strip()
        return f'<div class="fn"{bid} id="fn-{block.ref}"><sup>{block.ref}</sup> {inner}</div>'

    return None


def _para_style(block: Block) -> str:
    """ParagraphBlock/HeadingBlock의 format에서 CSS 스타일 추출."""
    fmt = getattr(block, "format", None)
    if not fmt:
        return ""
    parts: list[str] = []
    if fmt.alignment and fmt.alignment != "left":
        parts.append(f"text-align:{fmt.alignment}")
    if fmt.line_spacing:
        try:
            val = _parse_line_spacing(fmt.line_spacing)
            if abs(val - 1.6) > 0.05:
                parts.append(f"line-height:{val:.2f}")
        except (ValueError, TypeError):
            pass

    def _sane_mm(val: Any) -> bool:
        """Check whether a dimension value is within a sane range."""
        try:
            return abs(_to_float(val)) < 500
        except (ValueError, TypeError):
            return False

    if fmt.space_before and _sane_mm(fmt.space_before):
        parts.append(f"margin-top:{_to_css_val(fmt.space_before)}")
    if fmt.space_after and _sane_mm(fmt.space_after):
        parts.append(f"margin-bottom:{_to_css_val(fmt.space_after)}")
    if fmt.indent_left and _sane_mm(fmt.indent_left):
        parts.append(f"padding-left:{_to_css_val(fmt.indent_left)}")
    if fmt.indent_right and _sane_mm(fmt.indent_right):
        parts.append(f"padding-right:{_to_css_val(fmt.indent_right)}")
    if fmt.indent_first and _sane_mm(fmt.indent_first):
        parts.append(f"text-indent:{_to_css_val(fmt.indent_first)}")
    if getattr(fmt, "background_color", None):
        parts.append(f"background:{fmt.background_color}")
    for side in ("top", "bottom", "left", "right"):
        bval = getattr(fmt, f"border_{side}", None)
        if bval:
            parts.append(f"border-{side}:{bval}")
    return ";".join(parts)


def _render_inlines_html(inlines: list[Any], ctx: _HtmlCtx | None = None) -> str:
    """인라인을 HTML로 렌더링. ctx가 있으면 font-size/font-family도 적용."""
    merged = _merge_adjacent_inlines(inlines)
    rich = ctx is not None
    parts: list[str] = []
    for il in merged:
        if isinstance(il, TextInline):
            text = _escape_html(il.text)
            if not text.strip():
                if text:
                    parts.append(text)
                continue
            if il.bold:
                text = f"<strong>{text}</strong>"
            if il.italic:
                text = f"<em>{text}</em>"
            if il.strikethrough:
                text = f"<del>{text}</del>"
            if il.underline:
                text = f"<u>{text}</u>"
            if rich:
                span_styles: list[str] = []
                if il.font_size:
                    span_styles.append(f"font-size:{_to_css_val(il.font_size)}")
                if il.font_name:
                    fallback = _font_fallback(il.font_name)
                    span_styles.append(f"font-family:'{il.font_name}'{fallback}")
                if hasattr(il, "color") and il.color and str(il.color) != "#000000":
                    span_styles.append(f"color:{il.color}")
                if hasattr(il, "background_color") and il.background_color:
                    span_styles.append(f"background:{il.background_color}")
                if hasattr(il, "letter_spacing") and il.letter_spacing:
                    span_styles.append(f"letter-spacing:{_to_css_val(il.letter_spacing)}")
                if span_styles:
                    ss = ";".join(span_styles)
                    text = f'<span style="{ss}">{text}</span>'
            parts.append(text)
        elif isinstance(il, LinkInline):
            parts.append(f'<a href="{_escape_html(il.url)}">{_escape_html(il.text)}</a>')
        elif isinstance(il, ImageInline):
            alt = _escape_html(il.alt or "")
            parts.append(f'<img src="{_escape_html(il.src)}" alt="{alt}" style="max-height:1.2em;vertical-align:middle">')
        elif isinstance(il, EquationInline):
            latex = il.latex or il.hwp_script or ""
            parts.append(f"\\({_escape_html(latex)}\\)")
        elif isinstance(il, FootnoteRefInline):
            if il.ref_id:
                parts.append(f'<sup><a href="#fn-{il.ref_id}">{il.number or il.ref_id}</a></sup>')
    return "".join(parts)


def _render_table_html(
    block: TableBlock, ctx: _HtmlCtx,
    dropcap: tuple[str, float] | None = None,
) -> str:
    """Render a TableBlock to an HTML table with cell formatting."""
    if not block.rows:
        return ""
    first_row = block.rows[0]
    total_width = sum(c.width for c in first_row.cells if c.width)
    dc_injected = False
    tbl_width_pt = None
    if block.position and block.position.width:
        tbl_width_pt = block.position.width
    elif total_width > 0:
        tbl_width_pt = total_width
    cw = ctx.content_width if ctx else 481.0
    if tbl_width_pt and tbl_width_pt >= cw * 0.95:
        tbl_style = f'width:{cw:.0f}pt'
    elif tbl_width_pt:
        tbl_style = f'width:{tbl_width_pt:.0f}pt'
    else:
        tbl_style = f'width:{cw:.0f}pt'
    bid = _bid_attr(block, ctx)
    lines: list[str] = [f'<table{bid} style="{tbl_style}">']
    for row in block.rows:
        lines.append("<tr>")
        for cell in row.cells:
            attrs = ""
            if cell.row_span > 1:
                attrs += f' rowspan="{cell.row_span}"'
            if cell.col_span > 1:
                attrs += f' colspan="{cell.col_span}"'
            cell_w_pt = cell.width if cell.width else None
            content = _render_cell_content_html(cell, ctx)
            cell_text_len = sum(
                len(il.text)
                for cb in cell.content
                if isinstance(cb, ParagraphBlock) and cb.inlines
                for il in cb.inlines if hasattr(il, "text")
            )
            if dropcap and not dc_injected and cell_text_len > 30:
                char, fs = dropcap
                span = (
                    f'<span style="float:left;font-size:{fs:.0f}pt;'
                    f'line-height:0.85;margin:0 8pt 0 0;padding-top:4pt">'
                    f'{_escape_html(char)}</span>'
                )
                content = span + content
                dc_injected = True
            cell_style = _cell_style(cell)
            if cell_w_pt:
                cell_style = f"width:{cell_w_pt:.1f}pt;{cell_style}" if cell_style else f"width:{cell_w_pt:.1f}pt"
            style_attr = f' style="{cell_style}"' if cell_style else ""
            lines.append(f"<td{attrs}{style_attr}>{content}</td>")
        lines.append("</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _cell_style(cell: TableCell) -> str:
    """Build inline CSS style string for a table cell."""
    parts: list[str] = []
    fmt = cell.format if hasattr(cell, "format") and cell.format else None
    if fmt:
        for side in ("top", "bottom", "left", "right"):
            val = getattr(fmt, f"border_{side}", None)
            if val:
                parts.append(f"border-{side}:{val}")
        if fmt.background_color and fmt.background_color != "#ffffff":
            parts.append(f"background:{fmt.background_color}")
        if hasattr(fmt, "vertical_align") and fmt.vertical_align:
            parts.append(f"vertical-align:{fmt.vertical_align}")
        pad_parts = []
        for side in ("top", "right", "bottom", "left"):
            pv = getattr(fmt, f"padding_{side}", None)
            if pv:
                if isinstance(pv, (int, float)):
                    # numeric: assume pt
                    pad_parts.append(f"{pv:.1f}pt")
                elif hasattr(pv, "percent"):
                    pad_parts.append(f"{pv.percent:.1f}pt")
                elif isinstance(pv, str) and pv.endswith("mm"):
                    mm_val = float(pv[:-2])
                    pad_parts.append(f"{mm_val * 2.835:.1f}pt")
                elif isinstance(pv, str) and pv.endswith("pt"):
                    pad_parts.append(pv)
                else:
                    pad_parts.append("1pt")
            else:
                pad_parts.append("1pt")
        if any(p != "1pt" for p in pad_parts):
            parts.append(f"padding:{' '.join(pad_parts)}")
    if cell.height and cell.height > 0:
        h_pt = cell.height
        if h_pt > 20:
            parts.append(f"height:{h_pt:.1f}pt")
    if cell.content:
        for cb in cell.content:
            if hasattr(cb, "format") and cb.format and cb.format.alignment:
                parts.append(f"text-align:{cb.format.alignment}")
                break
    return ";".join(parts)


def _render_cell_content_html(cell: TableCell, ctx: _HtmlCtx) -> str:
    """Render table cell content blocks to HTML."""
    parts: list[str] = []
    for b in cell.content:
        if isinstance(b, ParagraphBlock):
            t = _render_inlines_html(b.inlines, ctx)
            if t:
                bid = _bid_attr(b, ctx)
                if bid:
                    t = f"<p{bid}>{t}</p>"
                parts.append(t)
        elif isinstance(b, EquationBlock):
            if b.latex:
                parts.append(f"\\({b.latex}\\)")
            elif b.hwp_script:
                parts.append(f"<!-- hwp-equation: {b.hwp_script} -->")
        elif isinstance(b, ImageBlock):
            src = ctx.resolve_src(b.src) if ctx.resolve_src else b.src
            alt = _escape_html(b.alt or "")
            style = "max-width:100%"
            if b.position and b.position.width:
                w = b.position.width
                h = (b.position.height or 0)
                style = f"width:{w:.0f}pt;height:{h:.0f}pt;max-width:100%"
            parts.append(f'<img src="{src}" alt="{alt}" style="{style}">')
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Markdown 렌더링 (기존 유지)
# ---------------------------------------------------------------------------


def render_md(doc: UdfDocument, *, embed_ids: bool = False) -> str:
    """Render a UdfDocument to a GFM Markdown string.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    embed_ids : bool, default False
        If True, emit ``<!-- id: blk-xxx -->`` comments before each
        block for round-trip ID preservation.

    Returns
    -------
    str
        GFM Markdown text with a trailing newline.
    """
    ctx = _MdCtx(embed_ids=embed_ids)
    parts: list[str] = []
    for block in doc.blocks:
        rendered = _render_block_md(block, ctx)
        if rendered is not None:
            parts.append(rendered)
    return "\n\n".join(p for p in parts if p) + "\n"


class _MdCtx:
    def __init__(self, *, embed_ids: bool) -> None:
        """Initialize Markdown rendering context."""
        self.embed_ids = embed_ids


# For backwards compat with any code using _Context
_Context = _MdCtx


def _render_block_md(block: Block, ctx: _MdCtx) -> str | None:
    """Render a single block to Markdown string."""
    id_comment = (
        f"<!-- id: {block.id} -->\n" if ctx.embed_ids and hasattr(block, "id") else ""
    )
    if isinstance(block, ParagraphBlock):
        inline_text = _render_inlines_md(block.inlines).lstrip()
        if not inline_text:
            return id_comment + "" if id_comment else None
        return id_comment + _escape_line_start(inline_text)
    if isinstance(block, HeadingBlock):
        prefix = "#" * max(1, min(6, block.level))
        return id_comment + f"{prefix} {_escape_md(block.text)}"
    if isinstance(block, TableBlock):
        return id_comment + _render_table_md(block, ctx)
    if isinstance(block, ListBlock):
        return id_comment + _render_list_md(block, ctx)
    if isinstance(block, ImageBlock):
        alt = block.alt or ""
        return id_comment + f"![{_escape_md(alt)}]({block.src})"
    if isinstance(block, FootnoteBlock):
        inner = "\n".join(
            p for p in (_render_block_md(b, ctx) or "" for b in block.content) if p
        )
        return id_comment + f"[^{block.ref}]: {inner}"
    if isinstance(block, EquationBlock):
        if block.latex:
            return id_comment + f"$$\n{block.latex}\n$$"
        if block.hwp_script:
            return id_comment + f"<!-- hwp-equation: {block.hwp_script} -->"
        return id_comment + "<!-- unsupported: equation -->"
    if isinstance(block, HorizontalRuleBlock):
        return id_comment + "---"
    if isinstance(block, (DrawingBlock, TextBoxBlock, ChartBlock, TextArtBlock)):
        return id_comment + f"<!-- unsupported: {block.type} -->"
    if isinstance(block, FieldBlock):
        text = _render_inlines_md(block.inlines) if block.inlines else (block.value or "")
        return id_comment + text if text else None
    if isinstance(block, (HeaderBlock, UnknownBlock)):
        return None
    return None


def _render_table_md(block: TableBlock, ctx: _MdCtx) -> str:
    """Render a TableBlock to an HTML table in Markdown output."""
    if not block.rows:
        return ""
    first_row = block.rows[0]
    total_width = sum(c.width for c in first_row.cells if c.width)
    lines: list[str] = ['<table width="100%">']
    for row in block.rows:
        lines.append("<tr>")
        for cell in row.cells:
            attrs = ""
            if cell.row_span > 1:
                attrs += f' rowspan="{cell.row_span}"'
            if cell.col_span > 1:
                attrs += f' colspan="{cell.col_span}"'
            if cell.width and total_width > 0:
                pct = round(cell.width / total_width * 100, 1)
                attrs += f' width="{pct}%"'
            content = _render_cell_content_md(cell, ctx)
            lines.append(f"<td{attrs}>{content}</td>")
        lines.append("</tr>")
    lines.append("</table>")
    return "\n".join(lines)


def _render_cell_content_md(cell: TableCell, ctx: _MdCtx) -> str:
    """Render table cell content for Markdown output."""
    parts: list[str] = []
    for b in cell.content:
        if isinstance(b, ParagraphBlock):
            t = _render_inlines_html(b.inlines)
            if t:
                parts.append(t)
        elif isinstance(b, EquationBlock):
            if b.latex:
                parts.append(f"$${b.latex}$$")
            elif b.hwp_script:
                parts.append(f"<!-- hwp-equation: {b.hwp_script} -->")
        elif isinstance(b, ImageBlock):
            alt = _escape_html(b.alt or "")
            style = "max-width:100%"
            if b.position and b.position.width:
                w = b.position.width
                h = (b.position.height or 0)
                style = f"width:{w:.0f}pt;height:{h:.0f}pt;max-width:100%"
            parts.append(f'<img src="{b.src}" alt="{alt}" style="{style}">')
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return "<br>".join(parts)


def _render_list_md(block: ListBlock, ctx: _MdCtx) -> str:
    """Render a ListBlock to Markdown list syntax."""
    lines: list[str] = []
    for idx, item in enumerate(block.items):
        prefix = f"{idx + 1}." if block.ordered else "-"
        text = _render_inlines_md(item.inlines)
        lines.append(f"{prefix} {text}")
        for child in item.children:
            child_text = _render_inlines_md(child.inlines)
            lines.append(f"  - {child_text}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 인라인 렌더러
# ---------------------------------------------------------------------------


def _render_inlines_md(inlines: list[Any]) -> str:
    """Render inline elements to Markdown with formatting markers."""
    merged = _merge_adjacent_inlines(inlines)
    parts: list[str] = []
    for il in merged:
        if isinstance(il, TextInline):
            text = _escape_md(il.text)
            lead = text[: len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()) :]
            inner = text.strip()
            if not inner:
                parts.append(text)
                continue
            if il.bold:
                inner = f"**{inner}**"
            if il.italic:
                inner = f"*{inner}*"
            if il.strikethrough:
                inner = f"~~{inner}~~"
            if il.underline:
                inner = f"<u>{inner}</u>"
            parts.append(lead + inner + trail)
        elif isinstance(il, LinkInline):
            parts.append(f"[{_escape_md(il.text)}]({il.url})")
        elif isinstance(il, ImageInline):
            alt = il.alt or ""
            parts.append(f"![{_escape_md(alt)}]({il.src})")
        elif isinstance(il, EquationInline):
            latex = il.latex or il.hwp_script or ""
            if latex:
                parts.append(f"${_escape_md(latex)}$")
        elif isinstance(il, FootnoteRefInline):
            if il.ref_id:
                parts.append(f"[^{il.ref_id}]")
    return "".join(parts)


# Backwards compat aliases
_render_inlines = _render_inlines_md

def _render_block(block: Block, ctx: _MdCtx) -> str | None:
    """Backwards-compatible alias for _render_block_md."""
    return _render_block_md(block, ctx)

def _render_table(block: TableBlock, ctx: Any) -> str:
    """Dispatch table rendering to HTML or Markdown based on context type."""
    if isinstance(ctx, _HtmlCtx):
        return _render_table_html(block, ctx)
    return _render_table_md(block, ctx)

def _render_cell_content(cell: TableCell, ctx: Any) -> str:
    """Dispatch cell content rendering to HTML or Markdown based on context type."""
    if isinstance(ctx, _HtmlCtx):
        return _render_cell_content_html(cell, ctx)
    return _render_cell_content_md(cell, ctx)

def _render_list(block: ListBlock, ctx: Any) -> str:
    """Backwards-compatible alias for _render_list_md."""
    return _render_list_md(block, ctx)


def _escape_html(text: str) -> str:
    """Escape HTML special characters (&, <, >, ")."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _merge_adjacent_inlines(inlines: list[Any]) -> list[Any]:
    """Merge consecutive TextInlines with identical formatting."""
    if not inlines:
        return []
    merged: list[Any] = [inlines[0]]
    for il in inlines[1:]:
        prev = merged[-1]
        if (
            isinstance(prev, TextInline)
            and isinstance(il, TextInline)
            and prev.bold == il.bold
            and prev.italic == il.italic
            and prev.underline == il.underline
            and prev.strikethrough == il.strikethrough
            and (prev.font_size or "") == (il.font_size or "")
            and (prev.font_name or "") == (il.font_name or "")
            and (prev.color or "") == (il.color or "")
            and (prev.background_color or "") == (il.background_color or "")
            and prev.superscript == il.superscript
            and prev.subscript == il.subscript
        ):
            merged[-1] = TextInline(
                text=prev.text + il.text,
                bold=prev.bold,
                italic=prev.italic,
                underline=prev.underline,
                strikethrough=prev.strikethrough,
                font_size=prev.font_size,
                font_name=prev.font_name,
                color=prev.color,
                background_color=prev.background_color,
                superscript=prev.superscript,
                subscript=prev.subscript,
                underline_color=prev.underline_color,
                letter_spacing=prev.letter_spacing,
                char_scale=prev.char_scale,
                char_offset=prev.char_offset,
                outline=prev.outline,
                shadow=prev.shadow,
            )
        else:
            merged.append(il)
    return merged


# ---------------------------------------------------------------------------
# 이스케이프
# ---------------------------------------------------------------------------

_MD_ESCAPE_CHARS = set(r"\`*_~|[]")

_LINE_START_ESCAPE_RE = re.compile(
    r"^(\d+)\."
    r"|^([#])"
    r"|^([-+])\s"
    r"|^(!)\["
    r"|^(>)"
)


def _escape_md(text: str) -> str:
    """Escape Markdown special characters with backslashes."""
    result: list[str] = []
    for ch in text:
        if ch in _MD_ESCAPE_CHARS:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)


def _escape_line_start(text: str) -> str:
    """Escape line-start patterns that could be misinterpreted as Markdown syntax."""
    m = _LINE_START_ESCAPE_RE.match(text)
    if not m:
        return text
    if m.group(1) is not None:
        return text[: m.end(1)] + "\\." + text[m.end() :]
    if m.group(2) is not None:
        return "\\" + text
    if m.group(3) is not None:
        return "\\" + text
    if m.group(4) is not None:
        return "\\" + text
    if m.group(5) is not None:
        return "\\" + text
    return text
