"""HWP verbatim roundtrip tests — table structure preservation.

Verifies that Seed Patch renderer preserves table structure through roundtrip.
General block/text/validation roundtrip is covered by test_p0_roundtrip.py.

HWP verbatim 라운드트립 테스트. 테이블 구조 보존을 검증.
일반적 블록/텍스트/검증 라운드트립은 test_p0_roundtrip.py에서 수행.
"""

from __future__ import annotations

import pathlib

import pytest

from udf.renderers.hwp import generate_hwp
from udf.parsers.hwp.parse import parse_hwp
from udf.core.schema import ParagraphBlock, TableBlock

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


class TestVerbatimTableRoundtrip:
    """Table structure preservation through HWP roundtrip."""

    def test_f04_table_preserved(self, tmp_path: pathlib.Path) -> None:
        """f04_simple_table.hwp의 테이블 구조(2행 3열)가 라운드트립 후 보존."""
        doc_orig = parse_hwp(_fixture("f04_simple_table.hwp"))
        out = str(tmp_path / "f04_rt.hwp")
        generate_hwp(doc_orig, out)

        doc_rt = parse_hwp(out)
        tables_rt = [b for b in doc_rt.blocks if isinstance(b, TableBlock)]
        assert len(tables_rt) >= 1
        tbl = tables_rt[0]
        assert len(tbl.rows) == 2
        assert all(len(r.cells) == 3 for r in tbl.rows)

    def test_f05_cell_text_preserved(self, tmp_path: pathlib.Path) -> None:
        """f05_table_cell_text.hwp의 셀 텍스트가 라운드트립 후 보존."""
        doc_orig = parse_hwp(_fixture("f05_table_cell_text.hwp"))
        out = str(tmp_path / "f05_rt.hwp")
        generate_hwp(doc_orig, out)

        doc_rt = parse_hwp(out)
        tables = [b for b in doc_rt.blocks if isinstance(b, TableBlock)]
        assert len(tables) >= 1
        all_cell_texts: list[str] = []
        for row in tables[0].rows:
            for cell in row.cells:
                for blk in cell.content:
                    if isinstance(blk, ParagraphBlock):
                        t = "".join(i.text for i in blk.inlines if hasattr(i, "text"))
                        all_cell_texts.append(t)
        assert any("이름" in t for t in all_cell_texts)
        assert any("홍길동" in t for t in all_cell_texts)
