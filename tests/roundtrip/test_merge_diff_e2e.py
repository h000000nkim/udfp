"""Phase 13e: merge_diff E2E 통합 테스트.

HWP fixture → parse → render MD (embed_ids) → 편집 → parse MD (start_id) →
merge_diff → 검증.

시나리오:
  1. 테이블 셀 텍스트 수정 → 수정 반영 + 서식 유지
  2. 단락 텍스트 수정 → 수정 반영 + 미수정 보존
  3. 무변경 → 원본과 동일 (changes == 0)
  4. 역검증: merge_diff가 실제 변경을 감지하는지 확인
"""

from __future__ import annotations

import pathlib

import pytest

from udf.core.ids import max_block_index
from udf.core.loss import diff_documents
from udf.merge_diff import merge_diff
from udf.parsers.hwp.parse import parse_hwp
from udf.parsers.md.parse import parse_md
from udf.renderers.md import render_md, _escape_md
from udf.schema.blocks import HeadingBlock, ParagraphBlock, TableBlock
from udf.schema.inlines import TextInline

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures" / "hwp"


def _fixture(name: str) -> str:
    p = FIXTURES / name
    assert p.exists(), f"fixture 없음: {p}"
    return str(p)


def _all_texts(doc) -> list[str]:
    texts = []
    for block in doc.blocks:
        if isinstance(block, ParagraphBlock):
            t = "".join(i.text for i in block.inlines if isinstance(i, TextInline))
            if t.strip():
                texts.append(t)
        elif isinstance(block, HeadingBlock):
            if block.text.strip():
                texts.append(block.text)
    return texts


class TestMergeDiffNoChangeE2E:
    """무변경 라운드트립 → merge_diff changes == 0."""

    @pytest.mark.parametrize(
        "filename",
        ["f01_plain_text.hwp", "f06_multiline.hwp", "f09_heading_h1h2.hwp"],
    )
    def test_no_edit_no_changes(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        md = render_md(doc, embed_ids=True)
        start = max_block_index(doc.blocks) + 1
        edited_doc = parse_md(md, start_id=start)
        result = merge_diff(doc, edited_doc)
        assert len(result.changes) == 0, (
            f"무변경인데 changes 발생: {[c.description for c in result.changes]}"
        )


class TestMergeDiffTextEditE2E:
    """단락 텍스트 수정 → merge_diff 반영."""

    @pytest.mark.parametrize(
        "filename",
        ["f01_plain_text.hwp", "f06_multiline.hwp", "f07_hangul_latin.hwp"],
    )
    def test_paragraph_edit_reflected(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        md = render_md(doc, embed_ids=True)

        orig_texts = _all_texts(doc)
        assert orig_texts, f"{filename}: 비어있는 fixture"

        first_text = orig_texts[0]
        new_text = "머지디프 편집 텍스트"
        edited_md = md.replace(_escape_md(first_text), new_text)

        start = max_block_index(doc.blocks) + 1
        edited_doc = parse_md(edited_md, start_id=start)
        result = merge_diff(doc, edited_doc)

        text_edits = [c for c in result.changes if c.change_type == "text_edit"]
        assert len(text_edits) >= 1, "텍스트 변경이 감지되지 않음"

        result_texts = _all_texts(result.document)
        assert new_text in result_texts, f"편집 텍스트 미반영: {result_texts!r}"

    @pytest.mark.parametrize(
        "filename",
        ["f06_multiline.hwp", "f07_hangul_latin.hwp"],
    )
    def test_unedited_paras_preserved(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        md = render_md(doc, embed_ids=True)

        orig_texts = _all_texts(doc)
        if len(orig_texts) < 2:
            pytest.skip("단락이 2개 미만")

        first_text = orig_texts[0]
        edited_md = md.replace(_escape_md(first_text), "수정된 단락")

        start = max_block_index(doc.blocks) + 1
        edited_doc = parse_md(edited_md, start_id=start)
        result = merge_diff(doc, edited_doc)

        result_texts = [t.strip() for t in _all_texts(result.document)]
        for t in orig_texts[1:]:
            assert t.strip() in result_texts, f"미편집 단락 손실: {t!r}"


class TestMergeDiffTableE2E:
    """테이블 셀 수정 → merge_diff 반영."""

    @pytest.mark.parametrize(
        "filename",
        ["f04_simple_table.hwp", "f05_table_cell_text.hwp"],
    )
    def test_table_cell_edit(self, filename: str) -> None:
        doc = parse_hwp(_fixture(filename))
        md = render_md(doc, embed_ids=True)

        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        if not tables:
            pytest.skip("테이블 없음")

        first_cell = tables[0].rows[0].cells[0]
        cell_text = "".join(p.text_content() for p in first_cell.content)
        if not cell_text.strip():
            pytest.skip("첫 셀이 비어있음")

        new_text = "셀수정완료"
        edited_md = md.replace(_escape_md(cell_text), new_text)

        start = max_block_index(doc.blocks) + 1
        edited_doc = parse_md(edited_md, start_id=start)
        result = merge_diff(doc, edited_doc)

        patched_tables = [b for b in result.document.blocks if isinstance(b, TableBlock)]
        assert patched_tables, "테이블이 사라짐"
        patched_cell = patched_tables[0].rows[0].cells[0]
        patched_text = "".join(p.text_content() for p in patched_cell.content)
        assert new_text in patched_text, (
            f"셀 텍스트 미반영: {patched_text!r}"
        )


class TestMergeDiffVerbatimPreserved:
    """merge_diff 후 verbatim 레이어가 보존되는지 확인."""

    def test_verbatim_layer_preserved(self) -> None:
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        md = render_md(doc, embed_ids=True)

        start = max_block_index(doc.blocks) + 1
        edited_doc = parse_md(md, start_id=start)
        result = merge_diff(doc, edited_doc)

        assert result.document.verbatim is not None, "verbatim 레이어 소실"
        assert result.document.verbatim.format == "hwp"
        assert result.document.verbatim.section_streams, "section_streams 소실"


class TestMergeDiffSemanticDiff:
    """merge_diff 결과의 시맨틱 diff 검증."""

    def test_no_edit_semantic_diff_zero(self) -> None:
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        md = render_md(doc, embed_ids=True)

        start = max_block_index(doc.blocks) + 1
        edited_doc = parse_md(md, start_id=start)
        result = merge_diff(doc, edited_doc)

        report = diff_documents(doc, result.document)
        assert len(report.lossy_blocks) == 0, (
            f"무변경인데 시맨틱 diff 발생: {[b.description for b in report.lossy_blocks]}"
        )


class TestMergeDiffFalsifiability:
    """역검증: merge_diff가 실제 변경을 감지하는지."""

    def test_detects_text_change(self) -> None:
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        md = render_md(doc, embed_ids=True)

        orig_texts = _all_texts(doc)
        assert orig_texts
        edited_md = md.replace(_escape_md(orig_texts[0]), "역검증용 텍스트")

        start = max_block_index(doc.blocks) + 1
        edited_doc = parse_md(edited_md, start_id=start)
        result = merge_diff(doc, edited_doc)

        assert len(result.changes) > 0, "텍스트 변경을 감지하지 못함"
        assert any(c.change_type == "text_edit" for c in result.changes)

    def test_identical_yields_no_changes(self) -> None:
        doc = parse_hwp(_fixture("f01_plain_text.hwp"))
        md = render_md(doc, embed_ids=True)

        start = max_block_index(doc.blocks) + 1
        edited_doc = parse_md(md, start_id=start)
        result = merge_diff(doc, edited_doc)

        assert len(result.changes) == 0, (
            f"동일 문서인데 변경 감지: {result.changes}"
        )
