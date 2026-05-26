"""HWP 섹션 스트림 패처 (텍스트, 수식, 테이블 속성).

Seed Patch 모드에서 변경된 단락/수식/테이블만 교체하고 나머지 레코드는 원본 그대로 보존.
세 종류 패치를 한 번의 파싱·재직렬화로 처리 (중간 오프셋 무효화 방지).

Public functions:
  apply_section_patches     — 텍스트+수식+테이블 속성 패치를 단일 사이클로 통합 적용
  apply_paragraph_patches   — 단락 텍스트 교체 + CharShape 오버라이드
  apply_equation_patches    — EQEDIT 수식 스크립트 교체
  apply_table_attr_patches  — 테이블 CTRL_HEADER 속성 (like_char 등) 전환

R-규칙 준수:
  R1: PARA_HEADER charCnt = len(new_pt) // 2
  R2: PARA_HEADER csCount 갱신
  R4: PCS pos >= new charCnt인 항목 제거
  함정 5: charCnt MSB 보존
"""

from __future__ import annotations

import struct

from udf.parsers.hwp.records import (
    HWPTAG_CTRL_HEADER,
    HWPTAG_EQEDIT,
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_TEXT,
    HwpRecord,
    iter_records,
)

_CTRL_2BYTE = frozenset({0x0000, 0x0009, 0x000A, 0x000D})

_Segment = tuple[str, bytes]


def _split_pt_segments(pt_payload: bytes) -> list[_Segment]:
    """PT 바이트를 텍스트/인라인 컨트롤 세그먼트로 분리한다.

    반환: [("text", utf16le_bytes), ("ctrl", 16byte_object), ...] 리스트.
    trailing CR(0x000D)는 포함하지 않는다.
    """
    segments: list[_Segment] = []
    text_buf = b""
    i = 0
    while i + 2 <= len(pt_payload):
        ch = struct.unpack_from("<H", pt_payload, i)[0]
        if ch == 0x000D:
            break
        if ch > 0x001F:
            text_buf += pt_payload[i : i + 2]
            i += 2
        elif ch in _CTRL_2BYTE:
            text_buf += pt_payload[i : i + 2]
            i += 2
        else:
            if text_buf:
                segments.append(("text", text_buf))
                text_buf = b""
            end = i + 16
            if end <= len(pt_payload):
                segments.append(("ctrl", pt_payload[i:end]))
            i = end
    if text_buf:
        segments.append(("text", text_buf))
    return segments


def _rebuild_pt_with_new_text(
    segments: list[_Segment],
    new_text: str,
    trailing_cr: bool,
) -> bytes:
    """텍스트 세그먼트만 new_text로 교체하고 ctrl 세그먼트는 보존한다."""
    ctrl_segments = [seg for seg in segments if seg[0] == "ctrl"]

    if not ctrl_segments:
        buf = new_text.encode("utf-16-le")
        if trailing_cr:
            buf += b"\x0d\x00"
        return buf

    old_text_parts: list[str] = []
    for kind, data in segments:
        if kind == "text":
            old_text_parts.append(data.decode("utf-16-le"))
    old_full = "".join(old_text_parts)

    if not old_full:
        result = b""
        for seg in ctrl_segments:
            result += seg[1]
        result += new_text.encode("utf-16-le")
        if trailing_cr:
            result += b"\x0d\x00"
        return result

    new_parts: list[str] = []
    remaining = new_text
    for idx, part in enumerate(old_text_parts):
        if idx < len(old_text_parts) - 1:
            old_pos = remaining.find(part) if part else -1
            if old_pos >= 0 and part:
                new_parts.append(remaining[: old_pos + len(part)])
                remaining = remaining[old_pos + len(part) :]
            else:
                ratio = len(part) / max(len(old_full), 1)
                take = max(0, int(len(remaining) * ratio))
                new_parts.append(remaining[:take])
                remaining = remaining[take:]
        else:
            new_parts.append(remaining)
            remaining = ""

    while len(new_parts) < len(old_text_parts):
        new_parts.append("")

    result = b""
    text_idx = 0
    for kind, data in segments:
        if kind == "text":
            if text_idx < len(new_parts):
                result += new_parts[text_idx].encode("utf-16-le")
            text_idx += 1
        else:
            result += data
    if trailing_cr:
        result += b"\x0d\x00"
    return result


def _serialize_record(rec: HwpRecord) -> bytes:
    """Serialize a single HWP record to bytes."""
    size = len(rec.payload)
    if size < 0xFFF:
        h = rec.tag_id | (rec.level << 10) | (size << 20)
        return struct.pack("<I", h) + rec.payload
    h = rec.tag_id | (rec.level << 10) | (0xFFF << 20)
    return struct.pack("<II", h, size) + rec.payload


def _serialize_records(records: list[HwpRecord]) -> bytes:
    """Serialize a list of HWP records to concatenated bytes."""
    return b"".join(_serialize_record(r) for r in records)


def _text_to_para_text(text: str, trailing_cr: bool) -> bytes:
    """일반 텍스트를 PARA_TEXT 페이로드 bytes로 변환 (인라인 오브젝트 없음).

    HWP PARA_TEXT는 UTF-16-LE이며 단락 끝에 0x000D(CR)를 포함한다.
    """
    buf = text.encode("utf-16-le")
    if trailing_cr:
        buf += b"\x0d\x00"
    return buf


def _has_trailing_cr(pt_payload: bytes) -> bool:
    """Check whether PARA_TEXT payload ends with CR (0x000D)."""
    return pt_payload.endswith(b"\x0d\x00")


def apply_paragraph_patches(
    section_bytes: bytes,
    patches: list[tuple[int, str]],
    *,
    cs_overrides: dict[int, int] | None = None,
) -> bytes:
    """Apply text patches to paragraphs in a section stream.

    Replaces paragraph text at specified offsets while preserving inline
    control objects and updating PARA_HEADER charCnt / csCount fields
    to satisfy R-rules (R1, R2, R4).

    Parameters
    ----------
    section_bytes : bytes
        Decompressed section stream bytes.
    patches : list[tuple[int, str]]
        List of (ph_offset, new_text) pairs. ``ph_offset`` is the byte
        offset of the target PARA_HEADER record. ``new_text`` is the
        replacement text (without trailing CR).
    cs_overrides : dict[int, int] or None
        Optional mapping of ph_offset → new CharShape ID. When provided,
        all PCS entries for that paragraph are rewritten to use the
        given CharShape ID.

    Returns
    -------
    bytes
        Re-serialized section stream with patches applied.
    """
    if not patches:
        return section_bytes

    patch_map = {offset: text for offset, text in patches}
    records = list(iter_records(section_bytes))

    for i, rec in enumerate(records):
        if rec.tag_id != HWPTAG_PARA_HEADER:
            continue
        if rec.offset not in patch_map:
            continue

        new_text = patch_map[rec.offset]
        ph_level = rec.level

        pt_idx: int | None = None
        pcs_idx: int | None = None
        for j in range(i + 1, len(records)):
            if records[j].level <= ph_level:
                break
            if records[j].tag_id == HWPTAG_PARA_TEXT and pt_idx is None:
                pt_idx = j
            elif records[j].tag_id == HWPTAG_PARA_CHAR_SHAPE and pcs_idx is None:
                pcs_idx = j

        old_pt_payload = records[pt_idx].payload if pt_idx is not None else b""
        trailing_cr = _has_trailing_cr(old_pt_payload) if old_pt_payload else True
        segments = _split_pt_segments(old_pt_payload)
        new_pt = _rebuild_pt_with_new_text(segments, new_text, trailing_cr)
        new_char_cnt = len(new_pt) // 2

        # PARA_HEADER 업데이트: charCnt(offset 0) + csCount(offset 12)
        ph_payload = bytearray(rec.payload)

        old_dw = struct.unpack_from("<I", ph_payload, 0)[0]
        msb = old_dw & 0x80000000  # 함정 5: MSB 보존
        struct.pack_into("<I", ph_payload, 0, msb | (new_char_cnt & 0x3FFFFFFF))

        # PARA_CHAR_SHAPE 정리 (R4: pos < charCnt) + cs_overrides 적용
        override_cs_id = (cs_overrides or {}).get(rec.offset)
        if pcs_idx is not None:
            pcs = records[pcs_idx].payload
            entries = [pcs[k : k + 8] for k in range(0, len(pcs) - len(pcs) % 8, 8)]
            valid = [
                e for e in entries if struct.unpack_from("<I", e, 0)[0] < new_char_cnt
            ]
            if not valid and entries:
                first = bytearray(entries[0])
                struct.pack_into("<I", first, 0, 0)
                valid = [bytes(first)]
            if override_cs_id is not None:
                valid = [
                    struct.pack("<II", struct.unpack_from("<I", e, 0)[0], override_cs_id)
                    for e in valid
                ]
            new_pcs = b"".join(valid)
            struct.pack_into("<H", ph_payload, 12, len(valid))  # csCount
            records[pcs_idx] = HwpRecord(
                HWPTAG_PARA_CHAR_SHAPE,
                records[pcs_idx].level,
                new_pcs,
                records[pcs_idx].offset,
            )

        records[i] = HwpRecord(
            HWPTAG_PARA_HEADER, rec.level, bytes(ph_payload), rec.offset
        )

        if pt_idx is not None:
            records[pt_idx] = HwpRecord(
                HWPTAG_PARA_TEXT, records[pt_idx].level, new_pt, records[pt_idx].offset
            )
        else:
            records.insert(i + 1, HwpRecord(
                HWPTAG_PARA_TEXT, ph_level + 1, new_pt, 0
            ))

    return _serialize_records(records)


def apply_table_attr_patches(
    section_bytes: bytes,
    patches: list[tuple[int, dict[str, bool]]],
) -> bytes:
    """Patch table control attributes (e.g. like_char) in a section stream.

    Parameters
    ----------
    section_bytes : bytes
        Decompressed section stream bytes.
    patches : list[tuple[int, dict[str, bool]]]
        List of (ph_offset, attrs) pairs. ``ph_offset`` is the byte
        offset of the host PARA_HEADER containing the table.
        ``attrs`` is a dict of attribute overrides, currently supporting
        ``like_char`` (bool).

    Returns
    -------
    bytes
        Re-serialized section stream.
    """
    if not patches:
        return section_bytes

    from udf.parsers.hwp.records import ctrl_id_from_payload

    patch_map = {offset: attrs for offset, attrs in patches}
    records = list(iter_records(section_bytes))

    for i, rec in enumerate(records):
        if rec.tag_id != HWPTAG_PARA_HEADER or rec.offset not in patch_map:
            continue
        attrs = patch_map[rec.offset]
        ph_level = rec.level

        for j in range(i + 1, len(records)):
            if records[j].level <= ph_level:
                break
            if records[j].tag_id == HWPTAG_CTRL_HEADER:
                try:
                    cid = ctrl_id_from_payload(records[j].payload)
                except Exception:
                    continue
                if cid != "tbl ":
                    continue
                ctrl_payload = bytearray(records[j].payload)
                if len(ctrl_payload) >= 8:
                    old_attr = struct.unpack_from("<I", ctrl_payload, 4)[0]
                    if "like_char" in attrs:
                        if attrs["like_char"]:
                            old_attr |= 0x1
                        else:
                            old_attr &= ~0x1
                    struct.pack_into("<I", ctrl_payload, 4, old_attr)
                    records[j] = HwpRecord(
                        records[j].tag_id, records[j].level,
                        bytes(ctrl_payload), records[j].offset,
                    )

    return _serialize_records(records)


def apply_section_patches(
    section_bytes: bytes,
    text_patches: list[tuple[int, str]] | None = None,
    eq_patches: list[tuple[int, str]] | None = None,
    tbl_attr_patches: list[tuple[int, dict[str, bool]]] | None = None,
    *,
    cs_overrides: dict[int, int] | None = None,
) -> bytes:
    """Apply text, equation, and table attr patches in a single parse-modify-serialize cycle.

    Sequential patching (separate functions per type) re-serializes records
    between passes, shifting byte offsets and breaking lookups for later
    patches. This function parses once, applies all types to the shared
    record list, then serializes once.

    Parameters
    ----------
    section_bytes : bytes
        Decompressed section stream bytes.
    text_patches : list[tuple[int, str]] or None
        (ph_offset, new_text) pairs for paragraph text replacement.
    eq_patches : list[tuple[int, str]] or None
        (ph_offset, new_hwp_script) pairs for equation replacement.
    tbl_attr_patches : list[tuple[int, dict[str, bool]]] or None
        (ph_offset, attrs) pairs for table attribute updates.
        Patches ALL 'tbl ' CTRL_HEADERs under each target PARA_HEADER
        (one PH can host multiple tables via GSO wrappers).
    cs_overrides : dict[int, int] or None
        ph_offset → new CharShape ID for text color/style overrides.

    Returns
    -------
    bytes
        Re-serialized section stream with all patches applied.
    """
    if not text_patches and not eq_patches and not tbl_attr_patches:
        return section_bytes

    from udf.parsers.hwp.records import ctrl_id_from_payload

    text_map = {offset: text for offset, text in (text_patches or [])}
    eq_map = {offset: script for offset, script in (eq_patches or [])}
    tbl_map = {offset: attrs for offset, attrs in (tbl_attr_patches or [])}

    records = list(iter_records(section_bytes))

    for i, rec in enumerate(records):
        if rec.tag_id != HWPTAG_PARA_HEADER:
            continue
        ph_level = rec.level

        # --- Text patch ---
        if rec.offset in text_map:
            new_text = text_map[rec.offset]
            pt_idx: int | None = None
            pcs_idx: int | None = None
            for j in range(i + 1, len(records)):
                if records[j].level <= ph_level:
                    break
                if records[j].tag_id == HWPTAG_PARA_TEXT and pt_idx is None:
                    pt_idx = j
                elif records[j].tag_id == HWPTAG_PARA_CHAR_SHAPE and pcs_idx is None:
                    pcs_idx = j

            old_pt_payload = records[pt_idx].payload if pt_idx is not None else b""
            trailing_cr = _has_trailing_cr(old_pt_payload) if old_pt_payload else True
            segments = _split_pt_segments(old_pt_payload)
            new_pt = _rebuild_pt_with_new_text(segments, new_text, trailing_cr)
            new_char_cnt = len(new_pt) // 2

            ph_payload = bytearray(rec.payload)
            old_dw = struct.unpack_from("<I", ph_payload, 0)[0]
            msb = old_dw & 0x80000000
            struct.pack_into("<I", ph_payload, 0, msb | (new_char_cnt & 0x3FFFFFFF))

            override_cs_id = (cs_overrides or {}).get(rec.offset)
            if pcs_idx is not None:
                pcs = records[pcs_idx].payload
                entries = [pcs[k : k + 8] for k in range(0, len(pcs) - len(pcs) % 8, 8)]
                valid = [
                    e for e in entries if struct.unpack_from("<I", e, 0)[0] < new_char_cnt
                ]
                if not valid and entries:
                    first = bytearray(entries[0])
                    struct.pack_into("<I", first, 0, 0)
                    valid = [bytes(first)]
                if override_cs_id is not None:
                    valid = [
                        struct.pack("<II", struct.unpack_from("<I", e, 0)[0], override_cs_id)
                        for e in valid
                    ]
                new_pcs = b"".join(valid)
                struct.pack_into("<H", ph_payload, 12, len(valid))
                records[pcs_idx] = HwpRecord(
                    HWPTAG_PARA_CHAR_SHAPE, records[pcs_idx].level,
                    new_pcs, records[pcs_idx].offset,
                )

            records[i] = HwpRecord(
                HWPTAG_PARA_HEADER, rec.level, bytes(ph_payload), rec.offset
            )

            if pt_idx is not None:
                records[pt_idx] = HwpRecord(
                    HWPTAG_PARA_TEXT, records[pt_idx].level, new_pt, records[pt_idx].offset
                )
            else:
                records.insert(i + 1, HwpRecord(
                    HWPTAG_PARA_TEXT, ph_level + 1, new_pt, 0
                ))

        # --- Equation patch ---
        if rec.offset in eq_map:
            new_script = eq_map[rec.offset]
            for j in range(i + 1, len(records)):
                if records[j].level <= ph_level:
                    break
                if records[j].tag_id == HWPTAG_CTRL_HEADER:
                    try:
                        cid = ctrl_id_from_payload(records[j].payload)
                    except Exception:
                        continue
                    if cid != "eqed":
                        continue
                    ctrl_level = records[j].level
                    for k in range(j + 1, len(records)):
                        if records[k].level <= ctrl_level:
                            break
                        if records[k].tag_id == HWPTAG_EQEDIT:
                            old_payload = records[k].payload
                            attr = old_payload[:4] if len(old_payload) >= 4 else b"\x00\x00\x00\x00"
                            script_bytes = new_script.encode("utf-16-le")
                            new_payload = attr + struct.pack("<H", len(new_script)) + script_bytes
                            records[k] = HwpRecord(
                                HWPTAG_EQEDIT, records[k].level,
                                new_payload, records[k].offset,
                            )
                            break
                    break

        # --- Table attr patch (patch ALL 'tbl ' under this PH) ---
        if rec.offset in tbl_map:
            attrs = tbl_map[rec.offset]
            for j in range(i + 1, len(records)):
                if records[j].level <= ph_level:
                    break
                if records[j].tag_id == HWPTAG_CTRL_HEADER:
                    try:
                        cid = ctrl_id_from_payload(records[j].payload)
                    except Exception:
                        continue
                    if cid != "tbl ":
                        continue
                    ctrl_payload = bytearray(records[j].payload)
                    if len(ctrl_payload) >= 8:
                        old_attr = struct.unpack_from("<I", ctrl_payload, 4)[0]
                        if "like_char" in attrs:
                            if attrs["like_char"]:
                                old_attr |= 0x1
                            else:
                                old_attr &= ~0x1
                        struct.pack_into("<I", ctrl_payload, 4, old_attr)
                        records[j] = HwpRecord(
                            records[j].tag_id, records[j].level,
                            bytes(ctrl_payload), records[j].offset,
                        )

    return _serialize_records(records)


def apply_equation_patches(
    section_bytes: bytes,
    patches: list[tuple[int, str]],
) -> bytes:
    """Replace EQEDIT record scripts in a section stream.

    Locates the CTRL_HEADER 'eqed' under each target PARA_HEADER and
    replaces its equation script payload.

    Parameters
    ----------
    section_bytes : bytes
        Decompressed section stream bytes.
    patches : list[tuple[int, str]]
        List of (ph_offset, new_hwp_script) pairs. ``ph_offset`` is
        the byte offset of the host PARA_HEADER record.

    Returns
    -------
    bytes
        Re-serialized section stream with equation patches applied.
    """
    if not patches:
        return section_bytes

    from udf.parsers.hwp.records import ctrl_id_from_payload

    patch_map = {offset: script for offset, script in patches}
    records = list(iter_records(section_bytes))

    for i, rec in enumerate(records):
        if rec.tag_id != HWPTAG_PARA_HEADER or rec.offset not in patch_map:
            continue
        new_script = patch_map[rec.offset]
        ph_level = rec.level

        for j in range(i + 1, len(records)):
            if records[j].level <= ph_level:
                break
            if records[j].tag_id == HWPTAG_CTRL_HEADER:
                try:
                    cid = ctrl_id_from_payload(records[j].payload)
                except Exception:
                    continue
                if cid != "eqed":
                    continue
                ctrl_level = records[j].level
                for k in range(j + 1, len(records)):
                    if records[k].level <= ctrl_level:
                        break
                    if records[k].tag_id == HWPTAG_EQEDIT:
                        old_payload = records[k].payload
                        attr = old_payload[:4] if len(old_payload) >= 4 else b"\x00\x00\x00\x00"
                        script_bytes = new_script.encode("utf-16-le")
                        new_payload = attr + struct.pack("<H", len(new_script)) + script_bytes
                        records[k] = HwpRecord(
                            HWPTAG_EQEDIT, records[k].level,
                            new_payload, records[k].offset,
                        )
                        break
                break

    return _serialize_records(records)
