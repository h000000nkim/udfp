"""DocInfo stream parser -- builds GlobalResources from HWP binary records."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any

from udf.schema import BlockFormat
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
from udf.parsers.hwp.records import (
    HWPTAG_BIN_DATA,
    HWPTAG_BORDER_FILL,
    HWPTAG_BULLET,
    HWPTAG_CHAR_SHAPE,
    HWPTAG_COMPATIBLE_DOCUMENT,
    HWPTAG_DOCUMENT_PROPERTIES,
    HWPTAG_FACE_NAME,
    HWPTAG_ID_MAPPINGS,
    HWPTAG_NUMBERING,
    HWPTAG_PARA_SHAPE,
    HWPTAG_STYLE,
    HWPTAG_TAB_DEF,
    iter_records,
)

_ALIGN_MAP = {
    0: "justify",
    1: "left",
    2: "right",
    3: "center",
    4: "distribute",
    5: "divide",
}
_UNDERLINE_TYPE_MAP = {0: None, 1: "solid", 2: "dot", 3: "dash", 4: "wave", 5: "double"}
_LINE_SPACING_TYPE_MAP = {
    0: "ratio",
    1: "fixed",
    2: "leading_only",
    3: "minimum",
}

# HWPUNIT → pt 변환: 1pt = 100 HWPUNIT
_HWPUNIT_PER_PT = 100
# HWPUNIT → mm 변환: 1mm ≈ 283.46 HWPUNIT
_HWPUNIT_PER_MM = 283.46


@dataclass
class DocInfoResult:
    """Aggregated result of DocInfo stream parsing.

    Provides indexed lookup tables (char_shapes, para_shapes, face_names,
    etc.) consumed by the BodyText section parser.
    """

    global_resources: GlobalResources
    char_shapes: list[dict[str, Any]] = field(default_factory=list)
    para_shapes: list[dict[str, Any]] = field(default_factory=list)
    face_names: list[str | None] = field(default_factory=list)
    style_names: list[str] = field(default_factory=list)  # style_id → name
    bindata_items: list[dict[str, Any]] = field(default_factory=list)  # 0-based index → {id, ext, stream}
    doc_properties: dict[str, Any] = field(default_factory=dict)
    compat_doc: dict[str, Any] = field(default_factory=dict)


def _parse_face_name(payload: bytes) -> str | None:
    """Extract the primary font name from a FaceName record."""
    result = _parse_face_name_detail(payload)
    return result.get("name")


def _parse_face_name_detail(payload: bytes) -> dict[str, Any]:
    """Parse a FaceName record into a detail dict with font name and fallbacks."""
    result: dict[str, Any] = {}
    if not payload:
        return result

    flags = payload[0]
    off = 1

    # font name (BSTR)
    if flags & 0x01:
        if off + 2 > len(payload):
            return result
        (name_len,) = struct.unpack_from("<H", payload, off)
        off += 2
        end = off + name_len * 2
        if end > len(payload):
            return result
        result["name"] = payload[off:end].decode("utf-16-le", errors="replace")
        off = end

    # substitute font info
    if flags & 0x02:
        if off + 1 <= len(payload):
            sub_type = payload[off]
            off += 1
            result["substitute_type"] = sub_type
            if off + 2 <= len(payload):
                (sub_name_len,) = struct.unpack_from("<H", payload, off)
                off += 2
                sub_end = off + sub_name_len * 2
                if sub_end <= len(payload):
                    result["substitute_name"] = payload[off:sub_end].decode(
                        "utf-16-le", errors="replace"
                    )
                    off = sub_end

    # typeinfo (10 bytes: panose)
    if flags & 0x04:
        if off + 10 <= len(payload):
            result["panose"] = payload[off : off + 10]

    return result


def _parse_char_shape(payload: bytes) -> dict[str, Any]:
    """CharShape 74바이트 구조 → dict.

    바이너리 레이아웃 (docinfo_builder.py / rhwp 기준):
      0-13   face_id[7]: uint16[7]
      14-20  ratio[7]: uint8[7]       (장평 50-200, 기본 100)
      21-27  char_spacing[7]: int8[7] (자간 -50~50)
      28-34  rel_size[7]: uint8[7]    (상대 크기, 기본 100)
      35-41  char_offset[7]: int8[7]  (상하 오프셋)
      42-45  base_size: int32         (HWPUNIT, 1pt = 100)
      46-49  attr: uint32
               bit0=italic, bit1=bold
               bits2-3=underline_type (0=none,1=bottom,3=top)
               bits4-7=underline_shape
               bits8-10=outline_type
               bits11-12=shadow_type
               bits18-20=strikethrough (≥2=active)
      50-51  shadow_offset_x/y: int8[2]
      52-55  text_color: uint32 (0x00BBGGRR)
      56-59  underline_color: uint32
      60-63  shade_color: uint32
      64-67  shadow_color: uint32
      68-69  border_fill_id: uint16
      70-73  strike_color: uint32
    """
    if len(payload) < 42:
        return {}

    _LANG_KEYS = ("hangul", "latin", "hanja", "japanese", "other", "symbol", "user")

    face_ids: tuple[int, ...] = struct.unpack_from("<7H", payload, 0)

    ratios = struct.unpack_from("<7B", payload, 14) if len(payload) >= 21 else (100,) * 7
    spacings = struct.unpack_from("<7b", payload, 21) if len(payload) >= 28 else (0,) * 7
    rel_sizes = struct.unpack_from("<7B", payload, 28) if len(payload) >= 35 else (100,) * 7
    offsets = struct.unpack_from("<7b", payload, 35) if len(payload) >= 42 else (0,) * 7

    ratio_hangul = ratios[0]
    spacing_hangul = spacings[0]
    offset_hangul = offsets[0]

    (base_size,) = struct.unpack_from("<i", payload, 42)

    attr = 0
    if len(payload) >= 50:
        (attr,) = struct.unpack_from("<I", payload, 46)

    italic = bool(attr & 0x01)
    bold = bool(attr & 0x02)
    underline_val = (attr >> 2) & 0x03
    outline_type = (attr >> 8) & 0x07
    shadow_type = (attr >> 11) & 0x03
    emboss = bool(attr & (1 << 13))
    engrave = bool(attr & (1 << 14))
    strikethrough_val = (attr >> 18) & 0x07

    color_hex: str | None = None
    if len(payload) >= 56:
        (color_raw,) = struct.unpack_from("<I", payload, 52)
        if color_raw & 0x00FFFFFF:
            r = color_raw & 0xFF
            g = (color_raw >> 8) & 0xFF
            b = (color_raw >> 16) & 0xFF
            color_hex = f"#{r:02x}{g:02x}{b:02x}"

    underline_color_hex: str | None = None
    if len(payload) >= 60:
        (underline_color_raw,) = struct.unpack_from("<I", payload, 56)
        if underline_color_raw & 0x00FFFFFF:
            ul_r = underline_color_raw & 0xFF
            ul_g = (underline_color_raw >> 8) & 0xFF
            ul_b = (underline_color_raw >> 16) & 0xFF
            underline_color_hex = f"#{ul_r:02x}{ul_g:02x}{ul_b:02x}"

    shade_color_hex: str | None = None
    if len(payload) >= 64:
        (shade_raw,) = struct.unpack_from("<I", payload, 60)
        if shade_raw and shade_raw != 0xFFFFFFFF:
            sr = shade_raw & 0xFF
            sg = (shade_raw >> 8) & 0xFF
            sb = (shade_raw >> 16) & 0xFF
            shade_color_hex = f"#{sr:02x}{sg:02x}{sb:02x}"

    font_size_pt = base_size / _HWPUNIT_PER_PT

    # Shadow offsets (offset 50-51)
    shadow_x: int | None = None
    shadow_y: int | None = None
    if len(payload) >= 52:
        shadow_x, shadow_y = struct.unpack_from("<2b", payload, 50)

    # Border fill ID (offset 68-69)
    cs_border_fill_id: int | None = None
    if len(payload) >= 70:
        (cs_border_fill_id,) = struct.unpack_from("<H", payload, 68)

    # Strike color (offset 70-73)
    strike_color_hex: str | None = None
    if len(payload) >= 74:
        (strike_raw,) = struct.unpack_from("<I", payload, 70)
        if strike_raw and strike_raw != 0xFFFFFFFF:
            stk_r = strike_raw & 0xFF
            stk_g = (strike_raw >> 8) & 0xFF
            stk_b = (strike_raw >> 16) & 0xFF
            strike_color_hex = f"#{stk_r:02x}{stk_g:02x}{stk_b:02x}"

    # Superscript/subscript: attr bit 15/16 OR synthesized from rel_size + char_offset
    hangul_rel_size = rel_sizes[0]
    superscript = bool(attr & (1 << 15)) or (hangul_rel_size < 100 and offset_hangul > 0)
    subscript = bool(attr & (1 << 16)) or (hangul_rel_size < 100 and offset_hangul < 0)

    result: dict[str, Any] = {
        "hangul_face_id": face_ids[0],
        "latin_face_id": face_ids[1],
        "bold": bold or None,
        "italic": italic or None,
        "underline": underline_val > 0 or None,
        "underline_type": _UNDERLINE_TYPE_MAP.get(underline_val),
        "underline_color": underline_color_hex,
        "outline": outline_type > 0 or None,
        "shadow": shadow_type > 0 or None,
        "emboss": emboss or None,
        "engrave": engrave or None,
        "superscript": superscript or None,
        "subscript": subscript or None,
        "strikethrough": strikethrough_val >= 2 or None,
        "strikeout_color": strike_color_hex,
        "font_size_pt": font_size_pt,
        "color": color_hex,
        "shade_color": shade_color_hex,
        "char_scale": ratio_hangul if ratio_hangul != 100 else None,
        "letter_spacing": f"{spacing_hangul}%" if spacing_hangul else None,
        "char_offset": f"{offset_hangul}%" if offset_hangul else None,
    }

    # All 7 language face_ids
    for i, key in enumerate(_LANG_KEYS):
        result[f"{key}_face_id"] = face_ids[i]
        if ratios[i] != 100:
            result[f"{key}_char_scale"] = ratios[i]
        if spacings[i]:
            result[f"{key}_letter_spacing"] = spacings[i]
        if rel_sizes[i] != 100:
            result[f"{key}_rel_size"] = rel_sizes[i]
        if offsets[i]:
            result[f"{key}_char_offset"] = offsets[i]

    if shadow_x:
        result["shadow_offset_x"] = shadow_x
    if shadow_y:
        result["shadow_offset_y"] = shadow_y
    if cs_border_fill_id:
        result["border_fill_id"] = cs_border_fill_id

    return result


def _parse_para_shape(payload: bytes) -> dict[str, Any]:
    """ParaShape attr + margins/spacing 추출.

    바이너리 레이아웃 (54-88바이트, 버전에 따라 다름):
      0-3    attr1: uint32
               bits 0-1: line_spacing_type (0=ratio, 1=fixed, 2=leading_only, 3=minimum)
               bits 2-4: alignment (0=justify, 1=left, 2=right, 3=center, 4=distribute, 5=divide)
               bit 5: protect (과부/고아 제어)
               bit 6: start_new_page (강제 페이지 나눔)
               bit 7: break_non_latin_word (0=BREAK_WORD, 1=KEEP_WORD)
               bit 8: break_latin_word (0=BREAK_WORD, 1=KEEP_WORD)
      4-27   margins/spacing: uint32[6] (left, right, top, bot, first, line_spacing)
      28-29  tab_def_id: uint16
      30-31  numbering_bullet_id: uint16
      32-33  border_fill_id: uint16
      34-35  level: int16 (개요 레벨)
    """
    if len(payload) < 4:
        return {}
    (attr,) = struct.unpack_from("<I", payload, 0)
    align_val = (attr >> 2) & 0x7
    ls_type_val = attr & 0x3

    result: dict[str, Any] = {
        "alignment": _ALIGN_MAP.get(align_val, "justify"),
        "line_spacing_type": _LINE_SPACING_TYPE_MAP.get(ls_type_val, "ratio"),
        "protect": bool(attr & (1 << 5)) or None,
        "start_new_page": bool(attr & (1 << 6)) or None,
    }

    if len(payload) >= 28:
        left_m, right_m, indent, top_sp, bot_sp, line_sp = struct.unpack_from(
            "<iiiIII", payload, 4
        )
        result.update(
            {
                "indent_left_hwp": left_m,
                "indent_right_hwp": right_m,
                "indent_first_hwp": indent,
                "space_before_hwp": top_sp,
                "space_after_hwp": bot_sp,
                "line_spacing_hwp": line_sp,
            }
        )

    if len(payload) >= 30:
        (tab_def_id,) = struct.unpack_from("<H", payload, 28)
        result["tab_def_id"] = tab_def_id

    if len(payload) >= 32:
        (numbering_bullet_id,) = struct.unpack_from("<H", payload, 30)
        result["numbering_bullet_id"] = numbering_bullet_id

    if len(payload) >= 34:
        (border_fill_id,) = struct.unpack_from("<H", payload, 32)
        result["border_fill_id"] = border_fill_id

    if len(payload) >= 36:
        (level,) = struct.unpack_from("<h", payload, 34)
        result["level"] = level

    return result


def _parse_style(payload: bytes) -> dict[str, Any]:
    """Style 레코드에서 이름, 타입, para/char shape ID 추출."""
    result: dict[str, Any] = {}
    off = 0
    # 이름 (BSTR: uint16 char count + UTF-16LE)
    if off + 2 > len(payload):
        return result
    (name_len,) = struct.unpack_from("<H", payload, off)
    off += 2
    if name_len > 0 and off + name_len * 2 <= len(payload):
        result["name"] = payload[off : off + name_len * 2].decode(
            "utf-16-le", errors="replace"
        )
        off += name_len * 2
    else:
        off += name_len * 2
    # 영문 이름 (BSTR)
    if off + 2 > len(payload):
        return result
    (ename_len,) = struct.unpack_from("<H", payload, off)
    off += 2 + ename_len * 2
    # type(1) + next_style_id(1) + lang_id(2) + locking_mask(2)
    if off + 6 > len(payload):
        return result
    style_type = payload[off]
    result["style_type"] = "paragraph" if style_type == 0 else "character"
    off += 6
    # para_shape_id(2) + char_shape_id(2)
    if off + 4 <= len(payload):
        ps_id, cs_id = struct.unpack_from("<HH", payload, off)
        result["para_shape_id"] = ps_id
        result["char_shape_id"] = cs_id
    return result


def _build_block_format(
    ps: dict[str, Any],
    char_shapes: list[dict[str, Any]],
    cs_id: int | None,
) -> BlockFormat:
    """ParaShape + CharShape → BlockFormat (Style 링킹용)."""
    _VALID_ALIGNS = ("left", "center", "right", "justify")
    _VALID_LS_TYPES = ("follow_char", "fixed", "leading_only", "minimum", "ratio")

    align = ps.get("alignment")
    ls_type = ps.get("line_spacing_type")
    ls_val = ps.get("line_spacing_hwp", 0)

    def _to_pt(v: int) -> float | None:
        if not v or v >= 0xFFFFFFF0:
            return None
        return hwpunit_to_pt(v)

    line_spacing: Ratio | float | None = None
    if ls_val and ls_val < 0xFFFFFFF0:
        if ls_type in (None, "ratio"):
            line_spacing = Ratio(ls_val)
        else:
            line_spacing = _to_pt(ls_val)

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
            fmt.font_size = float(font_size)

    return fmt


_NUMBERING_FORMAT_MAP: dict[int, str] = {
    0: "decimal",
    1: "circle_decimal",
    2: "roman_upper",
    3: "roman_lower",
    4: "alpha_upper",
    5: "alpha_lower",
    6: "hangul_syllable",
    7: "hangul_jamo",
    8: "hangul_phonetic",
    9: "ideograph",
    10: "circle_hangul_syllable",
    11: "circle_hangul_jamo",
    12: "circle_hangul_phonetic",
}


def _parse_numbering(payload: bytes) -> dict[str, Any]:
    """번호 매기기 레코드에서 7레벨 정보 추출.

    HWP Numbering 레벨별 구조:
      0-1:  flags (uint16)
      2-5:  reserved (uint32)
      6-7:  num_format (uint16, 번호 형식 타입)
      8-11: reserved (uint32, 0xFFFFFFFF)
      12-13: str_len (uint16, 형식 문자열 길이)
      14+:  format_str (utf-16-le, str_len * 2 bytes)
    """
    levels: list[dict[str, Any]] = []
    off = 0
    for level_idx in range(7):
        if off + 14 > len(payload):
            break
        num_format = struct.unpack_from("<H", payload, off + 6)[0]
        (str_len,) = struct.unpack_from("<H", payload, off + 12)
        off += 14
        fmt_str = ""
        if str_len > 0 and off + str_len * 2 <= len(payload):
            fmt_str = payload[off : off + str_len * 2].decode(
                "utf-16-le", errors="replace"
            )
        off += str_len * 2

        levels.append({
            "level": level_idx,
            "format": _NUMBERING_FORMAT_MAP.get(num_format, f"unknown_{num_format}"),
            "pattern": fmt_str if fmt_str else None,
        })

    # 7레벨 뒤 start values: uint32 × 7
    start_values: list[int] = []
    for _ in range(7):
        if off + 4 <= len(payload):
            start_values.append(struct.unpack_from("<I", payload, off)[0])
            off += 4

    return {"levels": levels, "start_values": start_values}


_TAB_KIND_MAP = {0: "left", 1: "right", 2: "center", 3: "decimal"}


def _parse_tab_def(payload: bytes) -> list[TabStop]:
    """TabDef → list of TabStop.

    Layout:
      0-3: flags (uint32, bit0=autotab_left, bit1=autotab_right)
      4-7: count (uint32)
      8+:  Tab entries, each 8 bytes (pos: uint32 HWPUNIT, flags: uint32)
    """
    stops: list[TabStop] = []
    if len(payload) < 8:
        return stops
    (count,) = struct.unpack_from("<I", payload, 4)
    off = 8
    for _ in range(min(count, 50)):
        if off + 8 > len(payload):
            break
        pos, tab_flags = struct.unpack_from("<II", payload, off)
        off += 8
        kind_val = tab_flags & 0xFF
        align = _TAB_KIND_MAP.get(kind_val, "left")
        pos_mm = pos / _HWPUNIT_PER_MM
        stops.append(TabStop(position=f"{pos_mm:.1f}mm", align=align))
    return stops


def _parse_border_fill(payload: bytes) -> dict[str, Any]:
    """BorderFill 레코드 상세 파싱.

    HWP BorderFill 구조:
      0-1: attr (uint16)
      2-5: left border (type:uint8, width:uint8, color:uint32 중 2바이트)
    간이 파싱: 4면 테두리 색상 + 배경색 추출.

    실제 구조는 복잡하나 핵심 필드만 추출:
      offset 2: border_type_left (1B)
      offset 3: border_width_left (1B)
      offset 4-7: border_color_left (4B, 0x00BBGGRR)
      이후 top/right/bottom 각 6B씩
      배경색은 뒤쪽에 위치 (오프셋은 버전에 따라 다름)
    """
    result: dict[str, Any] = {}
    if len(payload) < 2:
        return result

    # 4면 테두리 (각 6바이트: type 1B + width 1B + color 4B)
    border_names = ["left", "right", "top", "bottom"]
    off = 2  # attr 이후
    for name in border_names:
        if off + 6 > len(payload):
            break
        btype = payload[off]
        bwidth = payload[off + 1]
        (bcolor_raw,) = struct.unpack_from("<I", payload, off + 2)
        off += 6
        if btype and btype > 0:
            b_r = bcolor_raw & 0xFF
            b_g = (bcolor_raw >> 8) & 0xFF
            b_b = (bcolor_raw >> 16) & 0xFF
            result[f"border_{name}_color"] = f"#{b_r:02x}{b_g:02x}{b_b:02x}"
            _BORDER_STYLE_MAP = {0: "none", 1: "solid", 2: "dash", 3: "dot", 4: "dash_dot"}
            result[f"border_{name}_style"] = _BORDER_STYLE_MAP.get(btype, f"type_{btype}")
            _BORDER_WIDTH_MM = {0: 0.1, 1: 0.12, 2: 0.15, 3: 0.2, 4: 0.25, 5: 0.3, 6: 0.4, 7: 0.5}
            result[f"border_{name}_width"] = _BORDER_WIDTH_MM.get(bwidth, 0.1)

    # 대각선 (6B) — 스킵
    off += 6

    # 배경 타입 (4B attr)
    if off + 4 <= len(payload):
        (fill_attr,) = struct.unpack_from("<I", payload, off)
        off += 4
        # 단색 채우기인 경우 (bit 0)
        if fill_attr & 0x01:
            if off + 4 <= len(payload):
                (fg_color,) = struct.unpack_from("<I", payload, off)
                fg_rgb = fg_color & 0x00FFFFFF
                if fg_rgb != 0x00FFFFFF:
                    fc_r = fg_rgb & 0xFF
                    fc_g = (fg_rgb >> 8) & 0xFF
                    fc_b = (fg_rgb >> 16) & 0xFF
                    result["fill_color"] = f"#{fc_r:02x}{fc_g:02x}{fc_b:02x}"

    return result


def _parse_bin_data(payload: bytes) -> dict[str, Any]:
    """BIN_DATA 레코드 파싱. flags + binDataId + extension 추출.

    Embedded type (flags & 0x0F == 1):
      offset 0: flags (uint16)
      offset 2: binDataId (uint16) — OLE 스트림 이름에 사용 (BIN{id:04X}.ext)
      offset 4: ext BSTR (uint16 len + UTF-16LE)
    """
    result: dict[str, Any] = {}
    if len(payload) < 2:
        return result
    (flags,) = struct.unpack_from("<H", payload, 0)
    btype = flags & 0x0F
    result["flags"] = flags
    result["type"] = btype
    if btype == 1 and len(payload) >= 6:
        (bin_id,) = struct.unpack_from("<H", payload, 2)
        result["id"] = bin_id
        (ext_len,) = struct.unpack_from("<H", payload, 4)
        if ext_len > 0 and 6 + ext_len * 2 <= len(payload):
            ext = payload[6 : 6 + ext_len * 2].decode("utf-16-le", errors="replace")
            result["ext"] = ext
            result["stream"] = f"BIN{bin_id:04X}.{ext}"
    return result


def _parse_document_properties(payload: bytes) -> dict[str, Any]:
    """DOCUMENT_PROPERTIES (tag=16) 파싱.

    Layout:
      0-1:  section_count (uint16)
      2-3:  start_page (uint16)
      4-5:  start_footnote (uint16)
      6-7:  start_endnote (uint16)
      8-9:  start_picture (uint16)
      10-11: start_table (uint16)
      12-13: start_equation (uint16)
    """
    result: dict[str, Any] = {}
    if len(payload) < 2:
        return result
    result["section_count"] = struct.unpack_from("<H", payload, 0)[0]
    if len(payload) >= 4:
        result["start_page"] = struct.unpack_from("<H", payload, 2)[0]
    if len(payload) >= 6:
        result["start_footnote"] = struct.unpack_from("<H", payload, 4)[0]
    if len(payload) >= 8:
        result["start_endnote"] = struct.unpack_from("<H", payload, 6)[0]
    if len(payload) >= 10:
        result["start_picture"] = struct.unpack_from("<H", payload, 8)[0]
    if len(payload) >= 12:
        result["start_table"] = struct.unpack_from("<H", payload, 10)[0]
    if len(payload) >= 14:
        result["start_equation"] = struct.unpack_from("<H", payload, 12)[0]
    return result


def _parse_compatible_document(payload: bytes) -> dict[str, Any]:
    """COMPATIBLE_DOCUMENT (tag=31) 파싱.

    Layout:
      0-3: target_document (uint32) — 호환 대상 (0=default, 1=hwp2007, 2=ms_word)
    """
    result: dict[str, Any] = {}
    if len(payload) >= 4:
        target = struct.unpack_from("<I", payload, 0)[0]
        result["target_document"] = {0: "default", 1: "hwp2007", 2: "ms_word"}.get(
            target, str(target)
        )
    return result


def _parse_id_mappings(payload: bytes) -> list[int]:
    """ID_MAPPINGS 레코드에서 카테고리별 항목 수를 추출한다.

    HWP ID_MAPPINGS: uint16 × N (카테고리 순서)
      [0] 바이너리 데이터
      [1] 한글 FaceName
      [2] 영문 FaceName
      [3] 한자 FaceName
      [4] 일본어 FaceName
      [5] 기타 FaceName
      [6] 기호 FaceName
      [7] 사용자 FaceName
      [8] BorderFill
      [9] CharShape
      [10] TabDef
      [11] Numbering
      [12] Bullet
      [13] ParaShape
      [14] Style
      ... (추가 카테고리)
    """
    counts: list[int] = []
    for off in range(0, len(payload) - 1, 2):
        (cnt,) = struct.unpack_from("<H", payload, off)
        counts.append(cnt)
    return counts


_FACE_CATEGORY_NAMES = [
    "hangul", "latin", "hanja", "japanese", "other", "symbol", "user_defined"
]


def parse_doc_info(stream_bytes: bytes) -> DocInfoResult:
    """Parse the DocInfo stream into indexed lookup tables.

    Iterates over HWP binary records to extract character shapes, paragraph
    shapes, font faces, styles, numbering definitions, and other global
    resources.

    Parameters
    ----------
    stream_bytes : bytes
        Raw (decompressed) DocInfo stream content.

    Returns
    -------
    DocInfoResult
        Parsed global resources and indexed shape/font tables.
    """
    char_shapes: list[dict[str, Any]] = []
    para_shapes: list[dict[str, Any]] = []
    face_names: list[str | None] = []
    face_name_details: list[dict[str, Any]] = []
    styles: dict[str, StyleDef] = {}
    style_name_list: list[str] = []
    numberings: dict[str, NumberingDef] = {}
    bullets: dict[str, BulletDef] = {}
    border_fills: dict[str, BorderFillDef] = {}
    tab_defs: dict[str, TabDef] = {}
    face_name_objs: dict[str, FontFallbacks] = {}
    id_mapping_counts: list[int] = []
    bindata_items: list[dict[str, Any]] = []
    doc_properties: dict[str, Any] = {}
    compat_doc: dict[str, Any] = {}

    for rec in iter_records(stream_bytes):
        if rec.tag_id == HWPTAG_DOCUMENT_PROPERTIES:
            doc_properties = _parse_document_properties(rec.payload)

        elif rec.tag_id == HWPTAG_COMPATIBLE_DOCUMENT:
            compat_doc = _parse_compatible_document(rec.payload)

        elif rec.tag_id == HWPTAG_ID_MAPPINGS:
            id_mapping_counts = _parse_id_mappings(rec.payload)

        elif rec.tag_id == HWPTAG_BIN_DATA:
            bindata_items.append(_parse_bin_data(rec.payload))

        elif rec.tag_id == HWPTAG_FACE_NAME:
            detail = _parse_face_name_detail(rec.payload)
            name = detail.get("name")
            face_names.append(name)
            face_name_details.append(detail)
            idx = str(len(face_names) - 1)
            ff = FontFallbacks()
            if name:
                ff.hangul = name
                ff.latin = name
            face_name_objs[idx] = ff

        elif rec.tag_id == HWPTAG_CHAR_SHAPE:
            char_shapes.append(_parse_char_shape(rec.payload))

        elif rec.tag_id == HWPTAG_PARA_SHAPE:
            para_shapes.append(_parse_para_shape(rec.payload))

        elif rec.tag_id == HWPTAG_STYLE:
            raw = _parse_style(rec.payload)
            idx = str(len(styles))
            style_name = raw.get("name", f"style_{idx}")
            sdef = StyleDef(
                id=idx,
                name=style_name,
                style_type=raw.get("style_type"),
            )
            if "para_shape_id" in raw:
                ps_id = raw["para_shape_id"]
                if ps_id < len(para_shapes):
                    sdef.format = _build_block_format(
                        para_shapes[ps_id], char_shapes, raw.get("char_shape_id")
                    )
            styles[idx] = sdef
            style_name_list.append(style_name)

        elif rec.tag_id == HWPTAG_NUMBERING:
            idx = str(len(numberings))
            parsed_num = _parse_numbering(rec.payload)
            levels = []
            for lv in parsed_num.get("levels", []):
                levels.append(
                    NumberingLevel(
                        level=lv["level"],
                        format=lv.get("format"),
                        prefix=lv.get("pattern"),
                    )
                )
            if not levels:
                levels = [NumberingLevel(level=i) for i in range(7)]
            numberings[idx] = NumberingDef(id=idx, levels=levels)

        elif rec.tag_id == HWPTAG_BULLET:
            idx = str(len(bullets))
            bullet_char: str | None = None
            if len(rec.payload) >= 14:
                (wchar,) = struct.unpack_from("<H", rec.payload, 12)
                if wchar:
                    bullet_char = chr(wchar)
            bullets[idx] = BulletDef(id=idx, char=bullet_char)

        elif rec.tag_id == HWPTAG_TAB_DEF:
            idx = str(len(tab_defs))
            stops = _parse_tab_def(rec.payload)
            tab_defs[idx] = TabDef(id=idx, stops=stops)

        elif rec.tag_id == HWPTAG_BORDER_FILL:
            idx = str(len(border_fills))
            bf_data = _parse_border_fill(rec.payload)
            border_fills[idx] = BorderFillDef(
                id=idx,
                border_color=bf_data.get("border_left_color"),
                border_style=bf_data.get("border_left_style"),
                border_left_color=bf_data.get("border_left_color"),
                border_left_style=bf_data.get("border_left_style"),
                border_left_width=bf_data.get("border_left_width"),
                border_right_color=bf_data.get("border_right_color"),
                border_right_style=bf_data.get("border_right_style"),
                border_right_width=bf_data.get("border_right_width"),
                border_top_color=bf_data.get("border_top_color"),
                border_top_style=bf_data.get("border_top_style"),
                border_top_width=bf_data.get("border_top_width"),
                border_bottom_color=bf_data.get("border_bottom_color"),
                border_bottom_style=bf_data.get("border_bottom_style"),
                border_bottom_width=bf_data.get("border_bottom_width"),
                fill_color=bf_data.get("fill_color"),
            )

    # FaceName 7폴백 매핑: ID_MAPPINGS의 카테고리별 개수를 사용
    if id_mapping_counts and len(id_mapping_counts) >= 8:
        cat_counts = id_mapping_counts[1:8]  # hangul, latin, hanja, japanese, other, symbol, user
        # 각 카테고리별 FaceName을 FontFallbacks 슬롯에 매핑
        # HWP는 카테고리별로 같은 인덱스의 FaceName을 한 세트로 묶음
        max_per_cat = max(cat_counts) if cat_counts else 0
        cat_offsets = []
        off = 0
        for cnt in cat_counts:
            cat_offsets.append(off)
            off += cnt

        face_name_objs_new: dict[str, FontFallbacks] = {}
        for font_idx in range(max_per_cat):
            ff = FontFallbacks()
            for cat_idx, cat_name in enumerate(_FACE_CATEGORY_NAMES):
                cat_off = cat_offsets[cat_idx] if cat_idx < len(cat_offsets) else 0
                cat_cnt = cat_counts[cat_idx] if cat_idx < len(cat_counts) else 0
                global_fn_idx = cat_off + font_idx
                if font_idx < cat_cnt and global_fn_idx < len(face_names):
                    name = face_names[global_fn_idx]
                    if name:
                        setattr(ff, cat_name, name)
            face_name_objs_new[str(font_idx)] = ff
        face_name_objs = face_name_objs_new

    # GlobalResources 조립 (char_shapes/para_shapes는 dict[str, Any])
    gr = GlobalResources(
        char_shapes={str(i): cs for i, cs in enumerate(char_shapes)},
        para_shapes={str(i): ps for i, ps in enumerate(para_shapes)},
        face_names=face_name_objs,
        styles=styles,
        numberings=numberings,
        bullets=bullets,
        border_fills=border_fills,
        tab_defs=tab_defs,
    )
    # BinData: bindata_items를 GlobalResources.bin_data에 BinDataDef로 저장
    from udf.pipeline.verbatim import BinDataDef
    bin_data_dict: dict[str, Any] = {}
    for i, bd in enumerate(bindata_items):
        bin_data_dict[str(i)] = BinDataDef(
            flags=bd.get("flags"),
            bin_type=str(bd.get("type", "")),
            bin_id=bd.get("id"),
            ext=bd.get("ext"),
            stream=bd.get("stream"),
        )

    gr.bin_data = bin_data_dict

    return DocInfoResult(
        global_resources=gr,
        char_shapes=char_shapes,
        para_shapes=para_shapes,
        face_names=face_names,
        style_names=style_name_list,
        bindata_items=bindata_items,
        doc_properties=doc_properties,
        compat_doc=compat_doc,
    )
