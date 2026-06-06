"""BodyText 섹션 스트림 빌더 — From Scratch 모드용.

UdfDocument의 블록 목록을 받아 HWP BodyText/Section0 스트림 bytes를 생성한다.

PARA_HEADER 레이아웃 (22 bytes, hwp.md §5.1 기준):
  0-3    charCnt: uint32 (lower 30 bits) | (is_last << 31)
  4-7    controlMask: uint32
  8-9    para_shape_id: uint16
  10     style_id: uint8
  11     colSplit: uint8
  12-13  csCount: uint16
  14-15  rtCount: uint16
  16-17  lsCount: uint16
  18-21  instanceId: uint32

PARA_CHAR_SHAPE (PCS) 엔트리 (8 bytes):
  0-3    pos: uint32
  4-7    char_shape_id: uint32

PARA_LINE_SEG (PLS) 엔트리 (36 bytes):
  0-3    tpos: uint32
  4-7    vpos: uint32
  8-11   h: uint32
  12-35  기타 (표준값 채움)

PARA_TEXT: UTF-16LE + 0x000D (CR)
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

from udf.parsers.hwp.records import (
    HWPTAG_CTRL_HEADER,
    HWPTAG_LIST_HEADER,
    HWPTAG_PAGE_DEF,
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_LINE_SEG,
    HWPTAG_PARA_TEXT,
    HWPTAG_TABLE,
    HWPTAG_EQEDIT,
    HWPTAG_SHAPE_COMPONENT,
    HWPTAG_SHAPE_COMPONENT_PIC,
    HWPTAG_SHAPE_COMPONENT_RECT,
    iter_records,
)

# 함정 5: charCnt MSB 보존용 마스크
_MSB = 0x80000000
# 마지막 단락의 고정 필드 관찰값
_PH_MAGIC = 0xBA0994D2

# 기본 줄 높이 (HWPUNIT, 1pt = 100)
_DEFAULT_LINE_HEIGHT = 1000   # 10pt
# 기본 단락 간격: h × 160% 줄 간격 (PS[0] lsp=160)
_EFFECTIVE_PARA_HEIGHT = 1600  # exported for scratch.py


# ---------------------------------------------------------------------------
# 인라인 span (text + CharShape ID)
# ---------------------------------------------------------------------------


@dataclass
class TextSpan:
    """단일 CharShape가 적용되는 텍스트 구간."""
    text: str
    cs_id: int = 0


@dataclass
class CellImageInfo:
    """셀 내 이미지의 BinData 참조 + 크기 정보."""
    bin_item_id: int   # 1-based BIN_DATA index
    img_width: int     # HWPUNIT
    img_height: int    # HWPUNIT


# ---------------------------------------------------------------------------
# 레코드 직렬화 헬퍼 (body_writer.py와 동일 로직)
# ---------------------------------------------------------------------------


def _pack_record(tag_id: int, level: int, payload: bytes) -> bytes:
    """Serialize an HWP record header + payload to bytes."""
    size = len(payload)
    if size < 0xFFF:
        h = tag_id | (level << 10) | (size << 20)
        return struct.pack("<I", h) + payload
    h = tag_id | (level << 10) | (0xFFF << 20)
    return struct.pack("<II", h, size) + payload


def _bump_record_levels(data: bytes, delta: int) -> bytes:
    """Bump the level field of every HWP record header in *data* by *delta*."""
    out = bytearray()
    pos = 0
    while pos + 4 <= len(data):
        h = struct.unpack_from("<I", data, pos)[0]
        tag = h & 0x3FF
        lvl = (h >> 10) & 0x3FF
        sz = (h >> 20) & 0xFFF
        pos += 4
        if sz == 0xFFF:
            if pos + 4 > len(data):
                break
            sz = struct.unpack_from("<I", data, pos)[0]
            pos += 4
        if pos + sz > len(data):
            break
        payload = data[pos:pos + sz]
        pos += sz
        out += _pack_record(tag, lvl + delta, payload)
    return bytes(out)


# ---------------------------------------------------------------------------
# 개별 레코드 빌더
# ---------------------------------------------------------------------------


def _ctrl_mask_from_text(text: str) -> int:
    """텍스트 내 제어 문자에 대응하는 controlMask 비트를 반환한다."""
    mask = 0
    for ch in text:
        cp = ord(ch)
        if cp <= 0x001F and cp != 0x000D:
            mask |= (1 << cp)
    return mask


def _sanitize_text(text: str) -> str:
    """From Scratch 생성 시 안전하지 않은 제어 문자를 치환한다.

    HWP TAB(0x0009)은 TabDef 레코드 없이 사용하면 한컴이 '형식 복구'를
    발생시킨다. 0x000A(줄바꿈)도 별도 레코드가 필요하므로 공백으로 치환.
    """
    return text.replace("\t", " ").replace("\n", " ")


def _build_para_text(text: str) -> bytes:
    """PARA_TEXT 페이로드: UTF-16LE + 0x000D(CR)."""
    return _sanitize_text(text).encode("utf-16-le") + b"\x0d\x00"


def _build_pcs(spans: list[TextSpan]) -> bytes:
    """PARA_CHAR_SHAPE 페이로드: 각 span의 (pos, cs_id) 엔트리."""
    buf = b""
    pos = 0
    for span in spans:
        buf += struct.pack("<II", pos, span.cs_id)
        pos += len(span.text)
    return buf


def _build_pls(
    char_cnt: int,
    vpos: int = 0,
    h: int = _DEFAULT_LINE_HEIGHT,
    dist: int = 42520,
    line_spacing_pct: int = 160,
) -> bytes:
    """PARA_LINE_SEG 페이로드: 단일 줄 세그 (36 bytes).

    vpos: 섹션 상단 기준 절대 Y 위치 (HWPUNIT).
    h: 줄 높이 (font_size HWPUNIT).
    dist: 본문 영역 폭 (page_width - margin_left - margin_right).
    line_spacing_pct: 줄 간격 퍼센트 (예: 160).
    """
    ty = h * 85 // 100
    colx = max(0, h * (line_spacing_pct - 100) // 100)
    return struct.pack(
        "<9I",
        0,                    # tpos
        vpos,                 # vpos (절대 Y 위치)
        h,                    # h
        h,                    # tx (= h)
        ty,                   # ty (= h × 0.85)
        colx,                 # colx (= h × (ls-100)/100)
        0,                    # colw
        dist,                 # dist (본문 영역 폭)
        0x00060000,           # flags (bit17 + bit18)
    )


_GLYPH_WIDTH_CACHE: dict[str, dict[int, int]] = {}

try:
    from fontTools.ttLib import TTFont as _TTFont
    _HAS_FONTTOOLS = True
except ImportError:
    _HAS_FONTTOOLS = False


def _load_font_widths(font_name: str) -> dict[int, int] | None:
    """Load glyph advance widths from system font. Returns codepoint→width(1000 units) or None."""
    if not _HAS_FONTTOOLS or not font_name:
        return None
    if font_name in _GLYPH_WIDTH_CACHE:
        return _GLYPH_WIDTH_CACHE[font_name]
    import os
    search_dirs = [
        "/System/Library/Fonts/", "/Library/Fonts/",
        os.path.expanduser("~/Library/Fonts/"),
        "/usr/share/fonts/",
    ]
    candidates = [
        f"{font_name}.ttf", f"{font_name}.otf", f"{font_name}.ttc",
        f"{font_name}.TTF", f"{font_name}.OTF",
    ]
    for d in search_dirs:
        for c in candidates:
            path = os.path.join(d, c)
            if os.path.exists(path):
                try:
                    tt = _TTFont(path, fontNumber=0)
                    cmap = tt.getBestCmap() or {}
                    hmtx = tt["hmtx"].metrics if "hmtx" in tt else {}
                    upm = tt["head"].unitsPerEm if "head" in tt else 1000
                    widths = {}
                    for cp, gname in cmap.items():
                        if gname in hmtx:
                            widths[cp] = hmtx[gname][0] * 1000 // upm
                    tt.close()
                    _GLYPH_WIDTH_CACHE[font_name] = widths
                    return widths
                except Exception:
                    pass
    _GLYPH_WIDTH_CACHE[font_name] = {}
    return None


def _estimate_text_width(text: str, font_size_hu: int, font_name: str | None = None) -> int:
    """텍스트의 총 폭을 HWPUNIT 단위로 추산한다.

    fonttools가 설치되어 있고 폰트 파일이 있으면 실제 글리프 폭 사용.
    없으면 한글/CJK=1.0×, ASCII=0.6× fallback.
    """
    gw = _load_font_widths(font_name) if font_name else None
    w = 0
    for ch in text:
        cp = ord(ch)
        if gw and cp in gw:
            w += font_size_hu * gw[cp] // 1000
        elif 0xAC00 <= cp <= 0xD7A3 or 0x4E00 <= cp <= 0x9FFF or 0x3000 <= cp <= 0x303F:
            w += font_size_hu
        elif cp <= 0x007F:
            w += font_size_hu * 6 // 10
        else:
            w += font_size_hu
    return w


def _build_pls_multi(
    text: str,
    vpos: int,
    content_width: int,
    font_size_hu: int,
    line_spacing_pct: int,
) -> tuple[bytes, int]:
    """멀티라인 PLS 페이로드를 생성한다.

    Returns:
        (pls_payload, para_height) 튜플.
        para_height: 이 단락이 차지하는 총 높이 (HWPUNIT).
    """
    char_cnt = len(text) + 1  # +1 for CR
    if not text or content_width <= 0:
        line_height = font_size_hu * line_spacing_pct // 100
        pls = _build_pls(char_cnt, vpos, h=font_size_hu,
                         dist=content_width or 42520,
                         line_spacing_pct=line_spacing_pct)
        return pls, max(line_height, _EFFECTIVE_PARA_HEIGHT)

    total_width = _estimate_text_width(text, font_size_hu)
    n_lines = max(1, math.ceil(total_width / content_width))
    n_lines = min(n_lines, char_cnt)
    line_height = max(_DEFAULT_LINE_HEIGHT, font_size_hu * line_spacing_pct // 100)

    if n_lines == 1:
        pls = _build_pls(char_cnt, vpos, h=font_size_hu,
                         dist=content_width, line_spacing_pct=line_spacing_pct)
        return pls, line_height

    text_len = len(text)
    avg_char_width = total_width / text_len if text_len else font_size_hu
    ty = font_size_hu * 85 // 100
    colx = max(0, font_size_hu * (line_spacing_pct - 100) // 100)

    buf = b""
    tpos = 0
    for i in range(n_lines):
        line_vpos = vpos + i * line_height
        is_last_line = (i == n_lines - 1)
        if is_last_line:
            seg_chars = text_len - tpos + 1  # +1 for CR
        else:
            seg_chars = max(1, int(content_width / avg_char_width))
        buf += struct.pack(
            "<9I",
            tpos,
            line_vpos,
            font_size_hu,     # h
            font_size_hu,     # tx (= h)
            ty,               # ty (= h × 0.85)
            colx,             # colx (= h × (ls-100)/100)
            0,                # colw
            content_width,    # dist (본문 영역 폭)
            0x00060000,       # flags (bit17 + bit18)
        )
        tpos += seg_chars

    para_height = n_lines * line_height
    return buf, para_height


def _build_para_header(
    char_cnt: int,
    cs_count: int,
    ls_count: int,
    ps_id: int = 0,
    style_id: int = 0,
    control_mask: int = 0,
    is_last: bool = False,
    col_split: int = 0,
) -> bytes:
    """PARA_HEADER 페이로드 (24 bytes)."""
    msb = _MSB if is_last else 0
    buf = struct.pack("<I", msb | (char_cnt & 0x3FFFFFFF))  # 0-3
    buf += struct.pack("<I", control_mask)                   # 4-7
    buf += struct.pack("<H", ps_id)                         # 8-9
    buf += struct.pack("<B", style_id)                      # 10
    buf += struct.pack("<B", col_split)                     # 11  colSplit
    buf += struct.pack("<H", cs_count)                      # 12-13
    buf += struct.pack("<H", 0)                             # 14-15 rtCount
    buf += struct.pack("<H", ls_count)                      # 16-17
    buf += struct.pack("<I", 0)                             # 18-21 instanceId
    buf += struct.pack("<H", 0)                             # 22-23
    assert len(buf) == 24
    return buf


# ---------------------------------------------------------------------------
# 단락 빌더
# ---------------------------------------------------------------------------


def build_paragraph(
    spans: list[TextSpan],
    ps_id: int = 0,
    style_id: int = 0,
    level: int = 0,
    is_last: bool = False,
    vpos: int = 0,
    content_width: int = 0,
    font_size_hu: int = 1000,
    line_spacing_pct: int = 160,
    original_pls: bytes | None = None,
) -> tuple[bytes, int]:
    """Serialize text spans into a paragraph record set (PH + PT + PCS + PLS).

    Parameters
    ----------
    spans : list[TextSpan]
        Text spans with CharShape IDs to serialize.
    ps_id : int, default 0
        ParaShape ID for the paragraph header.
    style_id : int, default 0
        Style ID for the paragraph header.
    level : int, default 0
        Record nesting level.
    is_last : bool, default False
        If True, set the MSB (bit 31) in charCnt for section termination.
    vpos : int, default 0
        Vertical position in HWPUNIT from section top.
    content_width : int, default 0
        Content area width in HWPUNIT (for multi-line wrapping).
    font_size_hu : int, default 1000
        Font size in HWPUNIT (1pt = 100).
    line_spacing_pct : int, default 160
        Line spacing as percentage (e.g. 160 = 160%).

    Returns
    -------
    tuple[bytes, int]
        Record bytes and paragraph height in HWPUNIT.
    """
    text = "".join(s.text for s in spans)
    line_height = max(_DEFAULT_LINE_HEIGHT, font_size_hu * line_spacing_pct // 100)

    if not text:
        char_cnt = 1  # CR 1개
        ph = _build_para_header(char_cnt, 1, 1, ps_id, style_id, is_last=is_last)
        pcs = struct.pack("<II", 0, spans[0].cs_id if spans else 0)
        pls = _build_pls(char_cnt, vpos=vpos,
                         dist=content_width or 42520,
                         line_spacing_pct=line_spacing_pct)
        out = _pack_record(HWPTAG_PARA_HEADER, level, ph)
        out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 1, pcs)
        out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 1, pls)
        return out, line_height

    pt = _build_para_text(text)          # text + CR
    char_cnt = len(pt) // 2
    pcs = _build_pcs(spans)

    if original_pls is not None and len(original_pls) >= 36:
        pls = original_pls
        ls_entry_h = struct.unpack_from("<I", pls, 8)[0] if len(pls) >= 12 else line_height
        para_height = ls_entry_h if ls_entry_h > 0 else line_height
    elif content_width > 0:
        pls, para_height = _build_pls_multi(text, vpos, content_width, font_size_hu, line_spacing_pct)
    else:
        pls = _build_pls(char_cnt, vpos=vpos)
        para_height = line_height

    ls_count = len(pls) // 36

    ph = _build_para_header(
        char_cnt=char_cnt,
        cs_count=len(spans),
        ls_count=ls_count,
        ps_id=ps_id,
        style_id=style_id,
        control_mask=_ctrl_mask_from_text(text),
        is_last=is_last,
    )

    out = _pack_record(HWPTAG_PARA_HEADER, level, ph)
    out += _pack_record(HWPTAG_PARA_TEXT, level + 1, pt)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 1, pcs)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 1, pls)
    return out, para_height


def build_term_paragraph(level: int = 0, vpos: int = 0) -> bytes:
    """Build a section-termination paragraph (charCnt=1, MSB=1, no PARA_TEXT).

    Parameters
    ----------
    level : int, default 0
        Record nesting level.
    vpos : int, default 0
        Vertical position in HWPUNIT.

    Returns
    -------
    bytes
        Serialized record bytes for the termination paragraph.
    """
    char_cnt = 1
    ph = _build_para_header(char_cnt, 1, 1, is_last=True)
    pcs = struct.pack("<II", 0, 0)
    pls = _build_pls(char_cnt, vpos=vpos)
    out = _pack_record(HWPTAG_PARA_HEADER, level, ph)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 1, pcs)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 1, pls)
    return out


# ---------------------------------------------------------------------------
# secd 단락 빌더
# ---------------------------------------------------------------------------

_SIMPLE_CTRL = frozenset({0x0000, 0x0009, 0x000A})


def _patch_page_def_payload(payload: bytes, page_meta: dict[str, int]) -> bytes:
    """PAGE_DEF 페이로드의 페이지 크기/여백을 패치한다.

    PAGE_DEF 바이너리 레이아웃 (40 bytes):
      0-3: width, 4-7: height, 8-11: margin_left, 12-15: margin_right,
      16-19: margin_top, 20-23: margin_bottom, 24-27: margin_header,
      28-31: margin_footer, 32-35: gutter, 36-39: attr
    """
    buf = bytearray(payload)
    field_map = {
        "page_width": 0, "page_height": 4,
        "margin_left": 8, "margin_right": 12,
        "margin_top": 16, "margin_bottom": 20,
        "margin_header": 24, "margin_footer": 28,
        "gutter": 32,
    }
    for key, offset in field_map.items():
        if key in page_meta and offset + 4 <= len(buf):
            struct.pack_into("<I", buf, offset, page_meta[key])
    return bytes(buf)


def build_secd_paragraph(
    seed_section_bytes: bytes,
    page_meta: dict[str, int] | None = None,
    text: str = "",
    cs_id: int = 0,
    ps_id_override: int | None = None,
    style_id_override: int | None = None,
    is_last: bool = False,
    dist: int = 42520,
    line_spacing_pct: int = 160,
    extra_inline_ctrls: list[bytes] | None = None,
    page_bg_bf_id: int | None = None,
) -> bytes:
    """Reconstruct the secd paragraph from seed, merging new text content.

    The first paragraph in HWP files holds secd/dloc control objects and
    actual text simultaneously. This function preserves the seed's inline
    control objects while appending the given text.

    Parameters
    ----------
    seed_section_bytes : bytes
        Decompressed seed section stream.
    page_meta : dict[str, int] or None
        PAGE_DEF overrides (page_width, margin_left, etc.).
    text : str
        Text to merge into the secd paragraph.
    cs_id : int, default 0
        CharShape ID for the merged text.
    ps_id_override : int or None
        Override ParaShape ID (uses seed value if None).
    style_id_override : int or None
        Override style ID (uses seed value if None).
    is_last : bool, default False
        Whether this is the last paragraph in the section.
    dist : int, default 42520
        Content area width in HWPUNIT.
    line_spacing_pct : int, default 160
        Line spacing percentage.

    Returns
    -------
    bytes
        Serialized record bytes for the secd paragraph.
    """
    first_ph_payload: bytes | None = None
    para_text_payload: bytes | None = None
    ctrl_records = b""
    found_ph = False

    for rec in iter_records(seed_section_bytes):
        if rec.tag_id == HWPTAG_PARA_HEADER and rec.level == 0:
            if found_ph:
                break
            found_ph = True
            first_ph_payload = rec.payload
        elif found_ph:
            if rec.tag_id == HWPTAG_PARA_TEXT and rec.level == 1:
                para_text_payload = rec.payload
            elif rec.tag_id not in (HWPTAG_PARA_CHAR_SHAPE, HWPTAG_PARA_LINE_SEG):
                payload = rec.payload
                if rec.tag_id == HWPTAG_PAGE_DEF and page_meta:
                    payload = _patch_page_def_payload(payload, page_meta)
                if rec.tag_id == 75 and page_bg_bf_id is not None and len(payload) >= 14:
                    payload = bytearray(payload)
                    struct.pack_into("<H", payload, 12, page_bg_bf_id)
                    payload = bytes(payload)
                    page_bg_bf_id = None
                ctrl_records += _pack_record(rec.tag_id, rec.level, payload)

    if not first_ph_payload:
        return b""

    # seed PARA_TEXT에서 inline ctrl 오브젝트만 추출
    inline_bytes = b""
    if para_text_payload:
        i = 0
        while i + 1 < len(para_text_payload):
            (ch,) = struct.unpack_from("<H", para_text_payload, i)
            if ch == 0x000D:
                break
            elif ch in _SIMPLE_CTRL:
                inline_bytes += para_text_payload[i : i + 2]
                i += 2
            elif ch <= 0x001F:  # inline object = 16 bytes
                end = i + 16
                if end <= len(para_text_payload):
                    inline_bytes += para_text_payload[i:end]
                i = end
            else:
                break  # 일반 텍스트 시작 → 버림

    extra_bytes = b""
    if extra_inline_ctrls:
        for ctrl in extra_inline_ctrls:
            extra_bytes += ctrl

    new_pt = inline_bytes + extra_bytes + _sanitize_text(text).encode("utf-16-le") + b"\x0d\x00"
    char_cnt = len(new_pt) // 2

    ctrl_mask = struct.unpack_from("<I", first_ph_payload, 4)[0]
    if extra_inline_ctrls:
        for ctrl in extra_inline_ctrls:
            ctrl_code = struct.unpack_from("<H", ctrl, 0)[0]
            ctrl_mask |= (1 << ctrl_code)
    ctrl_mask |= _ctrl_mask_from_text(text)
    seed_ps_id = struct.unpack_from("<H", first_ph_payload, 8)[0]
    seed_style_id = first_ph_payload[10]
    ps_id = ps_id_override if ps_id_override is not None else seed_ps_id
    style_id = style_id_override if style_id_override is not None else seed_style_id

    all_inline_bytes = inline_bytes + extra_bytes
    inline_ctrl_count = len(all_inline_bytes) // 16
    if not text or cs_id == 0:
        n_pcs = 1
        pcs_entries = struct.pack("<II", 0, 0)
    else:
        n_pcs = 2
        pcs_entries = struct.pack("<II", 0, 0)
        text_start_pos = inline_ctrl_count * 8
        pcs_entries += struct.pack("<II", text_start_pos, cs_id)

    h = _DEFAULT_LINE_HEIGHT
    h * 85 // 100
    h * (line_spacing_pct - 100) // 100

    ph = _build_para_header(
        char_cnt=char_cnt,
        cs_count=n_pcs,
        ls_count=1,
        ps_id=ps_id,
        style_id=style_id,
        control_mask=ctrl_mask,
        is_last=is_last,
        col_split=3,
    )
    pls = _build_pls(char_cnt, vpos=0, h=h, dist=dist, line_spacing_pct=line_spacing_pct)

    out = _pack_record(HWPTAG_PARA_HEADER, 0, ph)
    out += _pack_record(HWPTAG_PARA_TEXT, 1, new_pt)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, 1, pcs_entries)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, 1, pls)
    out += ctrl_records
    return out


# ---------------------------------------------------------------------------
# 인라인 컨트롤 앵커 빌더
# ---------------------------------------------------------------------------

_CTRL_CODE_TABLE = 0x000B
_CTRL_CODE_EQED = 0x000B
_CTRL_CODE_FN = 0x0011   # footnote/endnote inline ctrl (NOT 0x000B)
_CTRL_CODE_GSO = 0x000B

_CTRL_ID_TBL = b"\x20\x6c\x62\x74"   # 'tbl ' LE
_CTRL_ID_EQED = b"\x64\x65\x71\x65"  # 'eqed' LE
_CTRL_ID_FN = b"\x20\x20\x6e\x66"    # 'fn  ' LE (reversed)
_CTRL_ID_EN = b"\x20\x20\x6e\x65"    # 'en  ' LE (reversed)
_CTRL_ID_GSO = b"\x20\x6f\x73\x67"   # 'gso ' LE (reversed)

_TBL_CTRL_ATTR = 0x082A2210
_TBL_TABLE_ATTR = 0x04000006
_DEFAULT_CELL_PADDING_H = 510   # 좌우 셀 패딩 (≈5.1pt = 1.8mm)
_DEFAULT_CELL_PADDING_V = 141   # 상하 셀 패딩 (≈1.41pt = 0.5mm)
_DEFAULT_CELL_BF_ID = 3
_MIN_CELL_HEIGHT = 282
_MIN_COL_WIDTH_HU = 1417   # 최소 열 폭 ≈5mm (14.17pt × 100)


def _auto_col_widths(
    n_cols: int,
    cell_texts: list[list[list[TextSpan]]],
    content_width: int,
    font_size_hu: int,
) -> list[int]:
    """Content-proportional column widths with sqrt dampening."""
    if n_cols <= 1:
        return [content_width]

    max_w = [0.0] * n_cols
    for row_spans in cell_texts:
        for ci, spans in enumerate(row_spans):
            if ci < n_cols:
                text = "".join(s.text for s in spans)
                max_w[ci] = max(max_w[ci], float(_estimate_text_width(text, font_size_hu)))

    dampened = [math.sqrt(max(w, 1.0)) for w in max_w]
    total_d = sum(dampened) or 1.0
    widths = [int(d / total_d * content_width) for d in dampened]

    for i in range(n_cols):
        if widths[i] < _MIN_COL_WIDTH_HU:
            deficit = _MIN_COL_WIDTH_HU - widths[i]
            widths[i] = _MIN_COL_WIDTH_HU
            above = [(j, widths[j]) for j in range(n_cols)
                     if j != i and widths[j] > _MIN_COL_WIDTH_HU]
            above_total = sum(w for _, w in above) or 1
            for j, w in above:
                widths[j] -= int(deficit * w / above_total)

    diff = content_width - sum(widths)
    if diff != 0:
        widths[-1] += diff

    return widths


def _build_inline_ctrl_obj(ctrl_code: int, ctrl_id_bytes: bytes) -> bytes:
    """PARA_TEXT 16바이트 인라인 컨트롤 오브젝트."""
    buf = struct.pack("<H", ctrl_code)
    buf += ctrl_id_bytes
    buf += b"\x00" * 8
    buf += struct.pack("<H", ctrl_code)
    assert len(buf) == 16
    return buf


def _build_ctrl_header_tbl(width: int, height: int, instance_id: int = 0) -> bytes:
    """CTRL_HEADER 'tbl ' 페이로드 (46B, 한컴 실제 파일 기준)."""
    buf = _CTRL_ID_TBL
    buf += struct.pack("<I", _TBL_CTRL_ATTR)
    buf += struct.pack("<ii", 0, 0)  # y, x offset
    buf += struct.pack("<II", width, height)
    buf += struct.pack("<hh", 0, 0)  # z_order, unknown
    buf += struct.pack("<4H", 283, 283, 283, 283)  # margins (≈2.83pt ≈1mm)
    buf += struct.pack("<I", instance_id)
    buf += struct.pack("<I", 0)  # captionAttr (한컴 46B 기준)
    buf += struct.pack("<H", 0)  # trailing
    assert len(buf) == 46
    return buf


def _build_table_record(
    n_rows: int, n_cols: int, bf_id: int = _DEFAULT_CELL_BF_ID,
    cells_per_row: list[int] | None = None,
    cell_spacing: int = 0,
    tbl_padding: tuple[int, int, int, int] | None = None,
) -> bytes:
    """TABLE (tag=77) 레코드 페이로드."""
    buf = struct.pack("<I", _TBL_TABLE_ATTR)
    buf += struct.pack("<HH", n_rows, n_cols)
    buf += struct.pack("<H", cell_spacing)
    pad = tbl_padding or (_DEFAULT_CELL_PADDING_H, _DEFAULT_CELL_PADDING_H,
                          _DEFAULT_CELL_PADDING_V, _DEFAULT_CELL_PADDING_V)
    buf += struct.pack("<4H", pad[0], pad[1], pad[2], pad[3])
    for ri in range(n_rows):
        cnt = cells_per_row[ri] if cells_per_row and ri < len(cells_per_row) else n_cols
        buf += struct.pack("<H", cnt)
    buf += struct.pack("<H", bf_id)
    buf += struct.pack("<H", 0)  # trailing field (원본 관찰)
    return buf


_CELL_VALIGN = {"top": 0, "center": 1, "bottom": 2}


def _build_list_header(
    row: int, col: int, colspan: int, rowspan: int,
    size_x: int, size_y: int, bf_id: int = _DEFAULT_CELL_BF_ID,
    para_count: int = 1,
    vertical_align: str | None = None,
) -> bytes:
    """LIST_HEADER (tag=72) 셀 페이로드 (47B, 한컴 실제 파일 기준)."""
    va = _CELL_VALIGN.get(vertical_align or "top", 0)
    listflags = 0x00000020 | (va << 2)
    buf = struct.pack("<HH", para_count, 0)  # paragraphs, unknown
    buf += struct.pack("<I", listflags)
    buf += struct.pack("<HH", col, row)
    buf += struct.pack("<HH", colspan, rowspan)
    buf += struct.pack("<II", size_x, size_y)
    buf += struct.pack("<4H", _DEFAULT_CELL_PADDING_H, _DEFAULT_CELL_PADDING_H,
                       _DEFAULT_CELL_PADDING_V, _DEFAULT_CELL_PADDING_V)
    buf += struct.pack("<H", bf_id)
    buf += struct.pack("<I", size_x)  # textWidth (한컴 47B 기준)
    buf += b"\x00" * 9
    assert len(buf) == 47
    return buf


def build_table(
    n_rows: int,
    n_cols: int,
    cell_texts: list[list[list[TextSpan]]],
    content_width: int,
    vpos: int,
    col_widths: list[int] | None = None,
    level: int = 0,
    font_size_hu: int = 1000,
    line_spacing_pct: int = 160,
    bf_id: int = _DEFAULT_CELL_BF_ID,
    cell_bf_ids: list[list[int]] | None = None,
    cell_ps_ids: list[list[int]] | None = None,
    cell_merges: list[list[tuple[int, int]]] | None = None,
    cell_images: list[list[list[CellImageInfo]]] | None = None,
    cell_widths_hint: list[list[int]] | None = None,
    row_heights_hint: list[int] | None = None,
    cell_valigns: list[list[str]] | None = None,
    tbl_cell_spacing: int = 0,
    tbl_padding: tuple[int, int, int, int] | None = None,
) -> tuple[bytes, int]:
    """Build a complete HWP table record set for a TableBlock.

    cell_merges: per-row list of (col_span, row_span) for each cell in that row.
    Rows in cell_merges correspond to the actual cells emitted per row (after merge).
    cell_images: per-row, per-cell list of CellImageInfo for images to embed in cells.
    """
    if not col_widths:
        col_widths = _auto_col_widths(n_cols, cell_texts, content_width, font_size_hu)
    table_width = sum(col_widths)

    # Build a grid to track which cells are covered by rowspan from above.
    # covered[ri][ci] = True means (ri, ci) is covered by a rowspan from a cell above.
    covered: list[list[bool]] = [[False] * n_cols for _ in range(n_rows)]
    if cell_merges:
        for ri in range(n_rows):
            logical_ci = 0
            if ri < len(cell_merges):
                for mi, (cs, rs) in enumerate(cell_merges[ri]):
                    while logical_ci < n_cols and covered[ri][logical_ci]:
                        logical_ci += 1
                    if logical_ci >= n_cols:
                        break
                    for dr in range(rs):
                        for dc in range(cs):
                            if ri + dr < n_rows and logical_ci + dc < n_cols:
                                if dr > 0 or dc > 0:
                                    covered[ri + dr][logical_ci + dc] = True
                    logical_ci += cs

    line_h = max(_DEFAULT_LINE_HEIGHT, font_size_hu * line_spacing_pct // 100)
    row_heights = [max(_MIN_CELL_HEIGHT, line_h)] * n_rows
    if row_heights_hint:
        for ri in range(min(n_rows, len(row_heights_hint))):
            if row_heights_hint[ri] > 0:
                row_heights[ri] = max(row_heights[ri], row_heights_hint[ri])
    for ri in range(n_rows):
        if ri < len(cell_texts):
            for ci_data, spans in enumerate(cell_texts[ri]):
                text = "".join(s.text for s in spans)
                col_w = col_widths[0] if col_widths else content_width
                if ci_data < n_cols and col_widths:
                    col_w = col_widths[ci_data]
                if cell_widths_hint and ri < len(cell_widths_hint) and ci_data < len(cell_widths_hint[ri]):
                    hint = cell_widths_hint[ri][ci_data]
                    if hint > 0:
                        col_w = hint
                if text and col_w > 0:
                    tw = _estimate_text_width(text, font_size_hu)
                    n_lines = max(1, math.ceil(tw / max(1, col_w - 2 * _DEFAULT_CELL_PADDING_H)))
                    n_lines = min(n_lines, len(text) + 1)
                    h = n_lines * line_h
                    row_heights[ri] = max(row_heights[ri], h)
        # Account for image heights in cells
        if cell_images and ri < len(cell_images):
            for ci_data, imgs in enumerate(cell_images[ri]):
                for img_info in imgs:
                    col_w = col_widths[ci_data] if ci_data < len(col_widths) else content_width
                    cell_content_w = max(1, col_w - 2 * _DEFAULT_CELL_PADDING_H)
                    ih = img_info.img_height
                    iw = img_info.img_width
                    if iw > cell_content_w:
                        ih = int(ih * cell_content_w / iw)
                    row_heights[ri] = max(row_heights[ri], row_heights[ri] + ih)

    table_height = sum(row_heights)

    # Compute actual cells per row for TABLE record
    cells_per_row: list[int] | None = None
    if cell_merges:
        cells_per_row = []
        for ri in range(n_rows):
            cnt = 0
            logical_ci = 0
            if ri < len(cell_merges):
                for cs, rs in cell_merges[ri]:
                    while logical_ci < n_cols and covered[ri][logical_ci]:
                        logical_ci += 1
                    if logical_ci >= n_cols:
                        break
                    cnt += 1
                    logical_ci += cs
            else:
                cnt = sum(1 for c in range(n_cols) if not covered[ri][c])
            cells_per_row.append(cnt)

    # 1. Host paragraph: PH + PT(inline ctrl) + PCS + PLS
    inline_obj = _build_inline_ctrl_obj(_CTRL_CODE_TABLE, _CTRL_ID_TBL)
    pt_payload = inline_obj + b"\x0d\x00"  # ctrl obj + CR
    char_cnt = len(pt_payload) // 2  # = 9
    ph = _build_para_header(char_cnt, 1, 1, control_mask=0x00000800)
    pcs = struct.pack("<II", 0, 0)
    pls = _build_pls(char_cnt, vpos=vpos)

    out = _pack_record(HWPTAG_PARA_HEADER, level, ph)
    out += _pack_record(HWPTAG_PARA_TEXT, level + 1, pt_payload)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 1, pcs)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 1, pls)

    # 2. CTRL_HEADER 'tbl '
    ctrl_payload = _build_ctrl_header_tbl(table_width, table_height)
    out += _pack_record(HWPTAG_CTRL_HEADER, level + 1, ctrl_payload)

    # 3. TABLE record
    tbl_payload = _build_table_record(n_rows, n_cols, bf_id=bf_id, cells_per_row=cells_per_row,
                                      cell_spacing=tbl_cell_spacing, tbl_padding=tbl_padding)
    out += _pack_record(HWPTAG_TABLE, level + 2, tbl_payload)

    # 4. Cell LIST_HEADER + cell paragraphs
    for ri in range(n_rows):
        logical_ci = 0
        data_ci = 0
        while logical_ci < n_cols:
            if covered[ri][logical_ci]:
                logical_ci += 1
                continue
            cs, rs = 1, 1
            if cell_merges and ri < len(cell_merges) and data_ci < len(cell_merges[ri]):
                cs, rs = cell_merges[ri][data_ci]
            size_x = sum(col_widths[logical_ci:logical_ci + cs])
            size_y = sum(row_heights[ri:ri + rs])
            cell_bf = bf_id
            if cell_bf_ids and ri < len(cell_bf_ids) and data_ci < len(cell_bf_ids[ri]):
                cell_bf = cell_bf_ids[ri][data_ci]

            # Determine images for this cell
            imgs: list[CellImageInfo] = []
            if cell_images and ri < len(cell_images) and data_ci < len(cell_images[ri]):
                imgs = cell_images[ri][data_ci]

            # paragraph count = 1 (text) + number of images
            para_count = 1 + len(imgs)
            cell_va = None
            if cell_valigns and ri < len(cell_valigns) and data_ci < len(cell_valigns[ri]):
                cell_va = cell_valigns[ri][data_ci]
            lh = _build_list_header(
                ri, logical_ci, cs, rs, size_x, size_y,
                bf_id=cell_bf, para_count=para_count,
                vertical_align=cell_va,
            )
            out += _pack_record(HWPTAG_LIST_HEADER, level + 2, lh)

            spans = [TextSpan("", 0)]
            if ri < len(cell_texts) and data_ci < len(cell_texts[ri]):
                spans = cell_texts[ri][data_ci] or [TextSpan("", 0)]

            cell_ps = 0
            if cell_ps_ids and ri < len(cell_ps_ids) and data_ci < len(cell_ps_ids[ri]):
                cell_ps = cell_ps_ids[ri][data_ci]

            has_imgs = len(imgs) > 0
            cell_para, _ = build_paragraph(
                spans, ps_id=cell_ps, level=level + 2,
                is_last=(not has_imgs),  # only last if no images follow
                vpos=0,
                content_width=max(1, size_x - 2 * _DEFAULT_CELL_PADDING_H),
                font_size_hu=font_size_hu,
                line_spacing_pct=line_spacing_pct,
            )
            out += cell_para

            # Emit image paragraphs inside the cell
            for img_idx, img_info in enumerate(imgs):
                cell_content_w = max(1, size_x - 2 * _DEFAULT_CELL_PADDING_H)
                iw = img_info.img_width
                ih = img_info.img_height
                if iw > cell_content_w:
                    ratio = cell_content_w / iw
                    iw = cell_content_w
                    ih = int(ih * ratio)
                img_rec, _ = build_image(
                    img_info.bin_item_id, iw, ih, vpos=0,
                    level=level + 2,
                    font_size_hu=font_size_hu,
                    line_spacing_pct=line_spacing_pct,
                )
                # Set MSB on last image paragraph in cell
                if img_idx == len(imgs) - 1:
                    img_rec = bytearray(img_rec)
                    if len(img_rec) >= 8:
                        ph_val = struct.unpack_from('<I', img_rec, 4)[0]
                        struct.pack_into('<I', img_rec, 4, ph_val | _MSB)
                    img_rec = bytes(img_rec)
                out += img_rec

            logical_ci += cs
            data_ci += 1

    line_height = font_size_hu * line_spacing_pct // 100
    total_height = table_height + line_height
    return out, total_height


# ---------------------------------------------------------------------------
# 수식 빌더
# ---------------------------------------------------------------------------


def build_equation(
    hwp_script: str,
    vpos: int,
    level: int = 0,
    font_size_hu: int = 1000,
    line_spacing_pct: int = 160,
) -> tuple[bytes, int]:
    """Build an equation record set (host paragraph + CTRL_HEADER + EQEDIT).

    Parameters
    ----------
    hwp_script : str
        HWP equation script string.
    vpos : int
        Vertical position in HWPUNIT.
    level : int, default 0
        Record nesting level.
    font_size_hu : int, default 1000
        Font size in HWPUNIT.
    line_spacing_pct : int, default 160
        Line spacing percentage.

    Returns
    -------
    tuple[bytes, int]
        Record bytes and paragraph height in HWPUNIT.
    """
    # 1. Host paragraph
    inline_obj = _build_inline_ctrl_obj(_CTRL_CODE_EQED, _CTRL_ID_EQED)
    pt_payload = inline_obj + b"\x0d\x00"
    char_cnt = len(pt_payload) // 2
    ph = _build_para_header(char_cnt, 1, 1, control_mask=0x00000800)
    pcs = struct.pack("<II", 0, 0)
    pls = _build_pls(char_cnt, vpos=vpos)

    out = _pack_record(HWPTAG_PARA_HEADER, level, ph)
    out += _pack_record(HWPTAG_PARA_TEXT, level + 1, pt_payload)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 1, pcs)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 1, pls)

    # 2. CTRL_HEADER 'eqed'
    ctrl_payload = _CTRL_ID_EQED
    ctrl_payload += struct.pack("<I", 0x0C2A2211)  # attr (원본 f15 관찰값)
    ctrl_payload += struct.pack("<ii", 0, 0)  # y, x
    ctrl_payload += struct.pack("<II", font_size_hu * 4, font_size_hu * 2)  # width, height
    ctrl_payload += struct.pack("<hh", 0, 0)  # z_order, unknown
    ctrl_payload += struct.pack("<4H", 56, 56, 0, 0)  # margins (원본: 0x38=56)
    ctrl_payload += struct.pack("<I", 0)  # instance_id
    ctrl_payload += struct.pack("<H", 0)  # trailing field
    out += _pack_record(HWPTAG_CTRL_HEADER, level + 1, ctrl_payload)

    # 3. EQEDIT record (tag=88)
    script_bytes = hwp_script.encode("utf-16-le")
    eqedit = struct.pack("<I", 0)  # attr
    eqedit += struct.pack("<H", len(hwp_script))  # script char count
    eqedit += script_bytes
    out += _pack_record(HWPTAG_EQEDIT, level + 2, eqedit)

    line_height = font_size_hu * line_spacing_pct // 100
    return out, max(line_height, font_size_hu * 2)


# ---------------------------------------------------------------------------
# 각주/미주 빌더
# ---------------------------------------------------------------------------


def _build_footnote_list_header(n_paragraphs: int = 1) -> bytes:
    """각주/미주 LIST_HEADER 페이로드 (16 bytes, hwplib fixture 기준)."""
    buf = struct.pack("<I", n_paragraphs)   # paraCount (u32)
    buf += struct.pack("<I", 0)             # property (u32)
    buf += struct.pack("<I", 0)             # unknown1 (u32)
    buf += struct.pack("<I", 0)             # unknown2 (u32)
    return buf


def build_footnote(
    ref_num: int,
    body_spans: list[TextSpan],
    vpos: int,
    level: int = 0,
    font_size_hu: int = 1000,
    line_spacing_pct: int = 160,
    content_width: int = 42520,
) -> tuple[bytes, int]:
    """Build a footnote record set (host paragraph + CTRL_HEADER + body).

    Parameters
    ----------
    ref_num : int
        1-based footnote reference number.
    body_spans : list[TextSpan]
        Text spans for the footnote body content.
    vpos : int
        Vertical position in HWPUNIT.
    level : int, default 0
        Record nesting level.
    font_size_hu : int, default 1000
        Font size in HWPUNIT.
    line_spacing_pct : int, default 160
        Line spacing percentage.
    content_width : int, default 42520
        Content area width in HWPUNIT.

    Returns
    -------
    tuple[bytes, int]
        Record bytes and paragraph height in HWPUNIT.
    """
    return _build_note_records(
        _CTRL_ID_FN, ref_num, body_spans, vpos, level,
        font_size_hu, line_spacing_pct, content_width,
    )


def build_endnote(
    ref_num: int,
    body_spans: list[TextSpan],
    vpos: int,
    level: int = 0,
    font_size_hu: int = 1000,
    line_spacing_pct: int = 160,
    content_width: int = 42520,
) -> tuple[bytes, int]:
    """Build an endnote record set (host paragraph + CTRL_HEADER + body).

    Parameters
    ----------
    ref_num : int
        1-based endnote reference number.
    body_spans : list[TextSpan]
        Text spans for the endnote body content.
    vpos : int
        Vertical position in HWPUNIT.
    level : int, default 0
        Record nesting level.
    font_size_hu : int, default 1000
        Font size in HWPUNIT.
    line_spacing_pct : int, default 160
        Line spacing percentage.
    content_width : int, default 42520
        Content area width in HWPUNIT.

    Returns
    -------
    tuple[bytes, int]
        Record bytes and paragraph height in HWPUNIT.
    """
    return _build_note_records(
        _CTRL_ID_EN, ref_num, body_spans, vpos, level,
        font_size_hu, line_spacing_pct, content_width,
        is_endnote=True,
    )


_CTRL_CODE_ATNO = 0x0012    # auto-number inline ctrl (footnote body)
_CTRL_ID_ATNO = b"\x6f\x6e\x74\x61"  # 'atno' LE

_ATNO_ATTR_FN = 0x00000021   # footnote auto-number attribute
_ATNO_ATTR_EN = 0x00000002   # endnote auto-number attribute


def _build_note_body_paragraph(
    ref_num: int,
    body_spans: list[TextSpan],
    level: int,
    font_size_hu: int,
    line_spacing_pct: int,
    content_width: int,
    is_endnote: bool = False,
) -> bytes:
    """각주/미주 본문 단락 (atno auto-number 포함)."""
    # PARA_TEXT: [0x0012 atno inline(16B)] + body_text + CR
    atno_inline = _build_inline_ctrl_obj(_CTRL_CODE_ATNO, _CTRL_ID_ATNO)
    body_text = b""
    for span in body_spans:
        if span.text:
            body_text += span.text.encode("utf-16-le")
    pt_payload = atno_inline + body_text + b"\x0d\x00"
    char_cnt = len(pt_payload) // 2

    ph = _build_para_header(char_cnt, 1, 1, control_mask=0x00040800, is_last=True)

    # PCS: position 0 = cs_id from first span
    first_cs = body_spans[0].cs_id if body_spans else 0
    pcs = struct.pack("<II", 0, first_cs)
    pls = _build_pls(char_cnt, vpos=0)

    out = _pack_record(HWPTAG_PARA_HEADER, level, ph)
    out += _pack_record(HWPTAG_PARA_TEXT, level + 1, pt_payload)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 1, pcs)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 1, pls)

    # CTRL_HEADER 'atno' (16B)
    atno_attr = _ATNO_ATTR_EN if is_endnote else _ATNO_ATTR_FN
    atno_payload = _CTRL_ID_ATNO
    atno_payload += struct.pack("<I", atno_attr)
    atno_payload += struct.pack("<I", ref_num)
    atno_payload += struct.pack("<H", 0)           # beforeDeco
    atno_payload += struct.pack("<H", 0x0029)      # afterDeco = ')'
    out += _pack_record(HWPTAG_CTRL_HEADER, level + 1, atno_payload)
    return out


def _build_note_records(
    ctrl_id_bytes: bytes,
    ref_num: int,
    body_spans: list[TextSpan],
    vpos: int,
    level: int,
    font_size_hu: int,
    line_spacing_pct: int,
    content_width: int,
    is_endnote: bool = False,
) -> tuple[bytes, int]:
    """각주/미주 공통 레코드 트리 빌더.

    레코드 트리 (hwplib 각주미주.hwp 역분석 기준):
      PARA_HEADER (level)         — 호스트 단락 (인라인 각주 마커 0x0011)
        PARA_TEXT (level+1)
        PARA_CHAR_SHAPE (level+1)
        PARA_LINE_SEG (level+1)
        CTRL_HEADER (level+1)     — 'fn  '/'en  ' (20B)
          LIST_HEADER (level+2)   — 본문 컨테이너 (16B)
          PARA_HEADER (level+2)   — 각주 본문 단락 (atno 포함)
            PARA_TEXT (level+3)   — [0x0012 atno] + text + CR
            PARA_CHAR_SHAPE (level+3)
            PARA_LINE_SEG (level+3)
            CTRL_HEADER (level+3) — 'atno' (16B)
    """
    # 1. Host paragraph with inline ctrl marker (0x0011 for fn/en)
    inline_obj = _build_inline_ctrl_obj(_CTRL_CODE_FN, ctrl_id_bytes)
    pt_payload = inline_obj + b"\x0d\x00"
    char_cnt = len(pt_payload) // 2
    ph = _build_para_header(char_cnt, 1, 1, control_mask=0x00000800)
    pcs = struct.pack("<II", 0, 0)
    pls = _build_pls(char_cnt, vpos=vpos)

    out = _pack_record(HWPTAG_PARA_HEADER, level, ph)
    out += _pack_record(HWPTAG_PARA_TEXT, level + 1, pt_payload)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 1, pcs)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 1, pls)

    # 2. CTRL_HEADER 'fn  '/'en  ' (20B)
    ctrl_payload = ctrl_id_bytes
    ctrl_payload += struct.pack("<I", ref_num)             # number (u32, 1-based)
    ctrl_payload += struct.pack("<H", 0)                   # beforeDecorationLetter
    ctrl_payload += struct.pack("<H", 0x0029)              # afterDecorationLetter = ')'
    ctrl_payload += struct.pack("<I", 0)                   # numberShape (0=DIGIT)
    ctrl_payload += struct.pack("<I", 0)                   # instanceId
    out += _pack_record(HWPTAG_CTRL_HEADER, level + 1, ctrl_payload)

    # 3. LIST_HEADER (16B)
    lh = _build_footnote_list_header(1)
    out += _pack_record(HWPTAG_LIST_HEADER, level + 2, lh)

    # 4. Body paragraph with atno auto-number
    out += _build_note_body_paragraph(
        ref_num, body_spans, level + 2,
        font_size_hu, line_spacing_pct, content_width,
        is_endnote=is_endnote,
    )

    line_height = font_size_hu * line_spacing_pct // 100
    return out, line_height


# ---------------------------------------------------------------------------
# 머리글/바닥글 빌더
# ---------------------------------------------------------------------------

_HF_INLINE_CTRL_CODE = 0x0010


def build_hf_inline_anchor(is_footer: bool) -> bytes:
    """Build 16-byte inline ctrl anchor for header/footer in PARA_TEXT."""
    ctrl_id = _CTRL_ID_FOOT if is_footer else _CTRL_ID_HEAD
    buf = struct.pack("<H", _HF_INLINE_CTRL_CODE)
    buf += ctrl_id
    buf += b"\x00" * 8
    buf += struct.pack("<H", _HF_INLINE_CTRL_CODE)
    return buf

_CTRL_ID_HEAD = b"\x64\x61\x65\x68"  # 'head' LE (reversed)
_CTRL_ID_FOOT = b"\x74\x6f\x6f\x66"  # 'foot' LE (reversed)

_APPLY_TO_MAP = {"all": 0, "even": 1, "odd": 2, "first": 0}


def build_header_footer(
    spans: list[TextSpan],
    is_footer: bool = False,
    apply_to: str = "all",
    level: int = 1,
    font_size_hu: int = 1000,
    line_spacing_pct: int = 160,
    content_width: int = 42520,
) -> bytes:
    """Build header/footer CTRL_HEADER + LIST_HEADER + content paragraph.

    Record tree:
      CTRL_HEADER 'head'/'foot' (level)     — 12 bytes
        LIST_HEADER (level+1)                — 34 bytes
        PARA_HEADER (level+1)                — content paragraph
          PARA_TEXT (level+2)
          PARA_CHAR_SHAPE (level+2)
          PARA_LINE_SEG (level+2)
    """
    ctrl_id = _CTRL_ID_FOOT if is_footer else _CTRL_ID_HEAD
    attr = _APPLY_TO_MAP.get(apply_to, 0)
    ctrl_payload = ctrl_id + struct.pack("<II", 0, attr)
    out = _pack_record(HWPTAG_CTRL_HEADER, level, ctrl_payload)

    hf_height = font_size_hu * line_spacing_pct // 100
    lh = struct.pack("<HH", 1, 0)
    lh += struct.pack("<I", 0)
    lh += struct.pack("<I", content_width)
    lh += struct.pack("<I", hf_height)
    lh += b"\x00" * 18
    out += _pack_record(HWPTAG_LIST_HEADER, level + 1, lh)

    text = _sanitize_text("".join(s.text for s in spans)) if spans else ""
    pt = text.encode("utf-16-le") + b"\x0d\x00"
    char_cnt = len(pt) // 2
    first_cs = spans[0].cs_id if spans else 0
    pcs = struct.pack("<II", 0, first_cs)
    pls = _build_pls(char_cnt, vpos=0, h=font_size_hu,
                     line_spacing_pct=line_spacing_pct)
    ph = _build_para_header(char_cnt, 1, 1, is_last=True)

    out += _pack_record(HWPTAG_PARA_HEADER, level + 1, ph)
    if text:
        out += _pack_record(HWPTAG_PARA_TEXT, level + 2, pt)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 2, pcs)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 2, pls)
    return out


# ---------------------------------------------------------------------------
# 이미지 (GSO) 빌더
# ---------------------------------------------------------------------------

_SHAPE_TYPE_PIC = b"\x63\x69\x70\x24"   # '$pic' reversed
_SHAPE_TYPE_REC = b"\x63\x65\x72\x24"   # '$rec' reversed

_GSO_CTRL_ATTR = 0x040A2311
_GSO_INST_COUNTER = 0x70000001


def _next_gso_instance_id() -> int:
    global _GSO_INST_COUNTER
    val = _GSO_INST_COUNTER
    _GSO_INST_COUNTER += 1
    return val


_GSO_CTRL_ATTR_FLOATING = 0x040A2310  # reference HWP: square flow, floating

_FLOW_REV = {"float": 0, "block": 1, "back": 2, "front": 3}
_TEXT_SIDE_REV = {"both": 0, "left": 1, "right": 2, "larger": 3}
_VRELTO_REV = {"paper": 0, "page": 1, "paragraph": 2}
_HRELTO_REV = {"paper": 0, "page": 1, "column": 2, "paragraph": 3}
_VALIGN_REV = {"top": 0, "middle": 1, "bottom": 2}
_HALIGN_REV = {"left": 0, "center": 1, "right": 2, "inside": 3, "outside": 4}
_WIDTH_RELTO_REV = {"paper": 0, "page": 1, "column": 2, "paragraph": 3, "absolute": 4}
_HEIGHT_RELTO_REV = {"paper": 0, "page": 1, "absolute": 2}


def _build_gso_attr(position=None, like_char: bool = True, flow: str | None = None,
                    floating: bool = False) -> int:
    """Build GSO attr bitmask from PositionInfo fields."""
    if position is None:
        if flow == 'back':
            return 0x00404000
        elif floating:
            return 0x046A0000
        return _GSO_CTRL_ATTR

    lc = position.like_char if position.like_char is not None else like_char
    attr = 1 if lc else 0
    if position.affect_line_spacing:
        attr |= (1 << 2)
    attr |= _VRELTO_REV.get(position.vrelto or "paragraph", 2) << 3
    attr |= _VALIGN_REV.get(position.valign or "top", 0) << 5
    attr |= _HRELTO_REV.get(position.hrelto or "paragraph", 3) << 8
    attr |= _HALIGN_REV.get(position.halign or "left", 0) << 10
    if position.restrict_in_page:
        attr |= (1 << 13)
    if position.overlap_others:
        attr |= (1 << 14)
    attr |= _WIDTH_RELTO_REV.get(position.width_relto or "absolute", 4) << 15
    attr |= _HEIGHT_RELTO_REV.get(position.height_relto or "absolute", 2) << 18
    flow_val = position.flow or flow
    attr |= _FLOW_REV.get(flow_val or "float", 0) << 21
    attr |= _TEXT_SIDE_REV.get(position.text_side or "both", 0) << 24
    return attr


def _build_gso_ctrl_header(
    width: int, height: int,
    x_offset: int = 0, y_offset: int = 0,
    floating: bool = False, flow: str | None = None,
    position=None,
) -> bytes:
    """CTRL_HEADER 'gso ' 페이로드 (44B).

    position: PositionInfo로부터 attr/offset/margins를 동적 조합.
    """
    inst_id = _next_gso_instance_id()
    attr = _build_gso_attr(position, flow=flow, floating=floating)

    if position and (position.x is not None or position.y is not None):
        x_off = round((position.x or 0) * 100)
        y_off = round((position.y or 0) * 100)
    else:
        x_off = x_offset
        y_off = y_offset

    z_order = 0
    if position and position.z_order is not None:
        z_order = position.z_order
    elif flow == 'back':
        z_order = 4

    m_left = m_right = m_top = m_bottom = 0
    if position:
        m_left = round((position.margin_left or 0) * 100)
        m_right = round((position.margin_right or 0) * 100)
        m_top = round((position.margin_top or 0) * 100)
        m_bottom = round((position.margin_bottom or 0) * 100)

    buf = _CTRL_ID_GSO
    buf += struct.pack("<I", attr)
    buf += struct.pack("<ii", y_off, x_off)
    buf += struct.pack("<II", width, height)
    buf += struct.pack("<i", z_order)
    buf += struct.pack("<2H", m_left, m_right)
    buf += struct.pack("<2H", m_top, m_bottom)
    buf += struct.pack("<I", inst_id)
    buf += struct.pack("<H", 0)                # preventPageBreak
    buf += struct.pack("<H", 0)                # descriptionLen
    assert len(buf) == 44
    return (buf, inst_id)


_SHAPE_TYPE_CON = b"\x6e\x6f\x63\x24"   # '$con' reversed




def _build_shape_component_con(
    width: int, height: int, inst_id: int | None = None,
    n_children: int = 1, child_types: list[bytes] | None = None,
    rotation: float = 0.0,
) -> bytes:
    """Build $con SHCOMP (top-level): gsoId×2 + CommonPart + children + instId."""
    if child_types is None:
        child_types = [b"cip$"]
    base = 196  # 8(gsoId×2) + 42(common) + 146(renderingInfo with count=1)
    total = base + 2 + 4 * n_children + 4
    buf = bytearray(total)
    o = 0
    buf[o:o+4] = _SHAPE_TYPE_CON; o += 4
    buf[o:o+4] = _SHAPE_TYPE_CON; o += 4
    struct.pack_into("<i", buf, o, 0); o += 4        # OffsetX
    struct.pack_into("<i", buf, o, 0); o += 4        # OffsetY
    struct.pack_into("<H", buf, o, 0); o += 2        # GroupingCount
    struct.pack_into("<H", buf, o, 1); o += 2        # LocalFileVersion
    struct.pack_into("<I", buf, o, width); o += 4
    struct.pack_into("<I", buf, o, height); o += 4
    struct.pack_into("<I", buf, o, width); o += 4
    struct.pack_into("<I", buf, o, height); o += 4
    struct.pack_into("<I", buf, o, 0x00080000); o += 4
    rot_angle = round(rotation * 10) if rotation else 0
    struct.pack_into("<H", buf, o, rot_angle & 0xFFFF); o += 2  # RotAngle
    struct.pack_into("<i", buf, o, width // 2); o += 4
    struct.pack_into("<i", buf, o, height // 2); o += 4
    struct.pack_into("<H", buf, o, 1); o += 2        # RenderingInfo count=1
    struct.pack_into("<d", buf, o, 1.0); struct.pack_into("<d", buf, o + 32, 1.0); o += 48
    struct.pack_into("<d", buf, o, 1.0); struct.pack_into("<d", buf, o + 32, 1.0); o += 48
    struct.pack_into("<d", buf, o, 1.0); struct.pack_into("<d", buf, o + 32, 1.0); o += 48
    assert o == base
    struct.pack_into("<H", buf, o, n_children); o += 2
    for ct in child_types:
        buf[o:o+4] = ct; o += 4
    if inst_id is None:
        inst_id = _next_gso_instance_id()
    struct.pack_into("<I", buf, o, inst_id)
    return bytes(buf)


def _build_shape_component_pic(width: int, height: int, child: bool = False) -> bytes:
    """SHAPE_COMPONENT '$pic' 페이로드.

    child=False → 196B top-level (nPairs=1)
    child=True  → variable size (nPairs=depth+1)
    """
    n_pairs = 1
    grp_cnt = 0
    base = 4 + (0 if child else 4) + 8 + 2 + 2 + 16 + 4 + 2 + 8 + 2
    mat_bytes = 48 * (1 + 2 * n_pairs)
    size = base + mat_bytes
    buf = bytearray(size)
    o = 0
    struct.pack_into("<4s", buf, o, _SHAPE_TYPE_PIC); o += 4
    if not child:
        struct.pack_into("<4s", buf, o, _SHAPE_TYPE_PIC); o += 4
    struct.pack_into("<i", buf, o, 0); o += 4        # OffsetX
    struct.pack_into("<i", buf, o, 0); o += 4        # OffsetY
    struct.pack_into("<H", buf, o, grp_cnt); o += 2  # GroupingCount
    struct.pack_into("<H", buf, o, 1); o += 2        # LocalFileVersion
    struct.pack_into("<I", buf, o, width); o += 4    # WidthAtCreate
    struct.pack_into("<I", buf, o, height); o += 4   # HeightAtCreate
    struct.pack_into("<I", buf, o, width); o += 4    # WidthAtCurrent
    struct.pack_into("<I", buf, o, height); o += 4   # HeightAtCurrent
    struct.pack_into("<I", buf, o, 0x00080000 if child else 0x24080000); o += 4  # Property
    struct.pack_into("<H", buf, o, 0); o += 2        # RotateAngle
    struct.pack_into("<i", buf, o, width // 2); o += 4   # RotateXCenter
    struct.pack_into("<i", buf, o, height // 2); o += 4  # RotateYCenter
    struct.pack_into("<H", buf, o, n_pairs); o += 2
    for _ in range(1 + 2 * n_pairs):
        struct.pack_into("<d", buf, o, 1.0)
        struct.pack_into("<d", buf, o + 32, 1.0)
        o += 48
    assert o == size, f"Expected {size}, got {o}"
    return bytes(buf)


def _build_shape_pic_payload(
    width: int, height: int, bin_item_id: int,
    orig_width: int = 0, orig_height: int = 0,
) -> bytes:
    """SHAPE_COMPONENT_PIC 페이로드.

    Layout:
      0-3:   borderColor (0)
      4-7:   borderThickness (0)
      8-11:  borderProperty (0 = no border)
      12-15: leftTopX (0)
      16-19: leftTopY (0)
      20-23: rightTopX (width)
      24-27: rightTopY (0)
      28-31: rightBottomX (width)
      32-35: rightBottomY (height)
      36-39: leftBottomX (0)
      40-43: leftBottomY (height)
      44-47: leftAfterCutting (0)
      48-51: topAfterCutting (0)
      52-55: rightAfterCutting (width)
      56-59: bottomAfterCutting (height)
      60-63: brightness (0)
      64-67: contrast (0)
      68-70: effect + padding (3B)
      71-72: binItemId (uint16 LE)
      73:    borderTransparency (0)
      74-77: instanceId (counter-based)
      78-81: imageTransparency (0)
      82-85: brightImageWidth (orig pixel dims)
      86-89: brightImageHeight (orig pixel dims)
    """
    bw = orig_width if orig_width else width
    bh = orig_height if orig_height else height
    buf = bytearray(90)
    struct.pack_into("<I", buf, 0, 0)              # borderColor
    struct.pack_into("<I", buf, 4, 0)              # borderThickness
    struct.pack_into("<I", buf, 8, 0)              # borderProperty
    struct.pack_into("<i", buf, 12, 0)             # leftTopX
    struct.pack_into("<i", buf, 16, 0)             # leftTopY
    struct.pack_into("<i", buf, 20, width)         # rightTopX
    struct.pack_into("<i", buf, 24, 0)             # rightTopY
    struct.pack_into("<i", buf, 28, width)         # rightBottomX
    struct.pack_into("<i", buf, 32, height)        # rightBottomY
    struct.pack_into("<i", buf, 36, 0)             # leftBottomX
    struct.pack_into("<i", buf, 40, height)        # leftBottomY
    struct.pack_into("<i", buf, 44, 0)             # leftAfterCutting
    struct.pack_into("<i", buf, 48, 0)             # topAfterCutting
    struct.pack_into("<i", buf, 52, width)         # rightAfterCutting
    struct.pack_into("<i", buf, 56, height)        # bottomAfterCutting
    struct.pack_into("<I", buf, 60, 0)             # brightness
    struct.pack_into("<I", buf, 64, 0)             # contrast
    struct.pack_into("<B", buf, 68, 0)             # effect
    # 69-70: padding
    struct.pack_into("<H", buf, 71, bin_item_id)   # binItemId (spec offset 71)
    struct.pack_into("<B", buf, 73, 0)             # borderTransparency
    struct.pack_into("<I", buf, 74, _next_gso_instance_id())  # instanceId
    struct.pack_into("<I", buf, 78, 0)             # imageTransparency
    struct.pack_into("<I", buf, 82, bw)            # brightImageWidth
    struct.pack_into("<I", buf, 86, bh)            # brightImageHeight
    return bytes(buf)



# Template-based $con builder (from original 11차시 HWP)
def build_image(
    bin_item_id: int,
    img_width: int,
    img_height: int,
    vpos: int,
    level: int = 0,
    font_size_hu: int = 1000,
    line_spacing_pct: int = 160,
    orig_width: int = 0,
    orig_height: int = 0,
    x_offset: int = 0,
    y_offset: int = 0,
    flow: str | None = None,
    position=None,
) -> tuple[bytes, int]:
    """Build an image record set (host paragraph + CTRL_HEADER + SHAPE_COMPONENT + PIC).

    Parameters
    ----------
    bin_item_id : int
        1-based BIN_DATA index referenced in SHAPE_COMPONENT_PIC.
    img_width : int
        Display width in HWPUNIT.
    img_height : int
        Display height in HWPUNIT.
    vpos : int
        Vertical position in HWPUNIT.
    level : int, default 0
        Record nesting level.
    font_size_hu : int, default 1000
        Font size in HWPUNIT.
    line_spacing_pct : int, default 160
        Line spacing percentage.
    orig_width : int, default 0
        Original image width in HWPUNIT (for PIC brightImageWidth).
    orig_height : int, default 0
        Original image height in HWPUNIT (for PIC brightImageHeight).
    x_offset : int, default 0
        Horizontal offset in HWPUNIT.
    y_offset : int, default 0
        Vertical offset in HWPUNIT.

    Returns
    -------
    tuple[bytes, int]
        Record bytes and paragraph height in HWPUNIT.
    """
    # 1. Host paragraph with inline ctrl marker
    inline_obj = _build_inline_ctrl_obj(_CTRL_CODE_GSO, _CTRL_ID_GSO)
    pt_payload = inline_obj + b"\x0d\x00"
    char_cnt = len(pt_payload) // 2
    ph = _build_para_header(char_cnt, 1, 1, control_mask=0x00000800)
    pcs = struct.pack("<II", 0, 0)
    is_floating = x_offset != 0 or y_offset != 0 or flow in ('back', 'front')
    pls = _build_pls(char_cnt, vpos=vpos)

    out = _pack_record(HWPTAG_PARA_HEADER, level, ph)
    out += _pack_record(HWPTAG_PARA_TEXT, level + 1, pt_payload)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 1, pcs)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 1, pls)

    # 2. CTRL_HEADER 'gso ' (44B)
    ctrl_pay, ctrl_inst_id = _build_gso_ctrl_header(
        img_width, img_height, x_offset=x_offset, y_offset=y_offset,
        floating=is_floating, flow=flow, position=position)
    out += _pack_record(HWPTAG_CTRL_HEADER, level + 1, ctrl_pay)

    if flow == 'back':
        con_pay = _build_shape_component_con(
            img_width, img_height, inst_id=ctrl_inst_id)
        out += _pack_record(HWPTAG_SHAPE_COMPONENT, level + 2, con_pay)
        out += _pack_record(HWPTAG_SHAPE_COMPONENT, level + 3,
                            _build_shape_component_pic(img_width, img_height, child=True))
        out += _pack_record(HWPTAG_SHAPE_COMPONENT_PIC, level + 4,
                            _build_shape_pic_payload(img_width, img_height, bin_item_id,
                                                     orig_width, orig_height))
    else:
        out += _pack_record(HWPTAG_SHAPE_COMPONENT, level + 2,
                            _build_shape_component_pic(img_width, img_height))
        out += _pack_record(HWPTAG_SHAPE_COMPONENT_PIC, level + 3,
                            _build_shape_pic_payload(img_width, img_height, bin_item_id,
                                                     orig_width, orig_height))

    line_height = font_size_hu * line_spacing_pct // 100
    if flow == 'back':
        return out, 0
    return out, max(line_height, img_height)


def _build_textbox_list_header(width: int, height: int) -> bytes:
    """LIST_HEADER for textbox content (33B, matching real HWP files)."""
    buf = struct.pack("<I", 1)                      # nPara
    buf += struct.pack("<I", 0x00000020)             # listFlags
    buf += struct.pack("<4H", 283, 283, 283, 283)   # margins
    buf += struct.pack("<I", width)                  # textWidth
    buf += b"\x00" * 13                              # reserved/padding
    return buf


def _build_shape_rect_payload(
    width: int, height: int, round_corner: int = 0,
) -> bytes:
    """SHAPE_COMPONENT_RECT payload (33B: round corner + 4 corner points + fill byte)."""
    buf = bytearray(33)
    struct.pack_into("<I", buf, 0, round_corner)
    struct.pack_into("<i", buf, 4, 0)              # leftTopX
    struct.pack_into("<i", buf, 8, 0)              # leftTopY
    struct.pack_into("<i", buf, 12, width)          # rightTopX
    struct.pack_into("<i", buf, 16, 0)              # rightTopY
    struct.pack_into("<i", buf, 20, width)          # rightBottomX
    struct.pack_into("<i", buf, 24, height)         # rightBottomY
    struct.pack_into("<i", buf, 28, 0)              # leftBottomX
    buf[32] = 0                                     # fill type (0=none)
    return bytes(buf)


def _css_hex_to_rgb(color: str) -> tuple[int, int, int]:
    """'#RRGGBB' → (r, g, b)."""
    c = color.lstrip("#")
    if len(c) >= 6:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return 0, 0, 0


def _build_fill_line_bytes(
    fill_color: str | None,
    line_color: str | None,
    line_width_pt: float | None,
) -> bytes:
    """Build fill + line style bytes to append after SHAPE_COMPONENT payload.

    Simplified version: solid fill + solid line only.
    Layout (appended to SHAPE_COMPONENT payload BEFORE the matrices):
      LineShape: 10 bytes (color(4) + width(4) + style(1) + endcap(1))
      Fill: 1 byte type + variable payload
    This is a simplified serialization that matches common real HWP files.
    """
    buf = b""
    if line_color:
        r, g, b = _css_hex_to_rgb(line_color)
        lc = struct.pack("<I", r | (g << 8) | (b << 16))
        lw = struct.pack("<I", round((line_width_pt or 0.4) * 100))
        buf += lc + lw + b"\x00\x00"
    if fill_color:
        r, g, b = _css_hex_to_rgb(fill_color)
        fc = r | (g << 8) | (b << 16)
        buf += struct.pack("<I", fc)
    return buf


def _build_rec_shcomp(
    width: int, height: int,
    line_color: str | None = None,
    fill_color: str | None = None,
    x_offset: int = 0,
    y_offset: int = 0,
    rotation: float = 0.0,
) -> bytes:
    """Build a template-based $rec SHAPE_COMPONENT (252B) with patched dimensions/colors."""
    buf = bytearray(252)
    buf[0:4] = _SHAPE_TYPE_REC
    buf[4:8] = _SHAPE_TYPE_REC
    struct.pack_into("<i", buf, 8, x_offset)     # OffsetX (hwplib CommonPart)
    struct.pack_into("<i", buf, 12, y_offset)    # OffsetY
    rot_angle = round(rotation * 10) if rotation else 0  # degrees × 10
    struct.pack_into("<H", buf, 16, rot_angle & 0xFFFF)  # rotAngle
    struct.pack_into("<H", buf, 18, 1)           # nGrp (actually LocalFileVersion)
    struct.pack_into("<I", buf, 20, width)        # initW
    struct.pack_into("<I", buf, 24, height)       # initH
    struct.pack_into("<I", buf, 28, width)        # curW
    struct.pack_into("<I", buf, 32, height)       # curH
    struct.pack_into("<I", buf, 36, 0x01080000)   # prop (fill always present)
    struct.pack_into("<i", buf, 42, width // 2)   # rotCX
    struct.pack_into("<i", buf, 46, height // 2)  # rotCY
    struct.pack_into("<H", buf, 50, 1)            # nPairs
    struct.pack_into("<d", buf, 52, 1.0)
    struct.pack_into("<d", buf, 84, 1.0)
    struct.pack_into("<d", buf, 100, 1.0)
    struct.pack_into("<d", buf, 132, 1.0)
    struct.pack_into("<d", buf, 148, 1.0)
    struct.pack_into("<d", buf, 180, 1.0)
    extra_off = 196
    if line_color:
        r, g, b = _css_hex_to_rgb(line_color)
        struct.pack_into("<BBBB", buf, extra_off, r, g, b, 0)
    else:
        struct.pack_into("<I", buf, extra_off, 0)
    struct.pack_into("<I", buf, extra_off + 4, 0x00000021)
    struct.pack_into("<I", buf, extra_off + 8, 0xD1000041)
    struct.pack_into("<I", buf, extra_off + 12, 0x00000100)
    if fill_color:
        r, g, b = _css_hex_to_rgb(fill_color)
        struct.pack_into("<BBBB", buf, extra_off + 16, 0, r, g, b)
    else:
        struct.pack_into("<BBBB", buf, extra_off + 16, 0, 0xFF, 0xFF, 0xFF)
    struct.pack_into("<I", buf, extra_off + 20, 0x00999999)
    struct.pack_into("<I", buf, extra_off + 24, 0xFFFFFFFF)
    buf[extra_off + 28:extra_off + 56] = b'\x00' * 28
    return bytes(buf)


def build_textbox_shape(
    content_records: bytes,
    width: int,
    height: int,
    vpos: int,
    fill_color: str | None = None,
    line_color: str | None = None,
    line_width_pt: float | None = None,
    level: int = 0,
    font_size_hu: int = 1000,
    line_spacing_pct: int = 160,
    x_offset: int = 0,
    y_offset: int = 0,
    floating: bool = False,
    position=None,
    tb_padding: tuple[int, int, int, int] | None = None,
    tb_vertical_align: str | None = None,
) -> tuple[bytes, int]:
    """Build a GSO textbox rectangle with two SHAPE_COMPONENTs (template-based)."""
    inline_obj = _build_inline_ctrl_obj(_CTRL_CODE_GSO, _CTRL_ID_GSO)
    pt_payload = inline_obj + b"\x0d\x00"
    char_cnt = len(pt_payload) // 2
    ph = _build_para_header(char_cnt, 1, 1, control_mask=0x00000800)
    pcs = struct.pack("<II", 0, 0)
    pls = _build_pls(char_cnt, vpos=vpos)

    out = _pack_record(HWPTAG_PARA_HEADER, level, ph)
    out += _pack_record(HWPTAG_PARA_TEXT, level + 1, pt_payload)
    out += _pack_record(HWPTAG_PARA_CHAR_SHAPE, level + 1, pcs)
    out += _pack_record(HWPTAG_PARA_LINE_SEG, level + 1, pls)

    ctrl_pay, _ = _build_gso_ctrl_header(width, height,
                                          x_offset=x_offset, y_offset=y_offset,
                                          floating=floating, position=position)
    out += _pack_record(HWPTAG_CTRL_HEADER, level + 1, ctrl_pay)

    # Single SHAPE_COMPONENT $rec (matching reference)
    rot = position.rotation if position and position.rotation else 0.0
    shcomp = _build_rec_shcomp(width, height, line_color=line_color, fill_color=fill_color, rotation=rot)
    out += _pack_record(HWPTAG_SHAPE_COMPONENT, level + 2, shcomp)

    # Count paragraphs in content for nPara
    n_para = 0
    pos = 0
    while pos + 4 <= len(content_records):
        hdr = struct.unpack_from('<I', content_records, pos)[0]
        tag = hdr & 0x3FF
        sz = (hdr >> 20) & 0xFFF
        if sz == 0xFFF:
            sz = struct.unpack_from('<I', content_records, pos + 4)[0]
            pos += 8
        else:
            pos += 4
        if tag == HWPTAG_PARA_HEADER:
            n_para += 1
        pos += sz
    n_para = max(1, n_para)

    # LIST_HEADER (33B — Hancom reference)
    lh = bytearray(33)
    struct.pack_into("<I", lh, 0, n_para)                  # nPara
    tb_va = _CELL_VALIGN.get(tb_vertical_align or "top", 0)
    struct.pack_into("<I", lh, 4, 0x00000020 | (tb_va << 2))  # flags
    pad = tb_padding or (285, 285, 285, 285)
    struct.pack_into("<4H", lh, 8, pad[0], pad[1], pad[2], pad[3])
    struct.pack_into("<I", lh, 16, width)                  # textWidth
    out += _pack_record(HWPTAG_LIST_HEADER, level + 3, bytes(lh))

    # Content at level+3 (same as LIST_HEADER)
    out += _bump_record_levels(content_records, level + 3)

    # RECT (33B template) at level+3
    rect = bytearray(33)
    struct.pack_into("<I", rect, 0, 0)                     # roundCorner
    struct.pack_into("<i", rect, 4, 0)
    struct.pack_into("<i", rect, 8, width)
    struct.pack_into("<i", rect, 12, 0)
    struct.pack_into("<i", rect, 16, width)
    struct.pack_into("<i", rect, 20, height)
    struct.pack_into("<i", rect, 24, 0)
    struct.pack_into("<i", rect, 28, height)
    out += _pack_record(HWPTAG_SHAPE_COMPONENT_RECT, level + 3, bytes(rect))

    line_height = font_size_hu * line_spacing_pct // 100
    if floating:
        return out, 0
    return out, max(line_height, height)


# ---------------------------------------------------------------------------
# 섹션 빌더 공개 API
# ---------------------------------------------------------------------------


def build_section(para_list: list[bytes], term_vpos: int = 0) -> bytes:
    """Concatenate paragraph record bytes and append a termination paragraph.

    Parameters
    ----------
    para_list : list[bytes]
        List of serialized paragraph record bytes.
    term_vpos : int, default 0
        Vertical position for the termination paragraph.

    Returns
    -------
    bytes
        Complete section stream bytes.
    """
    out = b"".join(para_list)
    out += build_term_paragraph(vpos=term_vpos)
    return out
