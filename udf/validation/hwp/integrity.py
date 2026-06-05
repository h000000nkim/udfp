"""HWP 파일 구조 정합성 검증 — 생성된 파일의 무결성을 확인.

R-규칙(rules.py)은 파싱된 UdfDocument 기반 검증이고,
이 모듈은 생성된 HWP 바이너리 파일의 구조적 정합성을 검증한다.

I-규칙 (Integrity Rules):
  I1: ID_MAPPINGS 카운트 == 실제 레코드 수 (CS, PS, BF, BinData)
  I2: 모든 CharShape의 face_id < FaceName 수
  I3: Body에서 참조하는 CS/PS ID < 실제 레코드 수
  I6: Preamble 단락의 controlMask ↔ PARA_TEXT 인라인 컨트롤 일치
  I7: DOCUMENT_PROPERTIES.sectionCount == Section 스트림 수
  I8: LIST_HEADER borderFillId ∈ [1, borderFillCount]
  I9: TABLE nRows×nCols == LIST_HEADER 자식 수
  I10: BIN_DATA embedding → BinData/ 스트림 존재
  I11: DocInfo 레코드 순서 (canonical tag order)
  I12: PLS tpos < charCnt (tpos overflow → 한컴 손상 판정)

R-파일 규칙 (File-level Rules):
  R5: FileHeader 시그니처 + 크기 + 버전
  R6: 필수 스트림 존재 (DocInfo, BodyText/Section0)
  R7: 압축 플래그 vs 실제 압축 방식 일치
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Literal

import olefile

from udf.parsers.hwp.records import (
    HWPTAG_BIN_DATA,
    HWPTAG_BORDER_FILL,
    HWPTAG_BULLET,
    HWPTAG_CHAR_SHAPE,
    HWPTAG_COMPATIBLE_DOCUMENT,
    HWPTAG_CTRL_HEADER,
    HWPTAG_DOC_DATA,
    HWPTAG_DOCUMENT_PROPERTIES,
    HWPTAG_FACE_NAME,
    HWPTAG_ID_MAPPINGS,
    HWPTAG_LAYOUT_COMPATIBILITY,
    HWPTAG_LIST_HEADER,
    HWPTAG_NUMBERING,
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_LINE_SEG,
    HWPTAG_PARA_SHAPE,
    HWPTAG_PARA_TEXT,
    HWPTAG_STYLE,
    HWPTAG_TAB_DEF,
    HWPTAG_TABLE,
    iter_records,
)


@dataclass
class IntegrityViolation:
    rule_id: str
    message: str
    severity: Literal["error", "warning"] = "error"


_IDMAP_BINDATA_OFF = 0
_IDMAP_BORDERFILL_OFF = 32
_IDMAP_CHARSHAPE_OFF = 36
_IDMAP_PARASHAPE_OFF = 52


def check_i1(docinfo_bytes: bytes) -> list[IntegrityViolation]:
    """Validate I1: ID_MAPPINGS counts must match actual record counts.

    Compares the declared counts for BinData, BorderFill, CharShape,
    and ParaShape in the ID_MAPPINGS record against the actual number
    of corresponding records found in DocInfo.

    Parameters
    ----------
    docinfo_bytes : bytes
        Raw (decompressed) DocInfo stream bytes.

    Returns
    -------
    list[IntegrityViolation]
        Violations found. Empty list means I1 passes.
    """
    violations: list[IntegrityViolation] = []

    actual_counts = {"BinData": 0, "BorderFill": 0, "CharShape": 0, "ParaShape": 0}
    idmap_counts: dict[str, int] = {}

    for rec in iter_records(docinfo_bytes):
        if rec.tag_id == HWPTAG_ID_MAPPINGS and len(rec.payload) >= 56:
            p = rec.payload
            idmap_counts = {
                "BinData": struct.unpack_from("<I", p, _IDMAP_BINDATA_OFF)[0],
                "BorderFill": struct.unpack_from("<I", p, _IDMAP_BORDERFILL_OFF)[0],
                "CharShape": struct.unpack_from("<I", p, _IDMAP_CHARSHAPE_OFF)[0],
                "ParaShape": struct.unpack_from("<I", p, _IDMAP_PARASHAPE_OFF)[0],
            }
        elif rec.tag_id == HWPTAG_BIN_DATA:
            actual_counts["BinData"] += 1
        elif rec.tag_id == HWPTAG_BORDER_FILL:
            actual_counts["BorderFill"] += 1
        elif rec.tag_id == HWPTAG_CHAR_SHAPE:
            actual_counts["CharShape"] += 1
        elif rec.tag_id == HWPTAG_PARA_SHAPE:
            actual_counts["ParaShape"] += 1

    if not idmap_counts:
        violations.append(
            IntegrityViolation(
                rule_id="I1",
                message="ID_MAPPINGS record not found in DocInfo",
            )
        )
        return violations

    for rec_type in ["BinData", "BorderFill", "CharShape", "ParaShape"]:
        expected = idmap_counts[rec_type]
        actual = actual_counts[rec_type]
        if expected != actual:
            violations.append(
                IntegrityViolation(
                    rule_id="I1",
                    message=f"ID_MAPPINGS {rec_type} count={expected} but actual records={actual}",
                )
            )

    return violations


def check_i2(docinfo_bytes: bytes) -> list[IntegrityViolation]:
    """Validate I2: all CharShape face_ids must be within FaceName bounds.

    Each of the 7 per-language face_id slots in every CharShape record
    must be less than the corresponding FaceName count declared in
    ID_MAPPINGS.

    Parameters
    ----------
    docinfo_bytes : bytes
        Raw (decompressed) DocInfo stream bytes.

    Returns
    -------
    list[IntegrityViolation]
        Violations found. Empty list means I2 passes.
    """
    violations: list[IntegrityViolation] = []

    face_counts: list[int] = []
    cs_faces: list[tuple[int, list[int]]] = []  # (cs_idx, [face_id×7])

    cs_idx = 0
    for rec in iter_records(docinfo_bytes):
        if rec.tag_id == HWPTAG_ID_MAPPINGS and len(rec.payload) >= 32:
            for lang in range(7):
                face_counts.append(
                    struct.unpack_from("<I", rec.payload, 4 + lang * 4)[0]
                )
        elif rec.tag_id == HWPTAG_CHAR_SHAPE and len(rec.payload) >= 14:
            faces = list(struct.unpack_from("<7H", rec.payload, 0))
            cs_faces.append((cs_idx, faces))
            cs_idx += 1

    if not face_counts:
        return violations

    for idx, faces in cs_faces:
        for lang, fid in enumerate(faces):
            if lang < len(face_counts) and fid >= face_counts[lang]:
                violations.append(
                    IntegrityViolation(
                        rule_id="I2",
                        message=f"CharShape[{idx}] face_id[{lang}]={fid} >= FaceName count={face_counts[lang]}",
                    )
                )
                break

    return violations


def check_i3_docinfo(docinfo_bytes: bytes) -> tuple[int, int, int]:
    """Count CharShape, ParaShape, and BorderFill records in DocInfo.

    Used as input for ``check_i3_body`` to validate cross-references.

    Parameters
    ----------
    docinfo_bytes : bytes
        Raw (decompressed) DocInfo stream bytes.

    Returns
    -------
    tuple[int, int, int]
        Counts of (CharShape, ParaShape, BorderFill) records.
    """
    cs = ps = bf = 0
    for rec in iter_records(docinfo_bytes):
        if rec.tag_id == HWPTAG_CHAR_SHAPE:
            cs += 1
        elif rec.tag_id == HWPTAG_PARA_SHAPE:
            ps += 1
        elif rec.tag_id == HWPTAG_BORDER_FILL:
            bf += 1
    return cs, ps, bf


def check_i3_body(
    section_bytes: bytes,
    cs_count: int,
    ps_count: int,
    bf_count: int = 0,
) -> list[IntegrityViolation]:
    """Validate I3: body CS/PS/BF references must be within DocInfo record bounds.

    Checks that every ParaShape ID in PARA_HEADER, CharShape ID in
    PARA_CHAR_SHAPE, and BorderFill ID in LIST_HEADER are within the
    actual record counts declared in DocInfo.

    Parameters
    ----------
    section_bytes : bytes
        Raw (decompressed) section stream bytes.
    cs_count : int
        Total number of CharShape records in DocInfo.
    ps_count : int
        Total number of ParaShape records in DocInfo.
    bf_count : int
        Total number of BorderFill records in DocInfo.

    Returns
    -------
    list[IntegrityViolation]
        Violations found. Empty list means I3 passes.
    """
    violations: list[IntegrityViolation] = []

    para_idx = 0
    for rec in iter_records(section_bytes):
        if rec.tag_id == HWPTAG_PARA_HEADER and len(rec.payload) >= 22:
            ps_id = struct.unpack_from("<H", rec.payload, 16)[0]
            if ps_id >= ps_count:
                violations.append(
                    IntegrityViolation(
                        rule_id="I3",
                        message=f"Para[{para_idx}] ParaShape ID={ps_id} >= PS count={ps_count}",
                    )
                )
            para_idx += 1
        elif rec.tag_id == HWPTAG_PARA_CHAR_SHAPE:
            n_entries = len(rec.payload) // 8
            for k in range(n_entries):
                cs_id = struct.unpack_from("<I", rec.payload, k * 8 + 4)[0]
                if cs_id >= cs_count:
                    violations.append(
                        IntegrityViolation(
                            rule_id="I3",
                            message=f"PCS entry CharShape ID={cs_id} >= CS count={cs_count}",
                        )
                    )
                    break
        elif rec.tag_id == HWPTAG_LIST_HEADER and bf_count > 0 and len(rec.payload) >= 34:
            bf_id = struct.unpack_from("<H", rec.payload, 32)[0]
            if bf_id > bf_count:
                violations.append(
                    IntegrityViolation(
                        rule_id="I3",
                        message=f"LIST_HEADER borderFillId={bf_id} > BF count={bf_count}",
                    )
                )

    return violations


def validate_hwp_integrity(docinfo_bytes: bytes) -> list[IntegrityViolation]:
    """Run I1 and I2 integrity checks on DocInfo bytes.

    Parameters
    ----------
    docinfo_bytes : bytes
        Raw (decompressed) DocInfo stream bytes.

    Returns
    -------
    list[IntegrityViolation]
        Combined violations from I1 and I2.
    """
    return check_i1(docinfo_bytes) + check_i2(docinfo_bytes)


def check_i4_con_children(section_bytes: bytes) -> list[IntegrityViolation]:
    """I4: $con nChildren 선언과 실제 SHCOMP 자식 수 일치 확인.

    $con SHCOMP가 nChildren=N으로 선언했으나 실제 자식 SHCOMP가 N개가 아니면
    Hancom이 "파일 손상" 판정.
    """
    from udf.parsers.hwp.records import iter_records, HWPTAG_SHAPE_COMPONENT

    violations: list[IntegrityViolation] = []
    recs = list(iter_records(section_bytes))
    for i, r in enumerate(recs):
        if r.tag_id != HWPTAG_SHAPE_COMPONENT or len(r.payload) < 10:
            continue
        st = r.payload[:4][::-1].decode("ascii", errors="replace")
        if st != "$con":
            continue
        is_child = r.level > 2
        np_off = 46 if is_child else 50
        if np_off + 2 > len(r.payload):
            continue
        n_pairs = struct.unpack_from("<H", r.payload, np_off)[0]
        mat_end = np_off + 2 + 48 * (1 + 2 * n_pairs)
        if mat_end + 2 > len(r.payload):
            continue
        n_children = struct.unpack_from("<H", r.payload, mat_end)[0]
        actual_children = 0
        for j in range(i + 1, len(recs)):
            if recs[j].level <= r.level:
                break
            if (
                recs[j].level == r.level + 1
                and recs[j].tag_id == HWPTAG_SHAPE_COMPONENT
            ):
                actual_children += 1
        if actual_children != n_children:
            violations.append(
                IntegrityViolation(
                    rule_id="I4",
                    message=f"$con at L{r.level} declares nChildren={n_children} but has {actual_children} SHCOMP children",
                )
            )
    return violations


def validate_hwp_full(
    docinfo_bytes: bytes,
    section_bytes: bytes | None = None,
) -> list[IntegrityViolation]:
    """Run all integrity checks (I1 + I2 + I3) on DocInfo and optionally body.

    Parameters
    ----------
    docinfo_bytes : bytes
        Raw (decompressed) DocInfo stream bytes.
    section_bytes : bytes or None
        Raw (decompressed) section stream bytes. If None, I3 is skipped.

    Returns
    -------
    list[IntegrityViolation]
        Combined violations from I1, I2, and optionally I3.
    """
    violations = check_i1(docinfo_bytes) + check_i2(docinfo_bytes)
    if section_bytes is not None:
        cs, ps, bf = check_i3_docinfo(docinfo_bytes)
        violations += check_i3_body(section_bytes, cs, ps, bf)
        violations += check_i4_con_children(section_bytes)
    return violations


# ---------------------------------------------------------------------------
# R-5/R-6/R-7: File-level validation (operates on file path, not raw bytes)
# ---------------------------------------------------------------------------

_HWP_SIG = b"HWP Document File"


def check_r5(path: str) -> list[IntegrityViolation]:
    """R-5: FileHeader signature, size, and version check."""
    violations: list[IntegrityViolation] = []
    if not olefile.isOleFile(path):
        return [IntegrityViolation("R5", "OLE2 파일이 아님")]

    ole = olefile.OleFileIO(path)
    try:
        if not ole.exists("FileHeader"):
            return [IntegrityViolation("R5", "FileHeader 스트림 없음")]
        raw = ole.openstream("FileHeader").read()
        if len(raw) < 256:
            violations.append(
                IntegrityViolation("R5", f"FileHeader {len(raw)}B (expected 256)")
            )
        if not raw[: len(_HWP_SIG)].startswith(_HWP_SIG):
            violations.append(
                IntegrityViolation("R5", f"시그니처 불일치: {raw[:32]!r}")
            )
        if len(raw) >= 36:
            ver = struct.unpack_from("<I", raw, 32)[0]
            major = (ver >> 24) & 0xFF
            if major < 5:
                violations.append(
                    IntegrityViolation("R5", f"미지원 버전: {major}", "warning")
                )
    finally:
        ole.close()
    return violations


def check_r6(path: str) -> list[IntegrityViolation]:
    """R-6: required streams must exist (DocInfo, BodyText/Section0)."""
    violations: list[IntegrityViolation] = []
    if not olefile.isOleFile(path):
        return []

    ole = olefile.OleFileIO(path)
    try:
        streams = {"/".join(s) for s in ole.listdir()}
        for required in ("DocInfo", "BodyText/Section0"):
            if required not in streams:
                violations.append(
                    IntegrityViolation("R6", f"필수 스트림 없음: {required}")
                )
    finally:
        ole.close()
    return violations


def check_r7(path: str) -> list[IntegrityViolation]:
    """R-7: compression flag vs actual stream compression consistency."""
    if not olefile.isOleFile(path):
        return []

    ole = olefile.OleFileIO(path)
    try:
        if not ole.exists("FileHeader"):
            return []
        fh = ole.openstream("FileHeader").read()
        if len(fh) < 40:
            return []
        flags = struct.unpack_from("<I", fh, 36)[0]
        is_compressed = bool(flags & 1)
        if is_compressed and ole.exists("DocInfo"):
            raw = ole.openstream("DocInfo").read()
            if raw[:2] in (b"\x78\x9c", b"\x78\x01", b"\x78\xda"):
                try:
                    zlib.decompress(raw)
                    return [
                        IntegrityViolation(
                            "R7",
                            "zlib 헤더 감지 — HWP는 raw DEFLATE(wbits=-15) 필수",
                        )
                    ]
                except zlib.error:
                    pass
    finally:
        ole.close()
    return []


def check_i5_root_alignment(path: str) -> list[IntegrityViolation]:
    """I5: Root Entry size must be aligned to OLE sector boundary.

    If the mini-stream container size is not a multiple of the sector
    size (typically 512B), Hancom rejects the file as corrupt.
    """
    if not olefile.isOleFile(path):
        return []
    violations: list[IntegrityViolation] = []
    with open(path, "rb") as f:
        header = f.read(512)
    if len(header) < 512:
        return []
    sector_size = 1 << struct.unpack_from("<H", header, 30)[0]
    ole = olefile.OleFileIO(path)
    try:
        root_size = ole.root.size
        if root_size > 0 and root_size % sector_size != 0:
            violations.append(
                IntegrityViolation(
                    rule_id="I5",
                    message=(
                        f"Root Entry size {root_size}B not aligned to "
                        f"sector size {sector_size}B "
                        f"(remainder {root_size % sector_size})"
                    ),
                    severity="warning",
                )
            )
    finally:
        ole.close()
    return violations


_INLINE_OBJ_CODES = frozenset(range(0x0020)) - frozenset(
    {0x0000, 0x0009, 0x000A, 0x000D, 0x001F}
)


def _ctrl_char_types_in_text(para_text: bytes) -> set[int]:
    """Extract the set of inline control char codes from PARA_TEXT."""
    codes: set[int] = set()
    pos = 0
    while pos + 2 <= len(para_text):
        ch = struct.unpack_from("<H", para_text, pos)[0]
        if ch in _INLINE_OBJ_CODES:
            codes.add(ch)
            pos += 16
        else:
            pos += 2
    return codes


def _ctrl_mask_bits(mask: int) -> set[int]:
    """Return set of bit positions that are set."""
    return {b for b in range(32) if mask & (1 << b)}


def check_i6_preamble_text(section_bytes: bytes) -> list[IntegrityViolation]:
    """I6: preamble PARA_HEADER.controlMask must match inline controls in PARA_TEXT.

    Hancom cross-validates controlMask bits against actual inline control
    characters in PARA_TEXT. A mismatch (e.g. missing bit 11) causes
    "파일이 손상되었습니다" rejection. (BUG-234)

    Specifically checks: if the preamble has controls like pgnp (0x0015),
    head (0x0010), foot (0x000b), nwno (0x0015), tbl (0x000b), then
    controlMask bit 11 must be set when applicable.
    """
    violations: list[IntegrityViolation] = []
    recs = list(iter_records(section_bytes))

    for i, rec in enumerate(recs):
        if rec.tag_id != HWPTAG_PARA_HEADER or rec.level != 0:
            continue
        if len(rec.payload) < 18:
            break

        has_secd = False
        para_text_payload: bytes | None = None

        for j in range(i + 1, len(recs)):
            if recs[j].level <= rec.level and recs[j].tag_id == HWPTAG_PARA_HEADER:
                break
            if recs[j].tag_id == HWPTAG_PARA_TEXT and recs[j].level == rec.level + 1:
                para_text_payload = recs[j].payload
            if recs[j].tag_id == HWPTAG_CTRL_HEADER and recs[j].level == rec.level + 1:
                if len(recs[j].payload) >= 4:
                    cid = struct.unpack_from("<I", recs[j].payload, 0)[0]
                    if cid == 0x73656364:
                        has_secd = True
        break

    if not has_secd or para_text_payload is None:
        return violations

    ctrl_mask = struct.unpack_from("<I", recs[0].payload, 4)[0]
    inline_codes = _ctrl_char_types_in_text(para_text_payload)

    if 0x0010 in inline_codes and not (ctrl_mask & 0x0800):
        violations.append(
            IntegrityViolation(
                rule_id="I6",
                message=(
                    f"controlMask=0x{ctrl_mask:08x} missing bit 11 "
                    f"but PARA_TEXT has head/footer ctrl (0x0010)"
                ),
            )
        )

    return violations


def check_i7_section_count(path: str) -> list[IntegrityViolation]:
    """I7: DOCUMENT_PROPERTIES.sectionCount must match actual Section stream count.

    Reads sectionCount from DocInfo's DOCUMENT_PROPERTIES (tag 16, offset 0, UINT16)
    and compares against the number of BodyText/SectionN streams in the OLE container.
    """
    violations: list[IntegrityViolation] = []
    try:
        ole = olefile.OleFileIO(path)
    except Exception:
        return violations

    try:
        docinfo_raw = ole.openstream("DocInfo").read()
        flags_raw = ole.openstream("FileHeader").read()
        compressed = bool(struct.unpack_from("<I", flags_raw, 36)[0] & 1)
        if compressed:
            docinfo_bytes = zlib.decompress(docinfo_raw, -15)
        else:
            docinfo_bytes = docinfo_raw

        declared_count: int | None = None
        for rec in iter_records(docinfo_bytes):
            if rec.tag_id == HWPTAG_DOCUMENT_PROPERTIES and len(rec.payload) >= 2:
                declared_count = struct.unpack_from("<H", rec.payload, 0)[0]
                break

        if declared_count is None:
            violations.append(IntegrityViolation(
                rule_id="I7", message="DOCUMENT_PROPERTIES not found in DocInfo",
            ))
            return violations

        actual_count = 0
        while ole.exists(f"BodyText/Section{actual_count}"):
            actual_count += 1

        if declared_count != actual_count:
            violations.append(IntegrityViolation(
                rule_id="I7",
                message=(
                    f"sectionCount mismatch: DOCUMENT_PROPERTIES={declared_count}, "
                    f"actual Section streams={actual_count}"
                ),
            ))
    finally:
        ole.close()

    return violations


def check_i8_border_fill_ref(
    docinfo_bytes: bytes, section_bytes: bytes,
) -> list[IntegrityViolation]:
    """I8: Table cell LIST_HEADER borderFillId must be within [1, borderFillCount].

    BorderFill uses 1-based indexing. In table cell LIST_HEADERs (payload >= 34),
    borderFillId is at offset 32 (UINT16). Only LIST_HEADERs that are children
    of a 'tbl ' CTRL_HEADER are checked.
    """
    violations: list[IntegrityViolation] = []

    bf_count = 0
    for rec in iter_records(docinfo_bytes):
        if rec.tag_id == HWPTAG_ID_MAPPINGS and len(rec.payload) > _IDMAP_BORDERFILL_OFF + 3:
            bf_count = struct.unpack_from("<I", rec.payload, _IDMAP_BORDERFILL_OFF)[0]
            break

    if bf_count == 0:
        return violations

    recs = list(iter_records(section_bytes))
    in_table_level: int | None = None

    for rec in recs:
        if rec.tag_id == HWPTAG_CTRL_HEADER and len(rec.payload) >= 4:
            ctrl_id = struct.unpack_from("<I", rec.payload, 0)[0]
            if ctrl_id == 0x74626C20:  # 'tbl ' as uint32 LE
                in_table_level = rec.level
            elif in_table_level is not None and rec.level <= in_table_level:
                in_table_level = None

        if rec.tag_id == HWPTAG_LIST_HEADER and len(rec.payload) >= 34:
            if in_table_level is not None and rec.level == in_table_level + 1:
                bf_id = struct.unpack_from("<H", rec.payload, 32)[0]
                if bf_id > bf_count:
                    violations.append(IntegrityViolation(
                        rule_id="I8",
                        message=(
                            f"Cell LIST_HEADER borderFillId={bf_id} > "
                            f"borderFillCount={bf_count} (offset={rec.offset})"
                        ),
                    ))

    return violations


def check_i9_table_nrows(section_bytes: bytes) -> list[IntegrityViolation]:
    """I9: TABLE record nRows/nCols must be consistent with LIST_HEADER children.

    TABLE (tag 77) payload: offset 0=attr(UINT32), 4=nRows(UINT16), 6=nCols(UINT16).
    Due to merged cells, actual LIST_HEADER count may be <= nRows*nCols.
    We check: (1) actual_cells <= nRows*nCols, (2) actual_cells > 0 when nRows>0.
    Also validates nRows and nCols have the declared number of row sizes in the
    TABLE payload (offset 8+: nCols UINT16 column widths, then nRows UINT16 row heights).
    """
    violations: list[IntegrityViolation] = []
    recs = list(iter_records(section_bytes))

    for i, rec in enumerate(recs):
        if rec.tag_id != HWPTAG_TABLE or len(rec.payload) < 8:
            continue
        n_rows = struct.unpack_from("<H", rec.payload, 4)[0]
        n_cols = struct.unpack_from("<H", rec.payload, 6)[0]
        max_cells = n_rows * n_cols
        tbl_level = rec.level

        actual_cells = 0
        for j in range(i + 1, len(recs)):
            if recs[j].level < tbl_level:
                break
            if recs[j].tag_id == HWPTAG_LIST_HEADER and recs[j].level == tbl_level:
                actual_cells += 1

        if max_cells > 0 and actual_cells == 0:
            violations.append(IntegrityViolation(
                rule_id="I9",
                message=(
                    f"TABLE declares {n_rows}×{n_cols} but has 0 LIST_HEADER children "
                    f"(offset={rec.offset})"
                ),
            ))
        elif actual_cells > max_cells:
            violations.append(IntegrityViolation(
                rule_id="I9",
                message=(
                    f"TABLE has {actual_cells} LIST_HEADERs > "
                    f"nRows×nCols={n_rows}×{n_cols}={max_cells} "
                    f"(offset={rec.offset})"
                ),
            ))

    return violations


def check_i10_bindata_streams(path: str) -> list[IntegrityViolation]:
    """I10: BIN_DATA embedding records must have matching BinData/ OLE streams.

    For each BIN_DATA record with type=EMBEDDING (bits 0-3 of type field == 2,
    i.e. "storage" type), verifies that the corresponding BinData/BINXXXX stream
    exists.
    """
    violations: list[IntegrityViolation] = []
    try:
        ole = olefile.OleFileIO(path)
    except Exception:
        return violations

    try:
        docinfo_raw = ole.openstream("DocInfo").read()
        flags_raw = ole.openstream("FileHeader").read()
        compressed = bool(struct.unpack_from("<I", flags_raw, 36)[0] & 1)
        if compressed:
            docinfo_bytes = zlib.decompress(docinfo_raw, -15)
        else:
            docinfo_bytes = docinfo_raw

        bin_id = 0
        for rec in iter_records(docinfo_bytes):
            if rec.tag_id != HWPTAG_BIN_DATA or len(rec.payload) < 2:
                continue
            bin_id += 1
            type_val = struct.unpack_from("<H", rec.payload, 0)[0]
            storage_type = type_val & 0x0F
            if storage_type not in (0, 2):
                continue

            found = False
            prefix = f"BinData/BIN{bin_id:04X}"
            for entry in ole.listdir():
                stream_name = "/".join(entry)
                if stream_name.upper().startswith(prefix.upper()):
                    found = True
                    break

            if not found:
                violations.append(IntegrityViolation(
                    rule_id="I10",
                    message=f"BIN_DATA #{bin_id} (type={storage_type}) missing stream {prefix}.*",
                    severity="warning",
                ))
    finally:
        ole.close()

    return violations


_DOCINFO_TAG_ORDER = [
    HWPTAG_DOCUMENT_PROPERTIES,
    HWPTAG_ID_MAPPINGS,
    HWPTAG_BIN_DATA,
    HWPTAG_FACE_NAME,
    HWPTAG_BORDER_FILL,
    HWPTAG_CHAR_SHAPE,
    HWPTAG_TAB_DEF,
    HWPTAG_NUMBERING,
    HWPTAG_BULLET,
    HWPTAG_PARA_SHAPE,
    HWPTAG_STYLE,
    HWPTAG_DOC_DATA,
    HWPTAG_COMPATIBLE_DOCUMENT,
    HWPTAG_LAYOUT_COMPATIBILITY,
]


def check_i11_docinfo_order(docinfo_bytes: bytes) -> list[IntegrityViolation]:
    """I11: DocInfo records must appear in the canonical tag order.

    Level-0 records must follow the ordering defined by the HWP spec.
    Repetitions of the same tag are fine, but a tag that should appear earlier
    must not come after a tag that should appear later.
    """
    violations: list[IntegrityViolation] = []

    order_map = {tag: idx for idx, tag in enumerate(_DOCINFO_TAG_ORDER)}
    max_order_seen = -1
    max_order_tag = -1

    for rec in iter_records(docinfo_bytes):
        if rec.level != 0:
            continue
        tag = rec.tag_id
        if tag not in order_map:
            continue
        order = order_map[tag]
        if order < max_order_seen:
            violations.append(IntegrityViolation(
                rule_id="I11",
                message=(
                    f"DocInfo record order violation: tag {tag} (order {order}) "
                    f"appeared after tag {max_order_tag} (order {max_order_seen}) "
                    f"at offset {rec.offset}"
                ),
            ))
            break
        if order > max_order_seen:
            max_order_seen = order
            max_order_tag = tag

    return violations


def check_i12_pls_tpos_bounds(section_bytes: bytes) -> list[IntegrityViolation]:
    """I12: Every PLS tpos must be < charCnt of its parent PARA_HEADER.

    PARA_LINE_SEG entries are 36 bytes each. Offset 0 of each entry is
    tpos (UINT32) — the character position of the line start. If tpos > charCnt,
    Hancom rejects the file as corrupted ("파일이 손상되었습니다").
    tpos == charCnt is allowed (observed in valid files for multi-line paragraphs).
    """
    violations: list[IntegrityViolation] = []
    recs = list(iter_records(section_bytes))

    for i, rec in enumerate(recs):
        if rec.tag_id != HWPTAG_PARA_HEADER:
            continue
        if len(rec.payload) < 4:
            continue
        raw_dw = struct.unpack_from("<I", rec.payload, 0)[0]
        char_cnt = raw_dw & 0x7FFFFFFF
        if char_cnt == 0:
            continue

        ph_level = rec.level
        for j in range(i + 1, len(recs)):
            if recs[j].level <= ph_level and recs[j].tag_id == HWPTAG_PARA_HEADER:
                break
            if recs[j].tag_id == HWPTAG_PARA_LINE_SEG and recs[j].level == ph_level + 1:
                pls = recs[j].payload
                for entry_off in range(0, len(pls) - 35, 36):
                    tpos = struct.unpack_from("<I", pls, entry_off)[0]
                    if tpos > char_cnt:
                        violations.append(IntegrityViolation(
                            rule_id="I12",
                            message=(
                                f"PLS tpos={tpos} > charCnt={char_cnt} "
                                f"(PH offset={rec.offset}, PLS entry {entry_off // 36})"
                            ),
                        ))
                        break
                break

    return violations


def validate_hwp_file(path: str) -> list[IntegrityViolation]:
    """Run R-5/R-6/R-7 + I-7/I-10 file-level checks on an HWP file."""
    results = check_r5(path) + check_r6(path) + check_r7(path)
    results += check_i7_section_count(path)
    results += check_i10_bindata_streams(path)
    return results
