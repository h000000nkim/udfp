"""f15-f21 HWP fixture 통합 파싱 테스트 — 수식, 양식 문서."""

from __future__ import annotations

import pathlib

import pytest

from udf.parsers.hwp.parse import parse_hwp
from udf.core.schema import ParagraphBlock, TableBlock

FIXTURES = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


MATH_FILES = [
    "f15_math_hanoi.hwp",
    "f16_math_log.hwp",
    "f17_math_quadratic.hwp",
]

FORM_FILES = [
    "f19_career_report.hwp",
    "f20_topic_report.hwp",
    "f21_library_plan.hwp",
]

ALL_FILES = MATH_FILES + FORM_FILES


class TestAdvancedFixturesParse:
    @pytest.mark.parametrize("filename", ALL_FILES)
    def test_parses_without_error(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        assert doc is not None
        assert doc.source_format == "hwp"

    @pytest.mark.parametrize("filename", ALL_FILES)
    def test_has_blocks(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        assert len(doc.blocks) > 0


class TestMathFixtures:
    def test_f15_has_equations(self) -> None:
        doc = parse_hwp(_fixture("f15_math_hanoi.hwp"))
        eq_blocks = [b for b in doc.blocks if b.type == "equation"]
        assert len(eq_blocks) >= 10

    def test_f15_has_tables(self) -> None:
        doc = parse_hwp(_fixture("f15_math_hanoi.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1

    def test_f16_has_tables(self) -> None:
        doc = parse_hwp(_fixture("f16_math_log.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 10

    def test_f17_has_tables(self) -> None:
        doc = parse_hwp(_fixture("f17_math_quadratic.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1


class TestFormFixtures:
    def test_f19_has_table(self) -> None:
        doc = parse_hwp(_fixture("f19_career_report.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1

    def test_f19_contains_form_text(self) -> None:
        doc = parse_hwp(_fixture("f19_career_report.hwp"))
        all_text = " ".join(
            i.text
            for b in doc.blocks
            if isinstance(b, ParagraphBlock)
            for i in b.inlines
            if hasattr(i, "text")
        )
        assert "진로" in all_text or "보고서" in all_text

    def test_f20_has_table(self) -> None:
        doc = parse_hwp(_fixture("f20_topic_report.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1

    def test_f20_contains_form_text(self) -> None:
        doc = parse_hwp(_fixture("f20_topic_report.hwp"))
        all_text = " ".join(
            i.text
            for b in doc.blocks
            if isinstance(b, ParagraphBlock)
            for i in b.inlines
            if hasattr(i, "text")
        )
        assert "주제탐구" in all_text or "보고서" in all_text

    def test_f21_large_document(self) -> None:
        doc = parse_hwp(_fixture("f21_library_plan.hwp"))
        assert len(doc.blocks) >= 100

    def test_f21_has_many_tables(self) -> None:
        doc = parse_hwp(_fixture("f21_library_plan.hwp"))
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 20
