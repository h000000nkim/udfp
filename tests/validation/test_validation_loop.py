"""검증 자동수정 루프 테스트.

정상 문서 → noop (바로 통과)
파손 문서 → 수렴 → 통과
"""

from __future__ import annotations

import base64
import pathlib
import struct

import pytest

from udf.parsers.hwp.parse import parse_hwp
from udf.parsers.hwp.records import (
    HWPTAG_PARA_HEADER,
    HwpRecord,
    iter_records,
)
from udf.validation.hwp.rules import validate_hwp
from udf.validation.validation_loop import validate_and_fix

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


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
# 정상 문서: validation loop = noop
# ---------------------------------------------------------------------------


class TestNoop:
    @pytest.mark.parametrize(
        "filename",
        [
            "f01_plain_text.hwp",
            "f02_char_format.hwp",
            "f03_para_align.hwp",
            "f04_simple_table.hwp",
            "f05_table_cell_text.hwp",
            "f06_multiline.hwp",
            "f07_hangul_latin.hwp",
            "f08_empty_paras.hwp",
            "f09_heading_h1h2.hwp",
            "f10_inline_mixed.hwp",
            "f11_para_align_4.hwp",
            "f12_heading_h1h4.hwp",
            "f13_pure_hangul.hwp",
            "f14_multilang_format.hwp",
        ],
    )
    def test_passing_doc_unchanged(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        original_streams = dict(doc.verbatim.section_streams) if doc.verbatim else {}

        fixed_doc, report = validate_and_fix(doc)
        assert report.is_passing(), f"검증 실패 ({filename}): " + ", ".join(
            f"{v.rule_id}:{v.message}" for v in report.all_violations
        )

        if fixed_doc.verbatim:
            for key, val in fixed_doc.verbatim.section_streams.items():
                assert val == original_streams.get(key), (
                    f"noop이어야 하는데 스트림 변경됨: {key}"
                )


# ---------------------------------------------------------------------------
# 파손 문서: charCnt 파손 → 자동 수정 → 수렴
# ---------------------------------------------------------------------------


class TestConvergence:
    def test_corrupted_charcnt_converges(self) -> None:
        """charCnt를 파손한 문서가 validation loop로 수렴한다."""
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        assert doc.verbatim is not None

        stream = base64.b64decode(doc.verbatim.section_streams["Section0"])
        records = list(iter_records(stream))

        corrupted_count = 0
        for i, rec in enumerate(records):
            if rec.tag_id == HWPTAG_PARA_HEADER and len(rec.payload) >= 4:
                ph = bytearray(rec.payload)
                old_dw = struct.unpack_from("<I", ph, 0)[0]
                msb = old_dw & 0x80000000
                struct.pack_into("<I", ph, 0, msb | 99999)
                records[i] = HwpRecord(rec.tag_id, rec.level, bytes(ph), rec.offset)
                corrupted_count += 1

        assert corrupted_count > 0, "파손할 PARA_HEADER가 없음"

        corrupted = _serialize_records(records)
        doc.verbatim.section_streams["Section0"] = base64.b64encode(corrupted).decode()

        # 파손 상태에서 검증 실패 확인 (역검증)
        from udf.validation.validation_loop import _reparse_from_streams

        corrupted_doc = _reparse_from_streams(doc)
        pre_report = validate_hwp(corrupted_doc)
        assert not pre_report.is_passing(), "파손 데이터인데 검증 통과 (역검증 실패)"

        # validation loop 실행
        fixed_doc, report = validate_and_fix(corrupted_doc)
        assert report.is_passing(), "자동수정 후에도 검증 실패: " + ", ".join(
            f"{v.rule_id}:{v.message}" for v in report.all_violations
        )
