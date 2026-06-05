"""DocInfo stream binary patcher for Seed Patch mode.

Supports finding or adding CharShape/BinData records and updating
ID_MAPPINGS counts without rebuilding the entire DocInfo stream. Used
by the HWP renderer to apply CharShape overrides and image additions
during Seed Patch rendering.
"""

from __future__ import annotations

import struct

from udf.parsers.hwp.records import (
    HWPTAG_BIN_DATA,
    HWPTAG_CHAR_SHAPE,
    HWPTAG_ID_MAPPINGS,
    HwpRecord,
    iter_records,
)

_IDMAP_BINDATA_OFFSET = 0
_IDMAP_CS_OFFSET = 36


def _serialize_record(rec: HwpRecord) -> bytes:
    size = len(rec.payload)
    if size < 0xFFF:
        h = rec.tag_id | (rec.level << 10) | (size << 20)
        return struct.pack("<I", h) + rec.payload
    h = rec.tag_id | (rec.level << 10) | (0xFFF << 20)
    return struct.pack("<II", h, size) + rec.payload


def _color_from_cs_payload(payload: bytes) -> int:
    if len(payload) >= 56:
        return struct.unpack_from("<I", payload, 52)[0]
    return 0


def _color_hex_to_bgr(hex_color: str) -> int:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return r | (g << 8) | (b << 16)


def find_matching_charshape(
    docinfo_bytes: bytes,
    base_cs_id: int,
    target_color_hex: str,
) -> int | None:
    """Find an existing CharShape that matches base except for color.

    Returns the CharShape index if found, None otherwise.
    """
    target_bgr = _color_hex_to_bgr(target_color_hex)
    records = list(iter_records(docinfo_bytes))
    cs_records = [r for r in records if r.tag_id == HWPTAG_CHAR_SHAPE]

    if base_cs_id >= len(cs_records):
        return None
    base_payload = bytearray(cs_records[base_cs_id].payload)
    if len(base_payload) < 56:
        return None

    base_compare = bytes(base_payload[:52]) + bytes(base_payload[56:])

    for idx, cs_rec in enumerate(cs_records):
        if len(cs_rec.payload) < 56:
            continue
        if _color_from_cs_payload(cs_rec.payload) != target_bgr:
            continue
        candidate = bytearray(cs_rec.payload)
        candidate_compare = bytes(candidate[:52]) + bytes(candidate[56:])
        if candidate_compare == base_compare:
            return idx
    return None


def add_charshape_clone(
    docinfo_bytes: bytes,
    base_cs_id: int,
    target_color_hex: str,
) -> tuple[bytes, int]:
    """Clone a CharShape record with a different color and append to DocInfo.

    Returns (new_docinfo_bytes, new_cs_id).
    Updates ID_MAPPINGS CharShape count automatically.
    """
    target_bgr = _color_hex_to_bgr(target_color_hex)
    records = list(iter_records(docinfo_bytes))
    cs_records = [(i, r) for i, r in enumerate(records) if r.tag_id == HWPTAG_CHAR_SHAPE]

    if base_cs_id >= len(cs_records):
        raise ValueError(f"base_cs_id {base_cs_id} out of range ({len(cs_records)} CharShapes)")

    _, base_rec = cs_records[base_cs_id]
    new_payload = bytearray(base_rec.payload)
    if len(new_payload) >= 56:
        struct.pack_into("<I", new_payload, 52, target_bgr)

    new_cs_id = len(cs_records)

    last_cs_rec_idx = cs_records[-1][0]
    new_rec = HwpRecord(
        HWPTAG_CHAR_SHAPE, base_rec.level, bytes(new_payload), 0
    )
    records.insert(last_cs_rec_idx + 1, new_rec)

    for i, rec in enumerate(records):
        if rec.tag_id == HWPTAG_ID_MAPPINGS:
            idmap = bytearray(rec.payload)
            if len(idmap) >= _IDMAP_CS_OFFSET + 4:
                old_count = struct.unpack_from("<I", idmap, _IDMAP_CS_OFFSET)[0]
                struct.pack_into("<I", idmap, _IDMAP_CS_OFFSET, old_count + 1)
                records[i] = HwpRecord(rec.tag_id, rec.level, bytes(idmap), rec.offset)
            break

    return b"".join(_serialize_record(r) for r in records), new_cs_id


def find_or_add_charshape(
    docinfo_bytes: bytes,
    base_cs_id: int,
    target_color_hex: str,
) -> tuple[bytes, int]:
    """Find an existing matching CharShape or create a new one.

    Returns (docinfo_bytes, cs_id). If an existing match was found,
    docinfo_bytes is unchanged.
    """
    existing = find_matching_charshape(docinfo_bytes, base_cs_id, target_color_hex)
    if existing is not None:
        return docinfo_bytes, existing
    return add_charshape_clone(docinfo_bytes, base_cs_id, target_color_hex)


def get_charshape_color(docinfo_bytes: bytes, cs_id: int) -> str | None:
    """Get the hex color string of a CharShape by index."""
    cs_records = [r for r in iter_records(docinfo_bytes) if r.tag_id == HWPTAG_CHAR_SHAPE]
    if cs_id >= len(cs_records):
        return None
    bgr = _color_from_cs_payload(cs_records[cs_id].payload)
    r = bgr & 0xFF
    g = (bgr >> 8) & 0xFF
    b = (bgr >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def add_bindata_record(
    docinfo_bytes: bytes,
    extension: str,
) -> tuple[bytes, int]:
    """Add a BIN_DATA record to DocInfo and update ID_MAPPINGS.

    Mirrors the ``add_charshape_clone`` pattern for BinData.

    Returns
    -------
    tuple[bytes, int]
        (new_docinfo_bytes, new_bin_item_id) where bin_item_id is 1-based.
    """
    from udf.renderers.hwp.docinfo_builder import BinDataSpec, pack_bin_data

    records = list(iter_records(docinfo_bytes))
    bd_indices = [(i, r) for i, r in enumerate(records) if r.tag_id == HWPTAG_BIN_DATA]

    new_bin_item_id = len(bd_indices) + 1
    spec = BinDataSpec(bin_data_id=new_bin_item_id, extension=extension)
    new_payload = pack_bin_data(spec)

    if bd_indices:
        insert_after = bd_indices[-1][0]
        level = bd_indices[-1][1].level
    else:
        insert_after = next(
            (i for i, r in enumerate(records) if r.tag_id == HWPTAG_ID_MAPPINGS), 0
        )
        level = 1

    records.insert(insert_after + 1, HwpRecord(HWPTAG_BIN_DATA, level, new_payload, 0))

    for i, rec in enumerate(records):
        if rec.tag_id == HWPTAG_ID_MAPPINGS:
            idmap = bytearray(rec.payload)
            if len(idmap) >= _IDMAP_BINDATA_OFFSET + 4:
                old_count = struct.unpack_from("<I", idmap, _IDMAP_BINDATA_OFFSET)[0]
                struct.pack_into("<I", idmap, _IDMAP_BINDATA_OFFSET, old_count + 1)
                records[i] = HwpRecord(rec.tag_id, rec.level, bytes(idmap), rec.offset)
            break

    return b"".join(_serialize_record(r) for r in records), new_bin_item_id
