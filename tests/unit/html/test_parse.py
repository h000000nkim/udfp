"""HTML 파서 유닛 테스트."""

from __future__ import annotations


from udf.core.schema import (
    DrawingBlock,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TextBoxBlock,
)
from udf.schema import (
    CodeBlock,
    CodeInline,
    EndnoteRefInline,
    FootnoteRefInline,
    HorizontalRuleBlock,
    ImageBlock,
    ListBlock,
    QuoteBlock,
    RubyInline,
    TextInline,
)
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


class TestBug130IndentMapping:
    """BUG-130: margin-left/right → indent_left/right 매핑."""

    def test_margin_left_to_indent(self) -> None:
        html = '<html><body><article>'
        html += '<p style="margin-left:24pt;margin-right:12pt">들여쓰기</p>'
        html += '</article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        assert p.format is not None
        assert p.format.indent_left == 24.0
        assert p.format.indent_right == 12.0

    def test_padding_left_fallback(self) -> None:
        html = '<html><body><article>'
        html += '<p style="padding-left:16pt">패딩 들여쓰기</p>'
        html += '</article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        assert p.format is not None
        assert p.format.indent_left == 16.0


class TestBug131FigureTag:
    """BUG-131: <figure> 태그 파싱."""

    def test_figure_image(self) -> None:
        html = '<html><body><article>'
        html += '<figure><img src="test.png" alt="테스트"></figure>'
        html += '</article></body></html>'
        doc = parse_html(html)
        imgs = [b for b in doc.blocks if isinstance(b, ImageBlock)]
        assert len(imgs) == 1
        assert imgs[0].src == "test.png"
        assert imgs[0].alt == "테스트"

    def test_figure_with_caption(self) -> None:
        html = '<html><body><article>'
        html += '<figure><img src="img.png" alt=""><figcaption>캡션 텍스트</figcaption></figure>'
        html += '</article></body></html>'
        doc = parse_html(html)
        imgs = [b for b in doc.blocks if isinstance(b, ImageBlock)]
        assert len(imgs) == 1
        assert imgs[0].caption is not None
        assert any(il.text == "캡션 텍스트" for il in imgs[0].caption if hasattr(il, "text"))


class TestBug132BlockTypes:
    """BUG-132: 누락된 블록 타입 파싱."""

    def test_unordered_list(self) -> None:
        html = '<html><body><article><ul><li>항목1</li><li>항목2</li></ul></article></body></html>'
        doc = parse_html(html)
        lists = [b for b in doc.blocks if isinstance(b, ListBlock)]
        assert len(lists) == 1
        assert lists[0].ordered is False
        assert len(lists[0].items) == 2

    def test_ordered_list(self) -> None:
        html = '<html><body><article><ol><li>첫째</li><li>둘째</li></ol></article></body></html>'
        doc = parse_html(html)
        lists = [b for b in doc.blocks if isinstance(b, ListBlock)]
        assert len(lists) == 1
        assert lists[0].ordered is True

    def test_nested_list(self) -> None:
        html = '<html><body><article><ul><li>부모<ul><li>자식</li></ul></li></ul></article></body></html>'
        doc = parse_html(html)
        lists = [b for b in doc.blocks if isinstance(b, ListBlock)]
        assert len(lists) == 1
        assert lists[0].items[0].children is not None
        assert len(lists[0].items[0].children) == 1

    def test_code_block(self) -> None:
        html = '<html><body><article><pre><code class="language-python">print("hello")</code></pre></article></body></html>'
        doc = parse_html(html)
        codes = [b for b in doc.blocks if isinstance(b, CodeBlock)]
        assert len(codes) == 1
        assert codes[0].code == 'print("hello")'
        assert codes[0].language == "python"

    def test_blockquote(self) -> None:
        html = '<html><body><article><blockquote><p>인용문</p></blockquote></article></body></html>'
        doc = parse_html(html)
        quotes = [b for b in doc.blocks if isinstance(b, QuoteBlock)]
        assert len(quotes) == 1
        assert len(quotes[0].content) == 1

    def test_horizontal_rule(self) -> None:
        html = '<html><body><article><p>위</p><hr><p>아래</p></article></body></html>'
        doc = parse_html(html)
        hrs = [b for b in doc.blocks if isinstance(b, HorizontalRuleBlock)]
        assert len(hrs) == 1


class TestBug133InlineTypes:
    """BUG-133: 누락된 인라인 타입."""

    def test_code_inline(self) -> None:
        html = '<html><body><article><p>텍스트 <code>코드</code> 끝</p></article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        code_inlines = [il for il in p.inlines if isinstance(il, CodeInline)]
        assert len(code_inlines) == 1
        assert code_inlines[0].code == "코드"

    def test_ruby_inline(self) -> None:
        html = '<html><body><article><p><ruby>漢字<rp>(</rp><rt>かんじ</rt><rp>)</rp></ruby></p></article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        rubies = [il for il in p.inlines if isinstance(il, RubyInline)]
        assert len(rubies) == 1
        assert rubies[0].base_text == "漢字"
        assert rubies[0].ruby_text == "かんじ"

    def test_subscript(self) -> None:
        html = '<html><body><article><p>H<sub>2</sub>O</p></article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        subs = [il for il in p.inlines if isinstance(il, TextInline) and il.subscript]
        assert len(subs) == 1
        assert subs[0].text == "2"

    def test_superscript(self) -> None:
        html = '<html><body><article><p>x<sup>2</sup></p></article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        sups = [il for il in p.inlines if isinstance(il, TextInline) and il.superscript]
        assert len(sups) == 1
        assert sups[0].text == "2"

    def test_footnote_ref(self) -> None:
        html = '<html><body><article><p>텍스트<sup><a href="#fn-1" class="footnote-ref">1</a></sup></p></article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        refs = [il for il in p.inlines if isinstance(il, FootnoteRefInline)]
        assert len(refs) == 1
        assert refs[0].ref_id == "1"

    def test_endnote_ref(self) -> None:
        html = '<html><body><article><p>텍스트<sup><a href="#en-abc" class="endnote-ref">2</a></sup></p></article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        refs = [il for il in p.inlines if isinstance(il, EndnoteRefInline)]
        assert len(refs) == 1
        assert refs[0].ref_id == "abc"
        assert refs[0].number == 2


class TestBug134CssRecovery:
    """BUG-134: TextInline CSS 속성 복원."""

    def test_background_color(self) -> None:
        html = '<html><body><article><p><span style="background-color:#ff0000">하이라이트</span></p></article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        hi = [il for il in p.inlines if isinstance(il, TextInline) and il.highlight_color]
        assert len(hi) == 1
        assert str(hi[0].highlight_color) == "#ff0000" or hi[0].highlight_color.to_hex() == "#ff0000"

    def test_small_caps(self) -> None:
        html = '<html><body><article><p><span style="font-variant:small-caps">Text</span></p></article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        sc = [il for il in p.inlines if isinstance(il, TextInline) and il.small_caps]
        assert len(sc) == 1

    def test_shadow(self) -> None:
        html = '<html><body><article><p><span style="text-shadow:1px 1px 2px rgba(0,0,0,0.3)">그림자</span></p></article></body></html>'
        doc = parse_html(html)
        p = doc.blocks[0]
        assert isinstance(p, ParagraphBlock)
        sh = [il for il in p.inlines if isinstance(il, TextInline) and il.shadow]
        assert len(sh) == 1


class TestBug135TheadTbody:
    """BUG-135: thead/tbody 지원."""

    def test_table_with_thead_tbody(self) -> None:
        html = '<html><body><article>'
        html += '<table><thead><tr><th>헤더</th></tr></thead>'
        html += '<tbody><tr><td>데이터1</td></tr><tr><td>데이터2</td></tr></tbody></table>'
        html += '</article></body></html>'
        doc = parse_html(html)
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) == 1
        assert len(tables[0].rows) == 3

    def test_table_with_tfoot(self) -> None:
        html = '<html><body><article>'
        html += '<table><tbody><tr><td>본문</td></tr></tbody>'
        html += '<tfoot><tr><td>합계</td></tr></tfoot></table>'
        html += '</article></body></html>'
        doc = parse_html(html)
        tables = [b for b in doc.blocks if isinstance(b, TableBlock)]
        assert len(tables) == 1
        assert len(tables[0].rows) == 2
