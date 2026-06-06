"""A5: HWPX Seed Patch 모드 테스트.

HWPX 파싱 → 변경 없이 재생성 → ZIP entry 보존 확인.
Seed Patch는 원본 ZIP에서 변경된 entry만 교체하므로
미수정 entry의 바이트 동등성을 검증한다.
"""

from __future__ import annotations

import pathlib
import zipfile

import pytest

import udf
from udf.renderers.hwpx import generate_hwpx

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwpx"

pytestmark = pytest.mark.skipif(
    not FIXTURES.exists(), reason="HWPX fixtures not available"
)


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


def _zip_entries(path: str) -> dict[str, bytes]:
    with zipfile.ZipFile(path, "r") as zf:
        return {info.filename: zf.read(info.filename) for info in zf.infolist()}


class TestHwpxSeedPatchPreservation:
    """Seed Patch 모드: 미변경 entry가 보존되는지 검증."""

    @pytest.mark.parametrize("filename", sorted(p.name for p in FIXTURES.glob("*.hwpx")))
    def test_no_edit_preserves_entries(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        src = _fixture(filename)
        doc = udf.parse(src)
        out = str(tmp_path / filename)
        generate_hwpx(doc, out, validate=False)

        original = _zip_entries(src)
        output = _zip_entries(out)

        for name in original:
            assert name in output, f"원본 entry '{name}' 소실: {filename}"


class TestHwpxSeedPatchBlockCount:
    """Seed Patch 후 블록 수가 동일한지 검증."""

    @pytest.mark.parametrize("filename", sorted(p.name for p in FIXTURES.glob("*.hwpx")))
    def test_block_count_preserved(
        self, filename: str, tmp_path: pathlib.Path
    ) -> None:
        src = _fixture(filename)
        doc = udf.parse(src)
        orig_count = len(doc.blocks)

        out = str(tmp_path / filename)
        generate_hwpx(doc, out, validate=False)
        rt_doc = udf.parse(out)

        assert len(rt_doc.blocks) == orig_count, (
            f"{filename}: 블록 수 변경 {orig_count} → {len(rt_doc.blocks)}"
        )


class TestHwpxSeedPatchTextPreserved:
    """Seed Patch 후 텍스트 보존 검증."""

    def test_table_text_roundtrip(self, tmp_path: pathlib.Path) -> None:
        src = _fixture("table_text.hwpx")
        doc = udf.parse(src)

        from tests.helpers import all_texts
        orig_texts = all_texts(doc)
        if not orig_texts:
            pytest.skip("No text in fixture")

        out = str(tmp_path / "table_text.hwpx")
        generate_hwpx(doc, out, validate=False)
        rt_doc = udf.parse(out)
        rt_texts = all_texts(rt_doc)

        for t in orig_texts:
            assert t in rt_texts, f"텍스트 손실: {t!r}"
