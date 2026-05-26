"""HWP R-규칙 자동 수정자 테스트.

정상 데이터 → 멱등성 확인
고의 파손 데이터 → fixer 복구 → R-규칙 통과 확인
"""

from __future__ import annotations

import base64
import pathlib
import struct

import pytest

from udf.parsers.hwp.parse import parse_hwp
from udf.parsers.hwp.records import (
    HWPTAG_PARA_CHAR_SHAPE,
    HWPTAG_PARA_HEADER,
    HwpRecord,
    iter_records,
)
from udf.validation.hwp.fixers import (
    fix_lineseg_r3,
    fix_oob_charshape,
    normalize_para_headers,
)
from udf.validation.hwp.rules import validate_hwp

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


def _get_section_stream(doc, section: str = "Section0") -> bytes:
    assert doc.verbatim is not None
    b64 = doc.verbatim.section_streams.get(section)
    assert b64 is not None
    return base64.b64decode(b64)


def _serialize_record(rec: HwpRecord) -> bytes:
    size = len(rec.payload)
    if size < 0xFFF:
        h = rec.tag_id | (rec.level << 10) | (size << 20)
        return struct.pack("<I", h) + rec.payload
    h = rec.tag_id | (rec.level << 10) | (0xFFF << 20)
    return struct.pack("<II", h, size) + rec.payload


def _serialize_records(records: list[HwpRecord]) -> bytes:
    return b"".join(_serialize_record(r) for r in records)


# ---------------------------------------------------------------------------
# 멱등성: 정상 스트림에 fixer 적용 → 변화 없음
# ---------------------------------------------------------------------------


class TestIdempotent:
    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
        ],
    )
    def test_normalize_para_headers_noop(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        stream = _get_section_stream(doc)
        result = normalize_para_headers(stream)
        assert result == stream

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f06_multiline.hwp",
        ],
    )
    def test_fix_lineseg_r3_noop(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        stream = _get_section_stream(doc)
        result = fix_lineseg_r3(stream)
        assert result == stream

    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
        ],
    )
    def test_fix_oob_charshape_noop(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        stream = _get_section_stream(doc)
        result = fix_oob_charshape(stream)
        assert result == stream


# ---------------------------------------------------------------------------
# R1 파손 → normalize_para_headers 복구
# ---------------------------------------------------------------------------


class TestR1Fix:
    def test_corrupted_charcnt_fixed(self) -> None:
        """charCnt를 고의 파손 → fixer 복구 → R-규칙 통과."""
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        stream = _get_section_stream(doc)

        # charCnt를 99999로 파손
        records = list(iter_records(stream))
        for i, rec in enumerate(records):
            if rec.tag_id == HWPTAG_PARA_HEADER and len(rec.payload) >= 4:
                ph = bytearray(rec.payload)
                old_dw = struct.unpack_from("<I", ph, 0)[0]
                msb = old_dw & 0x80000000
                struct.pack_into("<I", ph, 0, msb | 99999)
                records[i] = HwpRecord(rec.tag_id, rec.level, bytes(ph), rec.offset)
                break

        corrupted = _serialize_records(records)
        assert corrupted != stream

        fixed = normalize_para_headers(corrupted)
        assert fixed != corrupted

        # 수정된 스트림으로 재파싱 후 R1 통과 확인
        doc.verbatim.section_streams["Section0"] = base64.b64encode(fixed).decode()
        from udf.validation.validation_loop import _reparse_from_streams

        reparsed = _reparse_from_streams(doc)
        report = validate_hwp(reparsed)
        r1_violations = [v for v in report.r1 if v.rule_id == "R1"]
        assert not r1_violations, f"R1 여전히 위반: {r1_violations}"

    def test_msb_preserved_after_fix(self) -> None:
        """charCnt 수정 시 MSB가 보존되는지 확인 (함정 5)."""
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        stream = _get_section_stream(doc)

        records = list(iter_records(stream))
        for i, rec in enumerate(records):
            if rec.tag_id == HWPTAG_PARA_HEADER and len(rec.payload) >= 4:
                ph = bytearray(rec.payload)
                # MSB 설정 + charCnt 파손
                struct.pack_into("<I", ph, 0, 0x80000000 | 99999)
                records[i] = HwpRecord(rec.tag_id, rec.level, bytes(ph), rec.offset)
                break

        corrupted = _serialize_records(records)
        fixed = normalize_para_headers(corrupted)

        fixed_records = list(iter_records(fixed))
        for rec in fixed_records:
            if rec.tag_id == HWPTAG_PARA_HEADER and len(rec.payload) >= 4:
                (dw,) = struct.unpack_from("<I", rec.payload, 0)
                assert dw & 0x80000000, "MSB가 손실됨"
                break


# ---------------------------------------------------------------------------
# R4 파손 → fix_oob_charshape 복구
# ---------------------------------------------------------------------------


class TestR4Fix:
    def test_oob_pcs_removed(self) -> None:
        """PCS pos를 charCnt 이상으로 파손 → fixer가 제거."""
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        stream = _get_section_stream(doc)

        records = list(iter_records(stream))
        for i, rec in enumerate(records):
            if rec.tag_id == HWPTAG_PARA_CHAR_SHAPE and len(rec.payload) >= 8:
                pcs = bytearray(rec.payload)
                # 첫 번째 PCS 엔트리의 pos를 0으로 유지, OOB 엔트리 추가
                oob_entry = bytearray(8)
                struct.pack_into("<I", oob_entry, 0, 99999)  # pos = 99999
                struct.pack_into("<I", oob_entry, 4, 0)  # char_shape_id = 0
                new_pcs = pcs + bytes(oob_entry)
                records[i] = HwpRecord(
                    rec.tag_id, rec.level, bytes(new_pcs), rec.offset
                )
                break

        corrupted = _serialize_records(records)
        fixed = fix_oob_charshape(corrupted)

        # OOB 엔트리가 제거되었는지 확인
        fixed_records = list(iter_records(fixed))
        for rec in fixed_records:
            if rec.tag_id == HWPTAG_PARA_CHAR_SHAPE:
                for off in range(0, len(rec.payload) - 7, 8):
                    (pos,) = struct.unpack_from("<I", rec.payload, off)
                    assert pos < 99999, f"OOB PCS 엔트리 미제거: pos={pos}"
                break
