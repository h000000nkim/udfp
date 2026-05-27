"""HWP 파일 구조 정합성 검증 — 생성된 파일의 무결성을 확인.

R-규칙(rules.py)은 파싱된 UdfDocument 기반 검증이고,
이 모듈은 생성된 HWP 바이너리 파일의 구조적 정합성을 검증한다.

I-규칙 (Integrity Rules):
  I1: ID_MAPPINGS 카운트 == 실제 레코드 수 (CS, PS, BF, BinData)
  I2: 모든 CharShape의 face_id < FaceName 수
  I3: Body에서 참조하는 CS/PS ID < 실제 레코드 수
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Literal

from udf.parsers.hwp.records import (
    HWPTAG_BIN_DATA,
    HWPTAG_BORDER_FILL,
    HWPTAG_CHAR_SHAPE,
    HWPTAG_FACE_NAME,
    HWPTAG_ID_MAPPINGS,
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HWPTAG_PARA_SHAPE,
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
        violations.append(IntegrityViolation(
            rule_id="I1",
            message="ID_MAPPINGS record not found in DocInfo",
        ))
        return violations

    for rec_type in ["BinData", "BorderFill", "CharShape", "ParaShape"]:
        expected = idmap_counts[rec_type]
        actual = actual_counts[rec_type]
        if expected != actual:
            violations.append(IntegrityViolation(
                rule_id="I1",
                message=f"ID_MAPPINGS {rec_type} count={expected} but actual records={actual}",
            ))

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
    idmap_payload: bytes | None = None
    cs_faces: list[tuple[int, list[int]]] = []  # (cs_idx, [face_id×7])

    cs_idx = 0
    for rec in iter_records(docinfo_bytes):
        if rec.tag_id == HWPTAG_ID_MAPPINGS and len(rec.payload) >= 32:
            idmap_payload = rec.payload
            for lang in range(7):
                face_counts.append(struct.unpack_from("<I", rec.payload, 4 + lang * 4)[0])
        elif rec.tag_id == HWPTAG_CHAR_SHAPE and len(rec.payload) >= 14:
            faces = list(struct.unpack_from("<7H", rec.payload, 0))
            cs_faces.append((cs_idx, faces))
            cs_idx += 1

    if not face_counts:
        return violations

    for idx, faces in cs_faces:
        for lang, fid in enumerate(faces):
            if lang < len(face_counts) and fid >= face_counts[lang]:
                violations.append(IntegrityViolation(
                    rule_id="I2",
                    message=f"CharShape[{idx}] face_id[{lang}]={fid} >= FaceName count={face_counts[lang]}",
                ))
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
) -> list[IntegrityViolation]:
    """Validate I3: body CS/PS references must be within DocInfo record bounds.

    Checks that every ParaShape ID in PARA_HEADER and every CharShape ID
    in PARA_CHAR_SHAPE records are less than the actual record counts.

    Parameters
    ----------
    section_bytes : bytes
        Raw (decompressed) section stream bytes.
    cs_count : int
        Total number of CharShape records in DocInfo.
    ps_count : int
        Total number of ParaShape records in DocInfo.

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
                violations.append(IntegrityViolation(
                    rule_id="I3",
                    message=f"Para[{para_idx}] ParaShape ID={ps_id} >= PS count={ps_count}",
                ))
            para_idx += 1
        elif rec.tag_id == HWPTAG_PARA_CHAR_SHAPE:
            n_entries = len(rec.payload) // 8
            for k in range(n_entries):
                cs_id = struct.unpack_from("<I", rec.payload, k * 8 + 4)[0]
                if cs_id >= cs_count:
                    violations.append(IntegrityViolation(
                        rule_id="I3",
                        message=f"PCS entry CharShape ID={cs_id} >= CS count={cs_count}",
                    ))
                    break

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
        cs, ps, _ = check_i3_docinfo(docinfo_bytes)
        violations += check_i3_body(section_bytes, cs, ps)
    return violations
