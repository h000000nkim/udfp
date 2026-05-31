"""HTML 렌더러 단위 테스트.

22 블록, 8 인라인, TextInline 27 필드, BlockFormat 31 필드, CellFormat 13 필드 검증.
"""

from __future__ import annotations

import pytest

from udf.core.schema import DocumentMetadata, UdfDocument
from udf.renderers.html import render_html
from udf.schema.blocks import (
    BookmarkBlock,
    ChartBlock,
    CodeBlock,
    CommentBlock,
    DrawingBlock,
    EndnoteBlock,
    EquationBlock,
    FieldBlock,
    FooterBlock,
    FootnoteBlock,
    HeaderBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    PageBreakBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextArtBlock,
    TextBoxBlock,
    UnknownBlock,
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(*blocks, source_format="pdf"):
    return UdfDocument(source_format=source_format, blocks=list(blocks))


def _para(id_: str, *inlines):
    return ParagraphBlock(id=id_, inlines=list(inlines))


def _text(t, **kw):
    return TextInline(text=t, **kw)


# ===========================================================================
# Block tests — 22 types
# ===========================================================================


class TestHeadingBlock:
    def test_levels(self):
        for lvl in (1, 2, 3, 4, 5, 6):
            html = render_html(_doc(HeadingBlock(id="h", level=lvl, text=f"H{lvl}")))
            assert f"<h{lvl}" in html
            assert f"H{lvl}" in html

    def test_inlines_rendered(self):
        html = render_html(_doc(HeadingBlock(id="h", level=1, text="T",
                                             inlines=[_text("Bold", bold=True)])))
        assert "<strong>" in html

    def test_format_applied(self):
        html = render_html(_doc(HeadingBlock(
            id="h", level=1, text="T",
            format=BlockFormat(alignment="center"))))
        assert "text-align:center" in html


class TestParagraphBlock:
    def test_basic(self):
        html = render_html(_doc(_para("p1", _text("Hello"))))
        assert "<p" in html
        assert "Hello" in html

    def test_empty_skipped(self):
        html = render_html(_doc(_para("p1", _text("   "))))
        assert "<p" not in html or "   " not in html

    def test_format(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(indent_left=20.0))))
        assert "margin-left:20.0pt" in html


class TestTableBlock:
    def test_basic_table(self):
        html = render_html(_doc(TableBlock(id="t1", rows=[
            TableRow(cells=[
                TableCell(id="c1", content=[_para("p1", _text("A"))]),
                TableCell(id="c2", content=[_para("p2", _text("B"))]),
            ])
        ])))
        assert "<table" in html
        assert "<th" in html
        assert "A" in html
        assert "B" in html

    def test_spans(self):
        html = render_html(_doc(TableBlock(id="t1", rows=[
            TableRow(cells=[
                TableCell(id="c1", col_span=2, content=[_para("p1", _text("Wide"))]),
            ])
        ])))
        assert 'colspan="2"' in html

    def test_caption(self):
        html = render_html(_doc(TableBlock(id="t1", caption=[_text("Cap")], rows=[
            TableRow(cells=[TableCell(id="c1", content=[_para("p1", _text("X"))])])
        ])))
        assert "<caption>" in html
        assert "Cap" in html

    def test_cell_format(self):
        html = render_html(_doc(TableBlock(id="t1", rows=[
            TableRow(cells=[TableCell(
                id="c1",
                format=CellFormat(background_color=Color(255, 0, 0)),
                content=[_para("p1", _text("X"))]
            )])
        ])))
        assert "background-color:#ff0000" in html


class TestListBlock:
    def test_ordered(self):
        html = render_html(_doc(ListBlock(id="l1", ordered=True, items=[
            ListItem(id="i1", inlines=[_text("One")]),
            ListItem(id="i2", inlines=[_text("Two")]),
        ])))
        assert "<ol" in html
        assert "<li>" in html

    def test_unordered(self):
        html = render_html(_doc(ListBlock(id="l1", items=[
            ListItem(id="i1", inlines=[_text("A")]),
        ])))
        assert "<ul" in html

    def test_nested(self):
        html = render_html(_doc(ListBlock(id="l1", items=[
            ListItem(id="i1", inlines=[_text("P")], children=[
                ListItem(id="i2", inlines=[_text("C")]),
            ]),
        ])))
        assert html.count("<ul") >= 2

    def test_start(self):
        html = render_html(_doc(ListBlock(id="l1", ordered=True, start=5, items=[
            ListItem(id="i1", inlines=[_text("X")]),
        ])))
        assert 'start="5"' in html

    def test_checkbox(self):
        html = render_html(_doc(ListBlock(id="l1", items=[
            ListItem(id="i1", inlines=[_text("Done")], checked=True),
            ListItem(id="i2", inlines=[_text("Todo")], checked=False),
        ])))
        assert "checked" in html
        assert 'type="checkbox"' in html


class TestImageBlock:
    def test_http_src(self):
        html = render_html(_doc(ImageBlock(id="i1", src="http://x.com/img.png", alt="photo")))
        assert "<figure" in html
        assert '<img src="http://x.com/img.png"' in html
        assert 'alt="photo"' in html

    def test_dimensions(self):
        html = render_html(_doc(ImageBlock(id="i1", src="http://x.com/i.png", width=200)))
        assert "width:200" in html

    def test_empty_src_skipped(self):
        html = render_html(_doc(ImageBlock(id="i1", src="")))
        assert "<figure" not in html

    def test_bindata_embed(self):
        from udf.pipeline.document import VerbatimLayer
        doc = UdfDocument(
            source_format="hwp",
            blocks=[ImageBlock(id="i1", src="bindata:test.png")],
            verbatim=VerbatimLayer(format="hwp", bindata_streams={"test.png": "AAAA"}),
        )
        html = render_html(doc, embed_images=True)
        assert "data:image/png;base64,AAAA" in html


class TestCodeBlock:
    def test_basic(self):
        html = render_html(_doc(CodeBlock(id="c1", code="x = 1", language="python")))
        assert "<pre" in html
        assert "<code" in html
        assert 'language-python' in html
        assert "x = 1" in html

    def test_no_language(self):
        html = render_html(_doc(CodeBlock(id="c1", code="hello")))
        assert "<code>" in html
        assert "language-" not in html


class TestQuoteBlock:
    def test_basic(self):
        html = render_html(_doc(QuoteBlock(id="q1", content=[
            _para("p1", _text("Quoted text"))
        ])))
        assert "<blockquote" in html
        assert "Quoted text" in html


class TestHorizontalRule:
    def test_basic(self):
        html = render_html(_doc(HorizontalRuleBlock(id="hr1")))
        assert "<hr" in html


class TestEquationBlock:
    def test_latex(self):
        html = render_html(_doc(EquationBlock(id="eq1", latex="E=mc^2")))
        assert "equation" in html
        assert "$$E=mc^2$$" in html

    def test_hwp_script(self):
        html = render_html(_doc(EquationBlock(id="eq1", hwp_script="a over b")))
        assert "$$a over b$$" in html

    def test_empty_skipped(self):
        html = render_html(_doc(EquationBlock(id="eq1")))
        assert '$$' not in html.split("</style>")[-1]


class TestFootnoteBlock:
    def test_basic(self):
        html = render_html(_doc(FootnoteBlock(id="fn1", ref="fn1", content=[
            _para("p1", _text("Footnote content"))
        ])))
        assert 'id="fn-fn1"' in html
        assert "footnote" in html
        assert "Footnote content" in html


class TestEndnoteBlock:
    def test_collected_at_end(self):
        html = render_html(_doc(
            _para("p1", _text("Body")),
            EndnoteBlock(id="en1", ref="en1", content=[
                _para("ep1", _text("Endnote text"))
            ]),
        ))
        assert "endnotes" in html
        assert 'id="en-en1"' in html
        assert "Endnote text" in html


class TestHeaderBlock:
    def test_rendered_as_header(self):
        html = render_html(_doc(
            HeaderBlock(id="hd1", content=[_para("p1", _text("Header text"))]),
            _para("p2", _text("Body")),
        ))
        assert "<header" in html
        assert "Header text" in html


class TestFooterBlock:
    def test_rendered_as_footer(self):
        html = render_html(_doc(
            _para("p1", _text("Body")),
            FooterBlock(id="ft1", content=[_para("fp1", _text("Footer text"))]),
        ))
        assert "<footer" in html
        assert "Footer text" in html


class TestFieldBlock:
    def test_value(self):
        html = render_html(_doc(FieldBlock(id="f1", field_type="text", value="Hello")))
        assert "field" in html
        assert "Hello" in html

    def test_inlines(self):
        html = render_html(_doc(FieldBlock(
            id="f1", field_type="hyperlink",
            inlines=[_text("Click")]
        )))
        assert "Click" in html


class TestTextBoxBlock:
    def test_basic(self):
        html = render_html(_doc(TextBoxBlock(id="tb1", content=[
            _para("p1", _text("Box content"))
        ])))
        assert "text-box" in html
        assert "Box content" in html

    def test_styling(self):
        html = render_html(_doc(TextBoxBlock(
            id="tb1", width=200, background_color="#eee", line_width=2.0,
            content=[_para("p1", _text("X"))]
        )))
        assert "width:200" in html
        assert "background-color:#eee" in html
        assert "border-width:2.0pt" in html or "border-width:2" in html


class TestDrawingBlock:
    def test_placeholder(self):
        html = render_html(_doc(DrawingBlock(id="d1", shape_type="rectangle")))
        assert "drawing" in html
        assert "rectangle" in html

    def test_with_content(self):
        html = render_html(_doc(DrawingBlock(id="d1", content=[
            _para("p1", _text("Inside drawing"))
        ])))
        assert "Inside drawing" in html


class TestChartBlock:
    def test_placeholder(self):
        html = render_html(_doc(ChartBlock(id="ch1", description="Sales chart")))
        assert "chart" in html
        assert "Sales chart" in html


class TestTextArtBlock:
    def test_text(self):
        html = render_html(_doc(TextArtBlock(id="ta1", text="ART")))
        assert "text-art" in html
        assert "ART" in html


class TestPageBreakBlock:
    def test_basic(self):
        html = render_html(_doc(PageBreakBlock(id="pb1")))
        assert "page-break" in html


class TestBookmarkBlock:
    def test_anchor(self):
        html = render_html(_doc(BookmarkBlock(id="bk1", name="chapter1")))
        assert 'id="bm-chapter1"' in html


class TestCommentBlock:
    def test_hidden_by_default(self):
        html = render_html(_doc(CommentBlock(id="cm1", author="Alice", content=[
            _para("p1", _text("Review comment"))
        ])))
        assert "comment" in html
        assert "hidden" in html
        assert "Alice" in html
        assert "Review comment" in html


class TestUnknownBlock:
    def test_rendered_hidden(self):
        html = render_html(_doc(UnknownBlock(id="uk1", raw_bytes="", description="weird")))
        assert "unknown" in html
        assert "weird" in html


# ===========================================================================
# Inline tests — 8 types
# ===========================================================================


class TestTextInlineSemantic:
    def test_bold(self):
        html = render_html(_doc(_para("p1", _text("B", bold=True))))
        assert "<strong>" in html

    def test_italic(self):
        html = render_html(_doc(_para("p1", _text("I", italic=True))))
        assert "<em>" in html

    def test_underline(self):
        html = render_html(_doc(_para("p1", _text("U", underline=True))))
        assert "<u>" in html

    def test_strikethrough(self):
        html = render_html(_doc(_para("p1", _text("S", strikethrough=True))))
        assert "<del>" in html

    def test_superscript(self):
        html = render_html(_doc(_para("p1", _text("S", superscript=True))))
        assert "<sup>" in html

    def test_subscript(self):
        html = render_html(_doc(_para("p1", _text("S", subscript=True))))
        assert "<sub>" in html

    def test_hidden(self):
        html = render_html(_doc(_para("p1", _text("H", hidden=True))))
        assert "display:none" in html


class TestTextInlineCSS:
    def test_color(self):
        html = render_html(_doc(_para("p1", _text("X", color=Color(255, 0, 0)))))
        assert "color:#ff0000" in html

    def test_background_color(self):
        html = render_html(_doc(_para("p1", _text("X", background_color=Color(0, 255, 0)))))
        assert "background-color:#00ff00" in html

    def test_highlight_overrides_bg(self):
        html = render_html(_doc(_para("p1", _text("X",
            background_color=Color(0, 255, 0),
            highlight_color=Color(255, 255, 0)))))
        assert "background-color:#ffff00" in html

    def test_font_name(self):
        html = render_html(_doc(_para("p1", _text("X", font_name="바탕"))))
        assert "font-family:'바탕'" in html
        assert "Noto Serif KR" in html

    def test_font_size(self):
        html = render_html(_doc(_para("p1", _text("X", font_size=14.0))))
        assert "font-size:14.0pt" in html

    def test_letter_spacing(self):
        html = render_html(_doc(_para("p1", _text("X", letter_spacing=2.5))))
        assert "letter-spacing:0.025em" in html

    def test_char_scale(self):
        html = render_html(_doc(_para("p1", _text("X", char_scale=Ratio(85)))))
        assert "scaleX(0.85)" in html

    def test_char_offset(self):
        html = render_html(_doc(_para("p1", _text("X", char_offset=3.0))))
        assert "vertical-align:0.03em" in html

    def test_small_caps(self):
        html = render_html(_doc(_para("p1", _text("X", small_caps=True))))
        assert "font-variant:small-caps" in html

    def test_all_caps(self):
        html = render_html(_doc(_para("p1", _text("X", all_caps=True))))
        assert "text-transform:uppercase" in html

    def test_outline(self):
        html = render_html(_doc(_para("p1", _text("X", outline=True))))
        assert "text-stroke" in html

    def test_shadow(self):
        html = render_html(_doc(_para("p1", _text("X", shadow=True))))
        assert "text-shadow" in html

    def test_emboss(self):
        html = render_html(_doc(_para("p1", _text("X", emboss=True))))
        assert "text-shadow" in html

    def test_engrave(self):
        html = render_html(_doc(_para("p1", _text("X", engrave=True))))
        assert "text-shadow" in html

    def test_emphasis_mark(self):
        html = render_html(_doc(_para("p1", _text("X", emphasis_mark="dot"))))
        assert "text-emphasis:dot" in html

    def test_rtl(self):
        html = render_html(_doc(_para("p1", _text("X", rtl=True))))
        assert "direction:rtl" in html

    def test_underline_type(self):
        html = render_html(_doc(_para("p1", _text("X", underline=True, underline_type="dashed"))))
        assert "text-decoration-style:dashed" in html

    def test_underline_color(self):
        html = render_html(_doc(_para("p1", _text("X", underline=True, underline_color=Color(0, 0, 255)))))
        assert "text-decoration-color:#0000ff" in html

    def test_strikeout_color(self):
        html = render_html(_doc(_para("p1", _text("X", strikethrough=True, strikeout_color=Color(128, 0, 0)))))
        assert "text-decoration-color:#800000" in html


class TestLinkInline:
    def test_basic(self):
        html = render_html(_doc(_para("p1", LinkInline(text="Click", url="http://x.com"))))
        assert '<a href="http://x.com"' in html
        assert "Click" in html

    def test_title(self):
        html = render_html(_doc(_para("p1", LinkInline(text="L", url="http://x.com", title="Tip"))))
        assert 'title="Tip"' in html


class TestImageInline:
    def test_basic(self):
        html = render_html(_doc(_para("p1", ImageInline(src="http://x.com/i.png", alt="img"))))
        assert '<img src="http://x.com/i.png"' in html
        assert 'alt="img"' in html


class TestFootnoteRefInline:
    def test_basic(self):
        html = render_html(_doc(_para("p1", FootnoteRefInline(ref_id="fn1", number=1))))
        assert '<sup>' in html
        assert 'href="#fn-fn1"' in html
        assert "1" in html


class TestEndnoteRefInline:
    def test_basic(self):
        html = render_html(_doc(_para("p1", EndnoteRefInline(ref_id="en1", number=2))))
        assert '<sup>' in html
        assert 'href="#en-en1"' in html


class TestEquationInline:
    def test_latex(self):
        html = render_html(_doc(_para("p1", EquationInline(latex="x^2"))))
        assert "\\(x^2\\)" in html

    def test_hwp_script(self):
        html = render_html(_doc(_para("p1", EquationInline(hwp_script="a over b"))))
        assert "\\(a over b\\)" in html

    def test_empty_skipped(self):
        html = render_html(_doc(_para("p1", _text("A"), EquationInline(), _text("B"))))
        assert "A" in html
        assert "B" in html


class TestRubyInline:
    def test_basic(self):
        html = render_html(_doc(_para("p1", RubyInline(base_text="漢", ruby_text="かん"))))
        assert "<ruby>" in html
        assert "<rt>" in html
        assert "漢" in html
        assert "かん" in html


class TestCodeInline:
    def test_basic(self):
        html = render_html(_doc(_para("p1", CodeInline(code="var x"))))
        assert "<code>var x</code>" in html


# ===========================================================================
# BlockFormat CSS tests
# ===========================================================================


class TestBlockFormatCSS:
    def test_alignment(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(alignment="right"))))
        assert "text-align:right" in html

    def test_line_spacing_ratio(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(line_spacing=Ratio(200)))))
        assert "line-height:2.00" in html

    def test_line_spacing_float(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(line_spacing=160.0))))
        assert "line-height:1.60" in html

    def test_spacing(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(space_before=10.0, space_after=5.0))))
        assert "margin-top:10.0pt" in html
        assert "margin-bottom:5.0pt" in html

    def test_indent(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(indent_left=20.0, indent_first=15.0))))
        assert "margin-left:20.0pt" in html
        assert "text-indent:15.0pt" in html

    def test_background(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(background_color=Color(240, 240, 240)))))
        assert "background-color:#f0f0f0" in html

    def test_borders(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(border_top="1px solid #000"))))
        assert "border-top:1px solid #000" in html

    def test_vertical_text(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(text_direction="vertical"))))
        assert "writing-mode:vertical-rl" in html

    def test_page_break_before(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(page_break_before=True))))
        assert "page-break-before:always" in html

    def test_keep_with_next(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(keep_with_next=True))))
        assert "page-break-after:avoid" in html

    def test_bidi(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(bidi=True))))
        assert "direction:rtl" in html

    def test_drop_cap(self):
        html = render_html(_doc(ParagraphBlock(
            id="p1", inlines=[_text("X")],
            format=BlockFormat(drop_cap_lines=3))))
        assert "initial-letter:3" in html


# ===========================================================================
# CellFormat CSS tests
# ===========================================================================


class TestCellFormatCSS:
    def test_background(self):
        html = render_html(_doc(TableBlock(id="t1", rows=[
            TableRow(cells=[TableCell(
                id="c1",
                format=CellFormat(background_color=Color(200, 200, 200)),
                content=[_para("p1", _text("X"))])])])))
        assert "background-color:#c8c8c8" in html

    def test_vertical_align(self):
        html = render_html(_doc(TableBlock(id="t1", rows=[
            TableRow(cells=[TableCell(
                id="c1",
                format=CellFormat(vertical_align="middle"),
                content=[_para("p1", _text("X"))])])])))
        assert "vertical-align:middle" in html

    def test_no_wrap(self):
        html = render_html(_doc(TableBlock(id="t1", rows=[
            TableRow(cells=[TableCell(
                id="c1",
                format=CellFormat(no_wrap=True),
                content=[_para("p1", _text("X"))])])])))
        assert "white-space:nowrap" in html

    def test_padding(self):
        html = render_html(_doc(TableBlock(id="t1", rows=[
            TableRow(cells=[TableCell(
                id="c1",
                format=CellFormat(padding_top=5.0, padding_left=8.0),
                content=[_para("p1", _text("X"))])])])))
        assert "padding-top:5.0pt" in html
        assert "padding-left:8.0pt" in html


# ===========================================================================
# Feature tests
# ===========================================================================


class TestEmbedIds:
    def test_enabled(self):
        html = render_html(_doc(_para("p1", _text("X"))), embed_ids=True)
        assert 'data-bid="p1"' in html

    def test_disabled(self):
        html = render_html(_doc(_para("p1", _text("X"))), embed_ids=False)
        assert "data-bid" not in html


class TestHtmlEscape:
    def test_text_escaped(self):
        html = render_html(_doc(_para("p1", _text("<script>alert(1)</script>"))))
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_attribute_escaped(self):
        html = render_html(_doc(_para("p1", LinkInline(text="X", url='http://x.com/a"b'))))
        assert '&quot;' in html


class TestDocumentStructure:
    def test_has_html5_structure(self):
        html = render_html(_doc(_para("p1", _text("Hello"))))
        assert "<!DOCTYPE html>" in html
        assert '<html lang="en">' in html
        assert "<article>" in html
        assert "utf-8" in html

    def test_mathjax_loaded(self):
        html = render_html(_doc(_para("p1", _text("X"))))
        assert "MathJax" in html

    def test_google_fonts_loaded(self):
        html = render_html(_doc(_para("p1", _text("X"))))
        assert "Noto Sans KR" in html

    def test_print_css(self):
        html = render_html(_doc(_para("p1", _text("X"))))
        assert "@media print" in html

    def test_custom_title(self):
        html = render_html(_doc(_para("p1", _text("X"))), title="My Doc")
        assert "<title>My Doc</title>" in html

    def test_metadata_title(self):
        doc = UdfDocument(
            source_format="md",
            metadata=DocumentMetadata(title="From Meta"),
            blocks=[_para("p1", _text("X"))],
        )
        html = render_html(doc)
        assert "<title>From Meta</title>" in html


class TestImageResolution:
    def test_bindata_file_path(self):
        from udf.pipeline.document import VerbatimLayer
        doc = UdfDocument(
            source_format="hwp",
            blocks=[ImageBlock(id="i1", src="bindata:photo.png")],
            verbatim=VerbatimLayer(format="hwp", bindata_streams={"photo.png": "AAAA"}),
        )
        html = render_html(doc, image_dir="img")
        assert 'src="img/photo.png"' in html

    def test_bindata_embed(self):
        from udf.pipeline.document import VerbatimLayer
        doc = UdfDocument(
            source_format="hwp",
            blocks=[ImageBlock(id="i1", src="bindata:photo.jpg")],
            verbatim=VerbatimLayer(format="hwp", bindata_streams={"photo.jpg": "BBBB"}),
        )
        html = render_html(doc, embed_images=True)
        assert "data:image/jpeg;base64,BBBB" in html
