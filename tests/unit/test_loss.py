"""LossReport 헬퍼 단위 테스트."""

from __future__ import annotations

from udf.core.loss import (
    build_loss_report,
    diff_documents,
    format_limit_loss,
    unintended_loss,
    user_edited_loss,
)
from udf.core.schema import (
    HeadingBlock,
    LossCategory,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextInline,
    UdfDocument,
    VerbatimLayer,
)


def _doc(blocks: list) -> UdfDocument:
    return UdfDocument(
        source_format="hwp",
        blocks=blocks,
        verbatim=VerbatimLayer(format="hwp"),
    )


def _para(block_id: str, text: str) -> ParagraphBlock:
    return ParagraphBlock(
        type="paragraph",
        id=block_id,
        inlines=[TextInline(type="text", text=text)],
    )


class TestBuildLossReport:
    def test_no_loss(self) -> None:
        doc = _doc([_para("b_0", "hello")])
        report = build_loss_report(doc, [])
        assert report.total_blocks == 1
        assert report.lossless_blocks == 1
        assert report.lossy_blocks == []
        assert report.is_roundtrip_safe is True

    def test_format_limit_is_safe(self) -> None:
        doc = _doc([_para("b_0", "hello")])
        lossy = [format_limit_loss("b_0", "테두리 효과 미지원")]
        report = build_loss_report(doc, lossy)
        assert report.is_roundtrip_safe is True
        assert report.lossless_blocks == 0

    def test_unintended_is_not_safe(self) -> None:
        doc = _doc([_para("b_0", "hello")])
        lossy = [unintended_loss("b_0", "블록 소실")]
        report = build_loss_report(doc, lossy)
        assert report.is_roundtrip_safe is False

    def test_user_edited_is_safe(self) -> None:
        doc = _doc([_para("b_0", "new text")])
        lossy = [user_edited_loss("b_0", "텍스트 변경")]
        report = build_loss_report(doc, lossy)
        assert report.is_roundtrip_safe is True


class TestDiffDocuments:
    def test_identical_docs_no_loss(self) -> None:
        orig = _doc([_para("b_0", "hello"), _para("b_1", "world")])
        result = _doc([_para("b_0", "hello"), _para("b_1", "world")])
        report = diff_documents(orig, result)
        assert report.is_roundtrip_safe is True
        assert not any(
            b.loss_type == LossCategory.UNINTENDED for b in report.lossy_blocks
        )

    def test_missing_block_is_unintended(self) -> None:
        orig = _doc([_para("b_0", "hello"), _para("b_1", "world")])
        result = _doc([_para("b_0", "hello")])
        report = diff_documents(orig, result)
        assert not report.is_roundtrip_safe
        assert any(b.block_id == "b_1" for b in report.lossy_blocks)

    def test_text_change_is_user_edited(self) -> None:
        orig = _doc([_para("b_0", "original")])
        result = _doc([_para("b_0", "modified")])
        report = diff_documents(orig, result)
        assert report.is_roundtrip_safe is True
        assert report.lossy_blocks[0].loss_type == LossCategory.USER_EDITED

    def test_loss_category_helpers(self) -> None:
        fl = format_limit_loss("x", "desc")
        assert fl.loss_type == LossCategory.FORMAT_LIMIT
        ul = unintended_loss("x", "desc")
        assert ul.loss_type == LossCategory.UNINTENDED
        ue = user_edited_loss("x", "desc")
        assert ue.loss_type == LossCategory.USER_EDITED

    def test_block_type_mismatch_is_unintended(self) -> None:
        orig = _doc([_para("b_0", "hello")])
        result = _doc(
            [HeadingBlock(type="heading", id="b_0", level=1, text="hello")]
        )
        report = diff_documents(orig, result)
        assert not report.is_roundtrip_safe
        assert any(
            b.loss_type == LossCategory.UNINTENDED and "타입 변경" in b.description
            for b in report.lossy_blocks
        )


class TestDiffTable:
    def _table(self, block_id: str, cells: list[list[str]]) -> TableBlock:
        rows = []
        for ri, row_data in enumerate(cells):
            cs = []
            for ci, text in enumerate(row_data):
                cs.append(
                    TableCell(
                        id=f"{block_id}_r{ri}c{ci}",
                        content=[_para(f"{block_id}_r{ri}c{ci}_p", text)],
                    )
                )
            rows.append(TableRow(cells=cs))
        return TableBlock(type="table", id=block_id, rows=rows)

    def test_identical_table_no_loss(self) -> None:
        t1 = self._table("t_0", [["a", "b"], ["c", "d"]])
        t2 = self._table("t_0", [["a", "b"], ["c", "d"]])
        report = diff_documents(_doc([t1]), _doc([t2]))
        assert report.is_roundtrip_safe
        assert not report.lossy_blocks

    def test_cell_text_change_detected(self) -> None:
        t1 = self._table("t_0", [["a", "b"], ["c", "d"]])
        t2 = self._table("t_0", [["a", "B"], ["c", "d"]])
        report = diff_documents(_doc([t1]), _doc([t2]))
        assert report.is_roundtrip_safe
        assert len(report.lossy_blocks) == 1
        assert report.lossy_blocks[0].loss_type == LossCategory.USER_EDITED
        assert "셀[0,1]" in report.lossy_blocks[0].description

    def test_row_count_change_is_unintended(self) -> None:
        t1 = self._table("t_0", [["a", "b"], ["c", "d"]])
        t2 = self._table("t_0", [["a", "b"]])
        report = diff_documents(_doc([t1]), _doc([t2]))
        assert not report.is_roundtrip_safe

    def test_col_count_change_is_unintended(self) -> None:
        t1 = self._table("t_0", [["a", "b"], ["c", "d"]])
        t2 = self._table("t_0", [["a"], ["c"]])
        report = diff_documents(_doc([t1]), _doc([t2]))
        assert not report.is_roundtrip_safe


def _para_with_fmt(block_id: str, text: str, **fmt) -> ParagraphBlock:
    return ParagraphBlock(
        type="paragraph",
        id=block_id,
        inlines=[TextInline(type="text", text=text, **fmt)],
    )


class TestDiffFormatting:
    def test_color_change_detected(self) -> None:
        orig = _doc([_para_with_fmt("b_0", "hello", color="#000000")])
        result = _doc([_para_with_fmt("b_0", "hello", color="#ff0000")])
        report = diff_documents(orig, result)
        assert not report.is_roundtrip_safe
        assert any("color" in b.description for b in report.lossy_blocks)

    def test_bold_change_detected(self) -> None:
        orig = _doc([_para_with_fmt("b_0", "hello", bold=True)])
        result = _doc([_para_with_fmt("b_0", "hello", bold=None)])
        report = diff_documents(orig, result)
        assert not report.is_roundtrip_safe
        assert any("bold" in b.description for b in report.lossy_blocks)

    def test_identical_formatting_no_diff(self) -> None:
        a = _doc([_para_with_fmt("b_0", "hello", color="#ff0000", bold=True)])
        b = _doc([_para_with_fmt("b_0", "hello", color="#ff0000", bold=True)])
        report = diff_documents(a, b)
        assert report.is_roundtrip_safe
        assert not report.lossy_blocks

    def test_font_size_change_detected(self) -> None:
        orig = _doc([_para_with_fmt("b_0", "hello", font_size=10.0)])
        result = _doc([_para_with_fmt("b_0", "hello", font_size=12.0)])
        report = diff_documents(orig, result)
        assert not report.is_roundtrip_safe
        assert any("font_size" in b.description for b in report.lossy_blocks)
