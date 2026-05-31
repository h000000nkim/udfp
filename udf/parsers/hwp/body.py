"""BodyText stream parser -- converts HwpRecord tree to blocks[] + verbatim."""

from __future__ import annotations

import base64
import itertools
import re
import struct
from typing import Any

from udf.core.ids import make_block_id, make_verbatim_id
from udf.schema import (
    Block,
    BlockFormat,
    CellFormat,
    ChartBlock,
    DrawingBlock,
    EndnoteBlock,
    EquationBlock,
    EquationInline,
    FieldBlock,
    FooterBlock,
    FootnoteBlock,
    HeaderBlock,
    HeadingBlock,
    ImageBlock,
    ParagraphBlock,
    PositionInfo,
    TableBlock,
    TableCell,
    TableRow,
    TextArtBlock,
    TextBoxBlock,
    TextInline,
    UnknownBlock,
)
from udf.schema.types import Ratio, hwpunit_to_pt
from udf.pipeline.verbatim import VerbatimBlock
from udf.parsers.hwp.doc_info import DocInfoResult
from udf.parsers.hwp.records import (
    HWPTAG_CTRL_HEADER,
    HWPTAG_EQEDIT,
    HWPTAG_LIST_HEADER,
    HWPTAG_PAGE_DEF,
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_LINE_SEG,
    HWPTAG_PARA_TEXT,
    HWPTAG_SHAPE_COMPONENT,
    HWPTAG_SHAPE_COMPONENT_PIC,
    HWPTAG_SHAPE_COMPONENT_RECT,
    HWPTAG_TABLE,
    HwpRecord,
    _PT_CTRL_2BYTE,
    ctrl_id_from_payload,
    iter_records,
)

# CTRL_ID 값
_CTRL_ID_TABLE = "tbl "
_CTRL_ID_FOOTNOTE = "fn  "
_CTRL_ID_ENDNOTE = "en  "
_CTRL_ID_SECD = "secd"
_CTRL_ID_EQED = "eqed"
_CTRL_ID_GSO = "gso "
_CTRL_ID_HEADER = "head"
_CTRL_ID_FOOTER = "foot"
_CTRL_ID_COLD = "cold"
_CTRL_ID_PGNP = "pgnp"
_CTRL_ID_PGHD = "pghd"
_CTRL_ID_NWNO = "nwno"
_CTRL_ID_TCPS = "tcps"
_CTRL_ID_BOKM = "bokm"
_CTRL_ID_ATNO = "atno"
_CTRL_ID_HLK = "%hlk"
_CTRL_ID_BMK = "%bmk"

_CTRL_IDS_SKIP = frozenset({
    _CTRL_ID_SECD, _CTRL_ID_COLD, _CTRL_ID_PGHD, _CTRL_ID_TCPS,
    _CTRL_ID_NWNO, _CTRL_ID_BOKM, _CTRL_ID_BMK,
})

_FLOW_MAP = {0: "float", 1: "block", 2: "back", 3: "front"}
_TEXT_SIDE_MAP = {0: "both", 1: "left", 2: "right", 3: "larger"}
_VRELTO_MAP = {0: "paper", 1: "page", 2: "paragraph"}
_HRELTO_MAP = {0: "paper", 1: "page", 2: "column", 3: "paragraph"}
_VALIGN_MAP = {0: "top", 1: "middle", 2: "bottom"}
_HALIGN_MAP = {0: "left", 1: "center", 2: "right", 3: "inside", 4: "outside"}
_WIDTH_RELTO_MAP = {0: "paper", 1: "page", 2: "column", 3: "paragraph", 4: "absolute"}
_HEIGHT_RELTO_MAP = {0: "paper", 1: "page", 2: "absolute"}
_NUMBER_CATEGORY_MAP = {0: None, 1: "figure", 2: "table", 3: "equation"}

_OUTLINE_RE = re.compile(r"^개요\s*(\d+)$|^Heading\s*(\d+)$", re.IGNORECASE)
_PCT_RE = re.compile(r"^(-?\d+(?:\.\d+)?)%?$")


def _parse_pct_str(s: str) -> float | None:
    """Parse a percentage string like '50%' to float."""
    m = _PCT_RE.match(s)
    return float(m.group(1)) if m else None


def _heading_level_from_style(style_name: str) -> int | None:
    """Derive heading level (1-6) from a style name like 'Heading 2'."""
    m = _OUTLINE_RE.match(style_name.strip())
    if not m:
        return None
    level = int(m.group(1) or m.group(2))
    return min(max(level, 1), 6)


# HWPUNIT → pt (1 pt = 100 HWPUNIT)
_HU_TO_PT = 0.01


# ---------------------------------------------------------------------------
# PARA_TEXT 텍스트 추출
# ---------------------------------------------------------------------------


def _extract_text(pt_payload: bytes) -> str:
    """Extract plain-text characters from a PARA_TEXT payload."""
    chars: list[str] = []
    off = 0
    n = len(pt_payload)
    while off + 2 <= n:
        (code,) = struct.unpack_from("<H", pt_payload, off)
        if code > 0x001F:
            if code != 0xFFFF:  # BOM/invalid 방어
                if 0xD800 <= code <= 0xDBFF and off + 4 <= n:
                    (lo,) = struct.unpack_from("<H", pt_payload, off + 2)
                    if 0xDC00 <= lo <= 0xDFFF:
                        cp = 0x10000 + ((code - 0xD800) << 10) + (lo - 0xDC00)
                        chars.append(chr(cp))
                        off += 4
                        continue
                chars.append(chr(code))
            off += 2
        elif code in _PT_CTRL_2BYTE:
            if code == 0x0009 and off + 14 <= n:
                w1 = struct.unpack_from("<H", pt_payload, off + 4)[0]
                w2 = struct.unpack_from("<H", pt_payload, off + 6)[0]
                w3 = struct.unpack_from("<H", pt_payload, off + 8)[0]
                w4 = struct.unpack_from("<H", pt_payload, off + 10)[0]
                w5 = struct.unpack_from("<H", pt_payload, off + 12)[0]
                if w1 == 0 and w2 == 0x0203 and w3 == 0 and w4 == 0 and w5 == 0:
                    off += 14
                    continue
            off += 2
        else:
            # hwp.md §5.2: 그 외 모든 ctrl 코드는 인라인 오브젝트 (2+14=16바이트)
            off += 16
    return "".join(chars)


# ---------------------------------------------------------------------------
# PARA_CHAR_SHAPE → inline 분리
# ---------------------------------------------------------------------------


def _build_inlines(
    pt_payload: bytes,
    pcs_payload: bytes,
    char_shapes: list[dict[str, Any]],
    face_names: list[str | None] | None = None,
    font_fallbacks: dict[str, Any] | None = None,
    inline_objects: list[dict[str, Any]] | None = None,
) -> list[TextInline | EquationInline]:
    """Split PARA_TEXT into TextInline spans based on PARA_CHAR_SHAPE runs."""
    # PCS 엔트리: 4B pos + 4B char_shape_id
    entries: list[tuple[int, int]] = []
    for i in range(0, len(pcs_payload) - 7, 8):
        pos, cs_id = struct.unpack_from("<II", pcs_payload, i)
        entries.append((pos, cs_id))
    if not entries:
        text = _extract_text(pt_payload)
        return [TextInline(text=text)] if text else []

    # 텍스트를 문자 단위 리스트로 분해 (위치 추적)
    _EQ_SENTINEL = "﷐"  # Unicode noncharacter, safe sentinel
    chars_with_pos: list[tuple[int, str]] = []
    inline_eq_map: dict[int, int] = {}  # char position → inline_objects index
    inline_obj_idx = 0
    off = 0
    n = len(pt_payload)
    pos_idx = 0
    while off + 2 <= n:
        (code,) = struct.unpack_from("<H", pt_payload, off)
        if code > 0x001F and code != 0xFFFF:
            if 0xD800 <= code <= 0xDBFF and off + 4 <= n:
                (lo,) = struct.unpack_from("<H", pt_payload, off + 2)
                if 0xDC00 <= lo <= 0xDFFF:
                    cp = 0x10000 + ((code - 0xD800) << 10) + (lo - 0xDC00)
                    chars_with_pos.append((pos_idx, chr(cp)))
                    pos_idx += 2
                    off += 4
                    continue
            chars_with_pos.append((pos_idx, chr(code)))
            pos_idx += 1
            off += 2
        elif code in _PT_CTRL_2BYTE:
            if code == 0x0009 and off + 14 <= n:
                w1 = struct.unpack_from("<H", pt_payload, off + 4)[0]
                w2 = struct.unpack_from("<H", pt_payload, off + 6)[0]
                w3 = struct.unpack_from("<H", pt_payload, off + 8)[0]
                w4 = struct.unpack_from("<H", pt_payload, off + 10)[0]
                w5 = struct.unpack_from("<H", pt_payload, off + 12)[0]
                if w1 == 0 and w2 == 0x0203 and w3 == 0 and w4 == 0 and w5 == 0:
                    pos_idx += 7
                    off += 14
                    continue
            pos_idx += 1
            off += 2
        else:
            # hwp.md §5.2: 인라인 오브젝트 (2+14=16바이트 → 8 charCnt 단위)
            if (inline_objects and inline_obj_idx < len(inline_objects)
                    and inline_objects[inline_obj_idx].get("type") == "eqed"):
                chars_with_pos.append((pos_idx, _EQ_SENTINEL))
                inline_eq_map[pos_idx] = inline_obj_idx
            pos_idx += 8
            inline_obj_idx += 1
            off += 16

    if not chars_with_pos:
        return []

    def cs_id_at(char_pos: int) -> int:
        """Look up CharShape ID for a character position via interval search."""
        cs_id = entries[0][1]
        for p, cid in entries:
            if p <= char_pos:
                cs_id = cid
            else:
                break
        return cs_id

    # 같은 cs_id 구간을 TextInline으로 묶기 (수식 센티넬은 EquationInline으로 분리)
    inlines: list[TextInline | EquationInline] = []
    buf: list[str] = []
    cur_cs_id = cs_id_at(chars_with_pos[0][0])

    for char_pos, ch in chars_with_pos:
        if ch == _EQ_SENTINEL and char_pos in inline_eq_map:
            if buf:
                inlines.append(
                    _make_inline("".join(buf), cur_cs_id, char_shapes, face_names, font_fallbacks)
                )
                buf = []
            eq_idx = inline_eq_map[char_pos]
            eq_data = inline_objects[eq_idx] if inline_objects else {}
            inlines.append(EquationInline(
                latex=eq_data.get("latex"),
                hwp_script=eq_data.get("hwp_script"),
            ))
            continue
        this_cs_id = cs_id_at(char_pos)
        if this_cs_id != cur_cs_id:
            if buf:
                inlines.append(
                    _make_inline("".join(buf), cur_cs_id, char_shapes, face_names, font_fallbacks)
                )
            buf = [ch]
            cur_cs_id = this_cs_id
        else:
            buf.append(ch)

    if buf:
        inlines.append(
            _make_inline("".join(buf), cur_cs_id, char_shapes, face_names, font_fallbacks)
        )

    return inlines


def _make_inline(
    text: str,
    cs_id: int,
    char_shapes: list[dict[str, Any]],
    face_names: list[str | None] | None = None,
    font_fallbacks: dict[str, Any] | None = None,
) -> TextInline:
    """Build a TextInline from text and a CharShape index."""
    cs = char_shapes[cs_id] if cs_id < len(char_shapes) else {}
    font_size = cs.get("font_size_pt")

    font_name: str | None = None
    hangul_fid = cs.get("hangul_face_id")
    latin_fid = cs.get("latin_face_id")

    if font_fallbacks:
        ff = font_fallbacks.get(str(hangul_fid))
        hangul_font = getattr(ff, "hangul", None) if ff else None
        ff_latin = font_fallbacks.get(str(latin_fid))
        latin_font = getattr(ff_latin, "latin", None) if ff_latin else None
        if not latin_font and ff:
            latin_font = getattr(ff, "latin", None)
        if hangul_font and latin_font and hangul_font != latin_font:
            font_name = f"'{latin_font}', '{hangul_font}'"
        elif hangul_font:
            font_name = hangul_font
        elif latin_font:
            font_name = latin_font
    elif face_names:
        if hangul_fid is not None and hangul_fid < len(face_names):
            font_name = face_names[hangul_fid]

    ls = cs.get("letter_spacing")
    co = cs.get("char_offset")
    return TextInline(
        text=text,
        bold=cs.get("bold"),
        italic=cs.get("italic"),
        underline=cs.get("underline"),
        underline_type=cs.get("underline_type"),
        underline_color=cs.get("underline_color"),
        strikethrough=cs.get("strikethrough"),
        strikeout_color=cs.get("strikeout_color"),
        superscript=cs.get("superscript"),
        subscript=cs.get("subscript"),
        color=cs.get("color"),
        background_color=cs.get("shade_color"),
        font_name=font_name,
        font_size=font_size if font_size else None,
        shadow=cs.get("shadow"),
        emboss=cs.get("emboss"),
        engrave=cs.get("engrave"),
        outline=cs.get("outline"),
        char_scale=cs.get("char_scale"),
        letter_spacing=_parse_pct_str(ls) if isinstance(ls, str) else ls,
        char_offset=_parse_pct_str(co) if isinstance(co, str) else co,
    )


# ---------------------------------------------------------------------------
# ParaShape → BlockFormat
# ---------------------------------------------------------------------------


def _para_shape_to_format(
    ps: dict[str, Any],
    border_fills: dict[str, Any] | None = None,
) -> BlockFormat:
    """Convert a parsed ParaShape dict to a BlockFormat."""
    align = ps.get("alignment")
    left_m = ps.get("indent_left_hwp", 0)
    right_m = ps.get("indent_right_hwp", 0)
    first_m = ps.get("indent_first_hwp", 0)
    top_sp = ps.get("space_before_hwp", 0)
    bot_sp = ps.get("space_after_hwp", 0)
    ls_type = ps.get("line_spacing_type")
    ls_val = ps.get("line_spacing_hwp", 0)

    def _to_pt(v: int) -> float | None:
        if not v or v >= 0x80000000:
            return None
        return hwpunit_to_pt(v)

    def _to_pt_signed(v: int) -> float | None:
        if not v:
            return None
        sv = v if v < 0x80000000 else v - 0x100000000
        return hwpunit_to_pt(sv)

    valid_aligns = ("left", "center", "right", "justify")
    safe_align = align if align in valid_aligns else None

    valid_ls_types = ("follow_char", "fixed", "leading_only", "minimum", "ratio")
    safe_ls_type = ls_type if ls_type in valid_ls_types else None

    line_spacing: Ratio | float | None = None
    if ls_val:
        if ls_type in (None, "ratio"):
            line_spacing = Ratio(ls_val)
        else:
            line_spacing = _to_pt(ls_val)

    page_break_before = ps.get("start_new_page") or None
    keep_with_next = ps.get("with_next_paragraph") or None
    widow_orphan = ps.get("protect") or None
    level = ps.get("level")
    outline_level = level if level is not None and 1 <= level <= 7 else None

    bg_color: str | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None

    bf_id = ps.get("border_fill_id")
    if bf_id is not None and border_fills:
        bf_key = str(bf_id - 1) if bf_id > 0 else None
        bf = border_fills.get(bf_key) if bf_key is not None else None
        if bf is not None:
            bf_dict = bf.model_dump() if hasattr(bf, "model_dump") else bf
            bg_color = bf_dict.get("fill_color")
            borders: dict[str, str | None] = {}
            for side in ("top", "bottom", "left", "right"):
                style = bf_dict.get(f"border_{side}_style", "none")
                width = bf_dict.get(f"border_{side}_width", 0)
                color = bf_dict.get(f"border_{side}_color")
                if style and style != "none" and color:
                    css_style = "solid" if style == "solid" else style.replace("_", "-")
                    borders[side] = f"{width}mm {css_style} {color}"
            border_top = borders.get("top")
            border_bottom = borders.get("bottom")
            border_left = borders.get("left")
            border_right = borders.get("right")

    return BlockFormat(
        alignment=safe_align,
        indent_left=_to_pt(left_m),
        indent_right=_to_pt(right_m),
        indent_first=_to_pt_signed(first_m),
        space_before=_to_pt(top_sp),
        space_after=_to_pt(bot_sp),
        line_spacing=line_spacing,
        line_spacing_type=safe_ls_type,
        outline_level=outline_level,
        page_break_before=page_break_before,
        keep_with_next=keep_with_next,
        widow_orphan=widow_orphan,
        background_color=bg_color,
        border_top=border_top,
        border_bottom=border_bottom,
        border_left=border_left,
        border_right=border_right,
    )


# ---------------------------------------------------------------------------
# LIST_HEADER (셀) 파싱
# ---------------------------------------------------------------------------


def _parse_list_header(payload: bytes) -> dict[str, Any]:
    """LIST_HEADER (TableCell context) 파싱.

    Layout:
      0-1:   paragraphs (uint16)
      2-3:   unknown1 (uint16)
      4-7:   listflags (uint32) — bits 2-3: v_align
      8-9:   col (uint16)
      10-11: row (uint16)
      12-13: colspan (uint16)
      14-15: rowspan (uint16)
      16-19: width (SHWPUNIT, int32)
      20-23: height (SHWPUNIT, int32)
      24-25: padding_left (HWPUNIT16, uint16)
      26-27: padding_right (HWPUNIT16)
      28-29: padding_top (HWPUNIT16)
      30-31: padding_bottom (HWPUNIT16)
      32-33: borderfill_id (uint16)
    """
    if len(payload) < 24:
        return {}
    _, _, listflags, col, row, colspan, rowspan, size_x, size_y = struct.unpack_from(
        "<HHIHHHHII", payload, 0
    )
    v_align_val = (listflags >> 2) & 0x3
    v_align_map = {0: "top", 1: "middle", 2: "bottom"}
    result: dict[str, Any] = {
        "col": col,
        "row": row,
        "col_span": max(1, colspan),
        "row_span": max(1, rowspan),
        "size_x": size_x,
        "size_y": size_y,
        "v_align": v_align_map.get(v_align_val, "top"),
    }
    if len(payload) >= 32:
        pad_l, pad_r, pad_t, pad_b = struct.unpack_from("<4H", payload, 24)
        result["padding_left"] = pad_l
        result["padding_right"] = pad_r
        result["padding_top"] = pad_t
        result["padding_bottom"] = pad_b
    if len(payload) >= 34:
        (bf_id,) = struct.unpack_from("<H", payload, 32)
        result["border_fill_id"] = bf_id
    return result


# ---------------------------------------------------------------------------
# 레코드 트리 순회 유틸
# ---------------------------------------------------------------------------


def _collect_children(
    records: list[HwpRecord], start: int, parent_level: int
) -> tuple[list[HwpRecord], int]:
    """start 이후 parent_level보다 높은 레벨의 레코드를 children으로 수집."""
    children: list[HwpRecord] = []
    i = start
    while i < len(records) and records[i].level > parent_level:
        children.append(records[i])
        i += 1
    return children, i


# ---------------------------------------------------------------------------
# 단락 파싱
# ---------------------------------------------------------------------------


def _parse_paragraph(
    ph_rec: HwpRecord,
    children: list[HwpRecord],
    info: DocInfoResult,
    block_counter: itertools.count[int],
    verb_counter: itertools.count[int],
    section: str = "",
    inline_objects: list[dict[str, Any]] | None = None,
) -> tuple[ParagraphBlock | HeadingBlock, dict[str, VerbatimBlock]]:
    """Parse a PARA_HEADER record and its children into a block."""
    pt_payload = b""
    pcs_payload = b""
    pls_payload = b""
    pt_offset: int | None = None

    direct_level = ph_rec.level + 1
    for ch in children:
        if ch.level != direct_level:
            continue
        if ch.tag_id == HWPTAG_PARA_TEXT:
            pt_payload = ch.payload
            pt_offset = ch.offset
        elif ch.tag_id == HWPTAG_PARA_CHAR_SHAPE:
            pcs_payload = ch.payload
        elif ch.tag_id == HWPTAG_PARA_LINE_SEG:
            pls_payload = ch.payload

    ff_dict = info.global_resources.face_names if info.global_resources else None
    inlines = _build_inlines(
        pt_payload, pcs_payload, info.char_shapes, info.face_names, ff_dict,
        inline_objects=inline_objects,
    )

    # ParaShape → BlockFormat
    if len(ph_rec.payload) >= 10:
        (ps_id,) = struct.unpack_from("<H", ph_rec.payload, 8)
        ps = info.para_shapes[ps_id] if ps_id < len(info.para_shapes) else {}
        bf = info.global_resources.border_fills if info.global_resources else None
        fmt = _para_shape_to_format(ps, bf) if ps else None
    else:
        fmt = None

    # StyleId → HeadingBlock 감지 (PARA_HEADER offset 10 = styleId uint8)
    heading_level: int | None = None
    if len(ph_rec.payload) >= 11:
        style_id = ph_rec.payload[10]
        style_name = (
            info.style_names[style_id] if style_id < len(info.style_names) else ""
        )
        heading_level = _heading_level_from_style(style_name)

    blk_id = make_block_id(next(block_counter))
    verb_id = make_verbatim_id(next(verb_counter))

    vb = VerbatimBlock(
        raw_tag_id=ph_rec.tag_id,
        level=ph_rec.level,
        raw_bytes=base64.b64encode(ph_rec.payload).decode(),
        decoded={
            "section": section,
            "level": ph_rec.level,
            "ph_offset": ph_rec.offset,
            "pt_offset": pt_offset,
            "pt_bytes": base64.b64encode(pt_payload).decode() if pt_payload else "",
            "pcs_bytes": base64.b64encode(pcs_payload).decode()
            if pcs_payload
            else None,
            "pls_bytes": base64.b64encode(pls_payload).decode()
            if pls_payload
            else None,
        },
    )

    if heading_level is not None:
        text = "".join(i.text for i in inlines if isinstance(i, TextInline))
        block: ParagraphBlock | HeadingBlock = HeadingBlock(
            type="heading",
            id=blk_id,
            level=heading_level,
            text=text,
            inlines=list(inlines),
            format=fmt,
            verbatim_ref=verb_id,
        )
    else:
        block = ParagraphBlock(
            type="paragraph",
            id=blk_id,
            inlines=list(inlines),
            format=fmt,
            verbatim_ref=verb_id,
        )
    return block, {verb_id: vb}


# ---------------------------------------------------------------------------
# 표 파싱
# ---------------------------------------------------------------------------


def _parse_table(
    ctrl_rec: HwpRecord,
    ctrl_children: list[HwpRecord],
    info: DocInfoResult,
    block_counter: itertools.count[int],
    verb_counter: itertools.count[int],
    section: str = "",
) -> tuple[TableBlock, dict[str, VerbatimBlock]]:
    """Parse a 'tbl ' CTRL_HEADER and its children into a TableBlock."""
    verbatim_map: dict[str, VerbatimBlock] = {}
    position = _parse_ctrl_common(ctrl_rec.payload)

    # tbl_level: LIST_HEADER, TABLE 레코드가 위치하는 레벨
    tbl_level = ctrl_rec.level + 1
    cells_by_rc: dict[tuple[int, int], TableCell] = {}

    # TABLE record (tag=77) — 표 속성 레코드, 보존 필요
    tbl_rec: HwpRecord | None = None

    # HWP 구조: LIST_HEADER(셀)과 그 안의 PARA_HEADER가 같은 레벨에 나란히 위치.
    # 따라서 각 LIST_HEADER 이후 다음 LIST_HEADER(또는 TABLE record)까지의 모든
    # 레코드를 셀 내용으로 간주한다.
    i = 0
    while i < len(ctrl_children):
        rec = ctrl_children[i]

        if rec.level == tbl_level and rec.tag_id == HWPTAG_TABLE and tbl_rec is None:
            tbl_rec = rec
            i += 1
            continue

        if rec.level == tbl_level and rec.tag_id == HWPTAG_LIST_HEADER:
            lh = _parse_list_header(rec.payload)
            row, col = lh.get("row", 0), lh.get("col", 0)

            # 다음 LIST_HEADER 또는 TABLE record(같은 레벨)까지 셀 내용 수집
            j = i + 1
            cell_children: list[HwpRecord] = []
            while j < len(ctrl_children):
                r = ctrl_children[j]
                if r.level == tbl_level and r.tag_id in (
                    HWPTAG_LIST_HEADER,
                    HWPTAG_TABLE,
                ):
                    break
                cell_children.append(r)
                j += 1

            # PARA_HEADER가 tbl_level에 위치하므로 base_level=tbl_level로 파싱
            cell_blocks, cell_verb = _parse_block_list(
                cell_children, tbl_level, info, block_counter, verb_counter, section
            )
            verbatim_map.update(cell_verb)

            cell_verb_id = make_verbatim_id(next(verb_counter))
            cell_vb = VerbatimBlock(
                raw_tag_id=rec.tag_id,
                level=rec.level,
                raw_bytes=base64.b64encode(rec.payload).decode(),
                decoded={"level": rec.level},
            )
            verbatim_map[cell_verb_id] = cell_vb

            cell_id = make_block_id(next(block_counter))
            v_align = lh.get("v_align")
            cfmt = CellFormat(
                vertical_align=v_align
                if v_align in {"top", "middle", "bottom"}
                else None,
            )
            for side in ("top", "bottom", "left", "right"):
                pad_val = lh.get(f"padding_{side}", 0)
                if pad_val:
                    setattr(cfmt, f"padding_{side}", hwpunit_to_pt(pad_val))
            bf_id = lh.get("border_fill_id")
            if bf_id and bf_id > 0:
                bf_key = str(bf_id - 1)
                bf_def = info.global_resources.border_fills.get(bf_key)
                if bf_def:
                    if bf_def.fill_color:
                        cfmt.background_color = bf_def.fill_color
                    for side in ("top", "bottom", "left", "right"):
                        sc = getattr(bf_def, f"border_{side}_color", None)
                        ss = getattr(bf_def, f"border_{side}_style", None)
                        sw = getattr(bf_def, f"border_{side}_width", None)
                        if sc and ss and ss != "none":
                            w_mm = sw if sw else 0.1
                            w_pt = round(w_mm * 2.835, 1)
                            _CSS_BORDER = {"dash": "dashed", "dot": "dotted", "dash_dot": "dashed"}
                            css_style = _CSS_BORDER.get(ss, "solid")
                            setattr(cfmt, f"border_{side}", f"{w_pt}pt {css_style} {sc}")
            raw_w = lh.get("size_x")
            raw_h = lh.get("size_y")
            cells_by_rc[(row, col)] = TableCell(
                id=cell_id,
                row_span=lh.get("row_span", 1),
                col_span=lh.get("col_span", 1),
                width=raw_w * _HU_TO_PT if raw_w is not None else None,
                height=raw_h * _HU_TO_PT if raw_h is not None else None,
                content=cell_blocks,
                format=cfmt,
                verbatim_ref=cell_verb_id,
            )
            i = j
        else:
            i += 1

    # 행 재구성
    if cells_by_rc:
        max_row = max(ri for ri, _ in cells_by_rc)
        rows = []
        for row_idx in range(max_row + 1):
            row_cells = [
                v for (ri, _), v in sorted(cells_by_rc.items()) if ri == row_idx
            ]
            if row_cells:
                rows.append(TableRow(cells=row_cells))
    else:
        rows = []

    tbl_props: dict[str, Any] = {}
    tbl_cell_spacing: float | None = None
    tbl_default_padding: float | None = None
    tbl_repeat_header: bool | None = None
    tbl_bf_id: int | None = None
    if tbl_rec and len(tbl_rec.payload) >= 18:
        tp = tbl_rec.payload
        tbl_attr = struct.unpack_from("<I", tp, 0)[0]
        n_rows, n_cols = struct.unpack_from("<HH", tp, 4)
        cell_spacing = struct.unpack_from("<H", tp, 8)[0]
        m_left, m_right, m_top, m_bottom = struct.unpack_from("<4H", tp, 10)
        tbl_props = {
            "attr": tbl_attr,
            "n_rows": n_rows,
            "n_cols": n_cols,
            "cell_spacing": cell_spacing,
            "margin_left": m_left,
            "margin_right": m_right,
            "margin_top": m_top,
            "margin_bottom": m_bottom,
        }
        if cell_spacing:
            tbl_cell_spacing = hwpunit_to_pt(cell_spacing)
        avg_pad = (m_left + m_right + m_top + m_bottom) / 4
        if avg_pad:
            tbl_default_padding = hwpunit_to_pt(avg_pad)
        tbl_repeat_header = bool(tbl_attr & (1 << 2)) or None
        # borderfill_id is after rowcols array: offset 18 + n_rows*2
        bf_off = 18 + n_rows * 2
        if len(tp) >= bf_off + 2:
            (bf_id,) = struct.unpack_from("<H", tp, bf_off)
            tbl_bf_id = bf_id if bf_id > 0 else None

    tbl_id = make_block_id(next(block_counter))
    tbl_verb_id = make_verbatim_id(next(verb_counter))
    verbatim_map[tbl_verb_id] = VerbatimBlock(
        raw_tag_id=ctrl_rec.tag_id,
        level=ctrl_rec.level,
        raw_bytes=base64.b64encode(ctrl_rec.payload).decode(),
        decoded={
            "section": section,
            "table_rec_bytes": base64.b64encode(tbl_rec.payload).decode()
            if tbl_rec
            else None,
            "table_props": tbl_props if tbl_props else None,
        },
    )

    table = TableBlock(
        type="table",
        id=tbl_id,
        rows=rows,
        position=position,
        cell_spacing=tbl_cell_spacing,
        default_padding=tbl_default_padding,
        repeat_header=tbl_repeat_header,
        border_fill_id=tbl_bf_id,
        verbatim_ref=tbl_verb_id,
    )
    return table, verbatim_map


# ---------------------------------------------------------------------------
# 각주/미주 파싱
# ---------------------------------------------------------------------------


def _parse_footnote_endnote(
    ctrl_rec: HwpRecord,
    ctrl_children: list[HwpRecord],
    info: DocInfoResult,
    block_counter: itertools.count[int],
    verb_counter: itertools.count[int],
    section: str,
    is_endnote: bool = False,
) -> tuple[FootnoteBlock | EndnoteBlock, dict[str, VerbatimBlock]]:
    """CTRL_HEADER("fn  " / "en  ") → FootnoteBlock / EndnoteBlock."""
    verbatim_map: dict[str, VerbatimBlock] = {}
    ctrl_level = ctrl_rec.level

    # LIST_HEADER 이후의 PARA_HEADER들을 내용으로 파싱
    content_records: list[HwpRecord] = []
    found_list_header = False
    for rec in ctrl_children:
        if rec.tag_id == HWPTAG_LIST_HEADER and rec.level == ctrl_level + 1:
            found_list_header = True
            continue
        if found_list_header:
            content_records.append(rec)

    content_blocks: list[Any] = []
    if content_records:
        base_level = ctrl_level + 1
        content_blocks, cv = _parse_block_list(
            content_records, base_level, info, block_counter, verb_counter, section
        )
        verbatim_map.update(cv)

    blk_id = make_block_id(next(block_counter))
    verb_id = make_verbatim_id(next(verb_counter))
    verbatim_map[verb_id] = VerbatimBlock(
        raw_tag_id=ctrl_rec.tag_id,
        level=ctrl_rec.level,
        raw_bytes=base64.b64encode(ctrl_rec.payload).decode(),
        decoded={"section": section, "ph_offset": ctrl_rec.offset},
    )

    # ref 번호: CTRL_HEADER payload offset 4 = number(u32)
    ref_num = "1"
    if len(ctrl_rec.payload) >= 8:
        (num,) = struct.unpack_from("<I", ctrl_rec.payload, 4)
        if num > 0:
            ref_num = str(num)

    if is_endnote:
        block: FootnoteBlock | EndnoteBlock = EndnoteBlock(
            type="endnote",
            id=blk_id,
            ref=ref_num,
            content=content_blocks,
            verbatim_ref=verb_id,
        )
    else:
        block = FootnoteBlock(
            type="footnote",
            id=blk_id,
            ref=ref_num,
            content=content_blocks,
            verbatim_ref=verb_id,
        )
    return block, verbatim_map


# ---------------------------------------------------------------------------
# Header/Footer (머리글/꼬리글) 파싱
# ---------------------------------------------------------------------------

_PLACES_MAP = {0: "all", 1: "even", 2: "odd"}


def _parse_header_footer(
    ctrl_rec: HwpRecord,
    ctrl_children: list[HwpRecord],
    info: DocInfoResult,
    block_counter: itertools.count[int],
    verb_counter: itertools.count[int],
    section: str,
    is_footer: bool = False,
) -> tuple[HeaderBlock | FooterBlock, dict[str, VerbatimBlock]]:
    """CTRL_HEADER("head" / "foot") → HeaderBlock / FooterBlock."""
    verbatim_map: dict[str, VerbatimBlock] = {}
    ctrl_level = ctrl_rec.level

    apply_to: str | None = None
    if len(ctrl_rec.payload) >= 8:
        (attr,) = struct.unpack_from("<I", ctrl_rec.payload, 4)
        places = attr & 0x3
        apply_to = _PLACES_MAP.get(places, "all")

    content_records: list[HwpRecord] = []
    found_list_header = False
    for rec in ctrl_children:
        if rec.tag_id == HWPTAG_LIST_HEADER and rec.level == ctrl_level + 1:
            found_list_header = True
            continue
        if found_list_header:
            content_records.append(rec)

    content_blocks: list[Any] = []
    if content_records:
        base_level = ctrl_level + 1
        content_blocks, cv = _parse_block_list(
            content_records, base_level, info, block_counter, verb_counter, section
        )
        verbatim_map.update(cv)

    blk_id = make_block_id(next(block_counter))
    verb_id = make_verbatim_id(next(verb_counter))
    verbatim_map[verb_id] = VerbatimBlock(
        raw_tag_id=ctrl_rec.tag_id,
        level=ctrl_rec.level,
        raw_bytes=base64.b64encode(ctrl_rec.payload).decode(),
        decoded={"section": section, "ph_offset": ctrl_rec.offset},
    )

    if is_footer:
        block: HeaderBlock | FooterBlock = FooterBlock(
            type="footer",
            id=blk_id,
            apply_to=apply_to,
            content=content_blocks,
            verbatim_ref=verb_id,
        )
    else:
        block = HeaderBlock(
            type="header",
            id=blk_id,
            apply_to=apply_to,
            content=content_blocks,
            verbatim_ref=verb_id,
        )
    return block, verbatim_map


# ---------------------------------------------------------------------------
# CTRL_HEADER 공통 필드 파싱 (개체 위치 정보)
# ---------------------------------------------------------------------------


def _parse_ctrl_common(payload: bytes) -> PositionInfo | None:
    """CTRL_HEADER 공통 헤더에서 위치 정보 추출.

    Layout (ctrlId 이후, pyhwp common_controls.py 기준):
      offset 4:  attr (uint32) — CommonControlFlags
      offset 8:  y (SHWPUNIT, signed int32)
      offset 12: x (SHWPUNIT, signed int32)
      offset 16: width (HWPUNIT, uint32)
      offset 20: height (HWPUNIT, uint32)
      offset 24: z_order (int16)
      offset 26: unknown1 (int16)
      offset 28: margin_left (HWPUNIT16, uint16)
      offset 30: margin_right (uint16)
      offset 32: margin_top (uint16)
      offset 34: margin_bottom (uint16)
      offset 36: instance_id (uint32)

    attr bits (pyhwp CommonControlFlags):
      bit 0:     inline (like_char)
      bit 2:     affect_line_spacing
      bits 3-4:  vrelto (0=paper, 1=page, 2=paragraph)
      bits 5-7:  valign (0=top, 1=middle, 2=bottom)
      bits 8-9:  hrelto (0=paper, 1=page, 2=column, 3=paragraph)
      bits 10-12: halign (0=left, 1=center, 2=right, 3=inside, 4=outside)
      bit 13:    restrict_in_page
      bit 14:    overlap_others
      bits 15-17: width_relto
      bits 18-19: height_relto
      bit 20:    protect_size_when_vrelto_paragraph
      bits 21-23: flow (0=float, 1=block, 2=back, 3=front)
      bits 24-25: text_side (0=both, 1=left, 2=right, 3=larger)
      bits 26-27: number_category
    """
    if len(payload) < 28:
        return None
    (attr,) = struct.unpack_from("<I", payload, 4)
    y_off = struct.unpack_from("<i", payload, 8)[0]
    x_off = struct.unpack_from("<i", payload, 12)[0]
    width = struct.unpack_from("<I", payload, 16)[0]
    height = struct.unpack_from("<I", payload, 20)[0]
    z_order = struct.unpack_from("<h", payload, 24)[0]

    like_char = bool(attr & 0x1)
    affect_ls = bool(attr & (1 << 2))
    vrelto_val = (attr >> 3) & 0x3
    valign_val = (attr >> 5) & 0x7
    hrelto_val = (attr >> 8) & 0x3
    halign_val = (attr >> 10) & 0x7
    restrict_in_page = bool(attr & (1 << 13))
    overlap_others = bool(attr & (1 << 14))
    width_relto_val = (attr >> 15) & 0x7
    height_relto_val = (attr >> 18) & 0x3
    flow_val = (attr >> 21) & 0x7
    text_side_val = (attr >> 24) & 0x3

    margin_left = margin_right = margin_top = margin_bottom = 0
    if len(payload) >= 36:
        margin_left, margin_right, margin_top, margin_bottom = struct.unpack_from(
            "<4H", payload, 28
        )

    return PositionInfo(
        x=x_off * _HU_TO_PT,
        y=y_off * _HU_TO_PT,
        width=width * _HU_TO_PT,
        height=height * _HU_TO_PT,
        z_order=z_order,
        like_char=like_char,
        flow=_FLOW_MAP.get(flow_val),
        text_side=_TEXT_SIDE_MAP.get(text_side_val),
        halign=_HALIGN_MAP.get(halign_val),
        valign=_VALIGN_MAP.get(valign_val),
        hrelto=_HRELTO_MAP.get(hrelto_val),
        vrelto=_VRELTO_MAP.get(vrelto_val),
        width_relto=_WIDTH_RELTO_MAP.get(width_relto_val),
        height_relto=_HEIGHT_RELTO_MAP.get(height_relto_val),
        margin_top=margin_top * _HU_TO_PT if margin_top else None,
        margin_bottom=margin_bottom * _HU_TO_PT if margin_bottom else None,
        margin_left=margin_left * _HU_TO_PT if margin_left else None,
        margin_right=margin_right * _HU_TO_PT if margin_right else None,
        restrict_in_page=restrict_in_page or None,
        overlap_others=overlap_others or None,
        affect_line_spacing=affect_ls or None,
    )


# ---------------------------------------------------------------------------
# SHAPE_COMPONENT fill/line 파싱
# ---------------------------------------------------------------------------


def _parse_shape_fill_line(pay: bytes) -> tuple[str | None, str | None, float | None]:
    """SHAPE_COMPONENT(tag=76) 페이로드에서 fill_color, line_color, line_width를 추출한다.

    Returns (fill_color, line_color, line_width_pt) as CSS hex strings / pt or None.
    """
    if len(pay) < 12:
        return None, None, None

    # ctrl_id가 두 번 반복되면 top-level shape (8B), 아니면 group child (4B)
    ctrl_id_size = 8 if pay[0:4] == pay[4:8] else 4
    off = ctrl_id_size

    # CommonPart: 42 bytes
    if off + 42 > len(pay):
        return None, None, None
    off += 42

    # RenderingInfo: 2B count + 48B translation + count * 96B pairs
    if off + 2 > len(pay):
        return None, None, None
    cnt = struct.unpack_from("<H", pay, off)[0]
    off += 2 + 48 + cnt * 96

    if off > len(pay):
        return None, None, None

    remaining = pay[off:]
    fill_color = None
    line_color = None
    line_width_pt = None

    # 남은 바이트에서 LineInfo(13B) + FillInfo(가변) + ShadowInfo(~22B) 파싱 시도
    # LineInfo 유무에 따라 두 가지 해석을 시도한다
    for has_line in (True, False):
        roff = 0
        lc = None
        lw = None
        if has_line:
            if len(remaining) < 13:
                continue
            line_style = remaining[8] & 0x0F
            lw_hu = struct.unpack_from("<I", remaining, 4)[0]
            if lw_hu > 0 and line_style > 0:
                lc_raw = struct.unpack_from("<I", remaining, 0)[0]
                lc = "#{:02x}{:02x}{:02x}".format(
                    lc_raw & 0xFF, (lc_raw >> 8) & 0xFF, (lc_raw >> 16) & 0xFF
                )
                lw = lw_hu * 0.01
            roff = 13

        if roff + 4 > len(remaining):
            continue

        fill_type = struct.unpack_from("<I", remaining, roff)[0]
        roff += 4

        fc = None
        if fill_type & 1:  # solid fill
            if roff + 12 > len(remaining):
                continue
            bg_raw = struct.unpack_from("<I", remaining, roff)[0]
            fc = "#{:02x}{:02x}{:02x}".format(
                bg_raw & 0xFF, (bg_raw >> 8) & 0xFF, (bg_raw >> 16) & 0xFF
            )
            roff += 12  # bgColor(4) + patternColor(4) + patternType(4)
            # additionalProperty size
            if roff + 4 <= len(remaining):
                add_size = struct.unpack_from("<I", remaining, roff)[0]
                roff += 4 + add_size
            # alpha byte
            if roff < len(remaining):
                roff += 1
        elif fill_type == 0:
            roff += 4  # zero-padding

        # shadow 영역이 18~24 바이트 남으면 유효한 파싱
        shadow_left = len(remaining) - roff
        if 16 <= shadow_left <= 26:
            fill_color = fc
            line_color = lc
            line_width_pt = lw
            break

    return fill_color, line_color, line_width_pt


# ---------------------------------------------------------------------------
# $con 내부 nested sub-shape 추출
# ---------------------------------------------------------------------------


def _parse_shape_position(payload: bytes) -> PositionInfo | None:
    """SHAPE_COMPONENT(tag=76) 페이로드에서 위치/크기 추출.

    Layout: 4B shape_type, 4B x, 4B y,
            4B groupLevel+localVer, 4B origW, 4B origH, 4B curW, 4B curH, ...
    curW/curH가 존재하면 리사이즈 후 실제 치수를 사용.
    """
    if len(payload) < 24:
        return None
    x, y = struct.unpack_from("<ii", payload, 4)
    ow, oh = struct.unpack_from("<II", payload, 16)
    if len(payload) >= 32:
        cw, ch = struct.unpack_from("<II", payload, 24)
        if cw > 0 and ch > 0:
            return PositionInfo(x=x * _HU_TO_PT, y=y * _HU_TO_PT, width=cw * _HU_TO_PT, height=ch * _HU_TO_PT)
    return PositionInfo(x=x * _HU_TO_PT, y=y * _HU_TO_PT, width=ow * _HU_TO_PT, height=oh * _HU_TO_PT)


def _extract_child_shapes(
    ctrl_children: list[HwpRecord],
    block_counter: itertools.count[int],
    info: DocInfoResult | None = None,
) -> list[Block]:
    """$con 컨테이너에서 기하 도형 및 $pic 이미지 자식을 추출."""
    sc_indices = [
        i for i, r in enumerate(ctrl_children)
        if r.tag_id == HWPTAG_SHAPE_COMPONENT and len(r.payload) >= 4
    ]
    results: list[Block] = []
    for si, idx in enumerate(sc_indices):
        pay = ctrl_children[idx].payload
        st = pay[:4][::-1].decode("ascii", errors="replace")
        if st == "$con":
            continue
        next_sc = sc_indices[si + 1] if si + 1 < len(sc_indices) else len(ctrl_children)
        has_lh = any(
            ctrl_children[k].tag_id == HWPTAG_LIST_HEADER
            for k in range(idx + 1, next_sc)
        )
        if has_lh:
            continue
        pos = _parse_shape_position(pay)
        if st == "$pic" and info is not None:
            bin_item_id = None
            for k in range(idx + 1, next_sc):
                rec = ctrl_children[k]
                if rec.tag_id == HWPTAG_SHAPE_COMPONENT_PIC and len(rec.payload) >= 73:
                    bin_item_id = struct.unpack_from("<H", rec.payload, 71)[0]
                    break
            if bin_item_id is not None:
                src = _resolve_bin_src(bin_item_id, info)
                results.append(ImageBlock(
                    type="image",
                    id=make_block_id(next(block_counter)),
                    src=src,
                    width=pos.width if pos and pos.width else None,
                    height=pos.height if pos and pos.height else None,
                    position=pos,
                ))
                continue
        fc, lc, lw = _parse_shape_fill_line(pay)
        results.append(DrawingBlock(
            type="drawing",
            id=make_block_id(next(block_counter)),
            shape_type=st,
            position=pos,
            background_color=fc,
            line_color=lc,
            line_width=lw,
        ))
    return sorted(results, key=lambda s: (
        s.position.y if s.position else 0,
        s.position.x if s.position else 0,
    ))


def _extract_nested_textboxes(
    ctrl_children: list[HwpRecord],
    main_lh_idx: int,
    info: DocInfoResult,
    block_counter: itertools.count[int],
    verb_counter: itertools.count[int],
    section: str,
    *,
    scan_all: bool = False,
) -> tuple[list[Any], dict[str, VerbatimBlock]]:
    """$con 컨테이너에서 sub-shape 텍스트박스를 추출.

    scan_all=True이면 모든 LIST_HEADER를 추출 (첫 LH 포함).
    scan_all=False이면 첫 LH scope 이후의 LIST_HEADER만 추출 (기존 동작).
    """
    results: list[Any] = []
    verbatim_map: dict[str, VerbatimBlock] = {}

    if scan_all:
        i = 0
    else:
        main_lh_level = ctrl_children[main_lh_idx].level
        exit_idx = len(ctrl_children)
        for k in range(main_lh_idx + 1, len(ctrl_children)):
            if ctrl_children[k].level < main_lh_level:
                exit_idx = k
                break
        i = exit_idx
    while i < len(ctrl_children):
        rec = ctrl_children[i]
        if rec.tag_id == HWPTAG_LIST_HEADER:
            lh_level = rec.level
            # 직전 SHAPE_COMPONENT에서 위치/스타일 추출
            pos = None
            fill_c = None
            line_c = None
            line_w = None
            for j in range(i - 1, -1, -1):
                cr = ctrl_children[j]
                if cr.tag_id == HWPTAG_SHAPE_COMPONENT and len(cr.payload) >= 24:
                    pos = _parse_shape_position(cr.payload)
                    fc, lc, lw = _parse_shape_fill_line(cr.payload)
                    fill_c = fc
                    line_c = lc
                    line_w = lw
                    break
                if cr.tag_id == HWPTAG_LIST_HEADER:
                    break
            # LH 이후 content 수집: LH와 같은 레벨의 PARA_HEADER 포함
            content_recs = []
            round_corner = None
            j = i + 1
            while j < len(ctrl_children):
                cr = ctrl_children[j]
                if cr.level < lh_level:
                    break
                if cr.level == lh_level and cr.tag_id == HWPTAG_SHAPE_COMPONENT_PIC:
                    j += 1
                    break
                if cr.level == lh_level and cr.tag_id == HWPTAG_SHAPE_COMPONENT:
                    break
                if cr.tag_id == HWPTAG_SHAPE_COMPONENT_RECT and len(cr.payload) >= 4:
                    rc = struct.unpack_from("<I", cr.payload, 0)[0]
                    if rc > 0:
                        round_corner = rc
                    j += 1
                    continue
                content_recs.append(cr)
                j += 1
            if content_recs:
                blocks, cv = _parse_block_list(
                    content_recs, lh_level, info,
                    block_counter, verb_counter, section,
                )
                if blocks:
                    tb_id = make_block_id(next(block_counter))
                    br_pt = None
                    if round_corner and pos and pos.width and pos.height:
                        shorter = min(pos.width, pos.height)
                        br_pt = shorter * round_corner / 100.0
                    tb = TextBoxBlock(
                        type="text_box",
                        id=tb_id,
                        content=blocks,
                        position=pos,
                        background_color=fill_c,
                        line_color=line_c,
                        line_width=line_w,
                        border_radius=br_pt,
                    )
                    results.append(tb)
                verbatim_map.update(cv)
            i = j
            continue
        i += 1

    return results, verbatim_map


# ---------------------------------------------------------------------------
# GSO (그리기 객체) 파싱
# ---------------------------------------------------------------------------


def _parse_gso(
    ctrl_rec: HwpRecord,
    ctrl_children: list[HwpRecord],
    info: DocInfoResult,
    block_counter: itertools.count[int],
    verb_counter: itertools.count[int],
    section: str,
) -> tuple[ImageBlock | DrawingBlock | TextBoxBlock | ChartBlock | TextArtBlock, dict[str, VerbatimBlock]]:
    """CTRL_HEADER('gso ') → ImageBlock / DrawingBlock / TextBoxBlock / ChartBlock / TextArtBlock."""
    verbatim_map: dict[str, VerbatimBlock] = {}
    position = _parse_ctrl_common(ctrl_rec.payload)

    shape_type: str | None = None
    bin_item_id: int | None = None
    has_textbox_content = False
    fill_color: str | None = None
    line_color: str | None = None
    line_width_pt: float | None = None
    bg_image_src: str | None = None

    # 1단계: 전체 자식 스캔으로 shape_type, bin_item_id, textbox 여부 파악
    seen_list_header = False
    for rec in ctrl_children:
        if rec.tag_id == HWPTAG_SHAPE_COMPONENT and shape_type is None:
            if len(rec.payload) >= 4:
                shape_type = rec.payload[:4][::-1].decode("ascii", errors="replace")
        if rec.tag_id == HWPTAG_SHAPE_COMPONENT_PIC:
            if len(rec.payload) >= 73:
                if shape_type != "$con":
                    bin_item_id = struct.unpack_from("<H", rec.payload, 71)[0]
                elif not seen_list_header and bin_item_id is None:
                    bin_item_id = struct.unpack_from("<H", rec.payload, 71)[0]
        if rec.tag_id == HWPTAG_LIST_HEADER:
            has_textbox_content = True
            seen_list_header = True

    # 2단계: $con 컨테이너 처리 — $pic 배경 이미지 + $rec 텍스트박스 분리
    if shape_type == "$con" and has_textbox_content and bin_item_id is not None:
        bg_image_src = _resolve_bin_src(bin_item_id, info)

    # 3단계: fill/line 추출 — LIST_HEADER 직전의 SHAPE에서
    lh_shape_idx: int | None = None
    round_corner: int | None = None
    for idx, rec in enumerate(ctrl_children):
        if rec.tag_id == HWPTAG_SHAPE_COMPONENT:
            lh_shape_idx = idx
        if rec.tag_id == HWPTAG_LIST_HEADER:
            if lh_shape_idx is not None:
                fc, lc, lw = _parse_shape_fill_line(
                    ctrl_children[lh_shape_idx].payload
                )
                fill_color = fc
                line_color = lc
                line_width_pt = lw
            break
    # SHAPE_COMPONENT_RECT는 content 뒤에 위치 — 전체 스캔
    for rec in ctrl_children:
        if rec.tag_id == HWPTAG_SHAPE_COMPONENT_RECT and len(rec.payload) >= 4:
            rc = struct.unpack_from("<I", rec.payload, 0)[0]
            if rc > 0:
                round_corner = rc
                break

    if not has_textbox_content:
        for rec in ctrl_children:
            if rec.tag_id == HWPTAG_SHAPE_COMPONENT and len(rec.payload) >= 8:
                st = rec.payload[:4][::-1].decode("ascii", errors="replace")
                if st != "$con":
                    fc, lc, lw = _parse_shape_fill_line(rec.payload)
                    if fc or lc:
                        fill_color = fc
                        line_color = lc
                        line_width_pt = lw

    blk_id = make_block_id(next(block_counter))
    verb_id = make_verbatim_id(next(verb_counter))
    verbatim_map[verb_id] = VerbatimBlock(
        raw_tag_id=ctrl_rec.tag_id,
        level=ctrl_rec.level,
        raw_bytes=base64.b64encode(ctrl_rec.payload).decode(),
        decoded={
            "section": section,
            "ph_offset": ctrl_rec.offset,
            "shape_type": shape_type,
            "bin_item_id": bin_item_id,
        },
    )

    # ImageClip + PictureInfo from SHAPE_COMPONENT_PIC
    img_crop: dict[str, int] = {}
    img_brightness: int | None = None
    img_contrast: int | None = None
    for rec in ctrl_children:
        if rec.tag_id == HWPTAG_SHAPE_COMPONENT_PIC and len(rec.payload) >= 70:
            pay = rec.payload
            cl, ct, cr, cb = struct.unpack_from("<4i", pay, 44)
            if cl or ct or cr or cb:
                img_crop = {"left": cl, "top": ct, "right": cr, "bottom": cb}
            bright = struct.unpack_from("<b", pay, 68)[0]
            contr = struct.unpack_from("<b", pay, 69)[0]
            if bright:
                img_brightness = bright
            if contr:
                img_contrast = contr
            break

    block: ImageBlock | DrawingBlock | TextBoxBlock | ChartBlock | TextArtBlock
    if shape_type == "$pic" and bin_item_id is not None:
        src = _resolve_bin_src(bin_item_id, info)
        block = ImageBlock(
            type="image",
            id=blk_id,
            src=src,
            width=position.width if position and position.width else None,
            height=position.height if position and position.height else None,
            position=position,
            crop_left=img_crop.get("left"),
            crop_top=img_crop.get("top"),
            crop_right=img_crop.get("right"),
            crop_bottom=img_crop.get("bottom"),
            brightness=img_brightness,
            contrast=img_contrast,
            verbatim_ref=verb_id,
        )
    elif has_textbox_content:
        lh_idx = None
        tb_pad: dict[str, float | None] = {}
        tb_valign: str | None = None
        for idx, rec in enumerate(ctrl_children):
            if rec.tag_id == HWPTAG_LIST_HEADER:
                lh_idx = idx
                pay = rec.payload
                if len(pay) >= 8:
                    listflags = struct.unpack_from("<I", pay, 4)[0]
                    va = (listflags >> 2) & 0x3
                    tb_valign = {0: "top", 1: "middle", 2: "bottom"}.get(va)
                if len(pay) >= 16:
                    pl, pr, pt, pb = struct.unpack_from("<4H", pay, 8)
                    for side, v in [("left", pl), ("right", pr), ("top", pt), ("bottom", pb)]:
                        if v:
                            tb_pad[side] = hwpunit_to_pt(v)
                break
        content_blocks: list[Any] = []
        if shape_type == "$con" and lh_idx is not None:
            # $con 컨테이너: 각 sub-shape의 LIST_HEADER를 개별 TextBoxBlock으로 추출.
            # _parse_block_list는 사용하지 않음 — sibling sub-shape의 PARA_HEADER를
            # 동일 level에서 잘못 수집하여 중복이 발생하기 때문.
            nested, nv = _extract_nested_textboxes(
                ctrl_children, lh_idx, info,
                block_counter, verb_counter, section,
                scan_all=True,
            )
            content_blocks.extend(nested)
            verbatim_map.update(nv)
            geom_children = _extract_child_shapes(ctrl_children, block_counter, info)
            content_blocks.extend(geom_children)
        elif lh_idx is not None:
            lh_rec = ctrl_children[lh_idx]
            content_records = ctrl_children[lh_idx + 1:]
            if content_records:
                content_blocks, cv = _parse_block_list(
                    content_records, lh_rec.level, info,
                    block_counter, verb_counter, section,
                )
                verbatim_map.update(cv)
        br_pt = None
        if round_corner and position and position.width and position.height:
            shorter = min(position.width, position.height)
            br_pt = shorter * round_corner / 100.0
        block = TextBoxBlock(
            type="text_box",
            id=blk_id,
            content=content_blocks,
            position=position,
            padding_top=tb_pad.get("top"),
            padding_bottom=tb_pad.get("bottom"),
            padding_left=tb_pad.get("left"),
            padding_right=tb_pad.get("right"),
            vertical_align=tb_valign if tb_valign in ("top", "middle", "bottom") else None,
            background_color=fill_color,
            background_image=bg_image_src,
            line_color=line_color,
            line_width=line_width_pt,
            border_radius=br_pt,
            verbatim_ref=verb_id,
        )
    elif shape_type == "$cht":
        block = ChartBlock(
            type="chart",
            id=blk_id,
            position=position,
            description="[chart: not implemented]",
            verbatim_ref=verb_id,
        )
    elif shape_type == "$art":
        block = TextArtBlock(
            type="text_art",
            id=blk_id,
            position=position,
            verbatim_ref=verb_id,
        )
    else:
        child_drawing: list[DrawingBlock] = []
        child_content: list[Block] = []
        if shape_type == "$con":
            for cs in _extract_child_shapes(ctrl_children, block_counter, info):
                if isinstance(cs, DrawingBlock):
                    child_drawing.append(cs)
                else:
                    child_content.append(cs)
        block = DrawingBlock(
            type="drawing",
            id=blk_id,
            shape_type=shape_type,
            position=position,
            background_color=fill_color,
            line_color=line_color,
            line_width=line_width_pt,
            content=child_content,
            children=child_drawing,
            verbatim_ref=verb_id,
        )
    return block, verbatim_map


def _resolve_bin_src(bin_item_id: int, info: DocInfoResult) -> str:
    """binItemId(1-based) → BinData 스트림 경로 문자열."""
    idx = bin_item_id - 1
    if 0 <= idx < len(info.bindata_items):
        bd = info.bindata_items[idx]
        stream = bd.get("stream")
        if stream:
            return f"bindata:{stream}"
    return f"bindata:BIN{bin_item_id:04X}"


def _parse_equation(
    ctrl_rec: HwpRecord,
    ctrl_children: list[HwpRecord],
    block_counter: itertools.count[int],
    verb_counter: itertools.count[int],
    section: str,
) -> tuple[EquationBlock, dict[str, VerbatimBlock]]:
    """CTRL_HEADER("eqed") → EquationBlock. tag=88 (EQEDIT)에서 스크립트 추출."""
    verbatim_map: dict[str, VerbatimBlock] = {}

    hwp_script: str | None = None
    for rec in ctrl_children:
        if rec.tag_id == HWPTAG_EQEDIT:
            payload = rec.payload
            try:
                if len(payload) >= 6:
                    char_count = struct.unpack_from("<H", payload, 4)[0]
                    script_end = 6 + char_count * 2
                    if script_end <= len(payload):
                        hwp_script = payload[6:script_end].decode("utf-16-le")
                    else:
                        hwp_script = payload[6:].decode("utf-16-le").rstrip("\x00")
                else:
                    hwp_script = payload.decode("utf-16-le").rstrip("\x00")
            except (UnicodeDecodeError, struct.error):
                hwp_script = None
            break

    blk_id = make_block_id(next(block_counter))
    verb_id = make_verbatim_id(next(verb_counter))
    verbatim_map[verb_id] = VerbatimBlock(
        raw_tag_id=ctrl_rec.tag_id,
        level=ctrl_rec.level,
        raw_bytes=base64.b64encode(ctrl_rec.payload).decode(),
        decoded={"section": section, "ph_offset": ctrl_rec.offset},
    )

    from udf.parsers.hwp.equation import hwp_script_to_latex

    latex = hwp_script_to_latex(hwp_script) if hwp_script else None

    return EquationBlock(
        type="equation",
        id=blk_id,
        hwp_script=hwp_script,
        latex=latex,
        display=True,
        verbatim_ref=verb_id,
    ), verbatim_map


def _extract_equation_latex(
    ctrl_rec: HwpRecord,
    ctrl_children: list[HwpRecord],
) -> tuple[str | None, str | None]:
    """CTRL_HEADER("eqed")에서 (latex, hwp_script) 추출. 블록 생성 없이 경량 버전."""
    from udf.parsers.hwp.equation import hwp_script_to_latex

    hwp_script: str | None = None
    for rec in ctrl_children:
        if rec.tag_id == HWPTAG_EQEDIT:
            payload = rec.payload
            try:
                if len(payload) >= 6:
                    char_count = struct.unpack_from("<H", payload, 4)[0]
                    script_end = 6 + char_count * 2
                    if script_end <= len(payload):
                        hwp_script = payload[6:script_end].decode("utf-16-le")
                    else:
                        hwp_script = payload[6:].decode("utf-16-le").rstrip("\x00")
                else:
                    hwp_script = payload.decode("utf-16-le").rstrip("\x00")
            except (UnicodeDecodeError, struct.error):
                hwp_script = None
            break
    latex = hwp_script_to_latex(hwp_script) if hwp_script else None
    return latex, hwp_script


# body.py의 기존 _hwp_script_to_latex / _tokenize_hwp_eq는
# udf.parsers.hwp.equation 모듈로 이전됨.
# 하위 호환을 위한 re-export:
from udf.parsers.hwp.equation import hwp_script_to_latex as _hwp_script_to_latex  # noqa: F401, E402
from udf.parsers.hwp.equation import tokenize as _tokenize_hwp_eq  # noqa: F401, E402


# ---------------------------------------------------------------------------
# 필드형 컨트롤 파싱 (pgnp, atno, %hlk)
# ---------------------------------------------------------------------------

_FIELD_TYPE_MAP = {
    _CTRL_ID_PGNP: "page_number",
    _CTRL_ID_ATNO: "auto_number",
    _CTRL_ID_HLK: "hyperlink",
}

_ATNO_KIND_MAP = {
    0: "page", 1: "footnote", 2: "endnote", 3: "figure",
    4: "table", 5: "equation",
}


def _parse_field_ctrl(
    ctrl_rec: HwpRecord,
    ctrl_children: list[HwpRecord],
    info: DocInfoResult,
    block_counter: itertools.count[int],
    verb_counter: itertools.count[int],
    section: str = "",
    ctrl_id: str = "",
) -> tuple[FieldBlock, dict[str, VerbatimBlock]]:
    """pgnp/atno/%hlk CTRL → FieldBlock."""
    blk_id = make_block_id(next(block_counter))
    verb_id = make_verbatim_id(next(verb_counter))

    field_type = _FIELD_TYPE_MAP.get(ctrl_id, ctrl_id)
    value: str | None = None

    if ctrl_id == _CTRL_ID_ATNO and len(ctrl_rec.payload) >= 12:
        # Field common header: ctrl_id(4) + properties(4) + field-specific data
        # For atno, numbering kind is uint32 at offset 8
        num_kind = struct.unpack_from("<I", ctrl_rec.payload, 8)[0]
        value = _ATNO_KIND_MAP.get(num_kind, str(num_kind))
    elif ctrl_id == _CTRL_ID_HLK and len(ctrl_rec.payload) >= 11:
        try:
            # Field common header: ctrl_id(4) + properties(4) + etc_char(1) + strlen(2) + string
            pay = ctrl_rec.payload
            str_len = struct.unpack_from("<H", pay, 9)[0]
            if str_len > 0 and len(pay) >= 11 + str_len * 2:
                cmd_str = pay[11 : 11 + str_len * 2].decode("utf-16-le", errors="replace")
                url = cmd_str.split(";")[0]
                if url:
                    value = url.replace("\\:", ":").replace("\\#", "#").replace("\\?", "?")
        except Exception:
            pass

    verbatim_map = {
        verb_id: VerbatimBlock(
            raw_tag_id=ctrl_rec.tag_id,
            level=ctrl_rec.level,
            raw_bytes=base64.b64encode(ctrl_rec.payload).decode(),
            decoded={"section": section, "ctrl_id": ctrl_id},
        )
    }

    return FieldBlock(
        type="field",
        id=blk_id,
        field_type=field_type,
        value=value,
        verbatim_ref=verb_id,
    ), verbatim_map


# ---------------------------------------------------------------------------
# 블록 리스트 파싱 (재귀 가능)
# ---------------------------------------------------------------------------


def _parse_block_list(
    records: list[HwpRecord],
    base_level: int,
    info: DocInfoResult,
    block_counter: itertools.count[int],
    verb_counter: itertools.count[int],
    section: str = "",
) -> tuple[list[Any], dict[str, VerbatimBlock]]:
    """Walk a flat record list and group paragraphs into blocks."""
    blocks: list[Any] = []
    verbatim_map: dict[str, VerbatimBlock] = {}
    i = 0

    while i < len(records):
        rec = records[i]
        if rec.level != base_level:
            i += 1
            continue

        if rec.tag_id == HWPTAG_PARA_HEADER:
            children, next_i = _collect_children(records, i + 1, rec.level)
            ctrl_recs = [
                c
                for c in children
                if c.tag_id == HWPTAG_CTRL_HEADER and c.level == base_level + 1
            ]
            first_ctrl_id = (
                ctrl_id_from_payload(ctrl_recs[0].payload) if ctrl_recs else ""
            )

            # 주요 블록 (표/수식) 파싱
            handled_primary = False
            if ctrl_recs and first_ctrl_id == _CTRL_ID_TABLE:
                # 단락 텍스트가 있으면 테이블 앞에 ParagraphBlock으로 보존
                pt_child = next(
                    (c for c in children
                     if c.tag_id == HWPTAG_PARA_TEXT and c.level == base_level + 1),
                    None,
                )
                if pt_child is not None:
                    host_text = _extract_text(pt_child.payload)
                    if host_text.strip():
                        para, pv = _parse_paragraph(
                            rec, children, info, block_counter, verb_counter, section
                        )
                        blocks.append(para)
                        verbatim_map.update(pv)

                ctrl = ctrl_recs[0]
                ctrl_children, _ = _collect_children(
                    children, children.index(ctrl) + 1, ctrl.level
                )
                table, tv = _parse_table(
                    ctrl, ctrl_children, info, block_counter, verb_counter, section
                )
                if table.verbatim_ref and table.verbatim_ref in tv:
                    tbl_vb = tv[table.verbatim_ref]
                    decoded = dict(tbl_vb.decoded) if tbl_vb.decoded else {}
                    decoded["ph_offset"] = rec.offset
                    decoded["ph_level"] = rec.level
                    tbl_vb.decoded = decoded
                blocks.append(table)
                verbatim_map.update(tv)
                handled_primary = True
            elif ctrl_recs and first_ctrl_id == _CTRL_ID_EQED and len(ctrl_recs) == 1:
                ctrl = ctrl_recs[0]
                ctrl_children, _ = _collect_children(
                    children, children.index(ctrl) + 1, ctrl.level
                )
                eq_blk, ev = _parse_equation(
                    ctrl, ctrl_children, block_counter, verb_counter, section,
                )
                if eq_blk.verbatim_ref and eq_blk.verbatim_ref in ev:
                    eq_vb = ev[eq_blk.verbatim_ref]
                    decoded = dict(eq_vb.decoded) if eq_vb.decoded else {}
                    decoded["ph_offset"] = rec.offset
                    decoded["ph_level"] = rec.level
                    eq_vb.decoded = decoded
                blocks.append(eq_blk)
                verbatim_map.update(ev)
                handled_primary = True

            if not handled_primary:
                inline_objects = None
                if ctrl_recs:
                    inline_objects = []
                    for ctrl in ctrl_recs:
                        cid = ctrl_id_from_payload(ctrl.payload)
                        if cid == _CTRL_ID_EQED:
                            cc, _ = _collect_children(
                                children, children.index(ctrl) + 1, ctrl.level
                            )
                            latex, hwp_script = _extract_equation_latex(ctrl, cc)
                            inline_objects.append({
                                "type": "eqed",
                                "latex": latex,
                                "hwp_script": hwp_script,
                            })
                        else:
                            inline_objects.append({"type": "other"})
                para, pv = _parse_paragraph(
                    rec, children, info, block_counter, verb_counter, section,
                    inline_objects=inline_objects,
                )
                blocks.append(para)
                verbatim_map.update(pv)

            # 단락 내 모든 CTRL_HEADER 순회: gso/eqed/fn/en/tbl 추출
            for ctrl in ctrl_recs:
                cid = ctrl_id_from_payload(ctrl.payload)
                if cid in _CTRL_IDS_SKIP:
                    continue
                if cid == _CTRL_ID_TABLE and handled_primary:
                    continue
                cc, _ = _collect_children(
                    children, children.index(ctrl) + 1, ctrl.level
                )
                if cid == _CTRL_ID_TABLE:
                    table, tv = _parse_table(
                        ctrl, cc, info, block_counter, verb_counter, section
                    )
                    if table.verbatim_ref and table.verbatim_ref in tv:
                        tbl_vb = tv[table.verbatim_ref]
                        decoded = dict(tbl_vb.decoded) if tbl_vb.decoded else {}
                        decoded["ph_offset"] = rec.offset
                        decoded["ph_level"] = rec.level
                        tbl_vb.decoded = decoded
                    blocks.append(table)
                    verbatim_map.update(tv)
                elif cid == _CTRL_ID_GSO:
                    gso_blk, gv = _parse_gso(
                        ctrl, cc, info,
                        block_counter, verb_counter, section,
                    )
                    blocks.append(gso_blk)
                    verbatim_map.update(gv)
                elif cid == _CTRL_ID_EQED and not handled_primary:
                    pass
                elif cid in (_CTRL_ID_FOOTNOTE, _CTRL_ID_ENDNOTE):
                    fn_blk, fv = _parse_footnote_endnote(
                        ctrl, cc, info, block_counter, verb_counter, section,
                        is_endnote=(cid == _CTRL_ID_ENDNOTE),
                    )
                    blocks.append(fn_blk)
                    verbatim_map.update(fv)
                elif cid in (_CTRL_ID_HEADER, _CTRL_ID_FOOTER):
                    hf_blk, hfv = _parse_header_footer(
                        ctrl, cc, info, block_counter, verb_counter, section,
                        is_footer=(cid == _CTRL_ID_FOOTER),
                    )
                    blocks.append(hf_blk)
                    verbatim_map.update(hfv)
                elif cid in (_CTRL_ID_PGNP, _CTRL_ID_ATNO, _CTRL_ID_HLK):
                    f_blk, fv = _parse_field_ctrl(
                        ctrl, cc, info, block_counter, verb_counter, section, cid,
                    )
                    blocks.append(f_blk)
                    verbatim_map.update(fv)

            i = next_i

        elif rec.tag_id == HWPTAG_CTRL_HEADER:
            ctrl_id = ctrl_id_from_payload(rec.payload)
            children, next_i = _collect_children(records, i + 1, rec.level)
            if ctrl_id == _CTRL_ID_TABLE:
                table, tv = _parse_table(
                    rec, children, info, block_counter, verb_counter, section
                )
                blocks.append(table)
                verbatim_map.update(tv)
            elif ctrl_id in (_CTRL_ID_FOOTNOTE, _CTRL_ID_ENDNOTE):
                fn_blk, fv = _parse_footnote_endnote(
                    rec, children, info, block_counter, verb_counter, section,
                    is_endnote=(ctrl_id == _CTRL_ID_ENDNOTE),
                )
                blocks.append(fn_blk)
                verbatim_map.update(fv)
            elif ctrl_id == _CTRL_ID_EQED:
                eq_blk, ev = _parse_equation(
                    rec, children, block_counter, verb_counter, section,
                )
                blocks.append(eq_blk)
                verbatim_map.update(ev)
            elif ctrl_id == _CTRL_ID_GSO:
                gso_blk, gv = _parse_gso(
                    rec, children, info, block_counter, verb_counter, section,
                )
                blocks.append(gso_blk)
                verbatim_map.update(gv)
            elif ctrl_id in (_CTRL_ID_HEADER, _CTRL_ID_FOOTER):
                hf_blk, hfv = _parse_header_footer(
                    rec, children, info, block_counter, verb_counter, section,
                    is_footer=(ctrl_id == _CTRL_ID_FOOTER),
                )
                blocks.append(hf_blk)
                verbatim_map.update(hfv)
            elif ctrl_id in (_CTRL_ID_PGNP, _CTRL_ID_ATNO, _CTRL_ID_HLK):
                f_blk, fv = _parse_field_ctrl(
                    rec, children, info, block_counter, verb_counter, section, ctrl_id,
                )
                blocks.append(f_blk)
                verbatim_map.update(fv)
            elif ctrl_id in _CTRL_IDS_SKIP:
                pass
            else:
                # 미지원 ctrl: UnknownBlock으로 보존
                unk_id = make_block_id(next(block_counter))
                unk_verb_id = make_verbatim_id(next(verb_counter))
                verbatim_map[unk_verb_id] = VerbatimBlock(
                    raw_tag_id=rec.tag_id,
                    level=rec.level,
                    raw_bytes=base64.b64encode(rec.payload).decode(),
                    decoded={"section": section},
                )
                blocks.append(
                    UnknownBlock(
                        type="unknown",
                        id=unk_id,
                        raw_bytes=base64.b64encode(rec.payload).decode(),
                        description=f"ctrl_id={ctrl_id!r}",
                        verbatim_ref=unk_verb_id,
                    )
                )
            i = next_i

        else:
            i += 1

    return blocks, verbatim_map


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def parse_section(
    stream_bytes: bytes,
    info: DocInfoResult,
    section: str = "",
) -> tuple[list[Any], dict[str, VerbatimBlock]]:
    """Parse a BodyText section stream into document blocks.

    Parameters
    ----------
    stream_bytes : bytes
        Raw (decompressed) bytes of a BodyText/SectionN stream.
    info : DocInfoResult
        Parsed DocInfo containing char shapes, para shapes, etc.
    section : str, optional
        Section identifier used for block ID generation.

    Returns
    -------
    tuple[list[Any], dict[str, VerbatimBlock]]
        A list of semantic blocks and a map of verbatim preservation data.
    """
    records = list(iter_records(stream_bytes))
    block_counter: itertools.count[int] = itertools.count()
    verb_counter: itertools.count[int] = itertools.count()
    return _parse_block_list(records, 0, info, block_counter, verb_counter, section)


def extract_page_def(stream_bytes: bytes) -> dict[str, Any] | None:
    """Extract page dimensions from the PAGE_DEF record in a section stream.

    Scans the stream for HWPTAG_PAGE_DEF (tag 73) and converts HWPUNIT
    values to points.

    Parameters
    ----------
    stream_bytes : bytes
        Raw (decompressed) BodyText section stream.

    Returns
    -------
    dict[str, Any] | None
        Page dimensions (width, height, margins, orientation) in points,
        or ``None`` if no PAGE_DEF record is found.

    Notes
    -----
    PageDef binary layout::

        0-3:   page_width (uint32, HWPUNIT)
        4-7:   page_height
        8-11:  margin_left
        12-15: margin_right
        16-19: margin_top
        20-23: margin_bottom
        24-27: header_offset
        28-31: footer_offset
        32-35: bookbinding_offset
        36-39: attr (bit 0: orientation 0=portrait 1=landscape)
    """
    for rec in iter_records(stream_bytes):
        if rec.tag_id == HWPTAG_PAGE_DEF and len(rec.payload) >= 24:
            pay = rec.payload
            pw = struct.unpack_from("<I", pay, 0)[0]
            ph = struct.unpack_from("<I", pay, 4)[0]
            ml = struct.unpack_from("<I", pay, 8)[0]
            mr = struct.unpack_from("<I", pay, 12)[0]
            mt = struct.unpack_from("<I", pay, 16)[0]
            mb = struct.unpack_from("<I", pay, 20)[0]
            result: dict[str, Any] = {
                "page_width": hwpunit_to_pt(pw),
                "page_height": hwpunit_to_pt(ph),
                "margin_left": hwpunit_to_pt(ml),
                "margin_right": hwpunit_to_pt(mr),
                "margin_top": hwpunit_to_pt(mt),
                "margin_bottom": hwpunit_to_pt(mb),
            }
            if len(pay) >= 28:
                header_off = struct.unpack_from("<I", pay, 24)[0]
                result["header_offset"] = hwpunit_to_pt(header_off)
            if len(pay) >= 32:
                footer_off = struct.unpack_from("<I", pay, 28)[0]
                result["footer_offset"] = hwpunit_to_pt(footer_off)
            if len(pay) >= 40:
                attr = struct.unpack_from("<I", pay, 36)[0]
                result["orientation"] = "landscape" if (attr & 0x1) else "portrait"
            return result
    return None


def extract_columns_def(stream_bytes: bytes) -> dict[str, Any] | None:
    """Extract the first multi-column (cold) definition from a section stream.

    Parameters
    ----------
    stream_bytes : bytes
        Raw (decompressed) BodyText section stream.

    Returns
    -------
    dict[str, Any] | None
        Column layout info (count, same_width, gap) or ``None`` if not found.
    """
    for rec in iter_records(stream_bytes):
        if rec.tag_id == HWPTAG_CTRL_HEADER and len(rec.payload) >= 8:
            cid = ctrl_id_from_payload(rec.payload)
            if cid == "cold":
                flags = struct.unpack_from("<H", rec.payload, 4)[0]
                count = (flags >> 2) & 0xFF
                if count <= 1:
                    continue
                same_widths = bool(flags & (1 << 12))
                spacing = struct.unpack_from("<H", rec.payload, 6)[0]
                return {
                    "count": count,
                    "same_width": same_widths,
                    "gap": hwpunit_to_pt(spacing) if spacing else None,
                }
    return None
