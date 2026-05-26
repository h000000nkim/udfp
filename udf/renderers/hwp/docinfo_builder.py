"""DocInfo 스트림 빌더 — From Scratch 모드용.

seed DocInfo에서 DOCUMENT_PROPERTIES / FACE_NAME / BORDER_FILL / TAB_DEF /
NUMBERING / STYLE 레코드는 그대로 유지하고, CHAR_SHAPE / PARA_SHAPE 레코드만
교체 후 ID_MAPPINGS 카운트를 갱신하여 반환한다.

CharShape 바이너리 레이아웃 (74 bytes):
  0-13   face_id[7]: uint16[7]
  14-20  ratio[7]: uint8[7]       (0–100, 언어별 장평)
  21-27  char_spacing[7]: int8[7]
  28-34  rel_size[7]: uint8[7]
  35-41  char_offset[7]: int8[7]
  42-45  base_size: int32 (HWPUNIT, 1pt = 100, default=1000)
  46-49  attr: uint32
           bit0=italic, bit1=bold
           bits2-3=underline_type (0=none,1=bottom,3=top)
           bits4-7=underline_shape
           bits8-10=outline_type
           bits11-12=shadow_type
           bits18-20=strikethrough (≥2=active)
  50     shadow_offset_x: int8
  51     shadow_offset_y: int8
  52-55  text_color: uint32 (0x00RRGGBB)
  56-59  underline_color: uint32
  60-63  shade_color: uint32 (0xFFFFFF=흰색=음영없음)
  64-67  shadow_color: uint32 (default=0xB2B2B2)
  68-69  border_fill_id: uint16
  70-73  strike_color: uint32

ParaShape 바이너리 레이아웃 (88 bytes):
  0-3    attr: uint32  (alignment = bits 2-4: 0=justify, 1=left, 2=right, 3=center)
  4-27   margins/spacing: uint32[6] (left, right, top, bot, first, line_spacing)
  28-87  기타 (0으로 채움)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from udf.parsers.hwp.records import (
    HWPTAG_BIN_DATA,
    HWPTAG_BORDER_FILL,
    HWPTAG_CHAR_SHAPE,
    HWPTAG_DOC_DATA,
    HWPTAG_DOCUMENT_PROPERTIES,
    HWPTAG_FACE_NAME,
    HWPTAG_ID_MAPPINGS,
    HWPTAG_NUMBERING,
    HWPTAG_PARA_SHAPE,
    HWPTAG_STYLE,
    HWPTAG_TAB_DEF,
    iter_records,
)

# ID_MAPPINGS 내 카운트 오프셋 (index × 4)
# [0]=BinData, [1-7]=FaceName×7, [8]=BF, [9]=CS, [10]=TabDef,
# [11]=Numbering, [12]=Bullet, [13]=PS, [14]=Style
_IDMAP_BINDATA_OFF = 0
_IDMAP_BORDERFILL_OFF = 32
_IDMAP_CHARSHAPE_OFF = 36
_IDMAP_PARASHAPE_OFF = 52

# 정렬 값 → attr bits 2-4
_ALIGN_ATTR = {"justify": 0, "left": 1, "right": 2, "center": 3, "distribute": 4, "divide": 5}

# 테이블 셀용 BorderFill: 4면 실선 1px 검정, 채움 없음 (f04_simple_table BF[3] 참조)
_TABLE_CELL_BF = (
    b"\x00\x00"                    # attr
    b"\x01\x01\x00\x00\x00\x00"   # left border: type=solid, width=1, color=black
    b"\x01\x01\x00\x00\x00\x00"   # right border
    b"\x01\x01\x00\x00\x00\x00"   # top border
    b"\x01\x01\x00\x00\x00\x00"   # bottom border
    b"\x01\x00"                    # diagonal_type=none
    b"\x00\x00\x00\x00"           # diagonal_color
    b"\x00\x00\x00\x00\x00\x00\x00\x00"  # fill info (none)
)

# 유지할 태그 (CharShape/ParaShape/ID_MAPPINGS 제외)
_KEEP_TAGS = frozenset(
    [
        HWPTAG_DOCUMENT_PROPERTIES,
        HWPTAG_FACE_NAME,
        HWPTAG_BORDER_FILL,
        HWPTAG_TAB_DEF,
        HWPTAG_NUMBERING,
        HWPTAG_STYLE,
        HWPTAG_DOC_DATA,
        31,  # COMPATIBLE_DOCUMENT
        32,  # LAYOUT_COMPATIBILITY
        94,  # unknown (보존)
        30,  # DOC_DATA
        28,  # DISTRIBUTE_DOC_DATA
    ]
)


# ---------------------------------------------------------------------------
# 스펙 dataclass
# ---------------------------------------------------------------------------


@dataclass
class CharShapeSpec:
    face_hangul: int = 0
    face_latin: int = 0
    size_pt: float = 10.0
    bold: bool = False
    italic: bool = False
    underline: int = 0   # 0=없음 1=실선 2=점선 3=파선 4=물결 5=이중
    strikethrough: bool = False
    color_r: int = 0
    color_g: int = 0
    color_b: int = 0
    font_name: str | None = None


@dataclass
class BinDataSpec:
    bin_data_id: int     # binDataId for OLE stream naming: BIN{id:04X}.{ext}
    extension: str       # "jpg", "png", "gif", etc.


@dataclass
class BorderFillSpec:
    has_borders: bool = True
    border_type: int = 1    # 1=solid
    border_width: int = 1   # width code
    border_r: int = 0
    border_g: int = 0
    border_b: int = 0
    has_fill: bool = False
    fill_r: int = 255
    fill_g: int = 255
    fill_b: int = 255


@dataclass
class ParaShapeSpec:
    alignment: str = "left"          # left | right | center | justify
    line_spacing: int = 160          # % (예: 160 = 160%)
    indent_left: int = 0             # HWPUNIT
    indent_right: int = 0
    space_before: int = 0
    space_after: int = 0
    indent_first: int = 0


# ---------------------------------------------------------------------------
# 바이너리 직렬화
# ---------------------------------------------------------------------------


def pack_char_shape(spec: CharShapeSpec) -> bytes:
    """Serialize a CharShapeSpec into a 74-byte CharShape record payload.

    Parameters
    ----------
    spec : CharShapeSpec
        Character shape specification.

    Returns
    -------
    bytes
        74-byte binary payload for the CHAR_SHAPE record.
    """
    attr = 0
    if spec.italic:
        attr |= 0x01                        # bit 0: italic
    if spec.bold:
        attr |= 0x02                        # bit 1: bold
    if spec.underline:
        attr |= (1 & 0x03) << 2            # bits 2-3: underline_type=1 (bottom)
    if spec.strikethrough:
        attr |= (2 << 18)                   # bits 18-20: strikethrough ≥ 2

    text_color = spec.color_r | (spec.color_g << 8) | (spec.color_b << 16)
    base_size = int(spec.size_pt * 100)
    faces = [spec.face_hangul, spec.face_latin,
             spec.face_hangul, spec.face_hangul,
             spec.face_hangul, spec.face_hangul, spec.face_hangul]

    buf = struct.pack("<7H", *faces)          # 0-13   face_ids
    buf += bytes([100] * 7)                   # 14-20  ratio
    buf += bytes([0] * 7)                     # 21-27  char_spacing
    buf += bytes([100] * 7)                   # 28-34  rel_size
    buf += bytes([0] * 7)                     # 35-41  char_offset
    buf += struct.pack("<i", base_size)       # 42-45  base_size (i32)
    buf += struct.pack("<I", attr)            # 46-49  attr
    buf += bytes([0, 0])                      # 50-51  shadow_offset_x, shadow_offset_y
    buf += struct.pack("<I", text_color)      # 52-55  text_color
    buf += struct.pack("<I", 0)               # 56-59  underline_color
    buf += struct.pack("<I", 0x00FFFFFF)      # 60-63  shade_color (흰색=음영없음)
    buf += struct.pack("<I", 0x00B2B2B2)      # 64-67  shadow_color (기본 회색)
    buf += struct.pack("<H", 0)               # 68-69  border_fill_id
    buf += struct.pack("<I", 0)               # 70-73  strike_color
    assert len(buf) == 74
    return buf


def pack_bin_data(spec: BinDataSpec) -> bytes:
    """Serialize a BinDataSpec into a BIN_DATA record payload.

    Parameters
    ----------
    spec : BinDataSpec
        Binary data specification with ID and extension.

    Returns
    -------
    bytes
        Binary payload: flags(uint16) + binDataId(uint16) + extLen(uint16) + ext(UTF-16LE).
    """
    ext_utf16 = spec.extension.encode("utf-16-le")
    ext_len = len(spec.extension)
    buf = struct.pack("<H", 0x0001)         # flags: embedded
    buf += struct.pack("<H", spec.bin_data_id)
    buf += struct.pack("<H", ext_len)
    buf += ext_utf16
    return buf


def pack_border_fill(spec: BorderFillSpec) -> bytes:
    """Serialize a BorderFillSpec into a BORDER_FILL record payload.

    Parameters
    ----------
    spec : BorderFillSpec
        Border and fill specification.

    Returns
    -------
    bytes
        Variable-length payload (40 bytes without fill, 53 bytes with fill).
    """
    buf = struct.pack("<H", 0)  # attr

    if spec.has_borders:
        border_color = spec.border_r | (spec.border_g << 8) | (spec.border_b << 16)
        border_entry = struct.pack("<BB", spec.border_type, spec.border_width)
        border_entry += struct.pack("<I", border_color)
    else:
        border_entry = b"\x00\x00\x00\x00\x00\x00"

    buf += border_entry * 4  # left, right, top, bottom

    buf += b"\x00\x00\x00\x00\x00\x00"  # diagonal (none)

    if spec.has_fill:
        fill_color = spec.fill_r | (spec.fill_g << 8) | (spec.fill_b << 16)
        buf += struct.pack("<I", 1)              # fill_attr: bit 0 = solid fill
        buf += struct.pack("<I", fill_color)     # fg_color (실제 배경색)
        buf += struct.pack("<I", 0x00FFFFFF)     # pattern_color (흰색)
        buf += struct.pack("<i", -1)             # hatch_style: -1 = solid (패턴 없음)
        buf += b"\x00\x00\x00\x00\x00"          # trailing (5B, seed 관찰값)
    else:
        buf += struct.pack("<I", 0)              # fill_attr: no fill
        buf += struct.pack("<I", 0)              # padding

    return buf


def pack_para_shape(spec: ParaShapeSpec) -> bytes:
    """Serialize a ParaShapeSpec into an 88-byte ParaShape record payload.

    Parameters
    ----------
    spec : ParaShapeSpec
        Paragraph shape specification.

    Returns
    -------
    bytes
        88-byte binary payload for the PARA_SHAPE record.
    """
    align_val = _ALIGN_ATTR.get(spec.alignment, 0)
    # attr: bits 2-4 = alignment, bit 7-8 = 0x01 (일반 단락 플래그)
    attr = 0x00000180 | (align_val << 2)

    buf = struct.pack("<I", attr)              # 0-3    attr
    buf += struct.pack(
        "<6I",
        spec.indent_left,
        spec.indent_right,
        spec.space_before,
        spec.space_after,
        spec.indent_first,
        spec.line_spacing,
    )                                          # 4-27   margins/spacing
    buf += bytes(60)                           # 28-87  padding
    assert len(buf) == 88
    return buf


# ---------------------------------------------------------------------------
# 레코드 직렬화 헬퍼
# ---------------------------------------------------------------------------


def _pack_record(tag_id: int, level: int, payload: bytes) -> bytes:
    """Serialize an HWP record header + payload to bytes."""
    size = len(payload)
    if size < 0xFFF:
        h = tag_id | (level << 10) | (size << 20)
        return struct.pack("<I", h) + payload
    h = tag_id | (level << 10) | (0xFFF << 20)
    return struct.pack("<II", h, size) + payload


# ---------------------------------------------------------------------------
# DocInfo 빌더
# ---------------------------------------------------------------------------


def _read_seed_faces(seed_docinfo_bytes: bytes) -> list[int]:
    """seed CS[0]에서 face_id 7개를 읽어 반환한다."""
    for rec in iter_records(seed_docinfo_bytes):
        if rec.tag_id == HWPTAG_CHAR_SHAPE and len(rec.payload) >= 14:
            return list(struct.unpack_from("<7H", rec.payload, 0))
    return [0] * 7


def _count_seed_faces(seed_docinfo_bytes: bytes) -> int:
    """seed DocInfo에서 카테고리당 FaceName 레코드 수를 반환한다."""
    count = 0
    for rec in iter_records(seed_docinfo_bytes):
        if rec.tag_id == HWPTAG_FACE_NAME:
            count += 1
    return count // 7 if count >= 7 else count


def _pack_face_name(name: str) -> bytes:
    """Build a minimal FaceName record payload (property + length + name)."""
    encoded = name.encode("utf-16-le")
    name_len = len(name)
    return struct.pack("<BH", 0x01, name_len) + encoded


_ALIGN_FROM_ATTR = {0: "justify", 1: "left", 2: "right", 3: "center", 4: "distribute", 5: "divide"}


def read_seed_charshapes(seed_docinfo_bytes: bytes) -> list[CharShapeSpec]:
    """Parse CharShape records from seed DocInfo into CharShapeSpec list.

    Parameters
    ----------
    seed_docinfo_bytes : bytes
        Decompressed seed DocInfo stream.

    Returns
    -------
    list[CharShapeSpec]
        Parsed character shape specifications.
    """
    result: list[CharShapeSpec] = []
    for rec in iter_records(seed_docinfo_bytes):
        if rec.tag_id != HWPTAG_CHAR_SHAPE or len(rec.payload) < 56:
            continue
        p = rec.payload
        base_size = struct.unpack_from("<i", p, 42)[0]
        attr = struct.unpack_from("<I", p, 46)[0]
        text_color = struct.unpack_from("<I", p, 52)[0]
        result.append(CharShapeSpec(
            size_pt=base_size / 100.0,
            bold=bool(attr & 0x02),
            italic=bool(attr & 0x01),
            underline=(attr >> 2) & 0x03,
            strikethrough=((attr >> 18) & 0x07) >= 2,
            color_r=text_color & 0xFF,
            color_g=(text_color >> 8) & 0xFF,
            color_b=(text_color >> 16) & 0xFF,
        ))
    return result


def read_seed_parashapes(seed_docinfo_bytes: bytes) -> list[ParaShapeSpec]:
    """Parse ParaShape records from seed DocInfo into ParaShapeSpec list.

    Parameters
    ----------
    seed_docinfo_bytes : bytes
        Decompressed seed DocInfo stream.

    Returns
    -------
    list[ParaShapeSpec]
        Parsed paragraph shape specifications.
    """
    result: list[ParaShapeSpec] = []
    for rec in iter_records(seed_docinfo_bytes):
        if rec.tag_id != HWPTAG_PARA_SHAPE or len(rec.payload) < 28:
            continue
        p = rec.payload
        attr = struct.unpack_from("<I", p, 0)[0]
        align_val = (attr >> 2) & 0x07
        left, right, top, bot, first, line_sp = struct.unpack_from("<6I", p, 4)
        result.append(ParaShapeSpec(
            alignment=_ALIGN_FROM_ATTR.get(align_val, "justify"),
            line_spacing=line_sp,
            indent_left=left,
            indent_right=right,
            space_before=top,
            space_after=bot,
            indent_first=first,
        ))
    return result


def build_docinfo(
    seed_docinfo_bytes: bytes,
    char_shapes: list[CharShapeSpec],
    para_shapes: list[ParaShapeSpec],
    need_table_bf: bool = False,
    bin_data_specs: list[BinDataSpec] | None = None,
    extra_border_fills: list[BorderFillSpec] | None = None,
) -> tuple[bytes, int, int, int]:
    """Rebuild DocInfo by preserving all seed records and appending new ones.

    Seed Style records reference existing CS/PS IDs, so deleting them
    would cause OOB references. This function preserves all seed records
    and appends Document-Model-derived CS/PS/BF/BIN_DATA after them,
    updating ID_MAPPINGS counts accordingly.

    Parameters
    ----------
    seed_docinfo_bytes : bytes
        Decompressed seed DocInfo stream.
    char_shapes : list[CharShapeSpec]
        New CharShape records to append.
    para_shapes : list[ParaShapeSpec]
        New ParaShape records to append.
    need_table_bf : bool, default False
        Whether to prepend a default table-cell BorderFill.
    bin_data_specs : list[BinDataSpec] or None
        Additional BinData records for embedded images.
    extra_border_fills : list[BorderFillSpec] or None
        Additional BorderFill records (appended after table BF).

    Returns
    -------
    tuple[bytes, int, int, int]
        (docinfo_bytes, first_extra_bf_id, seed_cs_count, seed_ps_count).
        Body builder must offset cs_id by seed_cs_count and ps_id by
        seed_ps_count.
    """
    seed_bf_count = 0
    seed_cs_count = 0
    seed_ps_count = 0
    seed_bindata_count = 0

    seed_faces = _read_seed_faces(seed_docinfo_bytes)
    seed_face_per_cat = _count_seed_faces(seed_docinfo_bytes)

    for rec in iter_records(seed_docinfo_bytes):
        if rec.tag_id == HWPTAG_BORDER_FILL:
            seed_bf_count += 1
        elif rec.tag_id == HWPTAG_CHAR_SHAPE:
            seed_cs_count += 1
        elif rec.tag_id == HWPTAG_PARA_SHAPE:
            seed_ps_count += 1
        elif rec.tag_id == HWPTAG_BIN_DATA:
            seed_bindata_count += 1

    first_extra_bf_id = 0
    if need_table_bf:
        first_extra_bf_id = seed_bf_count + 1

    # 새 폰트 → FaceName 레코드 생성 + face_id 매핑
    unique_fonts: list[str] = []
    font_to_face_id: dict[str, int] = {}
    for cs in char_shapes:
        if cs.font_name and cs.font_name not in font_to_face_id:
            face_id = seed_face_per_cat + len(unique_fonts)
            font_to_face_id[cs.font_name] = face_id
            unique_fonts.append(cs.font_name)

    # FaceName은 카테고리별로 정렬되어야 하므로,
    # 각 카테고리의 마지막 시드 FaceName 뒤에 새 폰트를 삽입한다.
    # _extra_face_by_cat[cat_idx] = [record bytes for that category]
    _extra_face_by_cat: list[list[bytes]] = [[] for _ in range(7)]
    for fname in unique_fonts:
        payload = _pack_face_name(fname)
        for cat in range(7):
            _extra_face_by_cat[cat].append(_pack_record(HWPTAG_FACE_NAME, 1, payload))
    n_new_faces_per_cat = len(unique_fonts)

    # 새 CS에 face_id 적용
    for cs in char_shapes:
        if cs.font_name and cs.font_name in font_to_face_id:
            fid = font_to_face_id[cs.font_name]
            cs.face_hangul = fid
            cs.face_latin = fid
        else:
            cs.face_hangul = seed_faces[0]
            cs.face_latin = seed_faces[1]
    extra_cs = [_pack_record(HWPTAG_CHAR_SHAPE, 1, pack_char_shape(s)) for s in char_shapes]
    extra_ps = [_pack_record(HWPTAG_PARA_SHAPE, 1, pack_para_shape(s)) for s in para_shapes]
    extra_bd = []
    if bin_data_specs:
        extra_bd = [_pack_record(HWPTAG_BIN_DATA, 1, pack_bin_data(s)) for s in bin_data_specs]

    # BorderFill 추가: need_table_bf 먼저, 그 뒤 extra_border_fills
    extra_bf_records: list[bytes] = []
    if need_table_bf:
        extra_bf_records.append(_pack_record(HWPTAG_BORDER_FILL, 1, _TABLE_CELL_BF))
    if extra_border_fills:
        if not first_extra_bf_id:
            first_extra_bf_id = seed_bf_count + 1
        for bf_spec in extra_border_fills:
            extra_bf_records.append(
                _pack_record(HWPTAG_BORDER_FILL, 1, pack_border_fill(bf_spec))
            )

    # ID_MAPPINGS 카운트는 실제 레코드 수와 반드시 일치해야 한다.
    # 불일치 시 한컴이 "파일이 손상되었습니다" 다이얼로그를 표시한다.
    n_new_cs = len(char_shapes)
    n_new_ps = len(para_shapes)
    n_new_bf = len(extra_bf_records)
    n_new_bd = len(extra_bd)

    out_buf = b""
    _face_cat_idx = 0
    _face_in_cat = 0
    cs_appended = False
    ps_appended = False
    bf_appended = False
    bd_appended = False
    last_cs_seen = False
    last_ps_seen = False
    last_bf_seen = False
    last_bd_seen = False

    for rec in iter_records(seed_docinfo_bytes):
        if rec.tag_id == HWPTAG_ID_MAPPINGS:
            idmap = bytearray(rec.payload)
            if n_new_bd and len(idmap) > _IDMAP_BINDATA_OFF + 3:
                old = struct.unpack_from("<I", idmap, _IDMAP_BINDATA_OFF)[0]
                struct.pack_into("<I", idmap, _IDMAP_BINDATA_OFF, old + n_new_bd)
            # FaceName × 7 categories at offsets 4-28
            if n_new_faces_per_cat:
                for cat_off in range(4, 32, 4):
                    if len(idmap) > cat_off + 3:
                        old = struct.unpack_from("<I", idmap, cat_off)[0]
                        struct.pack_into("<I", idmap, cat_off, old + n_new_faces_per_cat)
            if n_new_bf and len(idmap) > _IDMAP_BORDERFILL_OFF + 3:
                old = struct.unpack_from("<I", idmap, _IDMAP_BORDERFILL_OFF)[0]
                struct.pack_into("<I", idmap, _IDMAP_BORDERFILL_OFF, old + n_new_bf)
            if n_new_cs and len(idmap) > _IDMAP_CHARSHAPE_OFF + 3:
                old = struct.unpack_from("<I", idmap, _IDMAP_CHARSHAPE_OFF)[0]
                struct.pack_into("<I", idmap, _IDMAP_CHARSHAPE_OFF, old + n_new_cs)
            if n_new_ps and len(idmap) > _IDMAP_PARASHAPE_OFF + 3:
                old = struct.unpack_from("<I", idmap, _IDMAP_PARASHAPE_OFF)[0]
                struct.pack_into("<I", idmap, _IDMAP_PARASHAPE_OFF, old + n_new_ps)
            out_buf += _pack_record(rec.tag_id, rec.level, bytes(idmap))
            continue

        if rec.tag_id == HWPTAG_FACE_NAME:
            _face_in_cat += 1
            if _face_in_cat >= seed_face_per_cat and _face_cat_idx < 7:
                out_buf += _pack_record(rec.tag_id, rec.level, rec.payload)
                for r in _extra_face_by_cat[_face_cat_idx]:
                    out_buf += r
                _face_cat_idx += 1
                _face_in_cat = 0
                continue

        if rec.tag_id == HWPTAG_BIN_DATA:
            last_bd_seen = True
        elif last_bd_seen and not bd_appended:
            for r in extra_bd:
                out_buf += r
            bd_appended = True

        if rec.tag_id == HWPTAG_CHAR_SHAPE:
            last_cs_seen = True
        elif last_cs_seen and not cs_appended:
            for r in extra_cs:
                out_buf += r
            cs_appended = True

        if rec.tag_id == HWPTAG_PARA_SHAPE:
            last_ps_seen = True
        elif last_ps_seen and not ps_appended:
            for r in extra_ps:
                out_buf += r
            ps_appended = True

        if rec.tag_id == HWPTAG_BORDER_FILL:
            last_bf_seen = True
        elif last_bf_seen and not bf_appended:
            for r in extra_bf_records:
                out_buf += r
            bf_appended = True

        out_buf += _pack_record(rec.tag_id, rec.level, rec.payload)

    while _face_cat_idx < 7:
        for r in _extra_face_by_cat[_face_cat_idx]:
            out_buf += r
        _face_cat_idx += 1
    if extra_bd and not bd_appended:
        for r in extra_bd:
            out_buf += r
    if extra_bf_records and not bf_appended:
        for r in extra_bf_records:
            out_buf += r
    if not cs_appended:
        for r in extra_cs:
            out_buf += r
    if not ps_appended:
        for r in extra_ps:
            out_buf += r

    return out_buf, first_extra_bf_id, seed_cs_count, seed_ps_count
