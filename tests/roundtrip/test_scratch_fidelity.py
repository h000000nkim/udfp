"""From Scratch 모드의 decompressed 바이트 정확성 테스트.

HWP→Scratch→HWP에서 원본과 Scratch의 decompressed 섹션 바이트를
레코드 단위로 비교하여 차이를 추적한다.

현재 상태: Scratch는 원본과 decompressed 동일을 보장하지 않음.
이 테스트는 차이의 수와 종류를 모니터링하여 개선을 추적한다.
"""

from __future__ import annotations

import pathlib
import struct
import zlib

import olefile
import pytest

from udf.parsers.hwp.parse import parse_hwp
from udf.parsers.hwp.records import iter_records
from udf.renderers.hwp.scratch import generate_hwp_scratch


_FIXTURES = pathlib.Path("tests/fixtures/hwp")
_SEED = str(_FIXTURES / "f01_plain_text.hwp")


def _decompress_section(path: str, section: str = "Section0") -> bytes:
    ole = olefile.OleFileIO(path)
    fh = ole.openstream("FileHeader").read()
    compressed = bool(struct.unpack_from("<I", fh, 36)[0] & 1)
    raw = ole.openstream(f"BodyText/{section}").read()
    ole.close()
    return zlib.decompress(raw, -15) if compressed else raw


def _count_record_diffs(orig: bytes, scratch: bytes) -> int:
    orig_recs = list(iter_records(orig))
    scratch_recs = list(iter_records(scratch))
    diffs = 0
    for o, s in zip(orig_recs, scratch_recs):
        if o.tag_id != s.tag_id or o.payload != s.payload or o.level != s.level:
            diffs += 1
    diffs += abs(len(orig_recs) - len(scratch_recs))
    return diffs


_RECORD_COUNT_XFAIL = {
    "f15_math_hanoi.hwp", "f16_math_log.hwp", "f17_math_quadratic.hwp",
    "f20_topic_report.hwp", "f21_library_plan.hwp",
}


@pytest.mark.parametrize(
    "filename",
    [f.name for f in _FIXTURES.glob("f[0-9]*.hwp")],
)
def test_scratch_record_count_matches(filename: str, tmp_path: pathlib.Path) -> None:
    """Scratch 출력의 레코드 수가 원본과 일치해야 한다."""
    if filename in _RECORD_COUNT_XFAIL:
        pytest.xfail(f"{filename}: 복잡한 구조 (수식/보고서) 레코드 재현 미완")
    src = str(_FIXTURES / filename)
    out = str(tmp_path / filename)
    doc = parse_hwp(src)
    generate_hwp_scratch(doc, out, _SEED)

    orig_dec = _decompress_section(src)
    scratch_dec = _decompress_section(out)

    orig_count = len(list(iter_records(orig_dec)))
    scratch_count = len(list(iter_records(scratch_dec)))
    assert orig_count == scratch_count, (
        f"레코드 수 불일치: 원본 {orig_count} vs Scratch {scratch_count}"
    )


@pytest.mark.parametrize(
    "filename",
    [f.name for f in _FIXTURES.glob("f[0-9]*.hwp")],
)
def test_scratch_diff_tracking(filename: str, tmp_path: pathlib.Path) -> None:
    """Scratch 출력의 레코드 차이 수를 추적한다 (개선 모니터링)."""
    src = str(_FIXTURES / filename)
    out = str(tmp_path / filename)
    doc = parse_hwp(src)
    generate_hwp_scratch(doc, out, _SEED)

    orig_dec = _decompress_section(src)
    scratch_dec = _decompress_section(out)
    diffs = _count_record_diffs(orig_dec, scratch_dec)
    total = len(list(iter_records(orig_dec)))
    pct = diffs / total * 100 if total else 0
    print(f"{filename}: {diffs}/{total} records differ ({pct:.0f}%)")
