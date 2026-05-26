"""Empty block fill + HWP render roundtrip tests.

Verifies that text added to empty paragraphs (via add_inline) survives
HWP Seed Patch rendering and re-parsing. This is the primary integration
test for the template-filling workflow.

빈 블록 채우기 → HWP 렌더 라운드트립 검증.
add_inline으로 채운 텍스트가 HWP Seed Patch 렌더 후 재파싱에서 생존하는지 확인.
양식 채우기 워크플로우의 핵심 통합 테스트.
"""

from __future__ import annotations

import pathlib

import pytest

from udf.parsers.hwp.parse import parse_hwp
from udf.renderers.hwp import generate_hwp
from udf.schema.blocks import ParagraphBlock, TableBlock
from udf.schema.inlines import TextInline


FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


def _find_empty_para_ids(doc, *, include_table_cells: bool = False) -> list[str]:
    """Collect IDs of empty ParagraphBlocks (inlines == []).

    Parameters
    ----------
    doc : UdfDocument
        Parsed document to search.
    include_table_cells : bool
        If True, also search inside table cell content.

    Returns
    -------
    list[str]
        Block IDs of empty paragraphs.
    """
    ids = []
    for b in doc.blocks:
        if isinstance(b, ParagraphBlock) and len(b.inlines) == 0:
            ids.append(b.id)
        if include_table_cells and isinstance(b, TableBlock):
            for row in b.rows:
                for cell in row.cells:
                    for cb in cell.content:
                        if isinstance(cb, ParagraphBlock) and len(cb.inlines) == 0:
                            ids.append(cb.id)
    return ids


class TestEmptyBlockFillRoundtrip:
    """Verify add_inline on empty paragraphs survives HWP render + re-parse.

    빈 단락에 add_inline 후 HWP 렌더 → 재파싱에서 텍스트 생존 확인.
    """

    def test_single_empty_para_fill(self, tmp_path: pathlib.Path) -> None:
        """Fill one empty paragraph, render HWP, re-parse, verify text present.

        단일 빈 단락 채우기 → 라운드트립 후 텍스트 생존 확인.

        Asserts
        -------
        - Target block has exactly 1 inline after re-parse.
        - Inline text matches what was inserted.
        """
        doc = parse_hwp(_fixture("f08_empty_paras.hwp"))
        empty = _find_empty_para_ids(doc)
        assert len(empty) > 0, "f08에 빈 단락이 없음"

        target = empty[0]
        doc.add_inline(target, TextInline(text="채움 테스트"))

        out = str(tmp_path / "filled.hwp")
        generate_hwp(doc, out)

        doc_rt = parse_hwp(out)
        block = doc_rt.get_block(target)
        assert block is not None
        assert len(block.inlines) > 0, f"{target} 인라인이 비어있음"
        assert block.inlines[0].text == "채움 테스트"

    def test_multiple_empty_paras_fill(self, tmp_path: pathlib.Path) -> None:
        """Fill ALL empty paragraphs with unique text, verify each survives.

        모든 빈 단락에 고유 텍스트를 채운 뒤 전부 라운드트립 생존 확인.

        Asserts
        -------
        - Every filled block retains its exact text after render + re-parse.
        """
        doc = parse_hwp(_fixture("f08_empty_paras.hwp"))
        empty = _find_empty_para_ids(doc)

        for i, bid in enumerate(empty):
            doc.add_inline(bid, TextInline(text=f"para_{i}"))

        out = str(tmp_path / "multi_filled.hwp")
        generate_hwp(doc, out)

        doc_rt = parse_hwp(out)
        for i, bid in enumerate(empty):
            block = doc_rt.get_block(bid)
            assert block is not None
            assert len(block.inlines) > 0, f"{bid} 인라인 소실"
            assert block.inlines[0].text == f"para_{i}", (
                f"{bid}: expected 'para_{i}', got '{block.inlines[0].text}'"
            )

    def test_non_empty_paras_unchanged(self, tmp_path: pathlib.Path) -> None:
        """Filling empty blocks must not alter pre-existing text in other blocks.

        빈 블록을 채울 때 기존 텍스트가 변하지 않는지 확인 (side-effect 검증).

        Asserts
        -------
        - All originally non-empty paragraphs retain their exact text.
        """
        doc = parse_hwp(_fixture("f08_empty_paras.hwp"))

        orig_texts = {}
        for b in doc.blocks:
            if isinstance(b, ParagraphBlock) and len(b.inlines) > 0:
                orig_texts[b.id] = "".join(
                    i.text for i in b.inlines if hasattr(i, "text")
                )

        empty = _find_empty_para_ids(doc)
        for bid in empty:
            doc.add_inline(bid, TextInline(text="new"))

        out = str(tmp_path / "preserve.hwp")
        generate_hwp(doc, out)

        doc_rt = parse_hwp(out)
        for bid, orig in orig_texts.items():
            block = doc_rt.get_block(bid)
            assert block is not None
            rt_text = "".join(
                i.text for i in block.inlines if hasattr(i, "text")
            )
            assert rt_text == orig, f"{bid}: '{orig}' → '{rt_text}'"


class TestTableCellFillRoundtrip:
    """Verify add_inline on empty table cells survives HWP render + re-parse.

    빈 테이블 셀에 add_inline 후 HWP 렌더 → 재파싱에서 텍스트 생존 확인.
    """

    def test_empty_table_cell_fill(self, tmp_path: pathlib.Path) -> None:
        """Fill an empty table cell paragraph, verify text after roundtrip.

        빈 테이블 셀의 단락에 텍스트를 채우고 라운드트립 후 생존 확인.

        Asserts
        -------
        - Cell paragraph has non-empty inlines after re-parse.
        - Inline text matches inserted value.
        """
        doc = parse_hwp(_fixture("f05_table_cell_text.hwp"))
        empty = _find_empty_para_ids(doc, include_table_cells=True)
        if not empty:
            pytest.skip("f05에 빈 테이블 셀 없음")

        target = empty[0]
        doc.add_inline(target, TextInline(text="셀 채움"))

        out = str(tmp_path / "cell_filled.hwp")
        generate_hwp(doc, out)

        doc_rt = parse_hwp(out)
        block = doc_rt.get_block(target)
        assert block is not None
        assert len(block.inlines) > 0
        assert block.inlines[0].text == "셀 채움"
