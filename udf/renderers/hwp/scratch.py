"""HWP From Scratch 생성기.

원본 HWP 없이 UdfDocument에서 새 HWP 파일을 생성한다.

전략:
  1. seed OLE 컨테이너(plain_text.hwp 등)를 복사
  2. DocInfo 스트림을 Document Model 기반으로 재빌드 후 교체
  3. BodyText/Section0 스트림을 Document Model 기반으로 재빌드 후 교체

이 방식은 OLE2 CFB 직렬화 없이 ole_patch.py 인프라를 재사용한다.
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import struct
import olefile
import zlib
from dataclasses import dataclass, field as dataclass_field
from pathlib import Path
from typing import Any, Iterator

from udf.core.schema import (
    Block, BookmarkBlock, ChartBlock, CodeBlock, CommentBlock, DrawingBlock,
    EndnoteBlock, EquationBlock, EquationInline, FieldBlock, FooterBlock,
    FootnoteBlock, FootnoteRefInline, HeaderBlock, HeadingBlock,
    HorizontalRuleBlock, ImageBlock, ImageInline, LinkInline, ListBlock,
    PageBreakBlock, ParagraphBlock, QuoteBlock, TableBlock, TextArtBlock,
    TextBoxBlock, TextInline, UdfDocument, UnknownBlock,
)
from udf.pipeline.loss import BlockLoss, LossCategory, LossReport
from udf.renderers.hwp.body_builder import (
    CellImageInfo, TextSpan, build_equation, build_footnote, build_endnote,
    build_header_footer, build_hf_inline_anchor, build_image,
    build_paragraph, build_secd_paragraph, build_term_paragraph,
    build_section, build_table, build_textbox_shape,
    _EFFECTIVE_PARA_HEIGHT,
)
from udf.renderers.hwp.docinfo_builder import (
    BinDataSpec,
    BorderFillSpec,
    CharShapeSpec,
    ParaShapeSpec,
    build_docinfo,
    pack_numbering,
    read_seed_charshapes,
    read_seed_parashapes,
)
from udf.renderers.hwp.ole_patch import add_hwp_stream, patch_hwp_stream
from udf.parsers.hwp.ole import OleReader
from udf.schema.types import pt_to_hwpunit


# ---------------------------------------------------------------------------
# HWP 기본값 상수
# ---------------------------------------------------------------------------

HWP_DEFAULTS: dict[str, Any] = {
    "page_width": 59528,       # A4 210mm = 595.28pt × 100 HWPUNIT/pt
    "page_height": 84186,      # A4 297mm = 841.86pt × 100
    "margin_top": 5668,        # 20mm = 56.68pt
    "margin_bottom": 4252,     # 15mm = 42.52pt
    "margin_left": 8504,       # 30mm = 85.04pt
    "margin_right": 8504,      # 30mm = 85.04pt
    "margin_header": 4252,     # 15mm
    "margin_footer": 4252,     # 15mm
    "gutter": 0,
    "font_name_hangul": "함초롬돋움",
    "font_name_latin": "함초롬돋움",
    "font_size_pt": 10.0,
    "line_spacing_pct": 160,
}


# style_id 매핑 (seed DocInfo의 스타일 테이블 기준: 0=바탕글, 2=개요1, 3=개요2, ...)
_STYLE_NORMAL = 0
_STYLE_HEADING = [2, 3, 4, 5, 6, 7]  # 개요1~6


# ---------------------------------------------------------------------------
# Document Model → CharShapeSpec / ParaShapeSpec 동적 수집
# ---------------------------------------------------------------------------

_HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{6})$")


def _parse_color(val: Any | None) -> tuple[int, int, int]:
    """Parse a color value to (R, G, B) tuple."""
    if not val:
        return (0, 0, 0)
    # Color object
    if hasattr(val, "r") and hasattr(val, "g") and hasattr(val, "b"):
        return (val.r, val.g, val.b)
    s = str(val).strip()
    m = _HEX_COLOR_RE.match(s)
    if m:
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return (0, 0, 0)


def _parse_font_size_pt(val: Any | None) -> float:
    """Parse a font size value to points."""
    if val is None:
        return HWP_DEFAULTS["font_size_pt"]
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str) or not val.strip():
        return HWP_DEFAULTS["font_size_pt"]
    v = val.strip().rstrip("pt").rstrip("px").strip()
    try:
        return float(v)
    except ValueError:
        return HWP_DEFAULTS["font_size_pt"]


def _charshape_key(spec: CharShapeSpec) -> tuple:
    """Return a hashable key tuple for CharShapeSpec deduplication."""
    return (
        spec.size_pt, spec.bold, spec.italic, spec.underline,
        spec.strikethrough, spec.color_r, spec.color_g, spec.color_b,
        spec.font_name,
        spec.outline, spec.shadow_type, spec.emboss, spec.engrave,
        spec.superscript, spec.subscript, spec.char_scale,
        spec.letter_spacing, spec.char_offset,
        spec.underline_color_r, spec.underline_color_g, spec.underline_color_b,
        spec.bg_color_r, spec.bg_color_g, spec.bg_color_b,
        spec.strike_color_r, spec.strike_color_g, spec.strike_color_b,
    )


def _parashape_key(spec: ParaShapeSpec) -> tuple:
    """Return a hashable key tuple for ParaShapeSpec deduplication."""
    return (
        spec.alignment, spec.line_spacing, spec.indent_left,
        spec.indent_right, spec.space_before, spec.space_after,
        spec.indent_first,
        spec.line_spacing_type,
        spec.widow_orphan, spec.page_break_before,
    )


def _extract_inline_text(inline: object) -> str:
    """비-TextInline 인라인에서 텍스트를 추출."""
    if isinstance(inline, TextInline):
        return inline.text or ""
    if isinstance(inline, LinkInline):
        return inline.text or ""
    if isinstance(inline, EquationInline):
        return inline.latex or inline.hwp_script or ""
    if isinstance(inline, FootnoteRefInline):
        return str(inline.number or inline.ref_id or "")
    return getattr(inline, "text", "") or ""


def _charshape_from_inline(inline: TextInline) -> CharShapeSpec:
    """Derive a CharShapeSpec from a TextInline's formatting."""
    r, g, b = _parse_color(inline.color)
    ul_r, ul_g, ul_b = _parse_color(inline.underline_color) if inline.underline_color else (0, 0, 0)
    bg_src = inline.highlight_color or inline.background_color
    bg_r, bg_g, bg_b = _parse_color(bg_src) if bg_src else (255, 255, 255)
    st_r, st_g, st_b = _parse_color(inline.strikeout_color) if inline.strikeout_color else (0, 0, 0)

    cs = 100
    if inline.char_scale is not None:
        cs = int(inline.char_scale.percent) if hasattr(inline.char_scale, "percent") else int(inline.char_scale)

    return CharShapeSpec(
        face_hangul=0,
        face_latin=0,
        size_pt=_parse_font_size_pt(inline.font_size),
        bold=inline.bold or False,
        italic=inline.italic or False,
        underline=1 if inline.underline else 0,
        strikethrough=inline.strikethrough or False,
        color_r=r, color_g=g, color_b=b,
        font_name=inline.font_name,
        outline=inline.outline or False,
        shadow_type=1 if inline.shadow else 0,
        emboss=inline.emboss or False,
        engrave=inline.engrave or False,
        superscript=inline.superscript or False,
        subscript=inline.subscript or False,
        char_scale=cs,
        letter_spacing=int(inline.letter_spacing or 0),
        char_offset=int(inline.char_offset or 0),
        underline_color_r=ul_r, underline_color_g=ul_g, underline_color_b=ul_b,
        bg_color_r=bg_r, bg_color_g=bg_g, bg_color_b=bg_b,
        strike_color_r=st_r, strike_color_g=st_g, strike_color_b=st_b,
    )


def _parashape_from_block(block: ParagraphBlock | HeadingBlock, default_ls: int = 160) -> ParaShapeSpec:
    """Derive a ParaShapeSpec from a block's format attributes."""
    fmt = getattr(block, "format", None)
    if not fmt:
        return ParaShapeSpec(line_spacing=default_ls)
    ls = fmt.line_spacing
    if ls is None:
        ls_val = default_ls
    elif hasattr(ls, "percent"):
        ls_val = round(ls.percent)
    elif isinstance(ls, (int, float)):
        ls_val = float(ls)
    elif isinstance(ls, str) and ls.endswith("%"):
        ls_val = round(float(ls.rstrip("%")))
    else:
        ls_val = default_ls

    ls_type = 0
    lst = getattr(fmt, "line_spacing_type", None)
    if lst:
        _LST_MAP = {"follow_char": 0, "ratio": 0, "fixed": 1, "leading_only": 2, "minimum": 3}
        ls_type = _LST_MAP.get(lst, 0)
        if ls_type != 0 and ls is not None:
            ls_val = pt_to_hwpunit(float(ls_val))

    return ParaShapeSpec(
        alignment=fmt.alignment or "justify",
        line_spacing=int(ls_val),
        indent_left=pt_to_hwpunit(fmt.indent_left) if fmt.indent_left else 0,
        indent_right=pt_to_hwpunit(fmt.indent_right) if fmt.indent_right else 0,
        space_before=pt_to_hwpunit(fmt.space_before) if fmt.space_before else 0,
        space_after=pt_to_hwpunit(fmt.space_after) if fmt.space_after else 0,
        indent_first=pt_to_hwpunit(fmt.indent_first) if fmt.indent_first else 0,
        line_spacing_type=ls_type,
        widow_orphan=fmt.widow_orphan or False,
        page_break_before=fmt.page_break_before or False,
        text_direction=fmt.text_direction or "horizontal",
    )


def _iter_all_text_blocks(blocks: list[Block]) -> Iterator[ParagraphBlock | HeadingBlock]:
    """Yield all ParagraphBlock/HeadingBlock recursively (including table cells and textboxes)."""
    for block in blocks:
        if isinstance(block, (ParagraphBlock, HeadingBlock)):
            yield block
        elif isinstance(block, TableBlock):
            for row in block.rows:
                for cell in row.cells:
                    yield from _iter_all_text_blocks(cell.content)
        elif isinstance(block, TextBoxBlock):
            yield from _iter_all_text_blocks(block.content)
        elif isinstance(block, DrawingBlock):
            yield from _iter_all_text_blocks(block.content)


def collect_shapes(
    doc: UdfDocument,
    default_ls: int = 160,
) -> tuple[list[CharShapeSpec], list[ParaShapeSpec], dict[tuple, int], dict[tuple, int]]:
    """Collect unique CharShape and ParaShape specs from Document Model blocks.

    Parameters
    ----------
    doc : UdfDocument
        The document model to analyze.
    default_ls : int, default 160
        Default line spacing percentage for blocks without format metadata.

    Returns
    -------
    tuple[list[CharShapeSpec], list[ParaShapeSpec], dict[tuple, int], dict[tuple, int]]
        (cs_list, ps_list, cs_map, ps_map) where maps are key-to-index.
    """
    cs_map: dict[tuple, int] = {}
    ps_map: dict[tuple, int] = {}
    cs_list: list[CharShapeSpec] = []
    ps_list: list[ParaShapeSpec] = []

    default_cs = CharShapeSpec(size_pt=HWP_DEFAULTS["font_size_pt"])
    dk = _charshape_key(default_cs)
    cs_map[dk] = 0
    cs_list.append(default_cs)

    default_ps = ParaShapeSpec(alignment="justify", line_spacing=default_ls)
    dpk = _parashape_key(default_ps)
    ps_map[dpk] = 0
    ps_list.append(default_ps)

    for block in _iter_all_text_blocks(doc.blocks):
        ps = _parashape_from_block(block, default_ls=default_ls)
        pk = _parashape_key(ps)
        if pk not in ps_map:
            ps_map[pk] = len(ps_list)
            ps_list.append(ps)

        heading_size: float | None = None
        if isinstance(block, HeadingBlock):
            heading_size = _HEADING_SIZE_PT.get(max(1, min(block.level, 6)))

        inlines = block.inlines if hasattr(block, "inlines") else []
        for il in inlines:
            if isinstance(il, TextInline):
                cs = _charshape_from_inline(il)
                if heading_size and cs.size_pt == HWP_DEFAULTS["font_size_pt"]:
                    cs = CharShapeSpec(
                        face_hangul=cs.face_hangul, face_latin=cs.face_latin,
                        size_pt=heading_size, bold=cs.bold or True,
                        italic=cs.italic, underline=cs.underline,
                        strikethrough=cs.strikethrough,
                        color_r=cs.color_r, color_g=cs.color_g, color_b=cs.color_b,
                        font_name=cs.font_name,
                    )
            elif isinstance(il, LinkInline):
                cs = _charshape_for_link()
            elif _extract_inline_text(il):
                cs = CharShapeSpec()
            else:
                continue
            ck = _charshape_key(cs)
            if ck not in cs_map:
                cs_map[ck] = len(cs_list)
                cs_list.append(cs)

    for lvl, sz in _HEADING_SIZE_PT.items():
        hcs = CharShapeSpec(size_pt=sz, bold=True)
        hk = _charshape_key(hcs)
        if hk not in cs_map:
            cs_map[hk] = len(cs_list)
            cs_list.append(hcs)

    # clickhere 필드용 CharShape (배경색 #e6e6e6)
    clk_cs = CharShapeSpec(
        size_pt=HWP_DEFAULTS["font_size_pt"],
        bg_color_r=230, bg_color_g=230, bg_color_b=230,
    )
    clk_k = _charshape_key(clk_cs)
    if clk_k not in cs_map:
        cs_map[clk_k] = len(cs_list)
        cs_list.append(clk_cs)

    code_cs = CharShapeSpec(
        size_pt=HWP_DEFAULTS["font_size_pt"],
        font_name="Courier New",
    )
    code_k = _charshape_key(code_cs)
    if code_k not in cs_map:
        cs_map[code_k] = len(cs_list)
        cs_list.append(code_cs)

    return cs_list, ps_list, cs_map, ps_map


def _match_seed_cs(
    seed_cs: list[CharShapeSpec],
    needed: dict[tuple, int],
) -> dict[tuple, int]:
    """Document Model-derived CS keys를 seed CS 인덱스로 매핑. 매치 안 되면 CS[0] 사용."""
    seed_keys: dict[tuple, int] = {}
    for i, s in enumerate(seed_cs):
        k = _charshape_key(s)
        if k not in seed_keys:
            seed_keys[k] = i
    result: dict[tuple, int] = {}
    for key in needed:
        result[key] = seed_keys.get(key, 0)
    return result


def _match_seed_ps(
    seed_ps: list[ParaShapeSpec],
    needed: dict[tuple, int],
) -> dict[tuple, int]:
    """Document Model-derived PS keys를 seed PS 인덱스로 매핑. 정렬값 기준 best match."""
    align_map: dict[str, int] = {}
    for i, s in enumerate(seed_ps):
        if s.alignment not in align_map:
            align_map[s.alignment] = i

    seed_keys = {_parashape_key(s): i for i, s in enumerate(seed_ps)}
    result: dict[tuple, int] = {}
    for key in needed:
        if key in seed_keys:
            result[key] = seed_keys[key]
        else:
            alignment = key[0]
            result[key] = align_map.get(alignment, 0)
    return result


def _resolve_cs_ids(
    seed_cs: list[CharShapeSpec],
    cs_list: list[CharShapeSpec],
    cs_map: dict[tuple, int],
) -> tuple[dict[tuple, int], list[CharShapeSpec]]:
    """CS keys를 seed 매칭 → 매칭 안 되면 새 레코드 추가.

    Returns:
        (final_cs_map, new_cs_specs).
        final_cs_map[key] = 실제 CS ID (seed 매칭이면 seed ID, 아니면 seed_count + new_idx).
        new_cs_specs = DocInfo에 추가할 새 CharShape 목록.
    """
    seed_count = len(seed_cs)
    seed_keys: dict[tuple, int] = {}
    for i, s in enumerate(seed_cs):
        k = _charshape_key(s)
        if k not in seed_keys:
            seed_keys[k] = i

    final_map: dict[tuple, int] = {}
    new_specs: list[CharShapeSpec] = []

    _FONT_NAME_IDX = 8

    for key, idx in cs_map.items():
        if key in seed_keys:
            final_map[key] = seed_keys[key]
        else:
            if key[_FONT_NAME_IDX] is None:
                match_id = None
                for sk, si in seed_keys.items():
                    if key[:_FONT_NAME_IDX] == sk[:_FONT_NAME_IDX] and key[_FONT_NAME_IDX + 1:] == sk[_FONT_NAME_IDX + 1:]:
                        match_id = si
                        break
                if match_id is not None:
                    final_map[key] = match_id
                    continue
            final_map[key] = seed_count + len(new_specs)
            new_specs.append(cs_list[idx])

    return final_map, new_specs


def _resolve_ps_ids(
    seed_ps: list[ParaShapeSpec],
    ps_list: list[ParaShapeSpec],
    ps_map: dict[tuple, int],
) -> tuple[dict[tuple, int], list[ParaShapeSpec]]:
    """PS keys를 seed 매칭 → 매칭 안 되면 새 레코드 추가.

    Returns:
        (final_ps_map, new_ps_specs).
    """
    seed_count = len(seed_ps)
    seed_keys: dict[tuple, int] = {}
    for i, s in enumerate(seed_ps):
        k = _parashape_key(s)
        if k not in seed_keys:
            seed_keys[k] = i

    final_map: dict[tuple, int] = {}
    new_specs: list[ParaShapeSpec] = []

    for key, idx in ps_map.items():
        if key in seed_keys:
            final_map[key] = seed_keys[key]
        else:
            final_map[key] = seed_count + len(new_specs)
            new_specs.append(ps_list[idx])

    return final_map, new_specs


class ScratchError(Exception):
    pass


def _parse_hu(val: Any | None, default: int) -> int:
    """CSS-like 치수 문자열 → HWPUNIT. "210mm" → 21000.

    float(pt)가 올 수 있으므로 숫자형은 pt로 간주하여 변환.
    """
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return round(val * 100)  # pt → HWPUNIT
    if not isinstance(val, str) or not val.strip():
        return default
    v = val.strip()
    try:
        if v.endswith("mm"):
            return round(float(v[:-2]) * 283.46)  # 1mm ≈ 283.46 HWPUNIT
        if v.endswith("cm"):
            return round(float(v[:-2]) * 2834.6)
        if v.endswith("pt"):
            return round(float(v[:-2]) * 100)  # 1pt = 100 HWPUNIT
        return round(float(v))
    except ValueError:
        return default


def _build_page_meta(metadata) -> dict[str, int] | None:
    """DocumentMetadata → PAGE_DEF 패치용 dict.

    metadata에 명시적 페이지 정보가 없으면 None 반환 → seed PAGE_DEF 유지.
    """
    if metadata is None:
        return None

    pw = metadata.page_width
    ph = metadata.page_height
    margins = metadata.margins
    hdr_margin = getattr(metadata, "header_margin", None)
    ftr_margin = getattr(metadata, "footer_margin", None)
    gutter = getattr(metadata, "gutter", None)

    if pw is None and ph is None and margins is None:
        sections = getattr(metadata, "sections", None)
        if sections:
            s = sections[0]
            pw = getattr(s, "page_width", None)
            ph = getattr(s, "page_height", None)
            margins = getattr(s, "margins", None)

    if pw is None and ph is None and margins is None:
        return None

    d: dict[str, int] = {}
    d["page_width"] = _parse_hu(pw, HWP_DEFAULTS["page_width"])
    d["page_height"] = _parse_hu(ph, HWP_DEFAULTS["page_height"])
    if margins:
        d["margin_top"] = _parse_hu(margins.top, HWP_DEFAULTS["margin_top"])
        d["margin_bottom"] = _parse_hu(margins.bottom, HWP_DEFAULTS["margin_bottom"])
        d["margin_left"] = _parse_hu(margins.left, HWP_DEFAULTS["margin_left"])
        d["margin_right"] = _parse_hu(margins.right, HWP_DEFAULTS["margin_right"])
    else:
        d["margin_top"] = HWP_DEFAULTS["margin_top"]
        d["margin_bottom"] = HWP_DEFAULTS["margin_bottom"]
        d["margin_left"] = HWP_DEFAULTS["margin_left"]
        d["margin_right"] = HWP_DEFAULTS["margin_right"]
    d["margin_header"] = _parse_hu(hdr_margin, HWP_DEFAULTS["margin_header"])
    d["margin_footer"] = _parse_hu(ftr_margin, HWP_DEFAULTS["margin_footer"])
    d["gutter"] = _parse_hu(gutter, HWP_DEFAULTS["gutter"])
    return d


def _read_seed_page_dims(seed_section: bytes) -> dict[str, int]:
    """seed 섹션 스트림에서 PAGE_DEF를 찾아 페이지 치수를 반환한다."""
    from udf.parsers.hwp.records import iter_records, HWPTAG_PAGE_DEF
    for rec in iter_records(seed_section):
        if rec.tag_id == HWPTAG_PAGE_DEF and len(rec.payload) >= 24:
            pw, ph = struct.unpack_from("<II", rec.payload, 0)
            ml, mr, mt, mb = struct.unpack_from("<4I", rec.payload, 8)
            return {
                "page_width": pw, "page_height": ph,
                "margin_left": ml, "margin_right": mr,
                "margin_top": mt, "margin_bottom": mb,
            }
    return {
        "page_width": HWP_DEFAULTS["page_width"],
        "page_height": HWP_DEFAULTS["page_height"],
        "margin_left": HWP_DEFAULTS["margin_left"],
        "margin_right": HWP_DEFAULTS["margin_right"],
        "margin_top": HWP_DEFAULTS["margin_top"],
        "margin_bottom": HWP_DEFAULTS["margin_bottom"],
    }


def _compress(data: bytes) -> bytes:
    """Compress data using raw DEFLATE (no header, as HWP expects)."""
    comp = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -15)
    return comp.compress(data) + comp.flush()


def _ensure_last_para_msb(section_bytes: bytes) -> bytes:
    """섹션 바이트에서 마지막 L0 PARA_HEADER의 MSB(bit 31)를 강제 설정."""
    HWPTAG_PH = 66
    buf = bytearray(section_bytes)
    last_ph_offset = -1
    pos = 0
    while pos + 4 <= len(buf):
        hdr = struct.unpack_from("<I", buf, pos)[0]
        tag = hdr & 0x3FF
        level = (hdr >> 10) & 0x3FF
        size = (hdr >> 20) & 0xFFF
        if size == 0xFFF:
            if pos + 8 > len(buf):
                break
            size = struct.unpack_from("<I", buf, pos + 4)[0]
            payload_start = pos + 8
        else:
            payload_start = pos + 4
        if tag == HWPTAG_PH and level == 0:
            last_ph_offset = payload_start
        pos = payload_start + size
    if last_ph_offset >= 0 and last_ph_offset + 4 <= len(buf):
        raw = struct.unpack_from("<I", buf, last_ph_offset)[0]
        if not (raw & 0x80000000):
            struct.pack_into("<I", buf, last_ph_offset, raw | 0x80000000)
    return bytes(buf)


def _read_seed_docinfo(seed_path: str) -> bytes:
    """seed에서 DocInfo를 (압축 해제된 상태로) 반환.

    OleReader가 FileHeader compressed 플래그를 보고 자동으로 압축 해제한다.
    """
    with OleReader.open(seed_path) as ole:
        return ole.read_stream(["DocInfo"])


def _charshape_for_link() -> CharShapeSpec:
    """Return blue underlined CharShapeSpec for hyperlinks."""
    return CharShapeSpec(color_r=0, color_g=0, color_b=255, underline=True)


def _spans_for_paragraph(
    block: ParagraphBlock,
    cs_map: dict[tuple, int],
) -> list[TextSpan]:
    """ParagraphBlock의 인라인들을 TextSpan 목록으로 변환 (동적 cs_id 매핑)."""
    spans: list[TextSpan] = []
    for inline in block.inlines:
        if isinstance(inline, TextInline):
            text = inline.text
            if not text:
                continue
            cs = _charshape_from_inline(inline)
        elif isinstance(inline, LinkInline):
            text = inline.text or inline.url or ""
            if not text:
                continue
            cs = _charshape_for_link()
        else:
            text = _extract_inline_text(inline)
            if not text:
                continue
            cs = CharShapeSpec()
        ck = _charshape_key(cs)
        cs_id = cs_map.get(ck, 0)
        if spans and spans[-1].cs_id == cs_id:
            spans[-1] = TextSpan(spans[-1].text + text, cs_id)
        else:
            spans.append(TextSpan(text, cs_id))
    return spans or [TextSpan("", 0)]


def _spans_for_paragraph_heading(
    block: ParagraphBlock,
    cs_map: dict[tuple, int],
    heading_size: float,
) -> list[TextSpan]:
    """Like _spans_for_paragraph but applies heading font size to default-sized inlines."""
    spans: list[TextSpan] = []
    for inline in block.inlines:
        if isinstance(inline, TextInline):
            text = inline.text
            if not text:
                continue
            cs = _charshape_from_inline(inline)
            if cs.size_pt == HWP_DEFAULTS["font_size_pt"]:
                cs = CharShapeSpec(
                    face_hangul=cs.face_hangul, face_latin=cs.face_latin,
                    size_pt=heading_size, bold=cs.bold or True,
                    italic=cs.italic, underline=cs.underline,
                    strikethrough=cs.strikethrough,
                    color_r=cs.color_r, color_g=cs.color_g, color_b=cs.color_b,
                    font_name=cs.font_name,
                )
        else:
            text = _extract_inline_text(inline)
            if not text:
                continue
            cs = CharShapeSpec(size_pt=heading_size, bold=True)
        ck = _charshape_key(cs)
        cs_id = cs_map.get(ck, 0)
        if spans and spans[-1].cs_id == cs_id:
            spans[-1] = TextSpan(spans[-1].text + text, cs_id)
        else:
            spans.append(TextSpan(text, cs_id))
    return spans or [TextSpan("", 0)]


# ---------------------------------------------------------------------------
# Block builder context + registry
# ---------------------------------------------------------------------------


@dataclass
class _ImageRef:
    """이미지 블록의 BinData 참조 정보."""
    bin_item_id: int    # 1-based BIN_DATA index
    bin_data_id: int    # OLE stream naming용 ID
    extension: str      # "jpg", "png", etc.
    src: str            # 원본 경로 또는 data URI


@dataclass
class EqTrailing:
    """EQEDIT trailing fields from verbatim."""
    base_unit: int
    text_color: int
    base_line: int
    unknown: int = 0
    version_len: int = 0


@dataclass
class _BuildCtx:
    """블록 빌더들이 공유하는 컨텍스트."""
    cs_map: dict[tuple, int]
    ps_map: dict[tuple, int]
    content_width: int
    font_size_hu: int
    line_spacing_pct: int
    seed_dims: dict[str, int]
    page_meta: dict[str, int] | None
    losses: list[BlockLoss] = dataclass_field(default_factory=list)
    images: list[_ImageRef] = dataclass_field(default_factory=list)
    seed_bindata_count: int = 0
    table_bf_base_id: int = 3
    bf_map: dict[tuple, int] = dataclass_field(default_factory=dict)
    ordered_list_ps_id: int = 0
    doc: UdfDocument | None = None
    unordered_list_ps_id: int = 0
    has_page_bg_image: bool = False
    eq_trailing_map: dict[str, EqTrailing] = dataclass_field(default_factory=dict)


def _extract_text_from_blocks(blocks: list[Block], cs_map: dict[tuple, int]) -> list[TextSpan]:
    """블록 리스트에서 텍스트를 추출하여 TextSpan 리스트로 반환 (중첩 테이블/텍스트박스 포함)."""
    spans: list[TextSpan] = []
    for block in blocks:
        if isinstance(block, ParagraphBlock):
            s = _spans_for_paragraph(block, cs_map)
            if s and s != [TextSpan("", 0)]:
                spans.extend(s)
        elif isinstance(block, HeadingBlock):
            spans.append(TextSpan(block.text, 0))
        elif isinstance(block, TableBlock):
            for row in block.rows:
                for cell in row.cells:
                    cell_spans = _extract_text_from_blocks(cell.content, cs_map)
                    if cell_spans and cell_spans != [TextSpan("", 0)]:
                        spans.extend(cell_spans)
                        spans.append(TextSpan("\n", 0))
        elif isinstance(block, TextBoxBlock):
            tb_spans = _extract_text_from_blocks(block.content, cs_map)
            if tb_spans and tb_spans != [TextSpan("", 0)]:
                spans.extend(tb_spans)
        elif hasattr(block, "text_content"):
            text = block.text_content()
            if text:
                spans.append(TextSpan(text, 0))
    return spans or [TextSpan("", 0)]


def _text_from_blocks(blocks: list[Block]) -> str:
    """블록 리스트에서 plain text만 추출."""
    parts: list[str] = []
    for b in blocks:
        if isinstance(b, ParagraphBlock):
            parts.append("".join(
                _extract_inline_text(il) for il in b.inlines
            ))
        elif isinstance(b, HeadingBlock):
            parts.append(b.text)
        elif hasattr(b, "text_content"):
            parts.append(b.text_content())
    return " ".join(p for p in parts if p)


BuildResult = tuple[bytes, int]  # (record_bytes, height)


_HEADING_SIZE_PT = {1: 24.0, 2: 18.0, 3: 14.0, 4: 12.0, 5: 11.0, 6: 10.0}


def _build_heading(block: HeadingBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """Build records for a HeadingBlock with outline style."""
    level = max(1, min(block.level, 6))
    style_id = _STYLE_HEADING[level - 1]
    heading_size = _HEADING_SIZE_PT[level]
    inlines = getattr(block, "inlines", None)
    if inlines:
        spans = _spans_for_paragraph_heading(
            type("_P", (), {"inlines": inlines})(),  # type: ignore[arg-type]
            ctx.cs_map, heading_size,
        )
    else:
        cs = CharShapeSpec(size_pt=heading_size, bold=True)
        ck = _charshape_key(cs)
        bold_cs_id = ctx.cs_map.get(ck, 0)
        spans = [TextSpan(block.text, bold_cs_id)]
    ps = _parashape_from_block(block, default_ls=ctx.line_spacing_pct)
    pk = _parashape_key(ps)
    ps_id = ctx.ps_map.get(pk, 0)
    orig_pls = _get_original_pls(block, ctx)
    return build_paragraph(
        spans, ps_id=ps_id, style_id=style_id, vpos=vpos,
        content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct, is_last=is_last,
        original_pls=orig_pls,
    )


def _get_original_pls(block: ParagraphBlock, ctx: _BuildCtx) -> bytes | None:
    """Retrieve original PLS bytes from verbatim if available."""
    import base64
    if not ctx.doc or not getattr(ctx.doc, 'verbatim', None):
        return None
    vref = getattr(block, 'verbatim_ref', None)
    if not vref:
        return None
    vl = ctx.doc.verbatim
    vb = vl.blocks.get(vref) if hasattr(vl, 'blocks') else None
    if not vb or not vb.decoded:
        return None
    pls_b64 = vb.decoded.get('pls_bytes')
    if not pls_b64:
        return None
    try:
        return base64.b64decode(pls_b64)
    except Exception:
        return None


def _build_para(block: ParagraphBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """Build records for a ParagraphBlock."""
    has_eq = any(isinstance(il, EquationInline) for il in block.inlines)
    if has_eq:
        from udf.renderers.hwp.body_builder import _PH_MAGIC
        return _build_para_with_eqs(
            block, ctx, rec_level=0, content_width=ctx.content_width,
            is_last=is_last, vpos=vpos, instance_id=_PH_MAGIC,
        )
    ps = _parashape_from_block(block, default_ls=ctx.line_spacing_pct)
    pk = _parashape_key(ps)
    ps_id = ctx.ps_map.get(pk, 0)
    spans = _spans_for_paragraph(block, ctx.cs_map)
    ls_pct = ctx.line_spacing_pct
    fmt = getattr(block, "format", None)
    if fmt and fmt.line_spacing is not None:
        if hasattr(fmt.line_spacing, "percent"):
            ls_pct = round(fmt.line_spacing.percent)
        elif isinstance(fmt.line_spacing, (int, float)):
            ls_type = getattr(fmt, "line_spacing_type", None)
            if ls_type in ("fixed", "leading_only", "minimum"):
                font_pt = ctx.font_size_hu / 100
                ls_pct = max(100, round(fmt.line_spacing / font_pt * 100)) if font_pt > 0 else 100
            else:
                ls_pct = int(fmt.line_spacing)
    orig_pls = _get_original_pls(block, ctx)
    return build_paragraph(
        spans, ps_id=ps_id, style_id=_STYLE_NORMAL, vpos=vpos,
        content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ls_pct, is_last=is_last,
        original_pls=orig_pls,
    )


def _compute_logical_cols(rows: list) -> int:
    """Compute the logical column count accounting for col_span."""
    max_cols = 0
    for row in rows:
        total = sum(getattr(c, "col_span", 1) or 1 for c in row.cells)
        max_cols = max(max_cols, total)
    return max(max_cols, 1)


def _compute_col_widths_merged(rows: list, n_cols: int) -> list[int] | None:
    """Derive per-column widths from cell widths, handling col_span>1."""
    widths: list[int | None] = [None] * n_cols
    # Pass 1: span=1 cells give exact widths
    for row in rows:
        logical_ci = 0
        for cell in row.cells:
            cs = getattr(cell, "col_span", 1) or 1
            w = getattr(cell, "width", None)
            if cs == 1 and w and w > 0 and logical_ci < n_cols:
                widths[logical_ci] = round(w * 100)
            logical_ci += cs
    if all(w is not None and w > 0 for w in widths):
        return [w for w in widths]  # type: ignore[misc]
    # Pass 2: span>1 cells — distribute evenly to unfilled columns
    for row in rows:
        logical_ci = 0
        for cell in row.cells:
            cs = getattr(cell, "col_span", 1) or 1
            w = getattr(cell, "width", None)
            if cs > 1 and w and w > 0 and logical_ci + cs <= n_cols:
                w_hu = round(w * 100)
                unfilled = [c for c in range(logical_ci, logical_ci + cs) if widths[c] is None]
                filled_sum = sum(widths[c] for c in range(logical_ci, logical_ci + cs) if widths[c] is not None)
                remaining = w_hu - filled_sum
                if unfilled and remaining > 0:
                    per = remaining // len(unfilled)
                    for c in unfilled:
                        widths[c] = per
            logical_ci += cs
    if all(w is not None and w > 0 for w in widths):
        return [w for w in widths]  # type: ignore[misc]
    return None


def _cell_needs_multi_build(cell_content: list[Block]) -> bool:
    """Check if a cell needs multi-block building (multi-paragraph, equation, or nested table)."""
    if len(cell_content) > 1:
        return True
    for cb in cell_content:
        if isinstance(cb, (EquationBlock, ListBlock, TableBlock)):
            return True
        if isinstance(cb, ParagraphBlock):
            for il in cb.inlines:
                if isinstance(il, EquationInline):
                    return True
    return False


def _build_para_with_eqs(
    block: ParagraphBlock,
    ctx: _BuildCtx,
    rec_level: int,
    content_width: int,
    is_last: bool,
    vpos: int = 0,
    instance_id: int = 0,
) -> tuple[bytes, int]:
    """Build a paragraph with inline equation controls (CTRL_HEADER + EQEDIT).

    Works for both cell paragraphs (instance_id=0) and top-level paragraphs
    (instance_id=_PH_MAGIC).
    """
    eq_inlines: list[EquationInline] = []
    for il in block.inlines:
        if isinstance(il, EquationInline):
            eq_inlines.append(il)
    if not eq_inlines:
        spans = _spans_for_paragraph(block, ctx.cs_map)
        ps = _parashape_from_block(block, default_ls=ctx.line_spacing_pct)
        pk = _parashape_key(ps)
        ps_id = ctx.ps_map.get(pk, 0)
        orig_pls = _get_original_pls(block, ctx)
        return build_paragraph(
            spans, ps_id=ps_id, level=rec_level,
            is_last=is_last, vpos=vpos,
            content_width=content_width,
            font_size_hu=ctx.font_size_hu,
            line_spacing_pct=ctx.line_spacing_pct,
            original_pls=orig_pls,
        )

    from udf.renderers.hwp.body_builder import (
        _pack_record, _build_para_header, _build_pls,
        _build_inline_ctrl_obj, _sanitize_text,
        _CTRL_CODE_EQED, _CTRL_ID_EQED,
        _ctrl_mask_from_text,
        HWPTAG_PARA_HEADER, HWPTAG_PARA_TEXT, HWPTAG_PARA_CHAR_SHAPE,
        HWPTAG_PARA_LINE_SEG, HWPTAG_CTRL_HEADER, HWPTAG_EQEDIT,
    )

    # Build PARA_TEXT with interleaved text and inline ctrl objects
    pt_payload = b""
    pcs_entries: list[tuple[int, int]] = []
    char_pos = 0
    eq_scripts: list[str] = []
    eq_trailings: list[bytes | None] = []

    for il in block.inlines:
        if isinstance(il, EquationInline):
            inline_obj = _build_inline_ctrl_obj(_CTRL_CODE_EQED, _CTRL_ID_EQED)
            pt_payload += inline_obj
            eq_scripts.append(il.hwp_script or il.latex or "")
            eq_trailings.append(getattr(il, "_eq_trailing", None))
            char_pos += 8  # inline ctrl = 8 charCnt units
        elif isinstance(il, TextInline):
            text = il.text or ""
            if not text:
                continue
            cs = _charshape_from_inline(il)
            ck = _charshape_key(cs)
            cs_id = ctx.cs_map.get(ck, 0)
            pcs_entries.append((char_pos, cs_id))
            pt_payload += _sanitize_text(text).encode("utf-16-le")
            char_pos += len(text)
        else:
            text = _extract_inline_text(il)
            if text:
                pcs_entries.append((char_pos, 0))
                pt_payload += _sanitize_text(text).encode("utf-16-le")
                char_pos += len(text)

    pt_payload += b"\x0d\x00"  # CR
    char_cnt = len(pt_payload) // 2

    if not pcs_entries:
        pcs_entries = [(0, 0)]
    pcs_buf = b""
    for pos, cs_id in pcs_entries:
        pcs_buf += struct.pack("<II", pos, cs_id)

    pls = _build_pls(char_cnt, vpos=vpos, dist=content_width,
                     line_spacing_pct=ctx.line_spacing_pct)
    ls_count = len(pls) // 36

    full_text = "".join(il.text or "" for il in block.inlines if isinstance(il, TextInline))
    ctrl_mask = _ctrl_mask_from_text(full_text)
    if eq_scripts:
        ctrl_mask |= 0x00000800  # inline ctrl bit

    ps = _parashape_from_block(block, default_ls=ctx.line_spacing_pct)
    pk = _parashape_key(ps)
    ps_id = ctx.ps_map.get(pk, 0)

    ph = _build_para_header(
        char_cnt=char_cnt,
        cs_count=len(pcs_entries),
        ls_count=ls_count,
        ps_id=ps_id,
        control_mask=ctrl_mask,
        is_last=is_last,
        instance_id=instance_id,
    )

    out = _pack_record(HWPTAG_PARA_HEADER, rec_level, ph)
    out += _pack_record(HWPTAG_PARA_TEXT, rec_level + 1, pt_payload)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, rec_level + 1, pcs_buf)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, rec_level + 1, pls)

    for i, script in enumerate(eq_scripts):
        ctrl_payload = _CTRL_ID_EQED
        ctrl_payload += struct.pack("<I", 0x0C2A2211)
        ctrl_payload += struct.pack("<ii", 0, 0)
        ctrl_payload += struct.pack("<II", ctx.font_size_hu * 4, ctx.font_size_hu * 2)
        ctrl_payload += struct.pack("<hh", 0, 0)
        ctrl_payload += struct.pack("<4H", 56, 56, 0, 0)
        ctrl_payload += struct.pack("<I", 0)
        ctrl_payload += struct.pack("<IH", 0, 0)  # trailing (6B)
        out += _pack_record(HWPTAG_CTRL_HEADER, rec_level + 1, ctrl_payload)

        script_bytes = script.encode("utf-16-le")
        eqedit = struct.pack("<I", 0)
        eqedit += struct.pack("<H", len(script))
        eqedit += script_bytes
        # trailing fields (14B) — 원본 verbatim 우선, fallback 상수
        raw_trailing = eq_trailings[i] if i < len(eq_trailings) else None
        if raw_trailing and len(raw_trailing) >= 14:
            eqedit += raw_trailing[:14]
        else:
            # script-based lookup from verbatim section stream
            tr = ctx.eq_trailing_map.get(f"_script:{script}")
            if tr:
                eqedit += struct.pack("<I", tr.base_unit)
                eqedit += struct.pack("<I", tr.text_color)
                eqedit += struct.pack("<H", tr.base_line)
                eqedit += struct.pack("<H", tr.unknown)
                eqedit += struct.pack("<H", tr.version_len)
            else:
                eqedit += struct.pack("<I", ctx.font_size_hu)
                eqedit += struct.pack("<I", 0x00000000)
                eqedit += struct.pack("<H", 84)
                eqedit += struct.pack("<H", 0)
                eqedit += struct.pack("<H", 0)
        out += _pack_record(HWPTAG_EQEDIT, rec_level + 2, eqedit)

    line_height = ctx.font_size_hu * ctx.line_spacing_pct // 100
    return out, max(line_height, ctx.font_size_hu * 2) if eq_scripts else line_height


def _build_cell_content(
    cell_blocks: list[Block],
    ctx: _BuildCtx,
    cell_level: int,
    cell_cw: int,
) -> tuple[bytes, int]:
    """Build all records for a cell's content blocks individually.

    Returns (record_bytes, para_count) where para_count counts paragraphs
    for the LIST_HEADER.
    """
    total_bytes = b""
    para_count = 0
    n_blocks = len(cell_blocks)

    for bi, cb in enumerate(cell_blocks):
        is_final = (bi == n_blocks - 1)

        if isinstance(cb, ParagraphBlock):
            has_eq = any(isinstance(il, EquationInline) for il in cb.inlines)
            if has_eq:
                rec, h = _build_para_with_eqs(
                    cb, ctx, cell_level, cell_cw, is_last=False)
            else:
                spans = _spans_for_paragraph(cb, ctx.cs_map)
                ps = _parashape_from_block(cb, default_ls=ctx.line_spacing_pct)
                pk = _parashape_key(ps)
                ps_id = ctx.ps_map.get(pk, 0)
                orig_pls = _get_original_pls(cb, ctx)
                rec, h = build_paragraph(
                    spans, ps_id=ps_id, level=cell_level,
                    is_last=False, vpos=0,
                    content_width=cell_cw,
                    font_size_hu=ctx.font_size_hu,
                    line_spacing_pct=ctx.line_spacing_pct,
                    original_pls=orig_pls,
                )
            total_bytes += rec
            para_count += 1

        elif isinstance(cb, HeadingBlock):
            level_h = max(1, min(cb.level, 6))
            heading_size = _HEADING_SIZE_PT[level_h]
            cs = CharShapeSpec(size_pt=heading_size, bold=True)
            ck = _charshape_key(cs)
            bold_cs_id = ctx.cs_map.get(ck, 0)
            spans = [TextSpan(cb.text, bold_cs_id)]
            rec, h = build_paragraph(
                spans, level=cell_level,
                is_last=False, vpos=0,
                content_width=cell_cw,
                font_size_hu=ctx.font_size_hu,
                line_spacing_pct=ctx.line_spacing_pct,
            )
            total_bytes += rec
            para_count += 1

        elif isinstance(cb, EquationBlock):
            script = getattr(cb, "hwp_script", None) or getattr(cb, "latex", "") or ""
            rec, h = build_equation(
                script, 0, level=cell_level,
                font_size_hu=ctx.font_size_hu,
                line_spacing_pct=ctx.line_spacing_pct,
            )
            total_bytes += rec
            para_count += 1

        elif isinstance(cb, TableBlock):
            result = _build_table_block(cb, 0, ctx, False)
            if result:
                rec, h = result
                if cell_level > 0:
                    from udf.renderers.hwp.body_builder import _bump_record_levels
                    rec = _bump_record_levels(rec, cell_level)
                total_bytes += rec
                para_count += 1

        elif isinstance(cb, ImageBlock):
            continue

        else:
            spans = _extract_text_from_blocks([cb], ctx.cs_map)
            if spans and spans != [TextSpan("", 0)]:
                rec, h = build_paragraph(
                    spans, level=cell_level,
                    is_last=False, vpos=0,
                    content_width=cell_cw,
                    font_size_hu=ctx.font_size_hu,
                    line_spacing_pct=ctx.line_spacing_pct,
                )
                total_bytes += rec
                para_count += 1

    if para_count == 0:
        rec, h = build_paragraph(
            [TextSpan("", 0)], level=cell_level,
            is_last=False, vpos=0,
            content_width=cell_cw,
            font_size_hu=ctx.font_size_hu,
            line_spacing_pct=ctx.line_spacing_pct,
        )
        total_bytes = rec
        para_count = 1

    return total_bytes, para_count


def _build_table_block(block: TableBlock, vpos: int, ctx: _BuildCtx, _is_last: bool) -> BuildResult:
    """Build records for a TableBlock with cell content."""
    cell_texts: list[list[list[TextSpan]]] = []
    cell_bf_ids: list[list[int]] = []
    cell_ps_ids: list[list[int]] = []
    cell_merges: list[list[tuple[int, int]]] = []
    cell_images: list[list[list[CellImageInfo]]] = []
    cell_valigns: list[list[str]] = []
    cell_pls_data: list[list[bytes | None]] = []
    has_merges = False
    has_cell_images = False
    has_cell_pls = False
    for row in block.rows:
        row_spans: list[list[TextSpan]] = []
        row_bfs: list[int] = []
        row_ps: list[int] = []
        row_merges: list[tuple[int, int]] = []
        row_imgs: list[list[CellImageInfo]] = []
        row_pls: list[bytes | None] = []
        for cell in row.cells:
            spans = _extract_text_from_blocks(cell.content, ctx.cs_map)
            row_spans.append(spans)
            first_cb = cell.content[0] if cell.content else None
            cpls = _get_original_pls(first_cb, ctx) if first_cb and isinstance(first_cb, ParagraphBlock) else None
            row_pls.append(cpls)
            if cpls:
                has_cell_pls = True

            # Collect ImageBlock/ImageInline from cell content
            imgs: list[CellImageInfo] = []
            for cb in cell.content:
                if isinstance(cb, ImageBlock) and cb.src:
                    ext = _guess_ext_with_verbatim(cb.src, ctx.doc)
                    if ext:
                        img_w = round((cb.width or 200) * 100)
                        img_h = round((cb.height or 150) * 100)
                        bin_item_id = ctx.seed_bindata_count + len(ctx.images) + 1
                        ctx.images.append(_ImageRef(
                            bin_item_id=bin_item_id,
                            bin_data_id=bin_item_id,
                            extension=ext,
                            src=cb.src,
                        ))
                        imgs.append(CellImageInfo(
                            bin_item_id=bin_item_id,
                            img_width=img_w,
                            img_height=img_h,
                        ))
                    else:
                        ctx.losses.append(BlockLoss(
                            block_id=cb.id,
                            loss_type=LossCategory.FORMAT_LIMIT,
                            description=f"ImageBlock in table cell: unsupported format: {cb.src[:50]}",
                        ))
                # Also handle ImageInline inside paragraphs within cells
                cell_inlines = getattr(cb, "inlines", None)
                if cell_inlines:
                    for il in cell_inlines:
                        if isinstance(il, ImageInline) and il.src:
                            ext = _guess_ext_with_verbatim(il.src, ctx.doc)
                            if ext:
                                img_w = round((il.width or 200) * 100)
                                img_h = round((il.height or 150) * 100)
                                bin_item_id = ctx.seed_bindata_count + len(ctx.images) + 1
                                ctx.images.append(_ImageRef(
                                    bin_item_id=bin_item_id,
                                    bin_data_id=bin_item_id,
                                    extension=ext,
                                    src=il.src,
                                ))
                                imgs.append(CellImageInfo(
                                    bin_item_id=bin_item_id,
                                    img_width=img_w,
                                    img_height=img_h,
                                ))
            row_imgs.append(imgs)
            if imgs:
                has_cell_images = True

            cell_fmt = getattr(cell, "format", None)
            bg_color = getattr(cell_fmt, "background_color", None) if cell_fmt else None
            # Detect per-side border styles
            cell_bt = (1, 1, 1, 1)  # (left, right, top, bottom) default solid
            if cell_fmt:
                _sides = []
                for _side in ("left", "right", "top", "bottom"):
                    _bval = getattr(cell_fmt, f"border_{_side}", None)
                    if _bval:
                        _parts = _bval.split()
                        _sides.append(_BORDER_STYLE_TO_TYPE.get(_parts[1], 1) if len(_parts) >= 2 else 1)
                    else:
                        _sides.append(0)  # no border
                cell_bt = tuple(_sides) if _sides != [1,1,1,1] else (1,1,1,1)
            if bg_color:
                r, g, b = _parse_color(bg_color)
                bf_key = (r, g, b) + cell_bt
                if bf_key not in ctx.bf_map:
                    ctx.bf_map[bf_key] = ctx.table_bf_base_id + len(ctx.bf_map) + 1
                row_bfs.append(ctx.bf_map[bf_key])
            elif cell_bt != (1, 1, 1, 1):
                bf_key = (0, 0, 0) + cell_bt
                if bf_key not in ctx.bf_map:
                    ctx.bf_map[bf_key] = ctx.table_bf_base_id + len(ctx.bf_map) + 1
                row_bfs.append(ctx.bf_map[bf_key])
            else:
                row_bfs.append(ctx.table_bf_base_id)
            first_block = cell.content[0] if cell.content else None
            if first_block and isinstance(first_block, (ParagraphBlock, HeadingBlock)):
                ps = _parashape_from_block(first_block, default_ls=ctx.line_spacing_pct)
                pk = _parashape_key(ps)
                row_ps.append(ctx.ps_map.get(pk, 0))
            else:
                row_ps.append(0)
            cs = getattr(cell, "col_span", 1) or 1
            rs = getattr(cell, "row_span", 1) or 1
            row_merges.append((cs, rs))
            if cs > 1 or rs > 1:
                has_merges = True
        row_valigns: list[str] = []
        for cell in row.cells:
            cell_fmt = getattr(cell, "format", None)
            va = getattr(cell_fmt, "vertical_align", None) if cell_fmt else None
            row_valigns.append(va or "top")
        cell_texts.append(row_spans)
        cell_bf_ids.append(row_bfs)
        cell_ps_ids.append(row_ps)
        cell_merges.append(row_merges)
        cell_images.append(row_imgs)
        cell_valigns.append(row_valigns)
        cell_pls_data.append(row_pls)
    n_rows = len(block.rows)
    n_cols = _compute_logical_cols(block.rows) if has_merges else max((len(r.cells) for r in block.rows), default=1)
    from collections import Counter as _Ctr
    _cell_ls: _Ctr[int] = _Ctr()
    for row in block.rows:
        for cell in row.cells:
            for cb in cell.content:
                _cf = getattr(cb, "format", None)
                if _cf and _cf.line_spacing and hasattr(_cf.line_spacing, "percent"):
                    _cell_ls[round(_cf.line_spacing.percent)] += 1
    tbl_ls = _cell_ls.most_common(1)[0][0] if _cell_ls else ctx.line_spacing_pct
    has_any_fixed_w = any(
        c.fixed_width for row in block.rows for c in row.cells
    )
    is_fixed = block.layout_type != "auto"

    col_widths: list[int] | None = None
    if (is_fixed or has_any_fixed_w) and block.rows and len(block.rows[0].cells) == n_cols:
        col_widths = [round((c.width or 0) * 100) for c in block.rows[0].cells]
        if not all(w > 0 for w in col_widths):
            col_widths = None
    if col_widths is None and block.col_widths and len(block.col_widths) == n_cols:
        col_widths = [round((cd.width or 0) * 100) for cd in block.col_widths]
        if not all(w > 0 for w in col_widths):
            col_widths = None
    if col_widths is None and block.rows:
        if has_merges:
            col_widths = _compute_col_widths_merged(block.rows, n_cols)
        else:
            first_row_widths = [round((c.width or 0) * 100) for c in block.rows[0].cells]
            if all(w > 0 for w in first_row_widths) and len(first_row_widths) == n_cols:
                col_widths = first_row_widths
    if col_widths is None and n_cols > 1:
        tbl_w = round((block.width or 0) * 100) or ctx.content_width
        per_col = tbl_w // n_cols
        if per_col >= 3000:
            col_widths = [per_col] * n_cols
    if col_widths:
        total = sum(col_widths)
        if total > ctx.content_width:
            scale = ctx.content_width / total
            col_widths = [max(1, int(w * scale)) for w in col_widths]
    cell_w_hint: list[list[int]] = []
    for row in block.rows:
        row_w: list[int] = []
        for cell in row.cells:
            row_w.append(round((cell.width or 0) * 100))
        cell_w_hint.append(row_w)

    freeze_row_flags: list[bool] = []
    row_h_hint: list[int] = []
    for ri, row in enumerate(block.rows):
        row_frozen = is_fixed or all(c.fixed_height for c in row.cells)
        freeze_row_flags.append(row_frozen)
        single_span = [c for c in row.cells if (c.row_span or 1) == 1]
        if single_span:
            rh = max(round((c.height or 0) * 100) for c in single_span)
        else:
            rh = round((row.height or 0) * 100) if row.height else 0
        if not rh:
            rh = max((round((c.height or 0) * 100) for c in row.cells), default=0)
        row_h_hint.append(rh)

    # Pre-build multi-block cell content (multi-paragraph, equations, etc.)
    cell_cb_data: list[list[tuple[bytes, int]]] | None = None
    needs_multi = any(
        _cell_needs_multi_build(cell.content)
        for row in block.rows for cell in row.cells
    )
    if needs_multi:
        from udf.renderers.hwp.body_builder import _DEFAULT_CELL_PADDING_H
        # Compute col_widths for cell content width (fallback to equal distribution)
        effective_cw = col_widths
        if effective_cw is None:
            from udf.renderers.hwp.body_builder import _auto_col_widths
            effective_cw = _auto_col_widths(n_cols, cell_texts, ctx.content_width, ctx.font_size_hu)
        cell_cb_data = []
        for ri, row in enumerate(block.rows):
            row_cb: list[tuple[bytes, int]] = []
            logical_ci = 0
            for di, cell in enumerate(row.cells):
                cs_span = getattr(cell, "col_span", 1) or 1
                cw_sum = sum(effective_cw[logical_ci:logical_ci + cs_span]) if logical_ci + cs_span <= len(effective_cw) else effective_cw[0] if effective_cw else ctx.content_width
                cell_cw = max(1, cw_sum - 2 * _DEFAULT_CELL_PADDING_H)
                cb_bytes, cb_pc = _build_cell_content(
                    cell.content, ctx, cell_level=2, cell_cw=cell_cw)
                row_cb.append((cb_bytes, cb_pc))
                logical_ci += cs_span
            cell_cb_data.append(row_cb)

    return build_table(
        n_rows, n_cols, cell_texts, ctx.content_width, vpos,
        col_widths=col_widths,
        cell_widths_hint=cell_w_hint if any(any(w > 0 for w in r) for r in cell_w_hint) else None,
        font_size_hu=ctx.font_size_hu, line_spacing_pct=tbl_ls,
        bf_id=ctx.table_bf_base_id,
        cell_bf_ids=cell_bf_ids,
        cell_ps_ids=cell_ps_ids,
        cell_merges=cell_merges if has_merges else None,
        cell_images=cell_images if has_cell_images else None,
        row_heights_hint=row_h_hint if any(h > 0 for h in row_h_hint) else None,
        freeze_row_heights=freeze_row_flags if any(freeze_row_flags) else None,
        cell_valigns=cell_valigns if any(va != "top" for row_va in cell_valigns for va in row_va) else None,
        tbl_cell_spacing=round((block.cell_spacing or 0) * 100),
        tbl_padding=_tbl_padding(block),
        cell_original_pls=cell_pls_data if has_cell_pls else None,
        cell_content_bytes=cell_cb_data,
        freeze_layout=block.layout_type != "auto",
    )


def _tbl_padding(block) -> tuple[int, int, int, int] | None:
    if block.rows:
        cell = block.rows[0].cells[0] if block.rows[0].cells else None
        cf = getattr(cell, "format", None) if cell else None
        if cf:
            pl = getattr(cf, "padding_left", None)
            pr = getattr(cf, "padding_right", None)
            pt = getattr(cf, "padding_top", None)
            pb = getattr(cf, "padding_bottom", None)
            if pl is not None and pr is not None and pt is not None and pb is not None:
                return (round(pl * 100), round(pr * 100), round(pt * 100), round(pb * 100))
    dp = block.default_padding
    if dp is None:
        return None
    v = round(dp * 100)
    return (v, v, v, v)


def _build_equation_block(block: EquationBlock, vpos: int, ctx: _BuildCtx, _is_last: bool) -> BuildResult:
    """Build records for an EquationBlock."""
    script = getattr(block, "hwp_script", None) or getattr(block, "latex", "") or ""
    # verbatim trailing lookup (verbatim_ref 또는 script 기반)
    vref = getattr(block, "verbatim_ref", None)
    tr = ctx.eq_trailing_map.get(vref) if vref else None
    if not tr:
        tr = ctx.eq_trailing_map.get(f"_script:{script}")
    trailing_bytes: bytes | None = None
    if tr:
        trailing_bytes = struct.pack("<IIHhH", tr.base_unit, tr.text_color, tr.base_line, tr.unknown, tr.version_len)
    return build_equation(
        script, vpos,
        font_size_hu=ctx.font_size_hu, line_spacing_pct=ctx.line_spacing_pct,
        eq_trailing=trailing_bytes,
    )


def _build_page_break(block: PageBreakBlock, vpos: int, ctx: _BuildCtx, _is_last: bool) -> BuildResult:
    """Handle a PageBreakBlock by computing vpos jump to next page."""
    pm = ctx.page_meta or ctx.seed_dims
    usable = (
        pm.get("page_height", ctx.seed_dims["page_height"])
        - pm.get("margin_top", ctx.seed_dims["margin_top"])
        - pm.get("margin_bottom", ctx.seed_dims["margin_bottom"])
    )
    if usable > 0:
        new_vpos = ((vpos // usable) + 1) * usable
        return b"", new_vpos - vpos
    return b"", 0


def _build_list_block(block: ListBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """ListBlock → 아이템별 단락으로 렌더링 (네이티브 번호 매기기)."""
    ps_id = ctx.ordered_list_ps_id if block.ordered else ctx.unordered_list_ps_id
    total_bytes = b""
    total_height = 0
    for idx, item in enumerate(block.items):
        spans: list[TextSpan] = []
        for il in (item.inlines or []):
            if isinstance(il, TextInline):
                if not il.text:
                    continue
                cs = _charshape_from_inline(il)
                ck = _charshape_key(cs)
                cs_id = ctx.cs_map.get(ck, 0)
                spans.append(TextSpan(il.text, cs_id))
            else:
                txt = _extract_inline_text(il)
                if txt:
                    spans.append(TextSpan(txt, 0))
        if not spans:
            text = item.text_content()
            if not ps_id:
                prefix = f"{idx + 1}. " if block.ordered else "• "
                text = prefix + text
            spans = [TextSpan(text, 0)]
        is_final = is_last and idx == len(block.items) - 1
        rec, h = build_paragraph(
            spans, ps_id=ps_id, vpos=vpos + total_height,
            content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
            line_spacing_pct=ctx.line_spacing_pct, is_last=is_final,
        )
        total_bytes += rec
        total_height += h
    if not block.items:
        return build_paragraph(
            [TextSpan("", 0)], vpos=vpos,
            content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
            line_spacing_pct=ctx.line_spacing_pct, is_last=is_last,
        )
    return total_bytes, total_height


def _build_code_block(block: CodeBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """CodeBlock → 등폭 폰트 단락으로."""
    code_cs = CharShapeSpec(
        size_pt=HWP_DEFAULTS["font_size_pt"],
        font_name="Courier New",
    )
    code_cs_id = ctx.cs_map.get(_charshape_key(code_cs), 0)
    spans = [TextSpan(block.code, code_cs_id)]
    ps = ParaShapeSpec(line_spacing=ctx.line_spacing_pct)
    pk = _parashape_key(ps)
    ps_id = ctx.ps_map.get(pk, 0)
    return build_paragraph(
        spans, ps_id=ps_id, vpos=vpos,
        content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct, is_last=is_last,
    )


def _build_quote_block(block: QuoteBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """QuoteBlock → 내부 블록을 순차 단락으로."""
    total_bytes = b""
    total_height = 0
    for idx, cb in enumerate(block.content):
        is_final = is_last and idx == len(block.content) - 1
        result = _dispatch_block(cb, vpos + total_height, ctx, is_final)
        if result:
            rec, h = result
            total_bytes += rec
            total_height += h
    if not block.content:
        return build_paragraph(
            [TextSpan("", 0)], vpos=vpos,
            content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
            line_spacing_pct=ctx.line_spacing_pct, is_last=is_last,
        )
    return total_bytes, total_height



def _sample_bg_image_color(doc: UdfDocument | None, x: float, y: float, w: float, h: float, content_width: int) -> str | None:
    """배경 이미지에서 (x,y) 위치의 픽셀 색상을 추출. PIL 없으면 None."""
    if not doc or not getattr(doc, 'verbatim', None):
        return None
    vl = doc.verbatim
    if not vl.bindata_streams:
        return None
    page_w = 595.0
    page_h = 842.0
    meta = getattr(doc.document, 'metadata', None)
    if meta and meta.sections:
        page_w = meta.sections[0].page_width or page_w
        page_h = meta.sections[0].page_height or page_h
    try:
        import io, base64
        from PIL import Image
        for bv in vl.bindata_streams.values():
            raw = base64.b64decode(bv)
            try:
                img = Image.open(io.BytesIO(raw))
                if img.size[0] > 500 and img.size[1] > 500:
                    px = img.size[0] / page_w
                    py = img.size[1] / page_h
                    cx = min(int((x + w / 2) * px), img.size[0] - 1)
                    cy = min(int((y + h / 2) * py), img.size[1] - 1)
                    r, g, b = img.getpixel((cx, cy))[:3]
                    return f"#{r:02x}{g:02x}{b:02x}"
            except Exception:
                pass
    except ImportError:
        pass
    return None

def _build_textbox_block(block: TextBoxBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """TextBoxBlock → GSO $rec if no complex children, else flat."""
    raw_w = block.width or 200
    tb_width = round(raw_w * 100)
    has_complex = any(isinstance(cb, (TableBlock, TextBoxBlock, DrawingBlock)) for cb in block.content)
    saved_cw = ctx.content_width
    ctx.content_width = tb_width
    content_bytes = b""
    content_height = 0
    for idx, cb in enumerate(block.content):
        is_final = idx == len(block.content) - 1
        result = _dispatch_block(cb, content_height, ctx, is_final)
        if result:
            rec, h = result
            content_bytes += rec
            content_height += h
    ctx.content_width = saved_cw
    if not content_bytes:
        return build_paragraph(
            [TextSpan("", 0)], vpos=vpos,
            content_width=tb_width, font_size_hu=ctx.font_size_hu,
            line_spacing_pct=ctx.line_spacing_pct, is_last=is_last,
        )
    if has_complex:
        pos_c = block.position
        is_small_complex = (pos_c and pos_c.x is not None and pos_c.y is not None
                            and block.width and block.height and (block.height or 0) < 200)
        if is_small_complex:
            text_spans = _extract_text_from_blocks(block.content, ctx.cs_map)
            text_rec = b""
            text_h = 0
            r = build_paragraph(text_spans, vpos=0,
                                content_width=tb_width, font_size_hu=ctx.font_size_hu,
                                line_spacing_pct=ctx.line_spacing_pct, is_last=True)
            text_rec = r[0]
            text_h = r[1]
            if text_rec:
                fill_c = block.background_color
                if not fill_c and block.line_color:
                    fill_c = block.line_color
                height_c = round((block.height or text_h / 100) * 100) or text_h
                return build_textbox_shape(
                    text_rec, tb_width, height_c, vpos,
                    line_color=block.line_color, fill_color=fill_c,
                    font_size_hu=ctx.font_size_hu, line_spacing_pct=ctx.line_spacing_pct,
                    x_offset=round(pos_c.x * 100), y_offset=round(pos_c.y * 100), floating=True,
                    position=pos_c,
                )
        if pos_c and pos_c.y is not None and block.height:
            target_y = round(pos_c.y * 100)
            if target_y > vpos:
                gap = target_y - vpos
                spacer, sh = build_paragraph(
                    [TextSpan("", 0)], vpos=vpos,
                    content_width=ctx.content_width,
                    font_size_hu=gap, line_spacing_pct=100, is_last=False)
                return spacer + content_bytes, sh + content_height
        return content_bytes, content_height
    width = tb_width
    height = round((block.height or content_height / 100) * 100) or content_height
    fill = block.background_color
    if not fill and block.line_color:
        fill = block.line_color
    if not fill and ctx.has_page_bg_image:
        has_white_text = any(
            str(getattr(il, "color", "")) == "#ffffff"
            for cb in block.content
            for il in (getattr(cb, "inlines", None) or [])
        )
        if has_white_text:
            sampled = _sample_bg_image_color(
                ctx.doc, block.position.x, block.position.y,
                block.width or 50, block.height or 14, ctx.content_width)
            fill = sampled or "#4a2040"
    pos = block.position
    is_positioned = (pos is not None and pos.x is not None and pos.y is not None
                     and block.width and block.height)
    x_off = round(pos.x * 100) if is_positioned else 0
    y_off = round(pos.y * 100) if is_positioned else 0
    tb_pad = None
    if any(getattr(block, f"padding_{s}", None) for s in ("left", "right", "top", "bottom")):
        def _p(s): return round((getattr(block, f"padding_{s}", None) or 2.85) * 100)
        tb_pad = (_p("left"), _p("right"), _p("top"), _p("bottom"))
    return build_textbox_shape(
        content_bytes, width, height, vpos,
        line_color=block.line_color,
        fill_color=fill,
        x_offset=x_off,
        y_offset=y_off,
        floating=is_positioned,
        font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct,
        position=pos,
        tb_padding=tb_pad,
        tb_vertical_align=block.vertical_align,
    )


def _build_drawing_block(block: DrawingBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """DrawingBlock → GSO textbox shape if has visual properties, else flat paragraphs."""
    all_blocks: list[Block] = list(block.content)
    for child_draw in block.children:
        all_blocks.append(child_draw)
    content_bytes = b""
    content_height = 0
    for idx, cb in enumerate(all_blocks):
        is_final = is_last and idx == len(all_blocks) - 1
        result = _dispatch_block(cb, vpos + content_height, ctx, is_final)
        if result:
            rec, h = result
            content_bytes += rec
            content_height += h
    if not content_bytes:
        return None
    return content_bytes, content_height


def _build_footnote_block(block: FootnoteBlock, vpos: int, ctx: _BuildCtx, _is_last: bool) -> BuildResult:
    """FootnoteBlock → 네이티브 CTRL_HEADER 'fn  ' + LIST_HEADER + 본문 단락."""
    ref_num = int(block.ref) if block.ref and block.ref.isdigit() else 1
    body_spans = _extract_text_from_blocks(block.content, ctx.cs_map) if block.content else [TextSpan("", 0)]
    return build_footnote(
        ref_num, body_spans, vpos,
        font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct,
        content_width=ctx.content_width,
    )


def _build_endnote_block(block: EndnoteBlock, vpos: int, ctx: _BuildCtx, _is_last: bool) -> BuildResult:
    """EndnoteBlock → 네이티브 CTRL_HEADER 'en  ' + LIST_HEADER + 본문 단락."""
    ref_num = int(block.ref) if block.ref and block.ref.isdigit() else 1
    body_spans = _extract_text_from_blocks(block.content, ctx.cs_map) if block.content else [TextSpan("", 0)]
    return build_endnote(
        ref_num, body_spans, vpos,
        font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct,
        content_width=ctx.content_width,
    )


def _build_field_block(block: FieldBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """FieldBlock → value 또는 inlines를 단락으로.

    clickhere 타입은 배경색으로 양식 필드를 시각 표시.
    """
    is_clickhere = block.field_type in ("clickhere", "click_here")

    if block.inlines:
        spans: list[TextSpan] = []
        for il in block.inlines:
            if isinstance(il, TextInline):
                if not il.text:
                    continue
                cs = _charshape_from_inline(il)
                if is_clickhere and cs.bg_color_r == 255 and cs.bg_color_g == 255 and cs.bg_color_b == 255:
                    cs = CharShapeSpec(
                        face_hangul=cs.face_hangul, face_latin=cs.face_latin,
                        size_pt=cs.size_pt, bold=cs.bold, italic=cs.italic,
                        underline=cs.underline, strikethrough=cs.strikethrough,
                        color_r=cs.color_r, color_g=cs.color_g, color_b=cs.color_b,
                        font_name=cs.font_name,
                        bg_color_r=230, bg_color_g=230, bg_color_b=230,
                    )
                ck = _charshape_key(cs)
                cs_id = ctx.cs_map.get(ck, 0)
                spans.append(TextSpan(il.text, cs_id))
            else:
                txt = _extract_inline_text(il)
                if txt:
                    spans.append(TextSpan(txt, 0))
        if not spans:
            spans = [TextSpan(block.value or "", 0)]
    else:
        text = block.value or ""
        if is_clickhere and text:
            cs = CharShapeSpec(
                size_pt=HWP_DEFAULTS["font_size_pt"],
                bg_color_r=230, bg_color_g=230, bg_color_b=230,
            )
            ck = _charshape_key(cs)
            cs_id = ctx.cs_map.get(ck, 0)
            spans = [TextSpan(text, cs_id)]
        else:
            spans = [TextSpan(text, 0)]
    return build_paragraph(
        spans, vpos=vpos,
        content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct, is_last=is_last,
    )


def _build_horizontal_rule(_block: HorizontalRuleBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """HorizontalRuleBlock → 빈 단락."""
    return build_paragraph(
        [TextSpan("", 0)], vpos=vpos,
        content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct, is_last=is_last,
    )


def _get_verbatim_section_bytes(doc: UdfDocument) -> bytes | None:
    """원본 verbatim section stream (Section0)을 디코딩하여 반환."""
    vl = getattr(doc, "verbatim", None)
    if not vl:
        return None
    section_streams = getattr(vl, "section_streams", None)
    if not section_streams:
        return None
    raw = section_streams.get("Section0")
    if not raw:
        return None
    if isinstance(raw, str):
        raw = base64.b64decode(raw)
    return raw


def _extract_aux_section_ctrls(doc: UdfDocument) -> tuple[bytes, bool]:
    """원본 verbatim section stream에서 dloc/pngp/onwn 보조 컨트롤을 추출.

    Returns
    -------
    tuple[bytes, bool]
        (ctrl records bytes, has_verbatim_dloc)
        has_verbatim_dloc이 True이면 seed의 dloc을 제거해야 함.
    """
    from udf.parsers.hwp.records import iter_records as _iter_recs, HWPTAG_CTRL_HEADER
    from udf.renderers.hwp.body_builder import _pack_record

    raw = _get_verbatim_section_bytes(doc)
    if not raw:
        return b"", False

    # dloc: seed와 다를 수 있으므로 verbatim에서 추출하여 seed 것을 교체
    # toof/daeh: _build_hf_ctrl_records()에서 처리
    _AUX_CTRL_IDS = {b"dloc", b"pngp", b"onwn"}
    result = b""
    has_dloc = False
    in_aux = False
    aux_level = 0
    for rec in _iter_recs(raw):
        if rec.tag_id == HWPTAG_CTRL_HEADER and rec.level == 1 and len(rec.payload) >= 4:
            cid = rec.payload[:4]
            if cid in _AUX_CTRL_IDS:
                in_aux = True
                aux_level = rec.level
                result += _pack_record(rec.tag_id, rec.level, rec.payload)
                if cid == b"dloc":
                    has_dloc = True
                continue
            else:
                in_aux = False
        elif rec.level <= 1 and in_aux:
            in_aux = False
        if in_aux and rec.level > aux_level:
            result += _pack_record(rec.tag_id, rec.level, rec.payload)

    return result, has_dloc


def _build_eq_trailing_map(doc: UdfDocument) -> dict[str, EqTrailing]:
    """verbatim section stream에서 모든 EQEDIT trailing 필드를 추출.

    두 가지 키로 인덱싱:
    - verbatim_ref (EquationBlock용)
    - "_script:{script_text}" (EquationInline용 — verbatim_ref가 없으므로 스크립트 텍스트로 매칭)
    """
    from udf.parsers.hwp.records import iter_records as _iter_recs

    raw = _get_verbatim_section_bytes(doc)
    if not raw:
        return {}

    vl = getattr(doc, "verbatim", None)

    # verbatim_ref → ph_offset 매핑 (EquationBlock용)
    offset_to_vref: dict[int, str] = {}
    if vl and hasattr(vl, "blocks") and vl.blocks:
        for block in doc.blocks:
            if block.type == "equation" and block.verbatim_ref:
                vb = vl.blocks.get(block.verbatim_ref)
                if vb and vb.decoded and "ph_offset" in vb.decoded:
                    offset_to_vref[vb.decoded["ph_offset"]] = block.verbatim_ref

    # 모든 EQEDIT 레코드를 파싱하여 trailing 추출 (스크립트 텍스트로도 인덱싱)
    result: dict[str, EqTrailing] = {}
    current_offset = 0
    pending_vref: str | None = None
    for rec in _iter_recs(raw):
        if rec.level == 0 and current_offset in offset_to_vref:
            pending_vref = offset_to_vref[current_offset]
        if rec.tag_id == 88:  # EQEDIT
            if len(rec.payload) >= 6:
                script_len = struct.unpack_from("<H", rec.payload, 4)[0]
                trailing_start = 6 + script_len * 2
                if trailing_start + 14 <= len(rec.payload):
                    script_bytes = rec.payload[6:6 + script_len * 2]
                    script_text = script_bytes.decode("utf-16-le", errors="replace")
                    bu = struct.unpack_from("<I", rec.payload, trailing_start)[0]
                    tc = struct.unpack_from("<I", rec.payload, trailing_start + 4)[0]
                    bl = struct.unpack_from("<H", rec.payload, trailing_start + 8)[0]
                    unk = struct.unpack_from("<H", rec.payload, trailing_start + 10)[0]
                    vlen = struct.unpack_from("<H", rec.payload, trailing_start + 12)[0]
                    tr = EqTrailing(
                        base_unit=bu, text_color=tc, base_line=bl,
                        unknown=unk, version_len=vlen,
                    )
                    if pending_vref:
                        result[pending_vref] = tr
                    # 스크립트 텍��트 기반 인덱싱 (inline equation 매칭용)
                    script_key = f"_script:{script_text}"
                    if script_key not in result:
                        result[script_key] = tr
            pending_vref = None
        elif rec.tag_id != 88:
            if rec.level == 0:
                pending_vref = None
        # Track byte offset for PH detection
        hdr_size = 4
        payload_size = len(rec.payload)
        if payload_size >= 0xFFF:
            hdr_size = 8
        current_offset += hdr_size + payload_size

    return result


def _build_hf_ctrl_records(block: HeaderBlock | FooterBlock, ctx: _BuildCtx) -> bytes:
    """HeaderBlock/FooterBlock → native CTRL_HEADER 'head'/'foot' records.

    These records are appended to the secd paragraph as children (level 1),
    not placed as standalone body paragraphs.
    """
    spans = _extract_text_from_blocks(block.content, ctx.cs_map)
    if not spans:
        spans = [TextSpan("", 0)]
    is_footer = isinstance(block, FooterBlock)
    return build_header_footer(
        spans,
        is_footer=is_footer,
        apply_to=block.apply_to or "all",
        level=1,
        font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct,
        content_width=ctx.content_width,
    )


def _build_image_block(block: ImageBlock, vpos: int, ctx: _BuildCtx, _is_last: bool) -> BuildResult | None:
    """ImageBlock → 네이티브 HWP GSO 이미지 (CTRL_HEADER 'gso ' + SHAPE_COMPONENT + PIC).

    이미지 데이터는 나중에 OLE 스트림으로 추가됨 (ctx.images에 참조 저장).
    """
    src = block.src
    if not src:
        ctx.losses.append(BlockLoss(
            block_id=block.id,
            loss_type=LossCategory.FORMAT_LIMIT,
            description="ImageBlock has no src",
        ))
        return None

    # 확장자 결정
    ext = _guess_ext_with_verbatim(src, ctx.doc)
    if not ext:
        ctx.losses.append(BlockLoss(
            block_id=block.id,
            loss_type=LossCategory.FORMAT_LIMIT,
            description=f"ImageBlock: unsupported or unknown image format: {src[:50]}",
        ))
        return None

    # 이미지 크기 (HWPUNIT)
    img_w = round((block.width or 200) * 100)   # pt → HWPUNIT
    img_h = round((block.height or 150) * 100)  # pt → HWPUNIT
    orig_w = img_w
    orig_h = img_h
    pos = block.position
    is_bg = pos and pos.flow == "back"
    if not is_bg and img_w > ctx.content_width:
        ratio = ctx.content_width / img_w
        img_w = ctx.content_width
        img_h = int(img_h * ratio)

    # BinData ID 할당
    bin_item_id = ctx.seed_bindata_count + len(ctx.images) + 1
    bin_data_id = bin_item_id

    ctx.images.append(_ImageRef(
        bin_item_id=bin_item_id,
        bin_data_id=bin_data_id,
        extension=ext,
        src=src,
    ))

    x_off = 0
    y_off = 0
    flow = None
    pos = block.position
    if pos and pos.x is not None:
        x_off = round(pos.x * 100)
    if pos and pos.y is not None:
        y_off = round(pos.y * 100)
    if pos:
        flow = pos.flow
        if not flow and pos.hrelto == "paper" and pos.vrelto == "paper":
            flow = "back"

    return build_image(
        bin_item_id, img_w, img_h, vpos,
        font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct,
        orig_width=orig_w,
        orig_height=orig_h,
        x_offset=x_off,
        y_offset=y_off,
        flow=flow,
        position=pos,
    )


def _guess_ext_with_verbatim(src: str, doc: UdfDocument | None) -> str | None:
    """확장자 추정 + verbatim bindata_streams fallback."""
    ext = _guess_image_ext(src)
    if not ext and src.startswith("bindata:") and doc is not None and getattr(doc, 'verbatim', None):
        key = src[len("bindata:"):]
        for skey in doc.verbatim.bindata_streams:
            bare = skey.rsplit(".", 1)[0]
            if bare == key and "." in skey:
                ext = _guess_image_ext(f"x.{skey.rsplit('.', 1)[-1]}")
                break
    return ext


def _guess_image_ext(src: str) -> str | None:
    """이미지 소스에서 확장자를 추정."""
    if src.startswith("data:"):
        mime = src.split(";")[0].split(":")[1] if ":" in src else ""
        ext_map = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
                   "image/bmp": "bmp", "image/tiff": "tif", "image/webp": "webp"}
        return ext_map.get(mime)
    ext = Path(src).suffix.lower().lstrip(".")
    if ext in ("jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "webp", "emf", "wmf"):
        return "jpg" if ext == "jpeg" else ("tif" if ext == "tiff" else ext)
    return None


def _read_image_data(src: str, doc: UdfDocument | None = None) -> bytes | None:
    """이미지 src에서 바이트 데이터를 읽는다."""
    if doc is not None:
        resolved = doc.resolve_image(src)
        if resolved is not None:
            return resolved
    if src.startswith("data:"):
        try:
            _, encoded = src.split(",", 1)
            return base64.b64decode(encoded)
        except Exception:
            return None
    if os.path.isfile(src):
        with open(src, "rb") as f:
            return f.read()
    return None


# Blocks that cannot be rendered — only report loss
_LOSS_ONLY_TYPES = {
    ChartBlock: "ChartBlock requires embedded chart data (not available in From Scratch)",
    TextArtBlock: "TextArtBlock requires WordArt rendering data (not available in From Scratch)",
    UnknownBlock: "UnknownBlock cannot be rendered",
}


_SKIP_TYPES = (BookmarkBlock, CommentBlock, HeaderBlock, FooterBlock)


# Builder function type: (block, vpos, ctx, is_last) -> (bytes, height)
_BLOCK_BUILDERS: dict[type, Any] = {
    ParagraphBlock: _build_para,
    HeadingBlock: _build_heading,
    TableBlock: _build_table_block,
    EquationBlock: _build_equation_block,
    PageBreakBlock: _build_page_break,
    ListBlock: _build_list_block,
    CodeBlock: _build_code_block,
    QuoteBlock: _build_quote_block,
    TextBoxBlock: _build_textbox_block,
    DrawingBlock: _build_drawing_block,
    FootnoteBlock: _build_footnote_block,
    EndnoteBlock: _build_endnote_block,
    FieldBlock: _build_field_block,
    HorizontalRuleBlock: _build_horizontal_rule,
    ImageBlock: _build_image_block,
}


def _dispatch_block(block: Block, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult | None:
    """블록 타입에 따라 적절한 빌더를 디스패치한다."""
    block_type = type(block)

    builder = _BLOCK_BUILDERS.get(block_type)
    if builder:
        return builder(block, vpos, ctx, is_last)

    if block_type in _LOSS_ONLY_TYPES:
        ctx.losses.append(BlockLoss(
            block_id=block.id,
            loss_type=LossCategory.FORMAT_LIMIT,
            description=_LOSS_ONLY_TYPES[block_type],
        ))
        return None

    if isinstance(block, _SKIP_TYPES):
        return None

    ctx.losses.append(BlockLoss(
        block_id=block.id,
        loss_type=LossCategory.FORMAT_LIMIT,
        description=f"Unknown block type: {block.type}",
    ))
    return None


_TBL_INLINE_CTRL = (
    struct.pack("<H", 0x000B)
    + b"\x20\x6c\x62\x74"
    + b"\x00" * 8
    + struct.pack("<H", 0x000B)
)


def _merge_tbl_into_prev_para(prev_bytes: bytes, tbl_bytes: bytes) -> bytes | None:
    """Merge table records into a preceding paragraph by injecting tbl inline ctrl.

    Strips the table's host PH/PT/PCS/PLS and injects the tbl inline control
    into the preceding paragraph's PT. Returns None if merge is not possible.
    """
    from udf.parsers.hwp.records import (
        iter_records as _ir, HWPTAG_PARA_HEADER as _PH,
        HWPTAG_PARA_TEXT as _PT, HWPTAG_CTRL_HEADER as _CH, HwpRecord,
    )
    prev_recs = list(_ir(prev_bytes))
    tbl_recs = list(_ir(tbl_bytes))
    if not prev_recs or prev_recs[0].tag_id != _PH:
        return None

    tbl_ctrl_start = None
    for ti, tr in enumerate(tbl_recs):
        if tr.tag_id == _CH:
            tbl_ctrl_start = ti
            break
    if tbl_ctrl_start is None:
        return None

    prev_ph = prev_recs[0]
    pt_idx = next((j for j in range(1, len(prev_recs))
                    if prev_recs[j].tag_id == _PT
                    and prev_recs[j].level == prev_ph.level + 1), None)
    if pt_idx is None:
        return None

    old_pt = prev_recs[pt_idx].payload
    if old_pt.endswith(b"\x0d\x00"):
        new_pt = old_pt[:-2] + _TBL_INLINE_CTRL + b"\x0d\x00"
    else:
        new_pt = old_pt + _TBL_INLINE_CTRL
    new_cc = len(new_pt) // 2

    ph_pay = bytearray(prev_ph.payload)
    old_dw = struct.unpack_from("<I", ph_pay, 0)[0]
    msb = old_dw & 0x80000000
    struct.pack_into("<I", ph_pay, 0, msb | (new_cc & 0x3FFFFFFF))
    if len(ph_pay) > 11:
        old_cm = struct.unpack_from("<I", ph_pay, 8)[0]
        struct.pack_into("<I", ph_pay, 8, old_cm | 0x00000800)

    from udf.renderers.hwp.body_writer import _serialize_record
    out = _serialize_record(HwpRecord(prev_ph.tag_id, prev_ph.level, bytes(ph_pay), 0))
    for j in range(1, len(prev_recs)):
        r = prev_recs[j]
        if j == pt_idx:
            out += _serialize_record(HwpRecord(r.tag_id, r.level, new_pt, 0))
        else:
            out += _serialize_record(r)

    base_level = prev_ph.level + 1
    for ti in range(tbl_ctrl_start, len(tbl_recs)):
        tr = tbl_recs[ti]
        delta = base_level - tbl_recs[tbl_ctrl_start].level
        out += _serialize_record(HwpRecord(tr.tag_id, tr.level + delta, tr.payload, 0))

    return out


def _promote_nested_tables(blocks: list[Block]) -> list[Block]:
    """Promote nested tables: when a table cell contains only a nested table, merge its rows."""
    result: list[Block] = []
    for blk in blocks:
        if not isinstance(blk, TableBlock):
            result.append(blk)
            continue
        promoted = _promote_table(blk)
        result.append(promoted)
    return result


def _promote_table(table: TableBlock) -> TableBlock:
    """Recursively promote nested tables within cells."""
    new_rows: list[Any] = []
    changed = False
    for row in table.rows:
        expanded_cells = False
        for cell in row.cells:
            if (len(cell.content) == 1
                    and isinstance(cell.content[0], TableBlock)
                    and (cell.col_span or 1) == 1
                    and len(row.cells) == 1):
                nested = _promote_table(cell.content[0])
                for nr in nested.rows:
                    new_rows.append(nr)
                expanded_cells = True
                changed = True
                break
        if not expanded_cells:
            new_rows.append(row)
    if not changed:
        return table
    return TableBlock(
        type="table",
        id=table.id,
        rows=new_rows,
        col_widths=table.col_widths,
        width=table.width,
        position=table.position,
        format=table.format,
        verbatim_ref=table.verbatim_ref,
    )


def _flatten_image_inlines(blocks: list[Block]) -> list[Block]:
    """Extract ImageInline from paragraphs into ImageBlocks placed right after the source paragraph."""
    counter_box: list[int] = [0]

    def _extract_from_block(blk: Block) -> list[ImageBlock]:
        imgs: list[ImageBlock] = []
        inlines = getattr(blk, "inlines", None)
        if inlines:
            img_inlines = [il for il in inlines if isinstance(il, ImageInline)]
            n_imgs = len(img_inlines)
            for il in img_inlines:
                counter_box[0] += 1
                w, h = il.width, il.height
                if n_imgs >= 2 and w and h:
                    scale = 1.0 / n_imgs
                    w = w * scale
                    h = h * scale
                imgs.append(ImageBlock(
                    type="image",
                    id=f"img_from_inline_{counter_box[0]}",
                    src=il.src,
                    width=w,
                    height=h,
                    alt=il.alt,
                    ))
        if isinstance(blk, TableBlock):
            pass
        else:
            content = getattr(blk, "content", None)
            if content and isinstance(content, list):
                for child in content:
                    imgs.extend(_extract_from_block(child))
        return imgs

    merged: list[Block] = []
    for blk in blocks:
        merged.append(blk)
        merged.extend(_extract_from_block(blk))
    return merged


def _has_tables(blocks: list[Block]) -> bool:
    """Check whether any block is a TableBlock."""
    for b in blocks:
        if isinstance(b, TableBlock):
            return True
    return False


def _collect_cell_bg_colors(blocks: list[Block]) -> list[tuple[int, int, int]]:
    """문서 블록에서 테이블 셀 배경색+테두리스타일을 재귀 수집."""
    colors: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()

    def _cell_border_type(fmt) -> int:
        if not fmt:
            return 1
        for side in ("top", "bottom", "left", "right"):
            bval = getattr(fmt, f"border_{side}", None)
            if bval:
                parts = bval.split()
                if len(parts) >= 2 and parts[1] != "solid":
                    return _BORDER_STYLE_TO_TYPE.get(parts[1], 1)
        return 1

    def _scan(block_list: list[Block]) -> None:
        for b in block_list:
            if isinstance(b, TableBlock):
                for row in b.rows:
                    for cell in row.cells:
                        fmt = getattr(cell, "format", None)
                        bg = getattr(fmt, "background_color", None) if fmt else None
                        bt = _cell_border_type(fmt)
                        if bg:
                            c = _parse_color(bg)
                            key = c
                            if key not in seen:
                                seen.add(key)
                                colors.append(c)
                        elif bt != 1:
                            # Non-solid border without bg — need separate BF
                            key = (0, 0, 0)
                            # Don't add duplicate (0,0,0) — handled by default BF
                        _scan(cell.content or [])
            elif isinstance(b, TextBoxBlock):
                _scan(b.content or [])
            elif isinstance(b, DrawingBlock):
                _scan(b.content or [])

    _scan(blocks)
    return colors


_BORDER_STYLE_TO_TYPE = {"solid": 1, "dashed": 2, "dotted": 3, "dash_dot": 4, "none": 0}


def _detect_table_border_type(blocks: list[Block]) -> int:
    """테이블에서 가장 많이 사용된 비-solid border style의 type 코드 반환."""
    from collections import Counter
    styles: Counter[str] = Counter()
    def _scan(block_list: list[Block]) -> None:
        for b in block_list:
            if isinstance(b, TableBlock):
                for row in b.rows:
                    for cell in row.cells:
                        fmt = getattr(cell, "format", None)
                        if not fmt:
                            continue
                        for side in ("top", "bottom", "left", "right"):
                            bval = getattr(fmt, f"border_{side}", None)
                            if bval:
                                parts = bval.split()
                                if len(parts) >= 2:
                                    styles[parts[1]] += 1
                        _scan(cell.content or [])
    _scan(blocks)
    if not styles:
        return 1
    most_common = styles.most_common(1)[0][0]
    return _BORDER_STYLE_TO_TYPE.get(most_common, 1)


def _patch_page_border_fill(section_bytes: bytes, bf_id: int) -> bytes:
    """Patch first PAGE_BORDER_FILL (tag 75) borderFillId in section bytes."""
    data = bytearray(section_bytes)
    i = 0
    while i < len(data) - 4:
        hdr = struct.unpack_from('<I', data, i)[0]
        tag = hdr & 0x3FF
        size = (hdr >> 20) & 0xFFF
        po = i + 4 if size < 0xFFF else i + 8
        if tag == 75 and size >= 14:
            struct.pack_into('<H', data, po + 12, bf_id)
            return bytes(data)
        next_i = po + (size if size < 0xFFF else struct.unpack_from('<I', data, i + 4)[0])
        if next_i <= i:
            break
        i = next_i
    return bytes(data)



def _inject_reference_con(output_path: str, reference_hwp: str) -> None:
    """Reference HWP의 $con 구조를 변환 결과에 주입."""
    import zlib
    from udf.parsers.hwp.ole import OleReader
    from udf.parsers.hwp.records import iter_records, HWPTAG_CTRL_HEADER, HWPTAG_PARA_HEADER
    from udf.renderers.hwp.body_builder import _pack_record

    with OleReader.open(reference_hwp) as ole:
        ref_sec = ole.read_stream(["BodyText", "Section0"])
    ref_recs = list(iter_records(ref_sec))

    ref_ctrl = next((i for i, r in enumerate(ref_recs)
                     if r.tag_id == HWPTAG_CTRL_HEADER and len(r.payload) >= 4
                     and r.payload[:4][::-1].decode("ascii", "replace").strip() == "gso"), None)
    if ref_ctrl is None:
        return

    con_records = b""
    ctrl_level = ref_recs[ref_ctrl].level
    for j in range(ref_ctrl, len(ref_recs)):
        if j > ref_ctrl and ref_recs[j].level <= ctrl_level:
            break
        con_records += _pack_record(ref_recs[j].tag_id, ref_recs[j].level, ref_recs[j].payload)

    with OleReader.open(output_path) as ole:
        conv_sec = ole.read_stream(["BodyText", "Section0"])
    conv_recs = list(iter_records(conv_sec))

    conv_ctrl = next((i for i, r in enumerate(conv_recs)
                      if r.tag_id == HWPTAG_CTRL_HEADER and len(r.payload) >= 4
                      and r.payload[:4][::-1].decode("ascii", "replace").strip() == "gso"), None)
    if conv_ctrl is None:
        return

    conv_ph = next(j for j in range(conv_ctrl - 1, -1, -1) if conv_recs[j].tag_id == HWPTAG_PARA_HEADER)
    conv_end = len(conv_recs)
    for j in range(conv_ctrl + 1, len(conv_recs)):
        if conv_recs[j].level <= conv_recs[conv_ph].level:
            conv_end = j
            break

    new_sec = b""
    for i, r in enumerate(conv_recs):
        if i < conv_ph:
            new_sec += _pack_record(r.tag_id, r.level, r.payload)
        elif i == conv_ph:
            for k in range(conv_ph, conv_ctrl):
                new_sec += _pack_record(conv_recs[k].tag_id, conv_recs[k].level, conv_recs[k].payload)
            new_sec += con_records
        elif i >= conv_end:
            new_sec += _pack_record(r.tag_id, r.level, r.payload)

    comp = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed = comp.compress(new_sec) + comp.flush()
    patch_hwp_stream(output_path, output_path, ["BodyText", "Section0"], compressed)


def generate_hwp_scratch(
    doc: UdfDocument,
    output_path: str,
    seed_path: str,
    reference_hwp: str | None = None,
    char_shapes: list[CharShapeSpec] | None = None,
    para_shapes: list[ParaShapeSpec] | None = None,
) -> LossReport | None:
    """Generate an HWP file from a UdfDocument using From Scratch mode.

    Copies the seed OLE container, then rebuilds and replaces the DocInfo
    and BodyText/Section0 streams based on the Document Model.

    Parameters
    ----------
    doc : UdfDocument
        The document model to render.
    output_path : str
        Destination path for the generated .hwp file.
    seed_path : str
        Path to the seed HWP file used as OLE container template.
    char_shapes : list[CharShapeSpec] or None
        Pre-collected CharShapes (auto-collected if None).
    para_shapes : list[ParaShapeSpec] or None
        Pre-collected ParaShapes (auto-collected if None).

    Returns
    -------
    LossReport or None
        Loss report if any blocks had lossy conversion, None otherwise.
    """
    # 0. ImageInline → ImageBlock 변환 (인라인 이미지를 별도 블록으로 분리)
    doc_blocks = _flatten_image_inlines(doc.blocks)

    # 1. OLE 컨테이너 복사
    shutil.copy2(seed_path, output_path)

    # 2. Document Model 스타일 수집 + seed 매칭
    seed_docinfo = _read_seed_docinfo(seed_path)
    seed_cs_list = read_seed_charshapes(seed_docinfo)
    seed_ps_list = read_seed_parashapes(seed_docinfo)

    from udf.parsers.hwp.records import HWPTAG_BIN_DATA, HWPTAG_NUMBERING as _TAG_NUM, iter_records as _iter_recs
    seed_bindata_docinfo = sum(1 for r in _iter_recs(seed_docinfo) if r.tag_id == HWPTAG_BIN_DATA)
    # OLE BinData 스트림 수도 확인 — DocInfo에 없는 orphaned 스트림과 충돌 방지
    _seed_ole_bindata = 0
    try:
        _shole = olefile.OleFileIO(seed_path)
        _seed_ole_bindata = sum(1 for s in _shole.listdir() if s[0] == "BinData")
        _shole.close()
    except Exception:
        pass
    seed_bindata_count = max(seed_bindata_docinfo, _seed_ole_bindata)
    seed_num_count = sum(1 for r in _iter_recs(seed_docinfo) if r.tag_id == _TAG_NUM)

    has_hwp_origin = getattr(doc, "source_format", None) == "hwp"
    if has_hwp_origin:
        default_ls_pct = HWP_DEFAULTS["line_spacing_pct"]
    else:
        from collections import Counter as _Counter
        _ls_counts: _Counter[int] = _Counter()
        for _b in _iter_all_text_blocks(doc_blocks):
            _fmt = getattr(_b, "format", None)
            if _fmt and _fmt.line_spacing and hasattr(_fmt.line_spacing, "percent"):
                _ls_counts[int(_fmt.line_spacing.percent)] += 1
        default_ls_pct = _ls_counts.most_common(1)[0][0] if _ls_counts else 100

    cs_list, ps_list, raw_cs_map, raw_ps_map = collect_shapes(doc, default_ls=default_ls_pct)

    # 2b. 리스트 블록 감지 → 네이티브 번호 매기기 준비
    has_ordered = any(isinstance(b, ListBlock) and b.ordered for b in doc_blocks)
    has_unordered = any(isinstance(b, ListBlock) and not b.ordered for b in doc_blocks)
    numbering_payloads: list[bytes] = []
    ordered_num_id = 0
    unordered_num_id = 0
    if has_ordered:
        numbering_payloads.append(pack_numbering(ordered=True))
        ordered_num_id = seed_num_count + len(numbering_payloads)
    if has_unordered:
        numbering_payloads.append(pack_numbering(ordered=False))
        unordered_num_id = seed_num_count + len(numbering_payloads)

    # 리스트용 ParaShape (들여쓰기 + numbering_id)
    list_indent = round(20 * 100)  # 20pt indent
    if has_ordered and ordered_num_id:
        ol_ps = ParaShapeSpec(alignment="justify", line_spacing=default_ls_pct,
                              indent_left=list_indent, numbering_id=ordered_num_id)
        pk = _parashape_key(ol_ps)
        if pk not in raw_ps_map:
            raw_ps_map[pk] = len(ps_list)
            ps_list.append(ol_ps)
    if has_unordered and unordered_num_id:
        ul_ps = ParaShapeSpec(alignment="justify", line_spacing=default_ls_pct,
                              indent_left=list_indent, numbering_id=unordered_num_id)
        pk = _parashape_key(ul_ps)
        if pk not in raw_ps_map:
            raw_ps_map[pk] = len(ps_list)
            ps_list.append(ul_ps)

    # seed에서 매칭되지 않는 CS/PS → 새 레코드로 DocInfo에 추가
    cs_map, new_cs_specs = _resolve_cs_ids(seed_cs_list, cs_list, raw_cs_map)
    ps_map, new_ps_specs = _resolve_ps_ids(seed_ps_list, ps_list, raw_ps_map)

    # 3. 페이지 배경 이미지 감지 (flow=back + A4 크기)
    page_bg_image: ImageBlock | None = None
    page_bg_bin_item_id: int | None = None
    _meta = getattr(doc, "metadata", None) if hasattr(doc, "metadata") else None
    _sec = (_meta.sections[0] if _meta and _meta.sections else None) if _meta else None
    _page_w = _sec.page_width if _sec and _sec.page_width else 595
    _page_h = _sec.page_height if _sec and _sec.page_height else 842
    for blk in doc_blocks:
        if isinstance(blk, ImageBlock) and getattr(blk, 'position', None):
            pos = blk.position
            if pos.flow == 'back' and blk.width and blk.height and blk.width > _page_w * 0.7 and blk.height > _page_h * 0.7:
                page_bg_image = blk
                break

    # 3b. 테이블 BorderFill 준비
    has_tbl = _has_tables(doc_blocks)
    table_bt = _detect_table_border_type(doc_blocks) if has_tbl else 1
    cell_bg_colors = _collect_cell_bg_colors(doc_blocks)
    extra_bf_specs: list[BorderFillSpec] = []
    for r, g, b in cell_bg_colors:
        extra_bf_specs.append(BorderFillSpec(
            has_borders=True, has_fill=True,
            fill_r=r, fill_g=g, fill_b=b,
        ))

    # 3c. 페이지 배경 이미지 — BF는 ctx.images에 등록 후 추가

    # 4. DocInfo 재빌드 (새 CS/PS/BF/NUMBERING 추가)
    new_docinfo, table_bf_id, _scs, _sps, *_ = build_docinfo(
        seed_docinfo, new_cs_specs, new_ps_specs,
        need_table_bf=has_tbl,
        table_border_type=table_bt,
        extra_border_fills=extra_bf_specs if extra_bf_specs else None,
        numbering_specs=numbering_payloads if numbering_payloads else None,
    )

    # table_bf_base_id: 기본 테이블 셀 BF (테두리 있음, 배경 없음)
    table_bf_base_id = table_bf_id if has_tbl else 3

    # 셀 배경색 → BF ID 매핑 (table_bf_id 다음부터)
    bf_map: dict[tuple, int] = {}
    for i, (r, g, b) in enumerate(cell_bg_colors):
        bf_map[(r, g, b)] = table_bf_base_id + 1 + i

    # 페이지 배경 BF ID (extra_bf_specs의 마지막)
    page_bg_bf_id_val: int | None = None

    # DocInfo 무결성 검증 (패치 전에)
    from udf.validation.hwp.integrity import validate_hwp_integrity
    violations = validate_hwp_integrity(new_docinfo)
    if violations:
        msgs = "; ".join(v.message for v in violations)
        raise ScratchError(f"DocInfo integrity check failed: {msgs}")

    # DocInfo 패치 (BodyText 생성 전에)
    compressed_di = _compress(new_docinfo)
    patch_hwp_stream(output_path, output_path, ["DocInfo"], compressed_di)

    # 5. BodyText 재빌드
    with OleReader.open(seed_path) as ole:
        seed_section = ole.read_stream(["BodyText", "Section0"])

    page_meta = _build_page_meta(doc.metadata)

    seed_dims = _read_seed_page_dims(seed_section)
    pm = page_meta or seed_dims
    content_width = (
        pm.get("page_width", seed_dims["page_width"])
        - pm.get("margin_left", seed_dims["margin_left"])
        - pm.get("margin_right", seed_dims["margin_right"])
    )
    default_font_hu = round(HWP_DEFAULTS["font_size_pt"] * 100)
    # default_ls_pct already computed above (before collect_shapes)

    # 리스트용 ParaShape ID 해석
    _ol_ps_id = 0
    _ul_ps_id = 0
    if has_ordered and ordered_num_id:
        ol_ps = ParaShapeSpec(alignment="justify", line_spacing=default_ls_pct,
                              indent_left=list_indent, numbering_id=ordered_num_id)
        _ol_ps_id = ps_map.get(_parashape_key(ol_ps), 0)
    if has_unordered and unordered_num_id:
        ul_ps = ParaShapeSpec(alignment="justify", line_spacing=default_ls_pct,
                              indent_left=list_indent, numbering_id=unordered_num_id)
        _ul_ps_id = ps_map.get(_parashape_key(ul_ps), 0)

    losses: list[BlockLoss] = []
    eq_trailing = _build_eq_trailing_map(doc)
    ctx = _BuildCtx(
        cs_map=cs_map, ps_map=ps_map,
        content_width=content_width,
        font_size_hu=default_font_hu,
        line_spacing_pct=default_ls_pct,
        seed_dims=seed_dims,
        page_meta=page_meta,
        losses=losses,
        seed_bindata_count=seed_bindata_count,
        table_bf_base_id=table_bf_base_id,
        bf_map=bf_map,
        ordered_list_ps_id=_ol_ps_id,
        unordered_list_ps_id=_ul_ps_id,
        doc=doc,
        has_page_bg_image=page_bg_image is not None,
        eq_trailing_map=eq_trailing,
    )

    # 첫 텍스트 블록을 secd 단락에 병합 (GAP-1 수정: 원본은 secd+텍스트 동시 보유)
    # 단, 첫 블록이 테이블 등 비텍스트이면 빈 secd를 생성하고 순서를 보존한다.
    first_block_idx = -1
    first_text = ""
    first_cs_id = 0
    first_ps_id: int | None = None
    first_style_id: int | None = None
    first_ls_pct = default_ls_pct
    for i, block in enumerate(doc_blocks):
        if isinstance(block, ParagraphBlock):
            spans = _spans_for_paragraph(block, cs_map)
            first_text = "".join(s.text for s in spans)
            first_cs_id = spans[0].cs_id if spans else 0
            ps = _parashape_from_block(block, default_ls=default_ls_pct)
            pk = _parashape_key(ps)
            first_ps_id = ps_map.get(pk)
            first_ls_pct = ps.line_spacing
            first_block_idx = i
            break
        elif isinstance(block, HeadingBlock):
            level = max(1, min(block.level, 6))
            heading_size = _HEADING_SIZE_PT[level]
            first_style_id = _STYLE_HEADING[level - 1]
            inlines = getattr(block, "inlines", None)
            if inlines:
                spans = _spans_for_paragraph_heading(
                    type("_P", (), {"inlines": inlines})(),  # type: ignore[arg-type]
                    cs_map, heading_size,
                )
                unique_cs = set(s.cs_id for s in spans if s.text)
                if len(unique_cs) > 1:
                    first_style_id = None
                    break
                first_cs_id = spans[0].cs_id if spans else 0
                first_text = "".join(s.text for s in spans)
            else:
                cs = CharShapeSpec(size_pt=heading_size, bold=True)
                ck = _charshape_key(cs)
                first_cs_id = cs_map.get(ck, 0)
                first_text = block.text
            ps = _parashape_from_block(block, default_ls=default_ls_pct)
            pk = _parashape_key(ps)
            first_ps_id = ps_map.get(pk)
            first_ls_pct = ps.line_spacing
            first_block_idx = i
            break
    # If non-text blocks precede the first text block, use empty secd to preserve order
    if first_block_idx > 0:
        first_text = ""
        first_cs_id = 0
        first_ps_id = None
        first_style_id = None
        first_ls_pct = default_ls_pct
        first_block_idx = -1

    hf_inline_anchors: list[bytes] = []
    for block in doc_blocks:
        if isinstance(block, (HeaderBlock, FooterBlock)):
            hf_inline_anchors.append(
                build_hf_inline_anchor(is_footer=isinstance(block, FooterBlock))
            )

    first_block_pls: bytes | None = None
    if first_block_idx >= 0:
        first_block_pls = _get_original_pls(doc_blocks[first_block_idx], ctx)

    # 보조 섹션 컨트롤 (dloc/pngp/onwn) — 원본 verbatim에서 추출
    aux_ctrls, has_verbatim_dloc = _extract_aux_section_ctrls(doc)

    secd_prefix = build_secd_paragraph(
        seed_section, page_meta=page_meta,
        text=first_text, cs_id=first_cs_id,
        ps_id_override=first_ps_id,
        style_id_override=first_style_id,
        dist=content_width, line_spacing_pct=first_ls_pct,
        extra_inline_ctrls=hf_inline_anchors or None,
        page_bg_bf_id=None,
        original_pls=first_block_pls,
        skip_seed_dloc=has_verbatim_dloc,
    )

    secd_prefix += aux_ctrls

    for block in doc_blocks:
        if isinstance(block, (HeaderBlock, FooterBlock)):
            secd_prefix += _build_hf_ctrl_records(block, ctx)


    para_records: list[bytes] = []
    current_vpos = _EFFECTIVE_PARA_HEIGHT  # secd 단락이 vpos=0 을 차지

    # 종결 단락 전략: 복합 블록이 마지막이면 별도 term 추가, 아니면 마지막 단락에 MSB
    # (빈 ParagraphBlock은 _build_para가 처리 — verbatim PLS 보존을 위해 스킵하지 않음)
    last_block_idx = -1
    need_term = False

    # 마지막으로 생성될 블록 인덱스 계산 (is_last 마킹용)
    last_effective_idx = -1
    last_effective_block: Block | None = None
    for idx in range(len(doc_blocks) - 1, -1, -1):
        if idx != first_block_idx:
            last_effective_idx = idx
            last_effective_block = doc_blocks[idx]
            break

    # 복합 블록(테이블/각주/미주/수식/이미지)이 마지막이면 종결 단락 필요
    # (MSB를 host PH에 설정하면 한컴이 CTRL 자식을 무시하고 손상 판정)
    _COMPOUND_TYPES = (TableBlock, FootnoteBlock, EndnoteBlock, EquationBlock, ImageBlock)
    if last_effective_block and isinstance(last_effective_block, _COMPOUND_TYPES):
        need_term = True


    pending_page_break = False
    for i, block in enumerate(doc_blocks):
        if i == first_block_idx or i == last_block_idx:
            continue

        if isinstance(block, PageBreakBlock):
            pending_page_break = True

        is_last_para = (not need_term and i == last_effective_idx)

        blk_fmt = getattr(block, "format", None)
        if pending_page_break and not isinstance(block, PageBreakBlock):
            if isinstance(block, (ParagraphBlock, HeadingBlock)):
                if blk_fmt is None:
                    from udf.schema.formats import BlockFormat
                    block.format = BlockFormat(page_break_before=True)
                elif not blk_fmt.page_break_before:
                    blk_fmt.page_break_before = True
            pending_page_break = False

        if blk_fmt and blk_fmt.space_before:
            current_vpos += pt_to_hwpunit(blk_fmt.space_before)

        if (isinstance(block, TableBlock)
                and para_records
                and isinstance(doc_blocks[i - 1] if i > 0 else None, (ParagraphBlock, HeadingBlock))):
            result = _build_table_block(block, current_vpos, ctx, False)
            if result:
                tbl_rec, tbl_h = result
                merged = _merge_tbl_into_prev_para(para_records[-1], tbl_rec)
                if merged is not None:
                    para_records[-1] = merged
                    current_vpos += tbl_h
                    if blk_fmt and blk_fmt.space_after:
                        current_vpos += pt_to_hwpunit(blk_fmt.space_after)
                    continue
                para_records.append(tbl_rec)
                current_vpos += tbl_h
                if blk_fmt and blk_fmt.space_after:
                    current_vpos += pt_to_hwpunit(blk_fmt.space_after)
        else:
            result = _dispatch_block(block, current_vpos, ctx, is_last_para)
            if result:
                rec, height = result
                if rec:
                    para_records.append(rec)
                current_vpos += height
                if blk_fmt and blk_fmt.space_after:
                    current_vpos += pt_to_hwpunit(blk_fmt.space_after)

    if need_term:
        section_bytes = secd_prefix + build_section(para_records, term_vpos=current_vpos)
    elif not para_records:
        section_bytes = secd_prefix + build_term_paragraph(vpos=current_vpos)
    else:
        section_bytes = secd_prefix + b"".join(para_records)
    section_bytes = _ensure_last_para_msb(section_bytes)
    from udf.validation.hwp.integrity import check_i4_con_children
    _i4 = check_i4_con_children(section_bytes)
    if _i4:
        import warnings
        warnings.warn(f"I4: {'; '.join(v.message for v in _i4)}", stacklevel=2)

    # 페이지 배경: ctx.images에서 bg 이미지 bin_item_id 확인
    pg_bg_bid: int | None = None
    if page_bg_image:
        for img_ref in ctx.images:
            if img_ref.src == page_bg_image.src:
                pg_bg_bid = img_ref.bin_item_id
                break
    # 페이지 배경 BF ID 예측: extra_bf_specs 마지막에 추가될 것
    if pg_bg_bid:
        page_bg_bf_id_val = table_bf_base_id + 1 + len(cell_bg_colors)
        section_bytes = _patch_page_border_fill(section_bytes, page_bg_bf_id_val)

    compressed = _compress(section_bytes)
    patch_hwp_stream(output_path, output_path, ["BodyText", "Section0"], compressed)
    # Reference HWP $con injection
    if reference_hwp and page_bg_image:
        try:
            _inject_reference_con(output_path, reference_hwp)
        except Exception:
            pass  # Fallback to existing rendering

    if ctx.images:
        actual_bg_bf_id = _embed_images(
            output_path, seed_path, ctx, new_cs_specs, new_ps_specs,
            has_tbl, extra_bf_specs, doc=doc,
            numbering_specs=numbering_payloads if numbering_payloads else None,
            page_bg_bin_item_id=pg_bg_bid,
        )
        if actual_bg_bf_id:
            raw = olefile.OleFileIO(output_path).openstream('BodyText/Section0').read()
            sec = bytearray(zlib.decompress(raw, -15))
            sec = bytearray(_patch_page_border_fill(bytes(sec), actual_bg_bf_id))
            patch_hwp_stream(output_path, output_path, ["BodyText", "Section0"], _compress(bytes(sec)))

    if losses:
        return LossReport(
            total_blocks=len(doc_blocks),
            lossless_blocks=len(doc_blocks) - len(losses),
            lossy_blocks=losses,
            is_roundtrip_safe=False,
        )
    return None


def _embed_images(
    output_path: str,
    seed_path: str,
    ctx: _BuildCtx,
    new_cs_specs: list[CharShapeSpec],
    new_ps_specs: list[ParaShapeSpec],
    has_tbl: bool,
    extra_bf_specs: list[BorderFillSpec],
    doc: UdfDocument | None = None,
    numbering_specs: list[bytes] | None = None,
    page_bg_bin_item_id: int | None = None,
) -> int | None:
    """이미지 BIN_DATA를 DocInfo에 추가하고 OLE 스트림에 이미지 데이터를 기록."""
    bin_specs: list[BinDataSpec] = []
    valid_images: list[tuple[_ImageRef, bytes]] = []

    for img_ref in ctx.images:
        data = _read_image_data(img_ref.src, doc=doc)
        if data is None:
            ctx.losses.append(BlockLoss(
                block_id="",
                loss_type=LossCategory.FORMAT_LIMIT,
                description=f"Image data not found: {img_ref.src[:80]}",
            ))
            continue
        bin_specs.append(BinDataSpec(
            bin_data_id=img_ref.bin_data_id,
            extension=img_ref.extension,
        ))
        valid_images.append((img_ref, data))

    if not valid_images:
        return

    # 페이지 배경 이미지 BF 추가 (BinData가 확정된 후)
    bf_specs = list(extra_bf_specs) if extra_bf_specs else []
    # Add border-type BFs from bf_map (dashed/dotted cells)
    for bf_key in sorted(ctx.bf_map.keys()):
        if len(bf_key) == 7:  # (r, g, b, bt_l, bt_r, bt_t, bt_b)
            r, g, b, bt_l, bt_r, bt_t, bt_b = bf_key
            has_custom_border = (bt_l, bt_r, bt_t, bt_b) != (1, 1, 1, 1)
            has_fill = (r, g, b) != (0, 0, 0)
            if has_custom_border or has_fill:
                bf_specs.append(BorderFillSpec(
                    has_borders=True,
                    border_type_left=bt_l, border_type_right=bt_r,
                    border_type_top=bt_t, border_type_bottom=bt_b,
                    has_fill=has_fill,
                    fill_r=r, fill_g=g, fill_b=b,
                ))
    if page_bg_bin_item_id:
        bf_specs.append(BorderFillSpec(
            has_borders=False, has_image_fill=True,
            image_fill_bin_item_id=page_bg_bin_item_id,
            image_fill_mode=1,
        ))

    # DocInfo 재빌드 (기존 CS/PS/BF + BIN_DATA 추가)
    # seed OLE에 orphaned BinData 스트림이 있으면 dummy BIN_DATA 레코드를 먼저 추가
    # (Hancom은 binItemId로 BIN_DATA 배열을 인덱싱하므로 인덱스가 일치해야 함)
    seed_docinfo = _read_seed_docinfo(seed_path)
    _orphan_specs: list[BinDataSpec] = []
    try:
        from udf.parsers.hwp.records import iter_records as _ir, HWPTAG_BIN_DATA as _BD_TAG
        _ole_check = olefile.OleFileIO(output_path)
        _ole_bins = sorted(
            s[-1] for s in _ole_check.listdir() if s[0] == "BinData"
        )
        _ole_check.close()
        _n_docinfo_bd = sum(
            1 for r in _ir(seed_docinfo) if r.tag_id == _BD_TAG
        )
        for _bn in _ole_bins:
            if _n_docinfo_bd >= ctx.seed_bindata_count:
                break
            _ext = _bn.rsplit(".", 1)[-1] if "." in _bn else "jpg"
            _idx = _n_docinfo_bd + 1
            _orphan_specs.append(BinDataSpec(bin_data_id=_idx, extension=_ext))
            _n_docinfo_bd += 1
    except Exception:
        pass
    all_bin_specs = _orphan_specs + bin_specs

    new_docinfo, _, _, _, *_ = build_docinfo(
        seed_docinfo, new_cs_specs, new_ps_specs,
        need_table_bf=has_tbl,
        bin_data_specs=all_bin_specs,
        extra_border_fills=bf_specs if bf_specs else None,
        numbering_specs=numbering_specs,
    )
    from udf.validation.hwp.integrity import validate_hwp_integrity
    violations = validate_hwp_integrity(new_docinfo)
    if violations:
        msgs = "; ".join(v.message for v in violations)
        raise ScratchError(f"DocInfo integrity check failed (images): {msgs}")
    compressed_di = _compress(new_docinfo)
    patch_hwp_stream(output_path, output_path, ["DocInfo"], compressed_di)

    # OLE 스트림에 이미지 데이터 추가 (BinData는 비압축 저장 — Hancom이 원본 바이트를 직접 읽음)
    for img_ref, data in valid_images:
        stream_name = f"BIN{img_ref.bin_data_id:04X}.{img_ref.extension}"
        add_hwp_stream(output_path, ["BinData", stream_name], data)

    # 이미지 fill BF가 추가된 경우 — DocInfo에서 총 BF 수를 세서 마지막 ID 반환
    if page_bg_bin_item_id:
        i = 0
        bf_count = 0
        while i < len(new_docinfo) - 4:
            h = struct.unpack_from('<I', new_docinfo, i)[0]
            t = h & 0x3FF
            s = (h >> 20) & 0xFFF
            po = i + 4 if s < 0xFFF else i + 8
            if t == 20:  # HWPTAG_BORDER_FILL
                bf_count += 1
            next_i = po + (s if s < 0xFFF else struct.unpack_from('<I', new_docinfo, i + 4)[0])
            if next_i <= i:
                break
            i = next_i
        return bf_count
    return None
