"""MD 렌더러 단위 테스트"""

from __future__ import annotations

from udf.core.schema import (
    DocumentMetadata,
    EquationInline,
    FootnoteRefInline,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextInline,
    UdfDocument,
)
from udf.renderers.md import render_md, render_html, _escape_md, _escape_line_start


def _make_doc(blocks: list) -> UdfDocument:
    return UdfDocument(
        source_format="hwp",
        metadata=DocumentMetadata(),
        blocks=blocks,
    )


def _para(text: str, blk_id: str = "b1") -> ParagraphBlock:
    return ParagraphBlock(
        type="paragraph",
        id=blk_id,
        inlines=[TextInline(text=text)],
    )


class TestEscapeMd:
    def test_special_chars(self) -> None:
        assert _escape_md("a*b") == r"a\*b"
        assert _escape_md("a_b") == r"a\_b"
        assert _escape_md("[link]") == r"\[link\]"

    def test_plain(self) -> None:
        assert _escape_md("hello 안녕") == "hello 안녕"

    def test_pipe_escaped(self) -> None:
        assert _escape_md("a|b") == r"a\|b"

    def test_hash_not_escaped_inline(self) -> None:
        assert _escape_md("#heading") == "#heading"
        assert _escape_md("C# programming") == "C# programming"


class TestEscapeLineStart:
    """줄 시작 블록 문법 이스케이프 테스트."""

    def test_ordered_list(self) -> None:
        assert _escape_line_start("1. 첫번째 항목") == "1\\. 첫번째 항목"
        assert _escape_line_start("23. 항목") == "23\\. 항목"

    def test_heading(self) -> None:
        assert _escape_line_start("# 제목") == "\\# 제목"
        assert _escape_line_start("## 부제") == "\\## 부제"

    def test_unordered_list(self) -> None:
        assert _escape_line_start("- 항목") == "\\- 항목"
        assert _escape_line_start("+ 항목") == "\\+ 항목"

    def test_image(self) -> None:
        assert _escape_line_start("![alt](url)") == "\\![alt](url)"

    def test_blockquote(self) -> None:
        assert _escape_line_start("> 인용") == "\\> 인용"

    def test_safe_patterns_unchanged(self) -> None:
        assert _escape_line_start("일반 텍스트") == "일반 텍스트"
        assert _escape_line_start("C# 프로그래밍") == "C# 프로그래밍"
        assert _escape_line_start("a-b 연결") == "a-b 연결"
        assert _escape_line_start("버전 1.0") == "버전 1.0"
        assert _escape_line_start("(1) 항목") == "(1) 항목"
        assert _escape_line_start("안녕!") == "안녕!"
        assert _escape_line_start("<해설> 내용") == "<해설> 내용"


class TestEscapeUnescapeSymmetry:
    """escape → unescape 라운드트립 대칭성."""

    def test_special_chars_roundtrip(self) -> None:
        from udf.parsers.md.parse import _unescape

        cases = [
            "a*b",
            "a|b|c",
            "hello [world]",
            "a_b_c",
            "a~b~c",
            "back\\slash",
        ]
        for orig in cases:
            escaped = _escape_md(orig)
            restored = _unescape(escaped)
            assert restored == orig, f"대칭 실패: {orig!r} → {escaped!r} → {restored!r}"


class TestRenderParagraph:
    def test_simple_text(self) -> None:
        doc = _make_doc([_para("안녕하세요")])
        md = render_md(doc, embed_ids=False)
        assert "안녕하세요" in md

    def test_empty_para_skipped(self) -> None:
        doc = _make_doc(
            [
                ParagraphBlock(type="paragraph", id="b1", inlines=[]),
                _para("유일한 텍스트", "b2"),
            ]
        )
        md = render_md(doc, embed_ids=False)
        assert "유일한 텍스트" in md

    def test_bold_italic(self) -> None:
        doc = _make_doc(
            [
                ParagraphBlock(
                    type="paragraph",
                    id="b1",
                    inlines=[
                        TextInline(text="굵게", bold=True),
                        TextInline(text=" "),
                        TextInline(text="기울임", italic=True),
                    ],
                )
            ]
        )
        md = render_md(doc, embed_ids=False)
        assert "**굵게**" in md
        assert "*기울임*" in md


class TestRenderHeading:
    def test_h1(self) -> None:
        doc = _make_doc([HeadingBlock(type="heading", id="h1", level=1, text="제목")])
        md = render_md(doc, embed_ids=False)
        assert md.startswith("# 제목")

    def test_h2(self) -> None:
        doc = _make_doc([HeadingBlock(type="heading", id="h2", level=2, text="소제목")])
        md = render_md(doc, embed_ids=False)
        assert "## 소제목" in md


class TestRenderTable:
    def test_simple_table(self) -> None:
        def cell(text: str, cid: str) -> TableCell:
            return TableCell(
                id=cid,
                content=[
                    ParagraphBlock(
                        type="paragraph", id=f"p{cid}", inlines=[TextInline(text=text)]
                    )
                ],
            )

        tbl = TableBlock(
            type="table",
            id="t1",
            rows=[
                TableRow(cells=[cell("이름", "c1"), cell("나이", "c2")]),
                TableRow(cells=[cell("홍길동", "c3"), cell("30", "c4")]),
            ],
        )
        doc = _make_doc([tbl])
        md = render_md(doc, embed_ids=False)
        assert "<table" in md
        assert "<td>이름</td>" in md
        assert "<td>홍길동</td>" in md


class TestEmbedIds:
    def test_id_comment_present(self) -> None:
        doc = _make_doc([_para("텍스트", "blk-001")])
        md = render_md(doc, embed_ids=True)
        assert "<!-- id: blk-001 -->" in md

    def test_no_id_comment(self) -> None:
        doc = _make_doc([_para("텍스트", "blk-001")])
        md = render_md(doc, embed_ids=False)
        assert "<!-- id:" not in md


class TestEquationInlineRendering:
    def test_md_latex(self) -> None:
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[
                    TextInline(text="에너지 "),
                    EquationInline(latex="E=mc^2"),
                    TextInline(text=" 공식"),
                ],
            )
        ])
        md = render_md(doc, embed_ids=False)
        assert "$E\\=mc^2$" in md or "$E=mc^2$" in md

    def test_md_hwp_script_fallback(self) -> None:
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[EquationInline(hwp_script="x + y")],
            )
        ])
        md = render_md(doc, embed_ids=False)
        assert "$" in md
        assert "x" in md

    def test_md_empty_equation_skipped(self) -> None:
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[
                    TextInline(text="앞"),
                    EquationInline(),
                    TextInline(text="뒤"),
                ],
            )
        ])
        md = render_md(doc, embed_ids=False)
        assert "앞" in md
        assert "뒤" in md
        assert "$" not in md

    def test_html_equation_inline(self) -> None:
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[
                    TextInline(text="공식: "),
                    EquationInline(latex="a^2+b^2=c^2"),
                ],
            )
        ])
        html = render_html(doc)
        assert "\\(a^2+b^2=c^2\\)" in html or "\\(a" in html


class TestFootnoteRefInlineRendering:
    def test_md_footnote_ref(self) -> None:
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[
                    TextInline(text="본문 텍스트"),
                    FootnoteRefInline(ref_id="1"),
                ],
            )
        ])
        md = render_md(doc, embed_ids=False)
        assert "[^1]" in md

    def test_md_footnote_ref_with_text(self) -> None:
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[
                    TextInline(text="앞"),
                    FootnoteRefInline(ref_id="fn1"),
                    TextInline(text="뒤"),
                ],
            )
        ])
        md = render_md(doc, embed_ids=False)
        assert "앞" in md
        assert "[^fn1]" in md
        assert "뒤" in md

    def test_html_footnote_ref(self) -> None:
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[
                    TextInline(text="본문"),
                    FootnoteRefInline(ref_id="2", number=2),
                ],
            )
        ])
        html = render_html(doc)
        assert 'href="#fn-2"' in html
        assert "<sup>" in html

    def test_html_footnote_ref_uses_number(self) -> None:
        doc = _make_doc([
            ParagraphBlock(
                type="paragraph", id="b1",
                inlines=[
                    FootnoteRefInline(ref_id="abc", number=5),
                ],
            )
        ])
        html = render_html(doc)
        assert ">5</a>" in html


class TestRenderHwpFixtures:
    def test_f01_plain_text(self) -> None:
        from udf.parsers.hwp.parse import parse_hwp
        import pathlib

        fixture = str(
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures"
            / "hwp"
            / "f01_plain_text.hwp"
        )
        doc = parse_hwp(fixture)
        md = render_md(doc, embed_ids=False)
        assert "첫 번째 단락" in md
        assert "두 번째 단락" in md
        assert "세 번째 단락" in md

    def test_f04_table(self) -> None:
        from udf.parsers.hwp.parse import parse_hwp
        import pathlib

        fixture = str(
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures"
            / "hwp"
            / "f04_simple_table.hwp"
        )
        doc = parse_hwp(fixture)
        md = render_md(doc, embed_ids=False)
        assert "<table" in md

    def test_f05_cell_text(self) -> None:
        from udf.parsers.hwp.parse import parse_hwp
        import pathlib

        fixture = str(
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures"
            / "hwp"
            / "f05_table_cell_text.hwp"
        )
        doc = parse_hwp(fixture)
        md = render_md(doc, embed_ids=False)
        assert "이름" in md
        assert "홍길동" in md
