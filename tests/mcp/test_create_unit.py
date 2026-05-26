"""create.py 유닛 테스트 — JSON→Block 변환 검증."""

from __future__ import annotations

import pytest

from udfp.create import (
    _build_block,
    _make_block_format,
    _make_cell_format,
    _make_inline,
    _make_inlines,
    _reset_counter,
    blocks_from_json,
    document_from_json,
)
from udf.schema.blocks import (
    CodeBlock,
    EquationBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ListBlock,
    PageBreakBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
)
from udf.schema.inlines import LinkInline, TextInline


@pytest.fixture(autouse=True)
def reset():
    _reset_counter()


class TestMakeInline:
    def test_plain_text(self):
        inline = _make_inline({"text": "hello"})
        assert isinstance(inline, TextInline)
        assert inline.text == "hello"

    def test_bold_italic(self):
        inline = _make_inline({"text": "x", "fmt": {"bold": True, "italic": True}})
        assert inline.bold is True
        assert inline.italic is True

    def test_font_size(self):
        inline = _make_inline({"text": "x", "fmt": {"size": 14.0}})
        assert inline.font_size == 14.0

    def test_font_name(self):
        inline = _make_inline({"text": "x", "fmt": {"font": "맑은 고딕"}})
        assert inline.font_name == "맑은 고딕"

    def test_color(self):
        inline = _make_inline({"text": "x", "fmt": {"color": "#FF0000"}})
        assert inline.color is not None

    def test_link_inline(self):
        inline = _make_inline({"text": "click", "url": "https://example.com"})
        assert isinstance(inline, LinkInline)
        assert inline.url == "https://example.com"

    def test_superscript(self):
        inline = _make_inline({"text": "2", "fmt": {"super": True}})
        assert inline.superscript is True

    def test_underline_strike(self):
        inline = _make_inline({"text": "x", "fmt": {"underline": True, "strike": True}})
        assert inline.underline is True
        assert inline.strikethrough is True


class TestMakeInlines:
    def test_from_text(self):
        inlines = _make_inlines({"text": "hello"})
        assert len(inlines) == 1
        assert inlines[0].text == "hello"

    def test_from_inlines_array(self):
        inlines = _make_inlines({"inlines": [
            {"text": "A", "fmt": {"bold": True}},
            {"text": "B"},
        ]})
        assert len(inlines) == 2
        assert inlines[0].bold is True
        assert inlines[1].text == "B"

    def test_empty_text(self):
        inlines = _make_inlines({"text": ""})
        assert inlines == []

    def test_no_text_no_inlines(self):
        inlines = _make_inlines({})
        assert inlines == []


class TestMakeBlockFormat:
    def test_alignment(self):
        fmt = _make_block_format({"align": "center"})
        assert fmt is not None
        assert fmt.alignment == "center"

    def test_spacing(self):
        fmt = _make_block_format({"space_before": 10.0, "space_after": 5.0})
        assert fmt.space_before == 10.0
        assert fmt.space_after == 5.0

    def test_empty(self):
        assert _make_block_format({}) is None

    def test_indent(self):
        fmt = _make_block_format({"indent_left": 20, "indent_1st": 10})
        assert fmt.indent_left == 20
        assert fmt.indent_first == 10


class TestMakeCellFormat:
    def test_bg_color(self):
        fmt = _make_cell_format({"bg": "#E0E0E0"})
        assert fmt is not None
        assert fmt.background_color is not None

    def test_valign(self):
        fmt = _make_cell_format({"valign": "middle"})
        assert fmt.vertical_align == "middle"

    def test_empty(self):
        assert _make_cell_format({}) is None


class TestBuildBlock:
    def test_heading(self):
        b = _build_block({"type": "heading", "level": 2, "text": "Title"})
        assert isinstance(b, HeadingBlock)
        assert b.level == 2
        assert b.text == "Title"

    def test_paragraph(self):
        b = _build_block({"type": "paragraph", "text": "Body"})
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 1

    def test_paragraph_with_inlines(self):
        b = _build_block({"type": "paragraph", "inlines": [
            {"text": "A", "fmt": {"bold": True}},
            {"text": "B"},
        ]})
        assert isinstance(b, ParagraphBlock)
        assert len(b.inlines) == 2
        assert b.inlines[0].bold is True

    def test_table_strings(self):
        b = _build_block({"type": "table", "rows": [["A", "B"], ["C", "D"]]})
        assert isinstance(b, TableBlock)
        assert len(b.rows) == 2
        assert len(b.rows[0].cells) == 2

    def test_table_dicts(self):
        b = _build_block({"type": "table", "rows": [
            [{"text": "Header", "fmt": {"bold": True}}, {"text": "Val"}],
        ]})
        assert isinstance(b, TableBlock)
        cell = b.rows[0].cells[0]
        assert cell.content[0].inlines[0].bold is True

    def test_table_col_widths(self):
        b = _build_block({"type": "table", "rows": [["A", "B"]], "col_widths": [100, 60]})
        assert len(b.col_widths) == 2
        assert b.col_widths[0].width == 100
        assert b.rows[0].cells[0].width == 100

    def test_table_header_rows(self):
        b = _build_block({"type": "table", "rows": [["H1"], ["D1"]], "header_rows": 1})
        assert b.rows[0].cells[0].is_header is True
        assert b.rows[1].cells[0].is_header is False

    def test_table_colspan(self):
        b = _build_block({"type": "table", "rows": [
            [{"text": "Merged", "colspan": 2}, {"text": "C"}],
        ]})
        assert b.rows[0].cells[0].col_span == 2

    def test_list_ordered(self):
        b = _build_block({"type": "list", "ordered": True, "items": ["A", "B"]})
        assert isinstance(b, ListBlock)
        assert b.ordered is True
        assert len(b.items) == 2

    def test_list_unordered(self):
        b = _build_block({"type": "list", "items": ["X", "Y"]})
        assert b.ordered is False

    def test_image(self):
        b = _build_block({"type": "image", "src": "/path/img.png", "width": 200})
        assert isinstance(b, ImageBlock)
        assert b.src == "/path/img.png"
        assert b.width == 200

    def test_code(self):
        b = _build_block({"type": "code", "code": "x = 1", "language": "python"})
        assert isinstance(b, CodeBlock)
        assert b.language == "python"

    def test_quote_text(self):
        b = _build_block({"type": "quote", "text": "Famous quote"})
        assert isinstance(b, QuoteBlock)
        assert len(b.content) == 1

    def test_quote_blocks(self):
        b = _build_block({"type": "quote", "blocks": [
            {"type": "paragraph", "text": "Line 1"},
            {"type": "paragraph", "text": "Line 2"},
        ]})
        assert len(b.content) == 2

    def test_equation(self):
        b = _build_block({"type": "equation", "latex": "E=mc^2"})
        assert isinstance(b, EquationBlock)
        assert b.latex == "E=mc^2"

    def test_page_break(self):
        b = _build_block({"type": "page_break"})
        assert isinstance(b, PageBreakBlock)

    def test_horizontal_rule(self):
        b = _build_block({"type": "horizontal_rule"})
        assert isinstance(b, HorizontalRuleBlock)

    def test_unknown_type_fallback(self):
        b = _build_block({"type": "nonexistent", "text": "fallback"})
        assert isinstance(b, ParagraphBlock)

    def test_heading_level_clamped(self):
        b = _build_block({"type": "heading", "level": 10, "text": "H10"})
        assert b.level == 6

    def test_heading_with_fmt(self):
        b = _build_block({"type": "heading", "level": 1, "text": "Big", "fmt": {"bold": True, "size": 24}})
        assert b.inlines[0].bold is True
        assert b.inlines[0].font_size == 24


class TestBlocksFromJson:
    def test_multiple_blocks(self):
        blocks = blocks_from_json([
            {"type": "heading", "level": 1, "text": "T"},
            {"type": "paragraph", "text": "P"},
        ])
        assert len(blocks) == 2
        assert blocks[0].id.startswith("b_")
        assert blocks[1].id.startswith("b_")
        assert blocks[0].id != blocks[1].id

    def test_counter_reset(self):
        blocks1 = blocks_from_json([{"type": "paragraph", "text": "A"}])
        blocks2 = blocks_from_json([{"type": "paragraph", "text": "B"}])
        assert blocks1[0].id == blocks2[0].id


class TestDocumentFromJson:
    def test_basic(self):
        doc = document_from_json(
            [{"type": "paragraph", "text": "hello"}],
            format="hwp",
        )
        assert doc.source_format == "hwp"
        assert len(doc.blocks) == 1

    def test_with_metadata(self):
        doc = document_from_json(
            [{"type": "paragraph", "text": "x"}],
            metadata={"title": "Test", "author": "Me"},
        )
        assert doc.metadata.title == "Test"
        assert doc.metadata.author == "Me"

    def test_with_page_a4(self):
        doc = document_from_json(
            [{"type": "paragraph", "text": "x"}],
            page={"paper": "A4"},
        )
        assert doc.metadata.page_width == pytest.approx(595.28, abs=1)
        assert doc.metadata.page_height == pytest.approx(841.89, abs=1)

    def test_with_page_landscape(self):
        doc = document_from_json(
            [{"type": "paragraph", "text": "x"}],
            page={"paper": "A4", "orientation": "landscape"},
        )
        assert doc.metadata.page_width > doc.metadata.page_height

    def test_with_page_margins(self):
        doc = document_from_json(
            [{"type": "paragraph", "text": "x"}],
            page={"paper": "A4", "margin_top": 10, "margin_left": 15},
        )
        assert doc.metadata.margins is not None
        assert doc.metadata.margins.top == pytest.approx(10 * 2.8346, abs=0.1)
        assert doc.metadata.margins.left == pytest.approx(15 * 2.8346, abs=0.1)

    def test_with_columns(self):
        doc = document_from_json(
            [{"type": "paragraph", "text": "x"}],
            page={"paper": "A4", "columns": 2, "column_gap": 12},
        )
        assert doc.metadata.columns is not None
        assert doc.metadata.columns.count == 2
