"""HWPX header.xml parser -- extracts GlobalResources.

Returns the same ``DocInfoResult`` used by the HWP binary parser so that
section parsers can reuse the same indexed lookup pattern.
"""

from __future__ import annotations

from typing import Any

from lxml import etree

from udf.schema.formats import BlockFormat
from udf.schema.types import Ratio, hwpunit_to_pt
from udf.pipeline.verbatim import (
    BorderFillDef,
    BulletDef,
    FontFallbacks,
    GlobalResources,
    NumberingDef,
    NumberingLevel,
    StyleDef,
    TabDef,
    TabStop,
)
from udf.parsers.hwp.doc_info import DocInfoResult

# OWPML 네임스페이스
NS = {
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
}

_ALIGN_MAP = {
    "JUSTIFY": "justify",
    "LEFT": "left",
    "RIGHT": "right",
    "CENTER": "center",
    "DISTRIBUTE": "distribute",
    "DIVIDE": "divide",
}

_LS_TYPE_MAP = {
    "PERCENT": "ratio",
    "FIXED": "fixed",
    "BETWEENLINES": "leading_only",
    "ATLEAST": "minimum",
}

_UNDERLINE_TYPE_MAP = {
    "BOTTOM": "solid",
    "CENTER": "solid",
    "TOP": "solid",
    "NONE": None,
}

_HWPUNIT_PER_MM = 283.46

_LANG_ATTRS = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")


def parse_header_xml(header_bytes: bytes) -> DocInfoResult:
    """Parse an HWPX ``header.xml`` into global document resources.

    Parameters
    ----------
    header_bytes : bytes
        Raw XML content of the header.xml file from an HWPX archive.

    Returns
    -------
    DocInfoResult
        Parsed char shapes, para shapes, font faces, styles, numbering
        definitions, and other global resources.
    """
    root = etree.fromstring(header_bytes)

    ref_list = root.find("hh:refList", NS)
    if ref_list is None:
        return DocInfoResult(global_resources=GlobalResources())

    char_shapes = _parse_char_properties(ref_list)
    para_shapes = _parse_para_properties(ref_list)
    face_names_list, face_name_objs = _parse_fontfaces(ref_list)
    border_fills = _parse_border_fills(ref_list)
    styles_dict, style_name_list = _parse_styles(ref_list, para_shapes, char_shapes)
    numberings = _parse_numberings(ref_list)
    bullets = _parse_bullets(ref_list)
    tab_defs = _parse_tab_defs(ref_list)

    doc_properties = _parse_begin_num(root)

    gr = GlobalResources(
        char_shapes={str(i): cs for i, cs in enumerate(char_shapes)},
        para_shapes={str(i): ps for i, ps in enumerate(para_shapes)},
        face_names=face_name_objs,
        styles=styles_dict,
        numberings=numberings,
        bullets=bullets,
        border_fills=border_fills,
        tab_defs=tab_defs,
    )

    return DocInfoResult(
        global_resources=gr,
        char_shapes=char_shapes,
        para_shapes=para_shapes,
        face_names=face_names_list,
        style_names=style_name_list,
        doc_properties=doc_properties,
    )


def _parse_char_properties(ref_list: etree._Element) -> list[dict[str, Any]]:
    """<hh:charProperties> → list of char_shape dicts."""
    result: list[dict[str, Any]] = []
    container = ref_list.find("hh:charProperties", NS)
    if container is None:
        return result

    for cp in container.iterfind("hh:charPr", NS):
        cs = _parse_single_char_pr(cp)
        result.append(cs)
    return result


def _parse_single_char_pr(el: etree._Element) -> dict[str, Any]:
    """Parse a single charPr element into a char shape dict."""
    height = int(el.get("height", "1000"))
    text_color = el.get("textColor", "#000000")
    shade_color = el.get("shadeColor", "none")

    font_size_pt = height / 100.0

    if text_color.lower() == "none":
        text_color = "#000000"
    color = text_color if text_color.startswith("#") else f"#{text_color}"

    shade_hex: str | None = None
    if shade_color and shade_color.lower() != "none":
        shade_hex = shade_color if shade_color.startswith("#") else f"#{shade_color}"

    bold = el.find("hh:bold", NS) is not None
    italic = el.find("hh:italic", NS) is not None

    underline_el = el.find("hh:underline", NS)
    underline = False
    underline_type: str | None = None
    underline_color: str | None = None
    if underline_el is not None:
        ul_type_str = underline_el.get("type", "NONE")
        if ul_type_str != "NONE":
            underline = True
            underline_type = _UNDERLINE_TYPE_MAP.get(ul_type_str, "solid")
            ul_color = underline_el.get("color", "")
            underline_color = ul_color if ul_color and ul_color.lower() != "#000000" else None

    strikeout_el = el.find("hh:strikeout", NS)
    strikethrough = False
    strikeout_type: str | None = None
    strikeout_color: str | None = None
    _STRIKE_SHAPES = {"SOLID", "DASH", "DOT", "DASH_DOT", "DASH_DOT_DOT", "LONG_DASH", "CIRCLE"}
    if strikeout_el is not None:
        st_shape = strikeout_el.get("shape", "NONE")
        if st_shape in _STRIKE_SHAPES:
            strikethrough = True
            strikeout_type = "solid"
            strikeout_color = strikeout_el.get("color")

    outline_el = el.find("hh:outline", NS)
    outline = False
    if outline_el is not None and outline_el.get("type", "NONE") != "NONE":
        outline = True

    shadow_el = el.find("hh:shadow", NS)
    shadow = False
    if shadow_el is not None and shadow_el.get("type", "NONE") != "NONE":
        shadow = True

    emboss = el.find("hh:emboss", NS) is not None
    engrave = el.find("hh:engrave", NS) is not None
    superscript = el.find("hh:supscript", NS) is not None
    subscript = el.find("hh:subscript", NS) is not None

    font_ref = el.find("hh:fontRef", NS)
    face_ids: dict[str, int] = {}
    if font_ref is not None:
        for lang in _LANG_ATTRS:
            val = font_ref.get(lang)
            if val is not None:
                face_ids[f"{lang}_face_id"] = int(val)

    ratio_el = el.find("hh:ratio", NS)
    ratio_hangul = 100
    if ratio_el is not None:
        ratio_hangul = int(ratio_el.get("hangul", "100"))

    spacing_el = el.find("hh:spacing", NS)
    spacing_hangul = 0
    if spacing_el is not None:
        spacing_hangul = int(spacing_el.get("hangul", "0"))

    offset_el = el.find("hh:offset", NS)
    offset_hangul = 0
    if offset_el is not None:
        offset_hangul = int(offset_el.get("hangul", "0"))

    result: dict[str, Any] = {
        "bold": bold or None,
        "italic": italic or None,
        "underline": underline or None,
        "underline_type": underline_type,
        "underline_color": underline_color,
        "strikethrough": strikethrough or None,
        "strikeout_type": strikeout_type,
        "strikeout_color": strikeout_color,
        "outline": outline or None,
        "shadow": shadow or None,
        "emboss": emboss or None,
        "engrave": engrave or None,
        "superscript": superscript or None,
        "subscript": subscript or None,
        "font_size_pt": font_size_pt,
        "color": color,
        "shade_color": shade_hex,
        "char_scale": ratio_hangul if ratio_hangul != 100 else None,
        "letter_spacing": f"{spacing_hangul}%" if spacing_hangul else None,
        "char_offset": f"{offset_hangul}%" if offset_hangul else None,
    }
    result.update(face_ids)
    return result


def _parse_para_properties(ref_list: etree._Element) -> list[dict[str, Any]]:
    """<hh:paraProperties> → list of para_shape dicts."""
    result: list[dict[str, Any]] = []
    container = ref_list.find("hh:paraProperties", NS)
    if container is None:
        return result

    for pp in container.iterfind("hh:paraPr", NS):
        ps = _parse_single_para_pr(pp)
        result.append(ps)
    return result


def _parse_single_para_pr(el: etree._Element) -> dict[str, Any]:
    """Parse a single paraPr element into a para shape dict."""
    result: dict[str, Any] = {}

    align_el = el.find("hh:align", NS)
    if align_el is not None:
        horiz = align_el.get("horizontal", "JUSTIFY")
        result["alignment"] = _ALIGN_MAP.get(horiz, "left")

    heading_el = el.find("hh:heading", NS)
    if heading_el is not None:
        h_type = heading_el.get("type", "NONE")
        if h_type == "OUTLINE":
            level = int(heading_el.get("level", "0"))
            result["level"] = level

    # margin과 lineSpacing은 <hp:switch> 안에 있을 수 있음
    margin_el, ls_el = _find_margin_and_linespacing(el)

    if margin_el is not None:
        for child in margin_el:
            tag = etree.QName(child.tag).localname
            val = int(child.get("value", "0"))
            if tag == "intent":
                result["indent_first_hwp"] = val
            elif tag == "left":
                result["indent_left_hwp"] = val
            elif tag == "right":
                result["indent_right_hwp"] = val
            elif tag == "prev":
                result["space_before_hwp"] = val
            elif tag == "next":
                result["space_after_hwp"] = val

    if ls_el is not None:
        ls_type_str = ls_el.get("type", "PERCENT")
        ls_value = int(ls_el.get("value", "160"))
        result["line_spacing_type"] = _LS_TYPE_MAP.get(ls_type_str, "ratio")
        result["line_spacing_hwp"] = ls_value

    break_el = el.find("hh:breakSetting", NS)
    if break_el is not None:
        if break_el.get("keepWithNext") == "1":
            result["with_next_paragraph"] = True
        if break_el.get("pageBreakBefore") == "1":
            result["start_new_page"] = True
        if break_el.get("widowOrphan") == "1":
            result["protect"] = True

    tab_pr_id = el.get("tabPrIDRef")
    if tab_pr_id is not None:
        result["tab_def_id"] = int(tab_pr_id)

    return result


def _find_margin_and_linespacing(
    para_pr: etree._Element,
) -> tuple[etree._Element | None, etree._Element | None]:
    """paraPr 내에서 margin과 lineSpacing 요소를 찾는다.

    직접 자식이거나 <hp:switch><hp:case>/<hp:default> 안에 있을 수 있다.
    hp:case의 intent(indent_first)와 hp:default의 left/right/prev/next를
    병합하여 HWP 바이너리와 최대한 일치시킨다.
    """
    # 직접 자식에서 찾기
    margin = para_pr.find("hh:margin", NS)
    ls = para_pr.find("hh:lineSpacing", NS)
    if margin is not None or ls is not None:
        return margin, ls

    # hp:switch 안에서 찾기
    switch = para_pr.find("hp:switch", NS)
    if switch is None:
        return None, None

    default = switch.find("hp:default", NS)
    case = switch.find("hp:case", NS)

    # 기본: default 사용
    margin = default.find("hh:margin", NS) if default is not None else None
    ls = default.find("hh:lineSpacing", NS) if default is not None else None

    if margin is not None or ls is not None:
        return margin, ls

    # case fallback
    if case is not None:
        margin = case.find("hh:margin", NS)
        ls = case.find("hh:lineSpacing", NS)
        return margin, ls

    return None, None


def _parse_fontfaces(
    ref_list: etree._Element,
) -> tuple[list[str | None], dict[str, FontFallbacks]]:
    """<hh:fontfaces> → (flat face_names list, FontFallbacks dict)."""
    face_names: list[str | None] = []
    face_name_objs: dict[str, FontFallbacks] = {}

    container = ref_list.find("hh:fontfaces", NS)
    if container is None:
        return face_names, face_name_objs

    lang_fonts: dict[str, list[str]] = {}
    for ff in container.iterfind("hh:fontface", NS):
        lang = ff.get("lang", "").lower()
        fonts_for_lang: list[str] = []
        for font_el in ff.iterfind("hh:font", NS):
            face = font_el.get("face", "")
            fonts_for_lang.append(face)
            face_names.append(face)
        lang_fonts[lang] = fonts_for_lang

    # FontFallbacks 구성: 각 font index에 대해 lang별 이름 매핑
    hangul_fonts = lang_fonts.get("hangul", [])
    latin_fonts = lang_fonts.get("latin", [])
    hanja_fonts = lang_fonts.get("hanja", [])
    japanese_fonts = lang_fonts.get("japanese", [])
    other_fonts = lang_fonts.get("other", [])
    symbol_fonts = lang_fonts.get("symbol", [])
    user_fonts = lang_fonts.get("user", [])

    max_count = max(
        len(hangul_fonts),
        len(latin_fonts),
        len(hanja_fonts),
        len(japanese_fonts),
        len(other_fonts),
        len(symbol_fonts),
        len(user_fonts),
        1,
    )

    for i in range(max_count):
        ff_obj = FontFallbacks()
        if i < len(hangul_fonts):
            ff_obj.hangul = hangul_fonts[i]
        if i < len(latin_fonts):
            ff_obj.latin = latin_fonts[i]
        if i < len(hanja_fonts):
            ff_obj.hanja = hanja_fonts[i]
        if i < len(japanese_fonts):
            ff_obj.japanese = japanese_fonts[i]
        if i < len(other_fonts):
            ff_obj.other = other_fonts[i]
        if i < len(symbol_fonts):
            ff_obj.symbol = symbol_fonts[i]
        if i < len(user_fonts):
            ff_obj.user_defined = user_fonts[i]
        face_name_objs[str(i)] = ff_obj

    return face_names, face_name_objs


def _parse_border_fills(ref_list: etree._Element) -> dict[str, BorderFillDef]:
    """<hh:borderFills> → dict[id, BorderFillDef]."""
    result: dict[str, BorderFillDef] = {}
    container = ref_list.find("hh:borderFills", NS)
    if container is None:
        return result

    for bf_el in container.iterfind("hh:borderFill", NS):
        bf_id = bf_el.get("id", str(len(result)))
        idx = str(int(bf_id) - 1) if bf_id.isdigit() and int(bf_id) > 0 else str(len(result))

        left_el = bf_el.find("hh:leftBorder", NS)
        right_el = bf_el.find("hh:rightBorder", NS)
        top_el = bf_el.find("hh:topBorder", NS)
        bottom_el = bf_el.find("hh:bottomBorder", NS)

        def _border_props(el: etree._Element | None) -> tuple[str | None, str | None, float | None]:
            if el is None:
                return None, None, None
            btype = el.get("type", "NONE")
            if btype == "NONE":
                return None, None, None
            color = el.get("color", "#000000")
            if color.lower() == "none":
                color = None
            style = btype.lower()
            width_str = el.get("width", "0.1 mm")
            try:
                width = float(width_str.replace("mm", "").strip())
            except ValueError:
                width = 0.1
            return color, style, width

        lc, ls, lw = _border_props(left_el)
        rc, rs, rw = _border_props(right_el)
        tc, ts, tw = _border_props(top_el)
        bc, bs, bw = _border_props(bottom_el)

        fill_color: str | None = None
        fill_brush = bf_el.find("hc:fillBrush", NS)
        if fill_brush is not None:
            win_brush = fill_brush.find("hc:winBrush", NS)
            if win_brush is not None:
                fc = win_brush.get("faceColor", "none")
                if fc and fc.lower() != "none":
                    fill_color = fc if fc.startswith("#") else f"#{fc}"
            if fill_color is None:
                grad = fill_brush.find("hc:gradation", NS)
                if grad is not None:
                    colors = grad.findall("hc:color", NS)
                    if colors:
                        gc = colors[-1].get("value", "")
                        if gc and gc.startswith("#"):
                            fill_color = gc

        result[idx] = BorderFillDef(
            id=idx,
            border_left_color=lc,
            border_left_style=ls,
            border_left_width=lw,
            border_right_color=rc,
            border_right_style=rs,
            border_right_width=rw,
            border_top_color=tc,
            border_top_style=ts,
            border_top_width=tw,
            border_bottom_color=bc,
            border_bottom_style=bs,
            border_bottom_width=bw,
            fill_color=fill_color,
        )

    return result


def _parse_styles(
    ref_list: etree._Element,
    para_shapes: list[dict[str, Any]],
    char_shapes: list[dict[str, Any]],
) -> tuple[dict[str, StyleDef], list[str]]:
    """<hh:styles> → (styles dict, style_name_list)."""
    styles: dict[str, StyleDef] = {}
    name_list: list[str] = []

    container = ref_list.find("hh:styles", NS)
    if container is None:
        return styles, name_list

    for st_el in container.iterfind("hh:style", NS):
        st_id = st_el.get("id", str(len(styles)))
        name = st_el.get("name", f"style_{st_id}")
        st_el.get("engName", "")
        st_type = st_el.get("type", "PARA")
        para_pr_id = st_el.get("paraPrIDRef")
        char_pr_id = st_el.get("charPrIDRef")

        sdef = StyleDef(
            id=st_id,
            name=name,
            style_type="paragraph" if st_type == "PARA" else "character",
        )

        if para_pr_id is not None:
            ps_idx = int(para_pr_id)
            if ps_idx < len(para_shapes):
                sdef.format = _build_block_format(
                    para_shapes[ps_idx],
                    char_shapes,
                    int(char_pr_id) if char_pr_id else None,
                )

        styles[st_id] = sdef
        name_list.append(name)

    return styles, name_list


def _build_block_format(
    ps: dict[str, Any],
    char_shapes: list[dict[str, Any]],
    cs_id: int | None,
) -> BlockFormat:
    """ParaShape + CharShape → BlockFormat."""
    _VALID_ALIGNS = ("left", "center", "right", "justify")
    _VALID_LS_TYPES = ("follow_char", "fixed", "leading_only", "minimum", "ratio")

    align = ps.get("alignment")
    ls_type = ps.get("line_spacing_type")
    ls_val = ps.get("line_spacing_hwp", 0)

    def _to_pt(v: int) -> float | None:
        if not v or v >= 0xFFFFFFF0:
            return None
        return hwpunit_to_pt(v)

    line_spacing: float | Ratio | None = None
    if ls_val and ls_val < 0xFFFFFFF0:
        if ls_type in (None, "ratio"):
            line_spacing = Ratio(ls_val)
        else:
            line_spacing = hwpunit_to_pt(ls_val)

    fmt = BlockFormat(
        alignment=align if align in _VALID_ALIGNS else None,
        indent_left=_to_pt(ps.get("indent_left_hwp", 0)),
        indent_right=_to_pt(ps.get("indent_right_hwp", 0)),
        space_before=_to_pt(ps.get("space_before_hwp", 0)),
        space_after=_to_pt(ps.get("space_after_hwp", 0)),
        line_spacing=line_spacing,
        line_spacing_type=ls_type if ls_type in _VALID_LS_TYPES else None,
    )

    if cs_id is not None and cs_id < len(char_shapes):
        cs = char_shapes[cs_id]
        fmt.bold = cs.get("bold")
        fmt.italic = cs.get("italic")
        font_size = cs.get("font_size_pt")
        if font_size:
            fmt.font_size = font_size

    return fmt


def _parse_numberings(ref_list: etree._Element) -> dict[str, NumberingDef]:
    """<hh:numberings> → dict."""
    result: dict[str, NumberingDef] = {}
    container = ref_list.find("hh:numberings", NS)
    if container is None:
        return result

    for num_el in container.iterfind("hh:numbering", NS):
        idx = str(len(result))
        levels: list[NumberingLevel] = []
        for para_head in num_el.iterfind("hh:paraHead", NS):
            level = int(para_head.get("level", str(len(levels))))
            fmt = para_head.get("numFormat", "DIGIT")
            text = para_head.text or ""
            levels.append(NumberingLevel(level=level, format=fmt.lower(), prefix=text or None))
        if not levels:
            levels = [NumberingLevel(level=i) for i in range(7)]
        result[idx] = NumberingDef(id=idx, levels=levels)

    return result


def _parse_bullets(ref_list: etree._Element) -> dict[str, BulletDef]:
    """<hh:bullets> → dict."""
    result: dict[str, BulletDef] = {}
    container = ref_list.find("hh:bullets", NS)
    if container is None:
        return result

    for bul_el in container.iterfind("hh:bullet", NS):
        idx = str(len(result))
        bullet_char = bul_el.get("char")
        result[idx] = BulletDef(id=idx, char=bullet_char)

    return result


def _parse_tab_defs(ref_list: etree._Element) -> dict[str, TabDef]:
    """<hh:tabProperties> → dict."""
    result: dict[str, TabDef] = {}
    container = ref_list.find("hh:tabProperties", NS)
    if container is None:
        return result

    for tab_el in container.iterfind("hh:tabPr", NS):
        idx = str(len(result))
        stops: list[TabStop] = []
        for tab_item in tab_el.iterfind("hh:tabItem", NS):
            pos = int(tab_item.get("pos", "0"))
            kind = tab_item.get("type", "LEFT").lower()
            pos_mm = pos / _HWPUNIT_PER_MM
            stops.append(TabStop(position=f"{pos_mm:.1f}mm", align=kind))
        result[idx] = TabDef(id=idx, stops=stops)

    return result


def _parse_begin_num(root: etree._Element) -> dict[str, Any]:
    """<hh:beginNum> → doc_properties dict."""
    result: dict[str, Any] = {}
    begin_num = root.find("hh:beginNum", NS)
    if begin_num is None:
        return result

    mappings = {
        "page": "start_page",
        "footnote": "start_footnote",
        "endnote": "start_endnote",
        "pic": "start_picture",
        "tbl": "start_table",
        "equation": "start_equation",
    }
    for attr, key in mappings.items():
        val = begin_num.get(attr)
        if val is not None:
            result[key] = int(val)

    return result
