"""HWP R-규칙 자동 수정자.

R1~R4 위반을 감지하고 스트림 수준에서 수정한 뒤 재직렬화한다.
모든 fixer는 압축 해제된 섹션 스트림 bytes를 받아 수정된 bytes를 반환한다.
수정이 불필요하면 원본을 그대로 반환 (멱등성).

준수 사항:
  함정 3: controlMask (PH offset 4) 절대 수정 금지
  함정 5: charCnt MSB 보존 (old_dw & 0x80000000)
"""

from __future__ import annotations

import struct

from udf.parsers.hwp.records import (
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_LINE_SEG,
    HWPTAG_PARA_TEXT,
    HwpRecord,
    iter_records,
)


def _serialize_record(rec: HwpRecord) -> bytes:
    """Serialize a single HwpRecord back to binary."""
    size = len(rec.payload)
    if size < 0xFFF:
        h = rec.tag_id | (rec.level << 10) | (size << 20)
        return struct.pack("<I", h) + rec.payload
    h = rec.tag_id | (rec.level << 10) | (0xFFF << 20)
    return struct.pack("<II", h, size) + rec.payload


def _serialize_records(records: list[HwpRecord]) -> bytes:
    """Serialize a list of HwpRecords back to a contiguous binary stream."""
    return b"".join(_serialize_record(r) for r in records)


def _find_children(
    records: list[HwpRecord], parent_idx: int
) -> dict[int, int | None]:
    """PARA_HEADER의 자식 레코드 인덱스를 태그별로 반환한다."""
    ph_level = records[parent_idx].level
    result: dict[int, int | None] = {
        HWPTAG_PARA_TEXT: None,
        HWPTAG_PARA_CHAR_SHAPE: None,
        HWPTAG_PARA_LINE_SEG: None,
    }
    for j in range(parent_idx + 1, len(records)):
        if records[j].level <= ph_level:
            break
        tag = records[j].tag_id
        if tag in result and result[tag] is None:
            result[tag] = j
    return result


def normalize_para_headers(stream: bytes) -> bytes:
    """Fix R1 and R2 violations by recalculating charCnt, csCount, and lsCount.

    Updates PARA_HEADER fields to match actual PARA_TEXT, PARA_CHAR_SHAPE,
    and PARA_LINE_SEG record lengths. Preserves the charCnt MSB (trap 5)
    and never modifies controlMask (trap 3).

    Parameters
    ----------
    stream : bytes
        Decompressed HWP section stream.

    Returns
    -------
    bytes
        Corrected stream, or the original if no changes were needed.
    """
    records = list(iter_records(stream))
    changed = False

    for i, rec in enumerate(records):
        if rec.tag_id != HWPTAG_PARA_HEADER:
            continue
        if len(rec.payload) < 18:
            continue

        children = _find_children(records, i)
        ph = bytearray(rec.payload)

        # R1: charCnt = len(PT) // 2
        pt_idx = children[HWPTAG_PARA_TEXT]
        if pt_idx is not None:
            pt_len = len(records[pt_idx].payload) // 2
            old_dw = struct.unpack_from("<I", ph, 0)[0]
            old_cnt = old_dw & 0x3FFFFFFF
            if old_cnt != pt_len:
                msb = old_dw & 0x80000000
                struct.pack_into("<I", ph, 0, msb | (pt_len & 0x3FFFFFFF))
                changed = True

        # R2: csCount = len(PCS) // 8
        pcs_idx = children[HWPTAG_PARA_CHAR_SHAPE]
        if pcs_idx is not None:
            expected_cs = len(records[pcs_idx].payload) // 8
            (cs_count,) = struct.unpack_from("<H", ph, 12)
            if cs_count != expected_cs:
                struct.pack_into("<H", ph, 12, expected_cs)
                changed = True

        # R2: lsCount = len(PLS) // 36
        pls_idx = children[HWPTAG_PARA_LINE_SEG]
        if pls_idx is not None:
            expected_ls = len(records[pls_idx].payload) // 36
            (ls_count,) = struct.unpack_from("<H", ph, 16)
            if ls_count != expected_ls:
                struct.pack_into("<H", ph, 16, expected_ls)
                changed = True

        if ph != rec.payload:
            records[i] = HwpRecord(rec.tag_id, rec.level, bytes(ph), rec.offset)

    if not changed:
        return stream
    return _serialize_records(records)


def fix_lineseg_r3(stream: bytes) -> bytes:
    """Fix R3 violations by inserting a minimal PLS entry for text paragraphs.

    When a paragraph has text but no PARA_LINE_SEG record (or an empty
    one), this fixer inserts a single 36-byte PLS entry with default
    height of 400 HWP units (~10pt).

    Parameters
    ----------
    stream : bytes
        Decompressed HWP section stream.

    Returns
    -------
    bytes
        Corrected stream, or the original if no changes were needed.
    """
    records = list(iter_records(stream))
    changed = False

    for i, rec in enumerate(records):
        if rec.tag_id != HWPTAG_PARA_HEADER:
            continue

        children = _find_children(records, i)
        pt_idx = children[HWPTAG_PARA_TEXT]
        if pt_idx is None:
            continue
        if len(records[pt_idx].payload) == 0:
            continue

        pls_idx = children[HWPTAG_PARA_LINE_SEG]
        if pls_idx is not None and len(records[pls_idx].payload) >= 36:
            continue

        # PLS 엔트리 1개 생성 (36 bytes)
        pls_entry = bytearray(36)
        # tpos=0 (offset 0), vpos=0 (offset 4)
        # h=400 (offset 8) — 기본 줄 높이
        struct.pack_into("<I", pls_entry, 8, 400)

        ph_level = rec.level

        if pls_idx is not None:
            records[pls_idx] = HwpRecord(
                HWPTAG_PARA_LINE_SEG,
                records[pls_idx].level,
                bytes(pls_entry),
                records[pls_idx].offset,
            )
        else:
            # PLS 레코드가 아예 없으면 PH 다음 레벨에 삽입
            insert_pos = i + 1
            for j in range(i + 1, len(records)):
                if records[j].level <= ph_level:
                    break
                insert_pos = j + 1
            records.insert(
                insert_pos,
                HwpRecord(
                    HWPTAG_PARA_LINE_SEG,
                    ph_level + 1,
                    bytes(pls_entry),
                    0,
                ),
            )

        # PH lsCount도 갱신
        if len(rec.payload) >= 18:
            ph = bytearray(rec.payload)
            struct.pack_into("<H", ph, 16, 1)
            records[i] = HwpRecord(rec.tag_id, rec.level, bytes(ph), rec.offset)

        changed = True

    if not changed:
        return stream
    return _serialize_records(records)


def fix_oob_charshape(stream: bytes) -> bytes:
    """Fix R4 violations by removing out-of-bounds PCS entries.

    Removes PARA_CHAR_SHAPE entries whose position is >= charCnt.
    If all entries would be removed, the first entry's position is
    reset to 0 to guarantee at least one PCS entry per paragraph.

    Parameters
    ----------
    stream : bytes
        Decompressed HWP section stream.

    Returns
    -------
    bytes
        Corrected stream, or the original if no changes were needed.
    """
    records = list(iter_records(stream))
    changed = False

    for i, rec in enumerate(records):
        if rec.tag_id != HWPTAG_PARA_HEADER:
            continue
        if len(rec.payload) < 18:
            continue

        children = _find_children(records, i)
        pt_idx = children[HWPTAG_PARA_TEXT]
        pcs_idx = children[HWPTAG_PARA_CHAR_SHAPE]
        if pt_idx is None or pcs_idx is None:
            continue

        char_cnt = len(records[pt_idx].payload) // 2
        if char_cnt == 0:
            continue

        pcs = records[pcs_idx].payload
        entries = [pcs[k : k + 8] for k in range(0, len(pcs) - len(pcs) % 8, 8)]
        valid = [e for e in entries if struct.unpack_from("<I", e, 0)[0] < char_cnt]

        if len(valid) == len(entries):
            continue

        if not valid and entries:
            first = bytearray(entries[0])
            struct.pack_into("<I", first, 0, 0)
            valid = [bytes(first)]

        new_pcs = b"".join(valid)
        records[pcs_idx] = HwpRecord(
            HWPTAG_PARA_CHAR_SHAPE,
            records[pcs_idx].level,
            new_pcs,
            records[pcs_idx].offset,
        )

        # csCount 갱신
        ph = bytearray(rec.payload)
        struct.pack_into("<H", ph, 12, len(valid))
        records[i] = HwpRecord(rec.tag_id, rec.level, bytes(ph), rec.offset)

        changed = True

    if not changed:
        return stream
    return _serialize_records(records)


ALL_FIXERS = [normalize_para_headers, fix_lineseg_r3, fix_oob_charshape]
