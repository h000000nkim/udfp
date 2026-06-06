"""MD 파서 단위 테스트"""

from __future__ import annotations

from udf.parsers.md.parse import parse_md
from udf.core.schema import (
    EquationInline,
    FootnoteBlock,
    FootnoteRefInline,
    HeadingBlock,
    ParagraphBlock,
    TableBlock,
    TextInline,
)


def _text(block: ParagraphBlock) -> str:
    return "".join(i.text for i in block.inlines if isinstance(i, TextInline))


class TestParseParagraph:
    def test_simple(self) -> None:
        doc = parse_md("안녕하세요")
        assert len(doc.blocks) == 1
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert _text(b) == "안녕하세요"

    def test_multiple_paras(self) -> None:
        doc = parse_md("첫째\n\n둘째")
        assert len(doc.blocks) == 2
        assert _text(doc.blocks[0]) == "첫째"  # type: ignore[arg-type]
        assert _text(doc.blocks[1]) == "둘째"  # type: ignore[arg-type]

    def test_bold(self) -> None:
        doc = parse_md("**굵게** 일반")
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        inlines = b.inlines
        assert any(
            isinstance(i, TextInline) and i.bold and i.text == "굵게" for i in inlines
        )

    def test_italic(self) -> None:
        doc = parse_md("*기울임*")
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert any(isinstance(i, TextInline) and i.italic for i in b.inlines)

    def test_strikethrough(self) -> None:
        doc = parse_md("~~취소~~")
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        assert any(isinstance(i, TextInline) and i.strikethrough for i in b.inlines)


class TestParseHeading:
    def test_h1(self) -> None:
        doc = parse_md("# 제목")
        assert len(doc.blocks) == 1
        b = doc.blocks[0]
        assert isinstance(b, HeadingBlock)
        assert b.level == 1
        assert b.text == "제목"

    def test_h3(self) -> None:
        doc = parse_md("### 소제목")
        b = doc.blocks[0]
        assert isinstance(b, HeadingBlock)
        assert b.level == 3


class TestParseTable:
    def test_basic(self) -> None:
        md = "| 이름 | 나이 |\n| --- | --- |\n| 홍길동 | 30 |"
        doc = parse_md(md)
        assert len(doc.blocks) == 1
        b = doc.blocks[0]
        assert isinstance(b, TableBlock)
        # 구분행 제외 2행
        assert len(b.rows) == 2

    def test_cell_text(self) -> None:
        md = "| A | B |\n| --- | --- |\n| C | D |"
        doc = parse_md(md)
        b = doc.blocks[0]
        assert isinstance(b, TableBlock)
        cell_texts = []
        for row in b.rows:
            for cell in row.cells:
                for blk in cell.content:
                    if isinstance(blk, ParagraphBlock):
                        cell_texts.append(_text(blk))
        assert "A" in cell_texts
        assert "C" in cell_texts


class TestParseBlockIds:
    def test_id_extracted(self) -> None:
        md = "<!-- id: blk-001 -->\n안녕"
        doc = parse_md(md)
        b = doc.blocks[0]
        assert b.id == "blk-001"

    def test_no_id_gets_generated(self) -> None:
        doc = parse_md("안녕")
        assert doc.blocks[0].id is not None
        assert len(doc.blocks[0].id) > 0

    def test_multiple_ids(self) -> None:
        md = "<!-- id: blk-001 -->\n첫째\n\n<!-- id: blk-002 -->\n둘째"
        doc = parse_md(md)
        assert doc.blocks[0].id == "blk-001"
        assert doc.blocks[1].id == "blk-002"


class TestRoundtripMd:
    """render_md → parse_md 왕복 테스트."""

    def test_text_preserved(self) -> None:
        from udf.parsers.hwp.parse import parse_hwp
        from udf.renderers.md import render_md
        import pathlib
        import pytest

        fixture = str(
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures"
            / "hwp"
            / "f01_plain_text.hwp"
        )
        if not pathlib.Path(fixture).exists():
            pytest.skip("HWP fixture not available")
        doc = parse_hwp(fixture)
        md = render_md(doc, embed_ids=True)
        doc2 = parse_md(md)

        texts1 = [
            "".join(i.text for i in b.inlines if isinstance(i, TextInline))
            for b in doc.blocks
            if isinstance(b, ParagraphBlock)
        ]
        texts2 = [
            "".join(i.text for i in b.inlines if isinstance(i, TextInline))
            for b in doc2.blocks
            if isinstance(b, ParagraphBlock)
        ]
        # 비어있지 않은 단락 텍스트는 보존되어야 함
        non_empty1 = [t for t in texts1 if t.strip()]
        non_empty2 = [t for t in texts2 if t.strip()]
        assert non_empty1 == non_empty2

    def test_ids_preserved(self) -> None:
        from udf.parsers.hwp.parse import parse_hwp
        from udf.renderers.md import render_md
        import pathlib
        import pytest

        fixture = str(
            pathlib.Path(__file__).parent.parent.parent
            / "fixtures"
            / "hwp"
            / "f01_plain_text.hwp"
        )
        if not pathlib.Path(fixture).exists():
            pytest.skip("HWP fixture not available")
        doc = parse_hwp(fixture)
        md = render_md(doc, embed_ids=True)
        doc2 = parse_md(md)

        orig_ids = {b.id for b in doc.blocks if isinstance(b, ParagraphBlock)}
        rt_ids = {b.id for b in doc2.blocks if isinstance(b, ParagraphBlock)}
        assert orig_ids == rt_ids


class TestParseEquationInline:
    def test_inline_equation(self) -> None:
        doc = parse_md("에너지 $E=mc^2$ 공식")
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        eq_inlines = [i for i in b.inlines if isinstance(i, EquationInline)]
        assert len(eq_inlines) == 1
        assert eq_inlines[0].latex == "E=mc^2"

    def test_equation_with_surrounding_text(self) -> None:
        doc = parse_md("앞 $x+y$ 뒤")
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        texts = [i.text for i in b.inlines if isinstance(i, TextInline)]
        assert any("앞" in t for t in texts)
        assert any("뒤" in t for t in texts)
        eqs = [i for i in b.inlines if isinstance(i, EquationInline)]
        assert len(eqs) == 1
        assert eqs[0].latex == "x+y"

    def test_multiple_equations(self) -> None:
        doc = parse_md("$a$ 그리고 $b$")
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        eqs = [i for i in b.inlines if isinstance(i, EquationInline)]
        assert len(eqs) == 2

    def test_equation_roundtrip(self) -> None:
        from udf.renderers.md import render_md
        from udf.core.schema import DocumentMetadata, UdfDocument

        doc = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[
                ParagraphBlock(
                    type="paragraph", id="b1",
                    inlines=[
                        TextInline(text="공식 "),
                        EquationInline(latex="E=mc^2"),
                        TextInline(text=" 입니다"),
                    ],
                )
            ],
        )
        md = render_md(doc, embed_ids=False)
        doc2 = parse_md(md)
        b = doc2.blocks[0]
        assert isinstance(b, ParagraphBlock)
        eqs = [i for i in b.inlines if isinstance(i, EquationInline)]
        assert len(eqs) == 1
        assert eqs[0].latex == "E=mc^2"


class TestParseFootnoteRefInline:
    def test_footnote_ref_inline(self) -> None:
        doc = parse_md("본문[^1] 계속")
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        refs = [i for i in b.inlines if isinstance(i, FootnoteRefInline)]
        assert len(refs) == 1
        assert refs[0].ref_id == "1"

    def test_footnote_ref_not_confused_with_def(self) -> None:
        doc = parse_md("[^1]: 각주 정의")
        assert isinstance(doc.blocks[0], FootnoteBlock)

    def test_footnote_ref_with_surrounding_text(self) -> None:
        doc = parse_md("앞[^fn1]뒤")
        b = doc.blocks[0]
        assert isinstance(b, ParagraphBlock)
        texts = [i.text for i in b.inlines if isinstance(i, TextInline)]
        refs = [i for i in b.inlines if isinstance(i, FootnoteRefInline)]
        assert any("앞" in t for t in texts)
        assert any("뒤" in t for t in texts)
        assert len(refs) == 1
        assert refs[0].ref_id == "fn1"

    def test_footnote_ref_roundtrip(self) -> None:
        from udf.renderers.md import render_md
        from udf.core.schema import DocumentMetadata, UdfDocument

        doc = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[
                ParagraphBlock(
                    type="paragraph", id="b1",
                    inlines=[
                        TextInline(text="본문"),
                        FootnoteRefInline(ref_id="1"),
                        TextInline(text=" 계속"),
                    ],
                )
            ],
        )
        md = render_md(doc, embed_ids=False)
        doc2 = parse_md(md)
        b = doc2.blocks[0]
        assert isinstance(b, ParagraphBlock)
        refs = [i for i in b.inlines if isinstance(i, FootnoteRefInline)]
        assert len(refs) == 1
        assert refs[0].ref_id == "1"


class TestParseFootnote:
    def test_footnote_def_parsed(self) -> None:
        md = "[^1]: 각주 내용입니다"
        doc = parse_md(md)
        assert len(doc.blocks) == 1
        blk = doc.blocks[0]
        assert isinstance(blk, FootnoteBlock)
        assert blk.ref == "1"
        assert len(blk.content) == 1
        para = blk.content[0]
        assert isinstance(para, ParagraphBlock)
        assert _text(para) == "각주 내용입니다"

    def test_footnote_with_id(self) -> None:
        md = "<!-- id: fn_001 -->\n[^2]: 두 번째 각주"
        doc = parse_md(md)
        blk = doc.blocks[0]
        assert isinstance(blk, FootnoteBlock)
        assert blk.id == "fn_001"
        assert blk.ref == "2"

    def test_footnote_render_roundtrip(self) -> None:
        from udf.renderers.md import render_md
        from udf.core.schema import DocumentMetadata, UdfDocument

        fn = FootnoteBlock(
            type="footnote",
            id="fn_1",
            ref="1",
            content=[
                ParagraphBlock(
                    type="paragraph",
                    id="fn_1_p",
                    inlines=[TextInline(text="각주 텍스트")],
                )
            ],
        )
        doc = UdfDocument(
            source_format="hwp",
            metadata=DocumentMetadata(),
            blocks=[fn],
        )
        md = render_md(doc, embed_ids=True)
        assert "[^1]:" in md
        assert "각주 텍스트" in md

        doc2 = parse_md(md)
        fn2 = [b for b in doc2.blocks if isinstance(b, FootnoteBlock)]
        assert len(fn2) == 1
        assert fn2[0].ref == "1"
