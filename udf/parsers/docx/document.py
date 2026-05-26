"""DOCX document.xml body parser -- converts XML elements to document blocks."""

from __future__ import annotations

import base64
from typing import Any

from lxml import etree

_HUGE_PARSER = etree.XMLParser(huge_tree=True)
_RECOVER_PARSER = etree.XMLParser(huge_tree=True, recover=True)

from udf.core.ids import make_block_id, make_verbatim_id
from udf.schema import (
    Block,
    CellFormat,
    EndnoteBlock,
    EquationBlock,
    EquationInline,
    FootnoteBlock,
    FootnoteRefInline,
    FooterBlock,
    HeaderBlock,
    HeadingBlock,
    ImageBlock,
    ImageInline,
    Inline,
    LinkInline,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    PositionInfo,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
)
from udf.pipeline.verbatim import VerbatimBlock
from udf.parsers.docx.styles import NS, StyleInfo, _parse_ppr, _parse_rpr, _twip_to_pt

_W = NS["w"]
_M = NS["m"]
_WPS = NS["wps"]


_block_counter: int = 0


def _next_id() -> str:
    """Generate the next sequential block ID."""
    global _block_counter
    _block_counter += 1
    return make_block_id(_block_counter)


def _next_vref() -> str:
    """Generate a verbatim ID for the current block."""
    global _block_counter
    return make_verbatim_id(_block_counter)


def parse_document_body(
    doc_bytes: bytes,
    style_info: StyleInfo,
) -> tuple[list[Block], dict[str, VerbatimBlock]]:
    """Parse the DOCX ``document.xml`` body into semantic blocks.

    Parameters
    ----------
    doc_bytes : bytes
        Raw XML content of ``word/document.xml``.
    style_info : StyleInfo
        Pre-parsed style, numbering, and relationship data.

    Returns
    -------
    tuple[list[Block], dict[str, VerbatimBlock]]
        Ordered list of blocks and a map of verbatim preservation data.
    """
    global _block_counter
    _block_counter = 0

    try:
        root = etree.fromstring(doc_bytes, parser=_HUGE_PARSER)
    except etree.XMLSyntaxError:
        root = etree.fromstring(doc_bytes, parser=_RECOVER_PARSER)

    _resolve_alternate_content(root)

    body = root.find("w:body", NS)
    if body is None:
        return [], {}

    blocks: list[Block] = []
    verbatim_map: dict[str, VerbatimBlock] = {}

    list_acc: list[tuple[str, int, ParagraphBlock]] = []

    for el in body:
        tag = _local_tag(el)

        if tag == "p":
            result, has_page_break, img_blocks = _parse_paragraph(el, style_info, verbatim_map)

            num_id, ilvl = _get_num_props(el)
            if num_id is not None:
                list_acc.append((num_id, ilvl, result))
                continue

            if list_acc:
                blocks.append(_flush_list(list_acc, style_info))
                list_acc = []

            heading_level = _detect_heading(el, style_info)
            if heading_level is not None:
                text = "".join(
                    i.text for i in result.inlines if isinstance(i, TextInline)
                )
                hb = HeadingBlock(
                    type="heading",
                    id=result.id,
                    level=heading_level,
                    text=text,
                    inlines=result.inlines,
                    format=result.format,
                    verbatim_ref=result.verbatim_ref,
                )
                blocks.append(hb)
            elif (
                len(result.inlines) == 1
                and isinstance(result.inlines[0], ImageInline)
                and len(img_blocks) == 1
            ):
                ib = img_blocks[0]
                ib.id = result.id
                ib.verbatim_ref = result.verbatim_ref
                blocks.append(ib)
            else:
                blocks.append(result)

            if has_page_break:
                blocks.append(PageBreakBlock(
                    type="page_break",
                    id=_next_id(),
                ))

        elif tag == "tbl":
            if list_acc:
                blocks.append(_flush_list(list_acc, style_info))
                list_acc = []
            tbl = _parse_table(el, style_info, verbatim_map)
            if tbl is not None:
                blocks.append(tbl)

        elif tag == "oMathPara":
            if list_acc:
                blocks.append(_flush_list(list_acc, style_info))
                list_acc = []
            eq = _parse_omath_para(el)
            if eq is not None:
                blocks.append(eq)

        elif tag == "oMath":
            # Top-level oMath (not inside a paragraph) → treat as display equation
            if list_acc:
                blocks.append(_flush_list(list_acc, style_info))
                list_acc = []
            text = _collect_omath_text(el)
            blocks.append(EquationBlock(
                type="equation",
                id=_next_id(),
                latex=text if text else None,
                display=True,
            ))

        elif tag == "sdt":
            if list_acc:
                blocks.append(_flush_list(list_acc, style_info))
                list_acc = []
            sdt_blocks = _parse_sdt_content(el, style_info, verbatim_map)
            blocks.extend(sdt_blocks)

        elif tag == "sectPr":
            pass

    if list_acc:
        blocks.append(_flush_list(list_acc, style_info))

    return blocks, verbatim_map


def _parse_sect_pr(sect_pr: etree._Element) -> dict[str, Any]:
    """Parse a w:sectPr element into a flat dict of section properties."""
    result: dict[str, Any] = {}

    pg_sz = sect_pr.find("w:pgSz", NS)
    if pg_sz is not None:
        w = pg_sz.get(f"{{{_W}}}w", "")
        h = pg_sz.get(f"{{{_W}}}h", "")
        if w:
            result["page_width"] = _twip_to_pt(w)
        if h:
            result["page_height"] = _twip_to_pt(h)
        orient = pg_sz.get(f"{{{_W}}}orient", "")
        if orient == "landscape":
            result["orientation"] = "landscape"

    pg_mar = sect_pr.find("w:pgMar", NS)
    if pg_mar is not None:
        for attr in ("top", "bottom", "left", "right", "header", "footer", "gutter"):
            val = pg_mar.get(f"{{{_W}}}{attr}", "")
            if val:
                result[f"margin_{attr}"] = _twip_to_pt(val)

    type_el = sect_pr.find("w:type", NS)
    if type_el is not None:
        val = type_el.get(f"{{{_W}}}val", "")
        _BREAK_MAP = {
            "nextPage": "next_page",
            "continuous": "continuous",
            "evenPage": "even_page",
            "oddPage": "odd_page",
            "nextColumn": "new_column",
        }
        if val in _BREAK_MAP:
            result["break_type"] = _BREAK_MAP[val]

    cols_el = sect_pr.find("w:cols", NS)
    if cols_el is not None:
        cols_data: dict[str, Any] = {}
        num = cols_el.get(f"{{{_W}}}num", "")
        if num:
            try:
                cols_data["count"] = int(num)
            except ValueError:
                pass
        space = cols_el.get(f"{{{_W}}}space", "")
        if space:
            cols_data["gap"] = _twip_to_pt(space)
        sep = cols_el.get(f"{{{_W}}}sep", "")
        if sep in ("true", "1", "on"):
            cols_data["separator"] = True
        eq_width = cols_el.get(f"{{{_W}}}equalWidth", "")
        if eq_width in ("false", "0", "off"):
            cols_data["same_width"] = False
        col_els = cols_el.findall("w:col", NS)
        if col_els:
            widths: list[float] = []
            for col_el in col_els:
                cw = col_el.get(f"{{{_W}}}w", "")
                if cw:
                    widths.append(_twip_to_pt(cw))
            if widths:
                cols_data["widths"] = widths
                cols_data["same_width"] = False
        if cols_data:
            result["columns"] = cols_data

    pg_num_type = sect_pr.find("w:pgNumType", NS)
    if pg_num_type is not None:
        start = pg_num_type.get(f"{{{_W}}}start", "")
        if start:
            try:
                result["start_page_number"] = int(start)
            except ValueError:
                pass
        fmt = pg_num_type.get(f"{{{_W}}}fmt", "")
        _NUM_FMT_MAP = {
            "decimal": "decimal",
            "lowerRoman": "roman_lower",
            "upperRoman": "roman_upper",
            "lowerLetter": "alpha_lower",
            "upperLetter": "alpha_upper",
        }
        if fmt in _NUM_FMT_MAP:
            result["page_number_format"] = _NUM_FMT_MAP[fmt]

    pg_borders = sect_pr.find("w:pgBorders", NS)
    if pg_borders is not None:
        for side in ("top", "bottom", "left", "right"):
            b_el = pg_borders.find(f"w:{side}", NS)
            if b_el is not None:
                color = b_el.get(f"{{{_W}}}color", "")
                sz = b_el.get(f"{{{_W}}}sz", "")
                style = b_el.get(f"{{{_W}}}val", "")
                if style and style not in ("none", "nil"):
                    w_pt = int(sz) / 8 if sz else 0.5
                    c = f"#{color}" if color and color != "auto" else "#000000"
                    result[f"border_{side}"] = f"{w_pt:.1f}pt solid {c}"

    ln_num = sect_pr.find("w:lnNumType", NS)
    if ln_num is not None:
        result["line_numbering"] = True

    return result


def extract_all_sections(doc_bytes: bytes) -> list[dict[str, Any]]:
    """Extract all section definitions from a DOCX document.

    DOCX defines sections via ``w:pPr/w:sectPr`` (intermediate) and
    ``w:body/w:sectPr`` (final).

    Parameters
    ----------
    doc_bytes : bytes
        Raw XML content of ``word/document.xml``.

    Returns
    -------
    list[dict[str, Any]]
        One dict per section with page size, margins, orientation, etc.
    """
    try:
        root = etree.fromstring(doc_bytes, parser=_HUGE_PARSER)
    except etree.XMLSyntaxError:
        root = etree.fromstring(doc_bytes, parser=_RECOVER_PARSER)
    body = root.find("w:body", NS)
    if body is None:
        return []

    sections: list[dict[str, Any]] = []

    for el in body:
        tag = _local_tag(el)
        if tag == "p":
            ppr = el.find("w:pPr", NS)
            if ppr is not None:
                sp = ppr.find("w:sectPr", NS)
                if sp is not None:
                    sections.append(_parse_sect_pr(sp))

    final_sp = body.find("w:sectPr", NS)
    if final_sp is not None:
        sections.append(_parse_sect_pr(final_sp))

    return sections


def extract_section_props(doc_bytes: bytes) -> dict[str, str]:
    """Extract page properties from the final ``w:sectPr`` element.

    Parameters
    ----------
    doc_bytes : bytes
        Raw XML content of ``word/document.xml``.

    Returns
    -------
    dict[str, str]
        Page width/height and margin values as strings (in twips).
    """
    sections = extract_all_sections(doc_bytes)
    if not sections:
        return {}
    result: dict[str, str] = {}
    final = sections[-1]
    for key in ("page_width", "page_height"):
        if key in final:
            result[key] = final[key]
    for attr in ("top", "bottom", "left", "right", "header", "footer", "gutter"):
        mk = f"margin_{attr}"
        if mk in final:
            result[mk] = final[mk]
    return result


# ---------------------------------------------------------------------------
# 단락
# ---------------------------------------------------------------------------


def _parse_paragraph(
    p_el: etree._Element,
    style_info: StyleInfo,
    verbatim_map: dict[str, VerbatimBlock],
) -> tuple[ParagraphBlock, bool, list[ImageBlock]]:
    """Returns (ParagraphBlock, has_page_break, image_blocks)."""
    bid = _next_id()
    vref = _next_vref()

    inlines, image_blocks = _collect_inlines(p_el, style_info)

    has_page_break = any(
        isinstance(i, TextInline) and i.text == "\f" for i in inlines
    )
    if has_page_break:
        inlines = [i for i in inlines if not (isinstance(i, TextInline) and i.text == "\f")]

    ppr = p_el.find("w:pPr", NS)
    fmt = _parse_ppr(ppr) if ppr is not None else None

    raw = base64.b64encode(etree.tostring(p_el, encoding="unicode").encode("utf-8")).decode()
    verbatim_map[vref] = VerbatimBlock(raw_bytes=raw)

    pb = ParagraphBlock(
        type="paragraph",
        id=bid,
        inlines=inlines,
        format=fmt,
        verbatim_ref=vref,
    )
    return pb, has_page_break, image_blocks


def _collect_inlines(
    p_el: etree._Element,
    style_info: StyleInfo,
) -> tuple[list[Inline], list[ImageBlock]]:
    inlines: list[Inline] = []
    image_blocks: list[ImageBlock] = []

    # w:fldChar state machine: tracks complex field regions
    # 0 = normal, 1 = in field (begin→separate), 2 = in display (separate→end)
    fld_depth = 0
    fld_state = 0
    fld_display: list[Inline] = []

    def _process_child(child: etree._Element) -> None:
        nonlocal fld_depth, fld_state, fld_display
        tag = _local_tag(child)

        if tag == "r":
            fld_char = child.find(f"{{{_W}}}fldChar")
            if fld_char is not None:
                fld_type = fld_char.get(f"{{{_W}}}fldCharType", "")
                if fld_type == "begin":
                    fld_depth += 1
                    if fld_depth == 1:
                        fld_state = 1
                        fld_display = []
                elif fld_type == "separate":
                    if fld_depth == 1:
                        fld_state = 2
                elif fld_type == "end":
                    if fld_depth == 1:
                        inlines.extend(fld_display)
                        fld_state = 0
                        fld_display = []
                    fld_depth = max(0, fld_depth - 1)
                return

            if fld_state == 1:
                return
            run_inlines, run_imgs = _parse_run(child, style_info)
            if fld_state == 2:
                fld_display.extend(run_inlines)
            else:
                inlines.extend(run_inlines)
            image_blocks.extend(run_imgs)

        elif tag == "hyperlink":
            if fld_state == 0:
                inlines.extend(_parse_hyperlink(child, style_info))
        elif tag == "ins":
            for sub in child:
                _process_child(sub)
        elif tag == "oMath":
            eq = _parse_omath_inline(child)
            if eq is not None:
                if fld_state == 2:
                    fld_display.append(eq)
                else:
                    inlines.append(eq)
        elif tag == "fldSimple":
            if fld_state == 0:
                inlines.extend(_parse_fld_simple(child))

    for child in p_el:
        _process_child(child)

    if fld_display:
        inlines.extend(fld_display)

    return inlines, image_blocks


def _parse_run(
    r_el: etree._Element,
    style_info: StyleInfo,
) -> tuple[list[Inline], list[ImageBlock]]:
    rpr = r_el.find("w:rPr", NS)
    props = _parse_rpr(rpr) if rpr is not None else {}

    inlines: list[Inline] = []
    image_blocks: list[ImageBlock] = []

    for child in r_el:
        tag = _local_tag(child)

        if tag == "t":
            text = child.text or ""
            if text:
                inlines.append(TextInline(
                    text=text,
                    bold=props.get("bold"),
                    italic=props.get("italic"),
                    underline=props.get("underline"),
                    strikethrough=props.get("strikethrough"),
                    color=props.get("color"),
                    background_color=props.get("background_color"),
                    font_name=props.get("font_name"),
                    font_size=props.get("font_size"),
                    superscript=props.get("superscript"),
                    subscript=props.get("subscript"),
                    small_caps=props.get("small_caps"),
                    hidden=props.get("hidden"),
                    letter_spacing=props.get("letter_spacing"),
                    outline=props.get("outline"),
                    shadow=props.get("shadow"),
                    underline_type=props.get("underline_type"),
                    underline_color=props.get("underline_color"),
                    strikeout_type=props.get("strikeout_type"),
                    highlight_color=props.get("highlight_color"),
                ))

        elif tag == "br":
            br_type = child.get(f"{{{_W}}}type", "")
            if br_type == "page":
                inlines.append(TextInline(text="\f"))
            else:
                inlines.append(TextInline(text="\n"))

        elif tag == "tab":
            inlines.append(TextInline(text="\t"))

        elif tag == "drawing":
            result = _parse_drawing(child, style_info)
            if isinstance(result, TextBoxBlock):
                for blk in result.content:
                    if isinstance(blk, ParagraphBlock):
                        inlines.extend(blk.inlines)
            elif result is not None:
                image_blocks.append(result)
                inlines.append(ImageInline(
                    src=result.src,
                    width=result.width,
                    height=result.height,
                ))

        elif tag == "footnoteReference":
            fn_id = child.get(f"{{{_W}}}id", "")
            if fn_id:
                inlines.append(FootnoteRefInline(
                    type="footnote_ref",
                    ref_id=fn_id,
                    number=int(fn_id) if fn_id.isdigit() else None,
                ))

        elif tag == "endnoteReference":
            en_id = child.get(f"{{{_W}}}id", "")
            if en_id:
                inlines.append(FootnoteRefInline(
                    type="footnote_ref",
                    ref_id=en_id,
                    number=int(en_id) if en_id.isdigit() else None,
                ))

    return inlines, image_blocks


def _parse_hyperlink(
    hl_el: etree._Element,
    style_info: StyleInfo,
) -> list[Inline]:
    rid = hl_el.get(f"{{{NS['r']}}}id", "")
    url = style_info.relationships.get(rid, "")

    text_parts: list[str] = []
    for r_el in hl_el.findall("w:r", NS):
        for t_el in r_el.findall("w:t", NS):
            text_parts.append(t_el.text or "")

    text = "".join(text_parts)
    if text and url:
        return [LinkInline(type="link", text=text, url=url)]
    elif text:
        return [TextInline(text=text)]
    return []


# ---------------------------------------------------------------------------
# 이미지
# ---------------------------------------------------------------------------


def _parse_drawing(
    drawing_el: etree._Element,
    style_info: StyleInfo,
) -> ImageBlock | TextBoxBlock | None:
    inline_el = drawing_el.find("wp:inline", NS)
    anchor_el = drawing_el.find("wp:anchor", NS)
    container = inline_el if inline_el is not None else anchor_el
    if container is None:
        return None

    # Check for text box content first
    txbx_content = _find_txbx_content(container)
    if txbx_content is not None:
        content: list[Block] = []
        for child in txbx_content:
            tag = _local_tag(child)
            if tag == "p":
                pb, _, _ = _parse_paragraph(child, style_info, {})
                content.append(pb)
            elif tag == "tbl":
                tbl = _parse_table(child, style_info, {})
                if tbl is not None:
                    content.append(tbl)
        return TextBoxBlock(
            type="text_box",
            id=_next_id(),
            content=content,
        )

    # 크기 (EMU → pt, 1pt = 12700 EMU)
    extent = container.find("wp:extent", NS)
    width_pt = None
    height_pt = None
    if extent is not None:
        cx = extent.get("cx", "")
        cy = extent.get("cy", "")
        if cx:
            try:
                width_pt = int(cx) / 12700
            except ValueError:
                pass
        if cy:
            try:
                height_pt = int(cy) / 12700
            except ValueError:
                pass

    # blip → rId → media path
    blip = container.find(".//a:blip", NS)
    if blip is None:
        return None

    embed_rid = blip.get(f"{{{NS['r']}}}embed", "")
    src = style_info.relationships.get(embed_rid, "")
    if src.startswith("media/"):
        src = f"bindata:{src[len('media/'):]}"
    elif not src.startswith("http"):
        src = f"bindata:{src}"

    position = None
    if anchor_el is not None:
        pos_h = anchor_el.find("wp:positionH", NS)
        pos_v = anchor_el.find("wp:positionV", NS)
        x = 0.0
        y = 0.0
        if pos_h is not None:
            offset = pos_h.find("wp:posOffset", NS)
            if offset is not None and offset.text:
                try:
                    x = int(offset.text) / 12700
                except ValueError:
                    pass
        if pos_v is not None:
            offset = pos_v.find("wp:posOffset", NS)
            if offset is not None and offset.text:
                try:
                    y = int(offset.text) / 12700
                except ValueError:
                    pass
        position = PositionInfo(
            x=x, y=y,
            width=width_pt, height=height_pt,
            like_char=False,
        )
    elif inline_el is not None:
        position = PositionInfo(
            width=width_pt, height=height_pt,
            like_char=True,
        )

    # crop (a:srcRect — values are thousandths of a percent)
    crop_left = crop_top = crop_right = crop_bottom = None
    src_rect = container.find(".//a:srcRect", NS)
    if src_rect is not None:
        for attr, name in (("l", "left"), ("t", "top"), ("r", "right"), ("b", "bottom")):
            val = src_rect.get(attr, "")
            if val:
                try:
                    parsed = int(val)
                    if parsed > 0:
                        if name == "left":
                            crop_left = parsed
                        elif name == "top":
                            crop_top = parsed
                        elif name == "right":
                            crop_right = parsed
                        else:
                            crop_bottom = parsed
                except ValueError:
                    pass

    # brightness/contrast (a:lum on blip)
    brightness = contrast = None
    if blip is not None:
        lum = blip.find("a:lum", NS)
        if lum is not None:
            b_val = lum.get("bright", "")
            c_val = lum.get("contrast", "")
            if b_val:
                try:
                    brightness = int(b_val)
                except ValueError:
                    pass
            if c_val:
                try:
                    contrast = int(c_val)
                except ValueError:
                    pass

    bid = _next_id()
    return ImageBlock(
        type="image",
        id=bid,
        src=src,
        width=width_pt,
        height=height_pt,
        position=position,
        crop_left=crop_left,
        crop_top=crop_top,
        crop_right=crop_right,
        crop_bottom=crop_bottom,
        brightness=brightness,
        contrast=contrast,
    )


# ---------------------------------------------------------------------------
# 테이블
# ---------------------------------------------------------------------------


_MAX_TABLE_DEPTH = 64


def _parse_table(
    tbl_el: etree._Element,
    style_info: StyleInfo,
    verbatim_map: dict[str, VerbatimBlock],
    _depth: int = 0,
) -> TableBlock | None:
    if _depth >= _MAX_TABLE_DEPTH:
        return None
    bid = _next_id()
    vref = _next_vref()

    rows_el = tbl_el.findall("w:tr", NS)
    if not rows_el:
        return None

    # tblPr 속성
    tbl_pr = tbl_el.find("w:tblPr", NS)
    cell_spacing = None
    if tbl_pr is not None:
        cs_el = tbl_pr.find("w:tblCellSpacing", NS)
        if cs_el is not None:
            cs_val = cs_el.get(f"{{{_W}}}w", "")
            cs_type = cs_el.get(f"{{{_W}}}type", "dxa")
            if cs_val and cs_type == "dxa":
                cell_spacing = _twip_to_pt(cs_val)

    # grid 정보 (열 너비)
    grid = tbl_el.find("w:tblGrid", NS)
    col_widths: list[float] = []
    if grid is not None:
        for gc in grid.findall("w:gridCol", NS):
            w_val = gc.get(f"{{{_W}}}w", "")
            col_widths.append(_twip_to_pt(w_val) if w_val else 0)

    # vMerge 추적용
    merge_state: dict[int, tuple[str, int]] = {}

    rows: list[TableRow] = []
    for row_el in rows_el:
        cells: list[TableCell] = []
        col_idx = 0

        for tc_el in row_el.findall("w:tc", NS):
            tc_pr = tc_el.find("w:tcPr", NS)

            # colSpan
            grid_span = 1
            if tc_pr is not None:
                gs_el = tc_pr.find("w:gridSpan", NS)
                if gs_el is not None:
                    try:
                        grid_span = int(gs_el.get(f"{{{_W}}}val", "1"))
                    except ValueError:
                        pass

            # vMerge
            v_merge = None
            if tc_pr is not None:
                vm_el = tc_pr.find("w:vMerge", NS)
                if vm_el is not None:
                    v_merge = vm_el.get(f"{{{_W}}}val", "continue")

            # 셀 너비
            cell_width = None
            if tc_pr is not None:
                w_el = tc_pr.find("w:tcW", NS)
                if w_el is not None:
                    w_type = w_el.get(f"{{{_W}}}type", "")
                    w_val = w_el.get(f"{{{_W}}}w", "")
                    if w_val and w_type == "dxa":
                        cell_width = _twip_to_pt(w_val)
            if cell_width is None and col_idx < len(col_widths):
                cell_width = sum(col_widths[col_idx:col_idx + grid_span])

            # 셀 서식
            cell_fmt = _parse_cell_format(tc_pr) if tc_pr is not None else None

            # vMerge="restart" → 새 병합 시작
            if v_merge == "restart":
                cell_id = _next_id()
                content = _parse_cell_content(tc_el, style_info, verbatim_map, _depth)
                merge_state[col_idx] = (cell_id, len(rows))
                cells.append(TableCell(
                    id=cell_id,
                    col_span=grid_span,
                    row_span=1,
                    width=cell_width,
                    content=content,
                    format=cell_fmt,
                ))
            elif v_merge is not None:
                # continue: 이전 restart 셀의 row_span 증가
                if col_idx in merge_state:
                    pass
                col_idx += grid_span
                continue
            else:
                # 병합 아님
                if col_idx in merge_state:
                    del merge_state[col_idx]
                cell_id = _next_id()
                content = _parse_cell_content(tc_el, style_info, verbatim_map, _depth)
                cells.append(TableCell(
                    id=cell_id,
                    col_span=grid_span,
                    row_span=1,
                    width=cell_width,
                    content=content,
                    format=cell_fmt,
                ))

            col_idx += grid_span

        if cells:
            rows.append(TableRow(cells=cells))

    # vMerge row_span 후처리
    _fixup_row_spans(rows, tbl_el, style_info)

    raw = base64.b64encode(etree.tostring(tbl_el, encoding="unicode").encode("utf-8")).decode()
    verbatim_map[vref] = VerbatimBlock(raw_bytes=raw)

    return TableBlock(
        type="table",
        id=bid,
        rows=rows,
        cell_spacing=cell_spacing,
        verbatim_ref=vref,
    )


def _fixup_row_spans(
    rows: list[TableRow],
    tbl_el: etree._Element,
    style_info: StyleInfo,
) -> None:
    """vMerge 기반으로 restart 셀의 row_span을 계산."""
    rows_el = tbl_el.findall("w:tr", NS)

    # col_idx → (시작 row_idx, 셀 참조) 추적
    active_merges: dict[int, tuple[int, TableCell]] = {}

    for row_idx, row_el in enumerate(rows_el):
        col_idx = 0
        cell_list_idx = 0

        if row_idx >= len(rows):
            break
        row_obj = rows[row_idx]

        for tc_el in row_el.findall("w:tc", NS):
            tc_pr = tc_el.find("w:tcPr", NS)
            gs_el = tc_pr.find("w:gridSpan", NS) if tc_pr is not None else None
            grid_span = 1
            if gs_el is not None:
                try:
                    grid_span = int(gs_el.get(f"{{{_W}}}val", "1"))
                except ValueError:
                    pass

            vm_el = tc_pr.find("w:vMerge", NS) if tc_pr is not None else None

            if vm_el is not None:
                val = vm_el.get(f"{{{_W}}}val", "continue")
                if val == "restart":
                    if cell_list_idx < len(row_obj.cells):
                        active_merges[col_idx] = (row_idx, row_obj.cells[cell_list_idx])
                    cell_list_idx += 1
                else:
                    if col_idx in active_merges:
                        start_row, cell_ref = active_merges[col_idx]
                        cell_ref.row_span = row_idx - start_row + 1
            else:
                if col_idx in active_merges:
                    del active_merges[col_idx]
                cell_list_idx += 1

            col_idx += grid_span


def _parse_cell_content(
    tc_el: etree._Element,
    style_info: StyleInfo,
    verbatim_map: dict[str, VerbatimBlock],
    _depth: int = 0,
) -> list[Block]:
    content: list[Block] = []
    for child in tc_el:
        tag = _local_tag(child)
        if tag == "p":
            pb, has_page_break, _ = _parse_paragraph(child, style_info, verbatim_map)
            content.append(pb)
            if has_page_break:
                content.append(PageBreakBlock(
                    type="page_break",
                    id=_next_id(),
                ))
        elif tag == "tbl":
            nested = _parse_table(child, style_info, verbatim_map, _depth + 1)
            if nested is not None:
                content.append(nested)
    return content


def _parse_cell_format(tc_pr: etree._Element) -> CellFormat | None:
    parts: dict[str, Any] = {}

    shd = tc_pr.find("w:shd", NS)
    if shd is not None:
        fill = shd.get(f"{{{_W}}}fill", "")
        if fill and fill.lower() not in ("auto", "ffffff"):
            parts["background_color"] = f"#{fill}"

    v_align = tc_pr.find("w:vAlign", NS)
    if v_align is not None:
        val = v_align.get(f"{{{_W}}}val", "")
        if val in ("top", "center", "bottom"):
            parts["vertical_align"] = "middle" if val == "center" else val

    borders = tc_pr.find("w:tcBorders", NS)
    if borders is not None:
        for side in ("top", "bottom", "left", "right"):
            b_el = borders.find(f"w:{side}", NS)
            if b_el is not None:
                color = b_el.get(f"{{{_W}}}color", "")
                sz = b_el.get(f"{{{_W}}}sz", "")
                style = b_el.get(f"{{{_W}}}val", "")
                if style and style != "none" and style != "nil":
                    w_pt = int(sz) / 8 if sz else 0.5
                    c = f"#{color}" if color and color != "auto" else "#000000"
                    parts[f"border_{side}"] = f"{w_pt:.1f}pt solid {c}"

    mar = tc_pr.find("w:tcMar", NS)
    if mar is not None:
        for side in ("top", "bottom", "left", "right"):
            tag = "start" if side == "left" else ("end" if side == "right" else side)
            m_el = mar.find(f"w:{tag}", NS)
            if m_el is None:
                m_el = mar.find(f"w:{side}", NS)
            if m_el is not None:
                val = m_el.get(f"{{{_W}}}w", "")
                if val:
                    parts[f"padding_{side}"] = _twip_to_pt(val)

    if not parts:
        return None
    return CellFormat(**parts)


# ---------------------------------------------------------------------------
# 리스트
# ---------------------------------------------------------------------------


def _get_num_props(p_el: etree._Element) -> tuple[str | None, int]:
    ppr = p_el.find("w:pPr", NS)
    if ppr is None:
        return None, 0
    num_pr = ppr.find("w:numPr", NS)
    if num_pr is None:
        return None, 0
    num_id_el = num_pr.find("w:numId", NS)
    ilvl_el = num_pr.find("w:ilvl", NS)
    num_id = num_id_el.get(f"{{{_W}}}val", "") if num_id_el is not None else ""
    ilvl_str = ilvl_el.get(f"{{{_W}}}val", "0") if ilvl_el is not None else "0"
    if not num_id or num_id == "0":
        return None, 0
    try:
        ilvl = int(ilvl_str)
    except ValueError:
        ilvl = 0
    return num_id, ilvl


def _flush_list(
    acc: list[tuple[str, int, ParagraphBlock]],
    style_info: StyleInfo,
) -> ListBlock:
    bid = _next_id()

    first_num_id = acc[0][0]
    ordered = True
    num_def = style_info.numbering_defs.get(first_num_id)
    if num_def and num_def.levels:
        lvl0 = num_def.levels[0]
        if lvl0.format == "bullet":
            ordered = False
    items: list[ListItem] = []

    for num_id, ilvl, pb in acc:
        li = ListItem(id=pb.id, inlines=pb.inlines, verbatim_ref=pb.verbatim_ref)
        if ilvl == 0:
            items.append(li)
        elif items:
            items[-1].children.append(li)
        else:
            items.append(li)

    return ListBlock(
        type="list",
        id=bid,
        ordered=ordered,
        items=items,
    )


# ---------------------------------------------------------------------------
# 헤딩 감지
# ---------------------------------------------------------------------------


def _detect_heading(
    p_el: etree._Element,
    style_info: StyleInfo,
) -> int | None:
    ppr = p_el.find("w:pPr", NS)
    if ppr is None:
        return None
    style_el = ppr.find("w:pStyle", NS)
    if style_el is None:
        return None
    style_id = style_el.get(f"{{{_W}}}val", "")
    return style_info.heading_style_levels.get(style_id)


# ---------------------------------------------------------------------------
# mc:AlternateContent
# ---------------------------------------------------------------------------


def _resolve_alternate_content(root: etree._Element) -> None:
    mc_ns = NS.get("mc", "")
    ac_tag = f"{{{mc_ns}}}AlternateContent"
    choice_tag = f"{{{mc_ns}}}Choice"
    fallback_tag = f"{{{mc_ns}}}Fallback"

    for ac in root.iter(ac_tag):
        parent = ac.getparent()
        if parent is None:
            continue
        choice = ac.find(choice_tag)
        fallback = ac.find(fallback_tag)
        replacement = choice if choice is not None else fallback
        if replacement is not None:
            idx = list(parent).index(ac)
            for child in list(replacement):
                parent.insert(idx, child)
                idx += 1
        parent.remove(ac)


# ---------------------------------------------------------------------------
# OMML 수식 (Phase 1)
# ---------------------------------------------------------------------------


def _collect_omath_text(omath_el: etree._Element) -> str:
    """Recursively collect all m:t text from an oMath element."""
    texts: list[str] = []
    for t_el in omath_el.iter(f"{{{_M}}}t"):
        if t_el.text:
            texts.append(t_el.text)
    return "".join(texts)


def _parse_omath_inline(omath_el: etree._Element) -> EquationInline | None:
    """m:oMath → EquationInline."""
    text = _collect_omath_text(omath_el)
    return EquationInline(latex=text if text else None)


def _parse_omath_para(omath_para_el: etree._Element) -> EquationBlock | None:
    """m:oMathPara → EquationBlock (display equation)."""
    texts: list[str] = []
    for omath in omath_para_el.iter(f"{{{_M}}}oMath"):
        texts.append(_collect_omath_text(omath))
    text = "".join(texts)
    return EquationBlock(
        type="equation",
        id=_next_id(),
        latex=text if text else None,
        display=True,
    )


# ---------------------------------------------------------------------------
# 각주/미주 XML 파싱 (Phase 2)
# ---------------------------------------------------------------------------


def parse_footnotes_xml(
    fn_bytes: bytes,
    style_info: StyleInfo,
) -> list[FootnoteBlock]:
    """Parse ``word/footnotes.xml`` into footnote blocks.

    Parameters
    ----------
    fn_bytes : bytes
        Raw XML content of the footnotes file.
    style_info : StyleInfo
        Pre-parsed document styles.

    Returns
    -------
    list[FootnoteBlock]
        One block per footnote (separator entries with id 0/-1 are skipped).
    """
    root = etree.fromstring(fn_bytes, parser=_HUGE_PARSER)
    _resolve_alternate_content(root)
    blocks: list[FootnoteBlock] = []
    for fn in root.findall("w:footnote", NS):
        fn_id = fn.get(f"{{{_W}}}id", "")
        # Skip separator footnotes (id 0 and -1)
        if fn_id in ("0", "-1"):
            continue
        content: list[Block] = []
        for p in fn.findall("w:p", NS):
            pb, _, _ = _parse_paragraph(p, style_info, {})
            content.append(pb)
        blocks.append(FootnoteBlock(
            type="footnote",
            id=_next_id(),
            ref=fn_id,
            content=content,
        ))
    return blocks


def parse_endnotes_xml(
    en_bytes: bytes,
    style_info: StyleInfo,
) -> list[EndnoteBlock]:
    """Parse ``word/endnotes.xml`` into endnote blocks.

    Parameters
    ----------
    en_bytes : bytes
        Raw XML content of the endnotes file.
    style_info : StyleInfo
        Pre-parsed document styles.

    Returns
    -------
    list[EndnoteBlock]
        One block per endnote (separator entries with id 0/-1 are skipped).
    """
    root = etree.fromstring(en_bytes, parser=_HUGE_PARSER)
    _resolve_alternate_content(root)
    blocks: list[EndnoteBlock] = []
    for en in root.findall("w:endnote", NS):
        en_id = en.get(f"{{{_W}}}id", "")
        if en_id in ("0", "-1"):
            continue
        content: list[Block] = []
        for p in en.findall("w:p", NS):
            pb, _, _ = _parse_paragraph(p, style_info, {})
            content.append(pb)
        blocks.append(EndnoteBlock(
            type="endnote",
            id=_next_id(),
            ref=en_id,
            content=content,
        ))
    return blocks


# ---------------------------------------------------------------------------
# 머리글/바닥글 XML 파싱 (Phase 3)
# ---------------------------------------------------------------------------


def parse_header_xml(
    hdr_bytes: bytes,
    style_info: StyleInfo,
    apply_to: str | None = None,
) -> HeaderBlock:
    """Parse a ``word/headerN.xml`` file into a HeaderBlock.

    Parameters
    ----------
    hdr_bytes : bytes
        Raw XML content of the header file.
    style_info : StyleInfo
        Pre-parsed document styles.
    apply_to : str | None, optional
        Scope indicator (e.g. "default", "first", "even").

    Returns
    -------
    HeaderBlock
        Parsed header block with its content.
    """
    root = etree.fromstring(hdr_bytes, parser=_HUGE_PARSER)
    _resolve_alternate_content(root)
    content: list[Block] = []
    for p in root.findall("w:p", NS):
        pb, _, _ = _parse_paragraph(p, style_info, {})
        content.append(pb)
    for tbl in root.findall("w:tbl", NS):
        tb = _parse_table(tbl, style_info, {})
        if tb is not None:
            content.append(tb)
    return HeaderBlock(
        type="header",
        id=_next_id(),
        apply_to=apply_to,
        content=content,
    )


def parse_footer_xml(
    ftr_bytes: bytes,
    style_info: StyleInfo,
    apply_to: str | None = None,
) -> FooterBlock:
    """Parse a ``word/footerN.xml`` file into a FooterBlock.

    Parameters
    ----------
    ftr_bytes : bytes
        Raw XML content of the footer file.
    style_info : StyleInfo
        Pre-parsed document styles.
    apply_to : str | None, optional
        Scope indicator (e.g. "default", "first", "even").

    Returns
    -------
    FooterBlock
        Parsed footer block with its content.
    """
    root = etree.fromstring(ftr_bytes, parser=_HUGE_PARSER)
    _resolve_alternate_content(root)
    content: list[Block] = []
    for p in root.findall("w:p", NS):
        pb, _, _ = _parse_paragraph(p, style_info, {})
        content.append(pb)
    for tbl in root.findall("w:tbl", NS):
        tb = _parse_table(tbl, style_info, {})
        if tb is not None:
            content.append(tb)
    return FooterBlock(
        type="footer",
        id=_next_id(),
        apply_to=apply_to,
        content=content,
    )


# ---------------------------------------------------------------------------
# 필드 (Phase 4)
# ---------------------------------------------------------------------------


def _parse_fld_simple(fld_el: etree._Element) -> list[Inline]:
    """w:fldSimple → TextInline with the cached display value."""
    texts: list[str] = []
    for r in fld_el.findall("w:r", NS):
        for t in r.findall("w:t", NS):
            texts.append(t.text or "")
    display = "".join(texts)
    if display:
        return [TextInline(text=display)]
    return []


def _parse_sdt_content(
    sdt_el: etree._Element,
    style_info: StyleInfo,
    verbatim_map: dict[str, VerbatimBlock],
) -> list[Block]:
    """w:sdt → extract content from w:sdtContent."""
    sdt_content = sdt_el.find("w:sdtContent", NS)
    if sdt_content is None:
        return []
    result: list[Block] = []
    for child in sdt_content:
        tag = _local_tag(child)
        if tag == "p":
            pb, has_page_break, _ = _parse_paragraph(child, style_info, verbatim_map)
            result.append(pb)
            if has_page_break:
                result.append(PageBreakBlock(type="page_break", id=_next_id()))
        elif tag == "tbl":
            tbl = _parse_table(child, style_info, verbatim_map)
            if tbl is not None:
                result.append(tbl)
    return result


# ---------------------------------------------------------------------------
# TextBox in drawings (Phase 4)
# ---------------------------------------------------------------------------


def _find_txbx_content(container: etree._Element) -> etree._Element | None:
    """Search for wps:txbx/w:txbxContent inside a drawing container."""
    # wps:txbx > w:txbxContent
    for txbx in container.iter(f"{{{_WPS}}}txbx"):
        txbx_content = txbx.find(f"{{{_W}}}txbxContent")
        if txbx_content is not None:
            return txbx_content
    return None


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------


def _local_tag(el: etree._Element) -> str:
    tag = el.tag
    if isinstance(tag, str) and "}" in tag:
        return tag.split("}", 1)[1]
    return str(tag)
