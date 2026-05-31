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
        spec.line_spacing_type, spec.keep_with_next,
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
        ls_val = int(ls.percent)
    elif isinstance(ls, (int, float)):
        ls_val = float(ls)
    elif isinstance(ls, str) and ls.endswith("%"):
        ls_val = int(ls.rstrip("%"))
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
        keep_with_next=fmt.keep_with_next or False,
        widow_orphan=fmt.widow_orphan or False,
        page_break_before=fmt.page_break_before or False,
    )


def _iter_all_text_blocks(blocks: list[Block]) -> Iterator[ParagraphBlock | HeadingBlock]:
    """Yield all ParagraphBlock/HeadingBlock recursively (including table cells)."""
    for block in blocks:
        if isinstance(block, (ParagraphBlock, HeadingBlock)):
            yield block
        elif isinstance(block, TableBlock):
            for row in block.rows:
                for cell in row.cells:
                    yield from _iter_all_text_blocks(cell.content)


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

    for key, idx in cs_map.items():
        if key in seed_keys:
            final_map[key] = seed_keys[key]
        else:
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
        return int(val * 100)  # pt → HWPUNIT
    if not isinstance(val, str) or not val.strip():
        return default
    v = val.strip()
    try:
        if v.endswith("mm"):
            return int(float(v[:-2]) * 283.46)  # 1mm ≈ 283.46 HWPUNIT
        if v.endswith("cm"):
            return int(float(v[:-2]) * 2834.6)
        if v.endswith("pt"):
            return int(float(v[:-2]) * 100)  # 1pt = 100 HWPUNIT
        return int(float(v))
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
    unordered_list_ps_id: int = 0


def _extract_text_from_blocks(blocks: list[Block], cs_map: dict[tuple, int]) -> list[TextSpan]:
    """블록 리스트에서 텍스트를 추출하여 TextSpan 리스트로 반환."""
    spans: list[TextSpan] = []
    for block in blocks:
        if isinstance(block, ParagraphBlock):
            s = _spans_for_paragraph(block, cs_map)
            if s and s != [TextSpan("", 0)]:
                spans.extend(s)
        elif isinstance(block, HeadingBlock):
            spans.append(TextSpan(block.text, 0))
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
    return build_paragraph(
        spans, ps_id=ps_id, style_id=style_id, vpos=vpos,
        content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct, is_last=is_last,
    )


def _build_para(block: ParagraphBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """Build records for a ParagraphBlock."""
    ps = _parashape_from_block(block, default_ls=ctx.line_spacing_pct)
    pk = _parashape_key(ps)
    ps_id = ctx.ps_map.get(pk, 0)
    spans = _spans_for_paragraph(block, ctx.cs_map)
    ls_pct = ctx.line_spacing_pct
    fmt = getattr(block, "format", None)
    if fmt and fmt.line_spacing is not None:
        if hasattr(fmt.line_spacing, "percent"):
            ls_pct = int(fmt.line_spacing.percent)
        elif isinstance(fmt.line_spacing, (int, float)):
            ls_type = getattr(fmt, "line_spacing_type", None)
            if ls_type in ("fixed", "leading_only", "minimum"):
                font_pt = ctx.font_size_hu / 100
                ls_pct = max(100, int(fmt.line_spacing / font_pt * 100)) if font_pt > 0 else 100
            else:
                ls_pct = int(fmt.line_spacing)
    return build_paragraph(
        spans, ps_id=ps_id, style_id=_STYLE_NORMAL, vpos=vpos,
        content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ls_pct, is_last=is_last,
    )


def _compute_logical_cols(rows: list) -> int:
    """Compute the logical column count accounting for col_span."""
    max_cols = 0
    for row in rows:
        total = sum(getattr(c, "col_span", 1) or 1 for c in row.cells)
        max_cols = max(max_cols, total)
    return max(max_cols, 1)


def _compute_col_widths_merged(rows: list, n_cols: int) -> list[int] | None:
    """Derive per-column widths from cells with col_span=1."""
    widths: list[int | None] = [None] * n_cols
    for row in rows:
        logical_ci = 0
        for cell in row.cells:
            cs = getattr(cell, "col_span", 1) or 1
            w = getattr(cell, "width", None)
            if cs == 1 and w and w > 0 and logical_ci < n_cols:
                w_hu = int(w * 100)
                if widths[logical_ci] is None or w_hu > 0:
                    widths[logical_ci] = w_hu
            logical_ci += cs
    if all(w is not None and w > 0 for w in widths):
        return [w for w in widths]  # type: ignore[misc]
    return None


def _build_table_block(block: TableBlock, vpos: int, ctx: _BuildCtx, _is_last: bool) -> BuildResult:
    """Build records for a TableBlock with cell content."""
    cell_texts: list[list[list[TextSpan]]] = []
    cell_bf_ids: list[list[int]] = []
    cell_ps_ids: list[list[int]] = []
    cell_merges: list[list[tuple[int, int]]] = []
    cell_images: list[list[list[CellImageInfo]]] = []
    has_merges = False
    has_cell_images = False
    for row in block.rows:
        row_spans: list[list[TextSpan]] = []
        row_bfs: list[int] = []
        row_ps: list[int] = []
        row_merges: list[tuple[int, int]] = []
        row_imgs: list[list[CellImageInfo]] = []
        for cell in row.cells:
            spans = _extract_text_from_blocks(cell.content, ctx.cs_map)
            row_spans.append(spans)

            # Collect ImageBlock/ImageInline from cell content
            imgs: list[CellImageInfo] = []
            for cb in cell.content:
                if isinstance(cb, ImageBlock) and cb.src:
                    ext = _guess_image_ext(cb.src)
                    if ext:
                        img_w = int((cb.width or 200) * 100)
                        img_h = int((cb.height or 150) * 100)
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
                            ext = _guess_image_ext(il.src)
                            if ext:
                                img_w = int((il.width or 200) * 100)
                                img_h = int((il.height or 150) * 100)
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
            if bg_color:
                r, g, b = _parse_color(bg_color)
                bf_key = (r, g, b)
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
        cell_texts.append(row_spans)
        cell_bf_ids.append(row_bfs)
        cell_ps_ids.append(row_ps)
        cell_merges.append(row_merges)
        cell_images.append(row_imgs)
    n_rows = len(block.rows)
    n_cols = _compute_logical_cols(block.rows) if has_merges else max((len(r.cells) for r in block.rows), default=1)
    from collections import Counter as _Ctr
    _cell_ls: _Ctr[int] = _Ctr()
    for row in block.rows:
        for cell in row.cells:
            for cb in cell.content:
                _cf = getattr(cb, "format", None)
                if _cf and _cf.line_spacing and hasattr(_cf.line_spacing, "percent"):
                    _cell_ls[int(_cf.line_spacing.percent)] += 1
    tbl_ls = _cell_ls.most_common(1)[0][0] if _cell_ls else ctx.line_spacing_pct
    col_widths: list[int] | None = None
    if block.rows:
        if has_merges:
            col_widths = _compute_col_widths_merged(block.rows, n_cols)
        else:
            first_row_widths = [int((c.width or 0) * 100) for c in block.rows[0].cells]
            if all(w > 0 for w in first_row_widths) and len(first_row_widths) == n_cols:
                col_widths = first_row_widths
    if col_widths:
        total = sum(col_widths)
        if total > ctx.content_width:
            scale = ctx.content_width / total
            col_widths = [max(1, int(w * scale)) for w in col_widths]
    return build_table(
        n_rows, n_cols, cell_texts, ctx.content_width, vpos,
        col_widths=col_widths,
        font_size_hu=ctx.font_size_hu, line_spacing_pct=tbl_ls,
        bf_id=ctx.table_bf_base_id,
        cell_bf_ids=cell_bf_ids,
        cell_ps_ids=cell_ps_ids,
        cell_merges=cell_merges if has_merges else None,
        cell_images=cell_images if has_cell_images else None,
    )


def _build_equation_block(block: EquationBlock, vpos: int, ctx: _BuildCtx, _is_last: bool) -> BuildResult:
    """Build records for an EquationBlock."""
    script = getattr(block, "hwp_script", None) or getattr(block, "latex", "") or ""
    return build_equation(
        script, vpos,
        font_size_hu=ctx.font_size_hu, line_spacing_pct=ctx.line_spacing_pct,
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


def _build_textbox_block(block: TextBoxBlock, vpos: int, ctx: _BuildCtx, is_last: bool) -> BuildResult:
    """TextBoxBlock → GSO textbox shape if has visual properties, else flat paragraphs."""
    content_bytes = b""
    content_height = 0
    for idx, cb in enumerate(block.content):
        is_final = is_last and idx == len(block.content) - 1
        result = _dispatch_block(cb, vpos + content_height, ctx, is_final)
        if result:
            rec, h = result
            content_bytes += rec
            content_height += h
    if not block.content:
        return build_paragraph(
            [TextSpan("", 0)], vpos=vpos,
            content_width=ctx.content_width, font_size_hu=ctx.font_size_hu,
            line_spacing_pct=ctx.line_spacing_pct, is_last=is_last,
        )
    # GSO textbox shape disabled — binary structure causes Hancom corruption.
    # Render content as flat paragraphs (loses background/border visual fidelity).
    return content_bytes, content_height


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
    ext = _guess_image_ext(src)
    if not ext:
        ctx.losses.append(BlockLoss(
            block_id=block.id,
            loss_type=LossCategory.FORMAT_LIMIT,
            description=f"ImageBlock: unsupported or unknown image format: {src[:50]}",
        ))
        return None

    # 이미지 크기 (HWPUNIT)
    img_w = int((block.width or 200) * 100)   # pt → HWPUNIT
    img_h = int((block.height or 150) * 100)  # pt → HWPUNIT
    if img_w > ctx.content_width:
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

    return build_image(
        bin_item_id, img_w, img_h, vpos,
        font_size_hu=ctx.font_size_hu,
        line_spacing_pct=ctx.line_spacing_pct,
    )


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
        if not isinstance(blk, TableBlock):
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
    """문서 블록에서 테이블 셀 배경색을 수집."""
    colors: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for b in blocks:
        if not isinstance(b, TableBlock):
            continue
        for row in b.rows:
            for cell in row.cells:
                fmt = getattr(cell, "format", None)
                bg = getattr(fmt, "background_color", None) if fmt else None
                if bg:
                    c = _parse_color(bg)
                    if c not in seen:
                        seen.add(c)
                        colors.append(c)
    return colors


def generate_hwp_scratch(
    doc: UdfDocument,
    output_path: str,
    seed_path: str,
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
    seed_bindata_count = sum(1 for r in _iter_recs(seed_docinfo) if r.tag_id == HWPTAG_BIN_DATA)
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
    list_indent = int(20 * 100)  # 20pt indent
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

    # 3. 테이블 BorderFill 준비
    has_tbl = _has_tables(doc_blocks)
    cell_bg_colors = _collect_cell_bg_colors(doc_blocks)
    extra_bf_specs: list[BorderFillSpec] = []
    for r, g, b in cell_bg_colors:
        extra_bf_specs.append(BorderFillSpec(
            has_borders=True, has_fill=True,
            fill_r=r, fill_g=g, fill_b=b,
        ))

    # 4. DocInfo 재빌드 (새 CS/PS/BF/NUMBERING 추가)
    new_docinfo, table_bf_id, _scs, _sps, *_ = build_docinfo(
        seed_docinfo, new_cs_specs, new_ps_specs,
        need_table_bf=has_tbl,
        extra_border_fills=extra_bf_specs if extra_bf_specs else None,
        numbering_specs=numbering_payloads if numbering_payloads else None,
    )

    # table_bf_base_id: 기본 테이블 셀 BF (테두리 있음, 배경 없음)
    table_bf_base_id = table_bf_id if has_tbl else 3

    # 셀 배경색 → BF ID 매핑 (table_bf_id 다음부터)
    bf_map: dict[tuple, int] = {}
    for i, (r, g, b) in enumerate(cell_bg_colors):
        bf_map[(r, g, b)] = table_bf_base_id + 1 + i

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
    default_font_hu = int(HWP_DEFAULTS["font_size_pt"] * 100)
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
    )

    # 첫 텍스트 블록을 secd 단락에 병합 (GAP-1 수정: 원본은 secd+텍스트 동시 보유)
    # 단, 첫 블록이 테이블 등 비텍스트이면 빈 secd를 생성하고 순서를 보존한다.
    first_block_idx = -1
    first_text = ""
    first_cs_id = 0
    first_ps_id: int | None = None
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
            first_text = block.text
            inlines = getattr(block, "inlines", None)
            if inlines:
                spans = _spans_for_paragraph(
                    type("_P", (), {"inlines": inlines})(),  # type: ignore[arg-type]
                    cs_map,
                )
                first_cs_id = spans[0].cs_id if spans else 0
            else:
                cs = CharShapeSpec(size_pt=HWP_DEFAULTS["font_size_pt"], bold=True)
                ck = _charshape_key(cs)
                first_cs_id = cs_map.get(ck, 0)
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
        first_ls_pct = default_ls_pct
        first_block_idx = -1

    hf_inline_anchors: list[bytes] = []
    for block in doc_blocks:
        if isinstance(block, (HeaderBlock, FooterBlock)):
            hf_inline_anchors.append(
                build_hf_inline_anchor(is_footer=isinstance(block, FooterBlock))
            )

    secd_prefix = build_secd_paragraph(
        seed_section, page_meta=page_meta,
        text=first_text, cs_id=first_cs_id,
        ps_id_override=first_ps_id,
        dist=content_width, line_spacing_pct=first_ls_pct,
        extra_inline_ctrls=hf_inline_anchors or None,
    )

    for block in doc_blocks:
        if isinstance(block, (HeaderBlock, FooterBlock)):
            secd_prefix += _build_hf_ctrl_records(block, ctx)

    para_records: list[bytes] = []
    current_vpos = _EFFECTIVE_PARA_HEIGHT  # secd 단락이 vpos=0 을 차지

    # 종결 단락 전략: 마지막 빈 블록이 있으면 별도 term 추가, 없으면 마지막 단락에 MSB
    last_block_idx = -1
    need_term = False
    if doc_blocks:
        lb = doc_blocks[-1]
        if isinstance(lb, ParagraphBlock) and not any(
            _extract_inline_text(il) for il in lb.inlines
        ):
            last_block_idx = len(doc_blocks) - 1
            need_term = True

    # 마지막으로 생성될 블록 인덱스 계산 (is_last 마킹용)
    last_effective_idx = -1
    last_effective_block: Block | None = None
    if not need_term:
        for idx in range(len(doc_blocks) - 1, -1, -1):
            if idx != first_block_idx and idx != last_block_idx:
                last_effective_idx = idx
                last_effective_block = doc_blocks[idx]
                break

    # 복합 블록(테이블/각주/미주/수식/이미지)이 마지막이면 종결 단락 필요
    # (MSB를 host PH에 설정하면 한컴이 CTRL 자식을 무시하고 손상 판정)
    _COMPOUND_TYPES = (TableBlock, FootnoteBlock, EndnoteBlock, EquationBlock, ImageBlock)
    if last_effective_block and isinstance(last_effective_block, _COMPOUND_TYPES):
        need_term = True

    for i, block in enumerate(doc_blocks):
        if i == first_block_idx or i == last_block_idx:
            continue
        is_last_para = (not need_term and i == last_effective_idx)

        # Account for space_before in vpos before building
        blk_fmt = getattr(block, "format", None)
        if blk_fmt and blk_fmt.space_before:
            current_vpos += pt_to_hwpunit(blk_fmt.space_before)

        result = _dispatch_block(block, current_vpos, ctx, is_last_para)
        if result:
            rec, height = result
            if rec:
                para_records.append(rec)
            current_vpos += height
            # Account for space_after in vpos
            if blk_fmt and blk_fmt.space_after:
                current_vpos += pt_to_hwpunit(blk_fmt.space_after)

    if need_term:
        section_bytes = secd_prefix + build_section(para_records, term_vpos=current_vpos)
    elif not para_records:
        section_bytes = secd_prefix + build_term_paragraph(vpos=current_vpos)
    else:
        section_bytes = secd_prefix + b"".join(para_records)
    section_bytes = _ensure_last_para_msb(section_bytes)

    compressed = _compress(section_bytes)
    patch_hwp_stream(output_path, output_path, ["BodyText", "Section0"], compressed)

    # 이미지 후처리: OLE 스트림에 이미지 데이터 추가
    if ctx.images:
        _embed_images(output_path, seed_path, ctx, new_cs_specs, new_ps_specs,
                      has_tbl, extra_bf_specs, doc=doc,
                      numbering_specs=numbering_payloads if numbering_payloads else None)

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
) -> None:
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

    # DocInfo 재빌드 (기존 CS/PS/BF + BIN_DATA 추가)
    seed_docinfo = _read_seed_docinfo(seed_path)
    new_docinfo, _, _, _, *_ = build_docinfo(
        seed_docinfo, new_cs_specs, new_ps_specs,
        need_table_bf=has_tbl,
        bin_data_specs=bin_specs,
        extra_border_fills=extra_bf_specs if extra_bf_specs else None,
        numbering_specs=numbering_specs,
    )
    from udf.validation.hwp.integrity import validate_hwp_integrity
    violations = validate_hwp_integrity(new_docinfo)
    if violations:
        msgs = "; ".join(v.message for v in violations)
        raise ScratchError(f"DocInfo integrity check failed (images): {msgs}")
    compressed_di = _compress(new_docinfo)
    patch_hwp_stream(output_path, output_path, ["DocInfo"], compressed_di)

    # OLE 스트림에 이미지 데이터 추가 (FileHeader compressed 플래그에 따라 압축)
    for img_ref, data in valid_images:
        stream_name = f"BIN{img_ref.bin_data_id:04X}.{img_ref.extension}"
        add_hwp_stream(output_path, ["BinData", stream_name], _compress(data))
