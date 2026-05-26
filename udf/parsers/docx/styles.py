"""DOCX styles.xml, numbering.xml, and relationships parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lxml import etree

_HUGE_PARSER = etree.XMLParser(huge_tree=True)

from udf.schema import BlockFormat
from udf.pipeline.verbatim import NumberingDef, NumberingLevel, StyleDef

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "mc": "http://schemas.openxmlformats.org/markup-compatibility/2006",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "pic": "http://schemas.openxmlformats.org/drawingml/2006/picture",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "wps": "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",
}

_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

_HEADING_PATTERN = {
    "heading 1": 1, "heading 2": 2, "heading 3": 3,
    "heading 4": 4, "heading 5": 5, "heading 6": 6,
}

_UNDERLINE_TYPE_MAP = {
    "single": "solid",
    "double": "double",
    "dotted": "dot",
    "dash": "dash",
    "dashDot": "dash_dot",
    "dashDotDot": "dash_dot_dot",
    "thick": "thick",
    "words": "words",
    "wave": "wave",
    "wavyDouble": "wave_double",
    "dottedHeavy": "dot",
    "dashHeavy": "dash",
    "dashDotHeavy": "dash_dot",
    "dashDotDotHeavy": "dash_dot_dot",
    "wavyHeavy": "wave",
}

_NUM_FORMAT_MAP = {
    "decimal": "decimal",
    "upperLetter": "alpha_upper",
    "lowerLetter": "alpha_lower",
    "upperRoman": "roman_upper",
    "lowerRoman": "roman_lower",
    "bullet": "bullet",
    "koreanCounting": "korean",
    "ganada": "korean",
}


@dataclass
class StyleInfo:
    """Aggregated style/numbering/relationship data for a DOCX file."""

    paragraph_styles: dict[str, StyleDef] = field(default_factory=dict)
    character_styles: dict[str, StyleDef] = field(default_factory=dict)
    heading_style_levels: dict[str, int] = field(default_factory=dict)
    default_para_format: BlockFormat | None = None
    default_char_props: dict[str, Any] = field(default_factory=dict)
    numbering_defs: dict[str, NumberingDef] = field(default_factory=dict)
    relationships: dict[str, str] = field(default_factory=dict)


def parse_relationships(rels_bytes: bytes) -> dict[str, str]:
    """Parse a DOCX ``.rels`` file into a relationship-ID to target-path map.

    Parameters
    ----------
    rels_bytes : bytes
        Raw XML content of a ``_rels/*.rels`` file.

    Returns
    -------
    dict[str, str]
        Mapping from relationship ID (e.g. ``rId1``) to its target path.
    """
    root = etree.fromstring(rels_bytes, parser=_HUGE_PARSER)
    result: dict[str, str] = {}
    for rel in root.iter(f"{{{_RELS_NS}}}Relationship"):
        rid = rel.get("Id", "")
        target = rel.get("Target", "")
        if rid:
            result[rid] = target
    return result


def parse_styles_xml(styles_bytes: bytes) -> tuple[
    dict[str, StyleDef],
    dict[str, StyleDef],
    dict[str, int],
    BlockFormat | None,
    dict[str, Any],
]:
    """Parse ``word/styles.xml`` into paragraph/character style definitions.

    Parameters
    ----------
    styles_bytes : bytes
        Raw XML content of ``word/styles.xml``.

    Returns
    -------
    tuple
        ``(para_styles, char_styles, heading_levels, default_para_format,
        default_char_props)`` -- each a dict or BlockFormat.
    """
    root = etree.fromstring(styles_bytes, parser=_HUGE_PARSER)

    para_styles: dict[str, StyleDef] = {}
    char_styles: dict[str, StyleDef] = {}
    heading_levels: dict[str, int] = {}
    default_para_fmt: BlockFormat | None = None
    default_char: dict[str, Any] = {}

    doc_defaults = root.find("w:docDefaults", NS)
    if doc_defaults is not None:
        rpr_default = doc_defaults.find("w:rPrDefault/w:rPr", NS)
        if rpr_default is not None:
            default_char = _parse_rpr(rpr_default)
        ppr_default = doc_defaults.find("w:pPrDefault/w:pPr", NS)
        if ppr_default is not None:
            default_para_fmt = _parse_ppr(ppr_default)

    for style_el in root.findall("w:style", NS):
        style_type = style_el.get(f"{{{NS['w']}}}type", "")
        style_id = style_el.get(f"{{{NS['w']}}}styleId", "")
        if not style_id:
            continue

        name_el = style_el.find("w:name", NS)
        name = name_el.get(f"{{{NS['w']}}}val", "") if name_el is not None else style_id

        parent_el = style_el.find("w:basedOn", NS)
        parent_id = parent_el.get(f"{{{NS['w']}}}val") if parent_el is not None else None

        ppr = style_el.find("w:pPr", NS)
        fmt = _parse_ppr(ppr) if ppr is not None else None

        sdef = StyleDef(
            id=style_id,
            name=name,
            style_type="paragraph" if style_type == "paragraph" else "character",
            parent_id=parent_id,
            format=fmt,
        )

        if style_type == "paragraph":
            para_styles[style_id] = sdef

            name_lower = name.lower()
            if name_lower in _HEADING_PATTERN:
                heading_levels[style_id] = _HEADING_PATTERN[name_lower]
            else:
                outline_el = None
                if ppr is not None:
                    outline_el = ppr.find("w:outlineLvl", NS)
                if outline_el is not None:
                    val = outline_el.get(f"{{{NS['w']}}}val", "")
                    try:
                        lvl = int(val) + 1
                        if 1 <= lvl <= 6:
                            heading_levels[style_id] = lvl
                    except ValueError:
                        pass
        elif style_type == "character":
            char_styles[style_id] = sdef

    return para_styles, char_styles, heading_levels, default_para_fmt, default_char


def parse_numbering_xml(numbering_bytes: bytes) -> dict[str, NumberingDef]:
    """Parse ``word/numbering.xml`` into numbering definitions.

    Parameters
    ----------
    numbering_bytes : bytes
        Raw XML content of ``word/numbering.xml``.

    Returns
    -------
    dict[str, NumberingDef]
        Mapping from numbering ID to its definition with level details.
    """
    root = etree.fromstring(numbering_bytes, parser=_HUGE_PARSER)

    abstract_nums: dict[str, list[NumberingLevel]] = {}
    for abstract in root.findall("w:abstractNum", NS):
        abstract_id = abstract.get(f"{{{NS['w']}}}abstractNumId", "")
        levels: list[NumberingLevel] = []
        for lvl_el in abstract.findall("w:lvl", NS):
            ilvl = lvl_el.get(f"{{{NS['w']}}}ilvl", "0")
            try:
                level_num = int(ilvl)
            except ValueError:
                level_num = 0

            fmt_el = lvl_el.find("w:numFmt", NS)
            fmt_val = fmt_el.get(f"{{{NS['w']}}}val", "") if fmt_el is not None else ""
            mapped_fmt = _NUM_FORMAT_MAP.get(fmt_val, fmt_val)

            lvl_text_el = lvl_el.find("w:lvlText", NS)
            lvl_text = lvl_text_el.get(f"{{{NS['w']}}}val", "") if lvl_text_el is not None else ""

            indent_el = lvl_el.find("w:pPr/w:ind", NS)
            indent_str = None
            if indent_el is not None:
                left = indent_el.get(f"{{{NS['w']}}}left", "")
                if left:
                    indent_str = f"{_twip_to_pt(left):.1f}pt"  # NumberingLevel.indent is still str

            levels.append(NumberingLevel(
                level=level_num,
                format=mapped_fmt or None,
                prefix=lvl_text or None,
                indent=indent_str,
            ))

        if abstract_id:
            abstract_nums[abstract_id] = levels

    result: dict[str, NumberingDef] = {}
    for num_el in root.findall("w:num", NS):
        num_id = num_el.get(f"{{{NS['w']}}}numId", "")
        abstract_ref = num_el.find("w:abstractNumIdRef", NS)
        if abstract_ref is None:
            abstract_ref = num_el.find("w:abstractNumId", NS)
        if abstract_ref is not None:
            abs_id = abstract_ref.get(f"{{{NS['w']}}}val", "")
            levels = abstract_nums.get(abs_id, [])
        else:
            levels = []

        if num_id:
            result[num_id] = NumberingDef(id=num_id, levels=levels)

    return result


def parse_style_info(
    styles_bytes: bytes | None,
    numbering_bytes: bytes | None,
    rels_bytes: bytes | None,
) -> StyleInfo:
    """Build a unified StyleInfo from DOCX support files.

    Parameters
    ----------
    styles_bytes : bytes | None
        Raw XML of ``word/styles.xml`` (may be None if absent).
    numbering_bytes : bytes | None
        Raw XML of ``word/numbering.xml`` (may be None if absent).
    rels_bytes : bytes | None
        Raw XML of ``word/_rels/document.xml.rels`` (may be None).

    Returns
    -------
    StyleInfo
        Combined style, numbering, and relationship data.
    """
    info = StyleInfo()

    if rels_bytes:
        info.relationships = parse_relationships(rels_bytes)

    if styles_bytes:
        (
            info.paragraph_styles,
            info.character_styles,
            info.heading_style_levels,
            info.default_para_format,
            info.default_char_props,
        ) = parse_styles_xml(styles_bytes)

    if numbering_bytes:
        info.numbering_defs = parse_numbering_xml(numbering_bytes)

    return info


def _parse_ppr(ppr: etree._Element) -> BlockFormat:
    from udf.schema.types import Ratio

    alignment = None
    jc = ppr.find("w:jc", NS)
    if jc is not None:
        val = jc.get(f"{{{NS['w']}}}val", "")
        alignment = {"left": "left", "center": "center", "right": "right",
                      "both": "justify", "justify": "justify"}.get(val)

    spacing = ppr.find("w:spacing", NS)
    line_spacing: float | Ratio | None = None
    space_before = None
    space_after = None
    if spacing is not None:
        line_val = spacing.get(f"{{{NS['w']}}}line", "")
        line_rule = spacing.get(f"{{{NS['w']}}}lineRule", "")
        if line_val:
            if line_rule == "exact" or line_rule == "atLeast":
                line_spacing = _twip_to_pt(line_val)
            else:
                try:
                    ratio = int(line_val) / 240 * 100
                    line_spacing = Ratio(ratio)
                except ValueError:
                    pass
        before = spacing.get(f"{{{NS['w']}}}before", "")
        if before:
            space_before = _twip_to_pt(before)
        after = spacing.get(f"{{{NS['w']}}}after", "")
        if after:
            space_after = _twip_to_pt(after)

    ind = ppr.find("w:ind", NS)
    indent_left = None
    indent_right = None
    indent_first = None
    if ind is not None:
        left = ind.get(f"{{{NS['w']}}}left", "") or ind.get(f"{{{NS['w']}}}start", "")
        if left:
            indent_left = _twip_to_pt(left)
        right = ind.get(f"{{{NS['w']}}}right", "") or ind.get(f"{{{NS['w']}}}end", "")
        if right:
            indent_right = _twip_to_pt(right)
        first = ind.get(f"{{{NS['w']}}}firstLine", "")
        hanging = ind.get(f"{{{NS['w']}}}hanging", "")
        if first:
            indent_first = _twip_to_pt(first)
        elif hanging:
            indent_first = -_twip_to_pt(hanging)

    keep_next = _bool_toggle(ppr, "w:keepNext")
    widow = _bool_toggle(ppr, "w:widowControl")
    page_break = _bool_toggle(ppr, "w:pageBreakBefore")

    # paragraph shading
    background_color = None
    shd = ppr.find("w:shd", NS)
    if shd is not None:
        fill = shd.get(f"{{{NS['w']}}}fill", "")
        if fill and fill.lower() not in ("auto", "ffffff"):
            background_color = f"#{fill}"

    # paragraph borders
    borders: dict[str, str] = {}
    p_bdr = ppr.find("w:pBdr", NS)
    if p_bdr is not None:
        for side in ("top", "bottom", "left", "right"):
            b_el = p_bdr.find(f"w:{side}", NS)
            if b_el is not None:
                b_color = b_el.get(f"{{{NS['w']}}}color", "")
                b_sz = b_el.get(f"{{{NS['w']}}}sz", "")
                b_style = b_el.get(f"{{{NS['w']}}}val", "")
                if b_style and b_style not in ("none", "nil"):
                    w_pt = int(b_sz) / 8 if b_sz else 0.5
                    c = f"#{b_color}" if b_color and b_color != "auto" else "#000000"
                    borders[f"border_{side}"] = f"{w_pt:.1f}pt solid {c}"

    # outline level
    outline_level = None
    outline_lvl = ppr.find("w:outlineLvl", NS)
    if outline_lvl is not None:
        val = outline_lvl.get(f"{{{NS['w']}}}val", "")
        try:
            lvl = int(val)
            if 0 <= lvl <= 7:
                outline_level = lvl
        except ValueError:
            pass

    return BlockFormat(
        alignment=alignment,
        line_spacing=line_spacing,
        space_before=space_before,
        space_after=space_after,
        indent_left=indent_left,
        indent_right=indent_right,
        indent_first=indent_first,
        keep_with_next=keep_next,
        widow_orphan=widow,
        page_break_before=page_break,
        background_color=background_color,
        outline_level=outline_level,
        **borders,
    )


def _parse_rpr(rpr: etree._Element) -> dict[str, Any]:
    props: dict[str, Any] = {}

    if _has_toggle(rpr, "w:b"):
        props["bold"] = True
    if _has_toggle(rpr, "w:i"):
        props["italic"] = True
    u_el = rpr.find("w:u", NS)
    if u_el is not None:
        u_val = u_el.get(f"{{{NS['w']}}}val", "single")
        if u_val != "none":
            props["underline"] = True
            u_type = _UNDERLINE_TYPE_MAP.get(u_val)
            if u_type:
                props["underline_type"] = u_type
            u_color = u_el.get(f"{{{NS['w']}}}color", "")
            if u_color and u_color.lower() != "auto":
                props["underline_color"] = f"#{u_color}"

    if _has_toggle(rpr, "w:strike"):
        props["strikethrough"] = True
        props["strikeout_type"] = "solid"
    elif _has_toggle(rpr, "w:dstrike"):
        props["strikethrough"] = True
        props["strikeout_type"] = "double"

    if _has_toggle(rpr, "w:outline"):
        props["outline"] = True
    if _has_toggle(rpr, "w:shadow"):
        props["shadow"] = True

    sz = rpr.find("w:sz", NS)
    if sz is not None:
        val = sz.get(f"{{{NS['w']}}}val", "")
        if val:
            try:
                props["font_size"] = int(val) / 2
            except ValueError:
                pass

    fonts = rpr.find("w:rFonts", NS)
    if fonts is not None:
        name = (
            fonts.get(f"{{{NS['w']}}}ascii")
            or fonts.get(f"{{{NS['w']}}}eastAsia")
            or fonts.get(f"{{{NS['w']}}}hAnsi")
        )
        if name:
            props["font_name"] = name

    color = rpr.find("w:color", NS)
    if color is not None:
        val = color.get(f"{{{NS['w']}}}val", "")
        if val and val.lower() != "auto":
            props["color"] = f"#{val}"

    shd = rpr.find("w:shd", NS)
    if shd is not None:
        fill = shd.get(f"{{{NS['w']}}}fill", "")
        if fill and fill.lower() not in ("auto", "ffffff"):
            props["background_color"] = f"#{fill}"

    vert = rpr.find("w:vertAlign", NS)
    if vert is not None:
        val = vert.get(f"{{{NS['w']}}}val", "")
        if val == "superscript":
            props["superscript"] = True
        elif val == "subscript":
            props["subscript"] = True

    caps = rpr.find("w:smallCaps", NS)
    if caps is not None:
        val = caps.get(f"{{{NS['w']}}}val", "true")
        if val != "false" and val != "0":
            props["small_caps"] = True

    vanish = rpr.find("w:vanish", NS)
    if vanish is not None:
        val = vanish.get(f"{{{NS['w']}}}val", "true")
        if val != "false" and val != "0":
            props["hidden"] = True

    spacing_el = rpr.find("w:spacing", NS)
    if spacing_el is not None:
        sp_val = spacing_el.get(f"{{{NS['w']}}}val", "")
        if sp_val:
            try:
                props["letter_spacing"] = int(sp_val) / 20
            except ValueError:
                pass

    return props


def _bool_toggle(parent: etree._Element, tag: str) -> bool | None:
    el = parent.find(tag, NS)
    if el is None:
        return None
    val = el.get(f"{{{NS['w']}}}val", "true")
    return val not in ("false", "0")


def _has_toggle(parent: etree._Element, tag: str) -> bool:
    el = parent.find(tag, NS)
    if el is None:
        return False
    val = el.get(f"{{{NS['w']}}}val", "true")
    return val not in ("false", "0")


def _twip_to_pt(twip_str: str) -> float:
    try:
        return int(twip_str) / 20
    except ValueError:
        return 0.0
