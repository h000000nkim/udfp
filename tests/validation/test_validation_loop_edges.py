"""A3: validation_loop 엣지케이스 테스트.

기존 test_validation_loop.py는 정상/파손 기본 시나리오를 커버.
여기서는 엣지케이스를 추가:
  - max_iterations=0 → 수정 없이 즉시 반환
  - max_iterations=1 → 1회만 시도
  - verbatim 없는 문서 → 수정 불가, 리포트만 반환
  - 이미 통과하는 문서 → 즉시 반환 (0회 반복)
"""

from __future__ import annotations

import base64
import pathlib
import struct

import pytest

from udf.core.schema import (
    DocumentMetadata,
    ParagraphBlock,
    TextInline,
    UdfDocument,
)
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


def _corrupt_charcnt(doc: UdfDocument) -> UdfDocument:
    """charCnt를 잘못된 값으로 파손."""
    assert doc.verbatim is not None
    stream = base64.b64decode(doc.verbatim.section_streams["Section0"])
    records = list(iter_records(stream))
    for i, rec in enumerate(records):
        if rec.tag_id == HWPTAG_PARA_HEADER and len(rec.payload) >= 4:
            ph = bytearray(rec.payload)
            old_dw = struct.unpack_from("<I", ph, 0)[0]
            msb = old_dw & 0x80000000
            struct.pack_into("<I", ph, 0, msb | 99999)
            records[i] = HwpRecord(rec.tag_id, rec.level, bytes(ph), rec.offset)

    from tests.validation.test_validation_loop import _serialize_records
    corrupted = _serialize_records(records)
    doc.verbatim.section_streams["Section0"] = base64.b64encode(corrupted).decode()

    from udf.validation.validation_loop import _reparse_from_streams
    return _reparse_from_streams(doc)


class TestMaxIterationsZero:
    def test_zero_iterations_no_fix(self):
        """max_iterations=0이면 수정 시도 없이 원본 리포트 반환."""
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        corrupted = _corrupt_charcnt(doc)
        result_doc, report = validate_and_fix(corrupted, max_iterations=0)
        assert not report.is_passing()


class TestMaxIterationsOne:
    def test_single_iteration_may_converge(self):
        """max_iterations=1이면 1회 수정 시도. charCnt 파손은 1회면 충분."""
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        corrupted = _corrupt_charcnt(doc)
        _, report = validate_and_fix(corrupted, max_iterations=1)
        assert report.is_passing(), "1회 수정으로 수렴 실패"


class TestAlreadyPassing:
    def test_passing_returns_immediately(self):
        """이미 통과하는 문서는 즉시 반환."""
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        original_streams = dict(doc.verbatim.section_streams)

        fixed, report = validate_and_fix(doc)
        assert report.is_passing()
        for key, val in fixed.verbatim.section_streams.items():
            assert val == original_streams[key], "통과 문서의 스트림이 변경됨"


class TestNoVerbatim:
    def test_no_verbatim_returns_report(self):
        """verbatim 레이어 없는 문서는 수정 불가, 리포트만 반환."""
        doc = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[TextInline(text="test")],
            )],
        )
        fixed, report = validate_and_fix(doc)
        assert fixed is doc
