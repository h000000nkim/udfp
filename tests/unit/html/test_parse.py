"""HTML 파서 유닛 테스트."""

from __future__ import annotations

import pytest

from udf.core.schema import (
    DrawingBlock,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TextBoxBlock,
)
from udf.schema import TextInline
from udf.parsers.html.parse import (
    _strip_autonumber_inlines,
    parse_html,
)


class TestStripAutonumber:
    """C-1: render_html이 추가한 번호 prefix 제거."""

    def test_arabic_dot(self) -> None:
        inlines = [
            TextInline(text="1.", bold=True),
            TextInline(text=" 제목 텍스트"),
        ]
        result = _strip_autonumber_inlines(inlines)
        assert len(result) == 1
        assert result[0].text == "제목 텍스트"

    def test_multi_level(self) -> None:
        inlines = [
            TextInline(text="1.2.", bold=True),
            TextInline(text=" 하위 제목"),
        ]
        result = _strip_autonumber_inlines(inlines)
        assert len(result) == 1
        assert result[0].text == "하위 제목"

    def test_korean_syllable(self) -> None:
        inlines = [
            TextInline(text="가.", bold=True),
            TextInline(text=" 항목"),
        ]
        result = _strip_autonumber_inlines(inlines)
        assert result[0].text == "항목"

    def test_parenthesized(self) -> None:
        inlines = [
            TextInline(text="(1)", bold=True),
            TextInline(text=" 항목"),
        ]
        result = _strip_autonumber_inlines(inlines)
        assert result[0].text == "항목"

    def test_non_number_not_stripped(self) -> None:
        inlines = [
            TextInline(text="중요:", bold=True),
            TextInline(text=" 내용"),
        ]
        result = _strip_autonumber_inlines(inlines)
        assert len(result) == 2
        assert result[0].text == "중요:"

    def test_no_bold_not_stripped(self) -> None:
        inlines = [
            TextInline(text="1."),
            TextInline(text=" 내용"),
        ]
        result = _strip_autonumber_inlines(inlines)
        assert len(result) == 2

    def test_empty_inlines(self) -> None:
        assert _strip_autonumber_inlines([]) == []


class TestParseHtmlHeading:
    """HeadingBlock 파싱 + 번호 제거."""

    def test_heading_with_numbering_and_bid(self) -> None:
        html = '<html><body><div class="page"><div class="content">'
        html += '<h1 data-bid="h1"><strong>1.</strong> 제목</h1>'
        html += '</div></div></body></html>'
        doc = parse_html(html)
        headings = [b for b in doc.blocks if isinstance(b, HeadingBlock)]
        assert len(headings) == 1
        assert headings[0].text == "제목"
        assert headings[0].id == "h1"

    def test_heading_without_bid_keeps_number(self) -> None:
        html = '<html><body><div class="page"><div class="content">'
        html += '<h1><strong>1.</strong> 제목</h1>'
        html += '</div></div></body></html>'
        doc = parse_html(html)
        headings = [b for b in doc.blocks if isinstance(b, HeadingBlock)]
        assert len(headings) == 1
        assert "1." in headings[0].text


class TestParseHtmlCellBid:
    """C-2: 테이블 셀 내부 <p data-bid> 추출."""

    def test_cell_paragraph_bid(self) -> None:
        html = '<html><body><div class="page"><div class="content">'
        html += '<table data-bid="t1"><tr>'
        html += '<td><p data-bid="cp1">셀 텍스트</p></td>'
        html += '</tr></table>'
        html += '</div></div></body></html>'
        doc = parse_html(html)
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) == 1
        cell = tables[0].rows[0].cells[0]
        assert len(cell.content) >= 1
        para = cell.content[0]
        assert isinstance(para, ParagraphBlock)
        assert para.id == "cp1"


class TestParseHtmlTextBoxDrawing:
    """C-3: TextBox/Drawing 감지."""

    def test_textbox_detection(self) -> None:
        html = '<html><body><div class="page"><div class="content">'
        html += '<div data-bid="tb1" style="padding:6pt 8pt;border:1pt solid black;overflow:hidden">'
        html += '<p>텍스트박스 내용</p></div>'
        html += '</div></div></body></html>'
        doc = parse_html(html)
        tbs = [b for b in doc.blocks if isinstance(b, TextBoxBlock)]
        assert len(tbs) == 1
        assert tbs[0].id == "tb1"

    def test_drawing_detection(self) -> None:
        html = '<html><body><div class="page"><div class="content">'
        html += '<div data-bid="d1" style="position:absolute;left:100pt;top:50pt;width:200pt;height:100pt;background:#cccccc">'
        html += '</div>'
        html += '</div></div></body></html>'
        doc = parse_html(html)
        drawings = [b for b in doc.blocks if isinstance(b, DrawingBlock)]
        assert len(drawings) == 1
        assert drawings[0].id == "d1"
        assert drawings[0].position is not None
        assert drawings[0].position.width == 200.0
