"""v1↔v2 마이그레이션 어댑터 테스트."""

from __future__ import annotations

import pytest

from udf.core import _schema_v1 as v1

from udf.migration import v1_to_v2, v2_to_v1
from udf.migration._blocks import ExtensionCollector, ExtensionLookup
from udf.migration._formats import (
    block_format_to_v1,
    block_format_to_v2,
    cell_format_to_v1,
    cell_format_to_v2,
    position_to_v1,
    position_to_v2,
)
from udf.migration._inlines import inline_to_v1, inline_to_v2
from udf.migration._metadata import metadata_to_v1, metadata_to_v2
from udf.migration._types import (
    color_to_str,
    format_mm,
    format_pct,
    format_pt,
    int_to_ratio,
    line_spacing_to_v1,
    line_spacing_to_v2,
    parse_dimension,
    parse_mm,
    parse_pct,
    parse_pt,
    ratio_to_int,
    str_to_color,
)
from udf.migration._verbatim import verbatim_to_v1, verbatim_to_v2
from udf.schema.types import Color, Ratio


# ===================================================================
# A. 타입 변환 단위 테스트
# ===================================================================


class TestParseFormat:
    def test_parse_pt(self):
        assert parse_pt("10.0pt") == 10.0
        assert parse_pt("0.5pt") == 0.5
        assert parse_pt(None) is None

    def test_parse_mm(self):
        v = parse_mm("25.4mm")
        assert v is not None
        assert abs(v - 72.0) < 0.1  # 25.4mm ≈ 72pt

    def test_parse_mm_none(self):
        assert parse_mm(None) is None

    def test_parse_pct(self):
        assert parse_pct("-5%") == -5.0
        assert parse_pct("100%") == 100.0
        assert parse_pct(None) is None

    def test_parse_dimension_pt(self):
        assert parse_dimension("10.0pt") == 10.0

    def test_parse_dimension_mm(self):
        v = parse_dimension("25.4mm")
        assert v is not None
        assert abs(v - 72.0) < 0.1

    def test_parse_dimension_cm(self):
        v = parse_dimension("2.54cm")
        assert v is not None
        assert abs(v - 72.0) < 0.1

    def test_parse_dimension_bare_number(self):
        assert parse_dimension("72.0") == 72.0

    def test_parse_dimension_none(self):
        assert parse_dimension(None) is None

    def test_parse_dimension_int_float_passthrough(self):
        assert parse_dimension(72) == 72.0
        assert parse_dimension(72.0) == 72.0

    def test_format_pt(self):
        assert format_pt(10.0) == "10.0pt"
        assert format_pt(None) is None

    def test_format_mm(self):
        s = format_mm(72.0)
        assert s is not None
        assert s.endswith("mm")
        val = float(s[:-2])
        assert abs(val - 25.4) < 0.1

    def test_format_pct(self):
        assert format_pct(-5.0) == "-5%"
        assert format_pct(100.0) == "100%"
        assert format_pct(None) is None

    def test_format_pct_decimal(self):
        assert format_pct(10.5) == "10.5%"


class TestColorConversion:
    def test_str_to_color(self):
        c = str_to_color("#ff0000")
        assert c is not None
        assert c.r == 255
        assert c.g == 0
        assert c.b == 0

    def test_color_to_str(self):
        c = Color(r=0, g=128, b=255)
        s = color_to_str(c)
        assert s is not None
        assert s.startswith("#")

    def test_color_roundtrip(self):
        original = "#aabbcc"
        c = str_to_color(original)
        result = color_to_str(c)
        assert result == original

    def test_none_passthrough(self):
        assert str_to_color(None) is None
        assert color_to_str(None) is None


class TestRatioConversion:
    def test_int_to_ratio(self):
        r = int_to_ratio(160)
        assert r is not None
        assert r.percent == 160.0

    def test_ratio_to_int(self):
        assert ratio_to_int(Ratio(160.0)) == 160

    def test_none_passthrough(self):
        assert int_to_ratio(None) is None
        assert ratio_to_int(None) is None


class TestLineSpacing:
    def test_ratio_to_v2(self):
        result = line_spacing_to_v2("160%", None)
        assert isinstance(result, Ratio)
        assert result.percent == 160.0

    def test_fixed_to_v2(self):
        result = line_spacing_to_v2("5.0mm", "fixed")
        assert isinstance(result, float)

    def test_ratio_to_v1(self):
        result = line_spacing_to_v1(Ratio(160.0), None)
        assert result == "160%"

    def test_fixed_to_v1(self):
        result = line_spacing_to_v1(72.0, "fixed")
        assert result is not None
        assert result.endswith("mm")

    def test_none_passthrough(self):
        assert line_spacing_to_v2(None, None) is None
        assert line_spacing_to_v1(None, None) is None


# ===================================================================
# B. 서식/인라인/메타데이터 변환 테스트
# ===================================================================


class TestBlockFormatConversion:
    def test_roundtrip(self):
        v1_bf = v1.BlockFormat(
            font_name="Arial",
            font_size="10.0pt",
            bold=True,
            alignment="center",
            line_spacing="160%",
            space_before="5.0mm",
            indent_left="10.0mm",
            background_color="#ff0000",
        )
        v2_bf = block_format_to_v2(v1_bf)
        assert v2_bf.font_size == 10.0
        assert v2_bf.bold is True
        assert isinstance(v2_bf.background_color, Color)

        v1_back = block_format_to_v1(v2_bf)
        assert v1_back.font_name == "Arial"
        assert v1_back.font_size == "10.0pt"
        assert v1_back.bold is True

    def test_none_passthrough(self):
        assert block_format_to_v2(None) is None
        assert block_format_to_v1(None) is None


class TestCellFormatConversion:
    def test_roundtrip(self):
        v1_cf = v1.CellFormat(
            background_color="#00ff00",
            padding="2.0mm",
            vertical_align="middle",
        )
        v2_cf = cell_format_to_v2(v1_cf)
        assert isinstance(v2_cf.background_color, Color)

        v1_back = cell_format_to_v1(v2_cf)
        assert v1_back.background_color == "#00ff00"

    def test_none_passthrough(self):
        assert cell_format_to_v2(None) is None
        assert cell_format_to_v1(None) is None


class TestPositionConversion:
    def test_v2_preserves_all_fields(self):
        v1_pos = v1.PositionInfo(
            x=100, y=200, width=300, height=400,
            z_order=1, flow="float",
            like_char=True,
            width_relto="page",
            height_relto="paper",
            restrict_in_page=True,
            rotation=45.0,
            opacity=0.8,
        )
        collector = ExtensionCollector("hwp")
        v2_pos = position_to_v2(v1_pos, collector, "b_0001")
        assert v2_pos.like_char is True
        assert v2_pos.x == 100
        assert v2_pos.width_relto == "page"
        assert v2_pos.height_relto == "paper"
        assert v2_pos.restrict_in_page is True
        assert v2_pos.rotation == 45.0
        assert v2_pos.opacity == 0.8

    def test_v1_restores_all_fields(self):
        from udf.schema import formats as v2f

        lookup = ExtensionLookup({})
        v2_pos = v2f.PositionInfo(
            x=100, y=200, width=300, height=400,
            z_order=1, flow="float", like_char=True,
            width_relto="page",
            height_relto="paper",
            restrict_in_page=True,
            rotation=45.0,
            opacity=0.8,
        )
        v1_pos = position_to_v1(v2_pos, lookup, "b_0001")
        assert v1_pos.width_relto == "page"
        assert v1_pos.height_relto == "paper"
        assert v1_pos.restrict_in_page is True
        assert v1_pos.rotation == 45.0
        assert v1_pos.opacity == 0.8

    def test_none_passthrough(self):
        collector = ExtensionCollector("hwp")
        lookup = ExtensionLookup({})
        assert position_to_v2(None, collector, "b") is None
        assert position_to_v1(None, lookup, "b") is None


class TestInlineConversion:
    def test_text_inline_roundtrip(self):
        v1_inl = v1.TextInline(
            text="hello",
            bold=True,
            color="#ff0000",
            font_size="10.0pt",
            letter_spacing="-5%",
            char_scale=160,
            emboss=True,
        )
        collector = ExtensionCollector("hwp")
        v2_inl = inline_to_v2(v1_inl, collector, "b_0001", 0)
        assert v2_inl.text == "hello"
        assert v2_inl.bold is True
        assert v2_inl.font_size == 10.0
        assert isinstance(v2_inl.color, Color)
        assert v2_inl.emboss is True

        lookup = ExtensionLookup(collector.to_extensions())
        v1_back = inline_to_v1(v2_inl, lookup, "b_0001", 0)
        assert v1_back.text == "hello"
        assert v1_back.font_size == "10.0pt"
        assert v1_back.char_scale == 160
        assert v1_back.emboss is True

    def test_link_inline(self):
        v1_inl = v1.LinkInline(text="link", url="https://example.com")
        collector = ExtensionCollector("hwp")
        v2_inl = inline_to_v2(v1_inl, collector, "b1", 0)
        assert v2_inl.text == "link"
        assert v2_inl.url == "https://example.com"

        lookup = ExtensionLookup({})
        v1_back = inline_to_v1(v2_inl, lookup, "b1", 0)
        assert v1_back.text == "link"
        assert v1_back.url == "https://example.com"

    def test_equation_inline_hwp_script(self):
        v1_inl = v1.EquationInline(latex="x^2", hwp_script="x^2", mathml="<math/>")
        collector = ExtensionCollector("hwp")
        v2_inl = inline_to_v2(v1_inl, collector, "b_0001", 0)
        assert v2_inl.latex == "x^2"
        assert v2_inl.hwp_script == "x^2"
        assert v2_inl.mathml == "<math/>"

        lookup = ExtensionLookup({})
        v1_back = inline_to_v1(v2_inl, lookup, "b_0001", 0)
        assert v1_back.hwp_script == "x^2"
        assert v1_back.mathml == "<math/>"

    def test_image_inline(self):
        v1_inl = v1.ImageInline(src="img.png", alt="test", width="100pt", height="50pt")
        collector = ExtensionCollector("hwp")
        v2_inl = inline_to_v2(v1_inl, collector, "b1", 0)
        assert v2_inl.width == 100.0
        assert v2_inl.height == 50.0

        lookup = ExtensionLookup({})
        v1_back = inline_to_v1(v2_inl, lookup, "b1", 0)
        assert v1_back.width == "100.0pt"
        assert v1_back.height == "50.0pt"

    def test_footnote_ref_inline(self):
        v1_inl = v1.FootnoteRefInline(ref_id="fn1", number=1)
        collector = ExtensionCollector("hwp")
        v2_inl = inline_to_v2(v1_inl, collector, "b1", 0)
        assert v2_inl.ref_id == "fn1"

        lookup = ExtensionLookup({})
        v1_back = inline_to_v1(v2_inl, lookup, "b1", 0)
        assert v1_back.ref_id == "fn1"


class TestMetadataConversion:
    def test_roundtrip(self):
        v1_meta = v1.DocumentMetadata(
            title="Test",
            author="Author",
            paper_width="595.3pt",
            paper_height="841.9pt",
            margins=v1.PageMargins(
                top="25.4mm", bottom="25.4mm",
                left="25.4mm", right="25.4mm",
            ),
            start_page_number=1,
            sections=[
                v1.SectionDef(
                    page_width="595.3pt",
                    page_height="841.9pt",
                ),
            ],
        )
        v2_meta = metadata_to_v2(v1_meta)
        assert v2_meta.title == "Test"
        assert v2_meta.page_width is not None
        assert v2_meta.start_page_number == 1

        v1_back = metadata_to_v1(v2_meta)
        assert v1_back.title == "Test"
        assert v1_back.paper_width is not None
        assert v1_back.start_page_number == 1


# ===================================================================
# C. 블록 단위 왕복 테스트
# ===================================================================


def _roundtrip_block(v1_block, source_format="hwp"):
    """v1 블록 → v2 → v1 왕복 후 원본과 비교."""
    from udf.migration._blocks import block_to_v1, block_to_v2

    collector = ExtensionCollector(source_format)
    v2_block = block_to_v2(v1_block, collector)
    lookup = ExtensionLookup(collector.to_extensions())
    v1_back = block_to_v1(v2_block, lookup)
    return v1_back


class TestBlockRoundtrip:
    def test_heading(self):
        blk = v1.HeadingBlock(
            type="heading", id="h1", level=1, text="Title",
            inlines=[v1.TextInline(text="Title")],
        )
        back = _roundtrip_block(blk)
        assert back.id == "h1"
        assert back.level == 1
        assert back.inlines[0].text == "Title"

    def test_paragraph(self):
        blk = v1.ParagraphBlock(
            type="paragraph", id="p1",
            inlines=[v1.TextInline(text="Hello", bold=True)],
            format=v1.BlockFormat(font_size="10.0pt"),
        )
        back = _roundtrip_block(blk)
        assert back.id == "p1"
        assert back.inlines[0].bold is True
        assert back.format.font_size == "10.0pt"

    def test_table_basic(self):
        blk = v1.TableBlock(
            type="table", id="t1",
            rows=[
                v1.TableRow(cells=[
                    v1.TableCell(
                        id="c1", row_span=1, col_span=1,
                        width=100.0, height=50.0,
                        content=[v1.ParagraphBlock(
                            type="paragraph", id="p_c1",
                            inlines=[v1.TextInline(text="cell")],
                        )],
                    ),
                ]),
            ],
        )
        back = _roundtrip_block(blk)
        assert back.id == "t1"
        assert len(back.rows) == 1
        assert back.rows[0].cells[0].content[0].inlines[0].text == "cell"

    def test_table_with_border_fill_id(self):
        blk = v1.TableBlock(
            type="table", id="t2",
            border_fill_id=5,
            border_top="1px solid black",
            rows=[v1.TableRow(cells=[
                v1.TableCell(id="c1", row_span=1, col_span=1, width=100.0, height=50.0, content=[], is_header=True),
            ], height="20.0pt")],
        )
        from udf.migration._blocks import block_to_v1, block_to_v2

        collector = ExtensionCollector("hwp")
        v2_blk = block_to_v2(blk, collector)
        assert v2_blk.border_fill_id == 5
        assert v2_blk.border_top == "1px solid black"
        assert v2_blk.rows[0].cells[0].is_header is True
        assert v2_blk.rows[0].height == 20.0

        lookup = ExtensionLookup({})
        back = block_to_v1(v2_blk, lookup)
        assert back.border_fill_id == 5
        assert back.border_top == "1px solid black"
        assert back.rows[0].cells[0].is_header is True
        assert back.rows[0].height == "20.0pt"

    def test_list_block(self):
        blk = v1.ListBlock(
            type="list", id="l1", ordered=True,
            items=[v1.ListItem(
                id="li1",
                inlines=[v1.TextInline(text="item 1")],
            )],
        )
        back = _roundtrip_block(blk)
        assert back.ordered is True
        assert back.items[0].inlines[0].text == "item 1"

    def test_image_block(self):
        blk = v1.ImageBlock(
            type="image", id="img1", src="image.png", alt="photo",
            width="100.0pt", height="200.0pt",
        )
        back = _roundtrip_block(blk)
        assert back.src == "image.png"
        assert back.width == "100.0pt"

    def test_code_block(self):
        blk = v1.CodeBlock(
            type="code", id="code1", language="python", code="print('hello')",
        )
        back = _roundtrip_block(blk)
        assert back.language == "python"
        assert back.code == "print('hello')"

    def test_quote_block(self):
        blk = v1.QuoteBlock(
            type="quote", id="q1",
            content=[v1.ParagraphBlock(
                type="paragraph", id="p_q1", inlines=[v1.TextInline(text="quoted")],
            )],
        )
        back = _roundtrip_block(blk)
        assert back.content[0].inlines[0].text == "quoted"

    def test_equation_block(self):
        blk = v1.EquationBlock(
            type="equation", id="eq1", latex="E=mc^2", hwp_script="E=mc^2", mathml="<math/>",
        )
        from udf.migration._blocks import block_to_v1, block_to_v2

        collector = ExtensionCollector("hwp")
        v2_blk = block_to_v2(blk, collector)
        assert v2_blk.hwp_script == "E=mc^2"
        assert v2_blk.mathml == "<math/>"

        lookup = ExtensionLookup({})
        back = block_to_v1(v2_blk, lookup)
        assert back.hwp_script == "E=mc^2"
        assert back.mathml == "<math/>"

    def test_footnote_block(self):
        blk = v1.FootnoteBlock(
            type="footnote", id="fn1", ref="fn_ref_1",
            content=[v1.ParagraphBlock(
                type="paragraph", id="p_fn1", inlines=[v1.TextInline(text="footnote text")],
            )],
        )
        back = _roundtrip_block(blk)
        assert back.ref == "fn_ref_1"
        assert back.content[0].inlines[0].text == "footnote text"

    def test_endnote_block(self):
        blk = v1.EndnoteBlock(
            type="endnote", id="en1", ref="en_ref_1",
            content=[v1.ParagraphBlock(
                type="paragraph", id="p_en1", inlines=[v1.TextInline(text="endnote")],
            )],
        )
        back = _roundtrip_block(blk)
        assert back.ref == "en_ref_1"

    def test_header_block(self):
        blk = v1.HeaderBlock(
            type="header", id="hdr1",
            content=[v1.ParagraphBlock(
                type="paragraph", id="p_hdr1", inlines=[v1.TextInline(text="header")],
            )],
        )
        back = _roundtrip_block(blk)
        assert back.content[0].inlines[0].text == "header"

    def test_footer_block(self):
        blk = v1.FooterBlock(
            type="footer", id="ftr1",
            content=[v1.ParagraphBlock(
                type="paragraph", id="p_ftr1", inlines=[v1.TextInline(text="footer")],
            )],
        )
        back = _roundtrip_block(blk)
        assert back.content[0].inlines[0].text == "footer"

    def test_field_block(self):
        blk = v1.FieldBlock(
            type="field", id="fld1", field_type="toc", value="TOC data",
        )
        back = _roundtrip_block(blk)
        assert back.field_type == "toc"
        assert back.value == "TOC data"

    def test_textbox_block(self):
        blk = v1.TextBoxBlock(
            type="text_box", id="tb1",
            width="200.0pt", height="100.0pt",
            content=[v1.ParagraphBlock(
                type="paragraph", id="p_tb1", inlines=[v1.TextInline(text="textbox")],
            )],
            position=v1.PositionInfo(
                x=0, y=0, width=200, height=100,
                like_char=True, width_relto="page",
            ),
        )
        from udf.migration._blocks import block_to_v1, block_to_v2

        collector = ExtensionCollector("hwp")
        v2_blk = block_to_v2(blk, collector)
        lookup = ExtensionLookup(collector.to_extensions())
        back = block_to_v1(v2_blk, lookup)
        assert back.content[0].inlines[0].text == "textbox"
        assert back.position.width_relto == "page"
        assert back.position.like_char is True

    def test_drawing_block(self):
        blk = v1.DrawingBlock(
            type="drawing", id="dr1",
            position=v1.PositionInfo(x=0, y=0, width=100, height=100),
        )
        back = _roundtrip_block(blk)
        assert back.id == "dr1"

    def test_page_break_block(self):
        blk = v1.PageBreakBlock(type="page_break", id="pb1")
        back = _roundtrip_block(blk)
        assert back.id == "pb1"


# ===================================================================
# D. Verbatim 레이어 테스트
# ===================================================================


class TestVerbatimConversion:
    def test_empty_verbatim(self):
        v1_vl = v1.VerbatimLayer(format="hwp")
        v2_vl = verbatim_to_v2(v1_vl)
        assert v2_vl.format == "hwp"
        assert v2_vl.block_mapping == {}

        v1_back = verbatim_to_v1(v2_vl)
        assert v1_back.format == "hwp"

    def test_with_styles(self):
        v1_vl = v1.VerbatimLayer(
            format="hwp",
            global_resources=v1.GlobalResources(
                styles={
                    "s1": v1.StyleDef(
                        id="s1", name="Normal",
                        style_type="paragraph",
                        format=v1.BlockFormat(font_size="10.0pt"),
                    ),
                },
            ),
        )
        v2_vl = verbatim_to_v2(v1_vl)
        s1 = v2_vl.global_resources.styles["s1"]
        assert s1.format is not None
        assert s1.format.font_size == 10.0

        v1_back = verbatim_to_v1(v2_vl)
        s1_back = v1_back.global_resources.styles["s1"]
        assert s1_back.format.font_size == "10.0pt"

    def test_with_blocks_and_resources(self):
        v1_vl = v1.VerbatimLayer(
            format="hwp",
            version="5.1",
            blocks={
                "b1": v1.VerbatimBlock(raw_tag_id=67, level=0, raw_bytes="AQID"),
            },
            global_resources=v1.GlobalResources(
                face_names={
                    "batang": v1.FontFallbacks(hangul="바탕", latin="Batang"),
                },
                numberings={
                    "n1": v1.NumberingDef(
                        id="n1",
                        levels=[v1.NumberingLevel(level=0, format="decimal", prefix="", suffix=".")],
                    ),
                },
                bullets={"b1": v1.BulletDef(id="b1", char="•")},
                tab_defs={"t1": v1.TabDef(id="t1", stops=[v1.TabStop(position="72pt", align="left")])},
                border_fills={
                    "bf1": v1.BorderFillDef(
                        id="bf1",
                        border_color="#000000",
                        border_left_width=1.0,
                    ),
                },
            ),
            section_streams={"section0": "base64data"},
            bindata_streams={"BIN0001.jpg": "imagedata"},
        )
        v2_vl = verbatim_to_v2(v1_vl)
        assert v2_vl.version == "5.1"
        assert v2_vl.blocks["b1"].raw_tag_id == 67
        assert v2_vl.global_resources.face_names["batang"].hangul == "바탕"
        assert v2_vl.section_streams["section0"] == "base64data"

        v1_back = verbatim_to_v1(v2_vl)
        assert v1_back.blocks["b1"].raw_bytes == "AQID"
        assert v1_back.global_resources.numberings["n1"].levels[0].format == "decimal"
        assert v1_back.global_resources.bullets["b1"].char == "•"
        assert v1_back.global_resources.tab_defs["t1"].stops[0].position == "72pt"
        assert v1_back.global_resources.border_fills["bf1"].border_left_width == 1.0
        assert v1_back.bindata_streams["BIN0001.jpg"] == "imagedata"


# ===================================================================
# E. 문서 전체 왕복 테스트
# ===================================================================


class TestDocumentRoundtrip:
    def test_empty_document(self):
        v1_doc = v1.UdfDocument(source_format="hwp")
        v2_doc = v1_to_v2(v1_doc)
        assert v2_doc.udf == "1.0"
        assert v2_doc.source_format == "hwp"
        assert v2_doc.document.blocks == []

        v1_back = v2_to_v1(v2_doc)
        assert v1_back.udf == "1.0"
        assert v1_back.source_format == "hwp"
        assert v1_back.blocks == []

    def test_document_with_blocks(self):
        v1_doc = v1.UdfDocument(
            source_format="hwp",
            metadata=v1.DocumentMetadata(
                title="Test Doc",
                paper_width="595.3pt",
                paper_height="841.9pt",
            ),
            blocks=[
                v1.HeadingBlock(type="heading", id="h1", level=1, text="Title",
                                inlines=[v1.TextInline(text="Title")]),
                v1.ParagraphBlock(type="paragraph", id="p1",
                                  inlines=[v1.TextInline(text="Body")]),
            ],
            page_boundaries=[
                v1.PageBoundary(page=1, start="h1"),
            ],
        )
        v2_doc = v1_to_v2(v1_doc)
        assert len(v2_doc.document.blocks) == 2
        assert v2_doc.document.metadata.title == "Test Doc"
        assert len(v2_doc.document.page_boundaries) == 1

        v1_back = v2_to_v1(v2_doc)
        assert v1_back.metadata.title == "Test Doc"
        assert len(v1_back.blocks) == 2
        assert v1_back.blocks[0].text == "Title"

    def test_document_with_direct_fields(self):
        v1_doc = v1.UdfDocument(
            source_format="hwp",
            blocks=[
                v1.EquationBlock(type="equation", id="eq1", latex="x^2", hwp_script="x SUPS 2"),
                v1.TableBlock(
                    type="table", id="t1", border_fill_id=3,
                    rows=[v1.TableRow(cells=[
                        v1.TableCell(id="c1", row_span=1, col_span=1,
                                     width=100.0, height=50.0, content=[]),
                    ])],
                ),
            ],
        )
        v2_doc = v1_to_v2(v1_doc)
        assert v2_doc.document.blocks[0].hwp_script == "x SUPS 2"
        assert v2_doc.document.blocks[1].border_fill_id == 3

        v1_back = v2_to_v1(v2_doc)
        assert v1_back.blocks[0].hwp_script == "x SUPS 2"
        assert v1_back.blocks[1].border_fill_id == 3

    def test_document_with_verbatim(self):
        v1_doc = v1.UdfDocument(
            source_format="hwp",
            blocks=[v1.ParagraphBlock(type="paragraph", id="p1", inlines=[v1.TextInline(text="hi")])],
            verbatim=v1.VerbatimLayer(
                format="hwp", version="5.1",
                blocks={"p1": v1.VerbatimBlock(raw_tag_id=67, level=0)},
                global_resources=v1.GlobalResources(
                    styles={"s1": v1.StyleDef(id="s1", name="Normal")},
                ),
            ),
        )
        v2_doc = v1_to_v2(v1_doc)
        assert v2_doc.verbatim is not None
        assert v2_doc.verbatim.format == "hwp"

        v1_back = v2_to_v1(v2_doc)
        assert v1_back.verbatim is not None
        assert v1_back.verbatim.blocks["p1"].raw_tag_id == 67

    def test_document_with_container_and_trace(self):
        v1_doc = v1.UdfDocument(
            source_format="hwp",
            original_container=v1.OriginalContainer(
                format="ole2", path="/tmp/test.hwp", checksum="abc123",
            ),
            conversion_trace=v1.ConversionTrace(
                parsed_at="2025-01-01T00:00:00",
                parser_version="1.0.0",
                checksum="def456",
            ),
        )
        v2_doc = v1_to_v2(v1_doc)
        assert v2_doc.original_container is not None
        assert v2_doc.original_container.format == "ole2"
        assert v2_doc.conversion_trace is not None
        assert v2_doc.conversion_trace.parser_version == "1.0.0"

        v1_back = v2_to_v1(v2_doc)
        assert v1_back.original_container.path == "/tmp/test.hwp"
        assert v1_back.conversion_trace.checksum == "def456"

    def test_nested_blocks(self):
        v1_doc = v1.UdfDocument(
            source_format="hwp",
            blocks=[
                v1.TableBlock(
                    type="table", id="t1",
                    rows=[v1.TableRow(cells=[
                        v1.TableCell(
                            id="c1", row_span=1, col_span=1,
                            width=200.0, height=100.0,
                            content=[
                                v1.ListBlock(
                                    type="list", id="l1", ordered=True,
                                    items=[v1.ListItem(
                                        id="li1",
                                        inlines=[
                                            v1.TextInline(text="nested"),
                                            v1.FootnoteRefInline(ref_id="fn1", number=1),
                                        ],
                                    )],
                                ),
                            ],
                        ),
                    ])],
                ),
                v1.FootnoteBlock(
                    type="footnote", id="fn1", ref="fn_ref_1",
                    content=[v1.ParagraphBlock(
                        type="paragraph", id="p_fn1",
                        inlines=[v1.TextInline(text="footnote content")],
                    )],
                ),
            ],
        )
        v2_doc = v1_to_v2(v1_doc)
        v1_back = v2_to_v1(v2_doc)

        table = v1_back.blocks[0]
        assert isinstance(table, v1.TableBlock)
        cell = table.rows[0].cells[0]
        list_blk = cell.content[0]
        assert isinstance(list_blk, v1.ListBlock)
        assert list_blk.items[0].inlines[0].text == "nested"

        fn = v1_back.blocks[1]
        assert isinstance(fn, v1.FootnoteBlock)
        assert fn.content[0].inlines[0].text == "footnote content"


# ===================================================================
# F. ExtensionCollector/Lookup 단위 테스트
# ===================================================================


class TestExtensionCollectorLookup:
    def test_empty_collector_returns_no_extensions(self):
        c = ExtensionCollector("hwp")
        assert c.to_extensions() == {}

    def test_collector_hwpx(self):
        c = ExtensionCollector("hwpx")
        c.add_inline_equation("b1:0", hwp_script="x^2")
        exts = c.to_extensions()
        assert "hwpx" in exts
        from udf.schema.extensions import HwpxExtension
        assert isinstance(exts["hwpx"], HwpxExtension)

    def test_unsupported_format_returns_empty(self):
        c = ExtensionCollector("docx")
        c.add_inline_text("b1:0", emboss=True)
        assert c.to_extensions() == {}

    def test_lookup_missing_key_returns_empty_dict(self):
        lookup = ExtensionLookup({})
        assert lookup.get_position("missing") == {}
        assert lookup.get_equation("missing") == {}
        assert lookup.get_block("missing") == {}
        assert lookup.get_inline_text("missing") == {}
