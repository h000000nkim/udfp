"""HWPTAG 레코드 디코더 및 태그 상수"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterator

# ---------------------------------------------------------------------------
# 태그 상수 (hwp.md §3 기준, BEGIN=16)
# ---------------------------------------------------------------------------

HWPTAG_BEGIN = 16  # 0x010

# DocInfo 스트림 태그
HWPTAG_DOCUMENT_PROPERTIES = 16
HWPTAG_ID_MAPPINGS = 17
HWPTAG_BIN_DATA = 18
HWPTAG_FACE_NAME = 19
HWPTAG_BORDER_FILL = 20
HWPTAG_CHAR_SHAPE = 21
HWPTAG_TAB_DEF = 22
HWPTAG_NUMBERING = 23
HWPTAG_BULLET = 24
HWPTAG_PARA_SHAPE = 25
HWPTAG_STYLE = 26
HWPTAG_DOC_DATA = 27
HWPTAG_DISTRIBUTE_DOC_DATA = 28
HWPTAG_COMPATIBLE_DOCUMENT = 31
HWPTAG_LAYOUT_COMPATIBILITY = 32

# BodyText 스트림 태그 (BEGIN + offset)
HWPTAG_PARA_HEADER = 66  # BEGIN + 50
HWPTAG_PARA_TEXT = 67  # BEGIN + 51
HWPTAG_PARA_CHAR_SHAPE = 68  # BEGIN + 52
HWPTAG_PARA_LINE_SEG = 69  # BEGIN + 53
HWPTAG_PARA_RANGE_TAG = 70  # BEGIN + 54
HWPTAG_CTRL_HEADER = 71  # BEGIN + 55
HWPTAG_LIST_HEADER = 72  # BEGIN + 56
HWPTAG_PAGE_DEF = 73  # BEGIN + 57
HWPTAG_FOOTNOTE_SHAPE = 74  # BEGIN + 58
HWPTAG_SHAPE_COMPONENT = 76  # BEGIN + 60
HWPTAG_TABLE = 77  # BEGIN + 61
HWPTAG_SHAPE_COMPONENT_LINE = 78  # BEGIN + 62
HWPTAG_SHAPE_COMPONENT_RECT = 79  # BEGIN + 63
HWPTAG_SHAPE_COMPONENT_ELLIPSE = 80  # BEGIN + 64
HWPTAG_SHAPE_COMPONENT_ARC = 81  # BEGIN + 65
HWPTAG_SHAPE_COMPONENT_POLYGON = 82  # BEGIN + 66
HWPTAG_SHAPE_COMPONENT_CURVE = 83  # BEGIN + 67
HWPTAG_SHAPE_COMPONENT_OLE = 84  # BEGIN + 68
HWPTAG_SHAPE_COMPONENT_PIC = 85  # BEGIN + 69
HWPTAG_CTRL_DATA = 90  # BEGIN + 74
HWPTAG_EQEDIT = 88  # BEGIN + 72

# ---------------------------------------------------------------------------
# PARA_TEXT 제어 코드 바이트 소비량 (library-mapping.md 기준)
# ---------------------------------------------------------------------------

# 2바이트 단순 제어 (코드 2바이트만 소비)
_PT_CTRL_2BYTE: frozenset[int] = frozenset({0x0000, 0x0009, 0x000A, 0x000D, 0x001F})

# hwp.md §5.2: 위 집합 외 모든 제어 코드(≤0x001F)는 인라인 오브젝트 (2+14=16바이트 소비)
# 0x001F: 전수분석(28건) 결과 항상 2바이트 소비. 다음 코드 유닛이 한글 텍스트.


@dataclass
class HwpRecord:
    tag_id: int
    level: int
    payload: bytes
    offset: int  # 스트림 내 레코드 시작 오프셋 (헤더 포함)


def iter_records(stream: bytes) -> Iterator[HwpRecord]:
    """압축 해제된 스트림에서 HwpRecord를 순서대로 yield한다."""
    off = 0
    n = len(stream)
    while off + 4 <= n:
        record_start = off
        (h,) = struct.unpack_from("<I", stream, off)
        tag_id = h & 0x3FF
        level = (h >> 10) & 0x3FF
        size = (h >> 20) & 0xFFF
        off += 4
        if size == 0xFFF:
            if off + 4 > n:
                break
            (size,) = struct.unpack_from("<I", stream, off)
            off += 4
        if off + size > n:
            break
        yield HwpRecord(
            tag_id=tag_id,
            level=level,
            payload=stream[off : off + size],
            offset=record_start,
        )
        off += size


def ctrl_id_from_payload(payload: bytes) -> str:
    """CTRL_HEADER 페이로드에서 4바이트 ctrlId를 ASCII 문자열로 반환한다.

    HWP는 ctrlId를 little-endian uint32로 저장하므로 바이트를 역전해야
    human-readable 형태("tbl ", "secd" 등)가 된다.
    """
    if len(payload) < 4:
        return ""
    return payload[:4][::-1].decode("ascii", errors="replace")
