"""From Scratch 생성기 유닛 테스트."""

from __future__ import annotations

import pathlib

import pytest

from udf.core.schema import (
    BlockFormat,
    BookmarkBlock,
    CodeBlock,
    DocumentMetadata,
    EndnoteBlock,
    EquationBlock,
    FieldBlock,
    FootnoteBlock,
    HeadingBlock,
    HorizontalRuleBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    PageBreakBlock,
    PageMargins,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
    TableCell,
    TableRow,
    TextBoxBlock,
    TextInline,
    UdfDocument,
    UnknownBlock,
)
from udf.renderers.hwp.scratch import (
    HWP_DEFAULTS,
    CharShapeSpec,
    ParaShapeSpec,
    collect_shapes,
    generate_hwp_scratch,
    _charshape_from_inline,
    _charshape_key,
    _parse_color,
    _parse_font_size_pt,
)
from udf.parsers.hwp.parse import parse_hwp

SEED = pathlib.Path(__file__).parent.parent.parent / "fixtures" / "hwp" / "f01_plain_text.hwp"


class TestColorParsing:
    def test_hex_color(self) -> None:
        assert _parse_color("#ff0000") == (255, 0, 0)
        assert _parse_color("#00ff00") == (0, 255, 0)
        assert _parse_color("#0000ff") == (0, 0, 255)

    def test_none_color(self) -> None:
        assert _parse_color(None) == (0, 0, 0)

    def test_invalid_color(self) -> None:
        assert _parse_color("red") == (0, 0, 0)


class TestFontSizeParsing:
    def test_pt_suffix(self) -> None:
        assert _parse_font_size_pt("12pt") == 12.0

    def test_none(self) -> None:
        assert _parse_font_size_pt(None) == HWP_DEFAULTS["font_size_pt"]


class TestCharShapeFromInline:
    def test_plain(self) -> None:
        il = TextInline(text="hello")
        cs = _charshape_from_inline(il)
        assert cs.size_pt == HWP_DEFAULTS["font_size_pt"]
        assert cs.bold is False
        assert cs.color_r == 0

    def test_bold_colored(self) -> None:
        il = TextInline(text="hello", bold=True, color="#ff0000", font_size=14.0)
        cs = _charshape_from_inline(il)
        assert cs.bold is True
        assert cs.color_r == 255
        assert cs.size_pt == 14.0


class TestCollectShapes:
    def test_default_always_present(self) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="a")])],
        )
        cs_list, ps_list, cs_map, ps_map = collect_shapes(doc)
        assert len(cs_list) >= 1
        assert len(ps_list) >= 1

    def test_distinct_styles_collected(self) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[
                ParagraphBlock(type="paragraph", id="p1", inlines=[
                    TextInline(text="normal"),
                    TextInline(text="bold", bold=True),
                    TextInline(text="colored", color="#ff0000"),
                ]),
            ],
        )
        cs_list, ps_list, cs_map, ps_map = collect_shapes(doc)
        assert len(cs_list) >= 3


class TestGenerateHwpScratch:
    @pytest.fixture
    def seed(self) -> str:
        assert SEED.exists(), f"seed 없음: {SEED}"
        return str(SEED)

    def test_simple_paragraphs(self, seed: str, tmp_path: pathlib.Path) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[
                ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="첫 번째")]),
                ParagraphBlock(type="paragraph", id="p2", inlines=[TextInline(text="두 번째")]),
            ],
        )
        out = str(tmp_path / "simple.hwp")
        generate_hwp_scratch(doc, out, seed)

        result = parse_hwp(out)
        texts = []
        for b in result.blocks:
            if isinstance(b, ParagraphBlock):
                t = "".join(i.text for i in b.inlines if isinstance(i, TextInline))
                if t.strip():
                    texts.append(t)
        assert "첫 번째" in texts
        assert "두 번째" in texts

    def test_heading_and_paragraph(self, seed: str, tmp_path: pathlib.Path) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[
                HeadingBlock(type="heading", id="h1", level=1, text="제목"),
                ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="본문")]),
            ],
        )
        out = str(tmp_path / "heading.hwp")
        generate_hwp_scratch(doc, out, seed)

        result = parse_hwp(out)
        all_texts = []
        for b in result.blocks:
            if isinstance(b, ParagraphBlock):
                t = "".join(i.text for i in b.inlines if isinstance(i, TextInline))
                if t.strip():
                    all_texts.append(t)
            elif isinstance(b, HeadingBlock):
                all_texts.append(b.text)
        assert "제목" in all_texts
        assert "본문" in all_texts

    def test_bold_italic_preserved(self, seed: str, tmp_path: pathlib.Path) -> None:
        doc = UdfDocument(
            source_format="md",
            blocks=[
                ParagraphBlock(type="paragraph", id="p1", inlines=[
                    TextInline(text="일반 "),
                    TextInline(text="굵게", bold=True),
                    TextInline(text=" 기울임", italic=True),
                ]),
            ],
        )
        out = str(tmp_path / "format.hwp")
        generate_hwp_scratch(doc, out, seed)

        result = parse_hwp(out)
        found = False
        for b in result.blocks:
            if isinstance(b, ParagraphBlock):
                t = "".join(i.text for i in b.inlines if isinstance(i, TextInline))
                if "굵게" in t:
                    found = True
        assert found

    def test_from_scratch_via_generate_hwp(self, seed: str, tmp_path: pathlib.Path) -> None:
        """generate_hwp()가 verbatim 없을 때 From Scratch fallback."""
        from udf.renderers.hwp import generate_hwp

        doc = UdfDocument(
            source_format="md",
            blocks=[
                ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="fallback 테스트")]),
            ],
        )
        out = str(tmp_path / "fallback.hwp")
        generate_hwp(doc, out, validate=False, seed_path=seed)

        result = parse_hwp(out)
        texts = [
            "".join(i.text for i in b.inlines if isinstance(i, TextInline))
            for b in result.blocks if isinstance(b, ParagraphBlock)
        ]
        assert any("fallback 테스트" in t for t in texts)


class TestBlockTypeCompleteness:
    """22개 블록 타입 전부 From Scratch 렌더링 or LossReport."""

    @pytest.fixture
    def seed(self) -> str:
        assert SEED.exists()
        return str(SEED)

    def _gen(self, blocks, seed, tmp_path):
        doc = UdfDocument(source_format="udf", blocks=blocks)
        out = str(tmp_path / "out.hwp")
        from udf.renderers.hwp.scratch import generate_hwp_scratch
        loss = generate_hwp_scratch(doc, out, seed)
        result = parse_hwp(out)
        return result, loss

    def test_list_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            ListBlock(type="list", id="l1", ordered=True, items=[
                ListItem(id="li1", inlines=[TextInline(text="첫째")]),
                ListItem(id="li2", inlines=[TextInline(text="둘째")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        texts = [b.text_content() for b in result.blocks]
        full = " ".join(texts)
        assert "1." in full and "첫째" in full
        assert loss is None

    def test_code_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            CodeBlock(type="code", id="c1", code="print('hello')"),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "print" in full
        assert loss is None

    def test_quote_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            QuoteBlock(type="quote", id="q1", content=[
                ParagraphBlock(type="paragraph", id="qp1", inlines=[TextInline(text="인용문")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "인용문" in full
        assert loss is None

    def test_horizontal_rule_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            HorizontalRuleBlock(type="horizontal_rule", id="hr1"),
            ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="after")]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        assert len(result.blocks) >= 3
        assert loss is None

    def test_footnote_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="본문")]),
            FootnoteBlock(type="footnote", id="fn1", ref="1", content=[
                ParagraphBlock(type="paragraph", id="fp1", inlines=[TextInline(text="각주 내용")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "각주 내용" in full
        assert loss is None  # native footnote CTRL_HEADER

    def test_endnote_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="본문")]),
            EndnoteBlock(type="endnote", id="en1", ref="1", content=[
                ParagraphBlock(type="paragraph", id="ep1", inlines=[TextInline(text="미주 내용")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "미주 내용" in full
        assert loss is None  # native endnote CTRL_HEADER

    def test_field_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            FieldBlock(type="field", id="f1", field_type="page_number", value="3"),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "3" in full
        assert loss is None

    def test_textbox_block(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            TextBoxBlock(type="text_box", id="tb1", content=[
                ParagraphBlock(type="paragraph", id="tp1", inlines=[TextInline(text="박스 내용")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "박스 내용" in full
        assert loss is None

    def test_image_block_loss(self, seed: str, tmp_path) -> None:
        """이미지 파일이 없으면 loss 보고."""
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            ImageBlock(type="image", id="img1", src="nonexistent_file.png"),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        assert loss is not None
        assert any("not found" in bl.description.lower() or "Image" in bl.description for bl in loss.lossy_blocks)

    def test_unknown_block_loss(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            UnknownBlock(type="unknown", id="u1", raw_bytes="deadbeef"),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        assert loss is not None
        assert any("UnknownBlock" in bl.description for bl in loss.lossy_blocks)

    def test_bookmark_skip(self, seed: str, tmp_path) -> None:
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            BookmarkBlock(type="bookmark", id="bm1", name="test"),
            ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="after")]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "before" in full and "after" in full
        assert loss is None

    def test_table_multi_content(self, seed: str, tmp_path) -> None:
        """셀 내 다중 블록이 모두 렌더링되는지 확인."""
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="intro")]),
            TableBlock(type="table", id="t1", rows=[
                TableRow(cells=[
                    TableCell(id="c1", content=[
                        ParagraphBlock(type="paragraph", id="cp1", inlines=[TextInline(text="셀A ")]),
                        ParagraphBlock(type="paragraph", id="cp2", inlines=[TextInline(text="셀B")]),
                    ]),
                ]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "셀A" in full and "셀B" in full

    def test_footnote_native_structure(self, seed: str, tmp_path) -> None:
        """네이티브 각주가 FootnoteBlock으로 파싱되는지 확인."""
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="본문")]),
            FootnoteBlock(type="footnote", id="fn1", ref="1", content=[
                ParagraphBlock(type="paragraph", id="fp1", inlines=[TextInline(text="각주 텍스트")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        fn_blocks = [b for b in result.blocks if isinstance(b, FootnoteBlock)]
        assert len(fn_blocks) >= 1, "파싱 결과에 FootnoteBlock이 있어야 함"
        assert fn_blocks[0].ref == "1"
        assert "각주 텍스트" in fn_blocks[0].text_content()
        assert loss is None

    def test_endnote_native_structure(self, seed: str, tmp_path) -> None:
        """네이티브 미주가 EndnoteBlock으로 파싱되는지 확인."""
        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="본문")]),
            EndnoteBlock(type="endnote", id="en1", ref="2", content=[
                ParagraphBlock(type="paragraph", id="ep1", inlines=[TextInline(text="미주 텍스트")]),
            ]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        en_blocks = [b for b in result.blocks if isinstance(b, EndnoteBlock)]
        assert len(en_blocks) >= 1, "파싱 결과에 EndnoteBlock이 있어야 함"
        assert en_blocks[0].ref == "2"
        assert "미주 텍스트" in en_blocks[0].text_content()
        assert loss is None

    def test_image_block_with_data(self, seed: str, tmp_path) -> None:
        """실제 이미지 데이터가 있으면 네이티브 이미지로 생성."""
        import base64
        # 최소 1x1 PNG
        png_1x1 = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        img_path = str(tmp_path / "test.png")
        with open(img_path, "wb") as f:
            f.write(png_1x1)

        blocks = [
            ParagraphBlock(type="paragraph", id="p0", inlines=[TextInline(text="before")]),
            ImageBlock(type="image", id="img1", src=img_path, width=100.0, height=80.0),
            ParagraphBlock(type="paragraph", id="p1", inlines=[TextInline(text="after")]),
        ]
        result, loss = self._gen(blocks, seed, tmp_path)
        full = " ".join(b.text_content() for b in result.blocks)
        assert "before" in full
        assert loss is None
