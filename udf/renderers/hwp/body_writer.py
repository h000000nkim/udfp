"""HWP 섹션 스트림 패처 (텍스트, 수식, 테이블 속성, 이미지 삽입).

Seed Patch 모드에서 변경된 단락/수식/테이블만 교체하고 나머지 레코드는 원본 그대로 보존.
세 종류 패치를 한 번의 파싱·재직렬화로 처리 (중간 오프셋 무효화 방지).

Public functions:
  apply_section_patches     — 텍스트+수식+테이블 속성 패치를 단일 사이클로 통합 적용
  inject_image_gso          — 기존 단락에 이미지 GSO 인라인 컨트롤 삽입
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
    HWPTAG_PARA_LINE_SEG,
    HWPTAG_PARA_TEXT,
    HWPTAG_SHAPE_COMPONENT,
    HWPTAG_SHAPE_COMPONENT_PIC,
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


def _rebuild_eqedit_payload(old_payload: bytes, new_script: str) -> bytes:
    """EQEDIT payload를 재조립한다. attr + script를 교체하되 trailer를 보존."""
    attr = old_payload[:4] if len(old_payload) >= 4 else b"\x00\x00\x00\x00"
    trailer = b""
    if len(old_payload) >= 6:
        old_script_len = struct.unpack_from("<H", old_payload, 4)[0]
        script_end = 6 + old_script_len * 2
        if script_end < len(old_payload):
            trailer = old_payload[script_end:]
    script_bytes = new_script.encode("utf-16-le")
    return attr + struct.pack("<H", len(new_script)) + script_bytes + trailer


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


def _common_prefix_len_seq(a: list[int], b: list[int]) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def _common_suffix_len_seq(a: list[int], b: list[int], prefix_len: int) -> int:
    n = min(len(a) - prefix_len, len(b) - prefix_len)
    for i in range(1, n + 1):
        if a[-i] != b[-i]:
            return i - 1
    return n


_CTRL_CHAR_LEN = 8


def _ctrl_char_positions(pt_payload: bytes) -> list[int]:
    """Get char-level positions of 16-byte inline ctrl objects in PT."""
    positions: list[int] = []
    char_pos = 0
    byte_pos = 0
    while byte_pos + 2 <= len(pt_payload):
        ch = struct.unpack_from("<H", pt_payload, byte_pos)[0]
        if ch == 0x000D:
            break
        if ch > 0x001F or ch in _CTRL_2BYTE:
            byte_pos += 2
            char_pos += 1
        else:
            positions.append(char_pos)
            byte_pos += 16
            char_pos += _CTRL_CHAR_LEN
    return positions


def _adjust_pcs_positions(
    old_pt: bytes, new_pt: bytes, pcs_entries: list[bytes],
) -> list[bytes]:
    """Adjust PCS entry positions to account for text length changes.

    When inline ctrl objects are present and their count is unchanged,
    uses them as fixed anchors to correctly handle disjoint multi-edits
    (e.g. text changed on both sides of a ctrl). Falls back to
    prefix/suffix matching when there are no ctrls or the ctrl count
    changed.
    """
    old_total = len(old_pt) // 2
    new_total = len(new_pt) // 2

    old_ctrls = _ctrl_char_positions(old_pt)
    new_ctrls = _ctrl_char_positions(new_pt)

    if old_ctrls and len(old_ctrls) == len(new_ctrls):
        if old_ctrls == new_ctrls and old_total == new_total:
            return pcs_entries
        return _adjust_pcs_by_ctrls(
            old_total, new_total, old_ctrls, new_ctrls, pcs_entries,
        )

    if old_total == new_total:
        return pcs_entries

    return _adjust_pcs_by_prefix_suffix(old_pt, new_pt, pcs_entries)


def _adjust_pcs_by_ctrls(
    old_total: int,
    new_total: int,
    old_ctrls: list[int],
    new_ctrls: list[int],
    pcs_entries: list[bytes],
) -> list[bytes]:
    """Remap PCS positions using ctrl segment anchors."""
    regions: list[tuple[int, int, int, int]] = []
    old_prev = 0
    new_prev = 0
    for oc, nc in zip(old_ctrls, new_ctrls):
        regions.append((old_prev, oc, new_prev, nc))
        old_prev = oc + _CTRL_CHAR_LEN
        new_prev = nc + _CTRL_CHAR_LEN
    regions.append((old_prev, old_total, new_prev, new_total))

    ctrl_map = {oc: nc for oc, nc in zip(old_ctrls, new_ctrls)}

    adjusted: list[bytes] = []
    for entry in pcs_entries:
        old_pos = struct.unpack_from("<I", entry, 0)[0]
        cs_id = struct.unpack_from("<I", entry, 4)[0]

        if old_pos in ctrl_map:
            new_pos = ctrl_map[old_pos]
        else:
            for oc, nc in zip(old_ctrls, new_ctrls):
                if oc < old_pos < oc + _CTRL_CHAR_LEN:
                    new_pos = nc + (old_pos - oc)
                    break
            else:
                new_pos = old_pos
                for os_, oe, ns_, ne in regions:
                    if os_ <= old_pos < oe:
                        rlen = oe - os_
                        if rlen == 0:
                            new_pos = ns_
                        else:
                            new_pos = ns_ + (old_pos - os_) * (ne - ns_) // rlen
                        break

        if 0 <= new_pos < new_total:
            adjusted.append(struct.pack("<II", new_pos, cs_id))

    return adjusted


def _adjust_pcs_by_prefix_suffix(
    old_pt: bytes, new_pt: bytes, pcs_entries: list[bytes],
) -> list[bytes]:
    """Fallback: prefix/suffix matching for single contiguous edits."""
    old_total = len(old_pt) // 2
    new_total = len(new_pt) // 2

    old_chars = [struct.unpack_from("<H", old_pt, i * 2)[0] for i in range(old_total)]
    new_chars = [struct.unpack_from("<H", new_pt, i * 2)[0] for i in range(new_total)]

    prefix = _common_prefix_len_seq(old_chars, new_chars)
    suffix = _common_suffix_len_seq(old_chars, new_chars, prefix)

    delta = new_total - old_total
    old_change_end = old_total - suffix

    adjusted = []
    for entry in pcs_entries:
        old_pos = struct.unpack_from("<I", entry, 0)[0]
        cs_id = struct.unpack_from("<I", entry, 4)[0]

        if old_pos < prefix:
            new_pos = old_pos
        elif old_pos >= old_change_end:
            new_pos = old_pos + delta
        else:
            new_pos = max(prefix, old_pos + delta)

        if new_pos < new_total:
            adjusted.append(struct.pack("<II", new_pos, cs_id))

    return adjusted


def _apply_cs_override(
    entries: list[bytes], override: int | dict[int, int],
) -> list[bytes]:
    """Apply CharShape override to PCS entries.

    If override is an int, replace ALL entries' cs_id.
    If override is a dict, replace only entries whose original pos
    matches a key (using closest-match for shifted positions).
    """
    if isinstance(override, int):
        return [
            struct.pack("<II", struct.unpack_from("<I", e, 0)[0], override)
            for e in entries
        ]
    result = []
    for e in entries:
        pos = struct.unpack_from("<I", e, 0)[0]
        cs_id = struct.unpack_from("<I", e, 4)[0]
        if pos in override:
            cs_id = override[pos]
        result.append(struct.pack("<II", pos, cs_id))
    return result


def apply_paragraph_patches(
    section_bytes: bytes,
    patches: list[tuple[int, str]],
    *,
    cs_overrides: dict[int, int | dict[int, int]] | None = None,
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
    cs_overrides : dict[int, int | dict[int, int]] or None
        ph_offset → CharShape override. Value can be a single int (applied
        to all PCS entries) or a dict mapping pcs_pos → new cs_id for
        per-entry overrides.

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
        pls_idx: int | None = None
        for j in range(i + 1, len(records)):
            if records[j].level <= ph_level:
                break
            if records[j].tag_id == HWPTAG_PARA_TEXT and pt_idx is None:
                pt_idx = j
            elif records[j].tag_id == HWPTAG_PARA_CHAR_SHAPE and pcs_idx is None:
                pcs_idx = j
            elif records[j].tag_id == HWPTAG_PARA_LINE_SEG and pls_idx is None:
                pls_idx = j

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
        cs_override_val = (cs_overrides or {}).get(rec.offset)
        new_pcs: bytes | None = None
        if pcs_idx is not None:
            pcs = records[pcs_idx].payload
            entries = [pcs[k : k + 8] for k in range(0, len(pcs) - len(pcs) % 8, 8)]
            if old_pt_payload and len(entries) > 1:
                entries = _adjust_pcs_positions(old_pt_payload, new_pt, entries)
            valid = [
                e for e in entries if struct.unpack_from("<I", e, 0)[0] < new_char_cnt
            ]
            if not valid and entries:
                first = bytearray(entries[0])
                struct.pack_into("<I", first, 0, 0)
                valid = [bytes(first)]
            if cs_override_val is not None:
                valid = _apply_cs_override(valid, cs_override_val)
            new_pcs = b"".join(valid)
            struct.pack_into("<H", ph_payload, 12, len(valid))  # csCount
            records[pcs_idx] = HwpRecord(
                HWPTAG_PARA_CHAR_SHAPE,
                records[pcs_idx].level,
                new_pcs,
                records[pcs_idx].offset,
            )
        elif new_char_cnt > 0:
            cs_id = 0
            if isinstance(cs_override_val, int):
                cs_id = cs_override_val
            elif isinstance(cs_override_val, dict) and 0 in cs_override_val:
                cs_id = cs_override_val[0]
            new_pcs = struct.pack("<II", 0, cs_id)
            struct.pack_into("<H", ph_payload, 12, 1)

        if pls_idx is not None and new_char_cnt > 0:
            pls_data = bytearray(records[pls_idx].payload)
            pls_changed = False
            for entry_off in range(0, len(pls_data) - 35, 36):
                tpos = struct.unpack_from("<I", pls_data, entry_off)[0]
                if tpos >= new_char_cnt:
                    struct.pack_into("<I", pls_data, entry_off, max(0, new_char_cnt - 1))
                    pls_changed = True
            if pls_changed:
                records[pls_idx] = HwpRecord(
                    HWPTAG_PARA_LINE_SEG, records[pls_idx].level,
                    bytes(pls_data), records[pls_idx].offset,
                )

        records[i] = HwpRecord(
            HWPTAG_PARA_HEADER, rec.level, bytes(ph_payload), rec.offset
        )

        if pt_idx is not None:
            records[pt_idx] = HwpRecord(
                HWPTAG_PARA_TEXT, records[pt_idx].level, new_pt, records[pt_idx].offset
            )
        else:
            insert_pos = i + 1
            records.insert(insert_pos, HwpRecord(
                HWPTAG_PARA_TEXT, ph_level + 1, new_pt, 0
            ))
            if pcs_idx is None and new_pcs is not None:
                records.insert(insert_pos + 1, HwpRecord(
                    HWPTAG_PARA_CHAR_SHAPE, ph_level + 1, new_pcs, 0
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
    cs_overrides: dict[int, int | dict[int, int]] | None = None,
    pcs_remap: dict[int, bytes] | None = None,
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
            pls_idx: int | None = None
            for j in range(i + 1, len(records)):
                if records[j].level <= ph_level:
                    break
                if records[j].tag_id == HWPTAG_PARA_TEXT and pt_idx is None:
                    pt_idx = j
                elif records[j].tag_id == HWPTAG_PARA_CHAR_SHAPE and pcs_idx is None:
                    pcs_idx = j
                elif records[j].tag_id == HWPTAG_PARA_LINE_SEG and pls_idx is None:
                    pls_idx = j

            old_pt_payload = records[pt_idx].payload if pt_idx is not None else b""
            trailing_cr = _has_trailing_cr(old_pt_payload) if old_pt_payload else True
            segments = _split_pt_segments(old_pt_payload)
            new_pt = _rebuild_pt_with_new_text(segments, new_text, trailing_cr)
            new_char_cnt = len(new_pt) // 2

            ph_payload = bytearray(rec.payload)
            old_dw = struct.unpack_from("<I", ph_payload, 0)[0]
            msb = old_dw & 0x80000000
            struct.pack_into("<I", ph_payload, 0, msb | (new_char_cnt & 0x3FFFFFFF))

            cs_override_val = (cs_overrides or {}).get(rec.offset)
            remap_pcs = (pcs_remap or {}).get(rec.offset)
            if pcs_idx is not None:
                if remap_pcs is not None:
                    entries = [remap_pcs[k : k + 8] for k in range(0, len(remap_pcs) - len(remap_pcs) % 8, 8)]
                else:
                    pcs = records[pcs_idx].payload
                    entries = [pcs[k : k + 8] for k in range(0, len(pcs) - len(pcs) % 8, 8)]
                    if old_pt_payload and len(entries) > 1:
                        entries = _adjust_pcs_positions(old_pt_payload, new_pt, entries)
                valid = [
                    e for e in entries if struct.unpack_from("<I", e, 0)[0] < new_char_cnt
                ]
                if not valid and entries:
                    first = bytearray(entries[0])
                    struct.pack_into("<I", first, 0, 0)
                    valid = [bytes(first)]
                if cs_override_val is not None:
                    valid = _apply_cs_override(valid, cs_override_val)
                new_pcs = b"".join(valid)
                struct.pack_into("<H", ph_payload, 12, len(valid))
                records[pcs_idx] = HwpRecord(
                    HWPTAG_PARA_CHAR_SHAPE, records[pcs_idx].level,
                    new_pcs, records[pcs_idx].offset,
                )
            elif new_char_cnt > 0:
                cs_id = 0
                if isinstance(cs_override_val, int):
                    cs_id = cs_override_val
                elif isinstance(cs_override_val, dict) and 0 in cs_override_val:
                    cs_id = cs_override_val[0]
                new_pcs = struct.pack("<II", 0, cs_id)
                struct.pack_into("<H", ph_payload, 12, 1)

            if pls_idx is not None and new_char_cnt > 0:
                pls_data = bytearray(records[pls_idx].payload)
                pls_changed = False
                for entry_off in range(0, len(pls_data) - 35, 36):
                    tpos = struct.unpack_from("<I", pls_data, entry_off)[0]
                    if tpos >= new_char_cnt:
                        struct.pack_into("<I", pls_data, entry_off, max(0, new_char_cnt - 1))
                        pls_changed = True
                if pls_changed:
                    records[pls_idx] = HwpRecord(
                        HWPTAG_PARA_LINE_SEG, records[pls_idx].level,
                        bytes(pls_data), records[pls_idx].offset,
                    )

            records[i] = HwpRecord(
                HWPTAG_PARA_HEADER, rec.level, bytes(ph_payload), rec.offset
            )

            if pt_idx is not None:
                records[pt_idx] = HwpRecord(
                    HWPTAG_PARA_TEXT, records[pt_idx].level, new_pt, records[pt_idx].offset
                )
            else:
                insert_pos = i + 1
                records.insert(insert_pos, HwpRecord(
                    HWPTAG_PARA_TEXT, ph_level + 1, new_pt, 0
                ))
                if pcs_idx is None and new_char_cnt > 0:
                    records.insert(insert_pos + 1, HwpRecord(
                        HWPTAG_PARA_CHAR_SHAPE, ph_level + 1, new_pcs, 0
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
                            new_payload = _rebuild_eqedit_payload(old_payload, new_script)
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
                        new_payload = _rebuild_eqedit_payload(old_payload, new_script)
                        records[k] = HwpRecord(
                            HWPTAG_EQEDIT, records[k].level,
                            new_payload, records[k].offset,
                        )
                        break
                break

    return _serialize_records(records)


# ---------------------------------------------------------------------------
# Image GSO injection for Seed Patch mode
# ---------------------------------------------------------------------------

_GSO_INLINE_CTRL = (
    struct.pack("<H", 0x000B)          # ctrl_code GSO
    + b"\x20\x6f\x73\x67"             # ctrl_id 'gso ' LE
    + b"\x00" * 8
    + struct.pack("<H", 0x000B)
)
assert len(_GSO_INLINE_CTRL) == 16


def _has_secd_ctrl(records: list[HwpRecord], ph_idx: int) -> bool:
    """Check if a paragraph contains a secd (section descriptor) control."""
    from udf.parsers.hwp.records import ctrl_id_from_payload

    ph_level = records[ph_idx].level
    for j in range(ph_idx + 1, len(records)):
        if records[j].level <= ph_level:
            break
        if records[j].tag_id == HWPTAG_CTRL_HEADER:
            try:
                cid = ctrl_id_from_payload(records[j].payload)
            except Exception:
                continue
            if cid in ("secd", "cold"):
                return True
    return False


def inject_image_gso(
    section_bytes: bytes,
    target_ph_offset: int,
    gso_child_records: list[HwpRecord],
) -> bytes:
    """Inject an image GSO inline control into an existing paragraph.

    Modifies PARA_TEXT (inserts 16B GSO marker before trailing CR),
    updates PARA_HEADER charCnt, and appends GSO child records
    (CTRL_HEADER + SHAPE_COMPONENT + PIC) as children of the paragraph.

    Does NOT add a new PARA_HEADER — Hancom DOC_DATA cross-validation
    requires the paragraph count to remain unchanged.

    If the target paragraph contains a secd/cold control, the injection
    is moved to the next content paragraph to avoid Hancom rendering
    corruption.

    Parameters
    ----------
    section_bytes : bytes
        Decompressed section stream.
    target_ph_offset : int
        Byte offset of the PARA_HEADER to inject into.
    gso_child_records : list[HwpRecord]
        Pre-built GSO records (CTRL_HEADER, SHAPE_COMPONENT, PIC).
        Levels will be adjusted relative to the target paragraph.

    Returns
    -------
    bytes
        Re-serialized section stream with the image injected.
    """
    records = list(iter_records(section_bytes))

    ph_idx: int | None = None
    for i, rec in enumerate(records):
        if rec.tag_id == HWPTAG_PARA_HEADER and rec.offset == target_ph_offset:
            ph_idx = i
            break
    if ph_idx is None:
        return section_bytes

    if _has_secd_ctrl(records, ph_idx):
        ph_level = records[ph_idx].level
        best = None
        for i in range(ph_idx + 1, len(records)):
            if records[i].tag_id != HWPTAG_PARA_HEADER or records[i].level != ph_level:
                continue
            if _has_secd_ctrl(records, i):
                continue
            cc = struct.unpack_from("<I", records[i].payload, 0)[0] & 0x3FFFFFFF
            if cc <= 1:
                best = i
                break
            if best is None:
                best = i
        if best is not None:
            ph_idx = best

    ph_rec = records[ph_idx]
    ph_level = ph_rec.level

    pt_idx: int | None = None
    pcs_idx: int | None = None
    pls_idx: int | None = None
    child_end = ph_idx + 1
    for j in range(ph_idx + 1, len(records)):
        if records[j].level <= ph_level:
            break
        child_end = j + 1
        if records[j].tag_id == HWPTAG_PARA_TEXT and pt_idx is None:
            pt_idx = j
        elif records[j].tag_id == HWPTAG_PARA_CHAR_SHAPE and pcs_idx is None:
            pcs_idx = j
        elif records[j].tag_id == HWPTAG_PARA_LINE_SEG and pls_idx is None:
            pls_idx = j

    old_pt = records[pt_idx].payload if pt_idx is not None else b"\x0d\x00"
    if old_pt.endswith(b"\x0d\x00"):
        new_pt = old_pt[:-2] + _GSO_INLINE_CTRL + b"\x0d\x00"
    else:
        new_pt = old_pt + _GSO_INLINE_CTRL

    new_char_cnt = len(new_pt) // 2

    ph_payload = bytearray(ph_rec.payload)
    old_dw = struct.unpack_from("<I", ph_payload, 0)[0]
    msb = old_dw & 0x80000000
    if len(ph_payload) >= 8:
        old_cm = struct.unpack_from("<I", ph_payload, 4)[0]
        struct.pack_into("<I", ph_payload, 4, old_cm | 0x00000800)
    struct.pack_into("<I", ph_payload, 0, msb | (new_char_cnt & 0x3FFFFFFF))
    records[ph_idx] = HwpRecord(
        HWPTAG_PARA_HEADER, ph_level, bytes(ph_payload), ph_rec.offset,
    )

    if pt_idx is not None:
        records[pt_idx] = HwpRecord(
            HWPTAG_PARA_TEXT, records[pt_idx].level, new_pt, records[pt_idx].offset,
        )
    else:
        records.insert(ph_idx + 1, HwpRecord(HWPTAG_PARA_TEXT, ph_level + 1, new_pt, 0))
        child_end += 1

    base_child_level = ph_level + 1
    adjusted: list[HwpRecord] = []
    for cr in gso_child_records:
        adjusted.append(HwpRecord(
            cr.tag_id,
            base_child_level + cr.level,
            cr.payload,
            0,
        ))

    for idx, arec in enumerate(adjusted):
        records.insert(child_end + idx, arec)

    return _serialize_records(records)
