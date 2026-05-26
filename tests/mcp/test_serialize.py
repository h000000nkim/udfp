"""Simplified JSON 직렬화기 테스트."""

from __future__ import annotations

import json
import pathlib

import pytest

from udf.schema.blocks import (
    BookmarkBlock,
    CodeBlock,
    EquationBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    QuoteBlock,
    FootnoteBlock,
    FieldBlock,
)
from udf.schema.formats import BlockFormat, CellFormat
from udf.schema.inlines import (
    CodeInline,
    EndnoteRefInline,
    EquationInline,
    FootnoteRefInline,
    ImageInline,
    LinkInline,
    RubyInline,
    TextInline,
)
from udf.schema.types import Color, Ratio
from udf.pipeline.document import UdfDocument

from udfp.serialize import (
    serialize_simplified,
    _compute_grid_coordinates,
    _serialize_inline_format,
)


FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


def _make_doc(*blocks, source_format: str = "udf") -> UdfDocument:
    return UdfDocument(source_format=source_format, blocks=list(blocks))


# ------------------------------------------------------------------
# Paragraph
# ------------------------------------------------------------------

class TestParagraph:
    def test_basic(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[TextInline(text="hello")],
        ))
        data = json.loads(serialize_simplified(doc))
        blk = data["blocks"][0]
        assert blk["id"] == "b_0001"
        assert blk["type"] == "paragraph"
        assert blk["inlines"][0]["idx"] == 0
        assert blk["inlines"][0]["text"] == "hello"

    def test_no_fmt_when_plain(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[TextInline(text="plain")],
        ))
        data = json.loads(serialize_simplified(doc))
        assert "fmt" not in data["blocks"][0]["inlines"][0]

    def test_formatted_inline(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[TextInline(text="bold", bold=True, font_size=12.0)],
        ))
        data = json.loads(serialize_simplified(doc))
        fmt = data["blocks"][0]["inlines"][0]["fmt"]
        assert fmt["bold"] is True
        assert fmt["size"] == 12.0

    def test_multiple_inlines_idx(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[
                TextInline(text="a"),
                TextInline(text="b"),
                TextInline(text="c"),
            ],
        ))
        data = json.loads(serialize_simplified(doc))
        idxs = [i["idx"] for i in data["blocks"][0]["inlines"]]
        assert idxs == [0, 1, 2]

    def test_block_format(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[TextInline(text="x")],
            format=BlockFormat(alignment="center"),
        ))
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["fmt"]["align"] == "center"

    def test_empty_block_format_omitted(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[TextInline(text="x")],
            format=BlockFormat(),
        ))
        data = json.loads(serialize_simplified(doc))
        assert "fmt" not in data["blocks"][0]


# ------------------------------------------------------------------
# Heading
# ------------------------------------------------------------------

class TestHeading:
    def test_heading(self):
        doc = _make_doc(HeadingBlock(
            id="b_0002", level=2, text="Chapter",
        ))
        data = json.loads(serialize_simplified(doc))
        blk = data["blocks"][0]
        assert blk["type"] == "heading"
        assert blk["level"] == 2
        assert blk["text"] == "Chapter"


# ------------------------------------------------------------------
# Table
# ------------------------------------------------------------------

class TestTable:
    def _make_table(self, rows_spec: list[list[tuple[int, int]]]) -> TableBlock:
        rows = []
        cell_id = 0
        for row_spec in rows_spec:
            cells = []
            for rs, cs in row_spec:
                cells.append(TableCell(
                    id=f"c_{cell_id:04d}",
                    row_span=rs,
                    col_span=cs,
                    content=[ParagraphBlock(
                        id=f"b_{cell_id:04d}",
                        inlines=[TextInline(text=f"cell{cell_id}")],
                    )],
                ))
                cell_id += 1
            rows.append(TableRow(cells=cells))
        return TableBlock(id="t_0001", rows=rows)

    def test_2x2_grid(self):
        tbl = self._make_table([[(1, 1), (1, 1)], [(1, 1), (1, 1)]])
        doc = _make_doc(tbl)
        data = json.loads(serialize_simplified(doc))
        rows = data["blocks"][0]["rows"]
        assert rows[0][0]["row"] == 0 and rows[0][0]["col"] == 0
        assert rows[0][1]["row"] == 0 and rows[0][1]["col"] == 1
        assert rows[1][0]["row"] == 1 and rows[1][0]["col"] == 0
        assert rows[1][1]["row"] == 1 and rows[1][1]["col"] == 1

    def test_colspan(self):
        tbl = self._make_table([[(1, 2)], [(1, 1), (1, 1)]])
        doc = _make_doc(tbl)
        data = json.loads(serialize_simplified(doc))
        rows = data["blocks"][0]["rows"]
        assert rows[0][0]["col_span"] == 2
        assert "row_span" not in rows[0][0]
        assert rows[1][0]["col"] == 0
        assert rows[1][1]["col"] == 1

    def test_rowspan(self):
        tbl = self._make_table([[(2, 1), (1, 1)], [(1, 1)]])
        doc = _make_doc(tbl)
        data = json.loads(serialize_simplified(doc))
        rows = data["blocks"][0]["rows"]
        assert rows[0][0]["row_span"] == 2
        assert rows[0][0]["col"] == 0
        assert rows[0][1]["col"] == 1
        assert rows[1][0]["col"] == 1

    def test_cell_content(self):
        tbl = self._make_table([[(1, 1)]])
        doc = _make_doc(tbl)
        data = json.loads(serialize_simplified(doc))
        cell = data["blocks"][0]["rows"][0][0]
        assert cell["content"][0]["type"] == "paragraph"

    def test_cell_format(self):
        tbl = TableBlock(id="t_0001", rows=[
            TableRow(cells=[
                TableCell(
                    id="c_0000",
                    content=[],
                    format=CellFormat(background_color=Color(255, 0, 0)),
                ),
            ])
        ])
        doc = _make_doc(tbl)
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["rows"][0][0]["fmt"]["bg"] == "#ff0000"


# ------------------------------------------------------------------
# Grid coordinates
# ------------------------------------------------------------------

class TestGridCoordinates:
    def test_empty(self):
        assert _compute_grid_coordinates([]) == []

    def test_complex_merge(self):
        rows = [
            TableRow(cells=[
                TableCell(id="c0", row_span=2, col_span=1, content=[]),
                TableCell(id="c1", row_span=1, col_span=2, content=[]),
            ]),
            TableRow(cells=[
                TableCell(id="c2", row_span=1, col_span=1, content=[]),
                TableCell(id="c3", row_span=1, col_span=1, content=[]),
            ]),
        ]
        coords = _compute_grid_coordinates(rows)
        assert coords[0] == [(0, 0), (0, 1)]
        assert coords[1] == [(1, 1), (1, 2)]


# ------------------------------------------------------------------
# List
# ------------------------------------------------------------------

class TestList:
    def test_ordered(self):
        doc = _make_doc(ListBlock(
            id="l_0001",
            ordered=True,
            items=[
                ListItem(id="li_0", inlines=[TextInline(text="one")]),
                ListItem(id="li_1", inlines=[TextInline(text="two")]),
            ],
        ))
        data = json.loads(serialize_simplified(doc))
        blk = data["blocks"][0]
        assert blk["ordered"] is True
        assert len(blk["items"]) == 2
        assert blk["items"][0]["inlines"][0]["text"] == "one"

    def test_nested(self):
        doc = _make_doc(ListBlock(
            id="l_0001",
            items=[
                ListItem(
                    id="li_0",
                    inlines=[TextInline(text="parent")],
                    children=[ListItem(id="li_0_0", inlines=[TextInline(text="child")])],
                ),
            ],
        ))
        data = json.loads(serialize_simplified(doc))
        child = data["blocks"][0]["items"][0]["children"][0]
        assert child["inlines"][0]["text"] == "child"


# ------------------------------------------------------------------
# Field
# ------------------------------------------------------------------

class TestField:
    def test_field(self):
        doc = _make_doc(FieldBlock(
            id="f_0001",
            field_type="text",
            value="hello",
            inlines=[TextInline(text="hello")],
        ))
        data = json.loads(serialize_simplified(doc))
        blk = data["blocks"][0]
        assert blk["field_type"] == "text"
        assert blk["value"] == "hello"


# ------------------------------------------------------------------
# Inline types
# ------------------------------------------------------------------

class TestInlineTypes:
    def test_link(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[LinkInline(text="click", url="https://example.com")],
        ))
        data = json.loads(serialize_simplified(doc))
        il = data["blocks"][0]["inlines"][0]
        assert il["type"] == "link"
        assert il["url"] == "https://example.com"

    def test_image_inline(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[ImageInline(src="img.png", alt="pic")],
        ))
        data = json.loads(serialize_simplified(doc))
        il = data["blocks"][0]["inlines"][0]
        assert il["type"] == "image_inline"
        assert il["alt"] == "pic"

    def test_footnote_ref(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[FootnoteRefInline(ref_id="fn_1", number=1)],
        ))
        data = json.loads(serialize_simplified(doc))
        il = data["blocks"][0]["inlines"][0]
        assert il["type"] == "footnote_ref"
        assert il["number"] == 1

    def test_endnote_ref(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[EndnoteRefInline(ref_id="en_1")],
        ))
        data = json.loads(serialize_simplified(doc))
        il = data["blocks"][0]["inlines"][0]
        assert il["type"] == "endnote_ref"

    def test_equation_inline(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[EquationInline(latex="E=mc^2")],
        ))
        data = json.loads(serialize_simplified(doc))
        il = data["blocks"][0]["inlines"][0]
        assert il["latex"] == "E=mc^2"

    def test_ruby(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[RubyInline(base_text="漢字", ruby_text="かんじ")],
        ))
        data = json.loads(serialize_simplified(doc))
        il = data["blocks"][0]["inlines"][0]
        assert il["type"] == "ruby"
        assert il["base_text"] == "漢字"

    def test_code_inline(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[CodeInline(code="x = 1", language="python")],
        ))
        data = json.loads(serialize_simplified(doc))
        il = data["blocks"][0]["inlines"][0]
        assert il["code"] == "x = 1"


# ------------------------------------------------------------------
# Color and Ratio
# ------------------------------------------------------------------

class TestFormatValues:
    def test_color_to_hex(self):
        inline = TextInline(text="r", color=Color(255, 0, 0))
        fmt = _serialize_inline_format(inline)
        assert fmt is not None
        assert fmt["color"] == "#ff0000"

    def test_color_with_alpha(self):
        inline = TextInline(text="r", color=Color(0, 0, 0, 0.5))
        fmt = _serialize_inline_format(inline)
        assert fmt is not None
        assert fmt["color"] == "#00000080"

    def test_ratio_line_spacing(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[TextInline(text="x")],
            format=BlockFormat(line_spacing=Ratio(160)),
        ))
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["fmt"]["line_h"] == 160.0


# ------------------------------------------------------------------
# Special block types
# ------------------------------------------------------------------

class TestSpecialBlocks:
    def test_image_block(self):
        doc = _make_doc(ImageBlock(id="i_0001", src="photo.png", alt="pic"))
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["src"] == "photo.png"

    def test_code_block(self):
        doc = _make_doc(CodeBlock(id="cd_0001", code="print(1)", language="python"))
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["language"] == "python"

    def test_equation_block(self):
        doc = _make_doc(EquationBlock(id="eq_0001", latex="a^2+b^2"))
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["latex"] == "a^2+b^2"

    def test_page_break(self):
        doc = _make_doc(PageBreakBlock(id="pb_0001"))
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["type"] == "page_break"

    def test_horizontal_rule(self):
        doc = _make_doc(HorizontalRuleBlock(id="hr_0001"))
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["type"] == "horizontal_rule"

    def test_bookmark(self):
        doc = _make_doc(BookmarkBlock(id="bk_0001", name="top"))
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["name"] == "top"


# ------------------------------------------------------------------
# Container blocks
# ------------------------------------------------------------------

class TestContainers:
    def test_textbox(self):
        doc = _make_doc(TextBoxBlock(
            id="tb_0001",
            content=[ParagraphBlock(id="b_0001", inlines=[TextInline(text="inside")])],
        ))
        data = json.loads(serialize_simplified(doc))
        blk = data["blocks"][0]
        assert blk["type"] == "text_box"
        assert blk["content"][0]["inlines"][0]["text"] == "inside"

    def test_quote(self):
        doc = _make_doc(QuoteBlock(
            id="q_0001",
            content=[ParagraphBlock(id="b_0001", inlines=[TextInline(text="cited")])],
        ))
        data = json.loads(serialize_simplified(doc))
        assert data["blocks"][0]["content"][0]["inlines"][0]["text"] == "cited"

    def test_footnote(self):
        doc = _make_doc(FootnoteBlock(
            id="fn_0001", ref="1",
            content=[ParagraphBlock(id="b_0001", inlines=[TextInline(text="note")])],
        ))
        data = json.loads(serialize_simplified(doc))
        blk = data["blocks"][0]
        assert blk["ref"] == "1"
        assert blk["content"][0]["inlines"][0]["text"] == "note"


# ------------------------------------------------------------------
# Pipeline field stripping
# ------------------------------------------------------------------

class TestPipelineStripping:
    def test_no_null_values(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[TextInline(text="hello")],
        ))
        raw = serialize_simplified(doc)
        assert "null" not in raw

    def test_no_verbatim_ref(self):
        doc = _make_doc(ParagraphBlock(
            id="b_0001",
            inlines=[TextInline(text="hello")],
            verbatim_ref="vref_123",
        ))
        raw = serialize_simplified(doc)
        assert "verbatim_ref" not in raw
        assert "vref_123" not in raw

    def test_no_unsupported(self):
        raw = serialize_simplified(_make_doc(ParagraphBlock(
            id="b_0001", inlines=[TextInline(text="x")],
        )))
        assert "unsupported" not in raw

    def test_source_format_preserved(self):
        doc = _make_doc(
            ParagraphBlock(id="b_0001", inlines=[TextInline(text="x")]),
            source_format="hwp",
        )
        data = json.loads(serialize_simplified(doc))
        assert data["source_format"] == "hwp"


# ------------------------------------------------------------------
# Fixture integration
# ------------------------------------------------------------------

HWP_FIXTURES = list((FIXTURES / "hwp").glob("*.hwp")) if (FIXTURES / "hwp").exists() else []


@pytest.mark.parametrize("fixture_path", HWP_FIXTURES[:5], ids=lambda p: p.name)
def test_hwp_fixture_serializable(fixture_path: pathlib.Path):
    import udf
    doc = udf.parse(str(fixture_path))
    raw = serialize_simplified(doc)
    data = json.loads(raw)
    assert "blocks" in data
    assert data["source_format"] == "hwp"
    assert "verbatim" not in raw
    assert "original_container" not in raw
    assert "conversion_trace" not in raw
    assert "loss_report" not in raw
