"""HTML 렌더러 단위 테스트.

UdfDocument를 직접 인메모리로 구성하여 render_html() 출력을 검증.
PDF 파서를 통하지 않으므로 렌더러 로직만 독립적으로 테스트한다.
"""

from __future__ import annotations


from udf.renderers.html import render_html
from udf.core.schema import (
    ConversionTrace,
    DocumentMetadata,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextInline,
    UdfDocument,
)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _make_doc(*blocks, source_format: str = "pdf", title: str | None = None,
              parser_version: str = "0.2.0") -> UdfDocument:
    """최소 UdfDocument 팩토리."""
    return UdfDocument(
        source_format=source_format,
        metadata=DocumentMetadata(title=title),
        blocks=list(blocks),
        conversion_trace=ConversionTrace(
            parsed_at="2026-05-11T00:00:00Z",
            parser_version=parser_version,
        ),
    )


def _text(text: str, *, bold: bool | None = None, italic: bool | None = None,
          underline: bool | None = None, strikethrough: bool | None = None) -> TextInline:
    return TextInline(text=text, bold=bold, italic=italic,
                      underline=underline, strikethrough=strikethrough)


def _para(id: str, *inlines: TextInline) -> ParagraphBlock:
    return ParagraphBlock(type="paragraph", id=id, inlines=list(inlines))


def _heading(id: str, level: int, text: str) -> HeadingBlock:
    return HeadingBlock(type="heading", id=id, level=level, text=text)


def _list_item(id: str, text: str) -> ListItem:
    return ListItem(id=id, inlines=[_text(text)])


def _cell(id: str, text: str) -> TableCell:
    return TableCell(id=id, content=[_para(f"{id}_p", _text(text))])


# ---------------------------------------------------------------------------
# 헤딩 레벨 테스트
# ---------------------------------------------------------------------------

class TestHeadingLevels:
    def test_heading_levels(self) -> None:
        doc = _make_doc(
            _heading("h1", 1, "Heading One"),
            _heading("h2", 2, "Heading Two"),
            _heading("h3", 3, "Heading Three"),
            _heading("h4", 4, "Heading Four"),
        )
        html = render_html(doc)
        assert "<h1>Heading One</h1>" in html
        assert "<h2>Heading Two</h2>" in html
        assert "<h3>Heading Three</h3>" in html
        assert "<h4>Heading Four</h4>" in html

    def test_heading_level_clamped_min(self) -> None:
        """level=1 은 <h1>."""
        doc = _make_doc(_heading("h", 1, "Min"))
        assert "<h1>Min</h1>" in render_html(doc)

    def test_heading_level_clamped_max(self) -> None:
        """level=6 은 <h6>."""
        doc = _make_doc(_heading("h", 6, "Max"))
        assert "<h6>Max</h6>" in render_html(doc)


# ---------------------------------------------------------------------------
# 인라인 서식 테스트
# ---------------------------------------------------------------------------

class TestInlineFormatting:
    def test_inline_bold(self) -> None:
        doc = _make_doc(_para("p1", _text("bold word", bold=True)))
        assert "<strong>bold word</strong>" in render_html(doc)

    def test_inline_italic(self) -> None:
        doc = _make_doc(_para("p1", _text("italic word", italic=True)))
        assert "<em>italic word</em>" in render_html(doc)

    def test_bold_and_italic(self) -> None:
        doc = _make_doc(_para("p1", _text("bi", bold=True, italic=True)))
        html = render_html(doc)
        # bold 먼저 감싸고 그 안에 italic, 또는 반대 순서 모두 허용
        assert "<strong>" in html and "<em>" in html and "bi" in html

    def test_inline_underline(self) -> None:
        doc = _make_doc(_para("p1", _text("under", underline=True)))
        assert "<u>under</u>" in render_html(doc)

    def test_inline_strikethrough(self) -> None:
        doc = _make_doc(_para("p1", _text("strike", strikethrough=True)))
        assert "<del>strike</del>" in render_html(doc)

    def test_plain_text_no_decoration(self) -> None:
        doc = _make_doc(_para("p1", _text("plain")))
        html = render_html(doc)
        assert "<p>plain</p>" in html
        assert "<strong>" not in html
        assert "<em>" not in html

    def test_mixed_inlines_in_paragraph(self) -> None:
        doc = _make_doc(_para("p1",
                              _text("start "),
                              _text("bold", bold=True),
                              _text(" end")))
        html = render_html(doc)
        assert "<strong>bold</strong>" in html
        assert "start" in html and "end" in html


# ---------------------------------------------------------------------------
# 리스트 테스트
# ---------------------------------------------------------------------------

class TestLists:
    def test_unordered_list(self) -> None:
        doc = _make_doc(ListBlock(
            type="list", id="ul1", ordered=False,
            items=[_list_item("i1", "Alpha"),
                   _list_item("i2", "Beta"),
                   _list_item("i3", "Gamma")],
        ))
        html = render_html(doc)
        assert "<ul>" in html
        assert "<li>Alpha</li>" in html
        assert "<li>Beta</li>" in html
        assert "<li>Gamma</li>" in html
        assert "<ol>" not in html

    def test_ordered_list(self) -> None:
        doc = _make_doc(ListBlock(
            type="list", id="ol1", ordered=True,
            items=[_list_item("i1", "First"),
                   _list_item("i2", "Second")],
        ))
        html = render_html(doc)
        assert "<ol>" in html
        assert "<li>First</li>" in html
        assert "<li>Second</li>" in html
        assert "<ul>" not in html

    def test_list_items_count(self) -> None:
        items = [_list_item(f"i{i}", f"Item {i}") for i in range(5)]
        doc = _make_doc(ListBlock(type="list", id="ul", ordered=False, items=items))
        html = render_html(doc)
        assert html.count("<li>") == 5


# ---------------------------------------------------------------------------
# 테이블 테스트
# ---------------------------------------------------------------------------

class TestTable:
    def test_table_rendered(self) -> None:
        tbl = TableBlock(
            type="table", id="t1",
            rows=[
                TableRow(cells=[_cell("c00", "Name"),  _cell("c01", "Age")]),
                TableRow(cells=[_cell("c10", "Alice"), _cell("c11", "30")]),
                TableRow(cells=[_cell("c20", "Bob"),   _cell("c21", "25")]),
            ],
        )
        doc = _make_doc(tbl)
        html = render_html(doc)
        assert "<table>" in html
        assert "<th>" in html       # 헤더 행 (첫 번째 행)
        assert "<td>" in html       # 데이터 행
        assert "Name" in html
        assert "Alice" in html
        assert "Bob" in html

    def test_table_first_row_th(self) -> None:
        tbl = TableBlock(
            type="table", id="t1",
            rows=[
                TableRow(cells=[_cell("c00", "H1"), _cell("c01", "H2")]),
                TableRow(cells=[_cell("c10", "D1"), _cell("c11", "D2")]),
            ],
        )
        html = render_html(_make_doc(tbl))
        # 첫 행은 <th>, 두 번째 행은 <td>
        assert "<th>H1</th>" in html
        assert "<td>D1</td>" in html

    def test_empty_table_no_crash(self) -> None:
        tbl = TableBlock(type="table", id="t_empty", rows=[])
        html = render_html(_make_doc(tbl))
        # 빈 테이블은 빈 문자열이므로 <table> 없어도 괜찮음
        assert isinstance(html, str)


# ---------------------------------------------------------------------------
# 이미지 테스트
# ---------------------------------------------------------------------------

class TestImage:
    def test_image_base64(self) -> None:
        img = ImageBlock(
            type="image", id="img1",
            src="data:image/png;base64,abc",
            alt="Test image",
        )
        html = render_html(_make_doc(img))
        assert "<img" in html
        assert 'src="data:image/png;base64,abc"' in html
        assert "Test image" in html

    def test_image_http(self) -> None:
        img = ImageBlock(
            type="image", id="img2",
            src="https://example.com/img.png",
            alt="Remote",
        )
        html = render_html(_make_doc(img))
        assert "<img" in html
        assert "https://example.com/img.png" in html

    def test_image_embedded_skipped(self) -> None:
        """embedded: 참조는 src 바이트 없으므로 렌더링 생략."""
        img = ImageBlock(
            type="image", id="img3",
            src="embedded:Im1",
        )
        html = render_html(_make_doc(img))
        # <img>가 없어야 함
        assert "<img" not in html


# ---------------------------------------------------------------------------
# 빈 단락 스킵 테스트
# ---------------------------------------------------------------------------

class TestEmptyParagraph:
    def test_empty_paragraph_skipped(self) -> None:
        doc = _make_doc(
            _heading("h1", 1, "Title"),
            _para("p_ws", _text("   ")),   # 공백만
            _para("p_ok", _text("content")),
        )
        html = render_html(doc)
        # 공백 단락은 <p>로 출력되지 않아야 함
        assert "<p>   </p>" not in html
        # 정상 단락은 출력
        assert "<p>content</p>" in html

    def test_empty_text_inline_skipped(self) -> None:
        doc = _make_doc(_para("p1", _text("")))
        html = render_html(doc)
        assert "<p></p>" not in html


# ---------------------------------------------------------------------------
# 푸터 메타데이터 테스트
# ---------------------------------------------------------------------------

class TestFooterMetadata:
    def test_footer_source_format(self) -> None:
        doc = _make_doc(source_format="pdf", parser_version="0.2.0")
        html = render_html(doc)
        assert "PDF" in html
        assert "0.2.0" in html

    def test_footer_hwp_format(self) -> None:
        doc = _make_doc(source_format="hwp", parser_version="1.0.0")
        html = render_html(doc)
        assert "HWP" in html
        assert "1.0.0" in html

    def test_footer_block_count(self) -> None:
        doc = _make_doc(
            _heading("h1", 1, "A"),
            _para("p1", _text("B")),
        )
        html = render_html(doc)
        # Blocks: 2 가 footer에 표시되어야 함
        assert "2" in html

    def test_title_in_html(self) -> None:
        doc = _make_doc(title="My Report")
        html = render_html(doc, title="My Report")
        assert "<title>My Report</title>" in html


# ---------------------------------------------------------------------------
# HTML 이스케이프 테스트
# ---------------------------------------------------------------------------

class TestHtmlEscape:
    def test_heading_escape(self) -> None:
        doc = _make_doc(_heading("h1", 1, "A & B > C"))
        html = render_html(doc)
        assert "A &amp; B &gt; C" in html
        assert "A & B > C" not in html

    def test_paragraph_escape(self) -> None:
        doc = _make_doc(_para("p1", _text("<script>alert(1)</script>")))
        html = render_html(doc)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
