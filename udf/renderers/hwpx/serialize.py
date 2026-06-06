"""Document Model → HWPX section XML 직렬화.

UdfDocument 블록 트리를 OWPML section*.xml 형식으로 변환한다.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

from udf.core.schema import (
    Block,
    CodeBlock,
    DrawingBlock,
    EndnoteBlock,
    EquationBlock,
    EquationInline,
    FieldBlock,
    FooterBlock,
    FootnoteBlock,
    FootnoteRefInline,
    HeaderBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ImageInline,
    LinkInline,
    ListBlock,
    ListItem,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
    UdfDocument,
)

# ---------------------------------------------------------------------------
# OWPML 네임스페이스
# ---------------------------------------------------------------------------

_NSMAP = {
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
    "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
}

_HP = f"{{{_NSMAP['hp']}}}"
_HS = f"{{{_NSMAP['hs']}}}"
_HC = f"{{{_NSMAP['hc']}}}"
_HH = f"{{{_NSMAP['hh']}}}"

_HWPUNIT_PER_PT = 100

_LXML_XML_DECL = b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
_HANCOM_XML_DECL = b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'


def _fix_xml_decl(data: bytes) -> bytes:
    """lxml XML 선언을 한컴 호환 형식으로 변환 (newline 제거 포함)."""
    if data.startswith(_LXML_XML_DECL):
        rest = data[len(_LXML_XML_DECL):]
        if rest.startswith(b"\n"):
            rest = rest[1:]
        return _HANCOM_XML_DECL + rest
    return data

# 현재 직렬화 세션의 charPr 매핑 (TextInline 스타일 키 → charPr ID)
_char_pr_map: dict[tuple, int] = {}
_char_pr_list: list[dict] = []

# BlockFormat → paraPr ID 매핑 (BUG-148)
_para_pr_map: dict[tuple, int] = {}
_para_pr_extra: list[dict] = []
_STD_PP_COUNT = 21  # 기본 paraPr 수

# CellFormat → borderFill ID 매핑 (BUG-151)
_bf_map: dict[tuple, int] = {}
_bf_extra: list[dict] = []
_STD_BF_COUNT = 3  # 기본 borderFill 수 (header에 3개 고정)

_ALIGN_TO_HWPX = {"left": "LEFT", "right": "RIGHT", "center": "CENTER", "justify": "JUSTIFY"}


def _block_format_key(fmt) -> tuple:
    if fmt is None:
        return ()
    return (
        fmt.alignment or "justify",
        round((fmt.space_before or 0) * 100),
        round((fmt.space_after or 0) * 100),
        round((fmt.indent_left or 0) * 100),
        round((fmt.indent_right or 0) * 100),
        round((fmt.indent_first or 0) * 100),
        int(fmt.line_spacing.percent) if fmt.line_spacing and hasattr(fmt.line_spacing, "percent") else 160,
        fmt.page_break_before or False,
        fmt.widow_orphan or False,
    )


def _collect_para_formats(blocks: list) -> None:
    """수집: 고유한 BlockFormat 조합을 모아 paraPr ID를 할당."""
    global _para_pr_map, _para_pr_extra
    _para_pr_map.clear()
    _para_pr_extra.clear()
    next_id = _STD_PP_COUNT
    for block in blocks:
        fmt = getattr(block, "format", None)
        if fmt is None:
            continue
        key = _block_format_key(fmt)
        if not key or key in _para_pr_map:
            continue
        align, sb, sa, il, ir, fi, ls, pb, wo = key
        _para_pr_map[key] = next_id
        _para_pr_extra.append({
            "id": str(next_id),
            "align": _ALIGN_TO_HWPX.get(align, "JUSTIFY"),
            "space_before": str(sb),
            "space_after": str(sa),
            "indent_left": str(il),
            "indent_right": str(ir),
            "indent_first": str(fi),
            "ls_val": str(ls),
            "page_break_before": "1" if pb else "0",
            "widow_orphan": "1" if wo else "0",
        })
        next_id += 1


def _get_para_pr_id(block) -> str | None:
    """블록의 BlockFormat에 매칭되는 paraPr ID를 반환."""
    fmt = getattr(block, "format", None)
    if fmt is None:
        return None
    key = _block_format_key(fmt)
    if key and key in _para_pr_map:
        return str(_para_pr_map[key])
    return None


def _cell_bf_key(fmt) -> tuple:
    if fmt is None:
        return ()
    bg = str(fmt.background_color or "")
    bl = str(fmt.border_left or "")
    br = str(fmt.border_right or "")
    bt = str(fmt.border_top or "")
    bb = str(fmt.border_bottom or "")
    return (bg, bl, br, bt, bb)


def _collect_cell_border_fills(blocks: list) -> None:
    global _bf_map, _bf_extra
    _bf_map.clear()
    _bf_extra.clear()
    next_id = _STD_BF_COUNT + 1  # 1-based
    for block in blocks:
        if not hasattr(block, "rows"):
            continue
        for row in block.rows:
            for cell in row.cells:
                fmt = getattr(cell, "format", None)
                key = _cell_bf_key(fmt)
                if not key or key == ("", "", "", "", "") or key in _bf_map:
                    continue
                bg, bl, br, bt, bb = key
                _bf_map[key] = next_id
                _bf_extra.append({
                    "id": str(next_id),
                    "bg": bg,
                    "border_left": bl, "border_right": br,
                    "border_top": bt, "border_bottom": bb,
                })
                next_id += 1


def _get_cell_bf_id(fmt) -> str:
    key = _cell_bf_key(fmt)
    if key and key in _bf_map:
        return str(_bf_map[key])
    return "1"


def _inline_style_key(il: TextInline) -> tuple:
    """TextInline 서식에서 charPr dedup 키를 생성."""
    return (
        il.bold or False, il.italic or False,
        il.underline or False, il.strikethrough or False,
        il.outline or False, il.shadow or False,
        il.emboss or False, il.engrave or False,
        str(il.color or ""), str(il.font_size or ""),
        str(il.font_name or ""),
    )


def _collect_char_styles(blocks: list[Block]) -> None:
    """문서 블록에서 고유 TextInline 스타일을 수집하여 _char_pr_map/_char_pr_list에 저장."""
    global _char_pr_map, _char_pr_list
    _char_pr_map = {}
    _char_pr_list = []

    # ID 0 = 기본 스타일 (항상 존재)
    default_key = (False, False, False, False, False, False, False, False, "", "", "")
    _char_pr_map[default_key] = 0
    _char_pr_list.append({})

    def _visit(blks: list[Block]) -> None:
        for block in blks:
            inlines = getattr(block, "inlines", None) or []
            for il in inlines:
                if isinstance(il, TextInline):
                    k = _inline_style_key(il)
                    if k not in _char_pr_map:
                        _char_pr_map[k] = len(_char_pr_list)
                        _char_pr_list.append(_inline_to_char_pr(il))
            content = getattr(block, "content", None) or []
            if content:
                _visit(content)
            if hasattr(block, "rows"):
                for row in block.rows:
                    for cell in row.cells:
                        _visit(cell.content)
            items = getattr(block, "items", None) or []
            for item in items:
                for il in (item.inlines or []):
                    if isinstance(il, TextInline):
                        k = _inline_style_key(il)
                        if k not in _char_pr_map:
                            _char_pr_map[k] = len(_char_pr_list)
                            _char_pr_list.append(_inline_to_char_pr(il))

    _visit(blocks)

    _HEADING_SIZE = {1: 24.0, 2: 18.0, 3: 14.0, 4: 12.0, 5: 11.0, 6: 10.0}
    for block in blocks:
        if isinstance(block, HeadingBlock):
            level = max(1, min(block.level, 6))
            hil = TextInline(text="", bold=True, font_size=_HEADING_SIZE[level])
            k = _inline_style_key(hil)
            if k not in _char_pr_map:
                _char_pr_map[k] = len(_char_pr_list)
                _char_pr_list.append(_inline_to_char_pr(hil))


def _inline_to_char_pr(il: TextInline) -> dict:
    """TextInline → charPr 속성 dict (header.xml 생성용)."""
    props: dict = {}
    if il.bold:
        props["bold"] = True
    if il.italic:
        props["italic"] = True
    if il.underline:
        props["underline"] = True
    if il.strikethrough:
        props["strikethrough"] = True
    if il.outline:
        props["outline"] = True
    if il.shadow:
        props["shadow"] = True
    if il.emboss:
        props["emboss"] = True
    if il.engrave:
        props["engrave"] = True
    if il.color:
        c = str(il.color)
        if not c.startswith("#"):
            c = f"#{c}"
        props["textColor"] = c
    if il.font_size is not None:
        props["height"] = round(float(il.font_size) * 100)
    if il.font_name:
        props["font_name"] = il.font_name
    if il.letter_spacing:
        props["letter_spacing"] = int(il.letter_spacing)
    if il.char_scale and hasattr(il.char_scale, "percent"):
        props["char_scale"] = int(il.char_scale.percent)
    if il.superscript:
        props["superscript"] = True
    if il.subscript:
        props["subscript"] = True
    if il.highlight_color:
        sc = str(il.highlight_color)
        props["shadeColor"] = sc if sc.startswith("#") else f"#{sc}"
    if il.underline_color:
        uc = str(il.underline_color)
        props["underline_color"] = uc if uc.startswith("#") else f"#{uc}"
    return props


def _get_char_pr_id(il: TextInline) -> str:
    """TextInline에 대응하는 charPrIDRef 문자열을 반환."""
    k = _inline_style_key(il)
    return str(_char_pr_map.get(k, 0))


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def blocks_to_section_xml(blocks: list[Block], doc: UdfDocument) -> bytes:
    """Convert a block list into HWPX section XML bytes.

    Parameters
    ----------
    blocks : list[Block]
        Blocks to serialize.
    doc : UdfDocument
        Full document (for metadata and global_resources references).

    Returns
    -------
    bytes
        UTF-8 encoded section XML with XML declaration.
    """
    _collect_char_styles(blocks)
    _collect_para_formats(blocks)
    _collect_cell_border_fills(blocks)

    sec = etree.Element(f"{_HS}sec", nsmap=_NSMAP)

    secpr_para = _build_secpr_paragraph(doc)
    secpr_el = secpr_para.find(f".//{_HP}secPr", namespaces=None)
    if secpr_el is None:
        for child in secpr_para:
            inner = child.find(f"{_HP}secPr")
            if inner is not None:
                secpr_el = inner
                break

    merged_secpr = False
    for block in blocks:
        elements = _block_to_elements(block, doc)
        if not merged_secpr and elements and secpr_el is not None:
            first_el = elements[0]
            if first_el.tag == f"{_HP}p":
                secpr_run = etree.Element(f"{_HP}run")
                secpr_run.set("charPrIDRef", "0")
                secpr_run.append(secpr_el)
                first_el.insert(0, secpr_run)
                merged_secpr = True
        for el in elements:
            sec.append(el)

    if not merged_secpr:
        sec.insert(0, secpr_para)

    return _fix_xml_decl(etree.tostring(
        sec,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    ))


def build_minimal_header_xml(doc: UdfDocument) -> bytes:
    """Generate a minimal header.xml for From Scratch mode.

    Includes one default fontface, charPr, paraPr, and style entry.

    Parameters
    ----------
    doc : UdfDocument
        Document model (used for potential metadata references).

    Returns
    -------
    bytes
        UTF-8 encoded header XML.
    """
    root = etree.Element(f"{_HH}head", nsmap=_NSMAP)
    root.set("version", "1.5")
    root.set("secCnt", "1")

    begin_num = etree.SubElement(root, f"{_HH}beginNum")
    begin_num.set("page", "1")
    begin_num.set("footnote", "1")
    begin_num.set("endnote", "1")
    begin_num.set("pic", "1")
    begin_num.set("tbl", "1")
    begin_num.set("equation", "1")

    ref_list = etree.SubElement(root, f"{_HH}refList")

    _LANGS_UPPER = ("HANGUL", "LATIN", "HANJA", "JAPANESE", "OTHER", "SYMBOL", "USER")
    _LANGS_LOWER = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")

    fontfaces = etree.SubElement(ref_list, f"{_HH}fontfaces")
    fontfaces.set("itemCnt", "7")
    for lang in _LANGS_UPPER:
        ff = etree.SubElement(fontfaces, f"{_HH}fontface")
        ff.set("lang", lang)
        font = etree.SubElement(ff, f"{_HH}font")
        font.set("face", "함초롬돋움")

    border_fills = etree.SubElement(ref_list, f"{_HH}borderFills")
    border_fills.set("itemCnt", str(3 + len(_bf_extra)))
    for bf_id in ("1", "2", "3"):
        bf = etree.SubElement(border_fills, f"{_HH}borderFill")
        bf.set("id", bf_id)
        for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
            b = etree.SubElement(bf, f"{_HH}{side}")
            b.set("type", "NONE")
            b.set("width", "0.1 mm")
            b.set("color", "#000000")
    for bf_def in _bf_extra:
        bf = etree.SubElement(border_fills, f"{_HH}borderFill")
        bf.set("id", bf_def["id"])
        _side_keys = [("leftBorder", "border_left"), ("rightBorder", "border_right"),
                      ("topBorder", "border_top"), ("bottomBorder", "border_bottom")]
        for side_tag, side_key in _side_keys:
            b = etree.SubElement(bf, f"{_HH}{side_tag}")
            bval = bf_def.get(side_key, "")
            if bval:
                parts = bval.split()
                b.set("width", parts[0] if parts else "0.1 mm")
                b.set("type", "SOLID" if len(parts) >= 2 and parts[1] == "solid" else "NONE")
                b.set("color", parts[2] if len(parts) >= 3 else "#000000")
            else:
                b.set("type", "NONE")
                b.set("width", "0.1 mm")
                b.set("color", "#000000")
        bg = bf_def.get("bg", "")
        if bg:
            fc = etree.SubElement(bf, f"{_HH}fillBrush")
            wc = etree.SubElement(fc, f"{_HH}winBrush")
            wc.set("faceColor", bg if bg.startswith("#") else f"#{bg}")
            wc.set("hatchColor", "#FFFFFF")
            wc.set("alpha", "0")

    char_props = etree.SubElement(ref_list, f"{_HH}charProperties")
    char_props.set("itemCnt", str(len(_char_pr_list)))
    for cp_id, cp_dict in enumerate(_char_pr_list):
        cp = etree.SubElement(char_props, f"{_HH}charPr")
        cp.set("id", str(cp_id))
        cp.set("height", str(cp_dict.get("height", 1000)))
        cp.set("textColor", cp_dict.get("textColor", "#000000"))
        cp.set("shadeColor", cp_dict.get("shadeColor", "none"))
        cp.set("useFontSpace", "0")
        cp.set("useKerning", "0")
        cp.set("symMark", "NONE")
        cp.set("borderFillIDRef", "1")
        font_ref = etree.SubElement(cp, f"{_HH}fontRef")
        for lang in _LANGS_LOWER:
            font_ref.set(lang, "0")
        cs_val = str(cp_dict.get("char_scale", 100))
        ratio = etree.SubElement(cp, f"{_HH}ratio")
        for lang in _LANGS_LOWER:
            ratio.set(lang, cs_val)
        ls_val = str(cp_dict.get("letter_spacing", 0))
        spacing = etree.SubElement(cp, f"{_HH}spacing")
        for lang in _LANGS_LOWER:
            spacing.set(lang, ls_val)
        rel_sz = etree.SubElement(cp, f"{_HH}relSz")
        for lang in _LANGS_LOWER:
            rel_sz.set(lang, "100")
        offset = etree.SubElement(cp, f"{_HH}offset")
        for lang in _LANGS_LOWER:
            offset.set(lang, "0")
        if cp_dict.get("bold"):
            etree.SubElement(cp, f"{_HH}bold")
        if cp_dict.get("italic"):
            etree.SubElement(cp, f"{_HH}italic")
        ul = etree.SubElement(cp, f"{_HH}underline")
        ul_color = cp_dict.get("underline_color", "#000000")
        if not ul_color.startswith("#"):
            ul_color = f"#{ul_color}"
        if cp_dict.get("underline"):
            ul.set("type", "BOTTOM")
            ul.set("shape", "SOLID")
            ul.set("color", ul_color)
        else:
            ul.set("type", "NONE")
            ul.set("shape", "SOLID")
            ul.set("color", "#000000")
        st_el = etree.SubElement(cp, f"{_HH}strikeout")
        if cp_dict.get("strikethrough"):
            st_el.set("shape", "SOLID")
            st_el.set("color", "#000000")
        else:
            st_el.set("shape", "NONE")
            st_el.set("color", "#000000")
        ol = etree.SubElement(cp, f"{_HH}outline")
        ol.set("type", cp_dict.get("outline") and "SOLID" or "NONE")
        sh = etree.SubElement(cp, f"{_HH}shadow")
        sh.set("type", cp_dict.get("shadow") and "DROP" or "NONE")
        sh.set("color", "#C0C0C0")
        sh.set("offsetX", "10")
        sh.set("offsetY", "10")
        if cp_dict.get("emboss"):
            etree.SubElement(cp, f"{_HH}emboss")
        if cp_dict.get("engrave"):
            etree.SubElement(cp, f"{_HH}engrave")
        if cp_dict.get("superscript"):
            sup = etree.SubElement(cp, f"{_HH}supscript")
            sup.set("sz", "70")
            sup.set("raise", "30")
        if cp_dict.get("subscript"):
            sub = etree.SubElement(cp, f"{_HH}subscript")
            sub.set("sz", "70")
            sub.set("lower", "30")

    tab_props = etree.SubElement(ref_list, f"{_HH}tabProperties")
    tab_props.set("itemCnt", "1")
    tp = etree.SubElement(tab_props, f"{_HH}tabPr")
    tp.set("id", "0")
    tp.set("autoTabLeft", "0")
    tp.set("autoTabRight", "0")

    numberings = etree.SubElement(ref_list, f"{_HH}numberings")
    numberings.set("itemCnt", "1")
    nb = etree.SubElement(numberings, f"{_HH}numbering")
    nb.set("id", "1")
    nb.set("start", "0")
    for lvl in range(1, 8):
        ph = etree.SubElement(nb, f"{_HH}paraHead")
        ph.set("start", "1")
        ph.set("level", str(lvl))
        ph.set("align", "LEFT")
        ph.set("useInstWidth", "1")
        ph.set("autoIndent", "1")
        ph.set("widthAdjust", "0")
        ph.set("textOffsetType", "PERCENT")
        ph.set("textOffset", "50")
        ph.set("numFormat", "DIGIT" if lvl % 2 == 1 else "HANGUL_SYLLABLE")
        ph.set("charPrIDRef", "4294967295")
        ph.set("checkable", "0")

    _STD_PP_DEFS = [
        {"id": "0", "align": "JUSTIFY", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "1", "align": "JUSTIFY", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "2", "align": "JUSTIFY", "indent": "800", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "3", "align": "JUSTIFY", "indent": "1600", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "4", "align": "JUSTIFY", "indent": "2400", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "5", "align": "JUSTIFY", "indent": "3200", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "6", "align": "JUSTIFY", "indent": "4000", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "7", "align": "JUSTIFY", "indent": "4800", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "8", "align": "JUSTIFY", "indent": "5600", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "9", "align": "JUSTIFY", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "10", "align": "JUSTIFY", "ls_type": "PERCENT", "ls_val": "130"},
        {"id": "11", "align": "LEFT", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "12", "align": "LEFT", "indent": "600", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "13", "align": "LEFT", "indent": "900", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "14", "align": "LEFT", "indent": "1200", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "15", "align": "LEFT", "indent": "1500", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "16", "align": "JUSTIFY", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "17", "align": "JUSTIFY", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "18", "align": "JUSTIFY", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "19", "align": "JUSTIFY", "ls_type": "PERCENT", "ls_val": "160"},
        {"id": "20", "align": "CENTER", "ls_type": "PERCENT", "ls_val": "160"},
    ]
    all_pp_defs = list(_STD_PP_DEFS) + list(_para_pr_extra)
    para_props = etree.SubElement(ref_list, f"{_HH}paraProperties")
    para_props.set("itemCnt", str(len(all_pp_defs)))
    for ppd in all_pp_defs:
        pp = etree.SubElement(para_props, f"{_HH}paraPr")
        pp.set("id", ppd["id"])
        align = etree.SubElement(pp, f"{_HH}align")
        align.set("horizontal", ppd["align"])
        align.set("vertical", "BASELINE")
        heading = etree.SubElement(pp, f"{_HH}heading")
        heading.set("type", "NONE")
        heading.set("idRef", "0")
        heading.set("level", "0")
        bs = etree.SubElement(pp, f"{_HH}breakSetting")
        bs.set("breakLatinWord", "KEEP_WORD")
        bs.set("breakNonLatinWord", "KEEP_WORD")
        bs.set("widowOrphan", ppd.get("widow_orphan", "0"))
        bs.set("keepWithNext", "0")
        bs.set("keepLines", "0")
        bs.set("pageBreakBefore", ppd.get("page_break_before", "0"))
        bs.set("lineWrap", "BREAK")
        auto_sp = etree.SubElement(pp, f"{_HH}autoSpacing")
        auto_sp.set("eAsianEng", "0")
        auto_sp.set("eAsianNum", "0")
        etree.SubElement(pp, f"{_HH}switch")
        bdr = etree.SubElement(pp, f"{_HH}border")
        bdr.set("borderFillIDRef", "2")
        bdr.set("offsetLeft", "0")
        bdr.set("offsetRight", "0")
        bdr.set("offsetTop", "0")
        bdr.set("offsetBottom", "0")
        bdr.set("connect", "0")
        bdr.set("ignoreMargin", "0")
        has_margin = ppd.get("indent") or ppd.get("indent_left") or ppd.get("indent_first")
        if has_margin:
            margin = etree.SubElement(pp, f"{_HH}margin")
            margin.set("indent", ppd.get("indent_first") or ppd.get("indent", "0"))
            margin.set("left", ppd.get("indent_left", "0"))
            margin.set("right", ppd.get("indent_right", "0"))
        if ppd.get("space_before") or ppd.get("space_after"):
            sp = etree.SubElement(pp, f"{_HH}spacing")
            sp.set("before", ppd.get("space_before", "0"))
            sp.set("after", ppd.get("space_after", "0"))
        if ppd.get("ls_type") or ppd.get("ls_val"):
            ls = etree.SubElement(pp, f"{_HH}lineSpacing")
            ls.set("type", ppd.get("ls_type", "PERCENT"))
            ls.set("value", ppd.get("ls_val", "160"))

    _STD_STYLES = [
        {"id": "0", "type": "PARA", "name": "바탕글", "eng": "Normal", "pp": "0", "cp": "0"},
        {"id": "1", "type": "PARA", "name": "본문", "eng": "Body", "pp": "1", "cp": "0"},
        {"id": "2", "type": "PARA", "name": "개요 1", "eng": "Outline 1", "pp": "2", "cp": "0"},
        {"id": "3", "type": "PARA", "name": "개요 2", "eng": "Outline 2", "pp": "3", "cp": "0"},
        {"id": "4", "type": "PARA", "name": "개요 3", "eng": "Outline 3", "pp": "4", "cp": "0"},
        {"id": "5", "type": "PARA", "name": "개요 4", "eng": "Outline 4", "pp": "5", "cp": "0"},
        {"id": "6", "type": "PARA", "name": "개요 5", "eng": "Outline 5", "pp": "6", "cp": "0"},
        {"id": "7", "type": "PARA", "name": "개요 6", "eng": "Outline 6", "pp": "7", "cp": "0"},
        {"id": "8", "type": "PARA", "name": "개요 7", "eng": "Outline 7", "pp": "8", "cp": "0"},
        {"id": "9", "type": "PARA", "name": "개요 8", "eng": "Outline 8", "pp": "18", "cp": "0"},
        {"id": "10", "type": "PARA", "name": "개요 9", "eng": "Outline 9", "pp": "16", "cp": "0"},
        {"id": "11", "type": "PARA", "name": "개요 10", "eng": "Outline 10", "pp": "17", "cp": "0"},
        {"id": "12", "type": "CHAR", "name": "쪽 번호", "eng": "Page Number", "pp": "0", "cp": "1"},
        {"id": "13", "type": "PARA", "name": "머리말", "eng": "Header", "pp": "9", "cp": "0"},
        {"id": "14", "type": "PARA", "name": "각주", "eng": "Footnote", "pp": "10", "cp": "0"},
        {"id": "15", "type": "PARA", "name": "미주", "eng": "Endnote", "pp": "10", "cp": "0"},
        {"id": "16", "type": "PARA", "name": "메모", "eng": "Memo", "pp": "11", "cp": "0"},
        {"id": "17", "type": "PARA", "name": "차례 제목", "eng": "TOC Heading", "pp": "12", "cp": "0"},
        {"id": "18", "type": "PARA", "name": "차례 1", "eng": "TOC 1", "pp": "13", "cp": "0"},
        {"id": "19", "type": "PARA", "name": "차례 2", "eng": "TOC 2", "pp": "14", "cp": "0"},
        {"id": "20", "type": "PARA", "name": "차례 3", "eng": "TOC 3", "pp": "15", "cp": "0"},
        {"id": "21", "type": "PARA", "name": "캡션", "eng": "Caption", "pp": "19", "cp": "0"},
    ]
    styles = etree.SubElement(ref_list, f"{_HH}styles")
    styles.set("itemCnt", str(len(_STD_STYLES)))
    for sd in _STD_STYLES:
        st = etree.SubElement(styles, f"{_HH}style")
        st.set("id", sd["id"])
        st.set("type", sd["type"])
        st.set("name", sd["name"])
        st.set("engName", sd["eng"])
        st.set("paraPrIDRef", sd["pp"])
        st.set("charPrIDRef", sd["cp"])

    compat = etree.SubElement(root, f"{_HH}compatibleDocument")
    compat.set("targetProgram", "HWP201X")
    etree.SubElement(compat, f"{_HH}layoutCompatibility")

    doc_opt = etree.SubElement(root, f"{_HH}docOption")
    li = etree.SubElement(doc_opt, f"{_HH}linkinfo")
    li.set("path", "")
    li.set("pageInherit", "0")
    li.set("footnoteInherit", "0")

    tc = etree.SubElement(root, f"{_HH}trackchageConfig")
    tc.set("flags", "56")

    return _fix_xml_decl(etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    ))


def build_content_hpf(
    section_count: int = 1,
    bindata_names: list[str] | None = None,
) -> bytes:
    """Generate a content.hpf (OPF package file) for From Scratch mode.

    Parameters
    ----------
    section_count : int, default 1
        Number of section XML files to reference.
    bindata_names : list[str] or None
        List of BinData filenames (e.g. ["image1.jpg"]) to add to manifest.

    Returns
    -------
    bytes
        UTF-8 encoded OPF package XML.
    """
    _OPF = "http://www.idpf.org/2007/opf/"
    nsmap = {
        "ha": "http://www.hancom.co.kr/hwpml/2011/app",
        "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
        "hp10": "http://www.hancom.co.kr/hwpml/2016/paragraph",
        "hs": "http://www.hancom.co.kr/hwpml/2011/section",
        "hc": "http://www.hancom.co.kr/hwpml/2011/core",
        "hh": "http://www.hancom.co.kr/hwpml/2011/head",
        "hhs": "http://www.hancom.co.kr/hwpml/2011/history",
        "hm": "http://www.hancom.co.kr/hwpml/2011/master-page",
        "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
        "dc": "http://purl.org/dc/elements/1.1/",
        "opf": _OPF,
        "ooxmlchart": "http://www.hancom.co.kr/hwpml/2016/ooxmlchart",
        "hwpunitchar": "http://www.hancom.co.kr/hwpml/2016/HwpUnitChar",
        "epub": "http://www.idpf.org/2007/ops",
        "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
    }
    package = etree.Element(f"{{{_OPF}}}package", nsmap=nsmap)
    package.set("version", "")
    package.set("unique-identifier", "")
    package.set("id", "")

    metadata = etree.SubElement(package, f"{{{_OPF}}}metadata")
    title = etree.SubElement(metadata, f"{{{_OPF}}}title")
    title.text = ""
    lang = etree.SubElement(metadata, f"{{{_OPF}}}language")
    lang.text = "ko"

    manifest = etree.SubElement(package, f"{{{_OPF}}}manifest")

    item = etree.SubElement(manifest, f"{{{_OPF}}}item")
    item.set("id", "header")
    item.set("href", "Contents/header.xml")
    item.set("media-type", "application/xml")

    for i in range(section_count):
        item = etree.SubElement(manifest, f"{{{_OPF}}}item")
        item.set("id", f"section{i}")
        item.set("href", f"Contents/section{i}.xml")
        item.set("media-type", "application/xml")

    if bindata_names:
        _EXT_MIME = {"jpg": "image/jpg", "jpeg": "image/jpeg", "png": "image/png",
                     "gif": "image/gif", "bmp": "image/bmp", "tif": "image/tiff"}
        for bname in bindata_names:
            base = bname.rsplit(".", 1)[0]
            ext = bname.rsplit(".", 1)[-1].lower() if "." in bname else ""
            item = etree.SubElement(manifest, f"{{{_OPF}}}item")
            item.set("id", base)
            item.set("href", f"BinData/{bname}")
            item.set("media-type", _EXT_MIME.get(ext, "application/octet-stream"))
            item.set("isEmbeded", "1")

    item = etree.SubElement(manifest, f"{{{_OPF}}}item")
    item.set("id", "settings")
    item.set("href", "settings.xml")
    item.set("media-type", "application/xml")

    spine = etree.SubElement(package, f"{{{_OPF}}}spine")
    ref = etree.SubElement(spine, f"{{{_OPF}}}itemref")
    ref.set("idref", "header")
    ref.set("linear", "yes")
    for i in range(section_count):
        ref = etree.SubElement(spine, f"{{{_OPF}}}itemref")
        ref.set("idref", f"section{i}")
        ref.set("linear", "yes")

    return _fix_xml_decl(etree.tostring(
        package,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    ))


def build_container_xml() -> bytes:
    """Generate META-INF/container.xml for From Scratch mode.

    Returns
    -------
    bytes
        UTF-8 encoded container XML pointing to Contents/content.hpf.
    """
    _OCF = "urn:oasis:names:tc:opendocument:xmlns:container"
    nsmap = {
        "ocf": _OCF,
        "hpf": "http://www.hancom.co.kr/schema/2011/hpf",
    }
    container = etree.Element(f"{{{_OCF}}}container", nsmap=nsmap)
    rootfiles = etree.SubElement(container, f"{{{_OCF}}}rootfiles")

    rf1 = etree.SubElement(rootfiles, f"{{{_OCF}}}rootfile")
    rf1.set("full-path", "Contents/content.hpf")
    rf1.set("media-type", "application/hwpml-package+xml")

    rf2 = etree.SubElement(rootfiles, f"{{{_OCF}}}rootfile")
    rf2.set("full-path", "Preview/PrvText.txt")
    rf2.set("media-type", "text/plain")

    rf3 = etree.SubElement(rootfiles, f"{{{_OCF}}}rootfile")
    rf3.set("full-path", "META-INF/container.rdf")
    rf3.set("media-type", "application/rdf+xml")

    return _fix_xml_decl(etree.tostring(
        container,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    ))


def build_version_xml() -> bytes:
    """Generate version.xml for From Scratch mode.

    Returns
    -------
    bytes
        UTF-8 encoded version XML with HWPML version metadata.
    """
    nsmap = {"hv": "http://www.hancom.co.kr/hwpml/2011/version"}
    root = etree.Element(
        "{http://www.hancom.co.kr/hwpml/2011/version}HCFVersion", nsmap=nsmap
    )
    root.set("tagetApplication", "WORDPROCESSOR")
    root.set("major", "5")
    root.set("minor", "1")
    root.set("micro", "1")
    root.set("buildNumber", "0")
    root.set("os", "1")
    root.set("xmlVersion", "1.5")
    root.set("application", "UDF")
    root.set("appVersion", "0.1.0")

    return _fix_xml_decl(etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    ))


def build_settings_xml() -> bytes:
    """Generate settings.xml for From Scratch mode."""
    _HA = "http://www.hancom.co.kr/hwpml/2011/app"
    nsmap = {
        "ha": _HA,
        "config": "urn:oasis:names:tc:opendocument:xmlns:config:1.0",
    }
    root = etree.Element(f"{{{_HA}}}HWPApplicationSetting", nsmap=nsmap)
    caret = etree.SubElement(root, f"{{{_HA}}}CaretPosition")
    caret.set("listIDRef", "0")
    caret.set("paraIDRef", "0")
    caret.set("pos", "0")
    return _fix_xml_decl(etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True,
    ))


def build_container_rdf(section_count: int = 1) -> bytes:
    """Generate META-INF/container.rdf for From Scratch mode."""
    _RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    _PKG = "http://www.hancom.co.kr/hwpml/2016/meta/pkg#"
    nsmap = {"rdf": _RDF}
    root = etree.Element(f"{{{_RDF}}}RDF", nsmap=nsmap)

    # header.xml
    desc = etree.SubElement(root, f"{{{_RDF}}}Description")
    desc.set(f"{{{_RDF}}}about", "")
    has_part = etree.SubElement(desc, f"{{{_PKG}}}hasPart")
    has_part.set(f"{{{_RDF}}}resource", "Contents/header.xml")

    desc2 = etree.SubElement(root, f"{{{_RDF}}}Description")
    desc2.set(f"{{{_RDF}}}about", "Contents/header.xml")
    rdf_type = etree.SubElement(desc2, f"{{{_RDF}}}type")
    rdf_type.set(f"{{{_RDF}}}resource", f"{_PKG}HeaderFile")

    # sections
    for i in range(section_count):
        desc_s = etree.SubElement(root, f"{{{_RDF}}}Description")
        desc_s.set(f"{{{_RDF}}}about", "")
        hp = etree.SubElement(desc_s, f"{{{_PKG}}}hasPart")
        hp.set(f"{{{_RDF}}}resource", f"Contents/section{i}.xml")

        desc_st = etree.SubElement(root, f"{{{_RDF}}}Description")
        desc_st.set(f"{{{_RDF}}}about", f"Contents/section{i}.xml")
        rt = etree.SubElement(desc_st, f"{{{_RDF}}}type")
        rt.set(f"{{{_RDF}}}resource", f"{_PKG}SectionFile")

    # document type
    desc_doc = etree.SubElement(root, f"{{{_RDF}}}Description")
    desc_doc.set(f"{{{_RDF}}}about", "")
    rt_doc = etree.SubElement(desc_doc, f"{{{_RDF}}}type")
    rt_doc.set(f"{{{_RDF}}}resource", f"{_PKG}Document")

    return _fix_xml_decl(etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True,
    ))


def build_manifest_xml() -> bytes:
    """Generate META-INF/manifest.xml for From Scratch mode."""
    _ODF = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
    nsmap = {"odf": _ODF}
    root = etree.Element(f"{{{_ODF}}}manifest", nsmap=nsmap)
    return _fix_xml_decl(etree.tostring(
        root, xml_declaration=True, encoding="UTF-8", standalone=True,
    ))


# ---------------------------------------------------------------------------
# 블록 → XML 요소 변환 (내부 함수)
# ---------------------------------------------------------------------------


def _block_to_elements(block: Block, doc: UdfDocument) -> list[etree._Element]:
    """단일 블록을 XML 요소 리스트로 변환한다.

    대부분은 1개 요소를 반환하지만, FootnoteBlock 등은 0개(참조 인라인에 포함)
    를 반환할 수 있다.
    """
    if isinstance(block, ParagraphBlock):
        return [_paragraph_to_xml(block, doc)]
    elif isinstance(block, HeadingBlock):
        return [_heading_to_xml(block, doc)]
    elif isinstance(block, TableBlock):
        return [_table_to_xml(block, doc)]
    elif isinstance(block, ImageBlock):
        return [_image_block_to_xml(block, doc)]
    elif isinstance(block, ListBlock):
        return _list_to_paragraphs(block, doc)
    elif isinstance(block, EquationBlock):
        return [_equation_block_to_xml(block, doc)]
    elif isinstance(block, (FootnoteBlock, EndnoteBlock)):
        return []
    elif isinstance(block, QuoteBlock):
        elements = []
        for child in block.content:
            elements.extend(_block_to_elements(child, doc))
        return elements if elements else [_empty_paragraph()]
    elif isinstance(block, CodeBlock):
        text = block.code or ""
        from udf.core.schema import TextInline as _TI
        lines = text.split("\n")
        result = []
        for line in lines:
            p = _paragraph_to_xml(
                ParagraphBlock(type="paragraph", id=block.id,
                               inlines=[_TI(text=line, font_name="Courier New")]),
                doc,
            )
            result.append(p)
        return result if result else [_empty_paragraph()]
    elif isinstance(block, HorizontalRuleBlock):
        return [_empty_paragraph()]
    elif isinstance(block, TextBoxBlock):
        elements: list[etree._Element] = []
        for child in block.content:
            elements.extend(_block_to_elements(child, doc))
        return elements if elements else [_empty_paragraph()]
    elif isinstance(block, (HeaderBlock, FooterBlock)):
        return []
    elif isinstance(block, DrawingBlock):
        elements = []
        for child in block.content:
            elements.extend(_block_to_elements(child, doc))
        for child_draw in getattr(block, "children", []):
            for cc in child_draw.content:
                elements.extend(_block_to_elements(cc, doc))
        return elements if elements else [_empty_paragraph()]
    elif isinstance(block, FieldBlock):
        if block.inlines:
            p = _paragraph_to_xml(
                ParagraphBlock(type="paragraph", id=block.id, inlines=block.inlines),
                doc,
            )
            return [p]
        return [_empty_paragraph()]
    else:
        return [_empty_paragraph()]


def _build_secpr_paragraph(doc: UdfDocument) -> etree._Element:
    """secPr을 포함하는 첫 번째 단락을 생성한다."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")

    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")

    sec_pr = etree.SubElement(run, f"{_HP}secPr")
    sec_pr.set("textDirection", "HORIZONTAL")
    sec_pr.set("spaceColumns", "1134")
    sec_pr.set("tabStop", "8000")
    sec_pr.set("tabStopVal", "4000")
    sec_pr.set("tabStopUnit", "HWPUNIT")
    sec_pr.set("outlineShapeIDRef", "1")
    sec_pr.set("memoShapeIDRef", "0")
    sec_pr.set("textVerticalWidthHead", "0")
    sec_pr.set("masterPageCnt", "0")

    grid = etree.SubElement(sec_pr, f"{_HP}grid")
    grid.set("lineGrid", "0")
    grid.set("charGrid", "0")
    grid.set("wonggojiFormat", "0")

    start_num = etree.SubElement(sec_pr, f"{_HP}startNum")
    start_num.set("pageStartsOn", "BOTH")
    start_num.set("page", "0")
    start_num.set("pic", "0")
    start_num.set("tbl", "0")
    start_num.set("equation", "0")

    visibility = etree.SubElement(sec_pr, f"{_HP}visibility")
    visibility.set("hideFirstHeader", "0")
    visibility.set("hideFirstFooter", "0")
    visibility.set("hideFirstMasterPage", "0")
    visibility.set("border", "SHOW_ALL")
    visibility.set("fill", "SHOW_ALL")
    visibility.set("hideFirstPageNum", "0")
    visibility.set("hideFirstEmptyLine", "0")
    visibility.set("showLineNumber", "0")

    line_num = etree.SubElement(sec_pr, f"{_HP}lineNumberShape")
    line_num.set("restartType", "0")
    line_num.set("countBy", "0")
    line_num.set("distance", "0")
    line_num.set("startNumber", "0")

    # pagePr — A4 기본값 (단위: HWPUNIT, 1pt = 100 HWPUNIT)
    width = 59528
    height = 84186
    margin_top = 5668
    margin_bottom = 4252
    margin_left = 8504
    margin_right = 8504
    margin_header = 4252
    margin_footer = 4252

    if doc.metadata and doc.metadata.sections:
        sec = doc.metadata.sections[0]
        if sec.page_width:
            width = _pt_to_hwpunit(sec.page_width)
        if sec.page_height:
            height = _pt_to_hwpunit(sec.page_height)
        if sec.margins:
            margin_top = _pt_to_hwpunit(sec.margins.top)
            margin_bottom = _pt_to_hwpunit(sec.margins.bottom)
            margin_left = _pt_to_hwpunit(sec.margins.left)
            margin_right = _pt_to_hwpunit(sec.margins.right)
        if sec.header_margin:
            margin_header = _pt_to_hwpunit(sec.header_margin)
        if sec.footer_margin:
            margin_footer = _pt_to_hwpunit(sec.footer_margin)

    landscape = False
    if doc.metadata and doc.metadata.sections:
        sec = doc.metadata.sections[0]
        if sec.orientation == "landscape":
            landscape = True

    page_pr = etree.SubElement(sec_pr, f"{_HP}pagePr")
    page_pr.set("landscape", "true" if landscape else "WIDELY")
    page_pr.set("width", str(width))
    page_pr.set("height", str(height))
    page_pr.set("gutterType", "LEFT_ONLY")

    gutter_val = "0"
    if doc.metadata and doc.metadata.sections:
        sec = doc.metadata.sections[0]
        if sec.gutter:
            gutter_val = str(_pt_to_hwpunit(sec.gutter))

    margin = etree.SubElement(page_pr, f"{_HP}margin")
    margin.set("header", str(margin_header))
    margin.set("footer", str(margin_footer))
    margin.set("gutter", gutter_val)
    margin.set("left", str(margin_left))
    margin.set("right", str(margin_right))
    margin.set("top", str(margin_top))
    margin.set("bottom", str(margin_bottom))

    if doc.metadata and doc.metadata.sections:
        sec = doc.metadata.sections[0]
        if sec.columns and sec.columns.count > 1:
            col_el = etree.SubElement(page_pr, f"{_HP}multiColumn")
            col_el.set("count", str(sec.columns.count))
            if sec.columns.gap:
                col_el.set("gap", str(_pt_to_hwpunit(sec.columns.gap)))
            col_el.set("sameWidth", "1" if sec.columns.same_width else "0")

    for note_tag, place, between in (
        ("footNotePr", "EACH_COLUMN", "283"),
        ("endNotePr", "END_OF_DOCUMENT", "0"),
    ):
        note_pr = etree.SubElement(sec_pr, f"{_HP}{note_tag}")
        anf = etree.SubElement(note_pr, f"{_HP}autoNumFormat")
        anf.set("type", "DIGIT")
        anf.set("userChar", "")
        anf.set("prefixChar", "")
        anf.set("suffixChar", ")")
        anf.set("supscript", "0")
        nl = etree.SubElement(note_pr, f"{_HP}noteLine")
        nl.set("length", "-1")
        nl.set("type", "SOLID")
        nl.set("width", "0.12 mm")
        nl.set("color", "#000000")
        ns = etree.SubElement(note_pr, f"{_HP}noteSpacing")
        ns.set("betweenNotes", between)
        ns.set("belowLine", "567")
        ns.set("aboveLine", "850")
        nb = etree.SubElement(note_pr, f"{_HP}numbering")
        nb.set("type", "CONTINUOUS")
        nb.set("newNum", "1")
        pl = etree.SubElement(note_pr, f"{_HP}placement")
        pl.set("place", place)
        pl.set("beneathText", "0")

    for pbf_type in ("BOTH", "EVEN", "ODD"):
        pbf = etree.SubElement(sec_pr, f"{_HP}pageBorderFill")
        pbf.set("type", pbf_type)
        pbf.set("borderFillIDRef", "1")
        pbf.set("textBorder", "PAPER")
        pbf.set("headerInside", "0")
        pbf.set("footerInside", "0")
        pbf.set("fillArea", "PAPER")
        off = etree.SubElement(pbf, f"{_HP}offset")
        off.set("left", "1417")
        off.set("right", "1417")
        off.set("top", "1417")
        off.set("bottom", "1417")

    return p


def _paragraph_to_xml(
    block: ParagraphBlock, doc: UdfDocument
) -> etree._Element:
    """Convert a ParagraphBlock to an <hp:p> element."""
    p = etree.Element(f"{_HP}p")

    para_pr_id = "0"
    style_id = "0"
    if (
        doc.verbatim
        and doc.verbatim.format == "hwpx"
        and block.verbatim_ref
        and block.verbatim_ref in doc.verbatim.blocks
    ):
        vb = doc.verbatim.blocks[block.verbatim_ref]
        if vb.decoded:
            para_pr_id = str(vb.decoded.get("paraPrIDRef", 0))
            style_id = str(vb.decoded.get("styleIDRef", 0))

    dyn_pp_id = _get_para_pr_id(block)
    if dyn_pp_id and para_pr_id == "0":
        para_pr_id = dyn_pp_id
    p.set("paraPrIDRef", para_pr_id)
    p.set("styleIDRef", style_id)
    pb = "1" if getattr(getattr(block, "format", None), "page_break_before", False) else "0"
    p.set("pageBreak", pb)
    p.set("columnBreak", "0")
    p.set("merged", "0")

    _append_inlines_as_runs(p, block.inlines, doc)
    _add_linesegarray(p)
    return p


def _add_linesegarray(p: etree._Element) -> None:
    """Append a minimal <hp:linesegarray> to a paragraph element."""
    lsa = etree.SubElement(p, f"{_HP}linesegarray")
    ls = etree.SubElement(lsa, f"{_HP}lineseg")
    ls.set("textpos", "0")
    ls.set("vertpos", "0")
    ls.set("vertsize", "1000")
    ls.set("textheight", "100")
    ls.set("baseline", "85")
    ls.set("spacing", "60")
    ls.set("horzpos", "0")
    ls.set("horzsize", "42520")
    ls.set("flags", "393216")


_HWPX_HEADING_STYLE = [2, 3, 4, 5, 6, 7]


def _heading_to_xml(
    block: HeadingBlock, doc: UdfDocument
) -> etree._Element:
    """Convert a HeadingBlock to an <hp:p> with outline style reference."""
    p = etree.Element(f"{_HP}p")

    para_pr_id = "0"
    style_id = "0"
    if (
        doc.verbatim
        and doc.verbatim.format == "hwpx"
        and block.verbatim_ref
        and block.verbatim_ref in doc.verbatim.blocks
    ):
        vb = doc.verbatim.blocks[block.verbatim_ref]
        if vb.decoded:
            para_pr_id = str(vb.decoded.get("paraPrIDRef", 0))
            style_id = str(vb.decoded.get("styleIDRef", 0))
    else:
        level = max(1, min(block.level, 6))
        style_id = str(_HWPX_HEADING_STYLE[level - 1])
        para_pr_id = str(level + 1)

    p.set("paraPrIDRef", para_pr_id)
    p.set("styleIDRef", style_id)
    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")

    _HWPX_HEADING_SIZE = {1: 24.0, 2: 18.0, 3: 14.0, 4: 12.0, 5: 11.0, 6: 10.0}
    level = max(1, min(block.level, 6))
    heading_size = _HWPX_HEADING_SIZE[level]

    inlines = block.inlines
    if not inlines and block.text:
        inlines = [TextInline(text=block.text, bold=True, font_size=heading_size)]
    elif inlines:
        sized = []
        for il in inlines:
            if isinstance(il, TextInline) and not il.font_size:
                sized.append(TextInline(
                    text=il.text, bold=il.bold if il.bold is not None else True,
                    italic=il.italic, underline=il.underline,
                    color=il.color, font_size=heading_size, font_name=il.font_name,
                ))
            else:
                sized.append(il)
        inlines = sized

    _append_inlines_as_runs(p, inlines, doc)
    _add_linesegarray(p)
    return p


def _table_to_xml(block: TableBlock, doc: UdfDocument) -> etree._Element:
    """Convert a TableBlock to an <hp:p> containing <hp:tbl>."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")

    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")

    row_cnt = len(block.rows)
    col_cnt = max((len(r.cells) for r in block.rows), default=0)

    tbl = etree.SubElement(run, f"{_HP}tbl")
    tbl.set("id", "0")
    tbl.set("zOrder", "0")
    tbl.set("numberingType", "TABLE")
    tbl.set("textWrap", "TOP_AND_BOTTOM")
    tbl.set("textFlow", "BOTH_SIDES")
    tbl.set("lock", "0")
    tbl.set("dropcapstyle", "None")
    tbl.set("pageBreak", "NONE")
    tbl.set("repeatHeader", "1" if block.repeat_header else "0")
    tbl.set("rowCnt", str(row_cnt))
    tbl.set("colCnt", str(col_cnt))
    tbl.set("cellSpacing", "0")
    tbl.set("borderFillIDRef", "1")
    tbl.set("noAdjust", "0")

    width_hu = 51008
    height_hu = 0
    if block.position and block.position.width:
        width_hu = round(block.position.width * _HWPUNIT_PER_PT)
    if block.position and block.position.height:
        height_hu = round(block.position.height * _HWPUNIT_PER_PT)

    sz = etree.SubElement(tbl, f"{_HP}sz")
    sz.set("width", str(width_hu))
    sz.set("widthRelTo", "ABSOLUTE")
    sz.set("height", str(height_hu))
    sz.set("heightRelTo", "ABSOLUTE")
    sz.set("protect", "0")

    pos = etree.SubElement(tbl, f"{_HP}pos")
    like_char = "1"
    if block.position and block.position.like_char is not None:
        like_char = "1" if block.position.like_char else "0"
    pos.set("treatAsChar", like_char)
    pos.set("affectLSpacing", "0")
    pos.set("flowWithText", "1")
    pos.set("allowOverlap", "0")
    pos.set("holdAnchorAndSO", "0")
    _VRELTO_HWPX = {"paper": "PAPER", "page": "PAGE", "paragraph": "PARA"}
    _HRELTO_HWPX = {"paper": "PAPER", "page": "PAGE", "column": "COLUMN", "paragraph": "PARA"}
    _VALIGN_HWPX = {"top": "TOP", "middle": "CENTER", "bottom": "BOTTOM"}
    _HALIGN_HWPX = {"left": "LEFT", "center": "CENTER", "right": "RIGHT", "inside": "INSIDE", "outside": "OUTSIDE"}
    bp = block.position
    pos.set("vertRelTo", _VRELTO_HWPX.get(bp.vrelto, "PARA") if bp and bp.vrelto else "PARA")
    pos.set("horzRelTo", _HRELTO_HWPX.get(bp.hrelto, "PARA") if bp and bp.hrelto else "PARA")
    pos.set("vertAlign", _VALIGN_HWPX.get(bp.valign, "TOP") if bp and bp.valign else "TOP")
    pos.set("horzAlign", _HALIGN_HWPX.get(bp.halign, "LEFT") if bp and bp.halign else "LEFT")
    pos.set("vertOffset", str(round(bp.y * 100)) if bp and bp.y else "0")
    pos.set("horzOffset", str(round(bp.x * 100)) if bp and bp.x else "0")

    out_margin = etree.SubElement(tbl, f"{_HP}outMargin")
    out_margin.set("left", str(round((bp.margin_left or 0) * 100)) if bp else "0")
    out_margin.set("right", str(round((bp.margin_right or 0) * 100)) if bp else "0")
    out_margin.set("top", str(round((bp.margin_top or 0) * 100)) if bp else "0")
    out_margin.set("bottom", str(round((bp.margin_bottom or 0) * 100)) if bp else "0")

    in_margin = etree.SubElement(tbl, f"{_HP}inMargin")
    in_margin.set("left", "510")
    in_margin.set("right", "510")
    in_margin.set("top", "141")
    in_margin.set("bottom", "141")

    for ri, row in enumerate(block.rows):
        tr = _table_row_to_xml(row, ri, doc)
        tbl.append(tr)

    return p


def _table_row_to_xml(
    row: TableRow, row_idx: int, doc: UdfDocument
) -> etree._Element:
    """Convert a TableRow to an <hp:tr> element."""
    tr = etree.Element(f"{_HP}tr")
    for ci, cell in enumerate(row.cells):
        tc = _table_cell_to_xml(cell, ci, row_idx, doc)
        tr.append(tc)
    return tr


def _table_cell_to_xml(
    cell: TableCell, col_idx: int, row_idx: int, doc: UdfDocument
) -> etree._Element:
    """Convert a TableCell to an <hp:tc> element."""
    tc = etree.Element(f"{_HP}tc")
    tc.set("name", "")
    tc.set("header", "0")
    tc.set("hasMargin", "0")
    tc.set("protect", "0")
    tc.set("editable", "0")
    tc.set("dirty", "0")
    tc.set("borderFillIDRef", _get_cell_bf_id(cell.format))

    va = "TOP"
    if cell.format and cell.format.vertical_align:
        va_map = {"top": "TOP", "middle": "CENTER", "bottom": "BOTTOM"}
        va = va_map.get(cell.format.vertical_align, "TOP")

    sub_list = etree.SubElement(tc, f"{_HP}subList")
    sub_list.set("id", "")
    sub_list.set("textDirection", "HORIZONTAL")
    sub_list.set("lineWrap", "BREAK")
    sub_list.set("vertAlign", va)
    sub_list.set("linkListIDRef", "0")
    sub_list.set("linkListNextIDRef", "0")
    sub_list.set("textWidth", "0")
    sub_list.set("textHeight", "0")
    sub_list.set("hasTextRef", "0")
    sub_list.set("hasNumRef", "0")

    for content_block in cell.content:
        elements = _block_to_elements(content_block, doc)
        for el in elements:
            sub_list.append(el)

    if len(sub_list) == 0:
        sub_list.append(_empty_paragraph())

    addr = etree.SubElement(tc, f"{_HP}cellAddr")
    addr.set("colAddr", str(col_idx))
    addr.set("rowAddr", str(row_idx))

    span = etree.SubElement(tc, f"{_HP}cellSpan")
    span.set("colSpan", str(cell.col_span))
    span.set("rowSpan", str(cell.row_span))

    w_hu = round(cell.width * _HWPUNIT_PER_PT) if cell.width else 5000
    h_hu = round(cell.height * _HWPUNIT_PER_PT) if cell.height else 3000
    sz = etree.SubElement(tc, f"{_HP}cellSz")
    sz.set("width", str(w_hu))
    sz.set("height", str(h_hu))

    pad_l = pad_r = 510
    pad_t = pad_b = 141
    if cell.format:
        _fmt = cell.format
        if _fmt.padding_left:
            pad_l = _pt_str_to_hwpunit(_fmt.padding_left)
        if _fmt.padding_right:
            pad_r = _pt_str_to_hwpunit(_fmt.padding_right)
        if _fmt.padding_top:
            pad_t = _pt_str_to_hwpunit(_fmt.padding_top)
        if _fmt.padding_bottom:
            pad_b = _pt_str_to_hwpunit(_fmt.padding_bottom)
    cm = etree.SubElement(tc, f"{_HP}cellMargin")
    cm.set("left", str(pad_l))
    cm.set("right", str(pad_r))
    cm.set("top", str(pad_t))
    cm.set("bottom", str(pad_b))

    return tc


def _image_block_to_xml(block: ImageBlock, doc: UdfDocument) -> etree._Element:
    """Convert an ImageBlock to an <hp:p> containing <hp:pic>."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")

    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")

    pic = etree.SubElement(run, f"{_HP}pic")

    # sz
    sz = etree.SubElement(pic, f"{_HP}sz")
    w_hu = _pt_str_to_hwpunit(block.width) if block.width else 0
    h_hu = _pt_str_to_hwpunit(block.height) if block.height else 0
    sz.set("width", str(w_hu))
    sz.set("height", str(h_hu))

    # img
    img = etree.SubElement(pic, f"{_HP}img")
    # src는 "bindata:NAME" 형식 → binaryItemIDRef로 변환
    src = block.src
    if src.startswith("bindata:"):
        src = src[len("bindata:"):]
    img.set("binaryItemIDRef", src)

    return p


def _equation_block_to_xml(
    block: EquationBlock, doc: UdfDocument
) -> etree._Element:
    """Convert an EquationBlock to an <hp:p> containing <hp:eqEdit>."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")

    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")

    eq = etree.SubElement(run, f"{_HP}eqEdit")
    script = block.hwp_script or block.latex or ""
    eq.set("script", script)

    return p


def _list_to_paragraphs(
    block: ListBlock, doc: UdfDocument
) -> list[etree._Element]:
    """ListBlock → 단락 리스트 (HWPX에는 별도 리스트 요소 없음, 단락으로 직렬화)."""
    result: list[etree._Element] = []
    for item in block.items:
        result.extend(_list_item_to_paragraphs(item, doc))
    return result


def _list_item_to_paragraphs(
    item: ListItem, doc: UdfDocument
) -> list[etree._Element]:
    """ListItem → 단락(들)."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")

    _append_inlines_as_runs(p, item.inlines, doc)
    result = [p]

    for child in item.children:
        result.extend(_list_item_to_paragraphs(child, doc))

    return result


def _append_inlines_as_runs(
    p: etree._Element,
    inlines: list[Any],
    doc: UdfDocument,
) -> None:
    """인라인 리스트를 <hp:run>/<hp:t> 등으로 변환하여 단락에 추가한다.

    동일 charPrIDRef를 가진 연속 TextInline은 하나의 run으로 병합한다.
    """
    if not inlines:
        # 빈 단락도 run + t 구조는 필요
        run = etree.SubElement(p, f"{_HP}run")
        run.set("charPrIDRef", "0")
        etree.SubElement(run, f"{_HP}t")
        return

    for inline in inlines:
        if isinstance(inline, TextInline):
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", _get_char_pr_id(inline))
            t = etree.SubElement(run, f"{_HP}t")

            # 탭/줄바꿈 처리
            text = inline.text
            if text == "\t":
                etree.SubElement(t, f"{_HP}tab")
            elif text == "\n":
                etree.SubElement(t, f"{_HP}lineBreak")
            else:
                t.text = text

        elif isinstance(inline, LinkInline):
            url = inline.url or ""
            if url:
                fb = etree.SubElement(p, f"{_HP}ctrl")
                fb.set("ctrlId", "hlk%")
                fb.set("type", "HYPERLINK")
                fb.set("url", url)
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", "0")
            t = etree.SubElement(run, f"{_HP}t")
            t.text = inline.text
            if url:
                etree.SubElement(p, f"{_HP}ctrl").set("ctrlId", "hlk%end")

        elif isinstance(inline, ImageInline):
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", "0")
            pic = etree.SubElement(run, f"{_HP}pic")
            sz = etree.SubElement(pic, f"{_HP}sz")
            sz.set("width", str(_pt_str_to_hwpunit(inline.width)))
            sz.set("height", str(_pt_str_to_hwpunit(inline.height)))
            img = etree.SubElement(pic, f"{_HP}img")
            src = inline.src
            if src.startswith("bindata:"):
                src = src[len("bindata:"):]
            img.set("binaryItemIDRef", src)

        elif isinstance(inline, EquationInline):
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", "0")
            eq = etree.SubElement(run, f"{_HP}eqEdit")
            script = inline.hwp_script or inline.latex or ""
            eq.set("script", script)

        elif isinstance(inline, FootnoteRefInline):
            run = etree.SubElement(p, f"{_HP}run")
            run.set("charPrIDRef", "0")
            fn = etree.SubElement(run, f"{_HP}footNote")
            if inline.number is not None:
                fn.set("number", str(inline.number))
            sub_list = etree.SubElement(fn, f"{_HP}subList")
            sub_list.append(_empty_paragraph())
        elif hasattr(inline, "type"):
            if inline.type == "endnote_ref":
                run = etree.SubElement(p, f"{_HP}run")
                run.set("charPrIDRef", "0")
                en = etree.SubElement(run, f"{_HP}endNote")
                if hasattr(inline, "number") and inline.number is not None:
                    en.set("number", str(inline.number))
                sub_list = etree.SubElement(en, f"{_HP}subList")
                sub_list.append(_empty_paragraph())
            elif inline.type == "code" and hasattr(inline, "text"):
                run = etree.SubElement(p, f"{_HP}run")
                run.set("charPrIDRef", "0")
                t = etree.SubElement(run, f"{_HP}t")
                t.text = inline.text
            elif inline.type == "ruby" and hasattr(inline, "text"):
                run = etree.SubElement(p, f"{_HP}run")
                run.set("charPrIDRef", "0")
                t = etree.SubElement(run, f"{_HP}t")
                t.text = inline.text


def _empty_paragraph() -> etree._Element:
    """빈 <hp:p> 요소를 생성한다."""
    p = etree.Element(f"{_HP}p")
    p.set("paraPrIDRef", "0")
    p.set("styleIDRef", "0")
    p.set("pageBreak", "0")
    p.set("columnBreak", "0")
    p.set("merged", "0")
    run = etree.SubElement(p, f"{_HP}run")
    run.set("charPrIDRef", "0")
    etree.SubElement(run, f"{_HP}t")
    return p


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _pt_to_hwpunit(val: Any) -> int:
    """pt 값을 HWPUNIT로 변환한다.

    문자열('595.28pt', '210.0mm') 및 숫자(float/int, pt 단위)
    모두 지원한다. Ratio 객체가 오면 percent 값을 그대로 반환한다.
    """
    if val is None:
        return 0
    # float/int — pt 단위로 간주
    if isinstance(val, (int, float)):
        return round(val * _HWPUNIT_PER_PT)
    # Ratio 객체 (line_spacing 등)
    if hasattr(val, "percent"):
        return round(val.percent)
    # 문자열
    if isinstance(val, str):
        if not val:
            return 0
        v = val.strip()
        if v.endswith("pt"):
            try:
                return round(float(v[:-2]) * _HWPUNIT_PER_PT)
            except ValueError:
                return 0
        if v.endswith("mm"):
            try:
                return round(float(v[:-2]) * 283.46)
            except ValueError:
                return 0
        try:
            return round(float(v))
        except ValueError:
            return 0
    return 0


def _pt_str_to_hwpunit(val: Any) -> int:
    """pt 값을 HWPUNIT로 변환한다. None → 0.

    문자열('12.0pt') 및 숫자(float) 모두 지원.
    """
    if val is None:
        return 0
    return _pt_to_hwpunit(val)
